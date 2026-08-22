"""设备登记链路（boot 域，不鉴权）：/devices/report 上报/注册/认领 + /devices/challenge 挑战。

契约要点（trust-root-blueprint §5.2 / §6.1）：
- 注册只在窗口期且须带有效 ECDSA P-256 公钥（130 hex 未压缩点）
- 存量设备窗口期内带公钥上报 = 密钥认领；密钥不一致拒绝覆盖
- 吊销设备不更新、不复活
"""

import hashlib

import pytest

MAC_A = "00:11:22:33:44:55"
MAC_B = "00:11:22:33:44:66"


def _pubkey_hash(pubkey_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(pubkey_hex)).hexdigest()


class TestDeviceReport:
    """/devices/report：宽松上报（空响应），窗口期注册/认领语义。"""

    def test_invalid_mac_ignored(self, client, auth_headers):
        res = client.get("/devices/report", params={"mac": "zzz-not-a-mac"})
        assert res.status_code == 200
        assert client.get("/devices", headers=auth_headers).json() == []

    def test_unknown_mac_outside_window_not_registered(self, client, auth_headers, ec_keypair):
        # 窗口未开 + 带公钥 → 不注册（200 空响应，不阻断引导）
        res = client.get("/devices/report", params={"mac": MAC_A, "pubkey": ec_keypair["pubkey_hex"]})
        assert res.status_code == 200
        assert client.get("/devices", headers=auth_headers).json() == []

    def test_unknown_mac_without_pubkey_not_registered(self, client, auth_headers):
        client.post("/settings/registration-window", json={"ttl_minutes": 30}, headers=auth_headers)
        res = client.get("/devices/report", params={"mac": MAC_A})
        assert res.status_code == 200
        assert client.get("/devices", headers=auth_headers).json() == []

    def test_register_in_window_with_pubkey(self, client, auth_headers, ec_keypair):
        client.post("/settings/registration-window", json={"ttl_minutes": 30}, headers=auth_headers)
        res = client.get("/devices/report", params={"mac": MAC_A, "pubkey": ec_keypair["pubkey_hex"]})
        assert res.status_code == 200
        dev = client.get(f"/devices/{MAC_A}", headers=auth_headers).json()
        assert dev["state"] == "pooled"
        assert dev["key_hash"] == ec_keypair["pubkey_hex"]
        assert dev["pubkey_hash"] == _pubkey_hash(ec_keypair["pubkey_hex"])
        assert dev["source"] == "ipxe"
        assert dev["bound_worker_id"] is None
        # 审计：注册记 device.register
        ops = client.get("/operations", headers=auth_headers).json()["entries"]
        assert any(e["op"] == "device.register" and e["status"] == "ok" and e.get("mac") == MAC_A for e in ops)

    def test_invalid_pubkey_not_registered(self, client, auth_headers):
        client.post("/settings/registration-window", json={"ttl_minutes": 30}, headers=auth_headers)
        for bad in ("abc", "00" * 65):  # 非 hex / 长度 130 但非法曲线点
            res = client.get("/devices/report", params={"mac": MAC_A, "pubkey": bad})
            assert res.status_code == 200
        assert client.get("/devices", headers=auth_headers).json() == []

    def test_claim_existing_device_in_window(self, client, auth_headers, ec_keypair):
        # 手动注册（无 key）→ 窗口期内带公钥上报 → 认领
        client.post("/devices", json={"mac": MAC_A}, headers=auth_headers)
        client.post("/settings/registration-window", json={"ttl_minutes": 30}, headers=auth_headers)
        res = client.get("/devices/report", params={"mac": MAC_A, "pubkey": ec_keypair["pubkey_hex"]})
        assert res.status_code == 200
        dev = client.get(f"/devices/{MAC_A}", headers=auth_headers).json()
        assert dev["key_hash"] == ec_keypair["pubkey_hex"]
        ops = client.get("/operations", headers=auth_headers).json()["entries"]
        assert any(e["op"] == "device.claim" and e["status"] == "ok" and e.get("mac") == MAC_A for e in ops)

    def test_key_mismatch_rejected(self, client, auth_headers, ec_keypair, register_claimed_device):
        register_claimed_device(MAC_A)
        # 另一把密钥 → 拒绝覆盖（key_hash 不变 + 审计 rejected）
        from cryptography.hazmat.primitives.asymmetric import ec as ecm
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        other = ecm.generate_private_key(ecm.SECP256R1())
        other_hex = other.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint).hex()
        client.post("/settings/registration-window", json={"ttl_minutes": 30}, headers=auth_headers)
        res = client.get("/devices/report", params={"mac": MAC_A, "pubkey": other_hex})
        assert res.status_code == 200
        dev = client.get(f"/devices/{MAC_A}", headers=auth_headers).json()
        assert dev["key_hash"] == ec_keypair["pubkey_hex"]
        ops = client.get("/operations", headers=auth_headers).json()["entries"]
        assert any(e["op"] == "device.claim" and e["status"] == "rejected"
                   and e.get("reason") == "key_mismatch" and e.get("mac") == MAC_A for e in ops)

    def test_revoked_device_not_updated_or_resurrected(self, client, auth_headers, ec_keypair):
        client.post("/devices", json={"mac": MAC_A}, headers=auth_headers)
        client.delete(f"/devices/{MAC_A}", headers=auth_headers)  # revoked
        client.post("/settings/registration-window", json={"ttl_minutes": 30}, headers=auth_headers)
        res = client.get("/devices/report", params={"mac": MAC_A, "pubkey": ec_keypair["pubkey_hex"],
                                                    "manufacturer": "Hacker Inc"})
        assert res.status_code == 200
        dev = client.get(f"/devices/{MAC_A}", headers=auth_headers).json()
        assert dev["state"] == "revoked"
        assert dev["key_hash"] is None  # 吊销不复活、不认领
        assert dev["fingerprint"].get("manufacturer") is None

    def test_report_updates_fingerprint(self, client, auth_headers):
        client.post("/devices", json={"mac": MAC_A, "manufacturer": "Dell"}, headers=auth_headers)
        res = client.get("/devices/report", params={"mac": MAC_A, "manufacturer": "Lenovo",
                                                    "serial": "SN-123", "mem-total": "0x1000"})
        assert res.status_code == 200
        dev = client.get(f"/devices/{MAC_A}", headers=auth_headers).json()
        assert dev["fingerprint"]["manufacturer"] == "Lenovo"
        assert dev["fingerprint"]["serial"] == "SN-123"
        assert dev["fingerprint"]["mem_total"] == 4096  # 0x1000 宽松解析
        assert dev["last_seen"] is not None

    def test_report_requires_no_token(self, client, auth_headers, ec_keypair):
        # boot 域不鉴权：无 Authorization 也能上报
        client.post("/settings/registration-window", json={"ttl_minutes": 30}, headers=auth_headers)
        res = client.get("/devices/report", params={"mac": MAC_A, "pubkey": ec_keypair["pubkey_hex"]})
        assert res.status_code == 200


class TestDeviceChallenge:
    """/devices/challenge：一次性 nonce 签发（绑定 mac、短 TTL）。"""

    def test_challenge_unregistered_404(self, client):
        res = client.get("/devices/challenge", params={"mac": MAC_A})
        assert res.status_code == 404

    def test_challenge_unclaimed_404(self, client, auth_headers):
        client.post("/devices", json={"mac": MAC_A}, headers=auth_headers)  # 无 key_hash
        res = client.get("/devices/challenge", params={"mac": MAC_A})
        assert res.status_code == 404

    def test_challenge_invalid_mac_400(self, client):
        res = client.get("/devices/challenge", params={"mac": "zzz"})
        assert res.status_code == 400

    def test_challenge_claimed_returns_nonce(self, client, auth_headers, register_claimed_device):
        register_claimed_device(MAC_A)
        res = client.get("/devices/challenge", params={"mac": MAC_A})
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/plain")
        # 响应为 #!ipxe 脚本体：set nonce <64hex>（iPXE chain 可直接消费）
        lines = res.text.strip().splitlines()
        assert lines[0] == "#!ipxe"
        assert len(lines) == 2 and lines[1].startswith("set nonce ")
        nonce = lines[1][len("set nonce "):]
        assert len(nonce) == 64
        assert int(nonce, 16) >= 0  # 64 hex 字符

    def test_challenge_no_token_required(self, client, auth_headers, register_claimed_device):
        register_claimed_device(MAC_A)
        assert client.get("/devices/challenge", params={"mac": MAC_A}).status_code == 200


class TestRegistrationWindowExpiry:
    """窗口 TTL 到期自动关闭（懒计算）。"""

    def test_expired_window_closed(self, client, auth_headers):
        import datetime as _dt

        client.post("/settings/registration-window", json={"ttl_minutes": 30}, headers=auth_headers)
        # 直接改写 settings.json：opened_at 改为 1 小时前 → TTL 已过
        from control_plane.app.stores import runtime_settings
        with runtime_settings.locked():
            runtime_settings.set("registration_window", {
                "opened_at": (_dt.datetime.now().astimezone() - _dt.timedelta(hours=1)).isoformat(),
                "ttl_minutes": 30,
            })
        body = client.get("/settings/registration-window", headers=auth_headers).json()
        assert body["open"] is False
        assert body["remaining_seconds"] == 0
        # 过期后 report 不再注册新设备
        res = client.get("/devices/report", params={"mac": MAC_B, "pubkey": "ab" * 65})
        assert res.status_code == 200
        assert client.get("/devices", headers=auth_headers).json() == []

    def test_expired_window_reopen_overwrites(self, client, auth_headers):
        import datetime as _dt

        from control_plane.app.stores import runtime_settings
        with runtime_settings.locked():
            runtime_settings.set("registration_window", {
                "opened_at": (_dt.datetime.now().astimezone() - _dt.timedelta(hours=1)).isoformat(),
                "ttl_minutes": 30,
            })
        res = client.post("/settings/registration-window", json={"ttl_minutes": 15}, headers=auth_headers)
        assert res.status_code == 201
        assert res.json()["open"] is True
        assert res.json()["ttl_minutes"] == 15
