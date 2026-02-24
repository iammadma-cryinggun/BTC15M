@echo off
title V5 Trading - Optimized for Real Balance
cd /d D:\OpenClaw\workspace\BTC_15min_V5_Professional

echo ================================================================================
echo V5 Auto Trading - OPTIMIZED FOR YOUR BALANCE
echo ================================================================================
echo.
echo Your Wallet: 0xa2df6aa5222938db97bf2d4224cffee51bd047bd
echo.
echo Optimized Configuration:
echo   - Minimum order: 2 USDC (Polymarket requirement)
echo   - Position size: 10%% of balance
echo   - No reserve (all funds available)
echo   - Max daily loss: 20%% of balance
echo.
echo With ~20 USDC balance:
echo   - Each trade: ~2 USDC
echo   - Can make: ~10 trades
echo   - Max daily loss: ~4 USDC
echo.
echo Press Ctrl+C to cancel, or
pause
echo.
echo Starting optimized system...
echo.

:: 设置本地代理网络环境
set HTTP_PROXY=http://127.0.0.1:15236
set HTTPS_PROXY=http://127.0.0.1:15236

:: 这里是循环重启的起点
:START_BOT
python -u auto_trader_ankr.py

:: 如果 Python 脚本因为网络断开等严重异常退出了，就会执行到下面这里
echo.
echo ================================================================================
echo [警告] 交易程序意外退出！将在 10 秒后自动重新启动...
echo 如果你想彻底停止，请现在快速按下 Ctrl+C 然后按 Y 确认。
echo ================================================================================
timeout /t 10
goto START_BOT