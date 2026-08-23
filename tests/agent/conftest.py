"""Agent（nvmet 后端）单测夹具：env 隔离 + 直接 import app.main。

storager/agent/app 注入 sys.path（顶层 app 包名与 control_plane.app / nvmet_host_main
均不冲突），KURRENT_* 环境变量在 import 前全量设置（main.py 顶层 _require_env）。
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_DIR = PROJECT_ROOT / "storager" / "agent"
sys.path.insert(0, str(AGENT_DIR))  # 注入 agent 目录：import app → agent/app 包

_STATE = Path(tempfile.mkdtemp(prefix="storager-agent-test-"))
os.environ["KURRENT_DISK_DIR"] = str(_STATE / "disks")
os.environ["KURRENT_NQN_BASE"] = "nqn.2026-07.com.test"
os.environ["KURRENT_BACKEND"] = "nvmet"
os.environ["KURRENT_AGENT_TOKEN"] = "test-agent-token"
os.environ["KURRENT_LOG_FILE"] = str(_STATE / "ops.jsonl")
os.environ["KURRENT_NVMET_HOST_URL"] = "http://127.0.0.1:4841"
os.environ["KURRENT_NVMET_HOST_TOKEN"] = "test-host-token"
os.environ["KURRENT_NVMET_CACHE_FILE"] = str(_STATE / "nvmet-credentials.json")

import app.main as agent_main  # noqa: E402


@pytest.fixture()
def fake_host():
    """内存 fake nvmet-host 客户端：记录调用序列，可注入 404/不可达。"""
    from app.nvmet import NvmetHostError

    class FakeHost:
        def __init__(self):
            self.calls: list = []
            self.subsystems: dict = {}
            self.unreachable = False

        def _check(self):
            if self.unreachable:
                raise NvmetHostError(0, "nvmet host unreachable: test")

        def healthz(self):
            self._check()
            return {"status": "ok", "configfs": True}

        def capabilities(self):
            self._check()
            return {"backend": "nvmet", "cd": False}

        def create_subsystem(self, nqn, backing):
            self._check()
            if nqn in self.subsystems:
                raise NvmetHostError(409, f"subsystem exists: {nqn}")
            self.calls.append(("create_subsystem", nqn, backing))
            self.subsystems[nqn] = backing

        def delete_subsystem(self, nqn):
            self._check()
            self.calls.append(("delete_subsystem", nqn))
            if nqn not in self.subsystems:
                raise NvmetHostError(404, f"subsystem not found: {nqn}")
            del self.subsystems[nqn]

        def list_subsystems(self):
            self._check()
            return [{"nqn": n, "namespaces": [{"nsid": 1, "device_path": b}], "hosts": []}
                    for n, b in self.subsystems.items()]

        def set_host(self, nqn, hostnqn, secret):
            self._check()
            if nqn not in self.subsystems:
                raise NvmetHostError(404, f"subsystem not found: {nqn}")
            self.calls.append(("set_host", nqn, hostnqn, secret))

        def delete_host(self, nqn, hostnqn):
            self._check()
            if nqn not in self.subsystems:
                raise NvmetHostError(404, f"subsystem not found: {nqn}")
            self.calls.append(("delete_host", nqn, hostnqn))

    host = FakeHost()
    return host, host.calls


@pytest.fixture()
def backend(fake_host, tmp_path):
    """NvmetBackend + NvmetCredentialCache（fake host + 独立缓存文件）。"""
    from app.nvmet import NvmetBackend, NvmetCredentialCache

    host, calls = fake_host
    disk_dir = tmp_path / "disks"
    disk_dir.mkdir()
    cache = NvmetCredentialCache(host, str(tmp_path / "creds.json"))
    return NvmetBackend(host, cache, str(disk_dir), "nqn.2026-07.com.test"), cache, calls


@pytest.fixture()
def agent_client(monkeypatch, fake_host, tmp_path):
    """Agent FastAPI 端点夹具：monkeypatch 全局 backend 为 nvmet 实例（不触发 lifespan）。"""
    from app.nvmet import NvmetBackend, NvmetCredentialCache
    from fastapi.testclient import TestClient

    host, calls = fake_host
    cache = NvmetCredentialCache(host, str(tmp_path / "agent-creds.json"))
    fake = NvmetBackend(host, cache, str(tmp_path / "disks"), "nqn.2026-07.com.test")
    monkeypatch.setattr(agent_main, "backend", fake)
    client = TestClient(agent_main.app)
    return client, fake, calls


@pytest.fixture()
def auth_headers():
    return {"Authorization": "Bearer test-agent-token"}
