#!/usr/bin/env python3
"""
Zeabur v2_experiment V6 启动脚本（WebSocket实时价格 + 25规则）
先启动 binance_oracle.py（后台），再启动 v2_experiment/v6_hft_engine.py（前台）
"""
import os
import sys
import subprocess
import time

print("=" * 70)
print("  BTC 15min - v2_experiment V6 版本启动中")
print("  特性: WebSocket实时价格 | 全时段入场 | 止盈止损 | 25规则")
print("=" * 70)
print()

# 检查文件
if not os.path.exists('binance_oracle.py'):
    print("[ERROR] binance_oracle.py not found!")
    sys.exit(1)

if not os.path.exists('v2_experiment/v6_hft_engine.py'):
    print("[ERROR] v2_experiment/v6_hft_engine.py not found!")
    sys.exit(1)

# 清理可能存在的旧oracle.log
if os.path.exists('oracle.log'):
    os.remove('oracle.log')

print("[1/2] 启动币安先知Oracle（后台运行）...")
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
print("[等待] 让Oracle系统初始化（10秒）...")
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
        signal = json.load(f)
    print(f"[OK] 信号文件已生成: score={signal.get('signal_score', 0):.2f}")
else:
    print("[WARN] oracle_signal.json 尚未生成（可能正在初始化）")

print()
print("[2/2] 启动 v2_experiment V6 交易引擎（WebSocket + 25规则）...")
print("=" * 70)
print()

# 定义清理函数
def cleanup(signum=None, frame=None):
    print()
    print("=" * 70)
    print("[STOP] 收到停止信号，清理进程...")
    try:
        oracle_process.terminate()
        oracle_process.wait(timeout=5)
        print(f"[OK] Oracle进程 (PID: {oracle_process.pid}) 已清理")
    except:
        oracle_process.kill()
        print("[OK] Oracle进程已强制终止")
    print("=" * 70)
    sys.exit(0)

# 注册信号处理
import signal
signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

# 启动 v2_experiment V6（前台运行）
try:
    # 切换到 v2_experiment 目录并启动 V6
    os.chdir('v2_experiment')
    process = subprocess.Popen([sys.executable, 'v6_hft_engine.py'])
    process.wait()
except KeyboardInterrupt:
    cleanup()
