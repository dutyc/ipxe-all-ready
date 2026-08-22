# Environment Deployment

> **This document covers: environment deployment · quick start.**
> Deploy the Controller (Control Plane) + storage node (Agent + iSCSI backend) in one go — universal across all platforms.
> Once the environment is ready, refer to *Windows Diskless Quick Deployment* / *Debian-family Diskless Quick Deployment* for golden-image creation and cloning.

## Deployment Topology: Two Compose Files

This project consists of **two independent Compose files** — they are **not a single unit**:

```
Controller Node — root docker-compose.yml (Control Plane)
├── ipxe-dnsmasq          DHCP / TFTP (host network, ports 67/69)
├── ipxe-control-plane    Control Plane API (4839), Worker lifecycle orchestration
└── ipxe-cp-webui         WebUI + file distribution (4838)

Storage Node — storager/ (Data Plane, can be co-located with Controller)
├── storager/iscsi/docker-compose.yml  iSCSI backend (3260, host network, stgt or LIO) + shared Agent (4840)
└── storager/nvmeof/docker-compose.yml NVMe-oF backend (nvmet host service, 4841) + shared Agent (4840)
```

Key concepts:

* **One Agent corresponds to one iSCSI backend; they are a single unit** — the Agent operates the local backend container via `docker.sock`.  
  However many storage nodes you deploy, that’s how many Agents there are. The Control Plane schedules across them using the `agents.yml` inventory.
* **Single-node / multi-node deployment**: When Workers are few and I/O pressure is low, the storage node can be co-located with the Controller (one Agent).  
  When there are many Workers and you need iSCSI SAN performance, split storage across multiple machines based on server I/O resources (one Agent per machine).  
  The Control Plane automatically schedules disk creation across multiple Agents using `role.disk`, avoiding a single-point storage bottleneck.

---

## Step 1: Deploy the Controller (Control Plane)

### 1.1 Preparation

On the Controller node (Debian / Ubuntu with Docker):

```bash
git clone https://github.com/dutyc/ipxe-all-ready.git
cd ipxe-all-ready
mkdir -p /pool1/iscsi_img        # Image directory (stores disk files; path can be customised)
```

### 1.2 Modify the dnsmasq Subnet

For a first-time deployment, copy the example templates first (docker-compose mounts the following config files via file-level bind mounts; if missing, a directory is created inside the container and the config will not take effect):

```bash
cp dnsmasq/dnsmasq.conf.example dnsmasq/dnsmasq.conf
cp dnsmasq/dhcp-hosts.conf.example dnsmasq/dhcp-hosts.conf
```

Edit `dnsmasq/dnsmasq.conf` and adjust according to your actual network environment:

```conf
interface=ens33                                  # Real NIC name
dhcp-range=192.168.80.50,192.168.80.100,255.255.255.0,12h   # Address pool (match your subnet)
dhcp-option=3,192.168.80.2                       # Gateway
dhcp-option=6,223.5.5.5                          # DNS
```

### 1.3 Obtain iPXE Firmware

Download the boot firmware from the **[Releases](https://github.com/dutyc/ipxe-stateless/releases)** page of our companion firmware repo **[iPXE-Stateless](https://github.com/dutyc/ipxe-stateless)** (the latest release is built from upstream iPXE baseline `e6e51ccb` plus custom patches; no compilation needed). Using firmware from the official iPXE release site is not recommended: official builds ship no native drivers for high-speed NICs, so RTL8125 (2.5G) / RTL8126 (5G) machines can only fall back to the UNDI/SNP compatibility path and may fail to boot; our firmware includes native driver support for these NICs.

The following files are required. Download them from the Release page and place them into the `tftp/` root directory. Release assets use flat names — strip the `pxe-uefi-` prefix so the filenames match what dnsmasq serves:

| Release asset | Filename in `tftp/` | Notes |
|---|---|---|
| `undionly.kpxe` | `undionly.kpxe` | BIOS firmware (UNDI interface; compatible with any NIC with a PXE ROM) |
| `pxe-uefi-snponly.efi` | `snponly.efi` | UEFI firmware (SNP-only, distributed by default) |
| `pxe-uefi-ipxe.efi` | `ipxe.efi` | UEFI firmware (native + SNP dual path, fallback for UEFI boot issues) |
| `pxe-uefi-snponly-debug.efi` | `snponly-debug.efi` | (optional) debug build, REALTEK driver logs for troubleshooting |
| `pxe-uefi-ipxe-debug.efi` | `ipxe-debug.efi` | (optional) debug build, REALTEK driver logs for troubleshooting |

Debug builds are for troubleshooting only: back up the original firmware before replacing it, and switch back to the release build once the issue is located.

`dnsmasq.conf` is already configured to distribute firmware based on architecture detection: UEFI → `snponly.efi`, BIOS → `undionly.kpxe`, second iPXE request → `boot.ipxe`. If a machine fails to boot over UEFI, first switch the efi64 boot file to `ipxe.efi` and retry; if it still fails, use a debug build to capture REALTEK driver logs.

> **memdisk (optional; not needed for regular boot)**: memdisk is only used for the legacy approach of booting ISO installation images directly via iPXE (`kernel memdisk` + `initrd xxx.iso`); this project boots diskless machines over iSCSI sanboot and does not need it. If required, download the SYSLINUX release package from the [SYSLINUX release page](https://www.kernel.org/pub/linux/utils/boot/syslinux/), extract it, and place `bios/memdisk/memdisk` into `tftp/`:
>
> ```bash
> cd /tmp
> wget https://mirrors.edge.kernel.org/pub/linux/utils/boot/syslinux/6.03/syslinux-6.03.tar.gz
> tar xzf syslinux-6.03.tar.gz
> cp syslinux-6.03/bios/memdisk/memdisk <project-path>/tftp/
> ```

### 1.4 Configure API Token (optional; boot works without it)

**Control Plane** (`control_plane/control_plane.env`):

```env
# Leave empty = all API endpoints are open (only /healthz is always accessible)
IPXE_CP_TOKEN=your-token
```

**WebUI** (`webui/app/.env`, **must match the value above**, otherwise the WebUI API calls will be rejected):

```env
VITE_CP_TOKEN=your-token
```

> Note: `VITE_` variables are injected at build time. After modification you need to rebuild the WebUI: `cd webui/app && npm install && npm run build`.  
> If you skip this section (leave the Token empty), no rebuild is necessary.

### 1.4.1 Registration Window & Enforcement (optional)

Device enrollment during deployment uses the **registration-window** model (replacing the former “auto-register” permanent switch): only while the window is open do new devices report with their public key (ECDSA P-256, generated by the firmware) to auto-join the **device pool** and complete key claim; once it closes, reports only record fingerprints without pool entry (no enrollment channel outside the window). The window is closed by default (TTL hard cap 1–60 min, auto-closes on expiry) and can be opened via WebUI or API:

- WebUI: the “Registration Window” panel at the top of the Devices (device pool) page — pick a duration (5/15/30/60 min) → “Open Window”; while open it shows the remaining time and offers “Close Early”
- API: `POST /settings/registration-window` (body `{"ttl_minutes": 30}`, see API Reference 5.1)

> The window only affects **new MACs**: when closed, new devices report fingerprints without entering the pool — pool them manually via “Register device” / “Register to Pool” on the Devices page or `POST /devices`, then bind them to a Worker with the bind wizard; existing pooled devices are unaffected. Existing devices booting during the window complete key claim (`key_hash` filled in).

**Signature enforcement switch** (transition-period compatibility, off by default): recommended to turn on only after all existing devices have completed key claim — afterwards `/boot-vars` is only served to bound devices that pass signature verification; keyless, signature-less or failing-signature devices are denied boot. Toggle the “Enforce Device Signature” checkbox in the Devices page “Registration Window” panel, or call `PUT /settings/enforcement` (see API Reference 5.1).

### 1.4.2 HTTPS Boot Chain (T5, required)

The device trust chain (firmware `keygen`/`pubkey`/`sign` + Control Plane challenge/signature verification) boots every machine through **HTTPS on port 443** — the nginx entry is the single TOFU trust anchor shared by all HTTPS targets (boot endpoints, `/file/` assets, `/tftp/` menu). No CA is involved: iPXE pins the self-signed leaf fingerprint on the first handshake.

The certificate is **generated automatically by the Control Plane on first start** (idempotent; RSA-2048 self-signed leaf, CA=False) — no manual step is required; nginx waits for `control_plane/state/certs/server.crt` before serving:

- **Leaf fingerprint** (TOFU pin baseline): `cat control_plane/state/certs/fingerprint.txt` (DER SHA-256 hex, same format as `openssl x509 -outform DER | sha256sum`)
- **SAN** is configurable via `IPXE_CP_CERT_SAN` (comma-separated `IP:`/`DNS:` entries, default `IP:127.0.0.1,DNS:localhost`); under TOFU the SAN is not part of device-side validation — only the fingerprint is pinned
- **HTTPS port**: default `443`; configurable via the compose variable `IPXE_HTTPS_PORT` (host mapping `IPXE_HTTPS_PORT:443`, the container keeps 443) — when changed, update `set https-port` in `tftp/boot.ipxe.cfg` to the same value (the two must stay in sync)
- `tftp/boot.ipxe.cfg` then chains: report → challenge → sign → boot-vars (see API Reference 5.2 / 16.6 for the endpoints)

> ⚠️ **Firmware must include the device-trust patches (0008/0009/0010)** — the HTTPS / `keygen` / `pubkey` / `sign` commands. Machines still running legacy firmware will **break the boot chain** (menu and boot-vars fetches over HTTPS fail). Upgrade all machines to the latest firmware release from [iPXE-Stateless releases](https://github.com/dutyc/ipxe-stateless/releases) before switching to this version of `boot.ipxe.cfg`.
>
> Transition: the signature enforcement switch is **off by default** — during the migration, devices without a key are still served via the degraded path (no nonce/sig). Turn enforcement on only after every device has completed key claim (see 1.4.1).
>
> Certificate rotation = delete `control_plane/state/certs/` → restart the Control Plane (regenerates the certificate) → restart nginx; devices must then clear the NVRAM fingerprint to re-enter the registration window.

### 1.5 Start the Controller

```bash
docker compose up -d
```

### 1.6 Verification

```bash
curl http://localhost:4839/healthz        # Control Plane
# Open http://<Controller IP>:4838 in a browser  # WebUI (see the WebUI User Guide for first use)
```

---

## Step 2: Deploy the Storage Node (Shared Agent + Backend)

> Perform this section once on each storage node; if co-located with the Controller, just run it locally.

### 2.1 Prepare the img Storage Directory (Determines Clone Speed)

Edit the volume mapping(s) in the compose of the backend you deploy and change the **host-side path** to the actual directory where this node stores img files: `storager/iscsi/docker-compose.yml` (the `storager-iscsi` and `storager-agent` blocks) or `storager/nvmeof/docker-compose.yml` (the `storager-agent` block) — the paths in the same file **must match**; the in-container path `/home/iscsi_img` stays unchanged and corresponds to `IPXE_DISK_DIR` in 2.3):

```yaml
# storager-iscsi service block
      - /pool1/iscsi_img:/home/iscsi_img   # change the host dir as needed, e.g. /data/iscsi_img
# storager-agent service block
      - /pool1/iscsi_img:/home/iscsi_img   # must match the mapping above
```

> **btrfs or ZFS (OpenZFS ≥ 2.2) is strongly recommended for the storage filesystem**: when cloning a golden image, the Agent prefers reflink (FICLONE, copy-on-write); on btrfs a clone completes in seconds and consumes almost no extra space. ZFS (OpenZFS ≥ 2.2) supports file-level reflink as well — instant clones, provided the master and the work disk live in the **same dataset** (ZFS < 2.2 or cross-dataset falls back to a full copy). If the directory sits on a filesystem without reflink support (ext4 / xfs), the Agent automatically falls back to a full copy, so clone time grows linearly with the image size (e.g. copying a 60 GB golden image takes several minutes). Format examples: `mkfs.btrfs -f /dev/sdb1`, or a ZFS pool with the storage directory on one dataset.

**Single storage node hardware bottlenecks** (basis for scaling out):

| Bottleneck | Impact | Recommendation |
|---|---|---|
| NIC throughput | Gigabit is ~125 MB/s theoretical; a single diskless Worker's sustained I/O can approach that, and throughput collapses when Workers share it | Production ≥ 10GbE; gigabit is only fine for validating with a few Workers |
| Disk I/O | Diskless Workers are dominated by small random reads; spinning disks are poor at random I/O | Use SSD / NVMe; size capacity and IOPS for the expected number of concurrent Workers |
| Memory / CPU | Affects iSCSI server queueing and caching | Regular config is fine; the bottleneck is usually network and disk |

**Scale out storage nodes by workload**: a single 10GbE link delivers roughly 1.1 GB/s effective throughput; at an average 50–100 MB/s sustained read per Worker, that supports about 10–20 concurrent Workers. For more Workers or higher I/O, add storage nodes (one Agent per machine — complete 2.2–2.4 and append a record in `agents.yml`); the Control Plane automatically schedules disk creation across Agents by `role.disk`.

### 2.2 Choose the Backend Type

The backends live in two directories under `storager/`, each with its own **standalone compose** (the Agent service is embedded in both — only the code is shared in `storager/agent/`); only **one** backend can run per node at a time (the `storager-agent` container name is fixed):

| Backend | Location | Characteristics |
|---|---|---|
| `stgt` | `storager/iscsi/docker-compose.yml`: uncomment the `ipxe-stgt` block and comment out `ipxe-lio` | User-space, supports mounting ISO as a virtual optical drive (`role.cd`), friendly to constrained environments |
| `lio` | `storager/iscsi/docker-compose.yml`: uncomment the `ipxe-lio` block and comment out `ipxe-stgt` | Kernel-space, production-grade disk performance (recommended for system disks) |
| `nvmet` | `storager/nvmeof/docker-compose.yml` (see 2.2.1) | Kernel NVMe-oF (NVMe/TCP), production-grade disk performance; the configuration plane lives in host configfs (kernel target), the management service is containerized, and the Agent calls it over HTTP (see the nvmet-host README) |

### 2.2.1 nvmet Backend (NVMe-oF, optional): Start the nvmet Management Service Container

With `IPXE_BACKEND=nvmet`, the kernel nvmet target and configfs stay on the host (they cannot be containerized), but the **management service runs as a container** (`ipxe-nvmet-host`, managed by `storager/nvmeof/docker-compose.yml`, which is a standalone compose embedding the Agent — no manual Python process):

```bash
# 1. Kernel modules + configfs (host; the only host step. Reload after reboot, or add to /etc/modules-load.d)
modprobe nvmet
modprobe nvmet-tcp
mount -t configfs configfs /sys/kernel/config

# 2. Configure storager/.env (see 2.3 below): IPXE_BACKEND=nvmet + token/URL

# 3. Build and start (the Agent service is embedded in this compose)
cd storager/nvmeof
docker compose --env-file ../.env up -d --build

# 4. Verify (port mapping is bound to the host loopback only)
curl http://127.0.0.1:4841/healthz
# → {"status":"ok","configfs":true}
```

The container is not privileged: configfs is bind-mounted into the container, and the container root writes are plain file writes plus symlink creation — no privileges needed (unrelated to LIO's targetclid/dbus dependency). The port mapping binds only `127.0.0.1:4841`, unreachable from the LAN; the Agent reaches it via the compose-internal network at `http://nvmet-host:4841`.

### 2.3 Configure `.env`

Edit `storager/.env`:

```env
IPXE_BACKEND=nvmet                           # nvmet = NVMe-oF (preferred/default); stgt / lio = iSCSI (fallback, see 2.2)
IPXE_AGENT_TOKEN=<generate a token>          # Generate: openssl rand -hex 32
IPXE_DISK_DIR=/home/iscsi_img                # Disk directory inside the container (matches the host storage dir set in 2.1)
IPXE_NQN_BASE=nqn.2026-07.com.controller     # Disk identifier namespace base (authoritative = NQN); the iSCSI IQN is derived from it (iqn. + nqn[4:])
IPXE_NVMET_HOST_URL=http://nvmet-host:4841   # compose-internal service name, Agent only
IPXE_NVMET_HOST_TOKEN=<generate a token>     # compose interpolates it into the container as NVMET_HOST_TOKEN
IPXE_NVMET_CACHE_FILE=/var/log/ipxe-agent/nvmet-credentials.json
TZ=Asia/Shanghai
# ── Only needed with IPXE_BACKEND=stgt|lio (iSCSI fallback, see 2.2) ──
# IPXE_ISCSI_CONTAINER=storager-iscsi
```

> **`base-iqn` is resolved dynamically at Worker boot**: the static value in `tftp/boot.ipxe.cfg` is only a fallback (placeholder).  
> When a Worker boots, iPXE fetches `/boot-vars` from the Control Plane, which returns the actual `base-iqn` of the storage node hosting the Worker's system disk  
> (the disk's IQN prefix — the disk NQN is the authoritative identifier, built from that node's `IPXE_NQN_BASE`; the IQN is derived from it), overriding the static fallback.  
> Each node's `IPXE_NQN_BASE` is therefore authoritative for the disks it hosts — it does not need to match the static value in `boot.ipxe.cfg`.

### 2.4 Register the Agent

Either of the two ways below:

**Option 1: WebUI (recommended)** — after the Controller is up, open the WebUI in a browser → **Agents** page → "+ Add Agent":

1. Enter the Agent ID (unique, e.g. `storage-lio-01`), the API URL (`base_url`: `http://host.docker.internal:4840` when co-located with the Controller, otherwise `http://<storage-node-IP>:4840`), and the Token (same as `IPXE_AGENT_TOKEN`; `${ENV}` environment-variable placeholders are supported).
2. Click "Probe" to auto-fetch the backend type / roles / tags / data-plane address and other parameters.
3. Confirm the "iSCSI data-plane" address is reachable by Workers (the probe derives it from the base_url hostname by default; change it to this node's LAN IP for remote deployments) → click "Add" to finish registration (written to `agents.yml`; takes part in scheduling immediately).

**Option 2: Edit `agents.yml` directly** — in the Controller’s `control_plane/config/agents.yml`, register this node (one entry per node):

```yaml
agents:
  storage-lio-01:                  # Agent ID (unique)
    base_url: http://host.docker.internal:4840   # Co-located with Controller; for remote deployment use http://<storage-node-IP>:4840
    iscsi_server: 192.168.80.3     # The address Workers will actually use to connect to iSCSI (this node’s IP)
    token: <same as IPXE_AGENT_TOKEN>
    role:
      disk: true                   # Disk capability (LIO does not support ISO optical drive; cd must be false)
      cd: false
    tags:
      - storage
      - lio        # use - nvmet for the nvmet backend (auto-detected by probing)
    enabled: true
```

Multi-node deployment: repeat 2.1–2.3 on each storage node and append a record in `agents.yml` (with a different Agent ID) (or add one entry per node on the Agents page when using the WebUI).

### 2.5 Start the Storage Node

```bash
# iSCSI backend (stgt / lio, per 2.2):
cd storager/iscsi && docker compose --env-file ../.env up -d
# NVMe-oF backend (per 2.2.1):
cd storager/nvmeof && docker compose --env-file ../.env up -d
```

### 2.6 Verification

```bash
curl http://localhost:4840/healthz            # Agent liveness
# WebUI → Agents page, confirm the Agent status is online (live)
# nvmet backend: additionally verify the host service:
curl http://localhost:4841/healthz            # ready when it returns {"status":"ok","configfs":true}
```

> Note: Agent status confirmation and all subsequent page operations are covered in the *WebUI User Guide*.

---

## Step 3: Deployment Checklist

| Service | Port | Verification |
|---|---|---|
| dnsmasq (DHCP/TFTP) | 67/69/UDP | Worker obtains an IP and loads iPXE on boot |
| Control Plane | 4839 | `curl http://localhost:4839/healthz` |
| HTTPS Boot Chain | 443 | `openssl s_client -connect <IP>:443 -brief` succeeds; machines boot through the trust chain |
| WebUI | 4838 | Accessible in a browser |
| iSCSI Agent | 4840 | `curl http://localhost:4840/healthz`; Agent appears online on the WebUI Agents page |
| iSCSI Backend | 3260 | After creating a disk in the WebUI, the target appears on the Workers page |
| nvmet Host Service (optional) | 4841 | `curl http://localhost:4841/healthz` returns `configfs:true` (only needed for the nvmet backend) |

Once the environment is ready, proceed to golden-image creation and diskless rollout ↓

* **WebUI**: *WebUI User Guide* (page functions & core workflows)
* **Windows**: *Windows Diskless Quick Deployment (Golden-Image Clone)*
* **Debian-family**: *Debian-family Diskless Quick Deployment (Golden-Image Clone)*