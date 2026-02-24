@echo off
chcp 65001 >nul
title 实时监控学习数据
cd /d D:\OpenClaw\workspace\BTC_15min_V5_Professional

echo.
echo ========================================
echo   启动实时监控（每30秒刷新）
echo   按 Ctrl+C 退出
echo ========================================
echo.

python 实时监控学习数据.py

pause
