# 第一章：iPXE 无盘架构设计与核心链路

## 1.1 为什么不用现成的方案？

市面上的无盘方案通常只有两条路：

1. **传统 PXE + NFS**：TFTP 传内核慢且容易丢包，NFS 挂载根文件系统在并发和高负载时经常出现文件锁死和权限问题。
2. **商业无盘软件**：高度黑盒，绑定特定硬件或系统版本，运维人员只能“点下一步”，出了问题无从排查。

`ipxe-all-ready` 选择第三条路：**全链路开源、基于 iSCSI 块存储的现代化无盘架构**。
我们抛弃了所有黑盒工具，用 iPXE 做引导，用 HTTP 做大文件传输，用 iSCSI 做底层存储。更重要的是，我们通过“降维打击”（如 `debootstrap` 和 `dism++`）绕过了各大操作系统官方安装器的缺陷，真正实现了 Debian、Ubuntu 和 Windows 11 的跨平台“秒级接入”。

## 1.2. 基础设施组件划分

在我们的架构中，有三个职责明确的组件：

*   **Controller (控制节点)**：提供 DHCP 和 TFTP/HTTP 服务。负责给 Worker 分配 IP，下发 iPXE 固件和启动脚本，并提供内核或 PE 镜像的下载。
*   **iSCSI Server (存储节点)**：提供块级存储。它不仅提供常规的读写 LUN（作为系统盘），在 Windows 部署场景中，还能通过 `tgt` 的 `--device-type cd` 参数，直接将 ISO 镜像映射为只读的虚拟光驱 LUN。
*   **Worker (计算节点)**：无本地硬盘的裸金属或虚拟机。通电后完全依赖网络获取身份和系统。

###  控制面的容器化编排 (Docker Compose)

在实战中，我们将 Controller 节点的核心服务通过 Docker Compose 进行了标准化编排。这不仅让控制面具备了“一键拉起、随处运行”的可移植性，更将复杂的底层网络与存储服务收敛为清晰的代码声明。

我们的控制面栈由三个核心容器组成：

1. **ipxe-dnsmasq**：负责 DHCP 身份分配与 TFTP 固件/脚本分发（破冰层）。
2. **ipxe-nginx**：作为 HTTP 资源大动脉，提供内核、initrd 或 PE 镜像的高速下载。
3. **ipxe-iscsi**：基于 `stgt` 提供 iSCSI 块存储底座，映射系统盘 LUN 与 ISO 虚拟光驱。

**实战架构考量：**

*   **摒弃 Bridge，拥抱 Host 网络**：DHCP 和 TFTP 高度依赖局域网广播与特定的 UDP 端口，而 iSCSI 对网络延迟和吞吐极度敏感。因此，所有核心服务均配置为 `network_mode: host`。我们拒绝 Docker 默认的 NAT 桥接网络，让容器直接融入物理网络，彻底避免端口映射带来的性能损耗与广播黑洞。
*   **存储底座的设备直通**：iSCSI 容器（`stgt`）被赋予了 `privileged: true` 权限，并直接挂载了宿主机的 `/dev`、`/lib/modules` 和 `/sys/kernel/config`。这使得容器内的 iSCSI Target 能够打破容器隔离，像宿主机原生进程一样直接操作底层块设备（或镜像文件），并动态加载必要的内核模块。

通过这种编排，原本需要在 Linux 系统层面繁琐配置和排错的四个独立服务，被完美封装成了一个高内聚、低耦合的无盘控制面底座。

## 1.3 协议栈的实战分工

在无数次超时和断连的毒打后，我们确立了以下协议分工边界：

1.  **TFTP (仅限破冰)**：只用来传输几十 KB 的 iPXE 固件（`undionly.kpxe` / `snponly.efi`）和几 KB 的 `.ipxe` 脚本。绝不用它传大文件，否则 UDP 丢包会让你怀疑人生。**实战血泪教训**：必须确保局域网内只有一个 DHCP 服务器在响应 PXE 请求，否则主路由的 DHCP 会下发错误的 Option 66，导致 iPXE 连错 TFTP 服务器直接超时。
2.  **HTTP (大文件传输)**：当 iPXE 脚本接管后，所有的 Linux `vmlinuz`/`initrd` 或 Windows `boot.wim` 全部走 HTTP 下载，利用 TCP 保证传输的完整性和速度。
3.  **iSCSI (系统运行底座)**：操作系统运行时的根文件系统。iSCSI 提供的是块设备（Block Device），操作系统会认为这是一块真实的本地物理硬盘，彻底规避了 NFS 的网络文件系统缺陷。

## 1.4 启动状态机：从通电到进系统

一次完整的无盘启动分为四个阶段。Linux 和 Windows 在后两个阶段有着完全不同的实战逻辑。

### Phase 1: 传统 PXE 破冰

Worker 通电，发送 DHCP Discover。Controller 分配 IP，并通过 Option 66/67 告诉它 TFTP 服务器的 IP 和 iPXE 固件的路径。Worker 下载固件并执行，原生 PXE ROM 使命结束。

### Phase 2: iPXE 接管与脚本加载

iPXE 初始化网卡，再次请求 DHCP。Controller 识别到 iPXE 标识，下发 `boot.ipxe` 脚本路径。iPXE 下载脚本，加载菜单，准备引导系统。

### Phase 3: 系统加载 (Linux 与 Windows 的分水岭)

*   **Linux (Debian/Ubuntu)**：我们**不依赖**官方安装器的网络安装模式（实战证明 Ubuntu 的 Subiquity 根本不支持 iSCSI 磁盘选择）。我们提前使用 `debootstrap` 将纯净系统部署到 iSCSI LUN 中，并修改了 `initramfs-tools` 的 hook 脚本，强制打包 iSCSI 配置。iPXE 直接执行 `sanboot`，将 LUN 控制权交给 GRUB，GRUB 加载内核。
*   **Windows 11**：我们使用 `dism++` 提前向 `boot.wim` 注入万能网卡和存储驱动（避开微软 ADK 的版本坑）。iPXE 执行两次 `sanhook`，同时挂载 iSCSI 系统盘和 iSCSI 虚拟光驱（ISO）。然后加载 `boot.wim` 进入 PE，直接运行光驱里的 `setup.exe` 进行原生安装。

### Phase 4: 内核接管与根文件系统挂载

*   **Linux**：内核启动，`initramfs` 读取我们强制注入的 `/etc/iscsi.initramfs`，加载 `iscsi_tcp` 模块，重新连接 iSCSI Target。通过 `/etc/fstab` 中的 UUID（而非易变的 `/dev/sdX`）精准挂载根分区，完成 `switch_root`。
*   **Windows**：安装完成后重启，Windows 通过 iBFT (iSCSI Boot Firmware Table) 机制，在启动极早期由原生 iSCSI 驱动接管系统盘，直接进入桌面。

## 1.5 自动化核心：动态 IQN 变量传递链

**请务必逐字研读本节，并对照仓库源码**

在正式展开之前，我必须给出强烈的建议：请一定要花时间（哪怕是一个小时）彻底搞懂下面这条变量传递链。同时，**请务必打开 `iPXE-All-Ready` 项目仓库，对照 `dnsmasq/` 目录下的配置文件，以及 `tftp/` 目录下的 `boot.ipxe` 和 `menu.ipxe` 真实源码一起阅读**。

互联网上绝大多数的 iPXE 教程，为了图省事，都选择了在脚本里“硬编码”（写死 MAC 地址、固定的 IQN），最终做出来的只是一个加一台机器就要改一次代码的“玩具”。他们之所以这么做，是因为不愿意、也没耐心去搞明白 iPXE 官方早就提供好的这套动态链路。

**这不是我们的发明，而是 iPXE 官方开发者留下的精妙架构。** 当你真正看懂了数据是如何跨越协议边界，从 DHCP 报文流出，经过 iPXE 引擎重组，最终精准嵌入 iSCSI 登录报文时，你一定会像我第一次研究透它时那样，忍不住感叹一句：“**实在是太巧妙了！**”

我们做的，只是拒绝阉割它，拒绝向黑盒妥协，并坚持在我们的全开源基础设施中，将这套官方机制原汁原味地落地。只有结合仓库里的真实代码，你才能看到这套机制是如何在工程上完美闭环的。

以下是这套官方机制在实战中的完整推演（以 MAC 为 `52:54:00:12:34:56`，主机名为 `worker-01` 的节点启动 Ubuntu 为例）：

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

当用户在菜单中选择启动 Ubuntu 时，`menu.ipxe` 会基于基础变量，进一步拼接出目标存储端的身份（Target IQN），并组装成 iSCSI 资源定位符（URI）。

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

**底层行为**：iPXE 向 `192.168.1.5` 发送 iSCSI Login Request，报文中明确声明：“我的 Initiator 是 `iqn.2026-07.com.controller:worker-01`，我要连接 Target `iqn.2026-07.com.controller:worker-01.Ubuntu`”。iSCSI Server 校验 ACL 通过后，将专属的 LUN 映射给该节点。

**总结**：这条链路彻底消灭了脚本中的硬编码。新增一台无盘工作站，只需在 DHCP 绑定 MAC 和 Hostname，在 iSCSI Server 创建对应后缀的 LUN，iPXE 脚本永远无需修改。



## 1.6  基础环境搭建与调试基线

在进入具体系统的部署前，必须先搭建一套标准化的验证环境。无盘启动涉及网络、存储、内核等多个底层协议，任何一个环节的微小偏差都会导致启动失败。

### 1.6.1 基础工具准备

在无盘启动的攻坚中，不要试图直接在物理裸金属上“硬刚”。底层协议栈的调试充满了不确定性和破坏性，你需要一套趁手的工具来构建你的“安全屋”和“手术室”。

**1. 虚拟化平台 (VMware Workstation 作为优先选择 / ESXi / PVE)：不仅是风洞，更是机床**

这是整个项目中最核心、最不可或缺的基础设施。如果你认为虚拟机只是用来“随便测测”的替代品，那就大错特错了。在无盘架构中，虚拟机扮演着两个极其关键的角色：

*   **角色一：无限试错的“风洞实验室”**
    无盘启动涉及 DHCP、TFTP、iSCSI、内核引导等多个极易翻车的环节。在物理机上，一次配置错误可能导致网卡 PXE ROM 锁死、BIOS 设置混乱，甚至误格式化本地硬盘，恢复成本极高。
    而虚拟机提供了完美的**快照与秒级回滚**能力。无论你把 iPXE 脚本改得多崩溃，或者把 iSCSI LUN 搞得多混乱，一键还原即可重新开始。这种“无限试错”的自由度和极高的重启反馈频率，是我们能在几天内连续攻克三个系统底层黑盒的前提。同时，虚拟网络能为你提供绝对纯净、不受主路由 DHCP 干扰的隔离测试环境。

*   **角色二：打破冷启动死锁的“驱动注入机床”**
    这是实战中极其高阶且救命的一招。当你面对一台最新的物理机，其网卡或存储控制器过于冷门，导致 Windows `boot.wim`、Linux 官方内核甚至你提前注入的驱动包里都没有对应驱动时，你会陷入绝望的“冷启动死锁”：**没驱动 -> 进不去系统 -> 进不去系统就没法装驱动**。
    此时，虚拟机就化身为了破局的“机床”。得益于 iSCSI 块存储与计算节点彻底解耦的特性，你可以采用“偷天换日”的战术：
    1. 在 Controller 端临时修改 DHCP 绑定，让一台配置了通用虚拟硬件（驱动完备）的虚拟机，去挂载那台物理机专属的 iSCSI 系统盘 LUN。
    2. 虚拟机启动进入系统后，你直接在系统内下载并安装物理机的冷门驱动（Windows 用 `dism`，Linux 用 `apt` 或编译内核模块并 `update-initramfs`）。
    3. 安装完毕后关闭虚拟机，把系统盘“还给”物理机。
       此时系统盘内已经“长”出了物理机所需的驱动，物理机通电即可满血启动。**只要虚拟机能跑起来的系统，就没有救不活的物理机。**

**2. Wireshark：网络底层的“透视眼”**

当 iPXE 报错或 iSCSI 握手失败时，不要看黑盒日志瞎猜，直接抓包看底层报文。常用以下三个过滤规则：

*   `dhcp：监控 DHCP 交互全过程，排查 IP 分配与 Option 66/67 (TFTP Server/Bootfile) 是否下发正确。
*   `tftp`：监控 iPXE 固件与 `.ipxe` 脚本的拉取状态，精准定位 `Connection timed out` 或 `File not found` 是网络不通还是路径错误。
*   `iscsi`：监控 iSCSI Login PDU，排查 IQN 认证失败、ACL 拒绝或 LUN 映射错误。

**3. VS Code + Remote - SSH：高效的代码编辑环境**

通过 SSH 远程连接 Controller 节点，利用 VS Code 强大的插件和文件树，高效编辑 iPXE 脚本、Docker Compose 文件及 dnsmasq 配置。让修改配置、编写脚本和查看日志可以在同一个窗口内丝滑完成。



### 1.6.2 Controller 节点环境部署

对于首次接触 iPXE 无盘架构的开发者，我们强烈建议将 Controller 节点部署在虚拟机平台（如 VMware Workstation）上进行验证。利用虚拟机的快照功能，可以在配错网络或搞崩 Docker 环境时实现秒级回滚，极大降低前期的试错成本。当全链路在虚拟机中跑通后，再将其迁移至物理机或 NAS 生产环境。

**1. 硬件与存储分配基线**

Controller 节点需要同时承载 DHCP、TFTP、HTTP 以及 iSCSI Target 服务，合理的资源划分是稳定运行的前提：

*   **计算资源**：2 核 CPU，2~4 GB 内存。
*   **系统盘**：20 GB。仅用于安装基础 Linux 操作系统（推荐 Ubuntu 22.04 LTS 或 Debian 12）及 Docker 引擎。
*   **数据盘**：60 GB（或更大）。建议作为独立虚拟磁盘添加，并挂载到 `/pool1` 目录。该盘专门用于存放 TFTP 脚本、HTTP 资源池（内核/PE镜像）以及 iSCSI 后端镜像文件，避免系统盘空间被无盘镜像撑爆。

**2. 网络架构(NAT 模式)**

在 VMware 中，将 Controller 节点的网络适配器设置为 **NAT 模式**。这既能保证 Controller 访问外部网络（用于拉取 Docker 镜像和 `debootstrap` 源），又能通过虚拟网卡与 Worker 节点构建一个相对隔离的测试局域网。

打开 VMware 顶部菜单的“编辑” -> “虚拟网络编辑器”，选中对应的 NAT 网络（如 VMnet8），**必须取消勾选“使用本地 DHCP 服务将 IP 地址分配给虚拟机”**，并点击应用。将 DHCP 分配权让渡给你的 Controller 节点。

同时将 Controller 的网络接口配置为**静态 IP**。

### **1.6.3. 操作系统内静态 IP 配置**

以 Ubuntu/Debian 常用的 Netplan 为例，编辑 `/etc/netplan/01-netcfg.yaml`（文件名可能因系统而异），将 DHCP 获取改为静态配置。假设 VMware NAT 网段为 `192.168.100.0/24`，网关为 `192.168.100.2`,我们将Controller IP配置为`192.168.100.10`：

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    ens33: # 替换为你实际的网卡名称，可通过 ip a 查看
      dhcp4: no
      addresses:
        - 192.168.100.10/24  # 设定 Controller 的固定静态 IP
      routes:
        - to: default
          via: 192.168.100.2 # VMware NAT 网络的网关
      nameservers:
        addresses: [8.8.8.8, 114.114.114.114]
```

配置完成后，执行 `sudo netplan apply` 使静态 IP 生效。

### **1.6.4. 存储规划与目录结构 (核心)**

项目仓库放在系统盘或数据盘均可，但我们**建议将数据盘独立出来，只存放 iSCSI 镜像文件**。这样在未来扩容或迁移时，只需挂载数据盘即可带走所有无盘系统盘，而无需触碰项目代码。

假设我们将 60GB 的数据盘格式化并挂载到 `/pool1`。

* **系统盘目录 (项目仓库)**：假设放在 `/home/ipxe-all-ready`，存放配置和小文件。

  ```text
  /home/ipxe-all-ready/
  ├── docker-compose.yml
  ├── dnsmasq/          # DHCP/TFTP 配置
  ├── tftp/             # iPXE 固件与脚本
  └── www/              # HTTP 资源 (内核/initrd/wim)
  ```

* **数据盘目录 (iSCSI 存储池)**：在 `/pool1` 下创建专门存放块设备镜像的目录。

  ```bash
  mkdir -p /pool1/iscsi_img
  ```

### **1.6.5. 准备 iSCSI 后端镜像文件与自动化注册**

在数据盘的 `iscsi_img` 目录下创建镜像文件时，**不要随意命名**。为了让整个无盘架构具备真正的弹性扩展能力，我们制定了严格的文件命名规范，并配套了自动化注册脚本。

*   **命名规范**：必须采用 `${hostname}.${os_type}.img` 的格式。
    *   *示例*：`worker-01.Debian.img`、`worker-01.Ubuntu.img`、`worker-02.Windows.img`。
    *   *核心逻辑*：这个命名格式与 1.5 节中 iPXE 动态拼接的 Target IQN（如 `iqn.2026-07.com.controller:worker-01.Debian`）形成了完美的映射关系。

使用 `fallocate` 瞬间创建 20GB 的稀疏文件（切勿使用 `dd` 全量写入）：

```bash
cd /pool1/iscsi_img
fallocate -l 20G worker-01.debian.img
fallocate -l 60G worker-01.win11.img
```

我们在项目仓库的根目录下提供了一个临时使用的自动化注册脚本`iscsi-target-gen.sh`

该脚本会扫描 `/pool1/iscsi_img` 目录，**根据文件名自动解析出主机名和系统类型**，并自动完成 Target 创建、LUN 绑定和 ACL 放行。

### **1.6.6. Docker Compose 存储映射说明**

由于项目代码在系统盘（`/home/ipxe-all-ready`），而 iSCSI 镜像在数据盘（`/pool1/iscsi_img`），在编写 `docker-compose.yml` 时，必须通过 `volumes` 将这两个物理路径精准映射到容器内部。

以 `ipxe-iscsi` 容器为例：

```yaml
  ipxe-iscsi:
    image: wtnb75/stgt
    container_name: ipxe-iscsi
    network_mode: host
    privileged: true
    volumes:
      # 将数据盘上的 iSCSI 镜像目录映射到容器内的 /home/iscsi_img
      # 读者可根据自己的实际挂载路径（如 /data/iscsi_img）修改冒号左侧的绝对路径
      - /pool1/iscsi_img:/home/iscsi_img 
```

*注：冒号左侧为宿主机的绝对路径（数据盘），冒号右侧为容器内的路径。iSCSI Target 服务和创建脚本将在容器内的 `/home/iscsi_img` 中寻找 `worker-01.debian.img` 并对外提供块设备服务。*

### 1.6.7. 适配破冰层核心配置 (dnsmasq) 与链式加载逻辑

在 `iPXE-All-Ready` 项目仓库的 `dnsmasq/` 目录下，我们已经为您准备好了生产级的 `dnsmasq.conf` 和 `dhcp-hosts.conf` 模板。您无需从零手写这些复杂的底层配置，**只需打开这些现成的文件，根据您的实际物理网络环境进行简单的参数替换即可。**

**请务必仔细核对以下配置中的修改项，确保其与您的 Controller 节点网络环境完全一致。**

```text
# dnsmasq/dnsmasq.conf (仓库已预置，请修改以下带 [修改] 标记的参数)

# 1. [修改] 监听指定网卡（在 host 网络下有效，请替换为你 Controller 的实际网卡名，如 ens33, eth0 等）
interface=enp1s5 
bind-interfaces

dhcp-range=::,static

# 2. [修改] DHCP 地址池与基础网络参数（请根据你的实际网段严格修改）
# 格式: 起始IP, 结束IP, 子网掩码, 租期
dhcp-range=192.168.1.50,192.168.1.100,255.255.255.0,12h
# [修改] Option 3: 下发网关 IP (通常是你的主路由或 NAT 网关)
dhcp-option=3,192.168.100.2
# [修改] Option 6: 下发 DNS 服务器
dhcp-option=6,223.5.5.5,8.8.8.8

# 3. 启用 TFTP 服务并指定容器内的根目录 (无需修改，与 docker-compose 映射对应)
enable-tftp
tftp-root=/var/tftp

# 4. 架构识别（基于 PXE Client Architecture Option 93，无需修改）
dhcp-match=set:bios,option:client-arch,0        # Legacy BIOS
dhcp-match=set:efi64,option:client-arch,7       # UEFI x64 (EFI BC)
dhcp-match=set:efi64,option:client-arch,9       # UEFI x64 (EFI x86_64)

# 5. 第一阶段引导：固件分发 (无需修改)
dhcp-boot=tag:efi64,snponly.efi                 # UEFI → snponly.efi
dhcp-boot=tag:bios,undionly.kpxe                # Legacy → undionly.kpxe

# 6. 第二阶段引导：iPXE 链式加载的灵魂 (Chain-loading，无需修改)
dhcp-userclass=set:ipxe,iPXE
dhcp-boot=tag:ipxe,boot.ipxe

# 7. 静态主机名分配（用于 iSCSI IQN 动态生成，无需修改）
dhcp-hostsfile=/etc/dnsmasq.d/dhcp-hosts.conf
dhcp-leasefile=/var/lib/misc/dnsmasq.leases

# 8. 日志（调试用，无需修改）
log-dhcp
log-queries
```

**核心参数修改 Checklist：**

1.  **网卡名 (`interface`)**：执行 `ip a` 查看 Controller 的真实网卡名（如 `ens33`、`eth0`），替换掉模板中的 `enp1s5`。
2.  **网段与网关 (`dhcp-range` & `dhcp-option=3`)**：这是最容易配错的地方。地址池和网关必须与 Controller 所在的物理网段或 VMware NAT 网段完全一致，否则 Worker 获取 IP 后无法路由到 Controller。
3.  **TFTP 根目录 (`tftp-root`)**：保持 `/var/tftp` 不变，这必须与 `docker-compose.yml` 中 `ipxe-dnsmasq` 容器的 volume 映射路径严格对应。

**底层机制深度解析（为什么模板要这么设计？）：**

*   **免除 Next-Server 硬编码**：模板中没有硬编码 `dhcp-boot` 的 Next-Server (TFTP 服务器 IP)。因为 dnsmasq 在 `bind-interfaces` 模式下，会自动将自身的监听 IP 作为 Next-Server 下发给客户端。这意味着未来 Controller 迁移或 IP 变更时，**此配置文件无需做任何修改**。
*   **链式加载的灵魂 (`dhcp-userclass=set:ipxe,iPXE`)**：这是破冰层最巧妙的设计。
    *   **第一次请求**：物理机原生 PXE ROM 发起 DHCP 请求，没有 `iPXE` 标识，dnsmasq 下发几十 KB 的 `snponly.efi`。
    *   **第二次请求**：`snponly.efi` 加载并接管网卡后，会**再次**发起 DHCP 请求。此时，它会在请求报文中带上 `User-Class: iPXE` 标识。dnsmasq 捕获到这个标识，触发 `tag:ipxe` 规则，直接下发 `boot.ipxe` 脚本。
    *   *避坑警告*：如果删掉这行配置，iPXE 加载后会再次下载 `snponly.efi`，导致无限死循环 (Bootloop)。

**适配 Worker 身份注入：**

接着，打开仓库中预置的 `dnsmasq/dhcp-hosts.conf`。这是 1.5 节变量传递链的起点，您只需将模板中的 MAC 地址替换为您 Worker 虚拟机或物理机的真实 MAC 地址：

```text
# dnsmasq/dhcp-hosts.conf (仓库已预置，请替换 MAC 地址)
# 格式: MAC地址, 主机名, 固定IP (可选)
# [修改] 请务必替换为你 Worker 虚拟机或物理机的真实 MAC 地址
00:0c:29:b9:8b:2d,worker-01,192.168.1.51
```

完成上述参数适配后，Controller 节点的 DHCP/TFTP 破冰层已具备完整的架构识别与链式加载能力。此时执行 `docker compose up -d`，即可瞬间拉起整个控制面。