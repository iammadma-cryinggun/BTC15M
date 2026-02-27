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
# 🎯 黄金分割版：5分钟（300秒）- 既能看清趋势，又不至于太迟钝
# 理由：过滤短线假动作和微观噪音，在15分钟期权周期取得最佳胜率
CVD_WINDOW_SEC = 300

# UT Bot + Hull 参数（默认值）- 硬编码默认值，可被 oracle_params.json 覆盖
UT_BOT_KEY_VALUE = 1.8  # 敏感度：添加1h大趋势锁后，5分钟可以更敏感（快速翻色抢跑）
UT_BOT_ATR_PERIOD = 10  # ATR周期
HULL_LENGTH = 20        # Hull MA周期（过去5小时）

# 动态参数文件路径（支持 DATA_DIR 环境变量）
_DATA_DIR = os.getenv('DATA_DIR', os.path.dirname(os.path.abspath(__file__)))
ORACLE_PARAMS_FILE = os.path.join(_DATA_DIR, 'oracle_params.json')

# 参数热更新间隔（秒）
PARAMS_RELOAD_INTERVAL = 300  # 5分钟


def load_oracle_params() -> dict:
    """从 oracle_params.json 加载动态参数，失败时返回硬编码默认值"""
    defaults = {
        'ut_bot_key_value': UT_BOT_KEY_VALUE,
        'ut_bot_atr_period': UT_BOT_ATR_PERIOD,
        'hull_length': HULL_LENGTH,
    }
    try:
        if os.path.exists(ORACLE_PARAMS_FILE):
            with open(ORACLE_PARAMS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # 只取已知字段，其余忽略
            params = {
                'ut_bot_key_value': float(data.get('ut_bot_key_value', defaults['ut_bot_key_value'])),
                'ut_bot_atr_period': int(data.get('ut_bot_atr_period', defaults['ut_bot_atr_period'])),
                'hull_length': int(data.get('hull_length', defaults['hull_length'])),
            }
            print(f"[ORACLE] 已加载动态参数: key_value={params['ut_bot_key_value']}, "
                  f"atr_period={params['ut_bot_atr_period']}, hull_length={params['hull_length']} "
                  f"(原因: {data.get('reason', 'unknown')})")
            return params
    except Exception as e:
        print(f"[ORACLE] 加载 oracle_params.json 失败，使用默认值: {e}")
    return defaults


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

    @staticmethod
    def calculate_ema(series: pd.Series, period: int) -> pd.Series:
        """计算指数移动平均线"""
        return series.ewm(span=period, adjust=False).mean()


class BinanceOracle:
    def __init__(self):
        self.cvd = 0.0                          # 累计主动买卖量差
        self.cvd_window = deque(maxlen=10000)               # (timestamp, delta) 滚动窗口（限制最大长度防内存泄漏）
        self.buy_wall = 0.0                     # 盘口买单墙（实时值）
        self.sell_wall = 0.0                    # 盘口卖单墙（实时值）
        self.buy_wall_history = deque(maxlen=10) # 买单墙历史（用于平滑）
        self.sell_wall_history = deque(maxlen=10) # 卖墙历史（用于平滑）
        self.last_price = 0.0                   # 最新成交价
        self.trade_count = 0                    # 成交笔数
        self.last_signal_score = 0.0            # 上次信号分
        self.last_write_time = 0                # 上次写文件时间

        # UT Bot + Hull K线数据存储
        self.klines_data = []                   # 存储15分钟 K 线数据
        self.klines_1h_data = []                # 存储1小时 K 线数据（大级别趋势判断）
        self.max_klines = 200                   # 最多存储200根K线

        # 动态参数（启动时从 oracle_params.json 加载）
        params = load_oracle_params()
        self.ut_bot_key_value = params['ut_bot_key_value']
        self.ut_bot_atr_period = params['ut_bot_atr_period']
        self.hull_length = params['hull_length']
        self.last_params_reload = time.time()   # 上次重载参数的时间戳

        print("[ORACLE] Binance Oracle initialized...")
        print(f"[ORACLE] Signal output: {SIGNAL_FILE}")
        print(f"[ORACLE] UT Bot: Key={self.ut_bot_key_value}, ATR={self.ut_bot_atr_period}")
        print(f"[ORACLE] Hull MA: Length={self.hull_length}")

    async def load_historical_klines(self):
        """启动时加载历史K线数据（解决UT Bot一直NEUTRAL的问题）"""
        try:
            print("[ORACLE] Loading historical K-lines from Binance...")
            url = "https://api.binance.com/api/v3/klines"
            proxies = {'http': PROXY, 'https': PROXY} if PROXY else None

            # 加载15分钟K线（战术级别）
            params_15m = {
                'symbol': 'BTCUSDT',
                'interval': '15m',
                'limit': 200
            }
            response = requests.get(url, params=params_15m, timeout=10, proxies=proxies)
            response.raise_for_status()
            data_15m = response.json()

            for kline in data_15m:
                self.add_kline(
                    kline[0], float(kline[1]), float(kline[2]),
                    float(kline[3]), float(kline[4]), float(kline[5])
                )

            print(f"[ORACLE] Loaded {len(self.klines_data)} historical 15m K-lines")

            # 加载1小时K线（战略级别）
            params_1h = {
                'symbol': 'BTCUSDT',
                'interval': '1h',
                'limit': 200
            }
            response_1h = requests.get(url, params=params_1h, timeout=10, proxies=proxies)
            response_1h.raise_for_status()
            data_1h = response_1h.json()

            for kline in data_1h:
                self.add_kline(
                    kline[0], float(kline[1]), float(kline[2]),
                    float(kline[3]), float(kline[4]), float(kline[5]),
                    is_1h=True  # 标记为1小时K线
                )

            print(f"[ORACLE] Loaded {len(self.klines_1h_data)} historical 1h K-lines")

            # 立即计算一次趋势
            trend_15m = self.get_ut_bot_hull_trend()
            trend_1h = self.get_1h_trend()
            print(f"[ORACLE] 15m trend: {trend_15m or 'CALCULATING...'} | 1h trend: {trend_1h or 'CALCULATING...'}")

        except Exception as e:
            print(f"[ORACLE] Failed to load historical K-lines: {e}")
            print(f"         Will wait for WebSocket to collect enough K-line data")

    def _trim_cvd_window(self):
        """裁剪超出窗口的旧数据"""
        cutoff = time.time() - CVD_WINDOW_SEC
        while self.cvd_window and self.cvd_window[0][0] < cutoff:
            _, delta = self.cvd_window.popleft()
            self.cvd -= delta

    def _calc_signal_score(self) -> float:
        """
        🎯 黄金分割版：量价配合的稳健评分

        核心理念：过滤假动作，要求真实资金流入确认
        - 光挂单不成交没用（Spoofing假动作）
        - 必须有真金白银砸进去（CVD）才能给高分
        """
        score = 0.0

        # 1. 5分钟级别 CVD 权重（真实成交量）
        # 假设 5 分钟内净流入 3 万美金算很强（300秒窗口）
        cvd_score = max(-5.0, min(5.0, self.cvd / 30000.0))
        score += cvd_score

        # 2. 盘口挂单权重（适当降低挂单的权重，防止被假单骗）
        avg_buy_wall = sum(self.buy_wall_history) / len(self.buy_wall_history) if self.buy_wall_history else 0
        avg_sell_wall = sum(self.sell_wall_history) / len(self.sell_wall_history) if self.sell_wall_history else 0
        total_wall = avg_buy_wall + avg_sell_wall

        imbalance = 0.0
        if total_wall > 0:
            imbalance = (avg_buy_wall - avg_sell_wall) / total_wall
            wall_score = imbalance * 3.0  # ⚠️ 从 5.0 降到 3.0，降低挂单权重
            score += wall_score

        # ==========================================
        # 💥 3. 终极抢跑特权 (保留，但必须极度极端)
        # ==========================================

        # 绝杀：必须挂单极度倾斜，且真金白银已经开始吃货
        # 光挂单不行，必须有成交确认（量价配合）
        if imbalance > 0.85 and self.cvd > 50000:
            print(f"       [🚀 NUCLEAR SIGNAL] 托盘如山+真金爆破 (imbalance={imbalance:.2f}, cvd={self.cvd/1000:.1f}K)，强制做多！")
            return 10.0
        elif imbalance < -0.85 and self.cvd < -50000:
            print(f"       [☄️ NUCLEAR SIGNAL] 压盘如山+真金砸盘 (imbalance={imbalance:.2f}, cvd={abs(self.cvd)/1000:.1f}K)，强制做空！")
            return -10.0

        return round(max(-10.0, min(10.0, score)), 3)

    def add_kline(self, timestamp, open_price, high, low, close, volume, is_1h=False):
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
        if is_1h:
            self.klines_1h_data.append(kline)
            if len(self.klines_1h_data) > self.max_klines:
                self.klines_1h_data.pop(0)
        else:
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

    def reload_params_if_needed(self):
        """每 5 分钟热重载一次 oracle_params.json（无需重启）"""
        if time.time() - self.last_params_reload < PARAMS_RELOAD_INTERVAL:
            return
        params = load_oracle_params()
        self.ut_bot_key_value = params['ut_bot_key_value']
        self.ut_bot_atr_period = params['ut_bot_atr_period']
        self.hull_length = params['hull_length']
        self.last_params_reload = time.time()
        print(f"[ORACLE] 参数热重载完成: key_value={self.ut_bot_key_value}, "
              f"atr_period={self.ut_bot_atr_period}, hull_length={self.hull_length}")

    def get_ut_bot_hull_trend(self):
        """获取 UT Bot + Hull 趋势判断"""
        # 热重载参数（每5分钟检查一次）
        self.reload_params_if_needed()

        if len(self.klines_data) < max(self.ut_bot_atr_period, self.hull_length) + 5:
            return None  # 数据不足

        # 转换为 DataFrame
        df = pd.DataFrame(self.klines_data)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

        # 计算 UT Bot 信号
        close = df['close'].values
        atr = TechnicalIndicators.calculate_atr(df, self.ut_bot_atr_period).values
        n_loss = self.ut_bot_key_value * atr

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

        # 计算 Hull MA（使用实例变量，支持热更新）
        hull = TechnicalIndicators.calculate_hma(df['close'], self.hull_length)
        hull_trend = hull.iloc[-1] > hull.iloc[-3]

        # 综合判断
        if ut_trend and hull_trend:
            return "LONG"
        elif (not ut_trend) and (not hull_trend):
            return "SHORT"
        else:
            return "NEUTRAL"  # 信号不一致，中性

    def get_1h_trend(self):
        """获取1小时级别大趋势（用于宏观重力压制判断）"""
        if len(self.klines_1h_data) < 50:
            return None  # 数据不足

        # 转换为 DataFrame
        df = pd.DataFrame(self.klines_1h_data)

        # 使用EMA20判断大趋势
        ema = TechnicalIndicators.calculate_ema(df['close'], 20)
        current_close = df['close'].iloc[-1]
        current_ema = ema.iloc[-1]

        # 简单趋势判断
        if current_close > current_ema:
            return "LONG"
        else:
            return "SHORT"

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

        # 计算 UT Bot + Hull 趋势（15分钟战术级别）
        ut_hull_trend = self.get_ut_bot_hull_trend()

        # 计算1小时大趋势（战略级别）
        trend_1h = self.get_1h_trend()

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
            # 趋势字段
            'ut_hull_trend': ut_hull_trend if ut_hull_trend else 'NEUTRAL',
            'trend_1h': trend_1h if trend_1h else 'NEUTRAL',  # 1小时大趋势
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
