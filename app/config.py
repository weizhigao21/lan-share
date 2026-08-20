"""全局配置。

集中管理端口、服务名、数据库路径等可调参数，避免散落在各模块。
"""
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    """服务配置项。"""

    app_name: str = "局域网信息互发"
    host: str = "0.0.0.0"
    port: int = 9777
    db_path: Path = BASE_DIR / "lan_share.db"
    # 超过该秒数未心跳（或未注册后活动）即视为离线，M2 接入 WebSocket 心跳后启用
    online_timeout: int = 90


settings = Settings()
