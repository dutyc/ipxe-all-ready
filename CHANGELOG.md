# 更新记录 (CHANGELOG)

本文件记录 ipxe-all-ready 项目的功能变更、接口调整与缺陷修复。

## 记录规范

- 每次代码 / 配置变更完成后，在对应日期区块追加条目（新增 / 变更 / 修复）
- **新增**：新功能、新端点、新配置项
- **变更**：行为调整、接口变更、数据模型调整
- **修复**：缺陷修复
- 涉及多个模块的改动，按模块分条列出；接口变更同时需同步 `docs/zh/guide/api/control-plane-api.md`（控制面 API 参考，文档站唯一权威）

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

- Control Plane：**/boot-vars 自动注册（Zero-touch Provisioning）**——新 MAC 请求时自动按顺序分配 hostname（`worker-%02d`，扫描台账 + dhcp 绑定最大序号 +1）、写入台账与 dhcp 绑定并 reload，返回 `menu-default=reboot` 短超时循环重启，等待管理员建盘 + 设置 `default_os` 后自动进入系统；新增环境变量 `IPXE_CP_AUTO_REGISTER`（默认 `true`）与 `IPXE_CP_AUTO_BOOT_TIMEOUT`（默认 `1`，单位毫秒）

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
- **文档站首页定制（中英双语）**：新增 `docs/.vitepress/theme/`（`index.js` 引入 `custom.css`）——整体黑白极简配色（浅色模式近黑 `#18181b`、深色模式近白 `#f4f4f5`，按钮文字反色适配），hero 大字等宽字体纯黑白（无渐变无动画），hero 背景仅留极淡网格，副标语中性灰；**首页内容由 6 个 feature 卡片改为朴素列表**（无圆点、细分隔线），中英文内容对齐当前版本（零接触自动注册 / 一机多系统 / 中心控制面 + Web UI / 秒级启动 / 拒绝黑盒 / 100% 纯开源工具链）
- **文档：新增《Windows 无盘快速部署（母盘克隆）》快速部署栏目**——`docs/zh/guide/windows-quick-deploy.md` 全流程（Controller 双编排部署 → 存储节点 Agent 部署 → 母盘制备/上传 → WebUI 秒级克隆 → 默认启动），文档站侧边栏新增「快速部署」分组；定位与环境部署文档与原理向实战文档区分
- **文档：文档站重构为「原理探索」+「快速部署专题」双专栏**——侧边栏新增「原理探索」分组（前言与第一～三章归入，记录 iPXE 无盘技术原理）、原「快速部署」分组更名「快速部署专题」，导航「实战指南」更名「原理探索」；新增《第四章：Debian 系 iBFT 无盘启动——母盘克隆的优雅解法》（`docs/zh/guide/debian-12-ibft.md`）：iBFT 六环链路（sanboot 写表 → ISCSI_IBFT_FIND 发现 → iscsi_ibft 导出 sysfs → initramfs ISCSI_AUTO → iscsistart -b 登录 → root=UUID 挂根）、内核配置与 open-iscsi 源码证据（hook 只拷 iscsistart/initiatorname.iscsi/iscsi.initramfs、node.startup 与 iBFT 无关）、母盘四步构建配方与 initrd 三件套验证、0x7f22208e 踩坑（固件可移动介质契约需 ESP 的 BOOTX64.EFI）、Debian 系通用性论证
- **文档：《Windows 无盘快速部署》新增 4.3 节「真实硬件制备母盘（备选路径）」**——目标硬件含专有驱动（特殊网卡 / RAID / HBA）时可在同型号真实机器上安装一次即得母盘；盘转换三种方式（disk2vhd + qemu-img / 拔盘 dd / Live 环境 dd）；驱动真实匹配、克隆零驱动问题，命名与克隆契约与虚拟机母盘完全一致
- **文档：新增《Debian 无盘快速部署（母盘克隆）》快速部署专题第二篇**——`docs/zh/guide/debian-quick-deploy.md` 全流程（环境准备与 Windows 篇共用清单 → 母盘制备（UEFI+GPT 前提 / 虚拟机与真实硬件双路径 / 四步配方 / BOOTX64.EFI / initrd 三件套验证 / 转换命名）→ 上传 → 自动注册 → WebUI 克隆（IQN `worker-xx.debian`）→ 默认启动 → 验收 iBFT）；FAQ 覆盖 0x7f22208e、VFS 根挂载失败、root=UUID 疑虑；侧边栏「快速部署专题」追加条目
- **文档：第四章《Debian 系 iBFT 无盘启动》新增 4.5 节「真实硬件制备（备选路径）」**——真实硬件安装后应用四步配方即得母盘，dd 全盘转换，契约与虚拟机母盘一致；原 4.5/4.6 顺延为 4.6/4.7
- **文档：中文文档站目录按专题分文件夹**——`docs/zh/guide/` 下新建 `exploration/`（原理探索：第一～四章）与 `quick-deploy/`（快速部署专题：Windows/Debian 两篇），前言保留根目录；`docs/.vitepress/config.mts` 侧边栏与 `docs/zh/index.md` 首页链接全部更新；README.zh-CN.md / README.md 文档站链接同步更新（zh README 同时收录第四章与快速部署两篇）
- **文档：环境部署独立成篇，快速部署两篇收窄为母盘专题**——新增《项目环境部署》（`docs/zh/guide/quick-deploy/environment-deploy.md`）：部署拓扑与 Controller / 存储节点部署（原 Windows 篇第 1~3 步）平台无关化，附部署核对清单与两篇母盘入口；Windows 篇删除环境部署部分、步骤重编号（原第 4~9 步 → 第 1~6 步，4.1~4.3 → 1.1~1.3）；Debian 篇环境准备清单改为指向新文；侧边栏「快速部署专题」置顶新篇，README.zh-CN.md 快速部署列表同步
- **文档：《Debian 无盘快速部署》更名《Debian 系无盘快速部署（母盘克隆）》**——正文同步覆盖 Debian 系发行版：1.1 安装小节与 1.2 真实硬件路径补充 Ubuntu 20.04/22.04/24.04，1.4 补充 Ubuntu 安装器源路径 `\EFI\ubuntu\`，1.6 命名表新增 Ubuntu 示例（`_tpl_ubuntu_24.04.img`，克隆时 OS 选 `Ubuntu`、IQN 后缀 `.ubuntu`）；侧边栏、README.zh-CN.md、环境部署篇引用同步（URL 保持不变）
- **文档：《Debian 系无盘快速部署》新增「支持范围」小节**——基于官方包库与内核配置查证：open-iscsi 在 Debian 11~13 与 Ubuntu 22.04/24.04/26.04 全系存在且自带完整 initramfs 集成（hooks/iscsi + local-top/iscsi，支持 `iscsi_auto`）；内核 `CONFIG_ISCSI_IBFT=m` 强制开启 `CONFIG_ISCSI_IBFT_FIND=y`（kernelconfig.io）；Ubuntu 的 `iscsi_ibft`/`iscsi_tcp`/`ib_iser` 模块位于基础 `linux-modules` 包（noble `generic.inclusion-list` 证实，最小安装自带，无需 linux-modules-extra）；矩阵标注 Debian 12 已实测、其余为同链路机制支持，并排除已 EOL 的 Debian 10 / Ubuntu 20.04
- **文档：英文文档站结构与中文站对齐**——侧边栏改为双专栏（Exploration：Foreword + Ch1~Ch4；Quick Deploy：Environment Setup + Windows/Debian-family Master Image），导航新增「Quick Deploy」；新增 5 个英文占位页（Ch3 `docs/guide/debian-12.md`、Ch4 `docs/guide/debian-12-ibft.md`、快速部署 3 篇 `docs/guide/quick-deploy/*.md`），每页含内容骨架与中文版链接（标注 translation in progress）；英文首页 hero 主按钮改为 Quick Deploy（与中文对齐）；README.md 文档章节补全为双专栏 7 条并改用英文站链接
- **文档：README.zh-CN.md 重构 + 路线图独立成文件**——新增 `ROADMAP.md`（路线图 Phase 1~4 + 近期规划，其中 CLI/reconcile/一键部署脚本从 README「控制面推进中」迁入）；README.zh-CN.md 重组为清晰分层（简介 → 架构总览（角色 + 设计原则 + 流量，合并原「项目总览」与「架构定义」）→ 核心能力 → 控制面能力详解（原「当前进展」拆出，消除与核心能力重复）→ 快速开始 → 官方文档 → 项目结构（补 ROADMAP.md）→ 攻坚记录 → 路线图（改为链接）→ 参与贡献 → License → 成长轨迹）；英文 README.md 保留其英文版 Roadmap 不动

### 修复

- WebUI 错误提示显示 `[object Object]`：FastAPI 422 的 `detail` 是校验错误数组，`api/client.js` 现在逐条拼接为 `字段: 错误信息` 文本
- **Agent LUN 直管页面按后端角色禁用创建按钮**：LIO 后端（`role.cd: false`）的“创建光驱 (ISO)”按钮置灰不可点，并显示提示“LIO 后端不支持 ISO 光驱”（hover 亦有 title）；同理 `role.disk: false` 时禁用“创建磁盘”；表单渲染双保险（无 role 配置的旧数据默认放行）；后端 `POST /agents/{id}/luns/cd` 与 `/luns/disk` 同步新增角色校验（400 拒绝，不再透传到 Agent）
- **Agent LUN 页白屏修复**：上一版将 `agent.role` 角色计算放在组件首次渲染（`agent` 为 null）即执行，导致 `TypeError: Cannot read properties of null (reading 'role')`，React 整树卸载白屏（API 请求都来不及发出）；现改为在 `if (!agent) return` 空态分支之后计算，并顺带修复 `Button` 组件不透传 `title` 等剩余属性（hover 提示此前未生效）
- **Zero-touch 自动注册不生效（worker 拿不到 hostname、不重启）**：根因是 `tftp/boot.ipxe.cfg` 的 `set controller_ip 192.168.1.5` 仍是模板默认值，与实际网段（192.168.80.x）不符——iPXE 请求 `http://${controller_ip}:4839/boot-vars` 不可达后 `|| goto vars-done` 静默跳过，后端从未收到请求（台账/dhcp 绑定始终为空），`menu-default` 由 menu.ipxe 兜底为 `exit`、`menu-timeout` 兜底为 0，菜单不自动选择也不重启；已改为 `set controller_ip ${next-server}`（同机部署下 next-server 即 DHCP 服务器 IP，与 dnsmasq 网段、agents.yml `iscsi_server` 一致，零硬编码，换 IP 无需改脚本），并清理了排查期间用假 MAC 触发自动注册产生的测试 worker（worker-00 及 dhcp 绑定，需重启 dnsmasq 容器彻底清除内存态）
  - **mac 传参由 `${mac:hexraw}` 改为 `${mac}`**：真实 iPXE 设备实测 `${mac:hexraw}` 修饰符展开异常（mac 参数为空导致后端不识别），带冒号格式 `${mac}` 一切正常；后端 `_normalize_boot_mac` 会剥离冒号/横线/点号归一化，两种格式均可识别
  - **自动注册编号从 `worker-01` 开始**：`_next_auto_hostname` 初始序号由 -1 改为 0（原逻辑第一个分配 `worker-00`），并将已注册的 worker-00 无缝改名为 worker-01（台账 + dhcp 绑定已同步，重启 dnsmasq 生效）
- **README.zh-CN.md 全面更新**：项目结构对齐当前代码（移除已删除的 `iscsi-target-gen.sh`，补齐 `CHANGELOG.md`、`assets/`、`iscsi-server/.env`、`webui/deploy/nginx/njs`、`docs/.vitepress` 等）；新增“核心能力”章节（零接触注册 / 一机多系统 / 中心控制面 + Web UI / 秒级启动 / 拒绝黑盒 / 纯开源）；功能介绍对齐当前实现（Zero-touch 自动注册、两步创建 + 多系统盘、默认启动配置、Agent LUN 直管与角色模型、WebUI 两步流程与 LUN 直管页）；Roadmap 勾选已完成的中心控制面与 Controller 容器化；文档章节补充第三章 Debian 12；移除表情符号；License 链接修正
- **Control_Plane_API_Docs.md 同步更新**：`/boot-vars` 的 iPXE 接入代码块与推荐传参改为 `${mac}`（注明 hexraw 修饰符在部分固件展开异常、chain 失败静默兜底与派生变量重建）；自动注册编号示例改为 `worker-01` 起；`IPXE_CP_AUTO_BOOT_TIMEOUT` 单位明确为毫秒；示例 IP 由模板值 192.168.1.5 改为实际网段 192.168.80.3；Agent LUN 直管补充 `role.disk`/`role.cd` 角色校验（400）；实现边界将多系统盘移入已支持列表

---

## 2026-08-03

### 新增

- Control Plane：`DELETE /workers/{worker_id}/luns/disk/{os}` —— 删除 Worker 的单个系统盘（iSCSI target）：`delete_file` 参数控制是否同时删除 backing `.img` 文件（`false` 仅删 target、文件保留可重新挂载），`ignore_missing_target` 在 Agent 侧 target 已不存在时忽略 404 继续完成台账清理；操作日志新增 `worker.disk.delete`（started/succeeded/failed）
- WebUI：Worker 详情页「系统盘」每张磁盘卡片新增**删除系统盘**按钮——ConfirmAction 确认弹窗（可勾选「同时删除 .img 磁盘文件」与「忽略已不存在的 Target」），删除中按钮禁用并显示「删除中...」，成功后自动刷新台账与启动变量
- Control Plane：`/boot-vars` 新增 `iscsi_sep` 字段——iSCSI root **连接符**（`${iscsi-server}` 与 `${base-iqn}` 之间的分隔字段），**按系统盘所在 Agent 的后端类型生成**：stgt 后端为 `:::1:`（lun 占位 1），LIO 后端为 `::::`（空占位，解决 LIO 后端 iSCSI 连接参数不兼容问题）；只投影差异连接符本身，root-path 拼装（`iscsi:${iscsi-server}${iscsi-sep}${base-iqn}:${hostname}.<os>`）由 iPXE 侧静态完成；后端类型优先读 `agents.yml` 该 Agent 的 `tags`（含 `lio`/`stgt` 标记，离线零成本），未标记时查询 Agent `/capabilities` 的 `backend` 字段（Agent 自报），查询失败默认 stgt 格式兼容

### 变更

- **文档：README 全面入口式重构（对齐 Docker/K8S 风格），控制面详解与攻坚记录迁入文档站**——README.md / README.zh-CN.md 精简为入口式结构（定位 → 架构三角色 → 核心能力 6 条 → 快速开始（clone + compose up + 端口）→ 官方文档链接 → 路线图（指向 ROADMAP.md）→ 参与贡献 → License → Star History），删除原「控制面能力详解」「我们已经攻克的壁垒」「详细项目结构」全文；文档站新增《控制面能力详解》（中英：设计原则 + 核心能力 8 项 + WebUI 能力 + 文件浏览器）与《我们已经攻克的壁垒》（中英：Linux 引导链 / Ubuntu / Windows 分组 9 条），VitePress 侧边栏注册（中英 Exploration 分组）；参与贡献章节新增 AI 辅助开发态度声明（不反对 AI 生成代码——项目本身由 Qwen/Codex/DeepSeek 协同完成，但贡献者必须自行理解整体架构：控制面/数据面分离、iPXE 引导链、动态变量传递链、文件即真相、iSCSI 会话保活；无法清晰阐述设计逻辑的 PR 拒绝合并，鼓励先提 Issue/Idea）
- **文档：`Control_Plane_API_Docs.md` 同步系统盘删除接口**——接口概览表新增 `DELETE /workers/{worker_id}/luns/disk/{os}` 条目，新增 7.4 章节（参数说明 + 保留 .img / 同时删除 .img 两个 curl 示例）
- **iPXE 脚本使用 `${iscsi-sep}` 变量**：`menu.ipxe` 全部系统项与安装项的 root-path 改为 `iscsi:${iscsi-server}${iscsi-sep}${base-iqn}:${hostname}.<os>`（原 `base-iscsi` 移除）；`boot.ipxe.cfg` 兜底值改为 `set iscsi-sep :::1:` + chain 后 `isset ${iscsi-sep} || ...` 守卫（不覆盖 `/boot-vars` 已下发的 LIO 格式）；WebUI `buildBootVarsCode` 展示 `set iscsi-sep`；API 文档 5 章节（字段来源表 + iPXE/JSON 示例 + 接入方式）与文档站控制面详解/Windows/Debian 文档同步更新

---

## 2026-08-03

### 新增

- Control Plane：`POST /workers/luns/disk/batch` — 批量给多个 Worker 创建系统盘（母盘克隆 / 空白盘），请求体 `targets` 逐项指定 `{worker_id, agent}` 存储节点分配（须已分配，不存在默认公共分配）；与单盘一致同一 `os` 至多一块、已存在自动跳过（不算失败）；逐项独立执行，单项失败不影响其余，返回 `succeeded` / `skipped` / `failed` 汇总；**创建成功的 Worker 自动将 `default_os` 设为本次批量系统**（批量部署直接进入默认启动，无需再调 `PUT /workers/{id}/default-os`；单盘接口不自动设置，审计记录 `worker.boot.set`）
- WebUI Workers 页新增「批量创建系统盘」模式：
  - 仅批量模式下每行出现勾选框，已拥有系统盘的 Worker 行标浅黄提醒（可正常勾选，重复 `os` 由后端自动跳过）；点击勾选单个，Shift+点击标定终点、中间自动勾选（范围选择基于当前筛选结果顺序）
  - 左侧常驻侧边栏（悬浮于视口左侧、不挤占原列表宽度）：已选 Worker 计数 + 批量系统盘参数（系统 / 空白盘或母盘克隆 / 大小或母盘名，**不含存储节点**）+「开始批量创建」按钮与结果汇总（成功 / 跳过 / 失败明细）
  - 右侧常驻侧边栏（悬浮于视口右侧、不挤占原列表宽度）：列出全部存储节点（role=disk），每个节点一个可拖拽标签框，内含「参与均摊」勾选 +「接管所选 Worker」按钮（已选 Worker 统一改派给该节点，覆盖之前单独指定）与已分配计数；节点列表底部新增「均摊分配所选 Worker」——勾选 ≥2 个节点后，已选 Worker 按参与节点轮流平均分配（覆盖之前分配）；拖动节点标签放到某行 = 该 Worker 单独指定该存储节点；行的「存储节点」列展示分配结果并可单独取消分配

### 变更

- 文档：`Control_Plane_API_Docs.md` 接口概览表新增批量创建条目，新增 7.1.3 章节（请求体字段表 + curl + 返回示例）

---

## 2026-08-03

### 新增

- **首个发行版（v0.1.0）发布准备 — 环境配置与注释收尾**：
  - `iscsi-server/.env` 与 `control_plane/config/agents.yml`（含真实部署 token）解除 git 跟踪并加入 `.gitignore`，仓库只保留 `*.example` 模板
  - 新增 `webui/app/.env.example`（VITE_CP_TOKEN 构建期变量说明）
  - `control_plane.env(.example)` / `iscsi-server/.env(.example)` 补齐分组注释（文件路径、dnsmasq 联动、启动行为、Token 同步说明）
  - `control_plane/config/agents.yml.example` 补齐字段注释（base_url / iscsi_server / token 占位 / role / tags / enabled）
  - 根 `docker-compose.yml`：各服务补齐职责注释，移除无人引用的误导性 `networks.ipxe` 段；`iscsi-server/docker-compose.yml` 补齐后端与 Agent 注释、清理行尾空格
  - `iscsi-server/agent/Dockerfile` 移除开发期对话遗留注释，改为规范说明
  - README（中英）快速开始补全配置步骤：`cp *.env.example` 准备流程、API 鉴权 Token 同步、存储节点独立部署指引
  - 文档收敛：删除冗余的 `iscsi-server/Agent_API_Docs.md`，保留更全面的 `API_Reference.md`（补入 Token 常量时间比对细节）
- Control Plane：`POST /workers/delete/batch` — 批量删除 Worker（请求体 `worker_ids` + `delete_disk` / `ignore_missing_target`）：每项独立执行（单项失败不影响其余，不存在的计入 failed），返回 `succeeded`/`failed` 汇总；成功项统一保存台账、统一 reload 一次 dnsmasq（优于逐删逐 reload）；审计逐项 `delete_worker`
- WebUI Workers 页新增独立「批量删除 Worker」模式（与批量创建互斥）：工具栏独立按钮进入/退出，勾选后左侧栏确认删除（含「同时删除 .img」/「忽略缺失 target」选项，与详情页一致）→ 结果汇总展示，成功后清空勾选并刷新
- Control Plane：`POST /agents/probe` — 探测 Agent 并自动推导注册参数（预览，不写文件）：调 `/healthz` + `/capabilities`，推导 `role`（disk 恒真 + cd 取 capabilities）/ `tags`（storage + backend）/ `iscsi_server`（回退 base_url 主机名），返回 backend / base_iqn / clone 等能力供确认；Agent 不可达或 token 错误返回 502，审计记录 `agent.probe`
- Control Plane：`POST /agents` — 注册新 Agent 写入 `agents.yml`，注册后立即生效；请求体含 `id` / `base_url`（须 http(s)://） / `token`（支持 `${ENV}` 占位）/ `iscsi_server` / `role`（disk/cd）/ `tags` / `enabled`；重复 id 返回 409，审计记录 `agent.register`；`AgentRegistry` 新增 `add()`（yaml 写回保持 `agents:` 顶层结构）
- WebUI Agents 页新增「+ 添加 Agent」入口（两步流程）：填 Agent ID / API 地址 / Token 点「探测」→ 后端自动获取后端类型 / 角色 / 标签 / 数据面地址等参数并在预览区展示（可修改，含只读能力标签）→ 点「添加」完成注册并刷新列表；地址变更后旧探测结果自动失效

### 变更

- 文档：《项目环境部署》1.3 节固件获取方式更新——不再下载解压 `tftp.zip`，改为从 [boot.ipxe.org](https://boot.ipxe.org/) 直接下载官方 release 固件（`undionly.kpxe`，以及 `x86_64-efi/` 下的 `ipxe-legacy.efi` / `ipxe.efi` / `snponly.efi`），全部统一放入 `tftp/` 根目录（不保留官网 `x86_64-efi/` 子目录，`wget` 默认只取 URL 末尾文件名）；`ipxe.efi` / `ipxe-legacy.efi` 为 UEFI 引导异常时的备选固件（改 `dnsmasq.conf` 的 efi64 引导文件）；补充 memdisk 说明——取自 SYSLINUX 发行包 `bios/memdisk/memdisk`，仅「iPXE 直接引导 ISO」的旧方式需要，常规无盘启动（iSCSI sanboot）不需要；中英文档同步

---

## 2026-08-04

### 新增

- Control Plane：`PUT /agents/{agent_id}` — 更新已有 Agent 配置（id 不可改，走路径参数）：`base_url` / `token` / `iscsi_server` / `role` / `tags` / `enabled` 全量覆盖写回 agents.yml，保存后立即生效；`token` 传空字符串 = 保持原值（API 不回显 token，前端无法回填）；`enabled=false` 停用（不再参与建盘/挂载调度与存活探测）；不存在返回 404，审计记录 `agent.update`；`AgentRegistry` 新增 `update()`（原 token 保留）
- Control Plane：`POST /agents/probe` 新增可选 `agent_id` 参数 — 编辑场景 token 留空时自动沿用注册表中该 Agent 的 token 探测（未知 id 忽略）
- WebUI Agents 页每张卡片右上角新增「编辑」按钮 — 点击后在列表上方弹出遮罩弹层（fixed 覆盖，不挤占原有布局；点遮罩空白处或「取消」关闭），编辑表单复用添加的两步探测流程：id 只读展示（走路径参数）、Token 留空保持不变（placeholder 提示，探测沿用注册表原值）、新增「启用（参与调度）」复选框，探测成功后方可保存，保存后刷新列表；停用的 Agent 卡片显示「停用」徽章
- Agent：`GET /masters` — 列出存储节点 `DISK_DIR` 下 `*_tpl_*` 母盘（新增 `MasterScanner` 后台 daemon 线程，每 30 秒周期扫描并带锁缓存 `{name, size, mtime}`，识别文件名含 `_tpl_` 标记的镜像；纯读接口，Bearer 鉴权，不写操作日志）
- Control Plane：`GET /masters` — 聚合列出全部启用磁盘角色 Agent 的母盘清单（遍历 `agents.yml` 中 `enabled` + `role.disk` 节点，逐台调用 Agent `list_masters()`；单台失败返回 `error` 字段并记审计 `master.list`（failed）不阻塞整体，全部失败 502 / 部分成功 200 / 无候选空列表）；`AgentClient` 新增 `list_masters()`
- WebUI：母盘克隆下拉选择——Workers 批量创建与 Worker 详情页「创建系统盘」的母盘名由手工输入改为下拉选择（数据来自 Control Plane 聚合的母盘清单）：批量模式下拉为母盘名去重选项（不绑定存储节点，选择后不自动接管，节点分配由均摊 / 接管 / 拖拽侧边栏决定），支持多存储节点均摊克隆；提交时校验目标节点本地均有该母盘——均摊激活（≥2 个节点参与均摊）时校验全部参与均摊节点，否则校验实际分配节点，缺失时列出缺失节点并阻止提交（用户可移除缺失节点的「参与均摊」勾选，或先在对应节点上传该母盘后再提交），克隆在各节点本地完成；详情页按所选存储节点过滤母盘、切换节点自动清空已选

### 变更

- 文档：`iscsi-server/API_Reference.md` 与 `control_plane/Control_Plane_API_Docs.md` 同步母盘清单接口——接口总览表新增 `GET /masters` 条目并新增独立章节（响应结构 `{agents: [{agent, iscsi_server, masters, error?}]}`、字段说明、失败容错语义）；Agent 侧 `API_Reference.md` 新增 `## 12. GET /masters（母盘清单）`，原编号顺延
- 文档：《项目环境部署》第 2 步新增 2.1「准备 img 存储目录」小节（原 2.1–2.5 顺延为 2.2–2.6）：明确 `iscsi-server/docker-compose.yml` 中 `- /pool1/iscsi_img:/home/iscsi_img` 卷映射须将宿主机侧路径改为存储节点实际存放 img 文件的目录（`ipxe-iscsi` 与 `ipxe-agent` 两处一致，容器内 `/home/iscsi_img` 不变）；存储目录文件系统强烈建议 btrfs（母盘克隆走 reflink/FICLONE 秒级完成，ext4/xfs 等不支持时回退全量拷贝，克隆时间随母盘大小线性增长）；新增单台 iSCSI 服务器硬件瓶颈表（网卡速率 / 硬盘 IO / 内存 CPU）与按并发 Worker 规模扩容存储节点建议（10GbE 约支撑 10–20 个并发 Worker）；中英文档同步
- 文档：Windows / Debian 系无盘快速部署「WebUI 秒级克隆」步骤的母盘名改为下拉选择说明——母盘列表由 WebUI 自动扫描存储节点生成（数据来自 Control Plane 聚合的 `GET /masters` 母盘清单，文件名须含 `_tpl_` 标记），无需手工输入；中英文档同步
- 文档：文档站中英文首页「核心能力」更新——以 README 六条为基础结构：原「秒级启动」改写为「母盘克隆秒级交付」（btrfs reflink 秒级克隆 + 支持矩阵同步为 Debian 11/12/13、Ubuntu 22.04/24.04/26.04、Windows 11 23H2/24H2/25H2），新增「批量部署」「Agent 直管与在线编辑」两条，原「中心控制面 + Web UI」并入后者；补齐「文件即真相」；中英文同步
- 文档：Windows / Debian 系无盘快速部署「第 5 步:设置默认启动」由可选步骤改为常规流程——设置默认系统后开机自动直达系统（无需在 iPXE 菜单手动选择）；仅需配置「默认系统(OS)」一个字段，下拉选项来自该 Worker 已挂载的系统盘（即刚克隆出的盘）；「默认菜单项(Menu Default)」保持默认（重启）不动——推导链 `default_os > boot.menu_default > reboot` 中 `default_os` 优先命中，未配置的菜单项维持重启兜底；中英文档同步
- 文档：Debian 系无盘快速部署「支持范围」注明桌面/服务器版本无差别——Ubuntu 不区分 Desktop / Server 版本，桌面环境（GNOME / KDE / XFCE 等）任意选择，不影响无盘启动；Debian 同理，按常规方式正常安装的系统均支持，无需担心桌面环境影响；1.1 安装步骤同步补充说明；中英文档同步
- 文档：IQN 契约表述修正——`tftp/boot.ipxe.cfg` 的 `base-iqn` 仅为静态兜底值（占位符），Worker 启动时 iPXE 经 `/boot-vars` 按系统盘所在存储节点获取实际 `base-iqn`（盘 IQN 前缀，源自该节点 `IPXE_IQN_BASE`）并覆盖；各存储节点 `IPXE_IQN_BASE` 对自身承载的盘是权威值，无需与 `boot.ipxe.cfg` 静态值一致；《项目环境部署》2.3 与快速部署「环境准备」/FAQ 同步修正；中英文档同步
- 文档：IQN 机制表述复核修正——架构文档（中英）1.5 节第 2 步补充 `base-iqn` 静态兜底 + `/boot-vars` 按系统盘所在存储节点动态覆盖机制（原按纯静态配置推演，缺覆盖环节），第 3 步 root-path 拼装改为与 `menu.ipxe` 一致的 `iscsi:${iscsi-server}${iscsi-sep}${base-iqn}:${hostname}.<os>` 变量格式（原硬编码 `::::`）；Control Plane 文档（中英）`/boot-vars` 返回变量列表补入 `base-iqn`；中英文档同步

---

## 2026-08-05

### 变更

- 文档：README 两版与文档站中英文首页 tagline、ROADMAP 的定位表述对齐《我的云原生定义》宣言——由「企业级无状态（Stateless）计算节点交付平台 / Enterprise-grade diskless computing platform / 云原生的无状态计算基础设施底座」统一改为「真正的云原生实现：把无状态贯彻到算力层本身，算力不绑定任何具体硬件，可丢弃、可替换、可瞬间重建」；路线图愿景改为「贯穿所有计算层的云原生元协议——同一套无状态语义自相似地嵌套于物理机与 hypervisor 每一层，层层皆云」；中英文同步
- 文档：新增仓库根目录 `Manifesto_zh-CN.md`（《我的云原生定义》宣言，由《我的云原生定义.md》重命名，移除文首对话残留）与英文全量翻译版 `Manifesto.md`（九章完整翻译，与中文版互为镜像）；README 中英文版定位段后新增宣言引用

---

## 2026-08-07

### 新增

- Agent：母盘克隆新增 ZFS 支持——存储目录位于 ZFS（OpenZFS ≥ 2.2）且母盘与克隆盘在同一数据集时，`FICLONE` 文件级 reflink 秒级克隆（与 btrfs 同路径，零额外磁盘占用）；ZFS < 2.2 或跨数据集（`st_dev` 不同）时自动回退全量拷贝，并在日志中给出明确诊断（区分「版本过低」与「跨数据集」两类原因）；新增 `_fs_type()`（解析 `/proc/self/mounts` 最长挂载点匹配）与 `_same_fs()`（`st_dev` 比较）
- Agent：`GET /capabilities` 新增 `fs_type` 字段（存储目录文件系统类型：btrfs / zfs / xfs / ext4 ...），`clone` 描述按文件系统类型区分（ZFS 标注 OpenZFS ≥ 2.2 与同数据集约束；xfs 标注需 reflink 特性；其余标注仅全量拷贝）；控制面 `GET /agents` 随 `capabilities` 透传

### 变更

- 文档：《项目环境部署》2.1「准备 img 存储目录」存储文件系统建议由「强烈建议 btrfs」扩展为「btrfs 或 ZFS（OpenZFS ≥ 2.2）」，补充 ZFS 文件级 reflink 的同一数据集约束与 ZFS < 2.2 / 跨数据集回退语义；文档站中英文首页「母盘克隆秒级交付」与控制面文档（中英）的 btrfs 表述同步扩展；`iscsi-server/API_Reference.md` `/capabilities` 章节同步 `fs_type` / `clone` 字段说明；中英文档同步
- WebUI：Agents 页面 Agent 卡片新增「文件系统」展示（`capabilities.fs_type`，等宽字体），注册/编辑探测结果新增 `fs_type` 标签；Control Plane `POST /agents/probe` 返回新增 `fs_type` 字段（透传 Agent `/capabilities`）；`Control_Plane_API_Docs.md` 两处示例同步
- 文档：API 文档迁入文档站——`control_plane/Control_Plane_API_Docs.md` 与 `iscsi-server/API_Reference.md` 移至 `docs/zh/guide/api/`（`control-plane-api.md` / `agent-api.md`，标题中文化），文档站新增「API 参考 / API Reference」栏目（中英侧边栏 + 导航栏），英文版为占位页（结构骨架 + 指向中文权威版，不全量翻译）；原文件删除，文档站成为唯一权威；README 两版官方文档列表新增 API 参考链接，快速开始端口区强调 Control Plane API 为开放 REST 接口、第三方系统与自动化脚本可直接调用
- 文档：两份 API 文档与 README 两版强调 **API 优先（API-first）调用准则**——控制面全部能力以 REST API 为第一接口，WebUI 本身只是该 API 的一个客户端；第三方系统与自动化脚本与 WebUI 平等，一律优先调用 Control Plane API（Agent API 为控制面与存储节点间的内部契约，不作为第三方入口）；英文占位页同步
- 文档：README 两版官方文档列表重构——原理探索系列（第一～四章 + 控制面能力详解 + 已攻克的壁垒）折叠为单个「原理探索 / Exploration」入口（指向专栏首页前言），「快速部署手册」与「API 参考」置顶为直达入口
- 文档：措辞修正——README 英文版 `copy-paste runbooks`、中文快速部署文档「可照抄」、英文 API 占位页 `copy-paste curl` 统一改为中性表述（step-by-step / 可直接执行 / directly executable）
- 文档：控制面 API 参考**中英两版**（7.0/7.3 章节）补强「默认启动系统」概念与字段语义——新增「是干什么的」说明（多盘模型下决定 iPXE 菜单超时后自动选中的启动项 + `/boot-vars` 默认启动盘投影；`os` 是菜单项 ID 而非盘名，合法值同建盘 7.1 枚举、不区分大小写）；`menu_timeout` 补 `0` = 无限等待永不自动选择（iPXE 官方语义）；7.0 修正错误示例（注册后无盘实际返回 `menu-default reboot` + 1ms，而非 exit/5000）并区分已配置/未配置两种超时默认值；7.3 与 7.0 `boot` 字段为同一台账字段的覆盖关系；英文版第 3 行残留 `copy-paste` 措辞一并修正
- 文档：README 两版徽章行首新增 **Cloud Native - True Cloud Native** 徽章（定位宣言的直观呈现）

### 修复

- 文档：API 文档端口号修正——`docs/zh/guide/api/agent-api.md` 全部 curl 示例与 Base URL 由错误的 `localhost:4841` 改为 `4840`（iscsi-server compose 实际映射 `4840:8080`），`control-plane-api.md` 的 `GET /agents` 返回示例 base_url 同步修正；全仓库 4841 零残留
- WebUI：capLabels 克隆方式文案映射缺失 ZFS/xfs/仅全量拷贝新文案（ZFS 支持上线后 UI 直接显示英文原文）——补齐映射并将匹配逻辑改为前缀匹配（动态文案 `full copy only (reflink unsupported on <fs>)` 归并到静态条目）
