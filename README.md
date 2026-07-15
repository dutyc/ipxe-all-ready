# IPXE-All-Ready

**IPXE-All-Ready** 旨在构建一套基于纯开源组件（iPXE + iSCSI + OS）的、企业级无状态（Stateless）计算节点部署标准。

我们的目标不仅是“跑通”无盘启动，而是要将这条充满黑盒与断头路的荒野，铺成一条跨平台、跨架构的现代化无盘基础设施高速公路。

**All 是真的 All，Ready 是真的 Ready。**
**无盘开源时代，来了。**

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

本项目采用现代化的分布式节点命名规范，采用以下角色定义：

* **Controller（控制端）**：集群的大脑与存储中心。提供 DHCP、HTTP 文件分发以及 iPXE 菜单路由。
* **iSCSI Server** ：提供块存储服务的节点，可与 Controller 同机或独立部署。
* **Worker（工作端）**：无状态的算力节点。无本地硬盘，通过 PXE 获取 IP，加载 iPXE，挂载 iSCSI 磁盘，最终引导操作系统。

## 当前进展与参与方式

目前，**Phase 1 核心系统攻坚已全面收官！Debian 12、Ubuntu 22.04 LTS 以及 Windows 11 24H2/25h2 的全链路已经彻底打通**，我们正在将无数个夜晚踩过的深坑封装为一键部署脚本。

我们现在不急于放出零散的“避坑命令”，因为我们希望交付给你的是一套**开箱即用、经过严苛验证的完整方案**。

如果你也对无状态计算架构充满野心，如果你也受够了商业方案的黑盒与傲慢：
- 请 **Star** 和 **Watch** 本项目，你将是第一批拿到多系统无盘部署完整方案的人。
- 欢迎在 **Discussions** 中探讨技术方向，或提交 **Pull Request** 参与 Phase 2/3/4 的适配研究。

**创造历史的人是怎样的？我们不知道，但今天，我们正在成为他们。**

## License

本项目遵循 MIT License。

## 项目成长轨迹

[![Star History Chart](https://api.star-history.com/svg?repos=dutyc/ipxe-all-ready&type=Date)](https://star-history.com/dutyc/ipxe-all-ready&Date)