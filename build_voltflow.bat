@echo off
REM Build VoltFlow as a single Windows executable: dist\VoltFlow.exe
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Create venv first: python -m venv .venv
    echo Then: .venv\Scripts\pip install -r requirements.txt PyInstaller
    exit /b 1
)
.venv\Scripts\python.exe -m pip install -q PyInstaller
.venv\Scripts\python.exe -m PyInstaller voltflow.spec --noconfirm
if errorlevel 1 exit /b 1
echo.
echo Done: dist\VoltFlow.exe
exit /b 0
