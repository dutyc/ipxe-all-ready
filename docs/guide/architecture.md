# Chapter 1: iPXE Diskless Architecture Design and Core Boot Chain

## 1.1 Why Not Use Existing Solutions?

Off-the-shelf diskless solutions usually fall into one of two paths:

1. **Traditional PXE + NFS**: TFTP is slow at transferring kernels and prone to packet loss; NFS-mounted root filesystems frequently suffer from file-locking issues and permission problems under concurrency and high load.
2. **Commercial diskless software**: Highly black-box, tied to specific hardware or OS versions. Operators can only click “Next” and have no way to troubleshoot when things go wrong.

`ipxe-all-ready` takes a third path: **a fully open-source, modern diskless architecture based on iSCSI block storage**.
We have abandoned all black-box tools — iPXE for booting, HTTP for large file transfers, and iSCSI as the underlying storage layer. More importantly, by going one level deeper with foundational tools (such as `debootstrap` and `dism++`), we bypass the flaws of official OS installers and truly achieve cross-platform “instant-on” capability for Debian, Ubuntu, and Windows 11.

## 1.2.1 Infrastructure Component Breakdown

In our architecture there is no complex control plane — only three components with clearly defined responsibilities:

*   **Controller**: Provides DHCP and TFTP/HTTP services. It assigns IP addresses to Workers, delivers the iPXE firmware and boot scripts, and serves kernel or PE images for download.
*   **iSCSI Server**: Provides block-level storage. Besides offering regular read/write LUNs (as system disks), in Windows deployment scenarios it can also map an ISO image directly as a read-only virtual optical drive LUN using `tgt`’s `--device-type cd` parameter.
*   **Worker**: A bare-metal server or virtual machine with no local disk. After power-on it relies entirely on the network to obtain its identity and operating system.

## 1.2.2 Containerised Orchestration of the Control Plane (Docker Compose)

In practice, we have standardised the core services of the Controller node through Docker Compose. This not only gives the control plane “one-click launch, run anywhere” portability, but also converges complex underlying network and storage services into a clear, declarative codebase.

Our control-plane stack consists of three core containers:

1. **ipxe-dnsmasq**: Handles DHCP identity assignment and TFTP firmware/script distribution (the bootstrap layer).
2. **ipxe-nginx**: Serves as the high-speed HTTP backbone, providing fast downloads of kernels, initrds, or PE images.
3. **ipxe-iscsi**: Based on `stgt`, provides the iSCSI block storage foundation, exposing system disk LUNs and ISO virtual optical drives.

**Real-world architecture considerations:**

*   **Rejecting bridge networks, embracing host networking**: DHCP and TFTP rely heavily on LAN broadcasts and specific UDP ports, while iSCSI is extremely sensitive to network latency and throughput. Therefore, all core services are configured with `network_mode: host`. We refuse Docker’s default NAT bridge network, allowing containers to join the physical network directly, completely avoiding the performance penalty and broadcast black holes caused by port mapping.
*   **Device passthrough for the storage backend**: The iSCSI container (`stgt`) is granted `privileged: true` and directly mounts the host’s `/dev`, `/lib/modules`, and `/sys/kernel/config`. This allows the iSCSI Target inside the container to break through container isolation and directly operate underlying block devices (or image files) just like a native host process, as well as dynamically load necessary kernel modules.

With this orchestration, four independent services that would traditionally require tedious configuration and troubleshooting at the Linux system level are perfectly encapsulated into a highly cohesive, loosely coupled diskless control-plane foundation.

## 1.3 Division of Responsibilities in the Protocol Stack

After being battered by countless timeouts and disconnections, we have established the following clear protocol boundaries:

1.  **TFTP (bootstrap only)**: Used exclusively to transfer the few tens of KB of iPXE firmware (`undionly.kpxe` / `snponly.efi`) and a few KB of `.ipxe` scripts. Never use it for large file transfers — UDP packet loss will otherwise make you question your life choices. **Hard-won lesson from the trenches**: You must ensure that only one DHCP server on the LAN responds to PXE requests; otherwise, the main router’s DHCP may hand out incorrect Option 66, causing iPXE to contact the wrong TFTP server and time out directly.
2.  **HTTP (large file transfers)**: Once the iPXE script takes over, all Linux `vmlinuz`/`initrd` or Windows `boot.wim` files are downloaded via HTTP, leveraging TCP to guarantee transfer integrity and speed.
3.  **iSCSI (operating system runtime foundation)**: The root filesystem while the OS is running. iSCSI presents a block device, making the operating system believe it is a real local physical disk, completely avoiding the pitfalls of NFS as a network filesystem.

## 1.4 Boot State Machine: From Power-On to Desktop

A complete diskless boot consists of four phases. Linux and Windows follow completely different real-world logic in the latter two phases.

### Phase 1: Traditional PXE Bootstrap

The Worker powers on and sends a DHCP Discover. The Controller assigns an IP address and tells it the TFTP server IP and the path to the iPXE firmware via Option 66/67. The Worker downloads the firmware and executes it; the native PXE ROM’s job is done.

### Phase 2: iPXE Takeover and Script Loading

iPXE initialises the NIC and requests DHCP again. The Controller recognises the iPXE identifier and delivers the path to the `boot.ipxe` script. iPXE downloads the script, loads the menu, and prepares to boot the OS.

### Phase 3: OS Loading (the Linux/Windows fork)

*   **Linux (Debian/Ubuntu)**: We **do not rely** on the official installers’ network installation mode (real-world testing proved Ubuntu’s Subiquity simply does not support iSCSI disk selection). Instead, we use `debootstrap` to provision a clean system onto the iSCSI LUN in advance and modify the `initramfs-tools` hook script to forcibly package the iSCSI configuration. iPXE directly executes `sanboot`, handing control of the LUN to GRUB, and GRUB loads the kernel.
*   **Windows 11**: We use `dism++` to inject a universal NIC and storage driver bundle into `boot.wim` beforehand (sidestepping Microsoft ADK version pitfalls). iPXE issues two `sanhook` commands, simultaneously attaching the iSCSI system disk and the iSCSI virtual optical drive (ISO). It then loads `boot.wim` into the PE environment and runs `setup.exe` directly from the virtual drive for a native installation.

### Phase 4: Kernel Takeover and Root Filesystem Mount

*   **Linux**: The kernel boots; `initramfs` reads our forcibly injected `/etc/iscsi.initramfs`, loads the `iscsi_tcp` module, and reconnects to the iSCSI Target. It precisely mounts the root partition using the UUID from `/etc/fstab` (instead of the ephemeral `/dev/sdX`) and completes `switch_root`.
*   **Windows**: After installation finishes, the system reboots. Through the iBFT (iSCSI Boot Firmware Table) mechanism, the native iSCSI driver takes over the system disk very early in the boot process, booting directly to the desktop.

## 1.5 Core Automation: The Dynamic IQN Variable Chain

To achieve “adding a new machine only requires DHCP configuration, with no script modifications needed,” we have designed a variable-passing chain that spans DHCP, iPXE, and iSCSI. Below is the complete real-world walkthrough of this chain (using a node with MAC `52:54:00:12:34:56` and hostname `worker-01` booting Ubuntu as an example):

### 1. Identity Injection at the DHCP Layer

In the Controller’s `dnsmasq`, we bind the MAC address to a hostname and deliver it via DHCP Option 12.

```text
# dnsmasq.conf
dhcp-host=52:54:00:12:34:56,worker-01
```

**Actual effect**: When the Worker sends a DHCP request, the Controller injects the environment variable `${hostname}` with the value `worker-01`.

### 2. Capturing iPXE Base Variables and Assembling the Initiator IQN

After taking over the NIC, the iPXE firmware captures the variables delivered by DHCP and assembles the current node’s identity as an iSCSI initiator (Initiator IQN) in `boot.ipxe`.

```ipxe
# boot.ipxe
set base-iqn iqn.2026-07.com.controller
set iscsi-server 192.168.1.5

# Assemble the Initiator IQN
set initiator-iqn ${base-iqn}:${hostname}
```

**Resulting variable values**:

*   `${hostname}` = `worker-01`
*   `${initiator-iqn}` = `iqn.2026-07.com.controller:worker-01`

### 3. Deriving the Target IQN and Assembling the URI in menu.ipxe

When the user selects “Boot Ubuntu” from the menu, `menu.ipxe` further derives the target storage identity (Target IQN) from the base variables and assembles the iSCSI resource locator (URI).

```ipxe
# menu.ipxe (Ubuntu boot entry)
# Derive the Target IQN (append the OS suffix to the hostname)
set target-iqn ${base-iqn}:${hostname}.Ubuntu

# Assemble the iSCSI URI
# Format: iscsi:<server>:[<protocol>]:[<port>]:[<lun>]:<target-iqn>
set root-path iscsi:${iscsi-server}::::${target-iqn}
```

**Resulting variable values**:

*   `${target-iqn}` = `iqn.2026-07.com.controller:worker-01.Ubuntu`
*   `${root-path}` = `iscsi:192.168.1.5::::iqn.2026-07.com.controller:worker-01.Ubuntu`

### 4. Final Consumption Across Protocol Boundaries

iPXE executes the `sanboot` command, translating the in-memory assembled variables into low-level iSCSI login packets.

```ipxe
# Perform diskless boot
sanboot --keep --drive 0x80 ${root-path}
```

**Under the hood**: iPXE sends an iSCSI Login Request to `192.168.1.5`. The request explicitly declares: “My Initiator is `iqn.2026-07.com.controller:worker-01`, I want to connect to Target `iqn.2026-07.com.controller:worker-01.Ubuntu`.” After the iSCSI Server verifies the ACL, it maps the dedicated LUN to this node.

**Summary**: This chain completely eliminates hardcoding from the scripts. To add a new diskless workstation, you only need to bind the MAC and hostname in DHCP and create a LUN with the corresponding suffix on the iSCSI Server. The iPXE scripts never need to be modified.