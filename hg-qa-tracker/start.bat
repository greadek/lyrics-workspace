@echo off
echo ========================================
echo   Hypergryph QA Job Tracker
echo ========================================
echo.
echo Starting server...
echo Browser access: http://localhost:8765
echo Press Ctrl+C to stop the server.
echo.
cd /d "%~dp0backend"

REM Use the real Python path first (py launcher may not exist on this machine)
if exist "E:\Python Learing\Python 3\python.exe" (
    "E:\Python Learing\Python 3\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8765
) else (
    py -3 -m uvicorn main:app --host 127.0.0.1 --port 8765
)
pause
