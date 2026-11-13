"""后台定时清理任务。

启动时立即执行一轮，之后按 settings.attachment_cleanup_interval 周期轮询。
数据库操作放在线程里跑（asyncio.to_thread），避免阻塞事件循环影响 WebSocket 心跳。
每次都用独立连接，不与请求级连接共用，减少锁竞争。
"""
import asyncio
import logging
import sqlite3

from app.config import settings
from app.database import get_connection
from app.services import cleanup_service

logger = logging.getLogger(__name__)


def cleanup_once_sync() -> dict[str, int]:
    """在独立连接上执行一轮清理并提交（供线程池调用）。"""
    conn = get_connection(settings.db_path)
    try:
        stats = cleanup_service.run_once(conn)
        conn.commit()
        return stats
    finally:
        conn.close()


async def run_periodically() -> None:
    """循环执行清理，直到任务被取消。"""
    while True:
        try:
            stats = await asyncio.to_thread(cleanup_once_sync)
            if stats["files"]:
                logger.info(
                    "已清理过期附件 %d 个，释放 %d 字节，影响消息 %d 条",
                    stats["files"],
                    stats["bytes"],
                    stats["messages"],
                )
        except asyncio.CancelledError:
            raise
        except (sqlite3.Error, OSError, ValueError) as exc:
            # 清理是后台维护动作，失败不应影响服务本身，下一轮继续重试
            logger.warning("附件清理失败，将在下一轮重试：%s", exc)
        await asyncio.sleep(settings.attachment_cleanup_interval)
