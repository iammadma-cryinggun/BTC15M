#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Binance WebSocket数据源 - 简化版
直接集成到auto_trader_ankr.py，像RSI一样处理
"""

import asyncio
import websockets
import json
import time
import threading
from collections import deque
from typing import Dict, Optional
import requests


class BinanceWebSocket:
    """
    Binance实时数据源（后台线程运行）

    像RSI一样，只是个数据采集器
    主程序直接从self.data读取数据
    """

    def __init__(self):
        # === 数据存储（线程安全） ===
        self.data = {
            'cvd_1m': 0.0,
            'cvd_5m': 0.0,
            'buy_wall': 0.0,
            'sell_wall': 0.0,
            'last_price': 0.0,
            'macd_histogram': 0.0,
            'delta_z_score': 0.0,
            'momentum_30s': 0.0,
            'momentum_60s': 0.0,
            'momentum_120s': 0.0,
            'signal_score': 0.0,
            'direction': 'NEUTRAL',
            'timestamp': 0,
        }

        # === 内部计算数据 ===
        self.cvd_short = 0.0
        self.cvd_long = 0.0
        self.cvd_window_short = deque(maxlen=10000)  # 1分钟窗口
        self.cvd_window_long = deque(maxlen=50000)    # 5分钟窗口
        self.cvd_history = deque(maxlen=100)          # 用于MACD/Z-Score

        self.buy_wall = 0.0
        self.sell_wall = 0.0
        self.buy_wall_history = deque(maxlen=10)
        self.sell_wall_history = deque(maxlen=10)

        self.price_history = deque(maxlen=150)  # 150秒用于120s动量
        self.trade_count = 0

        # === 后台线程 ===
        self.thread = None
        self.running = False
        self.loop = None

    def start(self):
        """启动后台线程"""
        if self.thread and self.thread.is_alive():
            return

        self.running = True
        self.thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.thread.start()
        print("[BINANCE WS] 后台线程已启动")

    def stop(self):
        """停止后台线程"""
        self.running = False
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)

    def _run_event_loop(self):
        """在新线程中运行asyncio事件循环"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        try:
            self.loop.run_until_complete(self._connect_all())
        except Exception as e:
            print(f"[BINANCE WS] 后台线程异常: {e}")
            # 自动重启
            time.sleep(5)
            if self.running:
                self._run_event_loop()

    async def _connect_all(self):
        """并发运行所有WebSocket连接"""
        await asyncio.gather(
            self._listen_trades(),
            self._listen_depth(),
        )

    async def _listen_trades(self):
        """监听逐笔成交"""
        url = "wss://stream.binance.com:9443/ws/btcusdt@aggTrade"

        while self.running:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    print("[BINANCE WS] AggTrade 已连接")

                    while self.running:
                        msg = await ws.recv()
                        data = json.loads(msg)

                        qty = float(data['q'])
                        price = float(data['p'])
                        is_buyer_maker = data['m']

                        self._update_trades(price, qty, is_buyer_maker)

            except Exception as e:
                print(f"[BINANCE WS] AggTrade 断开: {e}, 3秒后重连...")
                await asyncio.sleep(3)

    async def _listen_depth(self):
        """监听盘口深度"""
        url = "wss://stream.binance.com:9443/ws/btcusdt@depth20@100ms"

        while self.running:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    print("[BINANCE WS] Depth 已连接")

                    while self.running:
                        msg = await ws.recv()
                        data = json.loads(msg)

                        self._update_depth(data)

            except Exception as e:
                print(f"[BINANCE WS] Depth 断开: {e}, 3秒后重连...")
                await asyncio.sleep(3)

    def _update_trades(self, price: float, qty: float, is_buyer_maker: bool):
        """更新成交数据"""
        now = time.time()

        # 更新价格
        self.data['last_price'] = price
        self.price_history.append((now, price))

        # CVD计算
        delta = (qty * price) if not is_buyer_maker else -(qty * price)

        # 更新1分钟窗口
        cutoff_short = now - 60
        while self.cvd_window_short and self.cvd_window_short[0][0] < cutoff_short:
            _, old_delta = self.cvd_window_short.popleft()
            self.cvd_short -= old_delta

        self.cvd_window_short.append((now, delta))
        self.cvd_short += delta

        # 更新5分钟窗口
        cutoff_long = now - 300
        while self.cvd_window_long and self.cvd_window_long[0][0] < cutoff_long:
            _, old_delta = self.cvd_window_long.popleft()
            self.cvd_long -= old_delta

        self.cvd_window_long.append((now, delta))
        self.cvd_long += delta

        # 每10笔记录一次CVD历史
        self.trade_count += 1
        if self.trade_count % 10 == 0:
            self.cvd_history.append(self.cvd_long)

        # 计算信号分数
        self._calc_signal()

        # 更新公开数据
        self.data['cvd_1m'] = self.cvd_short
        self.data['cvd_5m'] = self.cvd_long
        self.data['timestamp'] = now

    def _update_depth(self, data: dict):
        """更新盘口数据"""
        self.buy_wall = sum(float(b[1]) for b in data['bids'])
        self.sell_wall = sum(float(a[1]) for a in data['asks'])

        # 平滑处理
        self.buy_wall_history.append(self.buy_wall)
        self.sell_wall_history.append(self.sell_wall)

        # 更新公开数据
        self.data['buy_wall'] = self.buy_wall
        self.data['sell_wall'] = self.sell_wall

    def _calc_momentum(self) -> tuple:
        """计算超短动量（30s/60s/120s）"""
        now = time.time()
        momentum_30s = 0.0
        momentum_60s = 0.0
        momentum_120s = 0.0

        # 提取最近的价格数据
        prices_30s = [p for t, p in self.price_history if now - t <= 30]
        prices_60s = [p for t, p in self.price_history if now - t <= 60]
        prices_120s = [p for t, p in self.price_history if now - t <= 120]

        if len(prices_30s) >= 2:
            momentum_30s = (prices_30s[-1] - prices_30s[0]) / prices_30s[0] * 100

        if len(prices_60s) >= 2:
            momentum_60s = (prices_60s[-1] - prices_60s[0]) / prices_60s[0] * 100

        if len(prices_120s) >= 2:
            momentum_120s = (prices_120s[-1] - prices_120s[0]) / prices_120s[0] * 100

        return momentum_30s, momentum_60s, momentum_120s

    def _calc_macd(self) -> float:
        """计算CVD的MACD柱状图"""
        if len(self.cvd_history) < 26:
            return 0.0

        import pandas as pd
        series = pd.Series(list(self.cvd_history))

        # MACD参数：快12，慢26，信号9
        ema_fast = series.ewm(span=12, adjust=False).mean()
        ema_slow = series.ewm(span=26, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal_line

        return float(histogram.iloc[-1]) if len(histogram) > 0 else 0.0

    def _calc_z_score(self) -> float:
        """计算CVD的Z-Score（偏离度）"""
        if len(self.cvd_history) < 20:
            return 0.0

        import pandas as pd
        import numpy as np
        series = pd.Series(list(self.cvd_history))

        rolling_mean = series.rolling(window=20).mean()
        rolling_std = series.rolling(window=20).std()

        z_score = (series - rolling_mean) / rolling_std
        return float(z_score.iloc[-1]) if len(z_score) > 0 else 0.0

    def _calc_signal(self):
        """计算综合信号分数和所有指标"""
        # 超短动量
        mom_30s, mom_60s, mom_120s = self._calc_momentum()

        # MACD和Z-Score
        macd_histogram = self._calc_macd()
        delta_z_score = self._calc_z_score()

        # CVD评分
        cvd_short_score = max(-3.0, min(3.0, self.cvd_short / 50000.0))
        cvd_long_score = max(-5.0, min(5.0, self.cvd_long / 150000.0))

        # 融合：短窗口60% + 长窗口40%
        cvd_score = cvd_short_score * 0.6 + cvd_long_score * 0.4

        # 盘口失衡
        total_wall = self.buy_wall + self.sell_wall
        imbalance = (self.buy_wall - self.sell_wall) / total_wall if total_wall > 0 else 0.0

        # 综合分数
        score = cvd_score + (imbalance * 5.0)

        # 更新公开数据
        self.data['momentum_30s'] = mom_30s
        self.data['momentum_60s'] = mom_60s
        self.data['momentum_120s'] = mom_120s
        self.data['macd_histogram'] = macd_histogram
        self.data['delta_z_score'] = delta_z_score
        self.data['signal_score'] = score
        self.data['direction'] = 'LONG' if score > 0 else 'SHORT'

    def get_data(self) -> dict:
        """获取当前数据（线程安全）"""
        return self.data.copy()


# 单例模式
_binance_ws = None

def get_binance_ws() -> BinanceWebSocket:
    """获取Binance WebSocket单例"""
    global _binance_ws
    if _binance_ws is None:
        _binance_ws = BinanceWebSocket()
        _binance_ws.start()
    return _binance_ws
