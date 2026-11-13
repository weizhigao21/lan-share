"""消息 API 路由：发送 / 历史 / 清空。

发送策略（核心：信息缓存，上线补发）：
- 目标在线 → 实时 WebSocket 推送，状态置 delivered
- 目标离线 → 落库 status='pending'，等目标上线后由 WS 端点批量补发
"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_db
from app.schemas import MessageOut, MessageSend
from app.services import device_service, file_service, message_service
from app.services.presence import presence

router = APIRouter(prefix="/messages", tags=["messages"])


@router.post("", response_model=MessageOut, status_code=201)
async def send_message(
    payload: MessageSend,
    db: sqlite3.Connection = Depends(get_db),
) -> MessageOut:
    """发送一条字符消息：目标在线实时推送，离线则缓存待补发。"""
    if device_service.get_device(db, payload.sender_id) is None:
        raise HTTPException(status_code=404, detail="发送方设备不存在")
    if device_service.get_device(db, payload.recipient_id) is None:
        raise HTTPException(status_code=404, detail="接收方设备不存在")

    msg = message_service.send_message(db, payload.sender_id, payload.recipient_id, payload.content)

    if await presence.is_online(payload.recipient_id):
        await presence.send_to(payload.recipient_id, {"type": "message", "data": msg, "offline": False})
        message_service.mark_delivered(db, msg["id"])
        msg["status"] = "delivered"

    db.commit()
    return MessageOut(**msg)


@router.get("/history", response_model=list[MessageOut])
async def get_history(
    device_id: str,
    peer_id: str,
    db: sqlite3.Connection = Depends(get_db),
) -> list[MessageOut]:
    """获取本机设备与指定对端之间的历史消息（按时间升序）。"""
    return [
        MessageOut(**m)
        for m in message_service.history(db, device_id, peer_id)
    ]


@router.delete("")
async def clear_messages(
    device_id: str,
    peer_id: str | None = None,
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """清空消息记录：传 peer_id 清空指定会话；不传则清空该设备全部消息。

    同时回收这些消息关联的附件磁盘文件，避免清理后仍占用空间。
    """
    att_ids = message_service.attachment_ids_for_clear(db, device_id, peer_id)
    if peer_id:
        deleted = message_service.clear_conversation(db, device_id, peer_id)
        scope = "conversation"
    else:
        deleted = message_service.clear_all(db, device_id)
        scope = "all"
    for att_id in att_ids:
        file_service.delete_attachment(db, att_id)
    db.commit()
    return {"scope": scope, "deleted": deleted}
