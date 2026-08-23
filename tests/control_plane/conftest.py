"""控制面单测夹具：TestClient + 每用例状态隔离 + ECDSA 测试密钥与高层场景。"""

import base64
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

from control_plane.app import trust as trust_mod
from control_plane.app.config import settings
from control_plane.app.main import app

TEST_TOKEN = "test-control-token"

# 常用测试 MAC（规范冒号格式）
MAC_A = "00:11:22:33:44:55"
MAC_B = "00:11:22:33:44:66"
MAC_C = "00:11:22:33:44:77"
MAC_D = "00:11:22:33:44:88"


@pytest.fixture()
def client():
    """TestClient：每个用例前清空全部状态文件 + 挑战 nonce 存储，保证用例互不污染。"""
    for f in (
        settings.agents_file,
        settings.workers_file,
        settings.devices_file,
        settings.operations_file,
        settings.settings_file,
        settings.dnsmasq_hosts_file,
        settings.credentials_file,
    ):
        f.unlink(missing_ok=True)
    trust_mod._nonce_store.clear()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_headers():
    """控制面 API Bearer 鉴权头（与 tests/conftest.py 的 KURRENT_CP_TOKEN 一致）。"""
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture()
def ec_keypair():
    """ECDSA P-256 测试密钥对：pubkey_hex（未压缩点 130 hex 契约）+ sign(mac, hostname, nonce)。

    签名数据 = nonce||mac||hostname（UTF-8 字节拼接），输出 base64(DER)，与控制面验签契约一致。
    """
    priv = ec.generate_private_key(ec.SECP256R1())
    pubkey_hex = priv.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint).hex()

    def sign(mac: str, hostname: str, nonce: str) -> str:
        data = f"{nonce}{mac}{hostname}".encode("utf-8")
        return base64.b64encode(priv.sign(data, ec.ECDSA(hashes.SHA256()))).decode()

    return {"pubkey_hex": pubkey_hex, "sign": sign}


@pytest.fixture()
def register_claimed_device(client, auth_headers, ec_keypair):
    """高层场景：开注册窗口 → report 上报（带测试公钥）→ 设备认领入池。

    返回 (mac, device_record)，device_record 含 key_hash/pubkey_hash（认领后）。
    """
    def _register(mac: str) -> dict:
        res = client.post("/settings/registration-window", json={"ttl_minutes": 30}, headers=auth_headers)
        assert res.status_code == 201
        res = client.get("/devices/report", params={"mac": mac, "pubkey": ec_keypair["pubkey_hex"]})
        assert res.status_code == 200
        dev = client.get(f"/devices/{mac}", headers=auth_headers)
        assert dev.status_code == 200
        assert dev.json()["state"] == "pooled"
        assert dev.json()["key_hash"] == ec_keypair["pubkey_hex"]
        return dev.json()
    return _register


@pytest.fixture()
def mock_agent_client(monkeypatch):
    """外置 Agent 客户端：patch AgentRegistry.client → 内存 fake client。

    用例内先 POST /agents 注册（role.disk=true）即可走完整建盘/删盘/选择链路
    （select_disk_agent 内部 healthz/capabilities 同样命中 fake）。
    """
    from control_plane.app.stores import agents

    fake = SimpleNamespace(
        healthz=lambda: {"status": "ok"},
        capabilities=lambda: {"base_nqn": "nqn.2026-07.com.test", "cd": False, "backend": "stgt"},
        create_disk=lambda iqn, filename, **kw: {"iqn": iqn, "backing": f"/srv/iscsi/{filename}"},
        create_cd=lambda iso, iqn: {"iqn": iqn, "backing": iso},
        delete_lun=lambda iqn, delete_file=False: {"deleted": iqn},
        list_luns=lambda: [],
        list_masters=lambda: {"masters": []},
        scan=lambda: {"created": [], "skipped": []},
        set_credential=lambda worker_id, secret, sub_nqns, host_nqns: {"worker_id": worker_id, "secret": bool(secret)},
    )
    monkeypatch.setattr(agents, "client", lambda agent: fake)
    return fake
