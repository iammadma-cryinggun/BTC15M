#!/usr/bin/env python3
"""
BTC 15分钟自动交易系统 - 主入口
Zeabur部署入口点 - V6 WebSocket高频引擎
"""

import os
import sys

print("=" * 70)
print("  BTC 15min V6 HFT Engine - WebSocket Real-time Trading")
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

# 导入并运行V6引擎
try:
    # 检查依赖
    try:
        import asyncio
        import websockets
        print("[OK] asyncio and websockets available")
    except ImportError as e:
        print(f"[ERROR] Missing dependency: {e}")
        print("[INFO] Please run: pip install websockets>=11.0.3")
        sys.exit(1)

    # 检查py_clob_client是否可用
    try:
        from py_clob_client.client import ClobClient
        CLOB_AVAILABLE = True
        print("[OK] py-clob-client available - Trading ENABLED")
    except ImportError:
        CLOB_AVAILABLE = False
        print("[WARN] py-clob-client NOT available - Trading DISABLED")
        print("[INFO] Bot will run in SIGNAL-ONLY mode")
        print("")

    # 导入V6引擎
    from v6_hft_engine import V6HFTEngine

    print("[INFO] Initializing V6 HFT Engine...")
    print("[INFO] WebSocket + V5 Complete Risk Control")
    print("")

    # 创建并运行V6引擎
    engine = V6HFTEngine()

    if not CLOB_AVAILABLE:
        print("[INFO] Signal-only mode activated")

    # 运行异步引擎
    asyncio.run(engine.run())

except KeyboardInterrupt:
    print("\n[INFO] Bot stopped by user")
    sys.exit(0)
except Exception as e:
    print(f"\n[ERROR] Bot crashed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
