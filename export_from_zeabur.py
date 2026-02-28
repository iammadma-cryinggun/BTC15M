#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zeabur云端数据库直接导出脚本
在Zeabur日志中直接复制粘贴运行
"""

import sqlite3
import sys
from datetime import datetime

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

db_path = '/app/data/btc_15min_auto_trades.db'

print("="*140)
print('Zeabur云端数据库导出')
print("="*140)

conn = sqlite3.connect(db_path, timeout=30.0)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# 检查表结构
cursor.execute("PRAGMA table_info(positions)")
columns = [col[1] for col in cursor.fetchall()]
print(f"数据库列: {', '.join(columns)}\n")

# 查询最近交易
try:
    cursor.execute("""
        SELECT
            entry_time, side, entry_token_price, exit_token_price,
            pnl_usd, pnl_pct, exit_reason, status,
            score, oracle_score, oracle_1h_trend, oracle_15m_trend, strategy
        FROM positions
        WHERE status = 'closed'
        ORDER BY entry_time DESC
        LIMIT 20
    """)
except sqlite3.OperationalError as e:
    print(f"[ERROR] {e}")
    print("\n尝试简化查询...")
    cursor.execute("""
        SELECT
            entry_time, side, entry_token_price, exit_token_price,
            pnl_usd, pnl_pct, exit_reason, status, score
        FROM positions
        WHERE status = 'closed'
        ORDER BY entry_time DESC
        LIMIT 20
    """)

trades = cursor.fetchall()

print(f"\n最近{len(trades)}笔交易:\n")

for i, t in enumerate(trades, 1):
    pnl_icon = "盈利" if t['pnl_usd'] and t['pnl_usd'] > 0 else "亏损"
    exit_price = f"{t['exit_token_price']:.4f}" if t['exit_token_price'] else "N/A"

    print(f"{i:2d}. [{t['entry_time']}] {t['side']:6s} {t['entry_token_price']:.4f}->{exit_price} {pnl_icon:4s} ${t['pnl_usd']:+.2f}")

    if t.get('oracle_score') and t['oracle_score'] != 0:
        print(f"     Oracle: {t['oracle_score']:+.2f} | 1H:{t['oracle_1h_trend']} 15m:{t['oracle_15m_trend']}")

# 统计
print("\n" + "="*140)
profit = sum(t['pnl_usd'] for t in trades if t['pnl_usd'] and t['pnl_usd'] > 0)
loss = sum(t['pnl_usd'] for t in trades if t['pnl_usd'] and t['pnl_usd'] < 0)
wins = sum(1 for t in trades if t['pnl_usd'] and t['pnl_usd'] > 0)
total = sum(1 for t in trades if t['pnl_usd'])

print(f"统计: {wins}/{total} 笔盈利, 净盈亏 ${profit+loss:+.2f}")
print("="*140)

conn.close()
