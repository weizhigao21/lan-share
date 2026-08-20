"""消息业务：发送、历史、清空、离线补发。

离线消息即 status='pending' 的行：目标设备上线建立 WebSocket 后批量补发并置为 delivered。
"""
import sqlite3
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 格式字符串。"""
    return datetime.now(timezone.utc).isoformat()


def send_message(
    db: sqlite3.Connection,
    sender_id: str,
    recipient_id: str,
    content: str,
) -> dict[str, Any]:
    """写入一条消息，初始状态为 pending（待送达）。

    Args:
        db: 数据库连接。
        sender_id: 发送方设备 ID。
        recipient_id: 接收方设备 ID。
        content: 消息内容。

    Returns:
        消息字典。
    """
    now = _now_iso()
    cur = db.execute(
        "INSERT INTO messages (sender_id, recipient_id, content, status, created_at) "
        "VALUES (?, ?, ?, 'pending', ?)",
        (sender_id, recipient_id, content, now),
    )
    return {
        "id": cur.lastrowid,
        "sender_id": sender_id,
        "recipient_id": recipient_id,
        "content": content,
        "msg_type": "text",
        "status": "pending",
        "created_at": now,
    }


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
    return [dict(row) for row in rows]


def pending_for(db: sqlite3.Connection, device_id: str) -> list[dict[str, Any]]:
    """查询该设备所有待送达（离线缓存）的消息。"""
    rows = db.execute(
        "SELECT * FROM messages "
        "WHERE recipient_id = ? AND status = 'pending' ORDER BY id ASC",
        (device_id,),
    ).fetchall()
    return [dict(row) for row in rows]


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
