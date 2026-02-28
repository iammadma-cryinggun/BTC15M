#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析最近交易是否在"追空"
检查是否在市场上涨时不断做空
"""

import sqlite3
import sys
from datetime import datetime

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

def analyze_recent_short(db_path):
    """分析最近的SHORT交易"""

    print("=" * 140)
    print('最近交易分析 - 是否在"追空"？')
    print("=" * 140)

    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 查询最近20笔交易
    cursor.execute("""
        SELECT
            entry_time, side, entry_token_price, exit_token_price,
            pnl_usd, pnl_pct, exit_reason, status, score
        FROM positions
        WHERE status = 'closed'
        ORDER BY entry_time DESC
        LIMIT 20
    """)

    trades = cursor.fetchall()

    print(f"\n【最近20笔交易】\n")

    short_count = 0
    short_loss_count = 0
    recent_short_losses = []

    for i, t in enumerate(trades, 1):
        pnl_icon = "🟢" if t['pnl_usd'] and t['pnl_usd'] > 0 else "🔴"
        exit_price = f"{t['exit_token_price']:.4f}" if t['exit_token_price'] else "0.0000"

        direction_icon = "⬇️做空" if t['side'] == 'SHORT' else "⬆️做多"

        print(f"{i:2d}. [{t['entry_time']}] {direction_icon:6s} {t['entry_token_price']:.4f}→{exit_price} "
              f"{pnl_icon} ${t['pnl_usd']:+.2f} ({t['pnl_pct']:+.1f}%) "
              f"分:{t['score']:+.1f} {t['exit_reason']}")

        if t['side'] == 'SHORT':
            short_count += 1
            if t['pnl_usd'] and t['pnl_usd'] < 0:
                short_loss_count += 1
                recent_short_losses.append(t)

    # 统计
    print(f"\n{'=' * 140}")
    print('【统计】')
    print('=' * 140)
    print(f"最近20笔中: SHORT {short_count} 笔, LONG {20 - short_count} 笔")
    print(f"SHORT亏损: {short_loss_count}/{short_count} 笔 ({short_loss_count/short_count*100 if short_count > 0 else 0:.1f}%)")

    # 检查是否连续SHORT亏损
    if recent_short_losses:
        print(f"\n{'=' * 140}")
        print('【最近SHORT亏损详情】')
        print('=' * 140)

        for t in recent_short_losses[:10]:
            print(f"\n[{t['entry_time']}] SHORT {t['entry_token_price']:.4f}→{t['exit_token_price']:.4f}")
            print(f"  盈亏: ${t['pnl_usd']:+.2f} ({t['pnl_pct']:+.1f}%)")
            print(f"  本地分: {t['score']:+.1f}")
            print(f"  退出: {t['exit_reason']}")

    # 检查前一笔交易的方向
    print(f"\n{'=' * 140}")
    print('【交易方向序列（最近20笔）】')
    print('=' * 140)

    direction_sequence = []
    for t in trades:
        direction_sequence.append('S' if t['side'] == 'SHORT' else 'L')

    # 每10个一行显示
    for i in range(0, len(direction_sequence), 10):
        segment = direction_sequence[i:i+10]
        segment_str = ' '.join(segment)
        print(f"  交易#{i+1:2d}-{i+len(segment):2d}:  {segment_str}")

    # 检测连续SHORT
    consecutive_shorts = 0
    max_consecutive_shorts = 0
    for d in direction_sequence:
        if d == 'S':
            consecutive_shorts += 1
            max_consecutive_shorts = max(max_consecutive_shorts, consecutive_shorts)
        else:
            consecutive_shorts = 0

    print(f"\n  最长连续SHORT: {max_consecutive_shorts} 笔")

    # 检查最近5笔是否都是SHORT
    recent_5 = direction_sequence[:5]
    if all(d == 'S' for d in recent_5):
        print(f"  ⚠️ 警告: 最近5笔全是SHORT！可能在追空")
    elif recent_5.count('S') >= 4:
        print(f"  ⚠️ 注意: 最近5笔中有{recent_5.count('S')}笔SHORT")

    # 按时间段分组统计
    print(f"\n{'=' * 140}")
    print('【按时间段SHORT胜率】')
    print('=' * 140)

    # 查询所有SHORT交易
    cursor.execute("""
        SELECT
            entry_time, side, pnl_usd, exit_reason
        FROM positions
        WHERE status = 'closed' AND side = 'SHORT'
        ORDER BY entry_time DESC
    """)

    all_shorts = cursor.fetchall()

    # 按时间分组
    time_groups = {
        '最近10笔': [],
        '最近20笔': [],
        '最近50笔': [],
        '全部': []
    }

    for idx, t in enumerate(all_shorts):
        if idx < 10:
            time_groups['最近10笔'].append(t)
        if idx < 20:
            time_groups['最近20笔'].append(t)
        if idx < 50:
            time_groups['最近50笔'].append(t)
        time_groups['全部'].append(t)

    for group_name, group_trades in time_groups.items():
        if group_trades:
            wins = sum(1 for t in group_trades if t['pnl_usd'] and t['pnl_usd'] > 0)
            pnl = sum(t['pnl_usd'] for t in group_trades if t['pnl_usd'])
            settled = sum(1 for t in group_trades if t['exit_reason'] == 'MARKET_SETTLED')

            print(f"\n  {group_name}:")
            print(f"    交易数:   {len(group_trades)} 笔")
            print(f"    盈利:     {wins} 笔")
            print(f"    胜率:     {wins/len(group_trades)*100:.1f}%")
            print(f"    净盈亏:   ${pnl:+.2f}")
            print(f"    结算亏损: {settled} 笔")

    print(f"\n{'=' * 140}\n")

    conn.close()

if __name__ == '__main__':
    db_path = r'C:\Users\Martin\Downloads\btc_15min_auto_trades (2).db'
    analyze_recent_short(db_path)
