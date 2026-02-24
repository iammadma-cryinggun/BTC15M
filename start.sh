#!/bin/bash
# Zeabur启动脚本

echo "========================================="
echo "  BTC 15min Trading Bot - Starting"
echo "========================================="
echo ""

# 检查Python版本
echo "[INFO] Python version:"
python --version
echo ""

# 检查环境变量
echo "[INFO] Checking environment variables..."
if [ -z "$PRIVATE_KEY" ]; then
    echo "[ERROR] PRIVATE_KEY not set!"
    echo "        Please configure this in Zeabur environment variables"
    exit 1
else
    echo "[OK] PRIVATE_KEY is set (${#PRIVATE_KEY} chars)"
fi

echo "[INFO] TELEGRAM_ENABLED: $TELEGRAM_ENABLED"
echo "[INFO] HTTP_PROXY: $HTTP_PROXY"
echo ""

# 检查依赖
echo "[INFO] Checking installed packages..."
pip list | grep -E "requests|dotenv|clob" || echo "[WARN] Some packages may be missing"
echo ""

# 启动主程序
echo "[INFO] Starting trading bot..."
echo "========================================="
echo ""

# 运行主程序（捕获退出码）
python auto_trader_ankr.py
EXIT_CODE=$?

echo ""
echo "========================================="
if [ $EXIT_CODE -eq 0 ]; then
    echo "[INFO] Bot exited normally (code: $EXIT_CODE)"
else
    echo "[ERROR] Bot crashed! Exit code: $EXIT_CODE"
fi
echo "========================================="

exit $EXIT_CODE
