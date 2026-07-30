以下是当前 Agent 最新的完整 API 接口文档。

## 全局说明

**1. 鉴权机制（Token）**
除 `/healthz` 外，所有接口均受预共享 Token 保护。请求时必须在 Header 中携带：
```http
Authorization: Bearer <your-token>
```
*注：比对采用常量时间算法（防时序攻击），失败统一返回 `401 Unauthorized`，不回显 Token 详情，日志中亦不记录 Token 值。*

**2. IQN 规范与自动小写化**
- **Base 校验**：所有包含 `iqn` 的接口，传入的 IQN 必须以该 Agent 配置的 `IPXE_IQN_BASE` 为前缀（如 `iqn.2026-07.com.controller:`），否则直接返回 `400` 拒绝。
- **自动小写化**：为兼容 iSCSI 规范及 LIO 后端的强制行为，Agent 会将接收到的 IQN 及推导出的文件名**强制转为小写**。例如传入 `worker-99.Ubuntu`，实际生效的 IQN 和文件名均为 `worker-99.ubuntu`。

**3. 能力差异**
不同后端能力不同（如 LIO 不支持 CD 光驱）。调用 `POST /lun/cd` 前，建议先通过 `GET /capabilities` 确认当前 Agent 的 `cd` 字段是否为 `true`。

---

## 接口列表概览

| 方法 | 路径 | 说明 | 鉴权 |
|---|---|---|---|
| GET | `/healthz` | 健康检查（探活） | 否 |
| POST | `/lun/disk` | 创建磁盘 LUN（同步创建/克隆 .img 文件） | 是 |
| POST | `/lun/cd` | 挂载 ISO 为虚拟光驱 LUN | 是 |
| POST | `/lun/scan` | 扫描目录，批量重建 Target | 是 |
| DELETE | `/lun` | 删除 Target（可选连文件一起删除） | 是 |
| GET | `/lun` | 列出当前所有 Target 及 LUN | 是 |
| GET | `/capabilities` | 获取 Agent 及后端的能力自描述 | 是 |
| GET | `/logs` | 拉取操作日志（支持游标增量拉取） | 是 |

---

## 接口详情

### GET /healthz
**说明**：健康检查接口，不改变状态，无需 Token。
**返回**：
```json
{"status": "ok"}
```

### POST /lun/disk
**说明**：创建磁盘 LUN。Agent 会同步创建 `.img` 文件（从母盘克隆，或建空盘），然后调用底层 iSCSI 后端建 Target 并指向该文件。
**请求体**：
| 字段 | 必填 | 说明 |
|---|---|---|
| `iqn` | 是 | 目标 IQN（需匹配 Base，会被自动小写化） |
| `master` | 二选一 | 母盘文件名（在 iscsi_img 中），将使用 reflink（秒级）或普通拷贝 |
| `size` | 二选一 | 空盘大小（如 `"20G"`），将创建稀疏文件（truncate） |
| `filename` | 否 | 覆盖默认推导的文件名 |

**curl 示例**：
```bash
curl -s -X POST http://localhost:4841/lun/disk \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"iqn":"iqn.2026-07.com.controller:worker-02.Ubuntu","size":"20G"}'
```
**成功返回**（注意 iqn 已小写化）：
```json
{"iqn": "iqn.2026-07.com.controller:worker-02.ubuntu", "backing": "/home/iscsi_img/worker-02.ubuntu.img"}
```

### POST /lun/cd
**说明**：挂载已存在的 ISO 文件为虚拟光驱。
**请求体**：
| 字段 | 必填 | 说明 |
|---|---|---|
| `iso` | 是 | ISO 文件名（在 iscsi_img 中） |
| `iqn` | 否 | 目标 IQN。不传则自动生成 `base:完整iso文件名`（含 .iso 后缀） |

**curl 示例**：
```bash
curl -s -X POST http://localhost:4841/lun/cd \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"iso":"win11.iso"}'
```
**成功返回**：
```json
{"iqn": "iqn.2026-07.com.controller:win11.iso", "backing": "/home/iscsi_img/win11.iso"}
```
*注：若后端为 LIO，此接口将返回 `400`（LIO 不支持 CD 设备类型）。*

### POST /lun/scan
**说明**：扫描 `iscsi_img` 目录，将 `.img` 建为磁盘，`.iso` 建为光驱。已存在的 Target 会跳过。此逻辑亦会在 Agent 启动时自动执行（stgt 后端）。
**curl 示例**：
```bash
curl -s -X POST http://localhost:4841/lun/scan -H "Authorization: Bearer $TOKEN"
```
**成功返回**：
```json
{
  "created": [{"iqn": "iqn...:worker-02.ubuntu", "cd": false}],
  "skipped": ["iqn...:win11.iso"]
}
```

### DELETE /lun
**说明**：删除指定的 Target。
**Query 参数**：
| 参数 | 必填 | 说明 |
|---|---|---|
| `iqn` | 是 | 要删除的 Target IQN |
| `delete_file` | 否 | 默认 `false`。设为 `true` 时连同底层的 `.img` 文件一并删除 |

**curl 示例**：
```bash
curl -s -X DELETE -G \
  --data-urlencode 'iqn=iqn.2026-07.com.controller:worker-02.Ubuntu' \
  --data-urlencode 'delete_file=true' \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:4841/lun
```
**成功返回**：
```json
{"deleted": "iqn.2026-07.com.controller:worker-02.ubuntu", "delete_file": true}
```

### GET /lun
**说明**：列出当前所有 Target 及其挂载的 LUN。
**curl 示例**：
```bash
curl -s http://localhost:4841/lun -H "Authorization: Bearer $TOKEN"
```
**成功返回**：
```json
[
  {
    "iqn": "iqn.2026-07.com.controller:worker-02.ubuntu",
    "luns": [
      {"lun": 0, "backing": null},
      {"lun": 1, "backing": "/home/iscsi_img/worker-02.ubuntu.img"}
    ]
  }
]
```
*注：`lun: 0` 是 iSCSI 协议自带的 Controller LUN，无 backing path；`lun: 1` 是我们挂载的实际数据盘。*

### GET /capabilities
**说明**：获取当前 Agent 的自描述信息，用于 Control Plane 判断该节点的后端类型及支持的能力。
**curl 示例**：
```bash
curl -s http://localhost:4841/capabilities -H "Authorization: Bearer $TOKEN"
```
**成功返回**（以 stgt 为例）：
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

### GET /logs
**说明**：拉取操作日志（仅记录写操作及启动时的 auto-scan）。Control Plane 通过 `since` 参数实现增量拉取。
**Query 参数**：
| 参数 | 必填 | 说明 |
|---|---|---|
| `since` | 否 | 游标（行号 id）。拉取 `id > since` 的日志，默认 `0`（从头拉取） |
| `limit` | 否 | 单次拉取最大条数，默认 `1000` |

**curl 示例**：
```bash
curl -s 'http://localhost:4841/logs?since=5&limit=100' -H "Authorization: Bearer $TOKEN"
```
**成功返回**：
```json
{
  "next_cursor": 8,
  "entries": [
    {
      "id": 6,
      "ts": "2026-07-26T08:01:12.123456+00:00",
      "op": "disk",
      "req": {"iqn": "iqn...:worker-02.ubuntu", "size": "20G"},
      "result": "ok",
      "client": "192.168.1.5"
    },
    {
      "id": 7,
      "ts": "2026-07-26T08:05:00.000000+00:00",
      "op": "delete",
      "req": {"iqn": "iqn...:worker-02.ubuntu", "delete_file": true},
      "result": "ok",
      "client": "192.168.1.5"
    },
    {
      "id": 8,
      "ts": "2026-07-26T08:10:00.000000+00:00",
      "op": "cd",
      "req": {"iso": "win11.iso"},
      "result": "failed",
      "error": "lio backend does not support cd",
      "client": "192.168.1.5"
    }
  ]
}
```
*注：Control Plane 下次拉取时，传入 `since=8` 即可实现增量同步。*

---

## 错误码速查

| HTTP 状态码 | 触发场景 |
|---|---|
| **200** | 成功 |
| **400** | IQN 不匹配本 Agent 的 Base；缺少必要参数（如 disk 接口未传 master 和 size）；在 LIO 后端调用 `/lun/cd` |
| **401** | 未提供 Token，或 Token 校验失败 |
| **404** | 指定的母盘/ISO 文件不存在；要删除的 IQN 不存在 |
| **409** | 要创建的 .img 文件已存在；要创建的 IQN 已存在 |
| **500** | 底层 iSCSI 命令（tgtadm / targetcli）执行失败（返回体中带原始报错） |
| **503** | 未找到 iSCSI 容器，或 Docker 守护进程连接失败 |