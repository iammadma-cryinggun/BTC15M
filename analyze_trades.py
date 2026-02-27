#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史交易数据分析工具
运行方式：python analyze_trades.py
"""

import sqlite3
import os
from datetime import datetime

def main():
    # 主交易数据库路径
    db_path = os.path.join(os.getenv('DATA_DIR', '/app/data'), 'btc_15min_auto_trades.db')

    if not os.path.exists(db_path):
        print(f"[ERROR] Database not found: {db_path}")
        return

    print('=' * 80)
    print('Historical Trading Analysis')
    print('=' * 80)
    print(f'Database: {db_path}')
    print(f'Size: {os.path.getsize(db_path)} bytes')
    print()

    conn = sqlite3.connect(db_path, timeout=30.0)
    cursor = conn.cursor()

    # 1. 查看所有交易
    print('\n[1] All Trading Records (Last 20)\n')
    cursor.execute('''
        SELECT id, timestamp, side, entry_token_price, size, exit_token_price, exit_reason, pnl_usd, pnl_pct
        FROM positions
        ORDER BY id DESC LIMIT 20
    ''')
    rows = cursor.fetchall()
    if rows:
        print(f'{"ID":<5} {"Time":<20} {"Side":<6} {"Entry":<8} {"Size":<8} {"Exit":<8} {"Reason":<25} {"PnL%":<8}')
        print('-' * 120)
        for row in rows:
            id, ts, side, entry, size, exit_p, reason, pnl_usd, pnl_pct = row
            ts = ts[:16] if len(ts) > 16 else ts
            reason = (reason or 'UNKNOWN')[:23]
            pnl_str = f'{pnl_pct:+.1f}%' if pnl_pct is not None else 'N/A'
            print(f'{id:<5} {ts:<20} {side:<6} {entry:<8.4f} {size:<8.1f} {exit_p or 0:<8.4f} {reason:<25} {pnl_str:<8}')
    else:
        print('No trading records found')

    # 2. 统计总体表现
    print('\n[2] Overall Statistics\n')
    cursor.execute('''
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
            AVG(pnl_pct) as avg_pnl,
            SUM(pnl_usd) as total_pnl
        FROM positions
        WHERE exit_reason IS NOT NULL
    ''')
    row = cursor.fetchone()
    if row and row[0] > 0:
        total, wins, avg_pnl, total_pnl = row
        win_rate = (wins / total * 100) if total > 0 else 0
        print(f'  Total Trades: {total}')
        print(f'  Win Rate: {win_rate:.1f}% ({wins}/{total})')
        print(f'  Avg Return: {avg_pnl:+.2f}%')
        print(f'  Total PnL: {total_pnl:+.2f} USDC')
    else:
        print('  No completed trades')

    # 3. 按方向统计
    print('\n[3] Statistics by Direction\n')
    cursor.execute('''
        SELECT
            side,
            COUNT(*) as total,
            SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
            AVG(pnl_pct) as avg_pnl,
            SUM(pnl_usd) as total_pnl
        FROM positions
        WHERE exit_reason IS NOT NULL
        GROUP BY side
    ''')
    rows = cursor.fetchall()
    if rows:
        print(f'{"Side":<8} {"Trades":<8} {"Wins":<8} {"Win Rate":<10} {"Avg Return":<12} {"Total PnL"}')
        print('-' * 70)
        for row in rows:
            side, total, wins, avg_pnl, total_pnl = row
            win_rate = (wins / total * 100) if total > 0 else 0
            print(f'{side:<8} {total:<8} {wins:<8} {win_rate:<8.1f}% {avg_pnl:+.2f}% ({total_pnl:+.2f} USDC)')

    # 4. 按退出原因统计
    print('\n[4] Statistics by Exit Reason\n')
    cursor.execute('''
        SELECT
            exit_reason,
            COUNT(*) as total,
            AVG(pnl_pct) as avg_pnl,
            SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins
        FROM positions
        WHERE exit_reason IS NOT NULL
        GROUP BY exit_reason
        ORDER BY total DESC
    ''')
    rows = cursor.fetchall()
    if rows:
        print(f'{"Exit Reason":<30} {"Count":<8} {"Wins":<8} {"Win Rate":<10} {"Avg Return"}')
        print('-' * 80)
        for row in rows:
            reason, total, wins, avg_pnl = row
            reason = (reason or 'UNKNOWN')[:28]
            win_rate = (wins / total * 100) if total > 0 else 0
            print(f'{reason:<30} {total:<8} {wins:<8} {win_rate:<8.1f}% {avg_pnl:+.2f}%')

    # 5. 盈亏分布
    print('\n[5] PnL Distribution\n')
    cursor.execute('''
        SELECT
            CASE
                WHEN pnl_pct >= 20 THEN '>= +20%'
                WHEN pnl_pct >= 10 THEN '+10% to +20%'
                WHEN pnl_pct >= 0 THEN '0% to +10%'
                WHEN pnl_pct >= -10 THEN '0% to -10%'
                WHEN pnl_pct >= -20 THEN '-10% to -20%'
                ELSE '< -20%'
            END as pnl_range,
            COUNT(*) as count,
            AVG(pnl_pct) as avg_pnl
        FROM positions
        WHERE exit_reason IS NOT NULL
        GROUP BY pnl_range
        ORDER BY MIN(pnl_pct) DESC
    ''')
    rows = cursor.fetchall()
    if rows:
        print(f'{"PnL Range":<15} {"Count":<8} {"Avg Return"}')
        print('-' * 35)
        for row in rows:
            pnl_range, count, avg_pnl = row
            print(f'{pnl_range:<15} {count:<8} {avg_pnl:+.2f}%')

    # 6. 最近表现
    print('\n[6] Recent Performance (Last 10 Trades)\n')
    cursor.execute('''
        SELECT timestamp, side, pnl_pct, exit_reason
        FROM positions
        WHERE exit_reason IS NOT NULL
        ORDER BY id DESC LIMIT 10
    ''')
    rows = cursor.fetchall()
    if rows:
        wins = sum(1 for _, _, pnl, _ in rows if pnl and pnl > 0)
        print(f'Last 10 trades win rate: {wins}/10 ({wins*10}%)')
        print()
        print(f'{"Time":<20} {"Side":<8} {"PnL%":<10} {"Reason"}')
        print('-' * 60)
        for ts, side, pnl, reason in rows:
            ts = ts[:16] if len(ts) > 16 else ts
            pnl_str = f'{pnl:+.1f}%' if pnl else 'N/A'
            reason = (reason or '')[:25]
            print(f'{ts:<20} {side:<8} {pnl_str:<10} {reason}')

    conn.close()
    print('\n' + '=' * 80)

if __name__ == '__main__':
    main()
