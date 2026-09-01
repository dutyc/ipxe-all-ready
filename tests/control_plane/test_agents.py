"""Agent 域（Bearer 鉴权）：注册/更新/探测/LUN/母盘聚合（AgentClient 全 mock，无网络）。"""

import pytest

from control_plane.app.agent_client import AgentClient


@pytest.fixture()
def agent_payload():
    return {
        "id": "ag-01",
        "base_url": "http://ag-01:8000",
        "role": {"disk": True, "cd": True},
        "tags": ["storage", "stgt"],
        "enabled": True,
    }


class TestAgentCrud:
    """Agent 注册/列表/更新。"""

    def test_create_agent(self, client, auth_headers, agent_payload):
        res = client.post("/agents", json=agent_payload, headers=auth_headers)
        assert res.status_code == 201
        body = res.json()
        assert body["id"] == "ag-01"
        assert body["role"] == {"disk": True, "cd": True}
        assert body["storager_ip"] is None  # 未显式配置 → 缺省空；回退 base_url 主机名仅在 boot-vars 投影时
        assert "token" not in body  # 身份由 mTLS 组件证书承载（K8S 同构），注册表无 token 字段
        # 列表（live=false：不做健康探测，返回纯台账）
        listing = client.get("/agents", params={"live": "false"}, headers=auth_headers).json()
        assert listing == [body]

    def test_create_duplicate_409(self, client, auth_headers, agent_payload):
        client.post("/agents", json=agent_payload, headers=auth_headers)
        res = client.post("/agents", json=agent_payload, headers=auth_headers)
        assert res.status_code == 409

    def test_create_invalid_id_400(self, client, auth_headers, agent_payload):
        agent_payload["id"] = "Bad ID!"
        res = client.post("/agents", json=agent_payload, headers=auth_headers)
        assert res.status_code == 400

    def test_create_invalid_base_url_400(self, client, auth_headers, agent_payload):
        agent_payload["base_url"] = "ag-01:8000"  # 缺 scheme
        res = client.post("/agents", json=agent_payload, headers=auth_headers)
        assert res.status_code == 400

    def test_update_agent(self, client, auth_headers, agent_payload):
        client.post("/agents", json=agent_payload, headers=auth_headers)
        res = client.put("/agents/ag-01", json={
            "base_url": "http://ag-01-new:9000",
            "role": {"disk": True, "cd": False},
            "tags": ["storage", "lio"],
            "enabled": False,
        }, headers=auth_headers)
        assert res.status_code == 200
        body = res.json()
        assert body["base_url"] == "http://ag-01-new:9000"
        assert body["role"] == {"disk": True, "cd": False}
        assert body["tags"] == ["storage", "lio"]
        assert body["enabled"] is False
        assert body["storager_ip"] is None

    def test_update_missing_404(self, client, auth_headers):
        res = client.put("/agents/ag-01", json={
            "base_url": "http://ag-01:8000", "role": {"disk": True, "cd": False},
        }, headers=auth_headers)
        assert res.status_code == 404

    def test_requires_token(self, client, agent_payload):
        assert client.get("/agents").status_code == 401
        assert client.post("/agents", json=agent_payload).status_code == 401


class TestAgentProbe:
    """探测预览：推导注册参数，不落盘（AgentClient 类方法 mock）。"""

    def test_probe_derives_params(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(AgentClient, "healthz", lambda self: {"status": "ok"})
        monkeypatch.setattr(AgentClient, "capabilities", lambda self: {
            "backend": "lio", "cd": True, "base_nqn": "nqn.2026-07.com.test",
        })
        res = client.post("/agents/probe", json={
            "base_url": "http://ag-probe:8000",
        }, headers=auth_headers)
        assert res.status_code == 200
        body = res.json()
        assert body["role"] == {"disk": True, "cd": True}
        assert body["tags"] == ["storage", "lio"]
        assert body["storager_ip"] == "ag-probe"
        assert body["backend"] == "lio"
        assert body["base_nqn"] == "nqn.2026-07.com.test"
        # 不落盘：agents 列表仍为空
        assert client.get("/agents", headers=auth_headers).json() == []

    def test_probe_unreachable_502(self, client, auth_headers, monkeypatch):
        def boom(self):
            raise RuntimeError("connection refused")
        monkeypatch.setattr(AgentClient, "healthz", boom)
        res = client.post("/agents/probe", json={"base_url": "http://down:8000"}, headers=auth_headers)
        assert res.status_code == 502

    def test_probe_edit_scenario(self, client, auth_headers, monkeypatch):
        """编辑场景探测：经控制面 mTLS 客户端证书鉴权（token 已随 K8S 同构改造移除），
        agent_id 仅作编辑场景标识，无 token 回退逻辑。"""
        monkeypatch.setattr(AgentClient, "healthz", lambda self: {"status": "ok"})
        monkeypatch.setattr(AgentClient, "capabilities", lambda self: {"backend": "stgt"})
        client.post("/agents", json={
            "id": "ag-01", "base_url": "http://ag-01:8000",
            "role": {"disk": True, "cd": False},
        }, headers=auth_headers)
        res = client.post("/agents/probe", json={
            "base_url": "http://ag-01:8000", "agent_id": "ag-01",
        }, headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["backend"] == "stgt"


class TestAgentLuns:
    """LUN 管理（agents.client mock）。"""

    def test_list_luns_empty(self, client, auth_headers, agent_payload, mock_agent_client):
        client.post("/agents", json=agent_payload, headers=auth_headers)
        res = client.get("/agents/ag-01/luns", headers=auth_headers)
        assert res.status_code == 200
        assert res.json() == []

    def test_luns_missing_agent_404(self, client, auth_headers):
        assert client.get("/agents/ag-01/luns", headers=auth_headers).status_code == 404

    def test_create_disk_lun(self, client, auth_headers, agent_payload, mock_agent_client):
        client.post("/agents", json=agent_payload, headers=auth_headers)
        res = client.post("/agents/ag-01/luns/disk", json={
            "iqn": "iqn.2026-07.com.test:worker-01.ubuntu",
            "filename": "worker-01.ubuntu.img",
            "master": "ubuntu-24.04-master",
        }, headers=auth_headers)
        assert res.status_code == 201
        assert res.json()["backing"] == "/srv/iscsi/worker-01.ubuntu.img"

    def test_create_cd_lun(self, client, auth_headers, agent_payload, mock_agent_client):
        client.post("/agents", json=agent_payload, headers=auth_headers)
        res = client.post("/agents/ag-01/luns/cd", json={"iso": "windows-11.iso"}, headers=auth_headers)
        assert res.status_code == 201

    def test_create_cd_on_non_cd_agent_400(self, client, auth_headers, agent_payload, mock_agent_client):
        agent_payload["role"] = {"disk": True, "cd": False}
        client.post("/agents", json=agent_payload, headers=auth_headers)
        res = client.post("/agents/ag-01/luns/cd", json={"iso": "windows-11.iso"}, headers=auth_headers)
        assert res.status_code == 400

    def test_scan(self, client, auth_headers, agent_payload, mock_agent_client):
        client.post("/agents", json=agent_payload, headers=auth_headers)
        res = client.post("/agents/ag-01/luns/scan", headers=auth_headers)
        assert res.status_code == 200
        assert res.json() == {"created": [], "skipped": []}


class TestMasters:
    """母盘聚合：逐 Agent 独立，失败不阻塞整体。"""

    def test_masters_aggregate(self, client, auth_headers, monkeypatch):
        from types import SimpleNamespace

        from control_plane.app.stores import agents

        def fake_client(agent):
            return SimpleNamespace(list_masters=lambda: {
                "masters": [{"name": "ubuntu-24.04-master", "size": "20G",
                              "path": f"/srv/{agent.id}/x.img"}],
            })
        monkeypatch.setattr(agents, "client", fake_client)
        for aid in ("ag-01", "ag-02"):
            client.post("/agents", json={
                "id": aid, "base_url": f"http://{aid}:8000",
                "role": {"disk": True, "cd": False},
            }, headers=auth_headers)
        res = client.get("/masters", headers=auth_headers)
        assert res.status_code == 200
        body = res.json()
        assert len(body["agents"]) == 2
        for entry in body["agents"]:
            assert len(entry["masters"]) == 1
            assert entry["masters"][0]["name"] == "ubuntu-24.04-master"

    def test_masters_partial_failure(self, client, auth_headers, monkeypatch):
        from types import SimpleNamespace

        from control_plane.app.agent_client import AgentAPIError
        from control_plane.app.stores import agents

        def flaky(agent):
            if agent.id == "ag-02":
                raise AgentAPIError(agent.id, 500, "boom")
            return SimpleNamespace(list_masters=lambda: {
                "masters": [{"name": "ubuntu-24.04-master", "size": "20G",
                              "path": f"/srv/{agent.id}/x.img"}],
            })
        monkeypatch.setattr(agents, "client", flaky)
        for aid in ("ag-01", "ag-02"):
            client.post("/agents", json={
                "id": aid, "base_url": f"http://{aid}:8000",
                "role": {"disk": True, "cd": False},
            }, headers=auth_headers)
        res = client.get("/masters", headers=auth_headers)
        assert res.status_code == 200  # 单台失败不阻塞整体
        body = res.json()
        failed = [e for e in body["agents"] if e["agent"] == "ag-02"][0]
        assert failed["masters"] == []
        assert failed["error"] == "boom"


class TestMasterTags:
    """母盘标签登记（控制面台账，备注性质）：登记/覆盖/清除/聚合合并/404。"""

    def _register_agent(self, client, auth_headers):
        res = client.post("/agents", json={
            "id": "ag-01", "base_url": "http://ag-01:8000",
            "role": {"disk": True, "cd": False}, "tags": ["storage", "stgt"],
        }, headers=auth_headers)
        assert res.status_code == 201, res.text

    def test_set_master_tag(self, client, auth_headers):
        self._register_agent(client, auth_headers)
        res = client.put("/agents/ag-01/masters/ubuntu-24.04-master/tag",
                         json={"os": "Ubuntu", "os_version": "24.04"}, headers=auth_headers)
        assert res.status_code == 200
        assert res.json() == {
            "agent": "ag-01", "name": "ubuntu-24.04-master",
            "os": "ubuntu", "os_version": "24.04", "remark": "",  # os 小写归一
        }
        # 覆盖更新（同键幂等）
        res = client.put("/agents/ag-01/masters/ubuntu-24.04-master/tag",
                         json={"os": "ubuntu", "os_version": "24.04.1"}, headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["os_version"] == "24.04.1"

    def test_set_master_tag_version_optional(self, client, auth_headers):
        self._register_agent(client, auth_headers)
        res = client.put("/agents/ag-01/masters/debian-master/tag",
                         json={"os": "debian"}, headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["os_version"] == ""  # 缺省 → ''（库表形态：无版本）

    def test_set_master_tag_invalid_os_400(self, client, auth_headers):
        self._register_agent(client, auth_headers)
        res = client.put("/agents/ag-01/masters/x/tag",
                         json={"os": "bad os!"}, headers=auth_headers)
        assert res.status_code == 400
        assert "invalid os" in res.json()["detail"]

    def test_clear_master_tag(self, client, auth_headers):
        self._register_agent(client, auth_headers)
        client.put("/agents/ag-01/masters/ubuntu-24.04-master/tag",
                   json={"os": "ubuntu", "os_version": "24.04"}, headers=auth_headers)
        res = client.delete("/agents/ag-01/masters/ubuntu-24.04-master/tag", headers=auth_headers)
        assert res.status_code == 200
        assert res.json() == {"agent": "ag-01", "name": "ubuntu-24.04-master", "removed": True}
        # 再清 → 未登记（removed=false）
        res = client.delete("/agents/ag-01/masters/ubuntu-24.04-master/tag", headers=auth_headers)
        assert res.json()["removed"] is False

    def test_master_tag_missing_agent_404(self, client, auth_headers):
        assert client.put("/agents/ag-99/masters/x/tag", json={"os": "ubuntu"},
                          headers=auth_headers).status_code == 404
        assert client.delete("/agents/ag-99/masters/x/tag", headers=auth_headers).status_code == 404

    def test_master_tag_requires_token(self, client, agent_payload):
        assert client.put("/agents/ag-01/masters/x/tag", json={"os": "ubuntu"}).status_code == 401
        assert client.delete("/agents/ag-01/masters/x/tag").status_code == 401

    def test_masters_aggregate_merges_tags(self, client, auth_headers, monkeypatch):
        """/masters 聚合：已登记的母盘条目附加 os/os_version；未登记的不附加。"""
        from types import SimpleNamespace

        from control_plane.app.stores import agents

        def fake_client(agent):
            return SimpleNamespace(list_masters=lambda: {
                "masters": [
                    {"name": "ubuntu-24.04-master", "size": "20G", "path": "/srv/x1.img"},
                    {"name": "unlabeled-master", "size": "30G", "path": "/srv/x2.img"},
                ],
            })
        monkeypatch.setattr(agents, "client", fake_client)
        self._register_agent(client, auth_headers)
        client.put("/agents/ag-01/masters/ubuntu-24.04-master/tag",
                   json={"os": "ubuntu", "os_version": "24.04"}, headers=auth_headers)

        res = client.get("/masters", headers=auth_headers)
        assert res.status_code == 200
        masters = res.json()["agents"][0]["masters"]
        tagged = next(m for m in masters if m["name"] == "ubuntu-24.04-master")
        assert tagged["os"] == "ubuntu"
        assert tagged["os_version"] == "24.04"
        untagged = next(m for m in masters if m["name"] == "unlabeled-master")
        assert "os" not in untagged and "os_version" not in untagged  # 未登记不附加
