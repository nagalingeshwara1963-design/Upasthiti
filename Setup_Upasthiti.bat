@echo off
title Upasthiti Setup
echo ============================================================
echo   UPASTHITI - one-time setup
echo ============================================================
cd /d "%~dp0"

set PYLAUNCHER=
py --version >nul 2>nul
if %ERRORLEVEL% EQU 0 set PYLAUNCHER=py
if not defined PYLAUNCHER (
  python --version >nul 2>nul
  if %ERRORLEVEL% EQU 0 set PYLAUNCHER=python
)
if not defined PYLAUNCHER (
  echo.
  echo Could not run Python. Tried "py" and "python", neither worked from this window.
  echo Install Python 3.10-3.12 from python.org ^(tick "Add python.exe to PATH"^),
  echo restart your laptop once, then run this again.
  echo.
  echo If you know Python IS installed, open Command Prompt in this folder and run:
  echo     py --version
  echo and send that result back.
  pause
  exit /b 1
)
echo Using: %PYLAUNCHER%
%PYLAUNCHER% --version
echo.

if not exist venv\Scripts\python.exe (
  echo Creating virtual environment...
  %PYLAUNCHER% -m venv venv
  if errorlevel 1 (
    echo.
    echo Could not create the virtual environment - see the error above.
    pause
    exit /b 1
  )
)
if not exist venv\Scripts\python.exe (
  echo.
  echo The virtual environment was not created correctly ^(venv\Scripts\python.exe is missing^).
  pause
  exit /b 1
)
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Package install failed - see the messages above.
  pause
  exit /b 1
)
venv\Scripts\python.exe setup_models.py
echo.
echo ============================================================
echo   Setup complete. Double-click Start_Upasthiti.bat to open the app.
echo ============================================================
pause
