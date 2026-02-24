#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重置学习系统统计数据"""

import os
import sqlite3
from datetime import datetime, timedelta

print("=" * 60)
print("学习系统数据重置工具")
print("=" * 60)

# 数据库文件路径
predictions_db = 'btc_15min_predictionsv2.db'
trades_db = 'btc_15min_auto_trades.db'

print("\n=== 当前数据统计 ===\n")

# 1. 检查预测数据库
if os.path.exists(predictions_db):
    conn = sqlite3.connect(predictions_db)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM predictions")
    total_predictions = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM predictions WHERE timestamp > datetime('now', '-24 hours')")
    recent_24h = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM predictions WHERE timestamp > datetime('now', '-1 day')")
    recent_1day = cursor.fetchone()[0]

    print(f"📊 预测数据库 ({predictions_db}):")
    print(f"  总预测记录: {total_predictions} 条")
    print(f"  最近24小时: {recent_24h} 条")
    print(f"  最近1天: {recent_1day} 条")

    # 显示最近5条预测
    cursor.execute("SELECT timestamp, price, score, is_correct FROM predictions ORDER BY id DESC LIMIT 5")
    recent = cursor.fetchall()
    if recent:
        print(f"\n  最近5条预测:")
        for r in recent:
            print(f"    {r[0]} | price={r[1]} | score={r[2]:.2f} | correct={r[3]}")

    conn.close()
else:
    print(f"❌ 预测数据库不存在: {predictions_db}")
    total_predictions = 0

print()

# 2. 检查交易数据库
if os.path.exists(trades_db):
    conn = sqlite3.connect(trades_db)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM trades")
    total_trades = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM trades WHERE timestamp > datetime('now', '-24 hours')")
    trades_24h = cursor.fetchone()[0]

    print(f"💰 交易数据库 ({trades_db}):")
    print(f"  总交易记录: {total_trades} 条")
    print(f"  最近24小时: {trades_24h} 条")

    # 显示今天交易
    cursor.execute("SELECT timestamp, side, price, value_usd FROM trades WHERE timestamp > datetime('now', '-24 hours') ORDER BY id DESC")
    today_trades = cursor.fetchall()
    if today_trades:
        print(f"\n  最近24小时交易:")
        wins = sum(1 for t in today_trades if t[3] > 0)  # value_usd > 0 表示盈利
        for t in today_trades:
            result = "✅盈利" if t[3] > 0 else "❌亏损"
            print(f"    {t[0]} | {t[1]} @ {t[2]} | ${t[3]:.2f} | {result}")
        print(f"\n  今日盈亏: {wins}/{len(today_trades)} 胜")

    conn.close()
else:
    print(f"❌ 交易数据库不存在: {trades_db}")

print("\n" + "=" * 60)
print("重置选项")
print("=" * 60)
print("请选择操作:")
print("1. 删除所有预测数据（重置统计）")
print("2. 只保留最近24小时的数据")
print("3. 只保留最近1天的数据")
print("4. 只退出（不执行任何操作）")

try:
    choice = input("\n请输入选项 (1/2/3/4): ").strip()

    if choice == '1':
        print("\n[操作] 删除所有预测数据...")
        if os.path.exists(predictions_db):
            os.remove(predictions_db)
            print("[OK] 预测数据库已删除，程序运行时会自动重建")
        else:
            print("[SKIP] 预测数据库不存在")

    elif choice == '2':
        print("\n[操作] 只保留最近24小时的数据...")
        conn = sqlite3.connect(predictions_db)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM predictions WHERE timestamp <= datetime('now', '-24 hours')")
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        print(f"[OK] 已删除 {deleted} 条旧记录")

    elif choice == '3':
        print("\n[操作] 只保留最近1天的数据...")
        conn = sqlite3.connect(predictions_db)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM predictions WHERE timestamp <= datetime('now', '-1 day')")
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        print(f"[OK] 已删除 {deleted} 条旧记录")

    else:
        print("\n[SKIP] 未执行重置")

    print("\n" + "=" * 60)
    print("操作完成")
    print("=" * 60)

except KeyboardInterrupt:
    print("\n\n[SKIP] 用户取消操作")
except Exception as e:
    print(f"\n[ERROR] 操作失败: {e}")
