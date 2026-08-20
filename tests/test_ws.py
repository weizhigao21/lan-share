"""WebSocket 实时通道测试：在线推送 / 离线补发 / 心跳 / 未注册拒绝。"""
import pytest


def _register(client, name):
    return client.post("/api/v1/devices/register", json={"name": name}).json()


def test_ws_rejects_unknown_device(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/api/v1/ws?device_id=nope"):
            pass


def test_ping_pong(client):
    a = _register(client, "A")
    with client.websocket_connect(f"/api/v1/ws?device_id={a['id']}") as ws_a:
        ws_a.send_json({"type": "ping"})
        assert ws_a.receive_json() == {"type": "pong"}


def test_realtime_push_when_online(client):
    a = _register(client, "A")
    b = _register(client, "B")
    with client.websocket_connect(f"/api/v1/ws?device_id={b['id']}") as ws_b:
        resp = client.post(
            "/api/v1/messages",
            json={"sender_id": a["id"], "recipient_id": b["id"], "content": "你好"},
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "delivered"

        msg = ws_b.receive_json()
        assert msg["type"] == "message"
        assert msg["data"]["content"] == "你好"
        assert msg.get("offline") is False


def test_offline_message_flushed_on_connect(client):
    a = _register(client, "A")
    b = _register(client, "B")

    resp = client.post(
        "/api/v1/messages",
        json={"sender_id": a["id"], "recipient_id": b["id"], "content": "离线消息"},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"

    # B 上线后应立即收到离线消息，且标记 offline=true
    with client.websocket_connect(f"/api/v1/ws?device_id={b['id']}") as ws_b:
        msg = ws_b.receive_json()
        assert msg["type"] == "message"
        assert msg["data"]["content"] == "离线消息"
        assert msg.get("offline") is True
