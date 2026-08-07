# Agent API Reference

This document describes the HTTP endpoints currently implemented by the Agent, intended for Control Plane consumption and deployment integration testing.

> **Calling convention**: The Agent API is the **internal contract** between the Control Plane and the storage nodes; the primary caller is the Control Plane. Third-party integrations should **prefer calling the Control Plane API** (see [Control Plane API Reference](./control-plane-api)) — the WebUI and third-party systems are equal clients; both only face the Control Plane.

Base URL for local verification:

```text
http://localhost:4840
```

In production, replace this with the actual Agent address on the corresponding storage node.

## 1. Agent Responsibilities

The Agent is the local executor on each iSCSI server. The Control Plane calls the Agent exclusively via HTTP; the Agent then enters the local iSCSI server container and executes `tgtadm` or `targetcli` to create, scan, delete, and query targets, LUNs, and backing files.

Two backends are currently supported:

| Backend | Purpose | ISO virtual CD | Persistence |
|---|---|---|---|
| `stgt` | Userspace iSCSI target; suitable for ISO virtual drives and installation paths | Supported | Rebuilds by scanning the image directory at startup |
| `lio` | Linux kernel-space iSCSI target; suitable for production disk LUNs | Not supported | `targetcli saveconfig` |

## 2. Global Rules

### 2.1 Authentication

Except for `GET /healthz`, all endpoints require a Bearer token:

```http
Authorization: Bearer <IPXE_AGENT_TOKEN>
```

A missing or incorrect token returns:

```text
401 unauthorized
```

Token comparison uses a constant-time algorithm (to prevent timing attacks); on failure, it uniformly returns `401` without echoing token details, and the token value is also not recorded in logs.

### 2.2 IQN Base Validation

For any endpoint that accepts an `iqn` in the request, the Agent verifies that it starts with its own base IQN.

The base IQN comes from `.env`:

```text
IPXE_IQN_BASE=iqn.2026-07.com.controller
```

Valid example:

```text
iqn.2026-07.com.controller:worker-02.Ubuntu
```

A mismatch returns:

```text
400 iqn base mismatch
```

### 2.3 Image Directory

The Agent uses `IPXE_DISK_DIR` from `.env` as the image directory, typically:

```text
/home/iscsi_img
```

Conventions:

- `.img` files serve as disk backing
- `.iso` files serve as virtual CD backing
- The Agent can create `.img` files
- The Agent does **not** create ISO files; it only mounts existing ones

### 2.4 IQN in Query Parameters

IQNs contain colons. When passing them as query parameters, use `curl -G --data-urlencode` instead of manually constructing the URL.

## 3. Endpoint Overview

| Method | Path | Description | Auth |
|---|---|---|---|
| `GET` | `/healthz` | Health check | No |
| `POST` | `/lun/disk` | Create a disk LUN and its corresponding `.img` file | Yes |
| `POST` | `/lun/cd` | Mount an ISO as a virtual CD LUN | Yes |
| `POST` | `/lun/scan` | Scan the image directory and bulk-create targets | Yes |
| `DELETE` | `/lun` | Delete a target, optionally deleting the backing file | Yes |
| `GET` | `/lun` | List current targets | Yes |
| `GET` | `/capabilities` | Query Agent backend capabilities | Yes |
| `GET` | `/masters` | List `*_tpl_*` master images (cached from periodic background scan) | Yes |
| `GET` | `/logs` | Query operation logs | Yes |

## 4. GET /healthz

Health check endpoint. The only endpoint that does not require a token.

Request:

```bash
curl -s http://localhost:4840/healthz
```

Response:

```json
{"status":"ok"}
```

## 5. POST /lun/disk

Creates a disk LUN and the corresponding `.img` backing file.

### 5.1 Request Body

```json
{
  "iqn": "iqn.2026-07.com.controller:worker-02.Ubuntu",
  "master": "_tpl_Ubuntu.img",
  "size": "20G",
  "filename": "worker-02.Ubuntu.img"
}
```

Field descriptions:

| Field | Required | Description |
|---|---:|---|
| `iqn` | Yes | The Target IQN assembled by the Control Plane; must match this Agent’s base IQN |
| `master` | Choose one | Master image filename; must already exist in `IPXE_DISK_DIR` |
| `size` | Choose one | Size of the empty sparse disk to create, e.g., `20G` |
| `filename` | No | Override the default backing filename |

At least one of `master` or `size` must be provided. If both are supplied, the current implementation prioritizes `master`.

### 5.2 File Naming

If `filename` is omitted, the Agent derives the filename from the IQN suffix:

```text
iqn.2026-07.com.controller:worker-02.Ubuntu
-> worker-02.Ubuntu.img
```

### 5.3 Creation Process

1. Validate IQN base.
2. Calculate the backing file path.
3. If the backing file already exists, return `409`.
4. If `master` is provided, first try a reflink clone; fall back to a regular copy on failure.
5. If `size` is provided, create a sparse file.
6. Call the backend to create the iSCSI target and LUN.
7. If target creation fails, delete the newly created backing file.

### 5.4 Example: Clone from Master

```bash
TOKEN=$(grep IPXE_AGENT_TOKEN .env | cut -d= -f2)

curl -s -X POST http://localhost:4840/lun/disk \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"iqn":"iqn.2026-07.com.controller:worker-02.Ubuntu","master":"_tpl_Ubuntu.img"}'
```

Response:

```json
{
  "iqn": "iqn.2026-07.com.controller:worker-02.ubuntu",
  "backing": "/home/iscsi_img/worker-02.ubuntu.img"
}
```

Note: The current implementation lowercases the IQN used for creating the target.

### 5.5 Example: Create Empty Disk

```bash
curl -s -X POST http://localhost:4840/lun/disk \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"iqn":"iqn.2026-07.com.controller:worker-99.Ubuntu","size":"20G"}'
```

## 6. POST /lun/cd

Mounts an existing ISO as a virtual CD LUN.

### 6.1 Backend Limitations

This endpoint relies on `stgt --device-type cd`.

| Backend | Behavior |
|---|---|
| `stgt` | Supported |
| `lio` | Returns `400 lio backend does not support cd` |

### 6.2 Request Body

```json
{
  "iso": "worker-01.Windows.iso",
  "iqn": "iqn.2026-07.com.controller:worker-01.Windows.iso"
}
```

Field descriptions:

| Field | Required | Description |
|---|---:|---|
| `iso` | Yes | ISO filename; must already exist in `IPXE_DISK_DIR` |
| `iqn` | No | Specify the Target IQN; if omitted, uses `base_iqn:iso_filename` |

### 6.3 Example

```bash
curl -s -X POST http://localhost:4840/lun/cd \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"iso":"worker-01.Windows.iso"}'
```

Response:

```json
{
  "iqn": "iqn.2026-07.com.controller:worker-01.windows.iso",
  "backing": "/home/iscsi_img/worker-01.Windows.iso"
}
```

## 7. POST /lun/scan

Scans `IPXE_DISK_DIR` and bulk-creates targets based on existing `.img` and `.iso` files.

### 7.1 Naming Rules

| File Type | IQN Suffix Rule | Example |
|---|---|---|
| `.img` | Strip the `.img` extension | `worker-02.Ubuntu.img` -> `base:worker-02.Ubuntu` |
| `.iso` | Keep the full filename | `worker-01.Windows.iso` -> `base:worker-01.Windows.iso` |

### 7.2 Backend Behavior

| Backend | Behavior |
|---|---|
| `stgt` | Scans `.img` and `.iso`; `.iso` files are created as CD-ROM |
| `lio` | Scans `.img`; skips `.iso` |

### 7.3 Example

```bash
curl -s -X POST http://localhost:4840/lun/scan \
  -H "Authorization: Bearer $TOKEN"
```

Response:

```json
{
  "created": [
    {
      "iqn": "iqn.2026-07.com.controller:worker-02.ubuntu",
      "cd": false
    },
    {
      "iqn": "iqn.2026-07.com.controller:worker-01.windows.iso",
      "cd": true
    }
  ],
  "skipped": []
}
```

## 8. DELETE /lun

Deletes the target for the specified IQN. Optionally also deletes the backing file.

### 8.1 Query Parameters

| Parameter | Required | Default | Description |
|---|---:|---|---|
| `iqn` | Yes | None | Target IQN to delete |
| `delete_file` | No | `false` | Whether to delete the backing file as well |

### 8.2 Delete Only the Target

```bash
curl -s -X DELETE -G \
  --data-urlencode 'iqn=iqn.2026-07.com.controller:worker-99.Ubuntu' \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:4840/lun
```

Response:

```json
{
  "deleted": "iqn.2026-07.com.controller:worker-99.ubuntu",
  "delete_file": false
}
```

### 8.3 Delete Target and Backing File

```bash
curl -s -X DELETE -G \
  --data-urlencode 'iqn=iqn.2026-07.com.controller:worker-99.Ubuntu' \
  --data-urlencode 'delete_file=true' \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:4840/lun
```

## 9. GET /lun

Lists the current iSCSI targets.

Request:

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:4840/lun
```

Example `stgt` response:

```json
[
  {
    "tid": 1,
    "iqn": "iqn.2026-07.com.controller:worker-02.ubuntu",
    "luns": [
      {
        "lun": 0,
        "backing": null
      },
      {
        "lun": 1,
        "backing": "/home/iscsi_img/worker-02.Ubuntu.img"
      }
    ]
  }
]
```

Notes:

- `stgt` shows LUN 0, which is the control LUN; its `backing` is `null`
- The actual disk or ISO is usually LUN 1
- `lio` responses do not include a `tid`, only `iqn` and `luns`

## 10. GET /capabilities

Queries the Agent’s current backend capabilities.

Request:

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:4840/capabilities
```

Example `stgt` (btrfs storage):

```json
{
  "backend": "stgt",
  "cd": true,
  "persistent": "auto-scan on startup",
  "base_iqn": "iqn.2026-07.com.controller",
  "fs_type": "btrfs",
  "clone": "reflink (FICLONE; xfs requires the reflink feature enabled) -> shutil.copy fallback",
  "empty_disk": "truncate (sparse)"
}
```

Example `lio` (ZFS storage):

```json
{
  "backend": "lio",
  "cd": false,
  "persistent": "saveconfig (auto-load on start)",
  "base_iqn": "iqn.2026-07.com.controller",
  "fs_type": "zfs",
  "clone": "reflink (FICLONE on OpenZFS >= 2.2, master and work disk in the same dataset) -> shutil.copy fallback",
  "empty_disk": "truncate (sparse)"
}
```

| Field | Description |
|---|---|
| `fs_type` | Filesystem type of the storage directory (`IPXE_DISK_DIR`), derived by matching the longest mount point in `/proc/self/mounts`. The Control Plane `GET /agents` passes this through as part of `capabilities`. |
| `clone` | Master clone method: btrfs and xfs (when reflink feature is enabled) use FICLONE reflink for near-instant cloning; ZFS requires OpenZFS ≥ 2.2 and the master and clone must reside in the same dataset (otherwise it falls back to a full `shutil.copy`); other filesystems only perform full copies. |

## 11. GET /logs

Reads the Agent operation log.

The log is an append-only JSON Lines file. The file path comes from:

```text
IPXE_LOG_FILE=/var/log/ipxe-agent/ops.jsonl
```

### 11.1 Query Parameters

| Parameter | Required | Default | Description |
|---|---:|---|---|
| `since` | No | `0` | Only return log entries with an id greater than this value |
| `limit` | No | `1000` | Maximum number of entries to return |

### 11.2 Example

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:4840/logs?since=1&limit=100' | python3 -m json.tool
```

Response:

```json
{
  "next_cursor": 12,
  "entries": [
    {
      "id": 12,
      "ts": "2026-07-27T12:00:00+00:00",
      "op": "disk",
      "req": {
        "iqn": "iqn.2026-07.com.controller:worker-99.Ubuntu",
        "master": null,
        "size": "1G",
        "filename": null
      },
      "result": "ok",
      "client": "127.0.0.1"
    }
  ]
}
```

Write operations that are recorded include:

- `disk`
- `cd`
- `scan`
- `delete`
- `auto_scan`

The log does **not** record tokens.

## 12. GET /masters (Master Image List)

Lists the available master image files under this node’s `IPXE_DISK_DIR`, for use by the Control Plane/WebUI when selecting a clone source.

Master images are identified by a filename convention: the filename must contain the `_tpl_` marker (e.g., `_tpl_ubuntu_2204.img`, `_tpl_debian_12.img`).

A background thread scans the image directory every 30 seconds after the Agent starts and caches the list. This endpoint returns the cached list directly without blocking on the filesystem (a newly added master becomes visible within at most 30 seconds).

### 12.1 Request

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:4840/masters | python3 -m json.tool
```

### 12.2 Response

```json
{
  "masters": [
    {"name": "_tpl_ubuntu_2204.img", "size": 10737418240, "mtime": 1785552000},
    {"name": "_tpl_debian_12.img", "size": 5368709120, "mtime": 1785552000}
  ]
}
```

Field descriptions:

| Field | Description |
|---|---|
| `name` | Master image filename (contains the `_tpl_` marker, e.g., `_tpl_ubuntu_2204.img`) |
| `size` | File size in bytes |
| `mtime` | Last modification time (Unix timestamp, seconds) |

When no masters are present, it returns `{"masters": []}`.

## 13. Error Codes

| Status Code | Common Trigger Conditions |
|---:|---|
| `400` | IQN base mismatch; missing required fields in the request; operation not supported by the current backend |
| `401` | Missing or incorrect token |
| `404` | Master file not found; ISO file not found; target not found |
| `409` | Backing file already exists; IQN already exists |
| `500` | `tgtadm` or `targetcli` execution failed |
| `503` | iSCSI container does not exist; Docker connection failed |

## 14. Control Plane Integration Recommendations

It is recommended that the Control Plane interacts with an Agent in this order:

1. Call `GET /healthz` for a liveness check.
2. Call `GET /capabilities` to determine the backend capabilities.
3. Call `POST /lun/disk` for system disks.
4. During Windows installation, schedule ISO optical drives only to Agents with `cd=true`.
5. After write operations, pull the audit log via `GET /logs?since=<cursor>`.

## 15. Deployment Notes

The Agent currently operates the local iSCSI container via the Docker socket:

```text
/var/run/docker.sock:/var/run/docker.sock
```

Therefore, the Agent should only be exposed on the control network or a trusted management network, and should not be directly exposed to the public internet.