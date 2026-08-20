"""WebSocket 端点：在线状态、心跳、离线消息补发。

连接地址：ws://<host>:<port>/api/v1/ws?device_id=<uuid>

协议（客户端 → 服务端）：
- {"type": "ping"}              心跳（前端每 30s 发送一次）

协议（服务端 → 客户端）：
- {"type": "pong"}              心跳应答
- {"type": "presence", "device_id": "...", "is_online": true/false}   在线状态广播
- {"type": "message", "data": {...}, "offline": true/false}           新消息（offline 标记离线补发）
"""
import asyncio
import sqlite3

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings
from app.database import get_connection
from app.services import device_service, message_service
from app.services.presence import presence

router = APIRouter(tags=["ws"])

HEARTBEAT_TIMEOUT = 90  # 秒，超过未收到心跳/任何消息则强制断开


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, device_id: str) -> None:
    """维护设备的实时连接：登记在线、推送离线消息、心跳保活。"""
    db: sqlite3.Connection = get_connection(settings.db_path)
    client_ip = ws.client.host if ws.client else None
    try:
        if device_service.get_device(db, device_id) is None:
            await ws.close(code=4004, reason="设备不存在")
            return

        await ws.accept()
        device_service.touch_device(db, device_id, client_ip)
        db.commit()
        await presence.register(device_id, ws)

        # 上线即补发离线消息（M4 离线缓存）
        await _flush_pending(db, device_id)
        db.commit()

        # 广播上线（排除自己）
        await presence.broadcast(
            {"type": "presence", "device_id": device_id, "is_online": True},
            exclude=device_id,
        )

        while True:
            try:
                data = await asyncio.wait_for(ws.receive_json(), timeout=HEARTBEAT_TIMEOUT)
            except asyncio.TimeoutError:
                await ws.close(code=4001, reason="心跳超时")
                break
            msg_type = data.get("type")
            if msg_type == "ping":
                device_service.touch_device(db, device_id, client_ip)
                db.commit()
                await ws.send_json({"type": "pong"})
            # 其余类型预留，忽略
    except WebSocketDisconnect:
        pass
    finally:
        still_online = await presence.unregister(device_id, ws)
        db.close()
        if not still_online:
            await presence.broadcast(
                {"type": "presence", "device_id": device_id, "is_online": False},
                exclude=device_id,
            )


async def _flush_pending(db: sqlite3.Connection, device_id: str) -> None:
    """将目标设备的离线消息逐条推送，并标记为已送达。"""
    for msg in message_service.pending_for(db, device_id):
        await presence.send_to(device_id, {"type": "message", "data": msg, "offline": True})
        message_service.mark_delivered(db, msg["id"])
