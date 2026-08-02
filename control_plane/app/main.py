import copy
import hmac
import logging
import re
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from .agent_client import AgentAPIError
from .config import settings
from .dnsmasq import DnsmasqHosts, normalize_mac
from .models import (
    CreateCdLunRequest,
    CreateDiskLunRequest,
    CreateWorkerDiskRequest,
    CreateWorkerRequest,
    SetWorkerDefaultBootRequest,
)
from .scheduler import AgentRegistry
from .state import FileStateStore, OperationLog


log = logging.getLogger("control-plane")

WORKER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
HOSTNAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
OS_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
HEX_MAC_RE = re.compile(r"^[0-9a-f]{12}$")

# menu.ipxe 主菜单 item ID（choose --default 的合法值），作为 boot.menu_default 的严格校验集合
MENU_ITEMS = {
    "windows", "ubuntu", "debian", "centos", "esxi",
    "menu-diag", "menu-install", "config", "shell", "reboot", "exit",
}
# 可作为系统盘的 os（menu.ipxe 操作系统项子集），建盘与 default_os 同源严格校验
OS_ITEMS = {"windows", "ubuntu", "debian", "centos", "esxi"}

app = FastAPI(title="IPXE-All-Ready Control Plane")
store = FileStateStore(settings.workers_file)
operations = OperationLog(settings.operations_file)
agents = AgentRegistry(settings.agents_file, settings.agent_timeout)
dnsmasq = DnsmasqHosts(settings.dnsmasq_hosts_file, settings.dnsmasq_container, settings.dnsmasq_reload)


def verify_control_token(request: Request) -> None:
    if not settings.control_token:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "unauthorized")
    if not hmac.compare_digest(auth[len("Bearer "):].strip(), settings.control_token):
        raise HTTPException(401, "unauthorized")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/boot-vars")
def boot_vars(
    mac: str | None = None,
    hostname: str | None = None,
    output_format: str = Query("ipxe", alias="format"),
):
    if output_format not in {"ipxe", "json"}:
        raise HTTPException(400, "format must be ipxe or json")
    payload = _boot_vars_payload(mac=mac, hostname=hostname)
    if output_format == "json":
        return JSONResponse(_boot_vars_json(payload))
    return Response(_boot_vars_ipxe(payload), media_type="text/plain")


@app.get("/agents", dependencies=[Depends(verify_control_token)])
def list_agents(live: bool = True):
    return agents.list_public(live=live)


@app.get("/agents/{agent_id}/luns", dependencies=[Depends(verify_control_token)])
def list_agent_luns(agent_id: str, request: Request):
    """列出指定 Agent 上的全部 iSCSI target/LUN。"""
    client = _agent_client_or_404(agent_id)
    try:
        result = client.list_luns()
    except AgentAPIError as exc:
        _record("lun.list", "failed", agent=agent_id, client=_client_host(request), error=exc.detail)
        raise HTTPException(exc.status_code, {"agent": exc.agent_id, "error": exc.detail}) from exc
    _record("lun.list", "ok", agent=agent_id, client=_client_host(request), count=len(result))
    return result


@app.post("/agents/{agent_id}/luns/disk", status_code=201, dependencies=[Depends(verify_control_token)])
def create_agent_disk_lun(agent_id: str, req: CreateDiskLunRequest, request: Request):
    """在指定 Agent 上创建磁盘 LUN：传 master 走母盘克隆，传 size 建空白盘。"""
    if not req.master and not req.size:
        raise HTTPException(400, "need master (clone) or size (empty disk)")
    client = _agent_client_or_404(agent_id)
    try:
        result = client.create_disk(req.iqn, req.filename or "", master=req.master, size=req.size)
    except AgentAPIError as exc:
        _record("lun.create_disk", "failed", agent=agent_id, client=_client_host(request), iqn=req.iqn, error=exc.detail)
        raise HTTPException(exc.status_code, {"agent": exc.agent_id, "error": exc.detail}) from exc
    _record("lun.create_disk", "ok", agent=agent_id, client=_client_host(request),
            iqn=result.get("iqn", req.iqn), backing=result.get("backing"))
    return result


@app.post("/agents/{agent_id}/luns/cd", status_code=201, dependencies=[Depends(verify_control_token)])
def create_agent_cd_lun(agent_id: str, req: CreateCdLunRequest, request: Request):
    """在指定 Agent 上创建 CD（ISO 虚拟光驱）LUN，仅 stgt 后端支持。"""
    client = _agent_client_or_404(agent_id)
    try:
        result = client.create_cd(req.iso, req.iqn or "")
    except AgentAPIError as exc:
        _record("lun.create_cd", "failed", agent=agent_id, client=_client_host(request), iso=req.iso, error=exc.detail)
        raise HTTPException(exc.status_code, {"agent": exc.agent_id, "error": exc.detail}) from exc
    _record("lun.create_cd", "ok", agent=agent_id, client=_client_host(request),
            iqn=result.get("iqn", req.iqn), iso=req.iso)
    return result


@app.delete("/agents/{agent_id}/luns", dependencies=[Depends(verify_control_token)])
def delete_agent_lun(
    agent_id: str,
    request: Request,
    iqn: str = Query(..., description="IQN of the target to delete"),
    delete_file: bool = Query(False, description="Delete the backing .img/.iso file as well."),
    ignore_missing: bool = Query(False, description="Ignore 404 from Agent while deleting the target."),
):
    """删除指定 Agent 上的一个 LUN/target。"""
    client = _agent_client_or_404(agent_id)
    try:
        result = client.delete_lun(iqn, delete_file=delete_file)
    except AgentAPIError as exc:
        if ignore_missing and exc.status_code == 404:
            _record("lun.delete", "ok", agent=agent_id, client=_client_host(request), iqn=iqn,
                    delete_file=delete_file, ignored_missing=True)
            return {"deleted": iqn, "delete_file": delete_file, "ignored_missing": True}
        _record("lun.delete", "failed", agent=agent_id, client=_client_host(request), iqn=iqn,
                delete_file=delete_file, error=exc.detail)
        raise HTTPException(exc.status_code, {"agent": exc.agent_id, "error": exc.detail}) from exc
    _record("lun.delete", "ok", agent=agent_id, client=_client_host(request), iqn=iqn, delete_file=delete_file)
    return result


@app.post("/agents/{agent_id}/luns/scan", dependencies=[Depends(verify_control_token)])
def scan_agent_luns(agent_id: str, request: Request):
    """触发 Agent 扫描镜像目录，为缺失文件重建 target（文件即真相）。"""
    client = _agent_client_or_404(agent_id)
    try:
        result = client.scan()
    except AgentAPIError as exc:
        _record("lun.scan", "failed", agent=agent_id, client=_client_host(request), error=exc.detail)
        raise HTTPException(exc.status_code, {"agent": exc.agent_id, "error": exc.detail}) from exc
    _record("lun.scan", "ok", agent=agent_id, client=_client_host(request),
            created=len(result.get("created", [])), skipped=len(result.get("skipped", [])))
    return result


def _agent_client_or_404(agent_id: str):
    try:
        agent = agents.get(agent_id)
    except KeyError:
        raise HTTPException(404, f"agent not found: {agent_id}") from None
    return agents.client(agent)


@app.get("/workers", dependencies=[Depends(verify_control_token)])
def list_workers():
    data = store.load_workers()
    return [
        _enrich_worker(worker_id, record)
        for worker_id, record in sorted(data["workers"].items())
    ]


@app.get("/workers/{worker_id}", dependencies=[Depends(verify_control_token)])
def get_worker(worker_id: str):
    worker_id = _canonical_id(worker_id)
    data = store.load_workers()
    record = data["workers"].get(worker_id)
    if not record:
        raise HTTPException(404, f"worker not found: {worker_id}")
    return _enrich_worker(worker_id, record)


@app.get("/workers/{worker_id}/status", dependencies=[Depends(verify_control_token)])
def get_worker_status(worker_id: str):
    worker_id = _canonical_id(worker_id)
    data = store.load_workers()
    record = data["workers"].get(worker_id)
    if not record:
        raise HTTPException(404, f"worker not found: {worker_id}")
    return {
        "worker": _enrich_worker(worker_id, record),
        "actual": _actual_state(record),
    }


@app.post("/workers", status_code=201, dependencies=[Depends(verify_control_token)])
def create_worker(req: CreateWorkerRequest, request: Request):
    """注册 Worker 身份：写入台账 + hostname/MAC 绑定。
    存储与身份分离：系统盘须另调 POST /workers/{worker_id}/luns/disk。"""
    worker_id = _canonical_id(req.worker_id)
    hostname = _canonical_hostname(req.hostname or worker_id)
    arch = req.arch or settings.default_arch
    mac = _canonical_mac(req.mac)

    cd_record: dict[str, Any] | None = None

    with store.locked():
        data = store.load_workers()
        workers = data["workers"]
        if worker_id in workers:
            raise HTTPException(409, f"worker already exists: {worker_id}")
        _ensure_hostname_not_in_workers(workers, hostname)
        try:
            dnsmasq.ensure_free(mac, hostname)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

        client_host = _client_host(request)
        _record("create_worker", "started", worker_id=worker_id, client=client_host)

        try:
            if req.windows_iso:
                cd_agent, cd_caps = agents.select_cd_agent()
                cd_iqn = _build_iqn(cd_caps["base_iqn"], worker_id, "windows.iso")
                cd_client = agents.client(cd_agent)
                cd_result = cd_client.create_cd(req.windows_iso, cd_iqn)
                cd_record = {
                    "agent": cd_agent.id,
                    "iqn": cd_result.get("iqn", cd_iqn),
                    "iso": req.windows_iso,
                    "backing": cd_result.get("backing"),
                }
                _record("agent.create_cd", "ok", worker_id=worker_id, agent=cd_agent.id, iqn=cd_record["iqn"])

            worker_record = {
                "hostname": hostname,
                "arch": arch,
                "state": "installing" if cd_record else "registered",
                "disks": [],
                "cd": cd_record,
            }
            if req.boot:
                worker_record["boot"] = req.boot.dict(exclude_none=True)
            workers[worker_id] = worker_record
            store.save_workers(data)
            _record("workers.write", "ok", worker_id=worker_id)

            dnsmasq.add_binding(mac, hostname)
            _record("dnsmasq.hosts.write", "ok", worker_id=worker_id, hostname=hostname, mac=mac)
            dnsmasq_result = dnsmasq.reload()
            _record("dnsmasq.reload", "ok", worker_id=worker_id, result=dnsmasq_result)

            _record("create_worker", "succeeded", worker_id=worker_id, client=client_host)
            return _enrich_worker(worker_id, worker_record)
        except AgentAPIError as exc:
            _record("create_worker", "failed", worker_id=worker_id, client=client_host, error=exc.detail)
            _persist_failed_worker(data, worker_id, hostname, arch, None, cd_record, exc.detail)
            raise HTTPException(exc.status_code, {"agent": exc.agent_id, "error": exc.detail}) from exc
        except Exception as exc:
            _record("create_worker", "failed", worker_id=worker_id, client=client_host, error=str(exc))
            _persist_failed_worker(data, worker_id, hostname, arch, None, cd_record, str(exc))
            raise HTTPException(500, str(exc)) from exc


@app.post("/workers/{worker_id}/luns/disk", status_code=201, dependencies=[Depends(verify_control_token)])
def create_worker_disk(worker_id: str, req: CreateWorkerDiskRequest, request: Request):
    """给指定 Worker 创建系统盘 LUN：传 master 走母盘克隆，传 size 建空白盘。
    系统盘按系统分类，一个 Worker 可挂多个系统的盘；同一系统（os）至多一个。"""
    worker_id = _canonical_id(worker_id)
    os_name = _canonical_os(req.os)
    if os_name not in OS_ITEMS:
        raise HTTPException(400, f"os must be one of {sorted(OS_ITEMS)}: {os_name}")
    _validate_disk(req.type, req.name, req.size)

    with store.locked():
        data = store.load_workers()
        record = data["workers"].get(worker_id)
        if not record:
            raise HTTPException(404, f"worker not found: {worker_id}")
        if _find_disk_by_os(record, os_name):
            raise HTTPException(409, f"worker already has a {os_name} system disk: {worker_id}")

        client_host = _client_host(request)
        _record("worker.disk.create", "started", worker_id=worker_id, client=client_host)

        try:
            if req.disk_agent:
                disk_agent = agents.get(req.disk_agent)
                if not disk_agent.role_disk:
                    raise HTTPException(400, f"agent {req.disk_agent} not configured for disk role")
                client = agents.client(disk_agent)
                try:
                    client.healthz()
                    disk_caps = client.capabilities()
                except Exception as exc:
                    raise HTTPException(503, f"agent {req.disk_agent} not reachable: {exc}") from exc
            else:
                disk_agent, disk_caps = agents.select_disk_agent()

            disk_iqn = _build_iqn(disk_caps["base_iqn"], worker_id, os_name)
            disk_filename = _build_disk_filename(worker_id, os_name)
            disk_client = agents.client(disk_agent)
            if req.type == "master":
                disk_result = disk_client.create_disk(disk_iqn, disk_filename, master=req.name)
            else:
                disk_result = disk_client.create_disk(disk_iqn, disk_filename, size=req.size)
            disk_record = {
                "agent": disk_agent.id,
                "iqn": disk_result.get("iqn", disk_iqn),
                "filename": disk_filename,
                "backing": disk_result.get("backing"),
                "os": os_name,
                "source": _disk_source(req.type, req.name, req.size),
            }
            _record("agent.create_disk", "ok", worker_id=worker_id, agent=disk_agent.id, iqn=disk_record["iqn"])

            _add_worker_disk(record, disk_record)
            if record.get("state") == "registered":
                record["state"] = "ready"
            store.save_workers(data)
            _record("workers.disk.write", "ok", worker_id=worker_id, iqn=disk_record["iqn"])

            _record("worker.disk.create", "succeeded", worker_id=worker_id, client=client_host)
            return _enrich_worker(worker_id, record)
        except AgentAPIError as exc:
            _record("worker.disk.create", "failed", worker_id=worker_id, client=client_host, error=exc.detail)
            raise HTTPException(exc.status_code, {"agent": exc.agent_id, "error": exc.detail}) from exc
        except Exception as exc:
            _record("worker.disk.create", "failed", worker_id=worker_id, client=client_host, error=str(exc))
            raise HTTPException(500, str(exc)) from exc


@app.put("/workers/{worker_id}/default-os", dependencies=[Depends(verify_control_token)])
def set_worker_default_boot(worker_id: str, req: SetWorkerDefaultBootRequest, request: Request):
    """设置 Worker 默认启动配置：os=默认系统（须与已挂系统盘一致）；
    menu_default/menu_timeout=菜单项覆盖；传 null 清除对应项。
    推导链：default_os > boot.menu_default > exit。"""
    worker_id = _canonical_id(worker_id)
    fields = req.model_fields_set
    if not (fields & {"os", "menu_default", "menu_timeout"}):
        raise HTTPException(400, "need at least one of os / menu_default / menu_timeout")

    with store.locked():
        data = store.load_workers()
        record = data["workers"].get(worker_id)
        if not record:
            raise HTTPException(404, f"worker not found: {worker_id}")

        # 先全部校验，再统一应用，保证原子性
        new_default_os: str | None = None
        clear_default_os = False
        if "os" in fields:
            if req.os is None or req.os == "":
                clear_default_os = True
            else:
                os_name = _canonical_os(req.os)
                disk = _find_disk_by_os(record, os_name)
                if not disk:
                    existing = ", ".join(d.get("os", "?") for d in _worker_disks(record)) or "none"
                    raise HTTPException(
                        400,
                        f"worker has no {os_name} system disk (worker disks: {existing})",
                    )
                new_default_os = os_name

        new_menu_default: str | None = None
        clear_menu_default = False
        if "menu_default" in fields:
            if req.menu_default is None or req.menu_default == "":
                clear_menu_default = True
            else:
                menu_default = req.menu_default.strip().lower()
                if menu_default not in MENU_ITEMS:
                    raise HTTPException(
                        400, f"menu_default must be one of {sorted(MENU_ITEMS)}: {req.menu_default}"
                    )
                new_menu_default = menu_default

        new_menu_timeout: int | None = None
        clear_menu_timeout = False
        if "menu_timeout" in fields:
            if req.menu_timeout is None:
                clear_menu_timeout = True
            elif req.menu_timeout < 0:
                raise HTTPException(400, f"menu_timeout must be >= 0: {req.menu_timeout}")
            else:
                new_menu_timeout = req.menu_timeout

        changes: list[str] = []
        if clear_default_os:
            record.pop("default_os", None)
            changes.append("default_os:cleared")
        elif new_default_os:
            record["default_os"] = new_default_os
            changes.append(f"default_os:{new_default_os}")

        boot = record.setdefault("boot", {})
        if clear_menu_default:
            boot.pop("menu_default", None)
            changes.append("menu_default:cleared")
        elif new_menu_default:
            boot["menu_default"] = new_menu_default
            changes.append(f"menu_default:{new_menu_default}")
        if clear_menu_timeout:
            boot.pop("menu_timeout", None)
            changes.append("menu_timeout:cleared")
        elif new_menu_timeout is not None:
            boot["menu_timeout"] = new_menu_timeout
            changes.append(f"menu_timeout:{new_menu_timeout}")
        if not boot:
            record.pop("boot", None)

        store.save_workers(data)
        _record(
            "worker.boot.set",
            "ok",
            worker_id=worker_id,
            client=_client_host(request),
            changes=",".join(changes),
        )
        return _enrich_worker(worker_id, record)


@app.delete("/workers/{worker_id}", dependencies=[Depends(verify_control_token)])
def delete_worker(
    worker_id: str,
    request: Request,
    delete_disk: bool = Query(False, description="Delete the disk backing .img as well."),
    ignore_missing_target: bool = Query(False, description="Ignore 404 from Agent while deleting LUNs."),
):
    worker_id = _canonical_id(worker_id)
    with store.locked():
        data = store.load_workers()
        record = data["workers"].get(worker_id)
        if not record:
            raise HTTPException(404, f"worker not found: {worker_id}")

        client_host = _client_host(request)
        _record("delete_worker", "started", worker_id=worker_id, client=client_host, delete_disk=delete_disk)

        try:
            if record.get("cd"):
                _delete_target(record["cd"], delete_file=False, ignore_missing=ignore_missing_target)
                _record("agent.delete_cd", "ok", worker_id=worker_id, agent=record["cd"]["agent"], iqn=record["cd"]["iqn"])
            for disk in _worker_disks(record):
                _delete_target(disk, delete_file=delete_disk, ignore_missing=ignore_missing_target)
                _record("agent.delete_disk", "ok", worker_id=worker_id, agent=disk["agent"], iqn=disk["iqn"], delete_file=delete_disk)

            hostname = record["hostname"]
            del data["workers"][worker_id]
            store.save_workers(data)
            _record("workers.delete", "ok", worker_id=worker_id)

            removed = dnsmasq.remove_hostname(hostname)
            _record("dnsmasq.hosts.delete", "ok", worker_id=worker_id, hostname=hostname, removed=removed)
            dnsmasq_result = dnsmasq.reload()
            _record("dnsmasq.reload", "ok", worker_id=worker_id, result=dnsmasq_result)

            _record("delete_worker", "succeeded", worker_id=worker_id, client=client_host)
            return {"deleted": worker_id, "delete_disk": delete_disk, "dnsmasq_removed": removed}
        except AgentAPIError as exc:
            _record("delete_worker", "failed", worker_id=worker_id, client=client_host, error=exc.detail)
            raise HTTPException(exc.status_code, {"agent": exc.agent_id, "error": exc.detail}) from exc
        except Exception as exc:
            _record("delete_worker", "failed", worker_id=worker_id, client=client_host, error=str(exc))
            raise HTTPException(500, str(exc)) from exc


@app.get("/operations", dependencies=[Depends(verify_control_token)])
def get_operations(since: int = 0, limit: int = 1000):
    return operations.read(since=since, limit=limit)


def _delete_target(target_record: dict[str, Any], *, delete_file: bool, ignore_missing: bool) -> None:
    agent = agents.get(target_record["agent"])
    try:
        agents.client(agent).delete_lun(target_record["iqn"], delete_file=delete_file)
    except AgentAPIError as exc:
        if ignore_missing and exc.status_code == 404:
            return
        raise


def _actual_state(record: dict[str, Any]) -> dict[str, Any]:
    actual: dict[str, Any] = {
        "dnsmasq": {
            "hostname": record["hostname"],
            "mac": dnsmasq.find_mac(record["hostname"]),
        }
    }
    actual["disks"] = [_target_actual(d, os=d.get("os")) for d in _worker_disks(record)]
    actual["cd"] = _target_actual(record.get("cd"))
    return actual


def _target_actual(target_record: dict[str, Any] | None, os: str | None = None) -> dict[str, Any] | None:
    if not target_record:
        return None
    try:
        agent = agents.get(target_record["agent"])
        targets = agents.client(agent).list_luns()
        found = next((target for target in targets if target.get("iqn") == target_record["iqn"]), None)
        return {"os": os, "exists": found is not None, "target": found}
    except Exception as exc:
        return {"os": os, "exists": False, "error": str(exc)}


def _boot_vars_payload(mac: str | None, hostname: str | None) -> dict[str, Any]:
    match = _find_worker_for_boot(mac=mac, hostname=hostname)
    if not match and mac:
        # 新 MAC：自动注册身份（hostname 顺序分配 + dhcp 绑定），随后返回 reboot 等待配置
        match = _auto_register_worker(mac)
    if not match:
        return {}
    worker_id, record = match
    disk = _default_disk_for(record)
    agent_id = disk.get("agent") if disk else None
    boot = record.get("boot") or {}
    menu_default = _menu_default_for(record)
    if menu_default == "reboot":
        # 未配置默认启动：短超时快速重启，等待管理员建盘/设默认系统
        menu_timeout = settings.auto_boot_timeout
    else:
        menu_timeout = boot.get("menu_timeout") or boot.get("menu-timeout") or settings.boot_menu_timeout
    payload: dict[str, Any] = {
        "worker_id": worker_id,
        "hostname": record["hostname"],
        "menu_default": str(menu_default),
        "menu_timeout": int(menu_timeout),
    }
    if agent_id:
        base_iqn = _base_iqn_from_target(disk.get("iqn"))
        try:
            iscsi_server = agents.iscsi_server_for(agent_id)
        except Exception:
            return {}
        payload["base_iqn"] = base_iqn
        payload["iscsi_server"] = iscsi_server
    return payload


AUTO_HOSTNAME_RE = re.compile(r"^worker-(\d+)$")


def _next_auto_hostname(workers: dict[str, Any]) -> str:
    """扫描现有 hostname（台账 + dhcp 绑定），取最大序号 +1，格式 worker-%02d。"""
    used: set[str] = set()
    for record in workers.values():
        hostname = str(record.get("hostname", ""))
        if hostname:
            used.add(hostname)
    used.update(binding.hostname for binding in dnsmasq.list_bindings())
    max_num = -1
    for name in used:
        m = AUTO_HOSTNAME_RE.match(name)
        if m:
            max_num = max(max_num, int(m.group(1)))
    return f"worker-{max_num + 1:02d}"


def _auto_register_worker(mac: str) -> tuple[str, dict[str, Any]] | None:
    """新 MAC 自动注册身份：顺序分配 hostname，写台账 + dhcp 绑定 + HUP。
    失败返回 None（不阻断 iPXE，下次请求重试）。"""
    if not settings.auto_register:
        return None
    try:
        mac = _canonical_mac(mac)
    except HTTPException:
        return None
    with store.locked():
        data = store.load_workers()
        workers = data["workers"]
        if any(binding.mac == mac for binding in dnsmasq.list_bindings()):
            return None
        hostname = _next_auto_hostname(workers)
        if hostname in workers:
            return None
        worker_record = {
            "hostname": hostname,
            "arch": settings.default_arch,
            "state": "registered",
            "disks": [],
            "cd": None,
        }
        workers[hostname] = worker_record
        try:
            store.save_workers(data)
            dnsmasq.add_binding(mac, hostname)
            try:
                dnsmasq.reload()
            except Exception:
                log.exception("auto-register: dnsmasq reload failed")
            _record("auto_register", "ok", worker_id=hostname, hostname=hostname, mac=mac)
            return hostname, worker_record
        except Exception as exc:
            # 回滚台账，避免留下无 MAC 绑定的孤儿 worker
            workers.pop(hostname, None)
            try:
                store.save_workers(data)
            except Exception:
                pass
            log.exception("auto-register failed")
            _record("auto_register", "failed", mac=mac, error=str(exc))
            return None


def _boot_vars_ipxe(payload: dict[str, Any]) -> str:
    lines = ["#!ipxe"]
    if not payload:
        lines.append("# no per-worker boot vars found")
        return "\n".join(lines) + "\n"
    lines.append(f"# boot vars for {payload['worker_id']}")
    if payload.get("base_iqn"):
        lines.append(f"set base-iqn {payload['base_iqn']}")
    if payload.get("iscsi_server"):
        lines.append(f"set iscsi-server {payload['iscsi_server']}")
    lines.extend(
        [
            f"set menu-default {payload['menu_default']}",
            f"set menu-timeout {payload['menu_timeout']}",
        ]
    )
    return "\n".join(lines) + "\n"



def _boot_vars_json(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    result: dict[str, Any] = {
        "menu_default": payload["menu_default"],
        "menu_timeout": payload["menu_timeout"],
    }
    if payload.get("base_iqn"):
        result["base_iqn"] = payload["base_iqn"]
    if payload.get("iscsi_server"):
        result["iscsi_server"] = payload["iscsi_server"]
    return result


def _base_iqn_from_target(iqn: str | None) -> str:
    if iqn and ":" in iqn:
        return iqn.rsplit(":", 1)[0]
    return "iqn.2026-07.com.controller"


def _find_worker_for_boot(mac: str | None, hostname: str | None) -> tuple[str, dict[str, Any]] | None:
    """身份识别：有 hostname 用 hostname，无 hostname 退回 MAC 反查。"""
    data = store.load_workers()
    workers = data["workers"]
    if hostname:
        try:
            found = _find_worker_by_hostname(workers, _canonical_hostname(hostname))
            if found:
                return found
        except HTTPException:
            pass
    normalized_mac = _normalize_boot_mac(mac) if mac else None
    if normalized_mac:
        for binding in dnsmasq.list_bindings():
            if binding.mac == normalized_mac:
                found = _find_worker_by_hostname(workers, binding.hostname)
                if found:
                    return found
    return None


def _find_worker_by_hostname(workers: dict[str, Any], hostname: str) -> tuple[str, dict[str, Any]] | None:
    if hostname in workers:
        return hostname, workers[hostname]
    for worker_id, record in workers.items():
        if record.get("hostname") == hostname:
            return worker_id, record
    return None


def _menu_default_for(record: dict[str, Any]) -> str:
    """默认启动项：default_os（建盘后单独设置）> boot.menu_default（显式配置）> reboot（未配置时循环重启等待）。"""
    default_os = str(record.get("default_os", "")).lower()
    if default_os:
        return default_os
    boot = record.get("boot") or {}
    menu_default = boot.get("menu_default") or boot.get("menu-default")
    if menu_default:
        return str(menu_default).lower()
    return "reboot"


def _enrich_worker(worker_id: str, record: dict[str, Any]) -> dict[str, Any]:
    item = copy.deepcopy(record)
    item["worker_id"] = worker_id
    item["mac"] = dnsmasq.find_mac(item["hostname"])
    return item


def _persist_failed_worker(
    data: dict[str, Any],
    worker_id: str,
    hostname: str,
    arch: str,
    disk_record: dict[str, Any] | None,
    cd_record: dict[str, Any] | None,
    error: str,
) -> None:
    if not disk_record and not cd_record:
        return
    data["workers"][worker_id] = {
        "hostname": hostname,
        "arch": arch,
        "state": "failed",
        "error": error,
        "disks": [disk_record] if disk_record else [],
        "cd": cd_record,
    }
    try:
        store.save_workers(data)
    except Exception:
        log.exception("failed to persist failed worker state")


def _validate_disk(kind: str, name: str | None, size: str | None) -> None:
    if kind == "master" and not name:
        raise HTTPException(400, "disk.name is required when disk.type=master")
    if kind == "empty" and not size:
        raise HTTPException(400, "disk.size is required when disk.type=empty")


def _disk_source(kind: str, name: str | None, size: str | None) -> dict[str, str]:
    if kind == "master":
        return {"type": kind, "name": name or ""}
    return {"type": kind, "size": size or ""}


def _worker_disks(record: dict[str, Any]) -> list[dict[str, Any]]:
    """读取 Worker 全部系统盘；兼容旧台账单盘字段 `disk`（自动回退）。"""
    disks = record.get("disks")
    if disks is not None:
        return disks
    legacy = record.get("disk")
    return [legacy] if legacy else []


def _add_worker_disk(record: dict[str, Any], disk_record: dict[str, Any]) -> None:
    """写入新系统盘；旧台账若仍是单盘字段 `disk`，先并入 `disks` 完成迁移。"""
    disks = record.get("disks")
    if disks is None:
        legacy = record.get("disk")
        disks = [legacy] if legacy else []
        record["disks"] = disks
        record.pop("disk", None)
    disks.append(disk_record)


def _find_disk_by_os(record: dict[str, Any], os_name: str) -> dict[str, Any] | None:
    """按系统名查找系统盘（os 不区分大小写）。"""
    os_name = os_name.lower()
    for disk in _worker_disks(record):
        if str(disk.get("os", "")).lower() == os_name:
            return disk
    return None


def _default_disk_for(record: dict[str, Any]) -> dict[str, Any] | None:
    """默认启动盘：default_os 对应系统盘；未设 default_os 时取第一块盘。"""
    disks = _worker_disks(record)
    if not disks:
        return None
    default_os = str(record.get("default_os", "")).lower()
    if default_os:
        for disk in disks:
            if str(disk.get("os", "")).lower() == default_os:
                return disk
    return disks[0]


def _ensure_hostname_not_in_workers(workers: dict[str, Any], hostname: str) -> None:
    for worker_id, record in workers.items():
        if record.get("hostname") == hostname:
            raise HTTPException(409, f"hostname already used by worker: {worker_id}")


def _build_iqn(base_iqn: str, worker_id: str, suffix: str) -> str:
    return f"{base_iqn.rstrip(':')}:{worker_id}.{suffix}".lower()


def _build_disk_filename(worker_id: str, os_name: str) -> str:
    return f"{worker_id}.{os_name}.img".lower()


def _canonical_id(value: str) -> str:
    worker_id = value.strip().lower()
    if not WORKER_ID_RE.match(worker_id):
        raise HTTPException(400, f"invalid worker_id: {value}")
    return worker_id


def _canonical_hostname(value: str) -> str:
    hostname = value.strip().lower()
    if not HOSTNAME_RE.match(hostname):
        raise HTTPException(400, f"invalid hostname: {value}")
    return hostname


def _canonical_os(value: str) -> str:
    os_name = value.strip().lower()
    if not OS_RE.match(os_name):
        raise HTTPException(400, f"invalid os: {value}")
    return os_name


def _canonical_mac(value: str) -> str:
    try:
        return normalize_mac(value)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _normalize_boot_mac(value: str) -> str | None:
    compact = value.strip().lower().replace(":", "").replace("-", "").replace(".", "")
    if not HEX_MAC_RE.match(compact):
        return None
    return ":".join(compact[i:i + 2] for i in range(0, 12, 2))


def _client_host(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _record(op: str, status: str, **extra: Any) -> None:
    try:
        operations.record(op, status, **extra)
    except Exception:
        log.exception("failed to write operation log")
