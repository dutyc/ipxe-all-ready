import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .agent_client import AgentClient, AgentConfig


class AgentRegistry:
    def __init__(self, agents_file: Path, timeout: float):
        self.agents_file = agents_file
        self.timeout = timeout

    def load(self) -> list[AgentConfig]:
        self.agents_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.agents_file.exists():
            return []
        with self.agents_file.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        agents_data = data.get("agents", data)
        if not isinstance(agents_data, dict):
            raise ValueError(f"invalid agents file: {self.agents_file}")
        agents: list[AgentConfig] = []
        for agent_id, raw in agents_data.items():
            if not isinstance(raw, dict):
                continue
            role = raw.get("role") or {}
            agents.append(
                AgentConfig(
                    id=str(agent_id),
                    base_url=str(raw.get("base_url", "")).rstrip("/"),
                    token=_expand_env(str(raw.get("token", ""))),
                    role_disk=bool(role.get("disk", False)),
                    role_cd=bool(role.get("cd", False)),
                    storager_ip=raw.get("storager_ip") or None,
                    enabled=bool(raw.get("enabled", True)),
                    tags=tuple(raw.get("tags") or ()),
                )
            )
        return agents

    def get(self, agent_id: str) -> AgentConfig:
        for agent in self.load():
            if agent.id == agent_id:
                return agent
        raise KeyError(agent_id)

    def add(
        self,
        agent_id: str,
        base_url: str,
        token: str = "",
        *,
        role_disk: bool = False,
        role_cd: bool = False,
        storager_ip: str | None = None,
        enabled: bool = True,
        tags: tuple[str, ...] = (),
    ) -> None:
        """注册新 Agent：写入 agents.yml（重复 id 由调用方先行校验）。"""
        self.agents_file.parent.mkdir(parents=True, exist_ok=True)
        if self.agents_file.exists():
            with self.agents_file.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {}
        agents_data = data.get("agents")
        if not isinstance(agents_data, dict):
            agents_data = {}
            data["agents"] = agents_data
        agents_data[agent_id] = {
            "base_url": base_url,
            "token": token,
            "role": {"disk": role_disk, "cd": role_cd},
            "storager_ip": storager_ip or "",
            "tags": list(tags),
            "enabled": enabled,
        }
        with self.agents_file.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    def update(
        self,
        agent_id: str,
        base_url: str,
        token: str | None = None,
        *,
        role_disk: bool = False,
        role_cd: bool = False,
        storager_ip: str | None = None,
        enabled: bool = True,
        tags: tuple[str, ...] = (),
    ) -> None:
        """更新已有 Agent：覆盖 agents.yml 中对应条目（id 不可改，不存在抛 KeyError）。
        token 传 None / 空字符串时保持原值（API 不回显 token，前端无法回填）。"""
        with self.agents_file.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        agents_data = data.get("agents")
        entry = agents_data.get(agent_id) if isinstance(agents_data, dict) else None
        if not isinstance(entry, dict):
            raise KeyError(agent_id)
        agents_data[agent_id] = {
            "base_url": base_url,
            "token": token or entry.get("token", ""),
            "role": {"disk": role_disk, "cd": role_cd},
            "storager_ip": storager_ip or "",
            "tags": list(tags),
            "enabled": enabled,
        }
        with self.agents_file.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    def client(self, agent: AgentConfig) -> AgentClient:
        return AgentClient(agent, self.timeout)

    def select_disk_agent(self) -> tuple[AgentConfig, dict[str, Any]]:
        return self._select(lambda agent: agent.role_disk, require_cd=False)

    def select_cd_agent(self) -> tuple[AgentConfig, dict[str, Any]]:
        return self._select(lambda agent: agent.role_cd, require_cd=True)

    def _select(self, role_predicate, *, require_cd: bool) -> tuple[AgentConfig, dict[str, Any]]:
        errors: list[str] = []
        for agent in self.load():
            if not agent.enabled or not role_predicate(agent):
                continue
            if not agent.base_url:
                errors.append(f"{agent.id}: missing base_url")
                continue
            client = self.client(agent)
            try:
                client.healthz()
                caps = client.capabilities()
            except Exception as exc:
                errors.append(f"{agent.id}: {exc}")
                continue
            if require_cd and not caps.get("cd"):
                errors.append(f"{agent.id}: cd not supported by backend")
                continue
            if "base_nqn" not in caps:
                errors.append(f"{agent.id}: capabilities missing base_nqn")
                continue
            return agent, caps
        role = "cd" if require_cd else "disk"
        detail = "; ".join(errors) if errors else "no enabled agent configured"
        raise RuntimeError(f"no available {role} agent: {detail}")

    def list_public(self, live: bool = True) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for agent in self.load():
            item = agent.public_dict()
            if live and agent.enabled and agent.base_url:
                try:
                    client = self.client(agent)
                    client.healthz()
                    item["health"] = "ok"
                    item["capabilities"] = client.capabilities()
                except Exception as exc:
                    item["health"] = "error"
                    item["error"] = str(exc)
            result.append(item)
        return result

    def storager_ip_for(self, agent_id: str) -> str:
        """数据面地址：显式配置优先，缺省回退 base_url 主机名（boot-vars 投影时兜底）。"""
        agent = self.get(agent_id)
        if agent.storager_ip:
            return agent.storager_ip
        parsed = urlparse(agent.base_url)
        return parsed.hostname or agent.base_url.removeprefix("http://").removeprefix("https://").split(":", 1)[0]


def _expand_env(value: str) -> str:
    return os.path.expandvars(value)
