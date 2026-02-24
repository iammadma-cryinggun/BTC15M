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

        # 指标更新时间戳
        self._last_indicator_update = 0

        # 断线重连退避
        self._reconnect_delay = 3

        print("\n[INFO] V5组件初始化完成，WebSocket连接准备中...\n")

    def get_current_market_slug(self):
        """获取当前15分钟市场的slug（使用UTC时间）"""
        now = int(datetime.now(timezone.utc).timestamp())
        aligned = (now // 900) * 900
        return f"btc-updown-15m-{aligned}"

    def _reset_price_cache(self):
        """切换市场时重置价格缓存，避免用旧价格触发新窗口信号"""
        self.current_price = None
        self.current_yes_price = None
        self.current_no_price = None
        self._last_indicator_update = 0
        print("[SWITCH] 价格缓存已重置")

    async def fetch_market_info_via_rest(self):
        """通过REST API获取市场信息（仅用于初始化和每15分钟重新获取）"""
        slug = self.get_current_market_slug()
        print(f"[INFO] 正在获取市场信息: {slug}")

        try:
            # 复用V5的http_session（已配置代理和重试）
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

                    if token_ids and len(token_ids) >= 2:
                        self.token_yes_id = str(token_ids[0])
                        self.token_no_id = str(token_ids[1])
                        print(f"[INFO] YES token: ...{self.token_yes_id[-8:]}")
                        print(f"[INFO] NO  token: ...{self.token_no_id[-8:]}")

                        # 🔍 获取市场结束时间（优先endTimestamp，其次endDate，最后endDateIso）
                        end_ts = market.get('endTimestamp') or market.get('endDate')
                        if end_ts:
                            print(f"[INFO] 市场结束时间: {end_ts}")
                            # 存储为endTimestamp，保证V5兼容性
                            market['endTimestamp'] = end_ts
                        else:
                            # 尝试解析endDateIso
                            end_iso = market.get('endDateIso')
                            if end_iso:
                                print(f"[INFO] endDateIso: {end_iso}")
                                # 转换为毫秒时间戳
                                from datetime import datetime, timezone
                                try:
                                    dt = datetime.fromisoformat(end_iso.replace('Z', '+00:00'))
                                    end_ts = int(dt.timestamp() * 1000)
                                    market['endTimestamp'] = end_ts
                                    print(f"[INFO] 转换后endTimestamp: {end_ts}")
                                except Exception as e:
                                    print(f"[WARN] endDateIso解析失败: {e}")
                            else:
                                print(f"[WARN] 所有时间字段都缺失！市场数据: {list(market.keys())}")
                    else:
                        print(f"[ERROR] 无法获取token IDs: {token_ids}")
                        return None

                    return market
                else:
                    print(f"[WARN] 市场未找到: {slug}")
                    return None
            else:
                print(f"[ERROR] REST请求失败: {response.status_code}")
                return None

        except Exception as e:
            print(f"[ERROR] 获取市场信息失败: {e}")
            return None

    def update_price_from_ws(self, data: dict):
        """从WebSocket消息更新价格"""
        try:
            # 处理price_changes类型（Polymarket的主要数据格式）
            price_changes = data.get("price_changes", [])
            if price_changes:
                for change in price_changes:
                    asset_id = change.get("asset_id")
                    if not asset_id:
                        continue

                    price_str = change.get("price") or change.get("best_bid")
                    if not price_str:
                        continue

                    token_price = float(price_str)

                    # 根据asset_id判断是YES还是NO token
                    if asset_id == self.token_yes_id:
                        self.current_yes_price = token_price
                        self.current_price = token_price
                    elif asset_id == self.token_no_id:
                        self.current_no_price = token_price
                        # 只有YES价格还未收到时，才用NO反推
                        if self.current_yes_price is None:
                            self.current_price = 1.0 - token_price

                # 每秒最多更新一次指标
                now = time.time()
                if now - self._last_indicator_update >= 1.0 and self.current_price:
                    high = max(self.current_yes_price or self.current_price,
                               self.current_no_price or self.current_price)
                    low = min(self.current_yes_price or self.current_price,
                              self.current_no_price or self.current_price)
                    self.v5.update_indicators(self.current_price, high, low)
                    self._last_indicator_update = now
                return

            # 处理book类型（直接订单簿数据）
            bids = data.get("bids", [])
            asks = data.get("asks", [])

            if not bids or not asks:
                return

            # Polymarket格式：[{"price": "0.54", "size": "100"}, ...]
            best_bid = float(bids[0]['price'])
            best_ask = float(asks[0]['price'])
            mid_price = (best_bid + best_ask) / 2

            asset_id = data.get("asset_id")

            # 根据asset_id判断是YES还是NO token
            if asset_id == self.token_yes_id:
                self.current_yes_price = mid_price
                self.current_price = mid_price
            elif asset_id == self.token_no_id:
                self.current_no_price = mid_price
                if self.current_yes_price is None:
                    self.current_price = 1.0 - mid_price

            # 每秒最多更新一次指标
            now = time.time()
            if now - self._last_indicator_update >= 1.0 and self.current_price:
                high = max(self.current_yes_price or self.current_price,
                           self.current_no_price or self.current_price)
                low = min(self.current_yes_price or self.current_price,
                          self.current_no_price or self.current_price)
                self.v5.update_indicators(self.current_price, high, low)
                self._last_indicator_update = now

        except Exception as e:
            if self.ws_message_count < 100:
                print(f"[DEBUG] Price update error: {e}")
                print(f"[DEBUG] Data sample: {str(data)[:200]}")

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

            # 检测信号改变（复用V5逻辑，作为止盈信号）
            if self.v5.last_signal_direction and self.v5.last_signal_direction != signal['direction']:
                print(f"[SIGNAL CHANGE] {self.v5.last_signal_direction} → {signal['direction']}")
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    self.v5.close_positions_by_signal_change,
                    self.current_price,
                    signal['direction']
                )

            # 更新V5的最后信号方向
            self.v5.last_signal_direction = signal['direction']

            # 风控检查（使用V5的can_trade，包含所有风控逻辑）
            can_trade, reason = self.v5.can_trade(signal, self.current_market)

            if can_trade:
                print(f"[TRADE] ✅ 风控通过: {reason}")

                loop = asyncio.get_running_loop()

                # 执行交易（扔到线程池，避免阻塞asyncio事件循环）
                order_result = await loop.run_in_executor(
                    None,
                    self.v5.place_order,
                    self.current_market,
                    signal
                )

                # 记录交易
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

                # 更新V6冷却时间戳（修复：原来从未更新）
                self.last_trade_time = time.time()

            else:
                print(f"[BLOCK] ❌ 风控拦截: {reason}")
                # 记录被拦截的信号到学习系统
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
        """检查持仓止盈止损"""
        if self.current_price:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                self.v5.check_positions,
                self.current_price
            )

    async def verify_predictions(self):
        """验证待验证的预测（修复：原来重复调用两次）"""
        loop = asyncio.get_running_loop()
        # 只调用v5的封装方法，内部已经调用了learning_system.verify_pending_predictions
        await loop.run_in_executor(
            None,
            self.v5.verify_pending_predictions
        )

    async def websocket_loop(self):
        """WebSocket主循环"""
        wss_uri = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

        while True:
            # 每个新的15分钟窗口重新获取市场信息，并重置价格缓存
            self._reset_price_cache()
            market = await self.fetch_market_info_via_rest()
            if not market:
                print("[WAIT] 等待市场开放，5秒后重试...")
                await asyncio.sleep(5)
                continue

            # 解析市场结束时间
            try:
                end_timestamp = market.get('endTimestamp')
                if end_timestamp:
                    self.market_end_time = datetime.fromtimestamp(
                        int(end_timestamp) / 1000, tz=timezone.utc
                    )
                    time_left = (self.market_end_time - datetime.now(timezone.utc)).total_seconds()
                    print(f"[INFO] 距离结算还有: {time_left/60:.1f} 分钟")
            except Exception:
                pass

            # 连接WebSocket
            try:
                async with websockets.connect(wss_uri) as ws:
                    print(f"[WSS] ✅ 连接成功！实时数据接收中...")
                    self._reconnect_delay = 3  # 连接成功后重置退避

                    # 订阅两个token的订单簿
                    sub_msg = {
                        "type": "market",
                        "assets_ids": [self.token_yes_id, self.token_no_id]
                    }
                    await ws.send(json.dumps(sub_msg))
                    print(f"[WSS] 已订阅: YES(...{self.token_yes_id[-8:]}), NO(...{self.token_no_id[-8:]})")

                    # 定时任务时间戳
                    last_positions_check = time.time()
                    last_prediction_check = time.time()
                    last_trade_check = time.time()

                    while True:
                        # 接收WebSocket消息（带超时，避免永久阻塞）
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            data = json.loads(msg)
                            self.ws_message_count += 1

                            # 调试：打印前5条原始消息
                            if self.ws_message_count <= 5:
                                print(f"[DEBUG] 第{self.ws_message_count}条消息: {json.dumps(data)[:300]}")

                            self.update_price_from_ws(data)

                            # 每50条消息打印一次心跳
                            if self.ws_message_count % 50 == 0:
                                yes_p = self.current_yes_price or 0
                                no_p = self.current_no_price or 0
                                print(f"[WSS] 💓 {self.ws_message_count}条 | YES: {yes_p:.4f} | NO: {no_p:.4f}")

                        except asyncio.TimeoutError:
                            pass  # 超时正常，继续执行定时任务

                        now = time.time()

                        # 每5秒检查持仓止盈止损
                        if now - last_positions_check >= 5:
                            await self.check_positions()
                            last_positions_check = now

                        # 每10秒验证预测
                        if now - last_prediction_check >= 10:
                            await self.verify_predictions()
                            last_prediction_check = now

                        # 每3秒检查交易信号（与V5保持一致）
                        if now - last_trade_check >= 3:
                            await self.check_and_trade()
                            last_trade_check = now

                        # 检查是否需要切换到下一个市场
                        if self.market_end_time:
                            time_left = (self.market_end_time - datetime.now(timezone.utc)).total_seconds()
                            if time_left < 10:
                                print(f"[SWITCH] 市场即将到期，切换到下一个15分钟窗口...")
                                break

            except websockets.exceptions.ConnectionClosed as e:
                print(f"[WSS] ⚠️ 连接断开: {e}，{self._reconnect_delay}秒后重连...")
                await asyncio.sleep(self._reconnect_delay)
                # 指数退避，最大30秒
                self._reconnect_delay = min(self._reconnect_delay * 2, 30)
            except Exception as e:
                print(f"[WSS] ❌ 错误: {e}，{self._reconnect_delay}秒后重连...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 30)

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
