# 控制面 API 参考

本文档描述当前 Control Plane 已实现的 HTTP 接口、请求参数、返回结构，以及可直接复制执行的 `curl` 测试命令。

> **API 优先（API-first）设计**：Control Plane 的全部能力都以 REST API 为第一接口——Web 管理界面（WebUI）本身也只是这套 API 的一个客户端，与任何第三方系统、自动化脚本完全平等。调用准则：**一切面向控制面**——第三方集成始终调用 Control Plane API，不绕过控制面直接操作 Agent 或数据面。

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
| `GET` | `/devices/report` | iPXE 设备信息上报（不鉴权，11 字段，见 16.6） |
| `GET` | `/devices/challenge` | 一次性 nonce 签发（不鉴权，挑战-响应，见 5.2） |
| `GET` | `/devices` | 设备池列表（state 过滤，见 16.1） |
| `GET` | `/devices/{mac}` | 单设备详情（见 16.2） |
| `POST` | `/devices` | 手动注册设备入池（见 16.3） |
| `POST` | `/devices/import` | 批量导入设备清单（见 16.4） |
| `DELETE` | `/devices/{mac}` | 注销设备（吊销，见 16.5） |
| `GET` | `/settings/registration-window` | 查询注册窗口状态（见 5.1） |
| `POST` | `/settings/registration-window` | 开启注册窗口（TTL 1-60 分钟硬上限，见 5.1） |
| `DELETE` | `/settings/registration-window` | 提前关闭注册窗口（见 5.1） |
| `GET` | `/settings/enforcement` | 查询设备身份验签强制开关（见 5.1） |
| `PUT` | `/settings/enforcement` | 切换设备身份验签强制开关（见 5.1） |
| `GET` | `/agents` | 查询 Agent 列表与能力 |
| `POST` | `/agents` | 注册新 Agent（写入 agents.yml，重复 id 返回 409） |
| `POST` | `/agents/probe` | 探测 Agent 并自动推导注册参数（预览，不写文件） |
| `PUT` | `/agents/{agent_id}` | 更新 Agent 配置（id 不可改，token 留空保持不变） |
| `GET` | `/agents/{agent_id}/luns` | 列出指定 Agent 上的 iSCSI target/LUN |
| `GET` | `/masters` | 聚合列出全部存储节点上的母盘清单（供克隆选盘） |
| `POST` | `/agents/{agent_id}/luns/disk` | 在指定 Agent 上创建磁盘 LUN（母盘克隆/空白盘） |
| `POST` | `/agents/{agent_id}/luns/cd` | 在指定 Agent 上创建 CD（ISO 虚拟光驱）LUN |
| `DELETE` | `/agents/{agent_id}/luns` | 删除指定 Agent 上的 LUN/target |
| `POST` | `/agents/{agent_id}/luns/scan` | 触发指定 Agent 扫描镜像目录重建 target |
| `POST` | `/workers` | 注册 Worker 身份（hostname 绑定；`mac` 可选，传了直接绑定设备） |
| `POST` | `/workers/batch` | 批量创建 Worker（数量 + 命名规则，逐项独立，`macs` 可选直接绑定，见 7.6） |
| `POST` | `/workers/{worker_id}/luns/disk` | 给指定 Worker 创建系统盘 LUN |
| `POST` | `/workers/luns/disk/batch` | 批量给多个 Worker 创建系统盘（每项指定存储节点） |
| `DELETE` | `/workers/{worker_id}/luns/disk/{os}` | 删除 Worker 单个系统盘（保留/删除 .img 文件） |
| `PUT` | `/workers/{worker_id}/default-os` | 设置 Worker 默认启动配置（系统 / 菜单项 / 超时） |
| `PUT` | `/workers/{worker_id}/mac` | 修改 Worker 的 MAC 绑定（更新 dnsmasq 绑定并 HUP 重载，审计旧/新 MAC，见 7.5） |
| `GET` | `/workers` | 列出 Worker |
| `GET` | `/workers/{worker_id}` | 查询单个 Worker |
| `GET` | `/workers/{worker_id}/status` | 查询 Worker 台账与实时状态 |
| `DELETE` | `/workers/{worker_id}` | 删除 Worker |
| `POST` | `/workers/delete/batch` | 批量删除 Worker（逐项独立，成功/失败汇总） |
| `PUT` | `/workers/{worker_id}/credential` | 设置/更新 NVMe-oF 认证密钥（DHHC-1 自检，见 7.7） |
| `DELETE` | `/workers/{worker_id}/credential` | 删除 NVMe-oF 认证密钥（吊销认证，见 7.7） |
| `GET` | `/workers/{worker_id}/credential` | 查询凭据元数据（不返回明文，见 7.7） |
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

> **注意**：该端点**只读**（启动变量投影，无写副作用）。注册窗口期注册（新 MAC 携公钥入设备池）已收敛到 `GET /devices/report`（见 16.6），由 `boot.ipxe.cfg` 在请求 `/boot-vars` 之前先 `chain`。

Control Plane 按以下顺序识别设备并投影启动变量：

1. `hostname` → `state/workers.yml`（hostname 或 worker_id）
2. `mac` → `state/devices.yml`（设备台账）→ `bound_worker_id` → `state/workers.yml`
3. `config/agents.yml`（默认启动盘的 Agent 数据面地址）

然后返回该 Worker 对应的 iSCSI Server、默认菜单项和菜单超时。

默认返回 iPXE 脚本片段，兼容性最好，可以直接被 iPXE `chain` 执行。加 `format=json` 时返回 JSON，方便人工调试。

### 字段来源

`/boot-vars` 返回的是 inventory 的投影：

| 返回字段 | 来源 |
|---|---|
| `base_nqn` | 默认启动盘（同选盘规则）的盘 NQN 前缀（C3 拼接：盘 NQN 由 Agent 按统一模板 `base:worker_id.os` 生成，固件侧 `sanboot nvme://<ip>:4420/${base-nqn}:<worker>.<os>` 拼装消费 = 盘记录权威值）；盘记录缺 `nqn`（存量盘）时不返回（不兼容遗留、不派生）；Worker 无系统盘时不返回 |
| `base_iqn` | `workers.yml` 中该 Worker 默认启动盘（`default_os` 对应的盘，未设时取第一块）的 `iqn` 去掉最后一个 `:` 后的前缀——盘标识权威 = NQN，IQN 由盘 NQN 派生；Worker 无系统盘时**不返回**（iPXE 沿用 `boot.ipxe.cfg` 静态默认值） |
| `storager_ip` | 默认启动盘（同上选盘规则）的 `agent` -> `agents.yml` 中该 Agent 的 `storager_ip`（数据面地址，NVMe-oF 引导与 iSCSI 安装器共用）；无系统盘时不返回 |
| `iscsi_sep` | iSCSI root **连接符**（`${storager-ip}` 与 `${base-iqn}` 之间的分隔字段，安装器 iSCSI 拼装消费），root-path 拼装由 iPXE 侧完成。**仅 stgt / LIO 后端返回**：stgt 后端为 `:::1:`（lun 占位 1），LIO 后端为 `::::`（空占位）；后端类型优先读 `agents.yml` 该 Agent 的 `tags`（含 `nvmet` / `lio` / `stgt` 标记），未标记时查询 Agent `/capabilities` 的 `backend` 字段，查询失败默认 stgt 格式；**nvmet 后端不下发**（menu 安装器项 `isset ${iscsi-sep}` 守卫跳过）；无系统盘时不返回 |
| `nbft_secret` | 该 Worker 的 NVMe-oF 认证密钥（DHHC-1，`state/credentials.yml` 按 worker_id 索引，见 7.7）；**已绑定 Worker 且密钥库有条目时注入**，无密钥 / 未绑定 / 请求被拒时不返回。固件侧消费：menu 拼 `nvme://...?secret=${nbft-secret}`（C3 已启用：secret 条件化拼装，无密钥走明文连接） |
| `hostnqn` | 该 Worker 的发起端 Host NQN（`KURRENT_CP_NQN_BASE` + `:host.<worker_id>`，与 nvmet-host 登记的 host 条目一致）；**已绑定 Worker 时注入**。固件侧消费：iPXE nvmetcp 默认 hostnqn 为 `nqn.2014-08.org.ipxe:<uuid>`（无 UUID 回退 `:ipxe`），与登记值不匹配时严格模式认证必败，须以本字段覆盖（固件 0011 补丁支持 `hostnqn` 设置） |
| `menu_default` | 推导链：`workers.yml` 的 `default_os`（建盘后单独设置）> `boot.menu_default`（显式配置）> `reboot`（未配置时循环重启等待） |
| `menu_timeout` | 已配置默认启动时：`boot.menu_timeout` > `IPXE_CP_BOOT_MENU_TIMEOUT`（默认 5000）；处于 `reboot` 循环时：固定用 `IPXE_CP_AUTO_BOOT_TIMEOUT`（默认 1）。单位均为毫秒 |

查找 Worker 的规则（**hostname 优先**）：

```text
hostname -> workers.yml（hostname 或 worker_id）
hostname 未命中或未传 -> mac -> devices.yml（设备台账）-> bound_worker_id -> workers.yml
未识别且 mac 已传 ->
  - 设备在池中（pooled）-> reboot 循环（menu-default=reboot + 短超时），等待绑定
  - 设备已吊销（revoked）-> 空脚本（菜单停留）
  - 未知 MAC + 注册窗口开启且带有效公钥 -> 入设备池（见下「注册窗口期注册」），返回 reboot 循环
  - 未知 MAC + 窗口关闭 / 无公钥 -> 空脚本（菜单停留；上报只记指纹不入池）
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

### 注册窗口期注册（Zero-touch Provisioning）

新设备开机时没有身份，iPXE 先 `chain` `/devices/report`（11 字段上报 + 可选 `pubkey`，见 16.6）再请求 `/boot-vars`。**注册只在窗口期**（2026-08-21 裁定）：仅当注册窗口开启且上报携带有效 ECDSA P-256 公钥时，未知 MAC 才被收进设备池；窗口关闭后上报只更新指纹、不入池（无窗口外注册通道，代码层不可配永久）。

1. `GET /devices/report`：未知 MAC + 窗口开启 + 带 `pubkey` → 写入 `state/devices.yml`（`state=pooled`，指纹入库，`key_hash` 填充，`source=ipxe`）
2. `GET /boot-vars`：MAC 在池中未绑定 → 返回 `menu-default=reboot` + 短超时，循环重启等待管理员绑定
3. 管理员将设备绑定到 Worker（WebUI / API，单绑 16.7、批量预览/执行 16.9/16.10）后，下次启动即按 Worker 配置正常引导

存量设备密钥认领：已入池设备在窗口期内带公钥上报即填充 `key_hash`（认领完成）；密钥不一致拒绝覆盖（吊销/重注册走删登记流程）。认领完成后建议开启验签强制（见 5.1）。

控制项：

| 项 | 默认 | 说明 |
|---|---:|---|
| 注册窗口 | 关闭 | 部署期用 `POST /settings/registration-window` 开启（TTL 1-60 分钟硬上限，到期自动关闭），见 5.1 |
| 验签强制 | 关闭 | `GET/PUT /settings/enforcement`：开启后 `/boot-vars` 只向验签通过的已绑定设备下发，见 5.1 |
| `IPXE_CP_AUTO_BOOT_TIMEOUT` | `1` | reboot 循环的菜单超时（毫秒） |

注册全程有操作日志（`device.register` / `device.claim`），失败回滚台账并返回空脚本，下次请求重试，不影响 iPXE 引导。

### 防冒领（绑定即认证）

请求带 `mac` 时，Control Plane 会校验该设备**绑定到了 hostname 命中的 Worker**（`bound_worker_id`）；不符合（绑定其他 Worker / 未绑定 / 未知设备）→ **拒绝下发**：返回空脚本，不泄露启动变量。不带 `mac`（仅 hostname）的请求无法校验身份，保持兼容放行。这使设备↔Worker 绑定成为开机时的认证边界：只有绑定的设备才能拿到该 Worker 的启动配置（如 `base_nqn` / `storager_ip`）。

### Query 参数

| 参数 | 必填 | 默认值 | 说明 |
|---|---:|---|---|
| `mac` | 否 | 无 | MAC 地址。后端自动剥离 `:` / `-` / `.` 后归一化，带冒号（`00:0c:29:b9:8b:2d`）与 `mac:hexraw`（`000c29b98b2d`）格式都支持 |
| `hostname` | 否 | 无 | 主机名，如 `worker-01` |
| `format` | 否 | `ipxe` | `ipxe` 或 `json` |
| `nonce` | 否 | 无 | 挑战-响应一次性 nonce（`/devices/challenge` 签发，见 5.2）；验签强制开启时缺失 → `missing_sig` 拒绝 |
| `sig` | 否 | 无 | ECDSA P-256 签名 base64(DER)，签名数据 `nonce‖mac‖hostname` 无分隔拼接（见 5.2）；验签强制开启时缺失 → `missing_sig` 拒绝。**兼容还原**：iPXE 拼 URL 不做百分号编码，base64 的 `+` 原样进入 query 后被按 form-urlencoded 解码为空格，服务端将空格还原为 `+` 再验签 |

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
set base-nqn nqn.2026-07.com.kurrent
set base-iqn iqn.2026-07.com.kurrent
set storager-ip 192.168.80.3
set iscsi-sep :::1:
set menu-default ubuntu
set menu-timeout 5000
set nbft-secret DHHC-1:01:<base64>   # 仅 NVMe-oF 认证启用时返回（见 7.7）
set hostnqn nqn.2026-07.com.kurrent:host.worker-01
```

已注册但未配置默认启动（无系统盘 / 未设 `default_os` / 未显式设 `boot.menu_default`）时返回：

```ipxe
#!ipxe
# boot vars for worker-01
set menu-default reboot
set menu-timeout 1
```

新 MAC（窗口期注册）与完全无法识别时，窗口关闭或无公钥则返回空脚本：

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
  "base_nqn": "nqn.2026-07.com.kurrent",
  "base_iqn": "iqn.2026-07.com.kurrent",
  "storager_ip": "192.168.80.3",
  "iscsi_sep": ":::1:",
  "menu_default": "ubuntu",
  "menu_timeout": 5000,
  "nbft_secret": "DHHC-1:01:<base64>",
  "hostnqn": "nqn.2026-07.com.kurrent:host.worker-01"
}
```

已注册但未配置默认启动时返回：

```json
{
  "menu_default": "reboot",
  "menu_timeout": 1
}
```

无法识别且未注册（窗口关闭 / 无公钥）时返回：

```json
{}
```

### iPXE 接入方式

`tftp/boot.ipxe.cfg` 中，信任根链在挑战-应答握手后**经 HTTPS（nginx 443，TOFU 信任锚）**拉取该端点（见 5.2）：

```ipxe
# 阶段 3：挑战-应答（R7）——签名请求携带 nonce+sig
:challenge
chain --autofree ${https-url}devices/challenge?mac=${mac} && goto signed || goto bootvars

:signed
sign ${nonce}${mac}${hostname} || goto bootvars
chain --autofree ${https-url}boot-vars?mac=${mac}&hostname=${hostname}&nonce=${nonce}&sig=${sig} || goto vars-done
goto vars-done

# 降级路径（challenge 失败：未注册/未认领，或旧固件）：
# 验签强制关闭期间放行；强制开启后 missing_sig 拒绝
:bootvars
chain --autofree ${https-url}boot-vars?mac=${mac}&hostname=${hostname} || goto vars-done

:vars-done
isset ${iscsi-sep} || set iscsi-sep :::1:
isset ${hostname} && set initiator-iqn ${base-iqn}:${hostname} || set initiator-iqn ${base-iqn}:${mac}
```

成功后返回的 `base-nqn` / `storager-ip` 可能覆盖静态默认值，派生变量在 `:vars-done` 重建；`isset` 守卫保留 `/boot-vars` 按后端下发的连接符（stgt `:::1:` / LIO `::::`）。

`menu.ipxe` 主引导项用 NVMe-oF 拼装：`set root-path nvme://${storager-ip}:4420/${base-nqn}:${hostname}.<os>`，已注入 `nbft-secret` 时附加 `?secret=`（`isset` 条件化）；安装项保持 iSCSI 拼装（`set root-path iscsi:${storager-ip}${iscsi-sep}${base-iqn}:${hostname}.<os>`），`iscsi:` 协议头与拼装结构保持静态，仅连接符由后端投影。

### Agent 数据面地址

`/boot-vars` 返回的是 Worker 连接存储的 **数据面地址**（NVMe-oF 引导 / iSCSI 安装器共用），不是 Agent HTTP API 地址。建议在 `config/agents.yml` 里显式配置：

```yaml
agents:
  storage-lio-01:
    base_url: http://host.docker.internal:4840
    storager_ip: 192.168.80.3
```

如果没有配置 `storager_ip`，Control Plane 会退回使用 `base_url` 的 host 部分；但当 `base_url` 是 `host.docker.internal` 时，这个值不适合给物理 Worker 使用。

### 5.1 注册窗口与验签强制（/settings/registration-window、/settings/enforcement）

#### 说明

注册窗口是部署期的受控注册通道（2026-08-21 裁定取代原 `auto-register` 永久开关，旧端点已删除）：仅窗口开启期间，新设备上报（`GET /devices/report`）可携公钥自动注册入池并完成密钥认领；窗口关闭后上报只记指纹不入池（无窗口外注册通道）。TTL 硬上限 60 分钟（代码层不可配永久），到期自动关闭（懒计算，状态以查询结果为准）。全部端点需 `Authorization: Bearer`。

验签强制开关（过渡期兼容）：关闭时无密钥设备照现状放行（防冒领边界）；开启后 `/boot-vars` 对已绑定设备执行注入四条件第 4 条——无 `key_hash` → `no_key` 拒绝；缺 `nonce`/`sig` → `missing_sig` 拒绝；重放或签名无效 → 拒绝。已认领设备带无效签名在过渡期同样拒绝（伪造签名不放行）。建议全部存量设备完成密钥认领后再开启。

#### GET /settings/registration-window

查询注册窗口状态（无记录/已过期 → `open=false`）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `open` | bool | 窗口是否开启 |
| `opened_at` | str | 开启时刻 ISO8601（未开启为 `null`） |
| `ttl_minutes` | int | 开启时配置的 TTL 分钟数（未开启为 `null`） |
| `closes_at` | str | 预计关闭时刻 ISO8601（未开启为 `null`） |
| `remaining_seconds` | int | 剩余秒数（未开启为 `0`） |

```json
{"open": true, "opened_at": "2026-08-21T10:00:00+08:00", "ttl_minutes": 30, "closes_at": "2026-08-21T10:30:00+08:00", "remaining_seconds": 1799}
```

#### POST /settings/registration-window

开启注册窗口（状态码 201）。已开启 → 409（先关闭再开）；过期残留记录可直接重开（覆盖）。写入操作日志（`settings.registration_window`）。

**请求体**：

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `ttl_minutes` | 是 | int | 1-60（超出返回 400） |

```bash
curl -X POST http://<host>:4839/settings/registration-window \
  -H "Authorization: Bearer $CP_TOKEN" -H "Content-Type: application/json" \
  -d '{"ttl_minutes": 30}'
```

**响应**：同 GET（开启后的窗口状态）。

#### DELETE /settings/registration-window

提前关闭注册窗口（从未开启/无记录 → 409）。写入操作日志（`settings.registration_window`）。

```bash
curl -X DELETE http://<host>:4839/settings/registration-window \
  -H "Authorization: Bearer $CP_TOKEN"
```

**响应**：`{"open": false}`

#### GET/PUT /settings/enforcement

查询/切换设备身份验签强制开关（持久化到 `state/settings.json`，重启保留）。

**请求体（PUT）**：

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `enabled` | 是 | bool | `true` = 开启强制（无密钥/无签名设备拒绝引导） |

```bash
curl -X PUT http://<host>:4839/settings/enforcement \
  -H "Authorization: Bearer $CP_TOKEN" -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

**响应**：`{"enabled": bool}`（GET/PUT 相同）。PUT 写入操作日志（`settings.enforcement`）。

### 5.2 GET /devices/challenge

挑战端点（**不鉴权**）：为 `/boot-vars` 验签链路签发一次性 nonce（短 TTL、绑定 MAC、防重放，nonce 本身无秘密）。设备不存在或未认领（无 `key_hash`）→ **404**（无法走验签链路）。

**Query 参数**：

| 参数 | 必填 | 说明 |
|---|---|---|
| `mac` | 是 | MAC 地址（归一化规则同 `/boot-vars`） |

**成功返回（200，`text/plain`）**：`#!ipxe` 脚本体——iPXE 用 `chain` 直接消费，执行后 `${nonce}` 即为 64 hex 字符一次性 nonce：

```ipxe
#!ipxe
set nonce 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

**错误**：`400`（非法 MAC）；`404`（设备不存在/未认领）。

**挑战-响应链路（与 `/boot-vars` 配合，设备身份验签）**：

1. `GET /devices/challenge?mac=<mac>` → 执行响应脚本后取得 `${nonce}`
2. iPXE 用设备密钥对 `nonce‖mac‖hostname`（UTF-8 无分隔拼接，mac 小写冒号格式）做 ECDSA P-256 签名 → `sig`（base64(DER)）
3. `GET /boot-vars?mac=&hostname=&nonce=&sig=` → 验签通过才下发凭据（注入四条件第 4 条，见 5.1）；验签失败 → 空脚本（拒绝下发，审计 `boot_vars.credential`，reason 见 5.1）

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
    "base_url": "http://10.0.0.11:4840",
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
      "fs_type": "btrfs",
      "cd": false,
      "persistent": "saveconfig (auto-load on start)",
      "base_nqn": "nqn.2026-07.com.controller",
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
| `storager_ip` | 否 | 数据面地址（业务网段 IP，协议中立）。缺省时回退为 `base_url` 的主机名 |
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
    "storager_ip": "192.168.1.6",
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
  "storager_ip": "192.168.1.6",
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
| `role.disk` | 恒为 `true`（Agent 即存储节点） |
| `role.cd` | 取 `capabilities.cd` |
| `tags` | `["storage", backend]`（`backend` 为 lio / stgt，同时供 `/boot-vars` 连接符推导） |
| `storager_ip` | 缺省回退 `base_url` 主机名 |

### 请求体字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `base_url` | 是 | Agent 控制面 API 地址，须以 `http://` 或 `https://` 开头 |
| `token` | 否 | Agent 鉴权 Token；Agent 配置了 `IPXE_AGENT_TOKEN` 时必填（Agent 不回显自身 token，无法自动获取） |
| `agent_id` | 否 | 编辑场景：`token` 留空时，沿用注册表中该 Agent 的 token 探测（未知 id 忽略） |

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
  "storager_ip": "host.docker.internal",
  "enabled": true,
  "backend": "stgt",
  "fs_type": "btrfs",
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

## 6.3 PUT /agents/{agent_id}

### 说明

更新已有 Agent：覆盖 `config/agents.yml` 中对应条目，保存后立即生效（建盘/挂载调度即用新配置）。`id` 不可改（走路径参数）；`token` 传空字符串 = **保持原值**（API 不回显 token，前端无法回填）。

适用场景：存储节点配置变动——数据面地址迁移、API 地址变更、Token 轮换、停用 / 启用节点。

### 请求体字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `base_url` | 是 | Agent 控制面 API 地址，须以 `http://` 或 `https://` 开头，末尾 `/` 自动去除 |
| `token` | 否 | 传空字符串 = 保持原值（不覆盖）；传新值 = 轮换。支持 `${ENV}` 占位 |
| `storager_ip` | 否 | 数据面地址。缺省时回退为 `base_url` 的主机名 |
| `role` | 否 | 角色：`disk`=可建系统盘，`cd`=可挂载 ISO；默认 `{disk: false, cd: false}` |
| `tags` | 否 | 自由标签数组 |
| `enabled` | 否 | 是否启用；`false` 停用（不再参与建盘/挂载调度与存活探测）；默认 `true` |

### curl

```bash
curl -s -X PUT "$BASE_URL/agents/storage-stgt-02" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "base_url": "http://host.docker.internal:4840",
    "token": "",
    "storager_ip": "192.168.1.8",
    "role": {"disk": true, "cd": false},
    "tags": ["storage", "stgt"],
    "enabled": true
  }'
```

### 成功返回（200）

```json
{
  "id": "storage-stgt-02",
  "base_url": "http://host.docker.internal:4840",
  "storager_ip": "192.168.1.8",
  "role": {"disk": true, "cd": false},
  "enabled": true,
  "tags": ["storage", "stgt"]
}
```

### 错误返回

| 状态码 | 场景 |
|---|---|
| `400` | `base_url` 非 http(s) 开头 |
| `404` | Agent `id` 不存在 |

> **编辑探测**：编辑场景建议先调 `POST /agents/probe`（6.2）验证新地址可达再保存——`token` 留空时，探测请求带 `agent_id` 参数即可，后端自动沿用注册表中该 Agent 的 token。

---

## 7. POST /workers

### 说明

注册一台 Worker 的**身份**：hostname 绑定。**存储与身份分离**——本接口不创建任何系统盘，系统盘须另调 `POST /workers/{worker_id}/luns/disk`（见 7.1）。`mac` 现为**可选**：

- 不传 `mac` → 纯空转 Worker（仅 hostname 绑定，不授权任何设备），后续可用 `POST /devices/{mac}/bind`（16.7）绑定设备
- 传 `mac` → 设备须已在设备池中（`state=pooled`），校验后直接绑定（一对一授权）；设备池外或已绑定 → `409`——**先注册，后绑定**

Control Plane 会：

1. 校验 `worker_id`、`hostname`；传了 `mac` 时校验 `mac`
2. 写入 `state/workers.yml`（`disks` 为空数组，`state=registered`）
3. 传了 `mac` 时绑定设备（写 `state/devices.yml` 的 `bound_worker_id` + 写 `dnsmasq/dhcp-hosts.conf`）
4. 通过 Docker 向 `ipxe-dnsmasq` 容器发送 HUP：

```bash
docker exec ipxe-dnsmasq killall -HUP dnsmasq
```

5. 如指定 `windows_iso`，额外调用 Agent 创建 CD target（安装期光驱，与系统盘无关）

### 请求体字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `worker_id` | 是 | Worker 编号。会自动转为小写。允许字母、数字、点、下划线、短横线 |
| `mac` | 否 | Worker 网卡 MAC 地址，格式如 `00:0c:29:b9:8b:2d`。传入时设备须已在设备池中（见 16 节），本调用同时完成绑定 |
| `hostname` | 否 | 主机名。不传时默认等于 `worker_id` |
| `arch` | 否 | 架构。不传时默认 `x86_64` |
| `windows_iso` | 否 | Windows 安装期 ISO 文件名。传入即在注册时额外创建安装光驱 target |
| `boot` | 否 | iPXE 菜单默认项与超时配置；不传则由 `/boot-vars` 按默认启动系统和全局默认值推导。与 7.3 `default-os` 端点写的是同一组台账字段，后设覆盖先设 |

### `boot` 字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `menu_default` | 否 | iPXE 主菜单默认项（菜单超时后自动选中启动），合法值见 7.3 合法值表；不区分大小写，如 `ubuntu`、`debian`、`windows`、`exit` |
| `menu_timeout` | 否 | iPXE 菜单超时，单位毫秒，如 `5000`；传 `0` 表示菜单无限等待、永不自动选择 |

不传 `boot` 时：

- `menu_default` 默认使用 `default_os`（建盘后单独设置，见 7.3）；未设置时默认 `reboot`（循环重启等待配置，见 5 节）；
- `menu_timeout` 已配置默认启动时默认使用 `IPXE_CP_BOOT_MENU_TIMEOUT`（当前 `5000`）；处于 `reboot` 循环时固定用 `IPXE_CP_AUTO_BOOT_TIMEOUT`（当前 `1` 毫秒，见 5 节）。

因此大多数 Worker 不需要传 `boot`。例如：

```json
{
  "worker_id": "worker-01",
  "mac": "00:0c:29:b9:8b:2d"
}
```

注册后 Worker 还没有系统盘，`/boot-vars` 会返回 `menu-default reboot` + 1 毫秒超时——Worker 进入快速重启循环，等待管理员建盘/配置默认启动系统：

```ipxe
set menu-default reboot
set menu-timeout 1
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

### PUT /workers/{worker_id}/mac（换绑映射）

修改 Worker 的 MAC 绑定（hostname 不变），内部映射为**设备换绑**：新 MAC 须在设备池中（`state=pooled`），绑定到本 Worker；旧设备（若绑定本 Worker）解绑回池。审计同时记录 `device.bind`（新）+ `device.unbind`（旧）与兼容事件 `worker.mac.update`。

**请求体**：`{"mac": "00:0c:29:b9:8b:2d"}`

**409**：新 MAC 池外 / 已吊销 / 已绑定其他 Worker；旧设备绑定到意外 Worker。

**幂等**：重复设置同一 MAC 返回 `changed=false`。

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
      "nqn": "nqn.2026-07.com.controller:worker-01.ubuntu",  # NVMe-oF 数据面标识（权威，NQN 不用 IQN 定义）
      "iqn": "iqn.2026-07.com.controller:worker-01.ubuntu",  # iSCSI 数据面标识（由 NQN 派生）
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

**「默认启动系统」是干什么的**：一台 Worker 可以挂多块系统盘（同一系统至多一块，如 `ubuntu` + `windows`）。每次开机，iPXE 菜单在超时后会自动选中某一项启动——本端点配置的默认启动系统决定自动选中哪一项，同时决定 `/boot-vars` 投影哪块盘的连接信息（`base_nqn` / `storager_ip` 取默认启动盘，见 5 节）。不设置时菜单自动选 `reboot`，配合 1 毫秒超时循环重启，等待管理员完成配置，避免静默进错系统。

**注意**：`os` 不是系统盘的任意名称，而是 menu.ipxe 操作系统菜单项的 ID（与建盘 7.1 的 `os` 同枚举），与已挂系统盘一一对应。

`/boot-vars` 的 `menu_default` 推导链：

```text
default_os（本端点 os 字段，优先）-> boot.menu_default（本端点 menu_default 字段）-> reboot（未配置，循环重启等待）
```

请求体三个字段可单独或组合传，至少传一个；传 `null`（或空字符串）表示清除对应项。可重复调用，后设覆盖先设——与注册时传入的 `boot`（见 7.0）写的是同一组台账字段。

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
| `os` | 否 | 默认启动的系统（菜单项 ID，不是盘名）——仅允许 `windows` `ubuntu` `debian` `centos` `esxi`（与建盘 7.1 同枚举），不区分大小写（自动转小写），须与该 Worker 已挂系统盘一致；传 `null` 清除 |
| `menu_default` | 否 | iPXE 主菜单默认项（菜单超时后自动选中），见下方合法值表；不区分大小写（自动转小写）；传 `null` 清除 |
| `menu_timeout` | 否 | 菜单超时毫秒数，非负整数；传 `0` 表示菜单无限等待、永不自动选择（等人工按键）；传 `null` 清除，恢复默认 `IPXE_CP_BOOT_MENU_TIMEOUT`（当前 `5000`） |

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

## 7.5 PUT /workers/{worker_id}/mac

### 说明

修改指定 Worker 的 **MAC 地址绑定**（hostname 不变）：Control Plane 会：

1. 校验 Worker 存在（不存在时返回 `404`）
2. 校验新 MAC 格式（非法返回 `400`）；**新 MAC 已被其他 hostname 占用时返回 `409`**（不写入，防止一 MAC 多 Worker）
3. 更新 `dnsmasq/dhcp-hosts.conf` 中该 hostname 的绑定并 HUP 重载 dnsmasq（保持文件 inode 不变，文件级 bind mount 下重载立即可见）
4. **审计记录 `worker.mac.update`（含 `old_mac` / `new_mac` / `changed` / `client`）**——即修改历史，可通过 `GET /operations` 查询；新 MAC 与旧 MAC 相同时 `changed=false`，不触发重载

> **注意**：`workers.yml` 台账不存 MAC，MAC 唯一权威在 `dnsmasq/dhcp-hosts.conf`，本端点直接改绑定文件；改完后 Worker 需重新获取 DHCP 租约（重启网卡 / 重新 PXE 启动）才会使用新 MAC 对应身份。

### Body 参数

| 参数 | 必填 | 说明 |
|---|---:|---|
| `mac` | 是 | 新 MAC 地址，格式 `XX:XX:XX:XX:XX:XX`（大小写均可，统一规范化） |

### 示例

```bash
curl -s -X PUT "$BASE_URL/workers/worker-01/mac" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"mac": "00:0c:29:b9:8b:01"}'
```

### 成功返回

返回该 Worker 的完整台账（`mac` 字段为更新后的实时反查结果）。

### 常见错误

| HTTP 状态码 | 常见原因 |
|---:|---|
| `400` | `mac` 格式非法 |
| `401` | 缺少 Token 或 Token 错误 |
| `404` | Worker 不存在，或该 hostname 在 dnsmasq 中无绑定 |
| `409` | 新 MAC 已被其他 hostname 占用 |
| `500` | dnsmasq 重载失败（绑定文件已更新） |

---

## 7.6 POST /workers/batch

### 说明

批量创建 Worker（**逐项独立**，单项失败不影响其余；**幂等**，重复执行不产生重复 Worker）。按 `name_prefix` + 序号生成 `worker_id`（`worker-01`、`worker-02` …，序号从 `01` 起，位宽随 `count` 自适应——`count=100` 时生成 `worker-001` … `worker-100`）。

- 不传 `macs` → 全部为**纯空转** Worker（仅 hostname 绑定，不授权任何设备），后续可用 `POST /devices/{mac}/bind`（16.7）绑定
- 传 `macs`（须与 `count` 等长）→ 逐项校验设备池并直接绑定（语义同 7 节传 `mac`：设备须 `state=pooled`，池外 / 已绑定 → 该项 `failed` 且**该项不创建**，可修正后重试）

不支持 `windows_iso`（安装期 ISO 请逐个走 7 节）。

### 请求体字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `count` | 是 | 创建数量，1–100 |
| `name_prefix` | 否 | Worker 编号前缀，默认 `worker-`。生成的 `worker_id` 须合法（允许字母、数字、点、下划线、短横线），非法前缀整批返回 `400` |
| `macs` | 否 | MAC 地址数组（格式 `00:0c:29:b9:8b:2d`），提供时长度必须等于 `count`，逐项校验并直接绑定 |
| `arch` | 否 | 架构。不传时默认 `x86_64` |
| `boot` | 否 | iPXE 菜单默认项与超时配置，字段同 7 节 |

### 幂等与失败分类

- `succeeded`：本次创建成功（传了 `macs` 时含绑定——绑定成功才创建该项）
- `skipped`：`worker_id` 已存在（重复执行同一请求的结果）
- `failed`：设备池外 / 已吊销 / 已绑定 / MAC 非法 / hostname 冲突等——该项不创建，其余项不受影响；修正后可重试

### 示例

```bash
curl -s -X POST "$BASE_URL/workers/batch" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "count": 3,
    "name_prefix": "worker-",
    "macs": ["00:0c:29:b9:8b:01", "00:0c:29:b9:8b:02", "00:0c:29:b9:8b:03"]
  }'
```

### 成功返回（200）

```json
{
  "succeeded": [
    {"worker_id": "worker-01", "hostname": "worker-01", "mac": "00:0c:29:b9:8b:01"}
  ],
  "skipped": [],
  "failed": [
    {
      "worker_id": "worker-02",
      "hostname": "worker-02",
      "mac": "00:0c:29:b9:8b:02",
      "error": "device already bound to worker-01: 00:0c:29:b9:8b:02"
    }
  ]
}
```

### 常见错误

| HTTP 状态码 | 常见原因 |
|---:|---|
| `400` | `name_prefix` 为空 / 生成的 `worker_id` 非法 / `macs` 长度不等于 `count` |
| `401` | 缺少 Token 或 Token 错误 |
| `422` | `count` 缺失 / 不在 1–100 范围 |

---

## 7.7 NVMe-oF 认证凭据（/workers/{worker_id}/credential）

### 说明

NVMe-oF 连接认证密钥库（按 Worker 跟盘裁定 2026-08-22）：密钥按 `worker_id` 索引，绑定到该
Worker 的设备共享同一密钥（换绑即换钥）。密钥为 **DHHC-1** 格式（蓝图 2.1 契约）：
`DHHC-1:<两位数字类型>:<base64(密钥 + CRC32 小端 4 字节)>`，密钥体 32 字节（SHA-256）或 64 字节（SHA-512）。

凭据写入后控制面会**推送期望状态给持有该 Worker 系统盘的 Agent**（审计 `credential.push`，不记密钥本体）：
Agent 转调存储节点 nvmet 宿主服务登记 hosts（子系统 = 盘（NQN 命名：盘标识权威 = NQN，IQN 由 NQN 派生（`iqn.` + nqn[4:]），如
`nqn.2026-07.com.controller:worker-01.ubuntu` → `iqn.2026-07.com.controller:worker-01.ubuntu`；
IQN 不作子系统 NQN 使用，NVMe Base Spec §7.9 要求 `nqn.` 前缀），Host NQN = 绑定设备 UUID 派生
`nqn.2014-08.org.ipxe:<uuid>`，无 UUID 设备回退共享 NQN `nqn.2014-08.org.ipxe:ipxe`）；
推送失败仅审计不阻断（Agent 缓存先行，reconcile 周期重放补齐）。

触发推送的操作：设置/删除凭据、设备绑定/解绑/换绑（`PUT /workers/{worker_id}/mac`）、建盘/删盘（含批量）、删除 Worker。

### PUT /workers/{worker_id}/credential

设置或更新密钥（幂等：重复设置同值 `updated_at` 不变）。

```bash
curl -X PUT "$BASE_URL/workers/worker-01/credential" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"secret": "DHHC-1:01:<base64>"}'
```

成功返回：

```json
{
  "worker_id": "worker-01",
  "exists": true,
  "secret_hash": "sha256:1a2b3c4d5e6f",
  "created_at": "2026-08-22T08:00:00+00:00",
  "updated_at": "2026-08-22T08:00:00+00:00"
}
```

| HTTP 状态码 | 常见原因 |
|---:|---|
| `422` | DHHC-1 自检失败（前缀/类型位数/base64/长度 36/68/CRC 终值任一不符） |
| `404` | Worker 不存在 |

### DELETE /workers/{worker_id}/credential

删除密钥（吊销该 Worker 名下全部绑定设备的认证资格，下次启动回落明文连接）：

```bash
curl -X DELETE "$BASE_URL/workers/worker-01/credential" -H "Authorization: Bearer $TOKEN"
```

成功返回 `{"deleted": "worker-01"}`；Worker 或条目不存在 → `404`。

### GET /workers/{worker_id}/credential

查询凭据元数据（**不返回明文**，`secret_hash` 只给前缀便于轮换比对）：

```bash
curl -s "$BASE_URL/workers/worker-01/credential" -H "Authorization: Bearer $TOKEN"
```

```json
{
  "worker_id": "worker-01",
  "exists": true,
  "secret_hash": "sha256:1a2b3c4d5e6f",
  "created_at": "2026-08-22T08:00:00+00:00",
  "updated_at": "2026-08-22T08:00:00+00:00"
}
```

无条目时 `exists=false` 且无 `secret_hash`。

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
2. **联动解绑设备**：所有 `bound_worker_id` 为该 Worker 的设备回池（`state=pooled`、`bound_worker_id=null`，设备**不吊销**）——先解绑落盘，解绑失败则中止删除
3. 如果存在 cd target，先删 cd
4. 再删 disk target
5. 从 `workers.yml` 删除该 Worker
6. 从 `dnsmasq/dhcp-hosts.conf` 删除 `mac,hostname` 这一行
7. HUP `ipxe-dnsmasq`

`POST /workers/delete/batch`（11.1）同样联动解绑。

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
| `mac` | 否 | — | 仅返回该设备（MAC）的操作（规范化后按 `mac` 字段过滤），用于设备绑定记录查看 |

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

在指定 Agent 上创建磁盘 LUN。传 `master` 走母盘克隆（优先 btrfs / ZFS(≥2.2) reflink 秒级），传 `size` 建空白盘（sparse）。Agent 未配置 `role.disk` 时返回 `400 agent ... not configured for disk role`。

#### Path 参数

| 参数 | 必填 | 说明 |
|---|---:|---|
| `agent_id` | 是 | Agent 标识 |

#### 请求体字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `iqn` | 是 | target IQN（盘 NQN 的派生形态），必须以该 Agent 的 IQN base（源自 `IPXE_NQN_BASE`）为前缀 |
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
| `iqn` | 否 | target IQN；不传时由 Agent 按派生 IQN base（源自 `IPXE_NQN_BASE`）:iso文件名 自动生成 |

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

## 15. GET /masters（母盘清单）

### 说明

聚合列出全部**启用磁盘角色**（`enabled=true` 且 `role.disk=true`）Agent 上的母盘清单。母盘由存储节点 Agent 的后台扫描线程周期扫描（默认每 30 秒），识别 `DISK_DIR` 下文件名含 `_tpl_` 标记的镜像文件（如 `_tpl_ubuntu_2204.img`）。

供 WebUI 母盘克隆下拉列表选盘。**与创建 Worker 的 API 无联动**——纯只读查询，不改任何状态，不写台账。

### 失败容错

- 单台 Agent 不可达或鉴权失败：该节点返回 `error` 字段并记审计 `master.list`（failed），**不阻塞整体**；
- 全部节点失败：整体返回 `502`；
- 部分成功 / 无可用节点：返回 `200`（无节点时 `agents` 为空数组）。

### curl

```bash
curl -s "$BASE_URL/masters" \
  -H "Authorization: Bearer $TOKEN"
```

### 成功返回示例

```json
{
  "agents": [
    {
      "agent": "storage-lio-01",
      "storager_ip": "192.168.80.3",
      "masters": [
        {"name": "_tpl_ubuntu_2204.img", "size": 10737418240, "mtime": 1785643200},
        {"name": "_tpl_debian_12.img", "size": 8589934592, "mtime": 1785729600}
      ]
    }
  ]
}
```

| 字段 | 说明 |
|---|---|
| `agents` | 数组，每项对应一个启用磁盘角色的 Agent |
| `agents[].agent` | Agent 编号（`config/agents.yml` 的 key） |
| `agents[].storager_ip` | 数据面地址（与 `/boot-vars` 相同的回退规则） |
| `agents[].masters` | 母盘数组，每项 `{name, size, mtime}`：文件名 / 字节大小 / 修改时间戳 |
| `agents[].error` | 该节点查询失败时的错误详情（成功节点无此字段） |

---

## 16. 设备池（设备台账）

设备台账（`state/devices.yml`）是三层实体模型（设备 / Worker / 系统盘）的底层实体：窗口期注册与手动导入只入设备池，**注册 ≠ 授权**——设备需绑定到 Worker 后才有身份。绑定关系权威在设备侧（`bound_worker_id`），Worker 侧只投影不存储。

**绑定语义（P2）**：设备 ↔ Worker 严格**一对一**。绑定走 `POST /devices/{mac}/bind`（16.7）；`force=true` 原子换绑（预校验 → 新绑定落盘 → 旧绑定清除 → 失败回滚）。解绑（`DELETE /devices/{mac}/bind`，16.8）后设备回池，Worker 的系统盘保留。删除 Worker 联动解绑（11 节）。`POST /workers` 传 `mac` 也直接完成绑定（7 节）。

**readiness 投影**：Worker 响应（列表 / 详情 / 状态）按台账派生两个字段：

- `bound_device`：绑定到该 Worker 的设备 MAC（无则 `null`）
- `readiness`：`ready`（绑定设备且有系统盘）/ `partial`（绑定设备**或**有系统盘）/ `idle`（两者皆无）

### 设备状态

| 状态 | 说明 |
|---|---|
| `pooled` | 在设备池中，未绑定（自动入池 / 手动注册 / 批量导入） |
| `bound` | 已绑定到 Worker（一对一），绑定关系见 `bound_worker_id` |
| `revoked` | 已注销（吊销），不再接受上报，不可重新注册 |

### 记录结构（示例）

```yaml
devices:
  "00:0c:29:b9:8b:2d":
    mac: 00:0c:29:b9:8b:2d
    uuid: "4c4c4544-..."          # SMBIOS UUID（双因子，可选）
    state: pooled                 # pooled | bound | revoked
    bound_worker_id: null         # 绑定关系权威在此，worker 侧只投影
    key_hash: null                # 安全蓝图阶段填充，本期留空
    source: ipxe                  # ipxe（自动入池）| manual（手动录入/导入）
    fingerprint:                  # 申报性质，设备上报更新
      manufacturer: ASUSTeK COMPUTER INC.
      product: ROG Zephyrus G15
      serial: "..."
      cpumodel: "Intel(R) Core(TM) Ultra 7 155H"
      mem_total: 32768            # 归一化十进制（兼容 0x hex 上报）
      mem_type: DDR5
      mem_speed: 5600
      chip: RTL8125
      busid: "0110ec8125"
    first_seen: 2026-08-15T10:00:00+08:00
    last_seen: 2026-08-15T12:00:00+08:00
```

### 16.1 GET /devices

设备池列表，`state` 过滤（`all` / `pooled` / `bound` / `revoked`，默认 `all`）。

**curl**：

```bash
curl http://<host>:4839/devices?state=pooled \
  -H "Authorization: Bearer $CP_TOKEN"
```

**成功返回**：数组，每项为一条设备记录（见上「记录结构」）。

### 16.2 GET /devices/{mac}

单设备详情（绑定 Worker、指纹、首/末次上报）。`mac` 用带冒号格式（`00:0c:29:b9:8b:2d`）。

**404**：设备不存在。

### 16.3 POST /devices

手动注册设备：MAC（+可选 UUID/型号/序列号）入池。

**请求体**：

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `mac` | 是 | str | MAC 地址 |
| `uuid` | 否 | str | SMBIOS UUID（双因子，可选） |
| `manufacturer` / `product` / `serial` | 否 | str | 申报信息，仅作台账初始值，设备上报后以申报值为准更新 |

**成功返回（201）**：设备记录（`state=pooled`，`source=manual`）。

**409**：设备已存在（含已吊销——吊销设备不可重新注册）。

### 16.4 POST /devices/import

批量导入设备清单（MAC 清单预导入）：逐项独立，重复跳过，非法/吊销计 `failed`。

**请求体**：

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `entries` | 是 | array | 清单数组，每项同 16.3 请求体（`mac` 必填） |

**成功返回**：

| 字段 | 说明 |
|---|---|
| `created` | 本次新增入池的 MAC 列表 |
| `skipped` | 已存在（pooled/bound）跳过项及原因 |
| `failed` | 非法 MAC / 已吊销项及原因 |

### 16.5 DELETE /devices/{mac}

注销设备（吊销）：`pooled` → `revoked`，设备保留在台账（审计保留）。

**409**：设备已绑定 Worker（须先解绑）或已吊销。

### 16.6 GET /devices/report

iPXE 设备信息上报入口（**不鉴权**，由 `boot.ipxe.cfg` 在请求 `/boot-vars` 之前先 `chain`）：更新指纹 + `last_seen`；未知 MAC 仅在注册窗口开启且带有效公钥时入池。**返回空脚本体**（`#!ipxe\n`，`chain` 可直接消费，无脚本副作用；空 body 会被部分 iPXE 报 EOF，故统一返回合法空脚本）。

| 参数 | 必填 | 说明 |
|---|---|---|
| `mac` | 是 | MAC，支持带冒号（`${mac}`）与 hex 无分隔（`${netX/mac}`）格式 |
| `uuid` / `manufacturer` / `product` / `serial` / `cpumodel` / `mem-type` / `chip` / `busid` | 否 | 字符串字段，空值容忍 |
| `mem-total` / `mem-speed` | 否 | 整数，兼容 `0x` hex 与十进制，归一化十进制存储 |
| `pubkey` | 否 | ECDSA P-256 公钥（130 hex 未压缩点），注册/认领用；无参数或非法 → 忽略 |

行为：

- 已注册设备：更新指纹（非空字段覆盖）+ `last_seen`，`state` 不变；窗口开启且带有效公钥时填充 `key_hash`（密钥认领），密钥不一致 → 拒绝覆盖（仅审计 `device.claim rejected`）
- 吊销设备：忽略（不更新、不复活）
- 未知 MAC + 注册窗口开启 + 带有效公钥：入池（`state=pooled`，`key_hash` 填充，`source=ipxe`）
- 未知 MAC + 窗口关闭 / 无公钥：只更新指纹不入池（注册只在窗口期，见 5.1）

**curl**（模拟 iPXE 上报）：

```bash
curl "http://<host>:4839/devices/report?mac=000c29b98b2d&uuid=4c4c4544-...&manufacturer=ASUSTeK%20COMPUTER%20INC.&product=ROG%20Zephyrus%20G15&cpumodel=Intel(R)%20Core(TM)%20Ultra%207%20155H&mem-total=0x8000&mem-type=DDR5&mem-speed=5600&chip=RTL8125&busid=0110ec8125"
```

### 16.7 POST /devices/{mac}/bind

绑定设备到 Worker（一对一授权）。设备或 Worker 已绑定时默认 **409**；`force=true` 执行**原子换绑**：预校验 → 新绑定落盘 → 旧绑定清除（旧设备回池）→ 失败时恢复台账快照并尽力恢复 dnsmasq（见 17 节「实现边界」）。幂等：同一设备重复绑定同一 Worker 返回 `200` 且不改动。

| Query 参数 | 必填 | 默认 | 说明 |
|---|---:|---|---|
| `worker_id` | 是 | — | 目标 Worker |
| `force` | 否 | `false` | 设备或 Worker 已绑定时原子换绑 |

**404**：设备或 Worker 不存在。**409**：设备已吊销 / 已绑定（未传 `force`）/ Worker 已绑定（未传 `force`）/ dnsmasq 冲突。

`force=true` 换绑场景：

- 设备已绑 `worker-01`，换到 `worker-02` → 设备迁移，`worker-01` 变空转（无设备）
- `worker-02` 原绑定的其他设备 → 回池
- 设备已绑 `worker-02` 且 `worker-02` 绑定该设备 → 幂等成功

审计记录 `device.bind`（含 `old_worker_id` / `old_device_mac`，即换绑历史）。

**curl**：

```bash
curl -X POST "http://<host>:4839/devices/00:0c:29:b9:8b:2d/bind?worker_id=worker-01&force=false" \
  -H "Authorization: Bearer $CP_TOKEN"
```

**成功返回（200）**：设备记录（`state=bound`，`bound_worker_id=worker-01`）。

### 16.8 DELETE /devices/{mac}/bind

解绑设备：回池（`state=pooled`、`bound_worker_id=null`），移除 dnsmasq 绑定并重载；Worker 的系统盘保留（其 `readiness` 降级为 `partial`/`idle`）。

**409**：设备未绑定。**404**：设备不存在。

**curl**：

```bash
curl -X DELETE "http://<host>:4839/devices/00:0c:29:b9:8b:2d/bind" \
  -H "Authorization: Bearer $CP_TOKEN"
```

### 16.9 POST /devices/bind/batch/preview

批量绑定**预览**（只读，不写任何东西）：把清单配成配对表。

**请求体**：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `mode` | 否 | `manifest`（默认）：用 `pairs`；`sequential`：`macs[i]` ↔ `worker_ids[i]` 按下标配对（长度不等 → `400`） |
| `pairs` | 否 | 数组，每项 `{mac, worker_id, manufacturer?, product?, serial?, uuid?}`；可选字段为**申报比对列**，与设备上报指纹比对（见下） |
| `macs` / `worker_ids` | 否 | `mode=sequential` 使用 |

逐项归类（独立判定，不整批拒绝）：

- `matched`：设备在池未绑定 + Worker 存在 + Worker 未绑定（含 `device_state`、`worker_state`、`fingerprint_mismatch`）
- `conflicts`：设备已绑定 / Worker 已绑定 / 清单内重复 MAC / Worker 不存在
- `not_found`：设备池外（`device not in pool`）、已吊销、MAC 非法

`fingerprint_mismatch` 一致时为 `null`，否则 `{"fields": ["serial", ...]}`——申报值与上报值（两者均非空）不符的列。申报性质，不阻断绑定。

**成功返回**：`{matched: [...], conflicts: [...], not_found: [...], summary: {total, ok, conflict, not_found}}`。

### 16.10 POST /devices/bind/batch

批量绑定**执行**（幂等，逐项独立，单项失败不影响其余）。请求体同 16.9。归类：

- `succeeded`：本次绑定成功（申报值与上报值不符时带 `fingerprint_mismatch` 标记）
- `skipped`：已绑定（同 Worker）/ 设备已绑定其他 Worker / Worker 已绑定 / 清单内重复 MAC
- `failed`：设备不存在（池外——先经 16.3/16.4 入池）/ MAC 非法

**审计**：除 `device.bind.batch` 汇总外，每个 `succeeded` 项另逐条记录 `device.bind`（`mac` / `worker_id`），保证设备绑定历史（`GET /operations?mac=`）完整；`skipped` / `failed` 仅在汇总计数。

**成功返回**：`{succeeded: [...], skipped: [...], failed: [...]}`。已完成的清单重跑全部 `skipped`。

**curl**：

```bash
curl -X POST "http://<host>:4839/devices/bind/batch" \
  -H "Authorization: Bearer $CP_TOKEN" \
  -d '{"mode":"manifest","pairs":[{"mac":"00:0c:29:b9:8b:2d","worker_id":"worker-01"}]}'
```

---

## 17. 当前实现边界

当前版本已经支持：

- Worker 身份注册（hostname 绑定；`mac` 可选，传了直接绑定设备）
- 批量创建 Worker（数量 + 命名规则，`macs` 可选直接绑定，`POST /workers/batch`，7.6 节）
- 设备台账（自动入池 / 手动注册 / 批量导入 / 注销吊销，`/devices` 系列端点）
- 设备↔Worker 一对一绑定（绑定 / force 换绑 / 解绑 / 批量绑定预览+执行，16.7–16.10）
- Worker `mac` 换绑映射（`PUT /workers/{worker_id}/mac`，7 节）
- 删除 Worker 联动解绑（11 / 11.1 节）
- boot-vars 防冒领（绑定即认证，5 节）
- iPXE 设备信息上报（11 字段指纹，`GET /devices/report`，窗口期注册只入池不建 Worker）
- Worker 系统盘创建（`POST /workers/{worker_id}/luns/disk`）
- Worker 默认启动配置设置（系统 / 菜单项 / 超时，`PUT /workers/{worker_id}/default-os`）
- Worker 删除
- Agent 选择
- Agent LUN 直管（列出 / 创建磁盘 / 创建 CD / 删除 / 扫描）
- 母盘清单查询（`GET /masters`，存储节点后台周期扫描缓存）
- Windows ISO 特例
- dnsmasq 主机名绑定
- Worker 与操作轨迹查询
- 多系统盘（一个 Worker 可挂载多个系统的系统盘，同一系统至多一个，由 `os` 区分、`default_os` 决定默认启动）
- NVMe-oF 认证凭据库（DHHC-1，按 Worker 跟盘，7.7 节；/boot-vars 注入 `nbft_secret`，5 节）
- 凭据推送驱动（凭据设置/吊销、绑定/解绑/换绑、建盘/删盘、删 Worker 时推送 Agent，Agent 转调 nvmet 宿主服务同步 hosts 矩阵）

当前版本还没有做：

- 自动 IP 管理
- 自动母盘生命周期管理
- 定时 reconcile
- 数据盘挂载（`/luns/data` 命名空间已预留）
- 文件存储无真正事务：回滚 = 重写；换绑清除旧绑定失败且恢复也失败时，靠审计定位手动处理（16.7）
---

### 各组件使用以下端口: 
#### Control
- dnsmasq: `67` , `66`
- nginx: `4838`
- Control_Plane: `4839`
#### iSCSI-sever
- Agent: `4840`
- Lio / stgt : `3260`
