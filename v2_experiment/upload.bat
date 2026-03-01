@echo off
echo ========================================
echo Git 上传脚本
echo ========================================
echo.

cd /d "D:\OpenClaw\workspace\BTC_15min_Lite\v2_experiment"

echo [1/6] 检查 Git 状态...
git status

echo.
echo [2/6] 添加所有修改的文件...
git add auto_trader_ankr.py voting_system.py CHANGES.md

echo.
echo [3/6] 提交修改...
git commit -m "补充投票系统7个占位规则和缺失的Polymarket API方法"

echo.
echo [4/6] 检查远程仓库...
git remote -v

echo.
echo [5/6] 如果没有远程仓库，添加它...
git remote add origin https://github.com/iammadma-cryinggun/BTC15M.git 2>nul

echo.
echo [6/6] 推送到 lite-speed-test 分支...
git push -u origin lite-speed-test --force

echo.
echo ========================================
echo 上传完成！
echo ========================================
pause
