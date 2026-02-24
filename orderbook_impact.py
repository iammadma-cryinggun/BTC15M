#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对比订单簿加入前后的准确率
订单簿加入时间：2026-02-21 02:00 CST
"""

import sqlite3
from datetime import datetime

DB_PATH = 'btc_15min_predictionsv2.db'
ORDERBOOK_ADDED = '2026-02-21 02:00:00'

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

def stats(label, where_clause, params):
    cursor.execute(f'''
        SELECT
            COUNT(*) as total,
            SUM(correct) as correct,
            SUM(CASE WHEN direction='LONG' THEN 1 ELSE 0 END) as long_total,
            SUM(CASE WHEN direction='LONG' AND correct=1 THEN 1 ELSE 0 END) as long_correct,
            SUM(CASE WHEN direction='SHORT' THEN 1 ELSE 0 END) as short_total,
            SUM(CASE WHEN direction='SHORT' AND correct=1 THEN 1 ELSE 0 END) as short_correct,
            AVG(score) as avg_score,
            AVG(confidence) as avg_conf
        FROM predictions
        WHERE verified=1 AND {where_clause}
    ''', params)
    row = cursor.fetchone()
    total, correct, lt, lc, st, sc, avg_score, avg_conf = row
    if not total or total == 0:
        print(f"\n{label}: 无数据")
        return
    print(f"\n{label} (共{total}条)")
    print(f"  总体准确率: {correct}/{total} = {correct/total*100:.1f}%")
    if lt: print(f"  做多: {lc}/{lt} = {lc/lt*100:.1f}%")
    if st: print(f"  做空: {sc}/{st} = {sc/st*100:.1f}%")
    print(f"  平均评分: {avg_score:.2f} | 平均置信度: {avg_conf*100:.1f}%")

print("=" * 60)
print(f"订单簿加入时间: {ORDERBOOK_ADDED}")
print("=" * 60)

stats("订单簿加入前", "timestamp < ?", (ORDERBOOK_ADDED,))
stats("订单簿加入后", "timestamp >= ?", (ORDERBOOK_ADDED,))

conn.close()
