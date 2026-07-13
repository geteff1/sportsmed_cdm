@echo off
chcp 65001 >nul
title 运动损伤接诊模拟器 SportsMed-CDM
cd /d "%~dp0"

echo ============================================================
echo   运动损伤接诊模拟器 · SportsMed-CDM 教学系统
echo ============================================================
echo.
echo 正在检查依赖 (flask, openai)...
python -c "import flask, openai" 2>nul
if errorlevel 1 (
    echo 缺少依赖，正在安装...
    python -m pip install flask openai
)

echo.
echo 启动服务中... 浏览器将自动打开 http://127.0.0.1:5000
echo 关闭本窗口即可停止服务。
echo.
start "" http://127.0.0.1:5000
python app.py
pause
