#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
from dotenv import load_dotenv
import sys

os.environ['HTTP_PROXY'] = 'http://127.0.0.1:15236'
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:15236'

load_dotenv()

from py_clob_client.client import ClobClient
import requests
import json

PRIVATE_KEY = os.getenv('PRIVATE_KEY')
CLOB_HOST = 'https://clob.polymarket.com'
CHAIN_ID = 137

print("=" * 60)
print("Diagnose: Why no trading signals?")
print("=" * 60)

try:
    client = ClobClient(CLOB_HOST, key=PRIVATE_KEY, chain_id=CHAIN_ID, signature_type=2)
    print("[OK] CLOB client initialized")
except Exception as e:
    print(f"[ERROR] CLOB client failed: {e}")
    sys.exit(1)

try:
    url = "https://gamma-api.polymarket.com/markets?limit=100"
    resp = requests.get(url, params={"closed": "false"}, proxies={'http': 'http://127.0.0.1:15236', 'https': 'http://127.0.0.1:15236'}, timeout=30)
    if resp.status_code == 200:
        data = resp.json()
        markets = data if isinstance(data, list) else data.get('markets', [])
        print(f"\n[OK] Got {len(markets)} active markets")

        # 放宽搜索条件，查找BTC市场（不限时间）
        btc_markets = [m for m in markets if 'bitcoin' in m.get('question', '').lower() or 'btc' in m.get('question', '').lower()]

        # 如果还是找不到，显示所有市场
        if not btc_markets:
            print("[WARN] No BTC markets found, showing all markets:")
            for i, market in enumerate(markets[:10]):
                print(f"  {i+1}. {market.get('question', 'N/A')[:60]}")
        else:
            print(f"[OK] Found {len(btc_markets)} BTC markets (any timeframe)")

        if btc_markets:
            print(f"[OK] Found {len(btc_markets)} BTC 15min markets")

            for i, market in enumerate(btc_markets[:3]):
                print(f"\n--- Market {i+1} ---")
                question = market.get('question', 'N/A')
                if question:
                    print(f"Question: {question[:80]}...")

                outcome_prices = market.get('outcomePrices', [])
                if isinstance(outcome_prices, str):
                    outcome_prices = json.loads(outcome_prices)

                if outcome_prices and len(outcome_prices) >= 2:
                    yes_price = float(outcome_prices[0])
                    no_price = float(outcome_prices[1])

                    print(f"YES: {yes_price:.4f}")
                    print(f"NO: {no_price:.4f}")

                    if yes_price > 0.80:
                        print("[FILTER] YES > 0.80 - SKIPPED")
                    elif no_price > 0.80:
                        print("[FILTER] NO > 0.80 - SKIPPED")
                    else:
                        print("[OK] Price filter passed")
                else:
                    print("[WARN] No price data available")
        else:
            print("[ERROR] No BTC 15min markets found")
    else:
        print(f"[ERROR] HTTP {resp.status_code}: {resp.text[:200]}")

except Exception as e:
    print(f"[ERROR] {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
