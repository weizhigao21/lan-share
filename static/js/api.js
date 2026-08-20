/* REST API 封装（M3：设备 + 消息） */
const API = {
  async register(name) {
    const resp = await fetch("/api/v1/devices/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(formatDetail(data.detail) || "注册失败");
    }
    return data;
  },

  async listDevices() {
    const resp = await fetch("/api/v1/devices");
    if (!resp.ok) throw new Error("获取设备列表失败");
    return resp.json();
  },

  async rename(id, name) {
    const resp = await fetch(`/api/v1/devices/${encodeURIComponent(id)}/name`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(formatDetail(data.detail) || "改名失败");
    }
    return data;
  },

  async send(senderId, recipientId, content) {
    const resp = await fetch("/api/v1/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sender_id: senderId, recipient_id: recipientId, content }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(formatDetail(data.detail) || "发送失败");
    }
    return data;
  },

  async history(deviceId, peerId) {
    const params = new URLSearchParams({ device_id: deviceId, peer_id: peerId });
    const resp = await fetch(`/api/v1/messages/history?${params}`);
    if (!resp.ok) throw new Error("获取历史消息失败");
    return resp.json();
  },

  async clearHistory(deviceId, peerId) {
    const params = new URLSearchParams({ device_id: deviceId, peer_id: peerId });
    const resp = await fetch(`/api/v1/messages?${params}`, { method: "DELETE" });
    if (!resp.ok) throw new Error("清空失败");
    return resp.json();
  },

  async getMyIp() {
    const resp = await fetch("/api/v1/ip");
    if (!resp.ok) throw new Error("获取本机IP失败");
    return (await resp.json()).ip;
  },
};

function formatDetail(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const first = detail[0];
    if (first && first.msg) return first.msg;
  }
  return null;
}
