---
layout: home

hero:
  name: "iPXE-All-Ready"
  text: "Zero to Ready. Plug and Boot."
  tagline: "Enterprise-grade, stateless computing infrastructure on 100% open-source iPXE + iSCSI toolchains — with a central control plane, a web management UI and zero-touch provisioning."
  actions:
    - theme: brand
      text: "Quick Deploy"
      link: "/guide/quick-deploy/environment-deploy"
    - theme: alt
      text: "View on GitHub"
      link: "https://github.com/dutyc/ipxe-all-ready"

---

## Core Features

- **Zero-Touch Provisioning** — Plug in a new machine and it registers itself: the control plane detects the MAC, assigns a hostname, and boots it into the target OS as soon as a system disk is attached — no pre-registration required.
- **Multi-OS per Worker** — One worker can host multiple system disks — Windows, Ubuntu, Debian, CentOS or ESXi — and switch the default boot OS on the fly, without ever touching the machine.
- **Master-Image Instant Cloning** — Prepare a golden image once, clone it endlessly: one click in the Web UI creates a worker disk from the master via reflink (copy-on-write), completing in seconds on btrfs. Debian 11/12/13, Ubuntu 22.04/24.04/26.04 and Windows 11 23H2/24H2/25H2 are covered end-to-end over iPXE + iSCSI, booting in seconds.
- **Bulk Deployment** — Batch-select workers on the Workers page to create or delete system disks for many machines at once: choosing a master from the dropdown auto-takes-over the workers to its storage node, with drag-and-drop / round-robin node assignment; new disks are set as the default OS, so bulk provisioning boots straight to the desktop.
- **Agent Direct Management & Online Editing** — A FastAPI control plane manages workers, Agents and LUNs through one unified API; the Web UI registers / edits Agents via a two-step probe (base_url, token, role, tags, enabled), manages iSCSI disks and ISO drives per Agent, and scales out storage nodes with disk scheduling by `role.disk`.
- **No Black Boxes** — Built with `debootstrap` and `dism++` instead of official installers (Subiquity / ADK). Every link of the boot chain stays transparent and fully controllable.
- **Files as the Source of Truth** — No database: `agents.yml`, `workers.yml`, `dhcp-hosts.conf` and `operations.jsonl` hold all control-plane state — diff-able and manually repairable.
- **100% Open Source** — Everything is built on open-source components — iPXE, stgt/LIO, dnsmasq, FastAPI, React, VitePress. No vendor lock-in, fully auditable.
