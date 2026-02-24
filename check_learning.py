#!/usr/bin/env python3
import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect('btc_15min_auto_trades.db')
cursor = conn.cursor()

one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')

cursor.execute("""
    SELECT COUNT(*) as total,
           SUM(CASE WHEN was_validated = 1 THEN 1 ELSE 0 END) as validated
    FROM predictions
    WHERE timestamp >= ?
""", (one_hour_ago,))

row = cursor.fetchone()
total, validated = row[0] if row else (0, 0), row[1] if row else (0, 0)

print(f"最近1小时预测统计：")
print(f"  总预测数: {total}")
print(f"  已验证: {validated}")
print(f"  待验证: {total - validated}")

conn.close()
