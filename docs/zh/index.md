---
layout: home

hero:
  name: "iPXE-All-Ready"
  text: "零接触接入,插电即就绪"
  tagline: "基于 100% 开源工具链(iPXE + iSCSI)的企业级无状态计算基础设施底座 —— 配备中心控制面、Web 管理界面与零接触自动注册。"
  actions:
    - theme: brand
      text: "快速部署"
      link: "/zh/guide/quick-deploy/environment-deploy"
    - theme: alt
      text: "GitHub 仓库"
      link: "https://github.com/dutyc/ipxe-all-ready"

---

## 核心能力

- **零接触自动注册** — 新机器插电即可：控制面自动识别 MAC、分配主机名并写入台账，管理员挂上系统盘、设定默认系统后，机器自动进入目标系统，全程无需人工预注册。
- **一机多系统** — 一台 Worker 可挂载多块系统盘 —— Windows / Ubuntu / Debian / CentOS / ESXi，随时在线切换默认启动系统，全程无需触碰机器。
- **中心控制面 + Web UI** — FastAPI 控制面通过统一 API 管理 Worker、iSCSI Agent 与 LUN，Web 界面完成身份注册、系统盘创建与默认启动配置，全程可视化。
- **秒级启动** — Debian 12、Ubuntu 22.04 LTS 与 Windows 11 24H2 经 iPXE + iSCSI 网络秒级启动，一套底座全平台覆盖。
- **拒绝黑盒** — 基于 debootstrap 与 dism++ 绕过官方安装器(Subiquity/ADK)限制，引导链每一环都透明可控，真正的基础设施即代码。
- **100% 纯开源工具链** — iPXE、tgt/LIO、dnsmasq、FastAPI、VitePress 全部基于开源组件构成，无厂商锁定，完整可审计。
