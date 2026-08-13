# 架构

![架构设计](../../assets/architecture.svg)

三个角色，沿 **控制面 / 数据面** 清晰切分：

- **Controller（控制器）** — 集群大脑。运行控制面 HTTP 服务（Worker 生命周期编排、Agent 调度、存储台账、dnsmasq 绑定、启动变量投影）与 DHCP/TFTP/HTTP 引导服务，全部容器化。
- **iSCSI Server（存储节点）** — 块存储。每节点运行一个 API Agent，经 docker.sock 驱动本地 stgt/LIO 后端执行控制面指令；后端差异封装在 Agent 内部。
- **Worker（算力节点）** — 无本地盘的无状态计算节点。PXE 引导、挂载 iSCSI 系统盘、运行操作系统；块读写直走 iSCSI 数据面，不经过控制面。
