# Windows Master-Image Quick Deploy (Clone)

> **Status: English translation in progress — this page is a structural placeholder.**
> The complete Chinese version is authoritative for now: [Windows 无盘快速部署(母盘克隆)](https://ipxe.lecreate.asia/zh/guide/quick-deploy/windows-quick-deploy)

From master image to a Windows diskless worker: prepare the image (VM or real hardware), upload, clone in the Web UI in seconds, boot straight to the desktop. Verified on Windows 11 23H2 / 24H2 / 25H2.

## Structure

- **Why Windows is clone-and-boot** — iBFT injected by iPXE at boot time; nothing machine-specific is baked into the disk
- **Step 1: Prepare the master image** — install in a VM → `qemu-img` convert; or real-hardware paths (disk2vhd / dd)
- **Step 2: Upload** — `scp` to `/pool1/iscsi_img`; re-uploading the same name updates the template
- **Step 3: Power on & auto-register** — zero-touch registration (`worker-01`…)
- **Step 4: WebUI instant clone** — OS=`Windows`, Type=`Master`, Master Name=`_tpl_windows_23h2.img`
- **Step 5: Default boot (optional)** — menu item `windows` for boot-to-desktop
- **Step 6: Verify** — boot chain + WebUI disk state

---
*This page will be translated in full. Until then, the Chinese version linked above is authoritative.*
