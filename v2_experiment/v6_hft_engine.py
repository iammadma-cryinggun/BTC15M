#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V6 高频引擎 (WebSocket + V5风控保留)
修复记录:
- 复用V5的http_session
- 修复verify_predictions重复调用
- 修复市场切换时价格缓存未重置
- 修复last_trade_time从不更新
- 新增get_order_book覆盖，使用WebSocket实时价格
- 新增断线重连指数退避
"""

import asyncio
import websockets
import json
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import sys

#  强制无缓冲输出（解决容器环境日志不显示问题）
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)

import auto_trader_ankr as v5


class V6HFTEngine:

    def __init__(self):
        print("=" * 70, flush=True)
        print("V6 高频引擎启动 (保留V5所有风控)", flush=True)
        print("=" * 70, flush=True)

        self.v5 = v5.AutoTraderV5()

        self.current_market = None
        self.current_price = None
        #  修复：分别存储bid和ask价格，避免spread被抹除
        self.yes_best_bid = None  # YES买一价（卖出时用）
        self.yes_best_ask = None  # YES卖一价（买入时用）
        self.no_best_bid = None   # NO买一价（卖出时用）
        self.no_best_ask = None   # NO卖一价（买入时用）
        #  修复：初始化current_yes_price和current_no_price，避免AttributeError
        self.current_yes_price = None
        self.current_no_price = None
        self.token_yes_id = None
        self.token_no_id = None
        self.last_trade_time = 0
        self.current_slug = None
        self.market_end_time = None
        self.ws_message_count = 0
        self.signal_count = 0
        self._last_indicator_update = 0
        self._reconnect_delay = 3

        #  性能优化：创建更大的线程池（默认是min(32, cpu_count + 4)）
        # 提升并发能力，避免HTTP/数据库操作阻塞WebSocket
        self.executor = ThreadPoolExecutor(max_workers=50, thread_name_prefix="v6_worker")
        print(f"[PERF] 线程池已创建: max_workers=50 (提升并发能力)")

        print("\n[INFO] V5组件初始化完成，WebSocket连接准备中...\n")
        self._patch_v5_order_book()

        #  Fire-and-Forget：异步任务跟踪
        self.pending_tasks = []  # 跟踪后台任务
        self.completed_tasks = 0  # 完成的任务计数

        #  状态锁：防止并发幽灵（重复下单）
        self._processing_orders = set()  # 正在处理中的订单/动作集合

        #  GC防护：抓住后台任务，防止被垃圾回收器提前销毁
        self._background_tasks = set()  # 存储所有活跃的后台Task

        # 加载动态参数（与V5保持一致）
        self.v5.load_dynamic_params()

        # 清理过期持仓
        self.v5.cleanup_stale_positions()

        # Telegram 启动通知
        if self.v5.telegram.enabled:
            self.v5.telegram.send("V6 高频引擎已启动 (WebSocket实时价格 + V5完整风控)")

    def _patch_v5_order_book(self):
        """覆盖V5的get_order_book，优先使用WebSocket缓存价格"""
        original = self.v5.get_order_book

        def fast_get_order_book(token_id: str, side: str = 'BUY'):
            #  关键修复：根据side返回正确的bid/ask价格
            # BUY时返回ask（卖一价，买入成本），SELL时返回bid（买一价，卖出收入）
            if token_id == self.token_yes_id:
                if side == 'BUY':
                    price = self.yes_best_ask  # 买入YES，需要用ask价格
                else:  # SELL
                    price = self.yes_best_bid   # 卖出YES，需要用bid价格
            elif token_id == self.token_no_id:
                if side == 'BUY':
                    price = self.no_best_ask   # 买入NO，需要用ask价格
                else:  # SELL
                    price = self.no_best_bid    # 卖出NO，需要用bid价格
            else:
                return original(token_id, side)

            if price is not None:
                print(f"       [WS PRICE] {token_id[-8:]}: {price:.4f} ({side}, WebSocket实时)")
                return price
            print(f"       [WS PRICE] {token_id[-8:]}: 暂无WebSocket数据，回退REST")
            return original(token_id, side)

        self.v5.get_order_book = fast_get_order_book

    def get_current_market_slug(self):
        now = int(datetime.now(timezone.utc).timestamp())
        aligned = (now // 900) * 900
        return f"btc-updown-15m-{aligned}"

    def _reset_price_cache(self):
        """切换市场时重置价格缓存"""
        self.current_price = None
        #  修复：重置bid/ask价格
        self.yes_best_bid = None
        self.yes_best_ask = None
        self.no_best_bid = None
        self.no_best_ask = None
        self._last_indicator_update = 0
        print("[SWITCH] 价格缓存已重置")

    async def _async_fire_and_forget(self, func, *args, task_name: str = "后台任务"):
        """
         后台异步任务包装器：Fire-and-Forget 模式

        在子线程中执行同步代码（如 py_clob_client SDK），
        主WebSocket循环完全不阻塞，继续监听价格更新

        Args:
            func: 要执行的同步函数
            *args: 函数参数
            task_name: 任务名称（用于日志）
        """
        try:
            #  关键：使用 asyncio.to_thread 在后台线程执行
            # 主循环立即返回，继续监听WebSocket！
            result = await asyncio.to_thread(func, *args)

            # 后台任务完成，记录结果
            self.completed_tasks += 1
            # print(f"       [后台捷报] [OK] {task_name}执行成功")  # 删除重复日志
            return result
        except Exception as e:
            print(f"       [后台警报] ❌ {task_name}执行失败: {str(e)[:100]}")
            return None

    async def _async_execute_trade(self, func, *args, task_name: str = "交易任务"):
        """
         后台执行完整交易流程：下单 + 记录

        Args:
            func: 下单函数
            *args: 下单参数
            task_name: 任务名称
        """
        try:
            # 步骤1：后台下单（不阻塞主循环）
            order_result = await asyncio.to_thread(func, *args)
            self.completed_tasks += 1

            if order_result:
                # print(f"       [后台捷报]  {task_name}成功: {order_result.get('orderId', 'N/A')[:8]}")  # 删除重复日志

                # 步骤2：后台记录交易（不阻塞主循环）
                market = args[0]  # self.current_market
                signal = args[1]  # signal

                await asyncio.to_thread(
                    self.v5.record_trade,
                    market, signal, order_result, False
                )
                # print(f"       [后台捷报] [OK] 交易记录已保存")  # 删除重复日志
            else:
                print(f"       [后台警报] ⚠  {task_name}失败: 返回空结果")

        except Exception as e:
            print(f"       [后台警报] ❌ {task_name}异常: {str(e)[:150]}")

    async def fetch_market_info_via_rest(self, force_next_window=False):
        # 尝试当前窗口，过期则尝试下一个
        #  修复：force_next_window=True 时跳过当前窗口，直接使用下一个（避免死循环）
        now = int(datetime.now(timezone.utc).timestamp())
        aligned = (now // 900) * 900

        # 如果强制使用下一个窗口，从 offset=900 开始
        if force_next_window:
            offsets = [900]  #  跳过当前窗口，只尝试下一个
        else:
            offsets = [0, 900]  # 正常：先尝试当前窗口，再尝试下一个
        for offset in offsets:
            slug = f"btc-updown-15m-{aligned + offset}"
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

                        # 检查市场是否已过期
                        end_date = market.get('endDate')
                        if end_date:
                            try:
                                end_dt = datetime.strptime(end_date, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                                now_dt = datetime.now(timezone.utc)
                                if (end_dt - now_dt).total_seconds() < 0:
                                    print(f"[WARN] 市场已过期，尝试下一个窗口: {slug}")
                                    continue
                            except:
                                pass

                        self.current_market = market
                        self.current_slug = slug
                        token_ids = market.get('clobTokenIds', [])
                        if isinstance(token_ids, str):
                            token_ids = json.loads(token_ids)
                        if token_ids and len(token_ids) >= 2:
                            self.token_yes_id = str(token_ids[0])
                            self.token_no_id = str(token_ids[1])
                            print(f"[INFO] YES token: ...{self.token_yes_id[-8:]}")
                            print(f"[INFO] NO  token: ...{self.token_no_id[-8:]}")

                            end_ts = market.get('endTimestamp') or market.get('endDate')
                            if end_ts:
                                market['endTimestamp'] = end_ts
                            else:
                                end_iso = market.get('endDateIso')
                                if end_iso:
                                    try:
                                        dt = datetime.fromisoformat(end_iso.replace('Z', '+00:00'))
                                        end_ts = int(dt.timestamp() * 1000)
                                        market['endTimestamp'] = end_ts
                                    except:
                                        pass
                        else:
                            print(f"[ERROR] 无法获取token IDs: {token_ids}")
                            continue
                        return market
                    else:
                        print(f"[WARN] 市场未找到: {slug}")
                else:
                    print(f"[ERROR] REST请求失败: {response.status_code}")
            except Exception as e:
                print(f"[ERROR] 获取市场信息失败: {e}")

        return None

    def update_price_from_ws(self, data):
        """
        处理WebSocket价格更新
        data格式可能是：
        1. dict - price_changes格式
        2. list - 订单簿快照格式
        """
        try:
            #  调试：打印前5条原始消息的完整结构
            if self.ws_message_count <= 5:
                data_str = json.dumps(data, ensure_ascii=False)[:400] if isinstance(data, (dict, list)) else str(data)
                print(f"[DEBUG] 第{self.ws_message_count}条消息: {data_str}")

            # 处理list格式（订单簿快照）
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "asset_id" in item:
                        # 转换为dict格式处理
                        self._process_orderbook_item(item)
                return

            # 处理dict格式（price_changes或book）
            if not isinstance(data, dict):
                return

            # 处理price_changes类型（Polymarket的主要数据格式）
            price_changes = data.get("price_changes", [])
            if price_changes:
                for change in price_changes:
                    asset_id = change.get("asset_id")
                    if not asset_id:
                        continue

                    # 优先用best_bid（真实买一价），price只是某笔挂单价格不代表市价
                    price_str = change.get("best_bid") or change.get("price")
                    if not price_str:
                        continue

                    token_price = float(price_str)

                    # YES和NO各自独立，直接存自己的价格，不互相推算
                    if asset_id == self.token_yes_id:
                        if 0.02 <= token_price <= 0.98:
                            self.current_yes_price = token_price
                            self.current_price = token_price
                    elif asset_id == self.token_no_id:
                        if 0.02 <= token_price <= 0.98:
                            self.current_no_price = token_price

                #  修复二：指标更新间隔从1秒改为30秒，避免时间轴坍缩
                now = time.time()
                if now - self._last_indicator_update >= 30.0 and self.current_yes_price:
                    self.v5.update_indicators(self.current_yes_price, self.current_yes_price, self.current_yes_price)
                    self._last_indicator_update = now
                return

            # 处理book类型（直接订单簿数据）
            event_type = data.get("event_type") or data.get("type", "")
            if event_type not in ("book", "price_change", "tick_size_change", "last_trade_price", ""):
                if "bids" not in data and "asks" not in data:
                    return
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            if not bids or not asks:
                return
            #  关键修复：必须用min/max，不能假设列表已排序
            # bids[0]可能不是最高价，asks[0]可能不是最低价
            best_bid = max(float(bid['price']) for bid in bids)   # 买一 = 最高买价
            best_ask = min(float(ask['price']) for ask in asks)   # 卖一 = 最低卖价
            mid_price = (best_bid + best_ask) / 2
            asset_id = data.get("asset_id")
            if asset_id == self.token_yes_id:
                self.yes_best_bid = best_bid
                self.yes_best_ask = best_ask
                self.current_yes_price = mid_price
                self.current_price = mid_price
            elif asset_id == self.token_no_id:
                self.no_best_bid = best_bid
                self.no_best_ask = best_ask
                self.current_no_price = mid_price
            #  修复二：指标更新间隔从1秒改为30秒
            now = time.time()
            if now - self._last_indicator_update >= 30.0 and self.current_yes_price:
                self.v5.update_indicators(self.current_yes_price, self.current_yes_price, self.current_yes_price)
                self._last_indicator_update = now
        except Exception as e:
            if self.ws_message_count < 100:
                print(f"[DEBUG] Price update error: {e}")
                print(f"[DEBUG] Data type: {type(data)}, Keys: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
                print(f"[DEBUG] Data sample: {str(data)[:300]}")
                import traceback
                print(f"[DEBUG] Traceback: {traceback.format_exc()}")

    def _process_orderbook_item(self, item: dict):
        """处理订单簿格式或价格更新的单个item"""
        try:
            asset_id = item.get("asset_id")
            if not asset_id:
                return

            mid_price = None
            best_bid = None
            best_ask = None

            # 情况A：如果Polymarket真的发来了详细盘口 (bids/asks)
            if "bids" in item and "asks" in item:
                bids = item.get("bids", [])
                asks = item.get("asks", [])
                if bids and asks:
                    best_bid = max(float(bid['price']) for bid in bids)
                    best_ask = min(float(ask['price']) for ask in asks)
                    mid_price = (best_bid + best_ask) / 2

            #  致命修复一：处理简单price字段（WebSocket type="market"的主要格式）
            elif "price" in item:
                price_val = float(item["price"])
                mid_price = price_val
                # 既然没有真实深度，临时用最新价充当买卖一价，防止后续下单算滑点时报错！
                best_bid = price_val
                best_ask = price_val

            # 如果什么都没解析出来，直接丢弃
            if mid_price is None:
                return

            # 更新引擎内存中的价格
            if asset_id == self.token_yes_id:
                if 0.02 <= mid_price <= 0.98:
                    if best_bid: self.yes_best_bid = best_bid
                    if best_ask: self.yes_best_ask = best_ask
                    self.current_yes_price = mid_price
                    self.current_price = mid_price
            elif asset_id == self.token_no_id:
                if 0.02 <= mid_price <= 0.98:
                    if best_bid: self.no_best_bid = best_bid
                    if best_ask: self.no_best_ask = best_ask
                    self.current_no_price = mid_price

            #  致命修复二：指标时间轴坍缩问题！
            # 从 1.0 秒改为 30.0 秒。让历史K线真正积累动能，激活 Oracle 融合放大器！
            now = time.time()
            if now - self._last_indicator_update >= 30.0 and self.current_yes_price:
                self.v5.update_indicators(self.current_yes_price, self.current_yes_price, self.current_yes_price)
                self._last_indicator_update = now

        except Exception as e:
            if self.ws_message_count < 100:
                print(f"[DEBUG] Process item error: {e}")

    async def check_and_trade(self):
        """检查信号并执行交易（完全复用V5逻辑）"""
        if not self.current_market or not self.current_price:
            return

        # 冷却期：距离上次交易至少60秒
        now = time.time()
        if now - self.last_trade_time < 60:
            return

        # 生成信号（复用V5，传入WebSocket实时NO价）
        signal = self.v5.generate_signal(self.current_market, self.current_price, no_price=self.current_no_price)

        if signal:
            self.signal_count += 1
            print(f"[SIGNAL] {signal['direction']} | Score: {signal['score']:.2f} | Price: {self.current_price:.4f}")

            # ❌ 禁用信号改变平仓（数据显示：SIGNAL_CHANGE胜率14.3%，亏损-10.02 USDC）
            # 持有到结算胜率更高（80.0%），不应该在信号改变时提前平仓
            # if self.v5.last_signal_direction and self.v5.last_signal_direction != signal['direction']:
            #     print(f"[SIGNAL CHANGE] {self.v5.last_signal_direction} -> {signal['direction']}")
            #     loop = asyncio.get_running_loop()
            #     await loop.run_in_executor(
            #         None, self.v5.close_positions_by_signal_change,
            #         self.current_price, signal['direction']
            #     )

            self.v5.last_signal_direction = signal['direction']

            # 风控检查（复用V5）
            can_trade, reason = self.v5.can_trade(signal, self.current_market)

            if can_trade:
                print(f"[TRADE] 风控通过: {reason}")

                #  状态锁：防止同一市场重复下单
                action_key = f"trade_{self.current_market.get('slug', 'unknown')}"

                if action_key in self._processing_orders:
                    print(f"[LOCK] ⚠  该市场正在处理中，跳过重复下单: {action_key}")
                else:
                    print(f"[TRADE]  发射后台下单任务（0延迟）...")

                    #  加锁：标记正在处理
                    self._processing_orders.add(action_key)

                    #  关键优化：Fire-and-Forget 模式 + 状态锁
                    async def task_with_unlock():
                        try:
                            await self._async_execute_trade(
                                self.v5.place_order, self.current_market, signal,
                                task_name="下单"
                            )
                        finally:
                            #  解锁：无论成功失败都释放锁
                            self._processing_orders.discard(action_key)

                    task = asyncio.create_task(task_with_unlock())

                    #  GC防护：抓住任务，防止被提前回收
                    self._background_tasks.add(task)
                    task.add_done_callback(self._background_tasks.discard)

                    # 立即更新统计（不等待下单完成）
                    self.v5.stats['total_trades'] += 1
                    self.v5.stats['daily_trades'] += 1
                    self.v5.stats['last_trade_time'] = datetime.now()
                    self.v5.last_traded_market = self.current_market.get('slug', '')
                    self.last_trade_time = time.time()

                    print(f"[TRADE] [OK] 下单任务已发射，WebSocket继续监听（0阻塞）")

            else:
                print(f"[BLOCK] 风控拦截: {reason}")
                #  Fire-and-Forget：异步记录学习
                action_key = "record_learning"
                if action_key not in self._processing_orders:
                    self._processing_orders.add(action_key)

                    async def learning_task_with_unlock():
                        try:
                            await self._async_fire_and_forget(
                                self.v5.record_prediction_learning,
                                self.current_market, signal, None, True,
                                task_name="记录学习数据"
                            )
                        finally:
                            self._processing_orders.discard(action_key)

                    #  GC防护：抓住任务，防止被提前回收
                    task = asyncio.create_task(learning_task_with_unlock())
                    self._background_tasks.add(task)
                    task.add_done_callback(self._background_tasks.discard)

    async def check_positions(self):
        """检查持仓止盈止损（复用V5逻辑）- 异步模式"""
        if self.current_price:
            #  状态锁：防止持仓检查重复执行
            action_key = "check_positions"

            if action_key in self._processing_orders:
                # 上一次检查还在进行中，跳过本次
                return

            self._processing_orders.add(action_key)

            #  Fire-and-Forget：不阻塞WebSocket
            async def positions_task_with_unlock():
                try:
                    await self._async_fire_and_forget(
                        self.v5.check_positions, self.current_price,
                        task_name="检查持仓"
                    )
                finally:
                    self._processing_orders.discard(action_key)

            #  GC防护：抓住任务，防止被提前回收
            task = asyncio.create_task(positions_task_with_unlock())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def verify_predictions(self):
        """验证待验证的预测（修复：只调用一次，避免重复验证）- 异步模式"""
        #  状态锁：防止预测验证重复执行
        action_key = "verify_predictions"

        if action_key in self._processing_orders:
            return

        self._processing_orders.add(action_key)

        #  Fire-and-Forget：不阻塞WebSocket
        async def verify_task_with_unlock():
            try:
                await self._async_fire_and_forget(
                    self.v5.verify_pending_predictions,
                    task_name="验证预测"
                )
            finally:
                self._processing_orders.discard(action_key)

        #  GC防护：抓住任务，防止被提前回收
        task = asyncio.create_task(verify_task_with_unlock())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def auto_adjust(self):
        """定期自动调整参数（复用V5逻辑）- 异步模式"""
        #  状态锁：防止参数调整重复执行
        action_key = "auto_adjust"

        if action_key in self._processing_orders:
            return

        self._processing_orders.add(action_key)

        #  Fire-and-Forget：不阻塞WebSocket
        async def adjust_task_with_unlock():
            try:
                await self._async_fire_and_forget(
                    self.v5.auto_adjust_parameters,
                    task_name="自动调整参数"
                )
            finally:
                self._processing_orders.discard(action_key)

        #  GC防护：抓住任务，防止被提前回收
        task = asyncio.create_task(adjust_task_with_unlock())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def print_trading_analysis(self):
        """输出交易分析（调用V5的方法）- 异步模式"""
        print("[V6] 开始调用交易分析...")
        #  状态锁：防止分析重复执行
        action_key = "print_trading_analysis"

        if action_key in self._processing_orders:
            return

        self._processing_orders.add(action_key)

        #  Fire-and-Forget：不阻塞WebSocket
        async def analysis_task_with_unlock():
            try:
                await self._async_fire_and_forget(
                    self.v5.print_trading_analysis,
                    task_name="交易分析"
                )
            finally:
                self._processing_orders.discard(action_key)

        #  GC防护：抓住任务，防止被提前回收
        task = asyncio.create_task(analysis_task_with_unlock())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def websocket_loop(self):
        """WebSocket主循环"""
        wss_uri = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

        #  标记：是否需要强制切换到下一个窗口（避免市场即将到期时的死循环）
        force_next_window = False

        while True:
            # 每个新的15分钟窗口重新获取市场信息，并重置价格缓存
            self._reset_price_cache()
            market = await self.fetch_market_info_via_rest(force_next_window=force_next_window)
            force_next_window = False  # 重置标记
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
                    print(f"[WSS] 连接成功！实时数据接收中...")
                    self._reconnect_delay = 3  # 连接成功，重置退避

                    # 订阅两个token的订单簿
                    sub_msg = {
                        "type": "market",
                        "assets_ids": [self.token_yes_id, self.token_no_id]
                    }
                    await ws.send(json.dumps(sub_msg))
                    print(f"[WSS] 已订阅: YES(...{self.token_yes_id[-8:]}), NO(...{self.token_no_id[-8:]})")

                    last_positions_check = time.time()
                    last_prediction_check = time.time()
                    last_trade_check = time.time()
                    last_adjust_check = time.time()
                    last_cleanup_check = time.time()
                    last_analysis_check = 0  #  启动时立即触发一次交易分析

                    #  启动时立即输出交易分析
                    print("[ANALYSIS] 启动时输出交易分析...")
                    await self.print_trading_analysis()
                    last_analysis_check = time.time()

                    while True:
                        # 接收WebSocket消息（带超时）
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
                                print(f"[WSS] 已接收{self.ws_message_count}条 | YES:{yes_p:.4f} NO:{no_p:.4f}")

                        except asyncio.TimeoutError:
                            pass  # 超时正常，继续执行定期任务

                        now = time.time()

                        # 每0.1秒检查持仓（极速响应止盈止损，抢占最佳成交价）
                        if now - last_positions_check >= 0.1:
                            await self.check_positions()
                            last_positions_check = now

                        # 每10秒验证预测（修复：只调用一次）
                        if now - last_prediction_check >= 10:
                            await self.verify_predictions()
                            last_prediction_check = now

                        # 每2秒检查交易信号
                        if now - last_trade_check >= 2:
                            await self.check_and_trade()
                            last_trade_check = now

                        # 每30秒自动调整参数
                        if now - last_adjust_check >= 30:
                            await self.auto_adjust()
                            last_adjust_check = now

                        # 每15分钟输出交易分析（新增）
                        if now - last_analysis_check >= 900:
                            elapsed = now - last_analysis_check
                            print(f"[ANALYSIS] 触发交易分析 (距上次{elapsed:.0f}秒)")
                            await self.print_trading_analysis()
                            last_analysis_check = now

                        # 每5分钟清理过期持仓
                        if now - last_cleanup_check >= 300:
                            #  状态锁：防止清理任务重复执行
                            action_key = "cleanup_stale_positions"

                            if action_key not in self._processing_orders:
                                self._processing_orders.add(action_key)

                                #  Fire-and-Forget：异步清理，不阻塞WebSocket
                                async def cleanup_task_with_unlock():
                                    try:
                                        await self._async_fire_and_forget(
                                            self.v5.cleanup_stale_positions,
                                            task_name="清理过期持仓"
                                        )
                                    finally:
                                        self._processing_orders.discard(action_key)

                                #  GC防护：抓住任务，防止被提前回收
                                task = asyncio.create_task(cleanup_task_with_unlock())
                                self._background_tasks.add(task)
                                task.add_done_callback(self._background_tasks.discard)

                            last_cleanup_check = now

                        # 检查是否需要切换市场
                        if self.market_end_time:
                            time_left = (self.market_end_time - datetime.now(timezone.utc)).total_seconds()
                            #  修复：只在剩余时间>0且<200秒时切换，避免已过期市场循环
                            if 0 < time_left < 200:
                                print(f"[SWITCH] 市场即将到期({time_left:.0f}秒)，切换到下一个15分钟窗口...")
                                self._reset_price_cache()
                                force_next_window = True  #  标记：强制使用下一个窗口
                                break
                            elif time_left <= 0:
                                # 市场已过期，强制重新获取市场
                                print(f"[SWITCH] 市场已过期({time_left:.0f}秒)，强制重新获取...")
                                self._reset_price_cache()
                                force_next_window = True  #  标记：强制使用下一个窗口
                                break
                        else:
                            # market_end_time 解析失败，用slug时间戳判断
                            if self.current_slug:
                                try:
                                    ts = int(self.current_slug.split('-')[-1])
                                    time_left = ts + 900 - int(datetime.now(timezone.utc).timestamp())
                                    #  修复：只在剩余时间>0且<200秒时切换
                                    if 0 < time_left < 200:
                                        print(f"[SWITCH] 市场即将到期(slug判断，剩余{time_left:.0f}秒)，切换...")
                                        self._reset_price_cache()
                                        force_next_window = True  #  标记：强制使用下一个窗口
                                        break
                                    elif time_left <= 0:
                                        # 市场已过期，强制重新获取市场
                                        print(f"[SWITCH] 市场已过期(slug判断，{time_left:.0f}秒)，强制重新获取...")
                                        self._reset_price_cache()
                                        force_next_window = True  #  标记：强制使用下一个窗口
                                        break
                                except:
                                    pass

            except websockets.exceptions.ConnectionClosed as e:
                print(f"[WSS] 连接断开: {e}，{self._reconnect_delay}秒后重连...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 30)
            except Exception as e:
                print(f"[WSS] 错误: {e}，{self._reconnect_delay}秒后重连...")
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
        finally:
            #  性能优化：关闭线程池，释放资源
            print("[PERF] 正在关闭线程池...")
            self.executor.shutdown(wait=True, cancel_futures=False)
            print("[PERF] 线程池已关闭")


async def main():
    engine = V6HFTEngine()
    await engine.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[STOP] 收到停止信号，正在退出...")
        sys.exit(0)
