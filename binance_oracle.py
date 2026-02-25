#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔮 币安 15分钟高频先知系统 (Binance Oracle)
专门为 Polymarket 15分钟大盘预测提供"抢跑"数据

输出文件: oracle_signal.json (供 auto_trader_ankr.py 读取)
"""

import asyncio
import websockets
import json
import os
import time
from datetime import datetime
from collections import deque

# 代理配置
PROXY = os.getenv('HTTP_PROXY', os.getenv('HTTPS_PROXY', ''))

# 信号输出路径（与 auto_trader_ankr.py 同目录）
SIGNAL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'oracle_signal.json')

# CVD滚动窗口（秒）
CVD_WINDOW_SEC = 900  # 15分钟


class BinanceOracle:
    def __init__(self):
        self.cvd = 0.0                          # 累计主动买卖量差
        self.cvd_window = deque()               # (timestamp, delta) 滚动窗口
        self.buy_wall = 0.0                     # 盘口买单墙
        self.sell_wall = 0.0                    # 盘口卖单墙
        self.last_price = 0.0                   # 最新成交价
        self.trade_count = 0                    # 成交笔数
        self.last_signal_score = 0.0            # 上次信号分
        self.last_write_time = 0                # 上次写文件时间
        print("🚀 币安天眼先知系统初始化完成...")
        print(f"📁 信号输出: {SIGNAL_FILE}")

    def _trim_cvd_window(self):
        """裁剪超出窗口的旧数据"""
        cutoff = time.time() - CVD_WINDOW_SEC
        while self.cvd_window and self.cvd_window[0][0] < cutoff:
            _, delta = self.cvd_window.popleft()
            self.cvd -= delta

    def _calc_signal_score(self) -> float:
        """
        计算综合信号分 (-10 到 +10)
        - CVD贡献：±5分
        - 盘口失衡贡献：±5分
        """
        score = 0.0

        # CVD分（归一化，以100 BTC为满分基准）
        cvd_score = max(-5.0, min(5.0, self.cvd / 20.0))
        score += cvd_score

        # 盘口失衡分
        total_wall = self.buy_wall + self.sell_wall
        if total_wall > 0:
            imbalance = (self.buy_wall - self.sell_wall) / total_wall
            wall_score = imbalance * 5.0
            score += wall_score

        return round(max(-10.0, min(10.0, score)), 3)

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
        }

        try:
            tmp = SIGNAL_FILE + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(signal, f)
            os.replace(tmp, SIGNAL_FILE)  # 原子写入，防止读到半截文件
        except Exception as e:
            print(f"[ORACLE] 写文件失败: {e}")

    async def listen_trades(self):
        """监听逐笔成交：捕捉主力资金的主动吃单"""
        url = "wss://stream.binance.com:9443/ws/btcusdt@aggTrade"
        while True:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    print("🟢 [连接成功] 币安实时成交流 (AggTrade)")
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
                print(f"[ORACLE] AggTrade断线: {e}，3秒后重连...")
                await asyncio.sleep(3)

    async def listen_depth(self):
        """监听盘口深度：捕捉做市商的挂单墙"""
        url = "wss://stream.binance.com:9443/ws/btcusdt@depth20@100ms"
        while True:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    print("🟢 [连接成功] 币安盘口深度 (Depth)")
                    while True:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        self.buy_wall = sum(float(b[1]) for b in data['bids'])
                        self.sell_wall = sum(float(a[1]) for a in data['asks'])
            except Exception as e:
                print(f"[ORACLE] Depth断线: {e}，3秒后重连...")
                await asyncio.sleep(3)

    async def print_status(self):
        """每2秒打印一次状态"""
        while True:
            await asyncio.sleep(2)
            total_wall = self.buy_wall + self.sell_wall
            imbalance = (self.buy_wall - self.sell_wall) / total_wall if total_wall > 0 else 0.0
            score = self.last_signal_score
            now = datetime.now().strftime("%H:%M:%S")
            color = "\033[92m" if score > 0 else "\033[91m"
            reset = "\033[0m"
            print(f"[{now}] 🔮 先知 | 分数: {color}{score:+.2f}{reset} | "
                  f"CVD(15m): {color}{self.cvd:+.1f} USD{reset} | "
                  f"盘口失衡: {imbalance*100:+.1f}% | "
                  f"买墙: {self.buy_wall:.1f} / 卖墙: {self.sell_wall:.1f} | "
                  f"BTC: {self.last_price:.1f}")

    async def run(self):
        """并发运行所有监听器"""
        await asyncio.gather(
            self.listen_trades(),
            self.listen_depth(),
            self.print_status(),
        )


if __name__ == "__main__":
    oracle = BinanceOracle()
    try:
        asyncio.run(oracle.run())
    except KeyboardInterrupt:
        print("\n🛑 先知系统已关闭。")
