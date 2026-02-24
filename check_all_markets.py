#!/usr/bin/env python3
import os
import requests

os.environ['HTTP_PROXY'] = 'http://127.0.0.1:15236'
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:15236'

print("Checking all active markets...")

try:
    url = "https://gamma-api.polymarket.com/markets?limit=100&closed=false"
    resp = requests.get(url, proxies={'http': 'http://127.0.0.1:15236', 'https': 'http://127.0.0.1:15236'}, timeout=30)

    if resp.status_code == 200:
        data = resp.json()
        markets = data if isinstance(data, list) else data.get('markets', [])
        print(f"Total: {len(markets)} active markets\n")

        # 显示前20个市场
        print("First 20 markets:")
        print("-" * 80)
        for i, m in enumerate(markets[:20]):
            question = m.get('question', '')
            slug = m.get('slug', '')
            print(f"{i+1}. [{slug}] {question[:70]}")

    else:
        print(f"Error: HTTP {resp.status_code}")

except Exception as e:
    print(f"Error: {e}")
