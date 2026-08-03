# Barriers We Have Broken Through

*Diskless booting is a technical wilderness full of black boxes and dead ends. The following are the core barriers we have broken through, one by one, while closing the full chain for Debian 12, Ubuntu 22.04 LTS, and Windows 11.*

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
