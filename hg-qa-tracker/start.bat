@echo off
chcp 65001 >nul
echo ========================================
echo   鹰角网络 QA 岗位追踪系统
echo   Hypergryph QA Job Tracker
echo ========================================
echo.
echo 正在启动服务...
echo 浏览器访问: http://localhost:8765
echo 按 Ctrl+C 停止服务
echo.
cd /d "%~dp0backend"

REM 优先使用本机真实 Python（避免 py 启动器缺失问题）
if exist "E:\Python Learing\Python 3\python.exe" (
    "E:\Python Learing\Python 3\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8765
) else (
    py -3 -m uvicorn main:app --host 0.0.0.0 --port 8765
)
pause
