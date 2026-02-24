#!/usr/bin/env python3
import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect('btc_15min_predictionsv2.db')
cursor = conn.cursor()

print("=" * 70)
print("检查预测记录数据库")
print("=" * 70)

# 查看表结构
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print(f"\n数据库表: {[t[0] for t in tables]}")

# 查询所有预测
cursor.execute("SELECT COUNT(*) FROM predictions")
total = cursor.fetchone()[0]
print(f"\n总预测数: {total}")

# 查询最近1小时的预测
one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
cursor.execute("""
    SELECT COUNT(*)
    FROM predictions
    WHERE timestamp >= ?
""", (one_hour_ago,))
recent = cursor.fetchone()[0]
print(f"最近1小时预测: {recent}")

# 查询待验证的预测
cursor.execute("""
    SELECT COUNT(*)
    FROM predictions
    WHERE was_validated = 0
""")
pending = cursor.fetchone()[0]
print(f"待验证预测: {pending}")

# 查询最近的几条预测
print("\n最近10条预测记录:")
cursor.execute("""
    SELECT timestamp, direction, predicted_price, actual_price, was_validated, market_slug
    FROM predictions
    ORDER BY timestamp DESC
    LIMIT 10
""")
recent_preds = cursor.fetchall()

for pred in recent_preds:
    ts, direction, pred_price, act_price, validated, slug = pred
    status = "✅已验证" if validated else "⏳待验证"
    print(f"  {ts} | {direction} | {pred_price:.4f} | {status}")

conn.close()
print("=" * 70)
