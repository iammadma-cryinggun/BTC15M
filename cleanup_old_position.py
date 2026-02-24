#!/usr/bin/env python3
import sqlite3
from datetime import datetime

conn = sqlite3.connect('btc_15min_auto_trades.db')
cursor = conn.cursor()

# 关闭持仓 #45
cursor.execute("""
    UPDATE positions
    SET status = 'closed',
        exit_reason = 'MANUAL_CLEANUP',
        exit_time = ?
    WHERE id = 45
""", (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),))

conn.commit()
conn.close()

print("[OK] 已手动关闭旧持仓 #45")
print("现在程序不会再监控这个持仓了")
