"""nvmet-host 宿主服务单测：mock configfs（NVMET_CONFIGFS 重定向）+ TestClient。

覆盖：鉴权、healthz、子系统 CRUD（严格模式/namespace/port 挂载）、host 认证
（dhchap_key 明文写入 + allowed_hosts symlink）、删除顺序（先摘 port 再删）。
真实内核 nvmet 验证留部署环境（本机无内核 nvmet）。
"""

import os

# Windows 路径段不允许冒号（WinError 267）：mock configfs 的 NQN 用点分隔（真实 NQN 冒号语义不受影响）
NQN = "nqn.2026-07.com.test.worker-01.ubuntu"
BACKING = "/srv/iscsi/worker-01.ubuntu.img"
HOST_NQN = "nqn.2026-07.com.kurrent.host.worker-01"
SECRET = "DHHC-1:01:YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXo="


def test_healthz_no_auth(nvmet, client, configfs):
    """healthz 是唯一不鉴权端点；configfs 未就绪（无 subsystems）→ false。"""
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "configfs": False}


def test_healthz_configfs_ready(nvmet, client, configfs):
    os.makedirs(configfs / "subsystems")
    assert client.get("/healthz").json()["configfs"] is True


def test_requires_auth(client):
    """除 healthz 外全部端点要求 Bearer token。"""
    assert client.get("/capabilities").status_code == 401
    assert client.get("/subsystems").status_code == 401
    assert client.post("/subsystems", json={"nqn": NQN, "backing": BACKING}).status_code == 401
    assert client.post("/port").status_code == 401
    assert client.put(f"/subsystems/{NQN}/hosts",
                      json={"hostnqn": HOST_NQN, "secret": SECRET}).status_code == 401
    bad = {"Authorization": "Bearer wrong"}
    assert client.get("/capabilities", headers=bad).status_code == 401


def test_capabilities(client, auth_headers):
    res = client.get("/capabilities", headers=auth_headers)
    assert res.status_code == 200
    caps = res.json()
    assert caps["backend"] == "nvmet"
    assert caps["cd"] is False
    assert caps["port"] == {"trtype": "tcp", "trsvcid": "4420", "tsas": "none"}


def test_ensure_port(client, auth_headers, configfs):
    res = client.post("/port", params={"trsvcid": "4420"}, headers=auth_headers)
    assert res.status_code == 200
    port = configfs / "ports" / "1"
    assert (port / "addr_trtype").read_text().strip() == "tcp"
    assert (port / "addr_traddr").read_text().strip() == "0.0.0.0"
    assert (port / "addr_trsvcid").read_text().strip() == "4420"
    assert (port / "addr_tsas").read_text().strip() == "none"


def test_create_subsystem_strict(client, auth_headers, configfs, symlinks):
    """创建子系统：严格模式（allow_any_host=0）+ namespace/1 + port 挂载。"""
    res = client.post("/subsystems", json={"nqn": NQN, "backing": BACKING}, headers=auth_headers)
    assert res.status_code == 201
    sub = configfs / "subsystems" / NQN
    assert (sub / "attr_allow_any_host").read_text().strip() == "0"
    ns = sub / "namespaces" / "1"
    assert (ns / "device_path").read_text().strip() == BACKING
    assert (ns / "enable").read_text().strip() == "1"
    link = configfs / "ports" / "1" / "subsystems" / NQN
    assert os.path.islink(link)
    assert symlinks[str(link)] == "../../subsystems/{NQN}".format(NQN=NQN)


def test_create_duplicate_409(client, auth_headers, configfs):
    client.post("/subsystems", json={"nqn": NQN, "backing": BACKING}, headers=auth_headers)
    res = client.post("/subsystems", json={"nqn": NQN, "backing": BACKING}, headers=auth_headers)
    assert res.status_code == 409


def test_list_subsystems(client, auth_headers, configfs):
    client.post("/subsystems", json={"nqn": NQN, "backing": BACKING}, headers=auth_headers)
    client.post("/subsystems", json={"nqn": NQN + ".2", "backing": BACKING + "2"}, headers=auth_headers)
    res = client.get("/subsystems", headers=auth_headers)
    assert res.status_code == 200
    subs = {s["nqn"]: s for s in res.json()["subsystems"]}
    assert set(subs) == {NQN, NQN + ".2"}
    assert subs[NQN]["namespaces"] == [{"nsid": 1, "device_path": BACKING}]
    assert subs[NQN]["hosts"] == []


def test_set_host_dhchap_key(client, auth_headers, configfs, symlinks):
    """host 认证：dhchap_key 写 DHHC-1 明文（无换行）+ allowed_hosts symlink。"""
    client.post("/subsystems", json={"nqn": NQN, "backing": BACKING}, headers=auth_headers)
    res = client.put(f"/subsystems/{NQN}/hosts",
                     json={"hostnqn": HOST_NQN, "secret": SECRET}, headers=auth_headers)
    assert res.status_code == 200
    sub = configfs / "subsystems" / NQN
    key_file = sub / "hosts" / HOST_NQN / "dhchap_key"
    assert key_file.read_text() == SECRET  # newline=False：内容与密钥完全一致
    allowed = sub / "allowed_hosts" / HOST_NQN
    assert os.path.islink(allowed)
    assert symlinks[str(allowed)] == "../../hosts/{h}".format(h=HOST_NQN)


def test_set_host_idempotent(client, auth_headers, configfs):
    client.post("/subsystems", json={"nqn": NQN, "backing": BACKING}, headers=auth_headers)
    for _ in range(2):
        res = client.put(f"/subsystems/{NQN}/hosts",
                         json={"hostnqn": HOST_NQN, "secret": SECRET}, headers=auth_headers)
        assert res.status_code == 200


def test_set_host_missing_subsystem_404(client, auth_headers, configfs):
    res = client.put(f"/subsystems/{NQN}/hosts",
                     json={"hostnqn": HOST_NQN, "secret": SECRET}, headers=auth_headers)
    assert res.status_code == 404


def test_delete_host(client, auth_headers, configfs):
    client.post("/subsystems", json={"nqn": NQN, "backing": BACKING}, headers=auth_headers)
    client.put(f"/subsystems/{NQN}/hosts",
               json={"hostnqn": HOST_NQN, "secret": SECRET}, headers=auth_headers)
    res = client.delete(f"/subsystems/{NQN}/hosts/{HOST_NQN}", headers=auth_headers)
    assert res.status_code == 200
    sub = configfs / "subsystems" / NQN
    assert not (sub / "hosts" / HOST_NQN).exists()
    assert not (sub / "allowed_hosts" / HOST_NQN).exists()


def test_delete_subsystem_detaches_port(client, auth_headers, configfs):
    client.post("/subsystems", json={"nqn": NQN, "backing": BACKING}, headers=auth_headers)
    client.put(f"/subsystems/{NQN}/hosts",
               json={"hostnqn": HOST_NQN, "secret": SECRET}, headers=auth_headers)
    res = client.delete(f"/subsystems/{NQN}", headers=auth_headers)
    assert res.status_code == 200
    assert not (configfs / "subsystems" / NQN).exists()
    assert not (configfs / "ports" / "1" / "subsystems" / NQN).exists()  # port 挂载已摘


def test_delete_subsystem_404(client, auth_headers, configfs):
    res = client.delete(f"/subsystems/{NQN}", headers=auth_headers)
    assert res.status_code == 404
