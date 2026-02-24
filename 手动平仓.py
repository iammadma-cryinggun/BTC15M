#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
立即手动平掉所有OPEN状态的持仓
"""
import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
import sqlite3
from datetime import datetime
import time

os.environ['HTTP_PROXY'] = 'http://127.0.0.1:15236'
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:15236'

load_dotenv()

PRIVATE_KEY = os.getenv('PRIVATE_KEY')
CLOB_HOST = 'https://clob.polymarket.com'
CHAIN_ID = 137
DB_PATH = 'btc_15min_auto_trades.db'

print("=" * 60)
print("立即平掉所有OPEN持仓".center(60))
print("=" * 60)

# 初始化客户端
client = ClobClient(CLOB_HOST, key=PRIVATE_KEY, chain_id=CHAIN_ID, signature_type=2)
api_creds = client.create_or_derive_api_creds()
client = ClobClient(CLOB_HOST, key=PRIVATE_KEY, chain_id=CHAIN_ID, creds=api_creds, signature_type=2)

# 查询所有OPEN持仓
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute("""
    SELECT id, side, entry_token_price, size, token_id, value_usdc
    FROM positions
    WHERE status = 'open'
""")
positions = cursor.fetchall()

if not positions:
    print("没有OPEN持仓")
else:
    print(f"找到 {len(positions)} 个OPEN持仓\n")

    for pos_id, side, entry_price, size, token_id, value_usdc in positions:
        print(f"[{pos_id}] {side} {size:.0f} @ {entry_price:.4f} (Token: {token_id[-8:]})")

        # 获取当前价格
        try:
            prices = client.get_market_prices(token_id)
            current_price = float(prices[0]) if prices else entry_price
        except:
            current_price = entry_price

        # 打2%折平仓
        close_price = max(0.01, current_price * 0.98)

        print(f"    当前价: {current_price:.4f} → 平仓价: {close_price:.4f}")

        # 挂平仓单
        try:
            order_args = OrderArgs(
                token_id=token_id,
                price=close_price,
                size=float(size),
                side=SELL
            )
            resp = client.create_and_post_order(order_args)

            if resp and 'orderID' in resp:
                order_id = resp['orderID']
                print(f"    ✅ 平仓单已挂: {order_id[-8:]}")

                # 等待成交
                for i in range(5):
                    time.sleep(1)
                    order = client.get_order(order_id)
                    if order.get('status') == 'FILLED':
                        filled_price = order.get('price', close_price)
                        pnl = size * (filled_price - entry_price) if side == 'LONG' else size * (entry_price - filled_price)
                        pnl_pct = (pnl / value_usdc) * 100

                        # 更新数据库
                        cursor.execute("""
                            UPDATE positions
                            SET status='closed', exit_reason='MANUAL_CLOSE',
                                exit_time=?, exit_token_price=?, pnl_usd=?, pnl_pct=?
                            WHERE id=?
                        """, (
                            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            filled_price, pnl, pnl_pct, pos_id
                        ))
                        conn.commit()
                        print(f"    ✅ 已成交: {filled_price:.4f} | PnL: ${pnl:+.2f} ({pnl_pct:+.1f}%)")
                        break
                else:
                    print(f"    ⚠️  未立即成交，请手动检查")
        except Exception as e:
            print(f"    ❌ 失败: {e}")

conn.close()
print("\n" + "=" * 60)
