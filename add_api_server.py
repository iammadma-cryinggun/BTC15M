#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单的HTTP API服务器，用于查询交易数据
在Zeabur环境变量中添加: ENABLE_API=true
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import sqlite3
import json
import os
from datetime import datetime

class TradeAPIHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok', 'timestamp': datetime.now().isoformat()}).encode())
            return

        if self.path == '/trades':
            # 查询最近5笔交易
            data_dir = os.getenv('DATA_DIR', '/app/data')
            db_path = os.path.join(data_dir, 'btc_15min_auto_trades.db')

            try:
                conn = sqlite3.connect(db_path, timeout=30.0)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT
                        id,
                        entry_time,
                        side,
                        entry_token_price,
                        exit_token_price,
                        pnl_usd,
                        pnl_pct,
                        exit_reason,
                        value_usdc,
                        size
                    FROM positions
                    WHERE status = 'closed'
                    ORDER BY entry_time DESC
                    LIMIT 5
                """)

                trades = []
                for row in cursor.fetchall():
                    trades.append({
                        'id': row['id'],
                        'entry_time': row['entry_time'],
                        'side': row['side'],
                        'entry_price': row['entry_token_price'],
                        'exit_price': row['exit_token_price'],
                        'pnl_usd': row['pnl_usd'],
                        'pnl_pct': row['pnl_pct'],
                        'exit_reason': row['exit_reason'],
                        'value_usdc': row['value_usdc'],
                        'size': row['size']
                    })

                conn.close()

                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps(trades, ensure_ascii=False, indent=2).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
            return

        # 404
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b'Not Found')

    def log_message(self, format, *args):
        # 禁用访问日志，避免干扰交易日志
        pass

def start_api_server(port=8888):
    """启动API服务器（在单独线程中）"""
    server = HTTPServer(('0.0.0.0', port), TradeAPIHandler)
    print(f"[API] HTTP API服务器已启动: http://0.0.0.0:{port}")
    print(f"[API] 端点:")
    print(f"[API]   GET /health  - 健康检查")
    print(f"[API]   GET /trades  - 最近5笔交易")
    server.serve_forever()

if __name__ == '__main__':
    # 独立运行模式（用于测试）
    start_api_server()
