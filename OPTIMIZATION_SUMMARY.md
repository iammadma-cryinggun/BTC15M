# 防守三板斧优化总结

## 修改日期
2026-02-24

---

## 一、CONFIG参数更新

### 1. risk 配置（第61-73行）
```python
'risk': {
    'max_position_pct': 0.15,
    'max_total_exposure_pct': 0.60,
    'reserve_usdc': 2.0,
    'min_position_usdc': 2.0,
    'max_daily_trades': 96,
    'max_daily_loss_pct': 0.50,
    'stop_loss_consecutive': 4,
    'pause_hours': 0.5,
    'max_same_direction_bullets': 2,
    'same_direction_cooldown_sec': 60,
    'max_stop_loss_pct': 0.28,      # 🛡️ 新增：最大止损28%
},
```

### 2. signal 配置（第75-93行）
```python
'signal': {
    'min_confidence': 0.75,
    'min_long_confidence': 0.50,
    'min_short_confidence': 0.50,
    'min_long_score': 2.5,
    'min_short_score': -2.5,
    'balance_zone_min': 0.48,
    'balance_zone_max': 0.52,
    'allow_long': True,
    'allow_short': True,

    # 🛡️ 新增：价格限制（允许追强势单，但拒绝极高位接盘）
    'max_entry_price': 0.80,  # 最高入场价：0.80（允许追涨，但28%止损保护）
    'min_entry_price': 0.20,  # 最低入场价：0.20（允许抄底，但28%止损保护）

    'dynamic_lookback': 100,
    'direction_threshold': 0.45,
},
```

---

## 二、第二斧：价格限制（已调整：0.20-0.80）（第1167-1175行）

```python
# 🛡️ === 第二斧：价格限制（允许追强势单） ===
price = signal.get('price', 0.5)
max_entry_price = CONFIG['signal'].get('max_entry_price', 0.80)
min_entry_price = CONFIG['signal'].get('min_entry_price', 0.20)

if price > max_entry_price:
    return False, f"🛡️ 拒绝极高位接盘: {price:.4f} > {max_entry_price:.2f} (风险太大)"
if price < min_entry_price:
    return False, f"🛡️ 拒绝极端低位: {price:.4f} < {min_entry_price:.2f} (风险太大)"
```

**作用**：
- 允许在0.20-0.80区间开仓（原来是0.35-0.65）
- 可以追强势单（如0.75），但28%止损会保护
- 只拒绝极端价格（>0.80或<0.20）

**修改原因**：
- 限制太严（0.35-0.65）会过滤掉高胜率的顺风局
- 当AI给出明确信号时，价格往往已经跑到0.70-0.75
- 有了28%止损作为安全底线，可以放宽价格限制

---

## 三、第一斧：时间防火墙（第1154-1165行）

```python
# 🛡️ === 第一斧：时间防火墙（拒绝垃圾时间） ===
if market:
    end_timestamp = market.get('endTimestamp')
    if end_timestamp:
        try:
            end_time = datetime.fromtimestamp(int(end_timestamp) / 1000, tz=timezone.utc)
            time_left = (end_time - datetime.now(timezone.utc)).total_seconds()
            # 距离结算不足180秒（3分钟），拒绝开仓
            if time_left < 180:
                return False, f"🛡️ 时间防火墙: 距离结算仅{time_left:.0f}秒，拒绝开仓"
        except:
            pass
```

**作用**：避免在15分钟合约的最后3分钟开仓，防止流动性黑洞导致的极端滑点。

---

## 四、第三斧：收紧止损线（第1427-1440行）

```python
# 🛡️ 第三斧：收紧止损线（防止断崖暴跌）
# 原止损：固定1U损失
sl_original = (value_usdc - 1.0) / max(size, 1)
# 新止损：最大28%百分比损失
sl_pct_max = CONFIG['risk'].get('max_stop_loss_pct', 0.28)  # 28%最大止损
sl_by_pct = entry_price * (1 - sl_pct_max)

# 取两者中更保守的（价格更高的，即更早止损）
sl_target_price = max(sl_original, sl_by_pct)

# 计算实际止损百分比
actual_sl_pct = (entry_price - sl_target_price) / entry_price
print(f"       [STOP ORDERS] entry={entry_price:.4f}, size={size}, value={value_usdc:.4f}")
print(f"       [STOP ORDERS] tp={tp_target_price:.4f} (固定+1U), sl={sl_target_price:.4f} (止损{actual_sl_pct:.1%})")
```

**作用**：
- 原止损：固定1U损失（小仓位时止损幅度达40-50%）
- 新止损：最大28%损失百分比
- 取两者更保守的（更早止损）

**其他位置应用**：
- 第1488-1492行：重新计算止盈止损时
- 第1531-1535行：实际成交价调整时
- 第1571-1575行：强制监控模式时

---

## 五、修复daily_loss统计（4个位置）

### 1. STALE_CLEANUP平仓（第638-640行）
```python
# 更新 daily_loss 统计
if pnl_usd < 0:
    self.stats['daily_loss'] += abs(pnl_usd)
```

### 2. STALE_CLEANUP结算（第701-703行）
```python
# 更新 daily_loss 统计
if pnl_usd < 0:
    self.stats['daily_loss'] += abs(pnl_usd)
```

### 3. 止盈止损触发（第2450-2453行）
```python
# 更新 daily_loss 统计
if pnl_usd < 0:
    self.stats['daily_loss'] += abs(pnl_usd)
    print(f"       [STATS] 累计每日亏损: ${self.stats['daily_loss']:.2f} / ${self.position_mgr.get_max_daily_loss():.2f}")
```

### 4. 信号改变平仓（第2576-2579行）
```python
# 更新 daily_loss 统计
if pnl_usd < 0:
    self.stats['daily_loss'] += abs(pnl_usd)
    print(f"       [STATS] 累计每日亏损: ${self.stats['daily_loss']:.2f} / ${self.position_mgr.get_max_daily_loss():.2f}")
```

---

## 六、启用每日亏损检查（第1192-1202行）

```python
# 每日最大亏损检查
max_loss = self.position_mgr.get_max_daily_loss()
if self.stats['daily_loss'] >= max_loss:
    # 检查是否是新的一天，如果是则重置
    if datetime.now().date() > self.last_reset_date:
        self.stats['daily_loss'] = 0.0
        self.stats['daily_trades'] = 0
        self.last_reset_date = datetime.now().date()
        print(f"       [RESET] 新的一天，每日亏损已重置")
    else:
        return False, f"Daily loss limit reached (${self.stats['daily_loss']:.2f}/${max_loss:.2f})"
```

---

## 七、修复虚假持仓bug（第1971-2000行）

```python
# 【关键修复】入场单超时未成交，撤单后放弃记录
# 判断逻辑：tp_order_id=None 且 tp_order_id不是字符串"UNCERTAIN"
if tp_order_id is None and actual_entry_price is not None and actual_entry_price > 0:
    # 这种情况说明：订单超时未成交，强制监控模式，但实际没有token
    # 需要验证是否真正有持仓
    print(f"       [POSITION] ⚠️  订单状态不明，验证持仓...")
    # 通过查询余额来确认（token_id需要从market获取）
    token_ids = market.get('clobTokenIds', [])
    if isinstance(token_ids, str):
        token_ids = json.loads(token_ids)
    token_id = str(token_ids[0] if signal['direction'] == 'LONG' else token_ids[1])

    try:
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
        params = BalanceAllowanceParams(
            asset_type=AssetType.CONDITIONAL,
            token_id=token_id,
            signature_type=2
        )
        result = self.client.get_balance_allowance(params)
        if result:
            balance = float(result.get('balance', 0))
            print(f"       [POSITION] Token余额: {balance:.2f} (需要: {position_size:.0f})")
            if balance < position_size * 0.5:  # 余额不足一半，说明未成交
                print(f"       [POSITION] ❌ 确认未成交，放弃记录持仓")
                conn.commit()
                conn.close()
                return
    except Exception as verify_err:
        print(f"       [POSITION] ⚠️  无法验证余额，假设未成交: {verify_err}")
        conn.commit()
        conn.close()
        return
```

**作用**：在记录持仓前验证token余额，防止记录虚假持仓。

---

## 八、数据清理

清理了虚假持仓记录（ID 82）：
```sql
UPDATE positions
SET status='closed', exit_reason='FAKE_POSITION_CANCEL',
    exit_time=?, pnl_usd=0, pnl_pct=0
WHERE id=82
```

---

## 修改总结

### 防守三板斧
1. **时间防火墙**：距离结算不足3分钟拒绝开仓
2. **价格限制**：允许在0.20-0.80区间开仓（可以追强势单，但28%止损保护）
3. **收紧止损线**：最大止损从40-50%收紧到28%

### Bug修复
1. **daily_loss统计**：在4个位置添加亏损累加逻辑
2. **虚假持仓**：通过验证token余额防止记录虚假持仓
3. **每日亏损检查**：启用每日最大亏损限制

### 预期效果
- 减少"垃圾时间"开仓的损失
- 拒绝高位接盘的微利高风险
- 快速斩断断崖暴跌的损失
- 正确追踪每日亏损，达到限制后自动暂停

---

## 当前系统状态

- **胜率**：63.8% (37胜/21负)
- **总盈亏**：+$10.12
- **盈亏比**：1.29
- **总交易**：82笔

通过这些防守优化，系统将在保持进攻性的同时，大幅减少极端行情下的利润失血！
