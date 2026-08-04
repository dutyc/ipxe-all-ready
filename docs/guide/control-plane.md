# Control Plane Capabilities

*The Control Plane is the brain of `ipxe-all-ready`: it orchestrates the Worker lifecycle, schedules Agents, maintains the storage ledger, drives DHCP bindings, and projects per-worker boot variables. This page details its core capabilities and design trade-offs.*

## Design Principles

- **Separation of control plane and data plane**: The Control Plane only handles scheduling and bookkeeping; Worker block-storage reads and writes travel directly over the iSCSI data plane, never passing through the control plane. Control-plane traffic is small and occurs only during provisioning, decommissioning, or boot-variable projection.
- **Files as the source of truth**: No database is introduced. `config/agents.yml` records the Agent inventory, `state/workers.yml` holds the Worker storage ledger, `dnsmasq/dhcp-hosts.conf` is the single source of truth for MAC → hostname mapping, and `operations.jsonl` maintains the control-plane audit trail — transparent, diff-able, and manually repairable.
- **iPXE static menus + dynamic variable injection**: `menu.ipxe` remains a static interaction layer; `boot.ipxe.cfg` fetches per-worker variables from the Control Plane early in the boot process, resolving boot-parameter differences across multiple iSCSI storage nodes.

## Core Capabilities

### Zero-touch Provisioning

When a new MAC first requests `/boot-vars`, the Control Plane automatically assigns a `worker-xx` hostname in sequence (starting from `worker-01`), writes the Worker ledger and the `dnsmasq` static binding, reloads via HUP, then returns `menu-default=reboot` with a short timeout (`IPXE_CP_AUTO_BOOT_TIMEOUT`, default 1s) to loop until the administrator configures the node. Once a system disk is created and a default OS is set, the node boots straight into the target system. `IPXE_CP_AUTO_REGISTER` (enabled by default) is the master switch.

### Worker Lifecycle Closed Loop (Two-Step Creation)

`POST /workers` registers identity only (hostname + MAC binding); `POST /workers/{id}/luns/disk` then creates the system disk — assembling the IQN, selecting a disk Agent, creating a blank disk or cloning from a golden image (btrfs reflink, seconds), writing the ledger and the `dnsmasq` binding, and reloading via HUP.

### Multi-OS per Worker (disks Array Model)

A single Worker can mount multiple system disks, at most one per OS (duplicates return 409); `PUT /workers/{id}/default-os` sets the default boot OS (`default_os`), menu default item (`menu_default`), and menu timeout (`menu_timeout`), with the derivation chain `default_os > boot.menu_default > reboot`. Switching the default OS never requires touching the machine.

### Per-Worker Boot-Variable Injection

While preserving the iPXE static menu interaction, the `/boot-vars` endpoint queries the inventory by MAC/hostname and dynamically returns variables such as `base-iqn`, `iscsi-server`, `iscsi-sep`, `menu-default`, and `menu-timeout`; `iscsi-sep` is the iSCSI root **separator** (the field between `${iscsi-server}` and `${base-iqn}`), generated per the backend type of the Agent hosting the system disk (stgt `:::1:` / LIO `::::`), while root-path assembly (`iscsi:${iscsi-server}${iscsi-sep}${base-iqn}:${hostname}.<os>`) stays static in `menu.ipxe` — only the differing separator is projected by the backend. When no default boot is configured it returns a `reboot` short-timeout loop. `boot.ipxe.cfg` fetches the variables at the end and recomputes the `iscsi-sep` fallback behind an `isset` guard (so an injected LIO format is never overwritten).

### Agent LUN Direct Management

`GET/POST/DELETE /agents/{id}/luns` and `POST /agents/{id}/luns/scan` directly manage targets on iSCSI storage nodes (list LUNs / create disk / create CD / delete / scan the image directory to rebuild), independent of the Worker ledger. Combined with the `role.disk / role.cd` capability model, operations unsupported by a backend are rejected/greyed out on both the API and WebUI sides (e.g., LIO does not support ISO optical drives).

### Distributed Scheduling Model

The Control Plane only issues HTTP requests; the API Agent on each iSCSI Server receives them and operates the local iSCSI server. Adding/removing a Worker has been converged from manual configuration changes into stable contracts like `POST /workers` and `DELETE /workers/{id}`.

### Heterogeneous Backend Design

Both stgt and LIO backends are integrated into the Agent, and the LIO server is containerized. Backend differences (including role capabilities) are encapsulated inside the Agent and invisible to the Control Plane. Each storage node treats the files in its image directory as the **single source of truth** — at startup it automatically scans the directory and rebuilds the iSCSI configuration, curing the volatility of stgt configurations.

### Storage Performance

Cloning from a golden image to a work disk completes in seconds on btrfs via reflink. Measured data blocks are shared with zero additional disk footprint.

## Web Management UI

A minimalist black-and-white industrial-style SPA built with React + Vite (Chinese/English), integrating the full management capability of the Control Plane.

- **Dashboard**: Overview of Worker / Agent cluster status, summary of recent operation logs.
- **Workers management**: List view, filtering, two-step creation (register identity → create system disk: blank / golden-image clone, five OS choices: Windows / Ubuntu / Debian / CentOS / ESXi), multi-disk display.
- **Worker details**: Multi-disk cards, live status probes (dnsmasq binding, disk/cd target existence), default-boot configuration form (`default_os` / `menu_default` / `menu_timeout`), boot-variable projection (code-block display of /boot-vars), safe deletion (inline double-confirmation with optional removal of the `.img` disk file).
- **Agents monitoring & LUN direct management**: Responsive grid card layout showing backend type, capability (disk/cd roles), and health status, with a live-probe toggle; clicking a card opens the Agent LUN management page for creating disks, creating CDs (greyed out with a hint per role), deleting, and scanning the directory to rebuild targets.
- **Operation logs**: Audit stream with incremental loading, timestamp + operation type + status flag + associated Worker.
- **Tech stack**: React 18 + React Router 6 (HashRouter) + pure CSS-variable-driven theming, zero third-party UI library dependencies.
- **Deployment**: Built by Vite as pure static files and served uniformly by the nginx container; API proxying is forwarded to the Control Plane through nginx, requiring no additional runtime.

## File Browser

Integrated into the same nginx container. An njs script provides a JSON directory-listing API, exposing iPXE boot files (ISO, kernel, initrd) under the `public/` directory.

- The file download endpoint `/file/` is designed specifically for iPXE `chain` / `initrd` commands; 404 responses are plain text and never return an HTML page.
- The Web UI and the file browser share the same nginx container (port :4838), with no extra process overhead.
