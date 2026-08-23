from dataclasses import dataclass
from typing import Any

import httpx


class AgentAPIError(Exception):
    def __init__(self, agent_id: str, status_code: int, detail: str):
        super().__init__(detail)
        self.agent_id = agent_id
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class AgentConfig:
    id: str
    base_url: str
    token: str
    role_disk: bool
    role_cd: bool
    storager_ip: str | None = None
    enabled: bool = True
    tags: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "base_url": self.base_url,
            "storager_ip": self.storager_ip,
            "role": {"disk": self.role_disk, "cd": self.role_cd},
            "enabled": self.enabled,
            "tags": list(self.tags),
        }


class AgentClient:
    def __init__(self, agent: AgentConfig, timeout: float):
        self.agent = agent
        self.timeout = timeout

    def healthz(self) -> dict[str, Any]:
        return self._request("GET", "/healthz", auth=False)

    def capabilities(self) -> dict[str, Any]:
        return self._request("GET", "/capabilities")

    def create_disk(self, iqn: str, filename: str, *, master: str | None = None, size: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"iqn": iqn, "filename": filename}
        if master:
            payload["master"] = master
        if size:
            payload["size"] = size
        return self._request("POST", "/lun/disk", json=payload)

    def create_cd(self, iso: str, iqn: str) -> dict[str, Any]:
        return self._request("POST", "/lun/cd", json={"iso": iso, "iqn": iqn})

    def delete_lun(self, iqn: str, delete_file: bool = False) -> dict[str, Any]:
        return self._request("DELETE", "/lun", params={"iqn": iqn, "delete_file": str(delete_file).lower()})

    def scan(self) -> dict[str, Any]:
        """触发 Agent 扫描镜像目录，为缺失文件重建 target。"""
        return self._request("POST", "/lun/scan")

    def list_luns(self) -> list[dict[str, Any]]:
        return self._request("GET", "/lun")

    def list_masters(self) -> dict[str, Any]:
        """列出 Agent 上可用母盘（后台扫描缓存的 *_tpl_* 文件清单）。"""
        return self._request("GET", "/masters")

    def set_credential(self, worker_id: str, secret: str | None, sub_nqns: list[str], host_nqns: list[str]) -> dict[str, Any]:
        """推送 NVMe-oF 凭据期望状态给 Agent（控制面驱动，Agent 转调宿主服务同步 hosts 矩阵）。
        secret=None 吊销该 worker；sub_nqns = 盘子系统 NQN，host_nqns = 绑定设备派生 NQN。"""
        return self._request("POST", "/credential", json={
            "worker_id": worker_id, "secret": secret,
            "sub_nqns": sub_nqns, "host_nqns": host_nqns,
        })

    def _request(self, method: str, path: str, *, auth: bool = True, **kwargs: Any) -> Any:
        headers = kwargs.pop("headers", {})
        if auth:
            headers["Authorization"] = f"Bearer {self.agent.token}"
        url = f"{self.agent.base_url.rstrip('/')}{path}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, url, headers=headers, **kwargs)
        except httpx.RequestError as exc:
            raise AgentAPIError(self.agent.id, 503, f"agent request failed: {exc}") from exc
        if response.status_code >= 400:
            raise AgentAPIError(self.agent.id, response.status_code, _response_detail(response))
        if not response.content:
            return None
        return response.json()


def _response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text
    if isinstance(payload, dict) and "detail" in payload:
        return str(payload["detail"])
    return str(payload)
