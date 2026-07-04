# IPXE-All-Ready

**IPXE-All-Ready** 是一个致力于实现纯开源组件（iPXE + iSCSI + Linux）无盘启动的自动化部署方案与避坑指南。

本项目旨在解决在 Linux 环境下使用 iPXE 进行 iSCSI 无盘引导时，因官方文档缺失、社区经验断层而导致的各种“黑盒”问题。通过本方案，你可以将一台普通的 x86 设备转化为无状态（Stateless）的计算节点，所有系统状态与数据均集中存储于服务端。

无盘开源时代，来了。

## 项目愿景与当前进度

本项目的终极目标是提供一套开箱即用的、支持多操作系统的纯开源无盘启动方案。

**当前进度：**
- [x] **Debian 12**：已完整跑通。从 PXE 引导、iSCSI 挂载、initramfs 模块注入到 GRUB 修复，全链路验证通过。
- [ ] **Ubuntu**：正在适配中。
- [ ] **Windows**：正在攻克注册表与驱动注入的“灵魂”逻辑。
- [ ] **自动化脚本**：正在将手动排查过程封装为 Controller 端的一键部署脚本。

如果你也对无状态计算架构感兴趣，欢迎 Star 并关注本项目，我们将持续更新多系统的适配进度。

## 为什么需要这个项目？

翻遍整个互联网，关于 iPXE + iSCSI 无盘 Linux 的完整记录屈指可数。官方文档简陋，社区里充满了“我遇到了问题”的求助，却鲜有完整的解决方案。

本项目总结了在纯开源链路中极易踩坑的核心技术细节，填补了这些空白：

1. **Initramfs 灵魂注入**：解决 Linux 无盘启动的“先有鸡还是先有蛋”死锁。强制将 `iscsi_tcp` 和 `ib_iser` 模块注入 initramfs，并配置 `open-iscsi` 自动握手。
2. **GRUB 参数与 MBR 修复**：修复 Debian/Ubuntu 安装程序在 iSCSI 环境下容易出现的 `GRUB_CMDLINE_LINUX_DEFAULT` 变量名拼写错误，以及 `update-grub` 后遗漏 `grub-install` 导致 MBR 无引导代码的黑屏问题。
3. **iPXE Sanboot 保活机制**：使用 `sanboot --keep --drive 0x80` 强制 iPXE 在移交控制权后保持 iSCSI 会话，防止内核在 initramfs 阶段因底层连接断开而 Kernel Panic。
4. **网络栈排雷**：强制禁用 IPv6 (`ipv6.disable=1`) 并配置 `ip=dhcp`，彻底杜绝虚拟机网络栈的路由黑洞与 DHCP 超时。

## 架构说明

本项目采用现代化的节点命名规范，摒弃了传统的 `master/slave` 或 `master/node` 称呼，采用以下角色定义：

* **Controller（控制端/服务端）**：提供 DHCP、HTTP 文件分发、iSCSI Target 存储以及 iPXE 菜单配置。
* **Worker（工作端/无盘节点）**：无本地硬盘的计算节点。通过 PXE 获取 IP，加载 iPXE，挂载 iSCSI 磁盘，并最终引导操作系统。

## 核心避坑指南（Debian 12 验证）

在 Worker 端通过 iPXE 引导 Debian Installer 完成基础系统安装后，**切勿直接重启**。必须通过 Rescue Mode 或挂载 iSCSI 磁盘到 Controller 本地进行以下修复：

**1. 修正 GRUB 变量名并注入网络启动参数**
安装程序默认生成的 GRUB 参数往往不包含网络启动指令，且变量名可能存在拼写陷阱。
```bash
sed -i 's/^GRUB_CMDLINE_DEFAULT=/GRUB_CMDLINE_LINUX_DEFAULT=/' /etc/default/grub
sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT=".*"/GRUB_CMDLINE_LINUX_DEFAULT="text ip=dhcp ipv6.disable=1"/' /etc/default/grub
```

**2. 确保 iSCSI 模块已注入 initramfs**
```bash
echo "iscsi_tcp" >> /etc/initramfs-tools/modules
echo "ib_iser" >> /etc/initramfs-tools/modules
update-initramfs -u -k all
```

**3. 将 GRUB 引导代码写入 MBR**
`update-grub` 仅生成配置文件，必须执行 `grub-install` 才能将 Stage 1 写入磁盘，否则 iPXE `sanboot` 会因找不到引导代码而黑屏。
```bash
grub-install /dev/sdX
grub-install --recheck /dev/sdX
```

**4. 断开 Controller 端连接**
在 Worker 重启前，必须在 Controller 端执行 `iscsiadm -u` 登出 Target，防止 SCSI 锁冲突导致文件系统损坏。

## 验证无盘启动

Worker 重启并成功进入系统后，可通过以下命令验证其无盘状态：

查看设备物理路径：
```bash
ls -l /dev/disk/by-path/
# 输出应包含：ip-192.168.1.5:3260-iscsi-iqn...-lun-0 -> ../../sda
```

查看内核启动参数：
```bash
cat /proc/cmdline
# 输出应包含：ip=dhcp ipv6.disable=1
```

## 贡献与关注

这是一个由极客驱动、从深坑中蹚出来的开源项目。如果你在使用本方案时遇到了新的坑并成功解决，或者希望加入 Ubuntu/Windows 的适配工作，欢迎提交 Issue 或 Pull Request。

**创造历史的人是怎样的？我们不知道，但今天，我们正在成为他们。**

关注 `ipxe-all-ready`，一起见证无盘开源时代的到来。

## License

本项目遵循 MIT License。