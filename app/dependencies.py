"""FastAPI 依赖注入。"""
import sqlite3
from collections.abc import Iterator

from app.config import settings
from app.database import get_connection


def get_db() -> Iterator[sqlite3.Connection]:
    """请求级数据库连接依赖。

    请求处理完成后自动提交；异常时回滚；最终关闭连接。

    Yields:
        数据库连接。
    """
    conn = get_connection(settings.db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
