"""PkiClient 引导请求测试（一键加入链路，2026-08-31）：base_url 上报等 payload 契约。"""

import json

import pytest

from storager.agent.app import pki_client


class _FakeResp:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps({
            "certificates": {
                "client.crt": "FAKE-CLIENT",
                "serving.crt": "FAKE-SERVING",
            },
            "ca_crt": "FAKE-CA",
        }).encode()

    def close(self):
        pass


def _client(monkeypatch, pki_dir, captured, **kwargs):
    def fake_urlopen(req, *, context=None, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data)
        captured["auth"] = req.get_header("Authorization")
        return _FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    defaults = dict(agent_id="t-ag-1", component="agent", pki_dir=pki_dir,
                    cp_base="https://cp", cp_ca=None, bootstrap_token=None)
    defaults.update(kwargs)
    return pki_client.PkiClient(**defaults)


@pytest.fixture()
def captured():
    return {}


def test_enroll_payload_carries_advertise_url(monkeypatch, pki_dir, captured):
    """enroll 请求体携带 base_url（KURRENT_ADVERTISE_URL → 控制面自动登记）。"""
    c = _client(monkeypatch, pki_dir, captured,
                bootstrap_token="tok.123", advertise_url="https://192.168.1.50:4840")
    c._enroll(renew=False)
    assert captured["url"] == "https://cp/api/cp/enroll"
    assert captured["auth"] == "Bearer tok.123"
    assert captured["body"]["agent_id"] == "t-ag-1"
    assert captured["body"]["component"] == "agent"
    assert captured["body"]["base_url"] == "https://192.168.1.50:4840"
    assert "csr_client" in captured["body"] and "csr_serving" in captured["body"]


def test_renew_payload_without_bearer(monkeypatch, pki_dir, captured):
    """renew 不带 Bearer（凭据 = 现有 client cert，TLS 层 mTLS）。"""
    # renew 走 mTLS：tmp 隔离目录无真实证书，直接假掉 context（urlopen 已被接管）
    monkeypatch.setattr(pki_client.PkiClient, "_cp_context", lambda self, wcc: object())
    c = _client(monkeypatch, pki_dir, captured, bootstrap_token=None)
    c._enroll(renew=True)
    assert captured["url"] == "https://cp/api/cp/enroll/renew"
    assert captured["auth"] is None


def test_no_token_and_no_cert_raises(monkeypatch, pki_dir, captured):
    """无 bootstrap token 且无 client cert → 拒绝引导（阻断启动）。"""
    c = _client(monkeypatch, pki_dir, captured, bootstrap_token=None)
    with pytest.raises(RuntimeError, match="cannot enroll"):
        c._enroll(renew=False)
