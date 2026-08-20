"""pytest 夹具：隔离的临时数据库 + TestClient。"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# 确保项目根目录可导入（兼容不同 pytest 启动方式）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """提供指向临时数据库的应用测试客户端（自动执行 lifespan 建表）。"""
    monkeypatch.setattr(settings, "db_path", tmp_path / "test.db")
    with TestClient(app) as c:
        yield c
