# iPXE-All-Ready

![Cloud Native](https://img.shields.io/badge/Cloud%20Native-True%20Cloud%20Native-18181b) [![Stars](https://img.shields.io/github/stars/dutyc/ipxe-all-ready)](https://github.com/dutyc/ipxe-all-ready/stargazers) [![Release](https://img.shields.io/github/v/release/dutyc/ipxe-all-ready)](https://github.com/dutyc/ipxe-all-ready/releases) [![License](https://img.shields.io/github/license/dutyc/ipxe-all-ready)](LICENSE) [![Docs](https://img.shields.io/badge/Docs-ipxe.lecreate.asia-2563eb)](https://ipxe.lecreate.asia)

[中文版](./README.zh-CN.md) | [English](./README.md)

**iPXE-All-Ready** is a cloud-native stateless computing platform built entirely on open-source components (iPXE + iSCSI + FastAPI + React). It pushes statelessness down to the compute layer itself: compute nodes hold no persistent state — identity, OS, and data are granted externally by the network and the control plane. A node comes alive the moment a cable is plugged in: it reports its fingerprint and joins the device pool automatically, then a few clicks in the Web UI bind it to a Worker, clone a system disk and set the default OS.

Read our manifesto: **[about/en/Manifesto.md](./about/en/Manifesto.md)** — *Our Definition of Cloud Native* (Chinese original: [about/zh/Manifesto.md](./about/zh/Manifesto.md)).

----

## Architecture

The control plane / data plane separation and the three roles — Controller, iSCSI Server, Worker — are detailed in **[about/en/ARCHITECTURE.md](./about/en/ARCHITECTURE.md)** (中文: [about/zh/ARCHITECTURE.md](./about/zh/ARCHITECTURE.md)).

## Quick Start

```bash
git clone https://github.com/dutyc/ipxe-all-ready
cd ipxe-all-ready

cp control_plane/control_plane.env.example control_plane/control_plane.env
cp dnsmasq/dnsmasq.conf.example dnsmasq/dnsmasq.conf
cp dnsmasq/dhcp-hosts.conf.example dnsmasq/dhcp-hosts.conf
# Adapt dnsmasq.conf: NIC name, subnet, gateway
docker compose up -d
```

* Web UI: `http://<controller-ip>:4838`
* Control Plane API: `http://<controller-ip>:4839`

Storage-node deployment and worker master-image clones are covered by the step-by-step [deployment runbooks](https://ipxe.lecreate.asia/guide/quick-deploy/environment-deploy).

## Key Features

New machines report their fingerprints and join the device pool on first boot; a few clicks in the Web UI bind them to a Worker and assign a system disk and a default OS. One worker can carry multiple system disks — Windows, Ubuntu, Debian, CentOS, ESXi — and switch between them online, with Debian 11/12/13, Ubuntu 22.04/24.04/26.04 and Windows 11 23H2/24H2/25H2 validated end-to-end over iPXE + iSCSI. There is no database: every control-plane state file is diff-able and manually repairable, and every capability is exposed as REST — the Web UI is just one client.

## Documentation

Docs site: **[ipxe.lecreate.asia](https://ipxe.lecreate.asia)** | **[中文文档](https://ipxe.lecreate.asia/zh/)**

- [Quick Deploy Runbooks](https://ipxe.lecreate.asia/guide/quick-deploy/environment-deploy) — environment setup, Windows & Debian master-image clones
- [API Reference](https://ipxe.lecreate.asia/guide/api/control-plane-api) — full endpoint contracts
- [Exploration](https://ipxe.lecreate.asia/guide/preface) — architecture deep-dives, Ch1–Ch4
- [Barriers We Have Broken Through](./about/en/Barriers.md) — a record of every technical wall we conquered

## Firmware Repo

The iPXE firmware at the bottom of the boot chain is built by our companion repo **[iPXE-Stateless](https://github.com/dutyc/ipxe-stateless)** — two sides of the same philosophy: this repo makes compute stateless, the firmware repo makes boot firmware stateless.

## Roadmap

A cross-platform, cross-architecture cloud-native meta-protocol: one stateless semantics, self-similarly nested across bare metal and hypervisors. See **[ROADMAP.md](./about/en/ROADMAP.md)**.

## Community & Contributing

Star / Watch / Discussions / PRs are all welcome. This project embraces AI-assisted development, with one hard requirement: **the AI can write the syntax, but architecture understanding must come from a human brain.** Please read [AI_POLICY.md](./about/en/AI_POLICY.md) before submitting a PR.

## License

[Apache License 2.0](./LICENSE)

## Star History

<a href="https://www.star-history.com/?repos=dutyc%2Fipxe-all-ready&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=dutyc/ipxe-all-ready&type=date&theme=dark&legend=top-left&sealed_token=zkQGmbPm0yH3EjnLTKc1DTe9hOaLnAeUdZlSlo92lycj2vyTy9VkyIW-uvH3P09ByCS5CiBI8QnhVbVNFyM211tGwSJ1yp7qE6ZsukdPCxJWkopIpVQepMXjrDwOAVENpL87Tr8qmmIYxQy6DawB8PaqrlfuVmGZPdnh9fPfJ8GtvnCIwkENEeVPSVp7" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=dutyc/ipxe-all-ready&type=date&legend=top-left&sealed_token=zkQGmbPm0yH3EjnLTKc1DTe9hOaLnAeUdZlSlo92lycj2vyTy9VkyIW-uvH3P09ByCS5CiBI8QnhVbVNFyM211tGwSJ1yp7qE6ZsukdPCxJWkopIpVQepMXjrDwOAVENpL87Tr8qmmIYxQy6DawB8PaqrlfuVmGZPdnh9fPfJ8GtvnCIwkENEeVPSVp7" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=dutyc/ipxe-all-ready&type=date&legend=top-left&sealed_token=zkQGmbPm0yH3EjnLTKc1DTe9hOaLnAeUdZlSlo92lycj2vyTy9VkyIW-uvH3P09ByCS5CiBI8QnhVbVNFyM211tGwSJ1yp7qE6ZsukdPCxJWkopIpVQepMXjrDwOAVENpL87Tr8qmmIYxQy6DawB8PaqrlfuVmGZPdnh9fPfJ8GtvnCIwkENEeVPSVp7" />
 </picture>
</a>
