@echo off
echo ========================================
echo 上传止盈开关修改到 GitHub
echo ========================================
echo.

cd /d "D:\OpenClaw\workspace\BTC_15min_Lite\v2_experiment"

echo [1/4] 添加修改的文件...
git add auto_trader_ankr.py voting_system.py CHANGES.md 止盈开关说明.md

echo.
echo [2/4] 提交修改...
git commit -m "添加止盈开关：暂时禁用追踪止盈和绝对止盈，补充投票系统7个占位规则"

echo.
echo [3/4] 推送到 GitHub...
git push origin lite-speed-test

echo.
echo [4/4] 完成！
echo ========================================
echo 查看代码：
echo https://github.com/iammadma-cryinggun/BTC15M/tree/lite-speed-test
echo ========================================
pause
