"""附件有效期清理测试：过期删除 / 未过期保留 / 文本不受影响 / 孤儿回收 / 接口提示。"""

import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.database import get_connection
from app.services import cleanup_service


def _register(client, name):
    return client.post("/api/v1/devices/register", json={"name": name}).json()


def _upload(client, sender, recipient, data=b"hello", filename="note.txt"):
    return client.post(
        "/api/v1/files/upload",
        data={"sender_id": sender["id"], "recipient_id": recipient["id"]},
        files={"file": (filename, data, "application/octet-stream")},
    ).json()


def _db() -> sqlite3.Connection:
    return get_connection(settings.db_path)


def _backdate_attachment(att_id: str, days: int) -> None:
    """把附件上传时间改到 N 天前，模拟已经存放很久的文件。"""
    stamp = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _db() as conn:
        conn.execute("UPDATE attachments SET created_at = ? WHERE id = ?", (stamp, att_id))


def _history(client, a, b):
    return client.get(
        "/api/v1/messages/history", params={"device_id": a["id"], "peer_id": b["id"]}
    ).json()


def _files_on_disk():
    folder = settings.upload_dir
    return list(folder.iterdir()) if folder.is_dir() else []


def test_expired_attachment_is_deleted(client):
    a, b = _register(client, "A"), _register(client, "B")
    att = _upload(client, a, b, filename="老歌.flac")["attachment"]
    _backdate_attachment(att["id"], 8)

    with _db() as conn:
        stats = cleanup_service.purge_expired(conn)
        conn.commit()

    assert stats["files"] == 1
    assert stats["messages"] == 1
    assert _files_on_disk() == []
    with _db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 0


def test_expired_file_message_keeps_timeline(client):
    """文件被清理后消息仍在，只是变成「已过期」提示，聊天记录不断档。"""
    a, b = _register(client, "A"), _register(client, "B")
    att = _upload(client, a, b, filename="老歌.flac")["attachment"]
    _backdate_attachment(att["id"], 8)

    with _db() as conn:
        cleanup_service.purge_expired(conn)
        conn.commit()

    history = _history(client, a, b)
    assert len(history) == 1
    msg = history[0]
    assert msg["msg_type"] == "file_expired"
    assert msg["content"] == "老歌.flac"
    assert msg["attachment"] is None


def test_text_messages_are_never_cleaned(client):
    """文本消息永久保留：清理只针对附件。"""
    a, b = _register(client, "A"), _register(client, "B")
    client.post(
        "/api/v1/messages",
        json={"sender_id": a["id"], "recipient_id": b["id"], "content": "这条要一直在"},
    )

    with _db() as conn:
        stats = cleanup_service.run_once(conn)
        conn.commit()

    assert stats["files"] == 0
    history = _history(client, a, b)
    assert [m["content"] for m in history] == ["这条要一直在"]
    assert history[0]["msg_type"] == "text"


def test_fresh_attachment_is_kept(client):
    a, b = _register(client, "A"), _register(client, "B")
    att = _upload(client, a, b)["attachment"]

    with _db() as conn:
        stats = cleanup_service.purge_expired(conn)
        conn.commit()

    assert stats["files"] == 0
    assert len(_files_on_disk()) == 1
    assert _history(client, a, b)[0]["attachment"]["id"] == att["id"]


def test_ttl_zero_disables_cleanup(client, monkeypatch):
    monkeypatch.setattr(settings, "attachment_ttl_days", 0)
    a, b = _register(client, "A"), _register(client, "B")
    att = _upload(client, a, b)["attachment"]
    _backdate_attachment(att["id"], 3650)

    with _db() as conn:
        stats = cleanup_service.purge_expired(conn)
        conn.commit()

    assert stats["files"] == 0
    assert len(_files_on_disk()) == 1


def test_attachment_reports_expiry(client):
    a, b = _register(client, "A"), _register(client, "B")
    att = _upload(client, a, b)["attachment"]

    assert att["expires_at"] is not None
    expires = datetime.fromisoformat(att["expires_at"])
    delta = expires - datetime.now(timezone.utc)
    # 默认保留 7 天，允许几分钟误差
    assert timedelta(days=6, hours=23) < delta < timedelta(days=7, minutes=5)


def test_download_after_cleanup_explains_expiry(client):
    a, b = _register(client, "A"), _register(client, "B")
    att = _upload(client, a, b)["attachment"]
    _backdate_attachment(att["id"], 8)

    with _db() as conn:
        cleanup_service.purge_expired(conn)
        conn.commit()

    resp = client.get(f"{att['url']}", params={"device_id": b["id"]})
    assert resp.status_code == 404
    assert "过期" in resp.json()["detail"]


def test_orphan_files_are_reclaimed(client):
    """uploads/ 里没有数据库记录的陈旧 UUID 文件会被回收。"""
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    orphan = settings.upload_dir / ("a" * 32)
    orphan.write_bytes(b"stale")
    old = time.time() - 3 * 3600
    os.utime(orphan, (old, old))

    with _db() as conn:
        stats = cleanup_service.purge_orphan_files(conn)
        conn.commit()

    assert stats["files"] == 1
    assert not orphan.exists()


def test_orphan_scan_skips_uploading_and_foreign_files(client):
    """保护期内的文件（可能正在上传）与非 UUID 命名的文件都不动。"""
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    uploading = settings.upload_dir / ("b" * 32)
    uploading.write_bytes(b"in flight")
    keep = settings.upload_dir / "我的笔记.txt"
    keep.write_text("手放进来的", encoding="utf-8")

    with _db() as conn:
        stats = cleanup_service.purge_orphan_files(conn)
        conn.commit()

    assert stats["files"] == 0
    assert uploading.exists()
    assert keep.exists()


def test_worker_single_run_uses_settings_path(client):
    """后台任务用独立连接跑一轮，不依赖请求上下文。"""
    from app.services import cleanup_worker

    a, b = _register(client, "A"), _register(client, "B")
    att = _upload(client, a, b)["attachment"]
    _backdate_attachment(att["id"], 10)

    stats = cleanup_worker.cleanup_once_sync()

    assert stats["files"] == 1
    assert _files_on_disk() == []


def test_meta_exposes_retention(client):
    meta = client.get("/api/v1/meta").json()
    assert meta["attachment_ttl_days"] == settings.attachment_ttl_days
