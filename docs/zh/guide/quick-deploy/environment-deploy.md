# 项目环境部署

> **本文档定位：环境部署 · 快速上线。**
> Controller（控制面）+ 存储节点（Agent + iSCSI 后端）一次性部署，全平台通用。
> 环境就绪后，母盘制备与克隆见《Windows 无盘快速部署》/《Debian 系无盘快速部署》。

## 部署拓扑：两个编排文件

本项目由**两个独立的编排文件**组成，**不是一体的**：

```
Controller 节点 —— 根目录 docker-compose.yml（控制面）
├── ipxe-dnsmasq          DHCP / TFTP（host 网络，67/69 端口）
├── ipxe-control-plane    控制面 API（4839），Worker 生命周期编排
└── ipxe-cp-webui         WebUI + 文件分发（4838）

存储节点 —— iscsi-server/docker-compose.yml（数据面，可与 Controller 同机）
├── ipxe-iscsi            iSCSI 后端（3260，host 网络，stgt 或 LIO 二选一）
└── ipxe-agent            Agent API（4840），接收控制面调度，操作本机后端
```

关键概念：

* **一个 Agent 对应一个 iSCSI 后端，他们是一个整体**——Agent 通过 `docker.sock` 操作本机后端容器，
  存储节点部署几个、Agent 就有几个，Control Plane 通过 `agents.yml` 清单调度。
* **单节点 / 多节点部署**：Worker 少、IO 压力小时，存储节点可与 Controller 同机（一个 Agent）；
  Worker 多、追求 iSCSI SAN 性能时，按服务器 IO 资源把存储拆到多台机器（每台一个 Agent），
  Control Plane 自动按 `role.disk` 在多个 Agent 间调度建盘，避免单点存储瓶颈。

---

## 第 1 步：部署 Controller（控制面）

### 1.1 准备

在 Controller 节点（Debian / Ubuntu + Docker）上：

```bash
git clone https://github.com/dutyc/ipxe-all-ready.git
cd ipxe-all-ready
mkdir -p /pool1/iscsi_img        # 镜像目录（存盘文件，路径可自定义）
```

### 1.2 修改 dnsmasq 网段

编辑 `dnsmasq/dnsmasq.conf`，按实际网络环境修改：

```conf
interface=ens33                                  # 实际网卡名
dhcp-range=192.168.80.50,192.168.80.100,255.255.255.0,12h   # 地址池（按实际网段）
dhcp-option=3,192.168.80.2                       # 网关
dhcp-option=6,223.5.5.5                          # DNS
```

### 1.3 获取 iPXE 固件

从 iPXE 官方发布站 [https://boot.ipxe.org/](https://boot.ipxe.org/) 下载启动固件（官方构建的 release 二进制，无需自行编译），需要以下文件（`x86_64-efi/` 为官网子目录）：

```
undionly.kpxe                    # BIOS 引导固件
x86_64-efi/
├── ipxe-legacy.efi              # UEFI 固件（旧版固件兼容，备选）
├── ipxe.efi                     # UEFI 固件（标准版，备选）
└── snponly.efi                  # UEFI 固件（SNP 精简版，dnsmasq 默认分发）
```

下载后**统一放入 `tftp/` 根目录**，不要保留官网的 `x86_64-efi/` 子目录（`wget` 默认只取 URL 末尾文件名存到当前目录）：

```bash
cd tftp
wget https://boot.ipxe.org/undionly.kpxe
wget https://boot.ipxe.org/x86_64-efi/ipxe-legacy.efi
wget https://boot.ipxe.org/x86_64-efi/ipxe.efi
wget https://boot.ipxe.org/x86_64-efi/snponly.efi
```

`dnsmasq.conf` 已按架构识别分发固件：UEFI → `snponly.efi`，BIOS → `undionly.kpxe`，iPXE 二次请求 → `boot.ipxe`。个别机器 UEFI 引导异常时，可将 efi64 引导文件改为 `ipxe.efi` 或 `ipxe-legacy.efi` 试验。

> **memdisk（可选，常规启动不需要）**：memdisk 仅用于「iPXE 直接引导 ISO 安装镜像」的旧方式（`kernel memdisk` + `initrd xxx.iso`），本项目常规无盘启动走 iSCSI sanboot，无需此文件。需要时从 [SYSLINUX 发布页](https://www.kernel.org/pub/linux/utils/boot/syslinux/) 下载发行包，解压取 `bios/memdisk/memdisk` 放入 `tftp/`：
>
> ```bash
> cd /tmp
> wget https://mirrors.edge.kernel.org/pub/linux/utils/boot/syslinux/6.03/syslinux-6.03.tar.gz
> tar xzf syslinux-6.03.tar.gz
> cp syslinux-6.03/bios/memdisk/memdisk <项目路径>/tftp/
> ```

### 1.4 配置 API Token（可选，不设置不影响启动）

**Control Plane**（`control_plane/control_plane.env`）：

```env
# 不设置 = 所有 API 端点开放（仅 /healthz 永远可达）
IPXE_CP_TOKEN=你的token
```

**WebUI**（`webui/app/.env`，**必须与上面对应填写**，否则 WebUI 调用 API 会被拒）：

```env
VITE_CP_TOKEN=你的token
```

> 注意：`VITE_` 变量在构建时注入，修改后需重新构建 WebUI：`cd webui/app && npm install && npm run build`。
> 若跳过本节（Token 留空），则无需构建。

### 1.5 启动 Controller

```bash
docker compose up -d
```

### 1.6 验证

```bash
curl http://localhost:4839/healthz        # Control Plane
# 浏览器打开 http://<Controller IP>:4838  # WebUI
```

---

## 第 2 步：部署存储节点（Agent + iSCSI 后端）

> 每台存储节点执行一次本节；与 Controller 同机则就地执行。

### 2.1 准备 img 存储目录（决定克隆速度）

编辑 `iscsi-server/docker-compose.yml`，将**两处卷映射的宿主机侧路径**改为本节点实际存放 img 文件的目录（`ipxe-iscsi` 与 `ipxe-agent` 两个服务块都要改，**必须一致**；容器内路径 `/home/iscsi_img` 保持不变，与 2.3 的 `IPXE_DISK_DIR` 对应）：

```yaml
# ipxe-iscsi 服务块
      - /pool1/iscsi_img:/home/iscsi_img   # 宿主目录按实际修改，如 /data/iscsi_img
# ipxe-agent 服务块
      - /pool1/iscsi_img:/home/iscsi_img   # 两处必须一致
```

> **文件系统强烈建议 btrfs**：克隆母盘时 Agent 优先使用 reflink（FICLONE 写时复制），btrfs 下克隆秒级完成、几乎不占额外空间；若目录落在 ext4 / xfs 等不支持 reflink 的文件系统上，会自动回退为全量拷贝，克隆时间随母盘大小线性增长（如 60GB 母盘约数分钟）。

**单台存储节点的硬件瓶颈**（扩容依据）：

| 瓶颈点 | 影响 | 建议 |
|---|---|---|
| 网卡速率 | 千兆理论 125MB/s，单个无盘 Worker 的持续读写就可能逼近上限，多 Worker 共享时急剧下降 | 生产 ≥ 10GbE（万兆）；千兆只适合少量 Worker 验证 |
| 硬盘 IO | 无盘 Worker 以小 IO 随机读为主，机械盘随机 IO 性能差 | 建议 SSD / NVMe，按并发 Worker 数规划容量与 IOPS |
| 内存 / CPU | 影响 iSCSI 服务端排队与缓存 | 常规配置即可，瓶颈通常在网络与磁盘 |

**按规模扩容存储节点**：单台 10GbE 有效吞吐约 1.1GB/s，按每 Worker 平均 50–100MB/s 持续读估算，约支撑 10–20 个并发 Worker；Worker 更多或 IO 要求更高时，添加存储节点（每台一个 Agent，按 2.2–2.4 完成配置并在 `agents.yml` 追加记录），Control Plane 按 `role.disk` 自动在多 Agent 间调度建盘。

### 2.2 选择后端类型

编辑 `iscsi-server/docker-compose.yml`，**二选一**启用后端服务块（容器同名 `ipxe-iscsi`，不可同时启用）：

| 后端 | 位置 | 特点 |
|---|---|---|
| `stgt` | 取消 `ipxe-stgt` 服务块注释，注释掉 `ipxe-lio` 块 | 用户态，支持把 ISO 挂成虚拟光驱（`role.cd`），受限环境友好 |
| `lio` | 取消 `ipxe-lio` 服务块注释，注释掉 `ipxe-stgt` 块 | 内核态，生产级磁盘性能（推荐系统盘） |

### 2.3 配置 `.env`

编辑 `iscsi-server/.env`：

```env
IPXE_ISCSI_CONTAINER=ipxe-iscsi
IPXE_DISK_DIR=/home/iscsi_img              # 容器内盘目录（对应 2.1 设置的宿主存储目录）
IPXE_IQN_BASE=iqn.2026-07.com.controller   # 本节点 IQN 前缀（权威值）：建盘按它生成盘 IQN，Worker 启动时 /boot-vars 按盘所在节点返回该前缀
IPXE_BACKEND=lio                           # 与 2.2 的选择一致（stgt / lio）
IPXE_AGENT_TOKEN=<生成一个token>           # 生成：openssl rand -hex 32
TZ=Asia/Shanghai
```

> **IQN 按 Worker 启动时动态解析**:`tftp/boot.ipxe.cfg` 里的 `base-iqn` 只是静态兜底值（占位符）。
> Worker 启动时，iPXE 从 Control Plane 拉取 `/boot-vars`，该端点按 Worker 系统盘所在存储节点返回实际的 `base-iqn`
> （即盘 IQN 前缀，源自该节点 `IPXE_IQN_BASE`），并覆盖静态兜底值。
> 因此各存储节点的 `IPXE_IQN_BASE` 对自身承载的盘是权威值，无需与 `boot.ipxe.cfg` 静态值一致。

### 2.4 登记 Agent

在 Controller 的 `control_plane/config/agents.yml` 登记本节点（一个节点一条）：

```yaml
agents:
  storage-lio-01:                  # Agent ID（唯一）
    base_url: http://host.docker.internal:4840   # 与 Controller 同机；异地部署填 http://<存储节点IP>:4840
    iscsi_server: 192.168.80.3     # Worker 实际连接 iSCSI 的地址（本节点 IP）
    token: <与 IPXE_AGENT_TOKEN 相同>
    role:
      disk: true                   # 磁盘能力（LIO 不支持 ISO 光驱，cd 必须 false）
      cd: false
    tags:
      - storage
      - lio
    enabled: true
```

多节点部署：每台存储节点重复 2.1–2.3，并在 `agents.yml` 追加一条记录（Agent ID 不同）。

### 2.5 启动存储节点

```bash
cd iscsi-server
docker compose up -d
```

### 2.6 验证

```bash
curl http://localhost:4840/healthz            # Agent 存活
# WebUI → Agents 页面确认 Agent 状态为在线（live）
```

---

## 第 3 步：部署核对清单

| 服务 | 端口 | 验证方式 |
|---|---|---|
| dnsmasq（DHCP/TFTP） | 67/69/UDP | Worker 开机能拿到 IP 并加载 iPXE |
| Control Plane | 4839 | `curl http://localhost:4839/healthz` |
| WebUI | 4838 | 浏览器可访问 |
| iSCSI Agent | 4840 | `curl http://localhost:4840/healthz`；WebUI Agents 页在线 |
| iSCSI 后端 | 3260 | WebUI 创建盘后 Workers 页显示 target |

环境就绪后，进入母盘制备与无盘上线流程 ↓

* **Windows**：《Windows 无盘快速部署（母盘克隆）》
* **Debian 系**：《Debian 系无盘快速部署（母盘克隆）》
