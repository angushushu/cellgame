@echo off
setlocal
rem Start the CellGame client (Windows).
rem Creates the venv on first run and installs dependencies if missing.
rem Double-click this file, or run it from PowerShell / cmd.
rem Settings live in client.properties next to this game (created on first run).
rem Extra args override it, e.g. start.bat --http-port 9101 --server ws://192.168.1.5:8765

for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "VENV=%ROOT%\venv"
set "PY=%VENV%\Scripts\python.exe"

where python >nul 2>&1
if errorlevel 1 (
    echo [start] python not found on PATH. Install Python 3.10+ or activate your conda env, then run again.
    pause
    exit /b 1
)

if not exist "%PY%" (
    echo [start] no venv found, creating one at %VENV% ...
    python -m venv "%VENV%"
    if errorlevel 1 (
        echo [start] venv creation failed.
        pause
        exit /b 1
    )
)

"%PY%" -c "import numpy, websockets" >nul 2>&1
if errorlevel 1 (
    echo [start] installing dependencies ...
    "%PY%" -m pip install -r "%ROOT%\requirements.txt"
    if errorlevel 1 (
        echo [start] pip install failed.
        pause
        exit /b 1
    )
)

echo [start] starting client; settings file: %ROOT%\client.properties
cd /d "%ROOT%"
"%PY%" -m client.main --config "%ROOT%\client.properties" %*
echo.
echo [start] client stopped.
pause
