@echo off
chcp 65001 >nul
title 查看学习报告
cd /d D:\OpenClaw\workspace\BTC_15min_V5_Professional

echo.
echo ========================================
echo   预测学习报告查看器
echo ========================================
echo.

python 查看学习报告.py

echo.
echo 按任意键退出...
pause >nul
