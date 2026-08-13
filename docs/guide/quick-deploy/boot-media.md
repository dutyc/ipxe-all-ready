# Boot Media Creation Guide

## Why Do You Need Local Boot Media?

In the standard network boot model, the NIC's PXE ROM fetches the boot program directly once the machine powers on. However, in real-world data center environments—consumer motherboards, commercial office PCs, and some white-box servers—pure PXE network boot typically faces significant deployment obstacles:

1. **Lack of firmware capability and hidden entry points**: Many consumer motherboards (e.g., Gigabyte, ASUS) do not provide a dedicated PXE/Network Boot entry, or bury it deep within multiple menu layers. By default, the UEFI Network Stack is often disabled.
2. **High manual intervention cost**: With pure PXE, operators must power on each machine, enter the BIOS, enable Network Boot, save, and reboot. In a data center with hundreds of machines, such per-machine manual interaction is unacceptable.
3. **Secure Boot restrictions**: Modern motherboards enable Secure Boot by default. When the firmware network stack (SNP/PXE) attempts to load an unsigned custom iPXE binary, it will throw a `Security Violation` and refuse to boot.

**The essence of local boot media—USB drives, local ESPs, GRUB chainloading—is to bypass the black-box constraints and tedious configuration of motherboard firmware at the network boot level, and hand boot control directly to stateless firmware.**

As long as the motherboard supports USB booting, or a trusted GRUB/ESP boot environment already exists on a local disk, you can skip the firmware network stack and load `ipxe-stateless` locally. It then takes over all subsequent network interaction.

---

This repository provides the following build artifacts, with the directory structure as shown:

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

All artifacts are produced by a single automated build pipeline. They differ only in carrier form; the firmware logic and driver set are exactly the same. Verify file integrity before use:

```bash
sha256sum -c SHA256SUMS
```

## UEFI Direct Boot (direct-uefi)

`ipxe.efi` is a standard UEFI application that can be loaded directly by any x86_64 UEFI firmware. `ipxe-debug.efi` is a debug build with verbose logging enabled; both are functionally identical, differing only in the level of log detail.

### 1.1 Creating a UEFI Bootable USB Drive (Manual)
Suitable for pure UEFI environments, as a portable boot tool:

```bash
# Assume the USB device is /dev/sdb; ensure no important data is on it
mkfs.vfat -F 32 /dev/sdb1

mount /dev/sdb1 /mnt
mkdir -p /mnt/EFI/BOOT
cp direct-uefi/ipxe.efi /mnt/EFI/BOOT/BOOTX64.EFI
sync && umount /mnt
```

`EFI/BOOT/BOOTX64.EFI` is the default fallback path for removable devices specified by the UEFI specification. Once inserted, it will appear in the motherboard boot menu (F11/F12) without requiring any firmware network stack configuration.

### 1.2 Writing to a Local ESP and Adding a Boot Entry
If the machine already has a local system or ESP partition, and you wish to keep the firmware on the local disk permanently to avoid relying on a USB drive:

```bash
mkdir -p /boot/efi/EFI/stateless
cp direct-uefi/ipxe.efi /boot/efi/EFI/stateless/

efibootmgr --create \
  --disk /dev/sda --part 1 \
  --label "iPXE Stateless" \
  --loader '\EFI\stateless\ipxe.efi'
```

### 1.3 Notes
- This artifact is an unsigned binary. On machines with Secure Boot enabled, you must disable Secure Boot, or enroll its hash via MokManager.
- Use `ipxe-debug.efi` for troubleshooting and log capture; use `ipxe.efi` in production.

## GRUB Boot (grub-bios)

`ipxe.lkrn` is iPXE packaged with a Linux kernel boot header (bzImage format). Any bootloader capable of loading a Linux kernel can load it.

This makes it particularly valuable on Legacy BIOS machines that already have GRUB or SYSLINUX deployed: **without modifying the existing boot chain, and without enabling PXE in the firmware, you can seamlessly hand control over to the network by simply appending an entry to the existing GRUB menu.**

### 2.1 GRUB2 (Legacy BIOS)

Append the following to `/etc/grub.d/40_custom`:

```bash
menuentry 'iPXE Stateless Boot' {
    insmod linux
    linux16 /boot/ipxe.lkrn
}
```

```bash
update-grub                                # Debian/Ubuntu
# or grub2-mkconfig -o /boot/grub2/grub.cfg  # RHEL/CentOS
```

### 2.2 GRUB Legacy (menu.lst)

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

### 2.4 GRUB Under UEFI: Use chainloader Instead

`linux16` is only for BIOS environments. Do not use `.lkrn` under UEFI GRUB; instead, directly chainload the EFI artifact:

```bash
menuentry 'iPXE Stateless Boot (UEFI)' {
    search --no-floppy --set=root --file /EFI/stateless/ipxe.efi
    chainloader /EFI/stateless/ipxe.efi
}
```

### 2.5 How It Works

Once `.lkrn` is loaded, iPXE immediately takes over the NIC and drives it using its own native PCI driver, without depending on any Linux runtime. The "Linux kernel header" is merely a wrapper to make GRUB accept the binary.

## USB Boot Medium (usb)

`ipxe.usb` is a full-disk raw image; simply write it and it's ready to use. It is suitable for environments without network boot or where the firmware completely disables the network stack.

### 3.1 Writing on Linux

```bash
lsblk    # First confirm the USB device name, e.g., /dev/sdb
dd if=usb/ipxe.usb of=/dev/sdb bs=4M status=progress conv=fsync
```

> **Note**: `of=` must point to the whole-disk device (e.g., `/dev/sdb`), not a partition (e.g., `/dev/sdb1`). Targeting the wrong device will destroy all data on that disk.

### 3.2 Writing on Windows

- **Rufus**: Select `ipxe.usb`, then choose **"Write in DD Image mode"** when prompted.
- Or use balenaEtcher, select the image, and write directly.

### 3.3 Booting

After writing, insert the medium into the target machine and select USB boot from the boot menu (F11/F12). This image contains a BIOS boot sector; if the target machine only supports UEFI and the firmware does not offer Legacy/CSM compatibility options, use the manual UEFI USB method described in Section 1.1 instead.

## Selection Guide

| Scenario | Recommended Artifact |
|---|---|
| Modern UEFI machines, network boot or local ESP | `direct-uefi/ipxe.efi` |
| Troubleshooting, serial/console log capture | `direct-uefi/ipxe-debug.efi` |
| Legacy BIOS with existing local GRUB/SYSLINUX | `grub-bios/ipxe.lkrn` |
| No network boot environment, portable medium needed | `usb/ipxe.usb` |
| Pure UEFI portable medium | Section 1.1 manual USB drive |

## Conclusion: The Medium Is Just a Carrier

All of the above media store no state and carry no identity; their sole responsibility is to **bring up the NIC and hand the machine over to the network.**

Upon power-on, the firmware requests an identity (iSCSI target, IQN, boot variables) from the control plane; the system disk and identity both come from the network. Whether the carrier is UEFI, GRUB, or USB, the semantics are exactly the same.