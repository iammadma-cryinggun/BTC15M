#!/bin/bash
# 快速上传脚本 - 隐患修复版本

cd D:\OpenClaw\workspace\BTC_15min_Lite

# 添加修改的文件
git add defense_layer.py
git add voting_system.py
git add voting_rules_config.py
git add 隐患修复报告.md

# 提交更改
git commit -m "🔧 修复两个关键隐患：时钟偏差 & CVD权重稀释

✅ 隐患1：本地时钟偏差风险
- 废弃本地取模计算 (15 - now.minute % 15)
- 改用绝对时间戳 (endTimestamp)
- 精确到毫秒级，不受本地时钟影响

✅ 隐患2：CVD权重被稀释
- CVD权重从 2.0 提升到 5.7
- 技术指标权重从 4.0 降低到 2.6
- CVD占比从 22% 提升到 55%

🎯 效果：
- 真金白银的声音永远大过图形指标
- 避免主力画门洗盘时被误导
- 跟随真实的订单流动向

📊 CVD统治级权重：
- Oracle 5m CVD: 3.0x (统治级)
- Oracle 1m CVD: 1.5x (即时动量)
- Delta Z-Score: 1.2x (CVD标准化)"

# 推送到 GitHub
git push origin lite-speed-test

echo "✅ 上传完成！"
echo "查看：https://github.com/iammadma-cryinggun/BTC15M/tree/lite-speed-test"
