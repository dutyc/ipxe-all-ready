# Ch4: Debian-family iBFT Boot — The Elegant Answer to Master-Image Cloning

> **Status: English translation in progress — this page is a structural placeholder.**
> The complete Chinese version is authoritative for now: [第四章:Debian 系 iBFT 无盘启动](https://ipxe.lecreate.asia/zh/guide/exploration/debian-12-ibft)

How a single kernel parameter (`iscsi_auto`) plus a single file (`BOOTX64.EFI`) turns any Debian-family master image into a clone-and-boot diskless OS — verified end-to-end on Debian 12 (desktop boots normally).

## Structure

- **4.1 Identity addressing** — where the boot identity (initiator / target / LUN) lives and who injects it
- **4.2 The six-link iBFT chain** — sanboot writes the table → kernel discovers it → `iscsi_ibft` exports sysfs → initramfs `ISCSI_AUTO` → `iscsistart -b` logs in → `root=UUID` mounts
- **4.3 Kernel config & open-iscsi source evidence** — why the initramfs hook only ships `iscsistart`, `initiatorname.iscsi` and `iscsi.initramfs`
- **4.4 The four-step master-image recipe** — open-iscsi, module injection, GRUB parameters, initrd rebuild + the three-artifact initrd check
- **4.5 The `0x7f22208e` pitfall** — the removable-media firmware contract: ESP must contain `BOOTX64.EFI`
- **4.6 Debian-family generality** — why the mechanism holds across Debian and Ubuntu

---
*This page will be translated in full. Until then, the Chinese version linked above is authoritative.*
