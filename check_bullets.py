#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查弹匣限制是否生效"""
import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect('btc_15min_auto_trades.db')
cursor = conn.cursor()

print("=" * 70)
print("检查最近的交易记录（按token_id + side分组）")
print("=" * 70)

# 查询最近1小时的记录
one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')

cursor.execute("""
    SELECT token_id, side,
           COUNT(*) as total_count,
           GROUP_CONCAT(id) as position_ids,
           MIN(entry_time) as first_entry,
           MAX(entry_time) as last_entry
    FROM positions
    WHERE entry_time >= ?
    GROUP BY token_id, side
    ORDER BY last_entry DESC
    LIMIT 20
""", (one_hour_ago,))

results = cursor.fetchall()

if not results:
    print("最近1小时没有交易记录")
else:
    print(f"\n最近1小时的交易统计（按 token_id + side 分组）：\n")
    for row in results:
        token_id, side, count, ids, first_entry, last_entry = row
        print(f"Token: {token_id[-8:]} | Side: {side}")
        print(f"  总开仓次数: {count}")
        print(f"  持仓ID: {ids}")
        print(f"  首次: {first_entry}")
        print(f"  末次: {last_entry}")

        if count > 2:
            print(f"  ⚠️  超过弹匣限制（2单）！")
        print()

conn.close()
print("=" * 70)
