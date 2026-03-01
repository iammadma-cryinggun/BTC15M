# V2 实验性版本 - 完整实现@jtrevorchapman的23个指标

## 📋 版本说明

这是基于@jtrevorchapman完整指标系统的实验性重构版本。

**当前运行的版本（稳定）**: `../` (父目录)
**实验性版本（本目录）**: `./v2_experiment/`

---

## 🎯 核心改动

### 1. **架构重构**
- ❌ **移除**"本地分"vs"Oracle分"的区分
- ❌ **移除**Oracle融合逻辑（同向增强/反向削弱）
- ✅ **统一投票系统**：所有指标平等输入
- ✅ **投票系统直接生成**最终方向和置信度

### 2. **新增11个指标规则**

#### **高级技术指标（7个）**

| 规则 | 对应@jtrevorchapman指标 | 说明 | 权重 |
|------|----------------------|------|------|
| **Momentum Acceleration** | - | 动量加速度（30s→60s→120s变化率） | 1.2x |
| **MACD Histogram** | MACD HIST | MACD柱状图（趋势转折点） | 1.0x |
| **EMA Cross** | EMA CROSS | EMA 9/21 交叉 | 0.9x |
| **Volatility Regime** | VOL REGIME | 波动率制度（高/低波动） | 0.8x |
| **Delta Z-Score** | DELTA Z-SCORE | CVD标准化分数 | 1.2x |
| **Price Trend 5** | - | 5周期价格趋势 | 0.8x |
| **Trading Intensity** | TRADE INTENSIVE | 交易强度（成交量变化） | 1.0x |

#### **Polymarket指标（4个）**

| 规则 | 对应@jtrevorchapman指标 | 说明 | 权重 |
|------|----------------------|------|------|
| **CL Data Age** | CL DATA AGE | 数据延迟检测（质量检查） | 0.5x |
| **PM YES** | PM YES | YES价格情绪 | 1.0x |
| **Bias Score** | BIAS SCORE | 综合偏差分数 | 1.0x |
| **PM Spread Dev** | PM SPREAD DEV | YES/NO价差异常 | 0.8x |

### 3. **占位规则（9个）**

需要Polymarket订单簿/持仓API：

- **Bid Walls** - 买墙检测
- **Ask Walls** - 卖墙检测
- **Orderbook Imbalance** - 订单簿失衡
- **NATURAL** - 自然价格（远离大单）
- **NAT ABS** - 自然价格绝对值
- **BUFFER TICKETS** - 缓冲订单数量
- **PM Spread** - PM价差（占位）
- **PM Sentiment** - PM情绪分析
- **POSITIONS** - 持仓分布

---

## 📊 投票系统配置

### **总计25个规则（对应@jtrevorchapman的23个原始指标）**

```
已激活（18个）：
  ├─ 超短动量 x3:               0.8 + 0.9 + 1.0 = 2.7x (10.9%)
  ├─ 标准指标 x5:               1.0 + 1.0 + 1.0 + 1.0 + 0.8 = 4.8x (19.4%)
  ├─ CVD系列 x3:                3.0 + 1.5 + 1.2 = 5.7x (23.0%) ← 主导
  ├─ 高级技术指标 x7:            1.2 + 1.0 + 0.9 + 0.8 + 1.2 + 0.8 + 1.0 = 6.9x (27.9%)
  ├─ PM指标 x4:                 0.5 + 1.0 + 1.0 + 0.8 = 3.3x (13.3%)
  └─ 趋势指标 x2:               1.0 + 1.0 = 2.0x (8.1%)

占位（9个，不投票）：
  └─ 订单簿/PM持仓数据 x9:      0x (0%)

总权重：25.8x（已激活18个规则）
```

### **指标覆盖率**

```
@jtrevorchapman的23个指标：

✅ 完全实现（14个）：43.5%
  ├─ MOMENTUM 30/60/120S
  ├─ RSI 14
  ├─ VWAP
  ├─ EMA CROSS
  ├─ CVD 5M/1M
  ├─ MACD HIST
  ├─ VOL REGIME
  ├─ DELTA Z-SCORE
  ├─ TRADE INTENSIVE
  └─ CL DATA AGE（新增）
  └─ PM YES（新增）
  └─ BIAS SCORE（新增）
  └─ PM SPREAD DEV（新增）

⚠️ 占位实现（9个）：39.1%
  ├─ BID WALLS
  ├─ ASK WALLS
  ├─ OBI
  ├─ NATURAL
  ├─ NAT ABS
  ├─ BUFFER TICKETS
  ├─ PM SPREAD
  ├─ PM SENTIMENT
  └─ POSITIONS

覆盖率：14/23 = 60.9% （完全实现）
       23/23 = 100% （含占位）
```

### **CVD主导地位**
- 5m CVD: 3.0x (11.6%)
- 1m CVD: 1.5x (5.8%)
- Delta Z-Score: 1.2x (4.7%)
- **CVD总权重: 5.7x (23.0%)** ← 仍然主导

---

## 🔄 与原版对比

| 维度 | 原版（V1） | 实验版（V2） |
|------|-----------|-------------|
| **架构** | 本地分 + Oracle分融合 | 统一投票系统 |
| **规则数量** | 9个规则 | 25个规则 |
| **已激活规则** | 9个 | 18个 |
| **CVD权重** | 4.5x / 11.2x (40.2%) | 5.7x / 25.8x (23.0%) |
| **@jtrevorchapman指标覆盖率** | 9/23 (39.1%) | 23/23 (100%) |
| **完全实现** | 9/23 (39.1%) | 14/23 (60.9%) |

---

## 🚀 使用方法

### **切换到实验版本**

```bash
# 停止当前运行的程序
# 然后启动实验版本
cd D:\OpenClaw\workspace\BTC_15min_Lite\v2_experiment
python auto_trader_ankr.py
```

### **回退到稳定版本**

```bash
# 停止实验版本
# 然后运行稳定版本
cd D:\OpenClaw\workspace\BTC_15min_Lite
python auto_trader_ankr.py
```

---

## ⚠️ 注意事项

1. **实验性版本未经充分测试**，建议先在模拟环境运行
2. **9个占位规则不投票**，需要Polymarket订单簿/持仓API才能激活
3. **CVD权重仍然最强**，但占比从40.2%降至23.0%（更均衡）
4. **新增11个指标可能需要调参**，请根据实盘数据调整
5. **指标覆盖率100%**（含占位规则），完全实现60.9%

---

## 📝 TODO

### **高优先级（需要API）**
- [ ] 获取Polymarket订单簿数据（激活买墙/卖墙/OBI）
- [ ] 获取Polymarket持仓数据（激活Positions规则）

### **中优先级（调参）**
- [ ] 调优新增11个指标的权重和阈值
- [ ] 回测验证25规则系统 vs 原9规则系统

### **低优先级（优化）**
- [ ] 优化投票聚合算法
- [ ] 添加规则动态权重调整

---

## 📞 相关文档

- `../ULTRA_SHORT_MOMENTUM_UPGRADE.md` - 超短动量升级文档
- `../VOTING_SYSTEM_INTEGRATION_COMPLETE.md` - 投票系统集成文档
- `../THREE_LAYER_ARCHITECTURE.md` - 三层架构文档

---

*更新时间: 2026-03-01*
*版本: V2 Experiment - Full 25 Rules*
*Commit: 755990b (待更新)*
