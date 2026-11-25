@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

where pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Error: pyinstaller が見つかりません。pip install pyinstaller を実行してください。
    exit /b 1
)

set EXTRA_ARGS=
python -c "import certifi" >nul 2>&1
if not errorlevel 1 (
    set EXTRA_ARGS=--collect-data certifi
)

pyinstaller --onefile --windowed --name HttpPostTool --noconfirm --clean %EXTRA_ARGS% http_post_tool.py
if errorlevel 1 exit /b 1

echo Build complete: %~dp0dist\HttpPostTool.exe
endlocal
