"""bootstrap token 签发端点（kubeadm token create 同构）：集群级通用引导凭据。

不带任何节点信息（kubeadm token create 不绑节点）：节点名由节点自决——kurrent join
缺省取宿主机名，enroll 自动登记（kubelet 首次上报自动注册 Node 同构）。
每次调用新签（明文不可恢复，登记只存 sha256 hash）；TTL 内可被多次 enroll 复用
（kubeadm bootstrap token 不限制使用次数），任意存储节点可用同一 token 引导。
nvmet-host 组件凭据不在此签发：agent enroll 上报 backend=nvmet 时控制面派生
随响应下发（能力上报驱动，签发不预知后端）。
"""

from fastapi import APIRouter, Depends, Request

from .. import config, pki
from ..auth import verify_control_token
from ..stores import record
from ..utils import client_host

router = APIRouter(dependencies=[Depends(verify_control_token)])


@router.post("/pki/tokens", status_code=201)
def issue_bootstrap_token(request: Request):
    """签发集群级通用 bootstrap token，返回明文（仅本次响应可见）。

    响应含 token / expires_at / usage；join 命令示例由 CLI 侧组装（kurrent token create）。
    """
    token = pki.issue_bootstrap_token(config.settings.pki_dir)
    token_id = token.split(".", 1)[0]
    info = pki.get_bootstrap_token(config.settings.pki_dir, token_id) or {}
    record("pki.bootstrap-token", "ok", client=client_host(request))
    return {
        "token": token,
        "expires_at": info.get("expires_at", ""),
        "usage": info.get("usage", []),
    }
