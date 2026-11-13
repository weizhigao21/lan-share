"""文件 API：上传（作为一条消息）/ 下载 / 内联预览。

文件消息复用 messages 表：在线时 WebSocket 实时推送，离线时 status='pending'
等待目标上线后由 WS 端点补发——与文本消息完全同一条链路。
"""
import sqlite3
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.dependencies import get_db
from app.schemas import MessageOut
from app.services import device_service, file_service, message_service
from app.services.presence import presence

router = APIRouter(prefix="/files", tags=["files"])


@router.post("/upload", response_model=MessageOut, status_code=201)
async def upload_file(
    sender_id: str = Form(...),
    recipient_id: str = Form(...),
    file: UploadFile = File(...),
    db: sqlite3.Connection = Depends(get_db),
) -> MessageOut:
    """上传文件并作为一条消息发给目标设备。

    表单字段：sender_id / recipient_id / file（multipart/form-data）。
    """
    if device_service.get_device(db, sender_id) is None:
        raise HTTPException(status_code=404, detail="发送方设备不存在")
    if device_service.get_device(db, recipient_id) is None:
        raise HTTPException(status_code=404, detail="接收方设备不存在")

    try:
        att = await file_service.save_upload(db, file, sender_id)
    except file_service.UploadTooLarge:
        # 带上具体上限，避免前端只看到一个光秃秃的 413
        limit = file_service.human_size(settings.max_upload_size)
        raise HTTPException(
            status_code=413,
            detail=f"文件超过单文件上限 {limit}（可用环境变量 LAN_SHARE_MAX_UPLOAD_MB 调整）",
        ) from None

    try:
        msg = message_service.send_message(
            db,
            sender_id,
            recipient_id,
            att["name"],
            msg_type="file",
            attachment_id=att["id"],
        )
        if await presence.is_online(recipient_id):
            await presence.send_to(
                recipient_id,
                {"type": "message", "data": msg, "offline": False},
            )
            message_service.mark_delivered(db, msg["id"])
            msg["status"] = "delivered"

        out = MessageOut(**msg)
        db.commit()
        return out
    except Exception:
        # 依赖会回滚整个事务（附件行 + 消息行），磁盘文件需显式清理
        file_service.delete_attachment(db, att["id"])
        raise


@router.api_route("/{attachment_id}/download", methods=["GET", "HEAD"])
async def download_file(
    attachment_id: str,
    device_id: str,
    inline: bool = False,
    db: sqlite3.Connection = Depends(get_db),
) -> FileResponse:
    """下载附件（地址不含文件名，兼容旧链接）；图片类型可带 inline=true 内联预览。

    必须同时接受 HEAD：安卓下载器普遍先发 HEAD 探测内容长度与文件名，
    探测拿不到就会退回"随机名 + .bin"。
    """
    return _download_response(db, attachment_id, device_id, inline)


@router.api_route("/{attachment_id}/download/{filename}", methods=["GET", "HEAD"])
async def download_file_with_name(
    attachment_id: str,
    filename: str,
    device_id: str,
    inline: bool = False,
    db: sqlite3.Connection = Depends(get_db),
) -> FileResponse:
    """同上，但 URL 末段带原始文件名。

    文件名仅用于给下载器取名，实际响应使用数据库里的 original_name；
    因此传什么都不会影响取到的文件。
    """
    del filename  # 只作 URL 命名用，取值以数据库为准
    return _download_response(db, attachment_id, device_id, inline)


def _gone_detail() -> str:
    """附件不存在时的提示文案：有保留期就说清楚，避免用户以为是下载坏了。"""
    ttl = settings.attachment_ttl_days
    if ttl <= 0:
        return "附件不存在"
    return f"附件不存在或已过期清理（文件仅保留 {ttl} 天）"


def _download_response(
    db: sqlite3.Connection,
    attachment_id: str,
    device_id: str,
    inline: bool,
) -> FileResponse:
    """校验权限并构造附件响应。"""
    att = file_service.get_attachment(db, attachment_id)
    if att is None:
        raise HTTPException(status_code=404, detail=_gone_detail())
    if not file_service.can_access(db, att, device_id):
        raise HTTPException(status_code=403, detail="无权下载该附件")

    path = file_service.stored_path(att)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail=_gone_detail())

    preview = inline and file_service.is_previewable(att["content_type"])
    disposition = "inline" if preview else "attachment"
    name = att["original_name"]
    # 两个文件名都带上：filename= 给只认 ASCII 的老下载器（扩展名必须保留），
    # filename* 给支持 RFC 5987 的浏览器提供准确的原始名（含中文）
    headers = {
        "Content-Disposition": (
            f'{disposition}; filename="{file_service.ascii_disposition_name(name)}"; '
            f"filename*=UTF-8''{quote(name)}"
        ),
        "X-Content-Type-Options": "nosniff",
    }
    return FileResponse(path, media_type=att["content_type"], headers=headers)
