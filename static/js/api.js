/* REST API 封装（设备 + 消息 + 文件） */
const API = {
  _currentUpload: null,

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

  /* 让服务端按 Cookie / 来源 IP 把设备身份认回来；没有可恢复身份时返回 null */
  async whoAmI() {
    const resp = await fetch("/api/v1/me/device");
    if (resp.status === 404) return null;
    if (!resp.ok) throw new Error("恢复设备身份失败");
    return resp.json();
  },

  /* 清除服务端身份 Cookie（尽力而为，失败不影响主流程） */
  async forgetDevice() {
    try {
      await fetch("/api/v1/me/device", { method: "DELETE" });
    } catch (err) {
      /* 忽略 */
    }
  },

  async deleteDevice(id) {
    const resp = await fetch(`/api/v1/devices/${encodeURIComponent(id)}`, { method: "DELETE" });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(formatDetail(data.detail) || "移除失败");
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

  /* 文件上传用 XHR（fetch 无法拿到上传进度）；返回 Promise<MessageOut> */
  uploadFile(senderId, recipientId, file, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      this._currentUpload = xhr;
      xhr.open("POST", "/api/v1/files/upload");
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
      };
      xhr.onload = () => {
        this._currentUpload = null;
        let data = {};
        try {
          data = JSON.parse(xhr.responseText);
        } catch (err) {
          /* 非 JSON 响应（如网关错误页）按状态码兜底 */
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(data);
        } else {
          reject(new Error(formatDetail(data.detail) || `上传失败 (${xhr.status})`));
        }
      };
      xhr.onerror = () => {
        this._currentUpload = null;
        reject(new Error("网络错误，上传失败"));
      };
      xhr.onabort = () => {
        this._currentUpload = null;
        reject(new Error("已取消上传"));
      };
      const form = new FormData();
      form.append("sender_id", senderId);
      form.append("recipient_id", recipientId);
      form.append("file", file, file.name);
      xhr.send(form);
    });
  },

  abortUpload() {
    if (this._currentUpload) this._currentUpload.abort();
  },

  /* 下载地址：直接用服务端给的 url（末段已带原文件名），只补 device_id / inline。
     文件名放在 URL 里，下载器即使忽略 download 属性与响应头也能取到正确名字。 */
  fileUrl(att, deviceId, inline) {
    const base = att.url || `/api/v1/files/${encodeURIComponent(att.id)}/download/${encodeURIComponent(att.name || "file")}`;
    const params = new URLSearchParams({ device_id: deviceId });
    if (inline) params.set("inline", "true");
    return base + "?" + params;
  },

  async getMyIp() {
    const resp = await fetch("/api/v1/ip");
    if (!resp.ok) throw new Error("获取本机IP失败");
    return (await resp.json()).ip;
  },

  /* 服务端配置（单文件上限等），用于上传前本地校验 */
  async getMeta() {
    const resp = await fetch("/api/v1/meta");
    if (!resp.ok) throw new Error("获取服务配置失败");
    return resp.json();
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
