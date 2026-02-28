#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完整分析：2月28日所有交易记录（日志 + Polymarket CSV）
"""

import csv
import sys
import re
from datetime import datetime

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

def extract_log_trades(log_files):
    """从日志提取交易"""
    trades = []

    for log_file in log_files:
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            oracle_signals = {}
            oracle_pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?\[ORACLE\] 先知分:([-\d.]+) \| 15m:(NEUTRAL|LONG|SHORT) \| 1h:(NEUTRAL|LONG|SHORT) \| 本地分:([-\d.]+)'
            entry_pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?entry=([0-9.]+).*?size=([0-9]+)'
            filled_pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?\[STOP ORDERS\] ✅ 入场订单已成交'

            for line in lines:
                match = re.search(oracle_pattern, line)
                if match:
                    oracle_signals[match.group(1)] = {
                        'oracle_score': float(match.group(2)),
                        'trend_15m': match.group(3),
                        'trend_1h': match.group(4),
                        'local_score': float(match.group(5))
                    }

            current_order = None
            for line in lines:
                match = re.search(entry_pattern, line)
                if match:
                    current_order = {
                        'time': match.group(1),
                        'entry_price': float(match.group(2)),
                        'size': int(match.group(3))
                    }

                if re.search(filled_pattern, line) and current_order:
                    filled_time = re.search(filled_pattern, line).group(1)

                    # 查找最近的Oracle信号
                    oracle_data = None
                    for ts in sorted(oracle_signals.keys(), reverse=True):
                        if ts <= filled_time:
                            oracle_data = oracle_signals[ts]
                            break

                    if oracle_data:
                        trades.append({
                            **current_order,
                            'oracle': oracle_data,
                            'filled_time': filled_time
                        })
                    current_order = None
        except Exception as e:
            print(f"[ERROR] {log_file}: {e}")

    return trades

def load_polymarket_trades(csv_file):
    """加载Polymarket交易记录"""
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        return list(reversed(list(reader)))

def match_and_analyze():
    """匹配日志交易和Polymarket记录"""

    log_files = [
        r'C:\Users\Martin\Downloads\runtime-log-20260228-081057.log',
        r'C:\Users\Martin\Downloads\runtime-log-20260228-082140.log'
    ]

    csv_file = r'C:\Users\Martin\Downloads\Polymarket-History-2026-02-28 (1).csv'

    # 提取数据
    log_trades = extract_log_trades(log_files)
    polymarket_trades = load_polymarket_trades(csv_file)

    print("="*140)
    print('2月28日完整交易分析（日志开仓 + Polymarket盈亏）')
    print("="*140)

    # 显示日志中找到的交易
    print(f"\n【日志中的开仓记录】共 {len(log_trades)} 笔:\n")

    for i, trade in enumerate(log_trades, 1):
        oracle = trade['oracle']

        # 计算融合分数
        if oracle['oracle_score'] * oracle['local_score'] > 0:
            fusion = oracle['local_score'] + oracle['oracle_score'] / 3.0
        else:
            fusion = oracle['local_score'] + oracle['oracle_score'] / 6.0

        # 转换为北京时间（UTC+8）
        utc_time = datetime.strptime(trade['filled_time'], '%Y-%m-%d %H:%M:%S')
        bj_time = utc_time.replace(hour=utc_time.hour + 8)

        print(f"交易 #{i} - 北京时间 {bj_time.strftime('%H:%M:%S')}")
        print(f"  方向:     SHORT (融合分数: {fusion:+.2f})")
        print(f"  入场价:   {trade['entry_price']:.4f}")
        print(f"  数量:     {trade['size']}手")
        print(f"\n  Oracle分数:   {oracle['oracle_score']:+.2f} {'🔥巨鲸!' if abs(oracle['oracle_score']) >= 10 else ''}")
        print(f"  本地分数:     {oracle['local_score']:+.2f}")
        print(f"  15分钟趋势:   {oracle['trend_15m']}")
        print(f"  1小时趋势:   {oracle['trend_1h']}")
        print()

    # Polymarket统计
    print("="*140)
    print("【Polymarket实际交易统计】")
    print("="*140)

    # 简单配对统计
    total_buy = sum(float(t['usdcAmount']) for t in polymarket_trades if t['action'] == 'Buy')
    total_sell = sum(float(t['usdcAmount']) for t in polymarket_trades if t['action'] == 'Sell')
    net_pnl = total_sell - total_buy

    print(f"总买入（投入）: ${total_buy:.2f}")
    print(f"总卖出（回收）: ${total_sell:.2f}")
    print(f"净盈亏: ${net_pnl:+.2f}")
    print(f"\n总交易次数: {len(polymarket_trades)} 笔")

    # 显示最近10笔
    print(f"\n最近10笔操作:\n")
    for i, trade in enumerate(polymarket_trades[:10], 1):
        ts = datetime.fromtimestamp(int(trade['timestamp'])).strftime('%H:%M:%S')
        action = trade['action']
        usdc = float(trade['usdcAmount'])
        tokens = float(trade['tokenAmount'])
        direction = trade['tokenName']

        print(f"{i:2d}. [{ts}] {action:4s} ${usdc:6.2f} -> {tokens:.2f} {direction}")

    print("\n" + "="*140)

if __name__ == '__main__':
    match_and_analyze()
