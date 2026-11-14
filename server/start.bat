@echo off
setlocal
rem Start the CellGame server (Windows).
rem Creates the venv on first run and installs dependencies if missing.
rem Double-click this file, or run it from PowerShell / cmd.
rem Settings live in server.properties next to this game (created on first run).
rem Extra args override it, e.g. start.bat --port 9000 --http-port 9001

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

echo [start] starting server; settings file: %ROOT%\server.properties
cd /d "%ROOT%"
"%PY%" -m server.main --config "%ROOT%\server.properties" %*
echo.
echo [start] server stopped.
pause
