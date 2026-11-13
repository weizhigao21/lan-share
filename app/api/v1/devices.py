"""设备相关 API 路由。

M1 范围：注册 / 列表 / 改名。M4 增加：移除离线设备（清理重复身份）。
"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.dependencies import get_db
from app.schemas import DeviceOut, DeviceRegister, DeviceRename
from app.services import device_service, file_service, message_service

router = APIRouter(prefix="/devices", tags=["devices"])


@router.post("/register", response_model=DeviceOut, status_code=201)
async def register_device(
    payload: DeviceRegister,
    request: Request,
    response: Response,
    db: sqlite3.Connection = Depends(get_db),
) -> DeviceOut:
    """注册新设备，服务端生成唯一 ID（UUID），仅返回显示名与 ID。

    同时写入设备身份 Cookie：即使浏览器清掉了 localStorage，下次打开也能认回同一台设备。
    """
    ip = request.client.host if request.client else None
    dev = device_service.register_device(db, payload.name, ip)
    device_service.set_device_cookie(response, dev["id"])
    return DeviceOut(**dev)


@router.get("", response_model=list[DeviceOut])
async def list_devices(
    db: sqlite3.Connection = Depends(get_db),
) -> list[DeviceOut]:
    """获取全部设备列表（含在线状态）。"""
    return [DeviceOut(**d) for d in device_service.list_devices(db)]


@router.patch("/{device_id}/name", response_model=DeviceOut)
async def rename_device(
    device_id: str,
    payload: DeviceRename,
    db: sqlite3.Connection = Depends(get_db),
) -> DeviceOut:
    """修改设备显示名称。"""
    dev = device_service.rename_device(db, device_id, payload.name)
    if dev is None:
        raise HTTPException(status_code=404, detail="设备不存在")
    return DeviceOut(**dev)


@router.delete("/{device_id}")
async def delete_device(
    device_id: str,
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """移除一台离线设备，连同与它相关的消息记录与附件文件。

    在线设备不允许移除（避免把正在用的会话清掉），需先关闭对应页面。
    """
    dev = device_service.get_device(db, device_id)
    if dev is None:
        raise HTTPException(status_code=404, detail="设备不存在")
    if dev["is_online"]:
        raise HTTPException(status_code=409, detail="设备在线，无法移除")

    att_ids = message_service.attachment_ids_for_clear(db, device_id)
    deleted_messages = message_service.clear_all(db, device_id)
    for att_id in att_ids:
        file_service.delete_attachment(db, att_id)
    device_service.delete_device(db, device_id)
    return {"deleted": True, "messages": deleted_messages, "attachments": len(att_ids)}
