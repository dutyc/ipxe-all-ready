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
from .models import CreateWorkerRequest
from .scheduler import AgentRegistry
from .state import FileStateStore, OperationLog


log = logging.getLogger("control-plane")

WORKER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
HOSTNAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
OS_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
HEX_MAC_RE = re.compile(r"^[0-9a-f]{12}$")

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
    worker_id = _canonical_id(req.worker_id)
    hostname = _canonical_hostname(req.hostname or worker_id)
    os_name = _canonical_os(req.os)
    arch = req.arch or settings.default_arch
    mac = _canonical_mac(req.mac)
    _validate_disk(req.disk.type, req.disk.name, req.disk.size)
    if req.windows_iso and os_name != "windows":
        raise HTTPException(400, "windows_iso is only allowed when os=windows")

    disk_record: dict[str, Any] | None = None
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
            if req.disk.type == "master":
                disk_result = disk_client.create_disk(disk_iqn, disk_filename, master=req.disk.name)
            else:
                disk_result = disk_client.create_disk(disk_iqn, disk_filename, size=req.disk.size)
            disk_record = {
                "agent": disk_agent.id,
                "iqn": disk_result.get("iqn", disk_iqn),
                "filename": disk_filename,
                "backing": disk_result.get("backing"),
                "source": _disk_source(req.disk.type, req.disk.name, req.disk.size),
            }
            _record("agent.create_disk", "ok", worker_id=worker_id, agent=disk_agent.id, iqn=disk_record["iqn"])

            if os_name == "windows" and req.windows_iso:
                cd_agent, cd_caps = agents.select_cd_agent()
                cd_iqn = _build_iqn(cd_caps["base_iqn"], worker_id, f"{os_name}.iso")
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
                "os": os_name,
                "arch": arch,
                "state": "installing" if cd_record else "ready",
                "disk": disk_record,
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
            _persist_failed_worker(data, worker_id, hostname, os_name, arch, disk_record, cd_record, exc.detail)
            raise HTTPException(exc.status_code, {"agent": exc.agent_id, "error": exc.detail}) from exc
        except Exception as exc:
            _record("create_worker", "failed", worker_id=worker_id, client=client_host, error=str(exc))
            _persist_failed_worker(data, worker_id, hostname, os_name, arch, disk_record, cd_record, str(exc))
            raise HTTPException(500, str(exc)) from exc


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
            _delete_target(record["disk"], delete_file=delete_disk, ignore_missing=ignore_missing_target)
            _record("agent.delete_disk", "ok", worker_id=worker_id, agent=record["disk"]["agent"], iqn=record["disk"]["iqn"], delete_file=delete_disk)

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
    actual["disk"] = _target_actual(record.get("disk"))
    actual["cd"] = _target_actual(record.get("cd"))
    return actual


def _target_actual(target_record: dict[str, Any] | None) -> dict[str, Any] | None:
    if not target_record:
        return None
    try:
        agent = agents.get(target_record["agent"])
        targets = agents.client(agent).list_luns()
        found = next((target for target in targets if target.get("iqn") == target_record["iqn"]), None)
        return {"exists": found is not None, "target": found}
    except Exception as exc:
        return {"exists": False, "error": str(exc)}


def _boot_vars_payload(mac: str | None, hostname: str | None) -> dict[str, Any]:
    match = _find_worker_for_boot(mac=mac, hostname=hostname)
    if not match:
        return {}
    worker_id, record = match
    disk = record.get("disk") or {}
    agent_id = disk.get("agent")
    if not agent_id:
        return {}
    base_iqn = _base_iqn_from_target(disk.get("iqn"))
    try:
        iscsi_server = agents.iscsi_server_for(agent_id)
    except Exception:
        return {}
    boot = record.get("boot") or {}
    menu_default = boot.get("menu_default") or boot.get("menu-default") or _menu_default_for(record)
    menu_timeout = boot.get("menu_timeout") or boot.get("menu-timeout") or settings.boot_menu_timeout
    return {
        "worker_id": worker_id,
        "hostname": record["hostname"],
        "base_iqn": base_iqn,
        "iscsi_server": iscsi_server,
        "menu_default": str(menu_default),
        "menu_timeout": int(menu_timeout),
    }


def _boot_vars_ipxe(payload: dict[str, Any]) -> str:
    lines = ["#!ipxe"]
    if not payload:
        lines.append("# no per-worker boot vars found")
        return "\n".join(lines) + "\n"
    lines.extend(
        [
            f"# boot vars for {payload['worker_id']}",
            f"set base-iqn {payload['base_iqn']}",
            f"set iscsi-server {payload['iscsi_server']}",
            f"set menu-default {payload['menu_default']}",
            f"set menu-timeout {payload['menu_timeout']}",
        ]
    )
    return "\n".join(lines) + "\n"


def _boot_vars_json(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    return {
        "base_iqn": payload["base_iqn"],
        "iscsi_server": payload["iscsi_server"],
        "menu_default": payload["menu_default"],
        "menu_timeout": payload["menu_timeout"],
    }


def _base_iqn_from_target(iqn: str | None) -> str:
    if iqn and ":" in iqn:
        return iqn.rsplit(":", 1)[0]
    return "iqn.2026-07.com.controller"


def _find_worker_for_boot(mac: str | None, hostname: str | None) -> tuple[str, dict[str, Any]] | None:
    data = store.load_workers()
    workers = data["workers"]
    normalized_mac = _normalize_boot_mac(mac) if mac else None
    if normalized_mac:
        for binding in dnsmasq.list_bindings():
            if binding.mac == normalized_mac:
                found = _find_worker_by_hostname(workers, binding.hostname)
                if found:
                    return found
    if hostname:
        try:
            return _find_worker_by_hostname(workers, _canonical_hostname(hostname))
        except HTTPException:
            return None
    return None


def _find_worker_by_hostname(workers: dict[str, Any], hostname: str) -> tuple[str, dict[str, Any]] | None:
    if hostname in workers:
        return hostname, workers[hostname]
    for worker_id, record in workers.items():
        if record.get("hostname") == hostname:
            return worker_id, record
    return None


def _menu_default_for(record: dict[str, Any]) -> str:
    os_name = str(record.get("os", "")).lower()
    if os_name == "windows":
        return "windows"
    return os_name or "exit"


def _enrich_worker(worker_id: str, record: dict[str, Any]) -> dict[str, Any]:
    item = copy.deepcopy(record)
    item["worker_id"] = worker_id
    item["mac"] = dnsmasq.find_mac(item["hostname"])
    return item


def _persist_failed_worker(
    data: dict[str, Any],
    worker_id: str,
    hostname: str,
    os_name: str,
    arch: str,
    disk_record: dict[str, Any] | None,
    cd_record: dict[str, Any] | None,
    error: str,
) -> None:
    if not disk_record and not cd_record:
        return
    data["workers"][worker_id] = {
        "hostname": hostname,
        "os": os_name,
        "arch": arch,
        "state": "failed",
        "error": error,
        "disk": disk_record,
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
