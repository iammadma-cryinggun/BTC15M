#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从日志文件中提取交易数据和Oracle分数
"""

import sys
import re
from datetime import datetime

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

def extract_trades_from_log(log_file):
    """从日志文件中提取交易数据"""

    with open(log_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # 存储所有Oracle信号
    oracle_signals = {}

    # 存储所有入场记录
    entry_orders = {}

    # 正则表达式
    oracle_pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?\[ORACLE\] 先知分:([-\d.]+) \| 15m:(NEUTRAL|LONG|SHORT) \| 1h:(NEUTRAL|LONG|SHORT) \| 本地分:([-\d.]+)'
    entry_pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?entry=([0-9.]+).*?size=([0-9]+)'
    filled_pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?\[STOP ORDERS\] ✅ 入场订单已成交'

    # 提取Oracle信号
    for line in lines:
        match = re.search(oracle_pattern, line)
        if match:
            timestamp = match.group(1)
            oracle_score = float(match.group(2))
            trend_15m = match.group(3)
            trend_1h = match.group(4)
            local_score = float(match.group(5))

            # 只保留最近的信号
            oracle_signals[timestamp] = {
                'oracle_score': oracle_score,
                'trend_15m': trend_15m,
                'trend_1h': trend_1h,
                'local_score': local_score
            }

    # 提取入场订单
    current_order = None
    for line in lines:
        # 检查是否是入场订单设置
        match = re.search(entry_pattern, line)
        if match:
            timestamp = match.group(1)
            entry_price = float(match.group(2))
            size = int(match.group(3))
            current_order = {
                'time': timestamp,
                'entry_price': entry_price,
                'size': size
            }

        # 检查是否成交
        if re.search(filled_pattern, line) and current_order:
            match_filled = re.search(filled_pattern, line)
            if match_filled:
                filled_time = match_filled.group(1)
                # 查找最近的Oracle信号
                oracle_data = None
                for ts in sorted(oracle_signals.keys(), reverse=True):
                    if ts <= filled_time:
                        oracle_data = oracle_signals[ts]
                        break

                if oracle_data:
                    entry_orders[filled_time] = {
                        **current_order,
                        'oracle': oracle_data,
                        'filled_time': filled_time
                    }
            current_order = None

    return entry_orders

def print_analysis(log_files):
    """打印分析结果"""

    print("="*140)
    print('从日志文件中提取的交易数据（含Oracle分数）')
    print("="*140)

    all_trades = []

    for log_file in log_files:
        try:
            trades = extract_trades_from_log(log_file)
            all_trades.extend(trades.values())
        except Exception as e:
            print(f"[ERROR] 处理文件 {log_file} 失败: {e}")

    # 按时间排序
    all_trades.sort(key=lambda x: x['time'])

    print(f"\n共找到 {len(all_trades)} 笔交易\n")

    for i, trade in enumerate(all_trades, 1):
        oracle = trade['oracle']

        # 计算融合分数
        if oracle['oracle_score'] * oracle['local_score'] > 0:
            fusion = oracle['local_score'] + oracle['oracle_score'] / 3.0
        else:
            fusion = oracle['local_score'] + oracle['oracle_score'] / 6.0

        direction_icon = "LONG" if fusion > 0 else "SHORT"

        print(f"\n{'='*140}")
        print(f"交易 #{i}")
        print(f"{'='*140}")
        print(f"  时间:     {trade['filled_time']}")
        print(f"  方向:     {direction_icon} (融合分数: {fusion:+.2f})")
        print(f"  入场价:   {trade['entry_price']:.4f}")
        print(f"  数量:     {trade['size']}手")
        print(f"\n  评分明细:")
        print(f"    Oracle分数:   {oracle['oracle_score']:+.2f}")
        print(f"    本地分数:     {oracle['local_score']:+.2f}")
        print(f"    融合分数:     {fusion:+.2f}")
        print(f"\n  趋势:")
        print(f"    15分钟趋势:   {oracle['trend_15m']}")
        print(f"    1小时趋势:   {oracle['trend_1h']}")

    print(f"\n{'='*140}\n")

# 处理用户提供的日志文件
log_files = [
    r'C:\Users\Martin\Downloads\runtime-log-20260228-081057.log',
    r'C:\Users\Martin\Downloads\runtime-log-20260228-082140.log'
]

print_analysis(log_files)
