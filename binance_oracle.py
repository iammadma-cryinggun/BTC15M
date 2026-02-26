#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Binance Oracle - 15分钟高频先知系统
专门为 Polymarket 15分钟大盘预测提供"抢跑"数据

输出文件: oracle_signal.json (供 auto_trader_ankr.py 读取)

升级版：集成 UT Bot + Hull Suite 趋势过滤
- Binance Oracle: 高频订单流信号（极速扳机）
- UT Bot + Hull: 技术趋势过滤（方向观察员）
"""

import asyncio
import websockets
import json
import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from collections import deque

# 代理配置
PROXY = os.getenv('HTTP_PROXY', os.getenv('HTTPS_PROXY', ''))

# 信号输出路径（与 auto_trader_ankr.py 同目录）
SIGNAL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'oracle_signal.json')

# CVD滚动窗口（秒）
CVD_WINDOW_SEC = 900  # 15分钟

# UT Bot + Hull 参数（优化后的最佳参数）
UT_BOT_KEY_VALUE = 2.0  # 🔥 修复：从0.5提高到2.0，避免过于敏感
UT_BOT_ATR_PERIOD = 10
HULL_LENGTH = 34


class TechnicalIndicators:
    """技术指标计算类"""

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


class BinanceOracle:
    def __init__(self):
        self.cvd = 0.0                          # 累计主动买卖量差
        self.cvd_window = deque()               # (timestamp, delta) 滚动窗口
        self.buy_wall = 0.0                     # 盘口买单墙（实时值）
        self.sell_wall = 0.0                    # 盘口卖单墙（实时值）
        self.buy_wall_history = deque(maxlen=10) # 买单墙历史（用于平滑）
        self.sell_wall_history = deque(maxlen=10) # 卖墙历史（用于平滑）
        self.last_price = 0.0                   # 最新成交价
        self.trade_count = 0                    # 成交笔数
        self.last_signal_score = 0.0            # 上次信号分
        self.last_write_time = 0                # 上次写文件时间

        # UT Bot + Hull K线数据存储
        self.klines_data = []                   # 存储 K 线数据
        self.max_klines = 200                   # 最多存储200根K线

        print("[ORACLE] Binance Oracle initialized...")
        print(f"[ORACLE] Signal output: {SIGNAL_FILE}")
        print(f"[ORACLE] UT Bot: Key={UT_BOT_KEY_VALUE}, ATR={UT_BOT_ATR_PERIOD}")
        print(f"[ORACLE] Hull MA: Length={HULL_LENGTH}")

    async def load_historical_klines(self):
        """启动时加载历史K线数据（解决UT Bot一直NEUTRAL的问题）"""
        try:
            print("[ORACLE] Loading historical K-lines from Binance...")
            url = "https://api.binance.com/api/v3/klines"
            params = {
                'symbol': 'BTCUSDT',
                'interval': '15m',
                'limit': 200
            }

            proxies = {'http': PROXY, 'https': PROXY} if PROXY else None
            response = requests.get(url, params=params, timeout=10, proxies=proxies)
            response.raise_for_status()
            data = response.json()

            for kline in data:
                self.add_kline(
                    kline[0],      # timestamp
                    float(kline[1]),  # open
                    float(kline[2]),  # high
                    float(kline[3]),  # low
                    float(kline[4]),  # close
                    float(kline[5])   # volume
                )

            print(f"[ORACLE] Loaded {len(self.klines_data)} historical K-lines")

            # 立即计算一次趋势
            trend = self.get_ut_bot_hull_trend()
            print(f"[ORACLE] Current UT Bot + Hull trend: {trend or 'CALCULATING...'}")

        except Exception as e:
            print(f"[ORACLE] Failed to load historical K-lines: {e}")
            print(f"         Will wait for WebSocket to collect enough K-line data (~16 hours)")

    def _trim_cvd_window(self):
        """裁剪超出窗口的旧数据"""
        cutoff = time.time() - CVD_WINDOW_SEC
        while self.cvd_window and self.cvd_window[0][0] < cutoff:
            _, delta = self.cvd_window.popleft()
            self.cvd -= delta

    def _calc_signal_score(self) -> float:
        """
        计算综合信号分 (-10 到 +10)
        - CVD贡献：±5分（每40万USD得1分，200万USD满分）
        - 盘口失衡贡献：±5分（使用10次移动平均平滑噪音）
        """
        score = 0.0

        # CVD分（归一化，以200万USD为满分基准，每40万USD得1分）
        cvd_score = max(-5.0, min(5.0, self.cvd / 400000.0))
        score += cvd_score

        # 盘口失衡分（使用移动平均平滑）
        avg_buy_wall = sum(self.buy_wall_history) / len(self.buy_wall_history) if self.buy_wall_history else 0
        avg_sell_wall = sum(self.sell_wall_history) / len(self.sell_wall_history) if self.sell_wall_history else 0
        total_wall = avg_buy_wall + avg_sell_wall
        if total_wall > 0:
            imbalance = (avg_buy_wall - avg_sell_wall) / total_wall
            wall_score = imbalance * 5.0
            score += wall_score

        return round(max(-10.0, min(10.0, score)), 3)

    def add_kline(self, timestamp, open_price, high, low, close, volume):
        """添加新的 K 线数据（旧方法，保持兼容）"""
        kline = {
            'timestamp': timestamp,
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume,
            'closed': True  # 默认为已闭合
        }
        self.klines_data.append(kline)
        if len(self.klines_data) > self.max_klines:
            self.klines_data.pop(0)

    def add_kline_with_closed(self, timestamp, open_price, high, low, close, volume, is_closed):
        """添加新的 K 线数据（带闭合状态）"""
        kline = {
            'timestamp': timestamp,
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume,
            'closed': is_closed
        }
        self.klines_data.append(kline)
        if len(self.klines_data) > self.max_klines:
            self.klines_data.pop(0)

    def get_ut_bot_hull_trend(self):
        """获取 UT Bot + Hull 趋势判断"""
        if len(self.klines_data) < max(UT_BOT_ATR_PERIOD, HULL_LENGTH) + 5:
            return None  # 数据不足

        # 转换为 DataFrame
        df = pd.DataFrame(self.klines_data)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

        # 计算 UT Bot 信号
        close = df['close'].values
        atr = TechnicalIndicators.calculate_atr(df, UT_BOT_ATR_PERIOD).values
        n_loss = UT_BOT_KEY_VALUE * atr

        xatr_trailing_stop = np.zeros(len(df))
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

        ut_trend = close[-1] > xatr_trailing_stop[-1]

        # 计算 Hull MA
        hull = TechnicalIndicators.calculate_hma(df['close'], HULL_LENGTH)
        hull_trend = hull.iloc[-1] > hull.iloc[-3]

        # 综合判断
        if ut_trend and hull_trend:
            return "LONG"
        elif (not ut_trend) and (not hull_trend):
            return "SHORT"
        else:
            return "NEUTRAL"  # 信号不一致，中性

    def _write_signal(self):
        """每秒写一次信号文件供 V6 引擎读取"""
        now = time.time()
        if now - self.last_write_time < 1.0:
            return
        self.last_write_time = now

        self._trim_cvd_window()
        score = self._calc_signal_score()
        self.last_signal_score = score

        total_wall = self.buy_wall + self.sell_wall
        imbalance = (self.buy_wall - self.sell_wall) / total_wall if total_wall > 0 else 0.0

        # 计算 UT Bot + Hull 趋势
        ut_hull_trend = self.get_ut_bot_hull_trend()

        signal = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'ts_unix': now,
            'signal_score': score,
            'direction': 'LONG' if score > 0 else 'SHORT',
            'cvd_15m': round(self.cvd, 4),
            'buy_wall': round(self.buy_wall, 2),
            'sell_wall': round(self.sell_wall, 2),
            'wall_imbalance': round(imbalance, 4),
            'last_price': self.last_price,
            'trade_count': self.trade_count,
            # UT Bot + Hull 趋势字段
            'ut_hull_trend': ut_hull_trend if ut_hull_trend else 'NEUTRAL',
        }

        try:
            tmp = SIGNAL_FILE + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(signal, f)
            os.replace(tmp, SIGNAL_FILE)  # 原子写入，防止读到半截文件
        except Exception as e:
            print(f"[ORACLE] Failed to write signal file: {e}")

    async def listen_trades(self):
        """监听逐笔成交：捕捉主力资金的主动吃单"""
        url = "wss://stream.binance.com:9443/ws/btcusdt@aggTrade"
        while True:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    print("[WS] Connected to Binance AggTrade stream")
                    while True:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        qty = float(data['q'])
                        price = float(data['p'])
                        is_buyer_maker = data['m']

                        self.last_price = price
                        self.trade_count += 1

                        # CVD：主动买入+，主动卖出-（用成交额加权）
                        delta = (qty * price) if not is_buyer_maker else -(qty * price)
                        self.cvd_window.append((time.time(), delta))
                        self.cvd += delta

                        self._write_signal()
            except Exception as e:
                print(f"[ORACLE] AggTrade disconnected: {e}, reconnecting in 3s...")
                await asyncio.sleep(3)

    async def listen_depth(self):
        """监听盘口深度：捕捉做市商的挂单墙"""
        url = "wss://stream.binance.com:9443/ws/btcusdt@depth20@100ms"
        while True:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    print("[WS] Connected to Binance Depth stream")
                    while True:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        # 更新实时值
                        self.buy_wall = sum(float(b[1]) for b in data['bids'])
                        self.sell_wall = sum(float(a[1]) for a in data['asks'])
                        # 推入历史记录（用于平滑）
                        self.buy_wall_history.append(self.buy_wall)
                        self.sell_wall_history.append(self.sell_wall)
            except Exception as e:
                print(f"[ORACLE] Depth disconnected: {e}, reconnecting in 3s...")
                await asyncio.sleep(3)

    async def listen_klines(self):
        """监听 K 线数据：用于 UT Bot + Hull 计算"""
        url = "wss://stream.binance.com:9443/ws/btcusdt@kline_15m"
        while True:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    print("[WS] Connected to Binance 15min K-line stream (for UT Bot + Hull)")
                    while True:
                        msg = await ws.recv()
                        data = json.loads(msg)

                        kline = data.get('k', {})
                        is_closed = kline.get('x', False)
                        kline_timestamp = kline['t']
                        kline_open = float(kline['o'])
                        kline_high = float(kline['h'])
                        kline_low = float(kline['l'])
                        kline_close = float(kline['c'])
                        kline_volume = float(kline['v'])

                        # 🔥 关键修复：实时更新未闭合的K线，避免14分钟滞后
                        if not self.klines_data:
                            # 第一次添加K线
                            self.add_kline_with_closed(kline_timestamp, kline_open, kline_high, kline_low, kline_close, kline_volume, is_closed)
                        elif self.klines_data[-1].get('timestamp') == kline_timestamp:
                            # 同一根K线，更新未闭合的数据
                            if not is_closed:
                                self.klines_data[-1]['high'] = max(self.klines_data[-1]['high'], kline_high)
                                self.klines_data[-1]['low'] = min(self.klines_data[-1]['low'], kline_low)
                                self.klines_data[-1]['close'] = kline_close
                                self.klines_data[-1]['volume'] = kline_volume
                                self.klines_data[-1]['closed'] = is_closed
                        else:
                            # 新的K线
                            if is_closed or self.klines_data[-1].get('closed', True):
                                # 上一根已闭合，追加新K线
                                self.add_kline_with_closed(kline_timestamp, kline_open, kline_high, kline_low, kline_close, kline_volume, is_closed)

                                # 每10根K线打印一次趋势
                                if len(self.klines_data) % 10 == 0:
                                    trend = self.get_ut_bot_hull_trend()
                                    print(f"[KLINE] Collected {len(self.klines_data)} bars | UT+Hull trend: {trend or 'CALCULATING...'}")
                            else:
                                # 上一根未闭合但来了新K线，先闭合上一根再添加新K线
                                self.klines_data[-1]['closed'] = True
                                self.add_kline_with_closed(kline_timestamp, kline_open, kline_high, kline_low, kline_close, kline_volume, is_closed)

            except Exception as e:
                print(f"[ORACLE] K-line disconnected: {e}, reconnecting in 3s...")
                await asyncio.sleep(3)

    async def print_status(self):
        """每2秒打印一次状态"""
        while True:
            await asyncio.sleep(2)
            # 使用平滑后的盘口值
            avg_buy = sum(self.buy_wall_history) / len(self.buy_wall_history) if self.buy_wall_history else self.buy_wall
            avg_sell = sum(self.sell_wall_history) / len(self.sell_wall_history) if self.sell_wall_history else self.sell_wall
            total_wall = avg_buy + avg_sell
            imbalance = (avg_buy - avg_sell) / total_wall if total_wall > 0 else 0.0
            score = self.last_signal_score

            # UT Bot + Hull 趋势
            ut_hull = self.get_ut_bot_hull_trend()

            now = datetime.now().strftime("%H:%M:%S")
            color = "\033[92m" if score > 0 else "\033[91m"
            reset = "\033[0m"

            ut_hull_color = "\033[92m" if ut_hull == "LONG" else "\033[91m" if ut_hull == "SHORT" else "\033[93m"

            print(f"[{now}] ORACLE | Score: {color}{score:+.2f}{reset} | "
                  f"CVD(15m): {color}{self.cvd:+.1f} USD{reset} | "
                  f"Imbalance: {imbalance*100:+.1f}% | "
                  f"UT+Hull: {ut_hull_color}{ut_hull or 'CALC'}{reset} | "
                  f"BTC: {self.last_price:.1f}")

    async def run(self):
        """并发运行所有监听器"""
        # 先加载历史K线数据（解决UT Bot一直NEUTRAL的问题）
        await self.load_historical_klines()

        await asyncio.gather(
            self.listen_trades(),
            self.listen_depth(),
            self.listen_klines(),  # 新增：K线监听
            self.print_status(),
        )


if __name__ == "__main__":
    oracle = BinanceOracle()
    try:
        asyncio.run(oracle.run())
    except KeyboardInterrupt:
        print("\n[ORACLE] Shutdown complete.")
