# Agent API Reference

本文档整理当前 Agent 已实现的 HTTP 接口，面向 Control Plane 调用与部署联调使用。

本地验证 Base URL：

```text
http://localhost:4841
```

实际部署时请替换为对应存储节点上的 Agent 地址。

## 1. Agent 职责

Agent 是每台 iSCSI Server 上的本地执行器。Control Plane 只通过 HTTP 调用 Agent；Agent 再进入本机 iSCSI 服务端容器，执行 `tgtadm` 或 `targetcli`，完成 Target、LUN、backing file 的创建、扫描、删除与查询。

当前支持两个后端：

| 后端 | 作用 | ISO 虚拟光驱 | 持久化方式 |
|---|---|---:|---|
| `stgt` | 用户态 iSCSI Target，适合 ISO 光驱与安装期链路 | 支持 | 启动时扫描镜像目录重建 |
| `lio` | Linux 内核态 iSCSI Target，适合生产磁盘 LUN | 不支持 | `targetcli saveconfig` |

## 2. 全局规则

### 2.1 鉴权

除 `GET /healthz` 外，所有接口都需要 Bearer token：

```http
Authorization: Bearer <IPXE_AGENT_TOKEN>
```

缺少 token 或 token 错误时返回：

```text
401 unauthorized
```

Token 比对采用常量时间算法（防时序攻击）；失败统一返回 `401`，不回显 Token 详情，日志中亦不记录 Token 值。

### 2.2 IQN Base 校验

凡是请求中带 `iqn` 的接口，Agent 都会检查它是否以本 Agent 的 base IQN 开头。

base IQN 来自 `.env`：

```text
IPXE_IQN_BASE=iqn.2026-07.com.controller
```

合法示例：

```text
iqn.2026-07.com.controller:worker-02.Ubuntu
```

不匹配时返回：

```text
400 iqn base mismatch
```

### 2.3 镜像目录

Agent 使用 `.env` 中的 `IPXE_DISK_DIR` 作为镜像目录，通常是：

```text
/home/iscsi_img
```

约定：

- `.img` 文件作为磁盘 backing
- `.iso` 文件作为虚拟光驱 backing
- Agent 可以创建 `.img`
- Agent 不创建 ISO，只挂载已存在的 ISO

### 2.4 Query 中的 IQN

IQN 含有冒号。作为 query 参数传递时，建议使用 `curl -G --data-urlencode`，不要手拼 URL。

## 3. 接口总览

| 方法 | 路径 | 说明 | 鉴权 |
|---|---|---|---|
| `GET` | `/healthz` | 健康检查 | 否 |
| `POST` | `/lun/disk` | 创建磁盘 LUN，并同步创建 `.img` | 是 |
| `POST` | `/lun/cd` | 挂载 ISO 为虚拟光驱 LUN | 是 |
| `POST` | `/lun/scan` | 扫描镜像目录，批量创建 target | 是 |
| `DELETE` | `/lun` | 删除 target，可选删除 backing 文件 | 是 |
| `GET` | `/lun` | 列出当前 target | 是 |
| `GET` | `/capabilities` | 查询 Agent 后端能力 | 是 |
| `GET` | `/logs` | 查询操作日志 | 是 |

## 4. GET /healthz

健康检查接口。唯一不需要 token 的接口。

请求：

```bash
curl -s http://localhost:4841/healthz
```

响应：

```json
{"status":"ok"}
```

## 5. POST /lun/disk

创建磁盘 LUN，并创建对应 `.img` backing 文件。

### 5.1 请求体

```json
{
  "iqn": "iqn.2026-07.com.controller:worker-02.Ubuntu",
  "master": "_tpl_Ubuntu.img",
  "size": "20G",
  "filename": "worker-02.Ubuntu.img"
}
```

字段说明：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `iqn` | 是 | Control Plane 拼好的 Target IQN，必须匹配本 Agent 的 base IQN |
| `master` | 二选一 | 母盘文件名，必须已存在于 `IPXE_DISK_DIR` |
| `size` | 二选一 | 创建空稀疏盘的大小，例如 `20G` |
| `filename` | 否 | 覆盖默认 backing 文件名 |

`master` 和 `size` 必须至少传一个。若两者都传，当前实现优先使用 `master`。

### 5.2 文件命名

如果不传 `filename`，Agent 会从 IQN 后缀推导文件名：

```text
iqn.2026-07.com.controller:worker-02.Ubuntu
-> worker-02.Ubuntu.img
```

### 5.3 创建流程

1. 校验 IQN base。
2. 计算 backing 文件路径。
3. 如果 backing 已存在，返回 `409`。
4. 如果传入 `master`，优先使用 reflink 克隆，失败后回退到普通复制。
5. 如果传入 `size`，创建 sparse file。
6. 调用后端创建 iSCSI target 和 LUN。
7. 如果 target 创建失败，删除刚创建的 backing 文件。

### 5.4 示例：从母盘克隆

```bash
TOKEN=$(grep IPXE_AGENT_TOKEN .env | cut -d= -f2)

curl -s -X POST http://localhost:4841/lun/disk \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"iqn":"iqn.2026-07.com.controller:worker-02.Ubuntu","master":"_tpl_Ubuntu.img"}'
```

响应：

```json
{
  "iqn": "iqn.2026-07.com.controller:worker-02.ubuntu",
  "backing": "/home/iscsi_img/worker-02.ubuntu.img"
}
```

注意：当前实现会把用于创建 target 的 IQN 转为小写。

### 5.5 示例：创建空盘

```bash
curl -s -X POST http://localhost:4841/lun/disk \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"iqn":"iqn.2026-07.com.controller:worker-99.Ubuntu","size":"20G"}'
```

## 6. POST /lun/cd

把已有 ISO 挂载为虚拟光驱 LUN。

### 6.1 后端限制

此接口依赖 `stgt --device-type cd`。

| 后端 | 行为 |
|---|---|
| `stgt` | 支持 |
| `lio` | 返回 `400 lio backend does not support cd` |

### 6.2 请求体

```json
{
  "iso": "worker-01.Windows.iso",
  "iqn": "iqn.2026-07.com.controller:worker-01.Windows.iso"
}
```

字段说明：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `iso` | 是 | ISO 文件名，必须已存在于 `IPXE_DISK_DIR` |
| `iqn` | 否 | 指定 Target IQN；不传则使用 `base_iqn:iso文件名` |

### 6.3 示例

```bash
curl -s -X POST http://localhost:4841/lun/cd \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"iso":"worker-01.Windows.iso"}'
```

响应：

```json
{
  "iqn": "iqn.2026-07.com.controller:worker-01.windows.iso",
  "backing": "/home/iscsi_img/worker-01.Windows.iso"
}
```

## 7. POST /lun/scan

扫描 `IPXE_DISK_DIR`，根据现有 `.img` 和 `.iso` 文件批量创建 target。

### 7.1 命名规则

| 文件类型 | IQN 后缀规则 | 示例 |
|---|---|---|
| `.img` | 去掉 `.img` 扩展名 | `worker-02.Ubuntu.img` -> `base:worker-02.Ubuntu` |
| `.iso` | 保留完整文件名 | `worker-01.Windows.iso` -> `base:worker-01.Windows.iso` |

### 7.2 后端行为

| 后端 | 行为 |
|---|---|
| `stgt` | 扫描 `.img` 和 `.iso`；`.iso` 创建为 CD-ROM |
| `lio` | 扫描 `.img`；跳过 `.iso` |

### 7.3 示例

```bash
curl -s -X POST http://localhost:4841/lun/scan \
  -H "Authorization: Bearer $TOKEN"
```

响应：

```json
{
  "created": [
    {
      "iqn": "iqn.2026-07.com.controller:worker-02.ubuntu",
      "cd": false
    },
    {
      "iqn": "iqn.2026-07.com.controller:worker-01.windows.iso",
      "cd": true
    }
  ],
  "skipped": []
}
```

## 8. DELETE /lun

删除指定 IQN 的 target。可选是否连 backing 文件一起删除。

### 8.1 Query 参数

| 参数 | 必填 | 默认 | 说明 |
|---|---:|---|---|
| `iqn` | 是 | 无 | 要删除的 Target IQN |
| `delete_file` | 否 | `false` | 是否删除 backing 文件 |

### 8.2 只删除 target

```bash
curl -s -X DELETE -G \
  --data-urlencode 'iqn=iqn.2026-07.com.controller:worker-99.Ubuntu' \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:4841/lun
```

响应：

```json
{
  "deleted": "iqn.2026-07.com.controller:worker-99.ubuntu",
  "delete_file": false
}
```

### 8.3 删除 target 并删除 backing 文件

```bash
curl -s -X DELETE -G \
  --data-urlencode 'iqn=iqn.2026-07.com.controller:worker-99.Ubuntu' \
  --data-urlencode 'delete_file=true' \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:4841/lun
```

## 9. GET /lun

列出当前 iSCSI target。

请求：

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:4841/lun
```

`stgt` 响应示例：

```json
[
  {
    "tid": 1,
    "iqn": "iqn.2026-07.com.controller:worker-02.ubuntu",
    "luns": [
      {
        "lun": 0,
        "backing": null
      },
      {
        "lun": 1,
        "backing": "/home/iscsi_img/worker-02.Ubuntu.img"
      }
    ]
  }
]
```

说明：

- `stgt` 会显示 LUN 0，这是控制 LUN，`backing` 为 `null`
- 实际磁盘或 ISO 通常是 LUN 1
- `lio` 返回结构不包含 `tid`，只包含 `iqn` 与 `luns`

## 10. GET /capabilities

查询 Agent 当前后端能力。

请求：

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:4841/capabilities
```

`stgt` 示例：

```json
{
  "backend": "stgt",
  "cd": true,
  "persistent": "auto-scan on startup",
  "base_iqn": "iqn.2026-07.com.controller",
  "clone": "reflink (FICLONE) -> shutil.copy fallback",
  "empty_disk": "truncate (sparse)"
}
```

`lio` 示例：

```json
{
  "backend": "lio",
  "cd": false,
  "persistent": "saveconfig (auto-load on start)",
  "base_iqn": "iqn.2026-07.com.controller",
  "clone": "reflink (FICLONE) -> shutil.copy fallback",
  "empty_disk": "truncate (sparse)"
}
```

## 11. GET /logs

读取 Agent 操作日志。

日志是 append-only JSON Lines，文件路径来自：

```text
IPXE_LOG_FILE=/var/log/ipxe-agent/ops.jsonl
```

### 11.1 Query 参数

| 参数 | 必填 | 默认 | 说明 |
|---|---:|---|---|
| `since` | 否 | `0` | 只返回 id 大于该值的日志 |
| `limit` | 否 | `1000` | 最多返回多少条 |

### 11.2 示例

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:4841/logs?since=1&limit=100' | python3 -m json.tool
```

响应：

```json
{
  "next_cursor": 12,
  "entries": [
    {
      "id": 12,
      "ts": "2026-07-27T12:00:00+00:00",
      "op": "disk",
      "req": {
        "iqn": "iqn.2026-07.com.controller:worker-99.Ubuntu",
        "master": null,
        "size": "1G",
        "filename": null
      },
      "result": "ok",
      "client": "127.0.0.1"
    }
  ]
}
```

会记录的写操作包括：

- `disk`
- `cd`
- `scan`
- `delete`
- `auto_scan`

日志不会记录 token。

## 12. 错误码

| 状态码 | 常见触发条件 |
|---:|---|
| `400` | IQN base 不匹配；请求缺少必要字段；当前后端不支持该操作 |
| `401` | 缺少 token 或 token 错误 |
| `404` | master 文件不存在；ISO 文件不存在；target 不存在 |
| `409` | backing 文件已存在；IQN 已存在 |
| `500` | `tgtadm` 或 `targetcli` 执行失败 |
| `503` | iSCSI 容器不存在；Docker 连接失败 |

## 13. Control Plane 调用建议

推荐 Control Plane 按以下顺序接入 Agent：

1. 调用 `GET /healthz` 做存活检查。
2. 调用 `GET /capabilities` 判断后端能力。
3. 对系统盘调用 `POST /lun/disk`。
4. Windows 安装期如需 ISO 光驱，只调度到 `cd=true` 的 Agent。
5. 写操作后通过 `GET /logs?since=<cursor>` 拉取审计日志。

## 14. 部署注意事项

当前 Agent 通过 Docker socket 操作本机 iSCSI 容器：

```text
/var/run/docker.sock:/var/run/docker.sock
```

因此 Agent 应只暴露在控制网或可信管理网络中，不应直接暴露到公网。
