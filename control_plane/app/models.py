from typing import Literal

from pydantic import BaseModel


class DiskSpec(BaseModel):
    type: Literal["master", "empty"]
    name: str | None = None
    size: str | None = None


class BootSpec(BaseModel):
    menu_default: str | None = None
    menu_timeout: int | None = None


class CreateWorkerRequest(BaseModel):
    worker_id: str
    mac: str
    os: str
    disk: DiskSpec
    hostname: str | None = None
    arch: str | None = None
    windows_iso: str | None = None
    boot: BootSpec | None = None
