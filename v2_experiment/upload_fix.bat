@echo off
echo ========================================
echo 上传 oracle 错误修复到 GitHub
echo ========================================
echo.

cd /d "D:\OpenClaw\workspace\BTC_15min_Lite\v2_experiment"

echo [1/4] 添加修改的文件...
git add auto_trader_ankr.py 修复说明-oracle错误.md

echo.
echo [2/4] 提交修复...
git commit -m "修复oracle变量未定义错误：添加oracle参数到calculate_defense_multiplier方法"

echo.
echo [3/4] 推送到 GitHub...
git push origin lite-speed-test

echo.
echo [4/4] 完成！
echo ========================================
echo 修复内容：
echo - 修复 calculate_defense_multiplier 方法缺少 oracle 参数
echo - 修复 CVD 否决权检查时的变量未定义错误
echo.
echo 查看代码：
echo https://github.com/iammadma-cryinggun/BTC15M/tree/lite-speed-test
echo ========================================
pause
