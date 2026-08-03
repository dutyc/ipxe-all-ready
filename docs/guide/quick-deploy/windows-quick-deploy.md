# Windows Diskless Quick Deployment (Golden-Image Clone)

> **This document covers: golden-image topic · quick start.**
> Complete workflow from golden image to a diskless Windows Worker: prepare the golden image → upload → instant clone via WebUI → boot directly to desktop.
> For environment deployment (Controller + storage node), see *Environment Deployment*. This document starts from golden-image preparation.
> Unlike Chapter 2 (installation from scratch), this guide does not customize PE or explain installation principles — it provides only reproducible steps and commands.

## Why Windows Can Be “Cloned and Booted”

Windows diskless boot relies on the iBFT (iSCSI Boot Firmware Table) written by iPXE: all boot parameters are injected by the firmware at boot time.  
**No machine‑specific identity is written inside the disk** (disk identifiers, boot entries, and network configuration are all decoupled from the specific machine).  
Therefore, as long as a golden image boots normally inside a virtual machine, every disk cloned from it is 100% bootable.

Full validation has been completed on the following versions, **with zero issues**:

| Windows Version | Validation Status |
|---|---|
| Windows 11 23H2 | Verified |
| Windows 11 24H2 | Verified |
| Windows 11 25H2 | Verified |

Different versions are distinguished simply by **choosing a different golden image** — no code or configuration changes are required.

### Differences from Chapter 2 (Installation from Scratch)

Both paths produce a diskless‑bootable Windows, but the **location** where the installation takes place differs, leading to completely different levels of complexity:

| Item | Chapter 2: From‑scratch install (iPXE direct install) | This document: Golden‑image clone |
|---|---|---|
| Where the OS is installed | iPXE → WinPE → iSCSI disk | VM local disk (conventional install) |
| PE customization / dism++ driver injection | Required | Not required |
| ISO virtual optical drive (dual‑target) | Required (sanhook + `--device-type cd`) | Not required |
| Bulk rollout | Repeat install on each machine | Instant clone via WebUI |

In golden‑image clone mode, the installation happens entirely inside a virtual machine. The entire PE chain from Chapter 2 (including the ISO virtual optical drive) is **completely bypassed**.  
After cloning, the iBFT mechanism guarantees bootability — no in‑disk processing is needed.

## Environment Preparation

Deployment of the Controller (Control Plane) and the storage node (Agent + iSCSI backend) is covered in *Environment Deployment*. The process is platform‑agnostic and treats Windows and Debian identically.  
The only contract: `IPXE_IQN_BASE` must match the `base-iqn` in `tftp/boot.ipxe.cfg`.

---

## Step 1: Prepare the Golden Image

### 1.1 Install Windows in a Virtual Machine

**Install Windows 11 (23H2 / 24H2 / 25H2 — any is fine) in a VM using a conventional method**. Any approach works — official ISO installation, deploying a sysprepped image, or migrating an existing system. After installation:

* Install VMware Tools (or the driver package for your virtualization platform) to ensure the **network driver** is in place.
* It is recommended to keep the VM disk size close to the target disk capacity (e.g., 40 GB / 60 GB).
* After installation, **shut down** the VM (do not boot the system for any initialization).

### 1.2 Convert VMDK to Raw Image

Locate the VM’s disk file (`.vmdk`) and convert it:

**On Windows (PowerShell):**

```powershell
qemu-img convert -p -f vmdk -O raw `
    "Windows 11 x64.vmdk" "_tpl_windows_23h2.img"
```

**On Linux:**

```bash
qemu-img convert -p -f vmdk -O raw "Windows 11 x64.vmdk" "_tpl_windows_23h2.img"
```

**Golden‑image naming convention** (must be followed; the WebUI uses this name to select the golden image during cloning):

| Version | Golden‑image filename |
|---|---|
| Windows 11 23H2 | `_tpl_windows_23h2.img` |
| Windows 11 24H2 | `_tpl_windows_24h2.img` |
| Windows 11 25H2 | `_tpl_windows_25h2.img` |

> Naming rule: `_tpl_<os>_<version>.img`. The `_tpl` prefix marks the file as a golden‑image template.  
> Cloned Worker disks are the production disks (`worker-xx.windows.img`, generated automatically by the system).

### 1.3 Install Windows on Real Hardware (Alternative Path)

When the target hardware includes **proprietary drivers that a VM cannot cover** (special NIC / RAID / HBA controller), you can install Windows once directly on the real hardware and use the result as the golden image — drivers will match the real hardware, eliminating any driver issues after cloning:

1. On a machine **identical to the target Worker model**, install Windows 11 (23H2 / 24H2 / 25H2 — any is fine) using a conventional method. Install all drivers, then shut down.
2. Convert the local disk to a raw image using one of the following three methods:

**Method A: Online conversion inside Windows (recommended, no disk removal)**

Use Sysinternals [disk2vhd](https://learn.microsoft.com/en-us/sysinternals/downloads/disk2vhd) to convert the system disk to a VHD, then convert that to raw:

```powershell
# Convert disk C: to VHD
.\disk2vhd.exe c: C:\tpl_windows_23h2.vhd

# VHD → raw
qemu-img convert -p -f vpc -O raw "C:\tpl_windows_23h2.vhd" "_tpl_windows_23h2.img"
```

**Method B: Remove the disk and use dd (attach the Windows system disk to a Linux machine)**

```bash
# After identifying the correct device, clone the entire disk (conv=sparse skips holes to save space)
dd if=/dev/sdb of=_tpl_windows_23h2.img bs=4M conv=sparse status=progress
```

**Method C: Boot via WinPE / Ubuntu Live and use dd**, command as above.

3. After conversion, the naming convention, upload, and clone process are **exactly the same** as for a VM golden image (see the naming table in 1.2 and Step 2).

> Note: For a real‑hardware golden image, the drivers are bound to the **hardware model of the preparation machine**; the clone target must have the same model / platform as the preparation machine.  
> All other contracts (`_tpl_` naming, upload, WebUI cloning, iBFT boot) are identical to those for a VM golden image.

## Step 2: Upload the Golden Image

Upload the golden image to the Controller’s image directory:

```bash
scp .\_tpl_windows_23h2.img user@192.168.80.3:/pool1/iscsi_img
```

**No additional actions are required** after the upload:

* The golden image will not be automatically mounted as an iSCSI Target (the LIO backend restores its saved configuration and does not scan the directory).
* The golden image can be updated at any time: simply re‑upload the same filename — this **does not affect** Worker disks that have already been cloned (cloning makes a copy, not a reference).

## Step 3: Power On the Worker — Automatic Registration

Set the diskless Worker to network boot (PXE) and power it on:

1. Obtain an address via DHCP → load iPXE → fetch boot variables.
2. **New MAC auto‑registration**: The Control Plane automatically assigns a hostname (`worker-01`, `worker-02`, …), writes it into the ledger, and automatically binds a static DHCP address — zero manual intervention required.
3. Open the WebUI (`http://x.x.x.x:4838`) → **Workers** page, where you will see the newly registered Worker.

## Step 4: Instant Clone via WebUI

On the Workers page, click a Worker to enter its detail page and create a system disk:

| Form Field | Value |
|---|---|
| Operating System (OS) | `Windows` |
| Disk Type | `Master` (golden‑image clone) |
| Master Name | `_tpl_windows_23h2.img` (the golden‑image name from Step 1) |

Click create — the process **completes in seconds**. The clone uses filesystem reflink (copy‑on‑write) to instantly produce a full system disk.  
At the same time, the iSCSI Target is automatically created with the IQN named (`iqn.2026-07.com.controller:worker-01.windows`). No command‑line interaction is required throughout the entire process.

## Step 5: Set Default Boot (Optional)

If not set, each time the Worker boots it will display the iPXE menu, where you must manually select **Boot Windows from iSCSI**.

To boot directly to the desktop, configure the **Default Boot** section on the Worker detail page:

| Form Field | Value |
|---|---|
| Default OS | `Windows` |
| Menu Default | `windows` |

After saving, the boot variables for this Worker are delivered immediately (`/boot-vars`). On the next boot the system will go straight into Windows.

## Step 6: Verification

1. Restart the Worker and observe the boot chain: iPXE → iSCSI login → Windows boot logo.
2. Reaching the desktop means verification is successful; repeat Steps 3–5 to roll out any number of Workers in bulk.
3. On the WebUI’s Workers page, confirm the disk status (IQN / filename / source `master: _tpl_windows_23h2.img`).

## Bulk Cloning and Version Management

* **Bulk rollout**: Power on multiple machines simultaneously, let them auto‑register → clone one by one in the WebUI → set default boot.
* **Version switching**: Simply choose a different golden image when cloning (`_tpl_windows_23h2.img` / `24h2` / `25h2`) — they do not interfere with each other.
* **Multiple systems on one machine**: On the Worker detail page, you can create multiple system disks for the same Worker and switch the default boot system at any time.

## FAQ

| Problem | Solution |
|---|---|
| After booting, the cloned disk stops at the iPXE menu | The default boot is not set; manually select **Boot Windows from iSCSI**, or set it up according to Step 5 |
| The cloned disk fails to boot (spinning circle / blue screen) | Issue with the golden image itself: check that the network driver is in place in the golden image, and that the golden image boots correctly inside a VM |
| Multiple clones share the same computer name | This is expected (no machine identity is written inside the disk). If you need to differentiate them, handle it manually (rename / sysprep) — it does not affect bootability |
| iSCSI target not found | ① Verify that `IPXE_IQN_BASE` in `iscsi-server/.env` matches `base-iqn` in `tftp/boot.ipxe.cfg`; ② Confirm the Worker is registered in the WebUI (the hostname binding is in effect); ③ On the detail page, the IQN in the disk list should be `…:worker-xx.windows` |
| WebUI operation returns 401 | The Control Plane has `IPXE_CP_TOKEN` set but `webui/app/.env` is not synchronized (see *Environment Deployment* 1.4), or the WebUI was not rebuilt after the change |
| Want to switch the golden‑image version | Upload a new golden image → choose the new golden image when cloning the target Worker. Existing Worker disks are not affected |