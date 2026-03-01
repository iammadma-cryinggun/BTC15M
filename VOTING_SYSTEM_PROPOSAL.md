# 采用图片平台置信度计算方式的实施方案

## 🎯 目标

从**分数归一化**改为**多规则投票系统**

---

## 📊 当前方式 vs 图片平台方式

### 当前方式（分数归一化）

```python
# 1. 计算本地分数
local_score = (
    price_momentum * 1.0 +
    vwap_status * 1.0 +
    rsi_status * 1.0 +
    trend_strength * 1.0
) * vol_multiplier

# 2. Oracle融合
oracle_boost = oracle_score / 5.0 if 同向 else oracle_score / 10.0
fused_score = local_score + oracle_boost

# 3. Memory调整
prior_adjustment = prior_bias * 2.0
final_score = fused_score + prior_adjustment

# 4. 分数归一化为置信度
confidence = min(abs(final_score) / 5.0, 0.99)

# 5. 判断方向
if final_score >= 4.0:
    direction = 'LONG'
elif final_score <= -3.0:
    direction = 'SHORT'
```

**特点**：
- ✅ 简单
- ❌ 无法追溯每个组件的贡献
- ❌ 所有组件融合后丢失细节

---

### 图片平台方式（多规则投票）

```python
# 1. 每个规则独立投票
rules = [
    {'name': 'Price Momentum', 'direction': 'LONG', 'confidence': 0.70},
    {'name': 'RSI', 'direction': 'LONG', 'confidence': 0.65},
    {'name': 'VWAP', 'direction': 'LONG', 'confidence': 0.55},
    {'name': 'Trend Strength', 'direction': 'SHORT', 'confidence': 0.45},
    {'name': 'Oracle 5m CVD', 'direction': 'LONG', 'confidence': 0.78},
    {'name': 'Oracle 1m CVD', 'direction': 'LONG', 'confidence': 0.72},
    {'name': 'UT Bot 15m', 'direction': 'LONG', 'confidence': 0.60},
    {'name': 'Session Memory', 'direction': 'LONG', 'confidence': 0.68},
]

# 2. 按方向分组
long_votes = [r for r in rules if r['direction'] == 'LONG']
short_votes = [r for r in rules if r['direction'] == 'SHORT']

# 3. 计算每个方向的平均置信度
long_confidence = sum(r['confidence'] for r in long_votes) / len(long_votes) if long_votes else 0
short_confidence = sum(r['confidence'] for r in short_votes) / len(short_votes) if short_votes else 0

# 4. 确定赢家方向
if long_confidence > short_confidence:
    final_direction = 'LONG'
    final_confidence = long_confidence
else:
    final_direction = 'SHORT'
    final_confidence = short_confidence

# 5. 阈值判断
if final_confidence >= 0.60:  # 60% gate
    # 可以交易
    pass
```

**特点**：
- ✅ 可以追溯每个规则的贡献
- ✅ 可以看到"投票一致性"
- ✅ 更灵活（可以动态调整规则）
- ❌ 更复杂

---

## 🚀 实施方案

### 方案1: 最小改动（推荐）

**改动点**：
1. 修改 `V5SignalScorer` 类，改为输出规则投票
2. 修改 `generate_signal()` 方法，改为投票聚合
3. 保持其他逻辑不变

**优点**：
- ✅ 改动最小
- ✅ 风险可控
- ✅ 可以逐步测试

---

### 方案2: 完全重构

**改动点**：
1. 创建 `SignalRule` 基类
2. 每个指标作为独立的规则类
3. 创建 `VotingSystem` 类管理投票
4. 完全重写信号生成逻辑

**优点**：
- ✅ 架构更清晰
- ✅ 易于扩展
- ❌ 改动大，风险高

---

## 💡 推荐方案1的实施细节

### 步骤1: 修改评分类

```python
# auto_trader_ankr.py

class V5SignalScorer:
    def calculate_rules(self, price: float, rsi: float, vwap: float,
                        price_history: list, oracle: dict = None) -> list:
        """
        计算每个规则的独立投票

        返回: [
            {'name': 'price_momentum', 'direction': 'LONG', 'confidence': 0.70, 'reason': '...'},
            {'name': 'rsi', 'direction': 'LONG', 'confidence': 0.65, 'reason': '...'},
            ...
        ]
        """
        rules = []

        # 规则1: 价格动量
        if len(price_history) >= 10:
            recent = price_history[-10:]
            momentum = (recent[-1] - recent[0]) / recent[0] * 100
            score = max(-10, min(10, momentum * 2))

            # 转换为方向和置信度
            if score > 2.0:
                direction = 'LONG'
                confidence = min(abs(score) / 10.0, 0.99)
            elif score < -2.0:
                direction = 'SHORT'
                confidence = min(abs(score) / 10.0, 0.99)
            else:
                direction = 'NEUTRAL'
                confidence = 0.0

            rules.append({
                'name': 'Price Momentum',
                'direction': direction,
                'confidence': confidence,
                'raw_score': score,
                'reason': f'Momentum: {momentum:+.2f}%'
            })

        # 规则2: RSI
        if rsi > 60:
            direction = 'SHORT'
            confidence = (rsi - 60) / 40.0  # 60→0%, 100→100%
        elif rsi < 40:
            direction = 'LONG'
            confidence = (40 - rsi) / 40.0  # 40→0%, 0→100%
        else:
            direction = 'NEUTRAL'
            confidence = 0.0

        rules.append({
            'name': 'RSI',
            'direction': direction,
            'confidence': confidence,
            'raw_score': 0,
            'reason': f'RSI: {rsi:.1f}'
        })

        # 规则3: VWAP偏离
        if vwap > 0:
            vwap_dist = ((price - vwap) / vwap * 100)
            if vwap_dist > 0.5:
                direction = 'SHORT'
                confidence = min(abs(vwap_dist) / 2.0, 0.99)
            elif vwap_dist < -0.5:
                direction = 'LONG'
                confidence = min(abs(vwap_dist) / 2.0, 0.99)
            else:
                direction = 'NEUTRAL'
                confidence = 0.0

            rules.append({
                'name': 'VWAP',
                'direction': direction,
                'confidence': confidence,
                'raw_score': 0,
                'reason': f'VWAP deviation: {vwap_dist:+.2f}%'
            })

        # 规则4: 趋势强度
        if len(price_history) >= 3:
            short_trend = (price_history[-1] - price_history[-3]) / price_history[-3] * 100
            trend_score = max(-5, min(5, short_trend * 3))

            if trend_score > 1.5:
                direction = 'LONG'
                confidence = min(abs(trend_score) / 5.0, 0.99)
            elif trend_score < -1.5:
                direction = 'SHORT'
                confidence = min(abs(trend_score) / 5.0, 0.99)
            else:
                direction = 'NEUTRAL'
                confidence = 0.0

            rules.append({
                'name': 'Trend Strength',
                'direction': direction,
                'confidence': confidence,
                'raw_score': trend_score,
                'reason': f'3-period trend: {short_trend:+.2f}%'
            })

        # 规则5-8: Oracle相关规则
        if oracle:
            oracle_score = oracle.get('signal_score', 0.0)
            cvd_1m = oracle.get('cvd_1m', 0.0)
            cvd_5m = oracle.get('cvd_5m', 0.0)
            ut_hull_trend = oracle.get('ut_hull_trend', 'NEUTRAL')

            # Oracle 5m CVD
            if abs(cvd_5m) >= 50000:
                direction = 'LONG' if cvd_5m > 0 else 'SHORT'
                confidence = min(abs(cvd_5m) / 150000.0, 0.99)
                rules.append({
                    'name': 'Oracle 5m CVD',
                    'direction': direction,
                    'confidence': confidence,
                    'raw_score': cvd_5m,
                    'reason': f'5m CVD: {cvd_5m:+.0f}'
                })

            # Oracle 1m CVD
            if abs(cvd_1m) >= 20000:
                direction = 'LONG' if cvd_1m > 0 else 'SHORT'
                confidence = min(abs(cvd_1m) / 50000.0, 0.99)
                rules.append({
                    'name': 'Oracle 1m CVD',
                    'direction': direction,
                    'confidence': confidence,
                    'raw_score': cvd_1m,
                    'reason': f'1m CVD: {cvd_1m:+.0f}'
                })

            # UT Bot 15m趋势
            if ut_hull_trend != 'NEUTRAL':
                confidence = 0.70  # 趋势指标给较高置信度
                rules.append({
                    'name': 'UT Bot 15m',
                    'direction': ut_hull_trend,
                    'confidence': confidence,
                    'raw_score': 0,
                    'reason': f'15m UT Bot trend: {ut_hull_trend}'
                })

        # 规则9: Session Memory
        if self.session_memory:
            try:
                features = self.session_memory.extract_session_features({...})
                prior_bias, _ = self.session_memory.calculate_prior_bias(features)

                if abs(prior_bias) >= 0.3:
                    direction = 'LONG' if prior_bias > 0 else 'SHORT'
                    confidence = min(abs(prior_bias), 0.99)
                    rules.append({
                        'name': 'Session Memory',
                        'direction': direction,
                        'confidence': confidence,
                        'raw_score': prior_bias,
                        'reason': f'Prior bias: {prior_bias:+.2f}'
                    })
            except:
                pass

        # 过滤掉NEUTRAL的规则
        rules = [r for r in rules if r['direction'] != 'NEUTRAL']

        return rules
```

---

### 步骤2: 投票聚合

```python
def aggregate_votes(self, rules: list) -> dict:
    """
    聚合多个规则的投票

    返回: {
        'direction': 'LONG' or 'SHORT',
        'confidence': 0.65,
        'long_votes': 7,
        'short_votes': 1,
        'long_confidence': 0.70,
        'short_confidence': 0.45
    }
    """
    if not rules:
        return None

    # 按方向分组
    long_rules = [r for r in rules if r['direction'] == 'LONG']
    short_rules = [r for r in rules if r['direction'] == 'SHORT']

    # 计算每个方向的平均置信度
    long_confidence = sum(r['confidence'] for r in long_rules) / len(long_rules) if long_rules else 0
    short_confidence = sum(r['confidence'] for r in short_rules) / len(short_rules) if short_rules else 0

    # 赢家方向 = 平均置信度更高的方向
    if long_confidence >= short_confidence:
        final_direction = 'LONG'
        final_confidence = long_confidence
    else:
        final_direction = 'SHORT'
        final_confidence = short_confidence

    return {
        'direction': final_direction,
        'confidence': final_confidence,
        'long_votes': len(long_rules),
        'short_votes': len(short_rules),
        'long_confidence': long_confidence,
        'short_confidence': short_confidence,
        'all_rules': rules
    }
```

---

### 步骤3: 修改generate_signal()

```python
def generate_signal(self, market: Dict, price: float, no_price: float = None) -> Optional[Dict]:
    # ... 前面的代码保持不变 ...

    # 新的投票系统
    rules = self.scorer.calculate_rules(price, rsi, vwap, price_hist, oracle)

    if not rules:
        return None

    # 打印每个规则的投票
    print(f"\n       [VOTING] 规则投票结果:")
    for i, rule in enumerate(rules, 1):
        icon = "🟢" if rule['direction'] == 'LONG' else "🔴"
        print(f"         {i}. {icon} {rule['name']}: {rule['direction']} {rule['confidence']:.0%} - {rule['reason']}")

    # 聚合投票
    vote_result = self.aggregate_votes(rules)

    if not vote_result:
        return None

    final_direction = vote_result['direction']
    final_confidence = vote_result['confidence']

    # 打印聚合结果
    print(f"\n       [AGGREGATION] 投票统计:")
    print(f"         LONG: {vote_result['long_votes']}票 (平均置信度{vote_result['long_confidence']:.0%})")
    print(f"         SHORT: {vote_result['short_votes']}票 (平均置信度{vote_result['short_confidence']:.0%})")
    print(f"         最终方向: {final_direction} | 置信度: {final_confidence:.0%}")

    # 置信度阈值检查
    min_confidence = 0.60  # 60% gate
    if final_confidence < min_confidence:
        print(f"         [REJECT] 置信度{final_confidence:.0%} < 门槛{min_confidence:.0%}")
        return None

    # 防御层评估
    defense_multiplier = self.calculate_defense_multiplier(price, 0, 0)  # 参数需要调整

    if defense_multiplier <= 0:
        print(f"         [DEFENSE] 防御层拦截")
        return None

    # 返回信号
    return {
        'direction': final_direction,
        'strategy': 'VOTING_SYSTEM',
        'score': 0,  # 不再使用分数
        'confidence': final_confidence,
        'vote_details': vote_result,
        'defense_multiplier': defense_multiplier,
        'rsi': rsi,
        'vwap': vwap,
        'price': price
    }
```

---

## 📊 效果对比

### 改动前

```
[ORACLE] 先知分:+4.27 | 15m UT Bot:LONG | 本地分:+3.70
[FUSION共振] 本地(3.70)与Oracle同向，÷5: +4.27 → +0.85
[MEMORY应用] 先知偏差+0.35 × 2.0 = +0.70 → 本地分调整至4.55
最终分数: +5.25, 置信度: 99%
```

### 改动后

```
       [VOTING] 规则投票结果:
         1. 🟢 Price Momentum: LONG 70% - Momentum: +1.25%
         2. 🟢 RSI: LONG 65% - RSI: 42.0
         3. 🟢 VWAP: LONG 55% - VWAP deviation: -0.60%
         4. 🟢 Trend Strength: LONG 60% - 3-period trend: +0.80%
         5. 🟢 Oracle 5m CVD: LONG 78% - 5m CVD: +120000
         6. 🟢 Oracle 1m CVD: LONG 72% - 1m CVD: +45000
         7. 🟢 UT Bot 15m: LONG 70% - 15m UT Bot trend: LONG
         8. 🟢 Session Memory: LONG 68% - Prior bias: +0.68

       [AGGREGATION] 投票统计:
         LONG: 8票 (平均置信度67%)
         SHORT: 0票 (平均置信度0%)
         最终方向: LONG | 置信度: 67%
```

---

## ✅ 优缺点分析

### 优点

1. **透明度高**
   - 可以看到每个规则的投票
   - 可以追溯哪个规则贡献大
   - 易于调试和优化

2. **灵活性高**
   - 可以动态添加/删除规则
   - 可以调整单个规则的权重
   - 可以禁用某个规则测试

3. **符合专业平台**
   - 与图片平台架构一致
   - 更容易被理解

### 缺点

1. **复杂度增加**
   - 代码量增加
   - 需要维护多个规则
   - 调试更困难

2. **性能开销**
   - 需要计算多个规则
   - 聚合计算需要额外时间

3. **参数调优**
   - 每个规则需要调参
   - 置信度阈值需要验证

---

## 🎯 建议

### 如果你想尝试

1. **先做实验版本**
   - 创建新文件 `auto_trader_voting.py`
   - 实现投票系统
   - 与现有系统并行测试

2. **回测验证**
   - 用历史数据回测
   - 对比投票系统 vs 当前系统
   - 验证胜率、盈利率

3. **逐步切换**
   - 先在测试环境运行
   - 确认稳定后再部署
   - 保留回退选项

### 如果不确定

1. **保持当前系统**
   - 已经验证有效
   - 简单可靠
   - 风险低

2. **增强日志**
   - 在当前系统中增加详细日志
   - 显示每个组件的贡献
   - 达到类似的透明度

---

## 📞 下一步

你想要我：
1. **实现投票系统** - 创建完整的代码
2. **做实验版本** - 创建 `auto_trader_voting.py`
3. **增强当前日志** - 不改架构，只增加详细输出
4. **保持现状** - 不做改动

请告诉我你的选择，我会相应实施。

---

*最后更新: 2026-03-01*
