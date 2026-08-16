# iPXE-All-Ready

![Cloud Native](https://img.shields.io/badge/Cloud%20Native-True%20Cloud%20Native-18181b) [![Stars](https://img.shields.io/github/stars/dutyc/ipxe-all-ready)](https://github.com/dutyc/ipxe-all-ready/stargazers) [![Release](https://img.shields.io/github/v/release/dutyc/ipxe-all-ready)](https://github.com/dutyc/ipxe-all-ready/releases) [![License](https://img.shields.io/github/license/dutyc/ipxe-all-ready)](LICENSE) [![Docs](https://img.shields.io/badge/Docs-ipxe.lecreate.asia-2563eb)](https://ipxe.lecreate.asia)

[中文版](./README.zh-CN.md) | [English](./README.md)

**iPXE-All-Ready** 是基于纯开源组件（iPXE + iSCSI + FastAPI + React）的云原生无状态计算平台，把无状态贯彻到算力层本身：计算节点自身不持有任何持久状态——身份、系统与数据均由网络和控制面外部授予，插上网线即活：上报指纹自动进入设备池，WebUI 绑定 Worker、克隆系统盘、设定默认系统后即自动进入目标系统。

阅读我们的宣言：**[about/zh/Manifesto.md](./about/zh/Manifesto.md)** —《我们的云原生》（English: [about/en/Manifesto.md](./about/en/Manifesto.md)）。

----

## 架构

控制面 / 数据面分离与三个角色（Controller、iSCSI Server、Worker）详见 **[about/zh/ARCHITECTURE.md](./about/zh/ARCHITECTURE.md)**（English: [about/en/ARCHITECTURE.md](./about/en/ARCHITECTURE.md)）。

## 快速上手

```bash
git clone https://github.com/dutyc/ipxe-all-ready
cd ipxe-all-ready

cp control_plane/control_plane.env.example control_plane/control_plane.env
cp dnsmasq/dnsmasq.conf.example dnsmasq/dnsmasq.conf
cp dnsmasq/dhcp-hosts.conf.example dnsmasq/dhcp-hosts.conf
# 修改 dnsmasq.conf：网卡名、网段、网关
docker compose up -d
```

* Web 界面：`http://<controller-ip>:4838`
* 控制面 API：`http://<controller-ip>:4839`

存储节点部署与 Worker 母盘克隆，见分步式[部署手册](https://ipxe.lecreate.asia/zh/guide/quick-deploy/environment-deploy)。

## 核心特性

新机器首启自动入设备池，WebUI 点几下即可绑定 Worker、分配系统盘与默认系统；一台 Worker 可挂载多块系统盘（Windows / Ubuntu / Debian / CentOS / ESXi）随时在线切换，Debian 11/12/13、Ubuntu 22.04/24.04/26.04、Windows 11 23H2/24H2/25H2 经 iPXE + iSCSI 全链路验证。不引入数据库，控制面状态全部为可 diff、可手工修复的文件；全部能力经 REST 开放，Web 界面只是其中一个客户端。

## 文档

文档站：**[ipxe.lecreate.asia](https://ipxe.lecreate.asia/zh/)** | **[English](https://ipxe.lecreate.asia)**

- [快速部署手册](https://ipxe.lecreate.asia/zh/guide/quick-deploy/environment-deploy) — 环境搭建、Windows 与 Debian 母盘克隆
- [API 参考](https://ipxe.lecreate.asia/zh/guide/api/control-plane-api) — 完整接口契约
- [探索系列](https://ipxe.lecreate.asia/zh/guide/preface) — 架构深潜，第一~四章
- [我们已经攻克的壁垒](./about/zh/Barriers.md) — 攻坚记录（仅 GitHub 展示）

## 固件仓库

引导链底层的 iPXE 固件由配套仓库 **[iPXE-Stateless](https://github.com/dutyc/ipxe-stateless)** 构建——与主仓库同一理念的一体两面：主仓库让算力无状态，固件仓库让引导固件无状态。

## 路线图

跨平台、跨架构的云原生元协议：一套无状态语义，在裸机与虚拟化层自相似地嵌套。完整规划见 **[ROADMAP.md](./about/en/ROADMAP.md)**。

## 社区与贡献

欢迎 Star / Watch / Discussions / Pull Requests。本项目拥抱 AI 辅助开发，但有一条硬性要求：**AI 可以写语法，架构必须由人脑理解**。提交 PR 前请阅读 [AI_POLICY.md](./about/zh/AI_POLICY.md)。

## 许可证

[Apache License 2.0](./LICENSE)

## Star History

<a href="https://www.star-history.com/?repos=dutyc%2Fipxe-all-ready&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=dutyc/ipxe-all-ready&type=date&theme=dark&legend=top-left&sealed_token=zkQGmbPm0yH3EjnLTKc1DTe9hOaLnAeUdZlSlo92lycj2vyTy9VkyIW-uvH3P09ByCS5CiBI8QnhVbVNFyM211tGwSJ1yp7qE6ZsukdPCxJWkopIpVQepMXjrDwOAVENpL87Tr8qmmIYxQy6DawB8PaqrlfuVmGZPdnh9fPfJ8GtvnCIwkENEeVPSVp7" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=dutyc/ipxe-all-ready&type=date&legend=top-left&sealed_token=zkQGmbPm0yH3EjnLTKc1DTe9hOaLnAeUdZlSlo92lycj2vyTy9VkyIW-uvH3P09ByCS5CiBI8QnhVbVNFyM211tGwSJ1yp7qE6ZsukdPCxJWkopIpVQepMXjrDwOAVENpL87Tr8qmmIYxQy6DawB8PaqrlfuVmGZPdnh9fPfJ8GtvnCIwkENEeVPSVp7" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=dutyc/ipxe-all-ready&type=date&legend=top-left&sealed_token=zkQGmbPm0yH3EjnLTKc1DTe9hOaLnAeUdZlSlo92lycj2vyTy9VkyIW-uvH3P09ByCS5CiBI8QnhVbVNFyM211tGwSJ1yp7qE6ZsukdPCxJWkopIpVQepMXjrDwOAVENpL87Tr8qmmIYxQy6DawB8PaqrlfuVmGZPdnh9fPfJ8GtvnCIwkENEeVPSVp7" />
 </picture>
</a>
