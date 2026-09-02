"""pytest 根配置：路径注入 + 测试状态隔离。

控制面声明式配置写为临时 kurrent.yaml 并经 KURRENT_CONFIG_FILE 指向
（config.py 顶层 import 即加载）；容器内路径常量在 import 后重定向到临时目录——
Settings 属性动态读常量，重定向即生效（不再读 KURRENT_CP_* 业务 env）。
"""

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# 测试状态目录：每个 pytest 进程一个临时目录，互不污染、退出后由系统清理
_STATE_DIR = Path(tempfile.mkdtemp(prefix="ipxe-cp-test-"))

# 控制面声明式配置（测试 spec：networking 必填，其余键走默认值）
_CONF_FILE = _STATE_DIR / "kurrent.yaml"
_CONF_FILE.write_text(
    """apiVersion: kurrent.io/v1
kind: ControlPlaneConfiguration
metadata:
  name: test-cp
spec:
  networking:
    interface: eth-test0
    subnet: 192.168.80.0/24
    dhcpRange: 192.168.80.50,192.168.80.100
    gateway: 192.168.80.2
    dns: 223.5.5.5
  dnsmasq:
    reload: false
""",
    encoding="utf-8",
)
os.environ["KURRENT_CONFIG_FILE"] = str(_CONF_FILE)

import control_plane.app.config as cp_cfg  # noqa: E402
# 容器内路径常量重定向到测试状态目录（Settings 属性动态读常量，无需重建实例）
cp_cfg.DEFAULT_AGENTS_FILE = str(_STATE_DIR / "agents.yml")
cp_cfg.DEFAULT_WORKERS_FILE = str(_STATE_DIR / "workers.yml")
cp_cfg.DEFAULT_DEVICES_FILE = str(_STATE_DIR / "devices.yml")
cp_cfg.DEFAULT_OPERATIONS_FILE = str(_STATE_DIR / "operations.jsonl")
cp_cfg.DEFAULT_SETTINGS_FILE = str(_STATE_DIR / "settings.json")
cp_cfg.DEFAULT_CERT_DIR = str(_STATE_DIR / "certs")
cp_cfg.DEFAULT_CREDENTIALS_FILE = str(_STATE_DIR / "credentials.yml")
cp_cfg.DEFAULT_DNSMASQ_HOSTS_FILE = str(_STATE_DIR / "dhcp-hosts.conf")
cp_cfg.DEFAULT_DNSMASQ_CONF = str(_STATE_DIR / "dnsmasq.conf")
cp_cfg.DEFAULT_PKI_DIR = str(_STATE_DIR / "pki")
cp_cfg.DEFAULT_MASTERS_FILE = str(_STATE_DIR / "masters.yml")
# 测试环境不触达真实 dnsmasq 容器（spec.dnsmasq.reload=false）
# 控制面鉴权 token（测试固定值，与生产环境变量同名覆盖）
os.environ["KURRENT_CP_TOKEN"] = "test-control-token"
