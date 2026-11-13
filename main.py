"""局域网信息互发 — 服务入口。

启动方式：
    python main.py

首次运行会在项目根目录创建 lan_share.db（SQLite）。
"""
import asyncio
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.v1.devices import router as devices_router
from app.api.v1.files import router as files_router
from app.api.v1.me import router as me_router
from app.api.v1.messages import router as messages_router
from app.api.v1.ws import router as ws_router
from app.config import settings
from app.database import init_db
from app.services import cleanup_worker
from app.utils.network import get_lan_ip


@asynccontextmanager
async def lifespan(_: FastAPI):
    """应用生命周期：启动时初始化数据库，并拉起附件有效期清理任务。"""
    init_db(settings.db_path)
    task = None
    if settings.attachment_cleanup_enabled:
        task = asyncio.create_task(cleanup_worker.run_periodically())
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(title=settings.app_name, version="0.4.0", lifespan=lifespan)


@app.middleware("http")
async def no_cache_static(request, call_next):
    """静态资源禁用缓存：避免浏览器缓存旧版本 JS/CSS 导致页面错乱。"""
    response = await call_next(request)
    if request.url.path.startswith(("/js/", "/css/", "/")):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


app.include_router(devices_router, prefix="/api/v1")
app.include_router(messages_router, prefix="/api/v1")
app.include_router(files_router, prefix="/api/v1")
app.include_router(me_router, prefix="/api/v1")
app.include_router(ws_router, prefix="/api/v1")
app.mount("/", StaticFiles(directory="static", html=True), name="static")


def _enable_windows_ansi() -> bool:
    """让 Windows 控制台按 ANSI 序列解析颜色。

    双击 .bat 打开的是旧版 conhost，默认关闭虚拟终端解析，uvicorn 的彩色日志会
    打印成 ``[32mINFO[0m`` 这样的乱码。开启成功返回 True；开启不了（比如输出被重定向）
    返回 False，由调用方关掉彩色日志。

    Returns:
        当前控制台是否能正确解析 ANSI 颜色码。
    """
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        # 0x0004 = ENABLE_VIRTUAL_TERMINAL_PROCESSING
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError, ValueError):
        # 非标准控制台（如 ConEmu / 重定向）下 ctypes 调用可能失败，退回无色输出
        return False


def _print_banner() -> None:
    """启动时打印访问地址，方便同网段设备加入。"""
    ip = get_lan_ip()
    print("=" * 52)
    print(f"  {settings.app_name} v0.4.0 已启动")
    print(f"  本机访问:   http://127.0.0.1:{settings.port}")
    print(f"  局域网访问: http://{ip}:{settings.port}")
    print("  手机 / 其他电脑在浏览器打开上述地址即可加入")
    print("=" * 52)


if __name__ == "__main__":
    import uvicorn

    use_colors = _enable_windows_ansi()
    _print_banner()
    uvicorn.run(app, host=settings.host, port=settings.port, use_colors=use_colors)
