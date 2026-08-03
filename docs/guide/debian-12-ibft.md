# Chapter 4: Debian-family iBFT Diskless Boot — The Elegant Golden-Image Clone Approach

By the time Chapter 3 wrapped up, all three paths had been proven: the official installer, image conversion, and the debootstrap skeleton. Yet one thing was never truly laid to rest — **every single path still required injecting iSCSI parameters into each machine’s initramfs**. Every time a new Worker was added, `/etc/iscsi/iscsi.initramfs` had to be modified and the initrd rebuilt.

On the Windows side the story was completely different: install once in a VM, convert the VMDK to an IMG, click “clone” in the WebUI, and **the machine boots the moment it’s powered on**. The login identity is provided by firmware, not baked into the disk.

Why can’t Linux do the same? — It can. There’s just a switch hiding along this path that almost nobody has ever walked: **iBFT**.

## 4.1 The Essence of the Problem: Where Does a Diskless Linux Identity Live?

The core of diskless booting is **identity addressing**: the system must determine three elements during boot — the initiator identity, the storage target, and the logical unit (LUN) — i.e., “where the boot source is located, and what identity to use to access it.” The key question is: where is this identity information stored, and who injects it?

| | Windows | Linux (the three paths in Chapter 3) |
|---|---|---|
| Identity carrier | The iBFT table written into memory by firmware | A static config file inside the initramfs |
| Who writes it | iPXE `sanboot` writes it automatically | Manually edit `/etc/iscsi/iscsi.initramfs` |
| Actions per machine | Zero (clone and go) | Modify files + rebuild initrd (per-worker customization) |
| Bulk rollout | Instant clone via WebUI | Repeat the work on every machine |

**The definition of elegance**: collapse “what every machine must do” into “what the golden image does once.” Windows achieves this because Microsoft and firmware vendors agreed on the iBFT protocol; Linux possesses the exact same firmware path — the `iscsi_ibft` kernel module and `iscsistart -b` have existed for over a decade — but virtually nobody has ever threaded the entire chain end-to-end.

## 4.2 iBFT: A Firmware-Level Identity Protocol

iBFT (iSCSI Boot Firmware Table) is a boot information table defined by the ACPI specification, traditionally written into memory by the Boot ROM of an onboard NIC. The iPXE `sanboot` command also constructs and writes this table — this is precisely the low-level mechanism that allows a diskless Windows system to “know who it is on its own.”

The iBFT table contains: the initiator name, target address and port, LUN, CHAP credentials, and the MAC address of the initiating NIC. When the kernel starts, this table is the sole identity credential provided by firmware.

The complete iBFT diskless chain consists of six links:

```
① iPXE sanboot ──> writes the iBFT table into memory
② Kernel ISCSI_IBFT_FIND=y ──> discovers the table’s presence early in boot
③ iscsi_ibft module ──> exports /sys/firmware/ibft/
④ initramfs local-top/iscsi (ISCSI_AUTO branch) ──> modprobe iscsi_ibft + iscsistart -N
⑤ iscsistart -b ──> reads the firmware table and establishes sessions one by one
⑥ root=UUID ──> mounts the root filesystem, enters user space
```

Link ① is shared entirely with Windows — iPXE writes the table regardless of the operating system. Link ⑥ is the UUID self-consistency mechanism already verified in Chapter 3. The real exploration happens in links ② ~ ⑤: **Does the kernel actually recognise this table? Does the initramfs actually contain code to consume it automatically?**

## 4.3 Chain of Evidence: Native Kernel and open-iscsi Support

### 4.3.1 Kernel: Official Configuration Confirmation

After downloading and unpacking the official Debian `linux-config-6.1` config package, the critical items are clear at a glance:

```config
CONFIG_ISCSI_IBFT_FIND=y    # Built into the kernel: scan and register iBFT table early in boot
CONFIG_ISCSI_IBFT=m         # Module that exports /sys/firmware/ibft/
CONFIG_ISCSI_TCP=m          # iSCSI over TCP transport
```

`_FIND=y` means the table discovery logic is compiled directly into the kernel, without depending on the initramfs to load any modules — **support at the kernel level is unconditional**. The table contents are mounted by the `iscsi_ibft` module to `/sys/firmware/ibft/` during the initramfs stage for user-space tools to read.

### 4.3.2 initramfs: An Official Switch Almost No One Knows About

The Debian packaging of open-iscsi comes with initramfs integration (`debian/extra/initramfs/`). Two key pieces of evidence:

**The hook script copies only three things** (`hooks/iscsi`):

```sh
copy_exec /sbin/iscsistart /sbin
cp /etc/iscsi/initiatorname.iscsi $DESTDIR/etc
if [ -r /etc/iscsi/iscsi.initramfs ]; then
    cp /etc/iscsi/iscsi.initramfs $DESTDIR/etc
fi
```

Notice: **no iscsid, no iscsid.conf**. All iSCSI operations during the initramfs stage go through `iscsistart` (a standalone tool that does not depend on the iscsid daemon).

**The ISCSI_AUTO branch in the local-top script** (`local-top/iscsi`):

```sh
if [ -n "$ISCSI_AUTO" ]; then
    modprobe iscsi_ibft
    iscsistart -N    # Read firmware table information (iBFT)
    iscsistart -f    # Attempt login based on the firmware table
    ...
fi
```

`ISCSI_AUTO` comes from the kernel parameter `iscsi_auto` — an **official hidden switch** reserved by the Debian packaging scripts but almost never used. Additionally, the `iscsistart -b` branch (`case 'b'`) iterates over the entire firmware table and establishes sessions one by one, acting as a fallback path for fully automatic login.

### 4.3.3 Unrelated to node.startup

A common misconception is that setting `node.startup = automatic` in `/etc/iscsi/iscsid.conf` affects iBFT booting. The source code proves otherwise: the initramfs does not carry iscsid.conf at all and does not start the iscsid process. The scope of `node.startup` is the `iscsiadm -m node -L automatic` command issued by the open-iscsi service **after the system enters user space**. For the iBFT boot path: **zero impact; leaving it at the default is fine**.

## 4.4 The Golden Image Build Recipe

Four command-level changes, all collapsed into the golden image:

```bash
# ① Install open-iscsi (provides iscsistart and initramfs integration scripts)
apt update && apt install -y open-iscsi

# ② Inject the required initramfs modules
cat >> /etc/initramfs-tools/modules <<'EOF'
iscsi_tcp
ib_iser
iscsi_ibft
EOF

# ③ Append boot parameters (iscsi_auto is the soul; ip=dhcp and ipv6.disable=1 ensure the network is ready)
sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT="\([^"]*\)"/GRUB_CMDLINE_LINUX_DEFAULT="\1 ip=dhcp ipv6.disable=1 iscsi_auto"/' /etc/default/grub

# ④ Rebuild the initrd (note: in a chroot, `uname -r` returns the host kernel; you must explicitly specify the version)
update-grub
update-initramfs -u -k all
```

After rebuilding, verify that the initrd is complete:

```bash
lsinitramfs /boot/initrd.img-$(ls /boot | grep -oP 'vmlinuz-\K.*' | head -1) | \
    grep -E "iscsistart|local-top/iscsi|iscsi_(tcp|ibft)"
```

Expect to see all three: `/sbin/iscsistart`, `scripts/local-top/iscsi`, `lib/modules/.../iscsi_ibft.ko`.

### 4.5 Real-Hardware Preparation (Alternative Path)

When the target hardware includes proprietary drivers that a VM cannot cover (special NIC / RAID / HBA), you can install Debian directly on real hardware and use the result as the golden image — the four‑step recipe consists of purely in‑disk operations, independent of the disk’s origin:

1. On a machine **identical to the target Worker model**, install Debian 12 using a conventional method and install all drivers.
2. Apply the four‑step recipe from Section 4.4 (open-iscsi, three modules, `iscsi_auto`, BOOTX64.EFI) — execute it directly inside the running system, or attach the disk to another machine and perform chroot adaptation.
3. Convert the local disk to a raw image:

```bash
# Full disk copy (conv=sparse skips holes to save space)
dd if=/dev/sdb of=_tpl_debian_12.img bs=4M conv=sparse status=progress
```

4. The naming convention, upload, and clone process are **exactly the same** as for a VM golden image (see the sections following Section 4.6).

> Note: For a real‑hardware golden image, the drivers are bound to the **hardware model of the preparation machine**; the clone target must have the same model / platform.  
> All other contracts (`_tpl_` naming, the four‑step recipe, BOOTX64.EFI, WebUI cloning) are identical to a VM golden image.

## 4.6 Real-World Testing: 0x7f22208e and the Firmware Removable-Media Contract

The first real-world test booting a cloned disk stopped at an iPXE error:

```
Registered SAN device 0x80
Boot from SAN device 0x80 failed: Error 0x7f22208e (https://ipxe.org/7f22208e)
```

Cross-referencing the official iPXE error code page, `0x7f22208e` is a **Platform-generated error** originating from `interface/efi/efi_block.c` — iPXE had already handed the disk over to the firmware; **it’s the firmware that cannot boot from this device**. The official note states explicitly:

> There must be a FAT32 or other EFI compatible partition and filesystem. There must be an EFI executable named correctly on this partition, (usually `/efi/boot/bootx64.efi`). **It is your system Firmware that fails to run the boot process of the device, not iPXE.**

The root cause became instantly clear: after iPXE presents the SAN disk to the firmware in UEFI mode, the firmware follows the **removable‑media boot path** and only recognises `\EFI\BOOT\BOOTX64.EFI` inside the ESP partition. But:

- **The Debian installer does not create this file** — it only writes `\EFI\debian\grubx64.efi` plus an NVRAM boot entry (a VM boots normally via the NVRAM path, which is why the golden image works fine inside a VM).
- **The Windows installer always writes it** — a copy of `bootmgfw.efi` naturally exists as `\EFI\BOOT\BOOTX64.EFI`.

This explains why Windows can boot immediately after cloning, while Debian fails on the very first boot. The fix is a single command, collapsed into the golden image’s ESP:

```bash
mount /dev/loop0p1 /mnt/esp
mkdir -p /mnt/esp/EFI/BOOT
cp /mnt/esp/EFI/debian/grubx64.efi /mnt/esp/EFI/BOOT/BOOTX64.EFI
umount /mnt/esp
```

The copy does not affect grub behavior: the configuration path (prefix) of `grubx64.efi` is embedded in the binary and still points to `/boot/grub/grub.cfg` on the root partition — **that’s where the `iscsi_auto` parameter written in Section 4.4 lives**. The firmware loads `BOOTX64.EFI` → grub → reads grub.cfg → enters the initramfs with `iscsi_auto`, thus connecting the six‑link chain.

## 4.7 Verification Results and Broader Applicability

### Verification Conclusions

A Debian 12 golden image, after cloning, was booted disklessly by iPXE: **the system entered normally, and the desktop environment started correctly**. The entire chain uses zero custom scripts and requires zero per-worker customization.

### Why It Is Universal Across the Debian Family

The three components this approach relies on are all **standard parts** of the Debian family:

| Dependency | Basis for Universality |
|---|---|
| initramfs `local-top/iscsi` and `iscsi_auto` | open-iscsi packaging scripts; Ubuntu / Mint / Deepin and other deb-based distros share the same origin |
| Kernel `iscsi_ibft` / `ISCSI_IBFT_FIND=y` | Ubuntu and other kernels inherit Debian’s configuration; the module and path are identical |
| Firmware contract `\EFI\BOOT\BOOTX64.EFI` | UEFI specification layer, independent of distribution (the pitfall is the same — the Ubuntu installer also doesn’t write this file) |

The same recipe can cover the entire Debian family. Points to note: Ubuntu’s grub resides under `\EFI\ubuntu\` (the source path for copying differs); if Secure Boot is enabled, copy `shimx64.efi` instead of `grubx64.efi` as BOOTX64.EFI. Distributions outside the deb family (RHEL family, Arch) use dracut rather than initramfs-tools — the mechanism differs and requires separate adaptation.

### Comparison with the Chapter 3 Paths

| Dimension | Chapter 3 (three paths) | Chapter 4 (iBFT) |
|---|---|---|
| Initial effort | Inject parameters + rebuild initrd per machine | Golden image, once |
| After cloning | Still requires per-worker customization | Zero handling |
| Surface area for mystery | Scattered across scripts on each machine | Collapsed into firmware + golden image |
| Bulk rollout | Repeat work on every machine | Instant clone via WebUI |
| Dependencies | Custom config + hook injection | Official mechanism (iscsi_auto) |

## Conclusion: One Parameter + One File

Looking back at the whole exploration: the kernel had supported it all along (`CONFIG_ISCSI_IBFT_FIND=y`), the initramfs had already reserved the switch (`iscsi_auto`), and the firmware contract was missing just one file (`BOOTX64.EFI`). No custom scripts, no per-worker work — **the most elegant implementation is often just walking the last step along an existing mechanism**.

From this day forward, Windows and the Debian family stand at the same starting line in the diskless world: install once, convert to an image, clone, power on. The complexity has been placed exactly where it belongs — in the golden image.