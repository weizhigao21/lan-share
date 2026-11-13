"""设备身份恢复 / 离线设备清理测试。

背景：浏览器（尤其安卓内置 WebView）清掉 localStorage 后，旧逻辑会让用户重新注册，
每开一次页面就多出一台同名设备。服务端现在用 Cookie + 来源 IP 兜底认回身份。
"""
import sqlite3

from app.config import settings

COOKIE = "lan_device_id"


def _register(client, name):
    return client.post("/api/v1/devices/register", json={"name": name}).json()


def _make_offline(device_id):
    """把设备 last_seen 改到很久以前，模拟离线。"""
    conn = sqlite3.connect(str(settings.db_path))
    with conn:
        conn.execute(
            "UPDATE devices SET last_seen = '2020-01-01T00:00:00+00:00' WHERE id = ?",
            (device_id,),
        )
    conn.close()


def test_register_writes_identity_cookie(client):
    dev = _register(client, "手机")
    assert client.cookies.get(COOKIE) == dev["id"]


def test_who_am_i_restores_from_cookie(client):
    dev = _register(client, "手机")
    resp = client.get("/api/v1/me/device")
    assert resp.status_code == 200
    assert resp.json()["id"] == dev["id"]
    assert resp.json()["name"] == "手机"


def test_who_am_i_falls_back_to_source_ip(client):
    """Cookie 丢了（换了浏览器/清了缓存），同一台设备仍应被认回来。"""
    dev = _register(client, "手机")
    client.cookies.clear()

    resp = client.get("/api/v1/me/device")
    assert resp.status_code == 200
    assert resp.json()["id"] == dev["id"]
    assert client.cookies.get(COOKIE) == dev["id"]  # 认回后重新写入 Cookie


def test_who_am_i_404_when_no_identity(client):
    assert client.get("/api/v1/me/device").status_code == 404


def test_forget_device_clears_cookie(client):
    _register(client, "手机")
    assert client.delete("/api/v1/me/device").json()["ok"] is True
    assert client.cookies.get(COOKIE) is None


def test_delete_online_device_rejected(client):
    dev = _register(client, "手机")
    resp = client.delete(f"/api/v1/devices/{dev['id']}")
    assert resp.status_code == 409


def test_delete_offline_device_purges_messages_and_files(client):
    a, b = _register(client, "电脑"), _register(client, "旧手机")
    upload = client.post(
        "/api/v1/files/upload",
        data={"sender_id": a["id"], "recipient_id": b["id"]},
        files={"file": ("note.txt", b"hi", "text/plain")},
    )
    assert upload.status_code == 201
    assert len(list(settings.upload_dir.iterdir())) == 1

    _make_offline(b["id"])
    resp = client.delete(f"/api/v1/devices/{b['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] is True
    assert body["messages"] == 1
    assert body["attachments"] == 1

    assert list(settings.upload_dir.iterdir()) == []
    assert client.get(
        f"/api/v1/messages/history?device_id={a['id']}&peer_id={b['id']}"
    ).json() == []
    ids = [d["id"] for d in client.get("/api/v1/devices").json()]
    assert b["id"] not in ids
    assert a["id"] in ids


def test_delete_unknown_device_404(client):
    assert client.delete("/api/v1/devices/nope").status_code == 404
