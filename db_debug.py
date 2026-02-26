#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
临时数据库查询接口 - 用于调试2月26日的交易问题
访问: http://your-zeabur-app-url/debug/db
"""

import sqlite3
import os
import json
from datetime import datetime
from flask import Flask, jsonify, send_file

app = Flask(__name__)

# 数据库路径
db_path = os.path.join(os.getenv('DATA_DIR', '/app/data'), 'btc_15min_auto_trades.db')

def query_db():
    """查询2月26日的交易数据"""
    if not os.path.exists(db_path):
        return {"error": "Database not found", "path": db_path}

    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 查询2月26日的所有持仓
    cursor.execute("""
        SELECT id, entry_time, side, entry_token_price, size, value_usdc,
               exit_time, exit_token_price, exit_reason, pnl_pct, status
        FROM positions
        WHERE entry_time LIKE '2026-02-26%'
        ORDER BY entry_time ASC
    """)

    rows = cursor.fetchall()
    conn.close()

    result = []
    for row in rows:
        result.append({
            "id": row["id"],
            "entry_time": row["entry_time"],
            "side": row["side"],
            "entry_price": float(row["entry_token_price"]) if row["entry_token_price"] else 0,
            "size": float(row["size"]),
            "value_usdc": float(row["value_usdc"]) if row["value_usdc"] else 0,
            "exit_time": row["exit_time"],
            "exit_price": float(row["exit_token_price"]) if row["exit_token_price"] else None,
            "exit_reason": row["exit_reason"],
            "pnl_pct": float(row["pnl_pct"]) if row["pnl_pct"] else 0,
            "status": row["status"]
        })

    return {
        "total": len(result),
        "data": result
    }

@app.route('/debug/db')
def debug_db():
    """返回JSON格式的查询结果"""
    result = query_db()
    return jsonify(result)

@app.route('/debug/db/download')
def download_db():
    """下载整个数据库文件"""
    if os.path.exists(db_path):
        return send_file(db_path, as_attachment=True)
    return "Database not found", 404

if __name__ == '__main__':
    # 注意：这个端口需要和主服务不同，避免冲突
    port = int(os.getenv('DEBUG_PORT', 5001))
    print(f"Starting debug server on port {port}...")
    print(f"Database: {db_path}")
    print(f"Access: http://localhost:{port}/debug/db")
    app.run(host='0.0.0.0', port=port)
