"""在线状态管理器：内存维护 设备ID → WebSocket 连接集合。

所有设备共享同一进程内的单例（presence），供 HTTP 路由与 WS 端点协作：
- HTTP 发送消息时判断目标在线 → 直接推送
- WS 端点连接/断开时登记与注销 → 广播在线状态
"""
import asyncio
import json
from collections import defaultdict

from fastapi import WebSocket


class PresenceManager:
    """集中管理设备在线状态与消息推送。"""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def register(self, device_id: str, ws: WebSocket) -> None:
        """登记一个 WebSocket 连接。"""
        async with self._lock:
            self._connections[device_id].add(ws)

    async def unregister(self, device_id: str, ws: WebSocket) -> bool:
        """移除一个连接。

        Returns:
            该设备是否仍有其他连接存活（True 表示仍在线）。
        """
        async with self._lock:
            conns = self._connections.get(device_id)
            if conns is None:
                return False
            conns.discard(ws)
            if not conns:
                self._connections.pop(device_id, None)
                return False
            return True

    async def is_online(self, device_id: str) -> bool:
        """判断设备当前是否在线。"""
        async with self._lock:
            return bool(self._connections.get(device_id))

    async def send_to(self, device_id: str, payload: dict) -> bool:
        """向设备的所有连接推送 JSON 消息。

        Returns:
            是否至少送达一个连接（离线设备返回 False）。
        """
        async with self._lock:
            conns = list(self._connections.get(device_id, ()))
        if not conns:
            return False
        text = json.dumps(payload, ensure_ascii=False)
        delivered = False
        for ws in conns:
            try:
                await ws.send_text(text)
                delivered = True
            except RuntimeError:
                # 连接已关闭，忽略
                continue
        return delivered

    async def broadcast(self, payload: dict, exclude: str | None = None) -> None:
        """向全部在线设备广播（可排除指定设备，如自己）。"""
        async with self._lock:
            targets = {
                did: list(conns)
                for did, conns in self._connections.items()
                if did != exclude
            }
        text = json.dumps(payload, ensure_ascii=False)
        for conns in targets.values():
            for ws in conns:
                try:
                    await ws.send_text(text)
                except RuntimeError:
                    continue


presence = PresenceManager()
