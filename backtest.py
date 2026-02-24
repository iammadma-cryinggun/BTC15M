#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest.py - Polymarket BTC 15min binary option backtest
Correct validation: win/loss based on window open price, not signal price
"""

import requests
import statistics
from collections import deque
from datetime import datetime
from typing import Tuple, Dict

PROXY = {'http': 'http://127.0.0.1:15236', 'https': 'http://127.0.0.1:15236'}


class StandardRSI:
    def __init__(self, period=14):
        self.period = period
        self.prices = []
        self.avg_gain = 0.0
        self.avg_loss = 0.0
        self.initialized = False

    def update(self, price: float):
        self.prices.append(price)
        if len(self.prices) < 2:
            return
        change = self.prices[-1] - self.prices[-2]
        gain = max(change, 0)
        loss = max(-change, 0)
        if not self.initialized and len(self.prices) >= self.period + 1:
            gains = [max(self.prices[i] - self.prices[i-1], 0) for i in range(1, self.period + 1)]
            losses = [max(self.prices[i-1] - self.prices[i], 0) for i in range(1, self.period + 1)]
            self.avg_gain = sum(gains) / self.period
            self.avg_loss = sum(losses) / self.period
            self.initialized = True
        elif self.initialized:
            self.avg_gain = (self.avg_gain * (self.period - 1) + gain) / self.period
            self.avg_loss = (self.avg_loss * (self.period - 1) + loss) / self.period

    def get_rsi(self) -> float:
        if not self.initialized:
            return 50.0
        if self.avg_loss == 0:
            return 100.0
        rs = self.avg_gain / self.avg_loss
        return 100 - (100 / (1 + rs))

    def is_ready(self) -> bool:
        return self.initialized


class StandardVWAP:
    def __init__(self):
        self.vwap_numerator = 0.0
        self.vwap_denominator = 0.0
        self.current_vwap = 0.0

    def update(self, price: float, volume: float = 1.0):
        self.vwap_numerator += price * volume
        self.vwap_denominator += volume
        if self.vwap_denominator > 0:
            self.current_vwap = self.vwap_numerator / self.vwap_denominator

    def get_vwap(self) -> float:
        return self.current_vwap


class StandardCCI:
    def __init__(self, period=20):
        self.period = period
        self.history = deque(maxlen=period)

    def update(self, high: float, low: float, close: float):
        hlc3 = (high + low + close) / 3.0
        self.history.append(hlc3)

    def get_cci(self) -> float:
        if len(self.history) < self.period:
            return 0.0
        data = list(self.history)
        mean = sum(data) / len(data)
        mad = sum(abs(x - mean) for x in data) / len(data)
        if mad == 0:
            return 0.0
        return (data[-1] - mean) / (0.015 * mad)

    def is_ready(self) -> bool:
        return len(self.history) >= self.period


class StandardATR:
    """Average True Range"""
    def __init__(self, period=14):
        self.period = period
        self.history = deque(maxlen=period)
        self.prev_close = None
        self.atr = 0.0

    def update(self, high: float, low: float, close: float):
        if self.prev_close is not None:
            tr = max(high - low, abs(high - self.prev_close), abs(low - self.prev_close))
        else:
            tr = high - low
        self.history.append(tr)
        if len(self.history) >= self.period:
            self.atr = sum(self.history) / len(self.history)
        self.prev_close = close

    def get_atr(self) -> float:
        return self.atr

    def is_ready(self) -> bool:
        return len(self.history) >= self.period


class StandardBBands:
    """Bollinger Bands"""
    def __init__(self, period=20, std_dev=2.0):
        self.period = period
        self.std_dev = std_dev
        self.history = deque(maxlen=period)

    def update(self, price: float):
        self.history.append(price)

    def get_bands(self):
        if len(self.history) < self.period:
            return None, None, None
        data = list(self.history)
        mean = sum(data) / len(data)
        variance = sum((x - mean) ** 2 for x in data) / len(data)
        std = variance ** 0.5
        upper = mean + self.std_dev * std
        lower = mean - self.std_dev * std
        return upper, mean, lower

    def get_position(self, price: float) -> float:
        """返回价格在布林带中的位置: -1(下轨) ~ 0(中轨) ~ +1(上轨)"""
        upper, mid, lower = self.get_bands()
        if upper is None or upper == lower:
            return 0.0
        return (price - mid) / (upper - mid)

    def is_ready(self) -> bool:
        return len(self.history) >= self.period


class V5SignalScorer:
    def __init__(self):
        self.weights = {
            'price_momentum': 1.0,
            'volatility': 0.5,
            'vwap_status': 1.0,
            'rsi_status': 1.0,
            'trend_strength': 0.8,
            'cci_status': 0.0,
            'orderbook_bias': 0.5,
            'atr_filter': 1.0,    # ATR波动率过滤
            'bbands_position': 1.0,  # 布林带位置
        }

    def calculate_score(self, price: float, rsi: float, vwap: float,
                        price_history: list, cci: float = 0.0,
                        atr: float = 0.0, bb_position: float = 0.0) -> Tuple[float, Dict]:
        score = 0.0
        components = {}

        if len(price_history) >= 3:
            momentum = (price_history[-1] - price_history[-3]) / price_history[-3] * 100 if price_history[-3] > 0 else 0
            mom_score = max(-5, min(5, momentum * 2))
            components['price_momentum'] = mom_score
            score += mom_score * self.weights['price_momentum']
        else:
            components['price_momentum'] = 0

        if len(price_history) >= 5:
            vol = statistics.stdev(price_history[-5:])
            norm_vol = min(vol / 0.1, 1.0)
            vol_score = (norm_vol - 0.5) * 10
            components['volatility'] = vol_score
            score += vol_score * self.weights['volatility']
        else:
            components['volatility'] = 0

        if vwap > 0:
            vwap_dist = (price - vwap) / vwap * 100
            if vwap_dist > 0.5:
                components['vwap_status'] = 1
            elif vwap_dist < -0.5:
                components['vwap_status'] = -1
            else:
                components['vwap_status'] = 0
            score += components['vwap_status'] * self.weights['vwap_status'] * 5
        else:
            components['vwap_status'] = 0

        is_extreme = rsi > 70 or rsi < 30
        if rsi > 70:
            components['rsi_status'] = -1
        elif rsi < 30:
            components['rsi_status'] = 1
        else:
            components['rsi_status'] = 0
        score += components['rsi_status'] * self.weights['rsi_status'] * 5

        if len(price_history) >= 3:
            short_trend = (price_history[-1] - price_history[-3]) / price_history[-3] * 100 if price_history[-3] > 0 else 0
            trend_score = max(-5, min(5, short_trend * 3))
            components['trend_strength'] = trend_score
            score += trend_score * self.weights['trend_strength']
        else:
            components['trend_strength'] = 0

        if cci > 100:
            cci_score = 1
        elif cci < -100:
            cci_score = -1
        else:
            cci_score = cci / 100.0
        components['cci_status'] = cci_score
        cci_weight = self.weights['cci_status'] * (3.0 if is_extreme else 1.0)
        score += cci_score * cci_weight * 5

        # ATR 过滤：ATR 相对价格的比例，波动大时信号更可靠
        if atr > 0 and price > 0:
            atr_pct = atr / price * 100
            # ATR > 0.1% 认为有足够波动，加分；< 0.05% 太平静，减分
            if atr_pct > 0.1:
                atr_score = min(atr_pct * 10, 2.0)
            else:
                atr_score = -1.0
            components['atr_filter'] = atr_score
            score += atr_score * self.weights['atr_filter']
        else:
            components['atr_filter'] = 0

        # 布林带位置：价格在上轨附近偏空，下轨附近偏多（均值回归）
        # bb_position: -1(下轨) ~ 0(中轨) ~ +1(上轨)
        if bb_position != 0.0:
            bb_score = -bb_position * 2.0  # 反转信号：上轨做空，下轨做多
            components['bbands_position'] = bb_score
            score += bb_score * self.weights['bbands_position']
        else:
            components['bbands_position'] = 0

        score = max(-10, min(10, score))
        return score, components


def fetch_klines(symbol: str, interval: str, limit: int = 500) -> list:
    url = 'https://api.binance.com/api/v3/klines'
    try:
        resp = requests.get(url, params={'symbol': symbol, 'interval': interval, 'limit': limit},
                            proxies=PROXY, timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f'[ERROR] fetch_klines: {e}')
    return []


def run_backtest(min_score: float = 2.5, min_confidence: float = 0.30, use_cci: bool = True):
    print('=' * 70)
    print(f'Backtest: min_score={min_score}, min_conf={min_confidence}, CCI={"ON" if use_cci else "OFF"}')
    print('Validation: win/loss vs 15min window OPEN price (Polymarket logic)')
    print('=' * 70)

    # Use 1m klines to simulate intra-window signal detection
    print('Fetching 1m klines (1500 bars = ~25h)...')
    klines_1m = fetch_klines('BTCUSDT', '1m', 1500)
    print(f'Got {len(klines_1m)} bars\n')
    if not klines_1m:
        print('[ERROR] No data')
        return

    # Group into 15-min windows
    windows = []
    i = 0
    while i + 15 <= len(klines_1m):
        w = klines_1m[i:i+15]
        windows.append({
            'open': float(w[0][1]),
            'close': float(w[14][4]),
            'klines': w,
            'time': datetime.fromtimestamp(int(w[0][0]) / 1000).strftime('%m-%d %H:%M'),
        })
        i += 15
    print(f'Total windows: {len(windows)}\n')

    scorer = V5SignalScorer()
    scorer_no_new = V5SignalScorer()
    scorer_no_new.weights['atr_filter'] = 0.0
    scorer_no_new.weights['bbands_position'] = 0.0

    rsi = StandardRSI(period=14)
    vwap = StandardVWAP()
    price_history = deque(maxlen=20)
    cci_calc = StandardCCI(period=20)
    atr_calc = StandardATR(period=14)
    bb_calc = StandardBBands(period=20)

    # Warmup with first 3 windows
    for w in windows[:3]:
        for k in w['klines']:
            close = float(k[4])
            rsi.update(close)
            vwap.update(close, float(k[5]))
            price_history.append(close)
            cci_calc.update(float(k[2]), float(k[3]), close)
            atr_calc.update(float(k[2]), float(k[3]), close)
            bb_calc.update(close)

    results = []
    results_no_cci = []

    for w in windows[3:]:
        window_open = w['open']
        window_close = w['close']
        actual_up = window_close > window_open

        signal_found = False
        signal_found_no_cci = False

        for j, k in enumerate(w['klines'][:8]):
            close = float(k[4])
            volume = float(k[5])
            high = float(k[2])
            low = float(k[3])

            rsi.update(close)
            vwap.update(close, volume)
            price_history.append(close)
            cci_calc.update(high, low, close)
            atr_calc.update(high, low, close)
            bb_calc.update(close)

            if not rsi.is_ready():
                continue

            cci_val = cci_calc.get_cci() if use_cci else 0.0
            atr_val = atr_calc.get_atr() if atr_calc.is_ready() else 0.0
            bb_pos = bb_calc.get_position(close) if bb_calc.is_ready() else 0.0

            if not signal_found:
                score, _ = scorer.calculate_score(close, rsi.get_rsi(), vwap.get_vwap(), list(price_history), cci_val, atr_val, bb_pos)
                conf = min(abs(score) / 5.0, 0.99)
                if score >= min_score and conf >= min_confidence:
                    results.append({'direction': 'LONG', 'score': score, 'cci': cci_val,
                                    'correct': actual_up, 'time': w['time']})
                    signal_found = True
                elif score <= -min_score and conf >= min_confidence:
                    results.append({'direction': 'SHORT', 'score': score, 'cci': cci_val,
                                    'correct': not actual_up, 'time': w['time']})
                    signal_found = True

            if not signal_found_no_cci:
                score2, _ = scorer_no_new.calculate_score(close, rsi.get_rsi(), vwap.get_vwap(), list(price_history), 0.0, 0.0, 0.0)
                conf2 = min(abs(score2) / 5.0, 0.99)
                if score2 >= min_score and conf2 >= min_confidence:
                    results_no_cci.append({'correct': actual_up})
                    signal_found_no_cci = True
                elif score2 <= -min_score and conf2 >= min_confidence:
                    results_no_cci.append({'correct': not actual_up})
                    signal_found_no_cci = True

        for k in w['klines'][8:]:
            close = float(k[4])
            rsi.update(close)
            vwap.update(close, float(k[5]))
            price_history.append(close)
            cci_calc.update(float(k[2]), float(k[3]), close)
            atr_calc.update(float(k[2]), float(k[3]), close)
            bb_calc.update(close)

    if not results:
        print('No signals generated')
        return

    total = len(results)
    correct = sum(1 for r in results if r['correct'])
    accuracy = correct / total * 100
    long_r = [r for r in results if r['direction'] == 'LONG']
    short_r = [r for r in results if r['direction'] == 'SHORT']
    long_acc = sum(1 for r in long_r if r['correct']) / len(long_r) * 100 if long_r else 0
    short_acc = sum(1 for r in short_r if r['correct']) / len(short_r) * 100 if short_r else 0

    print('=' * 70)
    print(f'Total signals: {total}  |  Correct: {correct}  |  Accuracy: {accuracy:.1f}%')
    print(f'LONG:  {len(long_r)} signals, accuracy {long_acc:.1f}%')
    print(f'SHORT: {len(short_r)} signals, accuracy {short_acc:.1f}%')
    print()

    if use_cci:
        print('[ CCI Range Analysis ]')
        cci_ranges = [
            ('Strong UP  CCI>200',  lambda r: r['cci'] > 200),
            ('Mild UP  100~200',    lambda r: 100 < r['cci'] <= 200),
            ('Neutral -100~100',    lambda r: -100 <= r['cci'] <= 100),
            ('Mild DN -200~-100',   lambda r: -200 <= r['cci'] < -100),
            ('Strong DN CCI<-200',  lambda r: r['cci'] < -200),
        ]
        print(f"  {'Range':<22} {'N':>5} {'OK':>5} {'Acc':>8}")
        print(f"  {'-'*22} {'-'*5} {'-'*5} {'-'*8}")
        for name, cond in cci_ranges:
            filtered = [r for r in results if cond(r)]
            if filtered:
                acc = sum(1 for r in filtered if r['correct']) / len(filtered) * 100
                print(f"  {name:<22} {len(filtered):>5} {sum(1 for r in filtered if r['correct']):>5} {acc:>7.1f}%")
        print()

    print('[ Score Range Analysis ]')
    score_ranges = [
        ('Strong LONG >=8',    lambda r: r['score'] >= 8),
        ('Mild LONG 5~8',      lambda r: 5 <= r['score'] < 8),
        ('Weak LONG 2.5~5',    lambda r: 2.5 <= r['score'] < 5),
        ('Weak SHORT -5~-2.5', lambda r: -5 < r['score'] <= -2.5),
        ('Mild SHORT -8~-5',   lambda r: -8 < r['score'] <= -5),
        ('Strong SHORT <=-8',  lambda r: r['score'] <= -8),
    ]
    print(f"  {'Range':<22} {'N':>5} {'OK':>5} {'Acc':>8}")
    print(f"  {'-'*22} {'-'*5} {'-'*5} {'-'*8}")
    for name, cond in score_ranges:
        filtered = [r for r in results if cond(r)]
        if filtered:
            acc = sum(1 for r in filtered if r['correct']) / len(filtered) * 100
            print(f"  {name:<22} {len(filtered):>5} {sum(1 for r in filtered if r['correct']):>5} {acc:>7.1f}%")
    print()

    print('[ CCI Impact ]')
    if results_no_cci:
        acc_no_cci = sum(1 for r in results_no_cci if r['correct']) / len(results_no_cci) * 100
        print(f'  Without CCI: {len(results_no_cci)} signals, accuracy {acc_no_cci:.1f}%')
    print(f'  With CCI:    {total} signals, accuracy {accuracy:.1f}%')
    delta = accuracy - (acc_no_cci if results_no_cci else accuracy)
    print(f'  CCI contribution: {delta:+.1f}%')
    print('=' * 70)


if __name__ == '__main__':
    run_backtest(min_score=2.5, min_confidence=0.30, use_cci=True)
