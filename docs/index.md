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
- **Central Control Plane + Web UI** — A FastAPI control plane manages workers, iSCSI agents and LUNs through one unified API, with a web UI for identity registration, system disk creation and boot configuration.
- **Second-Level Boot** — Debian 12, Ubuntu 22.04 LTS and Windows 11 24H2 boot over the network in seconds via iPXE + iSCSI, from a single infrastructure.
- **No Black Boxes** — Built with debootstrap and dism++ instead of official installers (Subiquity/ADK). Every link of the boot chain stays transparent and fully controllable.
- **100% Open Source** — Everything is built on open-source components — iPXE, tgt/LIO, dnsmasq, FastAPI, VitePress. No vendor lock-in, fully auditable.
