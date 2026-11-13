"""当前设备信息 API：来源 IP、服务参数、身份恢复与身份清除。"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.config import settings
from app.dependencies import get_db
from app.schemas import DeviceOut
from app.services import device_service

router = APIRouter(tags=["meta"])


@router.get("/ip")
async def my_ip(request: Request) -> dict:
    """返回请求方（当前设备）的局域网 IP。

    服务端从连接对端地址获取，每台设备看到的都是自己的 IP。
    """
    client = request.client
    return {"ip": client.host if client else ""}


@router.get("/meta")
async def server_meta() -> dict:
    """服务端可调参数，供前端在上传前做大小校验与保留期提示。"""
    return {
        "app_name": settings.app_name,
        "max_upload_size": settings.max_upload_size,
        "attachment_ttl_days": settings.attachment_ttl_days,
    }


@router.get("/me/device", response_model=DeviceOut)
async def who_am_i(
    request: Request,
    response: Response,
    db: sqlite3.Connection = Depends(get_db),
) -> DeviceOut:
    """找回当前浏览器的设备身份，用于浏览器清缓存 / 换内核后免重复注册。

    查找顺序：
    1. 身份 Cookie（同一浏览器最可靠）；
    2. 同来源 IP 的最近活跃设备（换了浏览器但仍是同一台手机/电脑）；
    3. 都没有 → 404，前端展示注册页。
    """
    cookie_id = request.cookies.get(device_service.DEVICE_COOKIE)
    dev = device_service.get_device(db, cookie_id) if cookie_id else None
    if dev is None:
        dev = device_service.find_by_ip(db, request.client.host if request.client else None)
    if dev is None:
        raise HTTPException(status_code=404, detail="未找到可恢复的设备身份")

    device_service.set_device_cookie(response, dev["id"])
    return DeviceOut(**dev)


@router.delete("/me/device")
async def forget_device(response: Response) -> dict:
    """清除身份 Cookie（设备身份失效或想重新注册时调用）。"""
    device_service.clear_device_cookie(response)
    return {"ok": True}
