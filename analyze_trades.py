#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度交易数据分析工具
分析不同维度下的交易表现，找出最优参数
"""

import sqlite3
import os
import sys
import csv
from datetime import datetime
from collections import defaultdict

# Windows终端编码修复
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# 数据库路径
db_path = r'D:\OpenClaw\workspace\BTC_15min_V5_Professional\数据库\btc_15min_auto_trades.db'

print(f"📊 数据库: {db_path}\n")

conn = sqlite3.connect(db_path, timeout=30.0)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# ========== 1. 按入场价格区间分析 ==========
print("=" * 80)
print("💰 按入场价格区间分析（什么价位开仓最赚钱？）")
print("=" * 80)

cursor.execute("""
    SELECT
        CASE
            WHEN entry_token_price < 0.10 THEN '极低 <0.10'
            WHEN entry_token_price < 0.20 THEN '低 0.10-0.20'
            WHEN entry_token_price < 0.30 THEN '中低 0.20-0.30'
            WHEN entry_token_price < 0.50 THEN '中 0.30-0.50'
            WHEN entry_token_price < 0.70 THEN '中高 0.50-0.70'
            ELSE '高 >=0.70'
        END as price_range,
        side,
        COUNT(*) as total,
        SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
        SUM(pnl_usd) as total_pnl,
        AVG(pnl_pct) as avg_pnl_pct,
        MAX(pnl_pct) as max_pct,
        MIN(pnl_pct) as min_pct
    FROM positions
    WHERE status = 'closed'
    GROUP BY price_range, side
    ORDER BY
        CASE
            WHEN price_range = '极低 <0.10' THEN 1
            WHEN price_range = '低 0.10-0.20' THEN 2
            WHEN price_range = '中低 0.20-0.30' THEN 3
            WHEN price_range = '中 0.30-0.50' THEN 4
            WHEN price_range = '中高 0.50-0.70' THEN 5
            ELSE 6
        END,
        side
""")

price_stats = cursor.fetchall()
current_range = None
for row in price_stats:
    if row['price_range'] != current_range:
        current_range = row['price_range']
        print(f"\n【{current_range}】")
    win_rate = (row['wins'] / row['total'] * 100) if row['total'] > 0 else 0
    total_pnl = row['total_pnl'] or 0
    pnl_icon = "🟢" if total_pnl > 0 else "🔴"
    print(f"  {row['side']:5s} | {row['total']:2d}笔 | 胜率:{win_rate:5.1f}% | "
          f"盈亏:${total_pnl:6.2f} | 均率:{row['avg_pnl_pct'] or 0:6.2f}% | "
          f"范围:{row['min_pct'] or 0:6.1f}% ~ {row['max_pct'] or 0:6.1f}%")

# ========== 2. 按退出原因分析 ==========
print("\n" + "=" * 80)
print("🎯 按退出原因分析（哪种方式平仓效果最好？）")
print("=" * 80)

cursor.execute("""
    SELECT
        exit_reason,
        side,
        COUNT(*) as total,
        SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
        SUM(pnl_usd) as total_pnl,
        AVG(pnl_pct) as avg_pnl_pct
    FROM positions
    WHERE status = 'closed' AND exit_reason IS NOT NULL
    GROUP BY exit_reason, side
    ORDER BY total_pnl DESC
""")

exit_stats = cursor.fetchall()
for row in exit_stats:
    win_rate = (row['wins'] / row['total'] * 100) if row['total'] > 0 else 0
    total_pnl = row['total_pnl'] or 0
    pnl_icon = "🟢" if total_pnl > 0 else "🔴"
    print(f"{pnl_icon} {row['exit_reason']:25s} | {row['side']:5s} | "
          f"{row['total']:2d}笔 | 胜率:{win_rate:5.1f}% | "
          f"盈亏:${total_pnl:7.2f} | 均率:{row['avg_pnl_pct'] or 0:6.2f}%")

# ========== 3. 按时间段分析（小时） ==========
print("\n" + "=" * 80)
print("⏰ 按开仓时间段分析（哪个时间段交易效果最好？）")
print("=" * 80)

cursor.execute("""
    SELECT
        CAST(strftime('%H', entry_time) AS INTEGER) as hour,
        side,
        COUNT(*) as total,
        SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
        SUM(pnl_usd) as total_pnl,
        AVG(pnl_pct) as avg_pnl_pct
    FROM positions
    WHERE status = 'closed'
    GROUP BY hour, side
    ORDER BY hour, side
""")

time_stats = defaultdict(lambda: {'LONG': None, 'SHORT': None})
for row in cursor.fetchall():
    time_stats[row['hour']][row['side']] = row

print(f"{'时间':<6} {'LONG':<40} {'SHORT':<40}")
print("-" * 80)
for hour in sorted(time_stats.keys()):
    line = f"{hour:02d}:00  "
    for side in ['LONG', 'SHORT']:
        data = time_stats[hour][side]
        if data:
            win_rate = (data['wins'] / data['total'] * 100) if data['total'] > 0 else 0
            total_pnl = data['total_pnl'] or 0
            line += f"{data['total']:2d}笔 ${total_pnl:6.2f} ({win_rate:4.0f}%)  "
        else:
            line += "-" * 36 + "  "
    print(line)

# ========== 4. 亏损交易详细分析 ==========
print("\n" + "=" * 80)
print("🔴 亏损TOP 10 交易（学习教训）")
print("=" * 80)

cursor.execute("""
    SELECT
        entry_time, side, entry_token_price, exit_token_price,
        size, value_usdc, pnl_usd, pnl_pct, exit_reason
    FROM positions
    WHERE status = 'closed' AND pnl_usd < 0
    ORDER BY pnl_usd ASC
    LIMIT 10
""")

loss_trades = cursor.fetchall()
for i, row in enumerate(loss_trades, 1):
    print(f"\n#{i} {row['entry_time']} | {row['side']:5s}")
    print(f"    进:{row['entry_token_price']:.4f} → 出:{row['exit_token_price'] or 0:.4f} | "
          f"{row['size']:.1f}股 @ ${row['value_usdc']:.2f}")
    print(f"    亏损:${row['pnl_usd']:.2f} ({row['pnl_pct']:.1f}%) | 退出:{row['exit_reason']}")

# ========== 5. 盈利交易详细分析 ==========
print("\n" + "=" * 80)
print("🟢 盈利TOP 10 交易（复制成功）")
print("=" * 80)

cursor.execute("""
    SELECT
        entry_time, side, entry_token_price, exit_token_price,
        size, value_usdc, pnl_usd, pnl_pct, exit_reason
    FROM positions
    WHERE status = 'closed' AND pnl_usd > 0
    ORDER BY pnl_usd DESC
    LIMIT 10
""")

win_trades = cursor.fetchall()
for i, row in enumerate(win_trades, 1):
    print(f"\n#{i} {row['entry_time']} | {row['side']:5s}")
    print(f"    进:{row['entry_token_price']:.4f} → 出:{row['exit_token_price']:.4f} | "
          f"{row['size']:.1f}股 @ ${row['value_usdc']:.2f}")
    print(f"    盈利:${row['pnl_usd']:.2f} ({row['pnl_pct']:.1f}%) | 退出:{row['exit_reason']}")

# ========== 6. 连续亏损/盈利分析 ==========
print("\n" + "=" * 80)
print("📈 连续交易分析（是否有连亏/连胜模式？）")
print("=" * 80)

cursor.execute("""
    SELECT
        entry_time,
        side,
        entry_token_price,
        exit_token_price,
        pnl_usd,
        exit_reason
    FROM positions
    WHERE status = 'closed'
    ORDER BY exit_time ASC
""")

all_trades = cursor.fetchall()
max_consecutive_wins = 0
max_consecutive_losses = 0
current_wins = 0
current_losses = 0
win_streaks = []
loss_streaks = []

for trade in all_trades:
    if trade['pnl_usd'] > 0:
        current_wins += 1
        if current_losses > 0:
            loss_streaks.append(current_losses)
            max_consecutive_losses = max(max_consecutive_losses, current_losses)
            current_losses = 0
    else:
        current_losses += 1
        if current_wins > 0:
            win_streaks.append(current_wins)
            max_consecutive_wins = max(max_consecutive_wins, current_wins)
            current_wins = 0

# 最后一段
if current_wins > 0:
    win_streaks.append(current_wins)
    max_consecutive_wins = max(max_consecutive_wins, current_wins)
if current_losses > 0:
    loss_streaks.append(current_losses)
    max_consecutive_losses = max(max_consecutive_losses, current_losses)

avg_win_streak = sum(win_streaks) / len(win_streaks) if win_streaks else 0
avg_loss_streak = sum(loss_streaks) / len(loss_streaks) if loss_streaks else 0

print(f"最长连胜: {max_consecutive_wins} 笔")
print(f"平均连胜: {avg_win_streak:.1f} 笔")
print(f"最长连亏: {max_consecutive_losses} 笔")
print(f"平均连亏: {avg_loss_streak:.1f} 笔")

# ========== 7. 持仓时长分析 ==========
print("\n" + "=" * 80)
print("⏱️  持仓时长分析（持有多久最合适？）")
print("=" * 80)

cursor.execute("""
    SELECT
        CASE
            WHEN julianday(exit_time) - julianday(entry_time) < 1.0/1440 THEN '<1分钟'
            WHEN julianday(exit_time) - julianday(entry_time) < 5.0/1440 THEN '1-5分钟'
            WHEN julianday(exit_time) - julianday(entry_time) < 15.0/1440 THEN '5-15分钟'
            WHEN julianday(exit_time) - julianday(entry_time) < 30.0/1440 THEN '15-30分钟'
            ELSE '>30分钟'
        END as duration,
        side,
        COUNT(*) as total,
        SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
        SUM(pnl_usd) as total_pnl,
        AVG(pnl_pct) as avg_pnl_pct
    FROM positions
    WHERE status = 'closed' AND exit_time IS NOT NULL
    GROUP BY duration, side
    ORDER BY
        CASE duration
            WHEN '<1分钟' THEN 1
            WHEN '1-5分钟' THEN 2
            WHEN '5-15分钟' THEN 3
            WHEN '15-30分钟' THEN 4
            ELSE 5
        END,
        side
""")

duration_stats = cursor.fetchall()
current_duration = None
for row in duration_stats:
    if row['duration'] != current_duration:
        current_duration = row['duration']
        print(f"\n【{current_duration}】")
    win_rate = (row['wins'] / row['total'] * 100) if row['total'] > 0 else 0
    total_pnl = row['total_pnl'] or 0
    pnl_icon = "🟢" if total_pnl > 0 else "🔴"
    print(f"  {row['side']:5s} | {row['total']:2d}笔 | 胜率:{win_rate:5.1f}% | "
          f"盈亏:${total_pnl:6.2f} | 均率:{row['avg_pnl_pct'] or 0:6.2f}%")

conn.close()

print("\n" + "=" * 80)
print("✅ 分析完成！")
print("=" * 80)
