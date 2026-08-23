# 第三章：Debian 12 无盘启动技术攻坚

> **早期探索声明**：本文为项目早期探索记录，所述方案与当前架构存在差异，仅供底层研究参考。

Debian 12 是 `iPXE-All-Ready` 项目首个攻克的操作系统，也是探索过程中遇到技术阻碍最多的环节。本章以 Debian 为主线展开，这不仅因为其底层引导机制具有较高的复杂性，更因为在部署过程中，完整验证并解决了这些长期存在的工程痛点。

在 2021 年的 iPXE 官方邮件列表中，iPXE 核心维护者 Michael Brown 在探讨 Debian 的 iSCSI 启动问题时曾坦言：“I've tried previously and given up”（我曾尝试过，但放弃了）。社区成员在回复中也明确指出：“For booting from iSCSI/SAN, it seems they don't support it”（对于从 iSCSI/SAN 启动，似乎官方并不支持），并得出结论：“There is no way to do this with the standard Debian initrd.”（使用标准的 Debian initrd 无法做到这一点）。

> [!NOTE]
> 此处参考文章：[[ipxe-devel] Diskless Client Centos via iSCSI](https://lists.ipxe.org/pipermail/ipxe-devel/2021-February/007377.html)

`iPXE-All-Ready` 项目的初衷，并非重复已有的常规操作，而是为了填补这一长期存在的技术空白。

解决 Debian 无盘启动的全链路过程确实棘手。但 iPXE 项目诞生至今已逾十余年，在 2026 年的今天，基础架构的拼图不应再留下这块缺口。如果没有人去做底层的适配与验证，这个“no way”的结论可能还会继续延续。

经过数日的调试与对 initramfs 打包机制的深度剖析，Debian 12 最终顺利从无盘环境中启动。

## 3.1 宏观整体分析：Debian 无盘启动的工程挑战与方法论	

在深入具体的部署路线之前，需要从系统引导的底层机制出发，剖析 Debian 无盘启动面临的核心工程挑战。理解这些难点，是掌握本章三条部署路线以及后续适配其他 Linux 发行版的基础。

#### 核心难点剖析

Debian 无盘启动的工程挑战主要集中在早期用户空间（Initramfs）的状态持久化、安装器（d-i）的配置继承机制以及网络块设备的寻址稳定性三个维度。

*   **Initramfs 阶段的状态持久化缺失**
    Linux 内核的引导流程要求在挂载根文件系统（Rootfs）之前，由 Initramfs 提供必要的驱动与挂载逻辑。当根文件系统驻留于 iSCSI 网络存储时，Initramfs 必须在极早期完成网络栈的初始化并执行 iSCSI 会话登录。然而，Debian 默认的 `initramfs-tools` 框架在处理网络根文件系统时，其内置的 Hook 脚本未能自动捕获并打包用户自定义的 iSCSI 连接参数，亦未强制包含必要的内核模块（如 `iscsi_tcp`）与用户态工具（如 `iscsistart`）。此机制缺陷导致内核在 Initramfs 阶段无法建立存储连接，最终引发 `VFS: Unable to mount root fs` 错误。
*   **安装器（d-i）的配置继承断层**
    Debian 官方网络安装器（d-i）具备在部署阶段发现并登录 iSCSI Target 的能力，从而将系统文件释放至网络 LUN。但在部署完成向本地系统移交控制权时，安装阶段建立的 iSCSI 会话参数与网络配置未能正确持久化至目标系统的 Initramfs 配置中。此外，标准 netboot 流程在软件包选择上存在限制（如默认绑定特定桌面环境），难以适应高度定制化的部署需求。
*   **网络块设备的拓扑漂移与寻址失效**
    在 iSCSI 存储拓扑中，块设备的枚举顺序受网络延迟、会话建立时序及控制器扫描顺序的影响。系统重启或硬件拓扑变更时，设备节点路径（如 `/dev/sda`）具有高度易变性。若目标系统的 `/etc/fstab` 依赖静态设备路径挂载根分区，将直接导致引导失败。因此，必须强制采用文件系统的 UUID 或 PARTUUID 作为挂载标识。

#### 三条路线的工程定位

针对上述难点以及不同的业务场景需求，本章提供三条独立的部署路线。每条路线均为完整的闭环，旨在从不同维度解决系统构建与 Initramfs 修复的问题。

*   **路线一：基于官方 netboot 安装器**
    此路线旨在重现并验证标准的网络安装流程。通过实际操作，可以直观地观察到官方安装器在 iSCSI 环境下的表现，并验证安装后 Initramfs 配置丢失的问题，随后通过 `chroot` 进行修复。
*   **路线二：虚拟机镜像转换与定制**
    当目标系统需要复杂的桌面环境、专有软件栈或特定的系统参数时，网络安装器往往力不从心。此路线通过在本地虚拟机中完成完整的系统安装与定制，随后将虚拟磁盘转换为 raw img 格式并注入 iSCSI 启动依赖，解决了系统安装多样化的问题。
*   **路线三：使用 debootstrap 构建纯净骨架**
    针对追求极致纯净、最小化体积和自动化部署的服务器场景，此路线绕过所有图形化或交互式安装器，直接通过 `debootstrap` 从镜像源拉取基础系统包，并在 `chroot` 环境中完成底层依赖的精准注入。

#### 方法论的推广意义

本章所提供的核心方法论——**“绕过官方安装器限制、直接构建或转换系统镜像、通过 chroot 深度定制 Initramfs Hook”**，不仅解决了 Debian 的问题，也是攻克大多数基于 `initramfs` 引导机制的 Linux 发行版（如 Ubuntu、Arch Linux、RHEL 系）无盘启动的通用范式。

## 3.2 路线一：基于官方 netboot 安装器

在 `iPXE-All-Ready` 项目仓库的 `tftp/menu.ipxe` 中，已经预置了 Debian 12 的安装调度逻辑。无需手动修改该脚本，只需理解其配置内容，并按照要求准备好相应的 HTTP 资源文件。

以下是 `menu.ipxe` 中关于 Debian 安装项的核心代码片段：

```ipxe
:debian-install
echo Starting Debian 12 installer for ${initiator-iqn}
set root-path iscsi:${storager-ip}${iscsi-sep}${base-iqn}:${hostname}.Debian
cpuid --ext 29 && set arch amd64 || set arch x86
set base-url http://${controller_ip}:88/Install/Debian/12
kernel ${base-url}/netboot/vmlinuz \
    auto=true \
    priority=critical \
    url=${base-url}/preseed.cfg \
    ipv6.disable=1 \
    netcfg/disable_autoconfig=true \
    mirror/country=manual \
    mirror/http/hostname=mirrors.tuna.tsinghua.edu.cn \
    mirror/http/directory=/debian \
    mirror/suite=bookworm \
    ---
initrd ${base-url}/netboot/initrd.gz
boot || goto failed
goto start
```

#### 配置解析

1. **变量传递与架构识别**
   脚本利用 1.5 节中建立的变量链，动态拼接出当前 Worker 专属的 iSCSI Target 路径（`${root-path}`）。同时，通过 `cpuid --ext 29` 指令检测 CPU 是否支持 64 位长模式，从而动态设置 `${arch}` 变量。
2. **网络初始化与基础环境辅助**
   参数 `auto=true`、`priority=critical` 以及 `url=.../preseed.cfg` 用于在安装极早期加载基础的预配置文件。该文件主要用于辅助完成网络接口的初始化等底层环境准备。网络就绪后，后续的系统安装流程（如语言、分区、软件包选择等）均在安装器界面中手动交互完成。
3. **网络配置控制**
   `netcfg/disable_autoconfig=true` 与 `ipv6.disable=1` 禁用了安装器默认的部分网络自动配置行为并关闭 IPv6，避免在多网卡或复杂的 iSCSI 网络环境下出现路由冲突或初始化卡顿。

为了让上述脚本正常工作，需要在 Controller 节点的 HTTP 资源池（对应仓库目录 `www/`）中，创建 `Install/Debian/12/` 目录，并准备以下文件：

```text
www/Install/Debian/12/
├── preseed.cfg           # 基础环境预配置文件 (仓库已提供)
└── netboot/
    ├── vmlinuz           # Debian 12 官方 netboot 内核
    └── initrd.gz         # Debian 12 官方 netboot 初始化内存盘
```

**获取 netboot 文件：**
从 Debian 官方镜像源下载这两个文件，放置于 `netboot/` 目录下：

```bash
# 切换到项目仓库根目录下的 www/Install/Debian/12/netboot
wget http://deb.debian.org/debian/dists/bookworm/main/installer-amd64/current/images/netboot/debian-installer/amd64/linux -O vmlinuz
wget http://deb.debian.org/debian/dists/bookworm/main/installer-amd64/current/images/netboot/debian-installer/amd64/initrd.gz
```

**创建 Debian 专属的稀疏文件：**

```bash
# 请自定义硬盘镜像大小
fallocate -l 20G worker-01.debian.img
```

准备就绪后，执行 `docker compose up -d` 启动三个容器的编排。

运行自动化脚本注册 Target：

```bash
./iscsi-target-gen.sh
```

输出如下：

```text
root@vm-ubuntu:/home/dutyc/ipxe-all-ready# ./iscsi-target-gen.sh 
发现以下镜像文件：
  worker-01.Debian.img
使用基础IQN模板: iqn.2026-07.com.controller:<文件名/后缀>

创建 Target: iqn.2026-07.com.controller:worker-01.Debian (TID=1, 类型: IMG)
  创建 LUN 1 -> /home/iscsi_img/worker-01.Debian.img
  绑定访问策略 -> ALL

显示当前所有 Target 配置:
Target 1: iqn.2026-07.com.controller:worker-01.Debian
    System information:
        Driver: iscsi
        State: ready
    I_T nexus information:
    LUN information:
        LUN: 0
            Type: controller
            SCSI ID: IET     00010000
            SCSI SN: beaf10
            Size: 0 MB, Block size: 1
            Online: Yes
            Removable media: No
            Prevent removal: No
            Readonly: No
            SWP: No
            Thin-provisioning: No
            Backing store type: null
            Backing store path: None
            Backing store flags: 
        LUN: 1
            Type: disk
            SCSI ID: IET     00010001
            SCSI SN: beaf11
            Size: 21475 MB, Block size: 512
            Online: Yes
            Removable media: No
            Prevent removal: No
            Readonly: No
            SWP: No
            Thin-provisioning: No
            Backing store type: rdwr
            Backing store path: /home/iscsi_img/worker-01.Debian.img
            Backing store flags: 
    Account information:
    ACL information:
        ALL
root@vm-ubuntu:/home/dutyc/ipxe-all-ready# 
```

使用 `curl` 和 `wireshark` 测试 HTTP 端点的状态，确保正常访问。

**创建 Worker 虚拟机：**
创建一台虚拟机，配置 2 核 4GB 内存，建议使用 UEFI 启动模式（BIOS 启动模式亦可，但界面会有些许差异），与 Controller 同 NAT 网段（`192.168.80.0/24`）。
此时局域网的基础参数如下：Controller IP 为 `192.168.80.3`，局域网网关为 `192.168.80.2`。

#### **安装过程与 iSCSI 配置**

启动无盘虚拟机，第一次启动可以看到以 MAC 地址拼接的 IQN，记录下 MAC 地址（此虚拟机 MAC 为 `00:0c:29:b9:8b:2d`）。

![屏幕截图 2026-07-17 151113](/assets/%E5%B1%8F%E5%B9%95%E6%88%AA%E5%9B%BE%202026-07-17%20151113.png)

编辑项目仓库中的 `dnsmasq/dhcp-hosts.conf` 文件，添加以下主机名分配：

```text
00:0c:29:b9:8b:2d,worker-01
```

然后重载 `dnsmasq` 容器的配置：

```bash
docker exec ipxe-dnsmasq killall -HUP dnsmasq
```

再次启动无盘虚拟机，可以看到以主机名拼接的基础 IQN 地址。

![image-20260717152039637](/assets/image-20260717152039637.png)

选择 `Installers` 选项，选择 `Hook Debian ${arch} iSCSI and install` 选项，下载所需文件，启动 netboot。

![屏幕截图 2026-07-17 155438](/assets/%E5%B1%8F%E5%B9%95%E6%88%AA%E5%9B%BE%202026-07-17%20155438.png)

安装器随后会提示为该 Worker 配置 IP 地址。此处配置的是安装程序运行时的网络环境，不会继承至 Debian 系统启动阶段，因此分配一个未被占用的 IP 即可，此处填写 `192.168.80.40/24`。

![image-20260717155806096](/assets/image-20260717155806096.png)

配置网关，填写该局域网内的网关地址 `192.168.80.2`。

![屏幕截图 2026-07-17 155854](/assets/%E5%B1%8F%E5%B9%95%E6%88%AA%E5%9B%BE%202026-07-17%20155854.png)

配置 DNS 服务器，填写 `223.5.5.5`。

![image-20260717160243132](/assets/image-20260717160243132.png)

进行语言选择。

![image-20260717160315226](/assets/image-20260717160315226.png)

随后进入镜像源配置阶段。需根据实际网络环境填写镜像源地址，否则会导致下载速度缓慢。该 netboot 安装程序默认会安装 GNOME 桌面环境（若需大规模部署，建议在局域网内搭建 deb 包缓存镜像站以提升效率）。此处配置为阿里云镜像源。

![image-20260717160738849](/assets/image-20260717160738849.png)

安装器将检查镜像可用性。若此步骤顺利通过，则表明网络配置正确；若提示连接错误且镜像源地址拼写无误，则需排查 IP 地址、网关或 DNS 配置是否存在异常。

![image-20260717160944807](/assets/image-20260717160944807.png)

随后进入 root 密码及常规用户设置环节，按常规流程配置即可。

![image-20260717161241983](/assets/image-20260717161241983.png)

完成账号设置后，安装器将提示配置 iSCSI 相关参数，选择 `Configure iSCSI volumes`。

![image-20260717161523200](/assets/image-20260717161523200.png)

界面出现以下提示：

```text
[! !] Partition disks
This menu allows you to configure iSCSI volumes.
iSCSI configuration actions

>Log into iSCSI targets
>Finish
```

选择 `Log into iSCSI targets`。

![image-20260717161807430](/assets/image-20260717161807430.png)

在 `iSCSI target portal address:` 提示符后，输入 iSCSI Server IP（本次部署中 Controller 与 iSCSI Server 同机，故填写 `192.168.80.3`）。

随后系统会要求输入认证账号与密码。由于 Target 端未配置 CHAP 认证，此处任意输入字符以满足安装器的表单校验逻辑即可完成连接。

![image-20260717162219109](/assets/image-20260717162219109.png)

部分情况下，安装器可能会要求重复输入一次凭据以确认连接，视具体提示进行操作即可。

连接成功后，界面将列出可用的 iSCSI Target，按空格键勾选目标，按 Tab 键切换至 `<Continue>` 并回车。

![image-20260717162430661](/assets/image-20260717162430661.png)

此时界面可能会提示 iSCSI 连接丢失：

```text
[! !] Partition disks

iSCSI login failed
Logging into the iSCSI target iqn.2026-07.com.controller:worker-01.Debian on 192.168.80.3:3260 failed.

Check /var/log/syslog or see virtual console 4 for the details.

<Continue>
```

![image-20260717162648543](/assets/image-20260717162648543.png)

针对此报错，需进行链路排查。首先检查 **Controller** 节点的 docker compose 状态：

```bash
root@vm-ubuntu:/home/dutyc/ipxe-all-ready# docker compose ps
NAME           IMAGE                                                                                      COMMAND                  SERVICE        CREATED             STATUS             PORTS
ipxe-dnsmasq   jpillora/dnsmasq@sha256:98b69ad825942089fb7c4b9153e3c5af0205eda3a103c691e30b1a13fd912830   "/usr/sbin/dnsmasq --…"   ipxe-dnsmasq   About an hour ago   Up About an hour   
storager-iscsi   wtnb75/stgt@sha256:1b609555f26bb7a2b2a49a093eff8473e196a8cff49acc684345020eb79f813e        "tgtd -f"                storager-iscsi     About an hour ago   Up About an hour   
ipxe-nginx     nginx@sha256:54f2a904c251d5a34adf545a72d32515a15e08418dae0266e23be2e18c66fefa              "/docker-entrypoint.…"   ipxe-nginx     About an hour ago   Up About an hour   0.0.0.0:88->80/tcp, [::]:88->80/tcp
root@vm-ubuntu:/home/dutyc/ipxe-all-ready# 
```

确认 iSCSI 容器状态正常，且历史输出显示 LUN 已成功创建。

为验证 iSCSI 服务本身的可用性，可直接在 **Controller** 所在的 Ubuntu 环境中安装 `open-iscsi` 工具并尝试连接（生产环境中建议使用独立的 Linux 节点进行验证）。若外部节点可正常挂载，则说明 iSCSI 服务端配置无误，问题局限于安装器环境。

安装 `open-iscsi`：

```bash
sudo apt update
sudo apt install open-iscsi -y

# 启动并设置开机自启
sudo systemctl enable --now iscsid.service
sudo systemctl status iscsid.service
```

发现并连接 iSCSI Server 的 Target：

```bash
# 请根据实际情况替换 <TARGET_IP>
sudo iscsiadm -m discovery -t sendtargets -p <TARGET_IP>:3260
```

输出如下：

```bash
root@vm-ubuntu:/home/dutyc/ipxe-all-ready# sudo iscsiadm -m discovery -t sendtargets -p 192.168.80.3:3260
192.168.80.3:3260,1 iqn.2026-07.com.controller:worker-01.Debian
root@vm-ubuntu:/home/dutyc/ipxe-all-ready# 
```

**登录所有已发现的 Target：**

```bash
sudo iscsiadm -m node -l
```

**或指定登录某个 Target：**

```bash
sudo iscsiadm -m node -T iqn.2026-07.com.controller:worker-01.Debian -p 192.168.80.3:3260 -l
```

登录成功后输出如下：

```bash
root@vm-ubuntu:/home/dutyc/ipxe-all-ready# sudo iscsiadm -m node -T iqn.2026-07.com.controller:worker-01.Debian -p 192.168.80.3:3260 -l
Logging in to [iface: default, target: iqn.2026-07.com.controller:worker-01.Debian, portal: 192.168.80.3,3260]
Login to [iface: default, target: iqn.2026-07.com.controller:worker-01.Debian, portal: 192.168.80.3,3260] successful.
root@vm-ubuntu:/home/dutyc/ipxe-all-ready# 
```

登录成功后，iSCSI LUN 将作为本地 SCSI 块设备呈现：

```bash
# 查看新增块设备
lsblk
```

输出中应显示与配置镜像大小一致的新磁盘（如 `/dev/sdc` 20G）。

既然外部节点连接与登录均成功，说明安装器界面的报错属于状态刷新导致的“假报错”。

经过测试，在红色警告界面同时按下 `Shift + F4` 组合键，界面会跳转回之前的 iSCSI 配置菜单：

```text
[! !] Partition disks

This menu allows you to configure iSCSI volumes.

iSCSI configuration actions

Log into iSCSI targets
Finish <---选择这个

<Go Back>
```

选择 `Finish` 并回车。

![image-20260717183827148](/assets/image-20260717183827148.png)

随后界面将正常跳转至硬盘分区阶段。在此界面可正常完成分区操作，进一步证实 iSCSI 硬盘实际上已成功连接。

![image-20260717184018562](/assets/image-20260717184018562.png)

在设备列表中可明确观察到一块 21GB 的硬盘，确认 iSCSI 存储已就绪。

![image-20260717185939498](/assets/image-20260717185939498.png)

完成分区流程后，系统开始安装基础组件。在安装 `Base system` 阶段，偶发安装失败并提示重试的情况，通常重试后即可继续。若持续卡死，建议改用路线二进行部署。

如果你使用 BIOS 启动模式，在安装Grub时,会提示如下：

```
Configuring grub-pc

You need to make the newly installed system bootable, by installing
the GRUB boot loader on a bootable device. The usual way to do this
is to install GRUB to your primary drive (UEFI partition/boot
record). You may instead install GRUB to a different drive (or
partition), or to removable media.

The device notation should be specified as a device in /dev. Below
are some examples:
- "/dev/sda" will install GRUB to your primary drive (UEFI
partition/boot
record);
"/dev/sdb" will install GRUB to a secondary drive (which may for
instance
be a thumbdrive);

<Go Back>

<Continue>
```

我们需要输入 `/dev/sda`，尝试安装 GRUB 启动器。此时有可能安装失败，不必担心，后续在 chroot 环境中可以手动安装补救。

最终，安装流程将抵达重启提示界面。

![image-20260717194257384](/assets/image-20260717194257384.png)

在此界面，由于 Initramfs 存在前文所述的配置断层缺陷，必须拦截重启流程并手动修复系统文件。修复方式有两种：其一，在当前界面按下 `Shift + F8` 呼出 `[! !] Debian installer main menu`，选择 `Execute a shell` 进入底层命令行环境，通过 `chroot` 修改配置。

#### **修复 initramfs 与 GRUB 配置**

当 Debian 安装程序完成所有文件的释放，提示 **"Installation complete"** 并准备重启时，**切勿直接选择 Continue**。

由于 Debian 官方安装器（d-i）在 iSCSI 环境下的配置继承缺陷，此时直接重启必然会导致 `VFS: Unable to mount root fs` 的 Kernel Panic。我们需要在安装流程的最后一步进行拦截，并手动修复目标系统的 Initramfs 配置。

1. 修复环境的选择：BusyBox 还是外部挂载？

在 "Installation complete" 界面，你可以按下组合键 `Shift + F8`，呼出 `[! !] Debian installer main menu` 菜单，选择 `Execute a shell` 选项，进入 d-i 底层的 BusyBox 命令行环境。

![image-20260717194651747](/assets/image-20260717194651747.png)

成功进入 Shell 后，理论上你可以直接通过以下命令挂载 `/target` 并进行 `chroot`：

```bash
# 在 BusyBox 环境中挂载目标系统的文件系统
mount --bind /dev /target/dev
mount --bind /proc /target/proc
mount --bind /sys /target/sys

# 切换到目标系统环境
chroot /target /bin/bash
```

![image-20260717194929225](/assets/image-20260717194929225.png)

**工程建议**：虽然上述方法可行，但**不建议**在安装程序的 BusyBox 命令行中进行复杂的 `chroot` 和文件编辑操作。BusyBox 环境极其简陋，无法便捷地复制粘贴长命令（如编写 Hook 脚本），且缺乏完整的终端支持，极易因拼写错误导致修复失败。

**更优的方案**是：放弃在 BusyBox 中操作，转而利用 iSCSI 块存储与计算节点解耦的特性，在另一台 Linux 设备（如 Controller 宿主机）上直接挂载该 Worker 的 iSCSI 硬盘，然后进行 `chroot` 修改。这样不仅能使用完整的终端环境，还能方便地记录报错日志。

2. 释放 iSCSI 锁（关键前置操作）

如果你选择上述的“外部挂载”方案，**必须首先将正在运行安装程序的 Worker 虚拟机彻底关机**。

*原因解释*：iSCSI 协议在底层依赖 SCSI 指令集。如果 Worker 虚拟机（Initiator A）和 Controller 宿主机（Initiator B）同时连接并挂载同一个 iSCSI Target（LUN），会导致严重的 SCSI 锁冲突。两个系统会同时尝试写入文件系统元数据，轻则导致文件系统损坏（Filesystem Corruption），重则直接引发内核 Panic。彻底关机可确保 Worker 释放 LUN 的控制权。

3. 在外部 Linux 设备上挂载 LUN 并 Chroot

确认 Worker 虚拟机已关机后，在 Controller 宿主机（或其他同网段的 Linux 设备）上执行以下操作：

**发现并登录 Target：**

```bash
# 发现 Target (请将 <TARGET_IP> 替换为 Controller 的真实 IP，如 192.168.80.3)
sudo iscsiadm -m discovery -t sendtargets -p <TARGET_IP>:3260
# 预期输出: 192.168.80.3:3260,1 iqn.2026-07.com.controller:worker-01.Debian

# 登录到指定的 IQN
sudo iscsiadm -m node -T iqn.2026-07.com.controller:worker-01.Debian -p <TARGET_IP>:3260 -l
```

**验证磁盘与分区结构：**

使用 `lsblk` 查看新挂载的块设备：

```bash
lsblk
```

输出示例：

```text
sdc      8:32   0   20G  0 disk 
├─sdc1   8:33   0  512M  0 part  # UEFI ESP 分区
├─sdc2   8:34   0 18.5G  0 part  # Debian 根分区 (/)
└─sdc3   8:35   0  976M  0 part  # Swap 交换分区
```

*注：在 UEFI 模式下，Debian 安装器会自动创建一个 512M 的 EFI 系统分区（sdc1）。我们需要挂载的是根分区（sdc2）。*

**挂载根分区并进入 Chroot 环境：**

```bash
# 创建挂载目录
sudo mkdir -p /mnt/worker-01

# 挂载根分区 (请根据 lsblk 的实际输出替换 /dev/sdc2)
sudo mount /dev/sdc2 /mnt/worker-01

# 绑定必要的虚拟文件系统
sudo mount --bind /dev /mnt/worker-01/dev
sudo mount --bind /proc /mnt/worker-01/proc
sudo mount --bind /sys /mnt/worker-01/sys

# 切换到目标系统环境
sudo chroot /mnt/worker-01 /bin/bash
```

4. 验证“配置断层”：官方安装器到底漏了什么？

为了证实社区中关于 "There is no way to do this with the standard Debian initrd" 的论断，以及我们进行“灵魂注入”的必要性，我们可以检查一下官方安装器到底有没有将 iSCSI 相关的配置继承到本地系统中。

在 `chroot` 环境中，查看 Initramfs 的模块加载列表：

```bash
cat /etc/initramfs-tools/modules
```

输出内容通常如下：

```text
# List of modules that you want to include in your initramfs.
# They will be loaded at boot time in the order below.
#
# Syntax:  module_name [args ...]
#
# You must run update-initramfs(8) to effect this change.
#
# Examples:
#
# raid1
# sd_mod
```

**结论**：列表中完全没有 `iscsi_tcp` 或 `ib_iser` 等 iSCSI 核心模块。这直接证明了 Debian 官方安装器在释放系统文件后，并未将安装阶段建立的 iSCSI 连接参数和底层驱动打包进本地的 `initrd.img` 中。

当系统重启，内核加载这个残缺的 `initrd.img` 时，自然无法在极早期连接网络存储，从而导致根文件系统挂载失败。

接下来，我们将在这个 `chroot` 环境中，手动补齐这些缺失的拼图，完成真正的“灵魂注入”。

5. 执行“灵魂注入”：补齐 Initramfs 与 GRUB 配置

进入 `chroot` 环境后，我们需要手动补齐 Debian 官方安装器遗漏的 iSCSI 启动依赖。这是确保系统重启后能够顺利挂载网络根文件系统的核心步骤。

**步骤 1：检查并安装 open-iscsi**

首先更新软件源，并检查 `open-iscsi` 软件包是否已被安装。如果安装器在释放系统时未包含该包，需要手动安装。

```bash
dpkg -l | grep open-iscsi
# 若未安装，则执行：
# apt update
# apt install -y open-iscsi
```

**步骤 2：注入 iSCSI 内核模块**

Initramfs 在启动早期需要加载特定的内核模块才能识别 iSCSI 设备。将 `iscsi_tcp` 和 `ib_iser` 添加到模块加载列表中：

```bash
# 将 iSCSI 模块添加到 initramfs 加载列表
echo "iscsi_tcp" >> /etc/initramfs-tools/modules
echo "ib_iser" >> /etc/initramfs-tools/modules

# 验证是否添加成功
cat /etc/initramfs-tools/modules
```

**步骤 3：配置 iSCSI 自动登录**

修改 `iscsid.conf` 配置文件，确保 iSCSI Initiator 在系统启动时自动尝试连接 Target，而不是等待手动触发。

```bash
# 修改 iscsid.conf，设置自动启动
sed -i 's/#node.startup = manual/node.startup = automatic/' /etc/iscsi/iscsid.conf
sed -i 's/node.startup = manual/node.startup = automatic/' /etc/iscsi/iscsid.conf

# 验证修改
grep "node.startup" /etc/iscsi/iscsid.conf
# 预期输出应包含：node.startup = automatic
```

**步骤 4：修改 GRUB 内核启动参数**

查看 GRUB 配置文件 `/etc/default/grub`，通常会发现 `GRUB_CMDLINE_LINUX_DEFAULT` 为 `quiet` , `GRUB_CMDLINE_LINUX` 处于空状态。

我们需要编辑 `GRUB_CMDLINE_LINUX_DEFAULT` 变量，注入 `ip=dhcp` 以确保内核在 Initramfs 阶段能够自动获取 IP 地址，并添加 `ipv6.disable=1` 避免网络初始化延迟。`GRUB_CMDLINE_LINUX` 保持为空即可。

```bash
# 使用 sed 替换 GRUB_CMDLINE_LINUX_DEFAULT 的值
sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT=".*"/GRUB_CMDLINE_LINUX_DEFAULT="text ip=dhcp ipv6.disable=1"/' /etc/default/grub

# 验证修改结果
grep "ip=dhcp" /etc/default/grub
# 预期输出：GRUB_CMDLINE_LINUX_DEFAULT="text ip=dhcp ipv6.disable=1"
```

*注：此处加入 `text` 参数是为了在启动时输出详细的控制台日志，便于观察 Initramfs 阶段的 iSCSI 连接状态。*

**步骤 5：重建 Initramfs 并验证打包结果**

这是最关键的一步。执行 `update-initramfs` 强制重新生成包含上述模块和配置的 `initrd.img`。

为了确保模块被正确打包，建议将执行结果重定向到文本文件中，并通过 `grep` 搜索 `iscsi` 相关的行进行验证。

```bash
# 重建所有内核版本的 initramfs，并将输出保存到日志文件
update-initramfs -u -k all > /tmp/initramfs_build.log 2>&1

# 搜索日志中关于 iscsi 模块的打包记录
grep -i "iscsi" /tmp/initramfs_build.log
```

**预期验证结果**：
在输出的日志中，应该能看到类似 `Adding module iscsi_tcp` 或 `Copying module iscsi_tcp` 的字样。如果日志中没有任何关于 `iscsi` 的记录，或者出现 `module not found` 的报错，说明内核模块未成功注入，需要返回步骤 2 检查模块名称或重新安装相关内核头文件。

与 BIOS 模式下必须手动重写 MBR 不同，UEFI 模式下的 Debian 安装器通常已经成功将 GRUB 的 EFI 文件释放到了 ESP 分区。iPXE 的 `sanboot` 会直接读取该 ESP 分区进行链式加载，因此不依赖主板 NVRAM 的启动项。但为了排除 iSCSI 网络环境导致的模块打包瑕疵，我们仍在 chroot 中执行一次带有 `--no-nvram` 参数的 `grub-install` 作为防御性巩固，确保万无一失。

确认 GRUB **启动器安装状态**

**UEFI 启动模式：**

**创建挂载点并挂载 ESP 分区**
根据我们之前 `lsblk` 的输出，`/dev/sdc1` 是那个 512M 的 EFI 系统分区。在 `chroot` 环境中执行：

```bash
# 确保目录存在
mkdir -p /boot/efi

# 挂载 EFI 系统分区 (请根据你实际的 lsblk 输出确认设备名，通常是 /dev/sdc1)
mount /dev/sdc1 /boot/efi
```

**验证挂载状态**
确认该分区已经被正确识别为 FAT32 文件系统：

```bash
df -h | grep /boot/efi
ls -l /boot/efi
```

*预期结果*：`df -h` 应该显示 `/dev/sdc1` 挂载在 `/boot/efi`，类型为 `vfat`。`ls` 应该能看到 `EFI` 目录。

**重新执行 UEFI GRUB 安装**
现在 `/boot/efi` 已经就绪，再次执行带有 `--no-nvram` 参数的防御性安装命令：

```bash
grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=debian --recheck --no-nvram
```

*预期结果*：终端应输出 `Installation finished. No error reported.`（安装完成，无错误报告）。

**BIOS 启动模式：**
请务必执行以下命令将 GRUB 安装到 iSCSI 磁盘（假设 iSCSI 硬盘设备为 `/dev/sdc`），确保万无一失：

```bash
grub-install /dev/sdc
grub-install --recheck /dev/sdc
```

**更新 GRUB 配置（UEFI 和 BIOS 模式都必须执行）**
最后，确保 `grub.cfg` 包含了我们之前注入的 `ip=dhcp` 等内核参数：

```bash
update-grub
```

**验证关键文件**

```bash
# 检查 initramfs 是否包含 iscsi 模块
ls -lh /boot/initrd.img-*

# 检查 GRUB 配置
cat /boot/grub/grub.cfg | grep -A 5 "menuentry" | head -20
```

然后退出 chroot：

```
exit
```

**清理环境与释放 iSCSI 锁**

此时不能急着启动 Worker 虚拟机，**务必先断开 iSCSI 连接**，否则会导致 SCSI 锁冲突，轻则文件系统损坏，重则内核 Panic。

执行以下命令安全断开：

```bash
# 卸载目录
sudo umount /mnt/worker-01/dev /mnt/worker-01/proc /mnt/worker-01/sys
sudo umount /mnt/worker-01
# 登出 iSCSI Target
sudo iscsiadm -m node -T iqn.2026-07.com.controller:worker-01.Debian -p 192.168.80.3:3260 -u
```

现在启动 Worker 虚拟机，尝试进行 iSCSI 启动。

由于该系统是通过官方安装器部署的，`open-iscsi` 服务已在安装阶段记录了 Target 的连接信息，因此系统启动后会自动维持 iSCSI 会话，无需额外配置。

如果一切顺利，可以看到 GNOME 桌面环境启动，至此 netboot 安装 Debian 的任务完成。

![image-20260704120832240](/assets/image-20260704120832240.png)

## 3.3 路线二：虚拟机镜像转换与定制

#### 工程定位与决策树

当目标系统需要复杂的桌面环境、专有的闭源驱动（如 NVIDIA 显卡驱动）、特定的商业软件栈，或者官方 netboot 安装器因网络波动和硬件兼容性问题反复失败时，路线一的标准流程会显得力不从心。

路线二采用“降维打击”的策略：在本地虚拟化平台中利用完整的 Debian ISO 镜像进行常规安装，完成所有高度定制化的配置后，将虚拟磁盘转换为 raw 格式，并通过外部 `chroot` 注入 iSCSI 启动依赖。这种方式彻底绕过了网络安装器的限制，将“系统构建”与“无盘适配”解耦。

为了适应不同的工程环境，本路线提供以下选择决策树：

*   **虚拟化构建平台**：VMware Workstation / VirtualBox / Proxmox VE (PVE)。
*   **磁盘格式转换工具**：`qemu-img` (Linux 命令行) / StarWind V2V Converter (Windows GUI) / `VBoxManage` (VirtualBox 自带)。
*   **镜像挂载方式**：iSCSI 网络挂载 / 本地 Loop 设备挂载。

**核心安全原则：外部 Chroot 修改**
理论上，可以直接在运行中的虚拟机内部安装 `open-iscsi` 并重建 `initramfs`。但工程实践中**强烈不建议**这样做。在系统运行时修改底层引导依赖，极易因误操作导致虚拟机本身失去本地启动能力，从而破坏原始模板。通过外部挂载并 `chroot` 进行修改，能够确保原始虚拟机镜像始终处于“安全、可回滚”的纯净状态。

#### 本地虚拟机环境下的系统构建

在选定的虚拟化平台中创建一台新的 Debian 12 虚拟机。

*   **硬件配置**：根据目标 Worker 的物理硬件规格，分配相应的 CPU、内存，并添加一块本地虚拟硬盘（建议 20GB 或以上）。
*   **固件类型**：根据目标物理机的引导模式，严格选择 UEFI 或 BIOS (Legacy)。
*   **系统安装与定制**：挂载 Debian 12 完整 ISO 镜像，按照常规流程进行系统安装。在此阶段，可以自由配置桌面环境（如 KDE、XFCE）、安装专有驱动、配置业务软件及系统参数。
*   **引导加载器**：确保 GRUB 被正确安装到该虚拟硬盘的引导扇区（BIOS）或 EFI 系统分区（UEFI）。

安装与定制完成后，**彻底关闭虚拟机**。

#### 虚拟磁盘格式转换

iSCSI Target 和 iPXE 需要标准的 raw 块设备格式，而虚拟化平台通常使用特定的磁盘格式（如 `.vmdk`、`.vdi` 或 `.qcow2`）。需根据所处环境选择合适的转换工具。

**方案 A：使用 `qemu-img` (推荐，适用于 Linux Controller)**
在 Controller 节点安装 `qemu-utils` 并执行转换：

```bash
sudo apt install qemu-utils -y
# 将 vmdk/qcow2 转换为 raw img 格式
qemu-img convert -f vmdk -O raw debian-vm-disk.vmdk worker-02.Debian.img
```

**方案 B：使用 StarWind V2V Converter (适用于 Windows 环境)**
若虚拟机文件存放在 Windows 宿主机上，可下载 StarWind V2V Converter (GUI 工具)。选择源 `.vmdk` 或 `.vdi` 文件，目标格式选择 `Raw` (或 `IMG`)，直接导出为 `worker-02.Debian.img`。

**方案 C：使用 `VBoxManage` (适用于 VirtualBox 用户)**
若使用 VirtualBox，可直接调用其内置工具进行克隆：

```bash
VBoxManage clonemedium disk debian-vm-disk.vdi worker-02.Debian.img --format RAW
```

**镜像挂载方案选择**

转换得到的 `.img` 文件包含完整的分区表，需将其映射为块设备以便后续挂载。

**方案 A：本地 Loop 设备挂载 (最便捷)**
利用 Linux 的 Loop 机制直接映射本地文件：

```bash
# 关联到 loop 设备并自动扫描分区 (-P 参数)
sudo losetup -fP worker-02.Debian.img
# 查看分配的 loop 设备 (如 /dev/loop0)
lsblk
```

**方案 B：iSCSI 网络挂载 (适用于跨节点操作)**
若转换后的 `.img` 文件存放在 NAS 或独立的存储节点上，可通过 iSCSI 将其暴露给 Controller 节点进行挂载：

```bash
# 在存储节点将 img 文件作为 LUN 暴露 (临时 Target)
# 在 Controller 节点发现并登录
sudo iscsiadm -m discovery -t sendtargets -p <STORAGE_IP>:3260
sudo iscsiadm -m node -T <临时_IQN> -p <STORAGE_IP>:3260 -l
lsblk
```

#### Chroot 环境下的 iSCSI 依赖注入 

确认根分区设备节点（如 `/dev/loop0p2`）后，挂载并进入 `chroot` 环境：

```bash
sudo mkdir -p /mnt/debian-vm
sudo mount /dev/loop0p2 /mnt/debian-vm  # 请替换为实际根分区节点

sudo mount --bind /dev /mnt/debian-vm/dev
sudo mount --bind /proc /mnt/debian-vm/proc
sudo mount --bind /sys /mnt/debian-vm/sys

sudo chroot /mnt/debian-vm /bin/bash
```

由于路线二是通过本地 ISO 常规安装的，系统内部**完全没有** iSCSI 网络启动的配置。我们需要在 `chroot` 环境中从零构建这些底层依赖。

**1. 安装 open-iscsi 并配置自动登录**

```bash
apt update
apt install -y open-iscsi

sed -i 's/#node.startup = manual/node.startup = automatic/' /etc/iscsi/iscsid.conf
sed -i 's/node.startup = manual/node.startup = automatic/' /etc/iscsi/iscsid.conf
```

**2. 手动创建 `/etc/iscsi.initramfs` (身份注入)**
这是路线二最关键的一步。Debian 的 initramfs 启动脚本（`/scripts/local-top/iscsi`）在极早期会优先读取 `/etc/iscsi.initramfs` 中的硬编码参数。由于本地安装不会生成此文件，必须手动创建，并写入 Controller 的 IP 以及该 Worker 专属的 Target IQN。

```bash
cat > /etc/iscsi.initramfs << 'EOF'
ISCSI_TARGET_NAME="iqn.2026-07.com.controller:worker-02.Debian"
ISCSI_TARGET_IP="192.168.80.3"
ISCSI_TARGET_PORT="3260"
ISCSI_TARGET_GROUP="1"
EOF
```

**3. 改造官方 Hook 脚本 (降维打击)**
Debian 官方的 `update-initramfs` 工具存在逻辑盲区：它的 Hook 脚本**不会**自动将根目录下的 `/etc/iscsi.initramfs` 打包进 initrd。如果直接执行更新，该文件将被忽略。必须直接修改官方 Hook 脚本，强制注入复制逻辑。

```bash
# 在官方 iscsi hook 脚本的 exit 0 之前，插入 cp 命令
sed -i '/^exit 0/i cp /etc/iscsi.initramfs ${DESTDIR}/etc/iscsi.initramfs' \
  /usr/share/initramfs-tools/hooks/iscsi
```

**4. 注入内核模块与修改 GRUB**

```bash
echo "iscsi_tcp" >> /etc/initramfs-tools/modules
echo "ib_iser" >> /etc/initramfs-tools/modules

sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT=".*"/GRUB_CMDLINE_LINUX_DEFAULT="text ip=dhcp ipv6.disable=1"/' /etc/default/grub
```

**5. 处理 UEFI 模式的 ESP 分区 (仅限 UEFI)**
若虚拟机采用 UEFI 模式，必须挂载 ESP 分区（如 `/dev/loop0p1`）：

```bash
mkdir -p /boot/efi
mount /dev/loop0p1 /boot/efi
```

**6. 重建 Initramfs 与更新 GRUB**

```bash
update-initramfs -u -k all
update-grub
```

*防御性操作*：为确保引导文件完整，再次执行 GRUB 安装。

*   **UEFI 模式**：`grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=debian --recheck --no-nvram`
*   **BIOS 模式**：`grub-install /dev/loop0`（注意此处使用 loop 设备本身，而非分区）。

> **深度阅读指引**：
> 为什么官方工具不打包这个文件？为什么不能绕过官方工具手动用 `cpio` 命令打包 initrd（这会导致灾难性的 Kernel Panic）？关于 Debian Initramfs 多段复合结构的“法医鉴定”与完整的排错血泪史，请参阅后续排查专题章节。

#### 环境清理与 Target 注册

完成配置后，安全退出 `chroot` 并释放挂载资源：

```bash
exit

sudo umount /mnt/debian-vm/dev /mnt/debian-vm/proc /mnt/debian-vm/sys
sudo umount /mnt/debian-vm/boot/efi  # 若挂载了 ESP 分区
sudo umount /mnt/debian-vm

# 释放 loop 设备
sudo losetup -d /dev/loop0
```

将修改好的 `worker-02.Debian.img` 移动至 Controller 节点的 iSCSI 存储池目录，并运行自动化脚本注册 Target：

```bash
mv worker-02.Debian.img /pool1/iscsi_img/
cd /home/ipxe-all-ready
./iscsi-target-gen.sh
```

 **无盘启动验证**

创建一台无本地硬盘的 Worker 虚拟机，配置与目标物理机一致的 MAC 地址，并在 `dnsmasq/dhcp-hosts.conf` 中绑定主机名 `worker-02`。重载 dnsmasq 配置后启动 Worker。

在 iPXE 菜单中选择 Debian 正常启动项。iPXE 将执行 `sanboot`，加载 iSCSI 磁盘上的 GRUB。由于系统内部已通过 Hook 改造注入了正确的 `/etc/iscsi.initramfs` 身份配置，内核将在 Initramfs 阶段精准连接专属 Target，最终顺利进入定制好的 Debian 桌面环境。全程无需人工干预，实现真正的“秒级接入”。

## 3.4 路线三：debootstrap 构建纯净骨架（思路）

#### 工程定位

路线三面向追求极致纯净、最小化体积与全自动化部署的服务器场景，与路线一、路线二形成互补：官方安装器负责「标准流程验证」，虚拟机镜像转换负责「高度定制化交付」，而本路线完全绕过图形化与交互式安装器——通过 `debootstrap` 直接从镜像源拉取基础系统包，在 `chroot` 环境中手工装配出最精简的 Debian 系统。

此路线在探索阶段已完整跑通（详见第四章开篇的回顾），正文不再逐步展开操作命令——直接上手的路径请以「快速部署」系列为准。

#### 核心思路

*   **最小化装配**：`debootstrap` 只从镜像源拉取 base 组件包，得到一个可启动的骨架 rootfs；后续软件在 `chroot` 内按需安装，系统体积与内容完全可控，不存在安装器强塞的任何软件包。
*   **底层依赖精准注入**：骨架装配完成后，在 `chroot` 内注入 iSCSI 启动依赖——内核模块（`iscsi_tcp`）、用户态工具（`iscsistart`）与身份配置（`/etc/iscsi.initramfs`）。这一步与路线一、路线二的 Hook 改造同源，是三条路线的公共难点，也是 3.1 节方法论的核心。
*   **寻址稳定性**：根分区一律以文件系统 UUID 挂载，规避 iSCSI 拓扑下设备节点漂移导致的引导失败（对应 3.1 节的第三项挑战）。
*   **自动化友好**：整条链路无任何交互式对话框，全部可脚本化，天然适合批量生成系统镜像——这是本路线区别于前两条路线的根本优势，也是后续架构承接它的基因所在。

#### 与当前架构的承接

路线三「可脚本化、批量构建」的思路，已在当前架构中以更优雅的方式落地：母盘一次制备（含 iBFT 改造，见第四章）→ 上传 → WebUI 秒级克隆 → 插电即启动，全程零 per-worker 定制、零命令行操作。详细实操请参阅「快速部署」系列《[Debian 系无盘快速部署（母盘克隆）](/zh/guide/quick-deploy/debian-quick-deploy)》——本路线在此不再提供逐步操作说明。

## 本章小结：从 “no way” 到三条路线跑通

回顾本章开篇引用的 2021 年 iPXE 官方邮件列表结论——“There is no way to do this with the standard Debian initrd.”——本章通过三条独立路线，完整填平了这个长期存在的技术空白：

| 路线 | 工程定位 | 适用场景 | 代价 |
|---|---|---|---|
| 路线一：官方 netboot 安装器 | 重现并验证标准网络安装流程，观测 d-i 的配置继承断层并修复 | 标准环境、可复现基线 | 对网络稳定与硬件兼容敏感，定制能力受限 |
| 路线二：虚拟机镜像转换与定制 | 本地 VM 完整安装后转换镜像，chroot 注入依赖 | 复杂桌面、闭源驱动、专有软件栈 | 需虚拟化平台与镜像转换工具链 |
| 路线三：debootstrap 构建纯净骨架 | 绕过安装器，chroot 手工装配最小系统 | 极致纯净、最小体积、全自动化 | 装配工作量大；本文仅保留思路，实操见快速部署系列 |

三条路线共享同一条方法论——**绕过官方安装器限制、直接构建或转换系统镜像、通过 chroot 深度定制 Initramfs Hook**——这正是 3.1 节所说的攻克大多数基于 `initramfs` 引导机制的 Linux 发行版（Ubuntu、Arch Linux、RHEL 系）无盘启动的通用范式。

但收官之际，一个痛点始终没有放下：**每台机器的 initramfs 都要手工注入 iSCSI 参数**。每加一台 Worker，就要改一次 `/etc/iscsi/iscsi.initramfs`、重建一次 initrd——距离「秒级接入」还差最后一步。如何把这最后一步也消除掉，正是下一章的主题。