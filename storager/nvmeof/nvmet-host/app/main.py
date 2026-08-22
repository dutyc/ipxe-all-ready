"""nvmet 宿主管理服务（NVMe-oF 存储接入 C4，2026-08-22 裁定：宿主原生 nvmet + Agent HTTP 调用）。

运行形态：存储节点宿主 root 运行（systemd unit），绑定 localhost + Bearer token；
直接操作内核 configfs（/sys/kernel/config/nvmet）——subsystem/namespace/port/hosts(dhchap_key)。
Agent 是唯一调用方；盘文件管理仍归 Agent（本服务不挂载盘目录）。
契约：blueprint/nvmeof-credential-design.md 第 6 节。

configfs 语义要点：
- attr_allow_any_host=0（严格）：host 须同时登记 hosts/<HOSTNQN>/dhchap_key 与 allowed_hosts 挂载才可连接
- DH-HMAC-CHAP 密钥：hosts/<HOSTNQN>/dhchap_key 写 DHHC-1 明文（固件契约格式）
- 删除子系统前须先摘除 port 挂载（symlink），否则 EBUSY
"""

import hmac
import logging
import os
import shutil
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

log = logging.getLogger("nvmet-host")

CONFIGFS_NVMET = os.getenv("NVMET_CONFIGFS", "/sys/kernel/config/nvmet")
PORT_ID = os.getenv("NVMET_PORT_ID", "1")


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"missing required env var: {name}")
    return val


TOKEN = _require_env("NVMET_HOST_TOKEN")


# ============================ configfs 操作封装 ============================


class NvmetManager:
    """configfs nvmet 操作：全部路径基于 self.root（默认 /sys/kernel/config/nvmet），
    测试可注入临时目录模拟 configfs 布局。"""

    def __init__(self, root: str = CONFIGFS_NVMET, port_id: str = PORT_ID):
        self.root = root
        self.port_id = port_id

    def ready(self) -> bool:
        return os.path.isdir(os.path.join(self.root, "subsystems"))

    def exists(self, nqn: str) -> bool:
        return os.path.isdir(self._sub_path(nqn))

    def create_subsystem(self, nqn: str, backing: str) -> None:
        """创建子系统 + namespace/1（backing 盘文件）+ 严格模式（allow_any_host=0）。"""
        sub = self._sub_path(nqn)
        if os.path.isdir(sub):
            raise ValueError(f"subsystem exists: {nqn}")
        os.makedirs(sub, exist_ok=True)
        try:
            self._write(sub, "attr_allow_any_host", "0")
            ns = os.path.join(sub, "namespaces", "1")
            os.makedirs(ns, exist_ok=True)
            self._write(ns, "device_path", backing)
            self._write(ns, "enable", "1")
        except Exception:
            shutil.rmtree(sub, ignore_errors=True)
            raise

    def delete_subsystem(self, nqn: str) -> None:
        """删除子系统：先摘除 port 挂载，再逐个禁用/删除 namespace，最后移除 hosts 与本体。"""
        sub = self._sub_path(nqn)
        if not os.path.isdir(sub):
            raise ValueError(f"subsystem not found: {nqn}")
        link = os.path.join(self.root, "ports", self.port_id, "subsystems", nqn)
        if os.path.islink(link):
            os.unlink(link)
        ns_base = os.path.join(sub, "namespaces")
        if os.path.isdir(ns_base):
            for name in sorted(os.listdir(ns_base)):
                ns = os.path.join(ns_base, name)
                enable = os.path.join(ns, "enable")
                if os.path.exists(enable):
                    self._write(ns, "enable", "0")
                shutil.rmtree(ns, ignore_errors=True)
        for d in ("hosts", "allowed_hosts"):
            shutil.rmtree(os.path.join(sub, d), ignore_errors=True)
        shutil.rmtree(sub, ignore_errors=True)

    def list_subsystems(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        base = os.path.join(self.root, "subsystems")
        if not os.path.isdir(base):
            return result
        for nqn in sorted(os.listdir(base)):
            sub = os.path.join(base, nqn)
            if not os.path.isdir(sub):
                continue
            namespaces = []
            ns_base = os.path.join(sub, "namespaces")
            if os.path.isdir(ns_base):
                for nsid in sorted(os.listdir(ns_base)):
                    namespaces.append({
                        "nsid": int(nsid),
                        "device_path": self._read(os.path.join(ns_base, nsid, "device_path")),
                    })
            hosts = []
            hosts_base = os.path.join(sub, "hosts")
            if os.path.isdir(hosts_base):
                hosts = sorted(os.listdir(hosts_base))
            result.append({"nqn": nqn, "namespaces": namespaces, "hosts": hosts})
        return result

    def set_host(self, nqn: str, hostnqn: str, secret: str) -> None:
        """登记/更新 host 认证：hosts/<hostnqn>/dhchap_key = DHHC-1 密钥 + allowed_hosts 挂载。"""
        sub = self._sub_path(nqn)
        if not os.path.isdir(sub):
            raise ValueError(f"subsystem not found: {nqn}")
        host_dir = os.path.join(sub, "hosts", hostnqn)
        os.makedirs(host_dir, exist_ok=True)
        self._write(host_dir, "dhchap_key", secret, newline=False)
        allowed = os.path.join(sub, "allowed_hosts", hostnqn)
        if not os.path.islink(allowed):
            os.symlink(f"../../hosts/{hostnqn}", allowed)

    def delete_host(self, nqn: str, hostnqn: str) -> None:
        """移除 host 认证：摘 allowed_hosts 挂载 + 删 hosts 条目。"""
        sub = self._sub_path(nqn)
        allowed = os.path.join(sub, "allowed_hosts", hostnqn)
        if os.path.islink(allowed):
            os.unlink(allowed)
        host_dir = os.path.join(sub, "hosts", hostnqn)
        if os.path.isdir(host_dir):
            shutil.rmtree(host_dir)

    def ensure_port(self, trtype: str = "tcp", adrfam: str = "ipv4", traddr: str = "0.0.0.0",
                    trsvcid: str = "4420", tsas: str = "none") -> dict[str, str]:
        """幂等创建/更新 NVMe/TCP 端口（默认 4420，无 TLS）。"""
        port = os.path.join(self.root, "ports", self.port_id)
        os.makedirs(port, exist_ok=True)
        self._write(port, "addr_trtype", trtype)
        self._write(port, "addr_adrfam", adrfam)
        self._write(port, "addr_traddr", traddr)
        self._write(port, "addr_trsvcid", trsvcid)
        self._write(port, "addr_tsas", tsas)
        return {"port": self.port_id, "trtype": trtype, "traddr": traddr,
                "trsvcid": trsvcid, "tsas": tsas}

    def attach_port(self, nqn: str) -> None:
        """把子系统挂到端口（symlink），幂等；创建子系统后必须挂载才对外可见。"""
        link = os.path.join(self.root, "ports", self.port_id, "subsystems", nqn)
        os.makedirs(os.path.dirname(link), exist_ok=True)
        if not os.path.islink(link):
            os.symlink(f"../../subsystems/{nqn}", link)

    def _sub_path(self, nqn: str) -> str:
        return os.path.join(self.root, "subsystems", nqn)

    @staticmethod
    def _write(path: str, attr: str, value: str, newline: bool = True) -> None:
        with open(os.path.join(path, attr), "w", encoding="utf-8") as f:
            f.write(value + ("\n" if newline else ""))

    @staticmethod
    def _read(path: str) -> str | None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return None


manager = NvmetManager()


# ============================ 请求模型 + 鉴权 ============================


class SubsystemCreate(BaseModel):
    nqn: str
    backing: str


class HostSet(BaseModel):
    hostnqn: str
    secret: str


def verify_token(authorization: str = Header("", alias="Authorization")) -> None:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "unauthorized")
    if not hmac.compare_digest(authorization[len("Bearer "):].strip(), TOKEN):
        raise HTTPException(401, "unauthorized")


app = FastAPI(title="nvmet-host")


@app.get("/healthz")
def healthz():
    """唯一不鉴权端点（探活）：configfs 就绪则 ok。"""
    return {"status": "ok", "configfs": manager.ready()}


@app.get("/capabilities", dependencies=[Depends(verify_token)])
def capabilities():
    return {
        "backend": "nvmet",
        "cd": False,
        "persistent": "host-native configfs (nvmet-host service)",
        "configfs": manager.root,
        "port": {"trtype": "tcp", "trsvcid": "4420", "tsas": "none"},
    }


@app.post("/port", dependencies=[Depends(verify_token)])
def ensure_port(trsvcid: str = "4420"):
    return manager.ensure_port(trsvcid=trsvcid)


@app.get("/subsystems", dependencies=[Depends(verify_token)])
def list_subsystems():
    return {"subsystems": manager.list_subsystems()}


@app.post("/subsystems", status_code=201, dependencies=[Depends(verify_token)])
def create_subsystem(req: SubsystemCreate):
    try:
        manager.create_subsystem(req.nqn, req.backing)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        manager.attach_port(req.nqn)
    except Exception as exc:
        raise HTTPException(500, f"attach port failed: {exc}") from exc
    return {"nqn": req.nqn, "backing": req.backing, "port": PORT_ID}


@app.delete("/subsystems/{nqn}", dependencies=[Depends(verify_token)])
def delete_subsystem(nqn: str):
    try:
        manager.delete_subsystem(nqn)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"deleted": nqn}


@app.put("/subsystems/{nqn}/hosts", dependencies=[Depends(verify_token)])
def set_host(nqn: str, req: HostSet):
    """登记/更新 host 认证（DHHC-1 密钥）。Agent 按绑定关系同步调用。"""
    try:
        manager.set_host(nqn, req.hostnqn, req.secret)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"nqn": nqn, "hostnqn": req.hostnqn, "set": True}


@app.delete("/subsystems/{nqn}/hosts/{hostnqn}", dependencies=[Depends(verify_token)])
def delete_host(nqn: str, hostnqn: str):
    manager.delete_host(nqn, hostnqn)
    return {"nqn": nqn, "hostnqn": hostnqn, "deleted": True}


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("NVMET_HOST_ADDR", "127.0.0.1")
    port = int(os.getenv("NVMET_HOST_PORT", "4841"))
    uvicorn.run(app, host=host, port=port, log_level="info")
