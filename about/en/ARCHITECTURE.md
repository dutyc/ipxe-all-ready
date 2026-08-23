# Architecture

![Architecture](../../assets/architecture.svg)

## Control Plane / Data Plane Separation

The system is split along one clean line: the **control plane** handles identity, scheduling and configuration over HTTP; the **data plane** carries block I/O over iSCSI and never touches the control plane. A Worker's disk traffic flows directly between the device and its Storager node, so a control-plane outage degrades provisioning but never in-flight I/O.

## The Three Roles

### Controller

The brain. A containerized node running:

- the **Control Plane HTTP service** (:4839) — device ledger & pool, device↔Worker binding, worker lifecycle, storage scheduling (LUN creation / mounting), boot-variable projection, audit log
- **dnsmasq** — DHCP / TFTP / HTTP boot services for PXE
- the **Web UI** (:4838) — one client of the REST API, not a separate system

All state is persisted as plain files (YAML / JSONL); there is no database.

### Storager

Block storage. Each node runs an **API Agent** (:4840) that executes Control Plane commands against a local iSCSI server container (LIO/stgt) via docker.sock. Backend differences are encapsulated inside the Agent: the Control Plane only ever speaks HTTP, the Agent translates it into backend operations, and the data-plane address is delivered to devices through boot variables.

### Devices

The stateless compute side. A physical device has no local disk: on PXE boot it reports its fingerprint (MAC / UUID / SMBIOS / CPU / memory / NIC) and is auto-admitted into the **device pool**; after being bound to a Worker (its compute identity) and given a system disk, it attaches the iSCSI disk and runs the OS. Block I/O travels the iSCSI data plane, never the control plane.

## Three Entities: Device, Worker, System Disk

The role layer maps onto an entity layer of three objects:

| Entity | Identity | Notes |
|---|---|---|
| **Device** | MAC (unique) | Physical machine, ledger entry; the authoritative side of the binding |
| **Worker** | `worker_id` (== hostname) | Compute identity; a Device bound to a Worker becomes that Worker's booting node |
| **System Disk** | IQN | Storage volume (master-clone or empty); multiple disks per Worker |

The binding relationship is authoritative on the **device side** (`bound_worker_id`); the Worker only holds a projection. Disks are decoupled from machines: unbinding or rebinding returns the device to the pool while its system disks stay on the Worker.

- Device lifecycle: `pooled` (in pool, awaiting binding) → `bound` → `revoked`
- Rebinding with `force=true` is atomic: new binding persisted, old binding cleared, ledger snapshot restored on failure
- One Worker can carry multiple system disks (Windows / Ubuntu / Debian / CentOS / ESXi) and switch the default boot OS online

## Boot Chain

1. Device powers on → DHCP (dnsmasq) → TFTP downloads iPXE → iPXE boots
2. iPXE reports the fingerprint to `/devices/report`; an unknown MAC is auto-admitted into the pool (unless auto-register is off)
3. iPXE requests `/boot-vars`; the request is **validated against the binding** — a MAC-bearing request must come from the device bound to the matched Worker, otherwise an empty script is returned (binding = authentication)
4. Bound device: boot variables point at its system disk → iSCSI login (data plane) → OS runs
5. Pooled-but-unbound device: reboot loop until bound

## State Storage: Files Are the Truth

No database. Every control-plane state file is plain text, diff-able and manually repairable:

- `state/devices.yml` — device ledger (pool / bindings)
- `state/workers.yml` — worker ledger
- `state/settings.json` — runtime settings (e.g. auto-register switch)
- `state/operations.jsonl` — full audit trail of every management operation
- `config/agents.yml` — registered Storager agents

Every capability is exposed as REST; the Web UI is just one client, and the CLI is another.

Performance boundary: the file-based state store is acceptable at IPv4 network scale; when the project adds IPv6 support, a high-performance database will be introduced.

## Security Boundary

- **API token** guards all management endpoints; boot-facing endpoints are exempt by design
- **Binding = authentication**: `/boot-vars` validates that the requesting MAC belongs to the matched Worker's bound device, preventing another device from stealing a Worker's boot identity
- Fingerprint reporting is unauthenticated but only feeds the pool — it grants no privilege
- `key_hash` on device records reserves the slot for the planned mutual-authentication phase

The architecture is evolving rapidly, and the authentication system (mutual device↔control-plane authentication, boot-chain integrity) is expected to be completed incrementally.

## Protocol Evolution

The data plane is iSCSI today, but the semantics — stateless compute, disk-machine decoupling, one identity chain from MAC to boot — do not depend on it. Storager backends are already abstracted behind the Agent, so swapping the transport does not touch the architecture.

The NVMe-oF (NVMe over TCP) track is under active research and already validated at the firmware layer (ipxe-stateless `research/nvme-of` branch):

- an iPXE-native **nvmetcp driver** performs `sanboot nvme://` directly, mirroring the existing iSCSI pattern;
- **DH-HMAC-CHAP authentication** (connection control) is implemented and verified — credentials are injected per boot through the control plane (`/boot-vars` → `nbft-secret`), never baked into firmware or menus;
- the **NBFT hand-off chain** — iPXE sanboot → NBFT ACPI table → OS-native consumption (`nvme connect-all --nbft`) → rootfs mount → login — is verified end-to-end in QEMU.

The two data planes coexist: iSCSI remains the production path (and the Windows fallback), NVMe-oF is the migration direction. Data-plane encryption (NVMe/TCP TLS) is the open mainline after authentication; the identity chain (device pool → binding → boot) is protocol-agnostic by design.
