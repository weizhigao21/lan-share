/* 页面主逻辑（M3：设备列表 + 实时聊天） */
const LS_DEVICE_ID = "lan_share_device_id";
const LS_DEVICE_NAME = "lan_share_device_name";

/* 隐私模式/无痕窗口下 localStorage 可能抛 SecurityError，统一安全访问 */
function safeGet(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* 存储不可用时降级为"本次会话内有效"，不阻断功能 */
  }
}

function safeRemove(key) {
  try {
    localStorage.removeItem(key);
  } catch {
    /* 忽略 */
  }
}

const state = {
  deviceId: safeGet(LS_DEVICE_ID),
  deviceName: safeGet(LS_DEVICE_NAME),
  devices: [],
  peer: null,      // 当前会话对端 {id, name}
  messages: [],    // 当前会话消息
  unread: {},      // 对端 id -> 未读数
  ws: null,
};

function $(sel) {
  return document.querySelector(sel);
}

function showView(viewSel) {
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  const target = $(viewSel);
  if (target) {
    target.classList.remove("hidden");
  }
}

function escapeHtml(value) {
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(value).replace(/[&<>"']/g, (c) => map[c]);
}

function setStatus(text) {
  showToast(text);
}

/* 轻量 toast：顶部居中短暂提示，自动消失 */
function showToast(text) {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    document.body.appendChild(el);
  }
  el.textContent = text;
  el.classList.remove("hide");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.add("hide"), 2600);
}

/* ---------- 设备列表 ---------- */

async function loadDevices() {
  try {
    state.devices = await API.listDevices();
    renderDevices();
  } catch (err) {
    setStatus("连接失败: " + err.message);
  }
}

/* 实时通道状态 → 顶栏连接圆点（绿=已连接，灰=断开） */
function setConnState(connected) {
  const dot = $("#connDot");
  if (!dot) return;
  dot.classList.toggle("connected", connected);
  dot.title = connected ? "实时通道已连接" : "实时通道断开，重连中…";
}

function renderDevices() {
  const list = $("#deviceList");
  list.innerHTML = "";
  const onlineCount = state.devices.filter((d) => d.is_online).length;
  $("#onlineCount").textContent = `(${state.devices.length} 台 · ${onlineCount} 在线)`;

  const sorted = [...state.devices].sort(
    (a, b) => (b.is_online - a.is_online) || a.name.localeCompare(b.name, "zh")
  );

  if (!sorted.length) {
    list.innerHTML = '<li class="empty">还没有其他设备加入</li>';
    return;
  }

  sorted.forEach((d) => {
    const li = document.createElement("li");
    li.className = "device-item" + (state.peer && state.peer.id === d.id ? " active" : "");
    const isMe = d.id === state.deviceId;
    const unread = state.unread[d.id] || 0;
    li.innerHTML = `
      <span class="status-dot ${d.is_online ? "online" : "offline"}"></span>
      <div class="device-info">
        <div class="device-name">${escapeHtml(d.name)}${isMe ? " <em>(我)</em>" : ""}</div>
        ${d.ip ? `<div class="device-ip">${escapeHtml(d.ip)}</div>` : ""}
      </div>
      ${unread ? `<span class="badge">${unread}</span>` : ""}
      <span class="device-state ${d.is_online ? "online" : ""}">${d.is_online ? "在线" : "离线"}</span>`;
    li.addEventListener("click", () => openChat(d));
    list.appendChild(li);
  });
}

/* ---------- 会话 ---------- */

async function openChat(device) {
  state.peer = { id: device.id, name: device.name };
  state.unread[device.id] = 0;
  $("#chatPeerName").textContent = device.name;
  $("#chatPeerState").textContent = device.is_online ? "在线" : "离线";
  $("#backBtn").classList.toggle("hidden", window.innerWidth >= 768);
  document.body.classList.add("chatting");

  try {
    state.messages = await API.history(state.deviceId, device.id);
  } catch (err) {
    state.messages = [];
    setStatus("加载历史失败: " + err.message);
  }
  renderMessages();
  enableInput(true);
  $("#messageInput").focus();
}

function backToDevices() {
  document.body.classList.remove("chatting");
}

function enableInput(enabled) {
  $("#messageInput").disabled = !enabled;
  $("#sendBtn").disabled = !enabled;
}

/* ---------- 消息渲染 ---------- */

function renderMessages() {
  const list = $("#messageList");
  list.innerHTML = "";
  if (!state.messages.length) {
    list.innerHTML = '<div class="empty-hint">还没有消息，发一条吧</div>';
  }
  state.messages.forEach((m) => appendMessageDOM(list, m, {}));
  scrollToBottom();
}

function appendMessageDOM(list, msg, opts) {
  if (opts.offline) {
    const tip = document.createElement("div");
    tip.className = "sys-tip";
    tip.textContent = "对方上线了，离线消息已送达";
    list.appendChild(tip);
  }
  const div = document.createElement("div");
  div.className = "msg " + (msg.sender_id === state.deviceId ? "mine" : "theirs");
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = msg.content;
  div.appendChild(bubble);
  list.appendChild(div);
}

function appendMessage(msg, opts) {
  appendMessageDOM($("#messageList"), msg, opts);
  scrollToBottom();
}

function scrollToBottom() {
  const list = $("#messageList");
  list.scrollTop = list.scrollHeight;
}

/* ---------- 发送 ---------- */

async function sendMessage() {
  const input = $("#messageInput");
  const content = input.value.trim();
  if (!content || !state.peer) return;
  input.value = "";
  try {
    const msg = await API.send(state.deviceId, state.peer.id, content);
    state.messages.push(msg);
    appendMessage(msg, {});
  } catch (err) {
    setStatus("发送失败: " + err.message);
  }
}

/* ---------- WebSocket 事件 ---------- */

function onWsMessage(msg) {
  if (!msg || typeof msg !== "object") return;

  switch (msg.type) {
    case "message": {
      const data = msg.data;
      if (!data || (data.recipient_id !== state.deviceId && data.sender_id !== state.deviceId)) return;
      const peerId = data.sender_id === state.deviceId ? data.recipient_id : data.sender_id;
      if (state.peer && state.peer.id === peerId) {
        state.messages.push(data);
        appendMessage(data, { offline: !!msg.offline });
      } else {
        state.unread[peerId] = (state.unread[peerId] || 0) + 1;
        renderDevices();
      }
      break;
    }

    case "presence": {
      const dev = state.devices.find((d) => d.id === msg.device_id);
      if (dev) {
        dev.is_online = msg.is_online;
        renderDevices();
        if (state.peer && state.peer.id === msg.device_id) {
          $("#chatPeerState").textContent = msg.is_online ? "在线" : "离线";
        }
      }
      break;
    }

    case "pong":
      break;
  }
}

/* ---------- 清空历史 ---------- */

async function clearHistory() {
  if (!state.peer) return;
  if (!confirm(`确定清空与「${state.peer.name}」的全部聊天记录吗？`)) return;
  try {
    await API.clearHistory(state.deviceId, state.peer.id);
    state.messages = [];
    renderMessages();
    setStatus("已清空该会话记录");
  } catch (err) {
    setStatus("清空失败: " + err.message);
  }
}

/* ---------- 改名 ---------- */

async function renameDevice() {
  const name = prompt("输入新的设备名称", state.deviceName);
  if (!name || !name.trim()) return;
  try {
    const dev = await API.rename(state.deviceId, name.trim());
    state.deviceName = dev.name;
    safeSet(LS_DEVICE_NAME, dev.name);
    $("#myDeviceLabel").textContent = dev.name;
    renderDevices();
    setStatus("设备名称已更新");
  } catch (err) {
    setStatus("改名失败: " + err.message);
  }
}

/* ---------- 启动 ---------- */

function startWs() {
  state.ws = new WsClient(state.deviceId, {
    onStatus: (s) => setConnState(s === "connected"),
    onMessage: onWsMessage,
    onRejected: handleWsRejected,
  });
  state.ws.connect();
}

/**
 * 校验本机设备 id 是否仍被服务端认可。
 * @returns {boolean|null} true=有效, false=已失效, null=网络异常无法判断
 */
async function checkDeviceValid() {
  try {
    const devices = await API.listDevices();
    return devices.some((d) => d.id === state.deviceId);
  } catch {
    return null;
  }
}

/** 设备身份失效（服务端清库/重启导致旧 id 不存在）→ 清身份回到注册页 */
function resetIdentity() {
  if (state.ws) {
    state.ws.close();
    state.ws = null;
  }
  safeRemove(LS_DEVICE_ID);
  safeRemove(LS_DEVICE_NAME);
  state.deviceId = null;
  state.deviceName = null;
  state.devices = [];
  showView("#registerView");
  const err = $("#registerError");
  if (err) {
    err.textContent = "设备身份已失效（服务端可能重启/清库过），请重新注册";
    err.classList.remove("hidden");
  }
}

/** WS 握手被拒：验证后决定是重置身份还是网络抖动继续重连 */
async function handleWsRejected() {
  const valid = await checkDeviceValid();
  if (valid === false) {
    resetIdentity();
    return;
  }
  // 设备有效或网络异常 → 重建连接（自动恢复）
  if (!state.ws) {
    startWs();
  } else {
    state.ws.connect();
  }
}

async function enterApp() {
  $("#myDeviceLabel").textContent = state.deviceName;
  $("#renameBtn").classList.remove("hidden");
  showView("#appView");

  // 先校验身份：旧 id 失效时直接引导重新注册，而不是卡在空白/无限重连
  const valid = await checkDeviceValid();
  if (valid === false) {
    resetIdentity();
    return;
  }

  loadDevices();
  setInterval(loadDevices, 10000);
  startWs();
}

function init() {
  // 显示当前设备自己的 IP（服务端从连接来源获取，非服务器地址）
  const urlEl = $("#accessUrl");
  if (urlEl) {
    urlEl.textContent = "…";
    API.getMyIp()
      .then((ip) => {
        if (urlEl) urlEl.textContent = ip;
      })
      .catch(() => {
        if (urlEl) urlEl.textContent = "";
      });
  }
  if (state.deviceId && state.deviceName) {
    enterApp();
  } else {
    showView("#registerView");
  }
}

/* 全局错误兜底：任何 JS 异常都在页面上显示，避免"空白页"无从排查 */
window.addEventListener("error", (e) => {
  const loc = e.filename ? ` (${e.filename.split("/").pop()}:${e.lineno})` : "";
  showFatalError((e.message || "脚本执行出错") + loc);
});

function showFatalError(message) {
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  const host = $("#registerView");
  if (!host) return;
  host.classList.remove("hidden");
  let box = document.querySelector(".fatal-error");
  if (!box) {
    box = document.createElement("div");
    box.className = "fatal-error";
    host.appendChild(box);
  }
  box.textContent = "页面出错：" + message;
}

/* ---------- 事件绑定 ---------- */

$("#registerBtn")?.addEventListener("click", async () => {
  const name = $("#deviceNameInput").value.trim();
  const errorEl = $("#registerError");
  if (!name) {
    errorEl.textContent = "请输入设备名称";
    errorEl.classList.remove("hidden");
    return;
  }
  try {
    const dev = await API.register(name);
    safeSet(LS_DEVICE_ID, dev.id);
    safeSet(LS_DEVICE_NAME, dev.name);
    state.deviceId = dev.id;
    state.deviceName = dev.name;
    errorEl.classList.add("hidden");
    enterApp();
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove("hidden");
  }
});

$("#deviceNameInput")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("#registerBtn").click();
});

$("#sendBtn")?.addEventListener("click", sendMessage);
$("#messageInput")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});
$("#backBtn")?.addEventListener("click", backToDevices);
$("#clearHistoryBtn")?.addEventListener("click", clearHistory);
$("#renameBtn")?.addEventListener("click", renameDevice);

init();
