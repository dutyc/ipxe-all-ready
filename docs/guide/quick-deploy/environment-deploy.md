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

Storage Node — iscsi-server/docker-compose.yml (Data Plane, can be co-located with Controller)
├── ipxe-iscsi            iSCSI backend (3260, host network, choose stgt or LIO)
└── ipxe-agent            Agent API (4840), receives Control Plane scheduling, operates local backend
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

### 1.4.1 Auto-register Switch (optional; on by default)

A new-MAC device reporting its fingerprint is auto-admitted into the **device pool** (zero-touch; enabled by default). To turn it off (e.g. during a mass machine rollout where you want to register machines manually first), there are two ways:

**Option 1: Fixed at deploy time (env var)** — append to `control_plane/control_plane.env`; takes effect at container startup:

```env
# false = disable auto-registration (new MACs get an empty script and wait for manual registration)
IPXE_CP_AUTO_REGISTER=false
```

**Option 2: Runtime toggle (WebUI button / API)** — switch anytime after deployment; takes effect immediately and persists (`state/settings.json`, survives restarts), taking precedence over the env var:

- WebUI: the "Auto-register" switch in the Devices (device pool) page toolbar (dark = on, light = off)
- API: `PUT /settings/auto-register` (see API Reference 5.1)

> The switch only affects **new MACs**: when off, new devices report fingerprints without entering the pool — pool them manually via "Register device" / "Register to Pool" on the Devices page or `POST /devices`, then bind them to a Worker with the bind wizard; existing pooled devices are unaffected.

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

## Step 2: Deploy the Storage Node (Agent + iSCSI Backend)

> Perform this section once on each storage node; if co-located with the Controller, just run it locally.

### 2.1 Prepare the img Storage Directory (Determines Clone Speed)

Edit `iscsi-server/docker-compose.yml` and change the **host-side path** of both volume mappings to the actual directory where this node stores img files (edit **both** the `ipxe-iscsi` and `ipxe-agent` service blocks — they **must match**; the in-container path `/home/iscsi_img` stays unchanged and corresponds to `IPXE_DISK_DIR` in 2.3):

```yaml
# ipxe-iscsi service block
      - /pool1/iscsi_img:/home/iscsi_img   # change the host dir as needed, e.g. /data/iscsi_img
# ipxe-agent service block
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

Edit `iscsi-server/docker-compose.yml` and **choose one** backend service block to enable (the container is named `ipxe-iscsi` in both cases; you cannot enable both simultaneously):

| Backend | Location | Characteristics |
|---|---|---|
| `stgt` | Uncomment the `ipxe-stgt` service block and comment out the `ipxe-lio` block | User-space, supports mounting ISO as a virtual optical drive (`role.cd`), friendly to constrained environments |
| `lio` | Uncomment the `ipxe-lio` service block and comment out the `ipxe-stgt` block | Kernel-space, production-grade disk performance (recommended for system disks) |

### 2.3 Configure `.env`

Edit `iscsi-server/.env`:

```env
IPXE_ISCSI_CONTAINER=ipxe-iscsi
IPXE_DISK_DIR=/home/iscsi_img              # Disk directory inside the container (matches the host storage dir set in 2.1)
IPXE_IQN_BASE=iqn.2026-07.com.controller   # This node's IQN prefix (authoritative): disk IQNs are built from it; /boot-vars returns it for disks hosted here
IPXE_BACKEND=lio                           # Must match the choice in 2.2 (stgt / lio)
IPXE_AGENT_TOKEN=<generate a token>        # Generate: openssl rand -hex 32
TZ=Asia/Shanghai
```

> **IQN is resolved dynamically at Worker boot**: the `base-iqn` in `tftp/boot.ipxe.cfg` is only a static fallback (placeholder).  
> When a Worker boots, iPXE fetches `/boot-vars` from the Control Plane, which returns the actual `base-iqn` of the storage node hosting the Worker's system disk  
> (the disk's IQN prefix, derived from that node's `IPXE_IQN_BASE`), overriding the static fallback.  
> Each node's `IPXE_IQN_BASE` is therefore authoritative for the disks it hosts — it does not need to match the static value in `boot.ipxe.cfg`.

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
      - lio
    enabled: true
```

Multi-node deployment: repeat 2.1–2.3 on each storage node and append a record in `agents.yml` (with a different Agent ID) (or add one entry per node on the Agents page when using the WebUI).

### 2.5 Start the Storage Node

```bash
cd iscsi-server
docker compose up -d
```

### 2.6 Verification

```bash
curl http://localhost:4840/healthz            # Agent liveness
# WebUI → Agents page, confirm the Agent status is online (live)
```

> Note: Agent status confirmation and all subsequent page operations are covered in the *WebUI User Guide*.

---

## Step 3: Deployment Checklist

| Service | Port | Verification |
|---|---|---|
| dnsmasq (DHCP/TFTP) | 67/69/UDP | Worker obtains an IP and loads iPXE on boot |
| Control Plane | 4839 | `curl http://localhost:4839/healthz` |
| WebUI | 4838 | Accessible in a browser |
| iSCSI Agent | 4840 | `curl http://localhost:4840/healthz`; Agent appears online on the WebUI Agents page |
| iSCSI Backend | 3260 | After creating a disk in the WebUI, the target appears on the Workers page |

Once the environment is ready, proceed to golden-image creation and diskless rollout ↓

* **WebUI**: *WebUI User Guide* (page functions & core workflows)
* **Windows**: *Windows Diskless Quick Deployment (Golden-Image Clone)*
* **Debian-family**: *Debian-family Diskless Quick Deployment (Golden-Image Clone)*