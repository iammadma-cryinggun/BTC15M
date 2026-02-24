@echo off
echo ======================================
echo   BTC 15min Trading Bot - Local Start
echo ======================================
echo.

REM 检查虚拟环境
if exist "venv\Scripts\activate.bat" (
    echo [INFO] Activating virtual environment...
    call venv\Scripts\activate.bat
) else (
    echo [WARN] No virtual environment found
)

REM 检查环境变量
if not exist .env (
    echo [INFO] Creating .env from .env.example
    copy .env.example .env
    echo.
    echo [IMPORTANT] Please edit .env and add your PRIVATE_KEY
    echo.
    pause
    exit /b
)

echo [INFO] Starting trading bot...
echo.
python auto_trader_ankr.py

pause
