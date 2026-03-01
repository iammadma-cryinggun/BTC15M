# BTC 15min Trading Bot - Lightweight Version

## 简介
轻量级版本，包含核心交易逻辑和双引擎架构，用于快速部署和测试。

## 文件说明
- `auto_trader_ankr.py` - 主交易逻辑 V5（REST轮询模式，稳定）
- `v6_hft_engine.py` - 高频交易引擎 V6（WebSocket模式，实验性）
- `binance_oracle.py` - Binance Oracle系统（CVD信号，极速版：2分钟窗口+核弹熔断）
- `oracle_params.json` - 动态参数配置文件
- `requirements.txt` - Python依赖包
- `start.py` - 启动脚本（支持V5/V6选择）

## 双引擎架构

### V5 - REST轮询模式（稳定）
- 每3秒轮询一次市场
- 适合生产环境
- 资源占用低
- 启动：`python start.py` 或 `python start.py v5`

### V6 - WebSocket高频模式（实验性）
- 实时WebSocket连接
- 毫秒级响应
- 需要更稳定的网络
- 启动：`python start.py v6`

## 核心特性
- Polymarket 15分钟市场自动交易
- UT Bot + Hull Suite 趋势过滤
- Binance CVD双核融合信号（极速版）
- 动态仓位管理（15%-30%）
- 智能止盈止损系统
- 极速Oracle：2分钟CVD窗口 + 核弹级失衡熔断

## 快速开始
```bash
# 安装依赖
pip install -r requirements.txt

# 修改配置（如果需要）
vim oracle_params.json

# 启动Oracle系统（第一个终端）
python binance_oracle.py

# 启动交易系统（第二个终端）
python start.py
# 或指定版本：python start.py v5 / python start.py v6
```

## 配置说明
`oracle_params.json` 支持热更新：
- `ut_bot_key_value`: UT Bot敏感度（默认1.5）
- `ut_bot_atr_period`: ATR周期（默认10）
- `hull_length`: Hull MA周期（默认20，约5小时）

## 极速Oracle改进（双窗口系统）
- **CVD窗口**: 双窗口系统（1分钟即时 + 5分钟趋势）
- **融合策略**: 5分钟窗口权重70%，1分钟窗口权重30%
- **高级指标**: MACD Histogram + Delta Z-Score（异常检测）
- **核弹熔断**: 盘口失衡>0.85且5分钟CVD>50K → 直接满分10.0
- **反向熔断**: 盘口失衡<-0.85且5分钟CVD<-50K → 直接满分-10.0

## 数据库
运行后会自动生成：
- `btc_15min_auto_trades.db` - 交易记录

## 注意事项
- 需要配置钱包私钥（RPC节点）
- 需要配置Telegram通知（可选）
- 建议先在测试环境运行

## 版本历史
- 创建日期: 2026-02-27
- 基于版本: BTC_15min_V5_Professional
- 提交: 017cbc6 (完全恢复老版本逻辑)
- 轻量化: 删除学习系统，保留交易分析
- 极速化: Oracle 2分钟窗口 + 核弹熔断
