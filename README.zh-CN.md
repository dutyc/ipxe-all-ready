# iPXE-All-Ready

![iPXE](https://img.shields.io/badge/iPXE-Network%20Boot-111111) ![iSCSI](https://img.shields.io/badge/iSCSI-Diskless%20Storage-0f766e) ![Control Plane](https://img.shields.io/badge/Control%20Plane-FastAPI-2563eb) ![Agent](https://img.shields.io/badge/Agent-STGT%20%2F%20LIO-7c3aed) ![dnsmasq](https://img.shields.io/badge/DHCP-dnsmasq-334155) ![Web UI](https://img.shields.io/badge/Web%20UI-React-18181b) ![License](https://img.shields.io/badge/License-Apache%202.0-green)

[中文版](./README.zh-CN.md) | [English](./README.md)

**iPXE-All-Ready** 是一套基于纯开源工具链（iPXE + iSCSI）构建的真正的云原生实现：把「无状态」贯彻到算力层本身——计算节点不持有任何属于自己的持久状态，身份、系统、数据全部由网络与控制面在外部赋予，可丢弃、可替换、可瞬间重建。无本地硬盘的算力节点插网线即活，无需人工预注册，无厂商锁定。

**我们的宣言：** [Manifesto_zh-CN.md](./Manifesto_zh-CN.md)（《我的云原生定义》）——真正的云原生，是把「无状态」贯彻到算力层本身，从上到下，没有一块冰。

本项目已从单纯的无盘启动验证，演进为一套完整的开源控制面：新机器插电即被自动识别与注册，挂载系统盘、切换默认启动系统在 Web 界面上几次点击即可完成。**All 是真的 All，Ready 是真的 Ready。**

## 架构总览

![架构设计](./assets/architecture.svg)

三个职责清晰分离的角色，严格区分**控制面**（做决策、做调度）与**数据面**（搬数据）：

* **Controller（控制端节点）**：集群的大脑。承载 Control Plane 常驻 HTTP 服务（Worker 生命周期编排、Agent 调度、存储台账、`dnsmasq` 绑定、启动变量投影），以及 DHCP/TFTP/HTTP 引导服务，全部容器化。
* **iSCSI Server（存储节点）**：提供块存储。每个节点驻守一个 API Agent，经 `docker.sock` 调度本机的 stgt 或 LIO 后端；后端差异封装在 Agent 内，Control Plane 不感知。
* **Worker（工作端）**：无本地硬盘的无状态算力节点。通电后 PXE 引导、挂载 iSCSI 系统盘、进入操作系统。块存储读写直接走 iSCSI 数据面，不经过控制面。

## 核心能力

- **零接触自动注册（Zero-touch Provisioning）**——新机器插电即被识别与注册，管理员在 Web 界面挂盘、设定默认系统，机器自动进入目标系统，全程零人工预注册。
- **一机多系统**——一台 Worker 可挂载多块系统盘（Windows / Ubuntu / Debian / CentOS / ESXi），随时在线切换默认启动系统，无需触碰机器。
- **秒级启动**——Debian 12、Ubuntu 22.04 LTS 与 Windows 11 24H2/25H2 经 iPXE + iSCSI 全链路验证，一套底座全平台覆盖。
- **拒绝黑盒**——基于 `debootstrap` 与 `dism++` 绕过官方安装器（Subiquity / ADK）限制，引导链每一环都透明可控，真正的基础设施即代码。
- **文件即真相**——不引入数据库：`agents.yml`、`workers.yml`、`dhcp-hosts.conf`、`operations.jsonl` 承载全部控制面状态，透明、可 diff、可手工修复。
- **100% 纯开源工具链**——iPXE、stgt/LIO、dnsmasq、FastAPI、React、VitePress 全部基于开源组件构成，无厂商锁定，完整可审计。

## 快速开始

> 前置条件：一台 Linux 主机（推荐 Debian 12 / Ubuntu 22.04）作为 Controller 节点，安装 Docker Engine。完整的硬件基线、网络规划与存储布局见[项目环境部署文档](https://ipxe.lecreate.asia/zh/guide/quick-deploy/environment-deploy)。

```bash
git clone https://github.com/dutyc/ipxe-all-ready
cd ipxe-all-ready

# 1. 修改 dnsmasq/dnsmasq.conf：网卡名、网段、网关
# 2. 准备控制面配置（仓库只跟踪 *.env.example 模板，含完整注释）：
cp control_plane/control_plane.env.example control_plane/control_plane.env
#    - 可选：设置 IPXE_CP_TOKEN 开启 API 鉴权（与 WebUI 的 VITE_CP_TOKEN 保持一致）
docker compose up -d

# 3. （可选）Web 管理界面构建：自定义鉴权 Token 时
#    cp webui/app/.env.example webui/app/.env，再 cd webui/app && npm run build

# 4. （可选）存储节点：在存储机器上部署 iscsi-server 目录
#    cp iscsi-server/.env.example iscsi-server/.env
#    填写 IPXE_AGENT_TOKEN（须与控制面 agents.yml 中该节点的 token 一致）
#    docker compose -f iscsi-server/docker-compose.yml up -d
```

* Web 管理界面：`http://<controller-ip>:4838`
* Control Plane API：`http://<controller-ip>:4839`

Worker 镜像交付请阅读下方快速部署文档。

## 官方文档与实战指南

完整的架构设计、底层原理解析以及各操作系统的部署实战，请访问我们的专属文档站：

**[ipxe.lecreate.asia](https://ipxe.lecreate.asia)** | **[中文文档](https://ipxe.lecreate.asia/zh/)**

核心章节：

* [第一章：架构设计与核心链路](https://ipxe.lecreate.asia/zh/guide/exploration/architecture)——iPXE + iSCSI 启动状态机与动态变量传递链
* [第二章：Windows 11 无盘系统全流程实战](https://ipxe.lecreate.asia/zh/guide/exploration/windows-11)——`dism++` 万能驱动注入 + 虚拟光驱安装
* [第三章：Debian 12 无盘系统全流程实战](https://ipxe.lecreate.asia/zh/guide/exploration/debian-12)——netboot 安装与母盘封装全链路
* [第四章：Debian 系 iBFT 无盘启动](https://ipxe.lecreate.asia/zh/guide/exploration/debian-12-ibft)——iBFT 六环链路与源码级证据链
* [控制面能力详解](https://ipxe.lecreate.asia/zh/guide/exploration/control-plane)——调度模型、API 契约与 Web 管理界面
* [我们已经攻克的壁垒](https://ipxe.lecreate.asia/zh/guide/exploration/barriers)——一路踩过并填平的黑盒深坑
* [快速部署手册](https://ipxe.lecreate.asia/zh/guide/quick-deploy/environment-deploy)——环境部署、Windows 与 Debian 系母盘克隆，可照抄

## 路线图

最终目标：构建跨平台、跨架构、贯穿所有计算层的云原生元协议——同一套无状态语义自相似地嵌套于物理机与 hypervisor 每一层，算力不绑定任何具体硬件，层层皆云。完整的阶段规划（Phase 1~4）与近期推进事项见 **[ROADMAP.md](./ROADMAP.md)**。

目前，**Phase 1 核心系统攻坚已全面收官**——Debian 12、Ubuntu 22.04 LTS 以及 Windows 11 24H2/25H2 的全链路已经彻底打通，分布式控制面与 Web 管理界面同步落地。

## 参与贡献

我们正在将无数个夜晚踩过的深坑封装为一套**开箱即用、经过严苛验证的完整方案**。你可以 **Star** / **Watch** 本项目、在 **Discussions** 中探讨技术方向，或提交 **Pull Request** 参与共建——提交 PR 前，请先阅读下方要求。

**关于 AI 辅助**：本项目不反对使用 AI 辅助生成代码——事实上，IPXE-All-Ready 本身就是在 Qwen、Codex、DeepSeek 等 AI 助手的协同下完成的，我们对 AI 辅助开发持开放态度。但对于社区贡献，我们有明确要求：**贡献者本人必须深刻理解项目的整体架构，而不仅仅是让 AI 去理解**。

这不要求你精通 iPXE 脚本的每一行语法，也不要求你能手写 iSCSI 登录报文，而是要求你理解：

- 控制面与数据面为什么要分离，边界在哪里
- iPXE 引导链从 DHCP 到内核接管的完整流程
- 动态变量传递链如何贯穿整个引导周期
- "文件即真相"的设计哲学，为什么不用数据库
- iSCSI 会话保活机制在整个链路中的位置与影响

**语法可以让 AI 搞定，但架构理解必须由人脑完成**。如果一份 PR 背后的设计逻辑不能被贡献者清晰阐述，我们会拒绝合并。不理解架构时，提个 Issue 或 Idea 比提交 PR 更有价值——Issue 是信号，不会污染代码库；PR 是方案，需要深刻。

欢迎每一位愿意理解架构的同行者，也感谢每一位提供真实使用反馈的用户。

## License

本项目遵循 [Apache License 2.0](./LICENSE)

## 项目成长轨迹

<a href="https://www.star-history.com/?repos=dutyc%2Fipxe-all-ready&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=dutyc/ipxe-all-ready&type=date&theme=dark&legend=top-left&sealed_token=zjOknpQELRo5XRHVkZyVFbzpe3vGpw7134qQQpvRcCNi89-GWZKA9NmUisZj8-0rngIFYnEpjMkDcTyDcbpjeoo6F4-CNJ-_Jn5DDmYZQElWO7WgDPbJuA" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=dutyc/ipxe-all-ready&type=date&legend=top-left&sealed_token=zjOknpQELRo5XRHVkZyVFbzpe3vGpw7134qQQpvRcCNi89-GWZKA9NmUisZj8-0rngIFYnEpjMkDcTyDcbpjeoo6F4-CNJ-_Jn5DDmYZQElWO7WgDPbJuA" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=dutyc/ipxe-all-ready&type=date&legend=top-left&sealed_token=zjOknpQELRo5XRHVkZyVFbzpe3vGpw7134qQQpvRcCNi89-GWZKA9NmUisZj8-0rngIFYnEpjMkDcTyDcbpjeoo6F4-CNJ-_Jn5DDmYZQElWO7WgDPbJuA" />
 </picture>
</a>
