#!/usr/bin/env bash
# kurrent-join.sh —— 存储节点一键加入控制面（kubeadm join 同构，2026-08-31）
#
# CLI 等价（推荐，行为完全一致）：kurrent join <cp-url> <bootstrap-token> <agent-id> \
#     [--nvmet-token <token>] [--advertise-url <url>] [--backend nvmet|stgt|lio]
# 本脚本为无 Go 环境节点的等价替代。
#
# 用法：
#   ./kurrent-join.sh <cp-url> <bootstrap-token> <agent-id> \
#       [--nvmet-token <token>] [--advertise-url <url>] [--backend nvmet|stgt|lio]
#
# 示例：
#   ./kurrent-join.sh https://192.168.1.10 69a163.xxxx storage-01 \
#       --nvmet-token 8b2f.xxxx --advertise-url https://192.168.1.50:4840
#
# 行为（幂等，可重复执行；仅更新本脚本管理的 .env 键，其余保留）：
#   1. 更新 storager/.env：组件身份/引导 token/控制面入口/证书挂载路径
#   2. 启动后端编排（nvmet: storager/nvmeof；stgt|lio: storager/iscsi）
#   3. 容器首次启动自动引导（bootstrap token → /enroll 换证书 → mTLS 起服），
#      控制面侧 enroll 自动登记（agents.yml），无需人工干预
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$SCRIPT_DIR/.env"

usage() {
    sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 1
}

# 幂等更新 .env 键：先删除所有既有匹配行再追加（键唯一，重复 join 不堆积）
upsert() {
    local key="$1" value="$2"
    touch "$ENV_FILE"
    if grep -q "^${key}=" "$ENV_FILE"; then
        sed -i "/^${key}=/d" "$ENV_FILE"
    fi
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
}

# ── 参数解析 ──
[ "$#" -lt 3 ] && usage
CP_URL="${1%/}"; TOKEN="$2"; AGENT_ID="$3"; shift 3

NVMET_TOKEN=""; ADVERTISE_URL=""; BACKEND=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --nvmet-token)  NVMET_TOKEN="${2:-}"; shift 2 ;;
        --advertise-url) ADVERTISE_URL="${2:-}"; shift 2 ;;
        --backend)      BACKEND="${2:-}"; shift 2 ;;
        *) echo "unknown option: $1" >&2; usage ;;
    esac
done

# ── 默认值推导 ──
CP_HOST="$(printf '%s' "$CP_URL" | sed -E 's|https?://([^/:]+).*|\1|')"
[ -n "$ADVERTISE_URL" ] || ADVERTISE_URL="https://${CP_HOST}:4840"
# 后端缺省沿用现有 .env，否则 nvmet（主协议）
if [ -z "$BACKEND" ] && grep -q '^KURRENT_BACKEND=' "$ENV_FILE" 2>/dev/null; then
    BACKEND="$(grep '^KURRENT_BACKEND=' "$ENV_FILE" | tail -1 | cut -d= -f2-)"
fi
[ -n "$BACKEND" ] || BACKEND="nvmet"
case "$BACKEND" in
    nvmet) COMPOSE_DIR="$SCRIPT_DIR/nvmeof" ;;
    stgt|lio) COMPOSE_DIR="$SCRIPT_DIR/iscsi" ;;
    *) echo "invalid backend: $BACKEND (nvmet|stgt|lio)" >&2; exit 1 ;;
esac

# ── 写 .env（仅本脚本管理的键）──
upsert KURRENT_AGENT_ID        "$AGENT_ID"
upsert KURRENT_BOOTSTRAP_TOKEN "$TOKEN"
upsert KURRENT_CP_ENROLL_URL   "$CP_URL"
upsert KURRENT_ADVERTISE_URL   "$ADVERTISE_URL"
upsert KURRENT_BACKEND         "$BACKEND"
# 证书宿主目录按 agent_id 隔离（compose 挂载插值；控制面与存储节点同机部署时生效）
upsert KURRENT_AGENT_PKI_HOST  "$PROJECT_ROOT/control_plane/state/pki/components/agent-$AGENT_ID"
if [ -n "$NVMET_TOKEN" ]; then
    upsert KURRENT_BOOTSTRAP_TOKEN_NVMET "$NVMET_TOKEN"
    upsert KURRENT_NVMET_PKI_HOST        "$PROJECT_ROOT/control_plane/state/pki/components/nvmet-$AGENT_ID"
fi

echo "==> kurrent-join: agent=$AGENT_ID backend=$BACKEND cp=$CP_URL"
echo "==> kurrent-join: starting $COMPOSE_DIR (compose --env-file ../.env)"
cd "$COMPOSE_DIR"
docker compose --env-file ../.env up -d

echo "==> kurrent-join: done. 容器首次启动会自动引导证书；"
echo "    控制面侧验证: kurrent agents list（或 WebUI「Agent 列表」看 health=ok）"
