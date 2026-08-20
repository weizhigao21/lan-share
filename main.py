"""局域网信息互发 — 服务入口。

启动方式：
    python main.py

首次运行会在项目根目录创建 lan_share.db（SQLite）。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.v1.devices import router as devices_router
from app.api.v1.me import router as me_router
from app.api.v1.messages import router as messages_router
from app.api.v1.ws import router as ws_router
from app.config import settings
from app.database import init_db
from app.utils.network import get_lan_ip


@asynccontextmanager
async def lifespan(_: FastAPI):
    """应用生命周期：启动时初始化数据库。"""
    init_db(settings.db_path)
    yield


app = FastAPI(title=settings.app_name, version="0.2.5", lifespan=lifespan)


@app.middleware("http")
async def no_cache_static(request, call_next):
    """静态资源禁用缓存：避免浏览器缓存旧版本 JS/CSS 导致页面错乱。"""
    response = await call_next(request)
    if request.url.path.startswith(("/js/", "/css/", "/")):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


app.include_router(devices_router, prefix="/api/v1")
app.include_router(messages_router, prefix="/api/v1")
app.include_router(me_router, prefix="/api/v1")
app.include_router(ws_router, prefix="/api/v1")
app.mount("/", StaticFiles(directory="static", html=True), name="static")


def _print_banner() -> None:
    """启动时打印访问地址，方便同网段设备加入。"""
    ip = get_lan_ip()
    print("=" * 52)
    print(f"  {settings.app_name} v0.2.5 已启动")
    print(f"  本机访问:   http://127.0.0.1:{settings.port}")
    print(f"  局域网访问: http://{ip}:{settings.port}")
    print("  手机 / 其他电脑在浏览器打开上述地址即可加入")
    print("=" * 52)


if __name__ == "__main__":
    import uvicorn

    _print_banner()
    uvicorn.run(app, host=settings.host, port=settings.port)
