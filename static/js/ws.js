/* WebSocket 客户端：连接、心跳、指数退避重连 */
class WsClient {
  constructor(deviceId, handlers) {
    this.deviceId = deviceId;
    this.handlers = handlers; // { onStatus, onMessage }
    this.ws = null;
    this.retryDelay = 1000;
    this.heartbeatTimer = null;
    this.manualClose = false;
  }

  connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${location.host}/api/v1/ws?device_id=${encodeURIComponent(this.deviceId)}`;
    this.ws = new WebSocket(url);
    this.opened = false;

    this.ws.onopen = () => {
      this.opened = true;
      this.retryDelay = 1000;
      this.handlers.onStatus?.("connected");
      // 心跳：每 30s 一次，服务端 90s 无消息会断开
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = setInterval(() => {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ type: "ping" }));
        }
      }, 30000);
    };

    this.ws.onmessage = (e) => {
      let msg;
      try {
        msg = JSON.parse(e.data);
      } catch {
        return;
      }
      this.handlers.onMessage?.(msg);
    };

    this.ws.onclose = () => {
      clearInterval(this.heartbeatTimer);
      this.handlers.onStatus?.("disconnected");
      if (this.manualClose) return;
      if (!this.opened) {
        // 握手阶段即失败：服务端可达但拒绝了连接（如设备 id 失效），
        // 不再盲目重连，交由 onRejected 决策（验证后重置身份或重建连接）
        this.handlers.onRejected?.();
        return;
      }
      // 已建立过连接后的断线 → 指数退避重连
      setTimeout(() => this.connect(), this.retryDelay);
      this.retryDelay = Math.min(this.retryDelay * 2, 30000);
    };

    this.ws.onerror = () => {
      if (this.ws) this.ws.close();
    };
  }

  close() {
    this.manualClose = true;
    clearInterval(this.heartbeatTimer);
    if (this.ws) this.ws.close();
  }
}
