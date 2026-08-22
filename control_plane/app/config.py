import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# 注册窗口 TTL 硬上限（分钟）：代码层不可配置为永久（2026-08-21 裁定：注册只在窗口期）
REGISTRATION_WINDOW_TTL_MAX_MINUTES = 60
REGISTRATION_WINDOW_TTL_MIN_MINUTES = 1
# 挑战 nonce 短 TTL（秒）：防重放，引导期无可靠时钟不能依赖时间戳
CHALLENGE_NONCE_TTL_SECONDS = 60


@dataclass(frozen=True)
class Settings:
    agents_file: Path = Path(os.getenv("IPXE_CP_AGENTS_FILE", "config/agents.yml"))
    workers_file: Path = Path(os.getenv("IPXE_CP_WORKERS_FILE", "state/workers.yml"))
    devices_file: Path = Path(os.getenv("IPXE_CP_DEVICES_FILE", "state/devices.yml"))
    operations_file: Path = Path(os.getenv("IPXE_CP_OPERATIONS_FILE", "state/operations.jsonl"))
    settings_file: Path = Path(os.getenv("IPXE_CP_SETTINGS_FILE", "state/settings.json"))
    dnsmasq_hosts_file: Path = Path(os.getenv("IPXE_CP_DNSMASQ_HOSTS_FILE", "dnsmasq/dhcp-hosts.conf"))
    dnsmasq_container: str = os.getenv("IPXE_CP_DNSMASQ_CONTAINER", "ipxe-dnsmasq")
    dnsmasq_reload: bool = _bool_env("IPXE_CP_DNSMASQ_RELOAD", True)
    default_arch: str = os.getenv("IPXE_CP_DEFAULT_ARCH", "x86_64")
    boot_menu_timeout: int = int(os.getenv("IPXE_CP_BOOT_MENU_TIMEOUT", "5000"))
    auto_boot_timeout: int = int(os.getenv("IPXE_CP_AUTO_BOOT_TIMEOUT", "1"))
    agent_timeout: float = float(os.getenv("IPXE_CP_AGENT_TIMEOUT", "10"))
    control_token: str = os.getenv("IPXE_CP_TOKEN", "")
    # TOFU 引导链服务器证书（自签，控制面启动时幂等生成；nginx 只读挂载 state/certs）
    cert_dir: Path = Path(os.getenv("IPXE_CP_CERT_DIR", "state/certs"))
    cert_san: str = os.getenv("IPXE_CP_CERT_SAN", "IP:127.0.0.1,DNS:localhost")
    cert_days: int = int(os.getenv("IPXE_CP_CERT_DAYS", "3650"))
    # NVMe-oF 认证凭据库（DHHC-1 密钥按 worker_id 索引，按 Worker 跟盘裁定 2026-08-22）
    credentials_file: Path = Path(os.getenv("IPXE_CP_CREDENTIALS_FILE", "state/credentials.yml"))


settings = Settings()
