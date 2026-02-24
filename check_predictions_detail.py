#!/usr/bin/env python3
import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect('btc_15min_predictionsv2.db')
cursor = conn.cursor()

print("=" * 70)
print("预测记录详情")
print("=" * 70)

# 查询所有预测
cursor.execute("SELECT COUNT(*) FROM predictions")
total = cursor.fetchone()[0]

# 查询已验证和未验证的
cursor.execute("SELECT COUNT(*) FROM predictions WHERE verified = 1")
verified = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM predictions WHERE verified = 0")
unverified = cursor.fetchone()[0]

print(f"\n总预测数: {total}")
print(f"已验证: {verified}")
print(f"待验证: {unverified}")

# 最近1小时
one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
cursor.execute("""
    SELECT COUNT(*), SUM(verified)
    FROM predictions
    WHERE timestamp >= ?
""", (one_hour_ago,))
recent_total, recent_verified = cursor.fetchone()
print(f"\n最近1小时:")
print(f"  总预测: {recent_total}")
print(f"  已验证: {recent_verified or 0}")

# 显示最近10条预测
print("\n最近10条预测:")
cursor.execute("""
    SELECT timestamp, direction, score, verified, correct, market_slug
    FROM predictions
    ORDER BY timestamp DESC
    LIMIT 10
""")
recent_preds = cursor.fetchall()

for pred in recent_preds:
    ts, direction, score, verified, correct, slug = pred
    status = "✅" if verified else "⏳"
    result = f"({['✓' if correct else '✗'][0]})" if verified else ""
    print(f"  {ts} | {direction} | Score: {score:.1f} | {status}{result}")

# 显示待验证的预测
print("\n待验证的预测（最早的10条）:")
cursor.execute("""
    SELECT timestamp, direction, score, market_slug
    FROM predictions
    WHERE verified = 0
    ORDER BY timestamp ASC
    LIMIT 10
""")
pending = cursor.fetchall()

if pending:
    for pred in pending:
        ts, direction, score, slug = pred
        print(f"  {ts} | {direction} | Score: {score:.1f} | {slug[-20:]}")
else:
    print("  (没有待验证的预测)")

conn.close()
print("=" * 70)
