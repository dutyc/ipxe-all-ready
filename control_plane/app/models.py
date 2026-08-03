from typing import Literal

from pydantic import BaseModel, Field


class BootSpec(BaseModel):
    menu_default: str | None = None
    menu_timeout: int | None = None


class CreateWorkerRequest(BaseModel):
    """注册 Worker 身份（hostname + MAC 绑定）。系统盘须另调 POST /workers/{id}/luns/disk。"""
    worker_id: str
    mac: str
    hostname: str | None = None
    arch: str | None = None
    windows_iso: str | None = None
    boot: BootSpec | None = None


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
    """探测 Agent 并自动推导注册参数（预览，不写任何文件）。"""
    base_url: str
    token: str = ""


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
    menu_default/menu_timeout=菜单项覆盖；传 null 清除对应项。推导链：default_os > boot.menu_default > exit。"""
    os: str | None = None
    menu_default: str | None = None
    menu_timeout: int | None = None


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
