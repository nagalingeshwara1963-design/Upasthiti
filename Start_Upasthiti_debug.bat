@echo off
cd /d "%~dp0"
echo Starting Upasthiti in debug mode - errors will show below.
venv\Scripts\python.exe -m app.launch
echo.
echo ---- Upasthiti closed. Read any error above. ----
pause
