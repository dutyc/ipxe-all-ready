"""信任根域（T3/T4，2026-08-21）：注册窗口、强制验签开关、挑战 nonce、设备公钥/签名验证。

被 boot（引导链验签）与 settings（窗口/开关管理端点）两个域共用，独立成域。
契约见 blueprint/ipxe-stateless-handoff.md（§5.2 变量与接口契约）。
"""

import base64
import datetime as _dt
import hashlib
import re
import secrets
import threading
import time
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, EllipticCurvePublicKey

from .config import CHALLENGE_NONCE_TTL_SECONDS
from .stores import devices, record, runtime_settings
from .utils import normalize_boot_mac

# 挑战 nonce 存储：进程内存（单容器单进程），绑定 mac、短 TTL、一次性（取出即删）
_nonce_store: dict[str, dict[str, Any]] = {}
_nonce_lock = threading.Lock()


def device_for_boot(mac: str | None) -> dict[str, Any] | None:
    """boot-vars 请求的 MAC 反查设备台账。"""
    normalized = normalize_boot_mac(mac) if mac else None
    if not normalized:
        return None
    data = devices.load()
    return data["devices"].get(normalized)


def window_record() -> dict[str, Any] | None:
    """注册窗口记录（settings.json registration_window）：无/非法 → None。"""
    rec = runtime_settings.get("registration_window")
    if not isinstance(rec, dict) or not rec.get("opened_at") or not rec.get("ttl_minutes"):
        return None
    return rec


def window_open() -> bool:
    """窗口开启判定：有记录且未过期（TTL 到期自动关闭，懒计算）。"""
    rec = window_record()
    if not rec:
        return False
    try:
        closes = _dt.datetime.fromisoformat(rec["opened_at"]) + _dt.timedelta(minutes=int(rec["ttl_minutes"]))
    except (ValueError, TypeError):
        return False
    return _dt.datetime.now().astimezone() < closes


def window_status() -> dict[str, Any]:
    """窗口状态投影（管理端点用）。"""
    rec = window_record()
    if not rec:
        return {"open": False, "opened_at": None, "ttl_minutes": None, "closes_at": None, "remaining_seconds": 0}
    try:
        opened = _dt.datetime.fromisoformat(rec["opened_at"])
        closes = opened + _dt.timedelta(minutes=int(rec["ttl_minutes"]))
    except (ValueError, TypeError):
        return {"open": False, "opened_at": None, "ttl_minutes": None, "closes_at": None, "remaining_seconds": 0}
    remaining = max(0, int((closes - _dt.datetime.now().astimezone()).total_seconds()))
    return {
        "open": remaining > 0,
        "opened_at": rec["opened_at"],
        "ttl_minutes": int(rec["ttl_minutes"]),
        "closes_at": closes.isoformat(),
        "remaining_seconds": remaining,
    }


def enforcement_enabled() -> bool:
    """设备身份验签强制开关（显式开关，2026-08-21 裁定）：开启后无密钥设备拒绝引导。"""
    return bool(runtime_settings.get("enforce_device_auth", False))


def issue_nonce(mac: str) -> str:
    """签发一次性 nonce（32B，64 hex），绑定 mac、短 TTL；懒清理过期项。"""
    nonce = secrets.token_hex(32)
    with _nonce_lock:
        now = time.time()
        expired = [m for m, e in _nonce_store.items() if now > e["expires"]]
        for m in expired:
            del _nonce_store[m]
        _nonce_store[mac] = {"nonce": nonce, "expires": now + CHALLENGE_NONCE_TTL_SECONDS}
    return nonce


def consume_nonce(mac: str, nonce: str) -> bool:
    """消费 nonce（一次性：取出即删，无论成败）；不存在/不匹配/过期 → False。"""
    with _nonce_lock:
        entry = _nonce_store.get(mac)
        if not entry:
            return False
        del _nonce_store[mac]
        if entry["nonce"] != nonce:
            return False
        return time.time() <= entry["expires"]


def parse_pubkey(value: str | None) -> str | None:
    """校验 ECDSA P-256 公钥（未压缩点 0x04||X||Y，65B，130 hex 字符；契约见 ipxe-stateless-handoff §5.2）。
    合法 → 规范化 hex；无参数/非法 → None（注册/认领拒绝，不阻断上报）。"""
    if not value:
        return None
    compact = value.strip().lower()
    if len(compact) != 130 or not re.fullmatch(r"[0-9a-f]{130}", compact):
        return None
    try:
        EllipticCurvePublicKey.from_encoded_point(SECP256R1(), bytes.fromhex(compact))
    except Exception:
        return None
    return compact


def verify_device_signature(mac: str, hostname: str, nonce: str, sig_b64: str, pubkey_hex: str) -> bool:
    """ECDSA P-256 验签：签名数据 = nonce||mac||hostname（UTF-8 字节拼接，契约见 ipxe-stateless-handoff §5.2）；
    签名 = base64(DER)；公钥 = 未压缩点 hex（key_hash）。任何异常 → False。"""
    try:
        pub = EllipticCurvePublicKey.from_encoded_point(SECP256R1(), bytes.fromhex(pubkey_hex))
        data = f"{nonce}{mac}{hostname}".encode("utf-8")
        pub.verify(base64.b64decode(sig_b64), data, ec.ECDSA(hashes.SHA256()))
        return True
    except Exception:
        return False


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def device_auth_blocked(
    mac: str | None,
    hostname: str | None,
    nonce: str | None,
    sig: str | None,
    worker_id: str,
) -> bool:
    """注入四条件第 4 条：设备身份签名验证（挑战-响应，trust-root-blueprint §6.1）。
    True = 拒绝下发。无 mac 无法验证身份（hostname 识别链），维持现状放行。
    无 key_hash：强制开启 → 拒绝（不降级，已绑定也不放行）；过渡期 → 放行现状防冒领。
    带 nonce+sig：重放/验签失败 → 拒绝（过渡期同样拒绝，伪造签名不放行）。"""
    normalized = normalize_boot_mac(mac) if mac else None
    if not normalized:
        return False
    device = device_for_boot(normalized)
    key_hash = device.get("key_hash") if device else None
    if not key_hash:
        if enforcement_enabled():
            record("boot_vars.credential", "rejected", mac=normalized, worker_id=worker_id, reason="no_key")
            return True
        return False
    if not nonce or not sig:
        if enforcement_enabled():
            record("boot_vars.credential", "rejected", mac=normalized, worker_id=worker_id, reason="missing_sig")
            return True
        return False
    hostname_clean = hostname.strip().lower() if hostname else ""
    if not hostname_clean:
        record("boot_vars.credential", "rejected", mac=normalized, worker_id=worker_id, reason="missing_hostname")
        return True
    if not consume_nonce(normalized, nonce):
        record("boot_vars.credential", "rejected", mac=normalized, worker_id=worker_id, reason="nonce_invalid")
        return True
    if not verify_device_signature(normalized, hostname_clean, nonce, sig, key_hash):
        record("boot_vars.credential", "rejected", mac=normalized, worker_id=worker_id, reason="verify_failed")
        return True
    return False
