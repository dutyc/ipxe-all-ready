# Environment Setup

> **Status: English translation in progress — this page is a structural placeholder.**
> The complete Chinese version is authoritative for now: [项目环境部署](https://ipxe.lecreate.asia/zh/guide/quick-deploy/environment-deploy)

One-time deployment of the Controller (control plane) and storage nodes (Agent + iSCSI backend), platform-independent. Once the environment is ready, proceed to the master-image walkthroughs.

## Structure

- **Deployment topology** — the two compose files: root `docker-compose.yml` (Controller) + `iscsi-server/docker-compose.yml` (storage node), not one unit
- **Step 1: Deploy the Controller** — clone, dnsmasq subnet, TFTP firmware, optional API token, startup & verification
- **Step 2: Deploy a storage node** — backend choice (stgt / LIO), `.env` (the `IPXE_IQN_BASE` contract), `agents.yml` registration, startup & verification
- **Step 3: Deployment checklist** — ports 67/69, 4839, 4838, 4840, 3260

---
*This page will be translated in full. Until then, the Chinese version linked above is authoritative.*
