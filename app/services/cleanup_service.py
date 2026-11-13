"""过期附件清理：文本消息永久保留，文件类附件按保留期自动删除。

清理策略（按需在后台定时执行，也可手动调用）：
1. 附件行 created_at 早于保留期 → 删除磁盘文件、删除 attachments 行，
   并把关联消息标记为 msg_type='file_expired'（消息本身保留，聊天记录不断档）；
2. uploads/ 下没有数据库记录的孤儿文件（UUID 命名且足够旧）→ 直接回收。

注意：只按「上传时间」判断，与是否已送达无关。对方长期离线导致文件过期时，
补发的消息会是一条「文件已过期清理」的提示，而不是丢失整条记录。
"""
import logging
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# 消息/附件批量处理：SQLite 的 IN (...) 参数个数有历史上限（999），分批更稳
_BATCH_SIZE = 200

# 孤儿文件保护期：上传流程是「先流式落盘、再入库」，进行中的大文件上传在库里
# 还查不到记录，必须留足时间窗口，避免清理任务把正在上传的文件删掉。
ORPHAN_MIN_AGE_SECONDS = 2 * 3600

_UUID_NAME = re.compile(r"[0-9a-f]{32}")


def _now() -> datetime:
    """当前 UTC 时间。"""
    return datetime.now(timezone.utc)


def cutoff_time(days: int) -> datetime | None:
    """返回过期时间点；保留期 <= 0 时返回 None 表示永不清理。"""
    if days <= 0:
        return None
    return _now() - timedelta(days=days)


def expires_at(created_at: str, days: int | None = None) -> datetime | None:
    """按附件上传时间推算清理时间；保留期 <= 0 时返回 None。

    Args:
        created_at: 附件 created_at 字段（UTC ISO 字符串）。
        days: 保留天数，默认取全局配置。

    Returns:
        到期时间（带时区）；无法解析或永久保留时为 None。
    """
    ttl = settings.attachment_ttl_days if days is None else days
    if ttl <= 0:
        return None
    try:
        created = datetime.fromisoformat(created_at)
    except (TypeError, ValueError):
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created + timedelta(days=ttl)


def _chunks(items: list[Any], size: int = _BATCH_SIZE) -> list[list[Any]]:
    """把列表切成固定大小的批次。"""
    return [items[i:i + size] for i in range(0, len(items), size)]


def purge_expired(db: sqlite3.Connection, days: int | None = None) -> dict[str, int]:
    """删除超过保留期的附件文件与记录。

    关联消息不会被删除，而是标记为 msg_type='file_expired' 且清空 attachment_id，
    这样聊天记录仍在，只是文件不可再下载。

    Args:
        db: 数据库连接（调用方负责 commit）。
        days: 保留天数，默认取 settings.attachment_ttl_days。

    Returns:
        {"files": 删除文件数, "bytes": 释放字节数, "messages": 影响消息数}
    """
    ttl = settings.attachment_ttl_days if days is None else days
    cut = cutoff_time(ttl)
    stats = {"files": 0, "bytes": 0, "messages": 0}
    if cut is None:
        return stats

    rows = db.execute(
        "SELECT id, stored_name, size FROM attachments WHERE created_at < ?",
        (cut.isoformat(),),
    ).fetchall()
    if not rows:
        return stats

    expired = [dict(row) for row in rows]
    for att in expired:
        stored = str(att["stored_name"])
        if _UUID_NAME.fullmatch(stored):
            path = settings.upload_dir / stored
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                # 文件被占用（如正在下载）时先记账失败，下次轮次重试
                logger.warning("删除过期附件失败 %s: %s", path, exc)
                continue
        stats["files"] += 1
        stats["bytes"] += int(att["size"] or 0)

    removed_ids = [att["id"] for att in expired]
    for chunk in _chunks(removed_ids):
        placeholders = ",".join("?" for _ in chunk)
        cur = db.execute(
            f"UPDATE messages SET msg_type = 'file_expired', attachment_id = NULL "
            f"WHERE attachment_id IN ({placeholders})",
            tuple(chunk),
        )
        stats["messages"] += max(cur.rowcount, 0)
        db.execute(f"DELETE FROM attachments WHERE id IN ({placeholders})", tuple(chunk))

    return stats


def purge_orphan_files(
    db: sqlite3.Connection,
    min_age_seconds: int = ORPHAN_MIN_AGE_SECONDS,
) -> dict[str, int]:
    """回收 uploads/ 里没有数据库记录的孤儿文件。

    只处理「32 位十六进制命名 + 存在时间超过保护期」的文件，
    避免误删正在上传的文件或用户手工放进目录的内容。

    Returns:
        {"files": 删除文件数, "bytes": 释放字节数}
    """
    stats = {"files": 0, "bytes": 0}
    folder = settings.upload_dir
    if not folder.is_dir():
        return stats

    known = {
        row["stored_name"]
        for row in db.execute("SELECT stored_name FROM attachments")
    }
    now = time.time()
    for entry in folder.iterdir():
        if not entry.is_file() or entry.name in known:
            continue
        if not _UUID_NAME.fullmatch(entry.name):
            continue
        try:
            info = entry.stat()
        except OSError:
            continue
        if now - info.st_mtime < min_age_seconds:
            continue
        try:
            entry.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("删除孤儿文件失败 %s: %s", entry, exc)
            continue
        stats["files"] += 1
        stats["bytes"] += info.st_size
    return stats


def run_once(db: sqlite3.Connection) -> dict[str, int]:
    """执行一轮完整清理（过期附件 + 孤儿文件），返回合并后的统计。"""
    expired = purge_expired(db)
    orphan = purge_orphan_files(db)
    return {
        "files": expired["files"] + orphan["files"],
        "bytes": expired["bytes"] + orphan["bytes"],
        "messages": expired["messages"],
    }
