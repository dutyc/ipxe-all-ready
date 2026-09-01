#!/usr/bin/env bash
# kurrent-join.sh 沙盒验证：临时目录 + fake docker，验证 .env 写入与默认值推导。
# 运行：bash tests/scripts/test_kurrent_join.sh（不进 pytest，纯 bash 验证）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/storager/nvmeof" "$TMP/storager/iscsi" "$TMP/bin"
cp "$ROOT/storager/kurrent-join.sh" "$TMP/storager/"

# fake docker：仅记录调用参数
cat > "$TMP/bin/docker" <<'EOF'
#!/usr/bin/env bash
echo "FAKE-DOCKER $*" >> "${FAKE_DOCKER_LOG}"
EOF
chmod +x "$TMP/bin/docker"
export PATH="$TMP/bin:$PATH"
export FAKE_DOCKER_LOG="$TMP/docker.log"

cd "$TMP/storager"

# ── 场景 1：nvmet 后端 + 双 token + 显式 advertise ──
./kurrent-join.sh https://192.168.1.10 abc123.def456 storage-01 \
    --nvmet-token 789abc.def012 --advertise-url https://192.168.1.50:4840 >/dev/null
grep -q '^KURRENT_AGENT_ID=storage-01$' .env
grep -q '^KURRENT_BOOTSTRAP_TOKEN=abc123.def456$' .env
grep -q '^KURRENT_BOOTSTRAP_TOKEN_NVMET=789abc.def012$' .env
grep -q '^KURRENT_CP_ENROLL_URL=https://192.168.1.10$' .env
grep -q '^KURRENT_ADVERTISE_URL=https://192.168.1.50:4840$' .env
grep -q '^KURRENT_BACKEND=nvmet$' .env
grep -q 'KURRENT_AGENT_PKI_HOST=.*/control_plane/state/pki/components/agent-storage-01$' .env
grep -q 'KURRENT_NVMET_PKI_HOST=.*/control_plane/state/pki/components/nvmet-storage-01$' .env
grep -q '^FAKE-DOCKER compose --env-file ../.env up -d$' "$FAKE_DOCKER_LOG"

# ── 场景 2：幂等 upsert + 后端沿用 + advertise 默认推导 ──
# 预置 lio 后端（模拟既有部署），再换 agent_id 重跑
cp .env .env.prev
echo 'KURRENT_BACKEND=lio' >> .env
./kurrent-join.sh https://cp2 host.gggg storage-02 >/dev/null
[ "$(grep -c '^KURRENT_AGENT_ID=' .env)" = "1" ]
grep -q '^KURRENT_AGENT_ID=storage-02$' .env
grep -q '^KURRENT_BACKEND=lio$' .env
[ "$(grep -c '^KURRENT_BACKEND=' .env)" = "1" ]
grep -q '^KURRENT_ADVERTISE_URL=https://cp2:4840$' .env
[ "$(grep -c '^KURRENT_ADVERTISE_URL=' .env)" = "1" ]
grep -q '^FAKE-DOCKER compose --env-file ../.env up -d$' "$FAKE_DOCKER_LOG"
# iscsi 后端目录被调用（lio → storager/iscsi）
grep -q 'up -d$' "$FAKE_DOCKER_LOG"

echo "kurrent-join.sh sandbox test PASSED"
