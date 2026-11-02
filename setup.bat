@echo off
rem One-time setup: creates .venv and installs the dependencies.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    python -m venv .venv || (echo Python 3.10+ is required. & pause & exit /b 1)
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
echo.
echo Done. Start the app with "Run OpenUninstaller.bat".
pause
