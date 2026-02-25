@echo off
chcp 65001 >nul
echo ======================================
echo   BTC 15min Trading Bot - 完整启动
echo ======================================
echo.

REM 检查虚拟环境
if exist "venv\Scripts\activate.bat" (
    echo [INFO] 激活虚拟环境...
    call venv\Scripts\activate.bat
) else (
    echo [WARN] 未找到虚拟环境
)

REM 检查环境变量
if not exist .env (
    echo [INFO] 从 .env.example 创建 .env
    copy .env.example .env
    echo.
    echo [重要] 请编辑 .env 添加你的 PRIVATE_KEY
    echo.
    pause
    exit /b
)

echo [INFO] 启动 Binance Oracle (提供UT Bot趋势)...
start "Binance Oracle" cmd /k "python binance_oracle.py"

timeout /t 3 /nobreak >nul

echo [INFO] 启动交易机器人...
echo.
echo ======================================
echo   两个窗口已启动：
echo   1. Binance Oracle - 实时监控BTC市场
echo   2. Trading Bot - 自动交易
echo ======================================
echo.
echo [提示] 关闭任一窗口将停止该服务
echo.

python auto_trader_ankr.py

pause
