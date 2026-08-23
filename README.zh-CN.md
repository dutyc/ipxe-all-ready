# Kurrent (周流)

![Cloud Native](https://img.shields.io/badge/Cloud%20Native-True%20Cloud%20Native-18181b) [![Stars](https://img.shields.io/github/stars/dutyc/kurrent)](https://github.com/dutyc/kurrent/stargazers) [![Release](https://img.shields.io/github/v/release/dutyc/kurrent)](https://github.com/dutyc/kurrent/releases) [![License](https://img.shields.io/github/license/dutyc/kurrent)](LICENSE) [![Docs](https://img.shields.io/badge/Docs-https://example.com-2563eb)](https://example.com)

[中文版](./README.zh-CN.md) | [English](./README.md)

**Make bare metal flow.**
*周流六虚，上下无常。*

K8s 花了十年，让应用成为云。
而 Kurrent，让算力成为云。

*K8s orchestrates the containers. Kurrent orchestrates the compute.*

**Kurrent** 是一套云原生无状态裸金属交付范式。它将“无状态”贯彻到物理算力层本身：计算节点（Device）自身不持有任何持久状态，身份（Worker）、系统与数据均由网络和控制面外部授予。插上网线即活，算力脱离硬件束缚，如电流般在裸金属节点间自由周流。

----

## 架构

控制面 / 数据面分离与三个角色（Controller、Storager、Devices）详见 **[about/zh/ARCHITECTURE.md](./about/zh/ARCHITECTURE.md)**（English: [about/en/ARCHITECTURE.md](./about/en/ARCHITECTURE.md)）。

## 快速上手

```bash
git clone https://github.com/dutyc/kurrent
cd kurrent

cp control_plane/control_plane.env.example control_plane/control_plane.env
cp dnsmasq/dnsmasq.conf.example dnsmasq/dnsmasq.conf
cp dnsmasq/dhcp-hosts.conf.example dnsmasq/dhcp-hosts.conf
# 修改 dnsmasq.conf：网卡名、网段、网关
docker compose up -d
```

* Web 界面：`http://<controller-ip>:4838`
* 控制面 API：`http://<controller-ip>:4839`

存储节点部署与 Worker 母盘克隆，见分步式[部署手册](https://ipxe.lecreate.asia/zh/guide/quick-deploy/environment-deploy)。

## 核心特性: 算力周流，即插即用

新机器首启自动入设备池，WebUI 点几下即可绑定 Worker、分配系统盘与默认系统；一台 Worker 可挂载多块系统盘（Windows / Ubuntu / Debian / CentOS / ESXi）随时在线切换，Debian 11/12/13、Ubuntu 22.04/24.04/26.04、Windows 11 23H2/24H2/25H2 经 iPXE + iSCSI 全链路验证。不引入数据库，控制面状态全部为可 diff、可手工修复的文件；全部能力经 REST 开放，Web 界面只是其中一个客户端。

## 文档
施工中...

## 固件仓库

引导链底层的 iPXE 固件由配套仓库 **[iPXE-Stateless](https://github.com/dutyc/ipxe-stateless)** 构建——与 Kurrent 同一理念的一体两面：Kurrent 让算力无状态，固件仓库让引导固件无状态。

## 路线图

跨平台、跨架构的云原生元协议：一套无状态语义，在裸机与虚拟化层自相似地嵌套。完整规划见 **[ROADMAP.md](./about/en/ROADMAP.md)**。

## 社区与贡献

欢迎 Star / Watch / Discussions / Pull Requests。本项目拥抱 AI 辅助开发，但有一条硬性要求：**AI 可以写语法，架构必须由人脑理解**。提交 PR 前请阅读 [AI_POLICY.md](./about/zh/AI_POLICY.md)。

## 许可证

[Apache License 2.0](./LICENSE)

## Star History

<a href="https://www.star-history.com/?repos=dutyc%2Fkurrent&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=dutyc/kurrent&type=date&theme=dark&legend=top-left&sealed_token=zkQGmbPm0yH3EjnLTKc1DTe9hOaLnAeUdZlSlo92lycj2vyTy9VkyIW-uvH3P09ByCS5CiBI8QnhVbVNFyM211tGwSJ1yp7qE6ZsukdPCxJWkopIpVQepMXjrDwOAVENpL87Tr8qmmIYxQy6DawB8PaqrlfuVmGZPdnh9fPfJ8GtvnCIwkENEeVPSVp7" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=dutyc/kurrent&type=date&legend=top-left&sealed_token=zkQGmbPm0yH3EjnLTKc1DTe9hOaLnAeUdZlSlo92lycj2vyTy9VkyIW-uvH3P09ByCS5CiBI8QnhVbVNFyM211tGwSJ1yp7qE6ZsukdPCxJWkopIpVQepMXjrDwOAVENpL87Tr8qmmIYxQy6DawB8PaqrlfuVmGZPdnh9fPfJ8GtvnCIwkENEeVPSVp7" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=dutyc/kurrent&type=date&legend=top-left&sealed_token=zkQGmbPm0yH3EjnLTKc1DTe9hOaLnAeUdZlSlo92lycj2vyTy9VkyIW-uvH3P09ByCS5CiBI8QnhVbVNFyM211tGwSJ1yp7qE6ZsukdPCxJWkopIpVQepMXjrDwOAVENpL87Tr8qmmIYxQy6DawB8PaqrlfuVmGZPdnh9fPfJ8GtvnCIwkENEeVPSVp7" />
 </picture>
</a>
