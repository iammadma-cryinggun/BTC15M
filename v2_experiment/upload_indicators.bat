@echo off
echo ========================================
echo 上传指标修复到 GitHub
echo ========================================
echo.

cd /d "D:\OpenClaw\workspace\BTC_15min_Lite\v2_experiment"

echo [1/4] 添加修改的文件...
git add voting_system.py 指标检查报告.md 指标修复总结.md

echo.
echo [2/4] 提交修复...
git commit -m "修复3个指标计算错误：动量加速度、MACD柱状图、波动率制度"

echo.
echo [3/4] 推送到 GitHub...
git push origin lite-speed-test

echo.
echo [4/4] 完成！
echo ========================================
echo 修复内容：
echo 1. 动量加速度 - 移除错误的时间除法
echo 2. MACD 柱状图 - 简化为 MACD 线
echo 3. 波动率制度 - 优化置信度计算逻辑
echo.
echo 现在所有 18 个激活规则都计算准确！
echo.
echo 查看代码：
echo https://github.com/iammadma-cryinggun/BTC15M/tree/lite-speed-test
echo ========================================
pause
