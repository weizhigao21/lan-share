"""设备业务逻辑：注册、查询、改名、身份恢复与清理。"""
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Response

from app.config import settings

# 设备身份 Cookie：localStorage 被清空/换浏览器时，靠它把身份认回来，
# 避免每次打开页面都注册出一个新的同名设备。
DEVICE_COOKIE = "lan_device_id"
DEVICE_COOKIE_MAX_AGE = 365 * 24 * 3600


def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 格式字符串。"""
    return datetime.now(timezone.utc).isoformat()


def _is_online(last_seen_iso: str | None) -> bool:
    """按最近活跃时间判断是否在线（M1 阶段无心跳，注册后窗口期内视为在线）。"""
    if not last_seen_iso:
        return False
    try:
        last = datetime.fromisoformat(last_seen_iso)
    except ValueError:
        return False
    return datetime.now(timezone.utc) - last < timedelta(seconds=settings.online_timeout)


def register_device(
    db: sqlite3.Connection,
    name: str,
    ip: str | None = None,
) -> dict[str, Any]:
    """注册新设备：服务端生成 UUID 作为唯一 ID。

    Args:
        db: 数据库连接。
        name: 设备显示名称（已通过 Pydantic 校验）。
        ip: 注册时的来源 IP（后续由 WS 连接/心跳持续更新）。

    Returns:
        设备字典（含 id / name / ip / last_seen / created_at）。
    """
    device_id = str(uuid.uuid4())
    now = _now_iso()
    db.execute(
        "INSERT INTO devices (id, name, ip, last_seen, created_at) VALUES (?, ?, ?, ?, ?)",
        (device_id, name, ip, now, now),
    )
    return {
        "id": device_id,
        "name": name,
        "ip": ip,
        "last_seen": now,
        "created_at": now,
        "is_online": True,  # 刚注册即活跃，窗口期内视为在线
    }


def list_devices(db: sqlite3.Connection) -> list[dict[str, Any]]:
    """查询全部设备，附带在线状态。

    Returns:
        设备字典列表，按注册时间升序。
    """
    rows = db.execute("SELECT * FROM devices ORDER BY created_at ASC").fetchall()
    return [
        {**dict(row), "is_online": _is_online(row["last_seen"])}
        for row in rows
    ]


def find_by_ip(db: sqlite3.Connection, ip: str | None) -> dict[str, Any] | None:
    """按来源 IP 找回设备（局域网内每台设备 IP 唯一）。

    同 IP 有多条记录时取最近活跃的那台，用于清过缓存的手机自动认回身份。

    Args:
        db: 数据库连接。
        ip: 请求来源 IP。

    Returns:
        设备字典；找不到返回 None。
    """
    if not ip:
        return None
    row = db.execute(
        "SELECT * FROM devices WHERE ip = ? ORDER BY last_seen DESC LIMIT 1",
        (ip,),
    ).fetchone()
    if row is None:
        return None
    return {**dict(row), "is_online": _is_online(row["last_seen"])}


def get_device(db: sqlite3.Connection, device_id: str) -> dict[str, Any] | None:
    """按 ID 查询单个设备。"""
    row = db.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if row is None:
        return None
    return {**dict(row), "is_online": _is_online(row["last_seen"])}


def rename_device(db: sqlite3.Connection, device_id: str, name: str) -> dict[str, Any] | None:
    """修改设备显示名称。

    Returns:
        更新后的设备字典；设备不存在返回 None。
    """
    cur = db.execute("UPDATE devices SET name = ? WHERE id = ?", (name, device_id))
    if cur.rowcount == 0:
        return None
    return get_device(db, device_id)


def touch_device(db: sqlite3.Connection, device_id: str, ip: str | None = None) -> None:
    """更新设备最近活跃时间（WS 上线 / 心跳时调用），并同步最新来源 IP。"""
    if ip:
        db.execute(
            "UPDATE devices SET last_seen = ?, ip = ? WHERE id = ?",
            (_now_iso(), ip, device_id),
        )
    else:
        db.execute(
            "UPDATE devices SET last_seen = ? WHERE id = ?",
            (_now_iso(), device_id),
        )


def delete_device(db: sqlite3.Connection, device_id: str) -> bool:
    """删除设备记录（消息与附件的清理由调用方负责）。

    Returns:
        是否删除成功（设备不存在返回 False）。
    """
    cur = db.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    return cur.rowcount > 0


def set_device_cookie(response: Response, device_id: str) -> None:
    """把设备 ID 写入 Cookie，供下次免注册恢复身份。"""
    response.set_cookie(
        key=DEVICE_COOKIE,
        value=device_id,
        max_age=DEVICE_COOKIE_MAX_AGE,
        path="/",
        httponly=True,
        samesite="lax",
    )


def clear_device_cookie(response: Response) -> None:
    """清除设备身份 Cookie（身份失效、重新注册前调用）。"""
    response.delete_cookie(key=DEVICE_COOKIE, path="/")
