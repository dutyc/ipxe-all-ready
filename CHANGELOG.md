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

### 变更

- **文档：README 全面入口式重构（对齐 Docker/K8S 风格），控制面详解与攻坚记录迁入文档站**——README.md / README.zh-CN.md 精简为入口式结构（定位 → 架构三角色 → 核心能力 6 条 → 快速开始（clone + compose up + 端口）→ 官方文档链接 → 路线图（指向 ROADMAP.md）→ 参与贡献 → License → Star History），删除原「控制面能力详解」「我们已经攻克的壁垒」「详细项目结构」全文；文档站新增《控制面能力详解》（中英：设计原则 + 核心能力 8 项 + WebUI 能力 + 文件浏览器）与《我们已经攻克的壁垒》（中英：Linux 引导链 / Ubuntu / Windows 分组 9 条），VitePress 侧边栏注册（中英 Exploration 分组）；参与贡献章节新增 AI 辅助开发态度声明（不反对 AI 生成代码——项目本身由 Qwen/Codex/DeepSeek 协同完成，但贡献者必须自行理解整体架构：控制面/数据面分离、iPXE 引导链、动态变量传递链、文件即真相、iSCSI 会话保活；无法清晰阐述设计逻辑的 PR 拒绝合并，鼓励先提 Issue/Idea）
