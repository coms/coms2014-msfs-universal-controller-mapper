@echo off
setlocal
cd /d "%~dp0"

where msfs-mapper >nul 2>nul
if errorlevel 1 (
    echo msfs-mapper was not found. Run install.bat first.
    pause
    exit /b 1
)

if /i "%~1"=="--live" (
    msfs-mapper run %2 %3 %4 %5 %6 %7 %8 %9
) else (
    msfs-mapper run --dry-run %*
)

if errorlevel 1 (
    echo.
    echo The simulator runtime exited with an error.
    pause
    exit /b 1
)
