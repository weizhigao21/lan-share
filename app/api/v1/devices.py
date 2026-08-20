"""设备相关 API 路由。

M1 范围：注册 / 列表 / 改名。删除与在线状态细化在后续里程碑实现。
"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request

from app.dependencies import get_db
from app.schemas import DeviceOut, DeviceRegister, DeviceRename
from app.services import device_service

router = APIRouter(prefix="/devices", tags=["devices"])


@router.post("/register", response_model=DeviceOut, status_code=201)
async def register_device(
    payload: DeviceRegister,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
) -> DeviceOut:
    """注册新设备，服务端生成唯一 ID（UUID），仅返回显示名与 ID。"""
    ip = request.client.host if request.client else None
    return DeviceOut(**device_service.register_device(db, payload.name, ip))


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
