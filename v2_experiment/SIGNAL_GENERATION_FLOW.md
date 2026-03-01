# 🔍 信号生成流程完整追踪

## 📊 从原始数据到最终决策的完整流程

---

## 🔄 完整数据流

```
原始数据采集
    ↓
指标计算（18个规则独立投票）
    ↓
投票聚合（多数原则 + 加权置信度）
    ↓
防御层过滤（5因子风险 dampening）
    ↓
最终决策（方向 + 置信度 + 仓位）
```

---

## 📡 Step 1: 原始数据采集

### 1.1 Polymarket数据（每3秒轮询）

**数据来源**: Polymarket CLOB API
```python
# auto_trader_ankr.py - 主循环
price = float(market.get('outcomePrices', [])[0])  # YES价格
self.price_history.append(price)
self.rsi.update(price)
self.vwap.update(price)
```

**采集数据**:
- ✅ YES价格（实时）
- ✅ 价格历史（最近20个点）
- ✅ RSI（基于价格历史计算）
- ✅ VWAP（基于价格历史计算）

### 1.2 Binance数据（WebSocket实时推送）

**数据来源**: Binance官方WebSocket
```python
# binance_oracle.py
wss://stream.binance.com:9443/ws/btcusdt@aggTrade     # 逐笔成交
wss://stream.binance.com:9443/ws/btcusdt@depth20@100ms # 盘口深度
```

**采集数据**:
- ✅ 超短动量（30s/60s/120s）
- ✅ CVD 1m/5m
- ✅ UT Bot 15m趋势
- ✅ Oracle综合分数

### 1.3 Session Memory数据（本地SQLite）

**数据来源**: 自身历史交易记录
```python
# session_memory.py
historical_sessions = get_historical_sessions(limit=200)
```

**采集数据**:
- ✅ 历史会话（30场相似场景）
- ✅ YES胜率（先验偏差）

---

## 🧮 Step 2: 指标计算（18个规则）

### 2.1 投票收集

```python
# voting_system.py Line 1070-1095
def collect_votes(self, **kwargs):
    votes = []

    for rule in self.rules:  # 18个规则
        vote = rule.evaluate(
            price=kwargs.get('price'),
            rsi=kwargs.get('rsi'),
            vwap=kwargs.get('vwap'),
            price_history=kwargs.get('price_history'),
            oracle=kwargs.get('oracle')
        )

        if vote and vote['direction'] != 'NEUTRAL':
            votes.append({
                'rule_name': rule.name,
                'direction': vote['direction'],
                'confidence': vote['confidence'],
                'reason': vote['reason'],
                'weight': rule.weight
            })

    return votes
```

### 2.2 具体规则计算示例

#### 示例1: CVD 5m规则（权重3.0x）

**输入**: `oracle['cvd_5m'] = 120000`

**计算过程**:
```python
# 阈值检查
if abs(120000) < 50000:
    return None  # 不通过
# ✓ 通过阈值

# 计算方向和置信度
direction = 'LONG'  # CVD > 0
confidence = min(120000 / 150000, 0.99) = 0.80

# 输出投票
{
    'rule_name': 'Oracle 5m CVD',
    'direction': 'LONG',
    'confidence': 0.80,
    'reason': '5m CVD +120000',
    'weight': 3.0  ← 最强指标
}
```

#### 示例2: Session Memory规则（权重1.0x）

**输入**:
- price = 0.35
- rsi = 42.0
- oracle_score = 5.0

**计算过程**:
```python
# 1. 提取5维特征
features = {
    'price_bin': 1,      # 0.20-0.40区间
    'time_slot': 2,      # 30-45分钟时段
    'rsi': 0.42,        # RSI归一化
    'oracle': 0.5,      # Oracle归一化
    'price_trend': 0.5  # 轻微上涨
}

# 2. 查找30场相似历史会话
similar_sessions = find_similar_sessions(features)

# 3. 计算先验偏差
YES胜率 = 20/30 = 66.7%
prior_bias = (20-10)/30 = 0.33

# 4. 输出投票
{
    'rule_name': 'Session Memory',
    'direction': 'LONG',
    'confidence': 0.33,
    'reason': '历史先验 0.33',
    'weight': 1.0
}
```

#### 示例3: 超短动量30s规则（权重0.8x）

**输入**: `oracle['momentum_30s'] = 1.25%`

**计算过程**:
```python
# 阈值检查
if abs(1.25) < 0.2:
    return None
# ✓ 通过阈值

# 计算方向和置信度
direction = 'LONG'
confidence = min(1.25 / 3.0, 0.99) = 0.42

# 输出投票
{
    'rule_name': 'Momentum 30s',
    'direction': 'LONG',
    'confidence': 0.42,
    'reason': '30s动量 +1.25%',
    'weight': 0.8
}
```

---

## 🗳️ Step 3: 投票聚合

### 3.1 收集所有投票

**假设18个规则中，10个参与了投票**:

```python
votes = [
  {'rule_name': 'Momentum 30s', 'direction': 'LONG', 'confidence': 0.42, 'weight': 0.8},
  {'rule_name': 'Momentum 60s', 'direction': 'LONG', 'confidence': 0.83, 'weight': 0.9},
  {'rule_name': 'Momentum 120s', 'direction': 'LONG', 'confidence': 0.99, 'weight': 1.0},
  {'rule_name': 'Price Momentum', 'direction': 'LONG', 'confidence': 0.80, 'weight': 1.0},
  {'rule_name': 'RSI', 'direction': 'LONG', 'confidence': 0.20, 'weight': 1.0},
  {'rule_name': 'VWAP', 'direction': 'SHORT', 'confidence': 0.60, 'weight': 1.0},
  {'rule_name': 'Trend Strength', 'direction': 'LONG', 'confidence': 0.44, 'weight': 1.0},
  {'rule_name': 'Oracle 5m CVD', 'direction': 'LONG', 'confidence': 0.80, 'weight': 3.0},
  {'rule_name': 'Oracle 1m CVD', 'direction': 'LONG', 'confidence': 0.90, 'weight': 1.5},
  {'rule_name': 'UT Bot 15m', 'direction': 'LONG', 'confidence': 0.70, 'weight': 1.0}
]
```

### 3.2 按方向分组

```python
long_votes = [v for v in votes if v['direction'] == 'LONG']   # 9票
short_votes = [v for v in votes if v['direction'] == 'SHORT'] # 1票
```

### 3.3 计算加权平均置信度

**LONG投票（9票）**:
```
规则1: 0.42 × 0.8 = 0.336
规则2: 0.83 × 0.9 = 0.747
规则3: 0.99 × 1.0 = 0.990
规则4: 0.80 × 1.0 = 0.800
规则5: 0.20 × 1.0 = 0.200
规则7: 0.44 × 1.0 = 0.440
规则8: 0.80 × 3.0 = 2.400  ← CVD权重最高
规则9: 0.90 × 1.5 = 1.350
规则10: 0.70 × 1.0 = 0.700

加权总和 = 7.963
总权重 = 10.2
加权置信度 = 7.963 / 10.2 = 0.781 (78.1%)
```

**SHORT投票（1票）**:
```
规则6: 0.60 × 1.0 = 0.600

加权置信度 = 0.600 (60.0%)
```

### 3.4 多数投票原则

```python
if len(long_votes) > len(short_votes):
    final_direction = 'LONG'      # 9 > 1 ✓
    final_confidence = 0.781
```

**结果**:
```
LONG:  9票 (加权置信度78.1%)
SHORT: 1票 (加权置信度60.0%)

最终方向: LONG
最终置信度: 78.1%
```

### 3.5 门槛检查

```python
# 检查最低门槛
if result['total_votes'] < 3:      # 10 ≥ 3 ✓
    return None

if result['confidence'] < 0.60:     # 0.781 ≥ 0.60 ✓
    return None

✅ 通过门槛
result['passed_gate'] = True
```

---

## 🛡️ Step 4: 防御层过滤

### 因子A: 时间锁

```python
minutes_to_expiry = 4  # 距离结算4分钟

if 2 <= minutes_to_expiry <= 5:
    multiplier = 1.0  # 黄金窗口，100%仓位
```

**结果**: ✅ 通过，multiplier = 1.0

### 因子B: 混沌过滤

```python
session_cross_count = 2  # 价格穿越2次

if session_cross_count >= 5:
    # 市场混乱
    if abs(cvd_5m) >= 150000:
        multiplier *= 1.0  # CVD极强，强行开仓
    else:
        return 0.0
```

**结果**: ✅ 通过，2 < 5，市场不混乱

### 因子C: 利润空间

```python
current_price = 0.35

if 0.28 <= current_price <= 0.43:
    multiplier *= 1.0  # 黄金区间
```

**结果**: ✅ 通过，0.35在黄金区间

### 因子D: CVD一致性

```python
oracle_score = 5.0  # Oracle分数
score = 5.0        # 信号分数（LONG为正）

if oracle_score * score < 0:
    multiplier *= 0.2  # 背离惩罚
```

**结果**: ✅ 通过，5.0 × 5.0 = 25 > 0，一致

### 因子E: 距离基准

```python
distance_from_baseline = abs(0.35 - 0.50) = 0.15

if distance_from_baseline >= 0.10:
    multiplier *= 1.0  # 远离基准
```

**结果**: ✅ 通过，0.15 > 0.10

### 最终乘数

```python
final_multiplier = 1.0  # 所有因子通过
```

---

## ✅ Step 5: 最终决策

```python
return {
    'direction': 'LONG',
    'strategy': 'VOTING_SYSTEM',
    'score': 5.0,
    'confidence': 0.78,
    'rsi': 42.0,
    'vwap': 0.34,
    'price': 0.35,
    'oracle_score': 5.0,
    'oracle_15m_trend': 'LONG',
    'defense_multiplier': 1.0,
    'vote_details': {...}
}
```

---

## 📊 信号生成总结

### 输入原始数据
```
Polymarket: YES价格=0.35, RSI=42.0, VWAP=0.34
Binance: CVD=+120000, 动量30s=+1.25%, Oracle=5.0
Session Memory: 先验偏差=+0.33
```

### 18个规则投票
```
10个规则参与投票
8个规则不投票（信号不明确）

投票结果: 9 LONG, 1 SHORT
```

### 投票聚合
```
LONG加权置信度: 78.1%
SHORT加权置信度: 60.0%
赢家: LONG（9票 vs 1票）
```

### 防御层过滤
```
时间锁: ✅ 4分钟（黄金窗口）
混沌过滤: ✅ 穿越2次（<5次）
利润空间: ✅ 价格0.35（黄金区间）
CVD一致性: ✅ 一致
距离基准: ✅ 0.15远离0.50

最终乘数: 1.0（全仓）
```

### 最终决策
```
方向: LONG
置信度: 78.1%
仓位: 100%
状态: ✅ 通过所有门槛
```

---

## 🎯 信号提炼的关键逻辑

1. **独立投票**: 18个规则独立评估，互不干扰
2. **加权聚合**: CVD等强指标有更高权重（3.0x）
3. **多数原则**: 投票数多的方向获胜
4. **门槛过滤**: 置信度<60%或投票数<3则拒绝
5. **防御 dampening**: 5个防御因子调整仓位大小

---

## 📈 与@jtrevorchapman对比

| 维度 | @jtrevorchapman | 我们的实现 |
|------|----------------|-----------|
| **规则数量** | 8-12个 | 18个 |
| **投票方式** | 独立投票 | 独立投票 ✅ |
| **聚合方式** | 多数原则 + 加权 | 多数原则 + 加权 ✅ |
| **门槛检查** | 最低门槛 | 最低门槛 ✅ |
| **防御层数量** | 5个因子 | 5个因子 ✅ |

**结论：完全按照@jtrevorchapman的三层架构运作！** ✅

---

*文档生成时间: 2026-03-01*
*版本: V2 Experiment*
*Commit: 1be1b69*
