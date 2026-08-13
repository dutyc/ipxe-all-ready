# Barriers We Have Broken Through

*Diskless booting is a technical wilderness full of black boxes and dead ends. The following are the core barriers we have broken through, one by one, while closing the full chain for Debian 12, Ubuntu 22.04 LTS, and Windows 11 — and while building the control-plane infrastructure.*

## Linux Boot Chain

1. **The initramfs "chicken-and-egg" deadlock**

   How can a minimal initramfs gain full iSCSI network-storage handshake capability before the kernel mounts the root filesystem? We have established standardized module-injection and automatic-login mechanisms.

2. **The bootloader black-box trap**

   Resolved the hidden typo in GRUB variable names during cross-environment installation, as well as the "perfect black screen" caused by missing MBR boot code after configuration updates.

3. **The iPXE session "cliff-edge" handover**

   Broke through the traditional `sanboot` behavior of tearing down the underlying connection at the moment of control handover, achieving seamless keep-alive and takeover of the iSCSI session from the Pre-OS environment into kernel space.

4. **Complex Pre-OS network stack initialization**

   Thoroughly eliminated IPv6 routing black holes, DHCP timeouts, and routing conflicts in multi-NIC environments during the very earliest boot stages.

5. **The `update-initramfs` black-box packaging trap**

   Discovered that the official hook scripts completely ignore the custom `/etc/iscsi.initramfs` file. By modifying `/usr/share/initramfs-tools/hooks/iscsi` to forcibly inject the configuration, we turned passive acceptance into active control.

## Ubuntu Deep Dives

6. **The Ubuntu Subiquity installer's iSCSI blind spot**

   The official installer completely hides iSCSI devices on the disk-selection screen. We abandoned graphical installation and used `debootstrap` to pull a clean system directly from the source, achieving "dimensionality-reduction" deployment.

7. **The Ubuntu ISO multi-layered Overlay structure trap**

   After extracting the squashfs we found core commands like `bash` missing, confirming the official ISO uses a layered architecture. We decisively switched to the `debootstrap` approach to ensure system integrity.

8. **Missing iSCSI modules in a clean system**

   The minimal system pulled by `debootstrap` contains no preconfigured iSCSI boot logic whatsoever. We explicitly injected kernel modules such as `iscsi_tcp` and `libiscsi`, manually built a complete node configuration with `node.startup = automatic`, and replaced device paths with UUIDs for cross-hardware compatibility.

## Windows Deep Dives

9. **Windows PE network deadlock and ADK dependency**

   Leveraged `dism++` to offline-inject a universal driver bundle (vmxnet3, pvscsi, iastorvd, etc.), breaking the no-NIC-driver deadlock in the PE phase and perfectly avoiding Microsoft ADK version restrictions. Combined with `--device-type cd` ISO mounting, the installer completes deployment as smoothly as reading from a physical CD-ROM.

## Control Plane & Infrastructure

10. **The file-level bind-mount inode trap in dnsmasq**

    `dhcp-hosts.conf` is mounted into the container as a file-level bind mount, which locks the inode at the moment of the write; the original rename-based atomic write replaced the inode on every save, so the container kept reading the stale file and HUP reloads were useless — only a container rebuild re-mounted the new file. Fix: truncate-write the original file in place (inode stays stable), restoring the file-level mount semantics and making HUP reloads effective again.

11. **LIO's incompatible iSCSI root separator**

    stgt root paths require `:::1:` (LUN placeholder 1) while LIO expects `::::` (empty placeholder). Assembling every root path with the stgt format made iSCSI mounts fail on LIO. `/boot-vars` now projects the differing separator (`iscsi-sep`) per the backend type of the Agent hosting the system disk, root-path assembly stays static on the iPXE side, and `boot.ipxe.cfg` guards with `isset` so the static fallback never overwrites an injected LIO format.

12. **The `${mac:hexraw}` expansion failure on real iPXE firmware**

    The `${mac:hexraw}` modifier recommended in official docs expands to an empty value on real iPXE devices, dropping the MAC parameter so the backend cannot recognize the machine and auto-registration silently fails. Switching to the colon-formatted `${mac}` works everywhere; the backend normalizes by stripping colons/dashes/dots, so both formats are recognized.

13. **Zero-touch auto-registration "silent failure"**

    If `boot.ipxe.cfg` still carries the template default controller IP — mismatching the real subnet — the iPXE request to `/boot-vars` is unreachable and `|| goto` skips it silently; the backend never sees the request, and the symptom is "worker gets no hostname and never reboots". Fix: `set controller_ip ${next-server}` (the DHCP server IP in a co-located deployment) — zero hardcoding, and subnet changes require no script edits.

14. **WebUI white screen: null dereference**

    The Agent role computation ran on the component's first render (when `agent` is still null), throwing `TypeError: Cannot read properties of null (reading 'role')` and unmounting the whole React tree before any API request could even be issued. Fix: compute the role only after the null-state branch returns.

15. **Confirmation dialogs clipped by container boundaries**

    The dialog expanded below the trigger button with `position: absolute`, and the card container's `overflow: hidden` clipped the expanded part (the bulk sidebar had the same flaw). Fix: `position: fixed` full-screen overlay with a centered dialog — no longer tied to the trigger's positioning context, so no container can clip it.
