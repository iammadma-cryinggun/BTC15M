#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查程序运行状态和弹匣限制触发情况"""
import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect('btc_15min_auto_trades.db')
cursor = conn.cursor()

print("=" * 70)
print("检查最近10分钟的交易信号和执行情况")
print("=" * 70)

# 1. 查询最近的信号记录
print("\n[1] 最近的信号记录（trades表）：\n")
ten_min_ago = (datetime.now() - timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')

cursor.execute("""
    SELECT timestamp, side, price, status, signal_score
    FROM trades
    WHERE timestamp >= ?
    ORDER BY timestamp DESC
    LIMIT 20
""", (ten_min_ago,))

trades = cursor.fetchall()
if not trades:
    print("  最近10分钟没有信号记录")
else:
    for trade in trades:
        timestamp, side, price, status, score = trade
        print(f"  {timestamp} | {side} | Score: {score} | Status: {status}")

# 2. 查询最近的持仓记录
print("\n[2] 最近的持仓记录（positions表）：\n")

cursor.execute("""
    SELECT id, entry_time, side, size, token_id, status
    FROM positions
    WHERE entry_time >= ?
    ORDER BY entry_time DESC
    LIMIT 20
""", (ten_min_ago,))

positions = cursor.fetchall()
if not positions:
    print("  最近10分钟没有持仓记录")
else:
    for pos in positions:
        pos_id, entry_time, side, size, token_id, status = pos
        print(f"  #{pos_id} | {entry_time} | {side} | {size}份 | Token: {token_id[-8:]} | {status}")

# 3. 按token_id分组统计
print("\n[3] 按token_id + side统计（验证弹匣限制）：\n")

cursor.execute("""
    SELECT token_id, side, COUNT(*) as count,
           GROUP_CONCAT(id) as ids,
           MIN(entry_time) as first_time,
           MAX(entry_time) as last_time
    FROM positions
    WHERE entry_time >= ?
    GROUP BY token_id, side
    HAVING COUNT(*) > 1
    ORDER BY last_time DESC
""", (ten_min_ago,))

groups = cursor.fetchall()
if not groups:
    print("  最近10分钟没有重复的token_id + side组合")
else:
    for group in groups:
        token_id, side, count, ids, first_time, last_time = group
        print(f"  Token: {token_id[-8:]} | {side}")
        print(f"    总次数: {count} | IDs: {ids}")
        print(f"    首次: {first_time} | 末次: {last_time}")
        if count > 2:
            print(f"    ⚠️  超过弹匣限制（2单）！")
        print()

conn.close()
print("=" * 70)
