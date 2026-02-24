#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
启动选择脚本
选择运行V5（REST轮询）或V6（WebSocket高频）
"""

import sys
import os


def print_banner():
    print("=" * 70)
    print("  BTC 15分钟自动交易系统")
    print("  V5: REST轮询模式 (稳定)")
    print("  V6: WebSocket高频模式 (实验性)")
    print("=" * 70)
    print()


def main():
    print_banner()

    # 检查是否有命令行参数
    if len(sys.argv) > 1:
        version = sys.argv[1].upper()
        if version == "V5":
            print("[INFO] 启动 V5 (REST轮询模式)...")
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

    # 没有参数时，让用户选择
    print("请选择版本:")
    print("  1. V5 (REST轮询) - 稳定版本，适合生产环境")
    print("  2. V6 (WebSocket) - 实验性版本，更快但需要测试")
    print("  3. 测试WebSocket连接")
    print()

    try:
        choice = input("输入选择 [1/2/3] (默认:1): ").strip()

        if choice == "2":
            print("\n[INFO] 启动 V6 (WebSocket高频模式)...")
            import v6_hft_engine
            asyncio = v6_hft_engine.asyncio
            engine = v6_hft_engine.V6HFTEngine()
            asyncio.run(engine.run())

        elif choice == "3":
            print("\n[INFO] 测试WebSocket连接...")
            import test_websocket
            asyncio = test_websocket.asyncio
            asyncio.run(test_websocket.test_polymarket_websocket())

        else:  # 默认V5
            print("\n[INFO] 启动 V5 (REST轮询模式)...")
            import auto_trader_ankr
            bot = auto_trader_ankr.AutoTraderV5()
            bot.run()

    except KeyboardInterrupt:
        print("\n\n[STOP] 收到停止信号，正在退出...")
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] 启动失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
