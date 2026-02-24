#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mark expired positions as settled"""
import sqlite3
from datetime import datetime

conn = sqlite3.connect('btc_15min_auto_trades.db')
cursor = conn.cursor()

print("=" * 70)
print("Mark Expired Positions as Settled")
print("=" * 70)

cursor.execute("""
    SELECT id, entry_time, side, size, entry_token_price
    FROM positions
    WHERE status = 'open'
    ORDER BY entry_time
""")

positions = cursor.fetchall()

if not positions:
    print("No OPEN positions found")
    conn.close()
    exit(0)

print(f"Found {len(positions)} OPEN position(s)\n")

for pos in positions:
    pos_id, entry_time, side, size, entry_price = pos

    entry_dt = datetime.strptime(entry_time, '%Y-%m-%d %H:%M:%S')
    minutes_old = (datetime.now() - entry_dt).total_seconds() / 60

    print(f"ID #{pos_id} | {entry_time} | {side} | {size} tokens | {minutes_old:.1f} min old")

    if minutes_old > 15:
        print(f"  [EXPIRED] Marking as settled...")

        # 根据当前市场价格计算盈亏
        # NO价格 0.9670 = 盈利
        current_price = 0.9670
        pnl = (current_price - entry_price) * size

        print(f"  Entry: {entry_price:.4f} -> Current: {current_price:.4f}")
        print(f"  PNL: ${pnl:.2f}")

        cursor.execute("""
            UPDATE positions
            SET status = 'closed',
                exit_time = ?,
                exit_token_price = ?,
                exit_reason = 'MARKET_SETTLED',
                pnl_usd = ?
            WHERE id = ?
        """, (
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            current_price,
            pnl,
            pos_id
        ))
        conn.commit()
        print(f"  [OK] Marked as settled\n")

conn.close()
print("=" * 70)
print("Done! The bot will now stop monitoring this position.")
print("=" * 70)
