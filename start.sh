#!/usr/bin/env python3
"""
Zeabur启动脚本（Python版，避免bash权限问题）
"""
import os
import sys
import subprocess

print("=" * 50)
print("  BTC 15min Trading Bot - Starting")
print("=" * 50)
print("")

# 检查Python版本
print("[INFO] Python version:")
print(sys.version)
print("")

# 检查环境变量
print("[INFO] Checking environment variables...")
private_key = os.getenv('PRIVATE_KEY')
if not private_key:
    print("[ERROR] PRIVATE_KEY not set!")
    print("        Please configure this in Zeabur environment variables")
    sys.exit(1)
else:
    print(f"[OK] PRIVATE_KEY is set ({len(private_key)} chars)")

print(f"[INFO] TELEGRAM_ENABLED: {os.getenv('TELEGRAM_ENABLED', 'false')}")
print(f"[INFO] HTTP_PROXY: {os.getenv('HTTP_PROXY', '(none)')}")
print("")

# 检查主文件是否存在
if not os.path.exists('auto_trader_ankr.py'):
    print("[ERROR] auto_trader_ankr.py not found!")
    print(f"        Current directory: {os.getcwd()}")
    print(f"        Files in directory: {os.listdir('.')}")
    sys.exit(1)
else:
    print("[OK] auto_trader_ankr.py found")

print("")
print("[INFO] Starting trading bot...")
print("=" * 50)
print("")

# 直接运行主程序（使用当前Python解释器）
os.execv(sys.executable, [sys.executable, 'auto_trader_ankr.py'])
