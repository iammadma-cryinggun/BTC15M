#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完整导出2月28日所有交易记录（含Oracle分数）
"""

import csv
import sys
import re
from datetime import datetime

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

def load_oracle_from_logs(log_files):
    """从日志加载所有Oracle信号"""
    oracle_signals = {}
    oracle_pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?\[ORACLE\] 先知分:([-\d.]+) \| 15m:(NEUTRAL|LONG|SHORT) \| 1h:(NEUTRAL|LONG|SHORT) \| 本地分:([-\d.]+)'

    for log_file in log_files:
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    match = re.search(oracle_pattern, line)
                    if match:
                        timestamp = match.group(1)
                        oracle_signals[timestamp] = {
                            'oracle_score': float(match.group(2)),
                            'trend_15m': match.group(3),
                            'trend_1h': match.group(4),
                            'local_score': float(match.group(5))
                        }
        except:
            pass

    return oracle_signals

def find_oracle_for_time(timestamp_str, oracle_signals):
    """为给定时间找到最近的Oracle信号"""
    target_time = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')

    # 查找最近的信号（前后2分钟内）
    best_match = None
    min_diff = 120  # 2分钟

    for ts_str, data in oracle_signals.items():
        ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
        diff = abs((target_time - ts).total_seconds())

        if diff < min_diff:
            min_diff = diff
            best_match = data

    return best_match

def main():
    log_files = [
        r'C:\Users\Martin\Downloads\runtime-log-20260228-081057.log',
        r'C:\Users\Martin\Downloads\runtime-log-20260228-082140.log'
    ]

    csv_file = r'C:\Users\Martin\Downloads\Polymarket-History-2026-02-28 (1).csv'

    # 加载数据
    oracle_signals = load_oracle_from_logs(log_files)

    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        trades = list(reversed(list(reader)))

    print("="*160)
    print('2月28日完整交易记录（Buy-Sell配对 + Oracle分数）')
    print("="*160)

    # 配对交易
    pairs = []
    i = 0
    while i < len(trades):
        if trades[i]['action'] == 'Buy':
            buy = trades[i]
            buy_time = datetime.fromtimestamp(int(buy['timestamp']))
            buy_usdc = float(buy['usdcAmount'])
            direction = buy['tokenName']

            # 向后找对应的Sell
            for j in range(i + 1, len(trades)):
                if (trades[j]['action'] == 'Sell' and
                    trades[j]['tokenName'] == direction):
                    sell = trades[j]
                    sell_time = datetime.fromtimestamp(int(sell['timestamp']))

                    pnl = float(sell['usdcAmount']) - buy_usdc
                    pnl_pct = (pnl / buy_usdc) * 100

                    # 查找Oracle数据
                    oracle = find_oracle_for_time(
                        buy_time.strftime('%Y-%m-%d %H:%M:%S'),
                        oracle_signals
                    )

                    pairs.append({
                        'buy_time': buy_time,
                        'sell_time': sell_time,
                        'direction': direction,
                        'buy_usdc': buy_usdc,
                        'sell_usdc': float(sell['usdcAmount']),
                        'pnl': pnl,
                        'pnl_pct': pnl_pct,
                        'oracle': oracle
                    })
                    i = j + 1
                    break
            else:
                i += 1
        else:
            i += 1

    # 按盈亏排序
    pairs.sort(key=lambda x: x['pnl'])

    # 显示所有交易
    print(f"\n共 {len(pairs)} 笔配对交易\n")

    for idx, trade in enumerate(pairs, 1):
        pnl_icon = "盈利" if trade['pnl'] > 0 else "亏损"
        oracle = trade['oracle']

        print(f"\n{'='*160}")
        print(f"交易 #{idx} - {pnl_icon}")
        print(f"{'='*160}")
        print(f"  买入时间: {trade['buy_time'].strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  卖出时间: {trade['sell_time'].strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  持仓时长: {(trade['sell_time'] - trade['buy_time']).total_seconds() / 60:.1f} 分钟")
        print(f"  方向:     {trade['direction']}")
        print(f"  投入:     ${trade['buy_usdc']:.2f}")
        print(f"  回收:     ${trade['sell_usdc']:.2f}")
        print(f"  盈亏:     ${trade['pnl']:+.2f} ({trade['pnl_pct']:+.1f}%)")

        if oracle:
            # 计算融合分数
            if oracle['oracle_score'] * oracle['local_score'] > 0:
                fusion = oracle['local_score'] + oracle['oracle_score'] / 3.0
            else:
                fusion = oracle['local_score'] + oracle['oracle_score'] / 6.0

            print(f"\n  【Oracle数据】")
            print(f"    Oracle分数:   {oracle['oracle_score']:+.2f}", end='')
            if abs(oracle['oracle_score']) >= 10:
                print(' 🔥🔥 核弹级巨鲸！')
            elif abs(oracle['oracle_score']) >= 7:
                print(' ⚡ 强力信号')
            else:
                print('')

            print(f"    本地分数:     {oracle['local_score']:+.2f}")
            print(f"    融合分数:     {fusion:+.2f}")
            print(f"    15分钟趋势:   {oracle['trend_15m']}")
            print(f"    1小时趋势:   {oracle['trend_1h']}")

            # 信号强度分析
            if abs(oracle['oracle_score']) >= 10:
                strength = "核弹级"
            elif abs(oracle['oracle_score']) >= 7:
                strength = "强力"
            elif abs(oracle['oracle_score']) >= 4:
                strength = "中等"
            else:
                strength = "弱"

            direction_str = "看跌" if oracle['oracle_score'] < 0 else "看涨"
            print(f"    信号强度:     {strength} {direction_str}")
        else:
            print(f"\n  【Oracle数据】无（日志中未找到匹配的Oracle信号）")

    # 统计
    profit_trades = [p for p in pairs if p['pnl'] > 0]
    loss_trades = [p for p in pairs if p['pnl'] < 0]
    total_profit = sum(p['pnl'] for p in profit_trades)
    total_loss = sum(p['pnl'] for p in loss_trades)

    print(f"\n{'='*160}")
    print('【总体统计】')
    print(f"{'='*160}")
    print(f"  总交易:     {len(pairs)} 笔")
    print(f"  盈利:       {len(profit_trades)} 笔, +${total_profit:.2f}")
    print(f"  亏损:       {len(loss_trades)} 笔, -${abs(total_loss):.2f}")
    print(f"  净盈亏:     ${total_profit + total_loss:+.2f}")
    print(f"  胜率:       {len(profit_trades) / len(pairs) * 100:.1f}%")

    # 亏损详情
    if loss_trades:
        print(f"\n{'='*160}")
        print('【亏损交易详情】（按亏损金额排序）')
        print(f"{'='*160}")
        loss_trades.sort(key=lambda x: x['pnl'])

        for idx, trade in enumerate(loss_trades[:10], 1):  # 只显示前10笔最亏的
            print(f"\n  {idx}. {trade['buy_time'].strftime('%H:%M')} {trade['direction']:4s} "
                  f"投入${trade['buy_usdc']:.2f} 回收${trade['sell_usdc']:.2f} = {trade['pnl']:+.2f} ({trade['pnl_pct']:+.1f}%)")
            if trade['oracle']:
                print(f"     Oracle: {trade['oracle']['oracle_score']:+.2f}")

    print(f"\n{'='*160}\n")

if __name__ == '__main__':
    main()
