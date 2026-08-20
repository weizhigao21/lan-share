# 局域网信息互发 (lan-share)

基于局域网（WiFi / 路由器）的设备间文字消息互发系统。一台 Windows 电脑运行服务，手机、平板、其他电脑**通过浏览器免安装访问**，支持实时消息、在线状态感知与**离线消息缓存补发**。

## 功能特性

- **设备唯一身份**：服务端生成 UUID，对外只显示自定义设备名称（ID 永不出现在界面）
- **实时消息互发**：WebSocket 推送，微信式聊天气泡
- **在线状态感知**：心跳保活 + 断线检测，上下线实时广播
- **离线消息缓存**：目标离线时消息暂存，上线后自动补发并提示"离线消息已送达"
- **历史记录**：会话记录持久化，支持清空
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
│   ├── services/              # 设备 / 消息 / 在线状态业务逻辑
│   ├── api/v1/                # devices / messages / ws / me 路由
│   └── utils/network.py       # 局域网 IP 探测
├── static/                    # 前端（index.html / css / js）
└── tests/                     # pytest 用例
```

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
git commit -m "feat: 局域网信息互发 v0.2.5"
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

当前版本 **v0.2.5**，详见 [CHANGELOG.md](CHANGELOG.md)。
