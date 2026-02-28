#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完整分析云端下载的数据库
包含所有Oracle数据和交易统计
"""

import sqlite3
import sys
from datetime import datetime
from collections import defaultdict

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

def analyze_database(db_path):
    """分析数据库中的所有交易"""

    print("=" * 160)
    print('BTC 15分钟自动交易 - 完整数据库分析')
    print("=" * 160)

    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 检查表结构
    cursor.execute("PRAGMA table_info(positions)")
    columns = [col[1] for col in cursor.fetchall()]
    print(f"\n数据库列: {', '.join(columns)}\n")

    # 检测数据库版本（是否有Oracle列）
    has_oracle = 'oracle_score' in columns
    has_strategy = 'strategy' in columns

    # 查询所有已关闭的交易
    if has_oracle and has_strategy:
        cursor.execute("""
            SELECT
                entry_time, side, entry_token_price, exit_token_price,
                pnl_usd, pnl_pct, exit_reason, status,
                score, oracle_score, oracle_1h_trend, oracle_15m_trend, strategy
            FROM positions
            WHERE status = 'closed'
            ORDER BY entry_time DESC
        """)
        print("✅ 检测到新版本数据库（包含Oracle数据）\n")
    else:
        cursor.execute("""
            SELECT
                entry_time, side, entry_token_price, exit_token_price,
                pnl_usd, pnl_pct, exit_reason, status, score
            FROM positions
            WHERE status = 'closed'
            ORDER BY entry_time DESC
        """)
        print("⚠️ 旧版本数据库（没有Oracle数据列）")
        print("   云端数据库已更新为包含Oracle数据的版本，下次下载将看到完整数据\n")

    trades = cursor.fetchall()

    if not trades:
        print("⚠️ 数据库中没有已关闭的交易记录")
        conn.close()
        return

    print(f"✅ 找到 {len(trades)} 笔已关闭交易\n")

    # ========== 详细交易列表 ==========
    print("=" * 160)
    print('【详细交易记录】')
    print("=" * 160)

    for i, t in enumerate(trades, 1):
        pnl_icon = "🟢盈利" if t['pnl_usd'] and t['pnl_usd'] > 0 else "🔴亏损"
        exit_price = f"{t['exit_token_price']:.4f}" if t['exit_token_price'] else "N/A"
        pnl_str = f"${t['pnl_usd']:+.2f} ({t['pnl_pct']:+.1f}%)" if t['pnl_usd'] is not None else "N/A"

        print(f"\n{'─' * 160}")
        print(f"交易 #{i} - {pnl_icon}")
        print(f"{'─' * 160}")
        print(f"  入场时间:   {t['entry_time']}")
        print(f"  方向:       {t['side']}")
        if has_strategy:
            strategy = t['strategy'] if 'strategy' in t.keys() else 'N/A'
            print(f"  策略:       {strategy}")
        print(f"  入场价:     {t['entry_token_price']:.4f}")
        print(f"  出场价:     {exit_price}")
        print(f"  盈亏:       {pnl_str}")
        print(f"  退出原因:   {t['exit_reason']}")

        # Oracle数据
        if has_oracle and t['oracle_score'] is not None and t['oracle_score'] != 0:
            print(f"\n  📊 Oracle指标:")
            print(f"    Oracle分数:   {t['oracle_score']:+.2f}", end='')

            if abs(t['oracle_score']) >= 12:
                print(' 🔥🔥🔥 超级核弹！')
            elif abs(t['oracle_score']) >= 10:
                print(' 🔥🔥 核弹级巨鲸！')
            elif abs(t['oracle_score']) >= 7:
                print(' ⚡ 强力信号')
            else:
                print('')

            trend_15m = t['oracle_15m_trend'] if 'oracle_15m_trend' in t.keys() else 'N/A'
            trend_1h = t['oracle_1h_trend'] if 'oracle_1h_trend' in t.keys() else 'N/A'
            print(f"    15分钟趋势:   {trend_15m}")
            print(f"    1小时趋势:    {trend_1h}")

        # 本地分数
        if t['score'] is not None:
            print(f"\n  🎯 本地指标:")
            print(f"    综合分数:     {t['score']:+.2f}")

    # ========== 总体统计 ==========
    print(f"\n{'=' * 160}")
    print('【总体统计】')
    print('=' * 160)

    profit_trades = [t for t in trades if t['pnl_usd'] and t['pnl_usd'] > 0]
    loss_trades = [t for t in trades if t['pnl_usd'] and t['pnl_usd'] < 0]

    total_profit = sum(t['pnl_usd'] for t in profit_trades)
    total_loss = sum(t['pnl_usd'] for t in loss_trades)
    total_trades = len([t for t in trades if t['pnl_usd']])

    print(f"\n  总交易:     {total_trades} 笔")
    print(f"  盈利:       {len(profit_trades)} 笔, +${total_profit:.2f}")
    print(f"  亏损:       {len(loss_trades)} 笔, -${abs(total_loss):.2f}")
    print(f"  净盈亏:     ${total_profit + total_loss:+.2f}")
    print(f"  胜率:       {len(profit_trades) / total_trades * 100:.1f}%")

    # ========== 本地分数表现分析 ==========
    print(f"\n{'=' * 160}")
    print('【本地分数表现分析】')
    print('=' * 160)

    # 按分数绝对值分组
    score_groups = {
        '超强信号 (|分数|≥10)': [],
        '强信号 (7≤|分数|<10)': [],
        '中等信号 (4≤|分数|<7)': [],
        '弱信号 (|分数|<4)': []
    }

    for t in trades:
        if 'score' in t.keys() and t['score'] is not None:
            score = abs(t['score'])
            if score >= 10:
                score_groups['超强信号 (|分数|≥10)'].append(t)
            elif score >= 7:
                score_groups['强信号 (7≤|分数|<10)'].append(t)
            elif score >= 4:
                score_groups['中等信号 (4≤|分数|<7)'].append(t)
            else:
                score_groups['弱信号 (|分数|<4)'].append(t)

    for group_name, group_trades in score_groups.items():
        if group_trades:
            wins = sum(1 for t in group_trades if t['pnl_usd'] and t['pnl_usd'] > 0)
            pnl = sum(t['pnl_usd'] for t in group_trades if t['pnl_usd'])
            win_rate = wins / len(group_trades) * 100

            print(f"\n  {group_name}:")
            print(f"    交易数:   {len(group_trades)} 笔")
            print(f"    胜率:     {win_rate:.1f}%")
            print(f"    净盈亏:   ${pnl:+.2f}")

    # ========== 方向表现分析 ==========
    print(f"\n{'=' * 160}")
    print('【方向表现分析（LONG vs SHORT）】')
    print('=' * 160)

    direction_stats = {
        'LONG': {'count': 0, 'wins': 0, 'pnl': 0.0, 'settled_loss': 0},
        'SHORT': {'count': 0, 'wins': 0, 'pnl': 0.0, 'settled_loss': 0}
    }

    for t in trades:
        if t['side'] in direction_stats and t['pnl_usd']:
            direction_stats[t['side']]['count'] += 1
            if t['pnl_usd'] > 0:
                direction_stats[t['side']]['wins'] += 1
            direction_stats[t['side']]['pnl'] += t['pnl_usd']
            if t['exit_reason'] == 'MARKET_SETTLED':
                direction_stats[t['side']]['settled_loss'] += 1

    for direction, stats in direction_stats.items():
        win_rate = stats['wins'] / stats['count'] * 100 if stats['count'] > 0 else 0
        print(f"\n  {direction}:")
        print(f"    交易数:   {stats['count']} 笔")
        print(f"    胜率:     {win_rate:.1f}%")
        print(f"    净盈亏:   ${stats['pnl']:+.2f}")
        print(f"    市场结算损失: {stats['settled_loss']} 笔 (-100%)")

    # ========== 退出原因分析 ==========
    print(f"\n{'=' * 160}")
    print('【退出原因分析】')
    print('=' * 160)

    exit_reason_stats = defaultdict(lambda: {'count': 0, 'pnl': 0.0})

    for t in trades:
        if t['pnl_usd'] and t['exit_reason']:
            exit_reason_stats[t['exit_reason']]['count'] += 1
            exit_reason_stats[t['exit_reason']]['pnl'] += t['pnl_usd']

    for reason, stats in sorted(exit_reason_stats.items(), key=lambda x: -x[1]['count']):
        avg_pnl = stats['pnl'] / stats['count'] if stats['count'] > 0 else 0
        print(f"\n  {reason}:")
        print(f"    交易数:   {stats['count']} 笔")
        print(f"    总盈亏:   ${stats['pnl']:+.2f}")
        print(f"    平均盈亏: ${avg_pnl:+.2f}")

    # ========== 策略统计 ==========
    if has_strategy and any('strategy' in t.keys() and t['strategy'] for t in trades):
        print(f"\n{'=' * 160}")
        print('【策略表现】')
        print('=' * 160)

        strategy_stats = defaultdict(lambda: {'count': 0, 'wins': 0, 'pnl': 0.0})

        for t in trades:
            if 'strategy' in t.keys() and t['strategy'] and t['pnl_usd']:
                s = t['strategy']
                strategy_stats[s]['count'] += 1
                if t['pnl_usd'] > 0:
                    strategy_stats[s]['wins'] += 1
                strategy_stats[s]['pnl'] += t['pnl_usd']

        for strategy, stats in sorted(strategy_stats.items()):
            win_rate = stats['wins'] / stats['count'] * 100 if stats['count'] > 0 else 0
            print(f"\n  {strategy}:")
            print(f"    交易数:   {stats['count']} 笔")
            print(f"    胜率:     {win_rate:.1f}%")
            print(f"    净盈亏:   ${stats['pnl']:+.2f}")

    # ========== Oracle分数统计 ==========
    if has_oracle:
        oracle_trades = [t for t in trades if 'oracle_score' in t.keys() and t['oracle_score'] is not None and t['oracle_score'] != 0]

        if oracle_trades:
            print(f"\n{'=' * 160}")
            print('【Oracle分数表现分析】')
            print('=' * 160)

            # 按Oracle分数绝对值分组
            oracle_groups = {
                '超强信号 (|分数|≥10)': [],
                '强信号 (7≤|分数|<10)': [],
                '中等信号 (4≤|分数|<7)': [],
                '弱信号 (|分数|<4)': []
            }

        for t in oracle_trades:
            score = abs(t['oracle_score'])
            if score >= 10:
                oracle_groups['超强信号 (|分数|≥10)'].append(t)
            elif score >= 7:
                oracle_groups['强信号 (7≤|分数|<10)'].append(t)
            elif score >= 4:
                oracle_groups['中等信号 (4≤|分数|<7)'].append(t)
            else:
                oracle_groups['弱信号 (|分数|<4)'].append(t)

            for group_name, group_trades in oracle_groups.items():
                if group_trades:
                    wins = sum(1 for t in group_trades if t['pnl_usd'] and t['pnl_usd'] > 0)
                    pnl = sum(t['pnl_usd'] for t in group_trades if t['pnl_usd'])
                    win_rate = wins / len(group_trades) * 100

                    print(f"\n  {group_name}:")
                    print(f"    交易数:   {len(group_trades)} 笔")
                    print(f"    胜率:     {win_rate:.1f}%")
                    print(f"    净盈亏:   ${pnl:+.2f}")

    # ========== 亏损交易详情 ==========
    if loss_trades:
        print(f"\n{'=' * 160}")
        print('【亏损交易TOP10】（按亏损金额排序）')
        print('=' * 160)

        loss_trades_sorted = sorted(loss_trades, key=lambda x: x['pnl_usd'])[:10]

        for idx, t in enumerate(loss_trades_sorted, 1):
            print(f"\n  {idx}. [{t['entry_time']}] {t['side']}")
            print(f"     入场: {t['entry_token_price']:.4f} -> 出场: {t['exit_token_price']:.4f}")
            print(f"     盈亏: ${t['pnl_usd']:+.2f} ({t['pnl_pct']:+.1f}%)")

            if has_oracle and 'oracle_score' in t.keys() and t['oracle_score']:
                trend_15m = t['oracle_15m_trend'] if 'oracle_15m_trend' in t.keys() else 'N/A'
                trend_1h = t['oracle_1h_trend'] if 'oracle_1h_trend' in t.keys() else 'N/A'
                print(f"     Oracle: {t['oracle_score']:+.2f} | 15m:{trend_15m} | 1h:{trend_1h}")

            score = t['score'] if 'score' in t.keys() else 'N/A'
            print(f"     本地分: {score}")

    # ========== 盈利交易TOP5 ==========
    if profit_trades:
        print(f"\n{'=' * 160}")
        print('【盈利交易TOP5】（按盈利金额排序）')
        print('=' * 160)

        profit_trades_sorted = sorted(profit_trades, key=lambda x: -x['pnl_usd'])[:5]

        for idx, t in enumerate(profit_trades_sorted, 1):
            print(f"\n  {idx}. [{t['entry_time']}] {t['side']}")
            print(f"     入场: {t['entry_token_price']:.4f} -> 出场: {t['exit_token_price']:.4f}")
            print(f"     盈亏: ${t['pnl_usd']:+.2f} ({t['pnl_pct']:+.1f}%)")

            if has_oracle and 'oracle_score' in t.keys() and t['oracle_score']:
                trend_15m = t['oracle_15m_trend'] if 'oracle_15m_trend' in t.keys() else 'N/A'
                trend_1h = t['oracle_1h_trend'] if 'oracle_1h_trend' in t.keys() else 'N/A'
                print(f"     Oracle: {t['oracle_score']:+.2f} | 15m:{trend_15m} | 1h:{trend_1h}")

            score = t['score'] if 'score' in t.keys() else 'N/A'
            print(f"     本地分: {score}")

    print(f"\n{'=' * 160}\n")

    conn.close()

if __name__ == '__main__':
    db_path = r'C:\Users\Martin\Downloads\btc_15min_auto_trades (2).db'
    analyze_database(db_path)
