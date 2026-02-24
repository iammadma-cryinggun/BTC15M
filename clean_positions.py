#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清理持仓和数据库工具"""

import os
import sqlite3
from dotenv import load_dotenv

os.environ['HTTP_PROXY'] = 'http://127.0.0.1:15236'
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:15236'

load_dotenv()

from py_clob_client.client import ClobClient

PRIVATE_KEY = os.getenv('PRIVATE_KEY')
CLOB_HOST = 'https://clob.polymarket.com'
CHAIN_ID = 137

print("=" * 60)
print("持仓清理工具")
print("=" * 60)

try:
    client = ClobClient(CLOB_HOST, key=PRIVATE_KEY, chain_id=CHAIN_ID, signature_type=2)
    print("[OK] CLOB客户端已连接\n")
except Exception as e:
    print(f"[ERROR] CLOB客户端连接失败: {e}")
    exit(1)

# 1. 检查实际持仓
print("=== 1. 检查Polymarket实际持仓 ===")
try:
    balances = client.get_balance_types()
    if balances:
        print(f"找到 {len(balances)} 种Token余额:")
        for token_id, amount in balances.items():
            if float(amount) > 0:
                print(f"  Token ID: {token_id}, 余额: {amount}")
    else:
        print("没有持仓余额")
except Exception as e:
    print(f"查询余额失败: {e}")

print()

# 2. 检查数据库
print("=== 2. 检查本地数据库 ===")
db_path = 'trading_bot.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()

    if not tables:
        print("数据库中没有表")
    else:
        for table in tables:
            table_name = table[0]
            cursor.execute(f'SELECT COUNT(*) FROM {table_name}')
            count = cursor.fetchone()[0]
            print(f"表 {table_name}: {count} 条记录")

            if count > 0 and table_name == 'positions':
                cursor.execute(f'SELECT id, side, size, entry_token_price, status FROM {table_name}')
                positions = cursor.fetchall()
                print("  持仓详情:")
                for pos in positions:
                    print(f"    ID={pos[0]}, {pos[1]} {pos[2]}份 @ {pos[3]}, 状态={pos[4]}")

    conn.close()
else:
    print("数据库文件不存在")

print()

# 3. 清理选项
print("=== 3. 清理选项 ===")
print("请选择操作:")
print("1. 重置数据库（删除所有表，重新初始化）")
print("2. 清空所有持仓记录")
print("3. 仅退出（不执行清理）")

choice = input("\n请输入选项 (1/2/3): ").strip()

if choice == '1':
    print("\n[操作] 重置数据库...")
    if os.path.exists(db_path):
        os.remove(db_path)
        print("[OK] 数据库已删除，程序运行时会自动重建")
    else:
        print("[SKIP] 数据库不存在")

elif choice == '2':
    print("\n[操作] 清空持仓记录...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM positions")
    conn.commit()
    print(f"[OK] 已删除 {cursor.rowcount} 条持仓记录")
    conn.close()

else:
    print("\n[SKIP] 未执行清理")

print("\n" + "=" * 60)
print("清理完成")
print("=" * 60)
