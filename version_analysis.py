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
print('Version Performance Analysis')
print('='*80)

# Query trading period
cursor.execute('SELECT MIN(entry_time) as first_trade, MAX(entry_time) as last_trade FROM positions WHERE status = "closed"')
row = cursor.fetchone()

first_trade = datetime.strptime(row['first_trade'], '%Y-%m-%d %H:%M:%S')
last_trade = datetime.strptime(row['last_trade'], '%Y-%m-%d %H:%M:%S')

print(f'\nTrading Period: {first_trade.strftime("%Y-%m-%d %H:%M")} to {last_trade.strftime("%Y-%m-%d %H:%M")}')
print(f'Duration: {(last_trade - first_trade).days} days\n')

# Group by date and side
cursor.execute('''
    SELECT
        DATE(entry_time) as trade_date,
        side,
        COUNT(*) as total_trades,
        SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
        SUM(pnl_usd) as total_pnl
    FROM positions
    WHERE status = 'closed'
    GROUP BY DATE(entry_time), side
    ORDER BY trade_date ASC
''')

results = cursor.fetchall()

print('Daily Performance by Direction:')
print('-'*80)
current_date = None
for row in results:
    if row['trade_date'] != current_date:
        current_date = row['trade_date']
        print(f"\n{current_date}:")

    win_rate = (row['wins'] / row['total_trades'] * 100) if row['total_trades'] > 0 else 0
    print(f"  {row['side']:6s} | {row['total_trades']:2d} trades | Win: {row['wins']:2d} | Rate: {win_rate:5.1f}% | P&L: ${row['total_pnl']:+6.2f}")

# Find best performing day
cursor.execute('''
    SELECT
        DATE(entry_time) as trade_date,
        COUNT(*) as total,
        SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
        SUM(pnl_usd) as total_pnl
    FROM positions
    WHERE status = 'closed'
    GROUP BY DATE(entry_time)
    ORDER BY total_pnl DESC
    LIMIT 1
''')

best_day = cursor.fetchone()
print('\n' + '='*80)
print(f'BEST DAY: {best_day["trade_date"]}')
print(f'  Trades: {best_day["total"]} | Wins: {best_day["wins"]} | P&L: ${best_day["total_pnl"]:+.2f}')

conn.close()
print('='*80)
