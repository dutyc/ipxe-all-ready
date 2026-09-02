"""enroll 自动登记 / bootstrap-token 签发 / agent 删除（一键加入链路，2026-08-31）。

K8S 同构：kubelet 首次上报自动注册 Node（enroll 自动登记）+ kubeadm token create
（集群级通用 bootstrap token，不绑节点、TTL 内可复用）+ kubectl delete node。
nvmet-host 组件凭据：agent enroll 上报 backend=nvmet 时控制面派生随响应下发。
"""

import re

import pytest

from control_plane.app import pki as pki_mod
from control_plane.app.config import settings
from control_plane.app.stores import agents

_FAKE_CERTS = {"client.crt": b"FAKE-CLIENT", "serving.crt": b"FAKE-SERVING"}


@pytest.fixture()
def tmp_pki(tmp_path):
    """隔离 pki_dir：不触碰真实 state/pki（enroll/token 相关操作全部落临时目录）。"""
    old = settings.pki_dir
    object.__setattr__(settings, "pki_dir", tmp_path)
    try:
        yield tmp_path
    finally:
        object.__setattr__(settings, "pki_dir", old)


def _mock_issue(monkeypatch):
    """mock 证书签发链路（不生成真实 CA/证书）。"""
    monkeypatch.setattr(pki_mod, "ensure_ca", lambda d: (object(), object()))
    monkeypatch.setattr(pki_mod, "sign_component_certs", lambda *a, **k: dict(_FAKE_CERTS))
    monkeypatch.setattr(pki_mod, "ca_cert_pem", lambda d: b"FAKE-CA")


def _enroll(client, token, agent_id, component, base_url="", capabilities=None):
    body = {
        "agent_id": agent_id, "component": component,
        "csr_client": "FAKE", "csr_serving": "FAKE",
        "serving_sans": ["127.0.0.1"], "base_url": base_url,
    }
    if capabilities is not None:
        body["capabilities"] = capabilities
    return client.post("/enroll", json=body, headers={"Authorization": f"Bearer {token}"})


class TestEnrollAutoRegister:
    def test_agent_auto_registered(self, client, tmp_pki, monkeypatch):
        """不在册 agent 用通用 token 引导 → 201 + agents.yml 自动登记（base_url 上报）。"""
        _mock_issue(monkeypatch)
        token = pki_mod.issue_bootstrap_token(tmp_pki)  # 集群级通用：不绑节点
        resp = _enroll(client, token, "auto-01", "agent", "https://192.168.1.50:4840")
        assert resp.status_code == 201
        assert resp.json()["certificates"] == {k: v.decode() for k, v in _FAKE_CERTS.items()}
        a = agents.get("auto-01")
        assert a.base_url == "https://192.168.1.50:4840"
        assert a.role_disk and not a.role_cd and a.enabled

    def test_auto_registered_without_base_url(self, client, tmp_pki, monkeypatch):
        """无 base_url 也自动登记（空地址，控制面不探测，WebUI/CLI 可补）。"""
        _mock_issue(monkeypatch)
        token = pki_mod.issue_bootstrap_token(tmp_pki)
        resp = _enroll(client, token, "auto-02", "agent")
        assert resp.status_code == 201
        assert agents.get("auto-02").base_url == ""

    def test_generic_token_reusable_across_nodes(self, client, tmp_pki, monkeypatch):
        """通用 token TTL 内可被多次 enroll 复用（kubeadm bootstrap token 不限制次数）。

        同一 token 引导第二个节点（不同 agent_id）→ 同样 201，token 不消耗。
        """
        _mock_issue(monkeypatch)
        token = pki_mod.issue_bootstrap_token(tmp_pki)
        assert _enroll(client, token, "node-a", "agent").status_code == 201
        assert _enroll(client, token, "node-b", "agent").status_code == 201
        assert agents.get("node-a") and agents.get("node-b")

    def test_nvmet_derives_component_token(self, client, tmp_pki, monkeypatch):
        """agent 上报 backend=nvmet → 响应携带派生 nvmet-host token（绑 agent_id）。

        派生 token 供 nvmet-host 容器引导：该 agent 用派生 token enroll 组件成功；
        换 agent_id 使用 → 401（防串用）。
        """
        _mock_issue(monkeypatch)
        token = pki_mod.issue_bootstrap_token(tmp_pki)
        resp = _enroll(client, token, "auto-07", "agent", "https://192.168.1.50:4840",
                       capabilities={"backend": "nvmet", "cd": False})
        assert resp.status_code == 201
        a = agents.get("auto-07")
        assert a.tags == ("auto", "storage", "nvmet")
        assert a.role_disk and not a.role_cd
        nvmet_token = resp.json().get("nvmet_token")
        assert nvmet_token and re.fullmatch(r"[0-9a-f]{6}\.[0-9a-f]{16}", nvmet_token)
        # 派生 token 引导 nvmet-host（agent 已登记）→ 201
        assert _enroll(client, nvmet_token, "auto-07", "nvmet-host").status_code == 201
        # 派生 token 绑 agent_id：换 id 使用 → 401（对方 agent 在册时才走到 token 校验）
        assert _enroll(client, pki_mod.issue_bootstrap_token(tmp_pki), "other-node", "agent").status_code == 201
        assert _enroll(client, nvmet_token, "other-node", "nvmet-host").status_code == 401

    def test_stgt_no_derivation(self, client, tmp_pki, monkeypatch):
        """stgt 后端（无 nvmet-host 组件）→ 响应不含 nvmet_token。"""
        _mock_issue(monkeypatch)
        token = pki_mod.issue_bootstrap_token(tmp_pki)
        resp = _enroll(client, token, "auto-08", "agent", "https://192.168.1.51:4840",
                       capabilities={"backend": "stgt", "cd": True})
        assert resp.status_code == 201
        assert "nvmet_token" not in resp.json()
        a = agents.get("auto-08")
        assert a.tags == ("auto", "storage", "stgt")
        assert a.role_disk and a.role_cd

    def test_auto_registered_without_capabilities_backward_compat(self, client, tmp_pki, monkeypatch):
        """旧 agent 不上报能力 → 兼容默认（仅 auto 标签、无 cd 角色、不派生）。"""
        _mock_issue(monkeypatch)
        token = pki_mod.issue_bootstrap_token(tmp_pki)
        resp = _enroll(client, token, "auto-09", "agent")
        assert resp.status_code == 201
        assert "nvmet_token" not in resp.json()
        a = agents.get("auto-09")
        assert a.tags == ("auto",)
        assert a.role_disk and not a.role_cd

    def test_invalid_base_url_rejected(self, client, tmp_pki, monkeypatch):
        """上报地址格式非法 → 400（不自动登记）。"""
        _mock_issue(monkeypatch)
        token = pki_mod.issue_bootstrap_token(tmp_pki)
        resp = _enroll(client, token, "auto-03", "agent", "not-a-url")
        assert resp.status_code == 400
        with pytest.raises(KeyError):
            agents.get("auto-03")

    def test_nvmet_not_auto_registered(self, client, tmp_pki, monkeypatch):
        """nvmet-host 不在册不自动登记（共享 agent_id，须 agent 组件先行在册）。"""
        _mock_issue(monkeypatch)
        token = pki_mod.issue_bootstrap_token(tmp_pki, "auto-04", "nvmet-host")
        resp = _enroll(client, token, "auto-04", "nvmet-host")
        assert resp.status_code == 400
        assert "not registered" in resp.json()["detail"]
        with pytest.raises(KeyError):
            agents.get("auto-04")

    def test_nvmet_token_not_burned_when_agent_missing(self, client, tmp_pki, monkeypatch):
        """nvmet-host 在 agent 未在册时 400 且 token 不消耗：agent 登记后重试仍成功。

        （token 校验本就 TTL 复用不消耗——400 先于 token 校验，重试语义天然成立）
        """
        _mock_issue(monkeypatch)
        nvmet_tok = pki_mod.issue_bootstrap_token(tmp_pki, "auto-06", "nvmet-host")
        assert _enroll(client, nvmet_tok, "auto-06", "nvmet-host").status_code == 400
        # agent 组件登记后，用同一 nvmet token 重试 → 201（token 未被消耗）
        agent_tok = pki_mod.issue_bootstrap_token(tmp_pki)
        assert _enroll(client, agent_tok, "auto-06", "agent").status_code == 201
        assert _enroll(client, nvmet_tok, "auto-06", "nvmet-host").status_code == 201


class TestTokenEndpoint:
    """POST /pki/tokens：集群级通用 bootstrap token 签发（kubeadm token create 同构）。"""

    def test_issue(self, client, tmp_pki, auth_headers):
        """签发成功：token 格式 <6位>.<16位>，明文仅本次可见；响应无节点绑定字段。"""
        resp = client.post("/pki/tokens", headers=auth_headers)
        assert resp.status_code == 201
        body = resp.json()
        assert re.fullmatch(r"[0-9a-f]{6}\.[0-9a-f]{16}", body["token"])
        assert body["expires_at"]
        assert body["usage"] == ["enroll"]
        assert "agent_id" not in body and "component" not in body

    def test_each_issue_is_new(self, client, tmp_pki, auth_headers):
        """每次签发都是新 token（kubeadm token create 每次新签；多 token 并存，TTL 复用）。"""
        first = client.post("/pki/tokens", headers=auth_headers).json()["token"]
        second = client.post("/pki/tokens", headers=auth_headers).json()["token"]
        assert first != second

    def test_requires_bearer(self, client, tmp_pki):
        resp = client.post("/pki/tokens")
        assert resp.status_code == 401

    def test_token_validate_rejects_unknown(self, client, tmp_pki, monkeypatch):
        """校验：未登记 token / 过期 token → 401（enroll 链路）。"""
        _mock_issue(monkeypatch)
        resp = _enroll(client, "deadbe.0123456789abcdef", "auto-x", "agent")
        assert resp.status_code == 401


class TestEnrollDualComponent:
    def test_agent_and_nvmet_enroll_independent(self, client, tmp_pki, monkeypatch):
        """agent 通用 token + nvmet 派生 token（绑 agent_id）：各自引导互不影响。"""
        _mock_issue(monkeypatch)
        agent_tok = pki_mod.issue_bootstrap_token(tmp_pki)
        nvmet_tok = pki_mod.issue_bootstrap_token(tmp_pki, "auto-05", "nvmet-host")
        assert agent_tok and nvmet_tok
        assert _enroll(client, agent_tok, "auto-05", "agent").status_code == 201
        # agent 在册后，nvmet 组件用自己 token 引导（agent 通用 token 不消耗不影响）
        resp = _enroll(client, nvmet_tok, "auto-05", "nvmet-host")
        assert resp.status_code == 201


class TestDeleteAgent:
    def test_delete(self, client, auth_headers):
        client.post("/agents", json={"id": "del-01", "base_url": "https://127.0.0.1:4840",
                                     "role": {"disk": True, "cd": False}}, headers=auth_headers)
        resp = client.delete("/agents/del-01", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["deleted"] == "del-01"
        assert client.get("/agents?live=false", headers=auth_headers).json() == []

    def test_missing_404(self, client, auth_headers):
        resp = client.delete("/agents/nope", headers=auth_headers)
        assert resp.status_code == 404
