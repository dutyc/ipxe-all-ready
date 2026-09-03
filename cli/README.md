# kurrent CLI

Kurrent 控制面命令行工具（kubectl 同构，2026-08-31）。零第三方依赖（`net/http` + `encoding/json`），单二进制分发，覆盖集群生命周期闭环（kubeadm 同构）：**`config print` 生成声明模板 → `init` 控制面初始化 → `token create` 签发引导凭据 → `join` 节点侧加入**。声明式配置（`yml` 是唯一输入，CLI 只负责校验与收敛启动——配置即声明、CLI 即工具）。

## 构建

```bash
cd cli
go build -o kurrent .        # 单二进制（约 9.6 MB）；版本号发版时注入，见下方

# 发版构建（版本号注入 + 交叉编译示例）：
#   go build -ldflags "-X main.version=v0.3.0" -o kurrent .

# 可选：全局安装（此后任意目录直接用 kurrent 命令，部署指南即此形态）
sudo install -m 0755 kurrent /usr/local/bin/kurrent
```

## 配置

```bash
# 方式一：命令行全局选项
./kurrent --server https://cp/api/cp --token <KURRENT_CP_TOKEN> agents list

# 方式二：环境变量兜底（与全局选项二选一）
export KURRENT_CP_URL=http://127.0.0.1:4839     # 默认即 http://127.0.0.1:4839
export KURRENT_CP_TOKEN=<token>                 # 控制面 Bearer token（WebUI 设置页可查）
./kurrent agents list
```

- `--server` 默认 `http://127.0.0.1:4839`（控制面直连）；经 nginx 入口传 `https://<host>/api/cp`
- `--token` 控制面 Bearer token；缺省时控制面开发模式（`KURRENT_CP_TOKEN` 为空）放行

## 命令

```text
kurrent [--server URL] [--token T] <group> <verb> [args]

  agents list [--no-live] [-o table|json]    列出 Agent（含存活探测）
  agents get <id>                             查看单个 Agent
  agents add <id> --base-url URL [--role disk,cd] [--storager-ip IP] [--tags a,b] [--disabled]
  agents edit <id> --base-url URL [...]       更新 Agent（全量覆盖，参数同 add）
  agents remove <id>                          删除 Agent 台账（含母盘标签）
  agents probe --base-url URL                 探测 Agent 能力（不落盘）
  token create [--cp-url URL]                签发集群级通用 bootstrap token（kubeadm token
                                              create 同构：不绑节点，TTL 内可复用，输出带地址的
                                              join 命令——--cp-url 或从 --server 推导）
  config print init-defaults|node-defaults   输出声明模板（kubeadm config print 同构；
                                              重定向为 control_plane/kurrent.yaml 或
                                              storager/kurrent.yaml 后编辑）
  init [--config PATH] [--dir PATH]          控制面初始化：校验声明并收敛启动控制面
                                              （默认读 control_plane/kurrent.yaml，kubeadm
                                              init 同构；--config 指定其他声明文件则应用之）
  join <cp-url> [--config PATH] [--token T] [--dir PATH]
                                              节点侧加入（kubeadm join <endpoint> 同构）：
                                              声明 kurrent.yaml 缺失自动生成、已存在则读入并
                                              同步地址，收敛启动 agent（幂等可重跑）
  workers list | workers get <id>             Worker 台账（只读）
  ops list [--limit N] [-o table|json]        操作审计日志（只读）
  version                                     输出版本号（发版构建 -ldflags 注入，如 v0.3.0）
```

位置参数与 `--key value` / `--key=value` / `--flag` 可任意混排（如 `agents add cli-test-01 --base-url https://x`）。

## 控制面初始化（kubeadm init 同构）

声明文件 `control_plane/kurrent.yaml` 即用户维护的权威配置（yml 是唯一输入）：

```bash
# 1) 生成带注释模板（与 kurrent.yaml.example 同源），编辑 spec.networking 五键（必填）
./kurrent config print init-defaults > control_plane/kurrent.yaml
$EDITOR control_plane/kurrent.yaml

# 2) 一条命令到运行态：校验声明 → 启动/重启控制面 → 等待 /healthz → 重启 dnsmasq 加载新 conf
./kurrent init
#    → 幂等可重跑：改声明后重跑即生效；--config 指向其他路径 = 应用该声明为控制面配置
```

## 一键加入流程（kubeadm join 同构）

```bash
# 1) 控制面：签发集群级通用 bootstrap token（不绑节点）；输出带控制面地址的 join 命令
./kurrent token create --cp-url https://192.168.1.10
#    → kurrent join https://192.168.1.10 --token a1b2c3.0123456789abcdef

# 2) 节点（存储服务器上，仓库根目录执行——命令已携带地址，粘贴即用）：
./kurrent join https://192.168.1.10 --token a1b2c3.0123456789abcdef
#    → storager/kurrent.yaml 缺失时按模板自动生成（url=命令地址、name=宿主机名、
#      backend nvmet、advertiseUrl 推导、diskDir/nqnBase 默认），已存在则读入合并并
#      同步地址（非 forbid：手工编辑保留；yml 即 kurrent.yaml 后续可编辑）
#    → bootstrap/agent.token（0600）+ .env 插值键 + docker compose 收敛启动 agent
#    仓库根以外执行需 --dir 指定 storager 目录

# 3) 验证：
./kurrent agents list
```

预置声明（可选）：`kurrent config print node-defaults > storager/kurrent.yaml` 生成带注释模板后编辑（改 backend/diskDir/advertiseUrl 等），再执行 join——join 读入并更新，手工字段保留。

要点：

- bootstrap token 为集群级通用引导凭据（`<6位>.<16位>`，TTL 默认 7 天，控制面只存 sha256 摘要）；**不绑节点**——节点身份由声明 `metadata.name` 自决（留空取宿主机名，kubelet Node 命名同构）+ enroll 自动登记；控制面地址由 join 命令携带（kubeadm join `<endpoint>` 同构，同步进声明 `spec.controlPlane.url`）
- token TTL 内可被**多次 enroll 复用**（kubeadm bootstrap token 不限制使用次数）；每次 `token create` 都是新签，旧 token 到期自然失效；token 不进 yml（引导凭据在独立文件 `storager/bootstrap/agent.token`，kubelet bootstrap-kubeconfig 同构）
- `nvmet-host` 组件凭据**不手工签发**：agent enroll 上报 `backend=nvmet` 时控制面派生随响应下发，agent 落盘 `storager/bootstrap/nvmet-host.token` 供其引导（能力上报驱动，签发不预知后端）
- enroll 自动登记时携带 `base_url`（声明 `spec.agent.advertiseUrl`，默认推导 `https://<cp-host>:4840`）与能力标签；特殊场景（NAT 等）编辑声明覆盖

## 输出

- 默认表格（`-o table`）；`-o json` 输出原始 JSON（便于 jq 管道）
- 空字段以 `-` 占位；退出码非 0 表示失败（错误信息输出到 stderr）

## 测试与回归

```bash
go vet ./... && go build -o kurrent .
# 全量回归（仓库根）：
.venv-linux/bin/python -m pytest tests/ -q
```
