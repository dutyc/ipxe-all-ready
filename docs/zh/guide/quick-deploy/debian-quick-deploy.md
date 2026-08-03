# Debian 系无盘快速部署(母盘克隆)

> **本文档定位:母盘专题 · 快速上线。**
> 从母盘到 Debian 系无盘 Worker 全流程:制备母盘(含 iBFT 改造)→ 上传 → WebUI 秒级克隆 → 开机直达系统。
> 环境部署(Controller + 存储节点)见《项目环境部署》,本文从母盘制备开始。

## 为什么 Debian 系可以"克隆即用"

与 Windows 同路径:启动参数由 iPXE `sanboot` 写入的 **iBFT 表**(iSCSI Boot Firmware Table)在启动瞬间提供,
initramfs 通过内核参数 `iscsi_auto` 自动读取固件表登录 iSCSI,**盘内不写死任何机器身份信息**。

但 Debian 系母盘与 Windows 母盘有一个**实质差别**:Windows 安装器会把引导文件放到固件要求的可移动介质路径,
Debian 系安装器不会——因此母盘需要一次性改造(**四步配方**),改造后克隆盘即用、零 per-worker 定制。

已实测验证:**Debian 12 母盘克隆后无盘启动,系统与桌面环境正常**;
Ubuntu 等 Debian 系发行版走同一链路,制备与克隆流程完全一致。

## 支持范围

机制前提(全部为 Debian 系发行版标准组件):initramfs-tools + open-iscsi(自带 initramfs 集成,
支持 `iscsi_auto` 参数)+ 内核 `iscsi_ibft` 模块(内核 ≥ 3.10 起为标准配置,
`CONFIG_ISCSI_IBFT=m` 强制开启 `CONFIG_ISCSI_IBFT_FIND=y`)。

| 发行版 | 支持版本 | 状态 |
|---|---|---|
| Debian | 11 / 12 / 13 | 机制支持,12 已实测 |
| Ubuntu | 22.04 / 24.04 / 26.04(LTS)及非 LTS 新版本 | 机制支持(同链路) |

> 不推荐 Debian 10、Ubuntu 20.04 及更早版本(已 EOL,机制虽满足但无安全支持期)。
> Ubuntu 的 iBFT 内核模块(`iscsi_ibft` / `iscsi_tcp` / `ib_iser`)位于基础内核包,最小安装亦自带,无需额外安装。

## 环境准备

Controller(控制面)与存储节点(Agent + iSCSI 后端)的部署见《项目环境部署》,平台无关,对 Windows / Debian 一视同仁。
唯一契约:`IPXE_IQN_BASE` 与 `tftp/boot.ipxe.cfg` 的 `base-iqn` 一致。

---

## 第 1 步:制备母盘

### 1.1 在虚拟机中安装 Debian 系发行版(主路径)

在虚拟机中**按常规方式安装 Debian 12**(或 Ubuntu 22.04 / 24.04 / 26.04 等 Debian 系发行版,见「支持范围」),关键前提:

* **必须 UEFI + GPT 安装**(BIOS 安装无 ESP 分区,无法满足 BOOTX64.EFI 固件契约)。
* 分区建议:ESP 分区 512M + 根分区 + swap(常规自动分区即可满足)。
* 安装桌面或服务器按需选择;安装完成后**关机**,准备盘内改造。

### 1.2 在真实硬件上安装(备选路径)

目标硬件含虚拟机无法覆盖的专有驱动(特殊网卡 / RAID / HBA)时,可在**同型号机器**上常规安装 Debian 12
(或对应 Debian 系发行版),驱动真实匹配。此路径下第 1.3 步直接在系统内执行,无需 chroot;
克隆目标必须与制备机同型号 / 同平台。

### 1.3 四步配方:盘内改造(核心)

将虚拟机磁盘挂载到任意 Linux 机器(`losetup -Pf` + chroot),或在真实硬件系统内直接执行:

```bash
# ① 安装 open-iscsi(提供 iscsistart 与 initramfs 集成脚本)
apt update && apt install -y open-iscsi

# ② 注入 initramfs 必需模块
cat >> /etc/initramfs-tools/modules <<'EOF'
iscsi_tcp
ib_iser
iscsi_ibft
EOF

# ③ 追加引导参数(iscsi_auto 是 iBFT 自动登录的开关)
sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT="\([^"]*\)"/GRUB_CMDLINE_LINUX_DEFAULT="\1 ip=dhcp ipv6.disable=1 iscsi_auto"/' /etc/default/grub

# ④ 重建 initrd(注意:chroot 中 uname -r 返回宿主内核,务必用 -k all 指定)
update-grub
update-initramfs -u -k all
```

chroot 改造的挂载流程:

```bash
losetup -Pf _tpl_debian_12.img
mount /dev/loop0p2 /mnt/img          # p2 为根分区(按实际分区调整)
mount --bind /dev /mnt/img/dev
mount --bind /proc /mnt/img/proc
mount --bind /sys /mnt/img/sys
chroot /mnt/img /bin/bash            # 在 chroot 内执行上述四步
# 结束后退出并卸载:exit → umount /mnt/img/{dev,proc,sys} → umount /mnt/img → losetup -d /dev/loop0
```

### 1.4 补 BOOTX64.EFI(固件可移动介质契约)

UEFI 引导下固件只认 ESP 分区里的 `\EFI\BOOT\BOOTX64.EFI`,而 Debian 安装器不会创建它——**缺了它克隆盘报 `0x7f22208e`**:

```bash
mount /dev/loop0p1 /mnt/esp          # p1 为 ESP 分区
mkdir -p /mnt/esp/EFI/BOOT
cp /mnt/esp/EFI/debian/grubx64.efi /mnt/esp/EFI/BOOT/BOOTX64.EFI
umount /mnt/esp
```

> 若启用 Secure Boot,BOOTX64.EFI 应拷贝 `shimx64.efi` 而非 `grubx64.efi`(VMware 默认关闭,直接 grubx64.efi 即可)。
> Ubuntu 安装器的源文件在 `\EFI\ubuntu\`(Debian 在 `\EFI\debian\`),拷贝源路径按实际发行版调整。

### 1.5 验证 initrd 三件套

```bash
lsinitramfs /boot/initrd.img-$(ls /boot | grep -oP 'vmlinuz-\K.*' | head -1) | \
    grep -E "iscsistart|local-top/iscsi|iscsi_(tcp|ibft)"
```

预期同时看到:`/sbin/iscsistart`、`scripts/local-top/iscsi`、`lib/modules/.../iscsi_ibft.ko`。
三者齐备才可继续,缺任何一项回 1.3 重查。

### 1.6 转换与命名

**虚拟机路径**(vmdk 转 raw):

```bash
qemu-img convert -p -f vmdk -O raw "Debian 12 x64.vmdk" "_tpl_debian_12.img"
```

**真实硬件路径**(dd 全盘):

```bash
dd if=/dev/sdb of=_tpl_debian_12.img bs=4M conv=sparse status=progress
```

| 版本 | 母盘文件名 |
|---|---|
| Debian 12 | `_tpl_debian_12.img` |
| Ubuntu 24.04(示例) | `_tpl_ubuntu_24.04.img` |

> 命名规则与 Windows 相同:`_tpl_系统_版本.img`。`_tpl` 前缀标记母盘模板,克隆出的 Worker 盘为正式盘(`worker-xx.debian.img`,系统自动生成)。
> Ubuntu 母盘克隆时 OS 选 `Ubuntu`(IQN 后缀 `.ubuntu`);其余流程与 Debian 完全一致。

## 第 2 步:上传母盘

```bash
scp _tpl_debian_12.img dutyc@192.168.80.3:/pool1/iscsi_img
```

上传后**无需任何额外操作**:母盘不会自动挂载为 Target;更新母盘重新上传同名文件即可,不影响已克隆出去的 Worker 盘。

## 第 3 步:Worker 通电,自动注册

无盘 Worker 设为网络启动,通电:

1. DHCP 获取地址 → 加载 iPXE → 拉取启动变量。
2. **新 MAC 自动注册**:自动分配主机名(`worker-01`、`worker-02` …),绑定 DHCP 静态地址,零人工干预。
3. WebUI(`http://192.168.80.3:4838`)→ **Workers** 页面查看新 Worker。

## 第 4 步:WebUI 秒级克隆

Workers 页面进入 Worker 详情页,创建系统盘:

| 表单字段 | 填写 |
|---|---|
| 操作系统(OS) | `Debian` |
| 磁盘类型(Type) | `Master`(母盘克隆) |
| 母盘文件名(Master Name) | `_tpl_debian_12.img`(第 1 步的母盘名) |

秒级完成(reflink 克隆),自动创建 iSCSI Target 与 IQN(`iqn.2026-07.com.controller:worker-01.debian`)。

## 第 5 步:设置默认启动(可选)

不设置时每次开机进 iPXE 菜单手动选择 **Boot Debian from iSCSI**。开机直达,在 Worker 详情页设置:

| 表单字段 | 填写 |
|---|---|
| 默认系统(OS) | `Debian` |
| 默认菜单项(Menu Default) | `debian` |

## 第 6 步:验证

1. 重启 Worker,观察启动链:BOOTX64.EFI → grub → iSCSI 登录 → 系统。
2. 进入系统后验收 iBFT 证据:

```bash
ls /sys/firmware/ibft/     # 固件表导出(网卡目录 + initiator/target)
iscsiadm -m session        # 当前 iSCSI 会话
```

3. WebUI Workers 页面确认盘状态(IQN / 文件名 / 来源 `master: _tpl_debian_12.img`)。

## 批量克隆与版本管理

* **批量上线**:多台机器同时通电 → 自动注册 → WebUI 逐个克隆 → 设置默认启动。
* **版本切换**:克隆时选择不同母盘(`_tpl_debian_12.img` / 其他版本)即可,互不影响。
* **一台机器多系统**:同一 Worker 可挂多块系统盘(Windows + Debian),随时切换默认启动系统。

## 常见问题

| 问题 | 处理 |
|---|---|
| 克隆盘报 `Boot from SAN device failed: Error 0x7f22208e` | ESP 缺 BOOTX64.EFI:按 1.4 补文件后**重新克隆**(旧克隆盘不带);确认母盘为 UEFI + GPT 安装 |
| 启动停在 iPXE 菜单 | 未设置默认启动,手动选择 **Boot Debian from iSCSI**,或按第 5 步设置 |
| 找不到 iSCSI 目标 | ① `iscsi-server/.env` 的 `IPXE_IQN_BASE` 与 `boot.ipxe.cfg` 的 `base-iqn` 一致;② Worker 已在 WebUI 注册;③ 详情页 IQN 为 `…:worker-xx.debian` |
| `VFS: Unable to mount root fs` | initrd 三件套未齐(1.5 验证失败):缺模块/iscsistart,回 1.3 重做并 `update-initramfs -u -k all` |
| 担心克隆盘 `root=UUID` 写死 | 属预期:UUID 是文件系统属性随克隆整体复制,克隆盘各自匹配自身盘,无需处理 |
| 母盘在虚拟机正常、克隆盘无法启动 | 检查 1.4 BOOTX64.EFI 是否已补(最常见的隐蔽原因) |
