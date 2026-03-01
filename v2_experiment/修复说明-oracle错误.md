# 修复说明 - oracle 变量未定义错误

## 🐛 问题描述

**错误信息**：`[WSS] 错误: name 'oracle' is not defined`

**触发场景**：
- 市场混乱（价格穿越基准线 ≥ 5 次）
- 防御层需要检查 CVD 强度时

## 🔍 问题原因

在 `calculate_defense_multiplier` 方法中：
- 第 1763 行使用了 `oracle.get('cvd_5m', 0.0)`
- 但 `oracle` 变量没有作为参数传入方法
- 导致运行时报错：`name 'oracle' is not defined`

## ✅ 修复方案

### 1. 修改方法签名（第 1688 行）

```python
# 修改前
def calculate_defense_multiplier(self, current_price: float, oracle_score: float, score: float) -> float:

# 修改后
def calculate_defense_multiplier(self, current_price: float, oracle_score: float, score: float, oracle: Dict = None) -> float:
```

### 2. 修改方法调用（第 1970 行）

```python
# 修改前
defense_multiplier = self.calculate_defense_multiplier(price, oracle_score, score)

# 修改后
defense_multiplier = self.calculate_defense_multiplier(price, oracle_score, score, oracle)
```

## 📝 代码逻辑

修复后，当市场混乱时：
```python
if self.session_cross_count >= 5:
    if is_nuke:
        # 核弹级信号，无视混乱
        pass
    else:
        # 检查 CVD 强度（现在 oracle 参数已正确传入）
        cvd_5m = oracle.get('cvd_5m', 0.0) if oracle else 0.0
        
        if abs(cvd_5m) >= 150000:
            # CVD 强烈信号，允许开仓
            pass
        else:
            # CVD 弱，拒绝开仓
            return 0.0
```

## 🎯 影响范围

- **修复文件**：`auto_trader_ankr.py`
- **影响功能**：防御层 CVD 否决权检查
- **向后兼容**：是（oracle 参数默认为 None）

## ✅ 测试建议

1. 运行系统，等待市场混乱场景（穿越基准线 ≥ 5 次）
2. 观察是否还会报 `oracle` 未定义错误
3. 检查 CVD 否决权逻辑是否正常工作

---

**修复日期**：2026-03-01 23:19  
**修复人**：Claude (OpenClaw)
