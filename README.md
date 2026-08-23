# Kurrent

![Cloud Native](https://img.shields.io/badge/Cloud%20Native-True%20Cloud%20Native-18181b) [![Stars](https://img.shields.io/github/stars/dutyc/kurrent)](https://github.com/dutyc/kurrent/stargazers) [![Release](https://img.shields.io/github/v/release/dutyc/kurrent)](https://github.com/dutyc/kurrent/releases) [![License](https://img.shields.io/github/license/dutyc/kurrent)](LICENSE) [![Docs](https://img.shields.io/badge/Docs-https://example.com-2563eb)](https://example.com)

[中文版](./README.zh-CN.md) | [English](./README.md)

**Make bare metal flow.**

*周流六虚，上下无常。* — from the *I Ching*: currents flow through the six voids, above and below, without constancy.

K8s spent a decade making applications cloud-native.
Kurrent makes compute cloud-native.

*K8s orchestrates the containers. Kurrent orchestrates the compute.*

**Kurrent** is a cloud-native stateless bare-metal delivery paradigm. It pushes statelessness down to the physical compute layer itself: compute nodes (Devices) hold no persistent state — identity (Worker), OS, and data are granted externally by the network and the control plane. Plug in a cable and a node comes alive; compute is unshackled from hardware and flows freely across bare-metal nodes, like current itself.

Read our manifesto: **[about/en/Manifesto.md](./about/en/Manifesto.md)** — *Our Definition of Cloud Native* (Chinese original: [about/zh/Manifesto.md](./about/zh/Manifesto.md)).

----

## Architecture

The control plane / data plane separation and the three roles — Controller, Storager, Devices — are detailed in **[about/en/ARCHITECTURE.md](./about/en/ARCHITECTURE.md)** (中文: [about/zh/ARCHITECTURE.md](./about/zh/ARCHITECTURE.md)).

## Quick Start

```bash
git clone https://github.com/dutyc/kurrent
cd kurrent

cp control_plane/control_plane.env.example control_plane/control_plane.env
cp dnsmasq/dnsmasq.conf.example dnsmasq/dnsmasq.conf
cp dnsmasq/dhcp-hosts.conf.example dnsmasq/dhcp-hosts.conf
# Adapt dnsmasq.conf: NIC name, subnet, gateway
docker compose up -d
```

* Web UI: `http://<controller-ip>:4838`
* Control Plane API: `http://<controller-ip>:4839`

Storage-node deployment and worker master-image clones are covered by the step-by-step [deployment runbooks](https://ipxe.lecreate.asia/guide/quick-deploy/environment-deploy).

## Key Features: Compute That Flows, Plug-and-Play

New machines report their fingerprints and join the device pool on first boot; a few clicks in the Web UI bind them to a Worker and assign a system disk and a default OS. One worker can carry multiple system disks — Windows, Ubuntu, Debian, CentOS, ESXi — and switch between them online, with Debian 11/12/13, Ubuntu 22.04/24.04/26.04 and Windows 11 23H2/24H2/25H2 validated end-to-end over iPXE + iSCSI. There is no database: every control-plane state file is diff-able and manually repairable, and every capability is exposed as REST — the Web UI is just one client.

## Documentation

Under construction...

## Firmware Repo

The iPXE firmware at the bottom of the boot chain is built by our companion repo **[iPXE-Stateless](https://github.com/dutyc/ipxe-stateless)** — two sides of the same philosophy: this repo makes compute stateless, the firmware repo makes boot firmware stateless.

## Roadmap

A cross-platform, cross-architecture cloud-native meta-protocol: one stateless semantics, self-similarly nested across bare metal and hypervisors. See **[ROADMAP.md](./about/en/ROADMAP.md)**.

## Community & Contributing

Star / Watch / Discussions / PRs are all welcome. This project embraces AI-assisted development, with one hard requirement: **the AI can write the syntax, but architecture understanding must come from a human brain.** Please read [AI_POLICY.md](./about/en/AI_POLICY.md) before submitting a PR.

## License

[Apache License 2.0](./LICENSE)

## Star History

<a href="https://www.star-history.com/?repos=dutyc%2Fkurrent&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=dutyc/kurrent&type=date&theme=dark&legend=top-left&sealed_token=zkQGmbPm0yH3EjnLTKc1DTe9hOaLnAeUdZlSlo92lycj2vyTy9VkyIW-uvH3P09ByCS5CiBI8QnhVbVNFyM211tGwSJ1yp7qE6ZsukdPCxJWkopIpVQepMXjrDwOAVENpL87Tr8qmmIYxQy6DawB8PaqrlfuVmGZPdnh9fPfJ8GtvnCIwkENEeVPSVp7" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=dutyc/kurrent&type=date&legend=top-left&sealed_token=zkQGmbPm0yH3EjnLTKc1DTe9hOaLnAeUdZlSlo92lycj2vyTy9VkyIW-uvH3P09ByCS5CiBI8QnhVbVNFyM211tGwSJ1yp7qE6ZsukdPCxJWkopIpVQepMXjrDwOAVENpL87Tr8qmmIYxQy6DawB8PaqrlfuVmGZPdnh9fPfJ8GtvnCIwkENEeVPSVp7" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=dutyc/kurrent&type=date&legend=top-left&sealed_token=zkQGmbPm0yH3EjnLTKc1DTe9hOaLnAeUdZlSlo92lycj2vyTy9VkyIW-uvH3P09ByCS5CiBI8QnhVbVNFyM211tGwSJ1yp7qE6ZsukdPCxJWkopIpVQepMXjrDwOAVENpL87Tr8qmmIYxQy6DawB8PaqrlfuVmGZPdnh9fPfJ8GtvnCIwkENEeVPSVp7" />
 </picture>
</a>
