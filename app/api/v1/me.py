"""当前设备信息 API。"""
from fastapi import APIRouter, Request

router = APIRouter(tags=["meta"])


@router.get("/ip")
async def my_ip(request: Request) -> dict:
    """返回请求方（当前设备）的局域网 IP。

    服务端从连接对端地址获取，每台设备看到的都是自己的 IP。
    """
    client = request.client
    return {"ip": client.host if client else ""}
