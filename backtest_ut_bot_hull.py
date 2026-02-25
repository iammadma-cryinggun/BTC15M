#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UT Bot + Hull Suite 回测脚本
验证指标在 Polymarket 15分钟 BTC 预测中的准确率

回测逻辑：
1. 每个15分钟窗口开始时检查信号
2. 预测该窗口内 BTC 涨跌
3. 窗口结束时验证实际结果
4. 计算胜率、盈亏等指标
"""

import sys
import io
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# 修复 Windows 控制台编码
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ==================== 配置 ====================
SYMBOL = "BTCUSDT"
INTERVAL = "15m"
BACKTEST_DAYS = 7  # 回测天数
PROXIES = {
    'http': 'http://127.0.0.1:15236',
    'https': 'http://127.0.0.1:15236'
}

# UT Bot 参数
UT_BOT_KEY_VALUE = 1.0
UT_BOT_ATR_PERIOD = 10

# Hull 参数
HULL_LENGTH = 55
HULL_MODE = "Hma"

# Binance API
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

    @staticmethod
    def calculate_hull_suite(df: pd.DataFrame, length: int) -> pd.Series:
        return TechnicalIndicators.calculate_hma(df['close'], length)


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

    ema_ut = close
    above = (ema_ut > xatr_trailing_stop) & (np.concatenate(([False], ema_ut[:-1] <= xatr_trailing_stop[:-1])))
    below = (ema_ut < xatr_trailing_stop) & (np.concatenate(([False], ema_ut[:-1] >= xatr_trailing_stop[:-1])))

    buy = (close > xatr_trailing_stop) & above
    sell = (close < xatr_trailing_stop) & below

    return {
        'xatr_trailing_stop': xatr_trailing_stop,
        'buy_signal': buy,
        'sell_signal': sell,
        'trend_up': close > xatr_trailing_stop
    }


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


def get_window_signal(df: pd.DataFrame, window_start_idx: int, ut_bot: dict, hull: pd.Series):
    """获取窗口开始时的信号"""
    if window_start_idx < HULL_LENGTH:
        return None

    # UT Bot 趋势
    ut_trend = "LONG" if ut_bot['trend_up'][window_start_idx] else "SHORT"

    # Hull 趋势（对比前2根）
    hull_trend = "LONG" if hull.iloc[window_start_idx] > hull.iloc[window_start_idx - 2] else "SHORT"

    # 综合信号
    if ut_trend == "LONG" and hull_trend == "LONG":
        return "LONG"
    elif ut_trend == "SHORT" and hull_trend == "SHORT":
        return "SHORT"
    else:
        return None  # 信号不一致，不交易


def run_backtest():
    """运行回测"""
    print("=" * 70)
    print("  UT Bot + Hull Suite 回测 (Polymarket 15分钟 BTC)")
    print("=" * 70)
    print()

    # 计算需要的K线数量（每天96根15分钟K线）
    limit = min(1000, BACKTEST_DAYS * 96 + 100)

    print(f"[配置] 回测天数: {BACKTEST_DAYS} 天")
    print(f"[配置] UT Bot: Key={UT_BOT_KEY_VALUE}, ATR Period={UT_BOT_ATR_PERIOD}")
    print(f"[配置] Hull: Length={HULL_LENGTH}")
    print()
    print("[获取] 正在下载历史K线数据...")

    df = fetch_klines(SYMBOL, INTERVAL, limit)

    if df is None or len(df) < HULL_LENGTH + UT_BOT_ATR_PERIOD + 10:
        print("[错误] 数据不足")
        return

    print(f"[完成] 已获取 {len(df)} 根K线")
    print(f"[时间范围] {df.index[0]} 到 {df.index[-1]}")
    print()

    # 计算指标
    print("[计算] UT Bot 信号...")
    ut_bot = calculate_ut_bot_signals(df, UT_BOT_KEY_VALUE, UT_BOT_ATR_PERIOD)

    print("[计算] Hull Suite...")
    hull = TechnicalIndicators.calculate_hull_suite(df, HULL_LENGTH)

    print("[开始] 回测中...")
    print()

    # 回测结果
    results = []
    total_windows = 0
    signal_count = 0
    win_count = 0

    # 从第 HULL_LENGTH 根K线开始（确保有足够数据计算指标）
    for i in range(HULL_LENGTH, len(df) - 1):
        total_windows += 1

        # 获取窗口开始时的信号
        signal = get_window_signal(df, i, ut_bot, hull)

        if signal is None:
            continue

        signal_count += 1

        # 窗口开始价格（当前K线的开盘价）
        entry_price = df['open'].iloc[i]

        # 窗口结束价格（下一根K线的收盘价）
        exit_price = df['close'].iloc[i + 1]

        # 实际方向（收盘价 > 开盘价 = UP）
        actual_direction = "LONG" if exit_price > entry_price else "SHORT"

        # 判断输赢
        is_win = (signal == actual_direction)
        if is_win:
            win_count += 1

        # 记录结果
        price_change_pct = (exit_price - entry_price) / entry_price * 100

        results.append({
            'timestamp': df.index[i],
            'signal': signal,
            'actual': actual_direction,
            'is_win': is_win,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'price_change_pct': price_change_pct
        })

    # 统计结果
    if signal_count > 0:
        win_rate = win_count / signal_count * 100
    else:
        win_rate = 0

    print("=" * 70)
    print("  回测结果")
    print("=" * 70)
    print()
    print(f"总窗口数: {total_windows}")
    print(f"产生信号: {signal_count}")
    print(f"胜率: {win_rate:.2f}%")
    print()

    # 分方向统计
    long_signals = [r for r in results if r['signal'] == 'LONG']
    short_signals = [r for r in results if r['signal'] == 'SHORT']

    if long_signals:
        long_wins = sum(1 for r in long_signals if r['is_win'])
        long_win_rate = long_wins / len(long_signals) * 100
        print(f"LONG 信号: {len(long_signals)} 笔 | 胜率: {long_win_rate:.2f}%")

    if short_signals:
        short_wins = sum(1 for r in short_signals if r['is_win'])
        short_win_rate = short_wins / len(short_signals) * 100
        print(f"SHORT 信号: {len(short_signals)} 笔 | 胜率: {short_win_rate:.2f}%")

    print()

    # 显示最近10笔交易
    print("[最近10笔交易]")
    print("-" * 70)
    for r in results[-10:]:
        win_mark = "[WIN]" if r['is_win'] else "[LOSE]"
        time_str = r['timestamp'].strftime('%m-%d %H:%M')
        print(f"{time_str} | {r['signal']:4s} | {win_mark} | 实际: {r['actual']:4s} | 涨跌: {r['price_change_pct']:+.2f}%")

    print("=" * 70)


if __name__ == "__main__":
    run_backtest()
