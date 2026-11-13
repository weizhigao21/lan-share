"""消息业务：发送、历史、清空、离线补发。

离线消息即 status='pending' 的行：目标设备上线建立 WebSocket 后批量补发并置为 delivered。
文件消息复用同一张表：msg_type='file' + attachment_id 关联附件，因此天然支持离线缓存。
"""
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.services import file_service


def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 格式字符串。"""
    return datetime.now(timezone.utc).isoformat()


def _decorate(db: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """把消息行批量装配成响应字典：一次性查出所有附件元信息，避免 N+1 查询。"""
    items = [dict(row) for row in rows]
    att_ids = {item["attachment_id"] for item in items if item.get("attachment_id")}
    atts: dict[str, dict[str, Any]] = {}
    if att_ids:
        placeholders = ",".join("?" for _ in att_ids)
        sql = f"SELECT * FROM attachments WHERE id IN ({placeholders})"
        for row in db.execute(sql, tuple(att_ids)):
            atts[row["id"]] = file_service.attachment_out(row)
    for item in items:
        item["attachment"] = atts.get(item.pop("attachment_id", None))
    return items


def send_message(
    db: sqlite3.Connection,
    sender_id: str,
    recipient_id: str,
    content: str,
    msg_type: str = "text",
    attachment_id: str | None = None,
) -> dict[str, Any]:
    """写入一条消息，初始状态为 pending（待送达）。

    Args:
        db: 数据库连接。
        sender_id: 发送方设备 ID。
        recipient_id: 接收方设备 ID。
        content: 消息内容（文件消息为原始文件名，便于旧客户端降级显示）。
        msg_type: 'text' 或 'file'。
        attachment_id: 文件消息关联的附件 ID。

    Returns:
        消息字典（含 attachment）。
    """
    now = _now_iso()
    cur = db.execute(
        "INSERT INTO messages "
        "(sender_id, recipient_id, content, msg_type, status, created_at, attachment_id) "
        "VALUES (?, ?, ?, ?, 'pending', ?, ?)",
        (sender_id, recipient_id, content, msg_type, now, attachment_id),
    )
    row = db.execute("SELECT * FROM messages WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _decorate(db, [row])[0]


def mark_delivered(db: sqlite3.Connection, message_id: int) -> None:
    """将消息标记为已送达。"""
    db.execute("UPDATE messages SET status = 'delivered' WHERE id = ?", (message_id,))


def history(
    db: sqlite3.Connection,
    device_id: str,
    peer_id: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """查询两个设备之间的双向历史消息（按时间升序）。

    Args:
        db: 数据库连接。
        device_id: 本机设备 ID。
        peer_id: 会话对端设备 ID。
        limit: 最多返回条数。

    Returns:
        消息字典列表。
    """
    rows = db.execute(
        "SELECT * FROM messages "
        "WHERE (sender_id = ? AND recipient_id = ?) OR (sender_id = ? AND recipient_id = ?) "
        "ORDER BY id ASC LIMIT ?",
        (device_id, peer_id, peer_id, device_id, limit),
    ).fetchall()
    return _decorate(db, rows)


def pending_for(db: sqlite3.Connection, device_id: str) -> list[dict[str, Any]]:
    """查询该设备所有待送达（离线缓存）的消息。"""
    rows = db.execute(
        "SELECT * FROM messages "
        "WHERE recipient_id = ? AND status = 'pending' ORDER BY id ASC",
        (device_id,),
    ).fetchall()
    return _decorate(db, rows)


def clear_conversation(db: sqlite3.Connection, device_id: str, peer_id: str) -> int:
    """清空两个设备之间的全部消息。

    Returns:
        删除条数。
    """
    cur = db.execute(
        "DELETE FROM messages "
        "WHERE (sender_id = ? AND recipient_id = ?) OR (sender_id = ? AND recipient_id = ?)",
        (device_id, peer_id, peer_id, device_id),
    )
    return cur.rowcount


def clear_all(db: sqlite3.Connection, device_id: str) -> int:
    """清空该设备相关的全部消息（收发双向）。

    Returns:
        删除条数。
    """
    cur = db.execute(
        "DELETE FROM messages WHERE sender_id = ? OR recipient_id = ?",
        (device_id, device_id),
    )
    return cur.rowcount


def attachment_ids_for_clear(
    db: sqlite3.Connection,
    device_id: str,
    peer_id: str | None = None,
) -> list[str]:
    """列出即将被清空的消息关联的附件 ID，供路由层回收磁盘文件。"""
    if peer_id:
        rows = db.execute(
            "SELECT DISTINCT attachment_id FROM messages WHERE attachment_id IS NOT NULL "
            "AND ((sender_id = ? AND recipient_id = ?) OR (sender_id = ? AND recipient_id = ?))",
            (device_id, peer_id, peer_id, device_id),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT DISTINCT attachment_id FROM messages WHERE attachment_id IS NOT NULL "
            "AND (sender_id = ? OR recipient_id = ?)",
            (device_id, device_id),
        ).fetchall()
    return [row["attachment_id"] for row in rows]
