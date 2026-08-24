"""Worker 管理端点（Bearer 鉴权）：CRUD / 批量 / 系统盘 / 默认启动 / MAC 换绑，及 Worker 台账投影。
含 NVMe-oF 凭据端点（/workers/{worker_id}/credential，DHHC-1 密钥按 Worker 跟盘）。"""

import base64
import copy
import hashlib
import logging
import zlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..agent_client import AgentAPIError
from ..auth import verify_control_token
from ..config import settings
from ..models import (
    BatchCreateWorkerDiskRequest,
    BatchCreateWorkersRequest,
    BatchDeleteWorkersRequest,
    CreateWorkerDiskRequest,
    CreateWorkerRequest,
    CredentialRequest,
    SetWorkerDefaultBootRequest,
    UpdateWorkerMacRequest,
)
from ..stores import agents, credentials, devices, dnsmasq, record, store
from ..utils import (
    add_worker_disk,
    build_disk_filename,
    build_iqn,
    build_nqn,
    canonical_hostname,
    canonical_id,
    canonical_mac,
    canonical_os,
    client_host,
    disk_source,
    ensure_hostname_not_in_workers,
    find_disk_by_os,
    now_iso,
    nqn_to_iqn,
    validate_disk,
    worker_disks,
)
from .devices import _bind_device, _ensure_device_poolable, _rollback_devices_binding, _unbind_worker_devices

log = logging.getLogger("control-plane")

# menu.ipxe 主菜单 item ID（choose --default 的合法值），作为 boot.menu_default 的严格校验集合
MENU_ITEMS = {
    "windows", "ubuntu", "debian", "centos", "esxi",
    "menu-diag", "menu-install", "config", "shell", "reboot", "exit",
}
# 可作为系统盘的 os（menu.ipxe 操作系统项子集），建盘与 default_os 同源严格校验
OS_ITEMS = {"windows", "ubuntu", "debian", "centos", "esxi"}

router = APIRouter(dependencies=[Depends(verify_control_token)])


@router.get("/workers")
def list_workers():
    data = store.load_workers()
    return [
        _enrich_worker(worker_id, record_)
        for worker_id, record_ in sorted(data["workers"].items())
    ]


@router.get("/workers/{worker_id}")
def get_worker(worker_id: str):
    worker_id = canonical_id(worker_id)
    data = store.load_workers()
    record_ = data["workers"].get(worker_id)
    if not record_:
        raise HTTPException(404, f"worker not found: {worker_id}")
    return _enrich_worker(worker_id, record_)


@router.get("/workers/{worker_id}/status")
def get_worker_status(worker_id: str):
    worker_id = canonical_id(worker_id)
    data = store.load_workers()
    record_ = data["workers"].get(worker_id)
    if not record_:
        raise HTTPException(404, f"worker not found: {worker_id}")
    return {
        "worker": _enrich_worker(worker_id, record_),
        "actual": _actual_state(record_),
    }


@router.post("/workers", status_code=201)
def create_worker(req: CreateWorkerRequest, request: Request):
    """注册 Worker 身份：写入台账 + hostname 绑定。
    mac 可选：不传 = 纯空转 Worker；传 = 校验设备在设备池中并直接绑定（一对一授权）。
    存储与身份分离：系统盘须另调 POST /workers/{worker_id}/luns/disk。"""
    worker_id = canonical_id(req.worker_id)
    hostname = canonical_hostname(req.hostname or worker_id)
    arch = req.arch or settings.default_arch
    mac = canonical_mac(req.mac) if req.mac else None

    cd_record: dict[str, Any] | None = None

    with store.locked():
        data = store.load_workers()
        workers = data["workers"]
        if worker_id in workers:
            raise HTTPException(409, f"worker already exists: {worker_id}")
        ensure_hostname_not_in_workers(workers, hostname)
        if mac:
            _ensure_device_poolable(mac)
            try:
                dnsmasq.ensure_free(mac, hostname)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc

        client_ip = client_host(request)
        record("create_worker", "started", worker_id=worker_id, client=client_ip)

        try:
            if req.windows_iso:
                cd_agent, cd_caps = agents.select_cd_agent()
                # CD 盘无 nqn（nvmet 不支持 cd）：base_nqn 派生 IQN 后按历史契约生成盘 IQN
                cd_iqn = build_iqn(nqn_to_iqn(cd_caps["base_nqn"]), worker_id, "windows.iso")
                cd_client = agents.client(cd_agent)
                cd_result = cd_client.create_cd(req.windows_iso, cd_iqn)
                cd_record = {
                    "agent": cd_agent.id,
                    "iqn": cd_result.get("iqn", cd_iqn),
                    "iso": req.windows_iso,
                    "backing": cd_result.get("backing"),
                }
                record("agent.create_cd", "ok", worker_id=worker_id, agent=cd_agent.id, iqn=cd_record["iqn"])

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
            record("workers.write", "ok", worker_id=worker_id)

            if mac:
                # 绑定设备（设备↔worker 一对一授权）：复用绑定核心流程
                bind_result = _bind_device(mac, worker_id, force=False)
                record("device.bind", "ok", mac=mac, worker_id=worker_id, force=False,
                       old_worker_id=bind_result.get("old_worker_id"),
                       old_device_mac=bind_result.get("old_device_mac"), client=client_ip)
            else:
                record("create_worker", "idle", worker_id=worker_id, hostname=hostname,
                       mac=None, client=client_ip)

            record("create_worker", "succeeded", worker_id=worker_id, client=client_ip)
            return _enrich_worker(worker_id, worker_record)
        except AgentAPIError as exc:
            record("create_worker", "failed", worker_id=worker_id, client=client_ip, error=exc.detail)
            _persist_failed_worker(data, worker_id, hostname, arch, None, cd_record, exc.detail)
            raise HTTPException(exc.status_code, {"agent": exc.agent_id, "error": exc.detail}) from exc
        except Exception as exc:
            record("create_worker", "failed", worker_id=worker_id, client=client_ip, error=str(exc))
            _persist_failed_worker(data, worker_id, hostname, arch, None, cd_record, str(exc))
            raise HTTPException(500, str(exc)) from exc


@router.post("/workers/batch")
def batch_create_workers(req: BatchCreateWorkersRequest, request: Request):
    """批量创建 Worker（逐项独立，幂等重跑）：命名规则 + 数量生成 worker_id（worker-01…），
    macs 与 count 等长时逐项绑定（设备须在池中，不传 = 全部纯空转）。
    已存在 → skipped；设备不可绑定 → failed 且该项不创建（可修正后重试）。不支持 windows_iso。"""
    prefix = req.name_prefix.strip()
    if not prefix:
        raise HTTPException(400, "name_prefix must not be empty")
    digits = max(2, len(str(req.count)))
    canonical_id(f"{prefix}{1:0{digits}d}")  # 命名规则预校验：生成的 worker_id 必须合法
    if req.macs is not None and len(req.macs) != req.count:
        raise HTTPException(400, f"macs length {len(req.macs)} must equal count {req.count}")

    succeeded: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    client_ip = client_host(request)
    record("create_worker.batch", "started", count=req.count, prefix=prefix, client=client_ip)

    with store.locked():
        data = store.load_workers()
        workers = data["workers"]
        for i in range(1, req.count + 1):
            worker_id = f"{prefix}{i:0{digits}d}"
            hostname = worker_id
            mac = canonical_mac(req.macs[i - 1]) if req.macs else None
            created = False
            try:
                if worker_id in workers:
                    skipped.append({"worker_id": worker_id, "reason": "already exists"})
                    continue
                ensure_hostname_not_in_workers(workers, hostname)
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
                record("workers.write", "ok", worker_id=worker_id)
                if mac:
                    bind_result = _bind_device(mac, worker_id, force=False)
                    record("device.bind", "ok", mac=mac, worker_id=worker_id, force=False,
                           old_worker_id=bind_result.get("old_worker_id"),
                           old_device_mac=bind_result.get("old_device_mac"), client=client_ip)
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
                    record("create_worker.batch", "rollback", worker_id=worker_id,
                           error=str(detail), client=client_ip)
                failed.append({
                    "worker_id": worker_id,
                    "hostname": hostname,
                    "mac": mac,
                    "error": str(detail),
                })

    record("create_worker.batch", "ok", created=len(succeeded), skipped=len(skipped),
           failed=len(failed), prefix=prefix, client=client_ip)
    return {"succeeded": succeeded, "skipped": skipped, "failed": failed}


@router.put("/workers/{worker_id}/mac")
def update_worker_mac(worker_id: str, req: UpdateWorkerMacRequest, request: Request):
    """修改 Worker 的 MAC 绑定（hostname 不变）：映射为设备换绑——
    新 MAC 须在设备池中（pooled），绑定新设备；旧设备解绑回池。审计记 device.bind + worker.mac.update（兼容）。"""
    worker_id = canonical_id(worker_id)
    new_mac = canonical_mac(req.mac)

    with store.locked():
        data = store.load_workers()
        record_ = data["workers"].get(worker_id)
        if not record_:
            raise HTTPException(404, f"worker not found: {worker_id}")
        hostname = record_["hostname"]
        client_ip = client_host(request)
        record("worker.mac.update", "started", worker_id=worker_id, client=client_ip)

        old_mac = dnsmasq.find_mac(hostname)
        if old_mac == new_mac:
            record("worker.mac.update", "ok", worker_id=worker_id, hostname=hostname,
                   old_mac=old_mac, new_mac=new_mac, changed=False, client=client_ip)
            return _enrich_worker(worker_id, record_)

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
            record("worker.mac.update", "failed", worker_id=worker_id, client=client_ip, error=str(exc))
            raise HTTPException(409, str(exc)) from exc
        if replaced is None:
            _rollback_devices_binding(new_mac, old_released, worker_id)
            record("worker.mac.update", "failed", worker_id=worker_id, client=client_ip,
                   error=f"no dnsmasq binding for hostname: {hostname}")
            raise HTTPException(409, f"no dnsmasq binding for hostname: {hostname}")
        try:
            dnsmasq_result = dnsmasq.reload()
        except Exception as exc:
            record("worker.mac.update", "failed", worker_id=worker_id, client=client_ip,
                   old_mac=old_mac, new_mac=new_mac, error=f"dnsmasq reload failed: {exc}")
            raise HTTPException(500, f"dnsmasq reload failed: {exc}") from exc

        record("worker.mac.update", "ok", worker_id=worker_id, hostname=hostname,
               old_mac=old_mac, new_mac=new_mac, changed=True, client=client_ip)
        record("dnsmasq.reload", "ok", worker_id=worker_id, result=dnsmasq_result)
        if old_released:
            record("device.unbind", "ok", mac=old_released, worker_id=worker_id,
                   reason="worker.mac.update", client=client_ip)
        record("device.bind", "ok", mac=new_mac, worker_id=worker_id, force=True,
               old_worker_id=worker_id, old_device_mac=old_released, client=client_ip)
        _push_credentials(worker_id)  # 换绑：host NQN 随新设备 UUID 变化，重新推送
        return _enrich_worker(worker_id, record_)


@router.post("/workers/{worker_id}/luns/disk", status_code=201)
def create_worker_disk(worker_id: str, req: CreateWorkerDiskRequest, request: Request):
    """给指定 Worker 创建系统盘 LUN：传 master 走母盘克隆，传 size 建空白盘。
    系统盘按系统分类，一个 Worker 可挂多个系统的盘；同一系统（os）至多一个。"""
    worker_id = canonical_id(worker_id)
    os_name = canonical_os(req.os)
    if os_name not in OS_ITEMS:
        raise HTTPException(400, f"os must be one of {sorted(OS_ITEMS)}: {os_name}")
    validate_disk(req.type, req.name, req.size)

    with store.locked():
        data = store.load_workers()
        record_ = data["workers"].get(worker_id)
        if not record_:
            raise HTTPException(404, f"worker not found: {worker_id}")
        if find_disk_by_os(record_, os_name):
            raise HTTPException(409, f"worker already has a {os_name} system disk: {worker_id}")

        client_ip = client_host(request)
        record("worker.disk.create", "started", worker_id=worker_id, client=client_ip)

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

            # 盘标识权威 = NQN（NVMe-oF 首选）：build_nqn 生成盘 NQN，IQN 由其派生（不参与定义）
            disk_nqn = build_nqn(disk_caps["base_nqn"], worker_id, os_name)
            disk_iqn = nqn_to_iqn(disk_nqn)
            disk_filename = build_disk_filename(worker_id, os_name)
            disk_client = agents.client(disk_agent)
            if req.type == "master":
                disk_result = disk_client.create_disk(disk_iqn, disk_filename, master=req.name)
            else:
                disk_result = disk_client.create_disk(disk_iqn, disk_filename, size=req.size)
            disk_record = {
                "agent": disk_agent.id,
                "nqn": disk_nqn,                              # NVMe-oF 数据面标识（权威）
                "iqn": nqn_to_iqn(disk_nqn),                  # iSCSI 数据面标识（由 NQN 派生）
                "filename": disk_filename,
                "backing": disk_result.get("backing"),
                "os": os_name,
                "source": disk_source(req.type, req.name, req.size),
            }
            record("agent.create_disk", "ok", worker_id=worker_id, agent=disk_agent.id, iqn=disk_record["iqn"])

            add_worker_disk(record_, disk_record)
            if record_.get("state") == "registered":
                record_["state"] = "ready"
            store.save_workers(data)
            record("workers.disk.write", "ok", worker_id=worker_id, iqn=disk_record["iqn"])

            record("worker.disk.create", "succeeded", worker_id=worker_id, client=client_ip)
            _push_credentials(worker_id)  # 新子系统须登记 hosts（worker 有密钥时）
            return _enrich_worker(worker_id, record_)
        except AgentAPIError as exc:
            record("worker.disk.create", "failed", worker_id=worker_id, client=client_ip, error=exc.detail)
            raise HTTPException(exc.status_code, {"agent": exc.agent_id, "error": exc.detail}) from exc
        except Exception as exc:
            record("worker.disk.create", "failed", worker_id=worker_id, client=client_ip, error=str(exc))
            raise HTTPException(500, str(exc)) from exc


@router.post("/workers/luns/disk/batch")
def batch_create_worker_disks(req: BatchCreateWorkerDiskRequest, request: Request):
    """批量给多个 Worker 创建系统盘：每个 target 指定 worker + 存储节点（agent，须已分配）。
    与单盘一致：master 走母盘克隆，empty 建空白盘；同一 os 至多一块，已存在则自动跳过（不算失败）。
    创建成功的 Worker 自动将 default_os 设为本次批量系统（批量部署直接进入默认启动）。
    逐项独立执行，单项失败不影响其余；返回 succeeded / skipped / failed 汇总。"""
    os_name = canonical_os(req.os)
    if os_name not in OS_ITEMS:
        raise HTTPException(400, f"os must be one of {sorted(OS_ITEMS)}: {os_name}")
    validate_disk(req.type, req.name, req.size)
    if not req.targets:
        raise HTTPException(400, "targets must not be empty")

    client_ip = client_host(request)
    succeeded: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    with store.locked():
        data = store.load_workers()
        for target in req.targets:
            worker_id = canonical_id(target.worker_id)
            record_ = data["workers"].get(worker_id)
            if not record_:
                failed.append({"worker_id": worker_id, "error": f"worker not found: {worker_id}"})
                continue
            if find_disk_by_os(record_, os_name):
                skipped.append({"worker_id": worker_id, "reason": f"already has a {os_name} system disk"})
                continue

            record("worker.disk.create", "started", worker_id=worker_id, client=client_ip)
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

                # 盘标识权威 = NQN（NVMe-oF 首选）：build_nqn 生成盘 NQN，IQN 由其派生（不参与定义）
                disk_nqn = build_nqn(disk_caps["base_nqn"], worker_id, os_name)
                disk_iqn = nqn_to_iqn(disk_nqn)
                disk_filename = build_disk_filename(worker_id, os_name)
                disk_client = agents.client(disk_agent)
                if req.type == "master":
                    disk_result = disk_client.create_disk(disk_iqn, disk_filename, master=req.name)
                else:
                    disk_result = disk_client.create_disk(disk_iqn, disk_filename, size=req.size)
                disk_record = {
                    "agent": disk_agent.id,
                    "nqn": disk_nqn,                              # NVMe-oF 数据面标识（权威）
                    "iqn": nqn_to_iqn(disk_nqn),                  # iSCSI 数据面标识（由 NQN 派生）
                    "filename": disk_filename,
                    "backing": disk_result.get("backing"),
                    "os": os_name,
                    "source": disk_source(req.type, req.name, req.size),
                }
                record("agent.create_disk", "ok", worker_id=worker_id, agent=disk_agent.id, iqn=disk_record["iqn"])

                add_worker_disk(record_, disk_record)
                if record_.get("state") == "registered":
                    record_["state"] = "ready"
                # 批量部署约定：创建成功即设为默认启动系统（单盘接口不自动设置）
                record_["default_os"] = os_name
                store.save_workers(data)
                record("workers.disk.write", "ok", worker_id=worker_id, iqn=disk_record["iqn"])
                record(
                    "worker.boot.set",
                    "ok",
                    worker_id=worker_id,
                    client=client_ip,
                    changes=f"default_os:{os_name}",
                )
                record("worker.disk.create", "succeeded", worker_id=worker_id, client=client_ip)
                succeeded.append({"worker_id": worker_id, "agent": disk_agent.id, "iqn": disk_record["iqn"]})
                _push_credentials(worker_id)  # 批量建盘后同步 hosts 登记
            except Exception as exc:
                detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
                if isinstance(detail, dict):
                    detail = detail.get("error") or str(detail)
                record("worker.disk.create", "failed", worker_id=worker_id, client=client_ip, error=str(detail))
                failed.append({"worker_id": worker_id, "agent": target.agent, "error": str(detail)})

    return {"succeeded": succeeded, "skipped": skipped, "failed": failed}


@router.delete("/workers/{worker_id}/luns/disk/{os_name}")
def delete_worker_disk(
    worker_id: str,
    os_name: str,
    request: Request,
    delete_file: bool = Query(False, description="Delete the disk backing .img as well."),
    ignore_missing_target: bool = Query(False, description="Ignore 404 from Agent while deleting the target."),
):
    """删除 Worker 的单个系统盘：可保留或删除 .img 文件；
    被删系统若为默认启动，联动清除 default_os 与同名 menu_default；无盘时状态回退 registered。"""
    worker_id = canonical_id(worker_id)
    os_name = canonical_os(os_name)
    with store.locked():
        data = store.load_workers()
        record_ = data["workers"].get(worker_id)
        if not record_:
            raise HTTPException(404, f"worker not found: {worker_id}")
        disk = find_disk_by_os(record_, os_name)
        if not disk:
            raise HTTPException(404, f"worker {worker_id} has no {os_name} system disk")

        client_ip = client_host(request)
        record("worker.disk.delete", "started", worker_id=worker_id, client=client_ip, os=os_name)

        try:
            _delete_target(disk, delete_file=delete_file, ignore_missing=ignore_missing_target)
            record("agent.delete_disk", "ok", worker_id=worker_id, agent=disk["agent"],
                   iqn=disk["iqn"], delete_file=delete_file)

            disks = record_.get("disks")
            if disks is not None:
                disks[:] = [d for d in disks if d is not disk]
            else:
                record_.pop("disk", None)  # 旧台账单盘字段

            # 联动：被删系统正是默认启动时清除 default_os 与同名 menu_default
            if str(record_.get("default_os", "")).lower() == os_name:
                record_.pop("default_os", None)
            boot = record_.get("boot") or {}
            if str(boot.get("menu_default", "")).lower() == os_name:
                boot.pop("menu_default", None)
                if not boot:
                    record_.pop("boot", None)

            # 无盘时状态回退 registered，等待重新建盘
            if not worker_disks(record_) and record_.get("state") == "ready":
                record_["state"] = "registered"

            store.save_workers(data)
            record("workers.disk.delete", "ok", worker_id=worker_id, os=os_name)
            record("worker.disk.delete", "succeeded", worker_id=worker_id, client=client_ip)
            _push_credentials(worker_id)  # 盘已删：同步移除 Agent 侧 hosts 登记
            return _enrich_worker(worker_id, record_)
        except AgentAPIError as exc:
            record("worker.disk.delete", "failed", worker_id=worker_id, client=client_ip, error=exc.detail)
            raise HTTPException(exc.status_code, {"agent": exc.agent_id, "error": exc.detail}) from exc
        except Exception as exc:
            record("worker.disk.delete", "failed", worker_id=worker_id, client=client_ip, error=str(exc))
            raise HTTPException(500, str(exc)) from exc


@router.put("/workers/{worker_id}/default-os")
def set_worker_default_boot(worker_id: str, req: SetWorkerDefaultBootRequest, request: Request):
    """设置 Worker 默认启动配置：os=默认系统（须与已挂系统盘一致）；
    menu_default/menu_timeout=菜单项覆盖；传 null 清除对应项。
    推导链：default_os > boot.menu_default > exit。"""
    worker_id = canonical_id(worker_id)
    fields = req.model_fields_set
    if not (fields & {"os", "menu_default", "menu_timeout"}):
        raise HTTPException(400, "need at least one of os / menu_default / menu_timeout")

    with store.locked():
        data = store.load_workers()
        record_ = data["workers"].get(worker_id)
        if not record_:
            raise HTTPException(404, f"worker not found: {worker_id}")

        # 先全部校验，再统一应用，保证原子性
        new_default_os: str | None = None
        clear_default_os = False
        if "os" in fields:
            if req.os is None or req.os == "":
                clear_default_os = True
            else:
                os_name = canonical_os(req.os)
                disk = find_disk_by_os(record_, os_name)
                if not disk:
                    existing = ", ".join(d.get("os", "?") for d in worker_disks(record_)) or "none"
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
            record_.pop("default_os", None)
            changes.append("default_os:cleared")
        elif new_default_os:
            record_["default_os"] = new_default_os
            changes.append(f"default_os:{new_default_os}")

        boot = record_.setdefault("boot", {})
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
            record_.pop("boot", None)

        store.save_workers(data)
        record(
            "worker.boot.set",
            "ok",
            worker_id=worker_id,
            client=client_host(request),
            changes=",".join(changes),
        )
        return _enrich_worker(worker_id, record_)


@router.delete("/workers/{worker_id}")
def delete_worker(
    worker_id: str,
    request: Request,
    delete_disk: bool = Query(False, description="Delete the disk backing .img as well."),
    ignore_missing_target: bool = Query(False, description="Ignore 404 from Agent while deleting LUNs."),
):
    worker_id = canonical_id(worker_id)
    with store.locked():
        data = store.load_workers()
        record_ = data["workers"].get(worker_id)
        if not record_:
            raise HTTPException(404, f"worker not found: {worker_id}")

        client_ip = client_host(request)
        record("delete_worker", "started", worker_id=worker_id, client=client_ip, delete_disk=delete_disk)

        # 吊销凭据推送（删盘前）：Agent 移除该 worker 的 hosts 登记并清缓存
        _push_credentials(worker_id, secret=None)

        # 联动解绑设备（设备回池，不吊销）：先解绑落盘，再删 worker（解绑失败则中止删除）
        unbound: list[str] = []
        with devices.locked():
            devs_data = devices.load()
            unbound = _unbind_worker_devices(devs_data, worker_id)
            if unbound:
                devices.save(devs_data)

        try:
            if record_.get("cd"):
                _delete_target(record_["cd"], delete_file=False, ignore_missing=ignore_missing_target)
                record("agent.delete_cd", "ok", worker_id=worker_id, agent=record_["cd"]["agent"], iqn=record_["cd"]["iqn"])
            for disk in worker_disks(record_):
                _delete_target(disk, delete_file=delete_disk, ignore_missing=ignore_missing_target)
                record("agent.delete_disk", "ok", worker_id=worker_id, agent=disk["agent"], iqn=disk["iqn"], delete_file=delete_disk)

            hostname = record_["hostname"]
            del data["workers"][worker_id]
            store.save_workers(data)
            record("workers.delete", "ok", worker_id=worker_id)
            for mac in unbound:
                record("device.unbind", "ok", mac=mac, worker_id=worker_id,
                       reason="worker.delete", client=client_ip)

            removed = dnsmasq.remove_hostname(hostname)
            record("dnsmasq.hosts.delete", "ok", worker_id=worker_id, hostname=hostname, removed=removed)
            dnsmasq_result = dnsmasq.reload()
            record("dnsmasq.reload", "ok", worker_id=worker_id, result=dnsmasq_result)

            record("delete_worker", "succeeded", worker_id=worker_id, client=client_ip)
            return {"deleted": worker_id, "delete_disk": delete_disk, "dnsmasq_removed": removed}
        except AgentAPIError as exc:
            record("delete_worker", "failed", worker_id=worker_id, client=client_ip, error=exc.detail)
            raise HTTPException(exc.status_code, {"agent": exc.agent_id, "error": exc.detail}) from exc
        except Exception as exc:
            record("delete_worker", "failed", worker_id=worker_id, client=client_ip, error=str(exc))
            raise HTTPException(500, str(exc)) from exc


@router.post("/workers/delete/batch")
def batch_delete_workers(req: BatchDeleteWorkersRequest, request: Request):
    """批量删除 Worker：逐项独立执行（单项失败不影响其余），返回 succeeded / failed 汇总。
    每项：删 CD/系统盘 target（delete_disk 控制是否连 .img）、移台账、移除 dnsmasq 绑定；
    全部成功项统一保存台账、统一 reload 一次 dnsmasq。"""
    if not req.worker_ids:
        raise HTTPException(400, "worker_ids must not be empty")

    client_ip = client_host(request)
    succeeded: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    with store.locked():
        data = store.load_workers()
        removed_hostnames: list[str] = []
        unbound_devices: list[str] = []
        for raw_id in req.worker_ids:
            worker_id = canonical_id(raw_id)
            record_ = data["workers"].get(worker_id)
            if not record_:
                failed.append({"worker_id": worker_id, "error": f"worker not found: {worker_id}"})
                continue

            record("delete_worker", "started", worker_id=worker_id, client=client_ip,
                   delete_disk=req.delete_disk)
            # 吊销凭据推送（删盘前）：Agent 移除该 worker 的 hosts 登记并清缓存
            _push_credentials(worker_id, secret=None)
            try:
                if record_.get("cd"):
                    _delete_target(record_["cd"], delete_file=False, ignore_missing=req.ignore_missing_target)
                    record("agent.delete_cd", "ok", worker_id=worker_id,
                           agent=record_["cd"]["agent"], iqn=record_["cd"]["iqn"])
                for disk in worker_disks(record_):
                    _delete_target(disk, delete_file=req.delete_disk, ignore_missing=req.ignore_missing_target)
                    record("agent.delete_disk", "ok", worker_id=worker_id,
                           agent=disk["agent"], iqn=disk["iqn"], delete_file=req.delete_disk)

                hostname = record_["hostname"]
                # 联动解绑设备（设备回池，不吊销）：解绑失败则该 worker 不删除
                with devices.locked():
                    devs_data = devices.load()
                    unbound = _unbind_worker_devices(devs_data, worker_id)
                    if unbound:
                        devices.save(devs_data)
                        unbound_devices.extend(unbound)
                del data["workers"][worker_id]
                record("workers.delete", "ok", worker_id=worker_id)
                for mac in unbound:
                    record("device.unbind", "ok", mac=mac, worker_id=worker_id,
                           reason="worker.delete", client=client_ip)
                removed_hostnames.append(hostname)
                record("delete_worker", "succeeded", worker_id=worker_id, client=client_ip)
                succeeded.append({"worker_id": worker_id, "hostname": hostname})
            except Exception as exc:
                detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
                if isinstance(detail, dict):
                    detail = detail.get("error") or str(detail)
                record("delete_worker", "failed", worker_id=worker_id,
                       client=client_ip, error=str(detail))
                failed.append({"worker_id": worker_id, "error": str(detail)})

        if succeeded:
            store.save_workers(data)
            for hostname in removed_hostnames:
                removed = dnsmasq.remove_hostname(hostname)
                record("dnsmasq.hosts.delete", "ok", hostname=hostname, removed=removed)
            dnsmasq_result = dnsmasq.reload()
            record("dnsmasq.reload", "ok", batch=len(removed_hostnames), result=dnsmasq_result)

    return {"succeeded": succeeded, "failed": failed}


def _delete_target(target_record: dict[str, Any], *, delete_file: bool, ignore_missing: bool) -> None:
    agent = agents.get(target_record["agent"])
    try:
        agents.client(agent).delete_lun(target_record["iqn"], delete_file=delete_file)
    except AgentAPIError as exc:
        if ignore_missing and exc.status_code == 404:
            return
        raise


def _actual_state(record_: dict[str, Any]) -> dict[str, Any]:
    actual: dict[str, Any] = {
        "dnsmasq": {
            "hostname": record_["hostname"],
            "mac": dnsmasq.find_mac(record_["hostname"]),
        }
    }
    actual["disks"] = [_target_actual(d, os=d.get("os")) for d in worker_disks(record_)]
    actual["cd"] = _target_actual(record_.get("cd"))
    return actual


def _target_actual(target_record: dict[str, Any] | None, os: str | None = None) -> dict[str, Any] | None:
    if not target_record:
        return None
    try:
        agent = agents.get(target_record["agent"])
        targets = agents.client(agent).list_luns()
        # 标识集合对比（兼容双数据面）：nvmet 的 target 标识是 NQN，stgt/lio 是 IQN
        record_ids = {target_record["iqn"], target_record.get("nqn")} - {None}
        found = next((t for t in targets if (t.get("nqn") or t.get("iqn")) in record_ids), None)
        return {"os": os, "exists": found is not None, "target": found}
    except Exception as exc:
        return {"os": os, "exists": False, "error": str(exc)}


def _enrich_worker(worker_id: str, record_: dict[str, Any]) -> dict[str, Any]:
    item = copy.deepcopy(record_)
    item["worker_id"] = worker_id
    item["mac"] = dnsmasq.find_mac(item["hostname"])
    bound_device = _bound_device_mac_for(worker_id)
    item["bound_device"] = bound_device
    item["readiness"] = _readiness_for(bound_device, bool(worker_disks(record_)))
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


# ============================ NVMe-oF 凭据（DHHC-1，按 Worker 跟盘） ============================

# Host NQN 前缀与盘 NQN 同域（KURRENT_CP_NQN_BASE，见 config.py；agent 侧同一 base）
HOST_NQN_PREFIX = settings.nqn_base


def _host_nqn_for(worker_id: str) -> str:
    """Host NQN 派生（按 worker_id，发起端身份；与盘 NQN 同域并立，host. 前缀区分角色）。"""
    return f"{HOST_NQN_PREFIX}:host.{worker_id}"


_UNSET = object()


def _push_credentials(worker_id: str, secret: object = _UNSET) -> None:
    """把 worker 的 NVMe-oF 凭据期望状态推送给持有其盘的 Agent（失败仅审计，不阻断主流程）。
    secret 缺省取密钥库当前条目（无条目 → None 吊销推送）；审计不记密钥本体。"""
    data = store.load_workers()
    record_ = data["workers"].get(worker_id)
    if not record_:
        return
    if secret is _UNSET:
        with credentials.locked():
            entry = credentials.load()["credentials"].get(worker_id)
        secret = entry.get("secret") if entry else None
    host_nqns = [_host_nqn_for(worker_id)]
    groups: dict[str, list[str]] = {}
    for disk in worker_disks(record_):
        # NVMe-oF 子系统标识 = NQN（盘记录权威字段）；缺 nqn（存量盘）→ 跳过该盘，
        # 不派生（不兼容遗留）：该盘不支持 NVMe-oF 凭据/引导
        if disk.get("nqn"):
            groups.setdefault(disk["agent"], []).append(disk["nqn"])
    for agent_id, sub_nqns in groups.items():
        agent = agents.get(agent_id)
        try:
            agents.client(agent).set_credential(worker_id, secret, sub_nqns, host_nqns)
            record("credential.push", "ok", worker_id=worker_id, agent=agent_id,
                   injected=bool(secret), sub_count=len(sub_nqns), host_count=len(host_nqns))
        except Exception as exc:
            log.warning(f"credential push failed: worker={worker_id} agent={agent_id}: {exc}")
            record("credential.push", "failed", worker_id=worker_id, agent=agent_id,
                   injected=bool(secret), error=str(exc))


def _validate_dhhc1(secret: str) -> None:
    """DHHC-1 密钥自检（nvmeof-credential-design.md 2.1 契约）：
    前缀、类型两位数字、base64 解码长度 36/68（32/64 字节密钥 + CRC32 小端 4 字节）、CRC 终值。
    非法 → ValueError（配置阶段即失败而非运行时暴露，对齐 nvmet-setup.sh 自检模式）。"""
    if not secret.startswith("DHHC-1:"):
        raise ValueError("secret must start with 'DHHC-1:'")
    rest = secret[len("DHHC-1:"):]
    kind, _, b64 = rest.partition(":")
    if not b64 or len(kind) != 2 or not kind.isdigit():
        raise ValueError("secret type must be two digits (e.g. 01 for SHA-256)")
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception:
        raise ValueError("secret base64 payload is invalid") from None
    if len(raw) not in (36, 68):
        raise ValueError("secret key must be 32 or 64 bytes (36/68 payload incl. CRC32)")
    key, crc = raw[:-4], raw[-4:]
    if zlib.crc32(key) != int.from_bytes(crc, "little"):
        raise ValueError("secret CRC32 checksum mismatch")


def _secret_hash(secret: str) -> str:
    """审计用哈希（不用于注入，注入用明文）：sha256 全量，审计输出仅前缀。"""
    return "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _credential_meta(entry: dict[str, Any]) -> dict[str, Any]:
    """凭据元数据视图：不返回明文；secret_hash 只给前缀便于轮换比对。"""
    return {
        "worker_id": entry["worker_id"],
        "exists": True,
        "secret_hash": str(entry.get("secret_hash", ""))[:15],
        "created_at": entry.get("created_at"),
        "updated_at": entry.get("updated_at"),
    }


@router.put("/workers/{worker_id}/credential")
def set_worker_credential(worker_id: str, req: CredentialRequest, request: Request):
    """设置/更新 NVMe-oF 认证密钥（DHHC-1，按 Worker 跟盘裁定）：密钥库键 = worker_id。
    自检失败 422；worker 不存在 404；重复设置同值幂等（updated_at 不变）。"""
    worker_id = canonical_id(worker_id)
    with store.locked():
        data = store.load_workers()
        if worker_id not in data["workers"]:
            raise HTTPException(404, f"worker not found: {worker_id}")
    secret = req.secret.strip()
    try:
        _validate_dhhc1(secret)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    now = now_iso()
    client_ip = client_host(request)
    with credentials.locked():
        creds = credentials.load()
        entry = creds["credentials"].get(worker_id)
        if entry and entry.get("secret") == secret:
            record("credential.set", "ok", worker_id=worker_id, changed=False, client=client_ip)
            # 幂等重放也触发推送：上次推送失败（agent 不在线/中途失败）时，
            # 重放同值密钥可补推；agent 侧 set_host 幂等，重复推送无害。
            _push_credentials(worker_id, secret=secret)
            return _credential_meta(entry)
        entry = {
            "worker_id": worker_id,
            "secret": secret,
            "secret_hash": _secret_hash(secret),
            "created_at": creds["credentials"].get(worker_id, {}).get("created_at", now),
            "updated_at": now,
        }
        creds["credentials"][worker_id] = entry
        credentials.save(creds)
    record("credential.set", "ok", worker_id=worker_id, changed=True, client=client_ip)
    _push_credentials(worker_id, secret=secret)
    return _credential_meta(entry)


@router.get("/workers/{worker_id}/credential")
def get_worker_credential(worker_id: str, request: Request):
    """凭据元数据（不返回明文）：exists / secret_hash 前缀 / 更新时间。"""
    worker_id = canonical_id(worker_id)
    with store.locked():
        data = store.load_workers()
        if worker_id not in data["workers"]:
            raise HTTPException(404, f"worker not found: {worker_id}")
    with credentials.locked():
        creds = credentials.load()
        entry = creds["credentials"].get(worker_id)
    record("credential.get", "ok", worker_id=worker_id, exists=bool(entry), client=client_host(request))
    if not entry:
        return {"worker_id": worker_id, "exists": False}
    return _credential_meta(entry)


@router.delete("/workers/{worker_id}/credential")
def delete_worker_credential(worker_id: str, request: Request):
    """删除密钥（吊销该 worker 名下全部绑定设备的认证资格）：下次启动回落明文连接。"""
    worker_id = canonical_id(worker_id)
    with store.locked():
        data = store.load_workers()
        if worker_id not in data["workers"]:
            raise HTTPException(404, f"worker not found: {worker_id}")
    with credentials.locked():
        creds = credentials.load()
        if worker_id not in creds["credentials"]:
            raise HTTPException(404, f"credential not found: {worker_id}")
        del creds["credentials"][worker_id]
        credentials.save(creds)
    record("credential.revoke", "ok", worker_id=worker_id, client=client_host(request))
    _push_credentials(worker_id, secret=None)
    return {"worker_id": worker_id, "deleted": True}
