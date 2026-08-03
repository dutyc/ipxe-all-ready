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
                    iscsi_server=raw.get("iscsi_server") or raw.get("iscsi_host"),
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
        iscsi_server: str | None = None,
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
            "iscsi_server": iscsi_server or "",
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
            if "base_iqn" not in caps:
                errors.append(f"{agent.id}: capabilities missing base_iqn")
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

    def iscsi_server_for(self, agent_id: str) -> str:
        agent = self.get(agent_id)
        if agent.iscsi_server:
            return agent.iscsi_server
        parsed = urlparse(agent.base_url)
        return parsed.hostname or agent.base_url.removeprefix("http://").removeprefix("https://").split(":", 1)[0]


def _expand_env(value: str) -> str:
    return os.path.expandvars(value)
