# Debian-family Diskless Quick Deployment (Golden-Image Clone)

> **This document covers: golden-image topic · quick start.**
> Complete workflow from golden image to a diskless Debian-family Worker: prepare the golden image (including iBFT adaptation) → upload → instant clone via WebUI → boot directly to the system.
> For environment deployment (Controller + storage node), see *Environment Deployment*. This document starts from golden-image preparation.

## Why Debian-family Can Be “Cloned and Booted”

The same path as Windows: boot parameters are provided at boot time by the **iBFT (iSCSI Boot Firmware Table)** written by iPXE’s `sanboot`.  
The initramfs uses the kernel parameter `iscsi_auto` to automatically read the firmware table and log in to iSCSI — **no machine‑specific identity is written inside the disk**.

However, there is one **substantial difference** between a Debian-family golden image and a Windows golden image: the Windows installer places boot files into the removable‑media path required by the firmware, whereas the Debian-family installer does not.  
Therefore the golden image needs a one‑time adaptation (**four‑step recipe**); after the adaptation, cloned disks are ready to use with zero per‑worker customization.

Verified by actual testing: **Debian 12 boots disklessly after cloning a golden image; the system and desktop environment function normally**.  
Ubuntu and other Debian-family distributions follow the same chain; the preparation and cloning workflow is identical.

## Scope of Support

Mechanism prerequisites (all are standard components of Debian-family distributions): initramfs-tools + open-iscsi (comes with initramfs integration, supports the `iscsi_auto` parameter) + kernel `iscsi_ibft` module (standard since kernel ≥ 3.10, `CONFIG_ISCSI_IBFT=m` and `CONFIG_ISCSI_IBFT_FIND=y` forced on).

| Distribution | Supported Versions | Status |
|---|---|---|
| Debian | 11 / 12 / 13 | Mechanically supported; 12 tested |
| Ubuntu | 22.04 / 24.04 / 26.04 (LTS) and newer non‑LTS releases | Mechanically supported (same chain) |

> Debian 10, Ubuntu 20.04, and earlier releases are not recommended (EOL; the mechanisms are satisfied but they are outside the security support window).  
> Ubuntu’s iBFT kernel modules (`iscsi_ibft` / `iscsi_tcp` / `ib_iser`) are located in the base kernel package and are present even in a minimal installation — no additional installation is needed.  
> Ubuntu is not split into Desktop vs Server editions: any desktop environment (GNOME / KDE / XFCE, etc.) works and does not affect diskless booting. The same applies to Debian — a normally installed system is always supported, with no need to worry about the desktop environment.

## Environment Preparation

Deployment of the Controller (Control Plane) and the storage node (Agent + iSCSI backend) is covered in *Environment Deployment*. The process is platform‑agnostic and treats Windows and Debian identically.  
The only contract: each storage node's `IPXE_IQN_BASE` is authoritative for the disks it hosts — disk IQNs are built from it at creation time, and at Worker boot iPXE fetches the actual `base-iqn` from `/boot-vars` (resolved to the node hosting the Worker's system disk), overriding the static fallback (placeholder) in `tftp/boot.ipxe.cfg`. The two do not need to match.

---

## Step 1: Prepare the Golden Image

### 1.1 Install a Debian-family Distribution in a Virtual Machine (Primary Path)

**Install Debian 12 (or Ubuntu 22.04 / 24.04 / 26.04, etc.) in a VM using a conventional method** (see “Scope of Support”). Critical prerequisites:

* **A UEFI + GPT installation is mandatory** (a BIOS installation lacks an ESP partition and cannot satisfy the BOOTX64.EFI firmware contract).
* Partition suggestion: 512 MB ESP + root partition + swap (standard automatic partitioning is sufficient).
* Choose desktop or server installation as desired (any desktop environment works and does not affect diskless booting); after installation, **shut down** the VM and prepare for in‑disk adaptation.

### 1.2 Install on Real Hardware (Alternative Path)

When the target hardware includes proprietary drivers that a VM cannot cover (special NIC / RAID / HBA), you can perform a conventional installation of Debian 12 (or the corresponding Debian-family distribution) on a **machine of the same model** — the drivers will match the real hardware.  
In this path, Step 1.3 is executed directly inside the running system without chroot.  
The clone target must have the same model / platform as the preparation machine.

### 1.3 Four‑Step Recipe: In‑Disk Adaptation (Core)

Mount the VM disk on any Linux machine (`losetup -Pf` + chroot), or execute directly inside the real‑hardware system:

```bash
# ① Install open-iscsi (provides iscsistart and initramfs integration scripts)
apt update && apt install -y open-iscsi

# ② Inject required initramfs modules
cat >> /etc/initramfs-tools/modules <<'EOF'
iscsi_tcp
ib_iser
iscsi_ibft
EOF

# ③ Append boot parameters (iscsi_auto is the switch for iBFT automatic login)
sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT="\([^"]*\)"/GRUB_CMDLINE_LINUX_DEFAULT="\1 ip=dhcp ipv6.disable=1 iscsi_auto"/' /etc/default/grub

# ④ Rebuild initrd (note: in a chroot, `uname -r` returns the host kernel; always use -k all)
update-grub
update-initramfs -u -k all
```

Mount workflow for chroot adaptation:

```bash
losetup -Pf _tpl_debian_12.img
mount /dev/loop0p2 /mnt/img          # p2 is the root partition (adjust to your actual partition)
mount --bind /dev /mnt/img/dev
mount --bind /proc /mnt/img/proc
mount --bind /sys /mnt/img/sys
chroot /mnt/img /bin/bash            # Execute the four steps above inside chroot
# After finishing, exit and unmount: exit → umount /mnt/img/{dev,proc,sys} → umount /mnt/img → losetup -d /dev/loop0
```

### 1.4 Add BOOTX64.EFI (Firmware Removable‑Media Contract)

Under UEFI boot, the firmware only recognizes `\EFI\BOOT\BOOTX64.EFI` inside the ESP partition. The Debian installer does not create it — **without it, the cloned disk reports error `0x7f22208e`**:

```bash
mount /dev/loop0p1 /mnt/esp          # p1 is the ESP partition
mkdir -p /mnt/esp/EFI/BOOT
cp /mnt/esp/EFI/debian/grubx64.efi /mnt/esp/EFI/BOOT/BOOTX64.EFI
umount /mnt/esp
```

> If Secure Boot is enabled, copy `shimx64.efi` instead of `grubx64.efi` as BOOTX64.EFI (VMware disables it by default, so grubx64.efi is sufficient).  
> For Ubuntu, the source file is under `\EFI\ubuntu\` (Debian under `\EFI\debian\`); adjust the source path according to the actual distribution.

### 1.5 Verify the Initrd Trio

```bash
lsinitramfs /boot/initrd.img-$(ls /boot | grep -oP 'vmlinuz-\K.*' | head -1) | \
    grep -E "iscsistart|local-top/iscsi|iscsi_(tcp|ibft)"
```

Expected to see all three: `/sbin/iscsistart`, `scripts/local-top/iscsi`, `lib/modules/.../iscsi_ibft.ko`.  
All three must be present before proceeding; if any is missing, go back to 1.3 and recheck.

### 1.6 Conversion and Naming

**VM path** (vmdk to raw):

```bash
qemu-img convert -p -f vmdk -O raw "Debian 12 x64.vmdk" "_tpl_debian_12.img"
```

**Real‑hardware path** (dd entire disk):

```bash
dd if=/dev/sdb of=_tpl_debian_12.img bs=4M conv=sparse status=progress
```

| Version | Golden‑image filename |
|---|---|
| Debian 12 | `_tpl_debian_12.img` |
| Ubuntu 24.04 (example) | `_tpl_ubuntu_24.04.img` |

> The naming rule is the same as for Windows: `_tpl_<os>_<version>.img`. The `_tpl` prefix marks the golden‑image template; cloned Worker disks are production disks (`worker-xx.debian.img`, generated automatically).  
> When cloning an Ubuntu golden image, choose `Ubuntu` for the OS field (IQN suffix `.ubuntu`); the rest of the process is identical to Debian.

## Step 2: Upload the Golden Image

```bash
scp _tpl_debian_12.img user@192.168.80.3:/pool1/iscsi_img
```

**No additional actions are required** after the upload: the golden image is not automatically mounted as a Target; to update the golden image, simply re‑upload the same filename — this does not affect Worker disks that have already been cloned.

## Step 3: Power On the Worker — Automatic Registration

Set the diskless Worker to network boot and power it on:

1. Obtain an address via DHCP → load iPXE → fetch boot variables.
2. **New MAC auto‑registration**: A hostname is automatically assigned (`worker-01`, `worker-02`, …), a static DHCP address is bound — zero manual intervention.
3. WebUI (`http://192.168.80.3:4838`) → **Workers** page to view the new Worker.

## Step 4: Instant Clone via WebUI

On the Workers page, enter the Worker detail page and create a system disk:

| Form Field | Value |
|---|---|
| Operating System (OS) | `Debian` |
| Disk Type | `Master` (golden‑image clone) |
| Master Name | Select `_tpl_debian_12.img` from the dropdown (the golden‑image name from Step 1) |

Completes in seconds (reflink clone). The iSCSI Target and IQN (`iqn.2026-07.com.controller:worker-01.debian`) are created automatically.

## Step 5: Set Default Boot

After setting the default OS, the Worker boots straight into the system on power‑on, with no need to select it manually at the iPXE menu. Configure it in the **Default Boot** section of the Worker detail page:

| Form Field | Value |
|---|---|
| Default OS | Select `Debian` from the dropdown (options come from the system disks already mounted on this Worker — the disk cloned in Step 4) |

> Only the **Default OS** field is required. Leave **Menu Default** at its default (reboot) — do not change it. The derivation chain is `default_os > boot.menu_default > reboot`: once `default_os` is set it takes priority, and an unset menu item keeps the reboot fallback.

## Step 6: Verification

1. Restart the Worker and observe the boot chain: BOOTX64.EFI → grub → iSCSI login → system.
2. After entering the system, verify the iBFT evidence:

```bash
ls /sys/firmware/ibft/     # Firmware table export (NIC directory + initiator/target)
iscsiadm -m session        # Current iSCSI session
```

3. On the WebUI Workers page, confirm the disk status (IQN / filename / source `master: _tpl_debian_12.img`).

## Bulk Cloning and Version Management

* **Bulk rollout**: Power on multiple machines simultaneously → auto‑register → clone one by one in the WebUI → set default boot.
* **Version switching**: Simply choose a different golden image when cloning (`_tpl_debian_12.img` / other versions) — they do not interfere with each other.
* **Multiple systems on one machine**: A single Worker can have multiple system disks (Windows + Debian) and switch the default boot system at any time.

## FAQ

| Problem | Solution |
|---|---|
| Cloned disk reports `Boot from SAN device failed: Error 0x7f22208e` | BOOTX64.EFI is missing from the ESP. Add the file as described in 1.4 and **re‑clone** (old cloned disks lack it). Confirm the golden image was installed as UEFI + GPT. |
| Boot stops at the iPXE menu | The default boot is not set. Manually select **Boot Debian from iSCSI**, or set it up according to Step 5. |
| iSCSI target not found | ① Verify the `IPXE_IQN_BASE` in `iscsi-server/.env` on the storage node hosting the Worker's system disk (authoritative: disk IQNs are built from it; `/boot-vars` returns it for the hosting node); ② Confirm the Worker is registered in the WebUI; ③ On the detail page, the IQN should be `…:worker-xx.debian` |
| `VFS: Unable to mount root fs` | The initrd trio is incomplete (1.5 verification failed): missing module/iscsistart. Redo 1.3 and run `update-initramfs -u -k all`. |
| Worried that the cloned disk has `root=UUID` hardcoded | This is expected: the UUID is a filesystem property that is copied as a whole during cloning; each cloned disk matches its own disk, no action needed. |
| Golden image boots fine in a VM but the cloned disk won’t boot | Check whether BOOTX64.EFI was added as described in 1.4 (the most common hidden cause). |