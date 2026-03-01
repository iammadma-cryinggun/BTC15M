# Oracle融合算法版本对比

## 📜 版本演变

### 🟢 版本1：初始版（2026-02-28）

**融合权重**：
```python
# 同向共振
oracle_boost = oracle_score / 2.5  # 最多±3.6分

# 反向背离
oracle_boost = oracle_score / 5.0   # 最多±1.8分

# 巨鲸熔断（VIP通道）
if oracle_score >= 9.0:
    return WHALE_SNIPER  # 满分通道
```

**特点**：
- Oracle权重较高（÷2.5）
- 巨鲸阈值9.0（较低）
- 适合：抢跑能力强，但容易假信号

---

### 🟡 版本2：三层融合版（2026-02-28）

**融合权重**：
```python
# 噪音豁免（abs(score) < 1.0）
oracle_boost = oracle_score / 2.5

# 正常同向
oracle_boost = oracle_score / 3.0    # 最多±3.3分

# 严重背离
oracle_boost = oracle_score / 6.0    # 最多±1.5分
```

**特点**：
- 复杂的三层逻辑
- 区分噪音、正常、背离
- 过度复杂，效果不佳

---

### 🔵 版本3：恢复旧版（当前，2026-03-01）

**融合权重**：
```python
# 同向共振
oracle_boost = oracle_score / 5.0   # 最多±2.0分

# 反向背离
oracle_boost = oracle_score / 10.0  # 最多±1.0分

# 核弹VIP通道
if oracle_score >= 12.0:
    return NUCLEAR_SNIPER  # 满分通道
```

**特点**：
- 简化逻辑（只有同向/反向）
- Oracle权重降低（更保守）
- 核弹阈值提高到12.0

---

## 🎯 图片平台的置信度计算

从图片分析，专业平台的置信度计算方式：

### 方法1：加权投票法

```python
# 8-12个规则独立投票
rules = [
    {'rule': 'Momentum 30s', 'direction': 'LONG', 'confidence': 0.55},
    {'rule': 'Momentum 60s', 'direction': 'LONG', 'confidence': 0.45},
    {'rule': 'CVD 5m', 'direction': 'LONG', 'confidence': 0.78},
    {'rule': 'CVD 1m', 'direction': 'LONG', 'confidence': 0.72},
    {'rule': 'UT Bot 15m', 'direction': 'LONG', 'confidence': 0.60},
    {'rule': 'RSI', 'direction': 'LONG', 'confidence': 0.65},
    {'rule': 'VWAP', 'direction': 'LONG', 'confidence': 0.55},
    {'rule': 'MACD', 'direction': 'LONG', 'confidence': 0.58},
]

# 计算每个方向的加权置信度
long_confidence = sum(r['confidence'] for r in rules if r['direction'] == 'LONG') / len([r for r in rules if r['direction'] == 'LONG'])
short_confidence = sum(r['confidence'] for r in rules if r['direction'] == 'SHORT']) / len([r for r in rules if r['direction'] == 'SHORT']) if any(r['direction'] == 'SHORT' for r in rules) else 0

# 最终方向和置信度
if long_confidence > short_confidence:
    final_direction = 'LONG'
    final_confidence = long_confidence
else:
    final_direction = 'SHORT'
    final_confidence = short_confidence
```

### 方法2：分数归一化法（我们当前的）

```python
# 融合分数范围：-10到+10
final_score = 5.25

# 转换为置信度（0-1）
confidence = min(abs(final_score) / 5.0, 0.99)

# 示例：
# score = 5.0  → confidence = 1.0 (100%)
# score = 2.5  → confidence = 0.5 (50%)
# score = 0.0  → confidence = 0.0 (0%)
```

### 对比

| 方法 | 图片平台 | 我们的系统 |
|------|---------|-----------|
| **计算方式** | 多规则加权投票 | 分数归一化 |
| **输入** | 8-12个独立规则 | 融合后的单一分数 |
| **输出** | 0-100% | 0-99% |
| **优势** | 更精细，可追溯规则来源 | 简单直接 |
| **劣势** | 复杂，需要维护多个规则 | 无法追溯哪个规则贡献大 |

---

## 🔧 修改建议

### 去掉核弹VIP通道

```python
# 删除这段代码（line 1815-1865）
if oracle_score >= WHALE_NUCLEAR_SCORE:
    # ... VIP通道逻辑
    return WHALE_SNIPER
```

**理由**：
1. 核弹级信号（Oracle≥12.0）极少出现
2. 即使出现，也应该通过正常融合逻辑处理
3. 避免绕过防御层的安全检查

### 保留当前融合权重

```python
# 当前配置（推荐保持）
同向：÷5   # Oracle最多贡献±2分
反向：÷10  # Oracle最多贡献±1分
```

**理由**：
1. 已验证可行
2. Oracle提供参考但不主导
3. 本地市场保持主要话语权

---

## 📊 实际案例对比

### 案例1：同向共振

```
本地分: +4.0
Oracle: +5.0

版本1 (÷2.5): 4.0 + 2.0 = 6.0
版本2 (÷3):   4.0 + 1.67 = 5.67
版本3 (÷5):   4.0 + 1.0 = 5.0  ← 当前

结论：版本3最保守，Oracle影响最小
```

### 案例2：反向背离

```
本地分: +4.0
Oracle: -5.0

版本1 (÷5):  4.0 - 1.0 = 3.0
版本2 (÷6):  4.0 - 0.83 = 3.17
版本3 (÷10): 4.0 - 0.5 = 3.5  ← 当前

结论：版本3最尊重本地判断，Oracle削弱最小
```

### 案例3：核弹级信号（去掉后）

```
Oracle: +12.5
本地分: -2.0

有VIP通道:
  → 直接返回 +12.5，无视本地判断

去掉VIP通道:
  → 反向融合：-2.0 + (12.5 / 10) = -0.75
  → 或者：Oracle太强，本地分被拉高：-2.0 + 1.25 = -0.75
  → 结果：分数不足，不交易 ✓ 更安全
```

---

## ✅ 推荐配置

**去掉核弹VIP通道**，使用当前融合权重：

```python
# 同向共振
oracle_boost = oracle_score / 5.0

# 反向背离
oracle_boost = oracle_score / 10.0

# 置信度计算
confidence = min(abs(score) / 5.0, 0.99)
```

**优势**：
- ✅ 简单清晰
- ✅ 已验证可行
- ✅ Oracle不主导
- ✅ 防御层始终生效
- ✅ 避免极端情况

---

*最后更新: 2026-03-01*
