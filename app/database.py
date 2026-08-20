"""SQLite 数据访问层：连接管理与建表。

使用标准库 sqlite3，单文件存储（lan_share.db），局域网设备规模下无需独立数据库服务。
"""
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    ip         TEXT,
    last_seen  TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id    TEXT NOT NULL,
    recipient_id TEXT NOT NULL,
    content      TEXT NOT NULL,
    msg_type     TEXT NOT NULL DEFAULT 'text',
    status       TEXT NOT NULL DEFAULT 'pending',
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_recipient ON messages(recipient_id, status);
CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender_id);
"""


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """为已存在的表补齐缺失列（轻量迁移）。"""
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def get_connection(db_path: Path | str) -> sqlite3.Connection:
    """打开数据库连接。

    Args:
        db_path: 数据库文件路径。

    Returns:
        配置好 row_factory 的连接对象。
    """
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | str) -> None:
    """初始化数据库表结构（幂等，可重复调用），并对旧库补齐新列。"""
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)
        _ensure_column(conn, "devices", "ip", "TEXT")
