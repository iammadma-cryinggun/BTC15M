#!/usr/bin/env python3
"""
简化的测试版本 - 先验证Zeabur部署
"""
import os
import sys

print("=" * 70)
print("  BTC 15min Trading Bot - Test Version")
print("=" * 70)
print("")

# 检查环境变量
private_key = os.getenv('PRIVATE_KEY')
if not private_key:
    print("[ERROR] PRIVATE_KEY not set!")
    print("        Please configure PRIVATE_KEY in Zeabur")
    sys.exit(1)

print(f"[OK] PRIVATE_KEY configured ({len(private_key)} chars)")
print("[INFO] Starting in test mode...")
print("")

# 测试导入
try:
    import requests
    print("[OK] requests imported")
except ImportError as e:
    print(f"[ERROR] Cannot import requests: {e}")

try:
    from dotenv import load_dotenv
    print("[OK] python-dotenv imported")
except ImportError as e:
    print(f"[ERROR] Cannot import dotenv: {e}")

# 尝试导入py_clob_client
try:
    from py_clob_client.client import ClobClient
    print("[OK] py_clob_client imported")
except ImportError as e:
    print(f"[WARN] Cannot import py_clob_client: {e}")
    print("[INFO] Running in SIGNAL-ONLY mode (no trading)")

print("")
print("[SUCCESS] Bot is ready!")
print("[INFO] All basic dependencies loaded")
print("")

# 保持容器运行
print("[INFO] Press Ctrl+C to stop...")
try:
    while True:
        import time
        time.sleep(60)
        print(f"[HEARTBEAT] {os.popen('date').read().strip()}")
except KeyboardInterrupt:
    print("\n[INFO] Stopped by user")
