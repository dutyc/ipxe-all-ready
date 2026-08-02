# 更新记录 (CHANGELOG)

本文件记录 ipxe-all-ready 项目的功能变更、接口调整与缺陷修复。

## 记录规范

- 每次代码 / 配置变更完成后，在对应日期区块追加条目（新增 / 变更 / 修复）
- **新增**：新功能、新端点、新配置项
- **变更**：行为调整、接口变更、数据模型调整
- **修复**：缺陷修复
- 涉及多个模块的改动，按模块分条列出；接口变更同时需同步 `control_plane/Control_Plane_API_Docs.md`

---

## 2026-08-01

### 新增

- Control Plane：`POST /workers/{worker_id}/luns/disk` —— 给指定 Worker 创建系统盘 LUN（母盘克隆 / 空白盘），端点位于 `/luns/` 命名空间，为数据盘（`/luns/data`）与多系统盘预留
- Control Plane：`PUT /workers/{worker_id}/default-os` —— 设置 Worker 默认启动配置，三个字段可设可清、可组合（详见下方"变更"）
- Control Plane：`GET/POST/DELETE /agents/{agent_id}/luns` 与 `POST /agents/{agent_id}/luns/scan` —— Agent iSCSI LUN/target 直管（列出 / 创建磁盘 / 创建 CD / 删除 / 扫描）
- Agent：`/lun/scan` 端点与扫描镜像目录重建 target 能力
- 配置文件：`iscsi-server/.env.example` 模板（补齐 `IPXE_*` 变量说明）

### 变更

- **创建 Worker 流程重构为两步（存储与身份分离）**：
  - `POST /workers` 只注册身份（hostname + MAC 绑定），不再接受 `disk` 字段；台账 `os` 字段移除，`state=registered`
  - 系统盘须另调 `POST /workers/{worker_id}/luns/disk` 创建，`os` 改为必填，写入 `disk.os` 台账（决定 IQN 后缀与文件名）；创建后 `state` 转 `ready`
  - 建盘 `os` 严格校验 ∈ `{windows, ubuntu, debian, centos, esxi}`（menu.ipxe 操作系统项）
  - Windows ISO 安装光驱仍随 `POST /workers` 的 `windows_iso` 创建，CD IQN 后缀固定为 `windows.iso`
- **默认启动配置模型**：
  - `PUT /workers/{worker_id}/default-os` 支持 `os`（默认系统，须与已挂系统盘一致）、`menu_default`（严格校验 menu.ipxe 主菜单 item ID）、`menu_timeout`（非负整数）；传 `null` 清除对应项
  - `/boot-vars` 推导链：`default_os` > `boot.menu_default` > `exit`；`boot.menu_default` 登记后随时可改（解决 WebUI 无法操作的问题）
  - 操作日志统一为 `worker.boot.set`（changes 明细）
- 时区处理全链路本地化：
  - `control_plane/app/state.py` 与 `iscsi-server/agent/app/main.py`：日志时间戳由 `datetime.now(timezone.utc)` 改为 `datetime.now().astimezone()`（跟随容器 TZ）
  - 两个 Dockerfile 安装 `tzdata` 并设 `ENV TZ=Asia/Shanghai`；`TZ` 环境变量写入 `control_plane.env`、`.env.example`、`iscsi-server/.env`、`.env.example`，docker-compose 不再写死
  - WebUI `Operations.jsx` 与 nginx njs `file-list.js` 改为本地时间展示
- 文档：`Control_Plane_API_Docs.md` 全面同步（两步创建流程、default-os 端点与合法值表、测试顺序、实现边界）

### 修复

- `DELETE /workers/{worker_id}` 在 Worker 无系统盘（`disk=None`）时不再崩溃（原 `_delete_target(record["disk"])` 会 TypeError）
- 日志时间与宿主机不一致问题（根因：代码写死显式 UTC，`/etc/localtime` 挂载对其无效）

---

## 2026-08-02

### 新增

- Control Plane：**/boot-vars 自动注册（Zero-touch Provisioning）**——新 MAC 请求时自动按顺序分配 hostname（`worker-%02d`，扫描台账 + dhcp 绑定最大序号 +1）、写入台账与 dhcp 绑定并 reload，返回 `menu-default=reboot` 短超时循环重启，等待管理员建盘 + 设置 `default_os` 后自动进入系统；新增环境变量 `IPXE_CP_AUTO_REGISTER`（默认 `true`）与 `IPXE_CP_AUTO_BOOT_TIMEOUT`（默认 `1` 秒）

### 变更

- **/boot-vars 行为调整**：
  - 身份识别改为 hostname 优先（hostname 未命中或未传时退回 MAC 反查）；无系统盘 Worker 不再返回空脚本，`menu_default` 兜底由 `exit` 改为 `reboot`（未配置默认启动时短超时循环重启；`exit` 仅显式设置时返回）
  - 无系统盘时不返回 `base_iqn`/`iscsi_server`（iPXE 沿用 `boot.ipxe.cfg` 静态默认值），`menu_timeout` 在 reboot 循环中固定用 `IPXE_CP_AUTO_BOOT_TIMEOUT`
- **WebUI Agent LUN 直管界面**：
  - Agents 页面卡片可点击，跳转新增 `agents/:id` 页面（`AgentLuns.jsx`）：列出该 Agent 全部 iSCSI LUN（DISK/CD 类型识别、backing、绑定状态），支持直接创建磁盘（母盘克隆 / 空白盘）、创建 CD（ISO）、删除、扫描目录重建 target，不依赖 Worker
  - 删除已绑定 Worker 的 LUN 时，确认框提示绑定关系（“删除后该 Worker 将无法启动”）并可选同时删除 backing 文件；列表中标黄显示“绑定: worker-xx”
- **WebUI 创建 Worker 流程改为两步（与后端对齐）**：
  - Workers 页创建表单只注册身份：worker_id + MAC（必填）+ Windows ISO（可选），不再传已废弃的 `os`/`disk` 字段；hostname 默认取 worker_id（不再单独填写）；列表 OS 列改读 `disk.os`
  - Worker 详情页新增“创建系统盘（第二步）”表单：系统（严格五选：windows/ubuntu/debian/centos/esxi）+ 磁盘类型（空白盘/母盘克隆）+ 大小/母盘名 + 存储节点；无盘 Worker 才显示，创建成功后状态转 `ready` 并刷新详情
- **系统盘模型升级为多盘（`disk` 单字段 → `disks` 数组）**：
  - 一个 Worker 可挂多个系统的系统盘（同一 `os` 至多一个，重复创建返回 `409`）；`POST /workers/{worker_id}/luns/disk` 不再限制单盘，创建表单在 Worker 详情页始终可用
  - 旧台账单盘字段 `disk` 自动迁移并入 `disks`（首次追加新盘时完成），读取全链路兼容
  - `/boot-vars` 选盘：`default_os` 对应的系统盘，未设时取第一块；`GET /workers/{worker_id}/status` 的 `actual.disk` 改为 `actual.disks` 数组（每项含 `os`）；`DELETE /workers/{worker_id}` 删除全部系统盘
  - WebUI：Workers 列表 OS 列显示全部系统（逗号分隔）、详情页展示每块盘卡片（含 os）、Agent LUN 页绑定检测覆盖全部盘
- **WebUI 默认启动配置表单**：Worker 详情页新增“默认启动配置”区块——展示当前 `default_os`/`boot.menu_default`/`boot.menu_timeout`，表单对接 `PUT /workers/{worker_id}/default-os`（os 仅可选已挂载系统盘，menu_default 为 menu.ipxe 主菜单 11 项，均可选“— 清除 —”，menu_timeout 支持“清除超时设置”复选框），保存后刷新台账与 /boot-vars 代码块
- **开发环境**：项目根新增 Python 虚拟环境 `.venv`（安装 control_plane 与 iscsi-server agent 的 requirements），`.gitignore` 增加 `.venv/`、`venv/`、`__pycache__/`、`*.py[cod]`

### 修复

- WebUI 错误提示显示 `[object Object]`：FastAPI 422 的 `detail` 是校验错误数组，`api/client.js` 现在逐条拼接为 `字段: 错误信息` 文本
