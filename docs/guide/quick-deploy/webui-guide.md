# WebUI User Guide

> **Document scope: WebUI · quick start.**
> Environment setup (Controller + storage nodes) is covered in *Environment Setup*; this document introduces the WebUI pages and the core workflow: **device intake → binding → clone → go live**.
> Every page action is equivalent to a Control Plane API call (API-first design: the WebUI is just one client of the API).

## Access & Auth

- **Entry**: open `http://<Controller IP>:4838` (WebUI port) in a browser.
- **Token**: if `IPXE_CP_TOKEN` was set during deployment, enter the matching Bearer Token in the top bar (builds with `VITE_CP_TOKEN` injected are pre-authenticated).
- **Language**: use the「中 / EN」switch in the top-right corner; display-only, does not affect operations.

The top navigation has five pages: **Dashboard / Workers / Devices / Agents / Operations**.

## Pages

### Dashboard (`/`)

- Stat cards: total Workers, Agents healthy/total.
- Recent operations: the latest 10 audit entries; "View all →" jumps to the Operations page.

### Workers (`/workers`)

Worker list (`worker_id` is the hostname, 1:1):

- Columns: worker_id, status, bound device MAC, readiness (`ready` = bound & system disk ready / `partial` = bound or has a disk / `idle` = neither), Agent, created time.
- Actions: **Create** (single; can include a MAC to bind immediately), **Batch create** (count + name prefix, e.g. `worker-` yields `worker-01`…), view details / delete per row.
- Click a row to open the Worker detail page.
- The "Page guide" button on the toolbar's right explains the top action buttons, filter, list columns and row interactions in a popover.

### Devices (`/devices`)

Device ledger page (the device entity of the three-entity model; the binding relationship is authoritative on the device side):

- **Toolbar**:
  - Auto-register switch: whether unknown-MAC devices reporting fingerprints are auto-admitted into the pool (on = report & join pool awaiting binding; off = report only, not pooled).
  - `+ Register device`: manually enter a MAC (+ optional UUID / vendor / model / serial) into the pool.
  - `Register to Pool`: bulk-paste a MAC manifest to admit devices into the pool (each line independent, duplicates skipped; hovering shows "No binding involved" — this action creates no Worker binding; bindings are made via the "Bind wizard").
  - `Bind wizard`: device ↔ Worker binding (see core workflow below).
  - Multi-select unbind: bulk-unbind selected devices (devices return to the pool; system disks stay on the Worker).
- **List**: sorted by intake time (`first_seen`); a copy button sits beside each MAC; status (`pooled` / `bound` / `revoked`), bound Worker, fingerprint summary, source (`ipxe` auto-intake / `manual`), first-reported time.
- **Expanded row**: full fingerprint (vendor/model/serial/CPU/memory etc.), UUID, last report, **binding history** (historical bind/unbind events, newest first; rebinds show `old worker → new worker`).
- The toolbar "Page guide" button explains each zone of the page in a popover.

### Worker Detail (`/workers/:id`)

- **System disks**: create a system disk (step 1: choose OS; step 2: clone type `Master` or `Empty`, master image name from the auto-scanned storage-node dropdown, size), disk list (IQN / file name / source / status), delete.
- **Default boot config**: `default_os` (only disks mounted to this Worker are selectable) → derivation chain `default_os > boot.menu_default > reboot`; if unset the machine loops rebooting until configured.
- Unbind / delete and other management actions.

### Agents (`/agents`)

Storage node (Agent + iSCSI backend) list: health (`live` / abnormal), role capabilities (disk / cd), tags; **+ Add Agent** (two-step probe registration: enter Agent ID / API URL / Token → probe auto-fetches parameters → confirm the data-plane address → add; written to `agents.yml`), per-row edit (base_url / token / role / enabled), disable; click through to view that node's LUN list (`/agents/:id`).

- The "Page guide" button in the toolbar explains the toolbar, the Agent card and row interactions in a popover.

### Operations (`/operations`)

Audit log (incremental view over `state/operations.jsonl`): all management operations newest-first, with opcode, status, and parameter details; used to trace binding, disk creation, registration, etc.

## Core Workflow (Quick Go-Live)

Using "new machine → diskless Worker" as the example:

### 1. Device Intake

- **Auto intake**: with the auto-register switch ON, powering the machine on (PXE boot) pools it automatically — no manual registration.
- **Manual intake**: Devices page "Register device" / "Register to Pool" (used when auto-register is OFF).

### 2. Bind Worker (Bind Wizard)

Devices page → "Bind wizard" → **Sequential allocation** mode (default):

1. Check pooled, unbound devices in the left column (sorted by intake time; search / select-all supported).
2. Check available Workers in the right column (allocated in check order; if Workers run short, fill in a prefix to auto-create the difference).
3. Confirm the summary bar "N devices → N Workers" → preview the pairing table → optionally export TSV for verification → confirm once more to execute.

> Switch to **Manifest pairing** mode if preferred: paste `mac, worker_id` lines (fingerprint match columns are optional declared values).

After binding the device status becomes `bound`, and its next PXE boot follows the Worker configuration.

### 3. Clone a System Disk

Workers page → open the Worker → "Create system disk":

| Field | Value |
|---|---|
| OS | the master's OS (e.g. `Windows` / `Debian`) |
| Clone type (Type) | `Master` (clone from master image); `Empty` (blank disk, install later) |
| Master image | select `_tpl_xxx.img` from the dropdown (auto-scanned from storage nodes) |

Creation is instant (reflink copy-on-write); the iSCSI Target and IQN are created automatically — no shell needed.

### 4. Set Default Boot

Worker detail page → "Default boot config" → choose the cloned disk as the default OS → save. The next boot goes straight into the OS, no iPXE menu interaction needed.

### 5. Verify

Reboot the Worker: iPXE → iSCSI login → OS boot logo → desktop/login. Confirm the disk state on the Workers page (IQN / source `master: _tpl_xxx.img`).

## Troubleshooting

| Problem | Resolution |
|---|---|
| 401 / invalid token | Check `webui/app/.env` `VITE_CP_TOKEN` matches `control_plane/control_plane.env` `IPXE_CP_TOKEN` (VITE_ variables are injected at build time; rebuild after changing) |
| Machine powered on but no new device in the pool | ① Is the auto-register switch ON? ② Check the Operations page for `device.report` entries (when the switch is OFF, reports are recorded without pooling) |
| No devices in the wizard's left column | Devices must be pooled (`pooled`) and unbound first; bound devices are excluded from allocation |
| No master in the clone dropdown | Master files must be named with a `_tpl_` prefix (e.g. `_tpl_windows_25h2.img`) and uploaded to the storage node's image directory |
| Worker stuck at the iPXE menu | Default boot is unset: configure "Default OS" in the Worker detail page, or pick the system entry manually in the menu |
