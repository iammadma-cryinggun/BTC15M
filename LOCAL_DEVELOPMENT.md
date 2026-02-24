# 本地开发文件说明

## 🔍 本地专用文件（不上传到GitHub）

以下文件仅用于本地开发和调试，**不要**提交到Git：

### 调试和测试脚本
- check_*.py - 各种检查脚本
- diagnose_*.py - 诊断脚本
- test_*.py - 测试文件
- analyze_recent_trades.py - 交易分析
- backtest.py - 回测工具
- code_check.py - 代码检查
- fetch_history.py - 历史数据获取
- orderbook_impact.py - 订单簿分析
- recompute_learning.py - 重新计算学习数据
- reset_learning_stats.py - 重置学习统计

### 清理脚本
- clean_positions.py - 清理持仓
- cleanup_old_position.py - 清理旧持仓
- clear_old_positions.py - 清除旧持仓
- close_failed_positions.py - 关闭失败的仓位
- force_close_expired.py - 强制平仓过期
- mark_settled.py - 标记已结算

### 监控脚本
- 实时监控学习数据.py
- 查看学习报告.py
- 查看报告.bat
- 实时监控.bat

### 授权相关
- 一键授权.py
- 链上授权.py
- 手动平仓.py

### 启动脚本
- 启动优化版.bat

### 数据库文件（自动生成）
- *.db - SQLite数据库
- *.db-journal - 数据库临时文件

---

## ✅ 线上版本（GitHub仓库）

### 核心代码（必需）
- auto_trader_ankr.py - 主交易程序
- prediction_learning_polymarket.py - 学习系统
- main.py - Zeabur入口点

### 配置文件
- requirements.txt - Python依赖
- Dockerfile - Zeabur构建配置
- zbpack.json - Zeabur部署配置
- .gitignore - Git排除规则
- .env.example - 环境变量模板

### 文档
- README.md - 项目说明
- DEPLOYMENT_GUIDE.md - 部署指南
- GEOBLOCK_SOLUTIONS.md - 地理封锁解决方案
- OPTIMIZATION_SUMMARY.md - 优化记录

### 辅助脚本
- start.sh - 启动脚本（Zeabur用）
- 本地启动.bat - 本地启动脚本

### 备份
- backup/ - 核心文件备份

---

## 🔄 开发工作流

### 本地测试
```bash
# 1. 本地运行测试
python auto_trader_ankr.py

# 2. 使用测试脚本
python check_learning.py
python check_predictions.py
```

### 推送到线上
```bash
# 1. 检查状态
git status

# 2. 提交代码
git add .
git commit -m "描述你的修改"

# 3. 推送到GitHub
git push origin master
```

### Zeabur自动部署
- 代码推送后，Zeabur会自动重新部署
- 等待1-2分钟，服务会重启

---

## 📋 文件清理建议

可以删除的本地测试文件：
- check_*.py (可以用main.py替代)
- diagnose_*.py (调试用，平时不需要)
- backtest.py (历史数据，已过时)

建议保留的文件：
- 实时监控学习数据.py (监控学习系统)
- 查看学习报告.py (查看统计)
- 手动平仓.py (紧急手动操作)
