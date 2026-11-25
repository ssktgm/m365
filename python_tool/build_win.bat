@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo Error: PyInstaller is not installed. Run: python -m pip install pyinstaller
    exit /b 1
)

set EXTRA_ARGS=
python -c "import certifi" >nul 2>&1
if not errorlevel 1 (
    set EXTRA_ARGS=--collect-data certifi
)

python -m PyInstaller --onefile --windowed --name HttpPostTool --noconfirm --clean %EXTRA_ARGS% http_post_tool.py
if errorlevel 1 exit /b 1

echo Build complete: %~dp0dist\HttpPostTool.exe
endlocal
