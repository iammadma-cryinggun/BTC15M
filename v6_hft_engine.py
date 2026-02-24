#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚀 V6 高频引擎 (WebSocket + V5风控保留)
利用原有的 V5 所有风控和交易逻辑，只替换价格获取方式为毫秒级WebSocket
"""

import asyncio
import websockets
import json
import time
from datetime import datetime, timezone
from collections import deque
import sys

# 导入V5的所有组件（完全复用）
import auto_trader_ankr as v5


class V6HFTEngine:
    """V6高频引擎：WebSocket价格 + V5完整风控"""

    def __init__(self):
        print("=" * 70)
        print("🚀 V6 高频引擎启动 (保留V5所有风控)")
        print("=" * 70)

        # 实例化V5机器人（自动复用其所有组件）
        self.v5 = v5.AutoTraderV5()

        # 价格缓存（从WebSocket获取）
        self.current_market = None
        self.current_price = None
        self.current_yes_price = None
        self.current_no_price = None
        self.token_yes_id = None
        self.token_no_id = None
        self.last_trade_time = 0

        # 市场信息
        self.current_slug = None
        self.market_end_time = None

        # 统计
        self.ws_message_count = 0
        self.signal_count = 0

        print("\n[INFO] V5组件初始化完成，WebSocket连接准备中...\n")

    def get_current_market_slug(self):
        """获取当前15分钟市场的slug"""
        # ✅ 修复: 明确使用UTC时间，避免服务器时区问题
        from datetime import datetime, timezone
        now = int(datetime.now(timezone.utc).timestamp())
        aligned = (now // 900) * 900
        # ✅ 修复: 使用V5的正确格式（不是starting-格式）
        return f"btc-updown-15m-{aligned}"

    async def fetch_market_info_via_rest(self):
        """通过REST API获取市场信息（仅用于初始化和每15分钟重新获取）"""
        slug = self.get_current_market_slug()
        print(f"[INFO] 正在获取市场信息: {slug}")

        try:
            response = self.v5.http_session.get(
                f"{v5.CONFIG['gamma_host']}/markets",
                params={'slug': slug},
                proxies=v5.CONFIG.get('proxy'),
                timeout=10
            )

            if response.status_code == 200:
                markets = response.json()
                if markets and len(markets) > 0:
                    market = markets[0]
                    self.current_market = market
                    self.current_slug = slug

                    # 获取token ID
                    token_ids = market.get('clobTokenIds', [])
                    if isinstance(token_ids, str):
                        token_ids = json.loads(token_ids)

                    if len(token_ids) >= 2:
                        self.token_yes_id = token_ids[0]
                        self.token_no_id = token_ids[1]
                        print(f"[OK] 市场加载成功: YES={self.token_yes_id[-8:]}, NO={self.token_no_id[-8:]}")
                        return market

            print(f"[WARN] 市场未找到或未开放，等待下一个窗口...")
            return None

        except Exception as e:
            print(f"[ERROR] 获取市场信息失败: {e}")
            return None

    def update_price_from_ws(self, data):
        """从WebSocket数据更新价格"""
        try:
            # ✅ 修复Bug 2: Polymarket格式是字典 {"price": "0.54", "size": "100"}
            if "bids" not in data or "asks" not in data:
                return

            bids = data.get("bids", [])
            asks = data.get("asks", [])

            if len(bids) == 0 or len(asks) == 0:
                return

            # ✅ 修复: 使用字典访问 bids[0]['price']
            best_bid = float(bids[0]['price'])
            best_ask = float(asks[0]['price'])
            mid_price = (best_bid + best_ask) / 2

            asset_id = data.get("asset_id")

            # 根据asset_id判断是YES还是NO
            if asset_id == self.token_yes_id:
                self.current_yes_price = mid_price
                # YES价格 = mid_price
                self.current_price = mid_price
            elif asset_id == self.token_no_id:
                self.current_no_price = mid_price
                # 如果只有NO价格，用1-NO计算YES价格
                if self.current_yes_price is None:
                    self.current_price = 1.0 - mid_price

            # 更新V5的指标（每秒最多更新一次，避免CPU爆炸）
            now = time.time()
            if now - self.v5.rsi.last_update_time >= 1.0:
                high = max(self.current_yes_price or 0.5, self.current_no_price or 0.5)
                low = min(self.current_yes_price or 0.5, self.current_no_price or 0.5)
                self.v5.update_indicators(self.current_price or 0.5, high, low)

        except Exception as e:
            # 🔍 调试：打印错误和原始数据（前100条）
            if self.ws_message_count < 100:
                print(f"[DEBUG] Price update error: {e}")
                print(f"[DEBUG] Data sample: {str(data)[:200]}")
            pass  # 静默失败，避免打印过多错误

    async def check_and_trade(self):
        """检查信号并执行交易（完全复用V5逻辑）"""
        if not self.current_market or not self.current_price:
            return

        # 冷却期：距离上次交易至少60秒
        now = time.time()
        if now - self.last_trade_time < 60:
            return

        # 生成信号（使用V5的generate_signal）
        signal = self.v5.generate_signal(self.current_market, self.current_price)

        if signal:
            self.signal_count += 1
            print(f"[SIGNAL] {signal['direction']} | Score: {signal['score']:.2f} | Price: {self.current_price:.4f}")

            # 风控检查（使用V5的can_trade，包含所有风控逻辑）
            can_trade, reason = self.v5.can_trade(signal, self.current_market)

            if can_trade:
                print(f"[TRADE] ✅ 风控通过: {reason}")

                # ✅ 修复Bug 1: 使用线程池执行同步操作，不阻塞asyncio事件循环
                loop = asyncio.get_running_loop()

                # 执行交易（扔到后台线程）
                order_result = await loop.run_in_executor(
                    None,
                    self.v5.place_order,
                    self.current_market,
                    signal
                )

                # 记录交易（也扔到后台线程）
                await loop.run_in_executor(
                    None,
                    self.v5.record_trade,
                    self.current_market,
                    signal,
                    order_result,
                    False
                )

                # 更新统计
                self.v5.stats['total_trades'] += 1
                self.v5.stats['daily_trades'] += 1
                self.v5.stats['last_trade_time'] = datetime.now()
                self.last_trade_time = now

                # Telegram通知
                if self.v5.telegram.enabled:
                    msg = f"⚡ <b>V6交易触发</b>\n方向: {signal['direction']}\n分数: {signal['score']:.2f}\n价格: {self.current_price:.4f}"
                    self.v5.telegram.send(msg, parse_mode="HTML")

            else:
                print(f"[BLOCK] ❌ 风控拦截: {reason}")
                # 记录被拦截的信号
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    self.v5.record_prediction_learning,
                    self.current_market,
                    signal,
                    None,
                    True
                )

    async def check_positions(self):
        """检查持仓止盈止损（每5秒检查一次）"""
        if self.current_price:
            # ✅ 修复: 使用线程池，避免阻塞WebSocket接收
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                self.v5.check_positions,
                self.current_price
            )

    async def verify_predictions(self):
        """验证待验证的预测（每10秒检查一次）"""
        if self.v5.learning_system:
            # ✅ 修复: 使用线程池，避免阻塞WebSocket接收
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                self.v5.verify_pending_predictions
            )
            await loop.run_in_executor(
                None,
                self.v5.learning_system.verify_pending_predictions
            )

    async def websocket_loop(self):
        """WebSocket主循环"""
        wss_uri = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

        while True:
            # 每个新的15分钟窗口重新获取市场信息
            market = await self.fetch_market_info_via_rest()
            if not market:
                print("[WAIT] 等待市场开放...")
                await asyncio.sleep(5)
                continue

            # 解析市场结束时间
            try:
                end_timestamp = market.get('endTimestamp')
                if end_timestamp:
                    self.market_end_time = datetime.fromtimestamp(int(end_timestamp) / 1000, tz=timezone.utc)
                    time_left = (self.market_end_time - datetime.now(timezone.utc)).total_seconds()
                    print(f"[INFO] 距离结算还有: {time_left/60:.1f} 分钟")
            except:
                pass

            # 连接WebSocket
            try:
                async with websockets.connect(wss_uri) as ws:
                    print(f"[WSS] ✅ 连接成功！实时数据接收中...")

                    # 订阅两个token的订单簿
                    sub_msg = {
                        "type": "market",
                        "assets_ids": [self.token_yes_id, self.token_no_id]
                    }
                    await ws.send(json.dumps(sub_msg))
                    print(f"[WSS] 已订阅: YES({self.token_yes_id[-8:]}), NO({self.token_no_id[-8:]})")

                    # 数据接收循环
                    last_positions_check = time.time()
                    last_prediction_check = time.time()
                    last_trade_check = time.time()

                    while True:
                        # 接收WebSocket消息（带超时，避免永久阻塞）
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            data = json.loads(msg)
                            self.ws_message_count += 1

                            # 🔍 调试：打印前5条原始消息
                            if self.ws_message_count <= 5:
                                print(f"[DEBUG] 收到第{self.ws_message_count}条消息: {json.dumps(data, indent=2)[:500]}")

                            # 更新价格
                            self.update_price_from_ws(data)

                            # 每秒打印一次价格更新（避免刷屏）
                            if self.ws_message_count % 50 == 0:
                                yes_p = self.current_yes_price or 0
                                no_p = self.current_no_price or 0
                                print(f"[WSS] 💓 已接收{self.ws_message_count}条消息 | YES: {yes_p:.4f} | NO: {no_p:.4f}")

                        except asyncio.TimeoutError:
                            # 超时是正常的，继续执行
                            pass

                        # 定期任务（不阻塞价格接收）
                        now = time.time()

                        # 每5秒检查持仓
                        if now - last_positions_check >= 5:
                            await self.check_positions()
                            last_positions_check = now

                        # 每10秒验证预测
                        if now - last_prediction_check >= 10:
                            await self.verify_predictions()
                            last_prediction_check = now

                        # 每2秒检查交易信号（有足够的价格变化后再检查）
                        if now - last_trade_check >= 2:
                            await self.check_and_trade()
                            last_trade_check = now

                        # 检查是否需要切换到下一个市场
                        if self.market_end_time:
                            time_left = (self.market_end_time - datetime.now(timezone.utc)).total_seconds()
                            if time_left < 10:  # 最后10秒断开，准备切换
                                print(f"[SWITCH] 市场即将到期，准备切换到下一个15分钟窗口...")
                                break

            except websockets.exceptions.ConnectionClosed as e:
                print(f"[WSS] ⚠️ 连接断开: {e}，3秒后重连...")
                await asyncio.sleep(3)
            except Exception as e:
                print(f"[WSS] ❌ 错误: {e}，3秒后重连...")
                await asyncio.sleep(3)

    async def run(self):
        """启动V6引擎"""
        try:
            await self.websocket_loop()
        except KeyboardInterrupt:
            print("\n" + "=" * 70)
            print(f"[STOP] V6引擎停止运行")
            print(f"  WebSocket消息: {self.ws_message_count}")
            print(f"  信号检测: {self.signal_count}")
            print(f"  总交易: {self.v5.stats['total_trades']}")
            print("=" * 70)


async def main():
    """主入口"""
    engine = V6HFTEngine()
    await engine.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[STOP] 收到停止信号，正在退出...")
        sys.exit(0)
