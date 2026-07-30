# IPXE-All-Ready

![iPXE](https://img.shields.io/badge/iPXE-Network%20Boot-111111) ![iSCSI](https://img.shields.io/badge/iSCSI-Diskless%20Storage-0f766e) ![Control Plane](https://img.shields.io/badge/Control%20Plane-FastAPI-2563eb) ![Agent](https://img.shields.io/badge/Agent-STGT%20%2F%20LIO-7c3aed) ![dnsmasq](https://img.shields.io/badge/DHCP-dnsmasq-334155) ![License](https://img.shields.io/badge/License-MIT-green)

[中文版](./README.zh-CN.md) | [English](./README.md)

**IPXE-All-Ready** 旨在构建一套基于纯开源组件（iPXE + iSCSI + OS）的、企业级无状态（Stateless）计算节点部署标准。

我们的目标不仅是“跑通”无盘启动，而是要将这条充满黑盒与断头路的荒野，铺成一条跨平台、跨架构的现代化无盘基础设施高速公路。

**All 是真的 All，Ready 是真的 Ready。**
**无盘开源时代，来了。**

## 项目总览

`ipxe-all-ready` 现在已经从单纯的无盘启动验证，演进为一套面向无状态计算节点交付的开源控制面雏形。它把过去分散在手工命令、静态配置和经验判断里的动作，收敛成清晰的组件边界：

- **Control Plane**：Controller 节点上的常驻 HTTP 服务，负责 Worker 生命周期编排、Agent 调度、Worker 存储台账、`dnsmasq` 主机名绑定，以及 `/boot-vars` 启动变量投影。
- **iSCSI Agent**：部署在每台 iSCSI Server 上的本地执行器，通过 HTTP 接收 Control Plane 调度，再经 `docker.sock` 操作本机 STGT / LIO iSCSI 服务端。
- **iPXE 静态菜单 + 动态变量注入**：`menu.ipxe` 保持静态交互，`boot.ipxe.cfg` 在启动早期从 Control Plane 拉取 per-worker 变量，解决多 iSCSI 存储节点下的启动参数差异。
- **文件即真相**：不引入数据库，使用 `agents.yml`、`workers.yml`、`dhcp-hosts.conf`、`operations.jsonl` 承载控制面状态，透明、可 diff、可手工修复。
- **控制面与数据面分离**：Control Plane 只做调度与台账，Worker 的块存储读写直接走 iSCSI 数据面，不经过控制面。

## 项目结构

```text
Control_Plane/
├── docker-compose.yml                  # Control Plane compose 入口
├── docker-compose.control-plane.yml    # Control Plane 独立 compose 示例
├── README.zh-CN.md
│
├── control_plane/                      # 控制平面（核心服务）
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── control_plane.env
│   ├── control_plane.env.example
│   ├── Control_Plane_API_Docs.md
│   ├── Agent_API_Docs.md
│   ├── app/                            # FastAPI 源码
│   │   ├── main.py                     # HTTP API 与 Worker 生命周期编排
│   │   ├── agent_client.py             # Agent HTTP 客户端
│   │   ├── scheduler.py                # Agent 选择与能力探测
│   │   ├── dnsmasq.py                  # dhcp-hosts.conf 管理与 HUP 重载
│   │   ├── state.py                    # YAML / JSONL 状态文件读写
│   │   ├── models.py                   # 请求模型
│   │   └── config.py                   # 环境变量配置
│   ├── config/                         # Agent 静态配置
│   │   ├── agents.yml
│   │   └── agents.yml.example
│   └── state/                          # 运行时状态
│       ├── workers.yml
│       └── operations.jsonl
│
├── dnsmasq/                            # DHCP 静态主机名绑定
│   └── dhcp-hosts.conf
│
└── tftp/                               # iPXE 引导文件
    ├── boot.ipxe
    ├── boot.ipxe.cfg
    ├── menu.ipxe
    ├── preseed.cfg
    ├── boot/
    └── config/
```

## 📚 官方文档与实战指南

完整的架构设计、底层原理解析以及各操作系统的“降维打击”部署实战，请访问我们的专属文档站：

 **[ipxe.lecreate.asia](https://ipxe.lecreate.asia)** | **[中文文档](https://ipxe.lecreate.asia/zh/)**

**当前文档已收录的核心攻坚内容：**

-  **[第一章：架构设计与核心链路](https://ipxe.lecreate.asia/zh/guide/architecture)**
  剖析 iPXE + iSCSI 启动状态机，拆解 DHCP/iPXE/iSCSI 动态变量传递链，彻底告别网络引导黑盒。
-  **[第二章：Windows 11 24H2 无盘全流程实战](https://ipxe.lecreate.asia/zh/guide/windows-11)**
  利用 `dism++` 避开 ADK 陷阱注入万能驱动，结合 `tgt --device-type cd` 虚拟光驱机制，实现原生 `setup.exe` 丝滑安装与 iBFT 无缝接管。

## 路线图 (Roadmap)

`ipxe-all-ready` 的最终目标并非仅仅实现单一系统的无盘启动，而是构建一个跨平台、跨架构、云原生的无状态计算基础设施底座。

### Phase 1: 破冰与核心系统攻坚
*确立无盘启动的核心标准，打通最主流桌面与服务器操作系统的底层引导闭环。*

- [x] **Debian 12**：已完成全链路验证，确立无盘启动的核心标准与底层逻辑基线。破解 initramfs 打包黑盒，具备"秒级接入"的能力。
- [x] **Ubuntu 22.04 LTS**：已通过 `debootstrap` 绕过 Subiquity 安装器黑盒，解决 ISO 多层 Overlay 结构缺失核心命令问题；显式注入 iSCSI 内核模块并手动构建自动登录节点配置；使用 UUID 替代设备路径实现跨硬件兼容；成功实现“插网线即启动”的秒级接入。
- [x] **Windows 11 24H2/25H2**：攻克 Windows 环境下的底层引导机制与系统状态依赖, 利用 `dism++` 避开 ADK 版本陷阱，向 `boot.wim` 注入包含 VMware/物理机全场景兼容的“驱动全家桶”；结合 iSCSI Server 的 `--device-type cd` 虚拟光驱挂载 ISO，实现安装程序的无缝接管与原生 iSCSI Boot 完美启动。

### Phase 2: 主流 Linux 发行版生态兼容
*跨越不同的包管理器与初始化流派，扩大无盘架构的 Linux 生态版图。*

- [ ] **Arch Linux**：适配其滚动更新特性与自定义初始化框架，提供面向极客的极简无盘方案。
- [ ] **RHEL / Fedora 系**：探索企业级 Linux 发行版在严格安全策略下的无盘运行模式与兼容性。
- [ ] **Alpine Linux**：打造面向边缘计算、微型路由与物联网节点的超轻量级无盘底座。

### Phase 3: 云原生与现代化架构演进
*推动控制平面的现代化，并探索下一代网络存储协议，突破传统架构瓶颈。*

- [ ] **Controller 容器化与高可用**：探索将引导服务与存储控制面容器化，实现一键部署与集群化管理。
- [ ] **下一代存储协议评估**：研究并测试 NVMe-oF 等高性能网络存储协议，探索突破传统 iSCSI I/O 瓶颈的路径。
- [ ] **云原生边缘节点纳管**：探索无盘 Worker 节点与轻量级 Kubernetes 集群的无缝对接，实现“开机即入列”的自动化编排。

### Phase 4: 跨架构与异构计算探索
*打破 x86 架构的边界，面向未来的多元化算力场景提供无状态底座。*

- [ ] **ARM64 架构支持**：研究 ARM UEFI 环境下的网络引导机制，探索 ARM 服务器与边缘集群的无盘化可能。
- [ ] **异构算力节点交付**：为 AI 推理、GPU 渲染等特殊算力节点，探索无盘系统结合共享存储的标准化交付模板。

## 我们已经攻克的壁垒

1. **Initramfs 的“先有鸡还是先有蛋”死锁**：如何在内核挂载根文件系统前，让极简的 initramfs 具备完整的 iSCSI 网络存储握手能力？我们已建立标准化的模块注入与自动登录机制。
2. **引导加载器的黑盒陷阱**：解决跨环境安装时，GRUB 变量名的隐蔽拼写错误，以及更新配置后 MBR 引导代码丢失导致的“完美黑屏”问题。
3. **iPXE 会话的“断崖式”移交**：突破 `sanboot` 在控制权移交瞬间断开底层连接的传统机制，实现 Pre-OS 到内核态 iSCSI 会话的无缝保活与接管。
4. **复杂的 Pre-OS 网络栈初始化**：在引导极早期彻底解决 IPv6 路由黑洞、DHCP 超时以及多网卡环境下的路由冲突。
5. **Update-initramfs 的黑盒打包陷阱**：发现官方 hook 脚本完全忽略自定义的 `/etc/iscsi.initramfs` 文件，通过修改 `/usr/share/initramfs-tools/hooks/iscsi` 强制注入配置，实现从"被动接受"到"主动控制"的逆转。
6. **Ubuntu Subiquity 安装器的 iSCSI 盲区**：官方安装器在磁盘选择界面完全隐藏 iSCSI 设备，放弃图形化安装，采用 `debootstrap` 直接从源拉取纯净系统，实现"降维打击"式部署。
7. **Ubuntu ISO 的多层 Overlay 结构陷阱**：提取 squashfs 后发现缺少 bash 等核心命令，**验证了官方 ISO 采用分层架构，果断切换至** `debootstrap` 方案，确保系统完整性。
8. **纯净系统的 iSCSI 模块缺失**：`debootstrap` 拉取的最小系统未预设任何 iSCSI 启动逻辑，显式注入 `iscsi_tcp`、`libiscsi` 等内核模块，手动构建包含 `node.startup = automatic` 的完整节点配置。
9. **Windows PE 阶段的网络死锁与 ADK 依赖**：利用 `dism++` 离线注入万能驱动全家桶（vmxnet3, pvscsi, iastorvd 等），打破 PE 阶段无网卡驱动的死锁，并完美避开微软 ADK 的版本限制；结合 `--device-type cd` 挂载 ISO，让安装程序像读取物理光盘一样顺畅完成部署。

## 架构定义

本项目采用现代化的分布式节点命名规范，并严格区分**控制面**（做决策、做调度，流量小）与**数据面**（搬数据，流量大），角色定义如下：

![架构设计](./assets/%E6%9E%B6%E6%9E%84%E8%AE%BE%E8%AE%A1.svg)

* **Controller（控制端节点）**：集群的大脑。承载 **Control Plane** 常驻 HTTP 服务，负责 Worker 生命周期编排、Agent 调度、Worker 存储台账、`dnsmasq` 主机名绑定，以及 iPXE 启动变量的只读动态投影。Control Plane 自身不直接操作任何 iSCSI 服务端，也不接管静态文件分发和菜单生成：HTTP 文件由 nginx 分发，iPXE 菜单保持静态交互，存储操作一律经由 Agent 完成，从而让本机光驱与远端系统盘走同一套调度逻辑。
* **iSCSI Server（存储节点）**：提供块存储的节点，可与 Controller 同机，也可独立部署到大容量 NAS / SAN。每个节点驻守一个 **API Agent**，接收 Control Plane 的 HTTP 请求，经 `docker.sock` 调度本机的 iSCSI 服务端容器。服务端软件可**异构**：**stgt**（用户态，支持把 ISO 挂成虚拟光驱，对受限环境友好）或 **LIO**（内核态，生产级磁盘）。后端差异封装在 Agent 内部，Control Plane 无需感知。该节点以镜像目录中的文件为**唯一真相**，启动时自动扫描目录、重建 iSCSI 配置，无需额外维护配置文件。
* **Worker（工作端）**：无状态算力节点，无本地硬盘。通电后经 PXE 获取 IP 与身份，加载 iPXE，挂载 iSCSI 系统盘（安装期加挂虚拟光驱），引导操作系统。

**控制面与数据面分离**

* **控制面流量**是 Control Plane 与 Agent 之间的 HTTP 调度，以及 Worker 启动早期向 `/boot-vars` 拉取 per-worker 变量的只读请求，体量小，只在开通、注销或启动参数投影时发生。
* **数据面流量**是 Worker 与 iSCSI Server 之间的块存储读写，与控制面在物理上分离。
* **安装介质与系统盘就近放置**：ISO 虚拟光驱靠近 Control Plane（安装介质本就在控制端），由控制端节点的 Agent 用 stgt 挂载；大容量系统盘放在远端 iSCSI Server。Worker 因此连接两个 iSCSI target——控制端的光驱与存储节点的系统盘。

## 当前进展与参与方式

目前，**Phase 1 核心系统攻坚已全面收官！Debian 12、Ubuntu 22.04 LTS 以及 Windows 11 24H2/25H2 的全链路已经彻底打通。** 在系统镜像打通的同时，我们同步搭建了**分布式控制面**——让"加一台无盘机器"从手工改几个文件，变成 Control Plane 的一条调度指令。

**控制面已落地**

* **分布式调度模型**：Control Plane 只发 HTTP，每台 iSCSI Server 上的 API Agent 接收并操作本地 iSCSI 服务端，控制面与数据面分离。新增/删除 Worker 已从手工修改配置收敛为 `POST /workers` 与 `DELETE /workers/{id}` 这类稳定契约。
* **文件即真相的轻量控制面**：不引入数据库，`config/agents.yml` 记录 Agent 清单，`state/workers.yml` 记录 Worker 存储台账，`dnsmasq/dhcp-hosts.conf` 作为 MAC -> hostname 的唯一真相，`operations.jsonl` 记录控制面操作轨迹。
* **Worker 生命周期闭环**：创建 Worker 时自动拼接 IQN、选择 disk Agent、调用 Agent 创建空白盘或从母盘克隆、写入 Worker 台账、写入 `dnsmasq` 静态主机名绑定，并通过 `docker.sock` 对 `ipxe-dnsmasq` 发送 HUP 重载配置。
* **per-worker 启动变量动态注入**：在保留 iPXE 静态菜单交互的前提下，新增 `/boot-vars` 只读端点，由 Control Plane 按 MAC/hostname 查询 inventory，动态返回 `iscsi-server`、`menu-default`、`menu-timeout` 等变量。`menu.ipxe` 零改动，`boot.ipxe.cfg` 只在末尾拉取变量并重算 `base-iscsi`，实现多 iSCSI 存储节点下的 per-worker 启动参数覆盖。
* **API Agent 的 stgt 后端**：磁盘 LUN 创建（同步生成 `.img` 文件）、ISO 虚拟光驱挂载、目录批量扫描、base IQN 校验，均已跑通验证；并以镜像目录文件为真相、节点启动自动扫描重建，根治 stgt 配置易失。
* **异构后端设计**：stgt 与 LIO 双后端均已接入 Agent，其中 LIO 服务端已容器化、Agent LIO 后端已跑通空白盘创建、target 删除与状态查询；后端差异封装在 Agent 内，Control Plane 不感知。
* **存储性能**：母盘到工作盘的克隆在 btrfs 上以 reflink 秒级完成，实测数据块共享、零额外磁盘占用。
* **Web 管理界面**：基于 React + Vite 构建的极简黑白工业风 SPA，集成 Control Plane 全部管理能力。
  * **Dashboard**：Worker / Agent 集群水位总览，最近操作日志摘要。
  * **Workers 管理**：列表查看、筛选过滤、内联创建表单（空白盘 / 母盘克隆 / Windows ISO 安装期），支持条件字段展示。
  * **Worker 详情**：台账信息（Identity / Disk / CD-ROM）、实时状态探测（dnsmasq 绑定、disk/cd target 存在性）、启动变量投影（/boot-vars 代码块展示）、安全删除（内联二次确认，可选删除 .img 磁盘文件）。
  * **Agents 监控**：自适应网格卡片布局，展示后端类型、能力描述、健康状态，支持 Live 探测开关。
  * **操作日志**：审计流水增量加载，时间戳 + 操作类型 + 状态标记 + 关联 Worker。
  * **技术栈**：React 18 + React Router 6 (HashRouter) + 纯 CSS 变量驱动主题，零第三方 UI 库依赖。
  * **部署**：Vite 构建为纯静态文件，由 nginx 容器统一分发；API 代理通过 nginx 转发至 Control Plane，无需额外运行时。
* **文件浏览器**：集成于同一 nginx 容器，通过 njs 脚本提供 JSON 目录列表 API，展示 `public/` 目录下的 iPXE 引导文件（ISO、kernel、initrd）。
  * 文件下载端点 `/file/` 专供 iPXE `chain` / `initrd` 指令使用，404 响应为纯文本绝不返回 HTML 页面。
  * Web UI 与文件浏览器共享同一 nginx 容器（:4838），无额外进程开销。

**控制面推进中**

* **CLI 与初步部署体验**：后续将提供薄 CLI，用于初始化配置、检查组件健康、启动 compose，以及作为 Control Plane API 的便捷客户端；日常 Worker 生命周期仍统一走 Control Plane HTTP。
* **更完整的 reconcile 能力**：对比 `workers.yml`、`dnsmasq/dhcp-hosts.conf` 与 Agent 实际 target 状态，报告并修复台账漂移。
* 将 Phase 1 的镜像制作、母盘人工封装流程与上述控制面串联为**一键部署脚本**。

我们正在将无数个夜晚踩过的深坑封装为一套**开箱即用、经过严苛验证的完整方案**，因此不急于放出零散的"避坑命令"。

如果你也对无状态计算架构充满野心，如果你也受够了商业方案的黑盒与傲慢：
- 请 **Star** 和 **Watch** 本项目，你将是第一批拿到多系统无盘部署完整方案的人。
- 欢迎在 **Discussions** 中探讨技术方向，或提交 **Pull Request** 参与 Phase 2/3/4 的适配研究。

**创造历史的人是怎样的？我们不知道，但今天，我们正在成为他们。**

## License

本项目遵循 MIT License。

## 项目成长轨迹

<a href="https://www.star-history.com/?repos=dutyc%2Fipxe-all-ready&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=dutyc/ipxe-all-ready&type=date&theme=dark&legend=top-left&sealed_token=zjOknpQELRo5XRHVkZyVFbzpe3vGpw7134qQQpvRcCNi89-GWZKA9NmUisZj8-0rngIFYnEpjMkDcTyDcbpjeoo6F4-CNJ-_Jn5DDmYZQElWO7WgDPbJuA" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=dutyc/ipxe-all-ready&type=date&legend=top-left&sealed_token=zjOknpQELRo5XRHVkZyVFbzpe3vGpw7134qQQpvRcCNi89-GWZKA9NmUisZj8-0rngIFYnEpjMkDcTyDcbpjeoo6F4-CNJ-_Jn5DDmYZQElWO7WgDPbJuA" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=dutyc/ipxe-all-ready&type=date&legend=top-left&sealed_token=zjOknpQELRo5XRHVkZyVFbzpe3vGpw7134qQQpvRcCNi89-GWZKA9NmUisZj8-0rngIFYnEpjMkDcTyDcbpjeoo6F4-CNJ-_Jn5DDmYZQElWO7WgDPbJuA" />
 </picture>
</a>
