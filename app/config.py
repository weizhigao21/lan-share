"""全局配置。

集中管理端口、服务名、数据库路径等可调参数，避免散落在各模块。
"""
import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_MAX_UPLOAD_MB = 2048
DEFAULT_ATTACHMENT_TTL_DAYS = 7


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    """读取整数环境变量；缺失、非法或小于下限时回退默认值。

    Args:
        name: 环境变量名。
        default: 未设置或非法时的默认值。
        minimum: 允许的最小值（例如保留天数允许 0 表示永久保留）。
    """
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


@dataclass
class Settings:
    """服务配置项。"""

    app_name: str = "局域网信息互发"
    host: str = "0.0.0.0"
    port: int = 9777
    db_path: Path = BASE_DIR / "lan_share.db"
    # 超过该秒数未心跳（或未注册后活动）即视为离线，M2 接入 WebSocket 心跳后启用
    online_timeout: int = 90
    # 附件落盘目录（文件名统一为 UUID，不含原始文件名，避免路径穿越）
    upload_dir: Path = BASE_DIR / "uploads"
    # 单文件上限，默认 2 GiB；可用环境变量 LAN_SHARE_MAX_UPLOAD_MB 覆盖
    # （音频 / 视频动辄上百 MB，旧默认 100 MiB 太紧）
    max_upload_size: int = _env_int("LAN_SHARE_MAX_UPLOAD_MB", DEFAULT_MAX_UPLOAD_MB) * 1024 * 1024
    # 附件保留天数：文本消息永久保留，文件（音视频/图片/压缩包等）到期自动删除。
    # 设为 0 表示永久保留；可用环境变量 LAN_SHARE_ATTACHMENT_TTL_DAYS 覆盖。
    attachment_ttl_days: int = _env_int(
        "LAN_SHARE_ATTACHMENT_TTL_DAYS", DEFAULT_ATTACHMENT_TTL_DAYS, minimum=0
    )
    # 后台清理间隔（秒）：启动时先清一次，之后按此周期轮询
    attachment_cleanup_interval: int = _env_int(
        "LAN_SHARE_CLEANUP_INTERVAL", 3600, minimum=60
    )
    # 测试或特殊场景可整体关掉后台清理任务
    attachment_cleanup_enabled: bool = True


settings = Settings()
