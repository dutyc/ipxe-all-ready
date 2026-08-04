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

- **零接触自动注册（Zero-touch Provisioning）** — 新机器插电即被识别与注册：控制面自动识别 MAC、分配主机名并写入台账，管理员在 Web 界面挂盘、设定默认系统后，机器自动进入目标系统，全程零人工预注册。
- **一机多系统** — 一台 Worker 可挂载多块系统盘 —— Windows / Ubuntu / Debian / CentOS / ESXi，随时在线切换默认启动系统，无需触碰机器。
- **母盘克隆秒级交付** — 母盘（Golden Image）制备一次、克隆无限：WebUI 一键从母盘克隆出系统盘，btrfs 存储上走 reflink（写时复制）秒级完成；Debian 11/12/13、Ubuntu 22.04/24.04/26.04 与 Windows 11 23H2/24H2/25H2 经 iPXE + iSCSI 全链路覆盖，网络秒级启动。
- **批量部署** — Workers 页批量勾选即可一次为多台机器创建 / 删除系统盘：母盘下拉选择后自动接管到母盘所在存储节点，支持拖拽 / 均摊分配节点，新盘自动设为默认启动，批量上线直通桌面。
- **Agent 直管与在线编辑** — FastAPI 控制面通过统一 API 管理 Worker、Agent 与 LUN；WebUI 两步探测注册 / 编辑 Agent（在线改 base_url、token、角色、标签与启用状态），Agent 页直管 iSCSI 磁盘与 ISO 光驱；存储节点横向扩展，建盘按 `role.disk` 自动调度。
- **拒绝黑盒** — 基于 `debootstrap` 与 `dism++` 绕过官方安装器（Subiquity / ADK）限制，引导链每一环都透明可控，真正的基础设施即代码。
- **文件即真相** — 不引入数据库：`agents.yml`、`workers.yml`、`dhcp-hosts.conf`、`operations.jsonl` 承载全部控制面状态，透明、可 diff、可手工修复。
- **100% 纯开源工具链** — iPXE、stgt/LIO、dnsmasq、FastAPI、React、VitePress 全部基于开源组件构成，无厂商锁定，完整可审计。
