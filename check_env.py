#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查环境变量加载"""
import os
from dotenv import load_dotenv

print("Before load_dotenv():")
print(f"  PRIVATE_KEY from os.getenv: {os.getenv('PRIVATE_KEY', 'NOT FOUND')}")

load_dotenv()

print("\nAfter load_dotenv():")
print(f"  PRIVATE_KEY from os.getenv: {os.getenv('PRIVATE_KEY', 'NOT FOUND')}")

if os.getenv('PRIVATE_KEY'):
    key = os.getenv('PRIVATE_KEY')
    print(f"  Length: {len(key)}")
    print(f"  First 10: {key[:10]}")
    print(f"  Last 6: {key[-6:]}")
else:
    print("  [ERROR] PRIVATE_KEY is still empty!")

# 模拟 CONFIG
CONFIG = {'private_key': os.getenv('PRIVATE_KEY', '')}
print(f"\nCONFIG['private_key'] exists: {bool(CONFIG['private_key'])}")
print(f"CONFIG['private_key'] length: {len(CONFIG['private_key']) if CONFIG['private_key'] else 0}")
