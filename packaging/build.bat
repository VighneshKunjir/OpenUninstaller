@echo off
rem Builds dist\OpenUninstaller\ (PyInstaller) and release\OpenUninstaller-<version>-Setup.exe (Inno Setup 6).
rem Needs: setup.bat run once, and Inno Setup 6 (winget install JRSoftware.InnoSetup).
setlocal
cd /d "%~dp0.."

if not exist .venv\Scripts\python.exe call setup.bat
.venv\Scripts\python.exe -m pip install -q pyinstaller || exit /b 1
.venv\Scripts\python.exe -m PyInstaller packaging\OpenUninstaller.spec --noconfirm --distpath dist --workpath build || exit /b 1

set "ISCC="
for %%P in ("%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do (
    if exist %%P set "ISCC=%%~P"
)
if not defined ISCC (
    echo Inno Setup 6 not found. Install it with:  winget install JRSoftware.InnoSetup
    exit /b 1
)
"%ISCC%" /Q packaging\installer.iss || exit /b 1
echo.
echo Installer written to the release folder:
dir /b release\*.exe
