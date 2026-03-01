# 修改说明

## 修改日期
2026-03-01

## 修改内容

### 1. voting_system.py - 补充 7 个占位规则

#### 已实现的规则：

1. **BidWallsRule** - 买墙检测
   - 检测前5档买单中是否有单档占比超过30%
   - 买墙存在 → 强支撑 → 做多

2. **AskWallsRule** - 卖墙检测
   - 检测前5档卖单中是否有单档占比超过30%
   - 卖墙存在 → 强阻力 → 做空

3. **OBIRule** - 订单簿失衡
   - 计算 OBI = (买量 - 卖量) / (买量 + 卖量)
   - OBI > 0.3 → 买盘强势 → 做多
   - OBI < -0.3 → 卖盘强势 → 做空

4. **NaturalPriceRule** - 自然价格
   - 排除前2档大单，计算加权平均价格
   - 当前价格偏离自然价格 ±1% → 可能是大单操纵
   - 价格被拉高 → 做空，价格被压低 → 做多

5. **NaturalAbsRule** - 自然价格绝对值
   - 基于自然价格本身判断市场情绪
   - 自然价格 > 0.60 → 市场看涨 → 做多
   - 自然价格 < 0.40 → 市场看跌 → 做空

6. **BufferTicketsRule** - 缓冲订单数量
   - 统计当前价格 ±2% 范围内的订单
   - 买单多 → 支撑强 → 做多
   - 卖单多 → 阻力强 → 做空

7. **PMSentimentRule** - Polymarket 情绪分析
   - 基于价格变化速度和一致性判断市场情绪
   - 快速上涨 + 低波动 → 乐观情绪 → 做多
   - 快速下跌 + 低波动 → 悲观情绪 → 做空

### 2. auto_trader_ankr.py - 补充缺失的 Polymarket API 方法

#### 新增方法：

1. **get_order_book(token_id, side)** 
   - 获取订单簿价格（买一/卖一价）
   - 调用 Polymarket CLOB API 的 `/price` 端点

2. **get_positions()**
   - 从数据库查询当前持仓统计
   - 返回 `{'LONG': 总多头, 'SHORT': 总空头}`

3. **get_real_positions()**
   - 从链上查询实时持仓
   - 通过 `get_balance_allowance` API 查询 YES/NO token 余额

4. **cancel_order(order_id)**
   - 取消指定订单
   - 使用 CLOB client 的 `cancel()` 方法

5. **cancel_pair_orders(tp_order_id, sl_order_id, reason)**
   - 批量取消止盈止损订单对
   - 自动判断止损单是订单ID还是价格字符串

6. **update_allowance_fixed(asset_type, token_id)**
   - 更新授权（USDC 或 Token）
   - 支持 COLLATERAL 和 CONDITIONAL 两种类型

## 投票系统状态

- **总规则数**: 25 个
- **已激活**: 25 个（100%）
- **占位规则**: 0 个

## 需要的数据

这些规则需要从 Polymarket API 获取订单簿数据：

```python
orderbook = {
    'bids': [(price1, size1), (price2, size2), ...],  # 买单：价格从高到低
    'asks': [(price1, size1), (price2, size2), ...]   # 卖单：价格从低到高
}
```

可以通过 Polymarket CLOB API 的 `/book` 端点获取。

## 使用方法

在 `generate_signal()` 中传入 `orderbook` 参数：

```python
signal = self.generate_signal(
    market=market, 
    price=price,
    orderbook=orderbook  # 新增参数
)
```

## 测试建议

1. 先测试不需要订单簿的规则（18个已有规则）
2. 实现订单簿数据获取后，测试新增的7个规则
3. 观察投票系统的决策质量是否提升
