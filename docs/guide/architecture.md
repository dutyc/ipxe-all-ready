# Chapter 1: iPXE Diskless Architecture Design and Core Boot Chain

## 1.1 Why Not Use Existing Solutions?

Diskless solutions on the market generally fall into two categories:

1. **Traditional PXE + NFS**: TFTP transfers the kernel slowly and is prone to packet loss; NFS-mounted root filesystems often suffer from file lockups and permission issues under concurrency and high load.
2. **Commercial diskless software**: Closed source, typically tied to specific hardware or OS versions. Operators lack control over the underlying boot chain, making troubleshooting difficult.

`ipxe-all-ready` adopts a third approach: **a fully open-source, iSCSI block‑storage‑based diskless architecture**.
This project uses iPXE for network booting, HTTP for large file transfers, and iSCSI for the underlying storage. At the same time, tools like `debootstrap` and `dism++` are used to bypass limitations of certain official OS installers, enabling cross‑platform deployment of Debian, Ubuntu, and Windows 11.

## 1.2 Infrastructure Component Breakdown

The architecture consists of three components with clearly defined responsibilities:

* **Controller**: Provides DHCP and TFTP/HTTP services. It assigns IP addresses to Workers, delivers iPXE firmware and boot scripts, and serves kernel or PE images for download.
* **iSCSI Server**: Provides block‑level storage. In addition to regular read/write LUNs (used as system disks), in Windows deployment scenarios it can map an ISO image as a read‑only virtual optical‑drive LUN using `tgt`’s `--device-type cd` parameter.
* **Worker**: A bare‑metal server or virtual machine with no local disk. After power‑on it depends entirely on the network to obtain its identity and operating system.

### Containerised Orchestration of the Control Plane (Docker Compose)

In practice, the core services of the Controller node are orchestrated with Docker Compose. This improves the portability of the control plane and expresses the underlying network and storage services as declarative code.

The control‑plane stack consists of three core containers:

1. **ipxe-dnsmasq**: Handles DHCP identity assignment and TFTP firmware/script distribution.
2. **ipxe-nginx**: Acts as the HTTP resource service, providing downloads of the kernel, initrd, or PE images.
3. **ipxe-iscsi**: Based on `stgt`, provides iSCSI block storage services, mapping system‑disk LUNs and ISO virtual optical drives.

**Architecture Considerations:**

* **Using host network mode**: DHCP and TFTP depend on LAN broadcasts and specific UDP ports; iSCSI is sensitive to network latency and throughput. Therefore, all core services are configured with `network_mode: host`. Avoid Docker’s default NAT bridge network to minimise the performance penalty and broadcast issues caused by port mapping.
* **Device passthrough for the storage backend**: The iSCSI container (`stgt`) is configured with `privileged: true` and mounts the host’s `/dev`, `/lib/modules`, and `/sys/kernel/config`. This allows the iSCSI Target inside the container to operate directly on underlying block devices (or image files) and load necessary kernel modules.

Through this orchestration, independent services that would otherwise need to be configured separately at the Linux system level are integrated into a highly cohesive control‑plane foundation.

## 1.3 Real‑World Division of Labour in the Protocol Stack

In actual deployments, a sensible division of protocols improves boot stability:

1. **TFTP (network boot only)**: Used to transfer the few tens of KB of iPXE firmware (`undionly.kpxe` / `snponly.efi`) and the few KB of `.ipxe` scripts. It is not used for large file transfers, as UDP packet loss can interrupt the transfer. **Note**: Ensure that only one DHCP server on the LAN responds to PXE requests; otherwise, the main router’s DHCP may hand out incorrect Option 66, causing iPXE to contact the wrong TFTP server and time out.
2. **HTTP (large file transfers)**: Once the iPXE script takes over, all Linux `vmlinuz`/`initrd` or Windows `boot.wim` files are downloaded via HTTP, leveraging TCP to guarantee transfer integrity and speed.
3. **iSCSI (operating system runtime foundation)**: Carries the root filesystem while the OS is running. iSCSI presents a block device, which the operating system recognises as a local physical disk, avoiding some of the pitfalls of NFS network filesystems.

## 1.4 Boot State Machine: From Power‑On to Desktop

A complete diskless boot consists of four phases. Linux and Windows differ in how they handle the latter two phases.

### Phase 1: Traditional PXE Bootstrap

The Worker powers on and sends a DHCP Discover. The Controller assigns an IP address and delivers the TFTP server IP and the path to the iPXE firmware via Option 66/67. The Worker downloads and executes the firmware; the native PXE ROM stage is finished.

### Phase 2: iPXE Takeover and Script Loading

iPXE initialises the NIC and requests DHCP again. The Controller recognises the iPXE identifier and delivers the path to the `boot.ipxe` script. iPXE downloads the script, loads the menu, and prepares to boot the OS.

### Phase 3: OS Loading (Differences Between Linux and Windows)

* **Linux (Debian/Ubuntu)**: The official installers’ network installation mode is not relied upon (Ubuntu’s Subiquity installer has limited support for iSCSI disk selection). A clean system is provisioned onto the iSCSI LUN in advance using `debootstrap`, and the `initramfs-tools` hook script is modified to package the iSCSI configuration. iPXE executes `sanboot`, handing control of the LUN to GRUB, and GRUB loads the kernel.
* **Windows 11**: `dism++` is used to inject a universal NIC and storage driver bundle into `boot.wim` beforehand (sidestepping Microsoft ADK version dependencies). iPXE issues two `sanhook` commands, simultaneously attaching the iSCSI system disk and the iSCSI virtual optical drive (ISO). It then loads `boot.wim` into the PE environment and runs `setup.exe` from the virtual drive for installation.

### Phase 4: Kernel Takeover and Root Filesystem Mount

* **Linux**: The kernel boots; `initramfs` reads the injected `/etc/iscsi.initramfs`, loads the `iscsi_tcp` module, and reconnects to the iSCSI Target. It mounts the root partition using the UUID in `/etc/fstab` and completes `switch_root`.
* **Windows**: After installation, the system reboots. Through the iBFT (iSCSI Boot Firmware Table) mechanism, the native iSCSI driver takes over the system disk early in the boot process and proceeds to the desktop.

## 1.5 Core Automation: The Dynamic IQN Variable Chain

**We recommend reading this section alongside the project repository source code.**

Understanding how this chain works is crucial for subsequent configuration. It is advisable to open the `iPXE-All-Ready` repository and follow along with the configuration files under `dnsmasq/` and the `boot.ipxe` and `menu.ipxe` source files under `tftp/`.

Some iPXE tutorials on the Internet hardcode MAC addresses or fixed IQNs in scripts. Such an approach requires frequent code changes when adding nodes. This project preserves the dynamic chain mechanism provided by iPXE, decoupling configuration from the number of nodes.

Below is a walkthrough of this mechanism in a real‑world environment (using a node with MAC `52:54:00:12:34:56` and hostname `worker-01` booting Ubuntu as an example):

### 1. Identity Injection at the DHCP Layer

In the Controller’s `dnsmasq`, the MAC address is bound to a hostname and delivered via DHCP Option 12.

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

* `${hostname}` = `worker-01`
* `${initiator-iqn}` = `iqn.2026-07.com.controller:worker-01`

### 3. Deriving the Target IQN and Assembling the URI in menu.ipxe

When the user selects “Boot Ubuntu” from the menu, `menu.ipxe` derives the target storage identity (Target IQN) from the base variables and assembles the iSCSI resource locator (URI).

```ipxe
# menu.ipxe (Ubuntu boot entry)
# Derive the Target IQN (append the OS suffix to the hostname)
set target-iqn ${base-iqn}:${hostname}.Ubuntu

# Assemble the iSCSI URI
# Format: iscsi:<server>:[<protocol>]:[<port>]:[<lun>]:<target-iqn>
set root-path iscsi:${iscsi-server}::::${target-iqn}
```

**Resulting variable values**:

* `${target-iqn}` = `iqn.2026-07.com.controller:worker-01.Ubuntu`
* `${root-path}` = `iscsi:192.168.1.5::::iqn.2026-07.com.controller:worker-01.Ubuntu`

### 4. Final Consumption Across Protocol Boundaries

iPXE executes the `sanboot` command, translating the in‑memory variables into low‑level iSCSI login packets.

```ipxe
# Perform diskless boot
sanboot --keep --drive 0x80 ${root-path}
```

**Under the hood**: iPXE sends an iSCSI Login Request to `192.168.1.5`. The packet contains the Initiator IQN and Target IQN. After the iSCSI Server verifies the ACL, it maps the corresponding LUN to the node.

**Summary**: This chain eliminates hardcoding from the scripts. When adding a new diskless workstation, you only need to bind the MAC and hostname in DHCP and create a LUN with the corresponding suffix on the iSCSI Server; the iPXE scripts never need to be modified.

## 1.6 Building the Base Environment and a Debugging Baseline

Before diving into the deployment of specific operating systems, it is necessary to set up a standardised verification environment. Diskless boot involves multiple low‑level protocols such as networking, storage, and the kernel; the accuracy of the environment configuration directly affects the boot outcome.

### 1.6.1 Preparing Basic Tools

During the debugging phase, it is recommended to avoid testing directly on physical machines. Debugging low‑level protocol stacks involves uncertainties; using virtualisation tools allows you to build an isolated test environment.

**1. Virtualisation Platform (VMware Workstation / ESXi / PVE)**

This is the most critical and indispensable infrastructure for the entire project. It is not just a “good enough” substitute for casual testing; it serves two main purposes in a diskless architecture:

* **Providing a rollback‑capable test environment**
  Diskless boot involves DHCP, TFTP, iSCSI, kernel booting, and more. On a physical machine, a configuration error may leave the NIC’s PXE ROM in an abnormal state or inadvertently wipe the local disk. Virtual machines offer snapshot and rollback capabilities, allowing quick environment resets. Moreover, a virtual network can provide an isolated test environment that is not interfered with by the main router’s DHCP.
* **Solving cold‑boot driver issues**
  When a physical machine has a newer NIC or storage controller whose drivers are missing from the Windows `boot.wim` or the official Linux kernel, you may encounter situations where the network cannot be connected or the disk cannot be recognised.
  In such cases, you can exploit the decoupling between iSCSI block storage and the compute node:
  1. On the Controller, temporarily modify the DHCP binding so that a virtual machine with generic virtual hardware mounts the iSCSI system‑disk LUN that is dedicated to that physical machine.
  2. Boot the virtual machine into the OS, then download and install the drivers required by the physical machine from within the system (using `dism` for Windows, or `apt` / compiling kernel modules and running `update-initramfs` for Linux).
  3. Shut down the virtual machine and release the LUN. At this point the system disk already contains the necessary drivers, and the physical machine can boot normally when powered on.

**2. Wireshark: Network Analysis Tool**

When iPXE reports errors or iSCSI handshakes fail, you can analyse the low‑level packets by capturing traffic. Common display filters include:

* `bootp`: Monitor DHCP interactions to troubleshoot IP assignment and the delivery of Options 66/67.
* `tftp`: Monitor the fetching of iPXE firmware and `.ipxe` scripts to locate `Connection timed out` or `File not found` issues.
* `iscsi`: Monitor iSCSI Login PDUs to troubleshoot IQN authentication, ACL, or LUN mapping issues.

**3. VS Code + Remote - SSH**

Connect to the Controller node remotely via SSH. Using VS Code to edit iPXE scripts, Docker Compose files, and dnsmasq configuration allows you to modify configurations and view logs within a single window.

### 1.6.2 Controller Node Environment Deployment

When deploying for the first time, it is recommended to run the Controller node on a virtualisation platform (such as VMware Workstation). Snapshots allow quick rollback if configuration errors occur. After the full chain has been verified, you can migrate it to a physical machine or a NAS environment.

**1. Hardware and Storage Allocation Baseline**

The Controller node needs to host DHCP, TFTP, HTTP, and iSCSI Target services:

* **Compute resources**: 2 vCPUs, 2–4 GB RAM.
* **System disk**: 20 GB. Used for the base Linux operating system (Ubuntu 22.04 LTS or Debian 12 is recommended) and the Docker engine.
* **Data disk**: 60 GB (or larger). It is recommended to add it as a separate virtual disk and mount it to `/pool1`. This disk is dedicated to storing iSCSI backend image files, avoiding consumption of the system disk space.

**2. Network Architecture (NAT Mode)**

In VMware, set the Controller node’s network adapter to **NAT mode**. This ensures the Controller can access the external network while building an isolated test LAN with the Worker nodes through the virtual NIC.

Open VMware’s “Virtual Network Editor”, select the corresponding NAT network (e.g., VMnet8), and **uncheck “Use local DHCP service to distribute IP addresses to virtual machines”**. Hand over the DHCP assignment authority to the Controller node.

At the same time, the Controller’s network interface must be configured with a static IP address.

### 1.6.3 Configuring a Static IP Inside the OS

Taking Netplan, commonly used on Ubuntu/Debian, as an example, edit `/etc/netplan/01-netcfg.yaml` and set a static IP. Assume the VMware NAT subnet is `192.168.100.0/24`, the gateway is `192.168.100.2`, and the Controller IP is `192.168.100.10`:

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    ens33: # Replace with the actual interface name (check with `ip a`)
      dhcp4: no
      addresses:
        - 192.168.100.10/24
      routes:
        - to: default
          via: 192.168.100.2
      nameservers:
        addresses: [8.8.8.8, 114.114.114.114]
```

After configuration, run `sudo netplan apply` to apply the settings.

### 1.6.4 Storage Planning and Directory Structure

It is recommended to separate the data disk and use it exclusively for iSCSI image files. This way, only the data disk needs to be handled during future expansion or migration.

Assume the 60 GB data disk is formatted and mounted to `/pool1`.

* **System disk directory (project repository)**: Assume it is located at `/home/ipxe-all-ready`, holding configuration and small files.

  ```text
  /home/ipxe-all-ready/
  ├── docker-compose.yml
  ├── dnsmasq/          # DHCP/TFTP configuration
  ├── tftp/             # iPXE firmware and scripts
  └── www/              # HTTP resources (kernel / initrd / wim)
  ```

* **Data disk directory (iSCSI storage pool)**: Create a directory under `/pool1` for block device images.

  ```bash
  mkdir -p /pool1/iscsi_img
  ```

### 1.6.5 Preparing iSCSI Backend Image Files and Automated Registration

When creating image files inside the `iscsi_img` directory, follow a specific naming convention so that they work with the automated registration script.

* **Naming convention**: Use the format `${hostname}.${os_type}.img`.
  * *Example*: `worker-01.Debian.img`, `worker-01.Ubuntu.img`, `worker-02.Windows.img`.
  * *Rationale*: This naming scheme corresponds to the Target IQNs dynamically assembled by iPXE as described in Section 1.5 (e.g., `iqn.2026-07.com.controller:worker-01.Debian`).

Create sparse files using `fallocate`:

```bash
cd /pool1/iscsi_img
fallocate -l 20G worker-01.debian.img
fallocate -l 60G worker-01.win11.img
```

An automated registration script `iscsi-target-gen.sh` is provided in the root of the project repository. This script scans the `/pool1/iscsi_img` directory, parses the hostname and OS type from the filenames, and automatically creates Targets, binds LUNs, and configures ACLs.

### 1.6.6 Docker Compose Storage Mapping

Since the project code resides on the system disk while the iSCSI images are on the data disk, you must map the physical paths into the containers via `volumes` in `docker-compose.yml`.

Taking the `ipxe-iscsi` container as an example:

```yaml
  ipxe-iscsi:
    image: wtnb75/stgt
    container_name: ipxe-iscsi
    network_mode: host
    privileged: true
    volumes:
      # Map the iSCSI image directory on the data disk to /home/iscsi_img inside the container
      - /pool1/iscsi_img:/home/iscsi_img 
```

*Note: The left side of the colon is the absolute path on the host; the right side is the path inside the container. The iSCSI Target service will read the image files from `/home/iscsi_img` inside the container and provide block device services.*

### 1.6.7 Adapting the Core Bootstrap Layer Configuration (dnsmasq) and Chain‑loading Logic

The project repository provides `dnsmasq.conf` and `dhcp-hosts.conf` templates under the `dnsmasq/` directory. You need to modify some parameters according to the actual physical network environment.

```text
# dnsmasq/dnsmasq.conf (modify the parameters marked with [MODIFY] below)

# 1. [MODIFY] Listen on the specified interface (replace with the actual NIC name of the Controller, e.g., ens33, eth0)
interface=enp1s5 
bind-interfaces

dhcp-range=::,static

# 2. [MODIFY] DHCP address pool and basic network parameters
dhcp-range=192.168.1.50,192.168.1.100,255.255.255.0,12h
# [MODIFY] Option 3: Gateway IP
dhcp-option=3,192.168.100.2
# [MODIFY] Option 6: DNS servers
dhcp-option=6,223.5.5.5,8.8.8.8

# 3. Enable TFTP service and specify the root directory inside the container (no modification needed)
enable-tftp
tftp-root=/var/tftp

# 4. Architecture identification (based on PXE Client Architecture Option 93; no modification needed)
dhcp-match=set:bios,option:client-arch,0        # Legacy BIOS
dhcp-match=set:efi64,option:client-arch,7       # UEFI x64 (EFI BC)
dhcp-match=set:efi64,option:client-arch,9       # UEFI x64 (EFI x86_64)

# 5. First-stage boot: firmware distribution (no modification needed)
dhcp-boot=tag:efi64,snponly.efi                 # UEFI → snponly.efi
dhcp-boot=tag:bios,undionly.kpxe                # Legacy → undionly.kpxe

# 6. Second-stage boot: iPXE chain‑loading (no modification needed)
dhcp-userclass=set:ipxe,iPXE
dhcp-boot=tag:ipxe,boot.ipxe

# 7. Static hostname assignment (used for dynamic iSCSI IQN generation; no modification needed)
dhcp-hostsfile=/etc/dnsmasq.d/dhcp-hosts.conf
dhcp-leasefile=/var/lib/misc/dnsmasq.leases

# 8. Logging (for debugging; no modification needed)
log-dhcp
log-queries
```

**Parameter modification notes:**

1. **Interface name (`interface`)**: Run `ip a` to check the actual NIC name of the Controller and replace `enp1s5` in the template.
2. **Subnet and gateway (`dhcp-range` & `dhcp-option=3`)**: The address pool and gateway must match the physical subnet or VMware NAT subnet where the Controller resides.
3. **TFTP root directory (`tftp-root`)**: Keep it as `/var/tftp`; it must correspond to the volume mapping of the `ipxe-dnsmasq` container in `docker-compose.yml`.

**Underlying mechanism explanation:**

* **Automatic Next‑Server delivery**: The template does not hardcode the Next‑Server (TFTP server IP) in `dhcp-boot`. In `bind-interfaces` mode, dnsmasq automatically advertises its own listening IP as the Next‑Server. If the Controller IP changes later, this configuration file does not need to be modified.
* **Chain‑loading (`dhcp-userclass=set:ipxe,iPXE`)**:
  * **First request**: The physical machine’s native PXE ROM sends a DHCP request without an `iPXE` tag; dnsmasq delivers `snponly.efi`.
  * **Second request**: After `snponly.efi` loads, it sends another DHCP request with the `User-Class: iPXE` tag. dnsmasq captures this tag, triggers the `tag:ipxe` rule, and delivers the `boot.ipxe` script.
  * *Note*: If this configuration is removed, after loading iPXE it would again download `snponly.efi`, causing a boot loop.

**Adapting Worker identity injection:**

Open `dnsmasq/dhcp-hosts.conf` and replace the template MAC addresses with the actual MAC addresses of your Worker VMs or physical machines:

```text
# dnsmasq/dhcp-hosts.conf
# Format: MAC address, hostname, fixed IP (optional)
00:0c:29:b9:8b:2d,worker-01,192.168.1.51
```

After adapting the parameters, run `docker compose up -d` to start the control‑plane services.