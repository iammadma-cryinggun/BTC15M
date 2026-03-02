#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BTC 15分钟自动交易系统 - 轻量级启动脚本
选择运行V5（REST轮询）或V6（WebSocket高频）

自动启动Oracle（后台线程），无需手动操作
"""

import sys
import os
import subprocess
import threading
import time


def print_banner():
    print("=" * 70)
    print("  BTC 15分钟自动交易系统 - v2_experiment 版本")
    print("  最新特性: 全时段入场 + 止盈止损 + 25规则全激活")
    print("=" * 70)
    print()


def start_oracle_background():
    """
    后台启动 binance_oracle.py
    返回: (process, log_file)
    """
    print("[1/2] 启动 Binance Oracle（CVD数据源）...")

    # 检查binance_oracle.py是否存在
    if not os.path.exists('binance_oracle.py'):
        print(f"  ❌ 错误: 找不到 binance_oracle.py")
        print(f"  📁 当前目录: {os.getcwd()}")
        return None, None

    try:
        # 创建日志文件
        oracle_log = open('oracle.log', 'w')

        # 启动Oracle进程（后台运行）
        oracle_process = subprocess.Popen(
            [sys.executable, 'binance_oracle.py'],
            stdout=oracle_log,
            stderr=subprocess.STDOUT
        )

        print(f"  ✅ Oracle进程已启动 (PID: {oracle_process.pid})")
        print(f"  📄 日志文件: oracle.log")
        print()

        # 等待Oracle初始化（10秒）
        print("[等待] 让Oracle初始化（10秒）...")
        time.sleep(10)

        # 检查进程状态
        if oracle_process.poll() is not None:
            print(f"  ❌ 错误: Oracle进程意外退出！")
            print(f"  📄 请检查 oracle.log 了解详情")
            return None, None

        # 检查信号文件
        if os.path.exists('oracle_signal.json'):
            import json
            try:
                with open('oracle_signal.json', 'r') as f:
                    signal = json.load(f)
                cvd_5m = signal.get('cvd_5m', 0.0)
                print(f"  ✅ 信号文件正常: CVD_5m={cvd_5m:+.0f}")
            except:
                print(f"  ⚠️  信号文件存在但解析失败")
        else:
            print(f"  ⚠️  信号文件尚未生成（可能还在初始化）")

        print()
        return oracle_process, oracle_log

    except Exception as e:
        print(f"  ❌ 启动Oracle失败: {e}")
        return None, None


# 全局变量：Oracle进程和日志文件
oracle_process = None
oracle_log = None


def cleanup_oracle():
    """清理Oracle进程"""
    global oracle_process, oracle_log

    if oracle_process:
        try:
            print()
            print("=" * 70)
            print("[STOP] 正在停止 Oracle 进程...")
            print("=" * 70)

            oracle_process.terminate()
            try:
                oracle_process.wait(timeout=5)
                print(f"  ✅ Oracle进程已停止")
            except:
                oracle_process.kill()
                print(f"  ✅ Oracle进程已强制停止")

        except Exception as e:
            print(f"  ⚠️  停止Oracle时出错: {e}")

    if oracle_log:
        try:
            oracle_log.close()
        except:
            pass


def main():
    print_banner()

    # 步骤1: 后台启动Oracle
    global oracle_process, oracle_log
    oracle_process, oracle_log = start_oracle_background()

    # 注册信号处理（确保Ctrl+C时清理Oracle）
    import signal
    def signal_handler(signum, frame):
        print()
        cleanup_oracle()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 步骤2: 启动交易引擎
    print("[2/2] 启动交易引擎...")
    print("=" * 70)
    print()

    # 检查是否有命令行参数
    if len(sys.argv) > 1:
        version = sys.argv[1].upper()
        if version == "V2":
            print("[INFO] 启动 v2_experiment (最新版本)...")
            import v2_experiment.auto_trader_ankr
            bot = v2_experiment.auto_trader_ankr.AutoTraderV5()
            bot.run()
            return
        elif version == "V5":
            print("[INFO] 启动 V5 (稳定版本)...")
            import auto_trader_ankr
            bot = auto_trader_ankr.AutoTraderV5()
            bot.run()
            return
        elif version == "V6":
            print("[INFO] 启动 V6 (WebSocket高频模式)...")
            import v6_hft_engine
            asyncio = v6_hft_engine.asyncio
            engine = v6_hft_engine.V6HFTEngine()
            asyncio.run(engine.run())
            return

    # 没有参数时，默认运行 v2_experiment
    print("[INFO] 启动 v2_experiment (最新版本)...")
    print("[提示] Oracle已自动在后台运行，无需手动操作")
    print()
    try:
        import v2_experiment.auto_trader_ankr
        bot = v2_experiment.auto_trader_ankr.AutoTraderV5()
        bot.run()

    except KeyboardInterrupt:
        print("\n\n[STOP] 收到停止信号，正在退出...")
        cleanup_oracle()
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] 启动失败: {e}")
        cleanup_oracle()
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
