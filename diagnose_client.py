#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断 CLOB 客户端初始化问题"""
import os
import sys

# 设置代理
os.environ['HTTP_PROXY'] = 'http://127.0.0.1:15236'
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:15236'

from dotenv import load_dotenv
load_dotenv()

print("=" * 70)
print("CLOB Client Diagnostic Tool")
print("=" * 70)

# 检查环境变量
print("\n[1/5] Checking environment variables...")
PRIVATE_KEY = os.getenv('PRIVATE_KEY')
WALLET_ADDRESS = os.getenv('WALLET_ADDRESS')

if not PRIVATE_KEY:
    print("  [ERROR] PRIVATE_KEY not found in .env")
    sys.exit(1)
else:
    print(f"  [OK] PRIVATE_KEY: {PRIVATE_KEY[:10]}...{PRIVATE_KEY[-6:]}")

if not WALLET_ADDRESS:
    print("  [WARN] WALLET_ADDRESS not found in .env")
else:
    print(f"  [OK] WALLET_ADDRESS: {WALLET_ADDRESS}")

# 检查代理
print("\n[2/5] Checking proxy connection...")
try:
    import requests
    resp = requests.get(
        "https://clob.polymarket.com",
        proxies={'http': 'http://127.0.0.1:15236', 'https': 'http://127.0.0.1:15236'},
        timeout=10
    )
    print(f"  [OK] Proxy working! Status: {resp.status_code}")
except Exception as e:
    print(f"  [ERROR] Proxy failed: {e}")
    print("  Please check your VPN/Proxy is running on port 15236")
    sys.exit(1)

# 初始化 SDK
print("\n[3/5] Initializing ClobClient...")
try:
    from py_clob_client.client import ClobClient
    print("  [OK] SDK imported")
except Exception as e:
    print(f"  [ERROR] SDK import failed: {e}")
    sys.exit(1)

# 创建临时客户端
print("\n[4/5] Creating temp client...")
try:
    CLOB_HOST = 'https://clob.polymarket.com'
    CHAIN_ID = 137

    temp_client = ClobClient(
        CLOB_HOST,
        key=PRIVATE_KEY,
        chain_id=CHAIN_ID,
        signature_type=2,
        funder=WALLET_ADDRESS
    )
    print("  [OK] Temp client created")
except Exception as e:
    print(f"  [ERROR] Temp client failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 申请 API 凭证
print("\n[5/5] Deriving API credentials...")
try:
    api_creds = temp_client.create_or_derive_api_creds()
    print("  [OK] API credentials derived")
    print(f"       Type: {type(api_creds)}")
except Exception as e:
    print(f"  [ERROR] API credentials failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 创建正式客户端
print("\n[BONUS] Creating final client...")
try:
    client = ClobClient(
        CLOB_HOST,
        key=PRIVATE_KEY,
        chain_id=CHAIN_ID,
        creds=api_creds,
        signature_type=2,
        funder=WALLET_ADDRESS
    )
    print("  [OK] Final client created")
except Exception as e:
    print(f"  [ERROR] Final client failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 70)
print("✅ ALL TESTS PASSED!")
print("=" * 70)
print("\nYour CLOB client is working correctly.")
print("You can now run: python auto_trader_ankr.py")
