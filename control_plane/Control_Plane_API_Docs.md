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
| `POST` | `/agents` | 注册新 Agent（写入 agents.yml，重复 id 返回 409） |
| `POST` | `/agents/probe` | 探测 Agent 并自动推导注册参数（预览，不写文件） |
| `GET` | `/agents/{agent_id}/luns` | 列出指定 Agent 上的 iSCSI target/LUN |
| `POST` | `/agents/{agent_id}/luns/disk` | 在指定 Agent 上创建磁盘 LUN（母盘克隆/空白盘） |
| `POST` | `/agents/{agent_id}/luns/cd` | 在指定 Agent 上创建 CD（ISO 虚拟光驱）LUN |
| `DELETE` | `/agents/{agent_id}/luns` | 删除指定 Agent 上的 LUN/target |
| `POST` | `/agents/{agent_id}/luns/scan` | 触发指定 Agent 扫描镜像目录重建 target |
| `POST` | `/workers` | 注册 Worker 身份（hostname + MAC 绑定） |
| `POST` | `/workers/{worker_id}/luns/disk` | 给指定 Worker 创建系统盘 LUN |
| `POST` | `/workers/luns/disk/batch` | 批量给多个 Worker 创建系统盘（每项指定存储节点） |
| `DELETE` | `/workers/{worker_id}/luns/disk/{os}` | 删除 Worker 单个系统盘（保留/删除 .img 文件） |
| `PUT` | `/workers/{worker_id}/default-os` | 设置 Worker 默认启动配置（系统 / 菜单项 / 超时） |
| `GET` | `/workers` | 列出 Worker |
| `GET` | `/workers/{worker_id}` | 查询单个 Worker |
| `GET` | `/workers/{worker_id}/status` | 查询 Worker 台账与实时状态 |
| `DELETE` | `/workers/{worker_id}` | 删除 Worker |
| `POST` | `/workers/delete/batch` | 批量删除 Worker（逐项独立，成功/失败汇总） |
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

给 iPXE 启动脚本读取 per-worker 启动变量。该接口不鉴权，只暴露受控内网启动所需变量。

> **注意**：该端点有写副作用 —— 当请求来自未绑定的新 MAC 时，会**自动注册**该 Worker（见下文「自动注册」），其余情况只读。

Control Plane 会根据 `mac` 或 `hostname` 查：

1. `dnsmasq/dhcp-hosts.conf`
2. `state/workers.yml`
3. `config/agents.yml`

然后返回该 Worker 对应的 iSCSI Server、默认菜单项和菜单超时。

默认返回 iPXE 脚本片段，兼容性最好，可以直接被 iPXE `chain` 执行。加 `format=json` 时返回 JSON，方便人工调试。

### 字段来源

`/boot-vars` 返回的是 inventory 的投影：

| 返回字段 | 来源 |
|---|---|
| `base_iqn` | `workers.yml` 中该 Worker 默认启动盘（`default_os` 对应的盘，未设时取第一块）的 `iqn` 去掉最后一个 `:` 后的前缀；Worker 无系统盘时**不返回**（iPXE 沿用 `boot.ipxe.cfg` 静态默认值） |
| `iscsi_server` | 默认启动盘（同上选盘规则）的 `agent` -> `agents.yml` 中该 Agent 的 `iscsi_server`；无系统盘时不返回 |
| `iscsi_sep` | iSCSI root **连接符**（`${iscsi-server}` 与 `${base-iqn}` 之间的分隔字段），root-path 拼装由 iPXE 侧完成。**按 Agent 后端类型生成**：stgt 后端为 `:::1:`（lun 占位 1），LIO 后端为 `::::`（空占位）；后端类型优先读 `agents.yml` 该 Agent 的 `tags`（含 `lio` / `stgt` 标记），未标记时查询 Agent `/capabilities` 的 `backend` 字段，查询失败默认 stgt 格式；无系统盘时不返回 |
| `menu_default` | 推导链：`workers.yml` 的 `default_os`（建盘后单独设置）> `boot.menu_default`（显式配置）> `reboot`（未配置时循环重启等待） |
| `menu_timeout` | 已配置默认启动时：`boot.menu_timeout` > `IPXE_CP_BOOT_MENU_TIMEOUT`（默认 5000）；处于 `reboot` 循环时：固定用 `IPXE_CP_AUTO_BOOT_TIMEOUT`（默认 1）。单位均为毫秒 |

查找 Worker 的规则（**hostname 优先**）：

```text
hostname -> workers.yml（hostname 或 worker_id）
hostname 未命中或未传 -> mac -> dnsmasq/dhcp-hosts.conf -> hostname -> workers.yml
都未命中且 mac 已传 -> 自动注册（见下）
```

### 默认启动项规则

默认启动项由 `/boot-vars` 按以下顺序推导：

```text
default_os（建盘后单独设置，见 7.3）-> boot.menu_default（显式配置）-> reboot（未配置）
```

- 推荐做法：创建系统盘后调用 `PUT /workers/{worker_id}/default-os` 设置默认启动系统：

```text
os=ubuntu  -> menu_default=ubuntu
os=debian  -> menu_default=debian
os=windows -> menu_default=windows
```

- 也可以不设置 `default_os`，改用 `boot.menu_default` 指定 iPXE 菜单默认项（如安装期 `menu-install`、退出 `exit`）
- 两者都没有时，`menu_default` 返回 `reboot`（短超时循环重启，等待管理员建盘 / 设置默认系统；`exit` 仅出现在显式设置时）

### 自动注册（Zero-touch Provisioning）

新 Worker 开机时没有 hostname，iPXE 会带 `mac` 请求 `/boot-vars`。若该 MAC 未绑定，Control Plane 自动完成登记：

1. 按顺序生成 hostname（扫描台账 + dhcp 绑定中 `worker-N` 的最大序号 +1，格式 `worker-%02d`，编号从 `worker-01` 开始）
2. 写入 `workers.yml`（`state=registered`，无系统盘）并绑定 `dnsmasq/dhcp-hosts.conf`（MAC -> hostname），触发 dnsmasq reload
3. 返回 `menu-default=reboot` + 短超时，让机器立即重启
4. 重启后 dnsmasq 下发 hostname，后续请求用 hostname 表明身份；在管理员创建系统盘并设置 `default_os` 之前，一直返回 `reboot` 循环重启
5. 管理员配置完成后，下次重启即按 `default_os` 进入对应系统

控制项（环境变量）：

| 变量 | 默认 | 说明 |
|---|---:|---|
| `IPXE_CP_AUTO_REGISTER` | `true` | 关闭后新 MAC 不再自动注册（返回空脚本） |
| `IPXE_CP_AUTO_BOOT_TIMEOUT` | `1` | reboot 循环的菜单超时（毫秒） |

自动注册全程有操作日志（`auto_register`），失败会回滚台账并返回空脚本，下次请求重试，不影响 iPXE 引导。

### Query 参数

| 参数 | 必填 | 默认值 | 说明 |
|---|---:|---|---|
| `mac` | 否 | 无 | MAC 地址。后端自动剥离 `:` / `-` / `.` 后归一化，带冒号（`00:0c:29:b9:8b:2d`）与 `mac:hexraw`（`000c29b98b2d`）格式都支持 |
| `hostname` | 否 | 无 | 主机名，如 `worker-01` |
| `format` | 否 | `ipxe` | `ipxe` 或 `json` |

`mac` 和 `hostname` 至少建议传一个。iPXE 端推荐两个都传：

```text
/boot-vars?mac=${mac}&hostname=${hostname}
```

> **注意**：规范上 `${mac:hexraw}` 与 `${mac}` 等价（后端统一归一化），但部分真实 iPXE 固件对 `hexraw` 修饰符展开异常（可能为空），实测必须使用带冒号的 `${mac}`——请勿改回 `hexraw`。

### iPXE 格式 curl

```bash
curl -s "$BASE_URL/boot-vars?mac=000c29b98b2d&hostname=worker-01"
```

成功返回示例：

```ipxe
#!ipxe
# boot vars for worker-01
set base-iqn iqn.2026-07.com.controller
set iscsi-server 192.168.80.3
set iscsi-sep :::1:
set menu-default ubuntu
set menu-timeout 5000
```

已注册但未配置默认启动（无系统盘 / 未设 `default_os` / 未显式设 `boot.menu_default`）时返回：

```ipxe
#!ipxe
# boot vars for worker-01
set menu-default reboot
set menu-timeout 1
```

新 MAC（触发自动注册）与完全无法识别时，若自动注册失败或未开启则返回空脚本：

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
  "iscsi_server": "192.168.80.3",
  "iscsi_sep": ":::1:",
  "menu_default": "ubuntu",
  "menu_timeout": 5000
}
```

已注册但未配置默认启动时返回：

```json
{
  "menu_default": "reboot",
  "menu_timeout": 1
}
```

无法识别且未触发自动注册时返回：

```json
{}
```

### iPXE 接入方式

`tftp/boot.ipxe.cfg` 末尾会拉取该端点：

```ipxe
chain --autofree http://${controller_ip}:4839/boot-vars?mac=${mac}&hostname=${hostname} || goto vars-done
# chain 失败（端点不可达）时静默跳过，沿用本文件顶部的静态默认值；
# 成功后返回的 base-iqn / iscsi-server 可能覆盖静态默认，需重建派生变量
# isset 守卫：/boot-vars 已下发按后端生成的 iscsi-sep（stgt `:::1:` / LIO `::::`）时不覆盖
isset ${iscsi-sep} || set iscsi-sep :::1:
isset ${hostname} && set initiator-iqn ${base-iqn}:${hostname} || set initiator-iqn ${base-iqn}:${mac}

:vars-done
```

`menu.ipxe` 各系统项与安装项用 `${iscsi-sep}` 插入 root-path（如 `set root-path iscsi:${iscsi-server}${iscsi-sep}${base-iqn}:${hostname}.windows`），`iscsi:` 协议头与拼装结构保持静态，仅连接符由后端投影。

### Agent 数据面地址

`/boot-vars` 返回的是 Worker 连接 iSCSI 的 **数据面地址**，不是 Agent HTTP API 地址。建议在 `config/agents.yml` 里显式配置：

```yaml
agents:
  storage-lio-01:
    base_url: http://host.docker.internal:4840
    iscsi_server: 192.168.80.3
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

## 6.1 POST /agents

### 说明

注册新 Agent：写入 `config/agents.yml`，注册后立即生效（建盘/挂载调度即会纳入该 Agent）。同一 `id` 重复注册返回 `409`。

**推荐流程**：先在 WebUI（或 `POST /agents/probe`，见 6.2）填写 API 地址并探测，自动获取角色 / 标签 / 数据面地址等参数，确认后调用本接口完成注册；也可直接全参数提交。

### 请求体字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `id` | 是 | Agent 编号。自动转小写，规则同 worker id（字母、数字、点、下划线、短横线） |
| `base_url` | 是 | Agent 控制面 API 地址，须以 `http://` 或 `https://` 开头，末尾 `/` 自动去除 |
| `token` | 否 | Agent 鉴权 Token，支持 `${ENV}` 环境变量占位（Control Plane 读取时展开）；无鉴权 Agent 可留空 |
| `iscsi_server` | 否 | iSCSI 数据面地址（业务网段 IP）。缺省时回退为 `base_url` 的主机名 |
| `role` | 否 | 角色：`disk`=可建系统盘（存储节点），`cd`=可挂载 ISO（光驱节点）；默认 `{disk: false, cd: false}` |
| `tags` | 否 | 自由标签数组（如 `storage`/`lio`/`stgt`），展示用；`lio`/`stgt` 标记同时参与 `/boot-vars` 连接符推导 |
| `enabled` | 否 | 是否启用；默认 `true` |

### curl

```bash
curl -s -X POST "$BASE_URL/agents" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "storage-stgt-02",
    "base_url": "http://host.docker.internal:4840",
    "token": "${STORAGE_STGT_02_TOKEN}",
    "iscsi_server": "192.168.1.6",
    "role": {"disk": true, "cd": false},
    "tags": ["storage", "stgt"],
    "enabled": true
  }'
```

### 成功返回（201）

```json
{
  "id": "storage-stgt-02",
  "base_url": "http://host.docker.internal:4840",
  "iscsi_server": "192.168.1.6",
  "role": {"disk": true, "cd": false},
  "enabled": true,
  "tags": ["storage", "stgt"]
}
```

### 错误返回

| 状态码 | 场景 |
|---|---|
| `400` | `id` 格式非法 / `base_url` 非 http(s) 开头 |
| `409` | Agent `id` 已存在 |

---

## 6.2 POST /agents/probe

### 说明

探测 Agent 并自动推导注册参数（**只读预览，不写任何文件**）：调用 Agent `/healthz`（无鉴权）+ `/capabilities`（Bearer token），按以下规则推导：

| 参数 | 推导规则 |
|---|---|
| `role.disk` | 恒为 `true`（Agent 即 iSCSI 存储节点） |
| `role.cd` | 取 `capabilities.cd` |
| `tags` | `["storage", backend]`（`backend` 为 lio / stgt，同时供 `/boot-vars` 连接符推导） |
| `iscsi_server` | 缺省回退 `base_url` 主机名 |

### 请求体字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `base_url` | 是 | Agent 控制面 API 地址，须以 `http://` 或 `https://` 开头 |
| `token` | 否 | Agent 鉴权 Token；Agent 配置了 `IPXE_AGENT_TOKEN` 时必填（Agent 不回显自身 token，无法自动获取） |

### curl

```bash
curl -s -X POST "$BASE_URL/agents/probe" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"base_url": "http://host.docker.internal:4840", "token": "${STORAGE_STGT_02_TOKEN}"}'
```

### 成功返回

```json
{
  "base_url": "http://host.docker.internal:4840",
  "role": {"disk": true, "cd": false},
  "tags": ["storage", "stgt"],
  "iscsi_server": "host.docker.internal",
  "enabled": true,
  "backend": "stgt",
  "base_iqn": "iqn.2026-07.com.controller",
  "clone": "reflink (FICLONE) -> shutil.copy fallback",
  "empty_disk": "truncate (sparse)",
  "persistent": "auto-scan on startup"
}
```

### 错误返回

| 状态码 | 场景 |
|---|---|
| `400` | `base_url` 非 http(s) 开头 |
| `502` | Agent 不可达（`/healthz` 失败）或 `/capabilities` 调用失败（如 token 错误） |

---

## 7. POST /workers

### 说明

注册一台 Worker 的**身份**：hostname + MAC 绑定。**存储与身份分离**——本接口不创建任何系统盘，系统盘须另调 `POST /workers/{worker_id}/luns/disk`（见 7.1）。Control Plane 会：

1. 校验 `worker_id`、`hostname`、`mac`
2. 写入 `state/workers.yml`（`disks` 为空数组，`state=registered`）
3. 写入 `dnsmasq/dhcp-hosts.conf`
4. 通过 Docker 向 `ipxe-dnsmasq` 容器发送 HUP：

```bash
docker exec ipxe-dnsmasq killall -HUP dnsmasq
```

5. 如指定 `windows_iso`，额外调用 Agent 创建 CD target（安装期光驱，与系统盘无关）

### 请求体字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `worker_id` | 是 | Worker 编号。会自动转为小写。允许字母、数字、点、下划线、短横线 |
| `mac` | 是 | Worker 网卡 MAC 地址，格式如 `00:0c:29:b9:8b:2d` |
| `hostname` | 否 | 主机名。不传时默认等于 `worker_id` |
| `arch` | 否 | 架构。不传时默认 `x86_64` |
| `windows_iso` | 否 | Windows 安装期 ISO 文件名。传入即在注册时额外创建安装光驱 target |
| `boot` | 否 | iPXE 菜单默认项与超时配置；不传则由 `/boot-vars` 按 OS 和全局默认值推导 |

### `boot` 字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `menu_default` | 否 | iPXE 主菜单默认项，如 `ubuntu`、`debian`、`windows`、`exit` |
| `menu_timeout` | 否 | iPXE 菜单超时，单位毫秒，如 `5000` |

不传 `boot` 时：

- `menu_default` 默认使用 `default_os`（建盘后单独设置，见 7.3）；未设置时默认 `reboot`（循环重启等待配置，见 5 节）；
- `menu_timeout` 默认使用 `IPXE_CP_BOOT_MENU_TIMEOUT`，当前默认 `5000`。

因此大多数 Worker 不需要传 `boot`。例如：

```json
{
  "worker_id": "worker-01",
  "mac": "00:0c:29:b9:8b:2d"
}
```

注册后 Worker 还没有系统盘，`/boot-vars` 会返回：

```ipxe
set menu-default exit
set menu-timeout 5000
```

创建系统盘后，调用 `PUT /workers/{worker_id}/default-os`（见 7.3）设置默认启动系统，`menu-default` 随即切换为该系统的菜单项（如 `ubuntu`）。

只有要覆盖菜单行为时才传 `boot`：

```json
{
  "worker_id": "worker-01",
  "mac": "00:0c:29:b9:8b:2d",
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
  "windows_iso": "Win11_24H2.iso",
  "boot": {
    "menu_default": "menu-install",
    "menu_timeout": 3000
  }
}
```

## 7.1 POST /workers/{worker_id}/luns/disk

### 说明

给指定 Worker 创建系统盘 LUN。系统盘按系统分类，一个 Worker 可挂多个系统的盘（同一系统至多一个）。Control Plane 会：

1. 校验 Worker 存在且尚未挂载该系统的盘（已存在时返回 `409`）
2. 确定该系统盘对应的系统：请求体 `os` 必填，决定 IQN 后缀与文件名
3. 选择存储 Agent（`disk_agent` 指定或自动选择）
4. 拼接 IQN 和 backing filename（`base-iqn:worker-id.os`）
5. 调用 Agent 创建磁盘 target（母盘克隆或空白盘）
6. 更新 `state/workers.yml` 中该 Worker 的 `disks` 台账（追加到数组），首次建盘时 `state` 由 `registered` 转为 `ready`

端点位于 `/luns/` 命名空间下，为将来数据盘（`/luns/data`）预留；多系统盘场景下，默认启动哪个系统由 `PUT /workers/{worker_id}/default-os` 的 `os` 决定。

### Path 参数

| 参数 | 必填 | 说明 |
|---|---:|---|
| `worker_id` | 是 | Worker 编号 |

### 请求体字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `type` | 是 | `master` 或 `empty` |
| `name` | 条件必填 | 当 `type=master` 时必填。表示母盘文件名 |
| `size` | 条件必填 | 当 `type=empty` 时必填。表示空白盘大小，如 `40G` |
| `os` | 是 | 该系统盘对应的系统（决定 IQN 后缀与文件名）。仅允许 `windows`、`ubuntu`、`debian`、`centos`、`esxi`（menu.ipxe 操作系统项） |
| `disk_agent` | 否 | 指定存储 Agent；不传时 Control Plane 自动选择 |

### 7.1.1 从母盘克隆

#### curl

```bash
curl -s -X POST "$BASE_URL/workers/worker-01/luns/disk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "master",
    "os": "ubuntu",
    "name": "_tpl_ubuntu_2204.img"
  }'
```

### 7.1.2 创建空白盘

#### curl

```bash
curl -s -X POST "$BASE_URL/workers/worker-00/luns/disk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "empty",
    "os": "ubuntu",
    "size": "40G"
  }'
```

### 成功返回示例（master 克隆）

```json
{
  "hostname": "worker-01",
  "arch": "x86_64",
  "state": "ready",
  "disks": [
    {
      "agent": "storage-lio-01",
      "iqn": "iqn.2026-07.com.controller:worker-01.ubuntu",
      "filename": "worker-01.ubuntu.img",
      "backing": "/home/iscsi_img/worker-01.ubuntu.img",
      "os": "ubuntu",
      "source": {
        "type": "master",
        "name": "_tpl_ubuntu_2204.img"
      }
    }
  ],
  "cd": null,
  "worker_id": "worker-01",
  "mac": "00:0c:29:b9:8b:2d"
}
```

### 成功返回示例（empty 空白盘）

```json
{
  "hostname": "worker-00",
  "arch": "x86_64",
  "state": "ready",
  "disks": [
    {
      "agent": "storage-lio-01",
      "iqn": "iqn.2026-07.com.controller:worker-00.ubuntu",
      "filename": "worker-00.ubuntu.img",
      "backing": "/home/iscsi_img/worker-00.ubuntu.img",
      "os": "ubuntu",
      "source": {
        "type": "empty",
        "size": "40G"
      }
    }
  ],
  "cd": null,
  "worker_id": "worker-00",
  "mac": "00:0c:29:b9:8b:00"
}
```

### 7.1.3 批量创建系统盘（POST /workers/luns/disk/batch）

批量部署场景：同一套盘参数应用到多个 Worker，每个 Worker 使用各自分配的存储节点（`targets[].agent` 必填——由 WebUI 的「接管所选 Worker」或拖拽指定产生，不存在默认公共分配）。

与单盘一致：`master` 走母盘克隆、`empty` 建空白盘；同一 `os` 至多一块，已存在则**自动跳过**（不算失败）。**创建成功的 Worker 自动将 `default_os` 设为本次批量系统**——批量部署直接进入默认启动，无需再调 `PUT /workers/{worker_id}/default-os`（单盘接口不自动设置）。逐项独立执行，单项失败不影响其余，返回 `succeeded` / `skipped` / `failed` 汇总。

#### 请求体字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `type` | 是 | `master` 或 `empty` |
| `os` | 是 | 该系统盘对应的系统（同一批次所有 Worker 相同，决定 IQN 后缀与文件名） |
| `name` | 条件必填 | 当 `type=master` 时必填。表示母盘文件名 |
| `size` | 条件必填 | 当 `type=empty` 时必填。表示空白盘大小，如 `40G` |
| `targets` | 是 | 数组，每项 `{worker_id, agent}`：Worker 编号 + 该 Worker 已分配的存储节点 |

#### curl

```bash
curl -s -X POST "$BASE_URL/workers/luns/disk/batch" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "master",
    "os": "ubuntu",
    "name": "_tpl_ubuntu_2204.img",
    "targets": [
      { "worker_id": "worker-01", "agent": "storage-lio-01" },
      { "worker_id": "worker-02", "agent": "storage-lio-01" },
      { "worker_id": "worker-03", "agent": "storage-stgt-01" }
    ]
  }'
```

#### 返回示例

```json
{
  "succeeded": [
    { "worker_id": "worker-01", "agent": "storage-lio-01", "iqn": "iqn.2026-07.com.controller:worker-01.ubuntu" },
    { "worker_id": "worker-03", "agent": "storage-stgt-01", "iqn": "iqn.2026-07.com.controller:worker-03.ubuntu" }
  ],
  "skipped": [
    { "worker_id": "worker-02", "reason": "already has a ubuntu system disk" }
  ],
  "failed": [
    { "worker_id": "worker-04", "agent": "storage-lio-01", "error": "worker not found: worker-04" }
  ]
}
```

---

## 7.2 Windows 安装期：身份注册 + ISO + 系统盘

Windows 安装流程分两步：先注册身份（可顺带指定安装介质 ISO），再创建系统盘。

### 7.2.1 身份注册（带 ISO）

```bash
curl -s -X POST "$BASE_URL/workers" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "worker_id": "worker-win-build",
    "mac": "00:0c:29:b9:8b:11",
    "windows_iso": "Win11_24H2.iso"
  }'
```

注册后返回 `state=installing`（存在 CD target），`disks` 为空数组。

### 7.2.2 创建系统盘

```bash
curl -s -X POST "$BASE_URL/workers/worker-win-build/luns/disk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "empty",
    "os": "windows",
    "size": "80G"
  }'
```

创建后返回：

```json
{
  "hostname": "worker-win-build",
  "arch": "x86_64",
  "state": "installing",
  "disks": [
    {
      "agent": "storage-lio-01",
      "iqn": "iqn.2026-07.com.controller:worker-win-build.windows",
      "filename": "worker-win-build.windows.img",
      "backing": "/home/iscsi_img/worker-win-build.windows.img",
      "os": "windows",
      "source": {
        "type": "empty",
        "size": "80G"
      }
    }
  ],
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

安装期结束后，CD target 随 Worker 删除流程清理。

### 常见错误

| HTTP 状态码 | 常见原因 |
|---:|---|
| `400` | 参数格式错误；`os` 不在 {windows/ubuntu/debian/centos/esxi}；`type=master` 却没传 `name`；`type=empty` 却没传 `size` |
| `401` | 缺少 Token 或 Token 错误 |
| `404` | 创建系统盘时 Worker 不存在 |
| `409` | `worker_id` 已存在；`hostname` 已存在；MAC 已绑定；Worker 已有该系统盘（同 `os` 重复创建）；Agent 上 IQN 已存在；backing 文件已存在 |
| `500` | dnsmasq reload 失败；写文件失败；其他未预期错误 |
| `503` | Agent 不可达；docker.sock 不可用 |

---

## 7.3 PUT /workers/{worker_id}/default-os

### 说明

设置 Worker 的默认启动配置（可设可清）。`/boot-vars` 的 `menu_default` 推导链：

```text
default_os（本端点 os 字段，优先）-> boot.menu_default（本端点 menu_default 字段）-> reboot（未配置，循环重启等待）
```

请求体三个字段可单独或组合传，至少传一个；传 `null`（或空字符串）表示清除对应项。可重复调用，后设覆盖先设。

要求：

- 设置 `os`：Worker 必须已有该系统盘（`POST /workers/{worker_id}/luns/disk` 创建的某个 `os`），否则返回 `400` 并列出当前系统盘；多盘模型下用 `os` 精确匹配要默认启动的系统
- 设置 `menu_default`：值必须为 `menu.ipxe` 主菜单的 item ID（严格校验，防止 iPXE `choose --default` 落空）
- 设置 `menu_timeout`：非负整数；清除后恢复默认 `IPXE_CP_BOOT_MENU_TIMEOUT`

### Path 参数

| 参数 | 必填 | 说明 |
|---|---:|---|
| `worker_id` | 是 | Worker 编号 |

### 请求体字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `os` | 否 | 默认启动的系统，须与该 Worker 已挂载系统盘一致，如 `ubuntu`；传 `null` 清除 |
| `menu_default` | 否 | iPXE 主菜单默认项，见下方合法值表；传 `null` 清除 |
| `menu_timeout` | 否 | 菜单超时毫秒数，非负整数；传 `null` 清除 |

### `menu_default` 合法值（menu.ipxe 主菜单 item ID）

| 类别 | 合法值 |
|---|---|
| 操作系统 | `windows` `ubuntu` `debian` `centos` `esxi` |
| 工具 / 安装 | `menu-diag` `menu-install` |
| 高级 | `config` `shell` `reboot` `exit` |

### 示例：设置默认系统

```bash
curl -s -X PUT "$BASE_URL/workers/worker-01/default-os" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "os": "ubuntu"
  }'
```

### 示例：设置菜单默认项与超时

```bash
curl -s -X PUT "$BASE_URL/workers/worker-win-build/default-os" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "menu_default": "menu-install",
    "menu_timeout": 3000
  }'
```

### 示例：清除默认系统

```bash
curl -s -X PUT "$BASE_URL/workers/worker-01/default-os" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "os": null
  }'
```

### 成功返回

返回该 Worker 的完整台账（含 `default_os`、`boot.menu_default`、`boot.menu_timeout` 等已设置字段）。

### 常见错误

| HTTP 状态码 | 常见原因 |
|---:|---|
| `400` | 三个字段都没传；`os` 与该 Worker 已挂载系统盘不一致；`menu_default` 不在合法值表；`menu_timeout` 为负数 |
| `401` | 缺少 Token 或 Token 错误 |
| `404` | Worker 不存在 |
| `409` | 设置 `os` 时 Worker 还没有系统盘 |

---

## 7.4 DELETE /workers/{worker_id}/luns/disk/{os}

### 说明

删除指定 Worker 的单个系统盘（按系统名，`os` 不区分大小写）。Control Plane 会：

1. 校验 Worker 存在且已挂载该系统盘（不存在时返回 `404`）
2. 调用该盘所在 Agent 删除 iSCSI target
3. 从 `state/workers.yml` 的 `disks` 数组中移除该盘记录
4. 联动清理：被删系统若为默认启动系统（`default_os`），一并清除 `default_os` 与同名的 `boot.menu_default`（防止 iPXE 启动到已删除的系统盘）
5. 删完最后一块盘时 `state` 由 `ready` 回退 `registered`（等待重新建盘）

### Query 参数

| 参数 | 默认 | 说明 |
|---|---:|---|
| `delete_file` | `false` | 是否同时删除 backing `.img` 文件。`false` 仅删除 target（.img 保留，可重新挂载） |
| `ignore_missing_target` | `false` | 目标在 Agent 上已不存在时是否忽略 404，继续完成台账删除 |

### 示例：删除系统盘但保留 .img

```bash
curl -s -X DELETE "$BASE_URL/workers/worker-01/luns/disk/ubuntu" \
  -H "Authorization: Bearer $TOKEN"
```

### 示例：删除系统盘并同时删除 .img 文件

```bash
curl -s -X DELETE "$BASE_URL/workers/worker-01/luns/disk/ubuntu?delete_file=true" \
  -H "Authorization: Bearer $TOKEN"
```

### 成功返回

返回该 Worker 的完整台账（`disks` 已不含被删系统盘；若为默认系统，`default_os`/`boot.menu_default` 已被清除；无盘时 `state=registered`）。

### 常见错误

| HTTP 状态码 | 常见原因 |
|---:|---|
| `400` | `os` 非法 |
| `401` | 缺少 Token 或 Token 错误 |
| `404` | Worker 不存在，或该 Worker 没有此系统盘 |

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
    "arch": "x86_64",
    "state": "ready",
    "disks": [
      {
        "agent": "storage-lio-01",
        "iqn": "iqn.2026-07.com.controller:worker-00.ubuntu",
        "filename": "worker-00.ubuntu.img",
        "backing": "/home/iscsi_img/worker-00.ubuntu.img",
        "os": "ubuntu",
        "source": {
          "type": "empty",
          "size": "40G"
        }
      }
    ],
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
    "arch": "x86_64",
    "state": "ready",
    "disks": [
      {
        "agent": "storage-lio-01",
        "iqn": "iqn.2026-07.com.controller:worker-01.ubuntu",
        "filename": "worker-01.ubuntu.img",
        "backing": "/home/iscsi_img/worker-01.ubuntu.img",
        "os": "ubuntu",
        "source": {
          "type": "master",
          "name": "_tpl_ubuntu_2204.img"
        }
      }
    ],
    "cd": null,
    "worker_id": "worker-01",
    "mac": "00:0c:29:b9:8b:2d"
  },
  "actual": {
    "dnsmasq": {
      "hostname": "worker-01",
      "mac": "00:0c:29:b9:8b:2d"
    },
    "disks": [
      {
        "os": "ubuntu",
        "exists": true,
        "target": {
          "iqn": "iqn.2026-07.com.controller:worker-01.ubuntu",
          "luns": [
            {
              "backing": "/home/iscsi_img/worker-01.ubuntu.img"
            }
          ]
        }
      }
    ],
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

## 11.1 POST /workers/delete/batch

### 说明

批量删除 Worker。每项独立执行，**单项失败不影响其余**，返回 `succeeded` / `failed` 汇总；每个 Worker 的处理与 11 节单删一致（删 CD/系统盘 target → 移台账 → 移除 dnsmasq 绑定），全部成功项统一保存台账并**只 reload 一次** dnsmasq。不存在的 Worker 计入 `failed`（`worker not found`）。

### 请求体字段

| 字段 | 必填 | 默认值 | 说明 |
|---|---:|---|---|
| `worker_ids` | 是 | — | 要删除的 Worker 编号数组 |
| `delete_disk` | 否 | `false` | 是否连 backing `.img` 文件一起删除 |
| `ignore_missing_target` | 否 | `false` | 删除时若 Agent 返回 `404 iqn not found`，是否忽略继续执行 |

### curl

```bash
curl -s -X POST "$BASE_URL/workers/delete/batch" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "worker_ids": ["worker-01", "worker-02"],
    "delete_disk": false,
    "ignore_missing_target": true
  }'
```

### 成功返回示例

```json
{
  "succeeded": [
    {"worker_id": "worker-01", "hostname": "worker-01"}
  ],
  "failed": [
    {"worker_id": "worker-03", "error": "worker not found: worker-03"}
  ]
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

### 13.4 注册 Worker 身份（hostname + MAC 绑定）

```bash
curl -s -X POST "$BASE_URL/workers" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "worker_id": "worker-00",
    "mac": "00:0c:29:b9:8b:00"
  }'
```

此时 Worker 已绑定 MAC，但还没有系统盘（`state=registered`，`disks` 为空数组）。

### 13.5 给 Worker-00 创建系统盘（空白盘）

```bash
curl -s -X POST "$BASE_URL/workers/worker-00/luns/disk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "empty",
    "os": "ubuntu",
    "size": "40G"
  }'
```

系统盘创建完成后 `state` 由 `registered` 转为 `ready`。

### 13.6 设置默认启动配置

```bash
curl -s -X PUT "$BASE_URL/workers/worker-00/default-os" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "os": "ubuntu"
  }'
```

此时 `/boot-vars` 的 `menu-default` 返回 `ubuntu`。菜单项与超时的设置示例见 7.3。

### 13.7 查询 Worker 台账

```bash
curl -s "$BASE_URL/workers/worker-00" \
  -H "Authorization: Bearer $TOKEN"
```

### 13.8 查询实时状态

```bash
curl -s "$BASE_URL/workers/worker-00/status" \
  -H "Authorization: Bearer $TOKEN"
```

### 13.9 删除 Worker，但保留空白盘文件

```bash
curl -s -X DELETE "$BASE_URL/workers/worker-00?delete_disk=false" \
  -H "Authorization: Bearer $TOKEN"
```

这一步正好适合“空白盘制作完成后，人工改名为母盘”的工作流。

---

## 14. Agent iSCSI LUN/target 管理

### 说明

Control Plane 可以直接管理任意 Agent 上的 iSCSI target/LUN。请求经 Control Plane 转发到 Agent（Agent 的 Bearer token 由 `config/agents.yml` 提供），因此调用方只需持有 Control Plane Token，无需直接接触 Agent。

与 Worker 生命周期接口（`POST /workers`、`DELETE /workers/{worker_id}`）的区别：

- Worker 接口面向**台账**：自动拼接 IQN、写 `state/workers.yml`、写 dnsmasq 绑定；
- LUN 管理接口面向**数据面直管**：不写任何台账，直接操作 Agent 上的 target，适合母盘管理、手工排障、ISO 临时挂载等场景。

所有接口都需要鉴权（`IPXE_CP_TOKEN`）。Agent 不存在时返回 `404 agent not found`；Agent 不可达时返回 `503`；Agent 侧的业务校验错误（如 IQN 前缀不匹配、文件已存在、IQN 已存在）会透传其状态码与 `detail`：

```json
{"agent": "storage-lio-01", "error": "iqn base mismatch: ..."}
```

### 14.1 GET /agents/{agent_id}/luns

列出指定 Agent 上的全部 iSCSI target/LUN。返回结构由 Agent 后端决定（stgt 带 `tid` 字段，LIO 为 `targetcli` 解析结果），Control Plane 原样透传。

#### Path 参数

| 参数 | 必填 | 说明 |
|---|---:|---|
| `agent_id` | 是 | Agent 标识，对应 `config/agents.yml` 的 key |

#### curl

```bash
curl -s "$BASE_URL/agents/storage-lio-01/luns" \
  -H "Authorization: Bearer $TOKEN"
```

#### 成功返回示例

```json
[
  {
    "iqn": "iqn.2026-07.com.controller:worker-01.ubuntu",
    "luns": [
      {
        "backing": "/home/iscsi_img/worker-01.ubuntu.img"
      }
    ]
  }
]
```

### 14.2 POST /agents/{agent_id}/luns/disk

在指定 Agent 上创建磁盘 LUN。传 `master` 走母盘克隆（优先 btrfs reflink 秒级），传 `size` 建空白盘（sparse）。Agent 未配置 `role.disk` 时返回 `400 agent ... not configured for disk role`。

#### Path 参数

| 参数 | 必填 | 说明 |
|---|---:|---|
| `agent_id` | 是 | Agent 标识 |

#### 请求体字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `iqn` | 是 | target IQN，必须以该 Agent 的 `base_iqn` 为前缀 |
| `filename` | 否 | backing 文件名；不传时由 Agent 按 IQN 自动生成 |
| `master` | 条件必填 | 母盘文件名（存在 `DISK_DIR` 下），与 `size` 二选一 |
| `size` | 条件必填 | 空白盘大小，如 `40G`，与 `master` 二选一 |

#### curl

```bash
# 从母盘克隆
curl -s -X POST "$BASE_URL/agents/storage-lio-01/luns/disk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "iqn": "iqn.2026-07.com.controller:worker-02.ubuntu",
    "master": "_tpl_ubuntu_2204.img"
  }'

# 建空白盘
curl -s -X POST "$BASE_URL/agents/storage-lio-01/luns/disk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "iqn": "iqn.2026-07.com.controller:worker-02.ubuntu",
    "filename": "worker-02.ubuntu.img",
    "size": "40G"
  }'
```

#### 成功返回示例

```json
{
  "iqn": "iqn.2026-07.com.controller:worker-02.ubuntu",
  "backing": "/home/iscsi_img/worker-02.ubuntu.img"
}
```

### 14.3 POST /agents/{agent_id}/luns/cd

在指定 Agent 上创建 CD（ISO 虚拟光驱）LUN。仅 `role.cd` 为 true 的 Agent 支持；未配置 cd 角色（如 LIO）时返回 `400 agent ... not configured for cd role`，后端能力限制由 Agent 透传。

#### 请求体字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `iso` | 是 | ISO 文件名（存在于 `DISK_DIR` 下） |
| `iqn` | 否 | target IQN；不传时由 Agent 按 `base_iqn:iso文件名` 自动生成 |

#### curl

```bash
curl -s -X POST "$BASE_URL/agents/controller-stgt/luns/cd" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "iso": "Win11_24H2.iso"
  }'
```

### 14.4 DELETE /agents/{agent_id}/luns

删除指定 Agent 上的一个 LUN/target。

#### Query 参数

| 参数 | 必填 | 默认值 | 说明 |
|---|---:|---|---|
| `iqn` | 是 | 无 | 要删除的 target IQN |
| `delete_file` | 否 | `false` | 是否连 backing 文件（`.img`/`.iso`）一起删 |
| `ignore_missing` | 否 | `false` | Agent 返回 `404 iqn not found` 时是否忽略并视为成功 |

#### curl

```bash
# 只删 target，保留 backing 文件
curl -s -X DELETE "$BASE_URL/agents/storage-lio-01/luns?iqn=iqn.2026-07.com.controller:worker-02.ubuntu" \
  -H "Authorization: Bearer $TOKEN"

# 连 backing 文件一起删，target 已不存在也继续
curl -s -X DELETE "$BASE_URL/agents/storage-lio-01/luns?iqn=iqn.2026-07.com.controller:worker-02.ubuntu&delete_file=true&ignore_missing=true" \
  -H "Authorization: Bearer $TOKEN"
```

#### 成功返回示例

```json
{
  "deleted": "iqn.2026-07.com.controller:worker-02.ubuntu",
  "delete_file": false
}
```

忽略缺失时返回：

```json
{
  "deleted": "iqn.2026-07.com.controller:worker-02.ubuntu",
  "delete_file": true,
  "ignored_missing": true
}
```

### 14.5 POST /agents/{agent_id}/luns/scan

触发 Agent 扫描镜像目录，为缺失的 `.img`/`.iso` 文件重建 target（文件即真相）。stgt 后端返回重建结果；LIO 后端因 `saveconfig` 持久化，通常全部跳过。

#### curl

```bash
curl -s -X POST "$BASE_URL/agents/storage-lio-01/luns/scan" \
  -H "Authorization: Bearer $TOKEN"
```

#### 成功返回示例

```json
{
  "created": [
    {
      "iqn": "iqn.2026-07.com.controller:worker-02.ubuntu",
      "cd": false
    }
  ],
  "skipped": []
}
```

---

## 15. 当前实现边界

当前版本已经支持：

- Worker 身份注册（hostname + MAC 绑定）
- Worker 系统盘创建（`POST /workers/{worker_id}/luns/disk`）
- Worker 默认启动配置设置（系统 / 菜单项 / 超时，`PUT /workers/{worker_id}/default-os`）
- Worker 删除
- Agent 选择
- Agent LUN 直管（列出 / 创建磁盘 / 创建 CD / 删除 / 扫描）
- Windows ISO 特例
- dnsmasq 主机名绑定
- Worker 与操作轨迹查询
- 多系统盘（一个 Worker 可挂载多个系统的系统盘，同一系统至多一个，由 `os` 区分、`default_os` 决定默认启动）

当前版本还没有做：

- 编辑 Worker
- 批量导入 Worker
- 自动 IP 管理
- 自动母盘生命周期管理
- 定时 reconcile
- 数据盘挂载（`/luns/data` 命名空间已预留）
---

### 各组件使用以下端口: 
#### Control
- dnsmasq: `67` , `66`
- nginx: `4838`
- Control_Plane: `4839`
#### iSCSI-sever
- Agent: `4840`
- Lio / stgt : `3260`
