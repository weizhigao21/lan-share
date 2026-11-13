"""附件业务：流式落盘、元数据登记、下载校验与清理。

设计要点：
- 磁盘文件名一律使用 UUID（32 位十六进制），原始文件名只存数据库，杜绝路径穿越；
- 文件本身不入库，仅登记元信息；消息通过 messages.attachment_id 关联；
- Content-Type 由服务端按扩展名推断，不信任客户端声明，避免上传 HTML 后同源执行脚本。
"""
import mimetypes
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import UploadFile

from app.config import settings
from app.services import cleanup_service

CHUNK_SIZE = 256 * 1024
SAFE_NAME_MAX = 180

# 常见类型显式映射，避免不同系统 mimetypes 注册表差异
COMMON_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".zip": "application/zip",
    ".mp4": "video/mp4",
    ".mp3": "audio/mpeg",
}

# 仅这些类型允许 inline 预览（排除 SVG 等可能携带脚本的类型）。
# 图片内嵌对话框、视频/音频内嵌播放器都依赖此白名单——不在名单内的
# inline=true 会退化为 attachment，媒体元素将拒绝加载。
PREVIEWABLE_TYPES = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
    "video/mp4", "video/webm", "video/ogg",
    "audio/mpeg", "audio/mp4", "audio/aac",
    "audio/wav", "audio/x-wav", "audio/ogg", "audio/flac",
}


class UploadTooLarge(Exception):
    """上传文件超过配置上限。"""


def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 格式字符串。"""
    return datetime.now(timezone.utc).isoformat()


def safe_filename(name: str | None) -> str:
    """清洗原始文件名：去路径、去控制字符与非法字符，限制长度。"""
    base = (name or "unnamed").replace("\\", "/").split("/")[-1]
    base = "".join(c for c in base if ord(c) >= 32 and c not in '<>:"|?*;')
    base = base.strip(" .")[:SAFE_NAME_MAX].strip(" .")
    return base or "unnamed"


def ascii_disposition_name(name: str) -> str:
    """生成 Content-Disposition 里 ASCII 安全的文件名，**始终保留扩展名**。

    部分安卓浏览器与非标准下载器只解析第一个 `filename=`，忽略 RFC 5987 的
    `filename*`。若此处把扩展名丢掉，在 application/octet-stream 下浏览器
    会自行补上 `.bin`——这正是"下载后变成一串数字.bin"的成因之一。
    """
    stem, ext = os.path.splitext(name)
    ext = "".join(c for c in ext if ord(c) < 128 and (c.isalnum() or c == "."))
    safe_stem = "".join(
        c for c in stem if ord(c) < 128 and c not in '<>:"/\\|?*;'
    ).strip(" .")
    return (safe_stem or "file") + ext


def download_url(att_id: str, name: str) -> str:
    """下载地址：末段带上原始文件名。

    文件名必须出现在 URL 里——浏览器原生下载器、安卓内置 WebView 的下载桥接
    都可能忽略 `download` 属性与响应头，只能从 URL 末段取名字。
    """
    return f"/api/v1/files/{att_id}/download/{quote(name, safe='')}"


def guess_content_type(name: str) -> str:
    """按原始文件名扩展名推断 MIME 类型。"""
    ext = Path(name).suffix.lower()
    if ext in COMMON_TYPES:
        return COMMON_TYPES[ext]
    guessed, _ = mimetypes.guess_type(name)
    return guessed or "application/octet-stream"


def is_previewable(content_type: str) -> bool:
    """是否允许在浏览器中内联预览（白名单：位图 / 常见音视频）。"""
    return content_type in PREVIEWABLE_TYPES


def human_size(size: int) -> str:
    """把字节数格式化成便于阅读的字符串（用于错误提示）。"""
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(size)
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    if idx == 0:
        return f"{int(value)} {units[idx]}"
    return f"{value:.0f} {units[idx]}" if value >= 10 else f"{value:.1f} {units[idx]}"


def attachment_out(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    """把附件行转换为对外响应的附件字典。

    expires_at 为按保留期推算的清理时间（永久保留时为 None），
    前端据此提示「还有几天被清理」。
    """
    att_id = row["id"]
    # 注意：sqlite3.Row 没有 __contains__，`"created_at" in row` 会遍历「值」而不是键，
    # 必须先取 keys()；dict 与 Row 都支持 keys()。
    keys = row.keys()
    created_at = row["created_at"] if "created_at" in keys else None
    expires = cleanup_service.expires_at(created_at) if created_at else None
    return {
        "id": att_id,
        "name": row["original_name"],
        "size": row["size"],
        "content_type": row["content_type"],
        "url": download_url(att_id, row["original_name"]),
        "expires_at": expires.isoformat() if expires is not None else None,
    }


def get_attachment(db: sqlite3.Connection, att_id: str) -> dict[str, Any] | None:
    """按 ID 查询附件元信息。"""
    row = db.execute("SELECT * FROM attachments WHERE id = ?", (att_id,)).fetchone()
    return dict(row) if row is not None else None


def stored_path(att: dict[str, Any]) -> Path | None:
    """返回附件的磁盘路径；存储名非法时返回 None（防止路径穿越）。"""
    stored = str(att["stored_name"])
    if not re.fullmatch(r"[0-9a-f]{32}", stored):
        return None
    return settings.upload_dir / stored


async def save_upload(
    db: sqlite3.Connection,
    upload: UploadFile,
    uploader_id: str,
) -> dict[str, Any]:
    """流式保存上传文件并登记附件元信息。

    Args:
        db: 数据库连接（由请求依赖注入，异常时整体回滚）。
        upload: 上传文件对象。
        uploader_id: 上传方设备 ID。

    Returns:
        对外附件字典（含下载 url）。

    Raises:
        UploadTooLarge: 文件超过 settings.max_upload_size。
    """
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    att_id = uuid.uuid4().hex
    original_name = safe_filename(upload.filename)
    content_type = guess_content_type(original_name)
    path = settings.upload_dir / att_id

    total = 0
    try:
        with path.open("wb") as f:
            while True:
                chunk = await upload.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.max_upload_size:
                    raise UploadTooLarge("文件超过大小上限")
                f.write(chunk)
    except BaseException:
        # 含客户端断连（CancelledError）：不留半截文件
        path.unlink(missing_ok=True)
        raise

    now = _now_iso()
    db.execute(
        "INSERT INTO attachments "
        "(id, original_name, stored_name, size, content_type, uploader_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (att_id, original_name, att_id, total, content_type, uploader_id, now),
    )
    return attachment_out({
        "id": att_id,
        "original_name": original_name,
        "size": total,
        "content_type": content_type,
        "created_at": now,
    })


def delete_attachment(db: sqlite3.Connection, att_id: str) -> None:
    """删除附件记录与磁盘文件（幂等）。"""
    att = get_attachment(db, att_id)
    if att is None:
        return
    path = stored_path(att)
    if path is not None:
        path.unlink(missing_ok=True)
    db.execute("DELETE FROM attachments WHERE id = ?", (att_id,))


def unlink_stored(att: dict[str, Any]) -> None:
    """仅删除磁盘文件（用于事务回滚时清理，不改数据库）。"""
    path = stored_path(att)
    if path is not None:
        path.unlink(missing_ok=True)


def can_access(db: sqlite3.Connection, att: dict[str, Any], device_id: str) -> bool:
    """下载权限：上传者本人，或该附件所关联消息的收/发双方。"""
    if att["uploader_id"] == device_id:
        return True
    hit = db.execute(
        "SELECT 1 FROM messages WHERE attachment_id = ? "
        "AND (sender_id = ? OR recipient_id = ?) LIMIT 1",
        (att["id"], device_id, device_id),
    ).fetchone()
    return hit is not None
