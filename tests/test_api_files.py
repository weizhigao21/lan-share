"""文件 API 测试：上传 / 下载 / 权限 / 大小限制 / 实时与离线推送 / 清空回收。"""

import pytest

from app.config import settings


def _register(client, name):
    return client.post("/api/v1/devices/register", json={"name": name}).json()


def _upload(client, sender, recipient, data=b"hello lan", filename="note.txt"):
    return client.post(
        "/api/v1/files/upload",
        data={"sender_id": sender["id"], "recipient_id": recipient["id"]},
        files={"file": (filename, data, "application/octet-stream")},
    )


def _files_on_disk():
    folder = settings.upload_dir
    return list(folder.iterdir()) if folder.is_dir() else []


def test_upload_creates_file_message(client):
    a, b = _register(client, "A"), _register(client, "B")
    resp = _upload(client, a, b)
    assert resp.status_code == 201
    msg = resp.json()
    assert msg["msg_type"] == "file"
    assert msg["status"] == "pending"  # 目标不在线，进入离线缓存
    assert msg["content"] == "note.txt"
    assert msg["attachment"]["name"] == "note.txt"
    assert msg["attachment"]["size"] == 9
    assert msg["attachment"]["url"].startswith("/api/v1/files/")
    assert len(_files_on_disk()) == 1


def test_download_returns_original_bytes(client):
    a, b = _register(client, "A"), _register(client, "B")
    att = _upload(client, a, b, data=b"\x00\x01binary\xff").json()["attachment"]
    url = f"{att['url']}?device_id={b['id']}"
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.content == b"\x00\x01binary\xff"
    assert "attachment" in resp.headers["content-disposition"]
    assert "note.txt" in resp.headers["content-disposition"]
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_download_url_embeds_original_filename(client):
    """下载地址末段必须带原文件名：安卓下载器只认 URL 取名字。"""
    a, b = _register(client, "A"), _register(client, "B")
    att = _upload(client, a, b, filename="spacedesk report.xapk").json()["attachment"]

    assert att["url"] == f"/api/v1/files/{att['id']}/download/spacedesk%20report.xapk"
    resp = client.get(f"{att['url']}?device_id={b['id']}")
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith(
        'attachment; filename="spacedesk report.xapk"'
    )


def test_ascii_fallback_keeps_extension(client):
    """中文名回退成 ASCII 时不能丢扩展名，否则会被浏览器补成 .bin。"""
    a, b = _register(client, "A"), _register(client, "B")
    att = _upload(client, a, b, filename="设计稿.xapk").json()["attachment"]

    cd = client.get(f"{att['url']}?device_id={b['id']}").headers["content-disposition"]
    assert 'filename="file.xapk"' in cd
    assert "filename*=UTF-8''%E8%AE%BE%E8%AE%A1%E7%A8%BF.xapk" in cd


def test_head_request_returns_download_metadata(client):
    """安卓下载器会先发 HEAD 探测；不应答就会退回"随机名 + .bin"。"""
    a, b = _register(client, "A"), _register(client, "B")
    att = _upload(client, a, b, data=b"abc", filename="voice.flac").json()["attachment"]

    resp = client.head(f"{att['url']}?device_id={b['id']}")
    assert resp.status_code == 200
    assert resp.headers["content-length"] == "3"
    assert resp.headers["content-disposition"].startswith('attachment; filename="voice.flac"')

    # 权限与缺失校验同样对 HEAD 生效
    assert client.head(f"{att['url']}?device_id=nobody").status_code == 403
    assert client.head("/api/v1/files/nope/download/x.flac?device_id=" + b["id"]).status_code == 404


def test_download_name_segment_is_cosmetic(client):
    """URL 末段只用于取名，实际文件名以数据库为准，传错也不影响内容。"""
    a, b = _register(client, "A"), _register(client, "B")
    att = _upload(client, a, b, filename="real.txt").json()["attachment"]

    resp = client.get(f"/api/v1/files/{att['id']}/download/fake.bin?device_id={b['id']}")
    assert resp.status_code == 200
    assert resp.content == b"hello lan"
    assert "real.txt" in resp.headers["content-disposition"]


def test_download_permission_and_missing(client):
    a, b, c = _register(client, "A"), _register(client, "B"), _register(client, "C")
    att = _upload(client, a, b).json()["attachment"]

    assert client.get(f"{att['url']}?device_id={c['id']}").status_code == 403
    assert client.get(f"{att['url']}?device_id={a['id']}").status_code == 200  # 发送方
    assert client.get(f"{att['url']}?device_id={b['id']}").status_code == 200  # 接收方
    assert client.get("/api/v1/files/nope/download?device_id=" + a["id"]).status_code == 404
    assert client.get(att["url"]).status_code == 422  # 缺少 device_id


def test_upload_unknown_device_404(client):
    b = _register(client, "B")
    resp = client.post(
        "/api/v1/files/upload",
        data={"sender_id": "nope", "recipient_id": b["id"]},
        files={"file": ("x.txt", b"x", "text/plain")},
    )
    assert resp.status_code == 404
    assert _files_on_disk() == []


def test_upload_rejects_oversize(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_size", 8)
    a, b = _register(client, "A"), _register(client, "B")
    resp = _upload(client, a, b, data=b"0123456789")
    assert resp.status_code == 413
    assert "上限" in resp.json()["detail"]  # 报错要说明具体上限，不能只说"太大"
    assert _files_on_disk() == []  # 超限时不留半截文件
    assert client.get(
        f"/api/v1/messages/history?device_id={a['id']}&peer_id={b['id']}"
    ).json() == []


def test_meta_exposes_upload_limit(client):
    """前端靠这个接口在上传前就提示超限，而不是传完才收 413。"""
    body = client.get("/api/v1/meta").json()
    assert body["max_upload_size"] == settings.max_upload_size
    assert body["max_upload_size"] >= 1024 ** 3  # 音频/视频要放得下，至少 1 GiB


def test_default_upload_limit_is_generous():
    """默认上限不能回到 100 MiB——那会把常见无损音频挡在门外。"""
    from app.config import DEFAULT_MAX_UPLOAD_MB

    assert DEFAULT_MAX_UPLOAD_MB >= 1024


def test_env_int_parsing(monkeypatch):
    from app.config import _env_int

    monkeypatch.setenv("LAN_SHARE_TEST_MB", "512")
    assert _env_int("LAN_SHARE_TEST_MB", 1) == 512
    monkeypatch.setenv("LAN_SHARE_TEST_MB", "abc")
    assert _env_int("LAN_SHARE_TEST_MB", 1) == 1
    monkeypatch.setenv("LAN_SHARE_TEST_MB", "-5")
    assert _env_int("LAN_SHARE_TEST_MB", 1) == 1
    monkeypatch.delenv("LAN_SHARE_TEST_MB")
    assert _env_int("LAN_SHARE_TEST_MB", 7) == 7


@pytest.mark.parametrize("size,expected", [
    (0, "0 B"),
    (1023, "1023 B"),
    (1536, "1.5 KB"),
    (100 * 1024 * 1024, "100 MB"),
    (2048 * 1024 * 1024, "2.0 GB"),
])
def test_human_size(size, expected):
    from app.services.file_service import human_size

    assert human_size(size) == expected


def test_filename_is_sanitized(client):
    a, b = _register(client, "A"), _register(client, "B")
    resp = _upload(client, a, b, filename="../../evil.txt")
    assert resp.status_code == 201
    assert resp.json()["attachment"]["name"] == "evil.txt"
    assert "evil.txt" not in [p.name for p in _files_on_disk()]  # 磁盘名是 UUID


def test_image_inline_preview_only_for_bitmaps(client):
    a, b = _register(client, "A"), _register(client, "B")
    png = _upload(client, a, b, filename="pic.png").json()["attachment"]
    txt = _upload(client, a, b, filename="plain.txt").json()["attachment"]

    r1 = client.get(f"{png['url']}?device_id={b['id']}&inline=true")
    assert r1.status_code == 200
    assert r1.headers["content-type"].startswith("image/png")
    assert r1.headers["content-disposition"].startswith("inline")

    r2 = client.get(f"{txt['url']}?device_id={b['id']}&inline=true")
    assert r2.headers["content-disposition"].startswith("attachment")


def test_text_message_has_no_attachment(client):
    a, b = _register(client, "A"), _register(client, "B")
    resp = client.post(
        "/api/v1/messages",
        json={"sender_id": a["id"], "recipient_id": b["id"], "content": "hi"},
    )
    assert resp.json()["msg_type"] == "text"
    assert resp.json()["attachment"] is None


def test_clear_conversation_reclaims_attachment(client):
    a, b = _register(client, "A"), _register(client, "B")
    assert _upload(client, a, b).status_code == 201
    assert len(_files_on_disk()) == 1

    resp = client.delete(f"/api/v1/messages?device_id={a['id']}&peer_id={b['id']}")
    assert resp.json()["deleted"] == 1
    assert _files_on_disk() == []
    att_url = "/api/v1/files/whatever/download"
    assert client.get(f"{att_url}?device_id={a['id']}").status_code == 404


def test_realtime_push_when_online(client):
    a, b = _register(client, "A"), _register(client, "B")
    with client.websocket_connect(f"/api/v1/ws?device_id={b['id']}") as ws_b:
        resp = _upload(client, a, b, filename="live.pdf")
        assert resp.status_code == 201
        assert resp.json()["status"] == "delivered"

        pushed = ws_b.receive_json()
        assert pushed["type"] == "message"
        assert pushed["offline"] is False
        assert pushed["data"]["msg_type"] == "file"
        assert pushed["data"]["attachment"]["name"] == "live.pdf"


def test_offline_file_flushed_on_connect(client):
    a, b = _register(client, "A"), _register(client, "B")
    assert _upload(client, a, b, filename="later.zip").json()["status"] == "pending"

    with client.websocket_connect(f"/api/v1/ws?device_id={b['id']}") as ws_b:
        pushed = ws_b.receive_json()
        assert pushed["type"] == "message"
        assert pushed["offline"] is True
        assert pushed["data"]["attachment"]["name"] == "later.zip"

    history = client.get(
        f"/api/v1/messages/history?device_id={b['id']}&peer_id={a['id']}"
    ).json()
    assert history[0]["msg_type"] == "file"
    assert history[0]["attachment"]["content_type"] == "application/zip"


@pytest.mark.parametrize("name,expected", [
    ("report.pdf", "application/pdf"),
    ("unknown.zzz", "application/octet-stream"),
    ("photo.JPG", "image/jpeg"),
])
def test_content_type_inferred_from_extension(client, name, expected):
    a, b = _register(client, "A"), _register(client, "B")
    att = _upload(client, a, b, filename=name).json()["attachment"]
    assert att["content_type"] == expected


def test_legacy_database_migrates(tmp_path):
    """旧库（无 ip / attachment_id / attachments 表）启动时自动迁移且数据不丢。"""
    from app.database import get_connection, init_db

    legacy = tmp_path / "legacy.db"
    with get_connection(legacy) as conn:
        conn.executescript(
            "CREATE TABLE devices (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
            "last_seen TEXT, created_at TEXT NOT NULL); "
            "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "sender_id TEXT NOT NULL, recipient_id TEXT NOT NULL, content TEXT NOT NULL, "
            "msg_type TEXT NOT NULL DEFAULT 'text', status TEXT NOT NULL DEFAULT 'pending', "
            "created_at TEXT NOT NULL); "
            "INSERT INTO devices VALUES ('old', '旧设备', NULL, '2026-01-01T00:00:00+00:00'); "
            "INSERT INTO messages (sender_id, recipient_id, content, created_at) "
            "VALUES ('old', 'old', '旧消息', '2026-01-01T00:00:00+00:00');"
        )
    init_db(legacy)
    with get_connection(legacy) as conn:
        dev_cols = [r[1] for r in conn.execute("PRAGMA table_info(devices)")]
        msg_cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)")]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "ip" in dev_cols
        assert "attachment_id" in msg_cols
        assert "attachments" in tables
        assert conn.execute("SELECT content FROM messages").fetchone()[0] == "旧消息"
