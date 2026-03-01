# 老版本融合度计算详解

## 📜 老版本文件信息

**文件**: `auto_trader_ankr(1).py`
**日期**: 2026年2月
**位置**: D:\xwechat_files\martin6016_fa48\msg\file\2026-02\

---

## 🎯 融合算法（老版本）

### 步骤1: Oracle融合

```python
if oracle:
    oracle_score = oracle.get('signal_score', 0.0)

    # 同向增强（权重20%），反向削弱（权重10%）
    if oracle_score * score > 0:
        oracle_boost = oracle_score / 5.0   # 同向：最多±2
    else:
        oracle_boost = oracle_score / 10.0  # 反向：最多±1

    score += oracle_boost
    score = max(-10, min(10, score))
```

**与当前版本一致**：✅ 完全相同

---

### 步骤2: 极端Oracle信号处理（老版本特有）

```python
# 极端Oracle信号（>8或<-8）需本地评分同向才触发
if oracle and abs(oracle_score) >= 8.0:
    if oracle_score >= 8.0 and score > 0 and price <= 0.95:
        direction = 'LONG'
        print(f"[ORACLE] 🚀 极端看涨信号({oracle_score:+.2f})，本地同向({score:.2f})，触发LONG！")
    elif oracle_score <= -8.0 and score < 0 and price >= 0.05:
        direction = 'SHORT'
        print(f"[ORACLE] 🔻 极端看跌信号({oracle_score:+.2f})，本地同向({score:.2f})，触发SHORT！")
    else:
        print(f"[ORACLE] ⚠️ 极端Oracle信号({oracle_score:+.2f})但本地评分反向({score:.2f})，忽略")
else:
    # 常规信号流程
    if score >= min_long_score and confidence >= min_long_conf:
        direction = 'LONG'
    elif score <= min_short_score and confidence >= min_short_conf:
        direction = 'SHORT'
```

**关键点**：
- ✅ 阈值：8.0（比当前版本的12.0低）
- ✅ 需要本地同向（不是VIP通道）
- ✅ 有价格限制（LONG ≤ 0.95, SHORT ≥ 0.05）
- ❌ 不满足条件时忽略（不会强制交易）

---

## 📊 完整决策流程（老版本）

### 场景1: 常规信号（Oracle < 8.0）

```
1. 本地评分
   score = 3.7

2. Oracle融合（同向）
   oracle_score = 5.0
   oracle_boost = 5.0 / 5.0 = 1.0
   fused_score = 3.7 + 1.0 = 4.7

3. 计算置信度
   confidence = 4.7 / 5.0 = 94%

4. 判断方向
   if fused_score >= 4.0 and confidence >= 60%:
       direction = 'LONG'
```

---

### 场景2: 极端信号（Oracle ≥ 8.0）

#### 情况A: 满足所有条件

```
1. 本地评分
   score = 2.5

2. Oracle融合（同向）
   oracle_score = 8.5
   oracle_boost = 8.5 / 5.0 = 1.7
   fused_score = 2.5 + 1.7 = 4.2

3. 检查极端信号条件
   oracle_score (8.5) >= 8.0  ✓
   score (4.2) > 0  ✓
   price (0.35) <= 0.95  ✓

4. 直接触发（跳过常规阈值检查）
   direction = 'LONG'
   日志: "🚀 极端看涨信号(+8.50)，本地同向(4.20)，触发LONG！"
```

#### 情况B: 不满足条件

```
1. 本地评分
   score = -1.5

2. Oracle融合（反向）
   oracle_score = 8.5
   oracle_boost = 8.5 / 10.0 = 0.85
   fused_score = -1.5 + 0.85 = -0.65

3. 检查极端信号条件
   oracle_score (8.5) >= 8.0  ✓
   score (-0.65) > 0  ✗ (不满足)

4. 忽略极端信号
   日志: "⚠️ 极端Oracle信号(+8.50)但本地评分反向(-0.65)，忽略"

5. 进入常规流程
   if -0.65 >= 4.0:  ✗ 不满足做多阈值
   if -0.65 <= -3.0:  ✗ 不满足做空阈值
   结果：不交易
```

---

## 🔍 老版本 vs 当前版本

### 融合算法对比

| 项目 | 老版本 | 当前版本 | 差异 |
|------|--------|----------|------|
| **同向融合** | ÷5 | ÷5 | ✓ 相同 |
| **反向融合** | ÷10 | ÷10 | ✓ 相同 |
| **极端阈值** | 8.0 | ~~12.0~~（已删除） | 不同 |
| **极端信号处理** | 需本地同向 | ~~VIP通道~~（已删除） | 不同 |
| **价格限制** | ≤0.95 / ≥0.05 | ~~≤0.20 / ≥0.80~~（已删除） | 不同 |

---

### 特殊机制对比

#### 老版本的"极端信号"机制

```python
# 阈值：8.0
# 条件：Oracle ≥ 8.0 + 本地同向 + 价格限制
# 处理：触发交易或忽略
# 特点：不是VIP通道，仍需满足基本条件
```

**示例**：
```
Oracle: +8.5
本地: +4.2
价格: $0.35
→ 触发LONG（满足所有条件）
```

```
Oracle: +8.5
本地: -0.65
价格: $0.35
→ 忽略（本地反向）
```

---

#### 当前版本的"核弹VIP"机制（已删除）

```python
# 阈值：12.0
# 条件：Oracle ≥ 12.0 + 价格限制 + RSI限制
# 处理：VIP通道，无视常规规则
# 特点：完全独立通道，防御层全通过
```

**示例**：
```
Oracle: +12.5
价格: $0.15
RSI: 22
→ VIP通道，强制做多，防御层全通过
```

---

#### 现在的版本（已删除特殊机制）

```python
# 阈值：无
# 条件：无
# 处理：所有信号走正常融合流程
# 特点：简单、一致、安全
```

---

## 💡 为什么删除了特殊机制？

### 老版本"极端信号"机制的问题

1. **阈值太低**（8.0）
   - 容易触发，但并非真正的"极端"
   - Oracle±8.0在双CVD窗口下并不罕见

2. **条件复杂**
   - 需要同时满足3个条件（阈值+本地同向+价格限制）
   - 增加代码复杂度

3. **效果有限**
   - 只在边缘情况下起作用
   - 大部分时间走常规流程

4. **容易混淆**
   - 与常规融合逻辑混在一起
   - 难以理解和调试

---

### 当前版本的优势

```python
# 简单清晰的单一流程
1. Oracle融合（÷5 / ÷10）
2. Memory调整（optional）
3. 置信度计算
4. 阈值判断
5. 防御层评估

# 没有特殊情况
# 没有VIP通道
# 所有信号一视同仁
```

**优势**：
- ✅ 简单易理解
- ✅ 逻辑一致
- ✅ 易于调试
- ✅ 安全可靠
- ✅ 防御层始终生效

---

## 📈 实际案例对比

### 案例: Oracle +9.0

#### 老版本处理

```
本地分: +3.0
Oracle: +9.0
价格: $0.40

步骤1: Oracle融合
  oracle_boost = 9.0 / 5.0 = 1.8
  fused_score = 3.0 + 1.8 = 4.8

步骤2: 检查极端信号
  oracle_score (9.0) >= 8.0  ✓
  fused_score (4.8) > 0  ✓
  price (0.40) <= 0.95  ✓

步骤3: 触发交易
  direction = 'LONG'
  日志: "🚀 极端看涨信号(+9.00)，本地同向(4.80)，触发LONG！"
```

#### 当前版本处理（已删除特殊机制）

```
本地分: +3.0
Oracle: +9.0
价格: $0.40

步骤1: Oracle融合
  oracle_boost = 9.0 / 5.0 = 1.8
  fused_score = 3.0 + 1.8 = 4.8

步骤2: Memory调整
  prior_bias = 0.3
  prior_adjustment = 0.6
  final_score = 4.8 + 0.6 = 5.4

步骤3: 计算置信度
  confidence = 5.4 / 5.0 = 99%

步骤4: 判断方向
  if 5.4 >= 4.0:
      direction = 'LONG'

步骤5: 防御层评估
  防御乘数: 0.8

步骤6: 最终仓位
  基础仓位: $3.00
  置信度: 99%
  防御: 0.8
  最终: $3.00 × 0.99 × 0.8 = $2.38
```

---

## ✅ 总结

### 老版本的融合度计算

```python
# 核心公式（与当前相同）
oracle_boost = oracle_score / 5.0 if 同向 else oracle_score / 10.0
fused_score = local_score + oracle_boost

# 置信度计算
confidence = min(abs(fused_score) / 5.0, 0.99)
```

### 特殊机制（已删除）

```python
# 老版本的"极端信号"处理
if abs(oracle_score) >= 8.0:
    if 本地同向 and 价格限制:
        触发交易  # 不是VIP通道，只是优先处理
    else:
        忽略并走常规流程
```

### 与当前版本的区别

| 项目 | 老版本 | 当前版本 |
|------|--------|----------|
| **融合算法** | ÷5 / ÷10 | ÷5 / ÷10 ✓ |
| **极端阈值** | 8.0 | 无 |
| **VIP通道** | 无 | 无（已删除） |
| **特殊处理** | 极端信号优先 | 无 |
| **防御层** | 始终生效 | 始终生效 ✓ |

---

*最后更新: 2026-03-01*
