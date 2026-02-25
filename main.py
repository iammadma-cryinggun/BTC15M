#!/usr/bin/env python3
"""
BTC 15分钟自动交易系统 - 主入口
Zeabur部署入口点 - 同时启动Oracle和交易机器人
"""

import os
import sys
import subprocess
import time

print("=" * 70)
print("  BTC 15min Trading System - Starting")
print("  Deployed on Zeabur")
print("=" * 70)
print("")

# 检查环境变量
private_key = os.getenv('PRIVATE_KEY')
if not private_key:
    print("[ERROR] PRIVATE_KEY not set!")
    print("        Please configure PRIVATE_KEY in Zeabur environment variables")
    sys.exit(1)

print(f"[OK] PRIVATE_KEY configured ({len(private_key)} chars)")
print(f"[INFO] TELEGRAM_ENABLED: {os.getenv('TELEGRAM_ENABLED', 'false')}")
print("")

# 检查文件是否存在
if not os.path.exists('binance_oracle.py'):
    print("[ERROR] binance_oracle.py not found!")
    sys.exit(1)

if not os.path.exists('auto_trader_ankr.py'):
    print("[ERROR] auto_trader_ankr.py not found!")
    sys.exit(1)

# 清理可能存在的旧oracle.log
if os.path.exists('oracle.log'):
    os.remove('oracle.log')

print("[1/2] 启动 Binance Oracle (后台)...")
# 启动Oracle，后台运行
oracle_log = open('oracle.log', 'w')
oracle_process = subprocess.Popen(
    [sys.executable, 'binance_oracle.py'],
    stdout=oracle_log,
    stderr=subprocess.STDOUT
)
print(f"     PID: {oracle_process.pid}")
print("     日志: oracle.log")
print("")

# 等待Oracle初始化
print("[等待] Oracle系统初始化中（10秒）...")
time.sleep(10)

# 检查Oracle进程
if oracle_process.poll() is not None:
    print("[ERROR] Oracle进程已退出！")
    print("=== oracle.log (最后20行) ===")
    with open('oracle.log', 'r') as f:
        lines = f.readlines()
        for line in lines[-20:]:
            print(line.rstrip())
    sys.exit(1)

print(f"[OK] Oracle运行正常 (PID: {oracle_process.pid})")

# 检查信号文件
if os.path.exists('oracle_signal.json'):
    import json
    with open('oracle_signal.json', 'r') as f:
        signal_data = json.load(f)
    ut_hull = signal_data.get('ut_hull_trend', 'UNKNOWN')
    print(f"[OK] 信号文件: score={signal_data.get('signal_score', 0):.2f}, UT+Hull={ut_hull}")
else:
    print("[WARN] oracle_signal.json 尚未生成（可能正在初始化K线）")

print("")
print("[2/2] 启动交易机器人 (前台)...")
print("=" * 70)
print("")

# 启动交易机器人（前台运行）
try:
    process = subprocess.Popen([sys.executable, 'auto_trader_ankr.py'])
    returncode = process.wait()
    print()
    print("=" * 70)
    print(f"[STOP] 交易机器人已停止 (退出码: {returncode})")
    print("=" * 70)
    print()
    print("[清理] 正在清理Oracle进程...")
    try:
        oracle_process.terminate()
        oracle_process.wait(timeout=5)
        print(f"[OK] Oracle进程已清理")
    except:
        oracle_process.kill()
        print("[OK] Oracle进程已强制终止")
except KeyboardInterrupt:
    print()
    print("=" * 70)
    print("[STOP] 收到中断信号，清理所有进程...")
    try:
        oracle_process.terminate()
        oracle_process.wait(timeout=5)
        print("[OK] Oracle进程已清理")
    except:
        oracle_process.kill()
        print("[OK] Oracle进程已强制终止")
    print("=" * 70)
