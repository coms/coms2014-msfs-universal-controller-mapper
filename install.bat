@echo off
setlocal
cd /d "%~dp0"

python -m pip install -e ".[sim]"
if errorlevel 1 (
    echo.
    echo Installation failed. Make sure Python and pip are installed and on PATH.
    pause
    exit /b 1
)

echo.
echo Installation complete. Start the desktop interface with start_gui.bat.
pause
