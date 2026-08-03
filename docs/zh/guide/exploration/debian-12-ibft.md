# 第四章：Debian 系 iBFT 无盘启动——母盘克隆的优雅解法

第三章收官时，三条路线全部跑通：官方安装器、镜像转换、debootstrap 骨架。但有一件事始终没有放下——**三条路线都需要在每台机器的 initramfs 里注入 iSCSI 参数**。每加一台 Worker，就要改一次 `/etc/iscsi/iscsi.initramfs`、重建一次 initrd。

而 Windows 侧的路径则截然不同：虚拟机里正常安装一次，vmdk 转成 img，WebUI 点一下克隆，**插电即启动**。登录身份由固件提供，而非写入盘内。

Linux 为什么做不到？——不是做不到，是这条路上藏着一个几乎没人走过的开关：**iBFT**。

## 4.1 问题的本质：Linux 无盘的身份，藏在哪

无盘启动的本质是**身份寻址**：系统引导时必须确定三要素——发起端标识（initiator）、存储端目标（target）与逻辑单元（LUN），即明确“启动源位于何处、以何身份访问”。问题的关键在于：这份身份信息存放于何处、由谁注入。

| | Windows | Linux（第三章三条路线） |
|---|---|---|
| 身份载体 | 固件写入内存的 iBFT 表 | initramfs 里的静态配置文件 |
| 谁来写 | iPXE `sanboot` 自动写 | 手工编辑 `/etc/iscsi/iscsi.initramfs` |
| 每台机器的动作 | 零（克隆即用） | 改文件 + 重建 initrd（per-worker 定制） |
| 批量上线 | WebUI 秒级克隆 | 每台重复施工 |

**优雅的定义**：把"每台机器都要做的事"收敛成"母盘做一次的事"。Windows 做到了，因为微软与固件厂商约定了 iBFT 协议；Linux 同样具备这条固件路径——`iscsi_ibft` 内核模块与 `iscsistart -b` 存在了十几年，只是极少有人把整条链路走通过。

## 4.2 iBFT：固件级的身份协议

iBFT（iSCSI Boot Firmware Table）是 ACPI 规范定义的引导信息表，传统上由板载网卡的 Boot ROM 写入内存。iPXE 的 `sanboot` 命令同样会构造并写入这张表——这正是 Windows 无盘能"盘自己知道自己是谁"的底层机制。

iBFT 表包含：initiator 名称、target 地址与端口、LUN、CHAP 凭据、发起网卡的 MAC。内核启动时，这张表即是固件提供的唯一身份凭证。

完整的 iBFT 无盘链路共六环：

```
① iPXE sanboot ──> 内存中写入 iBFT 表
② 内核 ISCSI_IBFT_FIND=y ──> 引导早期发现表的存在
③ iscsi_ibft 模块 ──> 导出 /sys/firmware/ibft/
④ initramfs local-top/iscsi（ISCSI_AUTO 分支）──> modprobe iscsi_ibft + iscsistart -N
⑤ iscsistart -b ──> 读取固件表逐条建立会话
⑥ root=UUID ──> 挂载根文件系统，进入用户态
```

第 ① 环与 Windows 完全共用——iPXE 写表不分操作系统；第 ⑥ 环是第三章验证过的 UUID 自洽机制。真正的探索发生在 ② ~ ⑤：**内核到底认不认这张表？initramfs 到底有没有自动消费它的代码？**

## 4.3 证据链：内核与 open-iscsi 的原生支持

### 4.3.1 内核：官方配置实锤

下载 Debian 官方 `linux-config-6.1` 配置包解包后，关键项一目了然：

```config
CONFIG_ISCSI_IBFT_FIND=y    # 内核内置：引导早期扫描并注册 iBFT 表
CONFIG_ISCSI_IBFT=m         # 模块导出 /sys/firmware/ibft/
CONFIG_ISCSI_TCP=m          # iSCSI over TCP 传输
```

`_FIND=y` 意味着表发现逻辑直接编进内核，不依赖 initramfs 加载任何模块——**内核层面无条件支持**。表的内容由 `iscsi_ibft` 模块在 initramfs 阶段挂载到 `/sys/firmware/ibft/`，供用户态工具读取。

### 4.3.2 initramfs：一个几乎没人知道的官方开关

open-iscsi 的 Debian 打包自带 initramfs 集成（`debian/extra/initramfs/`），两条关键证据：

**hook 脚本只拷贝三样东西**（`hooks/iscsi`）：

```sh
copy_exec /sbin/iscsistart /sbin
cp /etc/iscsi/initiatorname.iscsi $DESTDIR/etc
if [ -r /etc/iscsi/iscsi.initramfs ]; then
    cp /etc/iscsi/iscsi.initramfs $DESTDIR/etc
fi
```

注意：**没有 iscsid、没有 iscsid.conf**。initramfs 阶段的一切 iSCSI 操作都走 `iscsistart`（独立的小工具，不依赖 iscsid 守护进程）。

**local-top 脚本的 ISCSI_AUTO 分支**（`local-top/iscsi`）：

```sh
if [ -n "$ISCSI_AUTO" ]; then
    modprobe iscsi_ibft
    iscsistart -N    # 读取固件表信息（iBFT）
    iscsistart -f    # 依据固件表尝试登录
    ...
fi
```

`ISCSI_AUTO` 来自内核参数 `iscsi_auto`——一个由 Debian 打包脚本预留、但极少被使用的**官方隐藏开关**。此外，`iscsistart -b` 分支（`case 'b'`）会遍历整张固件表逐条建立会话，作为全自动登录的兜底路径。

### 4.3.3 与 node.startup 无关

一个常见的误解是修改 `/etc/iscsi/iscsid.conf` 的 `node.startup = automatic` 会影响 iBFT 启动。源码证明：initramfs 根本不携带 iscsid.conf、不启动 iscsid 进程，`node.startup` 的作用域是**系统进入用户态之后** open-iscsi 服务的 `iscsiadm -m node -L automatic`。对 iBFT 引导路径：**零影响，保持默认即可**。

## 4.4 母盘构建配方

四条命令级改动，全部收敛进母盘：

```bash
# ① 安装 open-iscsi（提供 iscsistart 与 initramfs 集成脚本）
apt update && apt install -y open-iscsi

# ② 注入 initramfs 必需模块
cat >> /etc/initramfs-tools/modules <<'EOF'
iscsi_tcp
ib_iser
iscsi_ibft
EOF

# ③ 追加引导参数（iscsi_auto 是灵魂，ip=dhcp 与 ipv6.disable=1 保证网络就绪）
sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT="\([^"]*\)"/GRUB_CMDLINE_LINUX_DEFAULT="\1 ip=dhcp ipv6.disable=1 iscsi_auto"/' /etc/default/grub

# ④ 重建 initrd（注意：chroot 中 uname -r 返回宿主内核，务必显式指定版本）
update-grub
update-initramfs -u -k all
```

重建后验证 initrd 是否完备：

```bash
lsinitramfs /boot/initrd.img-$(ls /boot | grep -oP 'vmlinuz-\K.*' | head -1) | \
    grep -E "iscsistart|local-top/iscsi|iscsi_(tcp|ibft)"
```

预期同时看到：`/sbin/iscsistart`、`scripts/local-top/iscsi`、`lib/modules/.../iscsi_ibft.ko`。

### 4.5 真实硬件制备（备选路径）

当目标硬件包含虚拟机无法覆盖的专有驱动（特殊网卡 / RAID / HBA）时，可直接在真实硬件上安装 Debian，产物即母盘——四步配方为纯盘内操作，与盘源无关：

1. 在一台**与目标 Worker 同型号**的机器上，按常规方式安装 Debian 12，装好全部驱动。
2. 应用 4.4 节的四步配方（open-iscsi、三模块、`iscsi_auto`、BOOTX64.EFI）——在系统内直接执行，或盘挂到其他机器后 chroot 改造均可。
3. 将本地盘转换为 raw 镜像：

```bash
# 全盘拷贝（conv=sparse 跳过空洞，节省空间）
dd if=/dev/sdb of=_tpl_debian_12.img bs=4M conv=sparse status=progress
```

4. 命名规范与上传、克隆流程与虚拟机母盘**完全一致**（见 4.6 节后续章节）。

> 注意：真实硬件母盘的驱动绑定的是**制备机的硬件型号**，克隆目标必须与制备机同型号 / 同平台；
> 其余契约（`_tpl_` 命名、四步配方、BOOTX64.EFI、WebUI 克隆）与虚拟机母盘完全相同。

## 4.6 实测：0x7f22208e 与固件的可移动介质契约

第一次实测克隆盘启动，停在 iPXE 报错：

```
Registered SAN device 0x80
Boot from SAN device 0x80 failed: Error 0x7f22208e (https://ipxe.org/7f22208e)
```

对照 iPXE 官方错误码页，`0x7f22208e` 是 **Platform-generated error**，来源为 `interface/efi/efi_block.c`——iPXE 已经把盘交给了固件，**是固件无法从该设备启动**。官方备注明确指出：

> There must be a FAT32 or other EFI compatible partition and filesystem. There must be an EFI executable named correctly on this partition, (usually `/efi/boot/bootx64.efi`). **It is your system Firmware that fails to run the boot process of the device, not iPXE.**

根因瞬间清晰：iPXE 在 UEFI 模式下将 SAN 盘呈现给固件后，固件走的是**可移动介质引导路径**，只认 ESP 分区里的 `\EFI\BOOT\BOOTX64.EFI`。而：

- **Debian 安装器不创建这个文件**——它只写 `\EFI\debian\grubx64.efi` + NVRAM 启动项（虚拟机正常启动走 NVRAM 路径，所以母盘在虚拟机里一切正常）；
- **Windows 安装器一定会写**——`bootmgfw.efi` 的副本天然存在于 `\EFI\BOOT\BOOTX64.EFI`。

这就解释了为什么 Windows 克隆后即可启动、Debian 却首次启动即失败。修复同样是一条命令，收敛进母盘 ESP：

```bash
mount /dev/loop0p1 /mnt/esp
mkdir -p /mnt/esp/EFI/BOOT
cp /mnt/esp/EFI/debian/grubx64.efi /mnt/esp/EFI/BOOT/BOOTX64.EFI
umount /mnt/esp
```

拷贝不影响 grub 行为：`grubx64.efi` 的配置路径（prefix）内嵌于二进制，仍指向根分区的 `/boot/grub/grub.cfg`——**4.4 节写入的 `iscsi_auto` 参数就在那里**。固件加载 `BOOTX64.EFI` → grub → 读 grub.cfg → 带 `iscsi_auto` 进入 initramfs，六环链路由此接通。

## 4.7 验证结果与推广意义

### 验证结论

Debian 12 母盘经克隆后由 iPXE 无盘启动：**系统正常进入，桌面环境正常启动**。整条链路零自定义脚本、零 per-worker 定制。

### 为什么 Debian 系通用

方案依赖的三个零件全部是 Debian 系的**标准件**：

| 依赖 | 通用性依据 |
|---|---|
| initramfs 的 `local-top/iscsi` 与 `iscsi_auto` | open-iscsi 打包脚本，Ubuntu / Mint / Deepin 等 deb 系同源 |
| 内核 `iscsi_ibft` / `ISCSI_IBFT_FIND=y` | Ubuntu 等内核配置沿袭 Debian，模块与路径一致 |
| 固件契约 `\EFI\BOOT\BOOTX64.EFI` | UEFI 规范层，与发行版无关（坑也一样，Ubuntu 安装器同样不写） |

同一份配方可覆盖整个 Debian 系。注意点：Ubuntu 的 grub 位于 `\EFI\ubuntu\`（拷贝源路径不同）；若启用 Secure Boot，BOOTX64.EFI 应拷贝 `shimx64.efi` 而非 `grubx64.efi`。deb 系之外的发行版（RHEL 系、Arch）使用 dracut 而非 initramfs-tools，机制不同，需另行适配。

### 与第三章路线的对比

| 维度 | 第三章（三条路线） | 第四章（iBFT） |
|---|---|---|
| 首次施工 | 每台机器注入参数 + 重建 initrd | 母盘一次 |
| 克隆之后 | 仍需 per-worker 定制 | 零处理 |
| 玄学面 | 散落在各机器脚本中 | 收敛进固件 + 母盘 |
| 批量上线 | 逐台重复 | WebUI 秒级克隆 |
| 依赖 | 自定义配置 + hook 注入 | 官方机制（iscsi_auto） |

## 结语：一个参数 + 一个文件

回顾整条探索：内核早就支持（`CONFIG_ISCSI_IBFT_FIND=y`），initramfs 早就预留了开关（`iscsi_auto`），固件契约只差一个文件（`BOOTX64.EFI`）。没有任何自定义脚本，没有 per-worker 施工——**最优雅的实现，往往是顺着既有机制走完最后一步**。

从今天起，Windows 与 Debian 系在无盘世界里站在了同一条起跑线上：装一次、转镜像、克隆、开机。复杂度被放在了唯一正确的位置——母盘。
