# kurrent CLI

Kurrent 控制面命令行工具（kubectl 同构，2026-08-31）。零第三方依赖（`net/http` + `encoding/json`），单二进制分发，覆盖一键加入闭环：**签发 bootstrap token → 输出 join 命令 → 节点侧 `kurrent-join.sh` 自动加入**。

## 构建

```bash
cd cli
go build -o kurrent .        # 单二进制（约 9.6 MB）
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
  nodes token <id> [--nvmet] [--cp-url URL]   签发 bootstrap token 并输出 join 命令
  join <cp-url> <token> <id> [--nvmet-token T] [--advertise-url URL] [--backend B] [--dir PATH]
                                            节点侧一键加入（kubeadm join 同构，幂等）
  workers list | workers get <id>             Worker 台账（只读）
  ops list [--limit N] [-o table|json]        操作审计日志（只读）
```

位置参数与 `--key value` / `--key=value` / `--flag` 可任意混排（如 `agents add cli-test-01 --base-url https://x`）。

## 一键加入流程（kubeadm join 同构）

```bash
# 1) 控制面：签发 bootstrap token 并输出 join 命令（--nvmet 时双组件）
./kurrent nodes token storage-lio-01 --nvmet
#    → kurrent join https://cp storage-lio-01 a1b2c3.0123456789abcdef --nvmet-token ...

# 2) 节点（storage-01 上，仓库根目录执行）：
./kurrent join https://<cp-host> <token> storage-lio-01 --nvmet-token <nvmet-token>
#    → 幂等写入 storager/.env（KURRENT_AGENT_ID / BOOTSTRAP_TOKEN / CP_ENROLL_URL /
#      ADVERTISE_URL / PKI_HOST 等），docker compose up -d
#    → 容器启动 ensure_pki() 用 token 引导，控制面 enroll 自动登记 agents.yml（不在册自动建条目）
#    仓库根以外执行需 --dir 指定 storager 目录；无 Go 环境可用 ./kurrent-join.sh 等价替代

# 3) 验证：
./kurrent agents list
```

要点：

- bootstrap token 为一次性（`<6位>.<16位>`，7 天 TTL，控制面只存 sha256 摘要）；enroll 成功后即废，轮换走 mTLS
- 同一 agent/component 已有未用 token 时重复签发返回 409（明文不可恢复，须删除 `state/pki/bootstrap-tokens.yml` 对应条目后重发）
- `nvmet-host` 组件不自动登记（共享 agent_id，须 agent 组件先行在册）
- 控制面签发后 enroll 请求自动携带 `base_url`（节点 `KURRENT_ADVERTISE_URL`，默认推导 `https://<cp-host>:4840`），自动登记时写入 agents.yml

## 输出

- 默认表格（`-o table`）；`-o json` 输出原始 JSON（便于 jq 管道）
- 空字段以 `-` 占位；退出码非 0 表示失败（错误信息输出到 stderr）

## 测试与回归

```bash
go vet ./... && go build -o kurrent .
# 全量回归（仓库根）：
.venv-linux/bin/python -m pytest tests/ -q
bash tests/scripts/test_kurrent_join.sh
```
