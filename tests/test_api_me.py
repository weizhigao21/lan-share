"""当前设备 IP API 测试。"""


def test_my_ip_returns_client_host(client):
    resp = client.get("/api/v1/ip")
    assert resp.status_code == 200
    data = resp.json()
    assert "ip" in data
    assert isinstance(data["ip"], str)
