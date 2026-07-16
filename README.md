# IPXE-All-Ready

[中文版](./README.zh-CN.md) | [English](./README.md)

**IPXE-All-Ready** aims to establish an enterprise-grade, stateless compute node deployment standard built entirely on open-source components (iPXE + iSCSI + OS).

Our goal is not just to “get diskless boot working,” but to pave the wilderness full of black boxes and dead ends into a modern, cross-platform, cross-architecture diskless infrastructure highway.

**All truly means All. Ready truly means Production-Ready.**  
**The open-source diskless era has arrived.**

## 📚 Official Documentation & Hands-on Guides

For complete architecture design, low-level mechanism deep-dives, and ground-up deployment walkthroughs for each operating system, visit our dedicated documentation site:

 **[ipxe.lecreate.asia](https://ipxe.lecreate.asia)** | **[中文文档](https://ipxe.lecreate.asia/zh/)**

**Core breakthrough topics currently covered:**

- **[Ch1: Architecture & Core Link](https://ipxe.lecreate.asia/guide/architecture)**  
  Dissect the iPXE + iSCSI boot state machine, unravel the DHCP/iPXE/iSCSI dynamic variable chain, and eliminate the black boxes in network booting.

- **[Ch2: Windows 11 Diskless Walkthrough](https://ipxe.lecreate.asia/guide/windows-11)**  
  Use `dism++` to sidestep the ADK trap and inject universal drivers; leverage the `tgt --device-type cd` virtual optical drive mechanism to achieve a seamless native `setup.exe` installation and iBFT handover.

## Roadmap

The ultimate vision of `ipxe-all-ready` is not merely diskless booting for a single operating system, but building a cross-platform, cross-architecture, cloud-native stateless computing infrastructure foundation.

### Phase 1: Breaking the Ice – Core System Breakthrough
*Establish the core diskless boot standard and close the low-level boot loop for the most mainstream desktop and server operating systems.*

- [x] **Debian 12**: Full chain validated; established the core diskless boot standard and baseline logic. Cracked the initramfs packaging black box, enabling “instant-on” capability.
- [x] **Ubuntu 22.04 LTS**: Bypassed the Subiquity installer black box via `debootstrap`, resolving missing core commands caused by the ISO’s multi-layered Overlay structure; explicitly injected iSCSI kernel modules and manually built auto‑login node configuration; replaced device paths with UUIDs for cross‑hardware compatibility; achieved true “plug‑and‑boot” instant‑on.
- [x] **Windows 11 24H2/25H2**: Conquered the low-level boot mechanisms and system state dependencies in Windows environments. Used `dism++` to sidestep the ADK version trap, injecting a comprehensive “driver bundle” into `boot.wim` that covers both VMware and bare-metal scenarios. Combined with the iSCSI server’s `--device-type cd` virtual optical drive mount of the ISO, we achieved seamless installer takeover and flawless native iSCSI boot.

### Phase 2: Broad Linux Distribution Ecosystem Compatibility
*Span different package managers and init system philosophies, expanding the diskless architecture’s Linux landscape.*

- [ ] **Arch Linux**: Adapt to its rolling-release model and custom initialization framework, providing a minimalist diskless solution for geeks.
- [ ] **RHEL / Fedora family**: Explore diskless operation modes and compatibility under strict enterprise security policies.
- [ ] **Alpine Linux**: Build an ultra-lightweight diskless base targeting edge computing, micro routers, and IoT nodes.

### Phase 3: Cloud-Native & Modern Architecture Evolution
*Modernize the control plane and explore next-generation network storage protocols to break through traditional architecture bottlenecks.*

- [ ] **Controller Containerization & High Availability**: Explore containerizing the boot services and storage control plane for one-click deployment and cluster management.
- [ ] **Next-Gen Storage Protocol Evaluation**: Research and test high-performance network storage protocols such as NVMe-oF, exploring paths to overcome traditional iSCSI I/O bottlenecks.
- [ ] **Cloud-Native Edge Node Onboarding**: Explore seamless integration of diskless worker nodes with lightweight Kubernetes clusters, achieving automated orchestration where nodes “power on and immediately join the cluster.”

### Phase 4: Cross-Architecture & Heterogeneous Computing
*Break the boundaries of x86, providing a stateless foundation for the diverse compute workloads of the future.*

- [ ] **ARM64 Architecture Support**: Investigate network boot mechanisms in ARM UEFI environments, exploring the feasibility of diskless ARM servers and edge clusters.
- [ ] **Heterogeneous Compute Node Delivery**: Develop standardized delivery templates combining diskless systems with shared storage for specialized compute nodes such as AI inference and GPU rendering.

## Barriers We Have Broken Through

1. **The initramfs “chicken-and-egg” deadlock**: How to equip a minimal initramfs with full iSCSI network storage handshake capability before the kernel mounts the root filesystem? We have established standardized module injection and automatic login mechanisms.
2. **The bootloader black-box trap**: Resolved hidden typos in GRUB variable names during cross-environment installation, as well as the “perfect black screen” caused by missing MBR boot code after configuration updates.
3. **The iPXE session “cliff-edge” handover**: Broke through the traditional `sanboot` behavior of tearing down the underlying connection at the moment of control handover, achieving seamless keep-alive and takeover of the iSCSI session from the Pre‑OS environment into kernel space.
4. **Complex Pre‑OS network stack initialization**: Thoroughly eliminated IPv6 routing black holes, DHCP timeouts, and routing conflicts in multi‑NIC environments during the very earliest boot stages.
5. **The `update-initramfs` black-box packaging trap**: Discovered that the official hook scripts completely ignore the custom `/etc/iscsi.initramfs` file. By modifying `/usr/share/initramfs-tools/hooks/iscsi` to forcibly inject the configuration, we turned passive acceptance into active control.
6. **The Ubuntu Subiquity installer’s iSCSI blind spot**: The official installer completely hides iSCSI devices on the disk selection screen. We abandoned graphical installation and used `debootstrap` to pull a clean system directly from the source, achieving “dimensionality reduction” deployment.
7. **The Ubuntu ISO multi-layered Overlay structure trap**: After extracting the squashfs we found core commands like `bash` missing, confirming the official ISO uses a layered architecture. We decisively switched to the `debootstrap` approach to ensure system integrity.
8. **Missing iSCSI modules in a clean system**: The minimal system pulled by `debootstrap` contains no preconfigured iSCSI boot logic whatsoever. We explicitly injected kernel modules such as `iscsi_tcp` and `libiscsi`, and manually built a complete node configuration with `node.startup = automatic`.
9. **Windows PE network deadlock and ADK dependency**: Leveraged `dism++` to offline-inject a universal driver bundle (vmxnet3, pvscsi, iastorvd, etc.), breaking the no‑NIC‑driver deadlock in the PE phase and perfectly avoiding Microsoft ADK version restrictions. Combined with `--device-type cd` ISO mounting, the installer completes deployment as smoothly as reading from a physical CD‑ROM.

## Architecture Definition

This project adopts a modern distributed node naming convention with the following roles:

* **Controller**: The brain and storage center of the cluster. Provides DHCP, HTTP file distribution, and iPXE menu routing.
* **iSCSI Server**: The node that provides block storage services. Can be co‑located with the Controller or deployed independently.
* **Worker**: A stateless compute node. It has no local disk; it obtains an IP address via PXE, loads iPXE, mounts an iSCSI disk, and finally boots the operating system.

## Current Progress & How to Get Involved

**Phase 1 – Core System Breakthrough is now fully completed!** The full chain for Debian 12, Ubuntu 22.04 LTS, and Windows 11 24H2/25H2 has been thoroughly validated. We are currently packaging every deep pitfall we conquered over countless nights into one‑click deployment scripts.

We are not releasing scattered “pitfall‑avoidance commands” right now because we want to deliver a **turnkey, rigorously tested, complete solution**.

If you, too, are ambitious about stateless computing architectures, and if you are fed up with the black boxes and arrogance of commercial solutions:
- **Star** and **Watch** this project – you will be among the first to receive the complete multi‑OS diskless deployment blueprint.
- Join the **Discussions** to explore technical directions, or submit **Pull Requests** to participate in Phase 2/3/4 adaptation research.

*What are those who make history like? We don't know, but today, we are becoming them.*

## License

This project is licensed under the MIT License.

## Star History

<a href="https://www.star-history.com/?repos=dutyc%2Fipxe-all-ready&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=dutyc/ipxe-all-ready&type=date&theme=dark&legend=top-left&sealed_token=zjOknpQELRo5XRHVkZyVFbzpe3vGpw7134qQQpvRcCNi89-GWZKA9NmUisZj8-0rngIFYnEpjMkDcTyDcbpjeoo6F4-CNJ-_Jn5DDmYZQElWO7WgDPbJuA" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=dutyc/ipxe-all-ready&type=date&legend=top-left&sealed_token=zjOknpQELRo5XRHVkZyVFbzpe3vGpw7134qQQpvRcCNi89-GWZKA9NmUisZj8-0rngIFYnEpjMkDcTyDcbpjeoo6F4-CNJ-_Jn5DDmYZQElWO7WgDPbJuA" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=dutyc/ipxe-all-ready&type=date&legend=top-left&sealed_token=zjOknpQELRo5XRHVkZyVFbzpe3vGpw7134qQQpvRcCNi89-GWZKA9NmUisZj8-0rngIFYnEpjMkDcTyDcbpjeoo6F4-CNJ-_Jn5DDmYZQElWO7WgDPbJuA" />
 </picture>
</a>