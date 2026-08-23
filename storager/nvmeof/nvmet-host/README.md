# nvmet-host：NVMe-oF 宿主管理服务（容器形态）

存储节点上的 nvmet（内核 configfs）管理服务。2026-08-22 裁定：**内核 nvmet 宿主原生**（数据面不走容器化），
**管理进程容器化**（由 `storager/nvmeof/docker-compose.yml` 托管——独立编排，Agent 服务内嵌，不手动跑 Python）。Agent 通过 HTTP 调用本服务完成子系统/认证管理。
盘文件管理仍归 Agent（与 stgt/LIO 一致）。

## 职责边界

| 层 | 组件 | 职责 |
|---|---|---|
| 内核 | 宿主 `nvmet` / `nvmet-tcp` 模块 | 数据面 target（NVMe/TCP，默认 4420） |
| 容器 | 本组件（`kurrent-nvmet-host` 容器） | configfs 操作：subsystem/namespace/port/hosts(nvme-auth-dhchap-secret) |
| 存储节点 | Agent（4840） | 盘文件管理（克隆/扫描）、后端调度、凭据推送转调本服务 |
| 控制面 | control-plane（4839） | 凭据库（按 Worker）、/boot-vars 注入、绑定关系权威 |

## 部署步骤

```bash
# 1. 内核模块 + configfs（宿主，唯一宿主步骤；重启后需重新加载或写入 /etc/modules-load.d）
modprobe nvmet
modprobe nvmet-tcp
mount -t configfs configfs /sys/kernel/config

# 2. 配置 storager/.env（从 .env.example 复制后修改）
#    KURRENT_BACKEND=nvmet
#    KURRENT_NVMET_HOST_URL=http://nvmet-host:4841   # compose 内部网络，Agent 专用
#    KURRENT_NVMET_HOST_TOKEN=<随机长串>              # compose 插值注入容器 NVMET_HOST_TOKEN

# 3. 构建并启动（Agent 服务内嵌本编排）
cd storager/nvmeof
docker compose --env-file ../.env up -d --build

# 4. 验证（宿主 loopback 映射）
curl http://127.0.0.1:4841/healthz
# → {"status":"ok","configfs":true}
```

> 容器无 privileged：configfs bind mount 后容器内 root 写操作是普通文件写 + symlink 创建，无需特权。
> 端口映射仅绑 `127.0.0.1:4841`（本机可验证），局域网不可达；Agent 走内部网络 `http://nvmet-host:4841`。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `NVMET_HOST_TOKEN` | 必填 | Bearer token（compose 从 `.env` 的 `KURRENT_NVMET_HOST_TOKEN` 插值注入；Agent 侧同值） |
| `NVMET_HOST_ADDR` | `127.0.0.1` | 监听地址；compose 已注入 `0.0.0.0`（容器内），对外仅 loopback 映射 |
| `NVMET_HOST_PORT` | `4841` | 监听端口 |
| `NVMET_CONFIGFS` | `/sys/kernel/config/nvmet` | configfs 根（测试可注入） |
| `NVMET_PORT_ID` | `1` | NVMe/TCP 端口 ID |

## API（全部 Bearer 鉴权，Agent 是唯一调用方）

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/healthz` | 探活（唯一不鉴权），`configfs` 字段报告就绪态 |
| `GET` | `/capabilities` | 后端能力（backend=nvmet、cd=false、端口 4420） |
| `POST` | `/port?trsvcid=4420` | 幂等确保 NVMe/TCP 端口 |
| `GET` | `/subsystems` | 子系统清单（含 namespaces/hosts） |
| `POST` | `/subsystems` | `{nqn, backing}` 创建子系统 + namespace/1（严格模式 allow_any_host=0）+ 挂端口 |
| `DELETE` | `/subsystems/{nqn}` | 删除（自动摘端口挂载） |
| `PUT` | `/subsystems/{nqn}/hosts` | `{hostnqn, secret}` 登记/更新 host 认证（DHHC-1 → nvme-auth-dhchap-secret + control 置位启用） |
| `DELETE` | `/subsystems/{nqn}/hosts/{hostnqn}` | 移除 host 认证 |

## 认证模型（按 Worker 跟盘，2026-08-22 裁定）

- 子系统 = 盘（NQN = 盘 IQN 同后缀派生：`iqn.2026-07.com.kurrent:worker-01.ubuntu` → `nqn.2026-07.com.kurrent:worker-01.ubuntu`，格式 `<base_nqn>:worker-XX.os`），`attr_allow_any_host=0`（严格）
- 连接认证 = DH-HMAC-CHAP（target 认证 host）：客户端 Host NQN（worker 维度派生 `nqn.2026-07.com.kurrent:host.<worker_id>`）
  须在 `hosts/<hostnqn>/` 有对应条目：`nvme-auth-dhchap-secret` = 该 worker 的 DHHC-1 密钥
  （`DHHC-1:01:<base64>` 明文，无换行），`nvme-auth-dhchap-control` = 1 启用认证（不置位则不校验）
- `allowed_hosts/` 为内核在 `attr_allow_any_host=1` 时自动维护的连接记录目录，严格模式下用户侧不操作
- hosts 矩阵随绑定关系同步：控制面在凭据设置/设备换绑时推送 Agent，Agent 转调本服务
- 无 UUID 回退：Host NQN 恒为 worker 派生（`nqn.2026-07.com.kurrent:host.<worker_id>`），每 worker 单条目

## 安全边界

- 端口映射仅绑宿主 loopback（127.0.0.1:4841）+ Bearer token（`hmac.compare_digest` 常量时间比对）
- configfs 操作需要 root（容器以 root 运行，bind mount 直写宿主内核配置面）；盘文件不经本服务
- 审计：Agent 侧 operations 记录凭据推送结果；本服务不落盘任何状态（configfs 即真相）
