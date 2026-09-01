# 更新记录 (CHANGELOG)

本文件记录 Kurrent（周流）项目的功能变更、接口调整与缺陷修复。

## 记录规范

- 每次代码 / 配置变更完成后，在对应日期区块追加条目（新增 / 变更 / 修复）
- **新增**：新功能、新端点、新配置项
- **变更**：行为调整、接口变更、数据模型调整
- **修复**：缺陷修复
- 涉及多个模块的改动，按模块分条列出；接口变更同时需同步 `api/control-plane-api.zh-CN.md` 与 `api/control-plane-api.en.md`（控制面 API 参考唯一权威；docs/ 文档站冻结待重写，不再修改）

---

## 2026-09-01

### 修复

- **enroll token 消耗顺序（nvmet-host 重试不再烧 token）**——`POST /enroll` 先校验在册再 consume：nvmet-host 与 agent 共享 agent_id，agent 未登记时 400 拒绝且 token 保持可用（restart 重试即 201），消除「400 但 token 已 used」崩溃循环；回归测试 `test_nvmet_token_not_burned_when_agent_missing`
- **storager-agent 镜像旧导致 base_url 上报缺失**——容器内 `pki_client.py` 为旧版（`docker compose up -d` 不带 `--build` 不更新 COPY 层，宿主文件与镜像内文件不同步），`--build` 重建镜像并重走 join 后恢复 base_url 登记

### 变更

- **Agent 能力上报（K8S `--node-labels` 同构）**——`pki_client.py` 引导时随 enroll 上报 `capabilities`（backend/cd；映射表 `BACKEND_CD_CAPABILITY`：stgt 支持 CD，lio/nvmet 不支持）；`/enroll` 自动登记据此推导 `tags=[auto, storage, <backend>]` 与 `role.cd`；旧 agent 缺省兼容（tags=auto、role.cd 默认 false）
- **光驱能力 UI 隐藏策略（不支持的后端不显示）**——AgentLuns 详情页：`role.cd=false` 时隐藏「+ 创建光驱」按钮与提示（移除写死 LIO 文案）、状态栏 cd 标记条件显示；Agents 列表页光驱属性行仅 `capabilities.cd=true` 时显示；i18n 键拆分（`statusRole`/`statusRoleCd`）

### 新增

- 回归测试 4 用例（token 不烧 1 + 能力推导 3：nvmet/stgt/旧兼容），控制面全量 187 测试通过

---

## 2026-08-31

### 新增

- **组件 PKI 体系（kubeadm 同构：bootstrap token + 组件证书 mTLS）**——控制面 `pki.py`：CA 自举（`state/pki/`）、bootstrap token 签发与一次性消耗（复合键 `agent_id/component`，Bearer 头携带）、组件证书签发（client/serving 双证书，CSR 控制面签发、serving SAN 校验）；`POST /enroll` 登记端点（agent_id/component/双 CSR/serving_sans/base_url），agent 与 nvmet-host 共享 agent_id，agent 自动登记（首次引导写入 agents.yml：base_url、role_disk、tags=auto）；`storager/agent` 与 `nvmet-host` 各新增 `pki_client.py` 引导客户端（首次引导 enroll → 证书落盘 → 到期自动续签，`KURRENT_*` 环境变量驱动，`KURRENT_ADVERTISE_URL` 支持 base_url 上报）
- **一键加入（kurrent-join.sh + CLI）**——`storager/kurrent-join.sh` 幂等 upsert `.env`（agent_id/bootstrap token/CP 地址/backend 等 8 键）+ `docker compose up -d`；`cli/`（Go）`kurrent join` 命令（连接控制面 → 签发 agent/nvmet-host 双 bootstrap token → 本地执行 join 脚本）+ `agents/nodes/workers` 子命令；`tests/scripts/test_kurrent_join.sh` 端到端脚本测试
- **Agent 管理 WebUI 增强**——Agents 页 agent 详情卡（backend/tags/base_url/health）、AgentLuns 操作面板、全局 `Modal.jsx` 组件、Layout 侧边栏重构（收起态）
- 组件 PKI 与一键加入测试套件——`tests/control_plane/test_join_flow.py`（join 全流程）、`tests/agent/test_pki_client.py`、`tests/pki_testkit.py`（测试 CA 工具）、`tests/scripts/test_kurrent_join.sh`；既有测试夹具同步 mTLS 化

### 变更

- **nginx 客户端 mTLS 认证**——`/agents/*`、`/luns/*` 等 agent 通道要求控制面 CA 签发证书，与 agent/nvmet-host 证书体系闭环；`nginx.conf` 新增 `ssl_verify_client` 配置
- **storager-agent / nvmet-host mTLS 化**——两组件对外调用改走 pki_client 证书（`agent_client.py` 双端适配），`/capabilities` 端点返回 backend/cd；nvmet-host 接入 `KURRENT_BACKEND`/`AGENT_PKI_HOST` 等配置；docker-compose/Dockerfile/requirements/.env.example 配套更新
- **WebUI 全站改造**——Agents/AgentLuns/Operations/WorkerDetail/Workers 页面重写（详情页布局：顶部状态栏 + 分类 Tab）；控制面 `agent_client.py`/`config.py`/`main.py` mTLS 与证书链适配

---

## 2026-08-30

### 变更

- **母盘身份标签分层模型（os_tag 盘级随机标识，2026-08-30 裁定）**——数据面唯一标识 = `worker_id.os.<os_tag>`（os_tag = 12 位 hex 随机串，`secrets.token_hex(6)`，docker 容器 ID 短形式；进盘 NQN / 文件名，IQN 由 NQN 派生）；上层台账 = (os, os_version, os_tag) 备注性质（人类理解用）；`build_nqn`/`build_disk_filename` 后缀带 os_tag（`worker-01.ubuntu.0d26b6f33a89`）；盘唯一性改为同一 worker 同一 (os, os_version) 至多一块（`find_disk_by_os_version`，空版本用 `''` 参与唯一键），同系统不同版本可并存；删盘/默认启动改按 os_tag 引用（`find_disk_by_tag`）
- **OS_ITEMS 退役（建盘 os 校验放开）**——2026-08-30 起不再存在合法 OS 集合：建盘 `os` 为自由字符串（小写归一，仅格式校验），同系统多版本靠盘级 os_tag 区分；`CreateWorkerDiskRequest`/`BatchCreateWorkerDiskRequest` 新增 `os_version` 字段（空 = 无版本）；`PUT /workers/{worker_id}/default-disk`（原 `/default-os` 废止）`disk` = 盘 os_tag（12 hex，精确引用具体盘），`menu_default` 严格校验集合收敛为导航项 + 遗留 OS 名（归一为 `boot-os`）
- **boot-vars 从默认盘投影系统标识 + menu 归一（MAIN MENU 动态化）**——`/boot-vars` 新增 `os`/`os_version`/`os_tag` 字段（来源 = 默认盘记录投影，与盘 NQN 后缀同源；空版本不下发），`base_nqn` 语义 = 盘 NQN 前缀（统一模板 `base:worker_id.os.<os_tag>`）；`menu_default` 推导链 `default_disk > boot.menu_default > reboot`，OS 语义默认值统一归一为唯一通用项 `boot-os`；`tftp/menu.ipxe` 主菜单收敛为唯一 OS 项（`os-label` 拼版本展示、root-path 拼 `${hostname}.${os}.${os-tag}`，新增 OS 无需改脚本）；WebUI WorkerDetail 建盘表单/默认启动选择器（os_tag）/boot-vars 预览、Workers 批量建盘同步；api/ 两份 API 文档全量同步（6.4 母盘标签新节、7.0-7.4 重写、13.6/17 节）

### 新增

- **母盘标签登记台账 + 端点（控制面登记，备注性质）**——`state/masters.yml`（`MasterTagStore`，键 = agent_id → 母盘名 → {os, os_version}，库表形态：字段原子、空版本 `''`）；`PUT/DELETE /agents/{agent_id}/masters/{master_name}/tag` 登记/清除（不校验母盘存在性，Agent 离线台账即权威）；`GET /masters` 聚合时合并标签（有登记附加 os/os_version，未登记不附加）；`KURRENT_CP_MASTERS_FILE` 配置项；WebUI AgentLuns 页母盘标签登记面板（编辑/保存/清除）；控制面测试新增母盘标签 8 用例，全量 203 测试通过

---

## 2026-08-24

### 修复

- **nvmet-host configfs 语义纠正（真实内核验证；2026-08-23「DH-HMAC-CHAP 认证三缺陷」条目方向作废，以本条为准）**——固件仓库联调实测 Linux v7.x nvmet 语义：host 条目是**全局**的（顶层 `hosts/<HOSTNQN>/dhchap_key` 写 DHHC-1 明文即启用认证，**无独立 control 属性**）；严格模式（`attr_allow_any_host=0`）host 准入 = `subsystems/<NQN>/allowed_hosts/` 下 **symlink 挂载全局 host 条目**（target 须 `nvmet_host_type`，否则 EINVAL），symlink 目标由内核按进程 cwd 解析须**绝对路径**（08-23 的「subsystems hosts/ 目录登记即准入 + nvme-auth-dhchap-control=1 置位 + 删除 allowed_hosts symlink」与真实语义不符）；端口在首个子系统挂载时才启用监听，`addr_*` 启用后不可写（-EACCES），删除 `addr_tsas` 写入（不写即无 TLS）；删除子系统须先摘 port / allowed_hosts 挂载再 rmdir（否则 EBUSY）；同步 storager/agent nvmet.py docstring、nvmet-host main.py 全量 configfs 操作、测试断言（allowed_hosts 列表 / dhchap_key / 删除顺序），nvmet-host 14 用例通过
- **/boot-vars 签名兼容还原（联调 verify_failed 修复）**——iPXE 拼 URL 不做百分号编码：base64(DER) 的 `+` 原样进入 query，Starlette 按 form-urlencoded 规则解码为空格 → 验签必败；验签前 `sig = sig.replace(" ", "+")`（base64 字符集不含空格，同时兼容 %2B 显式编码与未编码两种传递）
- **/devices/report 返回空脚本体（联调 EOF 修复）**——4 处空 `Response(status_code=200)` 改为 `Response("#!ipxe\n", media_type="text/plain")`：空 body 部分 iPXE 报 EOF，统一返回合法空脚本供 chain 直接消费（无脚本副作用）
- **凭据幂等重放补推**——`set_worker_credential` 同值幂等分支（changed=False）也调 `_push_credentials`：上次推送失败（agent 离线 / 中途失败）时重放同值密钥可补推，agent 侧 set_host 幂等、重复推送无害

### 变更

- **Host NQN 注入（C2 凭据链路配套，固件 0011 补丁消费）**——`/boot-vars` 新增 `hostnqn` 字段（iPXE / JSON 双格式）：iPXE nvmetcp 默认 hostnqn 为 `nqn.2014-08.org.ipxe:<uuid>`（无 UUID 回退 `:ipxe`），与 nvmet-host 登记的 `host.<worker_id>` 不匹配则严格模式认证必败，须按 worker 投影同一身份覆盖；`HOST_NQN_PREFIX` 硬编码改读 `settings.nqn_base`，新增 `KURRENT_CP_NQN_BASE` 配置（默认 `nqn.2026-07.com.kurrent`，与 agent/storager 的 `KURRENT_NQN_BASE` 同源，变更须两侧同步）；WebUI Worker 详情 boot-vars 预览补 hostnqn 行；api/ 两份 API 文档字段表 + iPXE/JSON 示例同步（示例域 .controller → .kurrent）；全量 189 测试通过（.venv-linux，Python 3.14，含 hostnqn 断言）
- **iscsi_sep 条件化（仅 stgt / lio 后端下发）**——`_worker_boot_payload` 仅 `backend in {"stgt", "lio"}` 时下发 `iscsi_sep`（nvmet 无 iSCSI target 不下发）；`_backend_for` 支持 nvmet（tags / capabilities 优先序 nvmet → lio → stgt）；`menu.ipxe` 5 个 iSCSI 安装器项加 `isset ${iscsi-sep} || goto start` 守卫（nvmet 后端跳过安装器项）；api/ 文档字段表同步
- **nvmet-host 容器化部署形态调整（联调部署）**——`network_mode: host`（nvmet 监听 socket 由写 configfs 的进程创建、绑定其网络命名空间；host 模式即宿主 netns，客户端可直达 4420，容器重建不丢监听；原 `127.0.0.1:4841` 端口映射与 compose 内部网络访问方式作废，Agent 改经 `host.docker.internal:host-gateway` + `http://127.0.0.1:4841` 访问）；`security_opt: apparmor:unconfined`（Ubuntu docker-default AppArmor profile 拒 configfs 写入）；新增 `NVMET_HOST_DISK_DIR`（configfs device_path 由写入进程所在挂载命名空间解析，按 basename 重拼到容器可见目录，不配置则原样写入）；compose 磁盘挂载与 agent 的 `KURRENT_DISK_DIR` 内容一致、路径可不同
- **构建源阿里云化（国内网络加速）**——control_plane / storager-agent 两个 Dockerfile 的 apt 源改阿里云镜像（deb822 `debian.sources` 与老式 `sources.list` 双格式 sed 覆盖，只替换域名）；nvmet-host Dockerfile 的 pip 走阿里云 PyPI 镜像（与其余服务一致）

## 2026-08-23

### 变更

- **API 文档独立于文档站（docs/ 冻结待重写）**——控制面 API 参考移出 docs/ 站体系：新建根目录 `api/`（`api/control-plane-api.zh-CN.md` / `api/control-plane-api.en.md`，内容自包含无站内链接），此后接口变更仅维护该两份；docs/ 目录整体冻结不再修改（vitepress 文档站为 iPXE-All-Ready 时代产物，架构升级后整体重写，docs/ 内旧副本保留待重写时处理）；CHANGELOG 记录规范中 API 文档权威位置引用同步更新
- **固件仓库更名 Kurrent Firmware（dutyc/kurrent-firmware）+ ABOUT 标语定稿**——配套固件仓库 `ipxe-stateless` 更名 `kurrent-firmware`，ABOUT 标语定为 *The firmware engine for Kurrent. Make bare metal flow at the boot layer.*；主仓库引用全量同步（中英 8 文件）：README 两版「固件仓库」小节（新名称/链接 + 标语引言）、《项目环境部署》1.3 节与固件升级警告（名称 + 仓库/Releases 链接）、《引导介质制作指南》本地加载引用、about ARCHITECTURE 协议演进章节固件分支引用；CHANGELOG 历史条目与蓝图契约文件名（ipxe-stateless-handoff）保留原名（历史记录，GitHub 仓库改名后旧链接 301 重定向）
- **C3 引导链拼接实施（NVMe-oF 数据面激活）**——`/boot-vars` 退役单值 `nqn` 投影，改投 `base_nqn`（盘 NQN 前缀；盘 NQN 由 Agent 按统一模板 `base:worker_id.os` 生成，无存量盘下固件重拼 = 盘记录权威值；盘记录缺 nqn 不下发）；`iscsi_server` → `storager_ip` 全面更名（boot-vars 键 / iPXE 变量 `storager-ip` / `agents.yml` 配置键 / Agent API 字段 / WebUI 表单与 boot-vars 预览 / 中英 API 文档字段表）；`menu.ipxe` 主引导 5 OS 项（windows/ubuntu/debian/centos/esxi）改 NVMe-oF 拼装 `nvme://${storager-ip}:4420/${base-nqn}:${hostname}.<os>` + `nbft-secret` isset 条件化附加 `?secret=`，安装器 5 项保持 iSCSI（引用同步改名）；`boot.ipxe.cfg` 静态默认变量与 vars-done 注释同步；测试 153 通过
- **修复：nvmet-host DH-HMAC-CHAP 认证三缺陷**——`hosts/<hostnqn>/dhchap_key` 非内核属性名（真实为 `nvme-auth-dhchap-secret`，真 configfs 上 open 即 FileNotFoundError，从未生效）改为正确属性写 DHHC-1 明文（无换行）；新增 `nvme-auth-dhchap-control=1` 置位（不置位认证不启用，密钥形同虚设）；删除 `allowed_hosts` 手动 symlink（内核在 allow_any_host=1 时自动维护的连接记录，严格模式准入靠 hosts 登记）；同步 delete_host/delete_subsystem、Agent docstring、nvmet-host README 认证模型章节、测试断言（14 用例通过）
- **Kurrent 全量品牌化（GitHub 仓库改名 dutyc/kurrent 后同步）**——环境变量前缀全量 `IPXE_*` → `KURRENT_*`（控制面 `KURRENT_CP_*`、存储节点 `KURRENT_BACKEND`/`KURRENT_NQN_BASE`/`KURRENT_AGENT_TOKEN`/`KURRENT_DISK_DIR`/`KURRENT_LOG_FILE`/`KURRENT_NVMET_*`/`KURRENT_ISCSI_CONTAINER`、HTTPS 入口端口 `KURRENT_HTTPS_PORT`；`.env.example`、compose 插值、webui 构建注释、tests conftest 同步）；容器名 `ipxe-*` → `kurrent-*`（根编排 dnsmasq/control-plane/webui 三服务，存储节点 `kurrent-nvmet-host`，自签证书 CN `kurrent-controller`）；NQN 命名空间统一 `nqn.2026-07.com.kurrent`（盘 NQN base 示例由 `.controller` 域更新；Host NQN 落地 C3 点 1 裁定：按 worker_id 派生 `nqn.2026-07.com.kurrent:host.<worker_id>`，废弃设备 UUID 派生与 `:ipxe` 共享回退，解绑后 host_nqns 恒定不变）；about/ 宣言与 AI 政策、CHANGELOG 抬头、README Star History URL 收尾；测试保留 `nqn.2026-07.com.test` 隔离域（产品示例与测试域分离）；vitepress 文档站为 iPXE-All-Ready 时代产物暂不动（架构升级后整体重写）；全量 189 测试通过

## 2026-08-22

### 变更

- **README 项目更名 Kurrent（周流）**——英文名 Kurrent（取自 current，C 换成 K8s 生态的 K），中文名周流（取自《周易》“周流六虚，上下无常”）；开头重写为品牌形态：`Make bare metal flow.` + 与 K8s 对标（K8s orchestrates the containers. Kurrent orchestrates the compute.），定位由“云原生无状态计算平台”升格为“云原生无状态裸金属交付范式”（中英同步，核心特性标题改“算力周流，即插即用”）；badges 与快速上手仓库 URL 同步为 `github.com/dutyc/kurrent`（准备 GitHub 仓库改名）；固件仓库段品牌化；其余文件（docs 站、CHANGELOG 抬头、NQN 命名空间）留待后续批量更名
- **challenge 响应契约定稿：#!ipxe 脚本体（设备信任根链 R7 对齐）**——`GET /devices/challenge` 响应由 text/plain 单行 `nonce=<64hex>` 改为 `#!ipxe\nset nonce <64hex>\n`：iPXE chain 直接消费为 `${nonce}`，原单行格式无法被 iPXE 作为脚本执行（固件侧 usage 文档假设 #!ipxe，联调前裁定修改控制面）；boot.py 响应体修改，测试同步更新（test_trust_chain / test_device_registry 按 `#!ipxe` 首行 + `set nonce ` 解析），123 用例复跑通过
- **API 参考补录 challenge 端点（中英同步）**——control-plane-api.md 端点表新增 `GET /devices/challenge` 行、新增 5.2 节（query 参数 mac、成功 #!ipxe 响应示例、400 非法 MAC / 404 未注册未认领、三步挑战-响应链路）、boot-vars Query 参数表补 nonce/sig 行（强制开启后缺失 → missing_sig 拒绝）；/boot-vars iPXE 接入方式示例同步为信任根链形态（HTTPS + nonce/sig 签名路径 + challenge 失败降级路径）
- **固件侧 R1-R5 交付对齐（ipxe-stateless 仓库）**——固件实施完成（补丁 0008/0009/0010：HTTPS + keygen/pubkey/sign 命令 + EFI 变量 NVS 后端 + TOFU 自动固化，QEMU 实测）；thirdparty/docs/device-trust-usage.md 按主仓库实际契约修订（/devices/report 空响应语义、/devices/challenge、/boot-vars 带 nonce+sig、阶段 4 注释残留修复）；handoff / trust-root-blueprint 状态行与 nonce 契约定稿同步
- **T5 引导链集成（主仓库侧，QEMU 联调后置）**——nginx 新增 443 ssl server（TLS1.2、TOFU 单锚统一证书、`/devices/*` + `/boot-vars` 反代控制面、/file/ 资产与 /tftp/ 菜单同源）；证书由**控制面启动时自动生成**（cert_bootstrap 幂等：RSA-2048 自签叶证书 CA=False、SAN 可配 `IPXE_CP_CERT_SAN`（默认 IP:127.0.0.1,DNS:localhost）、指纹输出 state/certs/fingerprint.txt（DER SHA-256 hex，与 openssl x509 -outform DER | sha256sum 同格式），新增 4 单测；nginx Dockerfile 等待证书就绪后启动，compose 挂载 state/certs 只读；gen-cert.sh 与 webui/deploy/nginx/certs 挂载废止）；docker-compose nginx 服务加 `443:443` + certs/tftp 卷；tftp/boot.ipxe.cfg 信任根链集成（keygen → pubkey → report → challenge → sign → boot-vars，challenge 失败降级不带 nonce/sig，menu/chain-url HTTPS 化）；environment-deploy（中英）新增 1.4.2「HTTPS 引导链（T5，必需）」：证书自动生成与指纹获取、固件 0008/0009/0010 前置条件、旧固件断链警告、过渡期验签强制开关语义、证书轮换说明
- **HTTPS 引导入口端口可配置化**——nginx 宿主端口映射改 `${IPXE_HTTPS_PORT:-443}:443`（容器内固定 443，nginx.conf 零改动）；boot.ipxe.cfg 新增 `set https-port`（默认 443）拼入 https-url；environment-deploy 1.4.2 说明两处同步要求（compose 变量 + 脚本变量）
- **NVMe-oF 认证凭据库 + 凭据 API（C1，按 Worker 跟盘裁定）**——新增 `CredentialStore`（`state/credentials.yml`，复用 `_load_yaml`/`_atomic_write_text` 原子写 + 线程锁，键 = worker_id；`IPXE_CP_CREDENTIALS_FILE` env）；workers 域 3 端点（API Token 鉴权）：`PUT /workers/{worker_id}/credential`（DHHC-1 自检：前缀 `DHHC-1:`、类型两位数字、base64 解码长度 36/68、zlib.crc32 小端终值校验，失败 422；worker 不存在 404；同值幂等 `updated_at` 不变）、`DELETE /workers/{worker_id}/credential`（吊销，不存在 404）、`GET /workers/{worker_id}/credential`（元数据 `exists`/`secret_hash` 前缀/`updated_at`，不返回明文）；审计 `credential.set`/`credential.revoke`/`credential.get` 不记密钥本体
- **/boot-vars 注入 nbft-secret（C2）**——`_worker_boot_payload` 追加 `nbft_secret`：绑定 Worker 在密钥库有条目时注入（按 Worker 跟盘：注入值 = 该 worker 密钥，无条目 → 不注入回落明文）；`_boot_vars_ipxe`/`_boot_vars_json` 渲染 `set nbft-secret <key>`；审计 `boot_vars.credential`（injected 布尔，不记密钥本体）；固件侧消费 `sanboot nvme://...?secret=${nbft-secret}`（C3 引导链分支后置，本轮只投影变量）
- **nvmet 管理服务容器化（部署形态调整，不再手动跑 Python）**——`ipxe-nvmet-host` 以容器运行（与 Agent 同一 compose 托管，删除 systemd unit 与宿主 venv 部署路径）：内核 nvmet target 与 configfs 仍宿主（modprobe + mount configfs 为唯一宿主步骤，无法容器化）；容器无 privileged（configfs bind mount 后容器内 root 直写，与 LIO 的 targetclid/dbus 特权依赖无关）；端口映射仅绑宿主 loopback `127.0.0.1:4841`（可本机 curl 验证），局域网不可达，Agent 经 compose 内部网络 `http://nvmet-host:4841` 访问；`.env` 的 `IPXE_NVMET_HOST_TOKEN` 经 compose 插值注入容器 `NVMET_HOST_TOKEN`（不再需要 `/etc/ipxe/nvmet-host.env`）；新增 nvmet-host Dockerfile，compose 新增 `nvmet-host` 服务块，部署文档（中英）2.2/2.2.1/2.3 与 nvmet-host README、.env.example 同步更新
- **存储节点目录重组：iscsi-server → storager/（iSCSI 与 NVMe-oF 后端独立编排）**——`iscsi-server/` 整体更名 `storager/`，后端按协议分目录：`storager/iscsi/`（stgt/lio）与 `storager/nvmeof/`（nvmet-host）各自目录持有**完整独立编排**（`docker-compose.yml` 内嵌共享 Agent 服务块，仅代码共享 `storager/agent/`，无跨文件引用）；部署命令统一为 `cd storager/iscsi|nvmeof && docker compose --env-file ../.env up -d`（.env 单一来源，插值经 --env-file 读取）；同一节点同一时刻仅启用一个后端 compose（`storager-agent` 容器名固定，互斥语义不变）；`.gitignore`、tests conftest 路径、部署文档（中英）结构图/2.1/2.2/2.2.1/2.3/2.5、nvmet-host README、`.env.example` 同步更新，全量 189 测试通过
- **存储节点服务命名统一 storager- 前缀**——存储节点服务不再用 ipxe- 前缀：`ipxe-agent` → `storager-agent`、`ipxe-iscsi` → `storager-iscsi`（两个 compose 的 service/image/container_name 同步；`IPXE_ISCSI_CONTAINER` 配置默认值改为 `storager-iscsi`——Agent 经 docker.sock 按该变量调度容器，无硬编码容器名）；日志路径 `/var/log/ipxe-agent` 与 `IPXE_*` 环境变量名不变（不属于服务名）；部署文档（中英）2.1/2.2/2.3 与探索文档容器示例同步；全量 189 测试通过
- **NVMe-oF 宿主 nvmet 服务 + Agent 推送驱动（C4）**——新组件 `iscsi-server/nvmet-host/`（FastAPI + Bearer token，绑定 localhost:4841，root 运行）：configfs 直写 `/sys/kernel/config/nvmet`（subsystem/namespace/port/hosts+dhchap_key，严格模式 `attr_allow_any_host=0`，allowed_hosts 相对 symlink），端点 `/healthz`/`/capabilities`/`/subsystems` CRUD + hosts 同步 + `/port`；systemd unit 样例 + README（modprobe nvmet nvmet-tcp、configfs 挂载、token env）；Agent 新增 `NvmetBackend`（不继承 Backend 基类——基类初始化 docker 客户端，nvmet 无 docker 依赖；iqn 字符串直接作子系统 NQN）与 `NvmetHostClient`（urllib 零依赖）+ `NvmetCredentialCache`（**缓存先行** 0600 落盘 + 60s 周期 reconcile 幂等重放 + 子系统 404 丢弃过期条目）；`POST /credential` 端点（非 nvmet 后端 400、宿主不可达 503）；控制面 `_push_credentials` 推送驱动（凭据设置/吊销、设备绑定/解绑/换绑、建盘/删盘含批量、删 Worker 共 8 触发点，失败仅审计不阻断）；Host NQN 派生 `nqn.2014-08.org.ipxe:<uuid>`（无 UUID 回退共享 `nqn.2014-08.org.ipxe:ipxe`）；env：`IPXE_NVMET_HOST_URL`/`IPXE_NVMET_HOST_TOKEN`/`IPXE_NVMET_CACHE_FILE`；单测 36 例（宿主服务 13 + Agent 23，Windows symlink/路径冒号兼容层）+ 控制面推送链路 7 例，全量 189 通过；真实挂载验证留部署环境（本机 Windows 无内核 nvmet）
- **NQN 标识体系修正（盘记录双标识，C4 缺陷纠正）**——子系统 NQN 不可用 IQN 替代（NVMe Base Spec §7.9：NQN 必须 `nqn.` 前缀，发起端拒绝 `iqn.` 前缀）：控制面新增 `iqn_to_nqn`（同后缀前缀变换），建盘/批量建盘盘记录新增 `nqn` 字段（存量盘读取时由 `iqn` 派生兼容）；`_push_credentials` 推送 `sub_nqns` 改用 NQN；Agent `NvmetBackend` 经 `to_nqn` 变换后写 configfs（create/delete/list/scan 全链路），`list_targets` 新增 `nqn` 键（`iqn` 键保留历史契约，值同为 NQN），`capabilities` 本地补 `base_iqn`（宿主服务未知 `IPXE_IQN_BASE`——此前 nvmet 建盘会 KeyError）；`_target_actual` 标识集合对比兼容双数据面；测试断言全量改 NQN，全量 189 通过
- **存储节点变量文件按 NVMe-oF 首选原则翻转（.env.example + 部署文档 2.3）**——`IPXE_BACKEND` 默认值 `lio` → `nvmet`（nvmet = NVMe-oF 首选/默认，stgt/lio = iSCSI 降级选项）；`IPXE_ISCSI_CONTAINER` 移至「iSCSI 降级段」并标注仅 stgt/lio 后端需要（nvmet 后端经 HTTP 驱动，不读该变量）；`IPXE_IQN_BASE` 注释改为双数据面语义（iSCSI 直接用为 IQN 前缀，NVMe-oF 派生 NQN `nqn.` + iqn[4:]）；NVMe-oF 专属变量（`IPXE_NVMET_HOST_URL`/`IPXE_NVMET_HOST_TOKEN`/`IPXE_NVMET_CACHE_FILE`）提前为后端专属第一段；部署文档（中英）2.3 `.env` 示例块同步翻转；Agent 代码零改动（`IPXE_BACKEND` 必填无默认，默认值仅体现在模板）
- **NQN 权威标识体系（盘标识方向反转：NQN 唯一配置入口，IQN 自动派生）**——`IPXE_IQN_BASE` 废止，节点只配置 `IPXE_NQN_BASE=nqn.2026-07.com.controller`（NQN 权威命名空间）；IQN 一律由 NQN 自动生成（`nqn_to_iqn` = `iqn.` + nqn[4:]，幂等），NQN 绝不由 IQN 定义；控制面新增 `build_nqn`（base_nqn + worker_id + os 生成盘 NQN）与 `nqn_to_iqn`，建盘/批量建盘盘记录 nqn 权威在前、iqn 派生（存量盘记录 `iqn_to_nqn` 回退保留，不违反方向原则）；capabilities 契约 `base_iqn` → `base_nqn`（scheduler 校验、agents 台账、建盘消费同步）；Agent 改读 `IPXE_NQN_BASE` 并内部派生 `IQN_BASE` 供 iSCSI 后端（stgt/lio），`NvmetBackend` 构造参数改 nqn_base（内部派生 iqn_base 供 scan 候选）；CD 盘经 `nqn_to_iqn(cd_caps["base_nqn"])` 派生；boot-vars `base-iqn` 变量保持 IQN 形态（iSCSI 引导消费，来源 = 盘 NQN 派生）；`.env.example`、部署/API 文档（中英 9 份）、WebUI（Agents 页展示与探测改 base_nqn、WorkerDetail 盘记录补 nqn 权威行）同步；全量 189 测试通过
- **boot-vars 下发盘 NQN（权威标识到消费端）+ 存量回退取消（架构基线 = research/nvme-of 分支，面向未来）**——`/boot-vars` 新增 `nqn` 字段：默认启动盘的盘 NQN（权威字段），iPXE 渲染 `set nqn <...>` / JSON 同键，固件侧 `sanboot nvme://<ip>:<port>/${nqn}` 拼装消费（C3 引导链分支后置，当前只投影变量）；与 `base-iqn` 同选盘规则（默认启动盘）、同条件（无系统盘不返回）；盘记录缺 `nqn`（存量盘）**不返回该键、不派生**——架构设计基于 research/nvme-of 分支、完全面向未来，不兼容 iSCSI 设施与遗留环境：`iqn_to_nqn` 函数删除（utils.py），`_push_credentials` 跳过缺 nqn 的盘（不推凭据），nvmet.py `to_nqn` docstring 去除引用；文档（中英）字段来源表 + iPXE/JSON 示例同步；全量 189 测试通过

---

## 2026-08-21

### 变更

- **ARCHITECTURE.md 协议演进章节细化（NVMe-oF 验证落地，中英同步）**——基于 ipxe-stateless research/nvme-of 分支验证结果：固件层 nvmetcp 驱动原生执行 `sanboot nvme://`、DH-HMAC-CHAP 认证（控制面按次启动注入 `nbft-secret`，不进固件镜像、不进引导菜单）、NBFT 接力链路 QEMU 端到端闭环；明确双数据面并存（iSCSI 生产路径 + Windows 回退通道，NVMe-oF 迁移方向）与认证/加密两条独立主线（TLS 为认证后开放主线）；蓝图侧同步更新（blueprint/ 不入库）：security-blueprint C6/已定决策 2 过时假设修正、ipxe-nvmeof-stack-blueprint 里程碑状态标注（M1/M2 已验证）、新增 nvmeof-credential-design.md 认证凭据落实设计（/boot-vars 注入契约、密钥库、3 个凭据 API 端点设计；密钥管理模型列为待定决策，暂不讨论）
- **信任根架构裁定：固件内置 CA 作废，信任根归位设备 NVRAM 密钥（蓝图专项）**——裁定「固件里不放 CA 证书，固件是所有的局域网设备都可以获取的，固件里面放 CA 无意义」：security-blueprint 已定决策 3 修订（信任根 = 设备 NVRAM ECDSA P-256 私钥，固件侧生成、私钥不出设备、控制面只存公钥）、§6 三层身份 CA 层取消、§8 注册窗口改固件生成+公钥上报、待定决策 1（CA 归属）消解（TOFU 模式下自签证书即可）；新建 blueprint/trust-root-blueprint.md（双向信任模型：设备侧 TOFU 服务器证书指纹固化 NVRAM + 控制面侧挑战-响应设备签名；自研 EFI 变量 NVS 后端复用上游 NVO 层；UEFI-only、BIOS 遗留回退；T1-T5 实施分期）；nvmeof-credential-design 注入条件扩为四条（新增设备身份签名验证）；thirdparty/ipxe 上游源码克隆查证（NVO 抽象层 / SetVariable 先例 / ecdsa_sign / EFI RNG 熵源）
- **抛弃传统 BIOS 引导：UEFI-only 升级为全系统基线（蓝图专项联动）**——裁定「抛弃 BIOS-only 设备」（存量可忽略，X3650 M4 级 2012 硬件已带 UEFI）：trust-root-blueprint 待定决策 2（BIOS 平台信任根）消解、§2.3/§3.4 BIOS 载体表述修订；ipxe-nvmeof-stack-blueprint 待定决策 2（BIOS 构型）消解、平台基线/引导链流程图/D3/D5/M7/风险表同步修订；security-blueprint 头部裁定声明追加；iSCSI 回退通道保留、载体收窄为 UEFI（照走 TOFU / 设备签名保护）；固件仓库 BIOS 构建目标（grub-bios / undionly / usb）**暂时保留不砍**（后续裁定：仅架构设计不考虑 BIOS）
- **信任根蓝图待定决策收敛：证书轮换 = 重新进注册窗口，设备密钥算法 = ECDSA P-256（蓝图专项）**——裁定：trust-root-blueprint 待定决策 1（设备密钥算法）消解为 ECDSA P-256（上游 ecdsa_sign 已有、32B 私钥 NVRAM 占用最小、密码学零新写、nonce 重用风险由 EFI RNG 熵源覆盖）；待定决策 3（证书轮换）消解为重新进注册窗口（双指纹过渡被否——需设计受旧指纹保护的新指纹下发通道）；§4.3 证书轮换节更新；security-blueprint 待定决策 1 的证书轮换引用同步更新；至此信任根蓝图待裁定的决策项全部收敛（剩余为实施期/对齐项：EFI 变量 GUID、私钥轮换与吊销、密钥生成侧）
+- **信任根蓝图源码复核修正 + 明文引导面决议（蓝图专项）**——基于 thirdparty/ipxe 上游源码逐行核对修正三处表述：默认构建内置 iPXE root CA（rootcert.c，非「无内置 CA」，附带 ALLOW_TRUST_OVERRIDE=1）、`${trust}` setting 生效路径（rootcert_init 启动早期一次性从 NVRAM settings 源读入，脚本层 `set trust` 无效，DHCP 来源无效）、上游无 TOFU 原语（TLS 验证失败即断链、证书不进 certstore，「首次握手固化指纹」需固件补丁扩展点，R2 交付物改新补丁）；裁定 boot.ipxe.cfg 获取保持明文（HTTP/TFTP）——明文引导面 = boot.ipxe + boot.ipxe.cfg 两个收敛指针脚本（内容收敛红线 + 静态降级参数非敏感化，被篡改可利用价值由 TOFU 兜底降级为引导 DoS），其后全链 HTTPS + TOFU，TOFU 固化时点后移到首个 HTTPS 请求；trust-root-blueprint T5/R1/R2/§3.2/§4.1/§4.2/§10.3 同步修订，nvme-of-bootchain-blueprint 架构图/引导协议/TRUST 构建参数、nvmeof-credential-design 引导态传输表述联动修订
+- **信任根注册模型三裁定（蓝图专项）**——① TOFU 首信 = 固件补丁（自动 TOFU：TLS 验证失败路径扩展点，窗口期首启接受握手 + 取指纹写 NVRAM；部署期预置指纹方案否，与无接触部署节奏冲突）；② 注册只在窗口期：注册窗口取代 auto_register 永久开关（settings.json 持久开关语义废止，无窗口外注册通道，代码层不可配永久）；③ 存量设备密钥认领：已部署设备无豁免，窗口期内开机走一遍密钥认领（固件生成密钥对 + 公钥上报 + key_hash 填充），认领后全部受验签保护；trust-root-blueprint 头部/§4.1/§5/§5.2/T3、security-blueprint 头部/§8、control-plane-update-plan 差异表/P4 行联动修订
- **存量未认领设备引导拒绝 + 补救路径（注册模型裁定④，蓝图专项）**——窗口关闭后无 key_hash 设备直接拒绝引导（注入四条件第 4 条硬性不过，已绑定也不放行）；补救路径 = 删除设备池登记 → 重开注册窗口重新注册 → 恢复 worker 绑定；trust-root-blueprint 头部/§5/§6.1/T4、security-blueprint 头部/§8、control-plane-update-plan P4 行联动修订
- **信任根控制面实施（T3/T4）：注册窗口 + 设备身份验签全链路落地**——main.py 按域拆分（2341 行 → 18 行组装入口 + routers/ 六域包，boot 域最先挂载保证 `/devices/report`、`/devices/challenge` 先于 `/devices/{mac}` 匹配）；`auto_register` 永久开关废止：新增 `GET/POST/DELETE /settings/registration-window`（TTL 1-60 分钟硬上限，到期懒计算自动关闭，已开启 409）与 `GET/PUT /settings/enforcement`（验签强制开关，持久化 settings.json）；`GET /devices/report` 扩展 `pubkey` 参数（ECDSA P-256 公钥，130 hex 未压缩点，注册/认领用，密钥不一致拒绝覆盖仅审计）；新增 `GET /devices/challenge`（一次性 nonce 64 hex、短 TTL、未注册/未认领 404）；`/boot-vars` 注入四条件第 4 条：无 key_hash（强制开 → `no_key`）、缺 nonce/sig（强制开 → `missing_sig`）、缺 hostname、nonce 重放、验签失败一律拒绝并审计 `boot_vars.credential`；过渡期无密钥设备照现状放行（伪造签名不放行）
- **控制面全链路单元测试（T9）**——tests/ 扩展至 123 用例（5.08s）：EC 密钥对夹具 + 签名 helper + 注册/认领高层夹具；覆盖设备登记/挑战（15）、验签链路与强制开关（15）、设备池 CRUD/绑定/批量（17）、worker 全生命周期（23）、agent 注册/探测/母盘（16）、审计分页（8）；测试即契约固化产品行为（iscsi_server 回退时机、base-iqn 前缀语义、审计 id 进程内自增、MAC 冒号格式、AgentClient 属性结构）
- **WebUI 注册窗口面板（T8）**——Devices 页旧「自动注册」开关替换为「注册窗口」面板：状态徽章 + TTL 选择（5/15/30/60 分钟）开启 + 倒计时（本地逐秒递减，归零回源刷新）+ 提前关闭 + 「设备身份验签强制」开关；API 文档（control-plane-api.md 中英）5.1 节与 16.6 节、快速部署三文档（environment-deploy 1.4.1 / webui-guide / windows-quick-deploy）同步为注册窗口模型

---

## 2026-08-16

### 变更

- **文档站：新增《WebUI 使用指南》（中英同步）**——新增 `docs/guide/quick-deploy/webui-guide.md` 与 `docs/zh/guide/quick-deploy/webui-guide.md`：页面分区功能说明（Dashboard / Workers / Devices 设备池 / Worker 详情 / Agents / Operations）+「设备入池 → 绑定向导（默认顺序分配）→ 克隆建盘 → 默认启动 → 验证」核心流程 + 常见问题（Token 401、设备不入池、向导左栏无设备、母盘下拉缺失、停在 iPXE 菜单）；《项目环境部署》1.6 / 2.6 验证节与底部流程入口同步链接；侧边栏导航（zh/en）同步
- **快速部署文档修正 P1 反转前的过期流程（中英同步）**——《项目环境部署》1.4.1：自动注册语义由「新 MAC 自动注册为 Worker」改为「自动入设备池」，开关位置由 Workers 页工具栏改为 Devices（设备池）页工具栏，关闭后的手动处理由「添加 Worker」改为「注册设备 / 导入清单 / POST /devices 入池后绑定向导」；《Windows 无盘快速部署》《Debian 系无盘快速部署》第 3 步由「自动注册 Worker + Workers 页查看」改为「自动入池 + Devices 页确认 + 绑定向导绑定」，「批量上线」与「找不到 iSCSI 目标」排查表述同步对齐
- **《项目环境部署》2.4 登记 Agent 补充 WebUI 方式（中英同步）**——由仅「编辑 `agents.yml`」改为两种方式任选：方式一 WebUI（推荐，Agents 页「+ 添加 Agent」两步探测注册：填 Agent ID / API 地址 / Token → 探测自动获取后端/角色/标签/数据面地址 → 确认 iSCSI 数据面为 Worker 可达地址 → 添加，写入 `agents.yml` 立即参与调度）；方式二直接编辑 `agents.yml`（原内容保留）；多节点部署说明同步；《WebUI 使用指南》Agents 页描述同步补全
- **WebUI：Dashboard 新增设备数量统计卡**——统计卡由 Workers / Agents 两卡扩展为 Workers / 设备池 / Agents 三卡，设备数为 `GET /devices`（含全部状态）计数，与 Workers/Agents 同源并行拉取；中英文案同步
- **WebUI：设备池「导入清单」更名为「登记设备入池」并加悬停提示**——与「绑定向导 → 清单配对」的混淆点消除：按钮文案改为「登记设备入池」（en: Register to Pool），鼠标悬停提示「不涉及绑定」（No binding involved，原生 title 提示）；页面介绍弹层中相关描述同步（自动注册开关说明、操作按钮说明）；《WebUI 使用指南》工具栏描述同步
- **WebUI：Workers / Agents 页新增「页面介绍」按钮**——与 Devices 页同款弹层：Workers 页工具栏右侧（顶部操作按钮 / 筛选 / 列表列 / 行交互四区块，含批量创建、批量建盘分配方式、就绪度语义）；Agents 页工具栏右侧（工具栏两步探测注册与在线探测开关 / Agent 卡片字段 / 行交互三区块）；中英文案同步，《WebUI 使用指南》对应页面描述同步
- **README 两版修正 P1 反转前的过期描述（简介 + 核心特性）**——「自动注册」→「自动入设备池」：简介改为「上报指纹自动进入设备池，WebUI 绑定 Worker、克隆系统盘、设定默认系统后即自动进入目标系统」（en 对应 "reports its fingerprint and joins the device pool automatically, then a few clicks in the Web UI bind it to a Worker, clone a system disk and set the default OS"）；核心特性改为「新机器首启自动入设备池，WebUI 点几下即可绑定 Worker、分配系统盘与默认系统」（en 对应 "report their fingerprints and join the device pool on first boot; a few clicks in the Web UI bind them to a Worker..."），与 2026-08-16 首页 Zero-Touch 表述及 P1 语义对齐
- **架构图全英文化 + ARCHITECTURE.md 拓展（中英同步）**——`assets/architecture.svg` 重制为全英文版并作为唯一图源（删除 `architecture-en.svg`，两版文档引用同步）；README 两版架构小节引用同步；`about/en/ARCHITECTURE.md` 与 `about/zh/ARCHITECTURE.md` 由三角色简介拓展为完整架构讲解：控制面/数据面分离（控制面故障不中断数据面 I/O）、三角色（Controller 容器化组件与纯文件态存储、Storager Agent 封装后端差异、Devices 指纹入池无状态计算）、三实体模型（设备/Worker/系统盘表格 + 绑定权威在设备侧与盘机分离 + 生命周期 pooled→bound→revoked 与原子换绑 + 多盘多系统在线切换）、引导链路五步（入池 → boot-vars 绑定校验 → iSCSI 登录）、状态存储文件即真相（devices.yml / workers.yml / settings.json / operations.jsonl / agents.yml）、安全边界（绑定即认证、key_hash 预留双向认证位）、协议演进（数据面可换 NVMe-oF，语义不变）

---

## 2026-08-15

### 新增

- **Control Plane：设备↔Worker 一对一绑定（P2 绑定语义）**——绑定关系权威在设备侧（`bound_worker_id`），worker 侧只投影；新增 `POST /devices/{mac}/bind`（默认 409，`force=true` 原子换绑：预校验 → 新绑定落盘 → 旧绑定清除（旧设备回池）→ 失败回滚台账快照 + 尽力恢复 dnsmasq，幂等）、`DELETE /devices/{mac}/bind`（解绑回池，盘留 worker）、`POST /devices/bind/batch/preview`（只读配对表：matched/conflicts/not_found + summary，manifest 清单配对 / sequential 顺序配对，可选申报列指纹比对 `fingerprint_mismatch`）、`POST /devices/bind/batch`（幂等执行：succeeded/skipped/failed 逐项独立，已绑定重跑全 skipped）；审计 `device.bind`（含 old_worker_id/old_device_mac 换绑历史）、`device.unbind`、`device.bind.batch`
- **Control Plane：Worker 就绪度派生字段**——Worker 列表/详情/状态响应新增 `bound_device`（绑定设备 MAC）与 `readiness`（绑定+有盘 → `ready`；绑定或有盘 → `partial`；皆无 → `idle`），由 `_enrich_worker` 统一投影
- **Control Plane：boot-vars 防冒领（D2，绑定即认证）**——带 `mac` 的 `/boot-vars` 请求须来自 hostname 命中 worker 的绑定设备，不符（绑定其他 worker / 未绑定 / 未知设备）→ 拒绝下发空脚本；不带 mac（仅 hostname）兼容放行
- **Control Plane：批量创建 Worker（P3）**——新增 `POST /workers/batch`：`count`（1–100）+ `name_prefix` 命名规则生成 `worker_id`（`worker-01`…，位宽随 count 自适应），逐项独立（单项失败不影响其余）、幂等（已存在 → `skipped` 不重复创建）；`macs` 可选（与 `count` 等长时逐项校验设备池并直接绑定，池外/已绑定 → 该项 `failed` 且不创建，修正后可重试）；不支持 `windows_iso`；审计 `create_worker.batch`（含 created/skipped/failed/prefix）
- **WebUI：设备池页 + 绑定向导（P3）**——新增 Devices 页（状态过滤/搜索 + 指纹详情 + 手动注册 + 清单导入 + 多选解绑二次确认）；新增「设备绑定」向导（manifest 清单 / sequential 顺序配对 → 预览配对表 → 导出 TSV 核对 → 二次确认执行 → 失败项保留清单重试）；Workers 页表单扩展数量 + 命名规则批量创建、列表新增绑定列（`bound_device` + readiness 三态 Badge）；路由 / 导航 / 中英文案同步

### 变更

- **`POST /workers` 的 `mac` 改为可选（P2）**——不传 = 纯空转 Worker（仅 hostname 绑定，readiness=idle）；传 = 校验设备在设备池中（pooled）并直接绑定（一对一授权），池外/已绑定 → 409（先注册后绑定，语义反转的预期影响面）；绑定失败时 worker 保留为空转
- **`PUT /workers/{worker_id}/mac` 映射为设备换绑（P2）**——新 MAC 须在设备池中（pooled）并绑定到本 worker，旧设备（若绑定本 worker）解绑回池；dnsmasq `replace_binding` 失败回滚台账；审计记 `device.bind` + `device.unbind` + 兼容 `worker.mac.update`；幂等返回 `changed=false`
- **`DELETE /workers/{worker_id}` 与 `POST /workers/delete/batch` 联动解绑（P2）**——先解绑设备落盘（回池不吊销，失败中止删除），再删 worker

- **Control Plane：设备台账（`DeviceStore` + `state/devices.yml`）**——三层实体模型（设备 / Worker / 系统盘）底层实体落地（P1）：绑定关系权威在设备侧（`bound_worker_id`），worker 侧只投影；设备状态 `pooled`（池中未绑定）/ `bound` / `revoked`；新增端点 `GET /devices`（state 过滤）、`GET /devices/{mac}`、`POST /devices`（手动注册入池）、`POST /devices/import`（批量导入，逐项独立，重复跳过、非法/吊销计 failed）、`DELETE /devices/{mac}`（注销吊销，bound 设备 409 须先解绑）；`key_hash` 字段预留安全蓝图阶段
- **Control Plane：`GET /devices/report`（不鉴权）**——iPXE 设备信息上报入口（11 字段：mac/uuid/厂商/型号/序列号/CPU/内存总量/内存类型/内存频率/网卡/总线 ID），宽松解析（空值容忍，`mem-total`/`mem-speed` 兼容 `0x` hex 与十进制、归一化十进制存储），更新指纹 + `last_seen`；未知 MAC 且 auto_register 开 → 入池；返回空响应（chain 无脚本副作用）；`tftp/boot.ipxe.cfg` 在请求 `/boot-vars` 之前先 chain 上报（失败静默跳过，不阻断引导）
- **Control Plane：旧数据迁移（启动时幂等）**——扫描 workers.yml + dhcp-hosts.conf，为存量 MAC 绑定生成 bound 设备实体（`source=manual`，指纹空，等待首次上报补充）；已存在跳过，失败仅记日志不阻断启动

- **自动注册语义反转（P1）**——新 MAC 不再自动创建 Worker + dnsmasq 绑定，只入设备池（`_auto_register_worker` 移除，入池收敛到 `/devices/report` 与 `/boot-vars` 兜底）；`/boot-vars` 变为只读投影（无写副作用）；识别链改为 hostname→worker、mac→设备台账→`bound_worker_id`→worker（迁移后存量绑定自动生效）；池中未绑定 → reboot 循环等待绑定；未知 MAC + auto_register 关 → 空脚本；审计操作码 `auto_register` → `device.register`
- **`IPXE_CP_AUTO_REGISTER` 开关语义**——由「新 MAC 是否自动注册为 Worker」变为「新 MAC 是否自动入设备池」，端点与持久化方式不变（运行时 API 优先于环境变量）
- **WebUI：自动注册开关迁移至设备池页**——Workers 页工具栏的全局自动注册开关移至 Devices 页工具栏（与「新 MAC 自动入设备池」语义同页对齐），Workers 页工具栏随之精简；开关 tooltip 文案同步修正为 P1 反转后的准确语义（原文案仍停留在「自动注册为 Worker」的旧描述）；中英文案同步
- **WebUI：设备池页新增「页面介绍」按钮**——Devices 页工具栏右侧新增介绍按钮，弹出遮罩面板逐项说明页面各功能区（自动注册开关 / 筛选与计数 / 操作按钮 / 列表列 / 行详情展开），中英双语
- **WebUI：绑定向导新增「图形化顺序分配」模式（替代原顺序配对文本模式）**——向导模式由「清单配对 / 顺序配对（文本粘贴）」改为「清单配对 / 图形化顺序分配」：左侧勾选池中未绑定设备（指纹摘要、搜索、全选），右侧勾选可用 Worker（按勾选顺序），按列表顺序一一对应自动分配；Worker 不足时按补建前缀自动调用 `POST /workers/batch` 补建差额，Worker 超出时截断；分配结果锁定后走预览 / 导出 / 二次确认 / 失败重试（graphical 重试沿用锁定分配、不重复补建）；向导数据源独立于页面状态过滤；后端零改动（复用 sequential 模式与 batch 端点）
- **WebUI：设备列表固定按入池时间排序**——设备池列表与绑定向导「图形化顺序分配」左栏统一按 `first_seen`（首次上报/入池时间）升序排列（无 `first_seen` 排最后），替代原 MAC 排序，作为绑定/沟通时指代设备的顺序基准（“从上往下第 N 台”）；纯前端展示层改动，后端零改动
- **Control Plane：`GET /operations` 支持 `mac` 过滤 + 批量绑定逐条审计**——新增可选 `mac` 参数（规范化后按设备过滤操作流水，用于设备绑定记录查看）；`POST /devices/bind/batch` 除汇总 `device.bind.batch` 外，每个 `succeeded` 项另逐条记录 `device.bind`（`mac`/`worker_id`），保证设备绑定历史完整，`skipped`/`failed` 仅汇总计数
- **WebUI：设备页绑定记录 + MAC 复制按钮**——设备行详情展开新增「绑定记录」区块（展开时按 mac 拉取审计，仅显示 bind/unbind 类事件，最新在前，换绑显示 `旧 worker → 新 worker`）；设备行 MAC 旁新增复制按钮（点击复制到剪贴板，1.5s 内 ✓ 反馈）
- **WebUI：绑定向导默认「顺序分配」**——向导默认模式由「清单配对」改为「顺序分配」（图形化双栏勾选分配），「图形化顺序分配」名称简化为「顺序分配」，「清单配对」保留为可选项（去除「默认」标注）；中英文案同步

### 修复

- **`/boot-vars` reboot 循环 payload 缺 `worker_id` 导致 500**——池中未绑定设备的新返回体（`menu_default`+`menu_timeout`）不含 `worker_id`，`_boot_vars_ipxe` 直接索引抛 KeyError（运行级验证暴露）；改为 `payload.get('worker_id', 'unbound')` 兜底，JSON 输出不受影响

---

## 2026-08-13

### 变更

- **《项目环境部署》1.3 节固件来源改为 ipxe-stateless（中英同步）**——不再从 iPXE 官方发布站 boot.ipxe.org 下载，改为从配套固件仓库 [iPXE-Stateless](https://github.com/dutyc/ipxe-stateless) 的 [Releases](https://github.com/dutyc/ipxe-stateless/releases) 页面下载最新 release；以正式语气说明不建议使用官方固件的动因（官方构建未包含高性能网卡原生驱动，RTL8125/RTL8126 仅能走 UNDI/SNP 兼容路径，引导可能失败）；以表格列明所需资产与放入 `tftp/` 后的文件名（`undionly.kpxe` + `pxe-uefi-snponly.efi` → `snponly.efi` + `pxe-uefi-ipxe.efi` → `ipxe.efi`，可选 `*-debug.efi` 调试版，去 `pxe-uefi-` 前缀匹配 dnsmasq 分发名）；`ipxe-legacy.efi` 随新产物移除；下载步骤精简为指引（不再提供逐条 wget / sha256sum / mv 命令）；UEFI 引导异常排查流程更新（先换 `ipxe.efi`，仍异常用调试版抓日志，替换前备份、定位后换回正式版）
- **README 两版「云原生固件仓库」小节精简**——参照 ipxe-stateless 仓库「项目定位」的概况风格，将 1 句引言 + 3 条要点列表压缩为一句全局概况，不含技术细节：与主仓库同一理念的一体两面（主仓库让算力无状态，固件仓库让引导固件无状态）
- **workers.yml 移出版本库，纳入 .gitignore**——`control_plane/state/workers.yml` 为控制面运行时台账（Worker 注册状态），提交会打乱部署环境；经 `git rm --cached` 从索引移除（工作区文件保留），并加入 .gitignore 运行时区块（注释同步改为「运行时状态、日志与租约」），与 `operations.jsonl` 同等对待
- **dhcp-hosts.conf 改为示例模板入库，主文件不再 push**——新增 `dnsmasq/dhcp-hosts.conf.example` 模板（含格式说明与示例绑定、复制命令），`dnsmasq/dhcp-hosts.conf`（MAC → hostname 运行时绑定）经 `git rm --cached` 移出版本库并纳入 .gitignore；部署者须先 `cp dhcp-hosts.conf.example dhcp-hosts.conf` 再填写真实绑定（docker-compose 以文件级 bind mount 挂载该文件，缺失时容器侧会生成目录导致 hostsfile 失效）
- **dnsmasq.conf 改为示例模板入库，主文件不再 push**——新增 `dnsmasq/dnsmasq.conf.example` 模板（环境相关项标注「[按实际修改]」：网卡名、DHCP 地址池、网关，引导链架构配置原样保留），`dnsmasq/dnsmasq.conf`（含真实网段）经 `git rm --cached` 移出版本库并纳入 .gitignore；环境部署文档 1.2 节同步补充首次部署先复制模板的步骤（文件级 bind mount 下缺失会生成目录导致配置不生效）
- **README 两版按 Kubernetes README 风格整体重构精简**——参照 kubernetes/kubernetes 经典 README 的「短段落 + 入口导航」风格：引言压缩为一段（去掉「PoC 演进史」段与「All/Ready」口号段）；Quick Start 压缩为最简命令（补充 `dnsmasq.conf` / `dhcp-hosts.conf` 模板复制步骤，去掉 WebUI token 构建与存储节点部署的可选步骤，外链部署手册）；Community & Contributing 的 AI 政策约 20 行压缩为一句核心要求 + 链接（完整政策保留在 AI_POLICY 文件）；Roadmap 去掉 Phase 状态段压缩为一句 + 链接；API 描述去重复化；License/Star History 保留；架构图引用与中英徽章行对齐
- **README 原 AI 辅助描述整合进 AI_POLICY（中英同步）**——逐条比对 README 删除的 AI 政策描述与 AI_POLICY 现有内容，确认立场声明、核心原则、PR #3 案例均已覆盖，仅缺 README 原第 5 条架构理解要点「iSCSI 会话保活机制在整个链路中的位置与影响」，已补入 AI_POLICY 两版第二章的问题清单（现共 5 条，与 README 原清单一一对应，无内容丢失）
- **Manifesto 标题改为「我们的云原生」，根目录文档分类整理入 about/（中英分目录）**——Manifesto 两版标题由「My/我的 Definition/云原生定义」改为「Our/我们的 Definition/云原生定义」（README 两版引用同步）；新建 `about/en/`（Manifesto、AI_POLICY、Barriers、ROADMAP）与 `about/zh/`（对应中文版）两个目录，经 `git mv` 分类存放，README/CHANGELOG/LICENSE 仍留根目录；README 引用路径全部更新，全仓库 git grep 确认无旧路径残留（文档站与根目录文档本就零引用，不受影响）
- **README「架构」部分独立为 ARCHITECTURE.md（中英双版）**——README 的 Architecture 小节（架构图 + 三角色说明）拆出为 `about/en/ARCHITECTURE.md` 与 `about/zh/ARCHITECTURE.md`（架构图引用路径修正为相对新目录 `../../assets/`），README 只保留一句 + 双语链接，进一步贴近 K8S 纯入口风格
- **about/zh/ 目录中文文档去除 _zh-CN 后缀（中英文件名统一）**——`about/zh/` 下 Manifesto / AI_POLICY / Barriers / ARCHITECTURE 四份中文文档文件名去掉 `_zh-CN` 后缀（目录已按语言区分，后缀冗余），README 两版与 CHANGELOG 当日条目中的引用路径同步更新，全仓库 grep 确认无 `_zh-CN.md` 引用残留
- **README「核心特性」小节列表段落化（中英同步）**——6 条 bullet 列表改为一段话（K8S 风格短段落）：零手工开通、一机多系统、秒级启动、文件即真相、API 优先五个要点并入 3 句连续叙述，保留全部信息量但不再用列表形式
- **README 两版引言定位修正（对齐宣言口径）**——重构时误将项目定位写回「云原生无盘计算平台 / cloud-native diskless computing platform」与「A diskless node」，与宣言「iPXE-All-Ready 从来不是一个简单的无盘项目」相悖（无盘只是表象，灵魂是无状态）；已改为「云原生无状态计算平台 / cloud-native stateless computing platform」与「A node」，措辞同步宣言「把无状态贯彻到算力层本身」（8-01 曾对齐过该口径，本次重构回退，已修正）
- **README 徽章行改为动态徽章为主（K8S 风格，中英两版同步）**——原先 7 枚静态技术栈徽章（iPXE / iSCSI / Control Plane / Agent / dnsmasq 等，颜色杂乱且含「iSCSI-Diskless Storage」与宣言相悖文案）删除，保留宣言灵魂标签「Cloud Native-True Cloud Native」置首，其余替换为 4 枚动态/静态徽章：GitHub Stars（shields.io 动态实时）、Release（v0.1.2，自动读取最新 tag）、License（动态读取仓库 Apache-2.0）、Docs（静态链接文档站 ipxe.lecreate.asia，蓝色取项目主色），全部 URL 已验证返回 200

---

## 2026-08-12

### 新增

- **文档站：新增《引导介质制作指南》（`docs/zh/guide/quick-deploy/boot-media.md`）**——快速部署专题第一篇，置顶于「项目环境部署」之上；涵盖 UEFI 直启（direct-uefi 手工 U 盘 / 本地 ESP）、GRUB 引导（grub-bios 的 GRUB2/GRUB Legacy/SYSLINUX 链式加载）、USB 整盘镜像（usb 的 Linux/Windows 写入）与选型指南，介绍 ipxe-stateless 固件六类构建产物中三类本地引导载体；叙述语气正式化（部署障碍、人工介入成本、Secure Boot 限制等表述）；英文侧边栏同步加「Boot Media」占位条目并创建占位页（翻译待后续补齐）；文档站默认入口（导航与首页 hero 按钮）仍指向「项目环境部署」

### 变更

- **原理探索系列：标题去「全流程」化 + 早期探索声明**——「Windows 11 24H2 无盘系统全流程实战」改为「Windows 11 无盘启动技术攻坚」、「Debian 12 无盘系统全流程实战」改为「Debian 12 无盘启动技术攻坚」（正文 H1 与中英侧边栏同步）；第一～三章（中文 3 篇 + 英文 3 篇）在文首统一加入早期探索声明，说明文章为项目早期探索记录、所述方案与当前架构存在差异、仅供底层研究参考；英文版占位页（`docs/guide/debian-12.md`）标题同步改为 Technical Breakthrough 并更新指向中文版的链接文案
- **第三章（Debian 12 无盘启动技术攻坚）补写路线三并正式收尾**——新增 3.4 节「debootstrap 构建纯净骨架（思路）」：仅讲解工程定位与核心思路（最小化装配、底层依赖注入、UUID 寻址、自动化友好），不再提供逐步操作命令，实操引导至快速部署系列《Debian 系无盘快速部署（母盘克隆）》；文末「未完待续…」替换为「本章小结：从 no way 到三条路线跑通」，以三路线对比表收束 3.1 方法论，并抛出 per-worker initramfs 注入痛点以衔接第四章 iBFT 主题；英文占位页结构同步为三路线并注明 3.4 仅思路级覆盖
- **英文文档目录与中文对齐：原理探索系列迁入 `exploration/` 子目录**——英文 6 篇（Ch1–Ch4、控制面、壁垒）经 `git mv` 从 `docs/guide/` 平铺结构迁入 `docs/guide/exploration/`（保留 Git 历史），与中文 `docs/zh/guide/exploration/` 完全对称；前言仍留 `docs/guide/preface.md`；侧边栏链接同步更新；旧路径不保留重定向（直接 404），标题风格维持英文 Ch1:/Ch2: 紧凑前缀不变
- **文档站：清理 VitePress 脚手架示例页**——删除 `docs/api-examples.md`（Runtime API Examples）与 `docs/markdown-examples.md`（Markdown Extension Examples），两者为脚手架自带示例、全仓库无任何引用，文档站根目录仅保留 `index.md`
- **早期探索声明范围收窄**——从第四章（iBFT 母盘克隆）、控制面能力详解、我们已经攻克的壁垒中英 6 篇文首移除「早期探索声明」：三者描述当前架构能力（iBFT 方案、控制面设计、已攻克壁垒），不属于早期探索记录；前言声明同步移除；声明仅保留于第一～三章（中英各 3 篇）
- **控制面能力详解（中英）内容核对更新**——补齐 8-03 以来全部能力：MAC 绑定修改（`PUT /workers/{id}/mac` + `worker.mac.update` 审计历史）、单系统盘独立删除（`DELETE /workers/{id}/luns/disk/{os}`，delete_file / ignore_missing_target）、批量部署（`/workers/luns/disk/batch` 自动设默认启动 + `/workers/delete/batch` 统一 reload，WebUI 勾选 / 拖拽 / 均摊 / 接管）、自动注册运行时开关（`GET/PUT /settings/auto-register` + `state/settings.json`，环境变量降级为启动默认值）、Agent 注册 / 探测 / 在线编辑（probe 两步推导、enabled 停用）、母盘清单（`GET /masters` 聚合 + Agent 30 秒扫描缓存 + WebUI 下拉选母盘）、ZFS 克隆细节（同数据集 reflink、跨数据集 / 版本过低 / xfs/ext4 回退全量拷贝、`fs_type` 上报）、建盘按 `role.disk` + `enabled` 调度；设计原则补 `state/settings.json`；WebUI 各条目同步（批量模式、MAC 编辑、单盘删除、Agent 两步注册编辑、自动注册开关、母盘下拉）
- **壁垒文章移出文档站，转为 GitHub 仓库展示**——《我们已经攻克的壁垒 / Barriers We Have Broken Through》经 `git mv` 从 `docs/{zh/}guide/exploration/` 移至仓库根目录（`Barriers_zh-CN.md` / `Barriers.md`，保留 Git 历史）；中英侧边栏条目移除，文档站内不再生成与引用该页面；README 两版官方文档列表新增根目录文件入口（原 Exploration 条目描述中的 Barriers 字样移除）
- **壁垒文章内容更新（中英同步）**——新增「控制面与基础设施攻坚」分组 6 条（第 10–15 条）：dnsmasq 文件级 bind mount 的 inode 陷阱（rename 原子写换 inode 致 HUP 失效，改截断写保持 inode）、LIO 与 stgt 的 iSCSI root 连接符差异（`iscsi-sep` 按后端投影 + `isset` 守卫）、真实 iPXE 固件 `${mac:hexraw}` 展开为空（改 `${mac}` 后端归一化）、Zero-touch 自动注册静默失效（controller_ip 改 `${next-server}` 零硬编码）、WebUI 白屏 null 解引用（角色计算延后至空态分支后）、确认弹窗被容器 overflow 裁剪（改 fixed 全屏遮罩）；引言同步补控制面基建维度
---

## 2026-08-01

### 新增

- Control Plane：`POST /workers/{worker_id}/luns/disk` —— 给指定 Worker 创建系统盘 LUN（母盘克隆 / 空白盘），端点位于 `/luns/` 命名空间，为数据盘（`/luns/data`）与多系统盘预留
- Control Plane：`PUT /workers/{worker_id}/default-os` —— 设置 Worker 默认启动配置，三个字段可设可清、可组合（详见下方"变更"）
- Control Plane：`GET/POST/DELETE /agents/{agent_id}/luns` 与 `POST /agents/{agent_id}/luns/scan` —— Agent iSCSI LUN/target 直管（列出 / 创建磁盘 / 创建 CD / 删除 / 扫描）
- Agent：`/lun/scan` 端点与扫描镜像目录重建 target 能力
- 配置文件：`iscsi-server/.env.example` 模板（补齐 `IPXE_*` 变量说明）

### 变更

- **创建 Worker 流程重构为两步（存储与身份分离）**：
  - `POST /workers` 只注册身份（hostname + MAC 绑定），不再接受 `disk` 字段；台账 `os` 字段移除，`state=registered`
  - 系统盘须另调 `POST /workers/{worker_id}/luns/disk` 创建，`os` 改为必填，写入 `disk.os` 台账（决定 IQN 后缀与文件名）；创建后 `state` 转 `ready`
  - 建盘 `os` 严格校验 ∈ `{windows, ubuntu, debian, centos, esxi}`（menu.ipxe 操作系统项）
  - Windows ISO 安装光驱仍随 `POST /workers` 的 `windows_iso` 创建，CD IQN 后缀固定为 `windows.iso`
- **默认启动配置模型**：
  - `PUT /workers/{worker_id}/default-os` 支持 `os`（默认系统，须与已挂系统盘一致）、`menu_default`（严格校验 menu.ipxe 主菜单 item ID）、`menu_timeout`（非负整数）；传 `null` 清除对应项
  - `/boot-vars` 推导链：`default_os` > `boot.menu_default` > `exit`；`boot.menu_default` 登记后随时可改（解决 WebUI 无法操作的问题）
  - 操作日志统一为 `worker.boot.set`（changes 明细）
- 时区处理全链路本地化：
  - `control_plane/app/state.py` 与 `iscsi-server/agent/app/main.py`：日志时间戳由 `datetime.now(timezone.utc)` 改为 `datetime.now().astimezone()`（跟随容器 TZ）
  - 两个 Dockerfile 安装 `tzdata` 并设 `ENV TZ=Asia/Shanghai`；`TZ` 环境变量写入 `control_plane.env`、`.env.example`、`iscsi-server/.env`、`.env.example`，docker-compose 不再写死
  - WebUI `Operations.jsx` 与 nginx njs `file-list.js` 改为本地时间展示
- 文档：`Control_Plane_API_Docs.md` 全面同步（两步创建流程、default-os 端点与合法值表、测试顺序、实现边界）

### 修复

- `DELETE /workers/{worker_id}` 在 Worker 无系统盘（`disk=None`）时不再崩溃（原 `_delete_target(record["disk"])` 会 TypeError）
- 日志时间与宿主机不一致问题（根因：代码写死显式 UTC，`/etc/localtime` 挂载对其无效）

---

## 2026-08-02

### 新增

- Control Plane：**/boot-vars 自动注册（Zero-touch Provisioning）**——新 MAC 请求时自动按顺序分配 hostname（`worker-%02d`，扫描台账 + dhcp 绑定最大序号 +1）、写入台账与 dhcp 绑定并 reload，返回 `menu-default=reboot` 短超时循环重启，等待管理员建盘 + 设置 `default_os` 后自动进入系统；新增环境变量 `IPXE_CP_AUTO_REGISTER`（默认 `true`）与 `IPXE_CP_AUTO_BOOT_TIMEOUT`（默认 `1`，单位毫秒）

### 变更

- **/boot-vars 行为调整**：
  - 身份识别改为 hostname 优先（hostname 未命中或未传时退回 MAC 反查）；无系统盘 Worker 不再返回空脚本，`menu_default` 兜底由 `exit` 改为 `reboot`（未配置默认启动时短超时循环重启；`exit` 仅显式设置时返回）
  - 无系统盘时不返回 `base_iqn`/`iscsi_server`（iPXE 沿用 `boot.ipxe.cfg` 静态默认值），`menu_timeout` 在 reboot 循环中固定用 `IPXE_CP_AUTO_BOOT_TIMEOUT`
- **WebUI Agent LUN 直管界面**：
  - Agents 页面卡片可点击，跳转新增 `agents/:id` 页面（`AgentLuns.jsx`）：列出该 Agent 全部 iSCSI LUN（DISK/CD 类型识别、backing、绑定状态），支持直接创建磁盘（母盘克隆 / 空白盘）、创建 CD（ISO）、删除、扫描目录重建 target，不依赖 Worker
  - 删除已绑定 Worker 的 LUN 时，确认框提示绑定关系（“删除后该 Worker 将无法启动”）并可选同时删除 backing 文件；列表中标黄显示“绑定: worker-xx”
- **WebUI 创建 Worker 流程改为两步（与后端对齐）**：
  - Workers 页创建表单只注册身份：worker_id + MAC（必填）+ Windows ISO（可选），不再传已废弃的 `os`/`disk` 字段；hostname 默认取 worker_id（不再单独填写）；列表 OS 列改读 `disk.os`
  - Worker 详情页新增“创建系统盘（第二步）”表单：系统（严格五选：windows/ubuntu/debian/centos/esxi）+ 磁盘类型（空白盘/母盘克隆）+ 大小/母盘名 + 存储节点；无盘 Worker 才显示，创建成功后状态转 `ready` 并刷新详情
- **系统盘模型升级为多盘（`disk` 单字段 → `disks` 数组）**：
  - 一个 Worker 可挂多个系统的系统盘（同一 `os` 至多一个，重复创建返回 `409`）；`POST /workers/{worker_id}/luns/disk` 不再限制单盘，创建表单在 Worker 详情页始终可用
  - 旧台账单盘字段 `disk` 自动迁移并入 `disks`（首次追加新盘时完成），读取全链路兼容
  - `/boot-vars` 选盘：`default_os` 对应的系统盘，未设时取第一块；`GET /workers/{worker_id}/status` 的 `actual.disk` 改为 `actual.disks` 数组（每项含 `os`）；`DELETE /workers/{worker_id}` 删除全部系统盘
  - WebUI：Workers 列表 OS 列显示全部系统（逗号分隔）、详情页展示每块盘卡片（含 os）、Agent LUN 页绑定检测覆盖全部盘
- **WebUI 默认启动配置表单**：Worker 详情页新增“默认启动配置”区块——展示当前 `default_os`/`boot.menu_default`/`boot.menu_timeout`，表单对接 `PUT /workers/{worker_id}/default-os`（os 仅可选已挂载系统盘，menu_default 为 menu.ipxe 主菜单 11 项，均可选“— 清除 —”，menu_timeout 支持“清除超时设置”复选框），保存后刷新台账与 /boot-vars 代码块
- **开发环境**：项目根新增 Python 虚拟环境 `.venv`（安装 control_plane 与 iscsi-server agent 的 requirements），`.gitignore` 增加 `.venv/`、`venv/`、`__pycache__/`、`*.py[cod]`
- **文档站首页定制（中英双语）**：新增 `docs/.vitepress/theme/`（`index.js` 引入 `custom.css`）——整体黑白极简配色（浅色模式近黑 `#18181b`、深色模式近白 `#f4f4f5`，按钮文字反色适配），hero 大字等宽字体纯黑白（无渐变无动画），hero 背景仅留极淡网格，副标语中性灰；**首页内容由 6 个 feature 卡片改为朴素列表**（无圆点、细分隔线），中英文内容对齐当前版本（零接触自动注册 / 一机多系统 / 中心控制面 + Web UI / 秒级启动 / 拒绝黑盒 / 100% 纯开源工具链）
- **文档：新增《Windows 无盘快速部署（母盘克隆）》快速部署栏目**——`docs/zh/guide/windows-quick-deploy.md` 全流程（Controller 双编排部署 → 存储节点 Agent 部署 → 母盘制备/上传 → WebUI 秒级克隆 → 默认启动），文档站侧边栏新增「快速部署」分组；定位与环境部署文档与原理向实战文档区分
- **文档：文档站重构为「原理探索」+「快速部署专题」双专栏**——侧边栏新增「原理探索」分组（前言与第一～三章归入，记录 iPXE 无盘技术原理）、原「快速部署」分组更名「快速部署专题」，导航「实战指南」更名「原理探索」；新增《第四章：Debian 系 iBFT 无盘启动——母盘克隆的优雅解法》（`docs/zh/guide/debian-12-ibft.md`）：iBFT 六环链路（sanboot 写表 → ISCSI_IBFT_FIND 发现 → iscsi_ibft 导出 sysfs → initramfs ISCSI_AUTO → iscsistart -b 登录 → root=UUID 挂根）、内核配置与 open-iscsi 源码证据（hook 只拷 iscsistart/initiatorname.iscsi/iscsi.initramfs、node.startup 与 iBFT 无关）、母盘四步构建配方与 initrd 三件套验证、0x7f22208e 踩坑（固件可移动介质契约需 ESP 的 BOOTX64.EFI）、Debian 系通用性论证
- **文档：《Windows 无盘快速部署》新增 4.3 节「真实硬件制备母盘（备选路径）」**——目标硬件含专有驱动（特殊网卡 / RAID / HBA）时可在同型号真实机器上安装一次即得母盘；盘转换三种方式（disk2vhd + qemu-img / 拔盘 dd / Live 环境 dd）；驱动真实匹配、克隆零驱动问题，命名与克隆契约与虚拟机母盘完全一致
- **文档：新增《Debian 无盘快速部署（母盘克隆）》快速部署专题第二篇**——`docs/zh/guide/debian-quick-deploy.md` 全流程（环境准备与 Windows 篇共用清单 → 母盘制备（UEFI+GPT 前提 / 虚拟机与真实硬件双路径 / 四步配方 / BOOTX64.EFI / initrd 三件套验证 / 转换命名）→ 上传 → 自动注册 → WebUI 克隆（IQN `worker-xx.debian`）→ 默认启动 → 验收 iBFT）；FAQ 覆盖 0x7f22208e、VFS 根挂载失败、root=UUID 疑虑；侧边栏「快速部署专题」追加条目
- **文档：第四章《Debian 系 iBFT 无盘启动》新增 4.5 节「真实硬件制备（备选路径）」**——真实硬件安装后应用四步配方即得母盘，dd 全盘转换，契约与虚拟机母盘一致；原 4.5/4.6 顺延为 4.6/4.7
- **文档：中文文档站目录按专题分文件夹**——`docs/zh/guide/` 下新建 `exploration/`（原理探索：第一～四章）与 `quick-deploy/`（快速部署专题：Windows/Debian 两篇），前言保留根目录；`docs/.vitepress/config.mts` 侧边栏与 `docs/zh/index.md` 首页链接全部更新；README.zh-CN.md / README.md 文档站链接同步更新（zh README 同时收录第四章与快速部署两篇）
- **文档：环境部署独立成篇，快速部署两篇收窄为母盘专题**——新增《项目环境部署》（`docs/zh/guide/quick-deploy/environment-deploy.md`）：部署拓扑与 Controller / 存储节点部署（原 Windows 篇第 1~3 步）平台无关化，附部署核对清单与两篇母盘入口；Windows 篇删除环境部署部分、步骤重编号（原第 4~9 步 → 第 1~6 步，4.1~4.3 → 1.1~1.3）；Debian 篇环境准备清单改为指向新文；侧边栏「快速部署专题」置顶新篇，README.zh-CN.md 快速部署列表同步
- **文档：《Debian 无盘快速部署》更名《Debian 系无盘快速部署（母盘克隆）》**——正文同步覆盖 Debian 系发行版：1.1 安装小节与 1.2 真实硬件路径补充 Ubuntu 20.04/22.04/24.04，1.4 补充 Ubuntu 安装器源路径 `\EFI\ubuntu\`，1.6 命名表新增 Ubuntu 示例（`_tpl_ubuntu_24.04.img`，克隆时 OS 选 `Ubuntu`、IQN 后缀 `.ubuntu`）；侧边栏、README.zh-CN.md、环境部署篇引用同步（URL 保持不变）
- **文档：《Debian 系无盘快速部署》新增「支持范围」小节**——基于官方包库与内核配置查证：open-iscsi 在 Debian 11~13 与 Ubuntu 22.04/24.04/26.04 全系存在且自带完整 initramfs 集成（hooks/iscsi + local-top/iscsi，支持 `iscsi_auto`）；内核 `CONFIG_ISCSI_IBFT=m` 强制开启 `CONFIG_ISCSI_IBFT_FIND=y`（kernelconfig.io）；Ubuntu 的 `iscsi_ibft`/`iscsi_tcp`/`ib_iser` 模块位于基础 `linux-modules` 包（noble `generic.inclusion-list` 证实，最小安装自带，无需 linux-modules-extra）；矩阵标注 Debian 12 已实测、其余为同链路机制支持，并排除已 EOL 的 Debian 10 / Ubuntu 20.04
- **文档：英文文档站结构与中文站对齐**——侧边栏改为双专栏（Exploration：Foreword + Ch1~Ch4；Quick Deploy：Environment Setup + Windows/Debian-family Master Image），导航新增「Quick Deploy」；新增 5 个英文占位页（Ch3 `docs/guide/debian-12.md`、Ch4 `docs/guide/debian-12-ibft.md`、快速部署 3 篇 `docs/guide/quick-deploy/*.md`），每页含内容骨架与中文版链接（标注 translation in progress）；英文首页 hero 主按钮改为 Quick Deploy（与中文对齐）；README.md 文档章节补全为双专栏 7 条并改用英文站链接
- **文档：README.zh-CN.md 重构 + 路线图独立成文件**——新增 `ROADMAP.md`（路线图 Phase 1~4 + 近期规划，其中 CLI/reconcile/一键部署脚本从 README「控制面推进中」迁入）；README.zh-CN.md 重组为清晰分层（简介 → 架构总览（角色 + 设计原则 + 流量，合并原「项目总览」与「架构定义」）→ 核心能力 → 控制面能力详解（原「当前进展」拆出，消除与核心能力重复）→ 快速开始 → 官方文档 → 项目结构（补 ROADMAP.md）→ 攻坚记录 → 路线图（改为链接）→ 参与贡献 → License → 成长轨迹）；英文 README.md 保留其英文版 Roadmap 不动

### 修复

- WebUI 错误提示显示 `[object Object]`：FastAPI 422 的 `detail` 是校验错误数组，`api/client.js` 现在逐条拼接为 `字段: 错误信息` 文本
- **Agent LUN 直管页面按后端角色禁用创建按钮**：LIO 后端（`role.cd: false`）的“创建光驱 (ISO)”按钮置灰不可点，并显示提示“LIO 后端不支持 ISO 光驱”（hover 亦有 title）；同理 `role.disk: false` 时禁用“创建磁盘”；表单渲染双保险（无 role 配置的旧数据默认放行）；后端 `POST /agents/{id}/luns/cd` 与 `/luns/disk` 同步新增角色校验（400 拒绝，不再透传到 Agent）
- **Agent LUN 页白屏修复**：上一版将 `agent.role` 角色计算放在组件首次渲染（`agent` 为 null）即执行，导致 `TypeError: Cannot read properties of null (reading 'role')`，React 整树卸载白屏（API 请求都来不及发出）；现改为在 `if (!agent) return` 空态分支之后计算，并顺带修复 `Button` 组件不透传 `title` 等剩余属性（hover 提示此前未生效）
- **Zero-touch 自动注册不生效（worker 拿不到 hostname、不重启）**：根因是 `tftp/boot.ipxe.cfg` 的 `set controller_ip 192.168.1.5` 仍是模板默认值，与实际网段（192.168.80.x）不符——iPXE 请求 `http://${controller_ip}:4839/boot-vars` 不可达后 `|| goto vars-done` 静默跳过，后端从未收到请求（台账/dhcp 绑定始终为空），`menu-default` 由 menu.ipxe 兜底为 `exit`、`menu-timeout` 兜底为 0，菜单不自动选择也不重启；已改为 `set controller_ip ${next-server}`（同机部署下 next-server 即 DHCP 服务器 IP，与 dnsmasq 网段、agents.yml `iscsi_server` 一致，零硬编码，换 IP 无需改脚本），并清理了排查期间用假 MAC 触发自动注册产生的测试 worker（worker-00 及 dhcp 绑定，需重启 dnsmasq 容器彻底清除内存态）
  - **mac 传参由 `${mac:hexraw}` 改为 `${mac}`**：真实 iPXE 设备实测 `${mac:hexraw}` 修饰符展开异常（mac 参数为空导致后端不识别），带冒号格式 `${mac}` 一切正常；后端 `_normalize_boot_mac` 会剥离冒号/横线/点号归一化，两种格式均可识别
  - **自动注册编号从 `worker-01` 开始**：`_next_auto_hostname` 初始序号由 -1 改为 0（原逻辑第一个分配 `worker-00`），并将已注册的 worker-00 无缝改名为 worker-01（台账 + dhcp 绑定已同步，重启 dnsmasq 生效）
- **README.zh-CN.md 全面更新**：项目结构对齐当前代码（移除已删除的 `iscsi-target-gen.sh`，补齐 `CHANGELOG.md`、`assets/`、`iscsi-server/.env`、`webui/deploy/nginx/njs`、`docs/.vitepress` 等）；新增“核心能力”章节（零接触注册 / 一机多系统 / 中心控制面 + Web UI / 秒级启动 / 拒绝黑盒 / 纯开源）；功能介绍对齐当前实现（Zero-touch 自动注册、两步创建 + 多系统盘、默认启动配置、Agent LUN 直管与角色模型、WebUI 两步流程与 LUN 直管页）；Roadmap 勾选已完成的中心控制面与 Controller 容器化；文档章节补充第三章 Debian 12；移除表情符号；License 链接修正
- **Control_Plane_API_Docs.md 同步更新**：`/boot-vars` 的 iPXE 接入代码块与推荐传参改为 `${mac}`（注明 hexraw 修饰符在部分固件展开异常、chain 失败静默兜底与派生变量重建）；自动注册编号示例改为 `worker-01` 起；`IPXE_CP_AUTO_BOOT_TIMEOUT` 单位明确为毫秒；示例 IP 由模板值 192.168.1.5 改为实际网段 192.168.80.3；Agent LUN 直管补充 `role.disk`/`role.cd` 角色校验（400）；实现边界将多系统盘移入已支持列表

---

## 2026-08-03

### 新增

- Control Plane：`DELETE /workers/{worker_id}/luns/disk/{os}` —— 删除 Worker 的单个系统盘（iSCSI target）：`delete_file` 参数控制是否同时删除 backing `.img` 文件（`false` 仅删 target、文件保留可重新挂载），`ignore_missing_target` 在 Agent 侧 target 已不存在时忽略 404 继续完成台账清理；操作日志新增 `worker.disk.delete`（started/succeeded/failed）
- WebUI：Worker 详情页「系统盘」每张磁盘卡片新增**删除系统盘**按钮——ConfirmAction 确认弹窗（可勾选「同时删除 .img 磁盘文件」与「忽略已不存在的 Target」），删除中按钮禁用并显示「删除中...」，成功后自动刷新台账与启动变量
- Control Plane：`/boot-vars` 新增 `iscsi_sep` 字段——iSCSI root **连接符**（`${iscsi-server}` 与 `${base-iqn}` 之间的分隔字段），**按系统盘所在 Agent 的后端类型生成**：stgt 后端为 `:::1:`（lun 占位 1），LIO 后端为 `::::`（空占位，解决 LIO 后端 iSCSI 连接参数不兼容问题）；只投影差异连接符本身，root-path 拼装（`iscsi:${iscsi-server}${iscsi-sep}${base-iqn}:${hostname}.<os>`）由 iPXE 侧静态完成；后端类型优先读 `agents.yml` 该 Agent 的 `tags`（含 `lio`/`stgt` 标记，离线零成本），未标记时查询 Agent `/capabilities` 的 `backend` 字段（Agent 自报），查询失败默认 stgt 格式兼容

### 变更

- **文档：README 全面入口式重构（对齐 Docker/K8S 风格），控制面详解与攻坚记录迁入文档站**——README.md / README.zh-CN.md 精简为入口式结构（定位 → 架构三角色 → 核心能力 6 条 → 快速开始（clone + compose up + 端口）→ 官方文档链接 → 路线图（指向 ROADMAP.md）→ 参与贡献 → License → Star History），删除原「控制面能力详解」「我们已经攻克的壁垒」「详细项目结构」全文；文档站新增《控制面能力详解》（中英：设计原则 + 核心能力 8 项 + WebUI 能力 + 文件浏览器）与《我们已经攻克的壁垒》（中英：Linux 引导链 / Ubuntu / Windows 分组 9 条），VitePress 侧边栏注册（中英 Exploration 分组）；参与贡献章节新增 AI 辅助开发态度声明（不反对 AI 生成代码——项目本身由 Qwen/Codex/DeepSeek 协同完成，但贡献者必须自行理解整体架构：控制面/数据面分离、iPXE 引导链、动态变量传递链、文件即真相、iSCSI 会话保活；无法清晰阐述设计逻辑的 PR 拒绝合并，鼓励先提 Issue/Idea）
- **文档：`Control_Plane_API_Docs.md` 同步系统盘删除接口**——接口概览表新增 `DELETE /workers/{worker_id}/luns/disk/{os}` 条目，新增 7.4 章节（参数说明 + 保留 .img / 同时删除 .img 两个 curl 示例）
- **iPXE 脚本使用 `${iscsi-sep}` 变量**：`menu.ipxe` 全部系统项与安装项的 root-path 改为 `iscsi:${iscsi-server}${iscsi-sep}${base-iqn}:${hostname}.<os>`（原 `base-iscsi` 移除）；`boot.ipxe.cfg` 兜底值改为 `set iscsi-sep :::1:` + chain 后 `isset ${iscsi-sep} || ...` 守卫（不覆盖 `/boot-vars` 已下发的 LIO 格式）；WebUI `buildBootVarsCode` 展示 `set iscsi-sep`；API 文档 5 章节（字段来源表 + iPXE/JSON 示例 + 接入方式）与文档站控制面详解/Windows/Debian 文档同步更新

---

## 2026-08-03

### 新增

- Control Plane：`POST /workers/luns/disk/batch` — 批量给多个 Worker 创建系统盘（母盘克隆 / 空白盘），请求体 `targets` 逐项指定 `{worker_id, agent}` 存储节点分配（须已分配，不存在默认公共分配）；与单盘一致同一 `os` 至多一块、已存在自动跳过（不算失败）；逐项独立执行，单项失败不影响其余，返回 `succeeded` / `skipped` / `failed` 汇总；**创建成功的 Worker 自动将 `default_os` 设为本次批量系统**（批量部署直接进入默认启动，无需再调 `PUT /workers/{id}/default-os`；单盘接口不自动设置，审计记录 `worker.boot.set`）
- WebUI Workers 页新增「批量创建系统盘」模式：
  - 仅批量模式下每行出现勾选框，已拥有系统盘的 Worker 行标浅黄提醒（可正常勾选，重复 `os` 由后端自动跳过）；点击勾选单个，Shift+点击标定终点、中间自动勾选（范围选择基于当前筛选结果顺序）
  - 左侧常驻侧边栏（悬浮于视口左侧、不挤占原列表宽度）：已选 Worker 计数 + 批量系统盘参数（系统 / 空白盘或母盘克隆 / 大小或母盘名，**不含存储节点**）+「开始批量创建」按钮与结果汇总（成功 / 跳过 / 失败明细）
  - 右侧常驻侧边栏（悬浮于视口右侧、不挤占原列表宽度）：列出全部存储节点（role=disk），每个节点一个可拖拽标签框，内含「参与均摊」勾选 +「接管所选 Worker」按钮（已选 Worker 统一改派给该节点，覆盖之前单独指定）与已分配计数；节点列表底部新增「均摊分配所选 Worker」——勾选 ≥2 个节点后，已选 Worker 按参与节点轮流平均分配（覆盖之前分配）；拖动节点标签放到某行 = 该 Worker 单独指定该存储节点；行的「存储节点」列展示分配结果并可单独取消分配

### 变更

- 文档：`Control_Plane_API_Docs.md` 接口概览表新增批量创建条目，新增 7.1.3 章节（请求体字段表 + curl + 返回示例）

---

## 2026-08-03

### 新增

- **首个发行版（v0.1.0）发布准备 — 环境配置与注释收尾**：
  - `iscsi-server/.env` 与 `control_plane/config/agents.yml`（含真实部署 token）解除 git 跟踪并加入 `.gitignore`，仓库只保留 `*.example` 模板
  - 新增 `webui/app/.env.example`（VITE_CP_TOKEN 构建期变量说明）
  - `control_plane.env(.example)` / `iscsi-server/.env(.example)` 补齐分组注释（文件路径、dnsmasq 联动、启动行为、Token 同步说明）
  - `control_plane/config/agents.yml.example` 补齐字段注释（base_url / iscsi_server / token 占位 / role / tags / enabled）
  - 根 `docker-compose.yml`：各服务补齐职责注释，移除无人引用的误导性 `networks.ipxe` 段；`iscsi-server/docker-compose.yml` 补齐后端与 Agent 注释、清理行尾空格
  - `iscsi-server/agent/Dockerfile` 移除开发期对话遗留注释，改为规范说明
  - README（中英）快速开始补全配置步骤：`cp *.env.example` 准备流程、API 鉴权 Token 同步、存储节点独立部署指引
  - 文档收敛：删除冗余的 `iscsi-server/Agent_API_Docs.md`，保留更全面的 `API_Reference.md`（补入 Token 常量时间比对细节）
- Control Plane：`POST /workers/delete/batch` — 批量删除 Worker（请求体 `worker_ids` + `delete_disk` / `ignore_missing_target`）：每项独立执行（单项失败不影响其余，不存在的计入 failed），返回 `succeeded`/`failed` 汇总；成功项统一保存台账、统一 reload 一次 dnsmasq（优于逐删逐 reload）；审计逐项 `delete_worker`
- WebUI Workers 页新增独立「批量删除 Worker」模式（与批量创建互斥）：工具栏独立按钮进入/退出，勾选后左侧栏确认删除（含「同时删除 .img」/「忽略缺失 target」选项，与详情页一致）→ 结果汇总展示，成功后清空勾选并刷新
- Control Plane：`POST /agents/probe` — 探测 Agent 并自动推导注册参数（预览，不写文件）：调 `/healthz` + `/capabilities`，推导 `role`（disk 恒真 + cd 取 capabilities）/ `tags`（storage + backend）/ `iscsi_server`（回退 base_url 主机名），返回 backend / base_iqn / clone 等能力供确认；Agent 不可达或 token 错误返回 502，审计记录 `agent.probe`
- Control Plane：`POST /agents` — 注册新 Agent 写入 `agents.yml`，注册后立即生效；请求体含 `id` / `base_url`（须 http(s)://） / `token`（支持 `${ENV}` 占位）/ `iscsi_server` / `role`（disk/cd）/ `tags` / `enabled`；重复 id 返回 409，审计记录 `agent.register`；`AgentRegistry` 新增 `add()`（yaml 写回保持 `agents:` 顶层结构）
- WebUI Agents 页新增「+ 添加 Agent」入口（两步流程）：填 Agent ID / API 地址 / Token 点「探测」→ 后端自动获取后端类型 / 角色 / 标签 / 数据面地址等参数并在预览区展示（可修改，含只读能力标签）→ 点「添加」完成注册并刷新列表；地址变更后旧探测结果自动失效

### 变更

- 文档：《项目环境部署》1.3 节固件获取方式更新——不再下载解压 `tftp.zip`，改为从 [boot.ipxe.org](https://boot.ipxe.org/) 直接下载官方 release 固件（`undionly.kpxe`，以及 `x86_64-efi/` 下的 `ipxe-legacy.efi` / `ipxe.efi` / `snponly.efi`），全部统一放入 `tftp/` 根目录（不保留官网 `x86_64-efi/` 子目录，`wget` 默认只取 URL 末尾文件名）；`ipxe.efi` / `ipxe-legacy.efi` 为 UEFI 引导异常时的备选固件（改 `dnsmasq.conf` 的 efi64 引导文件）；补充 memdisk 说明——取自 SYSLINUX 发行包 `bios/memdisk/memdisk`，仅「iPXE 直接引导 ISO」的旧方式需要，常规无盘启动（iSCSI sanboot）不需要；中英文档同步

---

## 2026-08-04

### 新增

- Control Plane：`PUT /agents/{agent_id}` — 更新已有 Agent 配置（id 不可改，走路径参数）：`base_url` / `token` / `iscsi_server` / `role` / `tags` / `enabled` 全量覆盖写回 agents.yml，保存后立即生效；`token` 传空字符串 = 保持原值（API 不回显 token，前端无法回填）；`enabled=false` 停用（不再参与建盘/挂载调度与存活探测）；不存在返回 404，审计记录 `agent.update`；`AgentRegistry` 新增 `update()`（原 token 保留）
- Control Plane：`POST /agents/probe` 新增可选 `agent_id` 参数 — 编辑场景 token 留空时自动沿用注册表中该 Agent 的 token 探测（未知 id 忽略）
- WebUI Agents 页每张卡片右上角新增「编辑」按钮 — 点击后在列表上方弹出遮罩弹层（fixed 覆盖，不挤占原有布局；点遮罩空白处或「取消」关闭），编辑表单复用添加的两步探测流程：id 只读展示（走路径参数）、Token 留空保持不变（placeholder 提示，探测沿用注册表原值）、新增「启用（参与调度）」复选框，探测成功后方可保存，保存后刷新列表；停用的 Agent 卡片显示「停用」徽章
- Agent：`GET /masters` — 列出存储节点 `DISK_DIR` 下 `*_tpl_*` 母盘（新增 `MasterScanner` 后台 daemon 线程，每 30 秒周期扫描并带锁缓存 `{name, size, mtime}`，识别文件名含 `_tpl_` 标记的镜像；纯读接口，Bearer 鉴权，不写操作日志）
- Control Plane：`GET /masters` — 聚合列出全部启用磁盘角色 Agent 的母盘清单（遍历 `agents.yml` 中 `enabled` + `role.disk` 节点，逐台调用 Agent `list_masters()`；单台失败返回 `error` 字段并记审计 `master.list`（failed）不阻塞整体，全部失败 502 / 部分成功 200 / 无候选空列表）；`AgentClient` 新增 `list_masters()`
- WebUI：母盘克隆下拉选择——Workers 批量创建与 Worker 详情页「创建系统盘」的母盘名由手工输入改为下拉选择（数据来自 Control Plane 聚合的母盘清单）：批量模式下拉为母盘名去重选项（不绑定存储节点，选择后不自动接管，节点分配由均摊 / 接管 / 拖拽侧边栏决定），支持多存储节点均摊克隆；提交时校验目标节点本地均有该母盘——均摊激活（≥2 个节点参与均摊）时校验全部参与均摊节点，否则校验实际分配节点，缺失时列出缺失节点并阻止提交（可移除缺失节点的「参与均摊」勾选，或先在对应节点上传该母盘后再提交），克隆在各节点本地完成；详情页按所选存储节点过滤母盘、切换节点自动清空已选

### 变更

- 文档：`iscsi-server/API_Reference.md` 与 `control_plane/Control_Plane_API_Docs.md` 同步母盘清单接口——接口总览表新增 `GET /masters` 条目并新增独立章节（响应结构 `{agents: [{agent, iscsi_server, masters, error?}]}`、字段说明、失败容错语义）；Agent 侧 `API_Reference.md` 新增 `## 12. GET /masters（母盘清单）`，原编号顺延
- 文档：《项目环境部署》第 2 步新增 2.1「准备 img 存储目录」小节（原 2.1–2.5 顺延为 2.2–2.6）：明确 `iscsi-server/docker-compose.yml` 中 `- /pool1/iscsi_img:/home/iscsi_img` 卷映射须将宿主机侧路径改为存储节点实际存放 img 文件的目录（`ipxe-iscsi` 与 `ipxe-agent` 两处一致，容器内 `/home/iscsi_img` 不变）；存储目录文件系统强烈建议 btrfs（母盘克隆走 reflink/FICLONE 秒级完成，ext4/xfs 等不支持时回退全量拷贝，克隆时间随母盘大小线性增长）；新增单台 iSCSI 服务器硬件瓶颈表（网卡速率 / 硬盘 IO / 内存 CPU）与按并发 Worker 规模扩容存储节点建议（10GbE 约支撑 10–20 个并发 Worker）；中英文档同步
- 文档：Windows / Debian 系无盘快速部署「WebUI 秒级克隆」步骤的母盘名改为下拉选择说明——母盘列表由 WebUI 自动扫描存储节点生成（数据来自 Control Plane 聚合的 `GET /masters` 母盘清单，文件名须含 `_tpl_` 标记），无需手工输入；中英文档同步
- 文档：文档站中英文首页「核心能力」更新——以 README 六条为基础结构：原「秒级启动」改写为「母盘克隆秒级交付」（btrfs reflink 秒级克隆 + 支持矩阵同步为 Debian 11/12/13、Ubuntu 22.04/24.04/26.04、Windows 11 23H2/24H2/25H2），新增「批量部署」「Agent 直管与在线编辑」两条，原「中心控制面 + Web UI」并入后者；补齐「文件即真相」；中英文同步
- 文档：Windows / Debian 系无盘快速部署「第 5 步:设置默认启动」由可选步骤改为常规流程——设置默认系统后开机自动直达系统（无需在 iPXE 菜单手动选择）；仅需配置「默认系统(OS)」一个字段，下拉选项来自该 Worker 已挂载的系统盘（即刚克隆出的盘）；「默认菜单项(Menu Default)」保持默认（重启）不动——推导链 `default_os > boot.menu_default > reboot` 中 `default_os` 优先命中，未配置的菜单项维持重启兜底；中英文档同步
- 文档：Debian 系无盘快速部署「支持范围」注明桌面/服务器版本无差别——Ubuntu 不区分 Desktop / Server 版本，桌面环境（GNOME / KDE / XFCE 等）任意选择，不影响无盘启动；Debian 同理，按常规方式正常安装的系统均支持，无需担心桌面环境影响；1.1 安装步骤同步补充说明；中英文档同步
- 文档：IQN 契约表述修正——`tftp/boot.ipxe.cfg` 的 `base-iqn` 仅为静态兜底值（占位符），Worker 启动时 iPXE 经 `/boot-vars` 按系统盘所在存储节点获取实际 `base-iqn`（盘 IQN 前缀，源自该节点 `IPXE_IQN_BASE`）并覆盖；各存储节点 `IPXE_IQN_BASE` 对自身承载的盘是权威值，无需与 `boot.ipxe.cfg` 静态值一致；《项目环境部署》2.3 与快速部署「环境准备」/FAQ 同步修正；中英文档同步
- 文档：IQN 机制表述复核修正——架构文档（中英）1.5 节第 2 步补充 `base-iqn` 静态兜底 + `/boot-vars` 按系统盘所在存储节点动态覆盖机制（原按纯静态配置推演，缺覆盖环节），第 3 步 root-path 拼装改为与 `menu.ipxe` 一致的 `iscsi:${iscsi-server}${iscsi-sep}${base-iqn}:${hostname}.<os>` 变量格式（原硬编码 `::::`）；Control Plane 文档（中英）`/boot-vars` 返回变量列表补入 `base-iqn`；中英文档同步

---

## 2026-08-05

### 变更

- 文档：README 两版与文档站中英文首页 tagline、ROADMAP 的定位表述对齐《我的云原生定义》宣言——由「企业级无状态（Stateless）计算节点交付平台 / Enterprise-grade diskless computing platform / 云原生的无状态计算基础设施底座」统一改为「真正的云原生实现：把无状态贯彻到算力层本身，算力不绑定任何具体硬件，可丢弃、可替换、可瞬间重建」；路线图愿景改为「贯穿所有计算层的云原生元协议——同一套无状态语义自相似地嵌套于物理机与 hypervisor 每一层，层层皆云」；中英文同步
- 文档：新增仓库根目录 `Manifesto_zh-CN.md`（《我的云原生定义》宣言，由《我的云原生定义.md》重命名，移除文首对话残留）与英文全量翻译版 `Manifesto.md`（九章完整翻译，与中文版互为镜像）；README 中英文版定位段后新增宣言引用

---

## 2026-08-07

### 新增

- Agent：母盘克隆新增 ZFS 支持——存储目录位于 ZFS（OpenZFS ≥ 2.2）且母盘与克隆盘在同一数据集时，`FICLONE` 文件级 reflink 秒级克隆（与 btrfs 同路径，零额外磁盘占用）；ZFS < 2.2 或跨数据集（`st_dev` 不同）时自动回退全量拷贝，并在日志中给出明确诊断（区分「版本过低」与「跨数据集」两类原因）；新增 `_fs_type()`（解析 `/proc/self/mounts` 最长挂载点匹配）与 `_same_fs()`（`st_dev` 比较）
- Agent：`GET /capabilities` 新增 `fs_type` 字段（存储目录文件系统类型：btrfs / zfs / xfs / ext4 ...），`clone` 描述按文件系统类型区分（ZFS 标注 OpenZFS ≥ 2.2 与同数据集约束；xfs 标注需 reflink 特性；其余标注仅全量拷贝）；控制面 `GET /agents` 随 `capabilities` 透传
- Control Plane：`GET/PUT /settings/auto-register` —— 全局自动注册开关运行时切换：环境变量 `IPXE_CP_AUTO_REGISTER` 降级为**启动默认值**，运行时状态持久化到 `state/settings.json`（重启保留、优先于环境变量、立即生效）；关闭后新 MAC 不再自动注册（已注册 Worker 不受影响）；切换写入操作日志（`settings.auto_register`）
- WebUI：Workers 页面工具栏新增「自动注册」开关按钮（状态点指示开/关、点击即切换、加载/切换失败显示错误信息）；i18n 中英文案同步
- 文档：控制面 API 参考中英两版新增 5.1 章节 `GET/PUT /settings/auto-register`（含两种配置方式对比表：环境变量 vs 运行时 API），第 3 节端点概览与第 5 节配置表同步更新；《项目环境部署》中英两版新增 1.4.1「自动注册开关」小节（部署时环境变量固定 vs 部署后 WebUI/API 运行时切换，含手动注册提醒）
- 文档：新增仓库根目录 `AI_POLICY_zh-CN.md` / `AI_POLICY.md`（《对 AI 辅助的态度》中英双语立场声明——「总设计师与施工队」边界、语法归 AI / 架构归人脑、PR #3 自动化扫描器误报真实案例记录）；README 两版「参与贡献 · 关于 AI 辅助」段落末尾引用（中文完整引用；英文正式引用，含中文原文互指）

### 变更

- 文档：《项目环境部署》2.1「准备 img 存储目录」存储文件系统建议由「强烈建议 btrfs」扩展为「btrfs 或 ZFS（OpenZFS ≥ 2.2）」，补充 ZFS 文件级 reflink 的同一数据集约束与 ZFS < 2.2 / 跨数据集回退语义；文档站中英文首页「母盘克隆秒级交付」与控制面文档（中英）的 btrfs 表述同步扩展；`iscsi-server/API_Reference.md` `/capabilities` 章节同步 `fs_type` / `clone` 字段说明；中英文档同步
- WebUI：Agents 页面 Agent 卡片新增「文件系统」展示（`capabilities.fs_type`，等宽字体），注册/编辑探测结果新增 `fs_type` 标签；Control Plane `POST /agents/probe` 返回新增 `fs_type` 字段（透传 Agent `/capabilities`）；`Control_Plane_API_Docs.md` 两处示例同步
- 文档：API 文档迁入文档站——`control_plane/Control_Plane_API_Docs.md` 与 `iscsi-server/API_Reference.md` 移至 `docs/zh/guide/api/`（`control-plane-api.md` / `agent-api.md`，标题中文化），文档站新增「API 参考 / API Reference」栏目（中英侧边栏 + 导航栏），英文版为占位页（结构骨架 + 指向中文权威版，不全量翻译）；原文件删除，文档站成为唯一权威；README 两版官方文档列表新增 API 参考链接，快速开始端口区强调 Control Plane API 为开放 REST 接口、第三方系统与自动化脚本可直接调用
- 文档：两份 API 文档与 README 两版强调 **API 优先（API-first）调用准则**——控制面全部能力以 REST API 为第一接口，WebUI 本身只是该 API 的一个客户端；第三方系统与自动化脚本与 WebUI 平等，一律优先调用 Control Plane API（Agent API 为控制面与存储节点间的内部契约，不作为第三方入口）；英文占位页同步
- 文档：README 两版官方文档列表重构——原理探索系列（第一～四章 + 控制面能力详解 + 已攻克的壁垒）折叠为单个「原理探索 / Exploration」入口（指向专栏首页前言），「快速部署手册」与「API 参考」置顶为直达入口
- 文档：措辞修正——README 英文版 `copy-paste runbooks`、中文快速部署文档「可照抄」、英文 API 占位页 `copy-paste curl` 统一改为中性表述（step-by-step / 可直接执行 / directly executable）
- 文档：控制面 API 参考**中英两版**（7.0/7.3 章节）补强「默认启动系统」概念与字段语义——新增「是干什么的」说明（多盘模型下决定 iPXE 菜单超时后自动选中的启动项 + `/boot-vars` 默认启动盘投影；`os` 是菜单项 ID 而非盘名，合法值同建盘 7.1 枚举、不区分大小写）；`menu_timeout` 补 `0` = 无限等待永不自动选择（iPXE 官方语义）；7.0 修正错误示例（注册后无盘实际返回 `menu-default reboot` + 1ms，而非 exit/5000）并区分已配置/未配置两种超时默认值；7.3 与 7.0 `boot` 字段为同一台账字段的覆盖关系；英文版第 3 行残留 `copy-paste` 措辞一并修正
- 文档：README 两版徽章行首新增 **Cloud Native - True Cloud Native** 徽章（定位宣言的直观呈现）
- Control Plane：`SetWorkerDefaultBootRequest` 注释推导链修正（`exit` → `reboot`，与 `_menu_default_for` 实际行为一致）

### 修复

- 文档：API 文档端口号修正——`docs/zh/guide/api/agent-api.md` 全部 curl 示例与 Base URL 由错误的 `localhost:4841` 改为 `4840`（iscsi-server compose 实际映射 `4840:8080`），`control-plane-api.md` 的 `GET /agents` 返回示例 base_url 同步修正；全仓库 4841 零残留
- WebUI：capLabels 克隆方式文案映射缺失 ZFS/xfs/仅全量拷贝新文案（ZFS 支持上线后 UI 直接显示英文原文）——补齐映射并将匹配逻辑改为前缀匹配（动态文案 `full copy only (reflink unsupported on <fs>)` 归并到静态条目）

---

## 2026-08-09

### 新增

- WebUI：添加 / 编辑 Agent 表单新增「iSCSI 数据面地址（可选）」折叠填写框——位于探测前的表单区（Agent ID / API 地址 / Token 之后），默认折叠，点击标题展开/收起（▶ 箭头旋转指示）；编辑模式该 Agent 已配置数据面地址时默认展开；探测成功后自动展开，展示探测推导的地址（base_url 主机名，Worker 侧常不可达），便于现场改为存储节点局域网 IP；中英文案同步

### 变更

- WebUI：探测结果区不再重复显示「iSCSI 数据面地址」输入框（该参数统一收敛到探测前的折叠框）；探测填充逻辑调整——探测前手填的数据面地址优先保留，不再被探测推导值（base_url 主机名）覆盖

---

## 2026-08-10

### 新增

- **Control Plane：`PUT /workers/{worker_id}/mac` —— 修改 Worker 的 MAC 地址绑定**（hostname 不变）：校验新 MAC 格式与占用（已被其他 hostname 绑定返回 `409`），更新 `dnsmasq/dhcp-hosts.conf` 并 HUP 重载（保持 inode 不变，重载立即可见）；审计记录 `worker.mac.update`（含 `old_mac`/`new_mac`/`changed`/`client`，即修改历史，`GET /operations` 可查），MAC 相同时 `changed=false` 不触发重载
- **WebUI：Worker 详情页「身份」卡片新增 MAC 绑定修改**——MAC 行显示当前绑定值 +「修改 MAC」按钮，编辑态提供输入框 / 保存 / 取消，保存失败显示错误（含 409 占用提示），并展示审计提示文案；对接 `PUT /workers/{worker_id}/mac`，保存后刷新台账

### 变更

- **README 中英双版新增「云原生固件仓库」小节**——在「核心能力」与「快速开始」之间引导读者了解配套固件仓库 [iPXE-Stateless](https://github.com/dutyc/ipxe-stateless)：固件本身无状态（DHCP 取配置、链式加载、无盘进系统）、仓库亦无状态（只维护补丁与构建资产、可随新基线重建）、全系无状态适配（RTL8125 native 驱动 / snponly 本地引导兜底 / debug 构建修复）
- **禁用 dnsmasq 容器的 8080 web 管理面板**：`jpillora/dnsmasq` 镜像默认 `ENTRYPOINT=webproc`，会在 8080 启动 web 管理面板（host 网络下直接占用宿主 8080）；compose 覆盖 `entrypoint: ["/usr/sbin/dnsmasq"]` 直接运行 dnsmasq 二进制，完全绕过 webproc；文档验证方式同步改为检查 67/69 UDP 端口监听（`ss -lunp`）

### 修复

- **Control Plane：dnsmasq 主机名绑定写入后不生效（重启 Worker / 手动 `killall -HUP dnsmasq` 均无效，重建容器才生效）**：根因是 `DnsmasqHosts._write_lines` 复用 `_atomic_write_text` 的 rename 原子写（mkstemp + os.replace），每次写入都更换文件 inode；而 `dhcp-hosts.conf` 在 docker-compose 中以**文件级 bind mount**（`./dnsmasq/dhcp-hosts.conf:/etc/dnsmasq.d/dhcp-hosts.conf`）挂载进容器，挂载锁定的是写入瞬间的 inode——rename 后容器内仍指向旧 inode，dnsmasq 永远读不到新绑定，只有重建容器重新挂载才生效；已改为直接截断写原文件（保持 inode 不变），文件级挂载语义不再被破坏，HUP 重载恢复有效
- **WebUI：删除确认框被容器边界裁剪（只能看到一点点）**：根因是 `ConfirmAction` 确认框用 `position: absolute` 在触发按钮下方展开，而 Worker 详情页系统盘卡片（`.detail-card`）设置了 `overflow: hidden`，展开部分被裁剪；批量删除侧边栏（230px 宽 + `overflow-y: auto`）同样存在该隐患。已将 `ConfirmAction` 改为**固定遮罩层 + 居中弹窗**（`position: fixed` 覆盖全屏，`z-index: 200`），不再依赖触发按钮的定位上下文，任何容器都无法裁剪；同时修复点击 disabled 按钮也会弹出确认框的问题（trigger 内 Button 禁用时不弹窗）