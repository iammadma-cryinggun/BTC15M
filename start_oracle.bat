@echo off
echo ========================================
echo 启动 Binance Oracle (CVD数据源)
echo ========================================
echo.

cd /d D:\OpenClaw\workspace\BTC_15min_Lite

echo [1/3] 检查 Python 环境...
python --version
if errorlevel 1 (
    echo [错误] Python 未安装或未添加到 PATH
    pause
    exit /b 1
)

echo [2/3] 检查 binance_oracle.py...
if not exist binance_oracle.py (
    echo [错误] binance_oracle.py 文件不存在
    pause
    exit /b 1
)

echo [3/3] 启动 Oracle...
echo.
echo ========================================
echo Oracle 正在运行...
echo 按 Ctrl+C 停止
echo ========================================
echo.

python binance_oracle.py

pause
