# 我们已经攻克的壁垒

*无盘启动是一条充满黑盒与断头路的技术荒野。以下是本项目在打通 Debian 12、Ubuntu 22.04 LTS 与 Windows 11 全链路、并构建控制面基础设施的过程中，逐一攻克的核心壁垒。*

## Linux 引导链

1. **Initramfs 的"先有鸡还是先有蛋"死锁**

   如何在内核挂载根文件系统前，让极简的 initramfs 具备完整的 iSCSI 网络存储握手能力？我们已建立标准化的模块注入与自动登录机制。

2. **引导加载器的黑盒陷阱**

   解决跨环境安装时 GRUB 变量名的隐蔽拼写错误，以及更新配置后 MBR 引导代码丢失导致的"完美黑屏"问题。

3. **iPXE 会话的"断崖式"移交**

   突破 `sanboot` 在控制权移交瞬间断开底层连接的传统机制，实现 Pre-OS 到内核态 iSCSI 会话的无缝保活与接管。

4. **复杂的 Pre-OS 网络栈初始化**

   在引导极早期彻底解决 IPv6 路由黑洞、DHCP 超时以及多网卡环境下的路由冲突。

5. **Update-initramfs 的黑盒打包陷阱**

   发现官方 hook 脚本完全忽略自定义的 `/etc/iscsi.initramfs` 文件，通过修改 `/usr/share/initramfs-tools/hooks/iscsi` 强制注入配置，实现从"被动接受"到"主动控制"的逆转。

## Ubuntu 专项攻坚

6. **Ubuntu Subiquity 安装器的 iSCSI 盲区**

   官方安装器在磁盘选择界面完全隐藏 iSCSI 设备。放弃图形化安装，采用 `debootstrap` 直接从源拉取纯净系统，实现"降维打击"式部署。

7. **Ubuntu ISO 的多层 Overlay 结构陷阱**

   提取 squashfs 后发现缺少 `bash` 等核心命令，验证了官方 ISO 采用分层架构，果断切换至 `debootstrap` 方案，确保系统完整性。

8. **纯净系统的 iSCSI 模块缺失**

   `debootstrap` 拉取的最小系统未预设任何 iSCSI 启动逻辑。显式注入 `iscsi_tcp`、`libiscsi` 等内核模块，手动构建包含 `node.startup = automatic` 的完整节点配置，并使用 UUID 替代设备路径实现跨硬件兼容。

## Windows 专项攻坚

9. **Windows PE 阶段的网络死锁与 ADK 依赖**

   利用 `dism++` 离线注入万能驱动全家桶（vmxnet3、pvscsi、iastorvd 等），打破 PE 阶段无网卡驱动的死锁，并完美避开微软 ADK 的版本限制；结合 `--device-type cd` 挂载 ISO，让安装程序像读取物理光盘一样顺畅完成部署。

## 控制面与基础设施攻坚

10. **dnsmasq 文件级挂载的 inode 陷阱**

    `dhcp-hosts.conf` 以文件级 bind mount 挂入容器，挂载锁定的是写入瞬间的 inode；原实现的 rename 原子写每次更换 inode，导致容器内永远读到旧文件、HUP 重载形同虚设，只有重建容器重新挂载才生效。改为直接截断写原文件（保持 inode 不变），文件级挂载语义不再被破坏，HUP 重载恢复有效。

11. **LIO 后端的 iSCSI root 连接符不兼容**

    stgt 的 root-path 需要 `:::1:`（lun 占位 1），LIO 后端则要求 `::::`（空占位）。若统一按 stgt 格式拼装，LIO 上的 iSCSI 挂载将失败。`/boot-vars` 按系统盘所在 Agent 的后端类型投影差异连接符（`iscsi-sep`），root-path 拼装保留在 iPXE 静态侧，`boot.ipxe.cfg` 再用 `isset` 守卫防止静态兜底值覆盖已下发的 LIO 格式。

12. **真实 iPXE 固件的 `${mac:hexraw}` 展开异常**

    官方文档惯用的 `${mac:hexraw}` 修饰符在真实 iPXE 设备上展开为空，MAC 参数丢失导致后端无法识别、自动注册失效；改用带冒号格式 `${mac}` 后一切正常，后端归一化剥离冒号/横线/点号，两种格式均可识别。

13. **Zero-touch 自动注册的"静默失效"**

    `boot.ipxe.cfg` 中 controller IP 若残留模板默认值、与真实网段不符，iPXE 请求 `/boot-vars` 不可达后 `|| goto` 静默跳过，后端从未收到请求——现象是"worker 拿不到 hostname、也不重启"。改为 `set controller_ip ${next-server}`（同机部署下即 DHCP 服务器 IP），零硬编码，更换网段无需改脚本。

14. **WebUI 白屏：null 解引用**

    Agent 角色计算在组件首次渲染（`agent` 为 null）即执行，`TypeError: Cannot read properties of null (reading 'role')` 导致 React 整树卸载白屏，API 请求都来不及发出。修复：在空态分支之后再计算角色。

15. **确认弹窗被容器边界裁剪**

    弹窗以 `position: absolute` 挂在触发按钮下方展开，而卡片容器 `overflow: hidden` 将展开部分裁掉（批量侧边栏同样存在该隐患）。改为 `position: fixed` 全屏遮罩 + 居中弹窗，不再依赖触发按钮的定位上下文，任何容器都无法裁剪。
