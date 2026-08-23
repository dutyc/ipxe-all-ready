"""Agent 管理端点（Bearer 鉴权）：注册/更新/探测、LUN 管理、母盘聚合（/masters）。"""

from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..agent_client import AgentAPIError, AgentClient, AgentConfig
from ..auth import verify_control_token
from ..models import CreateAgentRequest, CreateCdLunRequest, CreateDiskLunRequest, ProbeAgentRequest, UpdateAgentRequest
from ..stores import agents, record, store
from ..utils import WORKER_ID_RE, client_host

router = APIRouter(dependencies=[Depends(verify_control_token)])


@router.get("/agents")
def list_agents(live: bool = True):
    return agents.list_public(live=live)


@router.post("/agents", status_code=201)
def create_agent(req: CreateAgentRequest, request: Request):
    """注册新 Agent：写入 agents.yml（重复 id 返回 409）。
    base_url 须 http(s):// 开头；token 支持 ${ENV} 占位（读取时展开）；
    role 决定磁盘/光驱角色；storager_ip 为数据面地址（缺省用 base_url 主机名）。"""
    agent_id = req.id.strip().lower()
    if not WORKER_ID_RE.match(agent_id):  # Agent id 与 worker id 同一命名规则
        raise HTTPException(400, f"invalid agent id: {req.id}")
    base_url = req.base_url.strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(400, "base_url must start with http:// or https://")
    storager_ip = req.storager_ip.strip() if req.storager_ip else None
    try:
        agents.get(agent_id)
        raise HTTPException(409, f"agent already exists: {agent_id}")
    except KeyError:
        pass

    with store.locked():
        agents.add(
            agent_id,
            base_url,
            req.token.strip(),
            role_disk=req.role.disk,
            role_cd=req.role.cd,
            storager_ip=storager_ip,
            enabled=req.enabled,
            tags=tuple(t.strip() for t in req.tags if t.strip()),
        )
    record("agent.register", "ok", agent=agent_id, client=client_host(request))
    return agents.get(agent_id).public_dict()


@router.put("/agents/{agent_id}")
def update_agent(agent_id: str, req: UpdateAgentRequest, request: Request):
    """更新已有 Agent：覆盖 agents.yml 中对应条目（id 不可改，走路径参数）。
    token 传空字符串 = 保持原值（API 不回显 token）；enabled=false 停用（不再参与调度与存活探测）。"""
    agent_id = agent_id.strip().lower()
    base_url = req.base_url.strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(400, "base_url must start with http:// or https://")
    storager_ip = req.storager_ip.strip() if req.storager_ip else None
    try:
        agents.get(agent_id)
    except KeyError:
        raise HTTPException(404, f"agent not found: {agent_id}")

    with store.locked():
        agents.update(
            agent_id,
            base_url,
            req.token.strip() or None,
            role_disk=req.role.disk,
            role_cd=req.role.cd,
            storager_ip=storager_ip,
            enabled=req.enabled,
            tags=tuple(t.strip() for t in req.tags if t.strip()),
        )
    record("agent.update", "ok", agent=agent_id, client=client_host(request))
    return agents.get(agent_id).public_dict()


@router.post("/agents/probe")
def probe_agent(req: ProbeAgentRequest, request: Request):
    """探测 Agent：调 /healthz + /capabilities，自动推导注册参数预览（不写任何文件）。
    推导规则：role.disk 恒真（Agent 即存储节点）、role.cd 取 capabilities.cd；
    tags = [storage, backend]（lio/stgt，供 /boot-vars 连接符推导）；
    storager_ip 缺省回退 base_url 主机名。"""
    base_url = req.base_url.strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(400, "base_url must start with http:// or https://")

    # 编辑场景：token 留空时回退注册表中该 Agent 的 token（未知 id 则按空 token 探测）
    token = req.token.strip()
    if not token and req.agent_id:
        try:
            token = agents.get(req.agent_id.strip().lower()).token
        except KeyError:
            pass

    # 临时 AgentConfig 探测（不落盘，不进入注册表）
    probe_cfg = AgentConfig(
        id="_probe",
        base_url=base_url,
        token=token,
        role_disk=True,
        role_cd=False,
    )
    client = AgentClient(probe_cfg, agents.timeout)
    try:
        client.healthz()
    except Exception as exc:
        record("agent.probe", "failed", agent=base_url, client=client_host(request), error=str(exc))
        raise HTTPException(502, f"agent unreachable: {exc}") from exc
    try:
        caps = client.capabilities()
    except AgentAPIError as exc:
        record("agent.probe", "failed", agent=base_url, client=client_host(request), error=exc.detail)
        raise HTTPException(502, {"agent": base_url, "error": exc.detail}) from exc

    backend = str(caps.get("backend", "stgt")).lower()
    record("agent.probe", "ok", agent=base_url, client=client_host(request), backend=backend)
    return {
        "base_url": base_url,
        "role": {"disk": True, "cd": bool(caps.get("cd", False))},
        "tags": ["storage", backend],
        "storager_ip": urlparse(base_url).hostname or base_url,
        "enabled": True,
        "backend": backend,
        "fs_type": caps.get("fs_type", ""),
        "base_nqn": caps.get("base_nqn", ""),
        "clone": caps.get("clone", ""),
        "empty_disk": caps.get("empty_disk", ""),
        "persistent": caps.get("persistent", ""),
    }


@router.get("/agents/{agent_id}/luns")
def list_agent_luns(agent_id: str, request: Request):
    """列出指定 Agent 上的全部 iSCSI target/LUN。"""
    client = _agent_client_or_404(agent_id)
    try:
        result = client.list_luns()
    except AgentAPIError as exc:
        record("lun.list", "failed", agent=agent_id, client=client_host(request), error=exc.detail)
        raise HTTPException(exc.status_code, {"agent": exc.agent_id, "error": exc.detail}) from exc
    record("lun.list", "ok", agent=agent_id, client=client_host(request), count=len(result))
    return result


@router.post("/agents/{agent_id}/luns/disk", status_code=201)
def create_agent_disk_lun(agent_id: str, req: CreateDiskLunRequest, request: Request):
    """在指定 Agent 上创建磁盘 LUN：传 master 走母盘克隆，传 size 建空白盘。"""
    if not req.master and not req.size:
        raise HTTPException(400, "need master (clone) or size (empty disk)")
    agent = _agent_or_404(agent_id)
    if not agent.role_disk:
        raise HTTPException(400, f"agent {agent_id} not configured for disk role")
    client = agents.client(agent)
    try:
        result = client.create_disk(req.iqn, req.filename or "", master=req.master, size=req.size)
    except AgentAPIError as exc:
        record("lun.create_disk", "failed", agent=agent_id, client=client_host(request), iqn=req.iqn, error=exc.detail)
        raise HTTPException(exc.status_code, {"agent": exc.agent_id, "error": exc.detail}) from exc
    record("lun.create_disk", "ok", agent=agent_id, client=client_host(request),
           iqn=result.get("iqn", req.iqn), backing=result.get("backing"))
    return result


@router.post("/agents/{agent_id}/luns/cd", status_code=201)
def create_agent_cd_lun(agent_id: str, req: CreateCdLunRequest, request: Request):
    """在指定 Agent 上创建 CD（ISO 虚拟光驱）LUN，仅 stgt 后端支持。"""
    agent = _agent_or_404(agent_id)
    if not agent.role_cd:
        raise HTTPException(400, f"agent {agent_id} not configured for cd role (LIO backend does not support ISO)")
    client = agents.client(agent)
    try:
        result = client.create_cd(req.iso, req.iqn or "")
    except AgentAPIError as exc:
        record("lun.create_cd", "failed", agent=agent_id, client=client_host(request), iso=req.iso, error=exc.detail)
        raise HTTPException(exc.status_code, {"agent": exc.agent_id, "error": exc.detail}) from exc
    record("lun.create_cd", "ok", agent=agent_id, client=client_host(request),
           iqn=result.get("iqn", req.iqn), iso=req.iso)
    return result


@router.delete("/agents/{agent_id}/luns")
def delete_agent_lun(
    agent_id: str,
    request: Request,
    iqn: str = Query(..., description="IQN of the target to delete"),
    delete_file: bool = Query(False, description="Delete the backing .img/.iso file as well."),
    ignore_missing: bool = Query(False, description="Ignore 404 from Agent while deleting the target."),
):
    """删除指定 Agent 上的一个 LUN/target。"""
    client = _agent_client_or_404(agent_id)
    try:
        result = client.delete_lun(iqn, delete_file=delete_file)
    except AgentAPIError as exc:
        if ignore_missing and exc.status_code == 404:
            record("lun.delete", "ok", agent=agent_id, client=client_host(request), iqn=iqn,
                   delete_file=delete_file, ignored_missing=True)
            return {"deleted": iqn, "delete_file": delete_file, "ignored_missing": True}
        record("lun.delete", "failed", agent=agent_id, client=client_host(request), iqn=iqn,
               delete_file=delete_file, error=exc.detail)
        raise HTTPException(exc.status_code, {"agent": exc.agent_id, "error": exc.detail}) from exc
    record("lun.delete", "ok", agent=agent_id, client=client_host(request), iqn=iqn, delete_file=delete_file)
    return result


@router.post("/agents/{agent_id}/luns/scan")
def scan_agent_luns(agent_id: str, request: Request):
    """触发 Agent 扫描镜像目录，为缺失文件重建 target（文件即真相）。"""
    client = _agent_client_or_404(agent_id)
    try:
        result = client.scan()
    except AgentAPIError as exc:
        record("lun.scan", "failed", agent=agent_id, client=client_host(request), error=exc.detail)
        raise HTTPException(exc.status_code, {"agent": exc.agent_id, "error": exc.detail}) from exc
    record("lun.scan", "ok", agent=agent_id, client=client_host(request),
           created=len(result.get("created", [])), skipped=len(result.get("skipped", [])))
    return result


@router.get("/masters")
def list_masters(request: Request):
    """聚合列出全部启用磁盘角色 Agent 上的母盘（后台扫描缓存），供 WebUI 克隆选盘。
    单台 Agent 失败不阻塞整体：失败节点返回 error 字段；全部失败时整体 502。"""
    results: list[dict[str, Any]] = []
    total = failed = 0
    for agent in agents.load():
        if not (agent.enabled and agent.role_disk and agent.base_url):
            continue
        total += 1
        entry: dict[str, Any] = {
            "agent": agent.id,
            "storager_ip": agents.storager_ip_for(agent.id),
        }
        try:
            payload = agents.client(agent).list_masters()
        except AgentAPIError as exc:
            failed += 1
            record("master.list", "failed", agent=agent.id, client=client_host(request), error=exc.detail)
            entry["masters"] = []
            entry["error"] = exc.detail
            results.append(entry)
            continue
        masters = payload.get("masters", []) if isinstance(payload, dict) else []
        record("master.list", "ok", agent=agent.id, client=client_host(request), count=len(masters))
        entry["masters"] = masters
        results.append(entry)
    if total > 0 and failed == total:
        raise HTTPException(502, {"agents": results, "error": "all agents failed"})
    return {"agents": results}


def _agent_or_404(agent_id: str):
    try:
        return agents.get(agent_id)
    except KeyError:
        raise HTTPException(404, f"agent not found: {agent_id}") from None


def _agent_client_or_404(agent_id: str):
    return agents.client(_agent_or_404(agent_id))
