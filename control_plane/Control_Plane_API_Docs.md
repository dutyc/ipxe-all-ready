# Control Plane API Reference

本文档描述当前 Control Plane 已实现的 HTTP 接口、请求参数、返回结构，以及可直接复制执行的 `curl` 测试命令。

Control Plane 是 Controller 节点上的常驻 HTTP 服务，负责：

- 新增 Worker
- 删除 Worker
- 查询 Worker 台账
- 查询 Agent 状态
- 维护 `dnsmasq/dhcp-hosts.conf`
- 调用 Agent 创建或删除 iSCSI LUN

它不负责 iPXE 菜单生成、不负责静态文件分发、不直接操作 `tgtadm`/`targetcli`。

---

## 1. 基本信息

### 1.1 Base URL

本地示例：

```text
http://localhost:4839
```

如果你通过别的端口或域名暴露，请替换为实际地址。

### 1.2 环境变量文件

容器通过 compose 读取：

```yaml
env_file:
  - ./control_plane/control_plane.env
```

Control Plane 代码不会主动解析 `.env` 文件，而是通过 `os.getenv(...)` 读取容器环境变量。

### 1.3 鉴权

如果环境变量 `IPXE_CP_TOKEN` 为空，则 Control Plane 不启用鉴权。  
如果设置了 `IPXE_CP_TOKEN`，则除了 `GET /healthz` 外，其余所有接口都必须带：

```http
Authorization: Bearer <IPXE_CP_TOKEN>
```

示例：

```bash
export BASE_URL=http://localhost:4839
export TOKEN=replace-me
```

带鉴权的 curl 写法：

```bash
curl -s "$BASE_URL/workers" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 2. 文件即真相

当前 Control Plane 的状态文件分工如下：

| 文件 | 含义 |
|---|---|
| `config/agents.yml` | Agent 节点清单与调度角色 |
| `state/workers.yml` | Worker 存储台账 |
| `dnsmasq/dhcp-hosts.conf` | `MAC -> hostname` 绑定唯一真相 |
| `state/operations.jsonl` | 控制面操作轨迹 |

说明：

- `workers.yml` **不记录 MAC**；
- compose 需要把 `dnsmasq` 目录挂进容器，不要只挂载单个 `dhcp-hosts.conf` 文件；Control Plane 写入时会用临时文件做 atomic replace；
- `dnsmasq/dhcp-hosts.conf` 一行一个绑定，格式固定为：

```text
00:0c:29:b9:8b:2d,worker-01
```

---

## 3. 接口概览

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/healthz` | 健康检查 |
| `GET` | `/boot-vars` | iPXE 启动变量动态注入，不鉴权 |
| `GET` | `/agents` | 查询 Agent 列表与能力 |
| `POST` | `/workers` | 创建 Worker |
| `GET` | `/workers` | 列出 Worker |
| `GET` | `/workers/{worker_id}` | 查询单个 Worker |
| `GET` | `/workers/{worker_id}/status` | 查询 Worker 台账与实时状态 |
| `DELETE` | `/workers/{worker_id}` | 删除 Worker |
| `GET` | `/operations` | 读取操作日志 |

---

## 4. GET /healthz

### 说明

健康检查接口，不改状态，不需要鉴权。

### curl

```bash
curl -s "$BASE_URL/healthz"
```

### 成功返回

```json
{"status":"ok"}
```

---

## 5. GET /boot-vars

### 说明

给 iPXE 启动脚本读取 per-worker 启动变量。该接口不鉴权，定位与 `/healthz` 类似：只读、无副作用、只暴露受控内网启动所需变量。

Control Plane 会根据 `mac` 或 `hostname` 查：

1. `dnsmasq/dhcp-hosts.conf`
2. `state/workers.yml`
3. `config/agents.yml`

然后返回该 Worker 对应的 iSCSI Server、默认菜单项和菜单超时。

默认返回 iPXE 脚本片段，兼容性最好，可以直接被 iPXE `chain` 执行。加 `format=json` 时返回 JSON，方便人工调试。

### 字段来源

`/boot-vars` 不维护单独状态，也不会写任何文件。它返回的是现有 inventory 的只读投影：

| 返回字段 | 来源 |
|---|---|
| `base_iqn` | `workers.yml` 中该 Worker 的 `disk.iqn` 去掉最后一个 `:` 后的前缀 |
| `iscsi_server` | `workers.yml` 中该 Worker 的 `disk.agent` -> `agents.yml` 中该 Agent 的 `iscsi_server` |
| `menu_default` | 优先使用 `workers.yml` 中的 `boot.menu_default`；未设置时默认等于该 Worker 的 `os` |
| `menu_timeout` | 优先使用 `workers.yml` 中的 `boot.menu_timeout`；未设置时使用环境变量 `IPXE_CP_BOOT_MENU_TIMEOUT` |

查找 Worker 的规则：

```text
mac -> dnsmasq/dhcp-hosts.conf -> hostname -> workers.yml
hostname -> workers.yml
```

如果同时传 `mac` 和 `hostname`，优先使用 `mac` 在 `dnsmasq/dhcp-hosts.conf` 中查到的 hostname；查不到时再使用请求里的 `hostname`。

### 默认启动项规则

创建 Worker 时 **不需要必须传入默认启动哪个系统**。

普通情况下，`POST /workers` 传入的 `os` 就会成为默认启动项：

```text
os=ubuntu  -> menu_default=ubuntu
os=debian  -> menu_default=debian
os=windows -> menu_default=windows
```

只有需要覆盖默认行为时，才在创建 Worker 时传 `boot.menu_default` 或 `boot.menu_timeout`。例如让 Windows 制作机默认进入安装菜单，而不是直接进入 `windows` 菜单项。

### Query 参数

| 参数 | 必填 | 默认值 | 说明 |
|---|---:|---|---|
| `mac` | 否 | 无 | MAC 地址。支持 iPXE 的 `mac:hexraw` 格式，如 `000c29b98b2d`，也支持 `00:0c:29:b9:8b:2d` |
| `hostname` | 否 | 无 | 主机名，如 `worker-01` |
| `format` | 否 | `ipxe` | `ipxe` 或 `json` |

`mac` 和 `hostname` 至少建议传一个。iPXE 端推荐两个都传：

```text
/boot-vars?mac=${mac:hexraw}&hostname=${hostname}
```

### iPXE 格式 curl

```bash
curl -s "$BASE_URL/boot-vars?mac=000c29b98b2d&hostname=worker-01"
```

成功返回示例：

```ipxe
#!ipxe
# boot vars for worker-01
set base-iqn iqn.2026-07.com.controller
set iscsi-server 192.168.1.5
set menu-default ubuntu
set menu-timeout 5000
```

Worker 不存在时返回空脚本：

```ipxe
#!ipxe
# no per-worker boot vars found
```

### JSON 格式 curl

```bash
curl -s "$BASE_URL/boot-vars?mac=000c29b98b2d&hostname=worker-01&format=json"
```

成功返回示例：

```json
{
  "base_iqn": "iqn.2026-07.com.controller",
  "iscsi_server": "192.168.1.5",
  "menu_default": "ubuntu",
  "menu_timeout": 5000
}
```

Worker 不存在时返回：

```json
{}
```

### iPXE 接入方式

`tftp/boot.ipxe.cfg` 末尾会拉取该端点：

```ipxe
chain --autofree http://${controller_ip}:4839/boot-vars?mac=${mac:hexraw}&hostname=${hostname} || goto vars-done
set base-iscsi iscsi:${iscsi-server}:::1:${base-iqn}
isset ${hostname} && set initiator-iqn ${base-iqn}:${hostname} || set initiator-iqn ${base-iqn}:${mac}

:vars-done
```

`menu.ipxe` 不需要修改。

### Agent 数据面地址

`/boot-vars` 返回的是 Worker 连接 iSCSI 的 **数据面地址**，不是 Agent HTTP API 地址。建议在 `config/agents.yml` 里显式配置：

```yaml
agents:
  storage-lio-01:
    base_url: http://host.docker.internal:4840
    iscsi_server: 192.168.1.5
```

如果没有配置 `iscsi_server`，Control Plane 会退回使用 `base_url` 的 host 部分；但当 `base_url` 是 `host.docker.internal` 时，这个值不适合给物理 Worker 使用。

---

## 6. GET /agents

### 说明

列出 `config/agents.yml` 里配置的 Agent。默认会实时访问 Agent 的 `/healthz` 和 `/capabilities`。

### Query 参数

| 参数 | 必填 | 默认值 | 说明 |
|---|---:|---|---|
| `live` | 否 | `true` | 是否实时探测 Agent 状态与能力 |

### curl

实时探测：

```bash
curl -s "$BASE_URL/agents?live=true" \
  -H "Authorization: Bearer $TOKEN"
```

只看配置，不探测：

```bash
curl -s "$BASE_URL/agents?live=false" \
  -H "Authorization: Bearer $TOKEN"
```

### 成功返回示例

```json
[
  {
    "id": "storage-lio-01",
    "base_url": "http://10.0.0.11:4841",
    "role": {
      "disk": true,
      "cd": false
    },
    "enabled": true,
    "tags": [
      "storage",
      "lio"
    ],
    "health": "ok",
    "capabilities": {
      "backend": "lio",
      "cd": false,
      "persistent": "saveconfig (auto-load on start)",
      "base_iqn": "iqn.2026-07.com.controller",
      "clone": "reflink (FICLONE) -> shutil.copy fallback",
      "empty_disk": "truncate (sparse)"
    }
  }
]
```

---

## 7. POST /workers

### 说明

创建一台 Worker。Control Plane 会：

1. 校验 `worker_id`、`hostname`、`mac`
2. 选择合适的 Agent
3. 拼接 IQN 和 backing filename
4. 调用 Agent 创建磁盘 target
5. 如为 Windows 且指定 `windows_iso`，额外创建 CD target
6. 写入 `state/workers.yml`
7. 写入 `dnsmasq/dhcp-hosts.conf`
8. 通过 Docker 向 `ipxe-dnsmasq` 容器发送 HUP：

```bash
docker exec ipxe-dnsmasq killall -HUP dnsmasq
```

### 请求体字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `worker_id` | 是 | Worker 编号。会自动转为小写。允许字母、数字、点、下划线、短横线 |
| `mac` | 是 | Worker 网卡 MAC 地址，格式如 `00:0c:29:b9:8b:2d` |
| `os` | 是 | 操作系统标识，如 `ubuntu`、`debian`、`windows` |
| `disk` | 是 | 磁盘来源配置 |
| `hostname` | 否 | 主机名。不传时默认等于 `worker_id` |
| `arch` | 否 | 架构。不传时默认 `x86_64` |
| `windows_iso` | 否 | Windows 安装期 ISO 文件名，仅允许 `os=windows` 时传入 |
| `boot` | 否 | iPXE 菜单默认项与超时配置；不传则由 `/boot-vars` 按 OS 和全局默认值推导 |

### `disk` 字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `type` | 是 | `master` 或 `empty` |
| `name` | 条件必填 | 当 `type=master` 时必填。表示母盘文件名 |
| `size` | 条件必填 | 当 `type=empty` 时必填。表示空白盘大小，如 `40G` |

### `boot` 字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `menu_default` | 否 | iPXE 主菜单默认项，如 `ubuntu`、`debian`、`windows`、`exit` |
| `menu_timeout` | 否 | iPXE 菜单超时，单位毫秒，如 `5000` |

不传 `boot` 时：

- `menu_default` 默认使用 Worker 的 `os` 字段；
- `menu_timeout` 默认使用 `IPXE_CP_BOOT_MENU_TIMEOUT`，当前默认 `5000`。

因此大多数 Worker 不需要传 `boot`。例如：

```json
{
  "worker_id": "worker-01",
  "mac": "00:0c:29:b9:8b:2d",
  "os": "ubuntu",
  "disk": {
    "type": "empty",
    "size": "10G"
  }
}
```

这个 Worker 的 `/boot-vars` 会自动返回：

```ipxe
set menu-default ubuntu
set menu-timeout 5000
```

只有要覆盖菜单行为时才传 `boot`：

```json
{
  "worker_id": "worker-01",
  "mac": "00:0c:29:b9:8b:2d",
  "os": "ubuntu",
  "disk": {
    "type": "empty",
    "size": "10G"
  },
  "boot": {
    "menu_default": "exit",
    "menu_timeout": 0
  }
}
```

Windows 安装期如果希望默认进入安装菜单，可以这样传：

```json
{
  "worker_id": "worker-win-build",
  "mac": "00:0c:29:b9:8b:11",
  "os": "windows",
  "disk": {
    "type": "empty",
    "size": "80G"
  },
  "windows_iso": "Win11_24H2.iso",
  "boot": {
    "menu_default": "menu-install",
    "menu_timeout": 3000
  }
}
```

### 7.1 从母盘克隆创建 Worker

#### 请求体

```json
{
  "worker_id": "worker-01",
  "mac": "00:0c:29:b9:8b:2d",
  "os": "ubuntu",
  "disk": {
    "type": "master",
    "name": "_tpl_ubuntu_2204.img"
  }
}
```

#### curl

```bash
curl -s -X POST "$BASE_URL/workers" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "worker_id": "worker-01",
    "mac": "00:0c:29:b9:8b:2d",
    "os": "ubuntu",
    "disk": {
      "type": "master",
      "name": "_tpl_ubuntu_2204.img"
    }
  }'
```

### 7.2 创建空白盘 Worker

#### 请求体

```json
{
  "worker_id": "worker-00",
  "mac": "00:0c:29:b9:8b:00",
  "os": "ubuntu",
  "disk": {
    "type": "empty",
    "size": "40G"
  },
  "boot": {
    "menu_default": "ubuntu",
    "menu_timeout": 5000
  }
}
```

#### curl

```bash
curl -s -X POST "$BASE_URL/workers" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "worker_id": "worker-00",
    "mac": "00:0c:29:b9:8b:00",
    "os": "ubuntu",
    "disk": {
      "type": "empty",
      "size": "40G"
    }
  }'
```

### 7.3 Windows 安装期：空白盘 + ISO

只有 Windows 允许传 `windows_iso`。

#### 请求体

```json
{
  "worker_id": "worker-win-build",
  "mac": "00:0c:29:b9:8b:11",
  "os": "windows",
  "disk": {
    "type": "empty",
    "size": "80G"
  },
  "windows_iso": "Win11_24H2.iso"
}
```

#### curl

```bash
curl -s -X POST "$BASE_URL/workers" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "worker_id": "worker-win-build",
    "mac": "00:0c:29:b9:8b:11",
    "os": "windows",
    "disk": {
      "type": "empty",
      "size": "80G"
    },
    "windows_iso": "Win11_24H2.iso"
  }'
```

### 成功返回示例

Linux 母盘克隆示例：

```json
{
  "hostname": "worker-01",
  "os": "ubuntu",
  "arch": "x86_64",
  "state": "ready",
  "disk": {
    "agent": "storage-lio-01",
    "iqn": "iqn.2026-07.com.controller:worker-01.ubuntu",
    "filename": "worker-01.ubuntu.img",
    "backing": "/home/iscsi_img/worker-01.ubuntu.img",
    "source": {
      "type": "master",
      "name": "_tpl_ubuntu_2204.img"
    }
  },
  "cd": null,
  "worker_id": "worker-01",
  "mac": "00:0c:29:b9:8b:2d"
}
```

Windows 安装期示例：

```json
{
  "hostname": "worker-win-build",
  "os": "windows",
  "arch": "x86_64",
  "state": "installing",
  "disk": {
    "agent": "storage-lio-01",
    "iqn": "iqn.2026-07.com.controller:worker-win-build.windows",
    "filename": "worker-win-build.windows.img",
    "backing": "/home/iscsi_img/worker-win-build.windows.img",
    "source": {
      "type": "empty",
      "size": "80G"
    }
  },
  "cd": {
    "agent": "controller-stgt",
    "iqn": "iqn.2026-07.com.controller:worker-win-build.windows.iso",
    "iso": "Win11_24H2.iso",
    "backing": "/home/iscsi_img/Win11_24H2.iso"
  },
  "worker_id": "worker-win-build",
  "mac": "00:0c:29:b9:8b:11"
}
```

### 常见错误

| HTTP 状态码 | 常见原因 |
|---:|---|
| `400` | 参数格式错误；`windows_iso` 用在非 Windows 上；`disk.type=master` 却没传 `name`；`disk.type=empty` 却没传 `size` |
| `401` | 缺少 Token 或 Token 错误 |
| `409` | `worker_id` 已存在；`hostname` 已存在；MAC 已绑定；Agent 上 IQN 已存在；backing 文件已存在 |
| `500` | dnsmasq reload 失败；写文件失败；其他未预期错误 |
| `503` | Agent 不可达；docker.sock 不可用 |

---

## 8. GET /workers

### 说明

列出当前所有 Worker 台账。返回结果中的 `mac` 字段来自 `dnsmasq/dhcp-hosts.conf` 的实时反查。

### curl

```bash
curl -s "$BASE_URL/workers" \
  -H "Authorization: Bearer $TOKEN"
```

### 成功返回示例

```json
[
  {
    "hostname": "worker-00",
    "os": "ubuntu",
    "arch": "x86_64",
    "state": "ready",
    "disk": {
      "agent": "storage-lio-01",
      "iqn": "iqn.2026-07.com.controller:worker-00.ubuntu",
      "filename": "worker-00.ubuntu.img",
      "backing": "/home/iscsi_img/worker-00.ubuntu.img",
      "source": {
        "type": "empty",
        "size": "40G"
      }
    },
    "cd": null,
    "worker_id": "worker-00",
    "mac": "00:0c:29:b9:8b:00"
  }
]
```

---

## 9. GET /workers/{worker_id}

### 说明

查询单个 Worker 的台账记录。

### Path 参数

| 参数 | 必填 | 说明 |
|---|---:|---|
| `worker_id` | 是 | Worker 编号 |

### curl

```bash
curl -s "$BASE_URL/workers/worker-01" \
  -H "Authorization: Bearer $TOKEN"
```

### 成功返回

返回结构与 `POST /workers` 成功结果一致。

---

## 10. GET /workers/{worker_id}/status

### 说明

查询 Worker 的台账信息，并实时检查：

- `dnsmasq/dhcp-hosts.conf` 中是否存在 hostname 对应的 MAC
- Agent 上对应的 disk target 是否存在
- Agent 上对应的 cd target 是否存在

### Path 参数

| 参数 | 必填 | 说明 |
|---|---:|---|
| `worker_id` | 是 | Worker 编号 |

### curl

```bash
curl -s "$BASE_URL/workers/worker-01/status" \
  -H "Authorization: Bearer $TOKEN"
```

### 成功返回示例

```json
{
  "worker": {
    "hostname": "worker-01",
    "os": "ubuntu",
    "arch": "x86_64",
    "state": "ready",
    "disk": {
      "agent": "storage-lio-01",
      "iqn": "iqn.2026-07.com.controller:worker-01.ubuntu",
      "filename": "worker-01.ubuntu.img",
      "backing": "/home/iscsi_img/worker-01.ubuntu.img",
      "source": {
        "type": "master",
        "name": "_tpl_ubuntu_2204.img"
      }
    },
    "cd": null,
    "worker_id": "worker-01",
    "mac": "00:0c:29:b9:8b:2d"
  },
  "actual": {
    "dnsmasq": {
      "hostname": "worker-01",
      "mac": "00:0c:29:b9:8b:2d"
    },
    "disk": {
      "exists": true,
      "target": {
        "iqn": "iqn.2026-07.com.controller:worker-01.ubuntu",
        "luns": [
          {
            "backing": "/home/iscsi_img/worker-01.ubuntu.img"
          }
        ]
      }
    },
    "cd": null
  }
}
```

---

## 11. DELETE /workers/{worker_id}

### 说明

删除 Worker。Control Plane 会：

1. 从 `workers.yml` 找到该 Worker 的 disk/cd 台账
2. 如果存在 cd target，先删 cd
3. 再删 disk target
4. 从 `workers.yml` 删除该 Worker
5. 从 `dnsmasq/dhcp-hosts.conf` 删除 `mac,hostname` 这一行
6. HUP `ipxe-dnsmasq`

### Path 参数

| 参数 | 必填 | 说明 |
|---|---:|---|
| `worker_id` | 是 | 要删除的 Worker 编号 |

### Query 参数

| 参数 | 必填 | 默认值 | 说明 |
|---|---:|---|---|
| `delete_disk` | 否 | `false` | 是否连 backing `.img` 文件一起删除 |
| `ignore_missing_target` | 否 | `false` | 删除时若 Agent 返回 `404 iqn not found`，是否忽略继续执行 |

### curl

只删 target，保留 `.img`：

```bash
curl -s -X DELETE "$BASE_URL/workers/worker-01?delete_disk=false" \
  -H "Authorization: Bearer $TOKEN"
```

连 `.img` 一起删：

```bash
curl -s -X DELETE "$BASE_URL/workers/worker-01?delete_disk=true" \
  -H "Authorization: Bearer $TOKEN"
```

忽略 Agent 上 target 已不存在的情况：

```bash
curl -s -X DELETE "$BASE_URL/workers/worker-01?delete_disk=true&ignore_missing_target=true" \
  -H "Authorization: Bearer $TOKEN"
```

### 成功返回示例

```json
{
  "deleted": "worker-01",
  "delete_disk": false,
  "dnsmasq_removed": true
}
```

---

## 12. GET /operations

### 说明

读取 Control Plane 的操作流水。这个文件是 `state/operations.jsonl` 的增量查询接口。

### Query 参数

| 参数 | 必填 | 默认值 | 说明 |
|---|---:|---|---|
| `since` | 否 | `0` | 只返回 `id > since` 的记录 |
| `limit` | 否 | `1000` | 最多返回多少条 |

### curl

从头读取：

```bash
curl -s "$BASE_URL/operations" \
  -H "Authorization: Bearer $TOKEN"
```

增量读取：

```bash
curl -s "$BASE_URL/operations?since=10&limit=100" \
  -H "Authorization: Bearer $TOKEN"
```

### 成功返回示例

```json
{
  "next_cursor": 5,
  "entries": [
    {
      "id": 1,
      "ts": "2026-07-27T14:20:00+00:00",
      "op": "create_worker",
      "status": "started",
      "worker_id": "worker-01",
      "client": "172.18.0.1"
    },
    {
      "id": 2,
      "ts": "2026-07-27T14:20:01+00:00",
      "op": "agent.create_disk",
      "status": "ok",
      "worker_id": "worker-01",
      "agent": "storage-lio-01",
      "iqn": "iqn.2026-07.com.controller:worker-01.ubuntu"
    }
  ]
}
```

---

## 13. 典型测试顺序

建议这样验一遍：

### 13.1 查服务存活

```bash
curl -s "$BASE_URL/healthz"
```

### 13.2 查启动变量投影

```bash
curl -s "$BASE_URL/boot-vars?mac=000c29b98b2d&hostname=worker-01"
curl -s "$BASE_URL/boot-vars?mac=000c29b98b2d&hostname=worker-01&format=json"
```

### 13.3 查 Agent 配置和能力

注意：`config/agents.yml` 是由 Control Plane 容器内部读取的。Agent 如果和 Control Plane 在同一台宿主机上，不能写 `http://localhost:4840`，因为容器里的 `localhost` 指向 Control Plane 容器自己。

默认 compose 已配置：

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

因此同宿主机上的 Agent 建议写：

```yaml
base_url: http://host.docker.internal:4840
```

```bash
curl -s "$BASE_URL/agents?live=true" \
  -H "Authorization: Bearer $TOKEN"
```

### 13.4 创建一台 Linux 空白盘 Worker

```bash
curl -s -X POST "$BASE_URL/workers" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "worker_id": "worker-00",
    "mac": "00:0c:29:b9:8b:00",
    "os": "ubuntu",
    "disk": {
      "type": "empty",
      "size": "40G"
    }
  }'
```

### 13.5 查询 Worker 台账

```bash
curl -s "$BASE_URL/workers/worker-00" \
  -H "Authorization: Bearer $TOKEN"
```

### 13.6 查询实时状态

```bash
curl -s "$BASE_URL/workers/worker-00/status" \
  -H "Authorization: Bearer $TOKEN"
```

### 13.7 删除 Worker，但保留空白盘文件

```bash
curl -s -X DELETE "$BASE_URL/workers/worker-00?delete_disk=false" \
  -H "Authorization: Bearer $TOKEN"
```

这一步正好适合“空白盘制作完成后，人工改名为母盘”的工作流。

---

## 14. 当前实现边界

当前版本已经支持：

- Worker 创建
- Worker 删除
- Agent 选择
- Windows ISO 特例
- dnsmasq 主机名绑定
- Worker 与操作轨迹查询

当前版本还没有做：

- 编辑 Worker
- 批量导入 Worker
- 自动 IP 管理
- 自动母盘生命周期管理
- 定时 reconcile
---

### 各组件使用以下端口: 
#### Control
- dnsmasq: `67` , `66`
- nginx: `4838`
- Control_Plane: `4839`
#### iSCSI-sever
- Agent: `4840`
- Lio / stgt : `3260`
