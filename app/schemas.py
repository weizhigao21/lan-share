"""Pydantic 请求/响应模型（Pydantic v2）。"""
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class DeviceRegister(BaseModel):
    """设备注册 / 改名请求体。"""

    name: str = Field(min_length=1, max_length=32)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        """去除首尾空白，空名称视为非法。"""
        value = value.strip()
        if not value:
            raise ValueError("设备名称不能为空")
        return value


class DeviceRename(DeviceRegister):
    """设备改名请求体（校验规则同注册）。"""


class DeviceOut(BaseModel):
    """设备信息响应。

    is_online 由服务端根据 last_seen 与在线超时阈值实时计算；
    ip 为该设备最近一次连接服务端的来源地址。
    """

    id: str
    name: str
    ip: str | None = None
    is_online: bool
    last_seen: datetime
    created_at: datetime


class MessageSend(BaseModel):
    """发送消息请求体。"""

    sender_id: str
    recipient_id: str
    content: str = Field(min_length=1, max_length=2000)

    @field_validator("content")
    @classmethod
    def _strip_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("消息内容不能为空")
        return value


class AttachmentOut(BaseModel):
    """附件元信息（不含服务端磁盘路径）。

    expires_at 是自动清理时间；为 None 表示永久保留（保留期配置为 0）。
    """

    id: str
    name: str
    size: int
    content_type: str
    url: str
    expires_at: datetime | None = None


class MessageOut(BaseModel):
    """消息响应。

    msg_type='file' 时 attachment 携带附件信息；文本消息为 None。
    """

    id: int
    sender_id: str
    recipient_id: str
    content: str
    msg_type: str
    status: str
    created_at: datetime
    attachment: AttachmentOut | None = None
