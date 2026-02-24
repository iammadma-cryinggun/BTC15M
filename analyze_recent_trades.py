#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析最近的交易记录，验证止盈止损逻辑
"""
import sqlite3
import pandas as pd

conn = sqlite3.connect('btc_15min_auto_trades.db')

# 查询最近20笔已关闭的交易
df = pd.read_sql_query('''
    SELECT
        entry_time,
        side,
        entry_token_price,
        size,
        value_usdc,
        exit_token_price,
        pnl_usd,
        pnl_pct,
        exit_reason,
        take_profit_usd,
        stop_loss_usd
    FROM positions
    WHERE status = 'closed'
    ORDER BY entry_time DESC
    LIMIT 20
''', conn)

conn.close()

print("=" * 100)
print("最近20笔交易分析")
print("=" * 100)

for idx, row in df.iterrows():
    print(f"\n#{idx+1}")
    print(f"时间: {row['entry_time']}")
    print(f"方向: {row['side']}")
    print(f"入场: {row['size']:.0f} @ ${row['entry_token_price']:.4f} = ${row['value_usdc']:.2f}")
    print(f"出场: ${row['exit_token_price']:.4f}")
    print(f"盈亏: ${row['pnl_usd']:+.2f} ({row['pnl_pct']:+.1f}%)")
    print(f"原因: {row['exit_reason']}")

    # 验证是否符合±1 USDC
    expected_pnl_usd = 1.0 if row['pnl_usd'] > 0 else -1.0
    actual_pnl_diff = abs(row['pnl_usd'] - expected_pnl_usd)

    if actual_pnl_diff > 0.1:  # 超过10美分就算异常
        print(f"⚠️  盈亏不是±1 USDC: ${row['pnl_usd']:+.2f} (期望: ${expected_pnl_usd:+.2f})")
    else:
        print(f"✅ 符合±1 USDC 设计")

print("\n" + "=" * 100)
print("统计摘要")
print("=" * 100)

# 统计
total_trades = len(df)
avg_pnl = df['pnl_usd'].mean()
total_pnl = df['pnl_usd'].sum()
win_rate = (df['pnl_usd'] > 0).sum() / total_trades * 100

print(f"总交易: {total_trades}笔")
print(f"平均盈亏: ${avg_pnl:+.2f}")
print(f"总盈亏: ${total_pnl:+.2f}")
print(f"胜率: {win_rate:.1f}%")

# 按退出原因分组
print("\n按退出原因统计:")
grouped = df.groupby('exit_reason').agg({
    'pnl_usd': ['count', 'mean', 'sum']
})
print(grouped)

print("\n" + "=" * 100 + "\n")
