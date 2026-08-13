# 控制面能力详解

*控制面（Control Plane）是 `ipxe-all-ready` 的中枢：负责 Worker 生命周期编排、Agent 调度、存储台账、DHCP 绑定与启动变量投影。本文详解其核心能力与设计取舍。*

## 设计原则

- **控制面与数据面分离**：Control Plane 只做调度与台账，Worker 的块存储读写直接走 iSCSI 数据面，不经过控制面。控制面流量体量小，只在开通、注销或启动参数投影时发生。
- **文件即真相（Files as the Source of Truth）**：不引入数据库，`config/agents.yml` 记录 Agent 清单，`state/workers.yml` 记录 Worker 存储台账，`state/settings.json` 记录运行时设置，`dnsmasq/dhcp-hosts.conf` 作为 MAC → hostname 的唯一真相，`operations.jsonl` 记录控制面操作审计轨迹——透明、可 diff、可手工修复。
- **iPXE 静态菜单 + 动态变量注入**：`menu.ipxe` 保持静态交互，`boot.ipxe.cfg` 在启动早期从 Control Plane 拉取 per-worker 变量，解决多 iSCSI 存储节点下的启动参数差异。

## 核心能力

### 零接触自动注册（Zero-touch Provisioning）

新 MAC 首次请求 `/boot-vars` 时，控制面自动按序分配 `worker-xx` 主机名（从 `worker-01` 开始）、写入 Worker 台账与 `dnsmasq` 静态绑定并 HUP 重载，随后返回 `menu-default=reboot` + 短超时（`IPXE_CP_AUTO_BOOT_TIMEOUT`，默认 1 秒）循环重启，等待管理员配置；建盘并设置默认系统后自动进入目标系统。`IPXE_CP_AUTO_REGISTER`（默认开启）是**启动默认值**；部署后可通过 `GET/PUT /settings/auto-register` 运行时切换——状态持久化到 `state/settings.json`（重启保留、优先于环境变量、立即生效），WebUI Workers 页工具栏亦提供开关按钮；关闭后新 MAC 不再自动注册，已注册 Worker 不受影响。

### Worker 生命周期闭环（两步创建与单盘管理）

`POST /workers` 只注册身份（hostname + MAC 绑定），`POST /workers/{worker_id}/luns/disk` 再创建系统盘——自动拼接 IQN、按 `role.disk` 能力选择 disk Agent、创建空白盘或从母盘克隆（btrfs / ZFS≥2.2 reflink 秒级）、写入台账与 `dnsmasq` 绑定并 HUP 重载。系统盘可独立删除：`DELETE /workers/{worker_id}/luns/disk/{os}` 删除单个系统盘 target，`delete_file` 决定是否同时删除 backing `.img` 文件（保留文件可重新挂载）、`ignore_missing_target` 容忍 Agent 侧 target 已缺失；`DELETE /workers/{worker_id}` 注销 Worker 时清理其全部系统盘。

### 一机多系统（disks 数组模型）

一台 Worker 可挂多块系统盘，同一系统至多一块（重复创建返回 409）；`PUT /workers/{worker_id}/default-os` 设置默认启动系统（`default_os`）、菜单默认项（`menu_default`）与菜单超时（`menu_timeout`），推导链为 `default_os > boot.menu_default > reboot`，切换默认系统无需触碰机器。

### MAC 绑定修改（身份在线变更）

`PUT /workers/{worker_id}/mac` 修改 Worker 的 MAC 绑定（hostname 不变）：校验新 MAC 格式与占用（已被其他 hostname 绑定返回 409），截断写 `dhcp-hosts.conf` 保持文件 inode 不变并 HUP 重载，重载立即可见；审计记录 `worker.mac.update`（含 `old_mac` / `new_mac` / `changed` / `client`）即 MAC 修改历史，`GET /operations` 可查；新 MAC 与旧值相同时返回 `changed=false` 且不触发重载。WebUI Worker 详情页「身份」卡片提供修改入口。

### 批量部署

`POST /workers/luns/disk/batch` 批量给多个 Worker 创建系统盘：请求体逐项指定存储节点，与单盘一致同一 `os` 至多一块、已存在自动跳过（不算失败）；逐项独立执行、单项失败不影响其余，返回 `succeeded` / `skipped` / `failed` 汇总；创建成功的 Worker 自动将 `default_os` 设为本次批量系统，批量上线直通系统。`POST /workers/delete/batch` 批量删除 Worker：逐项独立执行，成功项统一保存台账、统一一次 dnsmasq reload（优于逐删逐 reload）。WebUI Workers 页提供批量创建 / 批量删除两种模式：行勾选（Shift 点击范围选择）、左侧参数侧边栏、右侧节点侧边栏（拖拽指定单节点、勾选参与均摊、接管所选 Worker）。

### per-worker 启动变量动态注入

在保留 iPXE 静态菜单交互的前提下，`/boot-vars` 端点按 MAC/hostname 查询 inventory，动态返回 `base-iqn`、`iscsi-server`、`iscsi-sep`、`menu-default`、`menu-timeout` 等变量；其中 `iscsi-sep` 是 iSCSI root 的**连接符**（`${iscsi-server}` 与 `${base-iqn}` 之间的分隔字段），按系统盘所在 Agent 的后端类型生成（stgt `:::1:` / LIO `::::`），root-path 拼装（`iscsi:${iscsi-server}${iscsi-sep}${base-iqn}:${hostname}.<os>`）由 `menu.ipxe` 静态完成，仅差异连接符由后端投影；未配置默认启动时返回 `reboot` 短超时循环。`boot.ipxe.cfg` 只在末尾拉取变量，并用 `isset` 守卫重算 `iscsi-sep` 兜底值（不覆盖已下发的 LIO 格式）。

### Agent 直管与在线编辑

- **注册 / 探测 / 编辑**：`POST /agents/probe` 两步探测（调 `/healthz` + `/capabilities` 自动推导 `role` / `tags` / `iscsi_server`，预览不写文件），`POST /agents` 注册（重复 id 返回 409），`PUT /agents/{agent_id}` 在线编辑（id 不可改、token 留空保持原值）；`enabled=false` 停用后不再参与建盘 / 挂载调度与存活探测。
- **LUN 直管**：`GET/POST/DELETE /agents/{id}/luns`、`POST /agents/{id}/luns/scan` 直接管理 iSCSI 存储节点上的 target（列 LUN / 创建磁盘 / 创建 CD / 删除 / 扫描镜像目录重建），不依赖 Worker 台账；配合 `role.disk / role.cd` 角色模型，后端能力不足的操作在 API 与 WebUI 两侧同时被拒绝 / 置灰（如 LIO 不支持 ISO 光驱）。
- **母盘清单**：`GET /masters` 聚合全部启用磁盘角色 Agent 的母盘清单（Agent 侧后台线程每 30 秒扫描镜像目录、识别 `_tpl_` 标记并缓存；单台失败不阻塞整体），WebUI 克隆时以下拉选择母盘，无需手工输入文件名。

### 分布式调度模型

Control Plane 只发 HTTP，每台 iSCSI Server 上的 API Agent 接收并操作本地 iSCSI 服务端，控制面与数据面分离。新增/删除 Worker 已从手工修改配置收敛为 `POST /workers`、`POST /workers/luns/disk/batch` 与 `DELETE /workers/{worker_id}` 这类稳定契约；建盘按 Agent 的 `role.disk` 能力与 `enabled` 状态筛选候选存储节点。

### 异构后端设计

stgt 与 LIO 双后端均已接入 Agent，LIO 服务端已容器化；后端差异（含角色能力）封装在 Agent 内，Control Plane 不感知。存储节点以镜像目录中的文件为**唯一真相**，启动时自动扫描目录、重建 iSCSI 配置，治愈了 stgt 配置易失的顽疾。

### 存储性能

母盘到工作盘的克隆在 btrfs 与 ZFS（OpenZFS ≥ 2.2，母盘与克隆盘须在同一数据集）上均以文件级 reflink（FICLONE）秒级完成，实测数据块共享、零额外磁盘占用；ZFS 版本过低或跨数据集、以及 xfs/ext4 等无 reflink 支持的场景自动回退全量拷贝（克隆时间随母盘大小线性增长）。Agent `/capabilities` 上报 `fs_type`（存储目录文件系统类型）供 UI 区分展示。

## Web 管理界面

基于 React + Vite 构建的极简黑白工业风 SPA（中英双语），集成 Control Plane 全部管理能力。

- **Dashboard**：Worker / Agent 集群水位总览，最近操作日志摘要。
- **Workers 管理**：列表查看、筛选过滤、两步创建（注册身份 → 创建系统盘：空白盘 / 母盘克隆，系统五选一：Windows / Ubuntu / Debian / CentOS / ESXi）、批量创建 / 批量删除模式（行勾选 + Shift 范围选择、左侧参数栏、右侧节点拖拽 / 均摊 / 接管）、多系统盘展示、工具栏自动注册开关。
- **Worker 详情**：多系统盘卡片（每盘独立删除，可勾选同时删除 `.img` 与忽略缺失 target）、实时状态探测（dnsmasq 绑定、disk/cd target 存在性）、身份卡片 MAC 在线修改、默认启动配置表单（`default_os` / `menu_default` / `menu_timeout`）、启动变量投影（/boot-vars 代码块展示）、安全删除（二次确认，可选删除 `.img` 磁盘文件）。
- **Agents 监控与直管**：自适应网格卡片布局，展示后端类型、能力（磁盘/光驱角色）、健康状态与文件系统类型，支持 Live 探测开关；「+ 添加 Agent」两步探测注册（自动推导角色 / 标签 / 数据面地址，探测后可在预览区修改，能力标签只读），卡片「编辑」按钮（遮罩弹层，Token 留空保持原值、可勾选停用）；点击卡片进入 Agent LUN 直管页，可直接创建磁盘（母盘下拉选择）、创建 CD（按角色置灰并提示）、删除、扫描目录重建 target。
- **操作日志**：审计流水增量加载，时间戳 + 操作类型 + 状态标记 + 关联 Worker（含 `worker.mac.update` 等身份变更历史）。
- **技术栈**：React 18 + React Router 6 (HashRouter) + 纯 CSS 变量驱动主题，零第三方 UI 库依赖。
- **部署**：Vite 构建为纯静态文件，由 nginx 容器统一分发；API 代理通过 nginx 转发至 Control Plane，无需额外运行时。

## 文件浏览器

集成于同一 nginx 容器，通过 njs 脚本提供 JSON 目录列表 API，展示 `public/` 目录下的 iPXE 引导文件（ISO、kernel、initrd）。

- 文件下载端点 `/file/` 专供 iPXE `chain` / `initrd` 指令使用，404 响应为纯文本绝不返回 HTML 页面。
- Web UI 与文件浏览器共享同一 nginx 容器（:4838），无额外进程开销。
