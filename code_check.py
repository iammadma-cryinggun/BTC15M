#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完整代码检查 - 验证所有方法调用"""
import os
import sys

print("=" * 70)
print("Code Verification Checklist")
print("=" * 70)

# 1. 检查导入
print("\n[1/5] Checking imports...")
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, BalanceAllowanceParams, AssetType, CreateOrderOptions
    from py_clob_client.order_builder.constants import BUY, SELL
    print("  All imports: OK")
except ImportError as e:
    print(f"  Import ERROR: {e}")
    sys.exit(1)

# 2. 检查 SDK 方法
print("\n[2/5] Checking SDK methods...")
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
    'get_headers': hasattr(client, 'get_headers'),
}

all_ok = True
for method, exists in methods.items():
    status = "OK" if exists else "ERROR - NOT FOUND"
    print(f"  {method}: {status}")
    if not exists:
        all_ok = False

if not all_ok:
    sys.exit(1)

# 3. 检查数据库列名
print("\n[3/5] Checking database columns...")
import sqlite3
conn = sqlite3.connect('btc_15min_auto_trades.db')
cursor = conn.cursor()
cursor.execute('PRAGMA table_info(positions)')
columns = [col[1] for col in cursor.fetchall()]

required_columns = ['id', 'token_id', 'side', 'status', 'entry_time']
for col in required_columns:
    if col in columns:
        print(f"  {col}: OK")
    else:
        print(f"  {col}: ERROR - NOT FOUND")
conn.close()

# 4. 检查 CreateOrderOptions 参数
print("\n[4/5] Checking CreateOrderOptions...")
try:
    options = CreateOrderOptions(tick_size="0.01")
    print("  CreateOrderOptions(tick_size): OK")
except Exception as e:
    print(f"  CreateOrderOptions ERROR: {e}")

# 5. 检查 BalanceAllowanceParams 参数
print("\n[5/5] Checking BalanceAllowanceParams...")
try:
    from py_clob_client.clob_types import BalanceAllowanceParams
    params = BalanceAllowanceParams(
        asset_type=AssetType.CONDITIONAL,
        token_id="test",
        signature_type=2
    )
    print("  BalanceAllowanceParams: OK")
except Exception as e:
    print(f"  BalanceAllowanceParams ERROR: {e}")

print("\n" + "=" * 70)
print("Verification Complete!")
print("=" * 70)
