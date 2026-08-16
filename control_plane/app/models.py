from typing import Literal

from pydantic import BaseModel, Field


class BootSpec(BaseModel):
    menu_default: str | None = None
    menu_timeout: int | None = None


class CreateWorkerRequest(BaseModel):
    """注册 Worker 身份。mac 可选：不传 = 纯空转 Worker（仅 hostname 绑定）；
    传 = 校验设备在设备池中并直接绑定（一对一授权）。系统盘须另调 POST /workers/{id}/luns/disk。"""
    worker_id: str
    mac: str | None = None
    hostname: str | None = None
    arch: str | None = None
    windows_iso: str | None = None
    boot: BootSpec | None = None


class BatchCreateWorkersRequest(BaseModel):
    """批量创建 Worker（逐项独立）：count 数量 + name_prefix 命名规则，
    worker_id = name_prefix + 序号（从 01 起，位宽按 count 自适应）。
    macs 可选：提供时须与 count 等长，逐项校验设备池并直接绑定；不传 = 全部纯空转。不支持 windows_iso。"""
    count: int = Field(..., ge=1, le=100, description="数量（1-100）")
    name_prefix: str = "worker-"
    arch: str | None = None
    macs: list[str] | None = None
    boot: BootSpec | None = None


class BindPair(BaseModel):
    """批量绑定清单项：mac + worker_id 必填；指纹比对列为可选申报值。"""
    mac: str
    worker_id: str
    manufacturer: str | None = None
    product: str | None = None
    serial: str | None = None
    uuid: str | None = None


class BatchBindRequest(BaseModel):
    """批量绑定请求：mode=manifest 用 pairs 清单配对；mode=sequential 用 macs/worker_ids 下标对齐顺序配对。"""
    mode: str = "manifest"
    pairs: list[BindPair] | None = None
    macs: list[str] | None = None
    worker_ids: list[str] | None = None


class UpdateWorkerMacRequest(BaseModel):
    """修改 Worker 的 MAC 绑定（hostname 不变）：更新 dnsmasq/dhcp-hosts.conf 中该 hostname 的绑定。"""
    mac: str


class CreateWorkerDiskRequest(BaseModel):
    """给指定 Worker 创建系统盘 LUN（母盘克隆或空白盘）。os 为该盘对应的系统，决定 IQN 后缀与文件名。"""
    type: Literal["master", "empty"]
    os: str
    name: str | None = None
    size: str | None = None
    disk_agent: str | None = None


class AgentRoleRequest(BaseModel):
    """Agent 角色：disk=可建系统盘（存储节点），cd=可挂载 ISO（光驱节点）。"""
    disk: bool = False
    cd: bool = False


class ProbeAgentRequest(BaseModel):
    """探测 Agent 并自动推导注册参数（预览，不写任何文件）。
    agent_id 可选：编辑场景 token 留空时，使用注册表中该 Agent 的 token 探测。"""
    base_url: str
    token: str = ""
    agent_id: str | None = None


class CreateAgentRequest(BaseModel):
    """注册新 Agent 到 agents.yml。token 支持 ${ENV} 占位（Control Plane 读取时展开）；
    tags 自由标签（如 storage/lio/stgt），仅作展示。"""
    id: str
    base_url: str
    token: str = ""
    iscsi_server: str | None = None
    role: AgentRoleRequest = Field(default_factory=AgentRoleRequest)
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True


class UpdateAgentRequest(BaseModel):
    """更新已有 Agent 的配置（id 不可改，走路径参数）。
    token 传空字符串 = 保持原值（API 不回显 token，前端无法回填）。"""
    base_url: str
    token: str = ""
    iscsi_server: str | None = None
    role: AgentRoleRequest = Field(default_factory=AgentRoleRequest)
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True


class BatchDiskTarget(BaseModel):
    """批量创建时单个 Worker 的存储节点分配（agent 必填：前端接管/拖拽产生）。"""
    worker_id: str
    agent: str


class BatchDeleteWorkersRequest(BaseModel):
    """批量删除 Worker：移除 dnsmasq 绑定与系统盘 target。
    delete_disk=true 时连系统盘 .img 一并删除；ignore_missing_target=true 容忍 target 已缺失。"""
    worker_ids: list[str]
    delete_disk: bool = False
    ignore_missing_target: bool = False


class BatchCreateWorkerDiskRequest(BaseModel):
    """批量创建系统盘：同一套盘参数应用到 targets 指定的多个 Worker，
    每个 Worker 使用各自分配的存储节点（agent）。同一 os 至多一块，重复自动跳过。"""
    type: Literal["master", "empty"]
    os: str
    name: str | None = None
    size: str | None = None
    targets: list[BatchDiskTarget]


class SetWorkerDefaultBootRequest(BaseModel):
    """设置 Worker 默认启动配置。os=默认系统（须与已挂系统盘一致）；
    menu_default/menu_timeout=菜单项覆盖；传 null 清除对应项。推导链：default_os > boot.menu_default > reboot。"""
    os: str | None = None
    menu_default: str | None = None
    menu_timeout: int | None = None


class SetAutoRegisterRequest(BaseModel):
    """运行时切换全局自动注册开关。enabled=false 后新 MAC 不再自动注册为 Worker。
    持久化到 state/settings.json，优先于环境变量 IPXE_CP_AUTO_REGISTER（后者为启动默认）。"""
    enabled: bool


class CreateDiskLunRequest(BaseModel):
    """在指定 Agent 上创建磁盘 LUN（母盘克隆或空白盘）。"""
    iqn: str
    filename: str | None = None
    master: str | None = None
    size: str | None = None


class CreateCdLunRequest(BaseModel):
    """在指定 Agent 上创建 CD（ISO 虚拟光驱）LUN，仅 stgt 后端支持。"""
    iso: str
    iqn: str | None = None


class CreateDeviceRequest(BaseModel):
    """手动注册设备：MAC（+可选 SMBIOS UUID）入设备池。
    型号/序列号等申报信息仅作台账初始值，设备上报后以申报值为准更新（申报性质，不用于认证）。"""
    mac: str
    uuid: str | None = None
    manufacturer: str | None = None
    product: str | None = None
    serial: str | None = None


class ImportDeviceEntry(BaseModel):
    """批量导入清单单行：mac 必填；uuid/型号/序列号为可选台账信息（比对列）。"""
    mac: str
    uuid: str | None = None
    manufacturer: str | None = None
    product: str | None = None
    serial: str | None = None


class ImportDevicesRequest(BaseModel):
    """批量导入设备清单（MAC 清单预导入）：逐项独立，重复跳过，非法/吊销计 failed。"""
    entries: list[ImportDeviceEntry]
