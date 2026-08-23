import os
import re
import abc
import shutil
import threading
import time
import logging
import hmac
import json
import datetime
from contextlib import asynccontextmanager, contextmanager

import docker
from fastapi import FastAPI, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("agent")

FICLONE = 0x40049409


# ============================ 框架层：配置 ============================

def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"missing required env var: {name} (check .env)")
    return val


def nqn_to_iqn(nqn: str) -> str:
    """NVMe NQN → iSCSI IQN（同后缀前缀变换，派生方向：NQN 权威，IQN 自动生成）：
    nqn.2026-07.com.kurrent:worker-01.ubuntu → iqn.2026-07.com.kurrent:worker-01.ubuntu。
    节点只配置 NQN 命名空间（KURRENT_NQN_BASE），iSCSI 数据面消费的 IQN 由此派生。"""
    nqn = nqn.strip().lower()
    if nqn.startswith("iqn."):
        return nqn
    if nqn.startswith("nqn."):
        return "iqn." + nqn[4:]
    return "iqn." + nqn


DISK_DIR = _require_env("KURRENT_DISK_DIR")
NQN_BASE = _require_env("KURRENT_NQN_BASE")        # 权威：盘标识命名空间（NVMe-oF 首选协议）
IQN_BASE = nqn_to_iqn(NQN_BASE)                 # 派生：iSCSI 数据面（同后缀前缀变换）
BACKEND = _require_env("KURRENT_BACKEND")
TOKEN = _require_env("KURRENT_AGENT_TOKEN")          # 必填，无默认值
LOG_FILE = _require_env("KURRENT_LOG_FILE")


# ============================ 框架层：文件操作 ============================

def _file_exists(path: str) -> bool:
    return os.path.exists(path)


def _parse_size(s: str) -> int:
    s = s.strip().upper()
    units = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    if s and s[-1] in units:
        return int(float(s[:-1]) * units[s[-1]])
    return int(s)


def _reflink(src: str, dst: str) -> bool:
    try:
        src_fd = os.open(src, os.O_RDONLY)
    except OSError as e:
        log.warning(f"reflink open src failed: {e}")
        return False
    try:
        dst_fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    except OSError as e:
        os.close(src_fd)
        log.warning(f"reflink open dst failed: {e}")
        return False
    try:
        import fcntl
        fcntl.ioctl(dst_fd, FICLONE, src_fd)
        return True
    except OSError as e:
        log.info(f"reflink not used: errno={e.errno} ({e.strerror})")
        return False
    finally:
        os.close(src_fd)
        os.close(dst_fd)


def _fs_type(path: str) -> str:
    """返回 path 所在挂载点的文件系统类型（解析 /proc/self/mounts，最长挂载点匹配）。"""
    real = os.path.realpath(path)
    best, best_len = "unknown", -1
    try:
        with open("/proc/self/mounts", "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mnt = parts[1].replace("\\040", " ")
                fstype = parts[2]
                if len(mnt) > best_len and (real == mnt or real.startswith(mnt.rstrip("/") + "/") or mnt == "/"):
                    best, best_len = fstype, len(mnt)
    except OSError:
        pass
    return best


def _same_fs(src: str, dst: str) -> bool:
    """源与目标是否同一文件系统（ZFS 各数据集 st_dev 不同，文件级 reflink 要求同数据集）。"""
    try:
        return os.stat(src).st_dev == os.stat(dst).st_dev
    except OSError:
        return False


def _clone_master(master_path: str, backing: str) -> None:
    if _reflink(master_path, backing):
        log.info(f"clone by reflink (instant): {backing}")
    else:
        # 诊断回退原因：ZFS 需 OpenZFS >= 2.2 且母盘与克隆盘在同一数据集才支持文件级 reflink
        fs = _fs_type(backing)
        if fs == "zfs":
            if not _same_fs(master_path, backing):
                log.warning(f"clone by copy (ZFS reflink requires master and work disk in the same dataset): {backing}")
            else:
                log.warning(f"clone by copy (ZFS file-level reflink requires OpenZFS >= 2.2): {backing}")
        else:
            log.warning(f"clone by copy (reflink unsupported on {fs}): {backing}")
        shutil.copy(master_path, backing)


def _make_empty(backing: str, size: str) -> None:
    with open(backing, "wb") as f:
        f.truncate(_parse_size(size))


def _remove_file(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


# ============================ 框架层：母盘扫描 ============================

class MasterScanner:
    """后台线程周期扫描 DISK_DIR，缓存 *_tpl_* 母盘清单（name/size/mtime）。

    母盘命名约定：文件名须包含 `_tpl_` 标记（如 _tpl_ubuntu_2204.img）。
    扫描结果带锁缓存，GET /masters 直接读缓存，不阻塞文件系统。
    """

    def __init__(self, disk_dir: str, interval: float = 30.0):
        self.disk_dir = disk_dir
        self.interval = interval
        self.lock = threading.Lock()
        self.cache: list = []
        self._stop = threading.Event()

    def _scan(self) -> list:
        items = []
        try:
            names = os.listdir(self.disk_dir)
        except OSError as e:
            log.warning(f"master scan failed: {e}")
            return items
        for n in sorted(names):
            if "_tpl_" not in n:
                continue
            p = os.path.join(self.disk_dir, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if not os.path.isfile(p):
                continue
            items.append({"name": n, "size": st.st_size, "mtime": int(st.st_mtime)})
        return items

    def start(self) -> None:
        self.refresh()
        threading.Thread(target=self._loop, daemon=True).start()
        log.info(f"master scanner started: dir={self.disk_dir} interval={self.interval}s")

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self.refresh()

    def refresh(self) -> None:
        items = self._scan()
        with self.lock:
            self.cache = items

    def list(self) -> list:
        with self.lock:
            return list(self.cache)


masters = MasterScanner(DISK_DIR)


def _iqn_to_filename(iqn: str) -> str:
    ident = iqn.split(":", 1)[1] if ":" in iqn else iqn
    return f"{ident}.img"


def _check_iqn(iqn: str) -> None:
    prefix = f"{IQN_BASE}:"
    if not iqn.startswith(prefix):
        raise HTTPException(400, f"iqn base mismatch: expect prefix '{prefix}', got '{iqn}'")


# ============================ 框架层：操作日志 ============================

class OperationLog:
    """append-only JSON Lines 操作日志。id 用行号当游标（MVP 不轮转前提下成立）。"""

    def __init__(self, path: str):
        self.path = path
        self.lock = threading.Lock()
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.next_id = 0
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.next_id = sum(1 for line in f if line.strip())

    def record(self, op: str, req: dict, result: str, client: str, **extra) -> None:
        with self.lock:
            self.next_id += 1
            entry = {"id": self.next_id,
                     # 跟随容器时区（/etc/localtime 挂载或 TZ 环境变量），输出带偏移的本地时间
                     "ts": datetime.datetime.now().astimezone().isoformat(),
                     "op": op, "req": req, "result": result, "client": client}
            entry.update(extra)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read(self, since: int = 0, limit: int = 1000) -> dict:
        entries = []
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if e.get("id", 0) > since:
                        entries.append(e)
                        if len(entries) >= limit:
                            break
        next_cursor = entries[-1]["id"] if entries else since
        return {"next_cursor": next_cursor, "entries": entries}


oplog = OperationLog(LOG_FILE)


# ============================ 框架层：token 鉴权 ============================

def verify_token(request: Request) -> None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "unauthorized")
    # 常量时间比对，防时序攻击；不回显 token、日志不记 token
    if not hmac.compare_digest(auth[len("Bearer "):].strip(), TOKEN):
        raise HTTPException(401, "unauthorized")


@contextmanager
def logged(op: str, req_dict: dict, client: str):
    """写操作外壳：成功记 ok，任何失败记 failed + 原因，再抛出。"""
    try:
        yield
        oplog.record(op, req_dict, "ok", client)
    except HTTPException as e:
        oplog.record(op, req_dict, "failed", client, error=str(e.detail))
        raise
    except Exception as e:
        oplog.record(op, req_dict, "failed", client, error=str(e))
        raise


# ============================ 驱动层：后端基类 ============================

class Backend(abc.ABC):
    def __init__(self):
        self.client = docker.from_env()
        self.container = _require_env("KURRENT_ISCSI_CONTAINER")

    def _exec(self, cmd: str) -> str:
        try:
            c = self.client.containers.get(self.container)
        except docker.errors.NotFound:
            raise HTTPException(503, f"iscsi container not found: {self.container}")
        except docker.errors.DockerException as e:
            raise HTTPException(503, f"docker error: {e}")
        res = c.exec_run(["sh", "-c", cmd])
        out = res.output.decode(errors="replace") if res.output else ""
        if res.exit_code != 0:
            raise HTTPException(500, f"cmd failed rc={res.exit_code}: {out.strip()}")
        return out

    def _exec_safe(self, cmd: str) -> None:
        try:
            c = self.client.containers.get(self.container)
            c.exec_run(["sh", "-c", cmd])
        except Exception:
            pass

    @abc.abstractmethod
    def create_target(self, iqn: str, backing: str, cd: bool) -> None: ...
    @abc.abstractmethod
    def delete_target(self, iqn: str) -> None: ...
    @abc.abstractmethod
    def list_targets(self) -> list: ...
    @abc.abstractmethod
    def capabilities(self) -> dict: ...
    @abc.abstractmethod
    def wait_ready(self) -> None: ...
    @abc.abstractmethod
    def startup(self) -> Optional[dict]: ...
    @abc.abstractmethod
    def scan(self) -> dict: ...


# ============================ 驱动层：stgt ============================

class StgtBackend(Backend):

    def _next_tid(self, targets: list) -> int:
        used = {t["tid"] for t in targets}
        tid = 1
        while tid in used:
            tid += 1
        return tid

    def list_targets(self) -> list:
        out = self._exec("tgtadm --lld iscsi --op show --mode target")
        targets, cur = [], None
        for line in out.splitlines():
            m = re.match(r"^Target\s+(\d+):\s+(\S+)", line)
            if m:
                cur = {"tid": int(m.group(1)), "iqn": m.group(2), "luns": []}
                targets.append(cur)
                continue
            if cur is None:
                continue
            ml = re.match(r"^\s+LUN:\s+(\d+)", line)
            if ml:
                cur["luns"].append({"lun": int(ml.group(1)), "backing": None})
                continue
            mb = re.match(r"^\s+Backing store path:\s+(.+)", line)
            if mb and cur["luns"]:
                val = mb.group(1).strip()
                cur["luns"][-1]["backing"] = None if val == "None" else val
        return targets

    def create_target(self, iqn: str, backing: str, cd: bool) -> None:
        targets = self.list_targets()
        if any(t["iqn"] == iqn for t in targets):
            raise HTTPException(409, f"iqn exists: {iqn}")
        tid = self._next_tid(targets)
        self._exec(f"tgtadm --lld iscsi --op new --mode target --tid {tid} --targetname {iqn}")
        dt = " --device-type cd" if cd else ""
        try:
            self._exec(f"tgtadm --lld iscsi --op new --mode logicalunit --tid {tid} --lun 1 "
                       f"--backing-store {backing}{dt}")
            self._exec(f"tgtadm --lld iscsi --op bind --mode target --tid {tid} --initiator-address ALL")
        except HTTPException:
            self._exec_safe(f"tgtadm --lld iscsi --op delete --mode target --tid {tid}")
            raise

    def delete_target(self, iqn: str) -> None:
        targets = self.list_targets()
        t = next((x for x in targets if x["iqn"] == iqn), None)
        if not t:
            raise HTTPException(404, f"iqn not found: {iqn}")
        tid = t["tid"]
        for lun in t["luns"]:
            if lun["lun"] == 0:
                continue
            self._exec(f"tgtadm --lld iscsi --op delete --mode logicalunit --tid {tid} --lun {lun['lun']}")
        self._exec(f"tgtadm --lld iscsi --op unbind --mode target --tid {tid} --initiator-address ALL")
        self._exec(f"tgtadm --lld iscsi --op delete --mode target --tid {tid}")

    def capabilities(self) -> dict:
        return {"backend": "stgt", "cd": True, "persistent": "auto-scan on startup"}

    def wait_ready(self, retries: int = 30, interval: int = 2) -> None:
        for i in range(retries):
            try:
                self._exec("tgtadm --lld iscsi --op show --mode target")
                return
            except HTTPException:
                log.info(f"waiting stgt ready... ({i+1}/{retries})")
                time.sleep(interval)
        raise RuntimeError("stgt not ready after retries")

    def scan(self) -> dict:
        names = [n for n in os.listdir(DISK_DIR) if n.lower().endswith((".img", ".iso"))]
        created, skipped = [], []
        existing = {t["iqn"] for t in self.list_targets()}
        for name in names:
            if name.lower().endswith(".iso"):
                iqn, cd = f"{IQN_BASE}:{name}".lower(), True
            else:
                iqn, cd = f"{IQN_BASE}:{name.rsplit('.', 1)[0]}".lower(), False
            if iqn in existing:
                skipped.append(iqn)
                continue
            try:
                self.create_target(iqn, f"{DISK_DIR}/{name}", cd=cd)
            except HTTPException as e:
                log.error(f"scan create failed for {name}: {e.detail}")
                continue
            existing.add(iqn)
            created.append({"iqn": iqn, "cd": cd})
        return {"created": created, "skipped": skipped}

    def startup(self) -> Optional[dict]:
        result = self.scan()
        log.info(f"stgt auto-scan done: created={len(result['created'])} skipped={len(result['skipped'])}")
        return result


# ============================ 驱动层：lio ============================

class LioBackend(Backend):

    @staticmethod
    def _bs_name(iqn: str) -> str:
        return iqn.split(":", 1)[1] if ":" in iqn else iqn

    def list_targets(self) -> list:
        out = self._exec("targetcli ls /iscsi")
        targets, cur = [], None
        for line in out.splitlines():
            m = re.search(r"o- (iqn\.\S+?)\s+\.", line)
            if m:
                cur = {"iqn": m.group(1), "luns": []}
                targets.append(cur)
                continue
            ml = re.search(r"o- lun\d+\s+.*\[fileio/\S+\s+\((.+?)\)", line)
            if ml and cur is not None:
                cur["luns"].append({"backing": ml.group(1)})
        return targets

    def create_target(self, iqn: str, backing: str, cd: bool) -> None:
        if cd:
            raise HTTPException(400, "lio backend does not support cd (ISO optical drive); use stgt for cd")
        if any(t["iqn"] == iqn for t in self.list_targets()):
            raise HTTPException(409, f"iqn exists: {iqn}")
        bs = self._bs_name(iqn)
        self._exec(f"targetcli /backstores/fileio create name={bs} file_or_dev={backing} write_back=true")
        try:
            self._exec(f"targetcli /iscsi create {iqn}")
            self._exec(f"targetcli /iscsi/{iqn}/tpg1/luns create /backstores/fileio/{bs}")
            self._exec(f"targetcli /iscsi/{iqn}/tpg1 set attribute generate_node_acls=1")
            self._exec(f"targetcli /iscsi/{iqn}/tpg1 set attribute demo_mode_write_protect=0")
            self._exec("targetcli saveconfig")
        except HTTPException:
            self._exec_safe(f"targetcli /iscsi delete {iqn}")
            self._exec_safe(f"targetcli /backstores/fileio delete {bs}")
            self._exec_safe("targetcli saveconfig")
            raise

    def delete_target(self, iqn: str) -> None:
        if not any(t["iqn"] == iqn for t in self.list_targets()):
            raise HTTPException(404, f"iqn not found: {iqn}")
        bs = self._bs_name(iqn)
        self._exec(f"targetcli /iscsi delete {iqn}")
        self._exec_safe(f"targetcli /backstores/fileio delete {bs}")
        self._exec("targetcli saveconfig")

    def capabilities(self) -> dict:
        return {"backend": "lio", "cd": False, "persistent": "saveconfig (auto-load on start)"}

    def wait_ready(self, retries: int = 30, interval: int = 2) -> None:
        for i in range(retries):
            try:
                self._exec("targetcli ls /iscsi")
                return
            except HTTPException:
                log.info(f"waiting lio (targetclid) ready... ({i+1}/{retries})")
                time.sleep(interval)
        raise RuntimeError("lio not ready after retries")

    def scan(self) -> dict:
        names = [n for n in os.listdir(DISK_DIR) if n.lower().endswith((".img", ".iso"))]
        created, skipped = [], []
        existing = {t["iqn"] for t in self.list_targets()}
        for name in names:
            if name.lower().endswith(".iso"):
                log.info(f"lio skips iso (cd unsupported): {name}")
                skipped.append(f"{IQN_BASE}:{name}".lower())
                continue
            iqn = f"{IQN_BASE}:{name.rsplit('.', 1)[0]}".lower()
            if iqn in existing:
                skipped.append(iqn)
                continue
            try:
                self.create_target(iqn, f"{DISK_DIR}/{name}", cd=False)
            except HTTPException as e:
                log.error(f"scan create failed for {name}: {e.detail}")
                continue
            existing.add(iqn)
            created.append({"iqn": iqn, "cd": False})
        return {"created": created, "skipped": skipped}

    def startup(self) -> Optional[dict]:
        log.info("lio backend: targets auto-loaded from saveconfig, no startup scan needed")
        return None


# ============================ 框架层：实例化 + 启动钩子 ============================

def _make_backend() -> Backend:
    if BACKEND == "stgt":
        return StgtBackend()
    if BACKEND == "lio":
        return LioBackend()
    if BACKEND == "nvmet":
        # 宿主原生 nvmet（C4）：经 nvmet-host 服务调 configfs；env 按需读取，不影响其他后端
        from .nvmet import NvmetBackend, NvmetCredentialCache, NvmetHostClient
        host = NvmetHostClient(_require_env("KURRENT_NVMET_HOST_URL"),
                               _require_env("KURRENT_NVMET_HOST_TOKEN"))
        cache_path = os.environ.get("KURRENT_NVMET_CACHE_FILE") or \
            os.path.join(os.path.dirname(LOG_FILE), "nvmet-credentials.json")
        cache = NvmetCredentialCache(host, cache_path)
        return NvmetBackend(host, cache, DISK_DIR, NQN_BASE)
    raise RuntimeError(f"unknown KURRENT_BACKEND: {BACKEND} (expect stgt|lio|nvmet)")


backend = _make_backend()


def _startup() -> None:
    backend.wait_ready()
    result = backend.startup()
    if result is not None:                       # stgt/nvmet 返回 scan 结果，lio 返回 None
        oplog.record("auto_scan", {}, "ok", "local",
                     created=len(result.get("created", [])),
                     skipped=len(result.get("skipped", [])))


_reconcile_stop = threading.Event()


def _reconcile_loop() -> None:
    """nvmet 凭据缓存周期重放（仅 nvmet 后端）：覆盖宿主服务不可达窗口的推送丢失。"""
    from .nvmet import NvmetBackend
    if not isinstance(backend, NvmetBackend):
        return
    log.info(f"nvmet credential reconcile loop started: interval={backend.cache.interval}s")
    while not _reconcile_stop.wait(backend.cache.interval):
        try:
            result = backend.cache.reconcile()
            if result["failed"]:
                log.warning(f"nvmet credential reconcile: applied={result['applied']} "
                            f"failed={result['failed']}")
        except Exception as exc:
            log.warning(f"nvmet credential reconcile failed: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_startup, daemon=True).start()
    masters.start()
    threading.Thread(target=_reconcile_loop, daemon=True).start()
    log.info(f"agent started: backend={BACKEND}, base NQN={NQN_BASE}")
    yield


app = FastAPI(lifespan=lifespan)


# ============================ 框架层：请求模型 + 路由 ============================

class DiskReq(BaseModel):
    iqn: str
    master: Optional[str] = None
    size: Optional[str] = None
    filename: Optional[str] = None

class CdReq(BaseModel):
    iso: str
    iqn: Optional[str] = None

class CredentialPushReq(BaseModel):
    """NVMe-oF 凭据推送（控制面驱动，仅 nvmet 后端）：
    secret=null 吊销该 worker；sub_nqns = 该 worker 在本节点的盘子系统 NQN，host_nqns = 绑定设备派生 NQN。"""
    worker_id: str
    secret: Optional[str] = None
    sub_nqns: list = []
    host_nqns: list = []


@app.get("/healthz")                             # 唯一不保护的接口，给健康检查/探活
def healthz():
    return {"status": "ok"}


@app.post("/credential", dependencies=[Depends(verify_token)])
def push_credential(req: CredentialPushReq, request: Request):
    """NVMe-oF 凭据推送（控制面驱动，仅 nvmet 后端）：更新缓存 + 转调宿主服务同步 hosts 矩阵。
    secret=null 吊销该 worker 全部绑定设备认证；审计不记密钥本体。"""
    from .nvmet import NvmetBackend, NvmetHostError
    if not isinstance(backend, NvmetBackend):
        raise HTTPException(400, "credential push requires KURRENT_BACKEND=nvmet")
    req_dict = {"worker_id": req.worker_id, "secret": bool(req.secret),
                "sub_nqns": req.sub_nqns, "host_nqns": req.host_nqns}
    with logged("credential", req_dict, request.client.host):
        try:
            return backend.cache.apply(req.worker_id, req.secret, req.sub_nqns, req.host_nqns)
        except NvmetHostError as exc:
            raise HTTPException(503, f"nvmet host error: {exc.detail}") from exc


@app.post("/lun/disk", dependencies=[Depends(verify_token)])
def create_disk(req: DiskReq, request: Request):
    req_dict = {"iqn": req.iqn, "master": req.master, "size": req.size, "filename": req.filename}
    with logged("disk", req_dict, request.client.host):
        _check_iqn(req.iqn)
        iqn = req.iqn.lower()
        filename = req.filename or _iqn_to_filename(iqn)
        backing = f"{DISK_DIR}/{filename}"
        if _file_exists(backing):
            raise HTTPException(409, f"file exists: {backing}")
        if req.master:
            master_path = f"{DISK_DIR}/{req.master}"
            if not _file_exists(master_path):
                raise HTTPException(404, f"master not found: {master_path}")
            _clone_master(master_path, backing)
        elif req.size:
            _make_empty(backing, req.size)
        else:
            raise HTTPException(400, "need master (clone) or size (empty disk)")
        try:
            backend.create_target(iqn, backing, cd=False)
        except HTTPException:
            _remove_file(backing)
            raise
        return {"iqn": iqn, "backing": backing}


@app.post("/lun/cd", dependencies=[Depends(verify_token)])
def create_cd(req: CdReq, request: Request):
    req_dict = {"iso": req.iso, "iqn": req.iqn}
    with logged("cd", req_dict, request.client.host):
        iso_path = f"{DISK_DIR}/{req.iso}"
        if not _file_exists(iso_path):
            raise HTTPException(404, f"iso not found: {iso_path}")
        iqn = (req.iqn or f"{IQN_BASE}:{req.iso}").lower()
        _check_iqn(iqn)
        backend.create_target(iqn, iso_path, cd=True)
        return {"iqn": iqn, "backing": iso_path}


@app.post("/lun/scan", dependencies=[Depends(verify_token)])
def scan(request: Request):
    try:
        result = backend.scan()
        oplog.record("scan", {}, "ok", request.client.host,
                     created=len(result["created"]), skipped=len(result["skipped"]))
        return result
    except HTTPException as e:
        oplog.record("scan", {}, "failed", request.client.host, error=str(e.detail))
        raise


@app.delete("/lun", dependencies=[Depends(verify_token)])
def delete(iqn: str, request: Request, delete_file: bool = False):
    req_dict = {"iqn": iqn, "delete_file": delete_file}
    with logged("delete", req_dict, request.client.host):
        iqn = iqn.lower()
        backings = []
        t = next((x for x in backend.list_targets() if x["iqn"] == iqn), None)
        if t:
            backings = [l["backing"] for l in t["luns"] if l.get("backing")]
        backend.delete_target(iqn)
        if delete_file:
            for b in backings:
                _remove_file(b)
        return {"deleted": iqn, "delete_file": delete_file}


@app.get("/lun", dependencies=[Depends(verify_token)])
def list_luns():
    return backend.list_targets()


@app.get("/masters", dependencies=[Depends(verify_token)])
def list_masters():
    """列出 DISK_DIR 下 *_tpl_* 母盘（后台线程周期扫描的缓存清单，供 Control Plane / WebUI 克隆选盘）。"""
    return {"masters": masters.list()}


@app.get("/capabilities", dependencies=[Depends(verify_token)])
def capabilities():
    caps = backend.capabilities()
    # 盘标识命名空间权威 = NQN（控制面建盘生成盘 NQN 依赖此键；iSCSI 数据面 IQN 由 NQN 派生）
    caps["base_nqn"] = NQN_BASE
    # 文件系统类型决定克隆方式：btrfs / ZFS(>=2.2 同数据集) / xfs(reflink 特性) 走 FICLONE 秒级，其余回退全量拷贝
    fs = _fs_type(DISK_DIR)
    caps["fs_type"] = fs
    if fs == "zfs":
        caps["clone"] = "reflink (FICLONE on OpenZFS >= 2.2, master and work disk in the same dataset) -> shutil.copy fallback"
    elif fs in ("btrfs", "xfs"):
        caps["clone"] = "reflink (FICLONE; xfs requires the reflink feature enabled) -> shutil.copy fallback"
    else:
        caps["clone"] = f"full copy only (reflink unsupported on {fs})"
    caps["empty_disk"] = "truncate (sparse)"
    return caps


@app.get("/logs", dependencies=[Depends(verify_token)])
def get_logs(since: int = 0, limit: int = 1000):
    return oplog.read(since, limit)