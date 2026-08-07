# Control Plane API Reference

This document describes the HTTP endpoints currently implemented by the Control Plane, including request parameters, response structures, and directly executable `curl` commands for testing.

> **API-first design**: All Control Plane capabilities are exposed through the REST API as the primary interface. The Web administration interface (WebUI) itself is just one client of this API, equal to any third-party system or automation script. The guiding principle: **Everything faces the Control Plane**. Third-party integrations always call the Control Plane API and never bypass it to operate directly on an Agent or the data plane.

The Control Plane is a persistent HTTP service running on the Controller node, responsible for:

- Adding Workers
- Removing Workers
- Querying Worker inventory
- Querying Agent status
- Maintaining `dnsmasq/dhcp-hosts.conf`
- Calling Agents to create or delete iSCSI LUNs

It does **not** generate iPXE menus, serve static files, or directly operate `tgtadm`/`targetcli`.

---

## 1. General Information

### 1.1 Base URL

Local example:

```text
http://localhost:4839
```

Replace with the actual address if you expose it on a different port or domain.

### 1.2 Environment File

The container reads environment variables through the Compose file:

```yaml
env_file:
  - ./control_plane/control_plane.env
```

The Control Plane code does **not** parse a `.env` file directly; it reads container environment variables via `os.getenv(...)`.

### 1.3 Authentication

If the environment variable `IPXE_CP_TOKEN` is empty, the Control Plane does **not** require authentication.  
If `IPXE_CP_TOKEN` is set, **all** endpoints except `GET /healthz` must include:

```http
Authorization: Bearer <IPXE_CP_TOKEN>
```

Example:

```bash
export BASE_URL=http://localhost:4839
export TOKEN=replace-me
```

curl with authentication:

```bash
curl -s "$BASE_URL/workers" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 2. Files Are the Source of Truth

The current Control Plane state files are divided as follows:

| File | Meaning |
|---|---|
| `config/agents.yml` | Agent node inventory and scheduling roles |
| `state/workers.yml` | Worker storage inventory |
| `dnsmasq/dhcp-hosts.conf` | Single source of truth for `MAC -> hostname` bindings |
| `state/operations.jsonl` | Control Plane operation audit trail |

Notes:

- `workers.yml` does **not** store MAC addresses.
- In the Compose file, mount the entire `dnsmasq` directory into the container, not just the single `dhcp-hosts.conf` file. The Control Plane performs an atomic replace using a temporary file when writing.
- `dnsmasq/dhcp-hosts.conf` contains one binding per line, with a fixed format:

```text
00:0c:29:b9:8b:2d,worker-01
```

---

## 3. Endpoint Overview

| Method | Path | Description |
|---|---|---|
| `GET` | `/healthz` | Health check |
| `GET` | `/boot-vars` | Dynamic iPXE boot variable injection, no auth required |
| `GET` | `/agents` | List Agents and their capabilities |
| `POST` | `/agents` | Register a new Agent (writes agents.yml; 409 if id exists) |
| `POST` | `/agents/probe` | Probe an Agent and auto-derive registration parameters (preview, no file writes) |
| `PUT` | `/agents/{agent_id}` | Update an Agent’s configuration (id cannot be changed; leave token empty to keep the current value) |
| `GET` | `/agents/{agent_id}/luns` | List iSCSI targets/LUNs on a given Agent |
| `GET` | `/masters` | Aggregate master image inventory from all storage nodes (for clone selection) |
| `POST` | `/agents/{agent_id}/luns/disk` | Create a disk LUN on a given Agent (master clone / empty disk) |
| `POST` | `/agents/{agent_id}/luns/cd` | Create a CD (ISO virtual drive) LUN on a given Agent |
| `DELETE` | `/agents/{agent_id}/luns` | Delete a LUN/target on a given Agent |
| `POST` | `/agents/{agent_id}/luns/scan` | Trigger an Agent to scan its image directory and rebuild targets |
| `POST` | `/workers` | Register a Worker identity (hostname + MAC binding) |
| `POST` | `/workers/{worker_id}/luns/disk` | Create a system disk LUN for a given Worker |
| `POST` | `/workers/luns/disk/batch` | Batch create system disks for multiple Workers (each specifies a storage node) |
| `DELETE` | `/workers/{worker_id}/luns/disk/{os}` | Delete a single system disk of a Worker (with option to keep/delete .img file) |
| `PUT` | `/workers/{worker_id}/default-os` | Set the Worker’s default boot configuration (OS / menu item / timeout) |
| `GET` | `/workers` | List Workers |
| `GET` | `/workers/{worker_id}` | Query a single Worker |
| `GET` | `/workers/{worker_id}/status` | Query Worker inventory and real-time status |
| `DELETE` | `/workers/{worker_id}` | Delete a Worker |
| `POST` | `/workers/delete/batch` | Batch delete Workers (each item processed independently, with success/failure summary) |
| `GET` | `/operations` | Read operation audit log |

---

## 4. GET /healthz

### Description

Health check endpoint. Does not change any state and requires no authentication.

### curl

```bash
curl -s "$BASE_URL/healthz"
```

### Successful Response

```json
{"status":"ok"}
```

---

## 5. GET /boot-vars

### Description

Provides per-worker boot variables for iPXE boot scripts. This endpoint does not require authentication and only exposes variables needed for booting within a controlled network.

> **Note**: This endpoint has a write side effect — when the request comes from an unbound new MAC, it **automatically registers** that Worker (see “Auto-Registration” below). In all other cases it is read-only.

The Control Plane looks up the request by `mac` or `hostname` against:

1. `dnsmasq/dhcp-hosts.conf`
2. `state/workers.yml`
3. `config/agents.yml`

Then returns the corresponding iSCSI server, default menu item, and menu timeout for that Worker.

By default, it returns an iPXE script snippet for maximum compatibility, which can be executed directly by iPXE’s `chain`. Add `format=json` to receive JSON (useful for manual debugging).

### Field Origins

The response of `/boot-vars` is a projection of the inventory:

| Response Field | Origin |
|---|---|
| `base_iqn` | The IQN of the Worker’s default boot disk (the disk for `default_os`; if not set, the first disk) with the last colon-and-following part stripped. **Not returned** if the Worker has no system disk (iPXE falls back to the static default in `boot.ipxe.cfg`). |
| `iscsi_server` | The `iscsi_server` of the Agent that hosts the default boot disk (same disk selection rule as above). Not returned when there is no system disk. |
| `iscsi_sep` | The iSCSI root **separator** (the part between `${iscsi-server}` and `${base-iqn}`). The root-path assembly is done on the iPXE side. **Generated according to the Agent backend type**: `:::1:` for stgt backends (lun placeholder 1), `::::` for LIO backends (empty placeholder). The backend type is determined first from the Agent’s `tags` in `agents.yml` (the presence of `lio`/`stgt`), then by querying the Agent’s `/capabilities` `backend` field, and finally defaulting to stgt format if the query fails. Not returned when there is no system disk. |
| `menu_default` | Derived chain: `workers.yml` `default_os` (set separately after disk creation) > `boot.menu_default` (explicit configuration) > `reboot` (loop reboot waiting when not configured) |
| `menu_timeout` | When a default boot is configured: `boot.menu_timeout` > `IPXE_CP_BOOT_MENU_TIMEOUT` (default 5000). When in `reboot` loop: always uses `IPXE_CP_AUTO_BOOT_TIMEOUT` (default 1). Units are milliseconds. |

Worker lookup rules (**hostname takes precedence**):

```text
hostname -> workers.yml (by hostname or worker_id)
hostname miss or not provided -> mac -> dnsmasq/dhcp-hosts.conf -> hostname -> workers.yml
neither matched and mac provided -> auto-registration (see below)
```

### Default Boot Item Rules

The default boot item is derived by `/boot-vars` in the following order:

```text
default_os (set separately after disk creation, see 7.3) -> boot.menu_default (explicit config) -> reboot (not configured)
```

- Recommended approach: after creating a system disk, call `PUT /workers/{worker_id}/default-os` to set the default boot OS:
  ```text
  os=ubuntu  -> menu_default=ubuntu
  os=debian  -> menu_default=debian
  os=windows -> menu_default=windows
  ```
- Alternatively, you can leave `default_os` unset and use `boot.menu_default` to specify a default item on the iPXE menu (e.g., `menu-install` during installation, or `exit`).
- When neither is configured, `menu_default` returns `reboot` (a short-timeout reboot loop waiting for the admin to create a disk / set a default OS; `exit` is only used when explicitly configured).

### Auto-Registration (Zero-touch Provisioning)

When a new Worker boots without a hostname, iPXE requests `/boot-vars` with its `mac`. If the MAC is not yet bound, the Control Plane automatically completes the registration:

1. Generates a hostname sequentially by scanning the inventory and dhcp bindings for the maximum `worker-N` number and incrementing it (format `worker-%02d`, starting from `worker-01`).
2. Writes to `workers.yml` (`state=registered`, no system disks) and binds the MAC in `dnsmasq/dhcp-hosts.conf` (MAC -> hostname), then triggers a dnsmasq reload.
3. Returns `menu-default=reboot` with a short timeout, causing the machine to immediately reboot.
4. On the next boot, dnsmasq provides the hostname, and subsequent requests identify the Worker by hostname. It will keep returning `reboot` loop reboots until the admin creates a system disk and sets `default_os`.
5. Once configured, the next reboot will boot into the corresponding OS via `default_os`.

Configuration (environment variables):

| Variable | Default | Description |
|---|---:|---|
| `IPXE_CP_AUTO_REGISTER` | `true` | When set to `false`, new MACs are no longer automatically registered (returns an empty script). |
| `IPXE_CP_AUTO_BOOT_TIMEOUT` | `1` | Menu timeout in milliseconds during the reboot loop. |

The entire auto-registration process is logged as operations (`auto_register`). On failure, the inventory is rolled back and an empty script is returned, so the next request will retry without affecting the iPXE boot process.

### Query Parameters

| Parameter | Required | Default | Description |
|---|---:|---|---|
| `mac` | No | None | MAC address. The backend normalizes it by stripping `:` / `-` / `.`. Both colon-separated (`00:0c:29:b9:8b:2d`) and `mac:hexraw` (`000c29b98b2d`) formats are supported. |
| `hostname` | No | None | Hostname, e.g., `worker-01`. |
| `format` | No | `ipxe` | `ipxe` or `json`. |

It is recommended to pass at least one of `mac` or `hostname`. From iPXE, it is best to pass both:

```text
/boot-vars?mac=${mac}&hostname=${hostname}
```

> **Note**: Although `${mac:hexraw}` is technically equivalent to `${mac}` (both are normalized), some real iPXE firmware expands the `hexraw` modifier incorrectly (possibly empty). In practice, you must use colon-separated `${mac}` — do not change it back to `hexraw`.

### curl (iPXE Format)

```bash
curl -s "$BASE_URL/boot-vars?mac=000c29b98b2d&hostname=worker-01"
```

Example success response:

```ipxe
#!ipxe
# boot vars for worker-01
set base-iqn iqn.2026-07.com.controller
set iscsi-server 192.168.80.3
set iscsi-sep :::1:
set menu-default ubuntu
set menu-timeout 5000
```

Registered but no default boot configured (no system disk / no `default_os` / no explicit `boot.menu_default`):

```ipxe
#!ipxe
# boot vars for worker-01
set menu-default reboot
set menu-timeout 1
```

New MAC (triggered auto-registration) or completely unrecognized, and if auto-registration fails or is disabled, returns an empty script:

```ipxe
#!ipxe
# no per-worker boot vars found
```

### curl (JSON Format)

```bash
curl -s "$BASE_URL/boot-vars?mac=000c29b98b2d&hostname=worker-01&format=json"
```

Example success response:

```json
{
  "base_iqn": "iqn.2026-07.com.controller",
  "iscsi_server": "192.168.80.3",
  "iscsi_sep": ":::1:",
  "menu_default": "ubuntu",
  "menu_timeout": 5000
}
```

Registered but no default boot configured:

```json
{
  "menu_default": "reboot",
  "menu_timeout": 1
}
```

Unrecognized and no auto-registration triggered:

```json
{}
```

### iPXE Integration

At the end of `tftp/boot.ipxe.cfg`, this endpoint is fetched:

```ipxe
chain --autofree http://${controller_ip}:4839/boot-vars?mac=${mac}&hostname=${hostname} || goto vars-done
# If the chain fails (endpoint unreachable), it silently continues with the static defaults at the top of this file.
# On success, the returned base-iqn / iscsi-server may override the static defaults; derived variables must be re-built.
# isset guard: do not override iscsi-sep if /boot-vars already provided a backend-specific separator (stgt `:::1:` / LIO `::::`)
isset ${iscsi-sep} || set iscsi-sep :::1:
isset ${hostname} && set initiator-iqn ${base-iqn}:${hostname} || set initiator-iqn ${base-iqn}:${mac}

:vars-done
```

In `menu.ipxe`, each OS and installation entry uses `${iscsi-sep}` in the root-path (e.g., `set root-path iscsi:${iscsi-server}${iscsi-sep}${base-iqn}:${hostname}.windows`). The `iscsi:` protocol prefix and assembly structure remain static; only the separator is projected from the backend.

### Agent Data-Plane Address

`/boot-vars` returns the **data-plane address** that Workers use to connect to iSCSI, not the Agent’s HTTP API address. It is recommended to explicitly configure it in `config/agents.yml`:

```yaml
agents:
  storage-lio-01:
    base_url: http://host.docker.internal:4840
    iscsi_server: 192.168.80.3
```

If `iscsi_server` is not configured, the Control Plane falls back to the host portion of `base_url`. However, when `base_url` is `host.docker.internal`, this value is not suitable for physical Workers.

---

## 6. GET /agents

### Description

Lists Agents configured in `config/agents.yml`. By default, it also probes each Agent’s `/healthz` and `/capabilities` in real time.

### Query Parameters

| Parameter | Required | Default | Description |
|---|---:|---|---|
| `live` | No | `true` | Whether to probe Agent status and capabilities in real time. |

### curl

Live probe:

```bash
curl -s "$BASE_URL/agents?live=true" \
  -H "Authorization: Bearer $TOKEN"
```

Configuration only, no probing:

```bash
curl -s "$BASE_URL/agents?live=false" \
  -H "Authorization: Bearer $TOKEN"
```

### Example Success Response

```json
[
  {
    "id": "storage-lio-01",
    "base_url": "http://10.0.0.11:4840",
    "role": {
      "disk": true,
      "cd": false
    },
    "enabled": true,
    "tags": [
      "storage",
      "lio"
    ],
    "health": "ok",
    "capabilities": {
      "backend": "lio",
      "fs_type": "btrfs",
      "cd": false,
      "persistent": "saveconfig (auto-load on start)",
      "base_iqn": "iqn.2026-07.com.controller",
      "clone": "reflink (FICLONE) -> shutil.copy fallback",
      "empty_disk": "truncate (sparse)"
    }
  }
]
```

---

## 6.1 POST /agents

### Description

Registers a new Agent: writes to `config/agents.yml` and takes effect immediately (the Agent will be included in disk creation / mount scheduling). Duplicate `id` registration returns `409`.

**Recommended flow**: first fill in the API address in the WebUI (or use `POST /agents/probe`, see 6.2) and probe to automatically obtain role, tags, data-plane address, etc. After confirming, call this endpoint to complete registration. Direct full-parameter submission is also supported.

### Request Body Fields

| Field | Required | Description |
|---|---:|---|
| `id` | Yes | Agent identifier. Automatically lowercased. Same character rules as worker id (letters, digits, dots, underscores, hyphens). |
| `base_url` | Yes | Agent Control Plane API address. Must start with `http://` or `https://`. Trailing `/` is removed automatically. |
| `token` | No | Agent authentication token. Supports `${ENV}` environment variable placeholder (expanded when the Control Plane reads it). Leave empty for Agents without authentication. |
| `iscsi_server` | No | iSCSI data-plane address (business network IP). Falls back to the hostname of `base_url` if omitted. |
| `role` | No | Roles: `disk` = can create system disks (storage node), `cd` = can mount ISOs (optical drive node). Default `{disk: false, cd: false}`. |
| `tags` | No | Free-form tag array (e.g., `storage`/`lio`/`stgt`), for display. The `lio`/`stgt` tags also participate in `/boot-vars` separator derivation. |
| `enabled` | No | Whether the Agent is enabled. Default `true`. |

### curl

```bash
curl -s -X POST "$BASE_URL/agents" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "storage-stgt-02",
    "base_url": "http://host.docker.internal:4840",
    "token": "${STORAGE_STGT_02_TOKEN}",
    "iscsi_server": "192.168.1.6",
    "role": {"disk": true, "cd": false},
    "tags": ["storage", "stgt"],
    "enabled": true
  }'
```

### Success Response (201)

```json
{
  "id": "storage-stgt-02",
  "base_url": "http://host.docker.internal:4840",
  "iscsi_server": "192.168.1.6",
  "role": {"disk": true, "cd": false},
  "enabled": true,
  "tags": ["storage", "stgt"]
}
```

### Error Responses

| Status Code | Scenario |
|---|---|
| `400` | Invalid `id` format / `base_url` does not start with http(s) |
| `409` | Agent `id` already exists |

---

## 6.2 POST /agents/probe

### Description

Probes an Agent and auto-derives registration parameters (**read-only preview, no files are written**): calls the Agent’s `/healthz` (no authentication) and `/capabilities` (with Bearer token), and derives:

| Parameter | Derivation Rule |
|---|---|
| `role.disk` | Always `true` (Agent is an iSCSI storage node) |
| `role.cd` | From `capabilities.cd` |
| `tags` | `["storage", backend]` (where `backend` is `lio` or `stgt`; also used for `/boot-vars` separator derivation) |
| `iscsi_server` | Falls back to `base_url` hostname if not provided |

### Request Body Fields

| Field | Required | Description |
|---|---:|---|
| `base_url` | Yes | Agent Control Plane API address. Must start with `http://` or `https://`. |
| `token` | No | Agent authentication token. Required if the Agent has `IPXE_AGENT_TOKEN` configured (the Agent does not echo its own token, so it cannot be retrieved automatically). |
| `agent_id` | No | In edit scenarios: when `token` is left empty, the probe will use the token already stored in the registry for this Agent. Ignored for unknown ids. |

### curl

```bash
curl -s -X POST "$BASE_URL/agents/probe" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"base_url": "http://host.docker.internal:4840", "token": "${STORAGE_STGT_02_TOKEN}"}'
```

### Success Response

```json
{
  "base_url": "http://host.docker.internal:4840",
  "role": {"disk": true, "cd": false},
  "tags": ["storage", "stgt"],
  "iscsi_server": "host.docker.internal",
  "enabled": true,
  "backend": "stgt",
  "fs_type": "btrfs",
  "base_iqn": "iqn.2026-07.com.controller",
  "clone": "reflink (FICLONE) -> shutil.copy fallback",
  "empty_disk": "truncate (sparse)",
  "persistent": "auto-scan on startup"
}
```

### Error Responses

| Status Code | Scenario |
|---|---|
| `400` | `base_url` does not start with http(s) |
| `502` | Agent unreachable (`/healthz` failed) or `/capabilities` call failed (e.g., wrong token) |

---

## 6.3 PUT /agents/{agent_id}

### Description

Updates an existing Agent: overwrites the corresponding entry in `config/agents.yml` and takes effect immediately (disk creation / mount scheduling uses the new configuration). The `id` cannot be changed (taken from the path parameter). An empty string for `token` means **keep the current value** (the API never echoes the token, so the frontend cannot fill it back in).

Use cases: iSCSI server configuration changes — data-plane address migration, API address change, token rotation, disable/enable a node.

### Request Body Fields

| Field | Required | Description |
|---|---:|---|
| `base_url` | Yes | Agent Control Plane API address. Must start with `http://` or `https://`. Trailing `/` is removed automatically. |
| `token` | No | Empty string = keep the current value (do not overwrite). Pass a new value to rotate. Supports `${ENV}` placeholders. |
| `iscsi_server` | No | iSCSI data-plane address. Falls back to the hostname of `base_url` if omitted. |
| `role` | No | Roles: `disk` = can create system disks, `cd` = can mount ISOs. Default `{disk: false, cd: false}`. |
| `tags` | No | Free-form tag array. |
| `enabled` | No | Whether the Agent is enabled. `false` disables it (it will no longer participate in disk creation/mount scheduling or liveness probes). Default `true`. |

### curl

```bash
curl -s -X PUT "$BASE_URL/agents/storage-stgt-02" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "base_url": "http://host.docker.internal:4840",
    "token": "",
    "iscsi_server": "192.168.1.8",
    "role": {"disk": true, "cd": false},
    "tags": ["storage", "stgt"],
    "enabled": true
  }'
```

### Success Response (200)

```json
{
  "id": "storage-stgt-02",
  "base_url": "http://host.docker.internal:4840",
  "iscsi_server": "192.168.1.8",
  "role": {"disk": true, "cd": false},
  "enabled": true,
  "tags": ["storage", "stgt"]
}
```

### Error Responses

| Status Code | Scenario |
|---|---|
| `400` | `base_url` does not start with http(s) |
| `404` | Agent `id` not found |

> **Probing during edit**: In edit scenarios, it is recommended to first call `POST /agents/probe` (6.2) to verify the new address is reachable before saving. If `token` is left empty, pass the `agent_id` parameter; the backend will automatically use the token stored in the registry for that Agent.

---

## 7. POST /workers

### Description

Registers a Worker’s **identity**: hostname + MAC binding. **Storage and identity are separated** — this endpoint does not create any system disks. System disks must be created separately via `POST /workers/{worker_id}/luns/disk` (see 7.1). The Control Plane will:

1. Validate `worker_id`, `hostname`, `mac`
2. Write to `state/workers.yml` (`disks` as empty array, `state=registered`)
3. Write to `dnsmasq/dhcp-hosts.conf`
4. Send a HUP signal to the `ipxe-dnsmasq` container via Docker:

```bash
docker exec ipxe-dnsmasq killall -HUP dnsmasq
```

5. If `windows_iso` is specified, additionally call the Agent to create a CD target (installation optical drive, unrelated to system disks).

### Request Body Fields

| Field | Required | Description |
|---|---:|---|
| `worker_id` | Yes | Worker identifier. Automatically lowercased. Allowed characters: letters, digits, dots, underscores, hyphens. |
| `mac` | Yes | Worker NIC MAC address, e.g., `00:0c:29:b9:8b:2d`. |
| `hostname` | No | Hostname. Defaults to `worker_id` if not provided. |
| `arch` | No | Architecture. Defaults to `x86_64`. |
| `windows_iso` | No | Windows installation ISO filename. When provided, an installation CD target is created during registration. |
| `boot` | No | iPXE menu default item and timeout configuration. If omitted, `/boot-vars` derives them from the default boot OS and global defaults. Writes to the same ledger fields as the 7.3 `default-os` endpoint; later calls override earlier ones. |

### `boot` Fields

| Field | Required | Description |
|---|---:|---|
| `menu_default` | No | Default item on the iPXE main menu (auto-selected after the menu times out); valid values in the 7.3 table; case-insensitive, e.g., `ubuntu`, `debian`, `windows`, `exit`. |
| `menu_timeout` | No | iPXE menu timeout in milliseconds, e.g., `5000`; `0` means the menu waits indefinitely and never auto-selects. |

When `boot` is omitted:

- `menu_default` defaults to `default_os` (set separately after disk creation, see 7.3); if not set, defaults to `reboot` (loop reboot waiting for configuration, see section 5).
- `menu_timeout` defaults to `IPXE_CP_BOOT_MENU_TIMEOUT` (currently `5000`) when a default boot is configured; in the `reboot` loop it is fixed to `IPXE_CP_AUTO_BOOT_TIMEOUT` (currently `1` ms, see section 5).

Therefore, most Workers do not need to pass `boot`. For example:

```json
{
  "worker_id": "worker-01",
  "mac": "00:0c:29:b9:8b:2d"
}
```

After registration, the Worker has no system disk, so `/boot-vars` returns `menu-default reboot` with a 1 ms timeout — the Worker enters a fast reboot loop waiting for the admin to create a disk / set a default boot OS:

```ipxe
set menu-default reboot
set menu-timeout 1
```

After creating a system disk, call `PUT /workers/{worker_id}/default-os` (see 7.3) to set the default boot OS, and `menu-default` will switch to that OS’s menu item (e.g., `ubuntu`).

Only pass `boot` when you want to override the menu behavior:

```json
{
  "worker_id": "worker-01",
  "mac": "00:0c:29:b9:8b:2d",
  "boot": {
    "menu_default": "exit",
    "menu_timeout": 0
  }
}
```

During Windows installation, if you want to default to the installation menu:

```json
{
  "worker_id": "worker-win-build",
  "mac": "00:0c:29:b9:8b:11",
  "windows_iso": "Win11_24H2.iso",
  "boot": {
    "menu_default": "menu-install",
    "menu_timeout": 3000
  }
}
```

## 7.1 POST /workers/{worker_id}/luns/disk

### Description

Creates a system disk LUN for a given Worker. System disks are categorized by OS; a Worker can have multiple system disks for different OSes (at most one per OS). The Control Plane will:

1. Verify the Worker exists and does not already have a disk for that OS (returns `409` if it does).
2. Determine the corresponding OS for the disk: the request body `os` is required and determines the IQN suffix and filename.
3. Select a storage Agent (specified by `disk_agent` or auto-selected).
4. Assemble the IQN and backing filename (`base-iqn:worker-id.os`).
5. Call the Agent to create the disk target (master clone or empty disk).
6. Update the Worker’s `disks` inventory in `state/workers.yml` (append to array). On the first disk creation, `state` transitions from `registered` to `ready`.

This endpoint resides under the `/luns/` namespace to reserve space for future data disks (`/luns/data`). In a multi-OS scenario, the default boot OS is determined by the `os` parameter of `PUT /workers/{worker_id}/default-os`.

### Path Parameters

| Parameter | Required | Description |
|---|---:|---|
| `worker_id` | Yes | Worker identifier. |

### Request Body Fields

| Field | Required | Description |
|---|---:|---|
| `type` | Yes | `master` or `empty`. |
| `name` | Conditionally required | Required when `type=master`. The master image filename. |
| `size` | Conditionally required | Required when `type=empty`. The empty disk size, e.g., `40G`. |
| `os` | Yes | The OS this system disk corresponds to (determines the IQN suffix and filename). Allowed values: `windows`, `ubuntu`, `debian`, `centos`, `esxi` (menu.ipxe OS items). |
| `disk_agent` | No | Specify a storage Agent. If omitted, the Control Plane auto-selects one. |

### 7.1.1 Clone from Master

#### curl

```bash
curl -s -X POST "$BASE_URL/workers/worker-01/luns/disk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "master",
    "os": "ubuntu",
    "name": "_tpl_ubuntu_2204.img"
  }'
```

### 7.1.2 Create Empty Disk

#### curl

```bash
curl -s -X POST "$BASE_URL/workers/worker-00/luns/disk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "empty",
    "os": "ubuntu",
    "size": "40G"
  }'
```

### Example Success Response (master clone)

```json
{
  "hostname": "worker-01",
  "arch": "x86_64",
  "state": "ready",
  "disks": [
    {
      "agent": "storage-lio-01",
      "iqn": "iqn.2026-07.com.controller:worker-01.ubuntu",
      "filename": "worker-01.ubuntu.img",
      "backing": "/home/iscsi_img/worker-01.ubuntu.img",
      "os": "ubuntu",
      "source": {
        "type": "master",
        "name": "_tpl_ubuntu_2204.img"
      }
    }
  ],
  "cd": null,
  "worker_id": "worker-01",
  "mac": "00:0c:29:b9:8b:2d"
}
```

### Example Success Response (empty disk)

```json
{
  "hostname": "worker-00",
  "arch": "x86_64",
  "state": "ready",
  "disks": [
    {
      "agent": "storage-lio-01",
      "iqn": "iqn.2026-07.com.controller:worker-00.ubuntu",
      "filename": "worker-00.ubuntu.img",
      "backing": "/home/iscsi_img/worker-00.ubuntu.img",
      "os": "ubuntu",
      "source": {
        "type": "empty",
        "size": "40G"
      }
    }
  ],
  "cd": null,
  "worker_id": "worker-00",
  "mac": "00:0c:29:b9:8b:00"
}
```

### 7.1.3 Batch Create System Disks (POST /workers/luns/disk/batch)

Batch deployment scenario: apply the same disk parameters to multiple Workers, each using its pre-assigned storage node (`targets[].agent` is required — it is generated by the WebUI’s “take over selected Workers” or drag-and-drop assignment; there is no common automatic allocation).

Same as single-disk creation: `master` clones from a master image, `empty` creates a blank disk. At most one disk per `os` is allowed; if a Worker already has one it is **automatically skipped** (not considered a failure). **Successfully created Workers automatically set `default_os` to the OS of this batch** — batch deployment goes directly to the default boot without needing an extra `PUT /workers/{worker_id}/default-os` call (single-disk creation does NOT set this automatically). Each item is processed independently; a failure of one does not affect the others. Returns a summary of `succeeded` / `skipped` / `failed`.

#### Request Body Fields

| Field | Required | Description |
|---|---:|---|
| `type` | Yes | `master` or `empty`. |
| `os` | Yes | The OS for the system disk (same for all Workers in the batch; determines the IQN suffix and filename). |
| `name` | Conditionally required | Required when `type=master`. The master image filename. |
| `size` | Conditionally required | Required when `type=empty`. The empty disk size, e.g., `40G`. |
| `targets` | Yes | Array of `{worker_id, agent}`: the Worker identifier and its assigned storage node. |

#### curl

```bash
curl -s -X POST "$BASE_URL/workers/luns/disk/batch" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "master",
    "os": "ubuntu",
    "name": "_tpl_ubuntu_2204.img",
    "targets": [
      { "worker_id": "worker-01", "agent": "storage-lio-01" },
      { "worker_id": "worker-02", "agent": "storage-lio-01" },
      { "worker_id": "worker-03", "agent": "storage-stgt-01" }
    ]
  }'
```

#### Example Response

```json
{
  "succeeded": [
    { "worker_id": "worker-01", "agent": "storage-lio-01", "iqn": "iqn.2026-07.com.controller:worker-01.ubuntu" },
    { "worker_id": "worker-03", "agent": "storage-stgt-01", "iqn": "iqn.2026-07.com.controller:worker-03.ubuntu" }
  ],
  "skipped": [
    { "worker_id": "worker-02", "reason": "already has a ubuntu system disk" }
  ],
  "failed": [
    { "worker_id": "worker-04", "agent": "storage-lio-01", "error": "worker not found: worker-04" }
  ]
}
```

---

## 7.2 Windows Installation: Identity Registration + ISO + System Disk

Windows installation is a two-step process: first register the identity (optionally specifying the installation ISO), then create the system disk.

### 7.2.1 Identity Registration (with ISO)

```bash
curl -s -X POST "$BASE_URL/workers" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "worker_id": "worker-win-build",
    "mac": "00:0c:29:b9:8b:11",
    "windows_iso": "Win11_24H2.iso"
  }'
```

After registration, the response has `state=installing` (a CD target exists) and `disks` as an empty array.

### 7.2.2 Create System Disk

```bash
curl -s -X POST "$BASE_URL/workers/worker-win-build/luns/disk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "empty",
    "os": "windows",
    "size": "80G"
  }'
```

Response after creation:

```json
{
  "hostname": "worker-win-build",
  "arch": "x86_64",
  "state": "installing",
  "disks": [
    {
      "agent": "storage-lio-01",
      "iqn": "iqn.2026-07.com.controller:worker-win-build.windows",
      "filename": "worker-win-build.windows.img",
      "backing": "/home/iscsi_img/worker-win-build.windows.img",
      "os": "windows",
      "source": {
        "type": "empty",
        "size": "80G"
      }
    }
  ],
  "cd": {
    "agent": "controller-stgt",
    "iqn": "iqn.2026-07.com.controller:worker-win-build.windows.iso",
    "iso": "Win11_24H2.iso",
    "backing": "/home/iscsi_img/Win11_24H2.iso"
  },
  "worker_id": "worker-win-build",
  "mac": "00:0c:29:b9:8b:11"
}
```

After installation finishes, the CD target is cleaned up as part of the Worker deletion flow.

### Common Errors

| HTTP Status | Common Causes |
|---:|---|
| `400` | Parameter format error; `os` not in {windows/ubuntu/debian/centos/esxi}; `type=master` but `name` missing; `type=empty` but `size` missing |
| `401` | Missing or incorrect Token |
| `404` | Worker not found when creating a system disk |
| `409` | `worker_id` already exists; `hostname` already exists; MAC already bound; Worker already has a disk for that OS (duplicate `os`); IQN already exists on Agent; backing file already exists |
| `500` | dnsmasq reload failed; file write failure; other unexpected errors |
| `503` | Agent unreachable; docker.sock unavailable |

---

## 7.3 PUT /workers/{worker_id}/default-os

### Description

**What the “default boot OS” is for**: a Worker can have multiple system disks (at most one per OS, e.g., `ubuntu` + `windows`). On every boot, the iPXE menu auto-selects one item after its timeout — the default boot OS configured here decides which item is auto-selected, and also decides which disk’s connection info `/boot-vars` projects (`base_iqn` / `iscsi_server` come from the default boot disk, see section 5). Without it, the menu auto-selects `reboot` with a 1 ms timeout and loops rebooting until the admin finishes configuration — never silently booting into the wrong OS.

**Note**: `os` is not an arbitrary name for the disk; it is the ID of a `menu.ipxe` OS menu item (same enum as the `os` of disk creation in 7.1), one-to-one with an attached system disk.

The `/boot-vars` `menu_default` derivation chain:

```text
default_os (the `os` field of this endpoint, highest priority) -> boot.menu_default (the `menu_default` field of this endpoint) -> reboot (not configured, loop reboot waiting)
```

The three request body fields can be sent individually or in combination; at least one must be provided. Sending `null` (or an empty string) clears the corresponding item. This endpoint can be called repeatedly; later calls override earlier ones — they write the same ledger fields as the `boot` passed at registration (see 7.0).

Requirements:

- When setting `os`: The Worker must already have a system disk for that OS (created by `POST /workers/{worker_id}/luns/disk`), otherwise a `400` is returned listing the current system disks. In the multi-disk model, use `os` to precisely match the OS to boot by default.
- When setting `menu_default`: The value must be a valid item ID from the `menu.ipxe` main menu (strict validation to prevent an empty `choose --default` in iPXE).
- When setting `menu_timeout`: Non-negative integer; `0` means the menu waits indefinitely (never auto-selects, waits for a human keypress); clearing restores the default `IPXE_CP_BOOT_MENU_TIMEOUT` (currently `5000`).

### Path Parameters

| Parameter | Required | Description |
|---|---:|---|
| `worker_id` | Yes | Worker identifier. |

### Request Body Fields

| Field | Required | Description |
|---|---:|---|
| `os` | No | Default boot OS (a menu item ID, not a disk name) — only `windows` `ubuntu` `debian` `centos` `esxi` are allowed (same enum as disk creation in 7.1), case-insensitive (auto-lowercased), and must match a system disk already attached to this Worker. Pass `null` to clear. |
| `menu_default` | No | Default item on the iPXE main menu (auto-selected after the menu times out). See the valid values table below; case-insensitive (auto-lowercased). Pass `null` to clear. |
| `menu_timeout` | No | Menu timeout in milliseconds, non-negative integer; `0` means the menu waits indefinitely (never auto-selects, waits for a human keypress). Pass `null` to clear, restoring `IPXE_CP_BOOT_MENU_TIMEOUT` (currently `5000`). |

### Valid `menu_default` Values (menu.ipxe Main Menu Item IDs)

| Category | Valid Values |
|---|---|
| Operating Systems | `windows` `ubuntu` `debian` `centos` `esxi` |
| Tools / Installation | `menu-diag` `menu-install` |
| Advanced | `config` `shell` `reboot` `exit` |

### Example: Set Default OS

```bash
curl -s -X PUT "$BASE_URL/workers/worker-01/default-os" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "os": "ubuntu"
  }'
```

### Example: Set Menu Default Item and Timeout

```bash
curl -s -X PUT "$BASE_URL/workers/worker-win-build/default-os" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "menu_default": "menu-install",
    "menu_timeout": 3000
  }'
```

### Example: Clear Default OS

```bash
curl -s -X PUT "$BASE_URL/workers/worker-01/default-os" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "os": null
  }'
```

### Success Response

Returns the full Worker inventory, including the set fields like `default_os`, `boot.menu_default`, `boot.menu_timeout`.

### Common Errors

| HTTP Status | Common Causes |
|---:|---|
| `400` | None of the three fields provided; `os` does not match any attached system disk; `menu_default` not in the valid values table; `menu_timeout` negative |
| `401` | Missing or incorrect Token |
| `404` | Worker not found |
| `409` | Setting `os` when the Worker has no system disks |

---

## 7.4 DELETE /workers/{worker_id}/luns/disk/{os}

### Description

Deletes a single system disk of a given Worker (by OS name; `os` is case-insensitive). The Control Plane will:

1. Verify the Worker exists and has a disk for that OS (returns `404` if not).
2. Call the hosting Agent to delete the iSCSI target.
3. Remove the disk entry from the Worker’s `disks` array in `state/workers.yml`.
4. Cleanup linkage: if the deleted disk was the default boot OS (`default_os`), both `default_os` and any matching `boot.menu_default` are cleared (to prevent iPXE from booting to a deleted disk).
5. When the last disk is deleted, `state` reverts from `ready` to `registered` (waiting for a new disk to be created).

### Query Parameters

| Parameter | Default | Description |
|---|---:|---|
| `delete_file` | `false` | Whether to also delete the backing `.img` file. `false` only deletes the target (the .img is retained and can be re-attached). |
| `ignore_missing_target` | `false` | If `true`, ignores a `404 iqn not found` from the Agent and continues with the inventory cleanup. |

### Example: Delete System Disk, Keep .img

```bash
curl -s -X DELETE "$BASE_URL/workers/worker-01/luns/disk/ubuntu" \
  -H "Authorization: Bearer $TOKEN"
```

### Example: Delete System Disk and .img File

```bash
curl -s -X DELETE "$BASE_URL/workers/worker-01/luns/disk/ubuntu?delete_file=true" \
  -H "Authorization: Bearer $TOKEN"
```

### Success Response

Returns the full Worker inventory (with `disks` no longer containing the deleted system disk; if it was the default, `default_os`/`boot.menu_default` are cleared; if no disks remain, `state=registered`).

### Common Errors

| HTTP Status | Common Causes |
|---:|---|
| `400` | Invalid `os` |
| `401` | Missing or incorrect Token |
| `404` | Worker not found, or the Worker does not have a disk for that OS |

---

## 8. GET /workers

### Description

Lists the inventory of all current Workers. The `mac` field in the response is a real-time reverse lookup from `dnsmasq/dhcp-hosts.conf`.

### curl

```bash
curl -s "$BASE_URL/workers" \
  -H "Authorization: Bearer $TOKEN"
```

### Example Success Response

```json
[
  {
    "hostname": "worker-00",
    "arch": "x86_64",
    "state": "ready",
    "disks": [
      {
        "agent": "storage-lio-01",
        "iqn": "iqn.2026-07.com.controller:worker-00.ubuntu",
        "filename": "worker-00.ubuntu.img",
        "backing": "/home/iscsi_img/worker-00.ubuntu.img",
        "os": "ubuntu",
        "source": {
          "type": "empty",
          "size": "40G"
        }
      }
    ],
    "cd": null,
    "worker_id": "worker-00",
    "mac": "00:0c:29:b9:8b:00"
  }
]
```

---

## 9. GET /workers/{worker_id}

### Description

Queries the inventory record of a single Worker.

### Path Parameters

| Parameter | Required | Description |
|---|---:|---|
| `worker_id` | Yes | Worker identifier. |

### curl

```bash
curl -s "$BASE_URL/workers/worker-01" \
  -H "Authorization: Bearer $TOKEN"
```

### Success Response

The response structure is identical to the successful `POST /workers` result.

---

## 10. GET /workers/{worker_id}/status

### Description

Queries the Worker’s inventory information and performs real-time checks:

- Whether the hostname’s MAC exists in `dnsmasq/dhcp-hosts.conf`.
- Whether the corresponding disk target(s) exist on the Agent(s).
- Whether the corresponding CD target exists on the Agent.

### Path Parameters

| Parameter | Required | Description |
|---|---:|---|
| `worker_id` | Yes | Worker identifier. |

### curl

```bash
curl -s "$BASE_URL/workers/worker-01/status" \
  -H "Authorization: Bearer $TOKEN"
```

### Example Success Response

```json
{
  "worker": {
    "hostname": "worker-01",
    "arch": "x86_64",
    "state": "ready",
    "disks": [
      {
        "agent": "storage-lio-01",
        "iqn": "iqn.2026-07.com.controller:worker-01.ubuntu",
        "filename": "worker-01.ubuntu.img",
        "backing": "/home/iscsi_img/worker-01.ubuntu.img",
        "os": "ubuntu",
        "source": {
          "type": "master",
          "name": "_tpl_ubuntu_2204.img"
        }
      }
    ],
    "cd": null,
    "worker_id": "worker-01",
    "mac": "00:0c:29:b9:8b:2d"
  },
  "actual": {
    "dnsmasq": {
      "hostname": "worker-01",
      "mac": "00:0c:29:b9:8b:2d"
    },
    "disks": [
      {
        "os": "ubuntu",
        "exists": true,
        "target": {
          "iqn": "iqn.2026-07.com.controller:worker-01.ubuntu",
          "luns": [
            {
              "backing": "/home/iscsi_img/worker-01.ubuntu.img"
            }
          ]
        }
      }
    ],
    "cd": null
  }
}
```

---

## 11. DELETE /workers/{worker_id}

### Description

Deletes a Worker. The Control Plane will:

1. Look up the Worker’s disk and CD inventory from `workers.yml`.
2. If a CD target exists, delete it first.
3. Then delete the disk target(s).
4. Remove the Worker from `workers.yml`.
5. Remove the `mac,hostname` line from `dnsmasq/dhcp-hosts.conf`.
6. Send HUP to `ipxe-dnsmasq`.

### Path Parameters

| Parameter | Required | Description |
|---|---:|---|
| `worker_id` | Yes | Worker identifier to delete. |

### Query Parameters

| Parameter | Required | Default | Description |
|---|---:|---|---|
| `delete_disk` | No | `false` | Whether to also delete backing `.img` files. |
| `ignore_missing_target` | No | `false` | If `true`, ignores `404 iqn not found` from the Agent and continues. |

### curl

Delete only targets, keep `.img` files:

```bash
curl -s -X DELETE "$BASE_URL/workers/worker-01?delete_disk=false" \
  -H "Authorization: Bearer $TOKEN"
```

Delete targets and `.img` files:

```bash
curl -s -X DELETE "$BASE_URL/workers/worker-01?delete_disk=true" \
  -H "Authorization: Bearer $TOKEN"
```

Ignore missing targets on the Agent:

```bash
curl -s -X DELETE "$BASE_URL/workers/worker-01?delete_disk=true&ignore_missing_target=true" \
  -H "Authorization: Bearer $TOKEN"
```

### Example Success Response

```json
{
  "deleted": "worker-01",
  "delete_disk": false,
  "dnsmasq_removed": true
}
```

---

## 11.1 POST /workers/delete/batch

### Description

Batch delete Workers. Each item is processed independently; **a failure of one does not affect the others**. Returns a summary of `succeeded` / `failed`. The processing per Worker is identical to the single deletion in section 11 (delete CD/system disk targets → remove from inventory → remove dnsmasq binding). After all successful items are processed, the inventory is saved and dnsmasq is reloaded **only once**. Non-existent Workers are counted as `failed` (`worker not found`).

### Request Body Fields

| Field | Required | Default | Description |
|---|---:|---|---|
| `worker_ids` | Yes | — | Array of Worker identifiers to delete. |
| `delete_disk` | No | `false` | Whether to also delete backing `.img` files. |
| `ignore_missing_target` | No | `false` | If `true`, ignores `404 iqn not found` from the Agent and continues. |

### curl

```bash
curl -s -X POST "$BASE_URL/workers/delete/batch" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "worker_ids": ["worker-01", "worker-02"],
    "delete_disk": false,
    "ignore_missing_target": true
  }'
```

### Example Success Response

```json
{
  "succeeded": [
    {"worker_id": "worker-01", "hostname": "worker-01"}
  ],
  "failed": [
    {"worker_id": "worker-03", "error": "worker not found: worker-03"}
  ]
}
```

---

## 12. GET /operations

### Description

Reads the Control Plane operation audit log. This file is an incremental query interface over `state/operations.jsonl`.

### Query Parameters

| Parameter | Required | Default | Description |
|---|---:|---|---|
| `since` | No | `0` | Only return records with `id > since`. |
| `limit` | No | `1000` | Maximum number of records to return. |

### curl

Read from the beginning:

```bash
curl -s "$BASE_URL/operations" \
  -H "Authorization: Bearer $TOKEN"
```

Incremental read:

```bash
curl -s "$BASE_URL/operations?since=10&limit=100" \
  -H "Authorization: Bearer $TOKEN"
```

### Example Success Response

```json
{
  "next_cursor": 5,
  "entries": [
    {
      "id": 1,
      "ts": "2026-07-27T14:20:00+00:00",
      "op": "create_worker",
      "status": "started",
      "worker_id": "worker-01",
      "client": "172.18.0.1"
    },
    {
      "id": 2,
      "ts": "2026-07-27T14:20:01+00:00",
      "op": "agent.create_disk",
      "status": "ok",
      "worker_id": "worker-01",
      "agent": "storage-lio-01",
      "iqn": "iqn.2026-07.com.controller:worker-01.ubuntu"
    }
  ]
}
```

---

## 13. Typical Test Sequence

It is recommended to verify in this order:

### 13.1 Check Service Liveness

```bash
curl -s "$BASE_URL/healthz"
```

### 13.2 Check Boot Variable Projection

```bash
curl -s "$BASE_URL/boot-vars?mac=000c29b98b2d&hostname=worker-01"
curl -s "$BASE_URL/boot-vars?mac=000c29b98b2d&hostname=worker-01&format=json"
```

### 13.3 Check Agent Configuration and Capabilities

Note: `config/agents.yml` is read from inside the Control Plane container. If an Agent is on the same host as the Control Plane, you cannot use `http://localhost:4840` because `localhost` inside the container points to the Control Plane container itself.

The default Compose file already configures:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Therefore, for an Agent on the same host, configure it as:

```yaml
base_url: http://host.docker.internal:4840
```

```bash
curl -s "$BASE_URL/agents?live=true" \
  -H "Authorization: Bearer $TOKEN"
```

### 13.4 Register Worker Identity (hostname + MAC binding)

```bash
curl -s -X POST "$BASE_URL/workers" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "worker_id": "worker-00",
    "mac": "00:0c:29:b9:8b:00"
  }'
```

At this point, the Worker is MAC-bound but has no system disk (`state=registered`, `disks` is an empty array).

### 13.5 Create a System Disk for worker-00 (empty disk)

```bash
curl -s -X POST "$BASE_URL/workers/worker-00/luns/disk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "empty",
    "os": "ubuntu",
    "size": "40G"
  }'
```

After the disk is created, `state` transitions from `registered` to `ready`.

### 13.6 Set Default Boot Configuration

```bash
curl -s -X PUT "$BASE_URL/workers/worker-00/default-os" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "os": "ubuntu"
  }'
```

Now `/boot-vars` will return `menu-default=ubuntu`. See section 7.3 for examples of setting menu items and timeout.

### 13.7 Query Worker Inventory

```bash
curl -s "$BASE_URL/workers/worker-00" \
  -H "Authorization: Bearer $TOKEN"
```

### 13.8 Query Real-Time Status

```bash
curl -s "$BASE_URL/workers/worker-00/status" \
  -H "Authorization: Bearer $TOKEN"
```

### 13.9 Delete Worker, Keeping the Empty Disk File

```bash
curl -s -X DELETE "$BASE_URL/workers/worker-00?delete_disk=false" \
  -H "Authorization: Bearer $TOKEN"
```

This step is ideal for a workflow where you create an empty disk, then manually rename it to a master image.

---

## 14. Agent iSCSI LUN/Target Management

### Description

The Control Plane can directly manage iSCSI targets/LUNs on any Agent. Requests are forwarded by the Control Plane to the Agent (the Agent’s Bearer token is provided by `config/agents.yml`), so callers only need the Control Plane Token and never need to contact the Agent directly.

Differences from Worker lifecycle endpoints (`POST /workers`, `DELETE /workers/{worker_id}`):

- Worker endpoints are **inventory-oriented**: they automatically assemble IQNs, write `state/workers.yml`, and write dnsmasq bindings.
- LUN management endpoints are **data-plane direct management**: they do not write any inventory; they directly operate targets on the Agent. Suitable for master image management, manual troubleshooting, temporary ISO mounting, etc.

All endpoints require authentication (`IPXE_CP_TOKEN`). If the Agent is not found, `404 agent not found` is returned. If the Agent is unreachable, `503` is returned. Business validation errors from the Agent side (e.g., IQN prefix mismatch, file already exists, IQN already exists) are passed through with the Agent’s status code and `detail`:

```json
{"agent": "storage-lio-01", "error": "iqn base mismatch: ..."}
```

### 14.1 GET /agents/{agent_id}/luns

Lists all iSCSI targets/LUNs on the specified Agent. The response structure depends on the Agent backend (stgt includes a `tid` field, LIO is the parsed output of `targetcli`). The Control Plane passes it through unchanged.

#### Path Parameters

| Parameter | Required | Description |
|---|---:|---|
| `agent_id` | Yes | Agent identifier, corresponding to a key in `config/agents.yml`. |

#### curl

```bash
curl -s "$BASE_URL/agents/storage-lio-01/luns" \
  -H "Authorization: Bearer $TOKEN"
```

#### Example Success Response

```json
[
  {
    "iqn": "iqn.2026-07.com.controller:worker-01.ubuntu",
    "luns": [
      {
        "backing": "/home/iscsi_img/worker-01.ubuntu.img"
      }
    ]
  }
]
```

### 14.2 POST /agents/{agent_id}/luns/disk

Creates a disk LUN on the specified Agent. Pass `master` to clone from a master image (prefers btrfs / ZFS(≥2.2) reflink for instant cloning), or pass `size` to create an empty sparse disk. If the Agent is not configured with `role.disk`, it returns `400 agent ... not configured for disk role`.

#### Path Parameters

| Parameter | Required | Description |
|---|---:|---|
| `agent_id` | Yes | Agent identifier. |

#### Request Body Fields

| Field | Required | Description |
|---|---:|---|
| `iqn` | Yes | Target IQN. Must be prefixed with the Agent’s `base_iqn`. |
| `filename` | No | Backing filename. If omitted, the Agent auto-generates one from the IQN. |
| `master` | Conditionally required | Master image filename (located in `DISK_DIR`). Mutually exclusive with `size`. |
| `size` | Conditionally required | Empty disk size, e.g., `40G`. Mutually exclusive with `master`. |

#### curl

```bash
# Clone from master
curl -s -X POST "$BASE_URL/agents/storage-lio-01/luns/disk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "iqn": "iqn.2026-07.com.controller:worker-02.ubuntu",
    "master": "_tpl_ubuntu_2204.img"
  }'

# Create empty disk
curl -s -X POST "$BASE_URL/agents/storage-lio-01/luns/disk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "iqn": "iqn.2026-07.com.controller:worker-02.ubuntu",
    "filename": "worker-02.ubuntu.img",
    "size": "40G"
  }'
```

#### Example Success Response

```json
{
  "iqn": "iqn.2026-07.com.controller:worker-02.ubuntu",
  "backing": "/home/iscsi_img/worker-02.ubuntu.img"
}
```

### 14.3 POST /agents/{agent_id}/luns/cd

Creates a CD (ISO virtual drive) LUN on the specified Agent. Only Agents with `role.cd` set to true support this. If the Agent is not configured for the CD role (e.g., LIO), it returns `400 agent ... not configured for cd role`. Backend capability limitations are passed through from the Agent.

#### Request Body Fields

| Field | Required | Description |
|---|---:|---|
| `iso` | Yes | ISO filename (present in `DISK_DIR`). |
| `iqn` | No | Target IQN. If omitted, the Agent auto-generates one from `base_iqn:iso_filename`. |

#### curl

```bash
curl -s -X POST "$BASE_URL/agents/controller-stgt/luns/cd" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "iso": "Win11_24H2.iso"
  }'
```

### 14.4 DELETE /agents/{agent_id}/luns

Deletes a LUN/target on the specified Agent.

#### Query Parameters

| Parameter | Required | Default | Description |
|---|---:|---|---|
| `iqn` | Yes | None | Target IQN to delete. |
| `delete_file` | No | `false` | Whether to also delete the backing file (`.img`/`.iso`). |
| `ignore_missing` | No | `false` | If `true`, treats a `404 iqn not found` from the Agent as success. |

#### curl

```bash
# Delete only the target, keep the backing file
curl -s -X DELETE "$BASE_URL/agents/storage-lio-01/luns?iqn=iqn.2026-07.com.controller:worker-02.ubuntu" \
  -H "Authorization: Bearer $TOKEN"

# Delete target and backing file, continue even if target was already missing
curl -s -X DELETE "$BASE_URL/agents/storage-lio-01/luns?iqn=iqn.2026-07.com.controller:worker-02.ubuntu&delete_file=true&ignore_missing=true" \
  -H "Authorization: Bearer $TOKEN"
```

#### Example Success Response

```json
{
  "deleted": "iqn.2026-07.com.controller:worker-02.ubuntu",
  "delete_file": false
}
```

When ignoring a missing target:

```json
{
  "deleted": "iqn.2026-07.com.controller:worker-02.ubuntu",
  "delete_file": true,
  "ignored_missing": true
}
```

### 14.5 POST /agents/{agent_id}/luns/scan

Triggers the Agent to scan its image directory and rebuild targets for missing `.img`/`.iso` files (file-is-truth). For stgt backends, the result includes what was recreated. For LIO backends, due to `saveconfig` persistence, it usually skips everything.

#### curl

```bash
curl -s -X POST "$BASE_URL/agents/storage-lio-01/luns/scan" \
  -H "Authorization: Bearer $TOKEN"
```

#### Example Success Response

```json
{
  "created": [
    {
      "iqn": "iqn.2026-07.com.controller:worker-02.ubuntu",
      "cd": false
    }
  ],
  "skipped": []
}
```

---

## 15. GET /masters (Master Image List)

### Description

Aggregates and lists the master images from all **enabled disk-role** Agents (`enabled=true` and `role.disk=true`). Master images are identified by the storage Agent’s background scanning thread (every 30 seconds by default), which looks for image files in `DISK_DIR` whose names contain the `_tpl_` marker (e.g., `_tpl_ubuntu_2204.img`).

Used by the WebUI for the master clone drop-down list. **It has no linkage to Worker creation APIs** — purely a read-only query, does not change any state or write inventory.

### Failure Tolerance

- A single Agent unreachable or authentication failure: that node returns an `error` field and logs an audit `master.list` (failed), **but does not block the overall result**.
- All nodes fail: the overall response is `502`.
- Partial success / no available nodes: returns `200` (with an empty `agents` array if no nodes).

### curl

```bash
curl -s "$BASE_URL/masters" \
  -H "Authorization: Bearer $TOKEN"
```

### Example Success Response

```json
{
  "agents": [
    {
      "agent": "storage-lio-01",
      "iscsi_server": "192.168.80.3",
      "masters": [
        {"name": "_tpl_ubuntu_2204.img", "size": 10737418240, "mtime": 1785643200},
        {"name": "_tpl_debian_12.img", "size": 8589934592, "mtime": 1785729600}
      ]
    }
  ]
}
```

| Field | Description |
|---|---|
| `agents` | Array, one entry per Agent with the disk role enabled. |
| `agents[].agent` | Agent identifier (key in `config/agents.yml`). |
| `agents[].iscsi_server` | Data-plane iSCSI address (same fallback rule as `/boot-vars`). |
| `agents[].masters` | Array of masters, each `{name, size, mtime}`: filename / size in bytes / modification timestamp. |
| `agents[].error` | Error details if querying this node failed (absent for successful nodes). |

---

## 16. Current Implementation Boundaries

The current version supports:

- Worker identity registration (hostname + MAC binding)
- Worker system disk creation (`POST /workers/{worker_id}/luns/disk`)
- Setting Worker default boot configuration (OS / menu item / timeout, `PUT /workers/{worker_id}/default-os`)
- Worker deletion
- Agent selection
- Agent LUN direct management (list / create disk / create CD / delete / scan)
- Master image list query (`GET /masters`, backed by periodic background scanning on storage nodes)
- Windows ISO special handling
- dnsmasq hostname bindings
- Worker and operation audit trail queries
- Multi-OS system disks (a Worker can have disks for multiple OSes, at most one per OS, distinguished by `os`, with `default_os` determining the default boot)

The current version does **not** yet include:

- Editing Workers
- Bulk importing Workers
- Automatic IP management
- Automatic master image lifecycle management
- Scheduled reconciliation
- Data disk attachment (the `/luns/data` namespace is reserved)

---

### Component Ports

#### Control
- dnsmasq: `67`, `66`
- nginx: `4838`
- Control Plane: `4839`

#### iSCSI Server
- Agent: `4840`
- LIO / stgt: `3260`