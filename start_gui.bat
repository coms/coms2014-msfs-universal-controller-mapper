@echo off
setlocal
cd /d "%~dp0"

where msfs-mapper >nul 2>nul
if errorlevel 1 (
    echo msfs-mapper was not found. Run install.bat first.
    pause
    exit /b 1
)

msfs-mapper --no-ai gui
if errorlevel 1 (
    echo.
    echo The GUI exited with an error.
    pause
    exit /b 1
)
