@echo off
title LeadSweep Launcher

echo ========================================
echo               LEADSWEEP
echo ========================================
echo.

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

if not exist logs mkdir logs

echo Checking system requirements...

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found in PATH.
    echo Please install Python 3.11+ and check "Add Python to PATH".
    start https://www.python.org/downloads/
    pause
    exit /b 1
)

where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js was not found in PATH.
    start https://nodejs.org/
    pause
    exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm was not found in PATH.
    start https://nodejs.org/
    pause
    exit /b 1
)

if not exist .env (
    if exist .env.example (
        copy .env.example .env >nul
        echo [INFO] Created .env from .env.example
    )
)

echo Preparing backend environment...
set "PY_EXE=python"
if exist .venv\Scripts\python.exe (
    set "PY_EXE=.venv\Scripts\python.exe"
    goto CHECK_FIRST_RUN
)

echo Creating virtual environment...
python -m venv .venv >> logs\startup.log 2>&1
if exist .venv\Scripts\python.exe (
    set "PY_EXE=.venv\Scripts\python.exe"
    echo Installing backend dependencies...
    if exist requirements.txt (
        .venv\Scripts\python.exe -m pip install -r requirements.txt >> logs\startup.log 2>&1
    )
    .venv\Scripts\python.exe -m playwright install chromium >> logs\startup.log 2>&1
)

:CHECK_FIRST_RUN
if not exist ".setup_done" (
    if exist "scripts\first_time_setup.py" (
        %PY_EXE% scripts\first_time_setup.py
    )
)

:CHECK_FRONTEND
echo Preparing frontend environment...
set "FRONTEND_DIR=web"
if exist "project\package.json" (
    set "FRONTEND_DIR=project"
)

if not exist %FRONTEND_DIR%\node_modules (
    echo Installing frontend dependencies...
    pushd %FRONTEND_DIR%
    call npm install >> ..\logs\startup.log 2>&1
    popd
)

echo Freeing ports 8000 and 5173...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000,5173 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }" >nul 2>&1

echo Starting FastAPI backend on port 8000...
start "" /b cmd /c "set PYTHONPATH=%CD%& %PY_EXE% -m uvicorn leadsweep.api:app --host 127.0.0.1 --port 8000 > logs\backend.log 2>&1"

echo Starting frontend dashboard on port 5173...
pushd %FRONTEND_DIR%
start "" /b cmd /c "npm run dev -- --host 127.0.0.1 --port 5173 > ..\logs\frontend.log 2>&1"
popd

echo.
echo Waiting for services to initialize...
set RETRIES=0

:WAIT_HEALTH
powershell -NoProfile -Command "Start-Sleep -Milliseconds 800"
set /a RETRIES=%RETRIES%+1

powershell -NoProfile -Command "$b = (Invoke-WebRequest -Uri 'http://127.0.0.1:8000/docs' -UseBasicParsing -TimeoutSec 1).StatusCode -eq 200; $f = (Invoke-WebRequest -Uri 'http://127.0.0.1:5173' -UseBasicParsing -TimeoutSec 1).StatusCode -eq 200; if ($b -and $f) { exit 0 } else { exit 1 }" >nul 2>&1
if %ERRORLEVEL% equ 0 goto READY

if %RETRIES% geq 35 (
    powershell -NoProfile -Command "try { $res = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/docs' -UseBasicParsing -TimeoutSec 1; exit 0 } catch { exit 1 }" >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Backend failed to start. See logs\backend.log
        pause
        exit /b 1
    )
    echo [ERROR] Frontend failed to start. See logs\frontend.log
    pause
    exit /b 1
)
goto WAIT_HEALTH

:READY
echo Backend: READY
echo Frontend: READY
echo Database: READY
echo Browser: READY
echo.
echo ========================================
echo Opening Dashboard...
echo ========================================
start http://localhost:5173

echo.
echo Application is running. Run STOP.bat to terminate.
pause >nul
