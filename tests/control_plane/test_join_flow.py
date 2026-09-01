"""enroll 自动登记 / bootstrap-token 签发 / agent 删除（一键加入链路，2026-08-31）。

K8S 同构：kubelet 首次上报自动注册 Node（enroll 自动登记）+ kubeadm token create
（bootstrap-token 签发端点）+ kubectl delete node（agent 台账删除）。
"""

import re

import pytest

from control_plane.app import pki as pki_mod
from control_plane.app.config import settings
from control_plane.app.stores import agents

_FAKE_CERTS = {"client.crt": b"FAKE-CLIENT", "serving.crt": b"FAKE-SERVING"}


@pytest.fixture()
def tmp_pki(tmp_path):
    """隔离 pki_dir：不触碰真实 state/pki（enroll/token 相关操作全部落临时目录）。
    settings 为 frozen dataclass，用 object.__setattr__ 绕过并恢复。"""
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
        """不在册 agent 引导 → 201 + agents.yml 自动登记（base_url 上报）。"""
        _mock_issue(monkeypatch)
        token = pki_mod.generate_bootstrap_token(tmp_pki, "auto-01", "agent")
        resp = _enroll(client, token, "auto-01", "agent", "https://192.168.1.50:4840")
        assert resp.status_code == 201
        assert resp.json()["certificates"] == {k: v.decode() for k, v in _FAKE_CERTS.items()}
        a = agents.get("auto-01")
        assert a.base_url == "https://192.168.1.50:4840"
        assert a.role_disk and not a.role_cd and a.enabled

    def test_auto_registered_without_base_url(self, client, tmp_pki, monkeypatch):
        """无 base_url 也自动登记（空地址，控制面不探测，WebUI/CLI 可补）。"""
        _mock_issue(monkeypatch)
        token = pki_mod.generate_bootstrap_token(tmp_pki, "auto-02", "agent")
        resp = _enroll(client, token, "auto-02", "agent")
        assert resp.status_code == 201
        assert agents.get("auto-02").base_url == ""

    def test_auto_registered_with_capabilities_nvmet(self, client, tmp_pki, monkeypatch):
        """agent 上报能力 → 自动登记推导标签（auto+storage+backend）与 cd 角色（K8S --node-labels 同构）。"""
        _mock_issue(monkeypatch)
        token = pki_mod.generate_bootstrap_token(tmp_pki, "auto-07", "agent")
        resp = _enroll(client, token, "auto-07", "agent", "https://192.168.1.50:4840",
                       capabilities={"backend": "nvmet", "cd": False})
        assert resp.status_code == 201
        a = agents.get("auto-07")
        assert a.tags == ("auto", "storage", "nvmet")
        assert a.role_disk and not a.role_cd

    def test_auto_registered_with_capabilities_stgt(self, client, tmp_pki, monkeypatch):
        """stgt 后端上报 cd=True → role.cd 推导为 True（支持 ISO 光驱）。"""
        _mock_issue(monkeypatch)
        token = pki_mod.generate_bootstrap_token(tmp_pki, "auto-08", "agent")
        resp = _enroll(client, token, "auto-08", "agent", "https://192.168.1.51:4840",
                       capabilities={"backend": "stgt", "cd": True})
        assert resp.status_code == 201
        a = agents.get("auto-08")
        assert a.tags == ("auto", "storage", "stgt")
        assert a.role_disk and a.role_cd

    def test_auto_registered_without_capabilities_backward_compat(self, client, tmp_pki, monkeypatch):
        """旧 agent 不上报能力 → 兼容默认（仅 auto 标签、无 cd 角色）。"""
        _mock_issue(monkeypatch)
        token = pki_mod.generate_bootstrap_token(tmp_pki, "auto-09", "agent")
        resp = _enroll(client, token, "auto-09", "agent")
        assert resp.status_code == 201
        a = agents.get("auto-09")
        assert a.tags == ("auto",)
        assert a.role_disk and not a.role_cd

    def test_invalid_base_url_rejected(self, client, tmp_pki, monkeypatch):
        """上报地址格式非法 → 400（不自动登记）。"""
        _mock_issue(monkeypatch)
        token = pki_mod.generate_bootstrap_token(tmp_pki, "auto-03", "agent")
        resp = _enroll(client, token, "auto-03", "agent", "not-a-url")
        assert resp.status_code == 400
        with pytest.raises(KeyError):
            agents.get("auto-03")

    def test_nvmet_not_auto_registered(self, client, tmp_pki, monkeypatch):
        """nvmet-host 不在册不自动登记（共享 agent_id，须 agent 组件先行在册）。"""
        _mock_issue(monkeypatch)
        token = pki_mod.generate_bootstrap_token(tmp_pki, "auto-04", "nvmet-host")
        resp = _enroll(client, token, "auto-04", "nvmet-host")
        assert resp.status_code == 400
        assert "not registered" in resp.json()["detail"]
        with pytest.raises(KeyError):
            agents.get("auto-04")

    def test_nvmet_token_not_burned_when_agent_missing(self, client, tmp_pki, monkeypatch):
        """nvmet-host 在 agent 未在册时 400 且不消耗 token：agent 登记后重试仍成功。

        回归：2026-09-01 曾先 consume 再校验在册，首次 400 即烧掉 token，
        restart 重试永远 401（与注释声称的「restart 重试即可」矛盾）。
        """
        _mock_issue(monkeypatch)
        nvmet_tok = pki_mod.generate_bootstrap_token(tmp_pki, "auto-06", "nvmet-host")
        assert _enroll(client, nvmet_tok, "auto-06", "nvmet-host").status_code == 400
        # agent 组件登记后，用同一 nvmet token 重试 → 201（token 未被消耗）
        agent_tok = pki_mod.generate_bootstrap_token(tmp_pki, "auto-06", "agent")
        assert _enroll(client, agent_tok, "auto-06", "agent").status_code == 201
        assert _enroll(client, nvmet_tok, "auto-06", "nvmet-host").status_code == 201


class TestBootstrapTokenEndpoint:
    def test_issue(self, client, tmp_pki, auth_headers):
        """签发成功：token 格式 <6位>.<16位>，明文仅本次可见。"""
        resp = client.post("/agents/tok-01/bootstrap-token", headers=auth_headers)
        assert resp.status_code == 201
        body = resp.json()
        assert re.fullmatch(r"[0-9a-f]{6}\.[0-9a-f]{16}", body["token"])
        assert body["agent_id"] == "tok-01"
        assert body["component"] == "agent"
        assert body["expires_at"]

    def test_idempotent_409(self, client, tmp_pki, auth_headers):
        """已有未用 token → 409（明文不可恢复，防重复签发）。"""
        assert client.post("/agents/tok-02/bootstrap-token", headers=auth_headers).status_code == 201
        resp = client.post("/agents/tok-02/bootstrap-token", headers=auth_headers)
        assert resp.status_code == 409

    def test_nvmet_component(self, client, tmp_pki, auth_headers):
        resp = client.post("/agents/tok-03/bootstrap-token?component=nvmet-host",
                           headers=auth_headers)
        assert resp.status_code == 201
        assert resp.json()["component"] == "nvmet-host"

    def test_invalid_component_422(self, client, tmp_pki, auth_headers):
        resp = client.post("/agents/tok-04/bootstrap-token?component=hacker",
                           headers=auth_headers)
        assert resp.status_code == 422

    def test_dual_component_isolated(self, client, tmp_pki, auth_headers):
        """同 agent 双组件各自独立：nvmet 签发不覆盖 agent token，agent 仍幂等 409。"""
        assert client.post("/agents/tok-06/bootstrap-token",
                           headers=auth_headers).status_code == 201
        resp = client.post("/agents/tok-06/bootstrap-token?component=nvmet-host",
                           headers=auth_headers)
        assert resp.status_code == 201
        assert resp.json()["component"] == "nvmet-host"
        # agent token 未被 nvmet 覆盖：重复签发仍 409
        assert client.post("/agents/tok-06/bootstrap-token",
                           headers=auth_headers).status_code == 409

    def test_requires_bearer(self, client, tmp_pki):
        resp = client.post("/agents/tok-05/bootstrap-token")
        assert resp.status_code == 401


class TestEnrollDualComponent:
    def test_agent_and_nvmet_enroll_independent(self, client, tmp_pki, monkeypatch):
        """双 token 同 agent：agent enroll 消耗后 nvmet token 不受影响（互不覆盖回归）。"""
        _mock_issue(monkeypatch)
        agent_tok = pki_mod.generate_bootstrap_token(tmp_pki, "auto-05", "agent")
        nvmet_tok = pki_mod.generate_bootstrap_token(tmp_pki, "auto-05", "nvmet-host")
        assert agent_tok and nvmet_tok  # 双 token 均签发成功，互不覆盖
        assert _enroll(client, agent_tok, "auto-05", "agent").status_code == 201
        # agent 在册后，nvmet 组件用自己 token 引导（agent token 已消耗不影响）
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
