"""组件 PKI 引导/轮换接口（K8S CSR API 同构，2026-08-31）。

- POST /enroll：组件首次注册。凭据 = 一次性 bootstrap token（Bearer 头，经 nginx
  TLS 传输）；校验 token 绑定身份与 CSR CN 一致后，用内部 CA 签发 client + serving 证书。
- POST /renew：证书轮换。凭据 = 组件现有 client cert（nginx 该路径强制 mTLS 校验，
  通过后把客户端证书 DN 透传到 X-Client-Cert-DN）；CN 必须在册（agents.yml 存在）
  且与请求 agent_id/component 匹配后重签。

两个接口都不挂 verify_control_token（那是 webui 的鉴权；组件凭据是证书/token 本身）。
"""

import logging

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from .. import config, pki, stores
from ..auth import settings

log = logging.getLogger("control-plane")

router = APIRouter(prefix="/enroll", tags=["enroll"])


class EnrollReq(BaseModel):
    agent_id: str
    component: str  # agent | nvmet-host
    csr_client: str  # PEM，CN = <prefix>-<agent_id>
    csr_serving: str  # PEM，CN 同上；签发 serving cert 用
    serving_sans: list[str] = []
    base_url: str = ""  # 控制面可达地址；agent 首次引导时上报，自动登记写入
    capabilities: dict = {}  # agent 上报自身能力（backend/cd），自动登记推导角色/标签；旧 agent 可缺省


def _issue(agent_id: str, component: str, req: EnrollReq) -> dict:
    """校验在册（agent 组件自动登记）+ 签发，返回 {certificates, ca_crt}。"""
    try:
        stores.agents.get(agent_id)  # agents.yml 在册校验（两类组件共用）
    except KeyError:
        if component != "agent":
            # nvmet-host 与 agent 共享 agent_id：须 agent 组件先行在册（部署序
            # 保证 agent 先引导；nvmet-host 容器 restart 重试即可）
            raise HTTPException(400, f"agent not registered: {agent_id}") from None
        # 自动登记（kubelet 首次上报自动注册 Node 同构）：默认 disk 角色，
        # base_url 由 agent 引导时上报（KURRENT_ADVERTISE_URL），加入后可改；
        # 能力标签（K8S --node-labels 同构）：agent 上报 backend → tags=[auto,storage,backend]，
        # cd 能力 → role.cd；旧 agent 不上报时兼容默认（仅 auto 标签、无 cd 角色）
        base_url = req.base_url.strip().rstrip("/")
        if base_url and not base_url.startswith(("http://", "https://")):
            raise HTTPException(400, "base_url must start with http:// or https://")
        backend = str(req.capabilities.get("backend") or "").strip()
        tags = ("auto", "storage", backend) if backend else ("auto",)
        with stores.store.locked():
            stores.agents.add(agent_id, base_url, role_disk=True,
                              role_cd=bool(req.capabilities.get("cd")),
                              enabled=True, tags=tags)
        log.info("enroll: auto-registered agent %s (base_url=%s, backend=%s)",
                 agent_id, base_url, backend or "-")

    ca_cert, ca_key = pki.ensure_ca(config.settings.pki_dir)
    try:
        certs = pki.sign_component_certs(
            ca_cert, ca_key, agent_id, component,
            req.csr_client.encode(), req.csr_serving.encode(), req.serving_sans,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "certificates": {name: pem.decode() for name, pem in certs.items()},
        "ca_crt": pki.ca_cert_pem(config.settings.pki_dir).decode(),
    }


@router.post("", status_code=201)
def enroll(req: EnrollReq, request: Request, authorization: str = Header("", alias="Authorization")):
    """首次引导：Bearer bootstrap token → 校验 → 签发。token 用后即废。"""
    token = authorization[len("Bearer "):].strip() if authorization.startswith("Bearer ") else ""
    # nvmet-host 与 agent 共享 agent_id：agent 未在册时先拒绝（不消耗 token），
    # 部署序保证 agent 先引导；nvmet-host 容器 restart 重试即可，token 不会被烧掉
    if req.component != "agent":
        try:
            stores.agents.get(req.agent_id)
        except KeyError:
            raise HTTPException(400, f"agent not registered: {req.agent_id}") from None
    try:
        pki.consume_bootstrap_token(config.settings.pki_dir, token, req.agent_id, req.component)
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc
    return _issue(req.agent_id, req.component, req)


@router.post("/renew")
def renew(req: EnrollReq, x_client_cert_dn: str = Header("", alias=config.CLIENT_CERT_DN_HEADER)):
    """证书轮换：nginx mTLS 校验 client cert 后透传 DN；CN 在册且匹配才重签。"""
    cn = pki.parse_dn_cn(x_client_cert_dn)
    prefix = pki.COMPONENT_PREFIX.get(req.component)
    if not prefix or cn != f"{prefix}-{req.agent_id}":
        raise HTTPException(401, f"client cert cn mismatch: {cn!r}")
    return _issue(req.agent_id, req.component, req)
