"""消息 API 测试：发送 / 历史 / 清空。"""


def _register(client, name):
    return client.post("/api/v1/devices/register", json={"name": name}).json()


def test_send_to_offline_device_is_pending(client):
    a = _register(client, "A")
    b = _register(client, "B")
    resp = client.post(
        "/api/v1/messages",
        json={"sender_id": a["id"], "recipient_id": b["id"], "content": "离线消息"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "pending"
    assert data["content"] == "离线消息"


def test_send_blank_content_rejected(client):
    a = _register(client, "A")
    b = _register(client, "B")
    resp = client.post(
        "/api/v1/messages",
        json={"sender_id": a["id"], "recipient_id": b["id"], "content": "   "},
    )
    assert resp.status_code == 422


def test_send_unknown_sender_404(client):
    b = _register(client, "B")
    resp = client.post(
        "/api/v1/messages",
        json={"sender_id": "nope", "recipient_id": b["id"], "content": "hi"},
    )
    assert resp.status_code == 404


def test_send_unknown_recipient_404(client):
    a = _register(client, "A")
    resp = client.post(
        "/api/v1/messages",
        json={"sender_id": a["id"], "recipient_id": "nope", "content": "hi"},
    )
    assert resp.status_code == 404


def test_history_returns_both_directions(client):
    a = _register(client, "A")
    b = _register(client, "B")
    client.post("/api/v1/messages", json={"sender_id": a["id"], "recipient_id": b["id"], "content": "m1"})
    client.post("/api/v1/messages", json={"sender_id": b["id"], "recipient_id": a["id"], "content": "m2"})
    resp = client.get(f"/api/v1/messages/history?device_id={a['id']}&peer_id={b['id']}")
    assert resp.status_code == 200
    msgs = resp.json()
    assert [m["content"] for m in msgs] == ["m1", "m2"]
    assert [m["sender_id"] for m in msgs] == [a["id"], b["id"]]


def test_clear_conversation(client):
    a = _register(client, "A")
    b = _register(client, "B")
    c = _register(client, "C")
    client.post("/api/v1/messages", json={"sender_id": a["id"], "recipient_id": b["id"], "content": "to-b"})
    client.post("/api/v1/messages", json={"sender_id": a["id"], "recipient_id": c["id"], "content": "to-c"})

    resp = client.delete(f"/api/v1/messages?device_id={a['id']}&peer_id={b['id']}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1

    # B 会话已清空，C 会话保留
    assert client.get(f"/api/v1/messages/history?device_id={a['id']}&peer_id={b['id']}").json() == []
    assert len(client.get(f"/api/v1/messages/history?device_id={a['id']}&peer_id={c['id']}").json()) == 1


def test_clear_all(client):
    a = _register(client, "A")
    b = _register(client, "B")
    client.post("/api/v1/messages", json={"sender_id": a["id"], "recipient_id": b["id"], "content": "x"})
    resp = client.delete(f"/api/v1/messages?device_id={a['id']}")
    assert resp.json()["deleted"] == 1
