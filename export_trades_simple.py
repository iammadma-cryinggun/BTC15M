#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导出最近交易记录（包含Oracle数据）
用法: cd /app && python export_trades_simple.py
"""

import sqlite3
import os
import sys
from datetime import datetime

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

data_dir = os.getenv('DATA_DIR', '/app/data')
db_path = os.path.join(data_dir, 'btc_15min_auto_trades.db')

if not os.path.exists(db_path):
    print(f"[ERROR] 数据库不存在: {db_path}")
    sys.exit(1)

conn = sqlite3.connect(db_path, timeout=30.0)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# 查询数据库实际有哪些列
cursor.execute("PRAGMA table_info(positions)")
columns_info = cursor.fetchall()
existing_columns = [col[1] for col in columns_info]

print(f"[INFO] 数据库列: {', '.join(existing_columns)}")

# 构建查询SQL（只查询存在的列）
required_columns = ['entry_time', 'side', 'entry_token_price', 'exit_token_price', 'pnl_usd', 'pnl_pct', 'exit_reason', 'status']
optional_columns = ['score', 'oracle_score', 'oracle_1h_trend', 'oracle_15m_trend', 'strategy']

select_columns = []
for col in required_columns:
    if col in existing_columns:
        select_columns.append(col)
for col in optional_columns:
    if col in existing_columns:
        select_columns.append(col)

sql = f"SELECT {', '.join(select_columns)} FROM positions WHERE status = 'closed' ORDER BY entry_time DESC LIMIT 10"

print(f"[INFO] 执行查询: {sql}\n")

cursor.execute(sql)
trades = cursor.fetchall()

print("\n" + "="*120)
print(f"最近{len(trades)}笔交易记录")
print("="*120)

for i, t in enumerate(trades, 1):
    pnl_icon = "盈利" if t['pnl_usd'] and t['pnl_usd'] > 0 else "亏损"
    exit_price = f"{t['exit_token_price']:.4f}" if t.get('exit_token_price') else "N/A"

    print(f"\n交易 #{i} - {pnl_icon}")
    print(f"  时间:     {t['entry_time']}")
    print(f"  方向:     {t['side']}")
    print(f"  入场价:   {t['entry_token_price']:.4f}")
    print(f"  出场价:   {exit_price}")
    if t.get('pnl_usd'):
        print(f"  盈亏:     ${t['pnl_usd']:+.2f} ({t['pnl_pct']:+.1f}%)")
    else:
        print(f"  盈亏:     N/A")
    print(f"  退出原因: {t['exit_reason']}")

    if 'score' in t and t['score'] is not None:
        print(f"  本地分数: {t['score']:+.2f}")
    if 'oracle_score' in t and t['oracle_score'] is not None:
        print(f"  Oracle分数: {t['oracle_score']:+.2f}")
        print(f"  1H趋势: {t['oracle_1h_trend']}")
        print(f"  15m趋势: {t['oracle_15m_trend']}")
    if 'strategy' in t and t['strategy'] is not None:
        print(f"  策略:     {t['strategy']}")

print("\n" + "="*120)

# 统计
if trades:
    profit_count = sum(1 for t in trades if t.get('pnl_usd') and t['pnl_usd'] > 0)
    loss_count = sum(1 for t in trades if t.get('pnl_usd') and t['pnl_usd'] < 0)
    total_pnl = sum(t['pnl_usd'] for t in trades if t.get('pnl_usd'))

    print(f"统计: 盈利{profit_count}笔, 亏损{loss_count}笔, 净盈亏${total_pnl:+.2f}")
    print("="*120 + "\n")

conn.close()
