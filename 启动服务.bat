@echo off
chcp 936 >nul
title 局域网信息互发 - 启动器
cd /d "%~dp0"

echo ============================================
echo   局域网信息互发 v0.4.0
echo ============================================
echo.

rem 首次运行自动安装依赖
python -c "import fastapi, uvicorn, httpx, multipart" >nul 2>&1
if errorlevel 1 (
    echo [提示] 检测到依赖未安装，正在自动安装，请稍候...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络后重试。
        pause
        exit /b 1
    )
)

echo 正在启动服务，浏览器访问 http://127.0.0.1:9777
echo 手机/其他设备访问 http://本机局域网IP:9777（见上方输出）
echo 停止服务请按 Ctrl+C
echo.
python main.py

echo.
echo 服务已停止。
pause
