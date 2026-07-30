import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    agents_file: Path = Path(os.getenv("IPXE_CP_AGENTS_FILE", "config/agents.yml"))
    workers_file: Path = Path(os.getenv("IPXE_CP_WORKERS_FILE", "state/workers.yml"))
    operations_file: Path = Path(os.getenv("IPXE_CP_OPERATIONS_FILE", "state/operations.jsonl"))
    dnsmasq_hosts_file: Path = Path(os.getenv("IPXE_CP_DNSMASQ_HOSTS_FILE", "dnsmasq/dhcp-hosts.conf"))
    dnsmasq_container: str = os.getenv("IPXE_CP_DNSMASQ_CONTAINER", "ipxe-dnsmasq")
    dnsmasq_reload: bool = _bool_env("IPXE_CP_DNSMASQ_RELOAD", True)
    default_arch: str = os.getenv("IPXE_CP_DEFAULT_ARCH", "x86_64")
    boot_menu_timeout: int = int(os.getenv("IPXE_CP_BOOT_MENU_TIMEOUT", "5000"))
    agent_timeout: float = float(os.getenv("IPXE_CP_AGENT_TIMEOUT", "10"))
    control_token: str = os.getenv("IPXE_CP_TOKEN", "")


settings = Settings()
