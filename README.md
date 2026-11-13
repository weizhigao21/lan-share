# 局域网信息互发 (lan-share)

基于局域网（WiFi / 路由器）的设备间消息与文件互发系统。一台 Windows 电脑运行服务，手机、平板、其他电脑**通过浏览器免安装访问**，支持实时文字消息、文件传输、在线状态感知与**离线消息缓存补发**。

## 功能特性

- **设备唯一身份**：服务端生成 UUID，对外只显示自定义设备名称（ID 永不出现在界面）
- **身份自动恢复**：浏览器清缓存 / 换内核后按 Cookie 与来源 IP 认回原身份，不会重复注册出同名设备
- **实时消息互发**：WebSocket 推送，微信式聊天气泡
- **文件互发**：附件按钮选择 / 拖拽上传（支持直接拖文件夹），多文件进度条，位图缩略图预览，单文件上限 2 GiB
- **数据保留策略**：文本消息永久保留；音视频 / 图片 / 压缩包等附件**保留 7 天**后自动清理，聊天记录仍保留「文件已过期」提示
- **在线状态感知**：心跳保活 + 断线检测，上下线实时广播
- **离线消息缓存**：目标离线时消息暂存，上线后自动补发并提示"离线消息已送达"
- **历史记录**：会话记录持久化，支持清空；离线设备可移除（连带清理其记录）
- **设备 IP 展示**：列表显示每台设备的局域网 IP，顶栏显示当前设备自身 IP
- **响应式 UI**：电脑宽屏（左设备列表 + 右聊天窗口）/ 手机窄屏（列表 → 聊天两级导航）

## 技术栈

| 层 | 选型 |
|----|------|
| Web 框架 | FastAPI + Pydantic v2 + Uvicorn |
| 实时通信 | WebSocket |
| 存储 | SQLite（标准库 `sqlite3`） |
| 前端 | 原生 HTML / CSS / JS（单页，无构建链） |
| 质量 | pytest + Ruff |

## 快速开始

### 环境要求

- Python 3.10+
- 所有设备处于同一局域网

### 启动服务

方式一（推荐）：双击 **`启动服务.bat`**（自动检查并安装依赖后启动）。

方式二（手动）：

```bash
pip install -r requirements.txt
python main.py
```

启动后终端显示访问地址：

```
本机访问:   http://127.0.0.1:9777
局域网访问: http://192.168.x.x:9777
```

手机 / 其他电脑浏览器打开 `局域网访问` 地址 → 输入设备名称即可加入。

## 目录结构

```
lan-share/
├── main.py                    # 服务入口（uvicorn 启动 + 打印访问地址）
├── 启动服务.bat               # Windows 一键启动脚本
├── app/
│   ├── config.py              # 配置（端口 9777 / DB 路径 / 在线超时）
│   ├── database.py            # SQLite 建表与轻量迁移
│   ├── schemas.py             # Pydantic 请求/响应模型
│   ├── dependencies.py        # 请求级 DB 连接
│   ├── services/              # 设备 / 消息 / 文件 / 在线状态 / 过期清理
│   ├── api/v1/                # devices / messages / files / ws / me 路由
│   └── utils/network.py       # 局域网 IP 探测
├── static/                    # 前端（index.html / css / js）
├── uploads/                   # 上传附件（首次上传自动创建，不入库）
├── tests/                     # pytest 用例
└── CHANGELOG.md               # 更新日志
```

## 文件传输

- 在聊天窗口点输入条左侧的回形针按钮选择文件，或直接把**文件 / 文件夹**拖到消息区；可一次选多个，逐个上传并显示进度，可随时取消。拖入文件夹会递归展开其中的文件（最多 300 个、8 层深度）。
- 单文件上限 **2 GiB**，可用环境变量 `LAN_SHARE_MAX_UPLOAD_MB` 覆盖（如 `set LAN_SHARE_MAX_UPLOAD_MB=4096`）。前端会先读 `GET /api/v1/meta` 的上限，超限文件直接跳过并提示，不会白传一遍。附件保存在项目根目录 `uploads/`，磁盘文件名为 UUID，原始文件名只存数据库。
- 文件也是一条消息：对方在线即时收到，离线则暂存服务端，上线后自动补发；清空聊天记录会一并回收附件文件。
- PNG / JPG / GIF / WebP / BMP 显示缩略图，点击下载原图；其它类型显示文件名、大小与下载按钮。
- 下载地址末段就是原文件名（`/api/v1/files/{id}/download/{原文件名}`），并配合 `Content-Disposition` 的 `filename` / `filename*`：即使安卓浏览器忽略 `download` 属性或响应头，下载器也能从 URL 取到正确的名字与扩展名（否则会被存成一串数字 + `.bin`）。微信 / QQ / 夸克等内置浏览器若限制下载，按提示点右上角「···」→ 在浏览器打开。
- 接口：`POST /api/v1/files/upload`（multipart 字段 `sender_id` / `recipient_id` / `file`）、`GET /api/v1/files/{id}/download/{filename}?device_id=<本机ID>`（图片内联预览加 `inline=true`；末段文件名只用于取名，实际以数据库为准，省略末段的旧地址仍可用）。下载同时接受 `HEAD`（安卓下载器会先探测）。仅上传者与该消息的收/发双方可下载。

## 数据保留

- **文本消息永久保留**，不会被自动删除。
- **附件（音视频 / 图片 / 压缩包等所有上传文件）默认保留 7 天**，到期后自动删除磁盘文件与附件记录；对应消息**不会消失**，而是变成一条灰色的「文件已过期清理」提示，聊天时间线完整保留。
- 清理在服务启动时先执行一次，之后每小时轮询（`attachment_cleanup_interval`）；顺带回收 `uploads/` 里没有数据库记录的孤儿文件（只处理 UUID 命名且超过 2 小时的文件，绝不碰正在上传的内容）。
- 调整保留期：启动前设置环境变量，单位天，`0` 表示永久保留。

  ```bat
  set LAN_SHARE_ATTACHMENT_TTL_DAYS=30
  启动服务.bat
  ```

- 前端文件卡片会显示「N 天后清理」；已过期的文件再点下载会明确提示已清理，而不是跳到错误页。

## 设备身份

- 注册后身份存三处：浏览器 localStorage、服务端 Cookie（`lan_device_id`，一年）、设备表的来源 IP。
- 打开页面时依次尝试 localStorage → Cookie → 同 IP 的最近活跃设备，任一命中即直接进入，不再要求重新起名。
- 设备列表中**离线且非本机**的设备右侧有 `✕`，可移除该设备并清理与它相关的消息与附件。

## 开发与测试

```bash
# 运行测试
python -m pytest tests/

# Lint
python -m ruff check .
```

## 项目仓库

- 远程仓库：<https://github.com/weizhigao21/lan-share>
- 更新日志：[CHANGELOG.md](CHANGELOG.md)

### 首次上传

```bash
git init
git add .
git commit -m "feat: 局域网信息互发 v0.4.0"
git branch -M main
git remote add origin https://github.com/weizhigao21/lan-share.git
git push -u origin main
```

### 日常更新（提交前先跑 pytest）

```bash
python -m pytest tests/
git add .
git commit -m "feat/fix: 变更说明"
git push
```

## 版本

当前版本 **v0.4.0**，详见 [CHANGELOG.md](CHANGELOG.md)。
