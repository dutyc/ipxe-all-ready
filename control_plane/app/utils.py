"""通用纯工具：命名规范化、时间、客户端地址、宽松解析、worker 台账纯函数。

不依赖任何业务状态（store/agents/devices/dnsmasq），可被任意模块引用。
"""

import datetime as _dt
import re
from typing import Any

from fastapi import HTTPException, Request

from .dnsmasq import normalize_mac

WORKER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
HOSTNAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
OS_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
HEX_MAC_RE = re.compile(r"^[0-9a-f]{12}$")


def canonical_id(value: str) -> str:
    worker_id = value.strip().lower()
    if not WORKER_ID_RE.match(worker_id):
        raise HTTPException(400, f"invalid worker_id: {value}")
    return worker_id


def canonical_hostname(value: str) -> str:
    hostname = value.strip().lower()
    if not HOSTNAME_RE.match(hostname):
        raise HTTPException(400, f"invalid hostname: {value}")
    return hostname


def canonical_os(value: str) -> str:
    os_name = value.strip().lower()
    if not OS_RE.match(os_name):
        raise HTTPException(400, f"invalid os: {value}")
    return os_name


def canonical_mac(value: str) -> str:
    try:
        return normalize_mac(value)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def normalize_boot_mac(value: str) -> str | None:
    compact = value.strip().lower().replace(":", "").replace("-", "").replace(".", "")
    if not HEX_MAC_RE.match(compact):
        return None
    return ":".join(compact[i:i + 2] for i in range(0, 12, 2))


def client_host(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat()


def clean_str(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def parse_uint(value: str | None) -> int | None:
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


def worker_disks(record: dict[str, Any]) -> list[dict[str, Any]]:
    """读取 Worker 全部系统盘；兼容旧台账单盘字段 `disk`（自动回退）。"""
    disks = record.get("disks")
    if disks is not None:
        return disks
    legacy = record.get("disk")
    return [legacy] if legacy else []


def add_worker_disk(record: dict[str, Any], disk_record: dict[str, Any]) -> None:
    """写入新系统盘；旧台账若仍是单盘字段 `disk`，先并入 `disks` 完成迁移。"""
    disks = record.get("disks")
    if disks is None:
        legacy = record.get("disk")
        disks = [legacy] if legacy else []
        record["disks"] = disks
        record.pop("disk", None)
    disks.append(disk_record)


def find_disk_by_os(record: dict[str, Any], os_name: str) -> dict[str, Any] | None:
    """按系统名查找系统盘（os 不区分大小写）。"""
    os_name = os_name.lower()
    for disk in worker_disks(record):
        if str(disk.get("os", "")).lower() == os_name:
            return disk
    return None


def default_disk_for(record: dict[str, Any]) -> dict[str, Any] | None:
    """默认启动盘：default_os 对应系统盘；未设 default_os 时取第一块盘。"""
    disks = worker_disks(record)
    if not disks:
        return None
    default_os = str(record.get("default_os", "")).lower()
    if default_os:
        for disk in disks:
            if str(disk.get("os", "")).lower() == default_os:
                return disk
    return disks[0]


def ensure_hostname_not_in_workers(workers: dict[str, Any], hostname: str) -> None:
    for worker_id, record in workers.items():
        if record.get("hostname") == hostname:
            raise HTTPException(409, f"hostname already used by worker: {worker_id}")


def build_iqn(base_iqn: str, worker_id: str, suffix: str) -> str:
    return f"{base_iqn.rstrip(':')}:{worker_id}.{suffix}".lower()


def build_nqn(base_nqn: str, worker_id: str, suffix: str) -> str:
    """由节点 NQN 命名空间生成盘 NQN（盘标识权威，NVMe-oF 首选协议）：
    nqn.2026-07.com.kurrent:worker-01.ubuntu。
    IQN 不参与生成——NQN 不能用 IQN 定义，IQN 由盘 NQN 派生（nqn_to_iqn）。"""
    return f"{base_nqn.rstrip(':')}:{worker_id}.{suffix}".lower()


def nqn_to_iqn(nqn: str) -> str:
    """NVMe NQN → iSCSI IQN（同后缀前缀变换，派生方向：NQN 权威，IQN 自动生成）：
    nqn.2026-07.com.kurrent:worker-01.ubuntu → iqn.2026-07.com.kurrent:worker-01.ubuntu。
    iSCSI 数据面（stgt/lio target、iPXE base-iqn 变量）消费 IQN 形态。"""
    nqn = nqn.strip().lower()
    if nqn.startswith("iqn."):
        return nqn
    if nqn.startswith("nqn."):
        return "iqn." + nqn[4:]
    return "iqn." + nqn


def build_disk_filename(worker_id: str, os_name: str) -> str:
    return f"{worker_id}.{os_name}.img".lower()


def validate_disk(kind: str, name: str | None, size: str | None) -> None:
    if kind == "master" and not name:
        raise HTTPException(400, "disk.name is required when disk.type=master")
    if kind == "empty" and not size:
        raise HTTPException(400, "disk.size is required when disk.type=empty")


def disk_source(kind: str, name: str | None, size: str | None) -> dict[str, str]:
    if kind == "master":
        return {"type": kind, "name": name or ""}
    return {"type": kind, "size": size or ""}
