#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完全模拟主程序的导入和初始化"""
import os
import sys

# 设置代理（必须在 load_dotenv 之前）
os.environ['HTTP_PROXY'] = 'http://127.0.0.1:15236'
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:15236'

print("=" * 70)
print("Exact Simulation of Main Program Import")
print("=" * 70)

# 1. Load .env
print("\n[1/4] Loading .env file...")
from dotenv import load_dotenv
load_dotenv()
print("  [OK] load_dotenv() executed")

# 2. Check PRIVATE_KEY
print("\n[2/4] Checking PRIVATE_KEY...")
PRIVATE_KEY = os.getenv('PRIVATE_KEY', '')
print(f"  PRIVATE_KEY exists: {bool(PRIVATE_KEY)}")
print(f"  PRIVATE_KEY length: {len(PRIVATE_KEY)}")
if not PRIVATE_KEY:
    print("  [ERROR] PRIVATE_KEY is empty!")
    sys.exit(1)

# 3. Import CLOB SDK
print("\n[3/4] Importing CLOB SDK...")
CLOB_AVAILABLE = False
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, BalanceAllowanceParams, AssetType, OrderOptions
    from py_clob_client.order_builder.constants import BUY, SELL
    CLOB_AVAILABLE = True
    print("  [OK] CLOB SDK imported")
    print(f"  CLOB_AVAILABLE = {CLOB_AVAILABLE}")
except ImportError as e:
    print(f"  [ERROR] Import failed: {e}")
    print(f"  CLOB_AVAILABLE = {CLOB_AVAILABLE}")
    sys.exit(1)

# 4. Create CONFIG (exact copy from main program)
print("\n[4/4] Creating CONFIG...")
CONFIG = {
    'clob_host': 'https://clob.polymarket.com',
    'gamma_host': 'https://gamma-api.polymarket.com',
    'chain_id': 137,
    'wallet_address': '0xd5d037390c6216CCFa17DFF7148549B9C2399BD3',
    'private_key': os.getenv('PRIVATE_KEY', ''),
    'proxy': {'http': 'http://127.0.0.1:15236', 'https': 'http://127.0.0.1:15236'},
}
print("  [OK] CONFIG created")

# 5. Check the exact condition from init_clob_client()
print("\n" + "=" * 70)
print("Checking condition from init_clob_client():")
print("=" * 70)
print(f"CONFIG['private_key'] = {bool(CONFIG['private_key'])}")
print(f"CLOB_AVAILABLE = {CLOB_AVAILABLE}")
print(f"\nCondition: if not CONFIG['private_key'] or not CLOB_AVAILABLE")
print(f"Result: {not CONFIG['private_key'] or not CLOB_AVAILABLE}")

if not CONFIG['private_key'] or not CLOB_AVAILABLE:
    print("\n[PREDICTION] Will print: '[INFO] Signal mode only (no CLOB client)'")
    print("[INFO] Signal mode only (no CLOB client)")
    sys.exit(1)
else:
    print("\n[PREDICTION] Will print: '[CLOB] Initializing...'")
    print("\n[CLOB] Initializing...")

print("\n" + "=" * 70)
print("SUCCESS! All checks passed")
print("=" * 70)
