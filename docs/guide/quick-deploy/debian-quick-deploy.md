# Debian-family Master-Image Quick Deploy (Clone)

> **Status: English translation in progress — this page is a structural placeholder.**
> The complete Chinese version is authoritative for now: [Debian 系无盘快速部署(母盘克隆)](https://ipxe.lecreate.asia/zh/guide/quick-deploy/debian-quick-deploy)

From master image to a Debian-family diskless worker: prepare the image (with the one-time four-step iBFT recipe), upload, clone in the Web UI, boot straight into the system. Verified on Debian 12; the same chain holds across Debian 11–13 and Ubuntu 22.04 / 24.04 / 26.04.

## Structure

- **Why Debian-family is clone-and-boot** — iBFT + `iscsi_auto`; the one real difference vs. Windows: the installer never creates `BOOTX64.EFI`
- **Supported versions** — mechanism prerequisites (initramfs-tools + open-iscsi + `iscsi_ibft`) across Debian / Ubuntu
- **Step 1: Prepare the master image** — install (UEFI+GPT) → four-step recipe → `BOOTX64.EFI` → three-artifact initrd check → convert & name (`_tpl_debian_12.img`)
- **Step 2: Upload** — `scp` to `/pool1/iscsi_img`
- **Step 3: Power on & auto-register** — zero-touch registration
- **Step 4: WebUI instant clone** — OS=`Debian`, Type=`Master`, IQN `worker-xx.debian`
- **Step 5: Default boot (optional)** — menu item `debian`
- **Step 6: Verify** — `ls /sys/firmware/ibft/`, `iscsiadm -m session`

---
*This page will be translated in full. Until then, the Chinese version linked above is authoritative.*
