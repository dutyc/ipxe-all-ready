# Control Plane Capabilities

*The Control Plane is the brain of `ipxe-all-ready`: it orchestrates the Worker lifecycle, schedules Agents, maintains the storage ledger, drives DHCP bindings, and projects per-worker boot variables. This page details its core capabilities and design trade-offs.*

## Design Principles

- **Separation of control plane and data plane**: The Control Plane only handles scheduling and bookkeeping; Worker block-storage reads and writes travel directly over the iSCSI data plane, never passing through the control plane. Control-plane traffic is small and occurs only during provisioning, decommissioning, or boot-variable projection.
- **Files as the source of truth**: No database is introduced. `config/agents.yml` records the Agent inventory, `state/workers.yml` holds the Worker storage ledger, `state/settings.json` holds runtime settings, `dnsmasq/dhcp-hosts.conf` is the single source of truth for MAC → hostname mapping, and `operations.jsonl` maintains the control-plane audit trail — transparent, diff-able, and manually repairable.
- **iPXE static menus + dynamic variable injection**: `menu.ipxe` remains a static interaction layer; `boot.ipxe.cfg` fetches per-worker variables from the Control Plane early in the boot process, resolving boot-parameter differences across multiple iSCSI storage nodes.

## Core Capabilities

### Zero-touch Provisioning

When a new MAC first requests `/boot-vars`, the Control Plane automatically assigns a `worker-xx` hostname in sequence (starting from `worker-01`), writes the Worker ledger and the `dnsmasq` static binding, reloads via HUP, then returns `menu-default=reboot` with a short timeout (`IPXE_CP_AUTO_BOOT_TIMEOUT`, default 1s) to loop until the administrator configures the node. Once a system disk is created and a default OS is set, the node boots straight into the target system. `IPXE_CP_AUTO_REGISTER` (enabled by default) is the **startup default**; after deployment the switch can be toggled at runtime via `GET/PUT /settings/auto-register` — the state persists to `state/settings.json` (survives restarts, takes precedence over the environment variable, takes effect immediately), and the WebUI Workers page toolbar provides a toggle button as well. When disabled, new MACs are no longer auto-registered; already-registered Workers are unaffected.

### Worker Lifecycle Closed Loop (Two-Step Creation and Per-Disk Management)

`POST /workers` registers identity only (hostname + MAC binding); `POST /workers/{worker_id}/luns/disk` then creates the system disk — assembling the IQN, selecting a disk Agent by `role.disk` capability, creating a blank disk or cloning from a golden image (btrfs or ZFS ≥ 2.2 reflink, seconds), writing the ledger and the `dnsmasq` binding, and reloading via HUP. System disks can be removed individually: `DELETE /workers/{worker_id}/luns/disk/{os}` deletes a single system disk target, with `delete_file` deciding whether to also delete the backing `.img` file (keeping the file allows re-attaching later) and `ignore_missing_target` tolerating a target that is already gone on the Agent side; `DELETE /workers/{worker_id}` cleans up all system disks when decommissioning a Worker.

### Multi-OS per Worker (disks Array Model)

A single Worker can mount multiple system disks, at most one per OS (duplicates return 409); `PUT /workers/{worker_id}/default-os` sets the default boot OS (`default_os`), menu default item (`menu_default`), and menu timeout (`menu_timeout`), with the derivation chain `default_os > boot.menu_default > reboot`. Switching the default OS never requires touching the machine.

### MAC Binding Update (Online Identity Change)

`PUT /workers/{worker_id}/mac` modifies a Worker's MAC binding (hostname unchanged): the new MAC is validated for format and occupancy (409 if already bound to another hostname), `dhcp-hosts.conf` is truncated in place to keep the file inode stable and then reloaded via HUP, visible immediately. The audit record `worker.mac.update` (with `old_mac` / `new_mac` / `changed` / `client`) doubles as the MAC change history and is queryable via `GET /operations`; when the new MAC equals the old one it returns `changed=false` without reloading. The WebUI Worker details page provides the edit entry in the Identity card.

### Bulk Deployment

`POST /workers/luns/disk/batch` creates system disks for multiple Workers at once: each entry in the request specifies its storage node; consistent with single-disk semantics, at most one disk per `os` and existing disks are skipped (not counted as failures); entries execute independently and a single failure does not block the rest, returning `succeeded` / `skipped` / `failed` summaries. Successfully created Workers get `default_os` set to the bulk OS automatically, so bulk provisioning boots straight into the system. `POST /workers/delete/batch` deletes Workers in bulk: entries execute independently, successful ones save the ledger together and trigger a single dnsmasq reload (better than reloading per deletion). The WebUI Workers page offers bulk-create / bulk-delete modes: row checkboxes (Shift-click range selection), a left parameter sidebar, and a right node sidebar (drag-and-drop assignment to a single node, round-robin participation, takeover of selected Workers).

### Per-Worker Boot-Variable Injection

While preserving the iPXE static menu interaction, the `/boot-vars` endpoint queries the inventory by MAC/hostname and dynamically returns variables such as `base-nqn`, `storager-ip`, `iscsi-sep`, `menu-default`, and `menu-timeout`; `iscsi-sep` is the iSCSI root **separator** (the field between `${storager-ip}` and `${base-iqn}`), generated per the backend type of the Agent hosting the system disk (stgt `:::1:` / LIO `::::`), while installer root-path assembly (`iscsi:${storager-ip}${iscsi-sep}${base-iqn}:${hostname}.<os>`) stays static in `menu.ipxe` — only the differing separator is projected by the backend. When no default boot is configured it returns a `reboot` short-timeout loop. `boot.ipxe.cfg` fetches the variables at the end and recomputes the `iscsi-sep` fallback behind an `isset` guard (so an injected LIO format is never overwritten).

### Agent Direct Management and Online Editing

- **Register / probe / edit**: `POST /agents/probe` performs the two-step probe (`/healthz` + `/capabilities`, auto-deriving `role` / `tags` / `storager_ip`, preview only, no file writes); `POST /agents` registers an Agent (duplicate id returns 409); `PUT /agents/{agent_id}` edits an Agent online (id immutable, empty token keeps the current value). With `enabled=false` an Agent is deactivated and no longer participates in disk creation / mount scheduling or health probing.
- **LUN direct management**: `GET/POST/DELETE /agents/{id}/luns` and `POST /agents/{id}/luns/scan` directly manage targets on iSCSI storage nodes (list LUNs / create disk / create CD / delete / scan the image directory to rebuild), independent of the Worker ledger. Combined with the `role.disk / role.cd` capability model, operations unsupported by a backend are rejected/greyed out on both the API and WebUI sides (e.g., LIO does not support ISO optical drives).
- **Master image inventory**: `GET /masters` aggregates the golden-image list from all enabled disk-role Agents (a background daemon thread on each Agent scans the image directory every 30 seconds, recognizing `_tpl_` markers and caching; a single failing Agent does not block the rest). The WebUI selects masters via a dropdown when cloning — no manual filename entry.

### Distributed Scheduling Model

The Control Plane only issues HTTP requests; the API Agent on each iSCSI Server receives them and operates the local iSCSI server. Adding/removing a Worker has been converged from manual configuration changes into stable contracts like `POST /workers`, `POST /workers/luns/disk/batch` and `DELETE /workers/{worker_id}`; disk creation filters candidate storage nodes by `role.disk` capability and `enabled` status.

### Heterogeneous Backend Design

Both stgt and LIO backends are integrated into the Agent, and the LIO server is containerized. Backend differences (including role capabilities) are encapsulated inside the Agent and invisible to the Control Plane. Each storage node treats the files in its image directory as the **single source of truth** — at startup it automatically scans the directory and rebuilds the iSCSI configuration, curing the volatility of stgt configurations.

### Storage Performance

Cloning from a golden image to a work disk completes in seconds via file-level reflink (FICLONE) on both btrfs and ZFS (OpenZFS ≥ 2.2, with the master and the clone in the same dataset), with measured data blocks shared at zero additional disk footprint. Scenarios without reflink — ZFS older than 2.2, cross-dataset, or filesystems like xfs/ext4 — automatically fall back to a full copy (clone time grows linearly with the master image size). The Agent reports `fs_type` (storage-directory filesystem) via `/capabilities` for UI display.

## Web Management UI

A minimalist black-and-white industrial-style SPA built with React + Vite (Chinese/English), integrating the full management capability of the Control Plane.

- **Dashboard**: Overview of Worker / Agent cluster status, summary of recent operation logs.
- **Workers management**: List view, filtering, two-step creation (register identity → create system disk: blank / golden-image clone, five OS choices: Windows / Ubuntu / Debian / CentOS / ESXi), bulk-create / bulk-delete modes (row checkboxes + Shift-click range selection, left parameter sidebar, right node sidebar with drag-and-drop / round-robin / takeover), multi-disk display, toolbar auto-register toggle.
- **Worker details**: Multi-disk cards (each disk independently deletable, with options to also delete the `.img` file and ignore missing targets), live status probes (dnsmasq binding, disk/cd target existence), online MAC editing in the Identity card, default-boot configuration form (`default_os` / `menu_default` / `menu_timeout`), boot-variable projection (code-block display of /boot-vars), safe deletion (double-confirmation with optional removal of the `.img` disk file).
- **Agents monitoring & direct management**: Responsive grid card layout showing backend type, capability (disk/cd roles), health status, and filesystem type, with a live-probe toggle; a "+ Add Agent" two-step probe registration (auto-derived role / tags / data-plane address, editable in the preview area, read-only capability tags), and an "Edit" button per card (overlay dialog, empty token keeps the current value, deactivation checkbox); clicking a card opens the Agent LUN management page for creating disks (master dropdown), creating CDs (greyed out with a hint per role), deleting, and scanning the directory to rebuild targets.
- **Operation logs**: Audit stream with incremental loading, timestamp + operation type + status flag + associated Worker (including identity-change history such as `worker.mac.update`).
- **Tech stack**: React 18 + React Router 6 (HashRouter) + pure CSS-variable-driven theming, zero third-party UI library dependencies.
- **Deployment**: Built by Vite as pure static files and served uniformly by the nginx container; API proxying is forwarded to the Control Plane through nginx, requiring no additional runtime.

## File Browser

Integrated into the same nginx container. An njs script provides a JSON directory-listing API, exposing iPXE boot files (ISO, kernel, initrd) under the `public/` directory.

- The file download endpoint `/file/` is designed specifically for iPXE `chain` / `initrd` commands; 404 responses are plain text and never return an HTML page.
- The Web UI and the file browser share the same nginx container (port :4838), with no extra process overhead.
