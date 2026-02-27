#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易数据导出工具
导出数据库中的所有交易记录和持仓记录，用于分析和学习
"""

import sqlite3
import os
import csv
import sys
from datetime import datetime
import json

# Windows终端编码修复
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# 数据库路径（根据环境自动选择）
data_dir = os.getenv('DATA_DIR', os.path.dirname(__file__))
# 优先使用V5专业版数据库（如果有）
v5_db = r'D:\OpenClaw\workspace\BTC_15min_V5_Professional\数据库\btc_15min_auto_trades.db'
db_path = v5_db if os.path.exists(v5_db) else os.path.join(data_dir, 'btc_15min_auto_trades.db')

if not os.path.exists(db_path):
    print(f"❌ 数据库文件不存在: {db_path}")
    print(f"当前工作目录: {os.getcwd()}")
    print(f"尝试的路径: {db_path}")
    exit(1)

print(f"📊 数据库位置: {db_path}\n")

# 连接数据库
conn = sqlite3.connect(db_path, timeout=30.0)
conn.row_factory = sqlite3.Row  # 使用字典格式
cursor = conn.cursor()

# ========== 1. 导出持仓记录 ==========
print("=" * 60)
print("📈 持仓记录统计")
print("=" * 60)

cursor.execute("""
    SELECT
        side,
        status,
        COUNT(*) as count,
        SUM(value_usdc) as total_value,
        SUM(pnl_usd) as total_pnl,
        AVG(pnl_pct) as avg_pct
    FROM positions
    GROUP BY side, status
    ORDER BY side, status
""")

stats = cursor.fetchall()
for row in stats:
    status_icon = "🟢" if row['status'] == 'closed' else "🔵" if row['status'] == 'open' else "🟡"
    print(f"{status_icon} {row['side']:6s} | {row['status']:8s} | "
          f"数量:{row['count']:3d} | 投入:${row['total_value']:7.2f} | "
          f"盈亏:${row['total_pnl']:7.2f} | 均率:{row['avg_pct']:6.2f}%")

# 导出持仓详情（兼容老数据库）
try:
    cursor.execute("""
        SELECT
            id, entry_time, side, entry_token_price, size, value_usdc,
            take_profit_usd, stop_loss_usd, take_profit_pct, stop_loss_pct,
            exit_time, exit_token_price, pnl_usd, pnl_pct, exit_reason, status, score
        FROM positions
        ORDER BY entry_time DESC
    """)
except sqlite3.OperationalError:
    # 老数据库没有score列
    cursor.execute("""
        SELECT
            id, entry_time, side, entry_token_price, size, value_usdc,
            take_profit_usd, stop_loss_usd, take_profit_pct, stop_loss_pct,
            exit_time, exit_token_price, pnl_usd, pnl_pct, exit_reason, status
        FROM positions
        ORDER BY entry_time DESC
    """)

positions = cursor.fetchall()
print(f"\n💾 导出 {len(positions)} 条持仓记录...")

with open('positions_export.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=positions[0].keys())
    writer.writeheader()
    writer.writerows([dict(row) for row in positions])

print("✅ 持仓记录已导出: positions_export.csv")

# ========== 2. 导出交易记录 ==========
print("\n" + "=" * 60)
print("📋 交易记录统计")
print("=" * 60)

cursor.execute("""
    SELECT
        side,
        status,
        COUNT(*) as count,
        SUM(value_usd) as total_value
    FROM trades
    GROUP BY side, status
    ORDER BY side, status
""")

trade_stats = cursor.fetchall()
for row in trade_stats:
    print(f"{row['side']:6s} | {row['status']:8s} | "
          f"数量:{row['count']:3d} | 金额:${row['total_value']:7.2f}")

# 导出交易详情
cursor.execute("""
    SELECT * FROM trades
    ORDER BY timestamp DESC
""")

trades = cursor.fetchall()
if trades:
    print(f"\n💾 导出 {len(trades)} 条交易记录...")
    with open('trades_export.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=trades[0].keys())
        writer.writeheader()
        writer.writerows([dict(row) for row in trades])
    print("✅ 交易记录已导出: trades_export.csv")
else:
    print("\n⚠️ 暂无交易记录")

# ========== 3. 关键统计指标 ==========
print("\n" + "=" * 60)
print("📊 关键指标分析")
print("=" * 60)

# 已平仓持仓
cursor.execute("""
    SELECT
        COUNT(*) as total_trades,
        SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as win_trades,
        SUM(CASE WHEN pnl_usd < 0 THEN 1 ELSE 0 END) as loss_trades,
        SUM(pnl_usd) as total_pnl,
        AVG(pnl_pct) as avg_pnl_pct,
        MAX(pnl_pct) as max_win_pct,
        MIN(pnl_pct) as max_loss_pct
    FROM positions
    WHERE status = 'closed'
""")

closed_stats = cursor.fetchone()
if closed_stats['total_trades'] > 0:
    win_rate = (closed_stats['win_trades'] / closed_stats['total_trades']) * 100
    print(f"总交易次数: {closed_stats['total_trades']}")
    print(f"盈利次数: {closed_stats['win_trades']}")
    print(f"亏损次数: {closed_stats['loss_trades']}")
    print(f"胜率: {win_rate:.2f}%")
    print(f"总盈亏: ${closed_stats['total_pnl']:.2f}")
    print(f"平均盈亏率: {closed_stats['avg_pnl_pct']:.2f}%")
    print(f"最大盈利: {closed_stats['max_win_pct']:.2f}%")
    print(f"最大亏损: {closed_stats['max_loss_pct']:.2f}%")
else:
    print("暂无已平仓记录")

# ========== 4. 今日统计 ==========
print("\n" + "=" * 60)
print("📅 今日交易统计")
print("=" * 60)

today = datetime.now().date().strftime('%Y-%m-%d')
cursor.execute("""
    SELECT
        COUNT(*) as count,
        SUM(pnl_usd) as total_pnl
    FROM positions
    WHERE status = 'closed' AND date(exit_time) = ?
""", (today,))

today_stats = cursor.fetchone()
print(f"今日平仓: {today_stats['count']} 单")
print(f"今日盈亏: ${today_stats['total_pnl'] or 0:.2f}")

# ========== 5. 合并持仓统计 ==========
print("\n" + "=" * 60)
print("🔗 合并持仓统计")
print("=" * 60)

try:
    cursor.execute("""
        SELECT COUNT(*) FROM positions WHERE merged_from > 0
    """)
    merged_count = cursor.fetchone()[0]
    print(f"合并持仓数量: {merged_count}")
except sqlite3.OperationalError:
    print("合并持仓: 老数据库无此功能")

# ========== 6. 最近10笔交易 ==========
print("\n" + "=" * 60)
print("🕒 最近10笔平仓记录")
print("=" * 60)

try:
    cursor.execute("""
        SELECT
            entry_time, side, entry_token_price, exit_token_price,
            pnl_usd, pnl_pct, exit_reason, score
        FROM positions
        WHERE status = 'closed'
        ORDER BY exit_time DESC
        LIMIT 10
    """)
    has_score = True
except sqlite3.OperationalError:
    cursor.execute("""
        SELECT
            entry_time, side, entry_token_price, exit_token_price,
            pnl_usd, pnl_pct, exit_reason
        FROM positions
        WHERE status = 'closed'
        ORDER BY exit_time DESC
        LIMIT 10
    """)
    has_score = False

recent = cursor.fetchall()
for row in recent:
    pnl_icon = "🟢" if row['pnl_usd'] > 0 else "🔴"
    exit_price = row['exit_token_price'] if row['exit_token_price'] else 0.0
    if has_score:
        print(f"{pnl_icon} {row['entry_time']} | {row['side']:5s} | "
              f"进:{row['entry_token_price']:.4f} → 出:{exit_price:.4f} | "
              f"盈亏:${row['pnl_usd']:6.2f} ({row['pnl_pct']:6.2f}%) | "
              f"理由:{row['exit_reason']:20s} | 评分:{row['score']:.1f}")
    else:
        print(f"{pnl_icon} {row['entry_time']} | {row['side']:5s} | "
              f"进:{row['entry_token_price']:.4f} → 出:{exit_price:.4f} | "
              f"盈亏:${row['pnl_usd']:6.2f} ({row['pnl_pct']:6.2f}%) | "
              f"理由:{row['exit_reason']:20s}")

conn.close()

print("\n" + "=" * 60)
print("✅ 导出完成！")
print("=" * 60)
print("\n📁 导出文件:")
print("   - positions_export.csv (持仓详情)")
print("   - trades_export.csv (交易详情)")
print("\n💡 可以用Excel/Numbers/Google Sheets打开分析")
