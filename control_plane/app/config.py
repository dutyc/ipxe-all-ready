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

# ── 组件 PKI（K8S 同构：内部 CA + bootstrap token 引导 + 证书轮换，2026-08-31）──
# bootstrap token 短 TTL：仅引导期一次性使用（格式 <6位>.<16位>，只存 sha256 hash）
BOOTSTRAP_TOKEN_TTL_DAYS = 7
# 组件证书短 TTL：90 天，验证轮换链路（CA 10 年）
COMPONENT_CERT_DAYS = 90
# 轮换触发阈值：剩余生命周期低于该比例时重新签发
RENEW_THRESHOLD = 0.2
# nginx mTLS 校验通过后透传的客户端证书 DN 头（renew 用）
CLIENT_CERT_DN_HEADER = "x-client-cert-dn"


@dataclass(frozen=True)
class Settings:
    agents_file: Path = Path(os.getenv("KURRENT_CP_AGENTS_FILE", "config/agents.yml"))
    workers_file: Path = Path(os.getenv("KURRENT_CP_WORKERS_FILE", "state/workers.yml"))
    devices_file: Path = Path(os.getenv("KURRENT_CP_DEVICES_FILE", "state/devices.yml"))
    operations_file: Path = Path(os.getenv("KURRENT_CP_OPERATIONS_FILE", "state/operations.jsonl"))
    settings_file: Path = Path(os.getenv("KURRENT_CP_SETTINGS_FILE", "state/settings.json"))
    dnsmasq_hosts_file: Path = Path(os.getenv("KURRENT_CP_DNSMASQ_HOSTS_FILE", "dnsmasq/dhcp-hosts.conf"))
    dnsmasq_container: str = os.getenv("KURRENT_CP_DNSMASQ_CONTAINER", "kurrent-dnsmasq")
    dnsmasq_reload: bool = _bool_env("KURRENT_CP_DNSMASQ_RELOAD", True)
    default_arch: str = os.getenv("KURRENT_CP_DEFAULT_ARCH", "x86_64")
    boot_menu_timeout: int = int(os.getenv("KURRENT_CP_BOOT_MENU_TIMEOUT", "5000"))
    auto_boot_timeout: int = int(os.getenv("KURRENT_CP_AUTO_BOOT_TIMEOUT", "1"))
    agent_timeout: float = float(os.getenv("KURRENT_CP_AGENT_TIMEOUT", "10"))
    control_token: str = os.getenv("KURRENT_CP_TOKEN", "")
    # TOFU 引导链服务器证书（自签，控制面启动时幂等生成；nginx 只读挂载 state/certs）
    cert_dir: Path = Path(os.getenv("KURRENT_CP_CERT_DIR", "state/certs"))
    cert_san: str = os.getenv("KURRENT_CP_CERT_SAN", "IP:127.0.0.1,DNS:localhost")
    cert_days: int = int(os.getenv("KURRENT_CP_CERT_DAYS", "3650"))
    # NVMe-oF 认证凭据库（DHHC-1 密钥按 worker_id 索引，按 Worker 跟盘裁定 2026-08-22）
    credentials_file: Path = Path(os.getenv("KURRENT_CP_CREDENTIALS_FILE", "state/credentials.yml"))
    # 组件 PKI 根目录（内部 CA + 组件证书 + bootstrap token 登记，2026-08-31）
    pki_dir: Path = Path(os.getenv("KURRENT_CP_PKI_DIR", "state/pki"))
    # 控制面自身 client cert 别名（cp→agent 的 mTLS 客户端身份，CN=control-plane）
    control_plane_component: str = os.getenv("KURRENT_CP_COMPONENT", "control-plane")
    # 母盘标签台账（2026-08-30 裁定：标签 = 控制面登记，备注性质，未来迁 masters 表）
    masters_file: Path = Path(os.getenv("KURRENT_CP_MASTERS_FILE", "state/masters.yml"))
    # NQN 命名空间 base（与 agent/storager 的 KURRENT_NQN_BASE 同源；盘 NQN 与
    # host NQN 都由它派生，变更须两侧同步）
    nqn_base: str = os.getenv("KURRENT_CP_NQN_BASE", "nqn.2026-07.com.kurrent")


settings = Settings()
