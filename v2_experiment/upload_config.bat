@echo off
echo ========================================
echo 上传配置修改到 GitHub
echo ========================================
echo.

cd /d "D:\OpenClaw\workspace\BTC_15min_Lite\v2_experiment"

echo [1/4] 添加修改的文件...
git add auto_trader_ankr.py 配置修改说明-全时段交易.md 修复说明-oracle错误.md

echo.
echo [2/4] 提交修改...
git commit -m "配置修改：去掉6分钟限制，恢复止盈止损功能，止损调整为50%%"

echo.
echo [3/4] 推送到 GitHub...
git push origin lite-speed-test

echo.
echo [4/4] 完成！
echo ========================================
echo 修改内容：
echo 1. 去掉 6 分钟限制，允许全时段入场
echo 2. 恢复止盈止损功能（追踪止盈 + 绝对止盈）
echo 3. 止损调整为 50%% （从 80%% 改为 50%%）
echo 4. 止盈调整为 30%% （从 90%% 改为 30%%）
echo.
echo 查看代码：
echo https://github.com/iammadma-cryinggun/BTC15M/tree/lite-speed-test
echo ========================================
pause
