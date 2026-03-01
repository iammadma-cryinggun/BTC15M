# Git 上传脚本
Set-Location "D:\OpenClaw\workspace\BTC_15min_Lite\v2_experiment"

Write-Host "========================================"
Write-Host "开始上传到 GitHub"
Write-Host "========================================"
Write-Host ""

Write-Host "[1/6] 添加修改的文件..."
git add auto_trader_ankr.py voting_system.py CHANGES.md

Write-Host ""
Write-Host "[2/6] 提交修改..."
git commit -m "补充投票系统7个占位规则和缺失的Polymarket API方法"

Write-Host ""
Write-Host "[3/6] 检查远程仓库..."
$remotes = git remote -v
if (-not ($remotes -match "origin")) {
    Write-Host "添加远程仓库..."
    git remote add origin https://github.com/iammadma-cryinggun/BTC15M.git
}

Write-Host ""
Write-Host "[4/6] 切换到 lite-speed-test 分支..."
git branch -M lite-speed-test

Write-Host ""
Write-Host "[5/6] 推送到 GitHub..."
git push -u origin lite-speed-test --force

Write-Host ""
Write-Host "========================================"
Write-Host "上传完成！"
Write-Host "========================================"
Write-Host ""
Write-Host "查看代码："
Write-Host "https://github.com/iammadma-cryinggun/BTC15M/tree/lite-speed-test"
