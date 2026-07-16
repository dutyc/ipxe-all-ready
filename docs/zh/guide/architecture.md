# 第一章：iPXE 无盘架构设计与核心链路

## 1.1 为什么不用现成的方案？

市面上的无盘方案通常分为两类：

1. **传统 PXE + NFS**：TFTP 传输内核速度较慢且容易丢包，NFS 挂载根文件系统在并发和高负载时容易出现文件锁死和权限问题。
2. **商业无盘软件**：封闭源码，通常绑定特定硬件或系统版本，运维人员缺乏对底层引导链路的控制权，排查问题较为困难。

`ipxe-all-ready` 采用第三种方案：**全链路开源、基于 iSCSI 块存储的无盘架构**。
本项目使用 iPXE 进行网络引导，HTTP 进行大文件传输，iSCSI 提供底层存储。同时，通过 `debootstrap` 和 `dism++` 等工具绕过部分操作系统官方安装器的限制，实现 Debian、Ubuntu 和 Windows 11 的跨平台部署。

## 1.2 基础设施组件划分

在本项目的架构中，包含三个职责明确的组件：

*   **Controller (控制节点)**：提供 DHCP 和 TFTP/HTTP 服务。负责为 Worker 分配 IP，下发 iPXE 固件和启动脚本，并提供内核或 PE 镜像的下载。
*   **iSCSI Server (存储节点)**：提供块级存储。除了提供常规的读写 LUN（作为系统盘）外，在 Windows 部署场景中，可通过 `tgt` 的 `--device-type cd` 参数，将 ISO 镜像映射为只读的虚拟光驱 LUN。
*   **Worker (计算节点)**：无本地硬盘的裸金属或虚拟机。通电后依赖网络获取身份和系统。

### 控制面的容器化编排 (Docker Compose)

在实际部署中，Controller 节点的核心服务通过 Docker Compose 进行编排。这提高了控制面的可移植性，并将底层网络与存储服务转化为代码声明。

控制面栈由三个核心容器组成：

1. **ipxe-dnsmasq**：负责 DHCP 身份分配与 TFTP 固件/脚本分发。
2. **ipxe-nginx**：作为 HTTP 资源服务，提供内核、initrd 或 PE 镜像的下载。
3. **ipxe-iscsi**：基于 `stgt` 提供 iSCSI 块存储服务，映射系统盘 LUN 与 ISO 虚拟光驱。

**架构考量：**

*   **采用 Host 网络模式**：DHCP 和 TFTP 依赖局域网广播与特定的 UDP 端口，iSCSI 对网络延迟和吞吐有较高要求。因此，所有核心服务均配置为 `network_mode: host`。避免使用 Docker 默认的 NAT 桥接网络，以减少端口映射带来的性能损耗与广播问题。
*   **存储底座的设备直通**：iSCSI 容器（`stgt`）配置了 `privileged: true` 权限，并挂载宿主机的 `/dev`、`/lib/modules` 和 `/sys/kernel/config`。这使得容器内的 iSCSI Target 能够直接操作底层块设备（或镜像文件），并加载必要的内核模块。

通过这种编排，原本需要在 Linux 系统层面分别配置的独立服务，被整合为一个高内聚的控制面底座。

## 1.3 协议栈的实战分工

在实际部署中，合理的协议分工能够提高引导的稳定性：

1.  **TFTP (仅限网络引导)**：用于传输几十 KB 的 iPXE 固件（`undionly.kpxe` / `snponly.efi`）和几 KB 的 `.ipxe` 脚本。不用于传输大文件，否则 UDP 丢包会导致传输中断。**注意事项**：需确保局域网内只有一个 DHCP 服务器响应 PXE 请求，否则主路由的 DHCP 可能会下发错误的 Option 66，导致 iPXE 连接错误的 TFTP 服务器并超时。
2.  **HTTP (大文件传输)**：当 iPXE 脚本接管后，所有的 Linux `vmlinuz`/`initrd` 或 Windows `boot.wim` 均通过 HTTP 下载，利用 TCP 保证传输的完整性和速度。
3.  **iSCSI (系统运行底座)**：承载操作系统运行时的根文件系统。iSCSI 提供块设备（Block Device），操作系统将其识别为本地物理硬盘，规避了 NFS 网络文件系统的部分缺陷。

## 1.4 启动状态机：从通电到进系统

一次完整的无盘启动分为四个阶段。Linux 和 Windows 在后两个阶段的处理逻辑存在差异。

### Phase 1: 传统 PXE 引导

Worker 通电，发送 DHCP Discover。Controller 分配 IP，并通过 Option 66/67 下发 TFTP 服务器的 IP 和 iPXE 固件的路径。Worker 下载固件并执行，原生 PXE ROM 阶段结束。

### Phase 2: iPXE 接管与脚本加载

iPXE 初始化网卡，再次请求 DHCP。Controller 识别到 iPXE 标识，下发 `boot.ipxe` 脚本路径。iPXE 下载脚本，加载菜单，准备引导系统。

### Phase 3: 系统加载 (Linux 与 Windows 的差异)

*   **Linux (Debian/Ubuntu)**：不依赖官方安装器的网络安装模式（Ubuntu 的 Subiquity 安装器对 iSCSI 磁盘选择支持有限）。提前使用 `debootstrap` 将纯净系统部署到 iSCSI LUN 中，并修改 `initramfs-tools` 的 hook 脚本以打包 iSCSI 配置。iPXE 执行 `sanboot`，将 LUN 控制权交给 GRUB，由 GRUB 加载内核。
*   **Windows 11**：使用 `dism++` 提前向 `boot.wim` 注入通用网卡和存储驱动（规避微软 ADK 的版本依赖问题）。iPXE 执行两次 `sanhook`，同时挂载 iSCSI 系统盘和 iSCSI 虚拟光驱（ISO）。随后加载 `boot.wim` 进入 PE，运行光驱里的 `setup.exe` 进行安装。

### Phase 4: 内核接管与根文件系统挂载

*   **Linux**：内核启动，`initramfs` 读取注入的 `/etc/iscsi.initramfs`，加载 `iscsi_tcp` 模块，重新连接 iSCSI Target。通过 `/etc/fstab` 中的 UUID 挂载根分区，完成 `switch_root`。
*   **Windows**：安装完成后重启，Windows 通过 iBFT (iSCSI Boot Firmware Table) 机制，在启动早期由原生 iSCSI 驱动接管系统盘，进入桌面。

## 1.5 自动化核心：动态 IQN 变量传递链

**建议结合项目仓库源码阅读本节**

理解该链路的工作机制对后续配置至关重要。建议打开 `iPXE-All-Ready` 项目仓库，对照 `dnsmasq/` 目录下的配置文件，以及 `tftp/` 目录下的 `boot.ipxe` 和 `menu.ipxe` 源码进行阅读。

互联网上部分 iPXE 教程选择在脚本中硬编码 MAC 地址或固定的 IQN。这种方式在增加节点时需要频繁修改代码。本项目保留了 iPXE 官方提供的动态链路机制，实现了配置与节点数量的解耦。

以下是该机制在实际环境中的推演（以 MAC 为 `52:54:00:12:34:56`，主机名为 `worker-01` 的节点启动 Ubuntu 为例）：

### 1. DHCP 层的身份注入

在 Controller 的 `dnsmasq` 中绑定 MAC 与主机名，并通过 DHCP Option 12 下发。

```text
# dnsmasq.conf
dhcp-host=52:54:00:12:34:56,worker-01
```

**实际效果**：Worker 发起 DHCP 请求时，Controller 会向其注入环境变量 `${hostname}`，其值为 `worker-01`。

### 2. iPXE 基础变量的捕获与 Initiator IQN 拼接

iPXE 固件接管网卡后，捕获 DHCP 下发的变量，并在 `boot.ipxe` 中拼接出当前节点作为 iSCSI 发起方的身份（Initiator IQN）。

```ipxe
# boot.ipxe
set base-iqn iqn.2026-07.com.controller
set iscsi-server 192.168.1.5

# 拼接 Initiator IQN
set initiator-iqn ${base-iqn}:${hostname}
```

**实际生成的变量值**：

*   `${hostname}` = `worker-01`
*   `${initiator-iqn}` = `iqn.2026-07.com.controller:worker-01`

### 3. menu.ipxe 中的 Target IQN 衍生与 URI 组装

当用户在菜单中选择启动 Ubuntu 时，`menu.ipxe` 会基于基础变量，拼接出目标存储端的身份（Target IQN），并组装成 iSCSI 资源定位符（URI）。

```ipxe
# menu.ipxe (Ubuntu 启动项)
# 拼接 Target IQN (在主机名后追加系统后缀)
set target-iqn ${base-iqn}:${hostname}.Ubuntu

# 组装 iSCSI URI
# 格式: iscsi:<server>:[<protocol>]:[<port>]:[<lun>]:<target-iqn>
set root-path iscsi:${iscsi-server}::::${target-iqn}
```

**实际生成的变量值**：

*   `${target-iqn}` = `iqn.2026-07.com.controller:worker-01.Ubuntu`
*   `${root-path}` = `iscsi:192.168.1.5::::iqn.2026-07.com.controller:worker-01.Ubuntu`

### 4. 跨越协议边界的最终消费

iPXE 执行 `sanboot` 指令，将内存中组装好的变量转化为底层的 iSCSI 登录报文。

```ipxe
# 执行无盘启动
sanboot --keep --drive 0x80 ${root-path}
```

**底层行为**：iPXE 向 `192.168.1.5` 发送 iSCSI Login Request，报文中包含 Initiator IQN 和 Target IQN。iSCSI Server 校验 ACL 通过后，将对应的 LUN 映射给该节点。

**总结**：这条链路消除了脚本中的硬编码。新增无盘工作站时，只需在 DHCP 绑定 MAC 和 Hostname，在 iSCSI Server 创建对应后缀的 LUN，iPXE 脚本无需修改。

## 1.6 基础环境搭建与调试基线

在进入具体系统的部署前，需要搭建标准化的验证环境。无盘启动涉及网络、存储、内核等多个底层协议，环境配置的准确性直接影响启动结果。

### 1.6.1 基础工具准备

在调试阶段，建议避免直接在物理机上测试。底层协议栈的调试存在不确定性，使用虚拟化工具可以构建隔离的测试环境。

**1. 虚拟化平台 (VMware Workstation / ESXi / PVE)**

这是整个项目中最核心、最不可或缺的基础设施。它不只是用来“随便测测”的替代品, 它在无盘架构中主要有两个作用：

*   **提供可回滚的测试环境**
    无盘启动涉及 DHCP、TFTP、iSCSI、内核引导等环节。在物理机上，配置错误可能导致网卡 PXE ROM 状态异常或本地硬盘被误操作。虚拟机提供快照与回滚能力，便于快速重置环境。同时，虚拟网络可以提供不受主路由 DHCP 干扰的隔离测试环境。
*   **解决冷启动驱动问题**
    当物理机的网卡或存储控制器较新，导致 Windows `boot.wim` 或 Linux 官方内核缺少对应驱动时，会出现无法连接网络或无法识别磁盘的问题。
    此时可以利用 iSCSI 块存储与计算节点解耦的特性进行处理：
    1. 在 Controller 端临时修改 DHCP 绑定，让一台配置了通用虚拟硬件的虚拟机挂载该物理机专属的 iSCSI 系统盘 LUN。
    2. 虚拟机启动进入系统后，在系统内下载并安装物理机所需的驱动（Windows 使用 `dism`，Linux 使用 `apt` 或编译内核模块并 `update-initramfs`）。
    3. 关闭虚拟机，释放 LUN。此时系统盘内已包含所需驱动，物理机通电即可正常启动。

**2. Wireshark：网络分析工具**

当 iPXE 报错或 iSCSI 握手失败时，可以通过抓包分析底层报文。常用的过滤规则包括：

*   `bootp`：监控 DHCP 交互过程，排查 IP 分配与 Option 66/67 下发情况。
*   `tftp`：监控 iPXE 固件与 `.ipxe` 脚本的拉取状态，定位 `Connection timed out` 或 `File not found` 问题。
*   `iscsi`：监控 iSCSI Login PDU，排查 IQN 认证、ACL 或 LUN 映射问题。

**3. VS Code + Remote - SSH**

通过 SSH 远程连接 Controller 节点，利用 VS Code 编辑 iPXE 脚本、Docker Compose 文件及 dnsmasq 配置，可以在同一窗口内完成配置修改和日志查看。

### 1.6.2 Controller 节点环境部署

建议首次部署时将 Controller 节点运行在虚拟机平台（如 VMware Workstation）上。利用快照功能可以在配置出错时快速回滚。全链路验证通过后，再迁移至物理机或 NAS 环境。

**1. 硬件与存储分配基线**

Controller 节点需要承载 DHCP、TFTP、HTTP 以及 iSCSI Target 服务：

*   **计算资源**：2 核 CPU，2~4 GB 内存。
*   **系统盘**：20 GB。用于安装基础 Linux 操作系统（推荐 Ubuntu 22.04 LTS 或 Debian 12）及 Docker 引擎。
*   **数据盘**：60 GB（或更大）。建议作为独立虚拟磁盘添加，并挂载到 `/pool1` 目录。该盘专门用于存放 iSCSI 后端镜像文件，避免系统盘空间被占用。

**2. 网络架构 (NAT 模式)**

在 VMware 中，将 Controller 节点的网络适配器设置为 **NAT 模式**。这既能保证 Controller 访问外部网络，又能通过虚拟网卡与 Worker 节点构建隔离的测试局域网。

打开 VMware 的“虚拟网络编辑器”，选中对应的 NAT 网络（如 VMnet8），**取消勾选“使用本地 DHCP 服务将 IP 地址分配给虚拟机”**。将 DHCP 分配权交由 Controller 节点处理。

同时，需将 Controller 的网络接口配置为静态 IP。

### 1.6.3 操作系统内静态 IP 配置

以 Ubuntu/Debian 常用的 Netplan 为例，编辑 `/etc/netplan/01-netcfg.yaml`，将网络配置为静态 IP。假设 VMware NAT 网段为 `192.168.100.0/24`，网关为 `192.168.100.2`，Controller IP 配置为 `192.168.100.10`：

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    ens33: # 替换为实际的网卡名称，可通过 ip a 查看
      dhcp4: no
      addresses:
        - 192.168.100.10/24
      routes:
        - to: default
          via: 192.168.100.2
      nameservers:
        addresses: [8.8.8.8, 114.114.114.114]
```

配置完成后，执行 `sudo netplan apply` 使配置生效。

### 1.6.4 存储规划与目录结构

建议将数据盘独立出来，专门存放 iSCSI 镜像文件。这样在后续扩容或迁移时，只需处理数据盘即可。

假设将 60GB 的数据盘格式化并挂载到 `/pool1`。

* **系统盘目录 (项目仓库)**：假设放在 `/home/ipxe-all-ready`，存放配置和小文件。

  ```text
  /home/ipxe-all-ready/
  ├── docker-compose.yml
  ├── dnsmasq/          # DHCP/TFTP 配置
  ├── tftp/             # iPXE 固件与脚本
  └── www/              # HTTP 资源 (内核/initrd/wim)
  ```

* **数据盘目录 (iSCSI 存储池)**：在 `/pool1` 下创建存放块设备镜像的目录。

  ```bash
  mkdir -p /pool1/iscsi_img
  ```

### 1.6.5 准备 iSCSI 后端镜像文件与自动化注册

在 `iscsi_img` 目录下创建镜像文件时，需遵循特定的命名规范，以便配合自动化注册脚本使用。

*   **命名规范**：采用 `${hostname}.${os_type}.img` 的格式。
    *   *示例*：`worker-01.Debian.img`、`worker-01.Ubuntu.img`、`worker-02.Windows.img`。
    *   *逻辑*：该命名格式与 1.5 节中 iPXE 动态拼接的 Target IQN（如 `iqn.2026-07.com.controller:worker-01.Debian`）相对应。

使用 `fallocate` 创建稀疏文件：

```bash
cd /pool1/iscsi_img
fallocate -l 20G worker-01.debian.img
fallocate -l 60G worker-01.win11.img
```

项目仓库根目录下提供了自动化注册脚本 `iscsi-target-gen.sh`。该脚本会扫描 `/pool1/iscsi_img` 目录，根据文件名解析主机名和系统类型，自动完成 Target 创建、LUN 绑定和 ACL 配置。

### 1.6.6 Docker Compose 存储映射说明

由于项目代码在系统盘，而 iSCSI 镜像在数据盘，在 `docker-compose.yml` 中需要通过 `volumes` 将物理路径映射到容器内部。

以 `ipxe-iscsi` 容器为例：

```yaml
  ipxe-iscsi:
    image: wtnb75/stgt
    container_name: ipxe-iscsi
    network_mode: host
    privileged: true
    volumes:
      # 将数据盘上的 iSCSI 镜像目录映射到容器内的 /home/iscsi_img
      - /pool1/iscsi_img:/home/iscsi_img 
```

*注：冒号左侧为宿主机的绝对路径，冒号右侧为容器内的路径。iSCSI Target 服务将在容器内的 `/home/iscsi_img` 中读取镜像文件并提供块设备服务。*

### 1.6.7 适配破冰层核心配置 (dnsmasq) 与链式加载逻辑

项目仓库的 `dnsmasq/` 目录下提供了 `dnsmasq.conf` 和 `dhcp-hosts.conf` 模板。需要根据实际物理网络环境修改部分参数。

```text
# dnsmasq/dnsmasq.conf (请修改以下带 [修改] 标记的参数)

# 1. [修改] 监听指定网卡（替换为 Controller 的实际网卡名，如 ens33, eth0 等）
interface=enp1s5 
bind-interfaces

dhcp-range=::,static

# 2. [修改] DHCP 地址池与基础网络参数
dhcp-range=192.168.1.50,192.168.1.100,255.255.255.0,12h
# [修改] Option 3: 下发网关 IP
dhcp-option=3,192.168.100.2
# [修改] Option 6: 下发 DNS 服务器
dhcp-option=6,223.5.5.5,8.8.8.8

# 3. 启用 TFTP 服务并指定容器内的根目录 (无需修改)
enable-tftp
tftp-root=/var/tftp

# 4. 架构识别（基于 PXE Client Architecture Option 93，无需修改）
dhcp-match=set:bios,option:client-arch,0        # Legacy BIOS
dhcp-match=set:efi64,option:client-arch,7       # UEFI x64 (EFI BC)
dhcp-match=set:efi64,option:client-arch,9       # UEFI x64 (EFI x86_64)

# 5. 第一阶段引导：固件分发 (无需修改)
dhcp-boot=tag:efi64,snponly.efi                 # UEFI → snponly.efi
dhcp-boot=tag:bios,undionly.kpxe                # Legacy → undionly.kpxe

# 6. 第二阶段引导：iPXE 链式加载 (Chain-loading，无需修改)
dhcp-userclass=set:ipxe,iPXE
dhcp-boot=tag:ipxe,boot.ipxe

# 7. 静态主机名分配（用于 iSCSI IQN 动态生成，无需修改）
dhcp-hostsfile=/etc/dnsmasq.d/dhcp-hosts.conf
dhcp-leasefile=/var/lib/misc/dnsmasq.leases

# 8. 日志（调试用，无需修改）
log-dhcp
log-queries
```

**参数修改说明：**

1.  **网卡名 (`interface`)**：执行 `ip a` 查看 Controller 的真实网卡名，替换模板中的 `enp1s5`。
2.  **网段与网关 (`dhcp-range` & `dhcp-option=3`)**：地址池和网关必须与 Controller 所在的物理网段或 VMware NAT 网段一致。
3.  **TFTP 根目录 (`tftp-root`)**：保持 `/var/tftp` 不变，需与 `docker-compose.yml` 中 `ipxe-dnsmasq` 容器的 volume 映射路径对应。

**底层机制说明：**

*   **Next-Server 自动下发**：模板中未硬编码 `dhcp-boot` 的 Next-Server (TFTP 服务器 IP)。dnsmasq 在 `bind-interfaces` 模式下，会自动将自身的监听 IP 作为 Next-Server 下发。后续 Controller IP 变更时，此配置文件无需修改。
*   **链式加载 (`dhcp-userclass=set:ipxe,iPXE`)**：
    *   **第一次请求**：物理机原生 PXE ROM 发起 DHCP 请求，无 `iPXE` 标识，dnsmasq 下发 `snponly.efi`。
    *   **第二次请求**：`snponly.efi` 加载后再次发起 DHCP 请求，并带上 `User-Class: iPXE` 标识。dnsmasq 捕获该标识，触发 `tag:ipxe` 规则，下发 `boot.ipxe` 脚本。
    *   *注意*：若移除此配置，iPXE 加载后会再次下载 `snponly.efi`，导致循环重启。

**适配 Worker 身份注入：**

打开 `dnsmasq/dhcp-hosts.conf`，将模板中的 MAC 地址替换为 Worker 虚拟机或物理机的真实 MAC 地址：

```text
# dnsmasq/dhcp-hosts.conf
# 格式: MAC地址, 主机名, 固定IP (可选)
00:0c:29:b9:8b:2d,worker-01,192.168.1.51
```

完成参数适配后，执行 `docker compose up -d` 启动控制面服务。