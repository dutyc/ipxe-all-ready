"""引导链端点（不鉴权）：healthz / boot-vars / devices/report / devices/challenge 及注入投影逻辑。"""

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from ..config import settings
from ..stores import agents, credentials, devices, dnsmasq, record, store
from ..trust import (
    device_auth_blocked,
    device_for_boot,
    issue_nonce,
    parse_pubkey,
    sha256_hex,
    window_open,
)
from ..utils import (
    canonical_hostname,
    clean_str,
    client_host,
    default_disk_for,
    normalize_boot_mac,
    now_iso,
    parse_uint,
)

router = APIRouter()


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/boot-vars")
def boot_vars(
    mac: str | None = None,
    hostname: str | None = None,
    nonce: str | None = None,
    sig: str | None = None,
    output_format: str = Query("ipxe", alias="format"),
):
    if output_format not in {"ipxe", "json"}:
        raise HTTPException(400, "format must be ipxe or json")
    payload = _boot_vars_payload(mac=mac, hostname=hostname, nonce=nonce, sig=sig)
    if output_format == "json":
        return JSONResponse(_boot_vars_json(payload))
    return Response(_boot_vars_ipxe(payload), media_type="text/plain")


@router.get("/devices/report")
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
    pubkey: str | None = Query(None),
):
    """iPXE 设备信息上报（不鉴权）：11 字段指纹 + 可带 pubkey（ECDSA P-256 公钥，注册/认领用），
    宽松解析（空值容忍，mem 兼容 0x hex/十进制），更新指纹 + last_seen。
    注册只在窗口期（2026-08-21 裁定）：未知 MAC 仅在窗口开启且带有效公钥时入池；
    存量设备窗口期内带公钥上报 = 密钥认领（key_hash 填充）。返回空响应（chain 无脚本副作用）。"""
    normalized = normalize_boot_mac(mac)
    if not normalized:
        return Response(status_code=200)  # 非法 MAC 忽略，不阻断引导
    fingerprint = {k: v for k, v in {
        "manufacturer": clean_str(manufacturer),
        "product": clean_str(product),
        "serial": clean_str(serial),
        "cpumodel": clean_str(cpumodel),
        "mem_total": parse_uint(mem_total),
        "mem_type": clean_str(mem_type),
        "mem_speed": parse_uint(mem_speed),
        "chip": clean_str(chip),
        "busid": clean_str(busid),
    }.items() if v is not None}
    now = now_iso()
    key_hex = parse_pubkey(pubkey)  # 合法 → 规范化 hex；无参数/非法 → None
    window_open_ = window_open()
    updated = False
    claimed = False
    with devices.locked():
        data = devices.load()
        devs = data["devices"]
        existing = devs.get(normalized)
        if existing:
            if existing.get("state") == "revoked":
                return Response(status_code=200)  # 吊销设备不更新、不复活
            existing.setdefault("fingerprint", {}).update(fingerprint)
            clean_uuid = clean_str(uuid)
            if clean_uuid:
                existing["uuid"] = clean_uuid
            existing["last_seen"] = now
            if window_open_ and key_hex:
                old_key = existing.get("key_hash")
                if old_key:
                    if old_key != key_hex:
                        # 密钥不一致：拒绝覆盖（吊销/重注册走删登记流程），仅审计
                        record("device.claim", "rejected", mac=normalized, reason="key_mismatch")
                else:
                    existing["key_hash"] = key_hex
                    existing["pubkey_hash"] = sha256_hex(bytes.fromhex(key_hex))
                    claimed = True
            devices.save(data)
            updated = True
        else:
            if not (window_open_ and key_hex):
                return Response(status_code=200)  # 注册只在窗口期且须带有效公钥
            devs[normalized] = {
                "mac": normalized,
                "uuid": clean_str(uuid),
                "state": "pooled",
                "bound_worker_id": None,
                "key_hash": key_hex,
                "pubkey_hash": sha256_hex(bytes.fromhex(key_hex)),
                "source": "ipxe",
                "fingerprint": fingerprint,
                "first_seen": now,
                "last_seen": now,
            }
            devices.save(data)
            updated = False
    if updated:
        record("device.report", "ok", mac=normalized, client=client_host(request), updated=True)
        if claimed:
            record("device.claim", "ok", mac=normalized)
    else:
        record("device.register", "ok", mac=normalized, source="ipxe", client=client_host(request))
    return Response(status_code=200)


@router.get("/devices/challenge")
def device_challenge(mac: str):
    """挑战端点（不鉴权）：一次性 nonce，短 TTL、绑定 mac。nonce 本身无秘密，仅防重放。
    设备不存在/未认领 → 404（无法走验签链路）。
    响应 #!ipxe 脚本体 set nonce <64hex>（iPXE chain 直接消费为 ${nonce}）。"""
    normalized = normalize_boot_mac(mac)
    if not normalized:
        raise HTTPException(400, "invalid mac")
    device = device_for_boot(normalized)
    if not device or not device.get("key_hash"):
        raise HTTPException(404, "device not registered or not claimed")
    nonce = issue_nonce(normalized)
    return Response(f"#!ipxe\nset nonce {nonce}\n", media_type="text/plain")


def _boot_vars_payload(
    mac: str | None,
    hostname: str | None,
    nonce: str | None = None,
    sig: str | None = None,
) -> dict[str, Any]:
    """启动变量投影。识别链：hostname→worker；mac→设备→绑定 worker。
    防冒领（D2）：带 mac 的请求须来自该 worker 绑定的设备（绑定即认证），不符 → 拒绝下发空脚本。
    注入四条件第 4 条（2026-08-21）：设备身份签名验证——强制开关开启后，无 key_hash / 无签名 /
    验签失败一律拒绝（已绑定也不放行）；过渡期无密钥设备照现状放行（防冒领）。
    注册语义：注册只在窗口期（走 /devices/report），boot-vars 无写副作用、无注册通道。"""
    match = _find_worker_for_boot(mac=mac, hostname=hostname)
    if match:
        if _boot_binding_ok(match[0], mac):
            if device_auth_blocked(mac, hostname, nonce, sig, match[0]):
                return {}  # 第 4 条不通过 → 拒绝下发
            payload = _worker_boot_payload(match)
            # NVMe-oF 凭据注入审计（C2，不记密钥本体，只记 injected 布尔）
            record("boot_vars.credential", "ok", mac=mac or "", hostname=hostname or "",
                   worker_id=match[0], injected=bool(payload.get("nbft_secret")))
            return payload
        return {}  # 冒领/未绑定设备请求 → 拒绝下发
    device = device_for_boot(mac)
    if device:
        # 池中未绑定：reboot 循环等待绑定；吊销/异常态：空脚本（绑定设备必然命中 dnsmasq → worker）
        if device.get("state") == "pooled":
            return _reboot_boot_payload()
        return {}
    return {}  # 未注册：无注册通道（注册只在窗口期，走 report）


def _worker_boot_payload(match: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    """按已识别 worker 投影启动变量（原 _boot_vars_payload 识别后主体）。"""
    worker_id, record_ = match
    disk = default_disk_for(record_)
    agent_id = disk.get("agent") if disk else None
    boot = record_.get("boot") or {}
    menu_default = _menu_default_for(record_)
    if menu_default == "reboot":
        # 未配置默认启动：短超时快速重启，等待管理员建盘/设默认系统
        menu_timeout = settings.auto_boot_timeout
    else:
        menu_timeout = boot.get("menu_timeout") or boot.get("menu-timeout") or settings.boot_menu_timeout
    payload: dict[str, Any] = {
        "worker_id": worker_id,
        "hostname": record_["hostname"],
        "menu_default": str(menu_default),
        "menu_timeout": int(menu_timeout),
    }
    if agent_id:
        # base-nqn 投影（C3 拼接起步）：来源 = 盘 NQN 前缀（盘 NQN 由 Agent 按统一模板
        # base:worker_id.os 生成，无存量盘、无历史命名，固件按模板重拼 = 盘记录权威值）；
        # 盘记录缺 nqn → 不下发该键，固件不拼 NVMe-oF 路径（不兼容遗留，不派生）
        nqn = disk.get("nqn")
        base_nqn = _base_nqn_from_target(nqn)
        # base-iqn 投影保持 iSCSI 形态（安装器 iSCSI 引导消费）：来源 = 盘 IQN（由盘 NQN 派生）前缀
        base_iqn = _base_iqn_from_target(disk.get("iqn"))
        try:
            storager_ip = agents.storager_ip_for(agent_id)
        except Exception:
            return {}
        backend = _backend_for(agent_id)
        # 只投影 iSCSI root 连接符（差异点），root-path 拼装由 iPXE 侧完成：
        # stgt 需 `:::1:`（lun 占位 1），LIO 需 `::::`（空占位）
        payload["base_nqn"] = base_nqn
        payload["base_iqn"] = base_iqn
        payload["storager_ip"] = storager_ip
        payload["iscsi_sep"] = ":::1:" if backend == "stgt" else "::::"
    # NVMe-oF 认证密钥注入（C2，按 Worker 跟盘裁定）：绑定 worker 在密钥库有条目时注入。
    # 固件侧消费：menu 拼 nvme://...?secret=${nbft-secret}（C3 已启用，secret 条件化拼装）；
    # 无条目 → 不注入，固件走明文连接（兼容未启用认证的 target）。
    secret = _credential_secret_for(worker_id)
    if secret:
        payload["nbft_secret"] = secret
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


def _boot_vars_ipxe(payload: dict[str, Any]) -> str:
    lines = ["#!ipxe"]
    if not payload:
        lines.append("# no per-worker boot vars found")
        return "\n".join(lines) + "\n"
    # reboot 循环 payload(池中未绑定)无 worker_id,统一用 unbound 标识
    lines.append(f"# boot vars for {payload.get('worker_id', 'unbound')}")
    if payload.get("base_nqn"):
        lines.append(f"set base-nqn {payload['base_nqn']}")
    if payload.get("base_iqn"):
        lines.append(f"set base-iqn {payload['base_iqn']}")
    if payload.get("storager_ip"):
        lines.append(f"set storager-ip {payload['storager_ip']}")
    if payload.get("iscsi_sep"):
        lines.append(f"set iscsi-sep {payload['iscsi_sep']}")
    if payload.get("nbft_secret"):
        lines.append(f"set nbft-secret {payload['nbft_secret']}")
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
    if payload.get("base_nqn"):
        result["base_nqn"] = payload["base_nqn"]
    if payload.get("base_iqn"):
        result["base_iqn"] = payload["base_iqn"]
    if payload.get("storager_ip"):
        result["storager_ip"] = payload["storager_ip"]
    if payload.get("iscsi_sep"):
        result["iscsi_sep"] = payload["iscsi_sep"]
    if payload.get("nbft_secret"):
        result["nbft_secret"] = payload["nbft_secret"]
    return result


def _base_iqn_from_target(iqn: str | None) -> str:
    if iqn and ":" in iqn:
        return iqn.rsplit(":", 1)[0]
    return "iqn.2026-07.com.controller"


def _base_nqn_from_target(nqn: str | None) -> str | None:
    """盘 NQN 的命名空间前缀（C3 拼接）：`nqn.2026-07.com.kurrent:worker-01.ubuntu` → 前缀。
    盘 NQN 由 Agent 按统一模板 `base:worker_id.os` 生成（无存量盘），前缀重拼 = 盘记录权威值；
    盘记录缺 nqn → 返回 None（不投影该键，固件不拼 NVMe-oF 路径）。"""
    if nqn and ":" in nqn:
        return nqn.rsplit(":", 1)[0]
    return None


def _credential_secret_for(worker_id: str) -> str | None:
    """按 Worker 跟盘：返回该 worker 的 DHHC-1 密钥（无条目 → None，不注入）。"""
    with credentials.locked():
        creds = credentials.load()
        entry = creds["credentials"].get(worker_id)
    return entry.get("secret") if entry else None


def _find_worker_for_boot(mac: str | None, hostname: str | None) -> tuple[str, dict[str, Any]] | None:
    """身份识别：有 hostname 用 hostname，无 hostname 退回 MAC 反查。"""
    data = store.load_workers()
    workers = data["workers"]
    if hostname:
        try:
            found = _find_worker_by_hostname(workers, canonical_hostname(hostname))
            if found:
                return found
        except HTTPException:
            pass
    normalized_mac = normalize_boot_mac(mac) if mac else None
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
    for worker_id, record_ in workers.items():
        if record_.get("hostname") == hostname:
            return worker_id, record_
    return None


def _menu_default_for(record_: dict[str, Any]) -> str:
    """默认启动项：default_os（建盘后单独设置）> boot.menu_default（显式配置）> reboot（未配置时循环重启等待）。"""
    default_os = str(record_.get("default_os", "")).lower()
    if default_os:
        return default_os
    boot = record_.get("boot") or {}
    menu_default = boot.get("menu_default") or boot.get("menu-default")
    if menu_default:
        return str(menu_default).lower()
    return "reboot"


def _boot_binding_ok(worker_id: str, mac: str | None) -> bool:
    """防冒领（D2）：带 mac 的启动请求须来自该 worker 绑定的设备（绑定即认证）；
    未带 mac（仅 hostname）无法校验身份，保持兼容放行。"""
    if not mac:
        return True
    device = device_for_boot(mac)
    return bool(device and device.get("state") == "bound" and device.get("bound_worker_id") == worker_id)
