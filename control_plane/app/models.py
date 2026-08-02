from typing import Literal

from pydantic import BaseModel


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
