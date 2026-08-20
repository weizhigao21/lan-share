"""设备注册 / 列表 / 改名 API 测试（M1）。"""


def test_register_device(client):
    resp = client.post("/api/v1/devices/register", json={"name": "我的手机"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"]
    assert data["name"] == "我的手机"
    assert data["is_online"] is True
    # TestClient 场景下来源 IP 为 testclient
    assert data["ip"] == "testclient"


def test_list_devices_include_ip(client):
    client.post("/api/v1/devices/register", json={"name": "A"})
    devices = client.get("/api/v1/devices").json()
    assert devices[0]["ip"] == "testclient"


def test_register_blank_name_rejected(client):
    resp = client.post("/api/v1/devices/register", json={"name": "   "})
    assert resp.status_code == 422


def test_register_name_too_long(client):
    resp = client.post("/api/v1/devices/register", json={"name": "x" * 33})
    assert resp.status_code == 422


def test_register_name_stripped(client):
    resp = client.post("/api/v1/devices/register", json={"name": "  书房电脑  "})
    assert resp.status_code == 201
    assert resp.json()["name"] == "书房电脑"


def test_list_devices(client):
    client.post("/api/v1/devices/register", json={"name": "A"})
    client.post("/api/v1/devices/register", json={"name": "B"})
    resp = client.get("/api/v1/devices")
    assert resp.status_code == 200
    devices = resp.json()
    assert len(devices) == 2
    assert [d["name"] for d in devices] == ["A", "B"]


def test_rename_device(client):
    dev = client.post("/api/v1/devices/register", json={"name": "A"}).json()
    resp = client.patch(f"/api/v1/devices/{dev['id']}/name", json={"name": "B"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "B"


def test_rename_device_not_found(client):
    resp = client.patch("/api/v1/devices/nonexistent/name", json={"name": "B"})
    assert resp.status_code == 404


def test_devices_persisted_across_connections(client):
    client.post("/api/v1/devices/register", json={"name": "持久设备"})
    resp = client.get("/api/v1/devices")
    assert resp.json()[0]["name"] == "持久设备"
