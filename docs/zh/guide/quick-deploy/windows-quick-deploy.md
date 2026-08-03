# Windows 无盘快速部署(母盘克隆)

> **本文档定位:母盘专题 · 快速上线。**
> 从母盘到 Windows 无盘 Worker 全流程:制备母盘 → 上传 → WebUI 秒级克隆 → 开机直达桌面。
> 环境部署(Controller + 存储节点)见《项目环境部署》,本文从母盘制备开始。
> 与第二章(从零安装)不同,本文档不定制 PE、不讲解安装原理,只讲可照抄的流程与命令。

## 为什么 Windows 可以"克隆即用"

Windows 无盘启动依赖 iPXE 写入的 iBFT(iSCSI Boot Firmware Table):启动参数全部由固件在启动瞬间写入,
**盘内不写死任何机器身份信息**(磁盘标识、启动项、网络配置均与具体机器解耦)。
因此母盘只要能在虚拟机上正常启动,克隆出来的每一块盘都 100% 可引导。

已在以下版本完成全量验证,**无任何坑**:

| Windows 版本 | 验证状态 |
|---|---|
| Windows 11 23H2 | 已验证 |
| Windows 11 24H2 | 已验证 |
| Windows 11 25H2 | 已验证 |

不同版本通过**选择不同母盘**来区分,无需修改任何代码或配置。

### 与第二章(从零安装)的差异

两条路都能得到可无盘启动的 Windows,但安装发生的**位置**不同,复杂度完全不同:

| 事项 | 第二章:从零安装(iPXE 直装) | 本文档:母盘克隆 |
|---|---|---|
| 系统安装位置 | iPXE → WinPE → iSCSI 盘 | 虚拟机本地盘(常规安装) |
| PE 定制 / dism++ 注入驱动 | 必需 | 不需要 |
| ISO 虚拟光驱(双 Target) | 必需(sanhook + `--device-type cd`) | 不需要 |
| 批量上线 | 每台重复安装 | WebUI 秒级克隆 |

母盘克隆模式下,安装完全发生在虚拟机内,第二章的整条 PE 链路(含 ISO 虚拟光驱)被**整体绕过**;
克隆后由 iBFT 机制保证启动,无需任何盘内处理。

## 环境准备

Controller(控制面)与存储节点(Agent + iSCSI 后端)的部署见《项目环境部署》,平台无关,对 Windows / Debian 一视同仁。
唯一契约:`IPXE_IQN_BASE` 与 `tftp/boot.ipxe.cfg` 的 `base-iqn` 一致。

---

## 第 1 步:制备母盘

### 1.1 在虚拟机中安装 Windows

在虚拟机中**按常规方式安装 Windows 11**(23H2 / 24H2 / 25H2 均可),怎么装都行——官方镜像安装、
封装镜像还原、现有系统迁移均可。安装完成后:

* 安装 VMware Tools(或对应虚拟化平台的驱动包),确保**网卡驱动**就绪。
* 建议把虚拟机磁盘控制在目标盘容量(如 40GB / 60GB)。
* 安装完成后**关机**(不要启动系统做任何初始化)。

### 1.2 vmdk 转 raw 镜像

找到虚拟机的磁盘文件(`.vmdk`),执行转换:

**Windows 本机(PowerShell):**

```powershell
qemu-img convert -p -f vmdk -O raw `
    "Windows 11 x64.vmdk" "_tpl_windows_23h2.img"
```

**Linux 本机:**

```bash
qemu-img convert -p -f vmdk -O raw "Windows 11 x64.vmdk" "_tpl_windows_23h2.img"
```

**母盘命名规范**(必须遵循,WebUI 克隆时按此名称选择母盘):

| 版本 | 母盘文件名 |
|---|---|
| Windows 11 23H2 | `_tpl_windows_23h2.img` |
| Windows 11 24H2 | `_tpl_windows_24h2.img` |
| Windows 11 25H2 | `_tpl_windows_25h2.img` |

> 命名规则:`_tpl_系统_版本.img`。`_tpl` 前缀标记该文件为母盘模板,
> 克隆出的 Worker 盘才是正式盘(`worker-xx.windows.img`,由系统自动生成)。

### 1.3 在真实硬件上安装 Windows(备选路径)

当目标硬件包含**虚拟机无法覆盖的专有驱动**(特殊网卡 / RAID / HBA 控制器)时,
可以直接在真实硬件上安装一次,产物即母盘——驱动真实匹配,克隆零驱动问题:

1. 在一台**与目标 Worker 同型号**的机器上,按常规方式安装 Windows 11(23H2 / 24H2 / 25H2 均可),装好全部驱动后关机。
2. 将本地盘转换为 raw 镜像,三种方式任选:

**方式一:Windows 内在线转换(推荐,无需拔盘)**

用 Sysinternals [disk2vhd](https://learn.microsoft.com/en-us/sysinternals/downloads/disk2vhd) 把系统盘转为 vhd,再转 raw:

```powershell
# 磁盘 C: 转换为 vhd
.\disk2vhd.exe c: C:\tpl_windows_23h2.vhd

# vhd → raw
qemu-img convert -p -f vpc -O raw "C:\tpl_windows_23h2.vhd" "_tpl_windows_23h2.img"
```

**方式二:拔盘 dd(Windows 系统盘挂到 Linux 机器)**

```bash
# 确认盘符后全盘拷贝(conv=sparse 跳过空洞,节省空间)
dd if=/dev/sdb of=_tpl_windows_23h2.img bs=4M conv=sparse status=progress
```

**方式三:WinPE / Ubuntu Live 启动后 dd**,命令同上。

3. 转换完成后,命名规范与上传、克隆流程与虚拟机母盘**完全一致**(见 1.2 命名表与第 2 步)。

> 注意:真实硬件母盘的驱动绑定的是**制备机的硬件型号**,克隆目标必须与制备机同型号 / 同平台;
> 其余契约(`_tpl_` 命名、上传、WebUI 克隆、iBFT 启动)与虚拟机母盘完全相同。

## 第 2 步:上传母盘

将母盘镜像上传到 Controller 的镜像目录:

```bash
scp .\_tpl_windows_23h2.img dutyc@192.168.80.3:/pool1/iscsi_img
```

上传完成后**无需任何额外操作**:

* 母盘不会自动挂载为 iSCSI Target(LIO 后端按已保存的配置恢复,不会扫描目录)。
* 母盘可以随时更新:重新上传同名文件即可,**不影响**已克隆出去的 Worker 盘(克隆是复制,不是引用)。

## 第 3 步:Worker 通电,自动注册

将无盘 Worker 设置为网络启动(PXE),通电开机:

1. DHCP 获取地址 → 加载 iPXE → 拉取启动变量。
2. **新 MAC 自动注册**:Control Plane 自动分配主机名(`worker-01`、`worker-02` …),
   写入台账并自动绑定 DHCP 静态地址,全程零人工干预。
3. 打开 WebUI(`http://x.x.x.x:4838`)→ **Workers** 页面,即可看到新注册的 Worker。

## 第 4 步:WebUI 秒级克隆

在 Workers 页面点击 Worker 进入详情页,创建系统盘:

| 表单字段 | 填写 |
|---|---|
| 操作系统(OS) | `Windows` |
| 磁盘类型(Type) | `Master`(母盘克隆) |
| 母盘文件名(Master Name) | `_tpl_windows_23h2.img`(即第 1 步的母盘名) |

点击创建,**秒级完成**——克隆基于文件系统 reflink(写时复制),瞬间生成完整系统盘,
同时自动完成 iSCSI Target 创建与 IQN 命名(`iqn.2026-07.com.controller:worker-01.windows`),
全程无需触碰命令行。

## 第 5 步:设置默认启动(可选)

不设置时,Worker 每次开机进入 iPXE 菜单,手动选择 **Boot Windows from iSCSI**。

如需开机直达桌面,在 Worker 详情页的 **默认启动(Default Boot)** 区域设置:

| 表单字段 | 填写 |
|---|---|
| 默认系统(OS) | `Windows` |
| 默认菜单项(Menu Default) | `windows` |

保存后,该 Worker 的启动变量即时下发(`/boot-vars`),下次开机自动进入 Windows。

## 第 6 步:验证

1. 重启 Worker,观察启动链:iPXE → iSCSI 登录 → Windows 启动 Logo。
2. 进入桌面即验证成功;重复第 3–5 步可批量上线任意数量的 Worker。
3. 在 WebUI 的 Workers 页面确认盘状态(IQN / 文件名 / 来源 `master: _tpl_windows_23h2.img`)。

## 批量克隆与版本管理

* **批量上线**:多台机器同时通电,自动注册 → 逐个在 WebUI 克隆 → 设置默认启动。
* **版本切换**:克隆时选择不同母盘即可(`_tpl_windows_23h2.img` / `24h2` / `25h2`),互不影响。
* **一台机器多系统**:Worker 详情页可为同一 Worker 创建多块系统盘,随时切换默认启动系统。

## 常见问题

| 问题 | 处理 |
|---|---|
| 克隆盘启动后停在 iPXE 菜单 | 未设置默认启动,手动选择 **Boot Windows from iSCSI**,或按第 5 步设置 |
| 克隆盘无法启动(转圈/蓝屏) | 母盘自身问题:检查母盘网卡驱动是否就绪、母盘在虚拟机中能否正常启动 |
| 多台克隆机计算机名相同 | 属于预期行为(盘内身份未写入机器信息)。如需区分,自行处理(改名 / sysprep),不影响启动 |
| 找不到 iSCSI 目标 | ① 核对 `iscsi-server/.env` 的 `IPXE_IQN_BASE` 与 `tftp/boot.ipxe.cfg` 的 `base-iqn` 一致;② 确认 Worker 已在 WebUI 注册(hostname 绑定生效);③ 详情页磁盘列表中 IQN 为 `…:worker-xx.windows` |
| WebUI 操作报 401 | Control Plane 设了 `IPXE_CP_TOKEN` 但 `webui/app/.env` 未同步(见《项目环境部署》1.4),或改后未重新构建 WebUI |
| 想换母盘版本 | 上传新母盘 → 对目标 Worker 克隆时选择新母盘。已有 Worker 盘不受影响 |
