#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手动关闭失败的开仓订单（止盈止损单都没挂上的情况）
"""
import os
import sys
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, AssetType
from py_clob_client.constants import SELL
import sqlite3
from datetime import datetime

# 设置代理
os.environ['HTTP_PROXY'] = 'http://127.0.0.1:15236'
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:15236'

load_dotenv()

PRIVATE_KEY = os.getenv('PRIVATE_KEY')
CLOB_HOST = 'https://clob.polymarket.com'
CHAIN_ID = 137
DB_PATH = 'btc_15min_auto_trades.db'

def main():
    print("=" * 80)
    print("手动关闭失败的开仓订单".center(80))
    print("=" * 80)

    # 初始化客户端
    client = ClobClient(
        CLOB_HOST,
        key=PRIVATE_KEY,
        chain_id=CHAIN_ID,
        signature_type=2
    )
    api_creds = client.create_or_derive_api_creds()
    client = ClobClient(
        CLOB_HOST,
        key=PRIVATE_KEY,
        chain_id=CHAIN_ID,
        creds=api_creds,
        signature_type=2
    )
    print(f"✅ 客户端初始化成功\n")

    # 连接数据库
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 查找没有止盈止损单的open持仓
    cursor.execute("""
        SELECT id, entry_time, side, entry_token_price, size, value_usdc, token_id
        FROM positions
        WHERE status = 'open'
          AND (take_profit_order_id IS NULL OR stop_loss_order_id IS NULL)
    """)

    failed_positions = cursor.fetchall()

    if not failed_positions:
        print("❌ 没有找到失败的持仓（所有open持仓都有止盈止损单）")
        conn.close()
        return

    print(f"找到 {len(failed_positions)} 个失败的持仓：\n")

    for pos in failed_positions:
        pos_id, entry_time, side, entry_price, size, value_usdc, token_id = pos

        print(f"持仓 #{pos_id}")
        print(f"  方向: {side}")
        print(f"  入场: {entry_price:.4f} × {size:.0f} = ${value_usdc:.2f}")
        print(f"  Token ID: {token_id}")
        print(f"  入场时间: {entry_time}")

        # 确认是否平仓
        choice = input("\n是否平仓这个持仓？(y/n): ").strip().lower()
        if choice != 'y':
            print("  跳过\n")
            continue

        try:
            # 获取当前市场价格
            print(f"  获取当前市场价格...")
            market_prices = client.get_market_prices(token_id)
            if market_prices and len(market_prices) > 0:
                current_price = float(market_prices[0])
                print(f"  当前价格: {current_price:.4f}")
            else:
                print(f"  ⚠️  无法获取市场价格，使用入场价格")
                current_price = entry_price

            # 计算平仓价格（使用当前买一价，确保成交）
            # 为了快速成交，使用略低于当前价格的卖单
            close_price = max(0.01, current_price * 0.98)  # 打2%折确保成交

            print(f"  平仓价格: {close_price:.4f} (打2%折)")

            # 创建市价平仓订单
            order_args = OrderArgs(
                token_id=token_id,
                price=close_price,
                size=float(size),
                side=SELL  # 平仓永远是SELL
            )

            print(f"  挂平仓单...")
            response = client.create_and_post_order(order_args)

            if response and 'orderID' in response:
                order_id = response['orderID']
                print(f"  ✅ 平仓单已挂: {order_id}")

                # 等待几秒看看是否成交
                import time
                time.sleep(3)

                order_info = client.get_order(order_id)
                if order_info:
                    status = order_info.get('status', '')
                    print(f"  订单状态: {status}")

                    # 更新数据库
                    if status == 'FILLED':
                        # 计算盈亏
                        if side == 'LONG':
                            pnl_usd = size * (close_price - entry_price)
                        else:
                            pnl_usd = size * (entry_price - close_price)
                        pnl_pct = (pnl_usd / value_usdc) * 100 if value_usdc > 0 else 0

                        cursor.execute("""
                            UPDATE positions
                            SET exit_time = ?, exit_token_price = ?, pnl_usd = ?,
                                pnl_pct = ?, exit_reason = 'MANUAL_CLOSE', status = 'closed'
                            WHERE id = ?
                        """, (
                            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            close_price,
                            pnl_usd,
                            pnl_pct,
                            pos_id
                        ))
                        conn.commit()
                        print(f"  ✅ 数据库已更新")
                        print(f"  盈亏: ${pnl_usd:+.2f} ({pnl_pct:+.1f}%)")
                    else:
                        print(f"  ⚠️  订单未成交，请稍后手动检查")
            else:
                print(f"  ❌ 平仓单失败")

        except Exception as e:
            print(f"  ❌ 平仓失败: {e}")
            import traceback
            traceback.print_exc()

        print()

    conn.close()
    print("=" * 80)
    print("完成".center(80))
    print("=" * 80)

if __name__ == '__main__':
    main()
