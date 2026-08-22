"""控制面 API Bearer 鉴权（依赖注入用）。"""

import hmac

from fastapi import HTTPException, Request

from .config import settings


def verify_control_token(request: Request) -> None:
    if not settings.control_token:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "unauthorized")
    if not hmac.compare_digest(auth[len("Bearer "):].strip(), settings.control_token):
        raise HTTPException(401, "unauthorized")
