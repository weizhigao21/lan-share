/* 页面主逻辑（M3：设备列表 + 实时聊天） */
const LS_DEVICE_ID = "lan_share_device_id";
const LS_DEVICE_NAME = "lan_share_device_name";

/* 隐私模式/无痕窗口下 localStorage 可能抛 SecurityError，统一安全访问 */
function safeGet(key) {
  try {
    return localStorage.getItem(key);
  } catch (err) {
    return null;
  }
}

function safeSet(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (err) {
    /* 存储不可用时降级为"本次会话内有效"，不阻断功能 */
  }
}

function safeRemove(key) {
  try {
    localStorage.removeItem(key);
  } catch (err) {
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
  maxUploadSize: 0, // 服务端单文件上限（字节），0 表示未知
  ws: null,
};

let uploading = false;  // 是否正在上传（串行处理多文件，避免并发挤占带宽）

function $(sel) {
  return document.querySelector(sel);
}

/* 绑定事件：元素不存在时静默跳过（老浏览器不支持可选链，统一用此写法） */
function on(selector, event, handler) {
  const el = $(selector);
  if (el) el.addEventListener(event, handler);
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
  // 断线期间常驻横幅提示，恢复后隐藏并 toast 通知
  const banner = $("#connBanner");
  if (banner) {
    const wasHidden = banner.classList.contains("hidden");
    banner.classList.toggle("hidden", connected);
    if (connected && !wasHidden) showToast("实时连接已恢复");
  }
}

/* 标签页标题显示未读总数：切到其他标签页时也能一眼看到 */
const BASE_TITLE = "局域网信息互发";
function updateTitle() {
  const total = Object.values(state.unread).reduce((sum, n) => sum + n, 0);
  document.title = total > 0 ? `(${total}) ${BASE_TITLE}` : BASE_TITLE;
}

function renderDevices() {
  const list = $("#deviceList");
  list.innerHTML = "";
  // 设备列表只展示其他设备（自己保留在 state.devices 里，供消息渲染与身份校验使用）
  const others = state.devices.filter((d) => d.id !== state.deviceId);
  const onlineCount = others.filter((d) => d.is_online).length;
  $("#onlineCount").textContent = `(${others.length} 台 · ${onlineCount} 在线)`;

  const sorted = [...others].sort(
    (a, b) => (b.is_online - a.is_online) || a.name.localeCompare(b.name, "zh")
  );

  if (!sorted.length) {
    list.innerHTML = '<li class="empty">还没有其他设备加入</li>';
    return;
  }

  sorted.forEach((d) => {
    const li = document.createElement("li");
    li.className = "device-item" + (state.peer && state.peer.id === d.id ? " active" : "");
    const unread = state.unread[d.id] || 0;
    // 离线设备允许移除（用于清理重复注册留下的旧身份）
    const removable = !d.is_online;
    li.innerHTML = `
      <span class="status-dot ${d.is_online ? "online" : "offline"}"></span>
      <div class="device-info">
        <div class="device-name">${escapeHtml(d.name)}</div>
        ${d.ip ? `<div class="device-ip">${escapeHtml(d.ip)}</div>` : ""}
      </div>
      ${unread ? `<span class="badge">${unread}</span>` : ""}
      ${removable ? '<button type="button" class="device-remove" title="移除该离线设备">✕</button>' : ""}
      <span class="device-state ${d.is_online ? "online" : ""}">${d.is_online ? "在线" : "离线"}</span>`;
    li.addEventListener("click", () => openChat(d));
    const removeBtn = li.querySelector(".device-remove");
    if (removeBtn) {
      removeBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        removeDevice(d);
      });
    }
    list.appendChild(li);
  });
}

/** 移除一台离线设备（连带与它的消息、附件文件） */
async function removeDevice(device) {
  const ok = confirm(
    `移除设备「${device.name}」？\n与它之间的聊天记录和已发送的文件会一并删除，此操作不可撤销。`,
  );
  if (!ok) return;
  try {
    await API.deleteDevice(device.id);
    if (state.peer && state.peer.id === device.id) {
      state.peer = null;
      state.messages = [];
      document.body.classList.remove("chatting");
      $("#chatPeerName").textContent = "选择设备开始聊天";
      $("#chatPeerState").textContent = "";
      enableInput(false);
      $("#messageList").innerHTML = '<div class="empty-hint">从左侧选择一台设备开始聊天</div>';
    }
    delete state.unread[device.id];
    updateTitle();
    setStatus("已移除设备：" + device.name);
    loadDevices();
  } catch (err) {
    setStatus("移除失败: " + err.message);
  }
}

/* ---------- 会话 ---------- */

async function openChat(device) {
  state.peer = { id: device.id, name: device.name };
  const wasChatting = document.body.classList.contains("chatting");
  state.unread[device.id] = 0;
  updateTitle();
  $("#chatPeerName").textContent = device.name;
  $("#chatPeerState").textContent = device.is_online ? "在线" : "离线";
  $("#backBtn").classList.toggle("hidden", window.innerWidth >= 768);
  document.body.classList.add("chatting");
  // 手机端压入一条历史记录：系统返回键先退到设备列表，而不是退出整个页面
  if (window.innerWidth < 768 && !wasChatting && !(history.state && history.state.chat)) {
    history.pushState({ chat: true }, "");
  }

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
  // 手机端有聊天历史记录时交给 popstate 统一收尾，保持历史栈干净
  if (window.innerWidth < 768 && history.state && history.state.chat) {
    history.back();
    return;
  }
  document.body.classList.remove("chatting");
}

window.addEventListener("popstate", () => {
  if (document.body.classList.contains("chatting")) {
    document.body.classList.remove("chatting");
  }
});

function enableInput(enabled) {
  $("#messageInput").disabled = !enabled;
  $("#sendBtn").disabled = !enabled;
  $("#attachBtn").disabled = !enabled || uploading;
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

/* ---------- 文件消息 ---------- */

const PREVIEW_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"];
const VIDEO_TYPES = ["video/mp4", "video/webm", "video/ogg"];
const AUDIO_TYPES = [
  "audio/mpeg", "audio/mp4", "audio/aac",
  "audio/wav", "audio/x-wav", "audio/ogg", "audio/flac",
];
/* 超大图不直接内嵌对话框（手机浏览器内存有限），回落为文件卡手动下载 */
const INLINE_IMAGE_MAX = 15 * 1024 * 1024;

function isPreviewable(contentType) {
  return PREVIEW_TYPES.includes(contentType);
}

function formatSize(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value >= 10 ? value.toFixed(0) : value.toFixed(1)} ${units[i]}`;
}

/* 保留期提示：expires_at 为空表示永久保留（保留期配置为 0） */
function retentionText(expiresAt) {
  if (!expiresAt) return "";
  const left = new Date(expiresAt).getTime() - Date.now();
  if (!Number.isFinite(left)) return "";
  if (left <= 0) return "即将清理";
  const days = Math.ceil(left / 86400000);
  if (days <= 1) {
    return Math.max(1, Math.ceil(left / 3600000)) + " 小时后清理";
  }
  return days + " 天后清理";
}

function renderFileCard(att) {
  const card = document.createElement("div");
  card.className = "file-card";
  const url = API.fileUrl(att, state.deviceId, false);

  if (isPreviewable(att.content_type)) {
    const link = document.createElement("a");
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener";
    link.title = "点击下载原图";
    const img = document.createElement("img");
    img.className = "file-thumb";
    img.src = API.fileUrl(att, state.deviceId, true);
    img.alt = att.name;
    img.loading = "lazy";
    img.addEventListener("error", () => img.classList.add("hidden"));
    link.appendChild(img);
    card.appendChild(link);
  }

  const body = document.createElement("div");
  body.className = "file-body";
  const name = document.createElement("div");
  name.className = "file-name";
  name.textContent = att.name;
  name.title = att.name;
  const meta = document.createElement("div");
  meta.className = "file-meta";
  meta.textContent = [formatSize(att.size), retentionText(att.expires_at)]
    .filter(Boolean)
    .join(" · ");
  const download = document.createElement("button");
  download.type = "button";
  download.className = "file-download";
  download.textContent = "下载";
  download.addEventListener("click", () => downloadAttachment(att));
  body.append(name, meta, download);
  card.appendChild(body);
  return card;
}

/* 附件按类型分流：图片/视频/音频在线直接展开（双方在线即"自动接收"体验），
   其他类型与超大图片保留文件卡 + 手动下载。加载失败统一回落到文件卡。 */
function renderAttachment(att) {
  const ct = att.content_type || "";
  if (PREVIEW_TYPES.includes(ct) && att.size <= INLINE_IMAGE_MAX) {
    return renderImageMsg(att);
  }
  if (VIDEO_TYPES.includes(ct)) return renderVideoMsg(att);
  if (AUDIO_TYPES.includes(ct)) return renderAudioMsg(att);
  return renderFileCard(att);
}

function fallbackToCard(att, mediaEl) {
  mediaEl.addEventListener("error", () => {
    const card = renderFileCard(att);
    if (mediaEl.parentNode) mediaEl.parentNode.replaceWith(card);
  });
}

function renderImageMsg(att) {
  const wrap = document.createElement("div");
  wrap.className = "media-msg";
  const img = document.createElement("img");
  img.className = "img-msg";
  img.src = API.fileUrl(att, state.deviceId, true);
  img.alt = att.name;
  img.loading = "lazy";
  img.addEventListener("click", () => openLightbox(img.src));
  fallbackToCard(att, img);
  wrap.appendChild(img);
  return wrap;
}

function renderVideoMsg(att) {
  const wrap = document.createElement("div");
  wrap.className = "media-msg";
  const video = document.createElement("video");
  video.className = "video-msg";
  video.controls = true;
  video.preload = "metadata";
  video.playsInline = true;  // iOS 内联播放，不强制全屏
  video.src = API.fileUrl(att, state.deviceId, true);
  fallbackToCard(att, video);
  wrap.appendChild(video);
  wrap.appendChild(buildMediaMeta(att));
  return wrap;
}

function renderAudioMsg(att) {
  const wrap = document.createElement("div");
  wrap.className = "media-msg";
  const audio = document.createElement("audio");
  audio.className = "audio-msg";
  audio.controls = true;
  audio.preload = "metadata";
  audio.src = API.fileUrl(att, state.deviceId, true);
  fallbackToCard(att, audio);
  wrap.appendChild(audio);
  wrap.appendChild(buildMediaMeta(att));
  return wrap;
}

function buildMediaMeta(att) {
  const meta = document.createElement("div");
  meta.className = "file-meta media-meta";
  meta.textContent = [att.name, formatSize(att.size), retentionText(att.expires_at)]
    .filter(Boolean)
    .join(" · ");
  return meta;
}

/* 图片灯箱：全屏黑底看原图，点击任意处关闭 */
function openLightbox(src) {
  let ov = document.getElementById("lightbox");
  if (!ov) {
    ov = document.createElement("div");
    ov.className = "lightbox";
    const big = document.createElement("img");
    big.alt = "图片预览";
    ov.appendChild(big);
    ov.addEventListener("click", () => ov.classList.add("hidden"));
    document.body.appendChild(ov);
  }
  ov.querySelector("img").src = src;
  ov.classList.remove("hidden");
}

/* 已被自动清理的文件：保留一条灰色记录，聊天时间线不断档 */
function renderExpiredCard(name) {
  const card = document.createElement("div");
  card.className = "file-card file-expired";
  const body = document.createElement("div");
  body.className = "file-body";
  const title = document.createElement("div");
  title.className = "file-name";
  title.textContent = name || "文件";
  title.title = name || "";
  const meta = document.createElement("div");
  meta.className = "file-meta";
  meta.textContent = "文件已过期清理，无法再下载";
  body.append(title, meta);
  card.appendChild(body);
  return card;
}

/* 文件下载：直接把带文件名的下载地址交给浏览器原生下载器。
   不再走 fetch→Blob：Blob 的地址是一串随机 UUID，安卓浏览器/内置 WebView
   一旦忽略 download 属性，就只能拿 UUID 当文件名，再按 octet-stream 补成 .bin
   （这就是"下载后文件名变成一串数字、后缀变 bin"的原因）。
   现在地址末段就是原文件名，任何下载器都能取到正确的名字与扩展名；
   大文件也不会被读进内存。 */
function isInAppBrowser() {
  return /MicroMessenger|QQ\/|Weibo|DingTalk|AliApp|Feishu|Lark|baiduboxapp|Quark|UCBrowser|MQQBrowser/i
    .test(navigator.userAgent);
}

async function downloadAttachment(att) {
  const url = API.fileUrl(att, state.deviceId, false);

  /* 已过保留期的文件先探测一次（下载器本来也会发 HEAD）：
     已被后台清理时给出明确提示，而不是把用户跳到一页 JSON 报错。
     未过期的文件不做预检，保持点击即下载的同步手势。 */
  if (att.expires_at && new Date(att.expires_at).getTime() <= Date.now()) {
    try {
      const probe = await fetch(url, { method: "HEAD" });
      if (probe.status === 404) {
        setStatus("文件已过期清理，无法再下载：" + att.name);
        return;
      }
      if (probe.status === 403) {
        setStatus("无权下载该文件");
        return;
      }
    } catch (err) {
      /* 探测失败就照常下载，交给浏览器处理 */
    }
  }

  const a = document.createElement("a");
  a.href = url;
  a.download = att.name;
  a.rel = "noopener";
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  setTimeout(function () {
    if (a.parentNode) a.parentNode.removeChild(a);
  }, 0);

  if (isInAppBrowser()) {
    setStatus("已开始下载：" + att.name + "；若没反应，请点右上角「···」→ 在浏览器打开本页");
  } else {
    setStatus("已开始下载：" + att.name);
  }
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
  if (msg.msg_type === "file" && msg.attachment) {
    bubble.classList.add("file-bubble");
    bubble.appendChild(renderAttachment(msg.attachment));
  } else if (msg.msg_type === "file_expired") {
    bubble.classList.add("file-bubble", "expired-bubble");
    bubble.appendChild(renderExpiredCard(msg.content));
  } else {
    bubble.textContent = msg.content;
  }
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

/* ---------- 文件上传 ---------- */

function showUploadProgress(label, ratio) {
  $("#uploadBar").classList.remove("hidden");
  $("#uploadLabel").textContent = label;
  $("#progressFill").style.width = `${Math.round((ratio || 0) * 100)}%`;
}

function hideUploadProgress() {
  $("#uploadBar").classList.add("hidden");
  $("#progressFill").style.width = "0%";
}

/** 串行上传选中的多个文件；每个文件成功即生成一条消息并渲染 */
async function handleFiles(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length || !state.peer || uploading) return;

  uploading = true;
  $("#attachBtn").disabled = true;
  const peerId = state.peer.id;

  for (let i = 0; i < files.length; i += 1) {
    const file = files[i];
    const limit = state.maxUploadSize;
    if (limit && file.size > limit) {
      setStatus(
        "「" + file.name + "」有 " + formatSize(file.size) +
        "，超过单文件上限 " + formatSize(limit) + "，已跳过"
      );
      continue;
    }
    const label = files.length > 1
      ? `上传 ${i + 1}/${files.length}：${file.name}`
      : `上传：${file.name}`;
    showUploadProgress(label, 0);
    try {
      const msg = await API.uploadFile(
        state.deviceId,
        peerId,
        file,
        (ratio) => showUploadProgress(label, ratio),
      );
      // 上传途中切换了会话：不把消息错插进当前会话，仅提示已发送
      if (state.peer && state.peer.id === peerId) {
        state.messages.push(msg);
        appendMessage(msg, {});
      } else {
        setStatus("文件已发送（会话已切换）");
      }
    } catch (err) {
      setStatus(err.message);
      if (err.message === "已取消上传") break;
    }
  }

  uploading = false;
  hideUploadProgress();
  $("#attachBtn").disabled = !state.peer;
  $("#fileInput").value = "";
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
        updateTitle();
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
  } catch (err) {
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
  API.forgetDevice();  // 同步清掉服务端身份 Cookie，否则下次会被"恢复"回失效身份
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

async function init() {
  showMyIp();
  loadServerMeta();
  if (state.deviceId && state.deviceName) {
    enterApp();
    return;
  }

  // localStorage 为空（隐私模式 / 被内置浏览器清理 / 换了浏览器）：
  // 先问服务端要回上次的身份，避免又注册出一个同名设备。
  let restored = null;
  try {
    restored = await API.whoAmI();
  } catch (err) {
    restored = null;
  }
  if (restored && restored.id && restored.name) {
    state.deviceId = restored.id;
    state.deviceName = restored.name;
    safeSet(LS_DEVICE_ID, restored.id);
    safeSet(LS_DEVICE_NAME, restored.name);
    enterApp();
    setStatus("已恢复设备身份：" + restored.name);
    return;
  }

  showView("#registerView");
}

/* 取服务端的单文件上限，用于上传前本地校验（拿不到就退化为只在服务端拦截） */
function loadServerMeta() {
  API.getMeta()
    .then((meta) => {
      if (meta && meta.max_upload_size) {
        state.maxUploadSize = meta.max_upload_size;
      }
    })
    .catch(() => {
      /* 忽略：不影响上传，服务端仍会兜底 */
    });
}

/* 显示当前设备自己的 IP（服务端从连接来源获取，非服务器地址） */
function showMyIp() {
  const urlEl = $("#accessUrl");
  if (!urlEl) return;
  urlEl.textContent = "…";
  API.getMyIp()
    .then((ip) => {
      urlEl.textContent = ip;
    })
    .catch(() => {
      urlEl.textContent = "";
    });
}

/* 全局错误兜底：只在页面底部挂一条可关闭的提示，绝不隐藏页面。
   内置浏览器/WebView 注入的第三方脚本报错很常见（例如 loadDownloads is not defined），
   那些与本项目无关，直接忽略——否则一条无关报错就会把整个聊天界面顶掉。 */
window.addEventListener("error", (e) => {
  const file = String(e.filename || "");
  if (file.indexOf("/js/") === -1) return;
  const name = file.split("/").pop();
  showScriptWarning((e.message || "脚本执行出错") + " (" + name + ":" + e.lineno + ")");
});

function showScriptWarning(message) {
  let el = document.getElementById("scriptWarning");
  if (!el) {
    el = document.createElement("div");
    el.id = "scriptWarning";
    el.className = "script-warning";
    el.title = "点击关闭";
    el.addEventListener("click", () => {
      el.className = "script-warning hide";
    });
    document.body.appendChild(el);
  }
  el.textContent = "脚本异常（不影响基本使用，可刷新重试）：" + message;
  el.className = "script-warning";
}

/* ---------- 拖拽文件夹：递归展开成文件列表 ---------- */

const DROP_MAX_FILES = 300;   // 一次拖入最多取这么多文件，防止误拖整个盘
const DROP_MAX_DEPTH = 8;     // 目录递归深度上限

function readAllDirEntries(reader) {
  return new Promise(function (resolve) {
    const all = [];
    (function next() {
      reader.readEntries(
        function (batch) {
          if (!batch.length) {
            resolve(all);
            return;
          }
          for (let i = 0; i < batch.length; i += 1) all.push(batch[i]);
          next();
        },
        function () {
          resolve(all);
        }
      );
    })();
  });
}

function collectEntry(entry, out, depth) {
  if (!entry || out.length >= DROP_MAX_FILES) return Promise.resolve();
  if (entry.isFile) {
    return new Promise(function (resolve) {
      entry.file(
        function (file) {
          out.push(file);
          resolve();
        },
        function () {
          resolve();
        }
      );
    });
  }
  if (entry.isDirectory) {
    if (depth >= DROP_MAX_DEPTH) return Promise.resolve();
    return readAllDirEntries(entry.createReader()).then(function (entries) {
      return entries.reduce(function (chain, child) {
        return chain.then(function () {
          return collectEntry(child, out, depth + 1);
        });
      }, Promise.resolve());
    });
  }
  return Promise.resolve();
}

/* 把 DataTransfer 展开成 File[]：文件夹会被递归读取其内容 */
function filesFromDataTransfer(dt) {
  const fallback = Array.prototype.slice.call((dt && dt.files) || []);
  if (!dt || !dt.items || !dt.items.length) return Promise.resolve(fallback);

  const entries = [];
  for (let i = 0; i < dt.items.length; i += 1) {
    const item = dt.items[i];
    if (item.kind !== "file") continue;
    let entry = null;
    if (typeof item.webkitGetAsEntry === "function") entry = item.webkitGetAsEntry();
    if (!entry && typeof item.getAsFile === "function") {
      const file = item.getAsFile();
      if (file) {
        // 老浏览器没有 entry API：退化成一个"只含单文件"的伪 entry
        entry = { isFile: true, file: function (cb) { cb(file); } };
      }
    }
    if (entry) entries.push(entry);
  }
  if (!entries.length) return Promise.resolve(fallback);

  const out = [];
  return entries
    .reduce(function (chain, entry) {
      return chain.then(function () {
        return collectEntry(entry, out, 0);
      });
    }, Promise.resolve())
    .then(function () {
      return out;
    });
}

/* ---------- 事件绑定 ---------- */

on("#registerBtn", "click", async () => {
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

on("#deviceNameInput", "keydown", (e) => {
  if (e.key === "Enter") $("#registerBtn").click();
});

on("#sendBtn", "click", sendMessage);
on("#messageInput", "keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});
on("#attachBtn", "click", () => {
  const input = $("#fileInput");
  if (input) input.click();
});
on("#fileInput", "change", (e) => handleFiles(e.target.files));
on("#cancelUploadBtn", "click", () => API.abortUpload());

/* 拖拽文件到消息区直接发送 */
const dropZone = $("#messageList");
if (dropZone) {
  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("drag-over");
  });
  dropZone.addEventListener("dragleave", (e) => {
    if (!dropZone.contains(e.relatedTarget)) dropZone.classList.remove("drag-over");
  });
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
    if (!state.peer) {
      setStatus("请先选择一台设备");
      return;
    }
    const dt = e.dataTransfer;
    setStatus("正在读取拖入的内容…");
    filesFromDataTransfer(dt)
      .then((files) => {
        if (!files.length) {
          setStatus("没有可上传的文件");
          return;
        }
        if (files.length > 1) {
          setStatus("已读取 " + files.length + " 个文件，开始上传");
        }
        handleFiles(files);
      })
      .catch(() => {
        setStatus("读取拖入内容失败，请改用回形针按钮选择文件");
      });
  });
}

on("#backBtn", "click", backToDevices);
on("#clearHistoryBtn", "click", clearHistory);
on("#renameBtn", "click", renameDevice);

init().catch(() => {
  // 恢复流程异常时退回注册页，保证页面永远可用
  showView("#registerView");
});

/* 供 index.html 的启动兜底检测：能执行到这里说明脚本解析与初始化正常 */
window.__lanStarted = true;
