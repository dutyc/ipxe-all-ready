"""控制面组装入口：装配共享存储（stores）、信任根域（trust）与六个资源域路由。

业务逻辑按域拆分到 app/utils.py（纯工具）、app/stores.py（全局单例 + 审计）、
app/auth.py（Bearer 鉴权）、app/trust.py（注册窗口/强制/验签）与 app/routers/ 各资源域。
本模块仅负责：创建 FastAPI 应用、按序挂载路由、启动时执行一次旧数据迁移。
"""

import logging

from fastapi import FastAPI

from . import cert_bootstrap, config
from .routers import agents, boot, devices, operations, settings, workers

log = logging.getLogger("control-plane")

app = FastAPI(title="IPXE-All-Ready Control Plane")

# boot 域最先挂载：/devices/report、/devices/challenge 必须先于 devices 域 /devices/{mac} 匹配
app.include_router(boot.router)
app.include_router(devices.router)
app.include_router(settings.router)
app.include_router(agents.router)
app.include_router(workers.router)
app.include_router(operations.router)

# 启动时执行一次旧数据迁移（幂等；失败仅记日志，不阻断启动）
devices.migrate_legacy_devices()

# 启动时幂等生成 TOFU 引导链服务器证书（失败仅记日志，不阻断启动；轮换 = 删 state/certs/ 重启）
try:
    cert_bootstrap.ensure_server_cert(config.settings.cert_dir, config.settings.cert_san, config.settings.cert_days)
except Exception:
    log.exception("cert: failed to ensure server certificate")
