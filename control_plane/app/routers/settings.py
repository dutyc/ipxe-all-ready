"""设置管理端点（Bearer 鉴权）：注册窗口开启/查询/关闭、设备身份验签强制开关。

窗口/开关状态逻辑在 trust 域（被 boot 验签链路共用），本模块仅 HTTP 壳。
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import verify_control_token
from ..config import REGISTRATION_WINDOW_TTL_MAX_MINUTES, REGISTRATION_WINDOW_TTL_MIN_MINUTES
from ..models import OpenRegistrationWindowRequest, SetEnforcementRequest
from ..stores import record, runtime_settings
from ..trust import enforcement_enabled, window_open, window_record, window_status
from ..utils import client_host, now_iso

router = APIRouter(dependencies=[Depends(verify_control_token)])


@router.get("/settings/registration-window")
def get_registration_window():
    """查询注册窗口状态：open / 开启时刻 / TTL / 关闭时刻 / 剩余秒数。
    TTL 到期自动关闭（懒计算，不主动清理）。未配置/已关闭 → open=false。"""
    return window_status()


@router.post("/settings/registration-window", status_code=201)
def open_registration_window(req: OpenRegistrationWindowRequest, request: Request):
    """开启注册窗口（部署期）：TTL 硬上限 60 分钟（代码层不可配永久），注册只在窗口期可发生。
    已开启 → 409（先关闭再开）；过期残留记录可直接重开（覆盖）。"""
    if not (REGISTRATION_WINDOW_TTL_MIN_MINUTES <= req.ttl_minutes <= REGISTRATION_WINDOW_TTL_MAX_MINUTES):
        raise HTTPException(
            400,
            f"ttl_minutes must be within {REGISTRATION_WINDOW_TTL_MIN_MINUTES}-"
            f"{REGISTRATION_WINDOW_TTL_MAX_MINUTES}",
        )
    with runtime_settings.locked():
        if window_open():
            raise HTTPException(409, "registration window already open")
        runtime_settings.set("registration_window", {"opened_at": now_iso(), "ttl_minutes": req.ttl_minutes})
    record("settings.registration_window", "open", ttl_minutes=req.ttl_minutes, client=client_host(request))
    return window_status()


@router.delete("/settings/registration-window")
def close_registration_window(request: Request):
    """提前关闭注册窗口：窗口期外注册被拒。从未开启/无记录 → 409。"""
    with runtime_settings.locked():
        if not window_record():
            raise HTTPException(409, "registration window is not open")
        runtime_settings.set("registration_window", None)
    record("settings.registration_window", "close", client=client_host(request))
    return {"open": False}


@router.get("/settings/enforcement")
def get_enforcement():
    """查询设备身份验签强制开关（过渡期兼容：关闭时无密钥设备照现状放行）。"""
    return {"enabled": enforcement_enabled()}


@router.put("/settings/enforcement")
def set_enforcement(req: SetEnforcementRequest, request: Request):
    """切换设备身份验签强制开关：开启后无 key_hash 设备 /boot-vars 直接拒绝下发
    （注入四条件第 4 条硬性，已绑定也不放行）；存量设备认领完成后由管理员开启。"""
    enabled = bool(runtime_settings.set("enforce_device_auth", req.enabled))
    record("settings.enforcement", "ok", enabled=enabled, client=client_host(request))
    return {"enabled": enabled}
