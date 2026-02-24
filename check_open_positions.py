#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('btc_15min_auto_trades.db')
cursor = conn.cursor()

# 先查看表结构
cursor.execute("PRAGMA table_info(positions)")
columns = cursor.fetchall()
print("positions 表结构:")
for col in columns:
    print(f"  {col[1]} ({col[2]})")
print()

# 查询所有 OPEN 持仓
cursor.execute("""
    SELECT * FROM positions WHERE status = 'open' ORDER BY entry_time DESC
""")
positions = cursor.fetchall()

if positions:
    print(f"共 {len(positions)} 个 OPEN 持仓:\n")
    for pos in positions:
        print(pos)
else:
    print("✅ 没有 OPEN 持仓")

conn.close()
