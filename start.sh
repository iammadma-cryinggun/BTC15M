#!/usr/bin/env python3
"""
Zeabur双核架构启动脚本
同时启动 binance_oracle.py 和 auto_trader_ankr.py
"""
import os
import sys
import subprocess
import time

print("=" * 70)
print("  BTC 15min 双核架构 - 启动中")
print("=" * 70)
print()

# 检查文件
if not os.path.exists('binance_oracle.py'):
    print("[ERROR] binance_oracle.py not found!")
    sys.exit(1)

if not os.path.exists('auto_trader_ankr.py'):
    print("[ERROR] auto_trader_ankr.py not found!")
    sys.exit(1)

# 清理可能存在的旧oracle.log
if os.path.exists('oracle.log'):
    os.remove('oracle.log')

print("[1/2] 启动币安先知 (后台)...")
# 启动Oracle，后台运行
oracle_log = open('oracle.log', 'w')
oracle_process = subprocess.Popen(
    [sys.executable, 'binance_oracle.py'],
    stdout=oracle_log,
    stderr=subprocess.STDOUT
)
print(f"     PID: {oracle_process.pid}")
print("     日志: oracle.log")
print()

# 等待Oracle初始化
print("[等待] 让先知系统初始化（10秒）...")
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
    print(f"[OK] 信号文件已生成: score={signal_data.get('signal_score', 0):.2f}")
else:
    print("[WARN] oracle_signal.json 尚未生成（可能正在初始化）")

print()
print("[2/2] 启动交易机器人 (前台)...")
print("=" * 70)
print()

# 🚀 移除信号处理（Zeabur容器环境中会报错）
# Zeabur有自己的信号管理机制

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
