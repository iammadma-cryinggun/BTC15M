# 双核融合系统工作原理详解

## 🎯 什么是"双核融合"

我们的系统同时运行**两个独立的信号引擎**，然后智能融合它们的判断：

```
┌─────────────────────────────────────────────────────────────┐
│  核心A: Polymarket本地引擎（市场内部数据）                    │
│  - YES/NO代币价格                                           │
│  - RSI、VWAP、Momentum                                      │
│  - 基于二元期权市场的直接观察                                │
└─────────────────────────────────────────────────────────────┘
                          ↕
                      【融合算法】
                          ↕
┌─────────────────────────────────────────────────────────────┐
│  核心B: Binance Oracle引擎（外部真实资金流）                  │
│  - 1分钟CVD（即时资金流）                                    │
│  - 5分钟CVD（趋势确认）                                      │
│  - UT Bot + Hull Suite趋势                                  │
│  - MACD Histogram、Delta Z-Score                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 📊 核心A: Polymarket本地引擎

### 数据来源
- **Polymarket API**: 每3秒轮询一次BTC 15分钟市场的YES/NO代币价格
- **价格历史**: 保存最近20个价格点

### 评分组件（5个因子）

| 组件 | 计算方式 | 权重 | 满分范围 |
|------|---------|------|---------|
| **价格动量** | (最新价 - 10个点前) / 起始价 × 100 × 2 | 1.0 | ±10 |
| **波动率** | 标准差 / 0.1，影响置信度倍数 | 0.5~1.0 | 不直接贡献分数 |
| **VWAP偏离** | 距离VWAP ±0.5%以上 | 1.0 | ±5 |
| **RSI状态** | RSI>60做空, RSI<40做多 | 1.0 | ±5 |
| **趋势强度** | 3个点的价格变化 × 3 | 1.0 | ±5 |

### 代码逻辑

```python
def calculate_score(self, price, rsi, vwap, price_history):
    score = 0
    components = {}

    # 1. 价格动量（10个点）
    if len(price_history) >= 10:
        recent = price_history[-10:]
        momentum = (recent[-1] - recent[0]) / recent[0] * 100
        momentum_score = max(-10, min(10, momentum * 2))
        components['price_momentum'] = momentum_score
        score += momentum_score * weight

    # 2. VWAP偏离
    if vwap > 0:
        vwap_dist = ((price - vwap) / vwap * 100)
        if vwap_dist > 0.5:
            components['vwap_status'] = 1  # 偏高 → 做空倾向
        elif vwap_dist < -0.5:
            components['vwap_status'] = -1  # 偏低 → 做多倾向
        score += components['vwap_status'] * 5

    # 3. RSI状态
    if rsi > 60:
        components['rsi_status'] = -1  # 超买 → 做空
    elif rsi < 40:
        components['rsi_status'] = 1   # 超卖 → 做多
    score += components['rsi_status'] * 5

    # 4. 趋势强度（3个点）
    if len(price_history) >= 3:
        short_trend = (price_history[-1] - price_history[-3]) / price_history[-3] * 100
        trend_score = max(-5, min(5, short_trend * 3))
        components['trend_strength'] = trend_score
        score += trend_score

    # 波动率调整（影响置信度，不影响方向）
    score = score * vol_multiplier

    return score, components
```

### 输出示例

```
本地评分分析:
  price_momentum: +2.5 (价格上涨1.25%)
  vwap_status: +1 (价格高于VWAP 0.6%)
  rsi_status: 0 (RSI=52，中性)
  trend_strength: +1.2 (3个点上涨0.4%)
  波动率调整: 0.8

本地总分: +3.7 (调整后)
```

---

## 🔮 核心B: Binance Oracle引擎

### 数据来源（3个WebSocket并发连接）

| 数据流 | WebSocket地址 | 更新频率 | 用途 |
|--------|--------------|---------|------|
| **逐笔成交** | `@aggTrade` | 实时（毫秒级） | CVD计算 |
| **盘口深度** | `@depth20@100ms` | 100ms | 订单簿不平衡 |
| **15m K线** | `@kline_15m` | 每15秒 | UT Bot + Hull |

### 双CVD窗口系统（最新升级）

#### 窗口1: 1分钟即时窗口（CVD_SHORT）
```
时间范围: 最近60秒
用途: 捕捉瞬时资金流变化
评分公式: cvd_short / 50000.0
满分阈值: ±5万USD = ±3分
示例: +$45K → +0.9分
```

#### 窗口2: 5分钟趋势窗口（CVD_LONG）
```
时间范围: 最近300秒
用途: 确认持续趋势方向
评分公式: cvd_long / 150000.0
满分阈值: ±15万USD = ±5分
示例: +$120K → +4.0分
```

#### 融合策略
```python
# 长窗口权重70%，短窗口权重30%
cvd_score = cvd_long_score * 0.7 + cvd_short_score * 0.3

# 示例计算:
# cvd_long_score = +4.0
# cvd_short_score = +0.9
# cvd_score = 4.0 * 0.7 + 0.9 * 0.3 = 2.8 + 0.27 = 3.07
```

### 盘口不平衡评分

```python
# 计算买卖墙不平衡
total_wall = avg_buy_wall + avg_sell_wall
imbalance = (avg_buy_wall - avg_sell_wall) / total_wall

# 转换为分数（降低挂单权重，防止假单欺骗）
wall_score = imbalance * 3.0  # 最大±3分
```

### 核弹级信号（极端情况）

```python
# 条件：极度盘口倾斜 + 真金白银确认
if imbalance > 0.85 and cvd_long > 50000:
    return 10.0  # 强制做多，满分
elif imbalance < -0.85 and cvd_long < -50000:
    return -10.0  # 强制做空，满分
```

### 高级指标

#### 1. MACD Histogram
```python
# 基于5分钟CVD的MACD(12, 26, 9)
macd_line, signal_line, histogram = calculate_macd(cvd_history)
# 输出: -22.2680（负值 = 下跌动能）
```

#### 2. Delta Z-Score
```python
# 20周期滚动Z-Score，检测异常资金流
z_scores = (cvd_series - rolling_mean) / rolling_std
# 输出: -0.271（低于均值0.271个标准差）
```

#### 3. UT Bot + Hull Suite趋势
```python
# 基于15分钟K线
- UT Bot (key_value=1.5, atr_period=10)
- Hull MA (length=20)

综合判断:
- UT看涨 + Hull看涨 → LONG
- UT看跌 + Hull看跌 → SHORT
- 信号不一致 → NEUTRAL
```

### Oracle总分计算

```python
oracle_score = cvd_long_score * 0.7 + cvd_short_score * 0.3 + wall_score

# 示例:
# CVD融合: +3.07
# 盘口不平衡: +1.2 (多头墙占优)
# Oracle总分: +4.27
```

### Oracle输出格式

```json
{
  "signal_score": +4.27,
  "direction": "LONG",
  "cvd_1m": +45000.0,
  "cvd_5m": +120000.0,
  "buy_wall": 1500000,
  "sell_wall": 800000,
  "wall_imbalance": 0.306,
  "macd_histogram": -22.2680,
  "delta_z_score": -0.271,
  "ut_hull_trend": "LONG",
  "trend_1h": "LONG"
}
```

---

## 🔄 双核融合算法

### 场景1: 同向共振（最强信号）

**条件**: `本地分 × Oracle分 > 0`（同方向）

```python
oracle_boost = oracle_score / 5.0  # ÷5，权重适中
final_score = local_score + oracle_boost
```

**示例**:
```
本地分: +3.7 (Polymarket看涨)
Oracle: +4.27 (Binance资金流入)

融合计算:
  oracle_boost = 4.27 / 5.0 = +0.85
  final_score = 3.7 + 0.85 = +4.55

日志: [FUSION共振] 本地(3.70)与Oracle同向，÷5: +4.27 → +0.85
```

**意义**: 两个独立系统都看涨 → 信心增强 → 适当加分

---

### 场景2: 反向背离（谨慎处理）

**条件**: `本地分 × Oracle分 < 0`（反方向）

```python
oracle_boost = oracle_score / 10.0  # ÷10，权重减半
final_score = local_score + oracle_boost
```

**示例**:
```
本地分: +3.7 (Polymarket看涨)
Oracle: -4.27 (Binance资金流出)

融合计算:
  oracle_boost = -4.27 / 10.0 = -0.43
  final_score = 3.7 - 0.43 = +3.27

日志: [FUSION背离] 本地(3.70)与Oracle反向，÷10: -4.27 → -0.43
```

**意义**: 两个系统冲突 → 保持本地判断，轻微降权

---

### 场景3: 核弹级巨鲸狙击（极端情况）

**条件**: `Oracle分数 ≥ 12.0`

```python
if oracle_score >= 12.0:
    if price < 0.20 and rsi < 70:  # 低位抄底保护
        # 完全跳过常规融合逻辑
        return {
            'direction': 'LONG',
            'score': 12.0,
            'strategy': 'WHALE_SNIPER',  # VIP通道
            'defense_multiplier': 1.0  # 全仓通过
        }
```

**示例**:
```
Oracle: +12.5 (核弹级信号)
价格: $0.18 (深度超卖)
RSI: 25 (极度超卖)

日志: 🚨 [💥核弹巨鲸狙击] oracle=12.5≥12.0 | price=0.18<0.20 | RSI=25<70
      ⚠️  无视15m趋势，强制赌V型反转！
```

**意义**: 极端异常 → 独立VIP通道 → 无视常规规则

---

## 📈 完整决策流程图

```
1. 读取Oracle信号
   ├─ signal_score: +4.27
   ├─ ut_hull_trend: LONG
   └─ 本地分: +3.7

2. 检查核弹级通道
   └─ oracle_score < 12.0 → 跳过

3. 执行双核融合
   ├─ 同向判断: 3.7 × 4.27 > 0 → 是
   ├─ 计算boost: 4.27 / 5.0 = +0.85
   └─ 融合分数: 3.7 + 0.85 = +4.55

4. RSI防呆检查
   └─ RSI=52, 不在极端区间 → 通过

5. 15m UT Bot趋势检查
   └─ ut_hull_trend=LONG, 方向一致 → 通过

6. 计算置信度
   └─ confidence = |4.55| / 5.0 = 91%

7. 生成信号
   ├─ direction: LONG
   ├─ score: +4.55
   ├─ confidence: 0.91
   └─ oracle_score: +4.27

8. 防御层评估
   ├─ 时间锁检查
   ├─ 混乱度检查
   ├─ 利润空间检查
   ├─ CVD一致性检查
   └─ 基准距离检查

9. 最终仓位计算
   ├─ 基础仓位: $30 × 10% = $3.00
   ├─ 置信度调整: $3.00 × 0.91 = $2.73
   ├─ 防御乘数: 0.8
   └─ 最终仓位: $2.73 × 0.8 = $2.18
```

---

## 🎯 双核融合的优势

### 1. **跨市场验证**
- Polymarket: 预测市场（基于群体认知）
- Binance: 现货市场（基于真实资金）
- 两者一致 → 信号更可靠

### 2. **抢跑能力**
- Polymarket反映的是"预期"
- Binance反映的是"正在发生的真金白银"
- Oracle可以提前1-2分钟发现趋势

### 3. **错误纠正**
```python
# 场景：Polymarket有滞后，但Binance已开始反转
本地分: +2.0 (Polymarket还在看涨)
Oracle: -6.0 (Binance已经开始砸盘)

融合后: 2.0 + (-6.0/10) = 1.4
# 分数降低，可能避免一次亏损交易
```

### 4. **噪音过滤**
```python
# 场景：Polymarket假突破
本地分: -3.5 (假跌破)
Oracle: +5.0 (Binance无恐慌性抛售)

融合后: -3.5 + 0.5 = -3.0
# Oracle削弱了假信号
```

---

## 🔧 参数调整

### Oracle融合权重

| 场景 | 当前配置 | 更激进 | 更保守 |
|------|---------|--------|--------|
| **同向** | ÷5 | ÷3 | ÷8 |
| **反向** | ÷10 | ÷5 | ÷15 |

**修改位置**: `auto_trader_ankr.py` line 1874-1878

```python
# 当前配置
if oracle_score * score > 0:
    oracle_boost = oracle_score / 5.0   # 同向
else:
    oracle_boost = oracle_score / 10.0  # 反向
```

### CVD窗口权重

| 场景 | 当前配置 | 更重视速度 | 更重视稳定 |
|------|---------|-----------|-----------|
| **长窗口** | 70% | 50% | 90% |
| **短窗口** | 30% | 50% | 10% |

**修改位置**: `binance_oracle.py` line 258-260

```python
# 当前配置
cvd_score = cvd_long_score * 0.7 + cvd_short_score * 0.3
```

---

## 📊 实际运行示例

### 示例1: 完美共振

```
[ORACLE] 先知分:+5.20 | 15m UT Bot:LONG | 本地分:+4.10
[FUSION共振] 本地(4.10)与Oracle同向，÷5: +5.20 → +1.04
[🧠 MEMORY] 先验偏差: +0.35 (历史数据显示LONG胜率72%)
       [MEMORY应用] 先知偏差+0.35 × 2.0 = +0.70 → 本地分调整至4.80
[🛡️ 防御层] 全仓通过 (乘数1.0)

最终信号:
  方向: LONG
  分数: +5.84
  置信度: 99%
  仓位: $3.00 (满仓)
```

### 示例2: 谨慎重合

```
[ORACLE] 先知分:-3.80 | 15m UT Bot:SHORT | 本地分:+2.50
[FUSION背离] 本地(2.50)与Oracle反向，÷10: -3.80 → -0.38
       [融合后分数: +2.12 (未达到做多门槛4.0)]

结果: 放弃交易（信号不够强）
```

### 示例3: 核弹级狙击

```
[ORACLE] 先知分:+12.50 | 15m UT Bot:SHORT | 本地分:-1.20
🚨 [💥核弹巨鲸狙击] oracle=12.5≥12.0 | price=0.15<0.20 | RSI=22<70
    ⚠️  无视15m趋势(SHORT)，强制赌V型反转！

结果: 满仓做多LONG $5.00 (VIP通道，防御层全通过)
```

---

## 🎓 总结

**双核融合** = **Polymarket本地观察** + **Binance资金流验证**

- **核心A**: 告诉你"市场在做什么"
- **核心B**: 告诉你"真金白银在做什么"
- **融合算法**: 判断两者是否一致，决定信任程度
- **防御层**: 控制最终仓位大小

**关键公式**:
```
最终分数 = 本地分 + (Oracle分 × 融合权重) + (先验偏差 × 2.0)
最终仓位 = 基础仓位 × 置信度 × 防御乘数
```

**核心优势**:
- ✅ 跨市场验证（降低单一市场噪音）
- ✅ 抢跑能力（Oracle提前1-2分钟）
- ✅ 错误纠正（反向时削弱本地判断）
- ✅ 极端情况捕捉（核弹级信号VIP通道）

---

*最后更新: 2026-03-01*
*版本: v1.1 - 双CVD窗口系统*
