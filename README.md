# IPXE-All-Ready

![iPXE](https://img.shields.io/badge/iPXE-Network%20Boot-111111) ![iSCSI](https://img.shields.io/badge/iSCSI-Diskless%20Storage-0f766e) ![Control Plane](https://img.shields.io/badge/Control%20Plane-FastAPI-2563eb) ![Agent](https://img.shields.io/badge/Agent-STGT%20%2F%20LIO-7c3aed) ![dnsmasq](https://img.shields.io/badge/DHCP-dnsmasq-334155) ![License](https://img.shields.io/badge/License-Apache%202.0-green)

[中文版](./README.zh-CN.md) | [English](./README.md)

**IPXE-All-Ready** aims to establish an enterprise-grade, stateless compute node deployment standard built entirely on open-source components (iPXE + iSCSI + OS).

Our goal is not just to "get diskless boot working," but to pave the wilderness full of black boxes and dead ends into a modern, cross-platform, cross-architecture diskless infrastructure highway.

**All truly means All. Ready truly means Production-Ready.**
**The open-source diskless era has arrived.**

## Project Overview

`ipxe-all-ready` has evolved from a simple diskless boot proof‑of‑concept into a nascent open‑source control plane for stateless compute node delivery. It converges the previously scattered manual commands, static configuration, and empirical guesswork into clearly defined component boundaries:

- **Control Plane**: A persistent HTTP service on the Controller node, responsible for Worker lifecycle orchestration, Agent scheduling, Worker storage ledger, `dnsmasq` hostname bindings, and `/boot-vars` boot‑variable projection.
- **iSCSI Agent**: A local executor deployed on each iSCSI Server. It receives orchestration commands from the Control Plane over HTTP and operates the host’s STGT / LIO iSCSI server via `docker.sock`.
- **iPXE static menus + dynamic variable injection**: `menu.ipxe` remains a static interaction layer. `boot.ipxe.cfg` fetches per‑worker variables from the Control Plane early in the boot process, resolving boot‑parameter differences across multiple iSCSI storage nodes.
- **Files as the source of truth**: No database is introduced. The control‑plane state is carried by `agents.yml`, `workers.yml`, `dhcp-hosts.conf`, and `operations.jsonl` — transparent, diff‑able, and manually repairable.
- **Separation of control plane and data plane**: The Control Plane only handles scheduling and bookkeeping. Worker block‑storage reads and writes travel directly over the iSCSI data plane, never passing through the control plane.

## Project Structure

```text
ipxe-all-ready/
├── docker-compose.yml
├── package.json
├── package-lock.json
├── iscsi-target-gen.sh
├── LICENSE
├── README.md
├── README.zh-CN.md
│
├── control_plane/                      # Control Plane (core service)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── control_plane.env
│   ├── control_plane.env.example
│   ├── Control_Plane_API_Docs.md
│   ├── app/                            # Python source code
│   ├── config/                         # Static configuration
│   └── state/                          # Runtime state
│
├── dnsmasq/                            # DHCP/TFTP configuration
│   ├── dnsmasq.conf
│   └── dhcp-hosts.conf
│
├── tftp/                               # iPXE boot files
│   ├── boot.ipxe
│   ├── boot.ipxe.cfg
│   ├── menu.ipxe
│   └── preseed.cfg
│
├── iscsi-server/                       # iSCSI storage service
│   ├── docker-compose.yml
│   ├── API_Reference.md
│   ├── Agent_API_Docs.md
│   ├── agent/                          # Agent component
│   ├── lio/                            # LIO kernel-space implementation
│   └── stgt/                           # STGT user-space implementation
│
├── webui/                              # Web admin panel (React + Vite)
│   ├── app/
│   │   └── src/                        # Frontend source (api, components, pages, i18n, styles)
│   └── deploy/                         # Deployment config (Nginx)
│       ├── Dockerfile
│       ├── nginx/
│       └── www/
│
└── docs/                               # Project documentation (Vitepress)
    ├── guide/                          # English guide
    └── zh/                             # Chinese guide
```

## 📚 Official Documentation & Hands‑on Guides

For complete architecture design, low‑level mechanism deep‑dives, and ground‑up deployment walkthroughs for each operating system, visit our dedicated documentation site:

 **[ipxe.lecreate.asia](https://ipxe.lecreate.asia)** | **[中文文档](https://ipxe.lecreate.asia/zh/)**

**Core breakthrough topics currently covered:**

- **[Ch1: Architecture & Core Link](https://ipxe.lecreate.asia/zh/guide/architecture)**  
  Dissect the iPXE + iSCSI boot state machine, unravel the DHCP/iPXE/iSCSI dynamic variable chain, and eliminate the black boxes in network booting.
- **[Ch2: Windows 11 Diskless Walkthrough](https://ipxe.lecreate.asia/zh/guide/windows-11)**  
  Use `dism++` to sidestep the ADK trap and inject universal drivers; leverage the `tgt --device-type cd` virtual optical drive mechanism to achieve a seamless native `setup.exe` installation and iBFT handover.

## Roadmap

The ultimate vision of `ipxe-all-ready` is not merely diskless booting for a single operating system, but building a cross‑platform, cross‑architecture, cloud‑native stateless computing infrastructure foundation.

### Phase 1: Breaking the Ice – Core System Breakthrough

*Establish the core diskless boot standard and close the low‑level boot loop for the most mainstream desktop and server operating systems.*

- [x] **Debian 12**: Full chain validated; established the core diskless boot standard and baseline logic. Cracked the initramfs packaging black box, enabling "instant‑on" capability.
- [x] **Ubuntu 22.04 LTS**: Bypassed the Subiquity installer black box via `debootstrap`, resolving missing core commands caused by the ISO’s multi‑layered Overlay structure; explicitly injected iSCSI kernel modules and manually built auto‑login node configuration; replaced device paths with UUIDs for cross‑hardware compatibility; achieved true "plug‑and‑boot" instant‑on.
- [x] **Windows 11 24H2/25H2**: Conquered the low‑level boot mechanisms and system state dependencies in Windows environments. Used `dism++` to sidestep the ADK version trap, injecting a comprehensive "driver bundle" into `boot.wim` that covers both VMware and bare‑metal scenarios. Combined with the iSCSI server’s `--device-type cd` virtual optical drive mount of the ISO, we achieved seamless installer takeover and flawless native iSCSI boot.

### Phase 2: Broad Linux Distribution Ecosystem Compatibility

*Span different package managers and init system philosophies, expanding the diskless architecture’s Linux landscape.*

- [ ] **Arch Linux**: Adapt to its rolling‑release model and custom initialization framework, providing a minimalist diskless solution for geeks.
- [ ] **RHEL / Fedora family**: Explore diskless operation modes and compatibility under strict enterprise security policies.
- [ ] **Alpine Linux**: Build an ultra‑lightweight diskless base targeting edge computing, micro routers, and IoT nodes.

### Phase 3: Cloud‑Native & Modern Architecture Evolution

*Modernize the control plane and explore next‑generation network storage protocols to break through traditional architecture bottlenecks.*

- [ ] **Controller Containerization & High Availability**: Explore containerizing the boot services and storage control plane for one‑click deployment and cluster management.
- [ ] **Next‑Gen Storage Protocol Evaluation**: Research and test high‑performance network storage protocols such as NVMe‑oF, exploring paths to overcome traditional iSCSI I/O bottlenecks.
- [ ] **Cloud‑Native Edge Node Onboarding**: Explore seamless integration of diskless worker nodes with lightweight Kubernetes clusters, achieving automated orchestration where nodes "power on and immediately join the cluster."

### Phase 4: Cross‑Architecture & Heterogeneous Computing

*Break the boundaries of x86, providing a stateless foundation for the diverse compute workloads of the future.*

- [ ] **ARM64 Architecture Support**: Investigate network boot mechanisms in ARM UEFI environments, exploring the feasibility of diskless ARM servers and edge clusters.
- [ ] **Heterogeneous Compute Node Delivery**: Develop standardized delivery templates combining diskless systems with shared storage for specialized compute nodes such as AI inference and GPU rendering.

## Barriers We Have Broken Through

1. **The initramfs “chicken‑and‑egg” deadlock**: How to equip a minimal initramfs with full iSCSI network storage handshake capability before the kernel mounts the root filesystem? We have established standardized module injection and automatic login mechanisms.
2. **The bootloader black‑box trap**: Resolved hidden typos in GRUB variable names during cross‑environment installation, as well as the “perfect black screen” caused by missing MBR boot code after configuration updates.
3. **The iPXE session “cliff‑edge” handover**: Broke through the traditional `sanboot` behavior of tearing down the underlying connection at the moment of control handover, achieving seamless keep‑alive and takeover of the iSCSI session from the Pre‑OS environment into kernel space.
4. **Complex Pre‑OS network stack initialization**: Thoroughly eliminated IPv6 routing black holes, DHCP timeouts, and routing conflicts in multi‑NIC environments during the very earliest boot stages.
5. **The `update-initramfs` black‑box packaging trap**: Discovered that the official hook scripts completely ignore the custom `/etc/iscsi.initramfs` file. By modifying `/usr/share/initramfs-tools/hooks/iscsi` to forcibly inject the configuration, we turned passive acceptance into active control.
6. **The Ubuntu Subiquity installer’s iSCSI blind spot**: The official installer completely hides iSCSI devices on the disk selection screen. We abandoned graphical installation and used `debootstrap` to pull a clean system directly from the source, achieving “dimensionality reduction” deployment.
7. **The Ubuntu ISO multi‑layered Overlay structure trap**: After extracting the squashfs we found core commands like `bash` missing, confirming the official ISO uses a layered architecture. We decisively switched to the `debootstrap` approach to ensure system integrity.
8. **Missing iSCSI modules in a clean system**: The minimal system pulled by `debootstrap` contains no preconfigured iSCSI boot logic whatsoever. We explicitly injected kernel modules such as `iscsi_tcp` and `libiscsi`, and manually built a complete node configuration with `node.startup = automatic`.
9. **Windows PE network deadlock and ADK dependency**: Leveraged `dism++` to offline‑inject a universal driver bundle (vmxnet3, pvscsi, iastorvd, etc.), breaking the no‑NIC‑driver deadlock in the PE phase and perfectly avoiding Microsoft ADK version restrictions. Combined with `--device-type cd` ISO mounting, the installer completes deployment as smoothly as reading from a physical CD‑ROM.

## Architecture Definition

This project adopts a modern distributed node naming convention and strictly separates the **control plane** (decision‑making, scheduling; low traffic) from the **data plane** (data movement; high traffic). The roles are defined as follows:

![Architecture Design](./assets/%E6%9E%B6%E6%9E%84%E8%AE%BE%E8%AE%A1.svg)

* **Controller**: The brain of the cluster. Hosts the **Control Plane** persistent HTTP service, responsible for Worker lifecycle orchestration, Agent scheduling, Worker storage ledger, `dnsmasq` hostname bindings, and read‑only dynamic projection of iPXE boot variables. The Control Plane itself never directly operates any iSCSI server, nor does it take over static file serving or menu generation: HTTP files are served by nginx, the iPXE menus remain static interactions, and all storage operations are delegated to Agents — so that the local optical drive and the remote system disk follow the same scheduling logic.
* **iSCSI Server**: The node that provides block storage. It can be co‑located with the Controller or deployed independently on a large‑capacity NAS / SAN. Each node hosts an **API Agent** that receives HTTP requests from the Control Plane and operates the local iSCSI server container via `docker.sock`. The server software can be **heterogeneous**: **stgt** (user‑space, supports mounting ISO as a virtual optical drive, friendly to constrained environments) or **LIO** (kernel‑space, production‑grade disk targets). Backend differences are encapsulated inside the Agent; the Control Plane does not need to be aware of them. The node treats the files in the image directory as the **single source of truth** — at startup it automatically scans the directory and rebuilds the iSCSI configuration, eliminating the need for separately maintained configuration files.
* **Worker**: A stateless compute node with no local disk. After power‑on it obtains an IP address and identity via PXE, loads iPXE, attaches the iSCSI system disk (and additionally the virtual optical drive during installation), and boots the operating system.

**Separation of Control Plane and Data Plane**

* **Control‑plane traffic** is the HTTP orchestration between the Control Plane and the Agents, plus the Worker’s early‑boot read‑only request to `/boot-vars` for per‑worker variables. The volume is small and occurs only during provisioning, decommissioning, or boot‑variable projection.
* **Data‑plane traffic** is the block‑storage read/write between the Worker and the iSCSI Server, physically separated from the control plane.
* **Installation media and system disk placed close to where they belong**: The ISO virtual optical drive is located near the Control Plane (the installation media originates on the Controller) and is mounted by the Controller node’s Agent using stgt; large‑capacity system disks reside on the remote iSCSI Server. A Worker therefore connects to two iSCSI targets — the Controller’s optical drive and the storage node’s system disk.

## Current Progress & How to Get Involved

**Phase 1 – Core System Breakthrough is now fully completed! The full chain for Debian 12, Ubuntu 22.04 LTS, and Windows 11 24H2/25H2 has been thoroughly validated.** While the system images were being nailed down, we simultaneously built a **distributed control plane** — so that "adding a diskless machine" is now a single orchestration command issued by the Control Plane instead of manually editing several files.

**Control Plane Already Landed**

* **Distributed scheduling model**: The Control Plane only issues HTTP requests; the API Agent on each iSCSI Server receives them and operates the local iSCSI server. Control plane and data plane are separated. Adding/removing a Worker has been converged from manual configuration changes into stable contracts like `POST /workers` and `DELETE /workers/{id}`.
* **Lightweight control plane with files as the source of truth**: No database. `config/agents.yml` records the Agent inventory, `state/workers.yml` holds the Worker storage ledger, `dnsmasq/dhcp-hosts.conf` serves as the single source of truth for MAC → hostname mapping, and `operations.jsonl` maintains the control‑plane audit trail.
* **Worker lifecycle closed loop**: Creating a Worker automatically assembles the IQN, selects a disk Agent, calls the Agent to create a blank disk or clone from a golden image, writes the Worker ledger, writes the `dnsmasq` static hostname binding, and sends a HUP signal to the `ipxe-dnsmasq` container via `docker.sock` to reload the configuration.
* **Dynamic per‑worker boot‑variable injection**: While preserving the iPXE static menu interaction, a read‑only `/boot-vars` endpoint has been added. The Control Plane queries the inventory by MAC/hostname and dynamically returns variables such as `iscsi-server`, `menu-default`, and `menu-timeout`. `menu.ipxe` requires zero changes; `boot.ipxe.cfg` simply fetches the variables at the end and recalculates `base-iscsi`, enabling per‑worker boot‑parameter overrides across multiple iSCSI storage nodes.
* **stgt backend for the API Agent**: Disk LUN creation (synchronously generating `.img` files), ISO virtual optical drive mounting, directory bulk scanning, and base IQN validation have all been verified. Using the image directory files as the truth and auto‑scanning at startup to rebuild the configuration has cured the volatility of stgt configurations.
* **Heterogeneous backend design**: Both stgt and LIO backends have been integrated into the Agent. The LIO server is containerized; the Agent’s LIO backend already supports blank disk creation, target deletion, and status queries. Backend differences are encapsulated inside the Agent and invisible to the Control Plane.
* **Storage performance**: Cloning from a golden image to a work disk completes in seconds on btrfs via reflink. Measured data blocks are shared with zero additional disk footprint.
* **Web management UI**: A minimalist black‑and‑white industrial‑style SPA built with React + Vite, integrating the full management capability of the Control Plane.
  * **Dashboard**: Overview of Worker / Agent cluster status, summary of recent operation logs.
  * **Workers management**: List view, filtering, inline creation form (blank disk / golden‑image clone / Windows ISO install phase), with conditional field display.
  * **Worker details**: Ledger information (Identity / Disk / CD‑ROM), live status probes (dnsmasq binding, disk/cd target existence), boot‑variable projection (code‑block display of /boot-vars), safe deletion (inline double‑confirmation with optional removal of the `.img` disk file).
  * **Agents monitoring**: Responsive grid card layout showing backend type, capability description, and health status, with a live‑probe toggle.
  * **Operation logs**: Audit stream with incremental loading, timestamp + operation type + status flag + associated Worker.
  * **Tech stack**: React 18 + React Router 6 (HashRouter) + pure CSS‑variable‑driven theming, zero third‑party UI library dependencies.
  * **Deployment**: Built by Vite as pure static files and served uniformly by the nginx container; API proxying is forwarded to the Control Plane through nginx, requiring no additional runtime.
* **File browser**: Integrated into the same nginx container. An njs script provides a JSON directory listing API, exposing iPXE boot files (ISO, kernel, initrd) under the `public/` directory.
  * The file download endpoint `/file/` is designed specifically for iPXE `chain` / `initrd` commands; 404 responses are plain text and never return an HTML page.
  * The Web UI and the file browser share the same nginx container (port :4838), with no extra process overhead.

**Control Plane In Progress**

* **CLI and initial deployment experience**: A thin CLI will be provided in the future for initializing configuration, checking component health, launching the compose stack, and serving as a convenient client for the Control Plane API. Routine Worker lifecycle management will continue to go through the Control Plane HTTP API.
* **More complete reconciliation capability**: Compare `workers.yml`, `dnsmasq/dhcp-hosts.conf`, and the actual target state reported by the Agents; report and repair ledger drift.
* Connecting the Phase 1 image creation and golden‑image manual packaging process with the above control plane into a **one‑click deployment script**.

We are currently packaging every deep pitfall we conquered over countless nights into a **turnkey, rigorously tested, complete solution**, so we are not releasing scattered "pitfall‑avoidance commands" right now.

If you, too, are ambitious about stateless computing architectures, and if you are fed up with the black boxes and arrogance of commercial solutions:

- **Star** and **Watch** this project — you will be among the first to receive the complete multi‑OS diskless deployment blueprint.
- Join the **Discussions** to explore technical directions, or submit **Pull Requests** to participate in Phase 2/3/4 adaptation research.

*What are those who make history like? We don't know, but today, we are becoming them.*

## License

This project is licensed under the [Apache License 2.0](./LICENSE).

## Star History

<a href="https://www.star-history.com/?repos=dutyc%2Fipxe-all-ready&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=dutyc/ipxe-all-ready&type=date&theme=dark&legend=top-left&sealed_token=zjOknpQELRo5XRHVkZyVFbzpe3vGpw7134qQQpvRcCNi89-GWZKA9NmUisZj8-0rngIFYnEpjMkDcTyDcbpjeoo6F4-CNJ-_Jn5DDmYZQElWO7WgDPbJuA" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=dutyc/ipxe-all-ready&type=date&legend=top-left&sealed_token=zjOknpQELRo5XRHVkZyVFbzpe3vGpw7134qQQpvRcCNi89-GWZKA9NmUisZj8-0rngIFYnEpjMkDcTyDcbpjeoo6F4-CNJ-_Jn5DDmYZQElWO7WgDPbJuA" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=dutyc/ipxe-all-ready&type=date&legend=top-left&sealed_token=zjOknpQELRo5XRHVkZyVFbzpe3vGpw7134qQQpvRcCNi89-GWZKA9NmUisZj8-0rngIFYnEpjMkDcTyDcbpjeoo6F4-CNJ-_Jn5DDmYZQElWO7WgDPbJuA" />
 </picture>
</a>