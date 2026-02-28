#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导出最近交易数据（用于Zeabur后台手动执行）
用法: python export_recent_trades.py
"""

import sqlite3
import json
import sys
from datetime import datetime

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# 支持环境变量配置数据目录
import os
data_dir = os.getenv('DATA_DIR', '/app/data')
db_path = os.path.join(data_dir, 'btc_15min_auto_trades.db')

conn = sqlite3.connect(db_path, timeout=30.0)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("="*120)
print('最近5笔交易详情')
print("="*120)

cursor.execute("""
    SELECT
        p.id,
        p.entry_time,
        p.side,
        p.entry_token_price,
        p.exit_token_price,
        p.pnl_usd,
        p.pnl_pct,
        p.exit_reason,
        p.value_usdc,
        p.size
    FROM positions p
    WHERE p.status = 'closed'
    ORDER BY p.entry_time DESC
    LIMIT 5
""")

trades = cursor.fetchall()

results = []
for i, trade in enumerate(trades, 1):
    pnl_icon = "盈利" if trade['pnl_usd'] > 0 else "亏损"

    print(f"\n{'='*120}")
    print(f"交易 #{i} - {pnl_icon}")
    print(f"{'='*120}")
    print(f"时间:     {trade['entry_time']}")
    print(f"方向:     {trade['side']}")
    print(f"入场价:   {trade['entry_token_price']:.4f}")
    print(f"出场价:   {trade['exit_token_price']:.4f if trade['exit_token_price'] else 'N/A'}")
    print(f"仓位:     {trade['size']:.0f}手 = ${trade['value_usdc']:.2f}")
    print(f"盈亏:     ${trade['pnl_usd']:+.2f} ({trade['pnl_pct']:+.1f}%)")
    print(f"退出原因: {trade['exit_reason']}")

    results.append({
        'id': trade['id'],
        'time': trade['entry_time'],
        'side': trade['side'],
        'entry_price': trade['entry_token_price'],
        'exit_price': trade['exit_token_price'],
        'pnl_usd': trade['pnl_usd'],
        'pnl_pct': trade['pnl_pct'],
        'exit_reason': trade['exit_reason']
    })

# 导出JSON
with open('recent_trades.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"\n已导出到: recent_trades.json")
conn.close()
