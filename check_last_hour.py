#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查最近1小时的交易"""
import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect('btc_15min_auto_trades.db')
cursor = conn.cursor()

print("=" * 70)
print("最近1小时交易记录")
print("=" * 70)

one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')

# 查询所有持仓
cursor.execute("""
    SELECT id, entry_time, side, size, token_id, status, entry_token_price
    FROM positions
    WHERE entry_time >= ?
    ORDER BY entry_time DESC
""", (one_hour_ago,))

positions = cursor.fetchall()

if not positions:
    print("最近1小时没有交易记录")
else:
    print(f"\n共 {len(positions)} 笔交易：\n")
    for pos in positions:
        pos_id, entry_time, side, size, token_id, status, price = pos
        print(f"#{pos_id} | {entry_time} | {side} | {size}份 @ {price:.4f} | {status}")
        print(f"     Token: {token_id}")

    # 按token_id分组
    print("\n" + "=" * 70)
    print("按token_id + side分组统计：")
    print("=" * 70)

    cursor.execute("""
        SELECT token_id, side, COUNT(*) as count,
               GROUP_CONCAT(id) as ids,
               MIN(entry_time) as first_time
        FROM positions
        WHERE entry_time >= ?
        GROUP BY token_id, side
        ORDER BY first_time DESC
    """, (one_hour_ago,))

    groups = cursor.fetchall()
    for token_id, side, count, ids, first_time in groups:
        print(f"\nToken: {token_id[-8:]} | {side}")
        print(f"  开仓次数: {count}")
        print(f"  持仓ID: {ids}")
        print(f"  首次开仓: {first_time}")
        if count > 2:
            print(f"  ⚠️  超过弹匣限制！")

conn.close()
