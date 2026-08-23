"""pytest 根配置：路径注入 + 测试状态隔离。

所有 KURRENT_CP_* 文件路径在 import control_plane 之前重定向到临时目录——
config.py 的 Settings() 在模块导入时实例化，环境变量必须在导入前生效。
"""

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# 测试状态目录：每个 pytest 进程一个临时目录，互不污染、退出后由系统清理
_STATE_DIR = Path(tempfile.mkdtemp(prefix="ipxe-cp-test-"))
os.environ["KURRENT_CP_AGENTS_FILE"] = str(_STATE_DIR / "agents.yml")
os.environ["KURRENT_CP_WORKERS_FILE"] = str(_STATE_DIR / "workers.yml")
os.environ["KURRENT_CP_DEVICES_FILE"] = str(_STATE_DIR / "devices.yml")
os.environ["KURRENT_CP_OPERATIONS_FILE"] = str(_STATE_DIR / "operations.jsonl")
os.environ["KURRENT_CP_SETTINGS_FILE"] = str(_STATE_DIR / "settings.json")
os.environ["KURRENT_CP_CERT_DIR"] = str(_STATE_DIR / "certs")
os.environ["KURRENT_CP_CREDENTIALS_FILE"] = str(_STATE_DIR / "credentials.yml")
os.environ["KURRENT_CP_DNSMASQ_HOSTS_FILE"] = str(_STATE_DIR / "dhcp-hosts.conf")
# 测试环境不触达真实 dnsmasq 容器
os.environ["KURRENT_CP_DNSMASQ_RELOAD"] = "false"
# 控制面鉴权 token（测试固定值，与生产环境变量同名覆盖）
os.environ["KURRENT_CP_TOKEN"] = "test-control-token"
