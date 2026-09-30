@echo off
setlocal
title Upasthiti Web Server
cd /d "%~dp0"

echo =======================================================
echo   Upasthiti - Face Recognition Web Attendance
echo =======================================================
echo.
echo Starting web server at http://localhost:8000 ...
echo (Press Ctrl+C to stop)
echo.

if exist venv\Scripts\python.exe (
    set "PY=venv\Scripts\python.exe"
) else (
    set "PY=python"
)

start "" http://localhost:8000
"%PY%" -m uvicorn app.web.server:app --host 0.0.0.0 --port 8000 --reload
pause
