#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最终代码验证"""
import os
import sys

print("=" * 70)
print("Final Code Verification")
print("=" * 70)

# 1. 导入检查
print("\n[1/4] Import check...")
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, BalanceAllowanceParams, AssetType, CreateOrderOptions
    from py_clob_client.order_builder.constants import BUY, SELL
    print("  All imports: OK")
except ImportError as e:
    print(f"  Import ERROR: {e}")
    sys.exit(1)

# 2. 使用的核心方法
print("\n[2/4] Core SDK methods check...")
from dotenv import load_dotenv
load_dotenv()

client = ClobClient(
    'https://clob.polymarket.com',
    key=os.getenv('PRIVATE_KEY'),
    chain_id=137,
    signature_type=2
)

methods = {
    'create_and_post_order': hasattr(client, 'create_and_post_order'),
    'get_order': hasattr(client, 'get_order'),
    'cancel': hasattr(client, 'cancel'),
    'get_balance_allowance': hasattr(client, 'get_balance_allowance'),
}

all_ok = True
for method, exists in methods.items():
    status = "OK" if exists else "ERROR"
    print(f"  {method}: {status}")
    if not exists:
        all_ok = False

# 3. 数据库列名
print("\n[3/4] Database columns check...")
import sqlite3
conn = sqlite3.connect('btc_15min_auto_trades.db')
cursor = conn.cursor()
cursor.execute('PRAGMA table_info(positions)')
columns = [col[1] for col in cursor.fetchall()]

required = ['id', 'token_id', 'side', 'status', 'entry_time']
for col in required:
    if col in columns:
        print(f"  {col}: OK")
    else:
        print(f"  {col}: ERROR - NOT FOUND")
        all_ok = False
conn.close()

# 4. 参数类
print("\n[4/4] Parameter classes check...")
try:
    opts = CreateOrderOptions(tick_size="0.01")
    print("  CreateOrderOptions: OK")

    params = BalanceAllowanceParams(
        asset_type=AssetType.CONDITIONAL,
        token_id="test",
        signature_type=2
    )
    print("  BalanceAllowanceParams: OK")
except Exception as e:
    print(f"  ERROR: {e}")
    all_ok = False

print("\n" + "=" * 70)
if all_ok:
    print("SUCCESS! All checks passed.")
else:
    print("FAILED! Some checks did not pass.")
print("=" * 70)

sys.exit(0 if all_ok else 1)
