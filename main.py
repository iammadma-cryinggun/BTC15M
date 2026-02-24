#!/usr/bin/env python3
"""
BTC 15分钟自动交易系统 - 主入口
Zeabur部署入口点
"""

import os
import sys

print("=" * 70)
print("  BTC 15min V5 Professional - Auto Trading System")
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

# 导入并运行主程序
try:
    # 导入主交易程序
    from auto_trader_ankr import AutoTraderV5

    print("[INFO] Initializing trading bot...")
    print("")

    # 创建并运行交易机器人
    bot = AutoTraderV5()
    bot.run()

except KeyboardInterrupt:
    print("\n[INFO] Bot stopped by user")
    sys.exit(0)
except Exception as e:
    print(f"\n[ERROR] Bot crashed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
