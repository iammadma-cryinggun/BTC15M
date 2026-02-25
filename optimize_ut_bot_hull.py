#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UT Bot + Hull Suite 参数优化脚本
网格搜索最佳参数组合

优化目标：最大化胜率
"""

import sys
import io
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from itertools import product

# 修复 Windows 控制台编码
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ==================== 配置 ====================
SYMBOL = "BTCUSDT"
INTERVAL = "15m"
BACKTEST_DAYS = 7
PROXIES = {
    'http': 'http://127.0.0.1:15236',
    'https': 'http://127.0.0.1:15236'
}

# 参数搜索空间
KEY_VALUES = [0.5, 1.0, 1.5, 2.0]  # UT Bot 敏感度
ATR_PERIODS = [5, 10, 14, 20]       # ATR 周期
HULL_LENGTHS = [21, 34, 55, 89]     # Hull MA 周期（斐波那契数列）

BINANCE_API = "https://api.binance.com"


class TechnicalIndicators:
    """技术指标计算"""

    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int) -> pd.Series:
        high = df['high']
        low = df['low']
        close = df['close']
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    @staticmethod
    def calculate_wma(series: pd.Series, period: int) -> pd.Series:
        def wma_func(x):
            weights = np.arange(1, len(x) + 1)
            return np.sum(weights * x) / np.sum(weights)
        return series.rolling(window=period).apply(wma_func, raw=True)

    @staticmethod
    def calculate_hma(series: pd.Series, length: int) -> pd.Series:
        half_length = int(length / 2)
        sqrt_length = int(np.sqrt(length))
        wma_half = TechnicalIndicators.calculate_wma(series, half_length)
        wma_full = TechnicalIndicators.calculate_wma(series, length)
        return TechnicalIndicators.calculate_wma(2 * wma_half - wma_full, sqrt_length)


def calculate_ut_bot_signals(df: pd.DataFrame, key_value: float, atr_period: int):
    """计算 UT Bot 信号"""
    close = df['close'].values
    atr = TechnicalIndicators.calculate_atr(df, atr_period).values
    n_loss = key_value * atr

    xatr_trailing_stop = np.zeros(len(df))
    pos = np.zeros(len(df))

    for i in range(1, len(df)):
        prev_stop = xatr_trailing_stop[i-1]
        current_close = close[i]
        prev_close = close[i-1]

        if current_close > prev_stop and prev_close > prev_stop:
            xatr_trailing_stop[i] = max(prev_stop, current_close - n_loss[i])
        elif current_close < prev_stop and prev_close < prev_stop:
            xatr_trailing_stop[i] = min(prev_stop, current_close + n_loss[i])
        elif current_close > prev_stop:
            xatr_trailing_stop[i] = current_close - n_loss[i]
        else:
            xatr_trailing_stop[i] = current_close + n_loss[i]

        if prev_close < prev_stop and current_close > xatr_trailing_stop[i]:
            pos[i] = 1
        elif prev_close > prev_stop and current_close < xatr_trailing_stop[i]:
            pos[i] = -1
        else:
            pos[i] = pos[i-1]

    return close > xatr_trailing_stop


def fetch_klines(symbol: str, interval: str, limit: int = 1000) -> pd.DataFrame:
    """获取 K线数据"""
    url = f"{BINANCE_API}/api/v3/klines"
    params = {'symbol': symbol, 'interval': interval, 'limit': limit}

    try:
        response = requests.get(url, params=params, timeout=10, proxies=PROXIES)
        response.raise_for_status()
        data = response.json()

        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ])

        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)

        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df
    except Exception as e:
        print(f"[ERROR] 获取K线失败: {e}")
        return None


def backtest_params(df: pd.DataFrame, key_value: float, atr_period: int, hull_length: int):
    """回测特定参数组合"""
    # 计算指标
    ut_trend = calculate_ut_bot_signals(df, key_value, atr_period)
    hull = TechnicalIndicators.calculate_hma(df['close'], hull_length)

    # 回测
    results = []
    signal_count = 0
    win_count = 0
    long_wins = 0
    long_count = 0
    short_wins = 0
    short_count = 0

    min_idx = max(atr_period, hull_length)

    for i in range(min_idx, len(df) - 1):
        # UT Bot 趋势
        ut_signal = "LONG" if ut_trend[i] else "SHORT"

        # Hull 趋势
        hull_signal = "LONG" if hull.iloc[i] > hull.iloc[i - 2] else "SHORT"

        # 综合信号
        if ut_signal != hull_signal:
            continue

        signal = ut_signal
        signal_count += 1

        if signal == "LONG":
            long_count += 1
        else:
            short_count += 1

        # 实际结果
        entry_price = df['open'].iloc[i]
        exit_price = df['close'].iloc[i + 1]
        actual = "LONG" if exit_price > entry_price else "SHORT"

        is_win = (signal == actual)
        if is_win:
            win_count += 1
            if signal == "LONG":
                long_wins += 1
            else:
                short_wins += 1

    if signal_count == 0:
        return None

    win_rate = win_count / signal_count * 100
    long_win_rate = long_wins / long_count * 100 if long_count > 0 else 0
    short_win_rate = short_wins / short_count * 100 if short_count > 0 else 0

    return {
        'key_value': key_value,
        'atr_period': atr_period,
        'hull_length': hull_length,
        'total_signals': signal_count,
        'win_rate': win_rate,
        'long_count': long_count,
        'long_win_rate': long_win_rate,
        'short_count': short_count,
        'short_win_rate': short_win_rate
    }


def run_optimization():
    """运行参数优化"""
    print("=" * 70)
    print("  UT Bot + Hull Suite 参数优化 (网格搜索)")
    print("=" * 70)
    print()

    # 获取数据
    limit = min(1000, BACKTEST_DAYS * 96 + 100)
    print(f"[获取] 下载历史数据 ({BACKTEST_DAYS}天)...")
    df = fetch_klines(SYMBOL, INTERVAL, limit)

    if df is None or len(df) < 100:
        print("[错误] 数据不足")
        return

    print(f"[完成] 已获取 {len(df)} 根K线")
    print()

    # 生成所有参数组合
    param_combinations = list(product(KEY_VALUES, ATR_PERIODS, HULL_LENGTHS))
    total_combinations = len(param_combinations)

    print(f"[搜索] 测试 {total_combinations} 种参数组合...")
    print(f"       Key Value: {KEY_VALUES}")
    print(f"       ATR Period: {ATR_PERIODS}")
    print(f"       Hull Length: {HULL_LENGTHS}")
    print()

    # 网格搜索
    results = []
    for idx, (key_val, atr_period, hull_length) in enumerate(param_combinations, 1):
        result = backtest_params(df, key_val, atr_period, hull_length)
        if result:
            results.append(result)

        # 进度显示
        if idx % 10 == 0 or idx == total_combinations:
            progress = idx / total_combinations * 100
            print(f"[进度] {idx}/{total_combinations} ({progress:.1f}%)")

    # 排序结果（按整体胜率）
    results_by_winrate = sorted(results, key=lambda x: x['win_rate'], reverse=True)

    print()
    print("=" * 70)
    print("  优化结果（按整体胜率排名）")
    print("=" * 70)
    print()

    print("Top 10 参数组合:")
    print("-" * 70)
    for i, r in enumerate(results_by_winrate[:10], 1):
        print(f"\n#{i}")
        print(f"  参数: Key={r['key_value']}, ATR={r['atr_period']}, Hull={r['hull_length']}")
        print(f"  整体: {r['total_signals']} 笔 | 胜率: {r['win_rate']:.2f}%")
        print(f"  LONG:  {r['long_count']} 笔 | 胜率: {r['long_win_rate']:.2f}%")
        print(f"  SHORT: {r['short_count']} 笔 | 胜率: {r['short_win_rate']:.2f}%")

    # 按方向分别排序
    print()
    print("=" * 70)
    print("  最佳 LONG 参数组合")
    print("=" * 70)
    long_results = [r for r in results if r['long_count'] >= 10]  # 至少10笔LONG信号
    long_results = sorted(long_results, key=lambda x: x['long_win_rate'], reverse=True)

    if long_results:
        best_long = long_results[0]
        print(f"\n参数: Key={best_long['key_value']}, ATR={best_long['atr_period']}, Hull={best_long['hull_length']}")
        print(f"LONG 胜率: {best_long['long_win_rate']:.2f}% ({best_long['long_count']} 笔)")
        print(f"整体胜率: {best_long['win_rate']:.2f}%")

    print()
    print("=" * 70)
    print("  最佳 SHORT 参数组合")
    print("=" * 70)
    short_results = [r for r in results if r['short_count'] >= 10]  # 至少10笔SHORT信号
    short_results = sorted(short_results, key=lambda x: x['short_win_rate'], reverse=True)

    if short_results:
        best_short = short_results[0]
        print(f"\n参数: Key={best_short['key_value']}, ATR={best_short['atr_period']}, Hull={best_short['hull_length']}")
        print(f"SHORT 胜率: {best_short['short_win_rate']:.2f}% ({best_short['short_count']} 笔)")
        print(f"整体胜率: {best_short['win_rate']:.2f}%")

    print("=" * 70)


if __name__ == "__main__":
    run_optimization()
