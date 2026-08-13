# 引导介质制作指南

## 为什么需要本地引导介质？

在标准的网络启动模型中，机器通电后由网卡 PXE ROM 直接拉取引导程序。然而在真实机房环境（消费级主板、商用办公机及部分白牌服务器）中，纯 PXE 网络引导通常面临显著的**部署障碍**：

1. **固件能力缺失与入口隐蔽**：大量消费级主板（如技嘉、华硕等）的固件不提供独立的 PXE/Network Boot 入口，或将其深藏于多层菜单之下；默认情况下，UEFI Network Stack 往往处于关闭状态。
2. **人工介入成本高**：依赖纯 PXE 时，运维人员须逐台开机、进入 BIOS、启用 Network Boot 并保存重启；在数百台规模的机房中，此类逐台人工操作不可接受。
3. **Secure Boot 限制**：现代主板默认启用 Secure Boot，固件网络栈（SNP/PXE）在加载未经签名的自定义 iPXE 二进制时将抛出 `Security Violation` 并拒绝引导。

**本地引导介质（U 盘、本地 ESP、GRUB 链式加载）的本质，是绕开主板固件在网络引导层面的黑盒限制与繁琐配置，将引导控制权直接移交给无状态固件。**

只要主板支持从 USB 启动，或本地磁盘中已存在受信任的 GRUB/ESP 引导环境，即可跳过固件网络栈，在本地直接加载 `ipxe-stateless`，由其接管后续全部网络交互。

---

本仓库提供以下构建产物，目录结构如下：

```text
├─direct-uefi
│      ipxe-debug.efi
│      ipxe.efi
│
├─grub-bios
│      ipxe.lkrn
│
└─usb
        ipxe.usb
```

全部产物由同一条自动化构建流水线生成，仅载体形态不同，固件逻辑与驱动集合完全一致。使用前应校验文件完整性：

```bash
sha256sum -c SHA256SUMS
```

## UEFI 直启（direct-uefi）

`ipxe.efi` 是标准 UEFI 应用程序，可被任意 x86_64 UEFI 固件直接加载。`ipxe-debug.efi` 为开启详细日志的调试构建，二者功能一致，仅日志详尽程度不同。

### 1.1 制作 UEFI 启动 U 盘（手工）
适用于纯 UEFI 环境，作为便携式引导工具：

```bash
# 假设 U 盘设备为 /dev/sdb，确认无重要数据
mkfs.vfat -F 32 /dev/sdb1

mount /dev/sdb1 /mnt
mkdir -p /mnt/EFI/BOOT
cp direct-uefi/ipxe.efi /mnt/EFI/BOOT/BOOTX64.EFI
sync && umount /mnt
```

`EFI/BOOT/BOOTX64.EFI` 为 UEFI 规范约定的可移动设备默认回退路径，插入后即出现在主板启动菜单（F11/F12）中，无需配置固件网络栈。

### 1.2 写入本地 ESP 并添加启动项
若机器已有本地系统或 ESP 分区，且希望将固件长期置于本地磁盘以摆脱 U 盘：

```bash
mkdir -p /boot/efi/EFI/stateless
cp direct-uefi/ipxe.efi /boot/efi/EFI/stateless/

efibootmgr --create \
  --disk /dev/sda --part 1 \
  --label "iPXE Stateless" \
  --loader '\EFI\stateless\ipxe.efi'
```

### 1.3 注意事项
- 本产物为未签名二进制。开启 Secure Boot 的机器需关闭 Secure Boot，或通过 MokManager 登记哈希。
- 故障复现与日志抓取使用 `ipxe-debug.efi`；生产环境使用 `ipxe.efi`。

## GRUB 引导（grub-bios）

`ipxe.lkrn` 是被封装为 Linux 内核启动头（bzImage 格式）的 iPXE，任何能加载 Linux 内核的引导器均可加载它。

这使得其在「本地已部署 GRUB/SYSLINUX 的 Legacy BIOS 机器」上具有显著价值：**无需改动现有引导链，亦无需在固件中启用 PXE，仅在现有 GRUB 菜单中追加一个条目，即可将控制权无缝移交至网络。**

### 2.1 GRUB2（Legacy BIOS）

在 `/etc/grub.d/40_custom` 中追加：

```bash
menuentry 'iPXE Stateless Boot' {
    insmod linux
    linux16 /boot/ipxe.lkrn
}
```

```bash
update-grub                                # Debian/Ubuntu
# 或 grub2-mkconfig -o /boot/grub2/grub.cfg  # RHEL/CentOS
```

### 2.2 GRUB Legacy（menu.lst）

```text
title iPXE Stateless Boot
kernel /boot/ipxe.lkrn
boot
```

### 2.3 SYSLINUX / PXELINUX

```text
LABEL ipxe
    MENU LABEL iPXE Stateless Boot
    KERNEL ipxe.lkrn
```

### 2.4 UEFI 下的 GRUB：改用 chainloader

`linux16` 仅适用于 BIOS 环境。UEFI GRUB 下不应使用 `.lkrn`，应直接 chainload EFI 产物：

```bash
menuentry 'iPXE Stateless Boot (UEFI)' {
    search --no-floppy --set=root --file /EFI/stateless/ipxe.efi
    chainloader /EFI/stateless/ipxe.efi
}
```

### 2.5 原理说明

`.lkrn` 被加载后，iPXE 立即接管网卡，并以自身原生 PCI 驱动进行驱动，不依赖任何 Linux 运行时。「Linux 内核头」仅是使 GRUB 接受该二进制的一层封装。

## USB 引导介质（usb）

`ipxe.usb` 为整盘 raw 镜像，写入即可使用，适用于无网络引导环境或固件完全禁用网络栈的场景。

### 3.1 Linux 下写入

```bash
lsblk    # 先确认 U 盘设备号，例如 /dev/sdb
dd if=usb/ipxe.usb of=/dev/sdb bs=4M status=progress conv=fsync
```

> **注意**：`of=` 必须指向整盘设备（如 `/dev/sdb`），不得指向分区（如 `/dev/sdb1`）；目标错误将导致该磁盘全部数据被销毁。

### 3.2 Windows 下写入

- **Rufus**：选择 `ipxe.usb` 后，在提示中选择 **“以 DD 镜像模式写入”**；
- 或使用 balenaEtcher，选择镜像直接写入。

### 3.3 启动

写入完成后，将介质插入目标机，在启动菜单（F11/F12）中选择 USB 启动。该镜像包含 BIOS 引导区；若目标机仅支持 UEFI 且固件不提供 Legacy/CSM 兼容选项，请改用 1.1 节的手工 UEFI U 盘方式。

## 选型指南

| 场景 | 推荐产物 |
|---|---|
| 现代 UEFI 机器，网络引导或本地 ESP | `direct-uefi/ipxe.efi` |
| 故障复现、串口/控制台抓日志 | `direct-uefi/ipxe-debug.efi` |
| Legacy BIOS，本地已有 GRUB/SYSLINUX | `grub-bios/ipxe.lkrn` |
| 无网络引导环境，需便携介质 | `usb/ipxe.usb` |
| 纯 UEFI 便携介质 | 第 1.1 节手工 U 盘 |

## 结语：介质仅是载体

以上所有介质均不保存任何状态，亦不携带任何身份，其唯一职责是：**启用网卡并将机器移交至网络。**

通电后，固件向控制面请求身份（iSCSI 目标、IQN、启动变量）；系统盘与身份均来自网络。无论载体为 UEFI、GRUB 还是 USB，其语义完全一致。