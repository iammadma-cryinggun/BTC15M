#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从Polymarket获取历史交易记录并重建盈亏统计"""

import os
import sqlite3
from dotenv import load_dotenv

os.environ['HTTP_PROXY'] = 'http://127.0.0.1:15236'
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:15236'

load_dotenv()

from py_clob_client.client import ClobClient
import requests
from datetime import datetime, timedelta

PRIVATE_KEY = os.getenv('PRIVATE_KEY')
CLOB_HOST = 'https://clob.polymarket.com'
CHAIN_ID = 137

print("=" * 60)
print("历史交易查询工具")
print("=" * 60)

try:
    client = ClobClient(CLOB_HOST, key=PRIVATE_KEY, chain_id=CHAIN_ID, signature_type=2)
    print("[OK] CLOB客户端已连接\n")
except Exception as e:
    print(f"[ERROR] {e}")
    exit(1)

# 方法1：尝试从py_clob_client获取交易历史
print("=== 方法1: SDK获取交易历史 ===")
try:
    # 尝试不同的方法
    if hasattr(client, 'get_trades'):
        trades = client.get_trades()
        print(f"找到 {len(trades)} 笔交易")
    elif hasattr(client, 'get_my_trades'):
        trades = client.get_my_trades()
        print(f"找到 {len(trades)} 笔交易")
    elif hasattr(client, 'get_user_fills'):
        fills = client.get_user_fills()
        print(f"找到 {len(fills)} 笔成交记录")
    else:
        print("SDK没有找到获取交易历史的方法")
        # 列出所有可用方法
        methods = [m for m in dir(client) if not m.startswith('_') and 'get' in m.lower()]
        print(f"可用的get方法: {methods[:10]}")
except Exception as e:
    print(f"SDK方法失败: {e}")

print()

# 方法2：尝试从Gamma API获取
print("=== 方法2: Gamma API获取 ===")
try:
    # Polymarket Gamma API可能没有个人交易记录的端点
    print("Gamma API主要用于市场数据，不提供个人交易历史")
except Exception as e:
    print(f"Gamma API失败: {e}")

print()

# 方法3：从本地trades数据库重建（基于假设）
print("=== 方法3: 从本地数据估算 ===")
print("注意：这是基于当前价格的理论估算，不是真实盈亏")

conn = sqlite3.connect('btc_15min_auto_trades.db')
cursor = conn.cursor()

# 获取当前市场价格
try:
    resp = requests.get(
        "https://gamma-api.polymarket.com/markets",
        params={'limit': 1, 'closed': False},
        proxies={'http': 'http://127.0.0.1:15236', 'https': 'http://127.0.0.1:15236'},
        timeout=10
    )
    if resp.status_code == 200:
        markets = resp.json()
        if markets:
            market = markets[0]
            outcome_prices = market.get('outcomePrices', [])
            if isinstance(outcome_prices, str):
                import json
                outcome_prices = json.loads(outcome_prices)
            if outcome_prices and len(outcome_prices) >= 2:
                current_yes = float(outcome_prices[0])
                current_no = float(outcome_prices[1])
                print(f"\n当前市场价格: YES={current_yes:.4f}, NO={current_no:.4f}")

                # 简单估算：假设所有持仓都在当前价格平仓
                cursor.execute("SELECT side, price, value_usd FROM trades WHERE status = 'posted'")
                executed_trades = cursor.fetchall()

                total_pnl = 0
                wins = 0
                total = 0

                print("\n理论盈亏估算（基于当前价格）:")
                for trade in executed_trades:
                    side, entry_price, value_usd = trade
                    if value_usd > 0:
                        total += 1
                        # 假设已结算
                        # 实际需要真实的出场价格
                        # 这里只是占位符
                        pass

                print("\n注意：这只是估算，真实盈亏需要从Polymarket网页端查看")
except Exception as e:
    print(f"获取价格失败: {e}")

conn.close()

print("\n" + "=" * 60)
print("建议：")
print("1. 从Polymarket网页端查看真实的交易历史和盈亏")
print("2. 网页端路径: Account → Activity → Trade History")
print("3. 从现在开始，程序会记录所有持仓到trading_bot.db")
print("=" * 60)
