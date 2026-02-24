#!/usr/bin/env python3
import os
from dotenv import load_dotenv
import requests

os.environ['HTTP_PROXY'] = 'http://127.0.0.1:15236'
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:15236'

print("Checking for BTC Up or Down markets...")

try:
    # 增加limit获取更多市场
    url = "https://gamma-api.polymarket.com/markets?limit=500&closed=false"
    resp = requests.get(url, proxies={'http': 'http://127.0.0.1:15236', 'https': 'http://127.0.0.1:15236'}, timeout=30)

    if resp.status_code == 200:
        data = resp.json()
        markets = data if isinstance(data, list) else data.get('markets', [])
        print(f"Got {len(markets)} active markets")

        # 搜索所有包含"bitcoin"的市场
        all_btc = []
        for m in markets:
            q = m.get('question', '').lower()
            if 'bitcoin' in q or 'btc' in q:
                all_btc.append(m)

        print(f"\nFound {len(all_btc)} BTC markets:")
        print("=" * 80)

        for i, m in enumerate(all_btc):
            question = m.get('question', '')
            # 显示市场名称
            print(f"{i+1}. {question}")

            # 检查是否包含时间信息
            if '15 min' in question.lower() or '15minute' in question.lower():
                print(f"   ^^^ This is a 15-minute market!")

        print("\n" + "=" * 80)
        print(f"Total: {len(all_btc)} BTC markets")

    else:
        print(f"Error: HTTP {resp.status_code}")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
