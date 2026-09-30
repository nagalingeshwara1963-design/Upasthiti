@echo off
cd /d "%~dp0"
if not exist "data\logs" mkdir "data\logs"
title Upasthiti
venv\Scripts\python.exe -m app.launch
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ========================================================
    echo  Upasthiti stopped with error code %ERRORLEVEL%.
    echo  Check data\logs\error.log for details.
    echo ========================================================
    pause
)
