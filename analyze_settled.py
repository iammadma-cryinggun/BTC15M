#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import sys
from datetime import datetime

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

db_path = r'D:\OpenClaw\workspace\BTC_15min_V5_Professional\数据库\btc_15min_auto_trades.db'
conn = sqlite3.connect(db_path, timeout=30.0)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print('='*80)
print('MARKET_SETTLED Win Rate Analysis (Final Results)')
print('='*80)

# Query all market settled trades
cursor.execute('''
    SELECT
        side,
        COUNT(*) as total,
        SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
        SUM(pnl_usd) as total_pnl,
        AVG(pnl_pct) as avg_pct,
        MAX(pnl_pct) as max_win,
        MIN(pnl_pct) as max_loss
    FROM positions
    WHERE exit_reason = 'MARKET_SETTLED'
    GROUP BY side
    ORDER BY side DESC
''')

results = cursor.fetchall()

total_trades = 0
total_wins = 0
total_pnl = 0

for row in results:
    total_trades += row['total']
    total_wins += row['wins']
    total_pnl += row['total_pnl']
    win_rate = (row['wins'] / row['total'] * 100) if row['total'] > 0 else 0

    print(f'\n{row["side"]:6s}:')
    print(f'  Total trades: {row["total"]}')
    print(f'  Winning trades: {row["wins"]}')
    print(f'  Losing trades: {row["total"] - row["wins"]}')
    print(f'  Win rate: {win_rate:.1f}%')
    print(f'  Total P&L: ${row["total_pnl"]:+.2f}')
    print(f'  Avg P&L %: {row["avg_pct"]:.2f}%')
    print(f'  Max win: {row["max_win"]:.2f}%')
    print(f'  Max loss: {row["max_loss"]:.2f}%')

overall_win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
print(f'\n=== OVERALL ===')
print(f'  Total trades: {total_trades}')
print(f'  Total wins: {total_wins}')
print(f'  Total losses: {total_trades - total_wins}')
print(f'  Overall win rate: {overall_win_rate:.1f}%')
print(f'  Total P&L: ${total_pnl:+.2f}')

# List each trade
print(f'\n=== Detailed Trades ===')
cursor.execute('''
    SELECT
        entry_time,
        side,
        entry_token_price,
        exit_token_price,
        pnl_usd,
        pnl_pct
    FROM positions
    WHERE exit_reason = 'MARKET_SETTLED'
    ORDER BY entry_time DESC
''')

details = cursor.fetchall()
for i, row in enumerate(details, 1):
    pnl_icon = 'WIN ' if row['pnl_usd'] > 0 else 'LOSS'
    print(f'{i:2d}. [{pnl_icon}] {row["entry_time"]} | {row["side"]:5s} | '
          f'{row["entry_token_price"]:.4f}->{row["exit_token_price"]:.4f} | '
          f'${row["pnl_usd"]:+.2f} ({row["pnl_pct"]:+.1f}%)')

conn.close()
print('\n' + '='*80)
