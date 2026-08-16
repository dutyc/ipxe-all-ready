import copy
import datetime as _dt
import hmac
import logging
import re
from typing import Any
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from .agent_client import AgentAPIError, AgentClient, AgentConfig
from .config import settings
from .dnsmasq import DnsmasqHosts, normalize_mac
from .models import (
    BatchBindRequest,
    BatchCreateWorkerDiskRequest,
    BatchCreateWorkersRequest,
    BatchDeleteWorkersRequest,
    BindPair,
    CreateAgentRequest,
    CreateCdLunRequest,
    CreateDeviceRequest,
    CreateDiskLunRequest,
    CreateWorkerDiskRequest,
    CreateWorkerRequest,
    ImportDevicesRequest,
    ProbeAgentRequest,
    SetAutoRegisterRequest,
    SetWorkerDefaultBootRequest,
    UpdateAgentRequest,
    UpdateWorkerMacRequest,
)
from .scheduler import AgentRegistry
from .state import DeviceStore, FileStateStore, OperationLog, RuntimeSettings


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
devices = DeviceStore(settings.devices_file)
operations = OperationLog(settings.operations_file)
agents = AgentRegistry(settings.agents_file, settings.agent_timeout)
dnsmasq = DnsmasqHosts(settings.dnsmasq_hosts_file, settings.dnsmasq_container, settings.dnsmasq_reload)
runtime_settings = RuntimeSettings(settings.settings_file)


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


@app.get("/devices/report")
def device_report(
    request: Request,
    mac: str,
    uuid: str | None = Query(None),
    manufacturer: str | None = Query(None),
    product: str | None = Query(None),
    serial: str | None = Query(None),
    cpumodel: str | None = Query(None),
    mem_total: str | None = Query(None, alias="mem-total"),
    mem_type: str | None = Query(None, alias="mem-type"),
    mem_speed: str | None = Query(None, alias="mem-speed"),
    chip: str | None = Query(None),
    busid: str | None = Query(None),
):
    """iPXE 设备信息上报（不鉴权）：11 字段，宽松解析（空值容忍，mem 兼容 0x hex/十进制），
    更新指纹 + last_seen；未知 MAC 且 auto_register 开 → 入池。返回空响应（chain 无脚本副作用）。"""
    normalized = _normalize_boot_mac(mac)
    if not normalized:
        return Response(status_code=200)  # 非法 MAC 忽略，不阻断引导
    fingerprint = {k: v for k, v in {
        "manufacturer": _clean_str(manufacturer),
        "product": _clean_str(product),
        "serial": _clean_str(serial),
        "cpumodel": _clean_str(cpumodel),
        "mem_total": _parse_uint(mem_total),
        "mem_type": _clean_str(mem_type),
        "mem_speed": _parse_uint(mem_speed),
        "chip": _clean_str(chip),
        "busid": _clean_str(busid),
    }.items() if v is not None}
    now = _now_iso()
    with devices.locked():
        data = devices.load()
        devs = data["devices"]
        existing = devs.get(normalized)
        if existing:
            if existing.get("state") == "revoked":
                return Response(status_code=200)  # 吊销设备不更新、不复活
            existing.setdefault("fingerprint", {}).update(fingerprint)
            clean_uuid = _clean_str(uuid)
            if clean_uuid:
                existing["uuid"] = clean_uuid
            existing["last_seen"] = now
            devices.save(data)
            updated = True
        else:
            if not runtime_settings.get("auto_register", settings.auto_register):
                return Response(status_code=200)  # 未注册且自动注册关：忽略
            devs[normalized] = {
                "mac": normalized,
                "uuid": _clean_str(uuid),
                "state": "pooled",
                "bound_worker_id": None,
                "key_hash": None,
                "source": "ipxe",
                "fingerprint": fingerprint,
                "first_seen": now,
                "last_seen": now,
            }
            devices.save(data)
            updated = False
    if updated:
        _record("device.report", "ok", mac=normalized, client=_client_host(request), updated=True)
    else:
        _record("device.report", "ok", mac=normalized, client=_client_host(request), registered=True)
    return Response(status_code=200)


@app.get("/devices", dependencies=[Depends(verify_control_token)])
def list_devices(state: str = Query("all")):
    """设备池列表：state 过滤（all/pooled/bound/revoked），含指纹与绑定关系。"""
    if state not in {"all", "pooled", "bound", "revoked"}:
        raise HTTPException(400, "state must be one of: all, pooled, bound, revoked")
    data = devices.load()
    items: list[dict[str, Any]] = []
    for mac, record in sorted(data["devices"].items()):
        if state != "all" and record.get("state") != state:
            continue
        item = copy.deepcopy(record)
        item["mac"] = mac
        items.append(item)
    return items


@app.get("/devices/{mac}", dependencies=[Depends(verify_control_token)])
def get_device(mac: str):
    """单设备详情：绑定 worker、指纹、首/末次上报。"""
    mac = _canonical_mac(mac)
    data = devices.load()
    record = data["devices"].get(mac)
    if not record:
        raise HTTPException(404, f"device not found: {mac}")
    item = copy.deepcopy(record)
    item["mac"] = mac
    return item


@app.post("/devices", status_code=201, dependencies=[Depends(verify_control_token)])
def create_device(req: CreateDeviceRequest, request: Request):
    """手动注册设备：MAC（+可选 UUID）入池。重复注册（含已吊销）返回 409。"""
    mac = _canonical_mac(req.mac)
    with devices.locked():
        data = devices.load()
        devs = data["devices"]
        if mac in devs:
            raise HTTPException(409, f"device already exists: {mac} (state={devs[mac].get('state')})")
        now = _now_iso()
        devs[mac] = {
            "mac": mac,
            "uuid": _clean_str(req.uuid),
            "state": "pooled",
            "bound_worker_id": None,
            "key_hash": None,
            "source": "manual",
            "fingerprint": {k: v for k, v in {
                "manufacturer": _clean_str(req.manufacturer),
                "product": _clean_str(req.product),
                "serial": _clean_str(req.serial),
            }.items() if v is not None},
            "first_seen": now,
            "last_seen": None,
        }
        devices.save(data)
    _record("device.register", "ok", mac=mac, source="manual", client=_client_host(request))
    return copy.deepcopy(devs[mac])


@app.post("/devices/import", dependencies=[Depends(verify_control_token)])
def import_devices(req: ImportDevicesRequest, request: Request):
    """批量导入设备清单（MAC 清单预导入）：逐项独立，重复跳过，非法/吊销计 failed。"""
    if not req.entries:
        raise HTTPException(400, "entries must not be empty")
    created: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    now = _now_iso()
    with devices.locked():
        data = devices.load()
        devs = data["devices"]
        for entry in req.entries:
            try:
                mac = _canonical_mac(entry.mac)
            except HTTPException:
                failed.append({"mac": entry.mac, "reason": "invalid mac"})
                continue
            existing = devs.get(mac)
            if existing:
                if existing.get("state") == "revoked":
                    failed.append({"mac": mac, "reason": "device revoked"})
                else:
                    skipped.append({"mac": mac, "reason": f"already {existing.get('state')}"})
                continue
            devs[mac] = {
                "mac": mac,
                "uuid": _clean_str(entry.uuid),
                "state": "pooled",
                "bound_worker_id": None,
                "key_hash": None,
                "source": "manual",
                "fingerprint": {k: v for k, v in {
                    "manufacturer": _clean_str(entry.manufacturer),
                    "product": _clean_str(entry.product),
                    "serial": _clean_str(entry.serial),
                }.items() if v is not None},
                "first_seen": now,
                "last_seen": None,
            }
            created.append({"mac": mac})
        if created:
            devices.save(data)
    _record("device.import", "ok", client=_client_host(request),
            created=len(created), skipped=len(skipped), failed=len(failed))
    return {"created": created, "skipped": skipped, "failed": failed}


@app.post("/devices/{mac}/bind", dependencies=[Depends(verify_control_token)])
def bind_device(
    mac: str,
    request: Request,
    worker_id: str = Query(..., description="Target worker to bind the device to."),
    force: bool = Query(False, description="Atomic rebind when device or worker is already bound."),
):
    """绑定设备到 Worker（设备↔worker 一对一授权）。默认 409（设备或 worker 已绑定）；
    force=true 原子换绑：预校验 → 新绑定落盘 → 旧绑定清除（旧设备回池）→ 失败回滚。
    幂等：重复绑定同 worker 直接返回。"""
    mac = _canonical_mac(mac)
    result = _bind_device(mac, worker_id, force)
    _record("device.bind", "ok", mac=mac, worker_id=worker_id, force=force,
            old_worker_id=result.get("old_worker_id"), old_device_mac=result.get("old_device_mac"),
            client=_client_host(request))
    return _device_record(mac)


@app.delete("/devices/{mac}/bind", dependencies=[Depends(verify_control_token)])
def unbind_device(mac: str, request: Request):
    """解绑设备：设备回池（state=pooled）、移除 dnsmasq 绑定；系统盘保留在 Worker（readiness 降级 partial/idle）。"""
    mac = _canonical_mac(mac)
    client_host = _client_host(request)
    with store.locked(), devices.locked():
        data = devices.load()
        devs = data["devices"]
        dev = devs.get(mac)
        if not dev:
            raise HTTPException(404, f"device not found: {mac}")
        if dev.get("state") != "bound":
            raise HTTPException(409, f"device not bound: {mac} (state={dev.get('state')})")
        worker_id = dev["bound_worker_id"]
        workers = store.load_workers()["workers"]
        hostname = _hostname_of(workers, worker_id)

        snapshot = copy.deepcopy(data)
        dev["state"] = "pooled"
        dev["bound_worker_id"] = None
        try:
            devices.save(data)
        except Exception as exc:
            raise HTTPException(500, f"devices save failed: {exc}") from exc
        if hostname:
            try:
                removed = dnsmasq.remove_hostname(hostname)
                _record("dnsmasq.hosts.delete", "ok", worker_id=worker_id, hostname=hostname, removed=removed)
                try:
                    dnsmasq.reload()
                except Exception:
                    log.exception("unbind: dnsmasq reload failed")
            except Exception as exc:
                # 回滚台账（dnsmasq 写入失败，恢复设备为 bound）
                data["devices"] = snapshot["devices"]
                try:
                    devices.save(data)
                except Exception:
                    log.exception("unbind rollback: devices save failed")
                raise HTTPException(500, f"dnsmasq unbind failed: {exc}") from exc
    _record("device.unbind", "ok", mac=mac, worker_id=worker_id, client=client_host)
    return _device_record(mac)


@app.post("/devices/bind/batch/preview", dependencies=[Depends(verify_control_token)])
def batch_bind_preview(req: BatchBindRequest):
    """批量绑定预览（只读）：manifest 清单配对 / sequential 顺序配对 → 配对表。
    冲突项（设备已绑定/worker 已绑定/清单内重复）与池外设备（not_found）不产生任何写入。"""
    pairs = _resolve_pairs(req)
    with store.locked(), devices.locked():
        workers = store.load_workers()["workers"]
        devs = devices.load()["devices"]
        matched: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        not_found: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_mac, worker_id, pair in pairs:
            try:
                mac = _canonical_mac(raw_mac)
            except HTTPException:
                not_found.append({"mac": raw_mac, "worker_id": worker_id, "reason": "invalid mac"})
                continue
            if mac in seen:
                conflicts.append({"mac": mac, "worker_id": worker_id, "reason": "duplicate in manifest"})
                continue
            seen.add(mac)
            dev = devs.get(mac)
            if not dev:
                not_found.append({"mac": mac, "worker_id": worker_id, "reason": "device not in pool"})
                continue
            if dev.get("state") == "revoked":
                not_found.append({"mac": mac, "worker_id": worker_id, "reason": "device revoked"})
                continue
            if dev.get("state") == "bound":
                conflicts.append({"mac": mac, "worker_id": worker_id,
                                  "reason": f"device already bound to {dev.get('bound_worker_id')}"})
                continue
            if worker_id not in workers:
                conflicts.append({"mac": mac, "worker_id": worker_id, "reason": f"worker not found: {worker_id}"})
                continue
            bound = _device_bound_to_worker(devs, worker_id)
            if bound:
                conflicts.append({"mac": mac, "worker_id": worker_id,
                                  "reason": f"worker already bound to {bound}"})
                continue
            mismatch = _fingerprint_mismatch(dev, pair)
            matched.append({
                "mac": mac,
                "worker_id": worker_id,
                "device_state": dev.get("state", "pooled"),
                "worker_state": workers[worker_id].get("state", "registered"),
                "fingerprint_mismatch": mismatch,
            })
        return {
            "matched": matched,
            "conflicts": conflicts,
            "not_found": not_found,
            "summary": {
                "total": len(pairs),
                "ok": len(matched),
                "conflict": len(conflicts),
                "not_found": len(not_found),
            },
        }


@app.post("/devices/bind/batch", dependencies=[Depends(verify_control_token)])
def batch_bind(req: BatchBindRequest, request: Request):
    """批量绑定执行（幂等，逐项独立）：已绑定配对 = skipped；池外设备 = failed（须先入池）；
    指纹不符不阻断（succeeded 项带 fingerprint_mismatch 标记）。"""
    pairs = _resolve_pairs(req)
    client_host = _client_host(request)
    succeeded: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_mac, worker_id, pair in pairs:
        try:
            mac = _canonical_mac(raw_mac)
        except HTTPException:
            failed.append({"mac": raw_mac, "worker_id": worker_id, "reason": "invalid mac"})
            continue
        if mac in seen:
            skipped.append({"mac": mac, "worker_id": worker_id, "reason": "duplicate in manifest"})
            continue
        seen.add(mac)
        # 幂等预检：已绑定目标 worker → skipped
        with store.locked(), devices.locked():
            devs = devices.load()["devices"]
            dev = devs.get(mac)
            if dev and dev.get("state") == "bound" and dev.get("bound_worker_id") == worker_id:
                skipped.append({"mac": mac, "worker_id": worker_id, "reason": "already bound"})
                continue
        try:
            _bind_device(mac, worker_id, force=False)
        except HTTPException as exc:
            if exc.status_code == 404:
                failed.append({"mac": mac, "worker_id": worker_id, "reason": str(exc.detail)})
            else:
                skipped.append({"mac": mac, "worker_id": worker_id, "reason": str(exc.detail)})
            continue
        item: dict[str, Any] = {"mac": mac, "worker_id": worker_id}
        with devices.locked():
            dev = devices.load()["devices"].get(mac)
            mismatch = _fingerprint_mismatch(dev, pair)
            if mismatch:
                item["fingerprint_mismatch"] = mismatch
        succeeded.append(item)
        _record("device.bind", "ok", mac=mac, worker_id=worker_id, force=False,
                old_worker_id=None, old_device_mac=None, client=client_host)
    _record("device.bind.batch", "ok", client=client_host, ok=len(succeeded),
            skipped=len(skipped), failed=len(failed))
    return {"succeeded": succeeded, "skipped": skipped, "failed": failed}


@app.delete("/devices/{mac}", dependencies=[Depends(verify_control_token)])
def revoke_device(mac: str, request: Request):
    """注销设备（吊销）：pooled → revoked；已绑定需先解绑（bound → 409）；已吊销 409。"""
    mac = _canonical_mac(mac)
    with devices.locked():
        data = devices.load()
        devs = data["devices"]
        record = devs.get(mac)
        if not record:
            raise HTTPException(404, f"device not found: {mac}")
        if record.get("state") == "revoked":
            raise HTTPException(409, f"device already revoked: {mac}")
        if record.get("state") == "bound":
            raise HTTPException(
                409, f"device is bound to worker {record.get('bound_worker_id')}, unbind first: {mac}"
            )
        record["state"] = "revoked"
        devices.save(data)
    _record("device.revoke", "ok", mac=mac, client=_client_host(request))
    return copy.deepcopy(record)


@app.get("/settings/auto-register", dependencies=[Depends(verify_control_token)])
def get_auto_register():
    """查询全局自动注册开关：运行时状态（state/settings.json）优先，未设置时回退环境变量默认。"""
    return {"enabled": runtime_settings.get("auto_register", settings.auto_register)}


@app.put("/settings/auto-register", dependencies=[Depends(verify_control_token)])
def set_auto_register(req: SetAutoRegisterRequest):
    """切换全局自动注册开关（持久化，立即生效；enabled=false 后新 MAC 不再自动注册）。"""
    enabled = runtime_settings.set("auto_register", req.enabled)
    _record("settings.auto_register", "ok", enabled=enabled)
    return {"enabled": enabled}


@app.get("/agents", dependencies=[Depends(verify_control_token)])
def list_agents(live: bool = True):
    return agents.list_public(live=live)


@app.post("/agents", status_code=201, dependencies=[Depends(verify_control_token)])
def create_agent(req: CreateAgentRequest, request: Request):
    """注册新 Agent：写入 agents.yml（重复 id 返回 409）。
    base_url 须 http(s):// 开头；token 支持 ${ENV} 占位（读取时展开）；
    role 决定磁盘/光驱角色；iscsi_server 为数据面地址（缺省用 base_url 主机名）。"""
    agent_id = req.id.strip().lower()
    if not WORKER_ID_RE.match(agent_id):  # Agent id 与 worker id 同一命名规则
        raise HTTPException(400, f"invalid agent id: {req.id}")
    base_url = req.base_url.strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(400, "base_url must start with http:// or https://")
    iscsi_server = req.iscsi_server.strip() if req.iscsi_server else None
    try:
        agents.get(agent_id)
        raise HTTPException(409, f"agent already exists: {agent_id}")
    except KeyError:
        pass

    with store.locked():
        agents.add(
            agent_id,
            base_url,
            req.token.strip(),
            role_disk=req.role.disk,
            role_cd=req.role.cd,
            iscsi_server=iscsi_server,
            enabled=req.enabled,
            tags=tuple(t.strip() for t in req.tags if t.strip()),
        )
    _record("agent.register", "ok", agent=agent_id, client=_client_host(request))
    return agents.get(agent_id).public_dict()


@app.put("/agents/{agent_id}", dependencies=[Depends(verify_control_token)])
def update_agent(agent_id: str, req: UpdateAgentRequest, request: Request):
    """更新已有 Agent：覆盖 agents.yml 中对应条目（id 不可改，走路径参数）。
    token 传空字符串 = 保持原值（API 不回显 token）；enabled=false 停用（不再参与调度与存活探测）。"""
    agent_id = agent_id.strip().lower()
    base_url = req.base_url.strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(400, "base_url must start with http:// or https://")
    iscsi_server = req.iscsi_server.strip() if req.iscsi_server else None
    try:
        agents.get(agent_id)
    except KeyError:
        raise HTTPException(404, f"agent not found: {agent_id}")

    with store.locked():
        agents.update(
            agent_id,
            base_url,
            req.token.strip() or None,
            role_disk=req.role.disk,
            role_cd=req.role.cd,
            iscsi_server=iscsi_server,
            enabled=req.enabled,
            tags=tuple(t.strip() for t in req.tags if t.strip()),
        )
    _record("agent.update", "ok", agent=agent_id, client=_client_host(request))
    return agents.get(agent_id).public_dict()


@app.post("/agents/probe", dependencies=[Depends(verify_control_token)])
def probe_agent(req: ProbeAgentRequest, request: Request):
    """探测 Agent：调 /healthz + /capabilities，自动推导注册参数预览（不写任何文件）。
    推导规则：role.disk 恒真（Agent 即存储节点）、role.cd 取 capabilities.cd；
    tags = [storage, backend]（lio/stgt，供 /boot-vars 连接符推导）；
    iscsi_server 缺省回退 base_url 主机名。"""
    base_url = req.base_url.strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(400, "base_url must start with http:// or https://")

    # 编辑场景：token 留空时回退注册表中该 Agent 的 token（未知 id 则按空 token 探测）
    token = req.token.strip()
    if not token and req.agent_id:
        try:
            token = agents.get(req.agent_id.strip().lower()).token
        except KeyError:
            pass

    # 临时 AgentConfig 探测（不落盘，不进入注册表）
    probe_cfg = AgentConfig(
        id="_probe",
        base_url=base_url,
        token=token,
        role_disk=True,
        role_cd=False,
    )
    client = AgentClient(probe_cfg, agents.timeout)
    try:
        client.healthz()
    except Exception as exc:
        _record("agent.probe", "failed", agent=base_url, client=_client_host(request), error=str(exc))
        raise HTTPException(502, f"agent unreachable: {exc}") from exc
    try:
        caps = client.capabilities()
    except AgentAPIError as exc:
        _record("agent.probe", "failed", agent=base_url, client=_client_host(request), error=exc.detail)
        raise HTTPException(502, {"agent": base_url, "error": exc.detail}) from exc

    backend = str(caps.get("backend", "stgt")).lower()
    _record("agent.probe", "ok", agent=base_url, client=_client_host(request), backend=backend)
    return {
        "base_url": base_url,
        "role": {"disk": True, "cd": bool(caps.get("cd", False))},
        "tags": ["storage", backend],
        "iscsi_server": urlparse(base_url).hostname or base_url,
        "enabled": True,
        "backend": backend,
        "fs_type": caps.get("fs_type", ""),
        "base_iqn": caps.get("base_iqn", ""),
        "clone": caps.get("clone", ""),
        "empty_disk": caps.get("empty_disk", ""),
        "persistent": caps.get("persistent", ""),
    }


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
    agent = _agent_or_404(agent_id)
    if not agent.role_disk:
        raise HTTPException(400, f"agent {agent_id} not configured for disk role")
    client = agents.client(agent)
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
    agent = _agent_or_404(agent_id)
    if not agent.role_cd:
        raise HTTPException(400, f"agent {agent_id} not configured for cd role (LIO backend does not support ISO)")
    client = agents.client(agent)
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


@app.get("/masters", dependencies=[Depends(verify_control_token)])
def list_masters(request: Request):
    """聚合列出全部启用磁盘角色 Agent 上的母盘（后台扫描缓存），供 WebUI 克隆选盘。
    单台 Agent 失败不阻塞整体：失败节点返回 error 字段；全部失败时整体 502。"""
    results: list[dict[str, Any]] = []
    total = failed = 0
    for agent in agents.load():
        if not (agent.enabled and agent.role_disk and agent.base_url):
            continue
        total += 1
        entry: dict[str, Any] = {
            "agent": agent.id,
            "iscsi_server": agents.iscsi_server_for(agent.id),
        }
        try:
            payload = agents.client(agent).list_masters()
        except AgentAPIError as exc:
            failed += 1
            _record("master.list", "failed", agent=agent.id, client=_client_host(request), error=exc.detail)
            entry["masters"] = []
            entry["error"] = exc.detail
            results.append(entry)
            continue
        masters = payload.get("masters", []) if isinstance(payload, dict) else []
        _record("master.list", "ok", agent=agent.id, client=_client_host(request), count=len(masters))
        entry["masters"] = masters
        results.append(entry)
    if total > 0 and failed == total:
        raise HTTPException(502, {"agents": results, "error": "all agents failed"})
    return {"agents": results}


def _agent_or_404(agent_id: str):
    try:
        return agents.get(agent_id)
    except KeyError:
        raise HTTPException(404, f"agent not found: {agent_id}") from None


def _agent_client_or_404(agent_id: str):
    return agents.client(_agent_or_404(agent_id))


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
    """注册 Worker 身份：写入台账 + hostname 绑定。
    mac 可选：不传 = 纯空转 Worker；传 = 校验设备在设备池中并直接绑定（一对一授权）。
    存储与身份分离：系统盘须另调 POST /workers/{worker_id}/luns/disk。"""
    worker_id = _canonical_id(req.worker_id)
    hostname = _canonical_hostname(req.hostname or worker_id)
    arch = req.arch or settings.default_arch
    mac = _canonical_mac(req.mac) if req.mac else None

    cd_record: dict[str, Any] | None = None

    with store.locked():
        data = store.load_workers()
        workers = data["workers"]
        if worker_id in workers:
            raise HTTPException(409, f"worker already exists: {worker_id}")
        _ensure_hostname_not_in_workers(workers, hostname)
        if mac:
            _ensure_device_poolable(mac)
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

            if mac:
                # 绑定设备（设备↔worker 一对一授权）：复用绑定核心流程
                bind_result = _bind_device(mac, worker_id, force=False)
                _record("device.bind", "ok", mac=mac, worker_id=worker_id, force=False,
                        old_worker_id=bind_result.get("old_worker_id"),
                        old_device_mac=bind_result.get("old_device_mac"), client=client_host)
            else:
                _record("create_worker", "idle", worker_id=worker_id, hostname=hostname,
                        mac=None, client=client_host)

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


@app.post("/workers/batch", dependencies=[Depends(verify_control_token)])
def batch_create_workers(req: BatchCreateWorkersRequest, request: Request):
    """批量创建 Worker（逐项独立，幂等重跑）：命名规则 + 数量生成 worker_id（worker-01…），
    macs 与 count 等长时逐项绑定（设备须在池中，不传 = 全部纯空转）。
    已存在 → skipped；设备不可绑定 → failed 且该项不创建（可修正后重试）。不支持 windows_iso。"""
    prefix = req.name_prefix.strip()
    if not prefix:
        raise HTTPException(400, "name_prefix must not be empty")
    digits = max(2, len(str(req.count)))
    _canonical_id(f"{prefix}{1:0{digits}d}")  # 命名规则预校验：生成的 worker_id 必须合法
    if req.macs is not None and len(req.macs) != req.count:
        raise HTTPException(400, f"macs length {len(req.macs)} must equal count {req.count}")

    succeeded: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    client_host = _client_host(request)
    _record("create_worker.batch", "started", count=req.count, prefix=prefix, client=client_host)

    with store.locked():
        data = store.load_workers()
        workers = data["workers"]
        for i in range(1, req.count + 1):
            worker_id = f"{prefix}{i:0{digits}d}"
            hostname = worker_id
            mac = _canonical_mac(req.macs[i - 1]) if req.macs else None
            created = False
            try:
                if worker_id in workers:
                    skipped.append({"worker_id": worker_id, "reason": "already exists"})
                    continue
                _ensure_hostname_not_in_workers(workers, hostname)
                if mac:
                    _ensure_device_poolable(mac)
                    try:
                        dnsmasq.ensure_free(mac, hostname)
                    except ValueError as exc:
                        raise HTTPException(409, str(exc)) from exc
                worker_record = {
                    "hostname": hostname,
                    "arch": req.arch or settings.default_arch,
                    "state": "registered",
                    "disks": [],
                    "cd": None,
                }
                if req.boot:
                    worker_record["boot"] = req.boot.dict(exclude_none=True)
                workers[worker_id] = worker_record
                store.save_workers(data)
                created = True
                _record("workers.write", "ok", worker_id=worker_id)
                if mac:
                    bind_result = _bind_device(mac, worker_id, force=False)
                    _record("device.bind", "ok", mac=mac, worker_id=worker_id, force=False,
                            old_worker_id=bind_result.get("old_worker_id"),
                            old_device_mac=bind_result.get("old_device_mac"), client=client_host)
                succeeded.append({"worker_id": worker_id, "hostname": hostname, "mac": mac})
            except Exception as exc:
                detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
                if created:
                    # 绑定阶段失败：回滚该项台账（dnsmasq 由 _bind_device 内部尽力恢复），可修正后重试
                    workers.pop(worker_id, None)
                    try:
                        store.save_workers(data)
                    except Exception:
                        log.exception("batch create rollback: workers save failed")
                    _record("create_worker.batch", "rollback", worker_id=worker_id,
                            error=str(detail), client=client_host)
                failed.append({
                    "worker_id": worker_id,
                    "hostname": hostname,
                    "mac": mac,
                    "error": str(detail),
                })

    _record("create_worker.batch", "ok", created=len(succeeded), skipped=len(skipped),
            failed=len(failed), prefix=prefix, client=client_host)
    return {"succeeded": succeeded, "skipped": skipped, "failed": failed}


@app.put("/workers/{worker_id}/mac", dependencies=[Depends(verify_control_token)])
def update_worker_mac(worker_id: str, req: UpdateWorkerMacRequest, request: Request):
    """修改 Worker 的 MAC 绑定（hostname 不变）：映射为设备换绑——
    新 MAC 须在设备池中（pooled），绑定新设备；旧设备解绑回池。审计记 device.bind + worker.mac.update（兼容）。"""
    worker_id = _canonical_id(worker_id)
    new_mac = _canonical_mac(req.mac)

    with store.locked():
        data = store.load_workers()
        record = data["workers"].get(worker_id)
        if not record:
            raise HTTPException(404, f"worker not found: {worker_id}")
        hostname = record["hostname"]
        client_host = _client_host(request)
        _record("worker.mac.update", "started", worker_id=worker_id, client=client_host)

        old_mac = dnsmasq.find_mac(hostname)
        if old_mac == new_mac:
            _record("worker.mac.update", "ok", worker_id=worker_id, hostname=hostname,
                    old_mac=old_mac, new_mac=new_mac, changed=False, client=client_host)
            return _enrich_worker(worker_id, record)

        # 新绑定落盘 + 旧设备回池（一次原子写）：预校验——新 MAC 设备须在池中且未绑定
        old_released: str | None = None
        with devices.locked():
            devs_data = devices.load()
            devs = devs_data["devices"]
            new_dev = devs.get(new_mac)
            if not new_dev:
                raise HTTPException(409, f"device not in pool, register first: {new_mac}")
            new_state = new_dev.get("state")
            if new_state == "revoked":
                raise HTTPException(409, f"device revoked: {new_mac}")
            if new_state == "bound":
                raise HTTPException(409, f"device already bound to {new_dev.get('bound_worker_id')}: {new_mac}")
            old_dev = devs.get(old_mac) if old_mac else None
            if old_dev and old_dev.get("bound_worker_id") not in (None, worker_id):
                raise HTTPException(409, f"device {old_mac} bound to unexpected worker: "
                                    f"{old_dev.get('bound_worker_id')}")

            new_dev["state"] = "bound"
            new_dev["bound_worker_id"] = worker_id
            if old_dev and old_dev.get("state") == "bound" and old_dev.get("bound_worker_id") == worker_id:
                old_dev["state"] = "pooled"
                old_dev["bound_worker_id"] = None
                old_released = old_mac
            try:
                devices.save(devs_data)
            except Exception as exc:
                raise HTTPException(500, f"devices save failed: {exc}") from exc

        # dnsmasq 替换绑定（hostname 不变，仅换 MAC）
        try:
            replaced = dnsmasq.replace_binding(hostname, new_mac)
        except ValueError as exc:
            _rollback_devices_binding(new_mac, old_released, worker_id)
            _record("worker.mac.update", "failed", worker_id=worker_id, client=client_host, error=str(exc))
            raise HTTPException(409, str(exc)) from exc
        if replaced is None:
            _rollback_devices_binding(new_mac, old_released, worker_id)
            _record("worker.mac.update", "failed", worker_id=worker_id, client=client_host,
                    error=f"no dnsmasq binding for hostname: {hostname}")
            raise HTTPException(409, f"no dnsmasq binding for hostname: {hostname}")
        try:
            dnsmasq_result = dnsmasq.reload()
        except Exception as exc:
            _record("worker.mac.update", "failed", worker_id=worker_id, client=client_host,
                    old_mac=old_mac, new_mac=new_mac, error=f"dnsmasq reload failed: {exc}")
            raise HTTPException(500, f"dnsmasq reload failed: {exc}") from exc

        _record("worker.mac.update", "ok", worker_id=worker_id, hostname=hostname,
                old_mac=old_mac, new_mac=new_mac, changed=True, client=client_host)
        _record("dnsmasq.reload", "ok", worker_id=worker_id, result=dnsmasq_result)
        if old_released:
            _record("device.unbind", "ok", mac=old_released, worker_id=worker_id,
                    reason="worker.mac.update", client=client_host)
        _record("device.bind", "ok", mac=new_mac, worker_id=worker_id, force=True,
                old_worker_id=worker_id, old_device_mac=old_released, client=client_host)
        return _enrich_worker(worker_id, record)


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


@app.post("/workers/luns/disk/batch", dependencies=[Depends(verify_control_token)])
def batch_create_worker_disks(req: BatchCreateWorkerDiskRequest, request: Request):
    """批量给多个 Worker 创建系统盘：每个 target 指定 worker + 存储节点（agent，须已分配）。
    与单盘一致：master 走母盘克隆，empty 建空白盘；同一 os 至多一块，已存在则自动跳过（不算失败）。
    创建成功的 Worker 自动将 default_os 设为本次批量系统（批量部署直接进入默认启动）。
    逐项独立执行，单项失败不影响其余；返回 succeeded / skipped / failed 汇总。"""
    os_name = _canonical_os(req.os)
    if os_name not in OS_ITEMS:
        raise HTTPException(400, f"os must be one of {sorted(OS_ITEMS)}: {os_name}")
    _validate_disk(req.type, req.name, req.size)
    if not req.targets:
        raise HTTPException(400, "targets must not be empty")

    client_host = _client_host(request)
    succeeded: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    with store.locked():
        data = store.load_workers()
        for target in req.targets:
            worker_id = _canonical_id(target.worker_id)
            record = data["workers"].get(worker_id)
            if not record:
                failed.append({"worker_id": worker_id, "error": f"worker not found: {worker_id}"})
                continue
            if _find_disk_by_os(record, os_name):
                skipped.append({"worker_id": worker_id, "reason": f"already has a {os_name} system disk"})
                continue

            _record("worker.disk.create", "started", worker_id=worker_id, client=client_host)
            try:
                disk_agent = agents.get(target.agent)
                if not disk_agent:
                    raise HTTPException(400, f"agent not found: {target.agent}")
                if not disk_agent.role_disk:
                    raise HTTPException(400, f"agent {target.agent} not configured for disk role")
                client = agents.client(disk_agent)
                try:
                    client.healthz()
                    disk_caps = client.capabilities()
                except Exception as exc:
                    raise HTTPException(503, f"agent {target.agent} not reachable: {exc}") from exc

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
                # 批量部署约定：创建成功即设为默认启动系统（单盘接口不自动设置）
                record["default_os"] = os_name
                store.save_workers(data)
                _record("workers.disk.write", "ok", worker_id=worker_id, iqn=disk_record["iqn"])
                _record(
                    "worker.boot.set",
                    "ok",
                    worker_id=worker_id,
                    client=client_host,
                    changes=f"default_os:{os_name}",
                )
                _record("worker.disk.create", "succeeded", worker_id=worker_id, client=client_host)
                succeeded.append({"worker_id": worker_id, "agent": disk_agent.id, "iqn": disk_record["iqn"]})
            except Exception as exc:
                detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
                if isinstance(detail, dict):
                    detail = detail.get("error") or str(detail)
                _record("worker.disk.create", "failed", worker_id=worker_id, client=client_host, error=str(detail))
                failed.append({"worker_id": worker_id, "agent": target.agent, "error": str(detail)})

    return {"succeeded": succeeded, "skipped": skipped, "failed": failed}


@app.delete("/workers/{worker_id}/luns/disk/{os_name}", dependencies=[Depends(verify_control_token)])
def delete_worker_disk(
    worker_id: str,
    os_name: str,
    request: Request,
    delete_file: bool = Query(False, description="Delete the disk backing .img as well."),
    ignore_missing_target: bool = Query(False, description="Ignore 404 from Agent while deleting the target."),
):
    """删除 Worker 的单个系统盘：可保留或删除 .img 文件；
    被删系统若为默认启动，联动清除 default_os 与同名 menu_default；无盘时状态回退 registered。"""
    worker_id = _canonical_id(worker_id)
    os_name = _canonical_os(os_name)
    with store.locked():
        data = store.load_workers()
        record = data["workers"].get(worker_id)
        if not record:
            raise HTTPException(404, f"worker not found: {worker_id}")
        disk = _find_disk_by_os(record, os_name)
        if not disk:
            raise HTTPException(404, f"worker {worker_id} has no {os_name} system disk")

        client_host = _client_host(request)
        _record("worker.disk.delete", "started", worker_id=worker_id, client=client_host, os=os_name)

        try:
            _delete_target(disk, delete_file=delete_file, ignore_missing=ignore_missing_target)
            _record("agent.delete_disk", "ok", worker_id=worker_id, agent=disk["agent"],
                    iqn=disk["iqn"], delete_file=delete_file)

            disks = record.get("disks")
            if disks is not None:
                disks[:] = [d for d in disks if d is not disk]
            else:
                record.pop("disk", None)  # 旧台账单盘字段

            # 联动：被删系统正是默认启动时清除 default_os 与同名 menu_default
            if str(record.get("default_os", "")).lower() == os_name:
                record.pop("default_os", None)
            boot = record.get("boot") or {}
            if str(boot.get("menu_default", "")).lower() == os_name:
                boot.pop("menu_default", None)
                if not boot:
                    record.pop("boot", None)

            # 无盘时状态回退 registered，等待重新建盘
            if not _worker_disks(record) and record.get("state") == "ready":
                record["state"] = "registered"

            store.save_workers(data)
            _record("workers.disk.delete", "ok", worker_id=worker_id, os=os_name)
            _record("worker.disk.delete", "succeeded", worker_id=worker_id, client=client_host)
            return _enrich_worker(worker_id, record)
        except AgentAPIError as exc:
            _record("worker.disk.delete", "failed", worker_id=worker_id, client=client_host, error=exc.detail)
            raise HTTPException(exc.status_code, {"agent": exc.agent_id, "error": exc.detail}) from exc
        except Exception as exc:
            _record("worker.disk.delete", "failed", worker_id=worker_id, client=client_host, error=str(exc))
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

        # 联动解绑设备（设备回池，不吊销）：先解绑落盘，再删 worker（解绑失败则中止删除）
        unbound: list[str] = []
        with devices.locked():
            devs_data = devices.load()
            unbound = _unbind_worker_devices(devs_data, worker_id)
            if unbound:
                devices.save(devs_data)

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
            for mac in unbound:
                _record("device.unbind", "ok", mac=mac, worker_id=worker_id,
                        reason="worker.delete", client=client_host)

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


@app.post("/workers/delete/batch", dependencies=[Depends(verify_control_token)])
def batch_delete_workers(req: BatchDeleteWorkersRequest, request: Request):
    """批量删除 Worker：逐项独立执行（单项失败不影响其余），返回 succeeded / failed 汇总。
    每项：删 CD/系统盘 target（delete_disk 控制是否连 .img）、移台账、移除 dnsmasq 绑定；
    全部成功项统一保存台账、统一 reload 一次 dnsmasq。"""
    if not req.worker_ids:
        raise HTTPException(400, "worker_ids must not be empty")

    client_host = _client_host(request)
    succeeded: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    with store.locked():
        data = store.load_workers()
        removed_hostnames: list[str] = []
        unbound_devices: list[str] = []
        for raw_id in req.worker_ids:
            worker_id = _canonical_id(raw_id)
            record = data["workers"].get(worker_id)
            if not record:
                failed.append({"worker_id": worker_id, "error": f"worker not found: {worker_id}"})
                continue

            _record("delete_worker", "started", worker_id=worker_id, client=client_host,
                    delete_disk=req.delete_disk)
            try:
                if record.get("cd"):
                    _delete_target(record["cd"], delete_file=False, ignore_missing=req.ignore_missing_target)
                    _record("agent.delete_cd", "ok", worker_id=worker_id,
                            agent=record["cd"]["agent"], iqn=record["cd"]["iqn"])
                for disk in _worker_disks(record):
                    _delete_target(disk, delete_file=req.delete_disk, ignore_missing=req.ignore_missing_target)
                    _record("agent.delete_disk", "ok", worker_id=worker_id,
                            agent=disk["agent"], iqn=disk["iqn"], delete_file=req.delete_disk)

                hostname = record["hostname"]
                # 联动解绑设备（设备回池，不吊销）：解绑失败则该 worker 不删除
                with devices.locked():
                    devs_data = devices.load()
                    unbound = _unbind_worker_devices(devs_data, worker_id)
                    if unbound:
                        devices.save(devs_data)
                        unbound_devices.extend(unbound)
                del data["workers"][worker_id]
                _record("workers.delete", "ok", worker_id=worker_id)
                for mac in unbound:
                    _record("device.unbind", "ok", mac=mac, worker_id=worker_id,
                            reason="worker.delete", client=client_host)
                removed_hostnames.append(hostname)
                _record("delete_worker", "succeeded", worker_id=worker_id, client=client_host)
                succeeded.append({"worker_id": worker_id, "hostname": hostname})
            except Exception as exc:
                detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
                if isinstance(detail, dict):
                    detail = detail.get("error") or str(detail)
                _record("delete_worker", "failed", worker_id=worker_id,
                        client=client_host, error=str(detail))
                failed.append({"worker_id": worker_id, "error": str(detail)})

        if succeeded:
            store.save_workers(data)
            for hostname in removed_hostnames:
                removed = dnsmasq.remove_hostname(hostname)
                _record("dnsmasq.hosts.delete", "ok", hostname=hostname, removed=removed)
            dnsmasq_result = dnsmasq.reload()
            _record("dnsmasq.reload", "ok", batch=len(removed_hostnames), result=dnsmasq_result)

    return {"succeeded": succeeded, "failed": failed}


@app.get("/operations", dependencies=[Depends(verify_control_token)])
def get_operations(since: int = 0, limit: int = 1000, mac: str | None = None):
    """审计日志（游标分页）；mac 可选：规范化后仅返回该设备的操作（用于设备绑定记录查看）。"""
    if mac is not None:
        mac = _canonical_mac(mac)
    result = operations.read(since=since, limit=limit)
    if mac is not None:
        result["entries"] = [e for e in result["entries"] if e.get("mac") == mac]
        result["next_cursor"] = result["entries"][-1]["id"] if result["entries"] else since
    return result


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
    """启动变量投影。识别链：hostname→worker；mac→设备→绑定 worker。
    防冒领（D2）：带 mac 的请求须来自该 worker 绑定的设备（绑定即认证），不符 → 拒绝下发空脚本。
    自动注册语义：新 MAC 只入设备池（不建 worker），池中未绑定返回 reboot 循环等待。"""
    match = _find_worker_for_boot(mac=mac, hostname=hostname)
    if match:
        if _boot_binding_ok(match[0], mac):
            return _worker_boot_payload(match)
        return {}  # 冒领/未绑定设备请求 → 拒绝下发
    device = _device_for_boot(mac)
    if device:
        # 池中未绑定：reboot 循环等待绑定；吊销/异常态：空脚本（绑定设备必然命中 dnsmasq → worker）
        if device.get("state") == "pooled":
            return _reboot_boot_payload()
        return {}
    if mac and _register_device_from_boot(mac):
        return _reboot_boot_payload()
    return {}


def _worker_boot_payload(match: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    """按已识别 worker 投影启动变量（原 _boot_vars_payload 识别后主体）。"""
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
        backend = _backend_for(agent_id)
        # 只投影 iSCSI root 连接符（差异点），root-path 拼装由 iPXE 侧完成：
        # stgt 需 `:::1:`（lun 占位 1），LIO 需 `::::`（空占位）
        payload["base_iqn"] = base_iqn
        payload["iscsi_server"] = iscsi_server
        payload["iscsi_sep"] = ":::1:" if backend == "stgt" else "::::"
    return payload


def _reboot_boot_payload() -> dict[str, Any]:
    """池中未绑定/已注册未配置：reboot 循环（短超时），等待绑定或配置完成。"""
    return {"menu_default": "reboot", "menu_timeout": settings.auto_boot_timeout}


def _backend_for(agent_id: str) -> str:
    """返回 Agent 的 iSCSI 后端类型（stgt | lio）。

    优先读配置 tags 标记（离线零成本），未标记时查询 /capabilities
    （Agent 自报），查询失败默认 stgt 以保持既有格式兼容。
    """
    try:
        agent = agents.get(agent_id)
    except KeyError:
        return "stgt"
    tags = {str(t).strip().lower() for t in agent.tags}
    if "lio" in tags:
        return "lio"
    if "stgt" in tags:
        return "stgt"
    try:
        backend = str(agents.client(agent).capabilities().get("backend", "")).lower()
        if backend in {"stgt", "lio"}:
            return backend
    except Exception:
        pass
    return "stgt"


def _device_for_boot(mac: str | None) -> dict[str, Any] | None:
    """boot-vars 请求的 MAC 反查设备台账。"""
    normalized = _normalize_boot_mac(mac) if mac else None
    if not normalized:
        return None
    data = devices.load()
    return data["devices"].get(normalized)


def _register_device_from_boot(mac: str) -> bool:
    """新 MAC 入设备池（不建 worker、不写 dnsmasq 绑定）。
    失败返回 False（不阻断 iPXE，下次请求重试）。"""
    if not runtime_settings.get("auto_register", settings.auto_register):
        return False
    normalized = _normalize_boot_mac(mac)
    if not normalized:
        return False
    now = _now_iso()
    with devices.locked():
        data = devices.load()
        devs = data["devices"]
        if normalized in devs:
            return False  # 已存在（池中/绑定/吊销），不重复处理
        devs[normalized] = {
            "mac": normalized,
            "uuid": None,
            "state": "pooled",
            "bound_worker_id": None,
            "key_hash": None,
            "source": "ipxe",
            "fingerprint": {},
            "first_seen": now,
            "last_seen": now,
        }
        try:
            devices.save(data)
        except Exception as exc:
            # 回滚台账，避免留下未落盘的孤儿条目
            devs.pop(normalized, None)
            log.exception("device register failed")
            _record("device.register", "failed", mac=normalized, error=str(exc))
            return False
    _record("device.register", "ok", mac=normalized, source="ipxe")
    return True


def _migrate_legacy_devices() -> None:
    """旧数据迁移：扫描 workers.yml + dnsmasq 绑定，为每个已有 MAC 绑定生成 bound 设备实体
    （state=bound, bound_worker_id=对应 worker, source=manual, 指纹空, 等待首次上报补充）。
    幂等：设备已存在则跳过。失败仅记日志，不阻断启动。"""
    try:
        with store.locked(), devices.locked():
            data = store.load_workers()
            devs = devices.load()
            changed = False
            for worker_id, record in data["workers"].items():
                hostname = str(record.get("hostname", ""))
                mac = dnsmasq.find_mac(hostname) if hostname else None
                if not mac or mac in devs["devices"]:
                    continue
                devs["devices"][mac] = {
                    "mac": mac,
                    "uuid": None,
                    "state": "bound",
                    "bound_worker_id": worker_id,
                    "key_hash": None,
                    "source": "manual",
                    "fingerprint": {},
                    "first_seen": _now_iso(),
                    "last_seen": None,
                }
                changed = True
            if changed:
                devices.save(devs)
    except Exception:
        log.exception("legacy device migration failed")


def _boot_vars_ipxe(payload: dict[str, Any]) -> str:
    lines = ["#!ipxe"]
    if not payload:
        lines.append("# no per-worker boot vars found")
        return "\n".join(lines) + "\n"
    # reboot 循环 payload(池中未绑定)无 worker_id,统一用 unbound 标识
    lines.append(f"# boot vars for {payload.get('worker_id', 'unbound')}")
    if payload.get("base_iqn"):
        lines.append(f"set base-iqn {payload['base_iqn']}")
    if payload.get("iscsi_server"):
        lines.append(f"set iscsi-server {payload['iscsi_server']}")
    if payload.get("iscsi_sep"):
        lines.append(f"set iscsi-sep {payload['iscsi_sep']}")
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
    if payload.get("iscsi_sep"):
        result["iscsi_sep"] = payload["iscsi_sep"]
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
    bound_device = _bound_device_mac_for(worker_id)
    item["bound_device"] = bound_device
    item["readiness"] = _readiness_for(bound_device, bool(_worker_disks(record)))
    return item


def _readiness_for(bound_device: str | None, has_disk: bool) -> str:
    """就绪度派生：绑定+有盘 → ready；绑定或有盘 → partial；皆无 → idle。"""
    if bound_device and has_disk:
        return "ready"
    if bound_device or has_disk:
        return "partial"
    return "idle"


def _bound_device_mac_for(worker_id: str) -> str | None:
    """反查绑定到该 worker 的设备 mac（设备台账权威面）。"""
    data = devices.load()
    for mac, dev in data["devices"].items():
        if dev.get("bound_worker_id") == worker_id:
            return mac
    return None


def _bind_device(mac: str, worker_id: str, force: bool) -> dict[str, Any]:
    """绑定/换绑核心（设备↔worker 一对一授权）。
    force=true 原子换绑：预校验 → 新绑定落盘 → 旧绑定清除（旧设备回池）→ 失败回滚（恢复台账 + 尽力恢复 dnsmasq）。
    幂等：设备已绑该 worker 且 worker 绑定该设备 → 直接返回。返回 {old_worker_id, old_device_mac}。"""
    with store.locked(), devices.locked():
        workers = store.load_workers()["workers"]
        record = workers.get(worker_id)
        if not record:
            raise HTTPException(404, f"worker not found: {worker_id}")
        hostname = str(record["hostname"])
        data = devices.load()
        devs = data["devices"]
        dev = devs.get(mac)
        if not dev:
            raise HTTPException(404, f"device not found: {mac}")
        if dev.get("state") == "revoked":
            raise HTTPException(409, f"device revoked: {mac}")

        old_worker = dev.get("bound_worker_id") if dev.get("state") == "bound" else None
        old_device = _device_bound_to_worker(devs, worker_id)
        if old_worker == worker_id and old_device == mac:
            return {"old_worker_id": old_worker, "old_device_mac": old_device}  # 幂等
        if old_worker and not force:
            raise HTTPException(409, f"device already bound to {old_worker}: {mac}")
        if old_device and not force:
            raise HTTPException(409, f"worker already bound to {old_device}: {worker_id}")

        # dnsmasq 预校验（台账与 dhcp 一致性）：非 force 要求双空闲；force 允许旧绑定存在、拒绝第三方占用
        try:
            if force:
                _check_swap_bindings(mac, hostname, old_worker, old_device, workers)
            else:
                dnsmasq.ensure_free(mac, hostname)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

        snapshot = copy.deepcopy(data)

        # 1) 新绑定落盘 + 旧设备回池（一次原子写）
        dev["state"] = "bound"
        dev["bound_worker_id"] = worker_id
        if old_device and old_device != mac:
            devs[old_device]["state"] = "pooled"
            devs[old_device]["bound_worker_id"] = None
        try:
            devices.save(data)
        except Exception as exc:
            raise HTTPException(500, f"devices save failed: {exc}") from exc

        # 2) dnsmasq：清旧绑定 + 加新绑定（reload 失败仅告警——文件已生效，容器下次重启加载）
        try:
            if old_worker and old_worker != worker_id:
                old_hostname = _hostname_of(workers, old_worker)
                if old_hostname:
                    dnsmasq.remove_hostname(old_hostname)
            if old_device and old_device != mac:
                dnsmasq.remove_hostname(hostname)
            dnsmasq.add_binding(mac, hostname)
            try:
                dnsmasq.reload()
            except Exception:
                log.exception("bind: dnsmasq reload failed")
        except Exception as exc:
            # 3) 失败回滚：恢复台账快照 + 尽力恢复 dnsmasq
            data["devices"] = snapshot["devices"]
            try:
                devices.save(data)
            except Exception:
                log.exception("bind rollback: devices save failed")
            try:
                dnsmasq.remove_hostname(hostname)
                if old_worker and old_worker != worker_id:
                    old_hostname = _hostname_of(workers, old_worker)
                    if old_hostname:
                        dnsmasq.add_binding(mac, old_hostname)
                if old_device and old_device != mac:
                    dnsmasq.add_binding(old_device, hostname)
                try:
                    dnsmasq.reload()
                except Exception:
                    pass
            except Exception:
                log.exception("bind rollback: dnsmasq restore failed")
            raise HTTPException(500, f"dnsmasq binding failed: {exc}") from exc

        return {"old_worker_id": old_worker, "old_device_mac": old_device}


def _check_swap_bindings(
    mac: str,
    hostname: str,
    old_worker: str | None,
    old_device: str | None,
    workers: dict[str, Any],
) -> None:
    """force 换绑的 dnsmasq 一致性预检：允许旧绑定存在（mac→旧 worker hostname、hostname→旧设备），
    第三方占用（其他 hostname 用了该 mac、其他 mac 用了该 hostname）→ 拒绝。"""
    old_hostname = _hostname_of(workers, old_worker)
    for binding in dnsmasq.list_bindings():
        if binding.mac == mac:
            if old_hostname and binding.hostname == old_hostname:
                continue
            raise ValueError(f"mac already bound to {binding.hostname}: {mac}")
        if binding.hostname == hostname:
            if old_device == binding.mac:
                continue
            raise ValueError(f"hostname already bound in dnsmasq: {hostname}")


def _device_bound_to_worker(devs: dict[str, Any], worker_id: str) -> str | None:
    """反查绑定到该 worker 的设备 mac（设备台账权威面；devs 为已加载的 devices dict）。"""
    for mac, dev in devs.items():
        if dev.get("bound_worker_id") == worker_id:
            return mac
    return None


def _hostname_of(workers: dict[str, Any], worker_id: str | None) -> str | None:
    if not worker_id:
        return None
    record = workers.get(worker_id)
    return str(record["hostname"]) if record else None


def _ensure_device_poolable(mac: str) -> dict[str, Any]:
    """设备池预校验：设备存在、未吊销、未绑定（pooled）→ 返回设备记录；否则 409。"""
    with devices.locked():
        data = devices.load()
        dev = data["devices"].get(mac)
        if not dev:
            raise HTTPException(409, f"device not in pool, register first: {mac}")
        if dev.get("state") == "revoked":
            raise HTTPException(409, f"device revoked: {mac}")
        if dev.get("state") == "bound":
            raise HTTPException(409, f"device already bound to {dev.get('bound_worker_id')}: {mac}")
        return dev


def _unbind_worker_devices(data: dict[str, Any], worker_id: str) -> list[str]:
    """联动解绑：把绑定到该 worker 的设备全部回池（state=pooled），返回解绑 mac 列表。"""
    unbound: list[str] = []
    for mac, dev in data["devices"].items():
        if dev.get("bound_worker_id") == worker_id:
            dev["state"] = "pooled"
            dev["bound_worker_id"] = None
            unbound.append(mac)
    return unbound


def _rollback_devices_binding(new_mac: str, old_released: str | None, worker_id: str) -> None:
    """PUT mac 换绑失败回滚：恢复台账（新设备回池、旧设备恢复绑定）。"""
    try:
        with devices.locked():
            data = devices.load()
            devs = data["devices"]
            dev = devs.get(new_mac)
            if dev and dev.get("state") == "bound" and dev.get("bound_worker_id") == worker_id:
                dev["state"] = "pooled"
                dev["bound_worker_id"] = None
            if old_released:
                old_dev = devs.get(old_released)
                if old_dev and old_dev.get("state") == "pooled":
                    old_dev["state"] = "bound"
                    old_dev["bound_worker_id"] = worker_id
            devices.save(data)
    except Exception:
        log.exception("worker.mac.update rollback: devices save failed")


def _resolve_pairs(req: BatchBindRequest) -> list[tuple[str, str, BindPair | None]]:
    """解析批量配对方式：manifest（pairs 清单）或 sequential（macs/worker_ids 下标对齐）。"""
    if req.mode == "manifest":
        if not req.pairs:
            raise HTTPException(400, "mode=manifest requires pairs")
        return [(p.mac, p.worker_id, p) for p in req.pairs]
    if req.mode == "sequential":
        if not req.macs or not req.worker_ids:
            raise HTTPException(400, "mode=sequential requires macs and worker_ids")
        if len(req.macs) != len(req.worker_ids):
            raise HTTPException(400, "macs and worker_ids must have the same length")
        return [(m, w, None) for m, w in zip(req.macs, req.worker_ids)]
    raise HTTPException(400, "mode must be manifest or sequential")


def _fingerprint_mismatch(dev: dict[str, Any] | None, pair: BindPair | None) -> dict[str, Any] | None:
    """清单申报列与设备上报指纹比对（申报性质，不阻断绑定）：
    申报值有值且与上报值（已上报）不符 → {"fields": [列名...]}；无比对列或一致 → None。"""
    if pair is None or dev is None:
        return None
    fp = dev.get("fingerprint") or {}
    checks = (
        ("manufacturer", pair.manufacturer, fp.get("manufacturer")),
        ("product", pair.product, fp.get("product")),
        ("serial", pair.serial, fp.get("serial")),
        ("uuid", pair.uuid, dev.get("uuid")),
    )
    fields = [
        name for name, expected, actual in checks
        if expected and actual is not None and str(expected).strip() != str(actual).strip()
    ]
    return {"fields": fields} if fields else None


def _boot_binding_ok(worker_id: str, mac: str | None) -> bool:
    """防冒领（D2）：带 mac 的启动请求须来自该 worker 绑定的设备（绑定即认证）；
    未带 mac（仅 hostname）无法校验身份，保持兼容放行。"""
    if not mac:
        return True
    device = _device_for_boot(mac)
    return bool(device and device.get("state") == "bound" and device.get("bound_worker_id") == worker_id)


def _device_record(mac: str) -> dict[str, Any]:
    """设备台账记录投影（含 mac 字段）。"""
    data = devices.load()
    record = data["devices"].get(mac)
    if not record:
        raise HTTPException(404, f"device not found: {mac}")
    item = copy.deepcopy(record)
    item["mac"] = mac
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


def _now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat()


def _clean_str(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _parse_uint(value: str | None) -> int | None:
    """宽松整数解析：兼容 0x hex 与十进制（契约：服务端需同时兼容两种格式）；非法/空 → None。"""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return int(cleaned, 0)
    except ValueError:
        return None


def _record(op: str, status: str, **extra: Any) -> None:
    try:
        operations.record(op, status, **extra)
    except Exception:
        log.exception("failed to write operation log")


# 启动时执行一次旧数据迁移（幂等；失败仅记日志，不阻断启动）
_migrate_legacy_devices()
