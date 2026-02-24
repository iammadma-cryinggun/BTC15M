#!/usr/bin/env python3
import sqlite3

DB_PATH = 'btc_15min_auto_trades.db'
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# 关闭所有旧的open持仓（清除无效订单ID）
cursor.execute("UPDATE positions SET status='closed', take_profit_order_id=NULL, stop_loss_order_id=NULL WHERE status='open'")
print(f"已清除 {cursor.rowcount} 条旧持仓")
conn.commit()
conn.close()
