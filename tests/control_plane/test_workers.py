"""Worker 域（Bearer 鉴权）：CRUD / 批量 / MAC 换绑 / 系统盘（mock agent）/ 默认启动 / 删除。"""

import pytest

MAC_A = "00:11:22:33:44:55"
MAC_B = "00:11:22:33:44:66"
MAC_C = "00:11:22:33:44:77"


@pytest.fixture()
def register_agent(client, auth_headers, mock_agent_client):
    """注册磁盘角色 Agent（mock client 已就位，无网络）。"""
    res = client.post("/agents", json={
        "id": "ag-01", "base_url": "http://ag-01:8000", "token": "test-token",
        "role": {"disk": True, "cd": False}, "tags": ["storage", "stgt"],
    }, headers=auth_headers)
    assert res.status_code == 201, res.text
    return res.json()


class TestWorkerCreate:
    """Worker 创建：空转 / 带 mac 绑定 / 冲突校验。"""

    def test_create_idle_worker(self, client, auth_headers):
        res = client.post("/workers", json={"worker_id": "worker-01"}, headers=auth_headers)
        assert res.status_code == 201
        body = res.json()
        assert body["hostname"] == "worker-01"  # hostname 缺省 = worker_id
        assert body["state"] == "registered"
        assert body["mac"] is None
        assert body["bound_device"] is None
        assert body["readiness"] == "idle"

    def test_create_with_arch_and_boot(self, client, auth_headers):
        res = client.post("/workers", json={
            "worker_id": "worker-01", "arch": "x86_64",
            "boot": {"menu_default": "windows", "menu_timeout": 5},
        }, headers=auth_headers)
        assert res.status_code == 201
        body = res.json()
        assert body["arch"] == "x86_64"
        assert body["boot"] == {"menu_default": "windows", "menu_timeout": 5}

    def test_create_with_mac_binds_device(self, client, auth_headers):
        client.post("/devices", json={"mac": MAC_A}, headers=auth_headers)
        res = client.post("/workers", json={"worker_id": "worker-01", "mac": MAC_A}, headers=auth_headers)
        assert res.status_code == 201, res.text
        assert res.json()["bound_device"] == MAC_A
        dev = client.get(f"/devices/{MAC_A}", headers=auth_headers).json()
        assert dev["state"] == "bound"
        assert dev["bound_worker_id"] == "worker-01"
        # dnsmasq 绑定
        from control_plane.app.config import settings
        assert MAC_A in settings.dnsmasq_hosts_file.read_text(encoding="utf-8")

    def test_create_duplicate_409(self, client, auth_headers):
        client.post("/workers", json={"worker_id": "worker-01"}, headers=auth_headers)
        res = client.post("/workers", json={"worker_id": "worker-01"}, headers=auth_headers)
        assert res.status_code == 409

    def test_create_invalid_id_400(self, client, auth_headers):
        res = client.post("/workers", json={"worker_id": "Bad ID!"}, headers=auth_headers)
        assert res.status_code == 400

    def test_create_hostname_conflict_409(self, client, auth_headers):
        client.post("/workers", json={"worker_id": "worker-01"}, headers=auth_headers)
        res = client.post("/workers", json={"worker_id": "worker-02", "hostname": "worker-01"},
                          headers=auth_headers)
        assert res.status_code == 409

    def test_create_mac_not_in_pool_409(self, client, auth_headers):
        res = client.post("/workers", json={"worker_id": "worker-01", "mac": MAC_A}, headers=auth_headers)
        assert res.status_code == 409
        assert "not in pool" in res.json()["detail"]

    def test_requires_token(self, client):
        assert client.post("/workers", json={"worker_id": "worker-01"}).status_code == 401
        assert client.get("/workers").status_code == 401


class TestWorkerBatch:
    """批量创建：逐项独立、幂等重跑。"""

    def test_batch_create(self, client, auth_headers):
        res = client.post("/workers/batch", json={"count": 3, "name_prefix": "worker-"},
                          headers=auth_headers)
        assert res.status_code == 200
        body = res.json()
        assert [i["worker_id"] for i in body["succeeded"]] == ["worker-01", "worker-02", "worker-03"]
        # 重跑 → 全部 skipped
        res = client.post("/workers/batch", json={"count": 3, "name_prefix": "worker-"},
                          headers=auth_headers)
        body = res.json()
        assert len(body["succeeded"]) == 0
        assert all(i["reason"] == "already exists" for i in body["skipped"])

    def test_batch_create_with_macs(self, client, auth_headers):
        for mac in (MAC_A, MAC_B, MAC_C):
            client.post("/devices", json={"mac": mac}, headers=auth_headers)
        res = client.post("/workers/batch", json={
            "count": 3, "name_prefix": "worker-",
            "macs": [MAC_A, MAC_B, MAC_C],
        }, headers=auth_headers)
        assert res.status_code == 200
        assert len(res.json()["succeeded"]) == 3
        assert len(client.get("/devices", params={"state": "bound"}, headers=auth_headers).json()) == 3

    def test_batch_macs_length_mismatch_400(self, client, auth_headers):
        res = client.post("/workers/batch", json={
            "count": 2, "name_prefix": "worker-", "macs": [MAC_A],
        }, headers=auth_headers)
        assert res.status_code == 400

    def test_batch_device_conflict_item_failed(self, client, auth_headers):
        # 设备已被其他 worker 占用 → 该项 failed 且不创建（worker 重名则 skipped，不在此用例范围）
        client.post("/devices", json={"mac": MAC_A}, headers=auth_headers)
        client.post("/devices", json={"mac": MAC_B}, headers=auth_headers)
        client.post("/workers", json={"worker_id": "worker-01", "mac": MAC_A}, headers=auth_headers)
        res = client.post("/workers/batch", json={
            "count": 2, "name_prefix": "node-",
            "macs": [MAC_A, MAC_B],
        }, headers=auth_headers)
        body = res.json()
        assert len(body["failed"]) == 1
        assert body["failed"][0]["worker_id"] == "node-01"
        assert "already bound" in body["failed"][0]["error"]
        assert len(body["succeeded"]) == 1
        assert body["succeeded"][0]["worker_id"] == "node-02"


class TestWorkerMac:
    """MAC 换绑：hostname 不变，旧设备回池，新设备绑定。"""

    def test_update_mac_rebind(self, client, auth_headers):
        client.post("/devices", json={"mac": MAC_A}, headers=auth_headers)
        client.post("/devices", json={"mac": MAC_B}, headers=auth_headers)
        client.post("/workers", json={"worker_id": "worker-01", "mac": MAC_A}, headers=auth_headers)

        res = client.put("/workers/worker-01/mac", json={"mac": MAC_B}, headers=auth_headers)
        assert res.status_code == 200, res.text
        assert res.json()["mac"] == MAC_B
        # 旧设备回池、新设备绑定
        old = client.get(f"/devices/{MAC_A}", headers=auth_headers).json()
        assert old["state"] == "pooled"
        new = client.get(f"/devices/{MAC_B}", headers=auth_headers).json()
        assert new["state"] == "bound"
        assert new["bound_worker_id"] == "worker-01"
        # dnsmasq：hostname 仍指向新 mac
        from control_plane.app.config import settings
        hosts = settings.dnsmasq_hosts_file.read_text(encoding="utf-8")
        assert MAC_B in hosts and MAC_A not in hosts

    def test_update_mac_same_unchanged(self, client, auth_headers):
        client.post("/devices", json={"mac": MAC_A}, headers=auth_headers)
        client.post("/workers", json={"worker_id": "worker-01", "mac": MAC_A}, headers=auth_headers)
        res = client.put("/workers/worker-01/mac", json={"mac": MAC_A}, headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["mac"] == MAC_A

    def test_update_mac_not_in_pool_409(self, client, auth_headers):
        client.post("/devices", json={"mac": MAC_A}, headers=auth_headers)
        client.post("/workers", json={"worker_id": "worker-01", "mac": MAC_A}, headers=auth_headers)
        res = client.put("/workers/worker-01/mac", json={"mac": MAC_C}, headers=auth_headers)
        assert res.status_code == 409


class TestWorkerDisks:
    """系统盘：建盘（mock agent）/ 批量建盘 / 删盘 / default_os 联动。"""

    def test_create_disk_ready(self, client, auth_headers, register_agent):
        client.post("/workers", json={"worker_id": "worker-01"}, headers=auth_headers)
        res = client.post("/workers/worker-01/luns/disk", json={
            "type": "master", "os": "ubuntu", "name": "ubuntu-24.04-master",
        }, headers=auth_headers)
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["state"] == "ready"
        assert body["disks"][0]["os"] == "ubuntu"
        assert body["disks"][0]["agent"] == "ag-01"
        assert body["disks"][0]["iqn"].endswith("worker-01.ubuntu")
        assert body["disks"][0]["source"] == {"type": "master", "name": "ubuntu-24.04-master"}

    def test_create_disk_duplicate_os_409(self, client, auth_headers, register_agent):
        client.post("/workers", json={"worker_id": "worker-01"}, headers=auth_headers)
        body = {"type": "empty", "os": "ubuntu", "size": "40G"}
        assert client.post("/workers/worker-01/luns/disk", json=body, headers=auth_headers).status_code == 201
        res = client.post("/workers/worker-01/luns/disk", json=body, headers=auth_headers)
        assert res.status_code == 409

    def test_create_disk_invalid_os_400(self, client, auth_headers, register_agent):
        client.post("/workers", json={"worker_id": "worker-01"}, headers=auth_headers)
        res = client.post("/workers/worker-01/luns/disk", json={
            "type": "empty", "os": "freedos", "size": "40G",
        }, headers=auth_headers)
        assert res.status_code == 400

    def test_batch_create_disks_sets_default_os(self, client, auth_headers, register_agent):
        client.post("/workers/batch", json={"count": 2, "name_prefix": "node-"}, headers=auth_headers)
        res = client.post("/workers/luns/disk/batch", json={
            "type": "empty", "os": "debian", "size": "40G",
            "targets": [{"worker_id": "node-01", "agent": "ag-01"},
                        {"worker_id": "node-02", "agent": "ag-01"}],
        }, headers=auth_headers)
        assert res.status_code == 200
        body = res.json()
        assert len(body["succeeded"]) == 2
        # 批量建盘约定：自动设为默认启动系统
        for wid in ("node-01", "node-02"):
            w = client.get(f"/workers/{wid}", headers=auth_headers).json()
            assert w["default_os"] == "debian"
            assert w["state"] == "ready"

    def test_batch_disk_skips_existing(self, client, auth_headers, register_agent):
        client.post("/workers", json={"worker_id": "worker-01"}, headers=auth_headers)
        client.post("/workers/worker-01/luns/disk", json={
            "type": "empty", "os": "ubuntu", "size": "40G",
        }, headers=auth_headers)
        res = client.post("/workers/luns/disk/batch", json={
            "type": "empty", "os": "ubuntu", "size": "40G",
            "targets": [{"worker_id": "worker-01", "agent": "ag-01"}],
        }, headers=auth_headers)
        body = res.json()
        assert len(body["succeeded"]) == 0
        assert body["skipped"][0]["reason"] == "already has a ubuntu system disk"

    def test_delete_disk_regress_state(self, client, auth_headers, register_agent):
        client.post("/workers", json={"worker_id": "worker-01"}, headers=auth_headers)
        client.post("/workers/worker-01/luns/disk", json={
            "type": "master", "os": "ubuntu", "name": "m",
        }, headers=auth_headers)
        client.put("/workers/worker-01/default-os", json={"os": "ubuntu"}, headers=auth_headers)
        res = client.delete("/workers/worker-01/luns/disk/ubuntu", headers=auth_headers)
        assert res.status_code == 200
        body = res.json()
        assert body["state"] == "registered"  # 无盘回退
        assert body["disks"] == []
        assert "default_os" not in body  # 默认启动联动清除


class TestDefaultBoot:
    """默认启动配置：os 须与已挂盘一致；menu_default 严格校验。"""

    def test_set_default_os_requires_disk(self, client, auth_headers):
        client.post("/workers", json={"worker_id": "worker-01"}, headers=auth_headers)
        res = client.put("/workers/worker-01/default-os", json={"os": "ubuntu"}, headers=auth_headers)
        assert res.status_code == 400
        assert "no ubuntu system disk" in res.json()["detail"]

    def test_set_invalid_menu_default_400(self, client, auth_headers):
        client.post("/workers", json={"worker_id": "worker-01"}, headers=auth_headers)
        res = client.put("/workers/worker-01/default-os", json={"menu_default": "hack"},
                         headers=auth_headers)
        assert res.status_code == 400

    def test_set_menu_timeout_negative_400(self, client, auth_headers):
        client.post("/workers", json={"worker_id": "worker-01"}, headers=auth_headers)
        res = client.put("/workers/worker-01/default-os", json={"menu_timeout": -1},
                         headers=auth_headers)
        assert res.status_code == 400

    def test_clear_default_os(self, client, auth_headers, register_agent):
        client.post("/workers", json={"worker_id": "worker-01"}, headers=auth_headers)
        client.post("/workers/worker-01/luns/disk", json={
            "type": "master", "os": "ubuntu", "name": "m",
        }, headers=auth_headers)
        client.put("/workers/worker-01/default-os", json={"os": "ubuntu"}, headers=auth_headers)
        res = client.put("/workers/worker-01/default-os", json={"os": None}, headers=auth_headers)
        assert res.status_code == 200
        assert "default_os" not in res.json()


class TestWorkerDelete:
    """删除：台账移除 + 设备回池 + dnsmasq 清理；批量逐项独立。"""

    def test_delete_worker(self, client, auth_headers):
        client.post("/devices", json={"mac": MAC_A}, headers=auth_headers)
        client.post("/workers", json={"worker_id": "worker-01", "mac": MAC_A}, headers=auth_headers)
        res = client.delete("/workers/worker-01", headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["deleted"] == "worker-01"
        # 台账移除 + 设备回池 + dnsmasq 清理
        assert client.get("/workers/worker-01", headers=auth_headers).status_code == 404
        dev = client.get(f"/devices/{MAC_A}", headers=auth_headers).json()
        assert dev["state"] == "pooled"
        from control_plane.app.config import settings
        assert "worker-01" not in settings.dnsmasq_hosts_file.read_text(encoding="utf-8")

    def test_delete_missing_404(self, client, auth_headers):
        assert client.delete("/workers/worker-01", headers=auth_headers).status_code == 404

    def test_batch_delete(self, client, auth_headers):
        client.post("/workers", json={"worker_id": "worker-01"}, headers=auth_headers)
        client.post("/workers", json={"worker_id": "worker-02"}, headers=auth_headers)
        res = client.post("/workers/delete/batch", json={
            "worker_ids": ["worker-01", "worker-02", "worker-99"],
        }, headers=auth_headers)
        assert res.status_code == 200
        body = res.json()
        assert [i["worker_id"] for i in body["succeeded"]] == ["worker-01", "worker-02"]
        assert body["failed"][0]["worker_id"] == "worker-99"
        assert len(client.get("/workers", headers=auth_headers).json()) == 0

    def test_delete_worker_with_disk(self, client, auth_headers, register_agent):
        client.post("/workers", json={"worker_id": "worker-01"}, headers=auth_headers)
        client.post("/workers/worker-01/luns/disk", json={
            "type": "master", "os": "ubuntu", "name": "m",
        }, headers=auth_headers)
        res = client.delete("/workers/worker-01", params={"delete_disk": "true"}, headers=auth_headers)
        assert res.status_code == 200
