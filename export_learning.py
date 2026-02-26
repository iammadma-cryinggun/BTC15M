#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导出学习系统数据到日志
将所有历史预测数据输出到日志，方便查看
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from prediction_learning_polymarket import PolymarketPredictionLearning
    import sqlite3
    from datetime import datetime

    print("=" * 80)
    print("📊 学习系统数据导出工具")
    print("=" * 80)
    print()

    # 连接数据库
    db_path = 'btc_15min_predictionsv2.db'

    if not os.path.exists(db_path):
        print(f"❌ 数据库文件不存在: {db_path}")
        print(f"   当前目录: {os.getcwd()}")
        print(f"   文件列表: {os.listdir('.')}")
        sys.exit(1)

    file_size = os.path.getsize(db_path)
    print(f"📁 数据库: {db_path} ({file_size} bytes)")
    print()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 检查表是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='predictions'")
    if not cursor.fetchone():
        print("❌ predictions表不存在，数据库可能是空的")
        sys.exit(1)

    # 统计数据
    cursor.execute('SELECT COUNT(*) FROM predictions')
    total = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM predictions WHERE verified = 1')
    verified = cursor.fetchone()[0]

    print(f"📊 数据概览:")
    print(f"   总预测数: {total}")
    print(f"   已验证: {verified}")
    print(f"   未验证: {total - verified}")
    print()

    if total == 0:
        print("⚠️  数据库为空，还没有预测记录")
        sys.exit(0)

    # 按时间排序的所有数据
    print("=" * 80)
    print("📋 所有预测记录（按时间顺序）")
    print("=" * 80)
    print()

    cursor.execute('''
        SELECT
            id,
            timestamp,
            direction,
            score,
            confidence,
            recommendation,
            verified,
            correct,
            actual_price,
            market_slug
        FROM predictions
        ORDER BY id ASC
    ''')

    rows = cursor.fetchall()

    for row in rows:
        (pid, timestamp, direction, score, confidence, rec,
         verified, correct, actual_price, market) = row

        status = "✓ 已验证" if verified else "○ 待验证"
        result = "✓ 正确" if correct == 1 else "✗ 错误" if verified else "- 未知"

        print(f"[{pid:4d}] {timestamp} | {direction:4s} | 分{score:5.1f} | {status} | {result}")
        if rec:
            print(f"       └─ {rec}")
        if verified and actual_price:
            print(f"       └─ 实际价格: {actual_price:.4f}")

    print()
    print("=" * 80)
    print("📈 准确率统计")
    print("=" * 80)
    print()

    if verified > 0:
        cursor.execute('''
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END) as correct
            FROM predictions
            WHERE verified = 1
        ''')
        row = cursor.fetchone()
        accuracy = row[1] / row[0] * 100
        print(f"总体准确率: {accuracy:.1f}% ({row[1]}/{row[0]})")
        print()

        # 按分数分组
        print("按信号分数分组:")
        cursor.execute('''
            SELECT
                CAST(score AS INTEGER) as score_range,
                COUNT(*) as total,
                SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END) as correct
            FROM predictions
            WHERE verified = 1
            GROUP BY score_range
            ORDER BY score_range DESC
        ''')

        for row in cursor.fetchall():
            score, total, correct = row
            acc = correct / total * 100
            bar = "█" * int(acc / 10)
            print(f"  分数约{int(score):2d}: {acc:5.1f}% {bar} ({correct}/{total})")

    conn.close()
    print()
    print("=" * 80)
    print("✅ 导出完成")
    print("=" * 80)

except Exception as e:
    print(f"❌ 错误: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
