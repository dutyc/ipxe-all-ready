# iPXE-All-Ready

![Cloud Native](https://img.shields.io/badge/Cloud%20Native-True%20Cloud%20Native-18181b) ![iPXE](https://img.shields.io/badge/iPXE-Network%20Boot-111111) ![iSCSI](https://img.shields.io/badge/iSCSI-Diskless%20Storage-0f766e) ![Control Plane](https://img.shields.io/badge/Control%20Plane-FastAPI-2563eb) ![Agent](https://img.shields.io/badge/Agent-STGT%20%2F%20LIO-7c3aed) ![dnsmasq](https://img.shields.io/badge/DHCP-dnsmasq-334155) ![License](https://img.shields.io/badge/License-Apache%202.0-green)

[中文版](./README.zh-CN.md) | [English](./README.md)

**iPXE-All-Ready** is a true cloud-native implementation built on a fully open-source toolchain (iPXE + iSCSI): it carries statelessness down to the compute layer itself — compute nodes hold no persistent state of their own; identity, OS, and data are granted externally by the network and the control plane, so nodes can be discarded, replaced, and rebuilt in an instant. A node with no local disk comes alive the moment a cable is plugged in: no manual pre-registration, no vendor lock-in.

**Our Manifesto:** [Manifesto.md](./Manifesto.md) — *My Definition of Cloud Native* (English; Chinese original: [Manifesto_zh-CN.md](./Manifesto_zh-CN.md)).

The project has evolved from a diskless-boot proof of concept into a complete control plane: new machines are auto-registered the moment they plug in, and adding a system disk or switching the default OS is a few clicks in the Web UI. **All truly means All. Ready truly means Production-Ready.**

## Architecture

![Architecture Design](./assets/architecture.svg)

Three roles with clearly separated responsibilities, following the **control plane / data plane** split:

* **Controller** — The brain of the cluster. Runs the Control Plane HTTP service (Worker lifecycle orchestration, Agent scheduling, storage ledger, `dnsmasq` bindings, boot-variable projection) plus DHCP/TFTP/HTTP boot services, all containerized.
* **iSCSI Server** — Provides block storage. Each node hosts an API Agent that executes Control Plane commands against a local stgt or LIO backend over `docker.sock`. Backend differences are encapsulated inside the Agent.
* **Worker** — A stateless compute node with no local disk. It PXE-boots, attaches its iSCSI system disk, and runs the OS. Block reads/writes go directly over the iSCSI data plane, never through the control plane.

## Key Features

- **Zero-touch provisioning** — New machines auto-register on first boot; a few clicks in the Web UI assigns a system disk and a default OS.
- **Multi-OS per worker** — One machine, multiple system disks (Windows / Ubuntu / Debian / CentOS / ESXi), switchable online without touching the hardware.
- **Instant-on boot** — Debian 11/12/13, Ubuntu 22.04/24.04/26.04 and Windows 11 23H2/24H2/25H2 validated end-to-end over iPXE + iSCSI.
- **No black boxes** — `debootstrap` and `dism++` bypass official installer limits (Subiquity / ADK); every link of the boot chain is transparent and auditable.
- **Files as the source of truth** — No database: `agents.yml`, `workers.yml`, `dhcp-hosts.conf`, and `operations.jsonl` are diff-able and manually repairable.
- **API-first** — Every Control Plane capability is exposed as REST; the Web UI itself is just a client of this API. Third-party systems and automation scripts are peers of the Web UI — integrate everything through the [API Reference](https://ipxe.lecreate.asia/guide/api/control-plane-api).
- **100% open-source toolchain** — iPXE, stgt/LIO, dnsmasq, FastAPI, React, VitePress. No vendor lock-in.

## Quick Start

> Prerequisites: a Linux host (Debian 12 / Ubuntu 22.04 recommended) with Docker Engine, used as the Controller node. Full environment planning (hardware baseline, network layout, storage layout) is covered in the [Environment Setup guide](https://ipxe.lecreate.asia/guide/quick-deploy/environment-deploy).

```bash
git clone https://github.com/dutyc/ipxe-all-ready
cd ipxe-all-ready

# 1. Adapt dnsmasq/dnsmasq.conf: NIC name, subnet, gateway
# 2. Prepare the Control Plane config (the repo tracks only *.env.example
#    templates, which carry full comments):
cp control_plane/control_plane.env.example control_plane/control_plane.env
#    - Optional: set IPXE_CP_TOKEN to enable API auth (keep it in sync
#      with the Web UI's VITE_CP_TOKEN)
docker compose up -d

# 3. (Optional) Rebuild the Web UI with a custom token:
#    cp webui/app/.env.example webui/app/.env && cd webui/app && npm run build

# 4. (Optional) Storage node: deploy the iscsi-server directory on it
#    cp iscsi-server/.env.example iscsi-server/.env
#    set IPXE_AGENT_TOKEN (must match the token of this node in agents.yml)
#    docker compose -f iscsi-server/docker-compose.yml up -d
```

* Web UI: `http://<controller-ip>:4838`
* Control Plane API: `http://<controller-ip>:4839` — open REST API, **directly callable by third-party systems and automation scripts** (auth / registration / disk provisioning / batch deploy / status queries; full contracts in the API Reference below)

Worker images are then delivered via the step-by-step runbooks below.

## Documentation

Full architecture deep-dives, per-OS deployment walkthroughs, and quick-deploy runbooks live on the dedicated docs site:

**[ipxe.lecreate.asia](https://ipxe.lecreate.asia)** | **[中文文档](https://ipxe.lecreate.asia/zh/)**

**Get started:**

* [Quick Deploy Runbooks](https://ipxe.lecreate.asia/guide/quick-deploy/environment-deploy) — step-by-step environment setup, Windows & Debian-family master-image clones
* [API Reference](https://ipxe.lecreate.asia/guide/api/control-plane-api) — full Control Plane & Agent endpoint contracts; start here for third-party integration
* [Exploration](https://ipxe.lecreate.asia/guide/preface) — architecture deep-dives, diskless boot principles, and the barriers we broke through (Ch1–Ch4 + Control Plane Capabilities + Barriers)

## Roadmap

The vision: a cross-platform, cross-architecture cloud-native meta-protocol spanning every compute layer — one stateless semantics, self-similarly nested across bare metal and hypervisors alike, compute bound to no specific hardware, cloud within cloud at every level. See **[ROADMAP.md](./ROADMAP.md)** for the full plan (Phase 1–4).

**Phase 1 — Core System Breakthrough is complete**: Debian 11/12/13, Ubuntu 22.04/24.04/26.04 and Windows 11 23H2/24H2/25H2 full chains validated, with the distributed control plane and Web UI already landed.

## Community & Contributing

We are packaging every deep pitfall we conquered into a turnkey, rigorously tested, complete solution. You can **Star** / **Watch** this project, explore technical directions in **Discussions**, or submit **Pull Requests** to contribute — please read the requirements below before submitting a PR.

**On AI assistance**: this project does not oppose AI-assisted code generation — in fact, iPXE-All-Ready itself was built in collaboration with AI assistants such as Qwen, Codex, and DeepSeek, and we are open to AI-assisted development. But for community contributions, we have a clear requirement: **contributors must deeply understand the project's overall architecture themselves, not just let the AI understand it**.

This does not mean mastering every line of iPXE syntax, nor hand-writing iSCSI login PDUs, but understanding:

- Why the control plane and data plane are separated, and where the boundary lies
- The complete iPXE boot chain from DHCP to kernel takeover
- How the dynamic variable chain spans the entire boot cycle
- The "files as the source of truth" philosophy — why no database
- The position and impact of the iSCSI session keep-alive mechanism in the whole chain

**The AI can handle the syntax, but architecture understanding must be done by a human brain.** If the design logic behind a PR cannot be clearly articulated by its contributor, we will reject the merge. If you don't understand the architecture yet, filing an Issue or Idea is more valuable than submitting a PR — an Issue is a signal that doesn't pollute the codebase; a PR is a solution that requires depth.

Our full AI-assistance policy statement, including the real-world case behind it (the complete PR #3 record), lives in [AI_POLICY.md](./AI_POLICY.md) (English; Chinese original: [AI_POLICY_zh-CN.md](./AI_POLICY_zh-CN.md)).

This is not a rejection of tools, but a commitment to the project's long-term quality. We welcome every companion willing to understand the architecture, and thank every user who provides real usage feedback.

## License

This project is licensed under the [Apache License 2.0](./LICENSE).

## Star History

<a href="https://www.star-history.com/?repos=dutyc%2Fipxe-all-ready&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=dutyc/ipxe-all-ready&type=date&theme=dark&legend=top-left&sealed_token=zjOknpQELRo5XRHVkZyVFbzpe3vGpw7134qQQpvRcCNi89-GWZKA9NmUisZj8-0rngIFYnEpjMkDcTyDcbpjeoo6F4-CNJ-_Jn5DDmYZQElWO7WgDPbJuA" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=dutyc/ipxe-all-ready&type=date&legend=top-left&sealed_token=zjOknpQELRo5XRHVkZyVFbzpe3vGpw7134qQQpvRcCNi89-GWZKA9NmUisZj8-0rngIFYnEpjMkDcTyDcbpjeoo6F4-CNJ-_Jn5DDmYZQElWO7WgDPbJuA" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=dutyc/ipxe-all-ready&type=date&legend=top-left&sealed_token=zjOknpQELRo5XRHVkZyVFbzpe3vGpw7134qQQpvRcCNi89-GWZKA9NmUisZj8-0rngIFYnEpjMkDcTyDcbpjeoo6F4-CNJ-_Jn5DDmYZQElWO7WgDPbJuA" />
 </picture>
</a>
