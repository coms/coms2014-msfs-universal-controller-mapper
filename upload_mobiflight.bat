@echo off
setlocal
cd /d "%~dp0"

if "%~1"=="" (
    set /p "PORT=Enter Arduino Mega COM port (for example COM5): "
) else (
    set "PORT=%~1"
)

if not defined PORT (
    echo No COM port specified.
    pause
    exit /b 1
)

set "ARDUINO_CLI="
for /f "delims=" %%I in ('where arduino-cli 2^>nul') do if not defined ARDUINO_CLI set "ARDUINO_CLI=%%I"
if not defined ARDUINO_CLI if exist "%LOCALAPPDATA%\Programs\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe" set "ARDUINO_CLI=%LOCALAPPDATA%\Programs\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"
if not defined ARDUINO_CLI if exist "%ProgramFiles%\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe" set "ARDUINO_CLI=%ProgramFiles%\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"
if not defined ARDUINO_CLI (
    echo Could not find Arduino CLI or the CLI bundled with Arduino IDE 2.
    echo Install Arduino IDE 2, or install arduino-cli and add it to PATH.
    pause
    exit /b 1
)

set "CONFIG=%USERPROFILE%\.msfs-mapper\mobiflight_mega.json"
set "TEMP_SKETCH=%TEMP%\mobiflight_mega_upload_%RANDOM%"
set "SKETCH=%TEMP_SKETCH%\mobiflight_mega"
mkdir "%SKETCH%" >nul 2>nul
if errorlevel 1 (
    echo Could not create temporary firmware build folder.
    exit /b 1
)

copy /y "src\msfs_mapper\data\firmware\mobiflight_mega\mobiflight_mega.ino" "%SKETCH%\mobiflight_mega.ino" >nul
if errorlevel 1 (
    echo Could not find the Mega firmware sketch.
    rmdir /s /q "%TEMP_SKETCH%"
    pause
    exit /b 1
)

set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
python -m msfs_mapper.firmware_config "%CONFIG%" --write-header "%SKETCH%\mobiflight_config.h"
if errorlevel 1 (
    echo Invalid Mega pin configuration. Edit it in the GUI and save before uploading.
    rmdir /s /q "%TEMP_SKETCH%"
    pause
    exit /b 1
)

echo Uploading Mega firmware to %PORT% using pin configuration:
type "%CONFIG%"
"%ARDUINO_CLI%" compile --upload --fqbn arduino:avr:mega --port "%PORT%" "%SKETCH%"
if errorlevel 1 (
    echo.
    echo Firmware upload failed. Check the COM port and ensure the Arduino AVR core is installed.
    rmdir /s /q "%TEMP_SKETCH%"
    pause
    exit /b 1
)

rmdir /s /q "%TEMP_SKETCH%"
echo.
echo Upload complete.
pause
