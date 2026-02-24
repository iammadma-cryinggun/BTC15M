#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Force close expired positions"""
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
import os
import sys

# Fix encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

os.environ['HTTP_PROXY'] = 'http://127.0.0.1:15236'
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:15236'

load_dotenv()

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs

PRIVATE_KEY = os.getenv('PRIVATE_KEY')
CLOB_HOST = 'https://clob.polymarket.com'
CHAIN_ID = 137

print("=" * 70)
print("Force Close Expired Positions")
print("=" * 70)

try:
    client = ClobClient(CLOB_HOST, key=PRIVATE_KEY, chain_id=CHAIN_ID, signature_type=2)
    print("[OK] CLOB client connected\n")
except Exception as e:
    print(f"[ERROR] {e}")
    exit(1)

conn = sqlite3.connect('btc_15min_auto_trades.db')
cursor = conn.cursor()

cursor.execute("""
    SELECT id, entry_time, side, size, token_id, entry_token_price
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
    pos_id, entry_time, side, size, token_id, entry_price = pos

    entry_dt = datetime.strptime(entry_time, '%Y-%m-%d %H:%M:%S')
    minutes_old = (datetime.now() - entry_dt).total_seconds() / 60

    print(f"ID #{pos_id} | {entry_time} | {side} | {size} tokens | {minutes_old:.1f} min old")

    if minutes_old > 15:
        print(f"  [EXPIRED] Force closing...")

        try:
            # Get current market price
            import requests
            resp = requests.get(
                "https://gamma-api.polymarket.com/markets",
                params={'limit': 1, 'closed': False},
                proxies={'http': 'http://127.0.0.1:15236', 'https': 'http://127.0.0.1:15236'},
                timeout=10
            )

            current_price = 0.5
            if resp.status_code == 200:
                markets = resp.json()
                if markets:
                    market = markets[0]
                    outcome_prices = market.get('outcomePrices', [])
                    if isinstance(outcome_prices, str):
                        import json
                        outcome_prices = json.loads(outcome_prices)
                    if outcome_prices and len(outcome_prices) >= 2:
                        current_price = float(outcome_prices[1])
                        print(f"  Current NO price: {current_price:.4f}")

            # Market order close
            close_price = max(0.01, min(0.99, current_price * 0.97))

            close_order_args = OrderArgs(
                token_id=token_id,
                price=round(close_price, 3),
                size=float(size),
                side='SELL'
            )

            print(f"  Posting market order @ {close_price:.4f}...")
            close_response = client.create_and_post_order(close_order_args)

            if close_response and 'orderID' in close_response:
                close_order_id = close_response['orderID']
                print(f"  [OK] Close order posted: {close_order_id[-8:]}")

                import time
                time.sleep(3)

                close_order = client.get_order(close_order_id)
                if close_order:
                    status = close_order.get('status')
                    print(f"  Order status: {status}")

                    if status in ['FILLED', 'MATCHED']:
                        actual_exit_price = close_order.get('price', current_price)
                        pnl = (actual_exit_price - entry_price) * size

                        cursor.execute("""
                            UPDATE positions
                            SET status = 'closed',
                                exit_time = ?,
                                exit_token_price = ?,
                                exit_reason = 'FORCE_CLOSE_EXPIRED',
                                pnl_usd = ?
                            WHERE id = ?
                        """, (
                            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            actual_exit_price,
                            pnl,
                            pos_id
                        ))
                        conn.commit()
                        print(f"  [OK] DB updated: PNL ~ ${pnl:.2f}")
                    else:
                        print(f"  [WARN] Order not filled yet")
            else:
                print(f"  [ERROR] Close failed: {close_response}")

        except Exception as e:
            print(f"  [ERROR] {e}")

    print()

conn.close()
print("=" * 70)
