#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V5 Auto Trading - Using Ankr API for Balance Detection (Continuous Mode)
"""

import sys
import time
import json
import os
import sqlite3
import requests
import math
import statistics
from datetime import datetime, timedelta, timezone
from collections import deque
from typing import Optional, Dict, Tuple
from dotenv import load_dotenv

# 代理配置（支持环境变量，云端部署可留空）
proxy = os.getenv('HTTP_PROXY', os.getenv('HTTPS_PROXY', ''))
if proxy:
    os.environ['HTTP_PROXY'] = proxy
    os.environ['HTTPS_PROXY'] = proxy
    print(f"[CONFIG] Using proxy: {proxy}")
else:
    print("[CONFIG] No proxy (direct connection)")

load_dotenv()

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, BalanceAllowanceParams, AssetType
    from py_clob_client.order_builder.constants import BUY, SELL
    CLOB_AVAILABLE = True
except ImportError:
    CLOB_AVAILABLE = False

# 导入预测学习系统
try:
    from prediction_learning_polymarket import PolymarketPredictionLearning
    LEARNING_AVAILABLE = True
except ImportError:
    LEARNING_AVAILABLE = False
    print("[WARN] 预测学习系统未找到，学习功能将被禁用")

CONFIG = {
    'clob_host': 'https://clob.polymarket.com',
    'gamma_host': 'https://gamma-api.polymarket.com',
    'chain_id': 137,
    'wallet_address': '0xd5d037390c6216CCFa17DFF7148549B9C2399BD3',  # 将从私钥自动生成
    'private_key': os.getenv('PRIVATE_KEY', ''),
    'proxy': {
        'http': os.getenv('HTTP_PROXY', os.getenv('HTTPS_PROXY', '')),
        'https': os.getenv('HTTPS_PROXY', os.getenv('HTTP_PROXY', ''))
    },

    # Ankr API for balance
    'ankr_rpc': 'https://rpc.ankr.com/polygon',
    'usdce_contract': '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174',  # USDC.e

    # Telegram 通知（支持环境变量配置）
    'telegram': {
        'enabled': os.getenv('TELEGRAM_ENABLED', 'true').lower() == 'true',
        'bot_token': os.getenv('TELEGRAM_BOT_TOKEN', ''),
        'chat_id': os.getenv('TELEGRAM_CHAT_ID', ''),
        'proxy': {'http': os.getenv('HTTP_PROXY', ''), 'https': os.getenv('HTTPS_PROXY', '')},
    },

    'risk': {
        'max_position_pct': 0.15,       # 15% per trade (to ensure min 2 USDC)
        'max_total_exposure_pct': 0.60,
        'reserve_usdc': 0.0,             # 🔥 不保留余额，全仓利用
        'min_position_usdc': 2.0,        # Minimum 2 USDC per order
        'max_daily_trades': 96,          # 15min市场: 96次/天 = 每15分钟1次
        'max_daily_loss_pct': 0.50,     # 50% daily loss (临时提高)
        'stop_loss_consecutive': 4,      # 提高到4（2太容易触发，错过机会）
        'pause_hours': 0.5,            # 缩短到0.5小时（2小时太长）
        'max_same_direction_bullets': 1,  # 同市场同方向最大持仓数（每窗口只开1单）
        'same_direction_cooldown_sec': 60,  # 同市场同方向最小间隔秒数
        'max_trades_per_window': 1,       # 每个15分钟窗口最多开单总数（防止多空横跳）
        'max_stop_loss_pct': 0.15,      # 最大止损15%
    },

    'signal': {
        'min_confidence': 0.75,  # 默认置信度（保留用于兼容）
        'min_long_confidence': 0.60,   # LONG最小置信度
        'min_short_confidence': 0.60,  # SHORT最小置信度
        'min_long_score': 4.0,      # 🔥 提高到4.0（LONG胜率22%，减少低质量信号）
        'min_short_score': -3.0,    # SHORT保持-3.0（胜率69%）
        'balance_zone_min': 0.49,  # 平衡区间下限
        'balance_zone_max': 0.51,  # 平衡区间上限
        'allow_long': True,   # 允许做多（但会动态调整）
        'allow_short': True,  # 允许做空（但会动态调整）

        # 🛡️ 价格限制（允许追强势单，但拒绝极高位接盘）
        'max_entry_price': 0.80,  # 最高入场价：0.80（允许追涨，但28%止损保护）
        'min_entry_price': 0.20,  # 最低入场价：0.20（允许抄底，但28%止损保护）

        # 动态调整参数
        'dynamic_lookback': 100,  # 最近100次交易用于评估
        'direction_threshold': 0.45,  # 降低到45%（60%太高，容易禁用某个方向）
    },

    'execution': {
        'cooldown': 60,
        'max_retries': 3,
        # 止盈止损配置
        'check_interval': 60,         # 每分钟检查一次持仓
    },

    'system': {
        'max_iterations': 100,
        'iteration_interval': 1,
        'dry_run': False,
    },
}

class TelegramNotifier:
    """Telegram 通知功能"""

    def __init__(self):
        self.enabled = CONFIG['telegram']['enabled']
        self.bot_token = CONFIG['telegram']['bot_token']
        self.chat_id = CONFIG['telegram']['chat_id']
        self.proxy = CONFIG['telegram']['proxy']
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        # 🚀 HTTP Session（复用TCP连接，提速Telegram通知）
        self.http_session = requests.Session()

    def send(self, message: str, parse_mode: str = None) -> bool:
        """发送Telegram消息

        Args:
            message: 消息内容
            parse_mode: 格式化模式 ('HTML' 或 'Markdown')

        Returns:
            bool: 是否发送成功
        """
        if not self.enabled:
            return False

        try:
            url = f"{self.base_url}/sendMessage"
            data = {
                'chat_id': self.chat_id,
                'text': message
            }
            if parse_mode:
                data['parse_mode'] = parse_mode

            # 🚀 使用Session复用TCP连接（提速Telegram通知）
            resp = self.http_session.post(url, json=data, proxies=self.proxy, timeout=10)
            if resp.status_code == 200:
                return True
            else:
                print(f"       [TELEGRAM ERROR] {resp.status_code}: {resp.text}")
                return False
        except Exception as e:
            print(f"       [TELEGRAM ERROR] {e}")
            return False

    def send_position_open(self, side: str, size: float, entry_price: float, value_usdc: float,
                          tp_price: float, sl_price: float, token_id: str, market_id: str):
        """发送开仓通知"""
        emoji = "🟢" if side == 'LONG' else "🔴"
        token_name = "YES" if side == 'LONG' else "NO"

        message = f"""{emoji} <b>开仓</b>

{emoji} 买入 {token_name}
💰 {value_usdc:.2f} USDC
📈 {size:.0f} 份 @ {entry_price:.4f}

🎯 止盈: {tp_price:.4f}
🛑 止损: {sl_price:.4f}"""

        return self.send(message, parse_mode='HTML')

    def send_stop_order_failed(self, side: str, size: float, tp_price: float, sl_price: float, token_id: str, error: str):
        """（已弃用）"""
        return False

    def send_position_closed(self, side: str, entry_price: float, exit_price: float, pnl_usd: float, reason: str):
        """（已弃用）"""
        return False

class RealBalanceDetector:
    """Get REAL balance using Ankr API"""

    def __init__(self, wallet: str):
        self.wallet = wallet
        self.balance_usdc = 0.0
        self.balance_pol = 0.0
        # 🚀 HTTP Session（复用TCP连接，提速RPC调用）
        self.http_session = requests.Session()

    def fetch(self) -> Tuple[float, float]:
        """Fetch real balance from Polygon"""
        print()
        # --- 强制使用网页版代理钱包查余额 ---
        CONFIG['wallet_address'] = "0xd5d037390c6216CCFa17DFF7148549B9C2399BD3"
        print("[BALANCE] Fetching REAL balance from Polygon...")

        try:
            # Use PublicNode RPC (works through proxy)
            url = "https://polygon-bor.publicnode.com"
            usdce_contract = CONFIG['usdce_contract']

            # Correctly format data for balanceOf call
            wallet_padded = self.wallet[2:].lower().rjust(64, '0')
            data = f"0x70a08231{wallet_padded}"

            # Get USDC.e balance
            payload = {
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [
                    {"to": usdce_contract, "data": data},
                    "latest"
                ],
                "id": 1
            }

            # 🚀 使用Session复用TCP连接（提速RPC调用）
            resp = self.http_session.post(url, json=payload, proxies=CONFIG['proxy'], timeout=10)

            if resp.status_code == 200:
                result = resp.json()
                if 'result' in result and result['result']:
                    result_hex = result['result']
                    balance_wei = int(result_hex, 16)
                    self.balance_usdc = balance_wei / 1e6  # USDC.e has 6 decimals
                    print(f"[OK] USDC.e balance: {self.balance_usdc:.2f}")
                else:
                    print("[WARN] No USDC.e found")
                    self.balance_usdc = 0.0
            else:
                print(f"[FAIL] Status {resp.status_code}")
                self.balance_usdc = 0.0

            # Get POL balance
            payload2 = {
                "jsonrpc": "2.0",
                "method": "eth_getBalance",
                "params": [self.wallet, "latest"],
                "id": 2
            }

            # 🚀 使用Session复用TCP连接（提速RPC调用）
            resp2 = self.http_session.post(url, json=payload2, proxies=CONFIG['proxy'], timeout=10)

            if resp2.status_code == 200:
                result2 = resp2.json()
                if 'result' in result2:
                    balance_wei = int(result2['result'], 16)
                    self.balance_pol = balance_wei / 1e18
                    print(f"[OK] POL balance: {self.balance_pol:.4f}")

            print()
            return self.balance_usdc, self.balance_pol

        except Exception as e:
            print(f"[ERROR] Balance fetch failed: {e}")
            print()
            print("[FATAL] 无法获取余额，为安全起见停止运行")
            print("[INFO] 请检查代理设置或网络连接")
            self.balance_usdc = 0.0
            self.balance_pol = 0.0
            return self.balance_usdc, self.balance_pol

class PositionManager:
    """Manage positions based on REAL balance"""

    def __init__(self, balance_usdc: float):
        self.balance = balance_usdc

    def calculate_position(self, confidence: float) -> float:
        available = self.balance - CONFIG['risk']['reserve_usdc']

        if available <= CONFIG['risk']['min_position_usdc']:
            return 0.0  # Not enough to meet minimum

        # Base position: 15% of balance
        base = self.balance * CONFIG['risk']['max_position_pct']

        # Adjust by confidence (0.3-1.0) -> (0.65-1.0 multiplier)
        mult = 0.5 + (confidence * 0.5)
        adjusted = base * mult

        # IMPORTANT: Must be at least 2 USDC
        min_required = CONFIG['risk']['min_position_usdc']
        final = max(adjusted, min_required)

        # But never exceed available balance (minus small buffer)
        max_safe = available * 0.95
        final = min(final, max_safe)

        # Round to 2 decimals
        final = round(final, 2)

        # Final sanity check
        if final < min_required or final > available:
            return 0.0

        return final

    def can_afford(self, amount: float) -> bool:
        available = self.balance - CONFIG['risk']['reserve_usdc']
        return amount <= available

    def get_max_daily_loss(self) -> float:
        return self.balance * CONFIG['risk']['max_daily_loss_pct']

class StandardRSI:
    def __init__(self, period: int = 14):
        self.period = period
        self.price_history = deque(maxlen=period + 1)
        self.current_rsi = 50.0

    def update(self, price: float) -> Optional[float]:
        self.price_history.append(price)
        if len(self.price_history) < self.period + 1:
            return None

        prices = list(self.price_history)
        gains, losses = [], []
        for i in range(1, len(prices)):
            change = prices[i] - prices[i - 1]
            gains.append(max(change, 0))
            losses.append(abs(min(change, 0)))

        avg_gain = sum(gains[-self.period:]) / self.period
        avg_loss = sum(losses[-self.period:]) / self.period

        if avg_loss == 0:
            self.current_rsi = 99.9 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            self.current_rsi = 100.0 - (100.0 / (1 + rs))

        self.current_rsi = max(0.1, min(99.9, self.current_rsi))
        return self.current_rsi

    def get_rsi(self) -> float:
        return self.current_rsi

    def is_ready(self) -> bool:
        return len(self.price_history) >= self.period + 1

class StandardVWAP:
    def __init__(self):
        self.vwap_numerator = 0.0
        self.vwap_denominator = 0.0
        self.current_vwap = 0.0
        self.last_reset_date = None

    def reset_at_midnight_utc(self):
        current_time = datetime.now(timezone.utc)
        current_date = current_time.date()
        if self.last_reset_date != current_date:
            self.vwap_numerator = 0.0
            self.vwap_denominator = 0.0
            self.last_reset_date = current_date
            return True
        return False

    def update(self, price: float, volume: float = 1.0):
        self.reset_at_midnight_utc()
        self.vwap_numerator += price * volume
        self.vwap_denominator += volume
        if self.vwap_denominator > 0:
            self.current_vwap = self.vwap_numerator / self.vwap_denominator

    def get_vwap(self) -> float:
        return self.current_vwap





class V5SignalScorer:
    def __init__(self):
        self.weights = {
            'price_momentum': 0.26,
            'volatility': 0.16,
            'vwap_status': 0.18,
            'rsi_status': 0.14,
            'trend_strength': 0.14,
            'orderbook_bias': 0.00,  # 已禁用
        }

    def calculate_score(self, price: float, rsi: float, vwap: float,
                       price_history: list) -> Tuple[float, Dict]:
        score = 0
        components = {}

        if len(price_history) >= 10:
            recent = price_history[-10:]
            momentum = (recent[-1] - recent[0]) / recent[0] * 100 if recent[0] > 0 else 0
            momentum_score = max(-10, min(10, momentum * 2))
            components['price_momentum'] = momentum_score
            score += momentum_score * self.weights['price_momentum']
        else:
            components['price_momentum'] = 0

        if len(price_history) >= 5:
            volatility = statistics.stdev(price_history[-5:])
            norm_vol = min(volatility / 0.1, 1.0)
            vol_score = (norm_vol - 0.5) * 10
            components['volatility'] = vol_score
            score += vol_score * self.weights['volatility']
        else:
            components['volatility'] = 0

        if vwap > 0:
            vwap_dist = ((price - vwap) / vwap * 100)
            if vwap_dist > 0.5:
                components['vwap_status'] = 1
            elif vwap_dist < -0.5:
                components['vwap_status'] = -1
            else:
                components['vwap_status'] = 0
            score += components['vwap_status'] * self.weights['vwap_status'] * 5
        else:
            components['vwap_status'] = 0

        # 放宽RSI阈值：从70/30改为60/40（15分钟合约需要更敏感）
        is_extreme = rsi > 60 or rsi < 40
        if rsi > 60:
            components['rsi_status'] = -1
        elif rsi < 40:
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


        score = max(-10, min(10, score))
        return score, components

    def calculate_score_with_orderbook(self, price: float, rsi: float, vwap: float,
                                        price_history: list, ob_bias: float) -> Tuple[float, Dict]:
        """带订单簿偏向的评分（ob_bias: -1.0~+1.0）"""
        score, components = self.calculate_score(price, rsi, vwap, price_history)
        ob_score = ob_bias * 2.0
        components['orderbook_bias'] = ob_score
        score += ob_score * self.weights['orderbook_bias'] * 10
        score = max(-10, min(10, score))
        return score, components

class AutoTraderV5:
    def __init__(self):
        # --- 强制使用网页版代理钱包 ---
        wallet_address = "0xd5d037390c6216CCFa17DFF7148549B9C2399BD3" 
        CONFIG['wallet_address'] = wallet_address

        print("=" * 70)
        print("V5 Auto Trading - WITH REAL BALANCE")
        print("=" * 70)
        print(f"Wallet: {wallet_address}")
        print()

        # Fetch REAL balance
        self.balance_detector = RealBalanceDetector(wallet_address)
        usdc, pol = self.balance_detector.fetch()

        # Position manager with REAL balance
        self.position_mgr = PositionManager(usdc)

        print("[BALANCE] Trading Configuration:")
        print(f"  REAL Balance: {usdc:.2f} USDC.e")
        print(f"  Available: {usdc - CONFIG['risk']['reserve_usdc']:.2f} USDC")
        print(f"  Reserve: {CONFIG['risk']['reserve_usdc']:.2f} USDC")
        print(f"  Min Position: {CONFIG['risk']['min_position_usdc']:.2f} USDC (Polymarket requirement)")
        print(f"  Max Position: {usdc * CONFIG['risk']['max_position_pct']:.2f} USDC (10%)")
        print(f"  Max Daily Loss: {self.position_mgr.get_max_daily_loss():.2f} USDC (20%)")
        print(f"  Estimated Trades: {int((usdc - CONFIG['risk']['reserve_usdc']) / 2)} trades")
        print()

        # Telegram 通知
        self.telegram = TelegramNotifier()
        if self.telegram.enabled:
            print("[TELEGRAM] 通知已启用")
        print()

        # Indicators
        self.rsi = StandardRSI(period=14)
        self.vwap = StandardVWAP()
        self.scorer = V5SignalScorer()
        self.price_history = deque(maxlen=20)

        # 🚀 HTTP Session池（复用TCP连接，提速3-5倍）
        self.http_session = requests.Session()
        # 配置连接池
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=20
        )
        self.http_session.mount("http://", adapter)
        self.http_session.mount("https://", adapter)

        # CLOB client
        self.client = None
        self.init_clob_client()

        # Stats
        self.stats = {
            'total_trades': 0,
            'wins': 0,
            'losses': 0,
            'consecutive_losses': 0,
            'daily_trades': 0,
            'daily_loss': 0.0,
            'total_pnl': 0.0,
            'last_trade_time': None,
            'signal_count': 0,  # 信号计数器（用于动态参数调整）
        }

        self.is_paused = False
        self.pause_until = None
        self.last_reset_date = datetime.now().date()
        self.last_traded_market = None  # 追踪最后交易的市场
        self.last_signal_direction = None  # 追踪上一次信号方向（用于信号改变检测）
        self.init_database()

        # 从数据库恢复当天的亏损和交易统计（防止重启后风控失效）
        self._restore_daily_stats()

        # 预测学习系统
        self.learning_system = None
        self.last_learning_report = 0
        if LEARNING_AVAILABLE:
            try:
                # 传入当前实际参数，让学习系统生成动态建议
                current_params = {
                    'min_confidence': CONFIG['signal']['min_confidence'],
                    'min_long_score': CONFIG['signal']['min_long_score'],
                    'min_short_score': CONFIG['signal']['min_short_score']
                }
                self.learning_system = PolymarketPredictionLearning(current_params=current_params)
                print("[OK] 预测学习系统已启用")
            except Exception as e:
                print(f"[WARN] 学习系统初始化失败: {e}")

        print("[OK] System Ready - Using REAL Balance!")
        print()

        # 恢复上次自动调整的参数
        self.load_dynamic_params()


        # 启动时清理过期持仓
        self.cleanup_stale_positions()

    def cleanup_stale_positions(self):
        """启动时清理过期持仓（超过20分钟的open持仓自动平仓）"""
        try:
            if not self.client:
                print("[CLEANUP] 跳过：CLOB客户端未初始化")
                return

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            # 获取更完整的持仓信息
            cursor.execute("""
                SELECT id, entry_time, side, entry_token_price, size, token_id,
                       take_profit_order_id, stop_loss_order_id
                FROM positions
                WHERE status = 'open'
            """)
            positions = cursor.fetchall()
            cleaned = 0
            for pos_id, entry_time, side, entry_price, size, token_id, tp_order_id, sl_order_id in positions:
                try:
                    entry_dt = datetime.strptime(entry_time, '%Y-%m-%d %H:%M:%S')
                    elapsed = (datetime.now() - entry_dt).total_seconds()
                    if elapsed > 1200:  # 超过20分钟
                        print(f"[CLEANUP] 持仓 #{pos_id} 超过20分钟，执行清理")

                        # 取消链上的止盈止损单
                        if tp_order_id:
                            try:
                                self.cancel_order(tp_order_id)
                                print(f"[CLEANUP] 已取消止盈单: {tp_order_id[-8:]}")
                            except:
                                pass
                        if sl_order_id:
                            try:
                                self.cancel_order(sl_order_id)
                                print(f"[CLEANUP] 已取消止损单: {sl_order_id[-8:]}")
                            except:
                                pass

                        # 尝试市价平仓
                        try:
                            from py_clob_client.clob_types import OrderArgs
                            import time

                            # 获取当前市场价格（使用 /price API）
                            try:
                                price_url = "https://clob.polymarket.com/price"
                                # 🚀 使用Session复用TCP连接（提速价格查询）
                                price_resp = self.http_session.get(
                                    price_url,
                                    params={"token_id": token_id, "side": "BUY"},
                                    proxies=CONFIG['proxy'],
                                    timeout=10
                                )
                                if price_resp.status_code == 200:
                                    price_data = price_resp.json()
                                    current_price = float(price_data.get('price', entry_price))
                                else:
                                    current_price = entry_price
                            except:
                                current_price = entry_price

                            # 计算平仓价格（打3%折确保成交）
                            close_price = max(0.01, current_price * 0.97)

                            close_order_args = OrderArgs(
                                token_id=token_id,
                                price=close_price,
                                size=float(size),
                                side=SELL
                            )

                            print(f"[CLEANUP] 挂市价平仓单: {close_price:.4f} × {size:.0f}")
                            close_response = self.client.create_and_post_order(close_order_args)

                            if close_response and 'orderID' in close_response:
                                close_order_id = close_response['orderID']
                                print(f"[CLEANUP] 平仓单已挂: {close_order_id[-8:]}")

                                # 等待成交
                                for wait_i in range(5):
                                    time.sleep(1)
                                    try:
                                        close_order = self.client.get_order(close_order_id)
                                        if close_order and close_order.get('status') in ('FILLED', 'MATCHED'):
                                            filled_price = close_order.get('price', close_price)
                                            # 计算盈亏（统一公式）
                                            pnl_usd = size * (filled_price - entry_price)
                                            pnl_pct = (pnl_usd / (size * entry_price)) * 100 if size * entry_price > 0 else 0

                                            cursor.execute("""
                                                UPDATE positions
                                                SET status='closed', exit_reason='STALE_CLEANUP',
                                                    exit_time=?, exit_token_price=?, pnl_usd=?, pnl_pct=?
                                                WHERE id=?
                                            """, (
                                                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                                filled_price,
                                                pnl_usd,
                                                pnl_pct,
                                                pos_id
                                            ))
                                            conn.commit()
                                            print(f"[CLEANUP] ✅ 持仓 #{pos_id} 已平仓: ${pnl_usd:+.2f} ({pnl_pct:+.1f}%)")
                                            # 更新 daily_loss 统计
                                            if pnl_usd < 0:
                                                self.stats['daily_loss'] += abs(pnl_usd)
                                            cleaned += 1
                                            break
                                    except:
                                        pass
                                else:
                                    # 等待超时，但仍然标记为closed
                                    print(f"[CLEANUP] ⚠️  平仓单未立即成交，标记为closed")
                                    cursor.execute("""
                                        UPDATE positions SET status='closed', exit_reason='STALE_CLEANUP',
                                        exit_time=? WHERE id=?
                                    """, (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), pos_id))
                                    conn.commit()
                                    cleaned += 1
                            else:
                                print(f"[CLEANUP] ❌ 平仓单失败，仅标记为closed")
                                cursor.execute("""
                                    UPDATE positions SET status='closed', exit_reason='STALE_CLEANUP',
                                    exit_time=? WHERE id=?
                                """, (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), pos_id))
                                conn.commit()
                                cleaned += 1

                        except Exception as close_error:
                            err_msg = str(close_error)
                            # 检查是否是订单簿不存在的错误（市场已结算）
                            if 'orderbook' in err_msg and 'does not exist' in err_msg:
                                print(f"[CLEANUP] ⚠️  市场已结算，订单簿已关闭")
                                # 使用当前价格计算盈亏并标记为closed
                                try:
                                    # 尝试获取当前市场价格（使用 /price API）
                                    price_url = "https://clob.polymarket.com/price"
                                    # 🚀 使用Session复用TCP连接（提速价格查询）
                                    price_resp = self.http_session.get(
                                        price_url,
                                        params={"token_id": token_id, "side": "BUY"},
                                        proxies=CONFIG['proxy'],
                                        timeout=10
                                    )
                                    if price_resp.status_code == 200:
                                        price_data = price_resp.json()
                                        settle_price = float(price_data.get('price', entry_price))
                                    else:
                                        settle_price = entry_price
                                except:
                                    settle_price = entry_price

                                # 计算盈亏（统一公式）
                                pnl_usd = size * (settle_price - entry_price)
                                pnl_pct = (pnl_usd / (size * entry_price)) * 100 if size * entry_price > 0 else 0

                                cursor.execute("""
                                    UPDATE positions
                                    SET status='closed', exit_reason='STALE_CLEANUP',
                                        exit_time=?, exit_token_price=?, pnl_usd=?, pnl_pct=?
                                    WHERE id=?
                                """, (
                                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                    settle_price, pnl_usd, pnl_pct, pos_id
                                ))
                                conn.commit()
                                print(f"[CLEANUP] ✅ 持仓 #{pos_id} 已结算: ${pnl_usd:+.2f} ({pnl_pct:+.1f}%) @ {settle_price:.4f}")
                                # 更新 daily_loss 统计
                                if pnl_usd < 0:
                                    self.stats['daily_loss'] += abs(pnl_usd)
                                cleaned += 1
                            else:
                                print(f"[CLEANUP] 平仓失败: {close_error}")
                                # 即使平仓失败，也标记为closed
                                cursor.execute("""
                                    UPDATE positions SET status='closed', exit_reason='STALE_CLEANUP',
                                    exit_time=? WHERE id=?
                                """, (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), pos_id))
                                conn.commit()
                                cleaned += 1

                except Exception as e:
                    print(f"[CLEANUP] 处理持仓 #{pos_id} 失败: {e}")
                    pass

            conn.close()
            if cleaned > 0:
                print(f"[CLEANUP] ✅ 清理了 {cleaned} 笔过期持仓")
        except Exception as e:
            print(f"[CLEANUP ERROR] {e}")

    def init_clob_client(self):
        if not CONFIG['private_key'] or not CLOB_AVAILABLE:
            print("[INFO] Signal mode only (no CLOB client)")
            return

        try:
            print("[CLOB] Initializing...")
            
            # 1. 临时客户端也必须加上代理模式配置，申请正确的代理版通行证！
            temp_client = ClobClient(
                CONFIG['clob_host'],
                key=CONFIG['private_key'],
                chain_id=CONFIG['chain_id'],
                signature_type=2,                # <--- 【核心修复：多签钱包类型】
                funder=CONFIG['wallet_address']  # <--- 【核心修复：代理地址】
            )
            api_creds = temp_client.create_or_derive_api_creds()

            # 2. 将代理版通行证注入正式客户端
            self.client = ClobClient(
                CONFIG['clob_host'],
                key=CONFIG['private_key'],
                chain_id=CONFIG['chain_id'],
                creds=api_creds,
                signature_type=2,                # <--- 【核心修复：多签钱包类型】
                funder=CONFIG['wallet_address']  # <--- 【核心修复：代理地址】
            )

            # 初始化时做一次全局授权（解决 not enough balance / allowance）
            try:
                self.update_allowance_fixed(AssetType.COLLATERAL)
                print("[OK] USDC 授权完成")
            except Exception as e:
                print(f"[WARN] USDC 授权失败（可忽略）: {e}")

            print("[OK] CLOB Ready")
            print("[INFO] 如遇到 'not enough balance / allowance' 错误")
            print("       请先运行: python 一键授权.py")
        except Exception as e:
            print(f"[WARN] CLOB Failed: {e}")
            self.client = None

    def init_database(self):
        self.db_path = '/tmp/btc_15min_auto_trades.db'
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 交易表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                side TEXT,
                price REAL,
                value_usd REAL,
                signal_score REAL,
                confidence REAL,
                rsi REAL,
                vwap REAL,
                order_id TEXT,
                status TEXT
            )
        """)

        # 持仓表（用于止盈止损监控和未来优化）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_time TEXT,
                side TEXT,
                entry_token_price REAL,
                size REAL,
                value_usdc REAL,
                take_profit_usd REAL DEFAULT 1.0,
                stop_loss_usd REAL DEFAULT 1.0,
                take_profit_pct REAL,
                stop_loss_pct REAL,
                take_profit_order_id TEXT,
                stop_loss_order_id TEXT,
                token_id TEXT,
                exit_time TEXT,
                exit_token_price REAL,
                pnl_usd REAL,
                pnl_pct REAL,
                exit_reason TEXT,
                status TEXT DEFAULT 'open'
            )
        """)

        conn.commit()

        # 兼容旧数据库：添加 token_id 列（如果不存在）
        try:
            cursor.execute("ALTER TABLE positions ADD COLUMN token_id TEXT")
            conn.commit()
        except:
            pass  # 列已存在，忽略

        conn.close()

    def _restore_daily_stats(self):
        """从数据库恢复当天的亏损和交易统计，防止重启后风控失效"""
        try:
            today = datetime.now().date().strftime('%Y-%m-%d')
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 恢复当天已关闭持仓的亏损总额
            cursor.execute("""
                SELECT COALESCE(SUM(ABS(pnl_usd)), 0)
                FROM positions
                WHERE status = 'closed'
                  AND pnl_usd < 0
                  AND date(exit_time) = ?
            """, (today,))
            row = cursor.fetchone()
            if row and row[0]:
                self.stats['daily_loss'] = float(row[0])

            # 恢复当天交易次数
            cursor.execute("""
                SELECT COUNT(*) FROM trades
                WHERE date(timestamp) = ? AND status = 'posted'
            """, (today,))
            row2 = cursor.fetchone()
            if row2 and row2[0]:
                self.stats['daily_trades'] = int(row2[0])

            conn.close()
            print(f"[RESTORE] 当天统计已恢复: 亏损=${self.stats['daily_loss']:.2f}, 交易={self.stats['daily_trades']}次")
        except Exception as e:
            print(f"[RESTORE] 恢复统计失败（不影响运行）: {e}")

    def record_prediction_learning(self, market: Dict, signal: Dict, order_result: Optional[Dict], was_blocked: bool = False):
        if not self.learning_system:
            return

        try:
            # 【去重检查】过滤重复信号（同一15分钟窗口内相同方向的信号只记录一次）
            market_slug = market.get('slug', '')
            # 去重key：市场窗口（slug）+ 方向
            signal_key = f"{market_slug}_{signal['direction']}"

            # 检查最近是否已记录过该窗口的该方向信号
            if not hasattr(self, '_last_signals'):
                self._last_signals = {}

            # 如果该窗口该方向已记录过，跳过
            if signal_key in self._last_signals:
                return  # 跳过重复信号

            # 记录该窗口该方向的信号
            self._last_signals[signal_key] = datetime.now()

            # 清理过期的信号记录（1小时前的）
            current_time = datetime.now()
            self._last_signals = {
                k: v for k, v in self._last_signals.items()
                if (current_time - v).total_seconds() < 3600
            }

            order_value = order_result.get('value', 0) if order_result else 0
            order_status = order_result.get('status', 'failed') if order_result else 'failed'
            entry_token_price = order_result.get('price', signal['price']) if order_result else signal['price']

            score = signal['score']
            if score >= 7:
                recommendation = f"强烈看涨 (做多YES) - 评分{score:.1f}"
            elif score >= 2.5:
                recommendation = f"看涨 (做多YES) - 评分{score:.1f}"
            elif score <= -7:
                recommendation = f"强烈看跌 (做多NO) - 评分{score:.1f}"
            elif score <= -2.5:
                recommendation = f"看跌 (做多NO) - 评分{score:.1f}"
            else:
                recommendation = f"持有 - 评分{score:.1f}"

            # 计算当前止盈止损百分比（基于真实token价格和固定1U）
            tp_pct = None
            sl_pct = None
            if order_result and order_result.get('status') == 'posted':
                real_token_price = order_result.get('token_price', entry_token_price)
                size = order_result.get('size', 0)
                if size > 0 and real_token_price > 0:
                    real_value = size * real_token_price
                    tp_price = (real_value + 1.0) / size
                    sl_price = (real_value - 1.0) / size
                    tp_pct = round((tp_price - real_token_price) / real_token_price, 4)
                    sl_pct = round((real_token_price - sl_price) / real_token_price, 4)

            self.learning_system.record_prediction(
                price=signal['price'],
                score=signal['score'],
                rsi=signal['rsi'],
                vwap=signal['vwap'],
                confidence=signal['confidence'],
                direction=signal['direction'],
                recommendation=recommendation,
                components=signal.get('components', {}),
                market_slug=market_slug,
                order_value=order_value,
                order_status=order_status,
                was_blocked=was_blocked,
                tp_pct=tp_pct,
                sl_pct=sl_pct,
                entry_token_price=entry_token_price,
            )
        except Exception as e:
            print(f"       [LEARNING ERROR] {e}")

    def verify_pending_predictions(self):
        if not self.learning_system:
            return 0
        try:
            return self.learning_system.verify_pending_predictions()
        except Exception as e:
            print(f"       [LEARNING VERIFY ERROR] {e}")
            return 0

    def _get_last_market_slug(self, pos_id: int = None) -> str:
        """获取指定持仓对应的市场 slug，用于学习系统回填
        
        通过 positions.token_id 反查 predictions 表中对应的 market_slug。
        多持仓时每个持仓独立查询，避免回填到错误记录。
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            if pos_id:
                # 通过 token_id 直接匹配 predictions 表的 market_slug
                cursor.execute("""
                    SELECT token_id, entry_time FROM positions WHERE id = ?
                """, (pos_id,))
                row = cursor.fetchone()
                if row:
                    token_id, entry_time = row
                    # 在 predictions 表里找最近一条匹配该 token 的记录
                    try:
                        pred_conn = sqlite3.connect('btc_15min_predictionsv2.db')
                        pred_cursor = pred_conn.cursor()
                        pred_cursor.execute("""
                            SELECT market_slug FROM predictions
                            WHERE timestamp <= ? AND market_slug IS NOT NULL
                            ORDER BY timestamp DESC LIMIT 1
                        """, (entry_time,))
                        pred_row = pred_cursor.fetchone()
                        pred_conn.close()
                        if pred_row and pred_row[0]:
                            conn.close()
                            return pred_row[0]
                    except:
                        pass
            conn.close()
        except:
            pass
        return self.last_traded_market or ''

    def print_learning_reports(self):
        if not self.learning_system:
            return
        try:
            self.learning_system.print_accuracy_report()
            self.learning_system.print_optimization_report()
            self.learning_system.print_tp_sl_report()
        except Exception as e:
            print(f"       [LEARNING REPORT ERROR] {e}")

    def get_market_data(self) -> Optional[Dict]:
        try:
            now = int(time.time())
            aligned = (now // 900) * 900

            # 尝试当前窗口，如果过期则尝试下一个窗口
            for offset in [0, 900]:
                slug = f"btc-updown-15m-{aligned + offset}"

                # 🚀 使用Session复用TCP连接（提速3-5倍）
                response = self.http_session.get(
                    f"{CONFIG['gamma_host']}/markets",
                    params={'slug': slug},
                    proxies=CONFIG['proxy'],
                    timeout=10
                )

                if response.status_code == 200:
                    markets = response.json()
                    if markets:
                        market = markets[0]

                        # 过滤：市场结算前2分钟停止交易
                        end_date = market.get('endDate')
                        if end_date:
                            try:
                                from datetime import timezone
                                end_dt = datetime.strptime(end_date, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                                now_dt = datetime.now(timezone.utc)
                                seconds_left = (end_dt - now_dt).total_seconds()
                                if seconds_left < 0:
                                    # 市场已过期，尝试下一个
                                    continue
                                if seconds_left < 120:
                                    print(f"       [MARKET] 市场即将结算({seconds_left:.0f}秒)，跳过")
                                    return None
                            except Exception:
                                pass

                        return market

            return None
        except:
            return None

    def parse_price(self, market: Dict) -> Optional[float]:
        try:
            outcome_prices = market.get('outcomePrices', '[]')
            if isinstance(outcome_prices, str):
                outcome_prices = json.loads(outcome_prices)
            if outcome_prices and len(outcome_prices) >= 1:
                return float(outcome_prices[0])
            return None
        except:
            return None

    def update_indicators(self, price: float, high: float = 0.0, low: float = 0.0):
        self.rsi.update(price)
        self.vwap.update(price)
        self.price_history.append(price)

    def _read_oracle_signal(self) -> Optional[Dict]:
        """读取 binance_oracle.py 输出的信号文件，超过10秒视为过期"""
        try:
            oracle_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'oracle_signal.json')
            if not os.path.exists(oracle_path):
                return None
            with open(oracle_path, 'r') as f:
                data = json.load(f)
            # 超过10秒的数据视为过期
            if time.time() - data.get('ts_unix', 0) > 10:
                return None
            return data
        except Exception:
            return None

    def generate_signal(self, market: Dict, price: float) -> Optional[Dict]:
        # 注意：V5主循环在调用generate_signal前已调用update_indicators
        # V6的update_price_from_ws每秒也会调用update_indicators
        # 这里不再重复调用，避免同一价格点被更新多次导致RSI/VWAP失真
        if not self.rsi.is_ready():
            return None

        rsi = self.rsi.get_rsi()
        vwap = self.vwap.get_vwap()
        price_hist = list(self.price_history)

        # === 统一价格过滤（整合三处分散的过滤逻辑）===
        # 有效入场区间：0.35~0.48 和 0.52~0.65
        # 低于0.35或高于0.65：风险收益比太差
        # 0.48~0.52：平衡区，信号不明确
        max_entry = CONFIG['signal'].get('max_entry_price', 0.65)
        min_entry = CONFIG['signal'].get('min_entry_price', 0.35)
        bal_min = CONFIG['signal']['balance_zone_min']
        bal_max = CONFIG['signal']['balance_zone_max']

        if price > max_entry:
            return None
        if price < min_entry:
            return None
        if bal_min <= price <= bal_max:
            return None

        # 获取NO价格，过滤市场一边倒情况
        try:
            outcome_prices = market.get('outcomePrices', '[]')
            if isinstance(outcome_prices, str):
                outcome_prices = json.loads(outcome_prices)
            no_price = float(outcome_prices[1]) if len(outcome_prices) > 1 else (1.0 - price)
            if price > 0.80:
                print(f"       [FILTER] YES价格 {price:.4f} > 0.80（市场过于看涨），跳过")
                return None
            if no_price > 0.80:
                print(f"       [FILTER] NO价格 {no_price:.4f} > 0.80（市场过于看跌），跳过")
                return None
        except:
            pass

        # 评分（ob_bias固定为0，orderbook_bias权重已禁用）
        score, components = self.scorer.calculate_score(price, rsi, vwap, price_hist)

        # ========== 双核融合：读取币安先知Oracle信号 ==========
        oracle = self._read_oracle_signal()
        oracle_score = 0.0
        if oracle:
            oracle_score = oracle.get('signal_score', 0.0)
            # Oracle分数映射到本地评分体系（Oracle±10 → 本地±2加成）
            oracle_boost = oracle_score / 5.0
            score += oracle_boost
            print(f"       [ORACLE] 先知分: {oracle_score:+.2f} | CVD(15m): {oracle.get('cvd_15m', 0):+.1f} | 盘口失衡: {oracle.get('wall_imbalance', 0)*100:+.1f}% | 融合后评分: {score:.2f}")
        # ======================================================

        confidence = min(abs(score) / 5.0, 0.99)

        direction = None
        min_long_conf = CONFIG['signal'].get('min_long_confidence', CONFIG['signal']['min_confidence'])
        min_short_conf = CONFIG['signal'].get('min_short_confidence', CONFIG['signal']['min_confidence'])

        # 极端Oracle信号（>8或<-8）直接触发，绕过本地评分门槛
        if oracle and abs(oracle_score) >= 8.0:
            if oracle_score >= 8.0 and price <= CONFIG['signal'].get('max_entry_price', 0.65):
                direction = 'LONG'
                print(f"       [ORACLE] 🚀 极端看涨信号({oracle_score:+.2f})，强制触发LONG！")
            elif oracle_score <= -8.0 and price >= CONFIG['signal'].get('min_entry_price', 0.35):
                direction = 'SHORT'
                print(f"       [ORACLE] 🔻 极端看跌信号({oracle_score:+.2f})，强制触发SHORT！")
        else:
            if score >= CONFIG['signal']['min_long_score'] and confidence >= min_long_conf:
                direction = 'LONG'
            elif score <= CONFIG['signal']['min_short_score'] and confidence >= min_short_conf:
                direction = 'SHORT'

        if direction:
            return {
                'direction': direction,
                'score': score,
                'confidence': confidence,
                'rsi': rsi,
                'vwap': vwap,
                'price': price,
                'components': components,
                'oracle_score': oracle_score,
            }
        return None

    def can_trade(self, signal: Dict, market: Dict = None) -> Tuple[bool, str]:
        # 检查是否新的一天，重置每日统计
        current_date = datetime.now().date()
        if self.last_reset_date != current_date:
            self.stats['daily_trades'] = 0
            self.stats['daily_loss'] = 0.0
            self.last_reset_date = current_date
            self.last_traded_market = None  # 重置最后交易的市场
            print(f"       [RESET] 新的一天，每日统计已重置")

        # 检查是否进入新的15分钟窗口（自动重置last_traded_market）
        if market and self.last_traded_market:
            current_slug = market.get('slug', '')
            if current_slug != self.last_traded_market:
                # 新的15分钟窗口，重置交易限制
                print(f"       [RESET] 新的15分钟窗口: {self.last_traded_market} → {current_slug}")
                self.last_traded_market = None

        # 【已禁用】每个市场只交易一次的限制（改为：同一市场只要没持仓就可以再开单）
        # 原因：15分钟合约内可能有多次交易机会（止盈后立即开新单）
        # if market and self.last_traded_market:
        #     current_slug = market.get('slug', '')
        #     if current_slug == self.last_traded_market:
        #         return False, "Already traded this market"

        # --- 检查持仓冲突 ---
        positions = self.get_positions()
        if signal['direction'] == 'LONG' and 'SHORT' in positions and positions['SHORT'] > 0:
            return False, f"Conflict: 已有 {positions['SHORT']:.0f} 空头仓位，无法做多"
        if signal['direction'] == 'SHORT' and 'LONG' in positions and positions['LONG'] > 0:
            return False, f"Conflict: 已有 {positions['LONG']:.0f} 多头仓位，无法做空"

        # 🛡️ === 核心风控：同市场同向"弹匣限制"与"射击冷却" ===
        if market:
            token_ids = market.get('clobTokenIds', [])
            if isinstance(token_ids, str):
                import json
                token_ids = json.loads(token_ids)

            if token_ids:
                try:
                    conn = sqlite3.connect(self.db_path)
                    cursor = conn.cursor()

                    # 使用 token_id 判断同一市场（每个15分钟市场有唯一的 token_id）
                    # LONG 用 YES token (index 0), SHORT 用 NO token (index 1)
                    token_id = str(token_ids[0] if signal['direction'] == 'LONG' else token_ids[1])

                    # 1. 弹匣限制：只统计当前15分钟窗口内的交易（加时间过滤）
                    # 当前窗口开始时间 = 当前UTC时间对齐到15分钟
                    from datetime import timezone as tz
                    now_utc = datetime.now(tz.utc)
                    window_start_ts = (int(now_utc.timestamp()) // 900) * 900
                    window_start_str = datetime.fromtimestamp(window_start_ts).strftime('%Y-%m-%d %H:%M:%S')

                    # 检查当前窗口同方向开单数
                    cursor.execute("""
                        SELECT count(*), max(entry_time)
                        FROM positions
                        WHERE token_id = ? AND side = ?
                          AND entry_time >= ?
                    """, (token_id, signal['direction'], window_start_str))

                    row = cursor.fetchone()
                    open_count = row[0] if row else 0
                    last_entry_time_str = row[1] if row and row[1] else None

                    # 检查当前窗口所有方向总开单数（防止多空横跳）
                    max_per_window = CONFIG['risk'].get('max_trades_per_window', 1)
                    yes_token_id = str(token_ids[0])
                    no_token_id = str(token_ids[1])
                    cursor.execute("""
                        SELECT count(*) FROM positions
                        WHERE (token_id = ? OR token_id = ?)
                          AND entry_time >= ?
                    """, (yes_token_id, no_token_id, window_start_str))
                    total_row = cursor.fetchone()
                    total_window_trades = total_row[0] if total_row else 0

                    conn.close()

                    if total_window_trades >= max_per_window:
                        return False, f"窗口限制: 本15分钟窗口已开{total_window_trades}单，最多{max_per_window}单"

                    # 弹匣限制：同一市场同一方向最多N发子弹
                    max_bullets = CONFIG['risk']['max_same_direction_bullets']
                    if open_count >= max_bullets:
                        return False, f"弹匣耗尽: {token_id[-8:]} {signal['direction']}已达最大持仓({max_bullets}单)"

                    # 射击冷却：距离上一单必须超过N秒
                    cooldown_sec = CONFIG['risk']['same_direction_cooldown_sec']
                    if last_entry_time_str:
                        last_entry_time = datetime.strptime(last_entry_time_str, '%Y-%m-%d %H:%M:%S')
                        seconds_since_last = (datetime.now() - last_entry_time).total_seconds()

                        if seconds_since_last < cooldown_sec:
                            remaining_sec = cooldown_sec - seconds_since_last
                            return False, f"⏳ 射击冷却中: 距离上一单仅{seconds_since_last:.0f}秒 (需>{cooldown_sec}s)"

                except Exception as e:
                    print(f"       [RISK CHECK ERROR] {e}")
                    # 风控检查失败时保守处理：允许交易（避免因bug错失机会）
                    pass

        # 🛡️ === 第一斧：时间防火墙（拒绝垃圾时间） ===
        # 注意：get_market_data 已过滤过期市场，这里只做二次确认
        if market:
            time_left = None
            try:
                # 统一用 endDate（与 get_market_data 保持一致，避免 endTimestamp 解析歧义）
                end_date = market.get('endDate')
                if end_date:
                    end_dt = datetime.strptime(end_date, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                    time_left = (end_dt - datetime.now(timezone.utc)).total_seconds()
            except Exception as e:
                return False, f"🛡️ 时间防火墙: 无法解析市场时间({e})，拒绝开仓"

            if time_left is not None:
                if time_left < 0:
                    # 市场已过期，拒绝开仓
                    return False, f"🛡️ 时间防火墙: 市场已过期({time_left:.0f}秒)，拒绝开仓"
                if time_left < 180:
                    return False, f"🛡️ 时间防火墙: 距离结算仅{time_left:.0f}秒，拒绝开仓"
            else:
                return False, "🛡️ 时间防火墙: 缺少市场结束时间，拒绝开仓"

        # 🛡️ === 第二斧：拒绝高位接盘（只做均势局） ===
        price = signal.get('price', 0.5)
        max_entry_price = CONFIG['signal'].get('max_entry_price', 0.65)
        min_entry_price = CONFIG['signal'].get('min_entry_price', 0.35)

        if price > max_entry_price:
            return False, f"🛡️ 拒绝高位接盘: {price:.4f} > {max_entry_price:.2f} (利润空间太小)"
        if price < min_entry_price:
            return False, f"🛡️ 拒绝极端低位: {price:.4f} < {min_entry_price:.2f} (风险太大)"

        # --- 检查是否允许做多/做空（动态调整）---
        if signal['direction'] == 'LONG' and not CONFIG['signal']['allow_long']:
            return False, "LONG disabled (low accuracy)"
        if signal['direction'] == 'SHORT' and not CONFIG['signal']['allow_short']:
            return False, "SHORT disabled (low accuracy)"

        if self.is_paused:
            if self.pause_until and datetime.now() < self.pause_until:
                remaining = int((self.pause_until - datetime.now()).total_seconds() / 60)
                return False, f"Paused {remaining}m"
            else:
                self.is_paused = False
                self.pause_until = None
                self.stats['consecutive_losses'] = 0

        # 每日最大亏损检查
        max_loss = self.position_mgr.get_max_daily_loss()
        if self.stats['daily_loss'] >= max_loss:
            # 检查是否是新的一天，如果是则重置
            if datetime.now().date() > self.last_reset_date:
                self.stats['daily_loss'] = 0.0
                self.stats['daily_trades'] = 0
                self.last_reset_date = datetime.now().date()
                print(f"       [RESET] 新的一天，每日亏损已重置")
            else:
                return False, f"Daily loss limit reached (${self.stats['daily_loss']:.2f}/${max_loss:.2f})"

        if self.stats['consecutive_losses'] >= CONFIG['risk']['stop_loss_consecutive']:
            self.is_paused = True
            self.pause_until = datetime.now() + timedelta(hours=CONFIG['risk']['pause_hours'])
            return False, f"3 losses - pause {CONFIG['risk']['pause_hours']}h"

        return True, "OK"

    def get_positions(self) -> Dict[str, float]:
        """查询当前持仓（从 positions 表）"""
        positions = {}  # {side: size}
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 从 positions 表获取当前持仓
            cursor.execute("""
                SELECT side, size
                FROM positions
                WHERE status = 'open'
            """)

            for row in cursor.fetchall():
                side, size = row
                if side in positions:
                    positions[side] += size
                else:
                    positions[side] = size

            conn.close()
        except Exception as e:
            print(f"       [POS CHECK ERROR] {e}")

        return positions

    def get_real_positions(self) -> Dict[str, float]:
        """获取实时持仓（从 Polymarket API）"""
        try:
            from py_clob_client.headers.headers import create_level_2_headers
            from py_clob_client.clob_types import RequestArgs

            url = f"{CONFIG['clob_host']}/positions"
            request_args = RequestArgs(method="GET", request_path="/positions")
            headers = create_level_2_headers(self.client.signer, self.client.creds, request_args)
            # 🚀 使用Session复用TCP连接（提速持仓查询）
            resp = self.http_session.get(url, headers=headers, proxies=CONFIG['proxy'], timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                positions = {}
                for pos in data:
                    asset_id = pos.get('asset_id', '')
                    side = pos.get('side', '')  # 'BUY' or 'SELL'
                    size = pos.get('size', 0)
                    if isinstance(size, str):
                        size = float(size)
                    if asset_id:
                        positions[side] = positions.get(side, 0) + size
                return positions
        except Exception as e:
            print(f"       [POS CHECK ERROR] {e}")
        return {}

    def cancel_order(self, order_id: str) -> bool:
        """取消订单"""
        try:
            response = self.client.cancel(order_id)
            # 修复判断逻辑：检查 canceled 数组是否包含订单ID
            if response:
                canceled_list = response.get('canceled', [])
                if canceled_list and order_id in canceled_list:
                    print(f"       [CANCEL] ✅ 订单已取消: {order_id[-8:]}")
                    return True
                else:
                    # success 字段可能不准确，主要看 canceled 数组
                    print(f"       [CANCEL FAIL] {order_id[-8:]}: canceled={canceled_list}")
                    return False
            else:
                print(f"       [CANCEL FAIL] {order_id[-8:]}: 无响应")
                return False
        except Exception as e:
            print(f"       [CANCEL ERROR] {order_id[-8:]}: {e}")
            return False

    def cancel_pair_orders(self, take_profit_order_id: str, stop_loss_order_id: str, triggered_order: str):
        """止盈成交时取消止损（现在止损是本地轮询，无需取消）"""
        if triggered_order == 'TAKE_PROFIT':
            # 止盈成交，无需操作（止损是本地轮询，没有挂单）
            pass
        elif triggered_order == 'STOP_LOSS':
            # 止损已在check_positions里撤止盈单了，这里无需重复
            pass

    def update_allowance_fixed(self, asset_type, token_id=None):
        """修复版授权：正确传入 funder 地址（绕过 SDK bug）"""
        from py_clob_client.headers.headers import create_level_2_headers
        from py_clob_client.http_helpers.helpers import get
        from py_clob_client.clob_types import RequestArgs
        UPDATE_BALANCE_ALLOWANCE = "/balance-allowance/update"
        request_args = RequestArgs(method="GET", request_path=UPDATE_BALANCE_ALLOWANCE)
        headers = create_level_2_headers(self.client.signer, self.client.creds, request_args)
        url = "{}{}?asset_type={}&signature_type=2".format(
            self.client.host, UPDATE_BALANCE_ALLOWANCE, asset_type
        )
        if token_id:
            url += "&token_id={}".format(token_id)
        return get(url, headers=headers)

    def ensure_allowance(self, token_id: str, expected_size: float) -> bool:
        """确保已授权指定token（用于SELL操作），并等待token到账

        返回: True=已授权且有余额, False=授权失败或余额不足
        """
        import time
        max_wait = 15  # 最多等待15秒

        try:
            params = BalanceAllowanceParams(
                asset_type=AssetType.CONDITIONAL,  # 条件token（YES/NO）
                token_id=token_id,
                signature_type=2
            )

            # 等待token到账并检查授权
            for wait_i in range(max_wait):
                try:
                    result = self.client.get_balance_allowance(params)
                    if result:
                        balance = float(result.get('balance', 0))
                        allowance = float(result.get('allowance', 0))

                        print(f"       [ALLOWANCE] token={token_id[-8:]}, balance={balance:.2f}, allowance={allowance:.2f}")

                        if balance >= expected_size:
                            # 余额足够，检查授权
                            if allowance > 0:
                                print(f"       [ALLOWANCE] ✅ 余额和授权都足够")
                                return True
                            else:
                                # 尝试授权
                                print(f"       [ALLOWANCE] 授权中...")
                                self.update_allowance_fixed(AssetType.CONDITIONAL, token_id)
                                print(f"       [ALLOWANCE] ✅ 授权请求已发送，等待链上确认...")
                                # 等待授权在链上生效（增加等待时间）
                                import time
                                for auth_wait in range(10):
                                    time.sleep(1)
                                    try:
                                        result2 = self.client.get_balance_allowance(params)
                                        if result2:
                                            allowance2 = float(result2.get('allowance', 0))
                                            if allowance2 > 0:
                                                print(f"       [ALLOWANCE] ✅ 授权已生效: allowance={allowance2:.2f} (等待{auth_wait+1}秒)")
                                                break
                                        elif auth_wait < 9:
                                            print(f"       [ALLOWANCE] 等待授权生效... ({auth_wait+1}/10)")
                                    except:
                                        if auth_wait < 9:
                                            print(f"       [ALLOWANCE] 查询授权状态... ({auth_wait+1}/10)")
                                        time.sleep(1)
                                else:
                                    print(f"       [ALLOWANCE] ⚠️  授权可能仍未生效，继续尝试挂单")
                                return True
                        else:
                            if wait_i < max_wait - 1:
                                print(f"       [ALLOWANCE] 等待token到账... ({wait_i+1}/{max_wait})")
                                time.sleep(1)

                except Exception as e:
                    err_str = str(e)
                    # 401 说明 API key 权限不足，无法查询授权，直接跳过等待挂单
                    if '401' in err_str or 'Unauthorized' in err_str:
                        print(f"       [ALLOWANCE] API key 权限不足，尝试直接授权token={token_id[-8:]}...")
                        try:
                            self.update_allowance_fixed(AssetType.CONDITIONAL, token_id)
                            print(f"       [ALLOWANCE] ✅ 授权请求已发送，等待链上确认...")
                            # 等待授权在链上生效（增加等待时间）
                            import time
                            for auth_wait in range(10):
                                time.sleep(1)
                            return True
                        except Exception as e2:
                            print(f"       [ALLOWANCE] 直接授权失败: {e2}，等待12秒后继续尝试挂单")
                            time.sleep(12)
                            return True
                    if wait_i < max_wait - 1:
                        print(f"       [ALLOWANCE] 查询失败，重试中... ({wait_i+1}/{max_wait}): {e}")
                        time.sleep(1)

            print(f"       [ALLOWANCE] ❌ 等待超时，但仍尝试挂单")
            return True  # 返回True让程序继续尝试

        except Exception as e:
            print(f"       [ALLOWANCE ERROR] {e}")
            import traceback
            traceback.print_exc()
            return True  # 即使失败也继续尝试

    def place_stop_orders(self, market: Dict, side: str, size: float, entry_price: float, value_usdc: float, entry_order_id: str = None) -> tuple:
        """开仓后同时挂止盈止损单（带重试机制）

        参数:
            entry_order_id: 入场订单ID，如果提供则等待订单成交后再挂止盈止损单，并返回实际成交价格

        返回: (take_profit_order_id, stop_loss_order_id, actual_entry_price)
              actual_entry_price: 实际入场成交价格（如果entry_order_id提供且成交），否则返回entry_price
        """
        import time

        actual_entry_price = entry_price  # 默认使用传入的价格

        try:
            token_ids = market.get('clobTokenIds', [])
            if isinstance(token_ids, str):
                token_ids = json.loads(token_ids)

            if not token_ids or len(token_ids) < 2:
                return None, None, entry_price

            outcome_prices = market.get('outcomePrices', [])
            if isinstance(outcome_prices, str):
                outcome_prices = json.loads(outcome_prices)

            # 确定token_id（平仓时用的token）
            # LONG平仓卖YES，SHORT平仓卖NO
            token_id = str(token_ids[0] if side == 'LONG' else token_ids[1])

            # 计算止盈止损价格
            # 正确算法：PnL = size * (exit_price - entry_price)
            # 目标盈亏 = ±1.0 USD → price_delta = 1.0 / size
            # 1U 硬止盈：固定盈利1 USDC
            tp_target_price = (value_usdc + 1.0) / max(size, 1)

            # 🛡️ 收紧止损线（防止断崖暴跌）
            # 原止损：固定1U损失
            sl_original = (value_usdc - 1.0) / max(size, 1)

            # 百分比止损：两种Token都是现货，逻辑完全相同
            # YES和NO都是：价格涨赚钱，价格跌亏钱
            # 所以止损都是：价格下跌15%
            sl_pct_max = CONFIG['risk'].get('max_stop_loss_pct', 0.15)  # 15%最大止损
            sl_by_pct = entry_price * (1 - sl_pct_max)

            # 取两者中更保守的（价格更高的，即更早止损）
            sl_target_price = max(sl_original, sl_by_pct)

            # 计算实际止损百分比
            actual_sl_pct = (entry_price - sl_target_price) / entry_price
            print(f"       [STOP ORDERS] entry={entry_price:.4f}, size={size}, value={value_usdc:.4f}")
            print(f"       [STOP ORDERS] tp={tp_target_price:.4f} (固定+1U), sl={sl_target_price:.4f} (止损{actual_sl_pct:.1%})")

            # 确保价格在 Polymarket 有效范围内，精度对齐 tick_size
            # 从市场数据获取 tick_size（默认 0.01）
            tick_size = float(market.get('orderPriceMinTickSize') or 0.01)

            def align_price(p: float) -> float:
                """对齐到 tick_size 精度，并限制在 tick_size ~ 1-tick_size"""
                p = round(round(p / tick_size) * tick_size, 4)
                return max(tick_size, min(1 - tick_size, p))

            tp_target_price = align_price(tp_target_price)
            sl_target_price = align_price(sl_target_price)

            # 检查止盈止损价格是否有意义（至少要有1个tick的差距）
            if tp_target_price <= entry_price or sl_target_price >= entry_price:
                print(f"       [STOP ORDERS] tp/sl价格方向错误，跳过挂单 tp={tp_target_price:.4f} sl={sl_target_price:.4f} entry={entry_price:.4f}")
                return None, None, entry_price

            # 止盈止损 size 等于实际买入量（查链上精确余额，避免取整超卖）
            try:
                from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
                bal_params = BalanceAllowanceParams(
                    asset_type=AssetType.CONDITIONAL,
                    token_id=token_id,
                    signature_type=2
                )
                bal_result = self.client.get_balance_allowance(bal_params)
                if bal_result:
                    raw = float(bal_result.get('balance', '0') or '0')
                    actual_size_on_chain = raw / 1e6
                    if actual_size_on_chain >= 0.5:
                        stop_size = actual_size_on_chain
                        print(f"       [STOP ORDERS] 链上精确余额: {stop_size} (DB size={size})")
                    else:
                        stop_size = int(size)
                else:
                    stop_size = int(size)
            except Exception as e:
                print(f"       [STOP ORDERS] 余额查询失败({e})，使用DB size")
                stop_size = int(size)

            # 如果提供了入场订单ID，等待订单成交后再挂止盈止损单
            if entry_order_id:
                print(f"       [STOP ORDERS] 等待入场订单成交: {entry_order_id[-8:]}...")
                max_wait = 60  # 60秒极限（避免Alpha Decay，15分钟合约信号60秒内必须成交）
                check_interval = 1.0  # 每1秒检查一次（避免触发Rate Limit）

                for wait_i in range(int(max_wait / check_interval)):
                    try:
                        entry_order = self.client.get_order(entry_order_id)
                        if entry_order:
                            status = entry_order.get('status', '')
                            # MATCHED 或 FILLED 都表示订单已成交
                            if status in ['FILLED', 'MATCHED']:
                                print(f"       [STOP ORDERS] ✅ 入场订单已成交 ({status})")
                                print(f"       [STOP ORDERS] ⏳ 等待 10 秒，确保 Token 到达钱包...")
                                time.sleep(10)
                                # 尝试获取实际成交价格
                                filled_price = entry_order.get('price')
                                if filled_price:
                                    actual_entry_price = float(filled_price)
                                    print(f"       [STOP ORDERS] 实际成交价: {actual_entry_price:.4f} (调整价格: {entry_price:.4f})")
                                    # 如果实际价格和调整价格不同，重新计算止盈止损价格
                                    if abs(actual_entry_price - entry_price) > 0.001:
                                        value_usdc = size * actual_entry_price
                                        # 重新计算止盈止损价格（基于实际成交价）
                                        tp_target_price = (value_usdc + 1.0) / max(size, 1)
                                        # 🛡️ 使用收紧的止损逻辑（两种Token逻辑相同）
                                        sl_original = (value_usdc - 1.0) / max(size, 1)
                                        sl_pct_max = CONFIG['risk'].get('max_stop_loss_pct', 0.15)
                                        sl_by_pct = actual_entry_price * (1 - sl_pct_max)
                                        sl_target_price = max(sl_original, sl_by_pct)
                                        tp_target_price = align_price(tp_target_price)
                                        sl_target_price = align_price(sl_target_price)
                                        print(f"       [STOP ORDERS] 重新计算止盈止损: tp={tp_target_price:.4f}, sl={sl_target_price:.4f}")
                                        print(f"       [STOP ORDERS] 更新value: {value_usdc:.2f} USDC")
                                break
                            elif status in ['CANCELLED', 'EXPIRED']:
                                print(f"       [STOP ORDERS] ❌ 入场订单已{status}，取消挂止盈止损单")
                                return None, None, entry_price
                            elif status == 'LIVE':
                                # 订单还在挂单中，继续等待
                                if wait_i < max_wait - 1:
                                    # 每10秒打印一次
                                    if wait_i % 10 == 0:
                                        print(f"       [STOP ORDERS] 订单状态: {status}，挂单中... ({int(wait_i*check_interval)+1}/{max_wait})")
                                    time.sleep(check_interval)
                            else:
                                if wait_i < max_wait - 1:
                                    if wait_i % 10 == 0:
                                        print(f"       [STOP ORDERS] 订单状态: {status}，等待中... ({int(wait_i*check_interval)+1}/{max_wait})")
                                    time.sleep(check_interval)
                    except Exception as e:
                        if wait_i < max_wait - 1:
                            time.sleep(check_interval)
                else:
                    # 超时后，再尝试最后检查一次（API可能有延迟）
                    print(f"       [STOP ORDERS] ⚠️  等待超时，进行最后检查...")
                    try:
                        entry_order = self.client.get_order(entry_order_id)
                        if entry_order and entry_order.get('status') in ['FILLED', 'MATCHED']:
                            print(f"       [STOP ORDERS] ✅ 最后检查发现订单已成交！")
                            status = entry_order.get('status')
                            filled_price = entry_order.get('price')
                            if filled_price:
                                actual_entry_price = float(filled_price)
                                print(f"       [STOP ORDERS] 实际成交价: {actual_entry_price:.4f} (调整价格: {entry_price:.4f})")
                                if abs(actual_entry_price - entry_price) > 0.001:
                                    value_usdc = size * actual_entry_price
                                    tp_target_price = (value_usdc + 1.0) / max(size, 1)
                                    # 🛡️ 使用收紧的止损逻辑（两种Token逻辑相同）
                                    sl_original = (value_usdc - 1.0) / max(size, 1)
                                    sl_pct_max = CONFIG['risk'].get('max_stop_loss_pct', 0.15)
                                    sl_by_pct = actual_entry_price * (1 - sl_pct_max)
                                    sl_target_price = max(sl_original, sl_by_pct)
                                    tp_target_price = align_price(tp_target_price)
                                    sl_target_price = align_price(sl_target_price)
                                    print(f"       [STOP ORDERS] 重新计算止盈止损: tp={tp_target_price:.4f}, sl={sl_target_price:.4f}")
                                    print(f"       [STOP ORDERS] 更新value: {value_usdc:.2f} USDC")
                        elif entry_order and entry_order.get('status') == 'LIVE':
                            # 订单还是LIVE状态，可能真的没成交，尝试撤单
                            print(f"       [STOP ORDERS] 订单状态仍为LIVE，尝试撤单")
                            cancel_success = False
                            try:
                                cancel_result = self.cancel_order(entry_order_id)
                                if cancel_result:
                                    print(f"       [STOP ORDERS] ✅ 撤单成功，安全放弃该笔交易")
                                    cancel_success = True
                                else:
                                    print(f"       [STOP ORDERS] ⚠️  撤单请求返回失败，订单可能仍在")
                            except Exception as cancel_err:
                                print(f"       [STOP ORDERS] ❌ 撤单异常: {cancel_err}")

                            # 【核心防御】撤单失败 = 订单可能还在 = 强制监控！
                            if not cancel_success:
                                print(f"       [STOP ORDERS] 🚨 无法确认订单状态，强制移交本地双向监控！")
                                # 使用原定入场价格计算止盈止损
                                if entry_price and size:
                                    value_usdc = size * entry_price
                                    # 需要重新定义align_price函数（因为它在函数外部定义）
                                    tick_size = 0.01  # 默认tick size
                                    try:
                                        tick_size = float(market.get('orderPriceMinTickSize') or 0.01)
                                    except:
                                        pass
                                    def align_price_local(p: float) -> float:
                                        p = round(round(p / tick_size) * tick_size, 4)
                                        return max(tick_size, min(1 - tick_size, p))

                                    tp_target_price = align_price_local((value_usdc + 1.0) / max(size, 1))
                                    # 🛡️ 使用收紧的止损逻辑（两种Token逻辑相同）
                                    sl_pct_max = CONFIG['risk'].get('max_stop_loss_pct', 0.15)
                                    sl_by_pct = entry_price * (1 - sl_pct_max)
                                    sl_original = (value_usdc - 1.0) / max(size, 1)
                                    sl_target_price = align_price_local(max(sl_original, sl_by_pct))
                                    actual_entry_price = entry_price
                                    print(f"       [STOP ORDERS] 🛡️  强制监控: entry={entry_price:.4f}, tp={tp_target_price:.4f}, sl={sl_target_price:.4f}")
                                    # 返回None作为tp_order_id（止盈单需后续挂），但返回其他参数强制监控
                                    return None, sl_target_price, actual_entry_price
                                else:
                                    print(f"       [STOP ORDERS] ❌ 无法获取价格信息，但为安全起见仍强制监控")
                                    # 即使没有价格信息，也返回原值强制监控
                                    return None, None, entry_price
                            else:
                                # 撤单成功，真的没成交，安全放弃
                                return None, None, None
                        else:
                            print(f"       [STOP ORDERS] ❌ 订单状态: {entry_order.get('status', 'UNKNOWN')}，放弃")
                            return None, None, None
                    except Exception as e:
                        print(f"       [STOP ORDERS] ❌ 最后检查失败: {e}")
                        return None, None, None

            # 确认token授权
            # 检查token授权
            print(f"       [STOP ORDERS] 检查token授权...")
            self.ensure_allowance(token_id, expected_size=stop_size)

            # ==========================================
            # 🚀 强制止盈挂单（带动态退避与重试机制）
            # ==========================================
            print(f"       [STOP ORDERS] ⏳ 开始挂止盈单前的强制冷却 (等待 5 秒让Polygon同步余额)...")
            time.sleep(5)  # 【核心防御】：首次挂单前必须硬等待！防止 Polymarket 后端缓存你的0余额状态

            # 组装止盈单参数 (注意：无论是做多还是做空，平仓永远是 SELL 你手里的 Token)
            from py_clob_client.clob_types import OrderArgs

            tp_order_args = OrderArgs(
                token_id=token_id,
                price=tp_target_price,  # 这里的 tp_target_price 必须是你之前修改过的绝对价格
                size=stop_size,
                side=SELL
            )

            max_retries = 6  # 增加重试次数，确保万无一失
            tp_order_id = None

            for attempt in range(1, max_retries + 1):
                print(f"       [STOP ORDERS] 🎯 尝试挂载限价止盈单 ({attempt}/{max_retries})... 目标价: {tp_target_price:.4f}")
                try:
                    # 向盘口发送限价挂单
                    tp_response = self.client.create_and_post_order(tp_order_args)

                    if tp_response and 'orderID' in tp_response:
                        tp_order_id = tp_response['orderID']
                        print(f"       [STOP ORDERS] ✅ 止盈挂单成功！订单已经躺在盘口等待暴涨。ID: {tp_order_id[-8:]}")
                        break  # 挂单成功，立刻跳出循环
                    else:
                        print(f"       [STOP ORDERS] ⚠️  挂单未报错但未返回订单ID: {tp_response}")
                        time.sleep(2)

                except Exception as e:
                    error_msg = str(e).lower()
                    if 'balance' in error_msg or 'allowance' in error_msg:
                        wait_time = attempt * 3
                        print(f"       [STOP ORDERS] 🔄 链上余额未同步，等待 {wait_time} 秒后重试...")
                        time.sleep(wait_time)
                        # 重新查链上余额，更新 stop_size 和 tp_order_args
                        try:
                            bal_result2 = self.client.get_balance_allowance(bal_params)
                            if bal_result2:
                                raw2 = float(bal_result2.get('balance', '0') or '0')
                                new_size = raw2 / 1e6
                                if new_size >= 0.5:
                                    stop_size = new_size
                                    tp_order_args = OrderArgs(
                                        token_id=token_id,
                                        price=tp_target_price,
                                        size=stop_size,
                                        side=SELL
                                    )
                                    print(f"       [STOP ORDERS] 🔄 更新余额: {stop_size}")
                        except Exception:
                            pass
                    else:
                        print(f"       [STOP ORDERS] ❌ 挂单发生未知异常: {e}")
                        time.sleep(3)

            # 兜底机制：如果 6 次（总计等了约 1 分钟）还是没挂上去
            if not tp_order_id:
                print(f"       [STOP ORDERS] 🚨 止盈单挂载彻底失败！已无缝移交【本地双向监控】系统兜底。")

            # 止损不挂单，由本地轮询监控（策略一：只挂止盈Maker，止损用Taker）
            # sl_target_price 保存到数据库供轮询使用
            sl_order_id = None

            if tp_order_id:
                print(f"       [STOP ORDERS] ✅ 止盈单已挂 @ {tp_target_price:.4f}，止损线 @ {sl_target_price:.4f} 由本地监控")
            else:
                print(f"       [STOP ORDERS] ❌ 止盈单挂单失败，将使用本地监控双向平仓")

            return tp_order_id, sl_target_price, actual_entry_price

        except Exception as e:
            print(f"       [STOP ORDERS ERROR] {e}")
            import traceback
            print(f"       [TRACEBACK] {traceback.format_exc()}")
            return None, None, entry_price

    def close_position(self, market: Dict, side: str, size: float, is_stop_loss: bool = False):
        """平仓函数

        Args:
            market: 市场数据
            side: LONG/SHORT
            size: 平仓数量
            is_stop_loss: 是否是止损调用（止损时直接市价，不防插针）
        """
        try:
            token_ids = market.get('clobTokenIds', [])
            if isinstance(token_ids, str):
                token_ids = json.loads(token_ids)

            if not token_ids:
                return False

            # 获取 token_id 和平仓方向
            # Polymarket机制：平仓永远是SELL（平多卖YES，平空卖NO）
            # clobTokenIds[0]=YES, clobTokenIds[1]=NO（固定顺序）
            token_id = str(token_ids[0] if side == 'LONG' else token_ids[1])
            opposite_side = SELL  # 平仓永远是SELL

            # 获取outcomePrices用于计算平仓价格
            outcome_prices = market.get('outcomePrices', [])
            if isinstance(outcome_prices, str):
                outcome_prices = json.loads(outcome_prices)

            # ========== 🛡️ 智能防插针止损保护 ==========
            # 获取公允价格（token_price）和实际买一价（best_bid）
            if side == 'LONG':
                # 平多仓 -> 卖出YES，查YES的买一价
                token_price = float(outcome_prices[0]) if outcome_prices and len(outcome_prices) > 0 else 0.5
                best_bid = self.get_order_book(token_id, side='BUY')
            else:
                # 平空仓 -> 卖出NO，查NO的买一价
                token_price = float(outcome_prices[1]) if outcome_prices and len(outcome_prices) > 1 else 0.5
                best_bid = self.get_order_book(token_id, side='BUY')

            # 🛡️ 防插针核心逻辑：最多允许折价5%，拒绝恶意接针
            min_acceptable_price = token_price * 0.95  # 公允价的95%作为底线

            # 🔥 止损场景：直接市价砸单，不要防插针保护
            if is_stop_loss:
                # ⚡ 止损模式：直接市价成交，放弃防插针
                # best_bid是买家愿意出的价格，直接用它挂卖单确保成交
                if best_bid and best_bid > 0.01:
                    close_price = best_bid
                else:
                    close_price = token_price  # fallback到公允价
                use_limit_order = False  # 强制市价单
                print(f"       [止损模式] ⚡ 直接市价砸单 @ {close_price:.4f} (止损优先，不防插针)")

                # ========== 核心修复：止损前撤销所有挂单释放冻结余额 ==========
                print(f"       [LOCAL SL] 🧹 正在紧急撤销该Token的所有挂单，释放被冻结的余额...")
                try:
                    self.client.cancel_all()
                    time.sleep(0.5)  # 等待服务器把余额退回账户
                    # 重新查询真实可用余额
                    from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
                    _params = BalanceAllowanceParams(
                        asset_type=AssetType.CONDITIONAL,
                        token_id=token_id,
                        signature_type=2
                    )
                    _result = self.client.get_balance_allowance(_params)
                    actual_balance = float(_result.get('balance', '0') or '0') / 1e6 if _result else 0
                    print(f"       [LOCAL SL] 🔓 余额释放成功，当前真实可用余额: {actual_balance:.2f} 份")
                    if actual_balance <= 0:
                        print(f"       [LOCAL SL] ⚠️ 撤单后余额依然为0，确认已无持仓。")
                        return None
                    close_size = actual_balance  # 用真实余额，不四舍五入
                except Exception as _e:
                    print(f"       [LOCAL SL 撤单失败] {_e}，退回原逻辑")
                    close_size = size
                # ================================================================
            elif best_bid and best_bid >= min_acceptable_price:
                # 正常止盈：买一价合理，直接市价平仓
                close_price = best_bid
                use_limit_order = False
            else:
                # ⚠️ 买一价太黑（流动性断层）！限价单等待
                close_price = min_acceptable_price
                use_limit_order = True
                print(f"       [防插针] ⚠️ 买一价({best_bid if best_bid else 0:.4f})远低于公允价({token_price:.4f})，改挂限价单 @ {close_price:.4f}")

            close_price = max(0.01, min(0.99, close_price))
            # ===========================================

            # 计算平仓数量（平全部）- 使用精确余额，不取整避免超卖
            # 先查链上实际可用余额，以实际余额为准
            try:
                from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
                params = BalanceAllowanceParams(
                    asset_type=AssetType.CONDITIONAL,
                    token_id=token_id,
                    signature_type=2
                )
                result = self.client.get_balance_allowance(params)
                if result:
                    amount = float(result.get('balance', '0') or '0')
                    actual_size = amount / 1e6
                    if actual_size >= 0.5:
                        close_size = actual_size
                        print(f"       [CLOSE] 链上精确余额: {close_size} (DB size={size})")
                    else:
                        close_size = int(size)
                else:
                    close_size = int(size)
            except Exception as e:
                print(f"       [CLOSE] 余额查询失败({e})，使用DB size")
                close_size = int(size)

            order_type = "限价单(挂单等待)" if use_limit_order else "市价单(立即成交)"
            print(f"       [CLOSE] {order_type} 平仓 {side} {close_size}份 @ {close_price:.4f}")

            order_args = OrderArgs(
                token_id=token_id,
                price=round(close_price, 3),
                size=close_size,
                side=opposite_side
            )

            # 下单（两种情况都用create_and_post_order，价格决定了成交方式）
            response = self.client.create_and_post_order(order_args)
            if response and 'orderID' in response:
                order_id = response['orderID']
                if use_limit_order:
                    print(f"       [CLOSE OK] 限价单已挂 {order_id[-8:]}，等待成交...")
                else:
                    print(f"       [CLOSE OK] 市价成交 {order_id[-8:]}")
                return order_id
            else:
                print(f"       [CLOSE FAIL] {response}")
                return None
        except Exception as e:
            error_msg = str(e).lower()
            # 💡 精准识别"余额不足"，并返回特殊标记
            if 'balance' in error_msg or 'allowance' in error_msg or 'insufficient' in error_msg:
                print(f"       [CLOSE OK] 限价单已提前成交或已手动平仓，跳过市价平仓")
                return "NO_BALANCE"  # 以前这里是返回 None，现在返回专属暗号
            print(f"       [CLOSE ERROR] {e}")
            return None

    def get_order_book(self, token_id: str, side: str = 'BUY') -> Optional[float]:
        """获取真实成交价（使用 /price API）

        Args:
            token_id: 代币ID
            side: 'BUY' 获取买一价（做空用），'SELL' 获取卖一价（做多用）

        Returns:
            float: 价格（转换失败返回None）
        """
        try:
            url = "https://clob.polymarket.com/price"
            # 🚀 使用Session复用TCP连接（提速3-5倍）
            resp = self.http_session.get(url, params={"token_id": token_id, "side": side}, proxies=CONFIG['proxy'], timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                price = data.get('price')
                if price is not None:
                    return float(price)
        except Exception as e:
            print(f"       [PRICE ERROR] {e}")
        return None

    def get_orderbook_bias(self, market: Dict) -> float:
        """
        获取订单簿偏向分数（-1.0 偏空 ~ +1.0 偏多）
        优先使用 Gamma market 的 bestBid/bestAsk，失败时调用 /book
        临近结算时（spread > 0.5）返回 0 避免失真信号
        """
        try:
            # 临近结算时订单簿失真，直接跳过
            spread = float(market.get('spread') or 0)
            if spread > 0.5:
                return 0.0

            # 优先用 Gamma market 直接提供的字段（无需额外请求）
            best_bid = market.get('bestBid')
            best_ask = market.get('bestAsk')
            if best_bid and best_ask:
                bid = float(best_bid)
                ask = float(best_ask)
                mid = (bid + ask) / 2
                # bid > mid 偏多，bid < mid 偏空，映射到 -1~+1
                bias = (bid - mid) / mid if mid > 0 else 0.0
                return round(max(-1.0, min(1.0, bias * 20)), 3)

            # 备用：调用 /book
            token_ids = market.get('clobTokenIds', [])
            if isinstance(token_ids, str):
                token_ids = json.loads(token_ids)
            if not token_ids:
                return 0.0

            token_id_yes = str(token_ids[0])
            url = "https://clob.polymarket.com/book"
            # 🚀 使用Session复用TCP连接（提速订单簿查询）
            resp = self.http_session.get(url, params={"token_id": token_id_yes},
                                proxies=CONFIG['proxy'], timeout=5)
            if resp.status_code != 200:
                return 0.0

            book = resp.json()

            # 临近结算时订单簿失真检测（bids全在0.01或asks全在0.99）
            bids = book.get('bids', [])
            asks = book.get('asks', [])
            if not bids or not asks:
                return 0.0
            if float(bids[0].get('price', 0)) < 0.05 or float(asks[0].get('price', 1)) > 0.95:
                return 0.0

            bid_depth = sum(float(b['size']) for b in bids[:3])
            ask_depth = sum(float(a['size']) for a in asks[:3])
            total = bid_depth + ask_depth
            if total == 0:
                return 0.0

            bias = (bid_depth - ask_depth) / total
            return round(bias, 3)
        except:
            return 0.0

    def place_order(self, market: Dict, signal: Dict) -> Optional[Dict]:
        if not self.client:
            print("       [SIGNAL MODE]")
            return None

        try:
            token_ids = market.get('clobTokenIds', [])
            
            # 修复点：确保 token_ids 被正确解析为列表
            if isinstance(token_ids, str):
                try:
                    token_ids = json.loads(token_ids)
                except Exception as e:
                    print(f"       [ERROR] 解析 token_ids 失败: {e}")
                    return None

            if not token_ids or len(token_ids) < 2:
                print("       [ERROR] 市场数据缺少完整的 token_ids")
                return None

            # Polymarket: token_ids[0]=YES, token_ids[1]=NO
            # LONG买YES, SHORT买NO
            token_id = str(token_ids[0] if signal['direction'] == 'LONG' else token_ids[1])

            # --- 查询真实成交价（V6优先用WebSocket，V5回退REST）---
            best_price = self.get_order_book(token_id, side='BUY')
            if best_price is not None:
                print(f"       [PRICE] WebSocket实时价: {best_price:.4f}")
                # 🔥 优先使用WebSocket实时价格（V6模式下是毫秒级数据）
                base_price = best_price
            else:
                # 回退：从market的outcomePrices获取（可能是15分钟前的旧数据）
                outcome_prices = market.get('outcomePrices', [])
                if isinstance(outcome_prices, str):
                    outcome_prices = json.loads(outcome_prices)
                if signal['direction'] == 'LONG':
                    base_price = float(outcome_prices[0]) if outcome_prices and len(outcome_prices) > 0 else float(signal['price'])
                else:
                    base_price = float(outcome_prices[1]) if outcome_prices and len(outcome_prices) > 1 else round(1.0 - float(signal['price']), 4)
                print(f"       [PRICE] 回退旧数据: {base_price:.4f}")

            print(f"       [PRICE] 使用={'YES' if signal['direction']=='LONG' else 'NO'}={base_price:.4f}")

            # tick_size 对齐
            tick_size_float = float(market.get('orderPriceMinTickSize') or 0.01)
            # tick_size 必须是字符串格式给 SDK（"0.1"/"0.01"/"0.001"/"0.0001"）
            tick_size_str = str(tick_size_float)

            def align_price(p: float) -> float:
                p = round(round(p / tick_size_float) * tick_size_float, 4)
                return max(tick_size_float, min(1 - tick_size_float, p))

            # --- 加滑点确保瞬间吃单成交，对齐 tick_size ---
            slippage_ticks = 2  # 加2个tick滑点
            adjusted_price = align_price(base_price + tick_size_float * slippage_ticks)

            # Calculate based on REAL balance
            position_value = self.position_mgr.calculate_position(signal['confidence'])

            if not self.position_mgr.can_afford(position_value):
                print(f"       [RISK] Cannot afford {position_value:.2f}")
                return None

            # 使用加上滑点后的价格计算购买份数
            size = int(position_value / adjusted_price)
            
            # --- 核心修复：满足 Polymarket 最小 Size 为 5 的硬性要求 ---
            # 开仓买6份，确保到账后余额足够挂5份止损单
            if size < 6:
                size = 6
                position_value = size * adjusted_price  # 重新计算需要花费的金额
                
                # 再次检查加上金额后，钱包里的钱还够不够
                if not self.position_mgr.can_afford(position_value):
                    print(f"       [RISK] 余额不足以购买最低 6 份 (需要 {position_value:.2f} USDC)")
                    return None
            # --------------------------------------------------------

            print(f"       [ORDER] {signal['direction']}")
            print(f"       [ORDER] Value: {position_value:.2f} USDC")
            print(f"       [ORDER] Token Price: {base_price:.4f} (Adjusted: {adjusted_price:.4f})")
            print(f"       [ORDER] Size: {size}")

            # 组装订单
            # Polymarket机制：做多=买YES，做空=买NO（开仓永远是BUY）
            order_args = OrderArgs(
                token_id=token_id,
                price=adjusted_price,
                size=float(size),
                side=BUY  # 开仓永远是BUY：LONG买YES，SHORT买NO
            )

            # 核心修复点：删除了不兼容的 options 参数，让 SDK 自动处理
            response = self.client.create_and_post_order(order_args)

            if response and 'orderID' in response:
                print(f"       [OK] {response['orderID']}")
                # 返回实际下单价格（adjusted_price）和实际size，用于准确计算盈亏和挂单
                return {'order_id': response['orderID'], 'status': 'posted', 'value': position_value, 'price': adjusted_price, 'token_price': base_price, 'size': float(size)}

            return None

        except Exception as e:
            import traceback
            print(f"       [ERROR] {e}")
            print(f"       [TRACEBACK] {traceback.format_exc()}")
            return None

    def record_trade(self, market: Dict, signal: Dict, order_result: Optional[Dict], was_blocked: bool = False):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            value = order_result.get('value', 0) if order_result else 0

            cursor.execute("""
                INSERT INTO trades (
                    timestamp, side, price, value_usd, signal_score,
                    confidence, rsi, vwap, order_id, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                signal['direction'],
                signal['price'],
                value,
                signal['score'],
                signal['confidence'],
                signal['rsi'],
                signal['vwap'],
                order_result.get('order_id', '') if order_result else '',
                order_result.get('status', 'failed') if order_result else 'failed',
            ))

            # 记录最后交易的市场，确保每个市场只交易一次
            if order_result and order_result.get('status') == 'posted':
                market_slug = market.get('slug', '')
                if market_slug:
                    self.last_traded_market = market_slug
                    print(f"       [MARKET] Traded: {market_slug}")

                # 记录持仓到positions表（使用实际下单价格，同时挂止盈止损单）
                actual_price = order_result.get('price', signal['price'])
                token_price = order_result.get('token_price', actual_price)  # 真实token价格

                # 固定1U止盈止损
                tp_usd = 1.0
                sl_usd = 1.0

                # 使用实际成交的size（从order_result中获取，而不是重新计算）
                position_size = int(order_result.get('size', max(1, int(value / actual_price))))

                # 挂止盈止损单（用实际成交价计算，entry_price=actual_price，value=size*actual_price）
                # 传入入场订单ID，等待订单成交后再挂止盈止损单
                entry_order_id = order_result.get('order_id', '')
                tp_order_id, sl_target_price, actual_entry_price = self.place_stop_orders(
                    market, signal['direction'], position_size, actual_price, position_size * actual_price, entry_order_id
                )

                # 【关键修复】入场单超时未成交，撤单后放弃记录
                # 判断逻辑：tp_order_id=None 且 tp_order_id不是字符串"UNCERTAIN"
                if tp_order_id is None and actual_entry_price is not None and actual_entry_price > 0:
                    # 这种情况说明：订单超时未成交，强制监控模式，但实际没有token
                    # 需要验证是否真正有持仓
                    print(f"       [POSITION] ⚠️  订单状态不明，验证持仓...")
                    # 通过查询余额来确认（token_id需要从market获取）
                    token_ids = market.get('clobTokenIds', [])
                    if isinstance(token_ids, str):
                        token_ids = json.loads(token_ids)
                    token_id = str(token_ids[0] if signal['direction'] == 'LONG' else token_ids[1])

                    try:
                        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
                        params = BalanceAllowanceParams(
                            asset_type=AssetType.CONDITIONAL,
                            token_id=token_id,
                            signature_type=2
                        )
                        result = self.client.get_balance_allowance(params)
                        if result:
                            balance = float(result.get('balance', 0))
                            print(f"       [POSITION] Token余额: {balance:.2f} (需要: {position_size:.0f})")
                            if balance < position_size * 0.5:  # 余额不足一半，说明未成交
                                print(f"       [POSITION] ❌ 确认未成交，放弃记录持仓")
                                conn.commit()
                                conn.close()
                                return
                    except Exception as verify_err:
                        print(f"       [POSITION] ⚠️  无法验证余额，假设未成交: {verify_err}")
                        conn.commit()
                        conn.close()
                        return
                elif tp_order_id is None and sl_target_price is None and actual_entry_price is None:
                    print(f"       [POSITION] ❌ 入场单未成交，放弃记录持仓")
                    conn.commit()
                    conn.close()
                    return

                # 初始化position_value
                position_value = position_size * actual_price

                # 使用实际成交价格（如果获取到了的话）
                if actual_entry_price and actual_entry_price != actual_price:
                    print(f"       [POSITION] 使用实际成交价格: {actual_entry_price:.4f} (调整价格: {actual_price:.4f})")
                    actual_price = actual_entry_price
                    # 重新计算value
                    position_value = position_size * actual_price

                # 计算止盈止损百分比（用于数据库记录和学习系统分析）
                # 止盈：目标价格 / 入场价格 - 1
                # 止损：入场价格 - 止损价格 / 入场价格
                tick_size = float(market.get('orderPriceMinTickSize') or 0.01)
                def align_price(p: float) -> float:
                    p = round(round(p / tick_size) * tick_size, 4)
                    return max(tick_size, min(1 - tick_size, p))

                real_value = position_size * actual_price
                tp_target_price = align_price((real_value + 1.0) / max(position_size, 1))
                sl_target_price = align_price((real_value - 1.0) / max(position_size, 1))

                tp_pct = round((tp_target_price - actual_price) / actual_price, 4) if actual_price > 0 else None
                sl_pct = round((actual_price - sl_target_price) / actual_price, 4) if actual_price > 0 else None

                # 发送开仓Telegram通知
                if self.telegram.enabled:
                    try:
                        # 使用place_stop_orders内部计算的实际止盈止损价格（基于实际成交价）
                        tick_size = float(market.get('orderPriceMinTickSize') or 0.01)
                        def align_price(p: float) -> float:
                            p = round(round(p / tick_size) * tick_size, 4)
                            return max(tick_size, min(1 - tick_size, p))

                        # 基于实际成交价格计算止盈止损（与place_stop_orders内部逻辑一致）
                        tp_price = align_price((position_value + 1.0) / max(position_size, 1))
                        sl_price = sl_target_price if sl_target_price else align_price((position_value - 1.0) / max(position_size, 1))

                        # 获取token_id
                        token_ids = market.get('clobTokenIds', [])
                        if isinstance(token_ids, str):
                            token_ids = json.loads(token_ids)
                        token_id = str(token_ids[0] if signal['direction'] == 'LONG' else token_ids[1])

                        market_id = market.get('slug', market.get('questionId', 'unknown'))
                        self.telegram.send_position_open(
                            signal['direction'], position_size, actual_price, position_value,
                            tp_price, sl_price, token_id, market_id
                        )
                        print(f"       [TELEGRAM] ✅ 开仓通知已发送")
                    except Exception as tg_error:
                        print(f"       [TELEGRAM ERROR] 发送开仓通知失败: {tg_error}")

                cursor.execute("""
                    INSERT INTO positions (
                        entry_time, side, entry_token_price,
                        size, value_usdc, take_profit_usd, stop_loss_usd,
                        take_profit_pct, stop_loss_pct,
                        take_profit_order_id, stop_loss_order_id, token_id, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    signal['direction'],
                    actual_price,  # 使用实际成交价格（已从订单中获取）
                    position_size,
                    position_value,  # 使用重新计算的value
                    tp_usd,
                    sl_usd,
                    tp_pct,
                    sl_pct,
                    tp_order_id,
                    # ⚠️ 此字段存的是止损价格字符串，不是订单ID！用于本地轮询止损
                    # 🔍 修复：sl_target_price为None时用入场价兜底计算，确保止损线永远存在
                    str(sl_target_price) if sl_target_price else str(round(max(0.01, actual_price * (1 - CONFIG['risk'].get('max_stop_loss_pct', 0.15))), 4)),
                    token_id,
                    'open'
                ))
                print(f"       [POSITION] 记录持仓: {signal['direction']} {position_value:.2f} USDC @ {actual_price:.4f}")

                # 根据止盈止损单状态显示不同信息
                if tp_order_id:
                    print(f"       [POSITION] ✅ 止盈单已挂 @ {tp_target_price:.4f}，止损线 @ {sl_target_price:.4f} 本地监控")
                else:
                    print(f"       [POSITION] ⚠️  止盈单挂单失败，将使用本地监控双向平仓")

            conn.commit()
            conn.close()

            self.record_prediction_learning(market, signal, order_result, was_blocked=was_blocked)

        except Exception as e:
            print(f"       [DB ERROR] {e}")

    def check_positions(self, current_token_price: float = None):
        """检查持仓状态，通过检查止盈止损单是否成交来判断
        
        注意：current_token_price 参数仅作备用，内部会对每个持仓单独查询准确价格。
        V6模式下由 get_order_book 覆盖返回 WebSocket 实时价格。
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 获取所有open状态的持仓（包括订单ID）
            cursor.execute("""
                SELECT id, entry_time, side, entry_token_price,
                       size, value_usdc, take_profit_order_id, stop_loss_order_id, token_id
                FROM positions
                WHERE status = 'open'
            """)
            positions = cursor.fetchall()

            if not positions:
                conn.close()
                return

            for pos in positions:
                pos_id, entry_time, side, entry_token_price, size, value_usdc, tp_order_id, sl_order_id, token_id = pos

                # 优先使用传入的实时价格（WebSocket），避免REST查询延迟
                pos_current_price = current_token_price if current_token_price else None
                if pos_current_price is None and token_id:
                    pos_current_price = self.get_order_book(token_id, side='BUY')
                if pos_current_price is None:
                    # fallback：从市场数据获取
                    try:
                        market = self.get_market_data()
                        if market:
                            outcome_prices = market.get('outcomePrices', [])
                            if isinstance(outcome_prices, str):
                                outcome_prices = json.loads(outcome_prices)
                            if side == 'LONG':
                                pos_current_price = float(outcome_prices[0]) if outcome_prices else 0.5
                            else:
                                pos_current_price = float(outcome_prices[1]) if len(outcome_prices) > 1 else 0.5
                    except:
                        pass
                if pos_current_price is None:
                    print(f"       [POSITION] 无法获取持仓 {pos_id} 的当前价格，跳过")
                    continue

                print(f"       [POSITION] {side} token价格: {pos_current_price:.4f}")

                # 调试：打印止损检查的详细信息
                if sl_order_id:
                    try:
                        sl_price = float(sl_order_id)
                        print(f"       [DEBUG] 止损检查: 当前价={pos_current_price:.4f}, 止损线={sl_price:.4f}, 触发={pos_current_price <= sl_price}")
                    except:
                        pass

                # 检查止盈和止损订单状态
                exit_reason = None
                triggered_order_id = None
                actual_exit_price = None  # 实际成交价格

                # 检查止盈单（带重试）
                if tp_order_id:
                    for _attempt in range(3):
                        try:
                            tp_order = self.client.get_order(tp_order_id)
                            if tp_order:
                                # Polymarket 成交状态可能是 FILLED 或 MATCHED
                                if tp_order.get('status') in ('FILLED', 'MATCHED'):
                                    exit_reason = 'TAKE_PROFIT'
                                    triggered_order_id = tp_order_id
                                    actual_exit_price = tp_order.get('price')
                                    if actual_exit_price is None:
                                        actual_exit_price = tp_order.get('matchAmount') / tp_order.get('matchedSize') if tp_order.get('matchedSize') else None
                            break
                        except Exception as e:
                            print(f"       [ORDER CHECK ERROR] TP order {tp_order_id}: {e}")
                            if _attempt < 2:
                                time.sleep(2 ** _attempt)

                # 余额检查：防止手动平仓后机器人继续尝试操作
                try:
                    from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
                    params = BalanceAllowanceParams(
                        asset_type=AssetType.CONDITIONAL,
                        token_id=token_id,
                        signature_type=2
                    )
                    result = self.client.get_balance_allowance(params)
                    if result:
                        amount = result.get('balance', '0')
                        if amount is not None:
                            try:
                                amount_float = float(amount)
                            except:
                                amount_float = 0

                            # 只有 balance 明确为0才认为已平仓（allowance为0不代表平仓）
                            # balance 单位是最小精度，需要除以1e6才是实际份数
                            actual_size = amount_float / 1e6
                            if actual_size < 0.5:  # 少于0.5份才认为已平仓
                                # 🔍 关键修复：余额为0需区分两种情况
                                # 场景A：止盈单成交 → 正收益
                                # 场景B：市场到期归零（止盈单锁住token未成交）→ 全亏
                                # 场景C：手动平仓 → 用当前价
                                # 先检查止盈单是否真的成交了
                                if tp_order_id and not exit_reason:
                                    try:
                                        tp_order_info = self.client.get_order(tp_order_id)
                                        if tp_order_info:
                                            tp_status = tp_order_info.get('status', '').upper()
                                            matched_size = float(tp_order_info.get('matchedSize', 0) or 0)
                                            if tp_status in ('MATCHED', 'FILLED') or matched_size > 0:
                                                # 止盈单真实成交
                                                exit_reason = 'TAKE_PROFIT'
                                                p = tp_order_info.get('price')
                                                actual_exit_price = float(p) if p else pos_current_price
                                                print(f"       [POSITION] ✅ 确认止盈单已成交 status={tp_status} @ {actual_exit_price:.4f}")
                                            else:
                                                # 止盈单未成交，余额为0 = 市场到期归零
                                                exit_reason = 'MARKET_SETTLED'
                                                actual_exit_price = 0.0
                                                print(f"       [POSITION] 💀 止盈单未成交(status={tp_status})，市场到期归零，记录真实亏损")
                                    except Exception as e:
                                        print(f"       [POSITION] 查询止盈单失败: {e}，保守处理为归零")
                                        exit_reason = 'MARKET_SETTLED'
                                        actual_exit_price = 0.0
                                elif not exit_reason:
                                    # 没有止盈单，余额为0 = 手动平仓
                                    print(f"       [POSITION] ⚠️  Token余额为{actual_size:.2f}份，检测到已手动平仓，停止监控")
                                    exit_reason = 'MANUAL_CLOSED'
                                    actual_exit_price = pos_current_price
                            else:
                                print(f"       [POSITION] [DEBUG] 余额查询成功，balance={actual_size:.2f}份")
                except Exception as e:
                    print(f"       [POSITION] [DEBUG] 余额查询失败: {e}")
                    pass

                # 如果止盈单没成交，检查本地止盈止损价格（双向轮询模式）
                if not exit_reason:
                    # ✅ 关键修复：使用与开仓时相同的公式，确保一致性
                    # 开仓时：tp = (value_usdc + 1.0) / size
                    # 这里也要用相同的公式，而不是 entry_price + 1/size
                    tp_target_price = (value_usdc + 1.0) / max(size, 1)

                    # 确保止盈价格在合理范围内 (Polymarket 最高价格为 1.0)
                    tp_target_price = max(0.01, min(0.99, tp_target_price))

                    # 获取止损价格（从字段读取）
                    sl_price = None
                    try:
                        if sl_order_id:
                            sl_price = float(sl_order_id)
                    except (ValueError, TypeError):
                        pass

                    # 获取市场剩余时间
                    seconds_left = None
                    try:
                        from datetime import timezone
                        market = self.get_market_data()
                        if market:
                            end_date = market.get('endDate')
                            if end_date:
                                end_dt = datetime.strptime(end_date, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                                now_dt = datetime.now(timezone.utc)
                                seconds_left = (end_dt - now_dt).total_seconds()
                    except:
                        pass

                    # 📊 显示双向监控状态
                    tp_gap = tp_target_price - pos_current_price
                    if sl_price:
                        sl_gap = pos_current_price - sl_price
                        time_info = f" | 剩余: {int(seconds_left)}s" if seconds_left else ""
                        print(f"       [MONITOR] 当前价: {pos_current_price:.4f} | TP目标: {tp_target_price:.4f} (差{tp_gap:.4f}) | SL止损: {sl_price:.4f} (距{sl_gap:.4f}){time_info}")
                    else:
                        print(f"       [MONITOR] 当前价: {pos_current_price:.4f} | TP目标: {tp_target_price:.4f} (差{tp_gap:.4f})")

                    # 双向监控：止盈和止损
                    # 1. 检查止盈（价格上涨触发）
                    if pos_current_price >= tp_target_price:
                        print(f"       [LOCAL TP] 触发本地止盈！当前价 {pos_current_price:.4f} >= 目标 {tp_target_price:.4f}")

                        # 撤销原有的止盈单（如果存在）
                        if tp_order_id:
                            try:
                                self.cancel_order(tp_order_id)
                                print(f"       [LOCAL TP] 已撤销原止盈单 {tp_order_id[-8:]}")
                            except:
                                pass

                        # 市价平仓
                        close_market = self.get_market_data()
                        if close_market:
                            close_order_id = self.close_position(close_market, side, size)

                            # 💡 增加识别 "NO_BALANCE" 的逻辑
                            if close_order_id == "NO_BALANCE":
                                # 🔍 关键修复：余额为0不代表止盈成交，必须查止盈单实际状态
                                # 场景A：止盈限价单成交 → 正收益 ✅
                                # 场景B：止盈限价单锁住token，市场到期归零 → 亏损 ❌
                                tp_actually_filled = False
                                tp_filled_price = None
                                if tp_order_id:
                                    try:
                                        tp_order_info = self.client.get_order(tp_order_id)
                                        if tp_order_info:
                                            tp_status = tp_order_info.get('status', '').upper()
                                            matched_size = float(tp_order_info.get('matchedSize', 0) or 0)
                                            if tp_status in ('MATCHED', 'FILLED') or matched_size > 0:
                                                tp_actually_filled = True
                                                p = tp_order_info.get('price')
                                                if p is not None:
                                                    tp_filled_price = float(p)
                                                print(f"       [LOCAL TP] ✅ 确认止盈单已成交 status={tp_status} price={tp_filled_price}")
                                            else:
                                                print(f"       [LOCAL TP] ❌ 止盈单未成交(status={tp_status})，余额为0是因为市场到期归零！")
                                    except Exception as e:
                                        print(f"       [LOCAL TP] 查询止盈单状态失败: {e}，保守处理为归零")

                                if tp_actually_filled:
                                    exit_reason = 'AUTO_CLOSED_OR_MANUAL'
                                    actual_exit_price = tp_filled_price if tp_filled_price else pos_current_price
                                else:
                                    # 市场到期归零，真实亏损
                                    exit_reason = 'MARKET_SETTLED'
                                    actual_exit_price = 0.0  # 归零，PnL = 0 - value_usdc = 全亏
                                    print(f"       [LOCAL TP] 💀 仓位已归零，记录真实亏损")
                            elif close_order_id:
                                exit_reason = 'TAKE_PROFIT_LOCAL'
                                triggered_order_id = close_order_id
                                actual_exit_price = pos_current_price  # fallback
                                # 🔍 修复：重试查询实际成交价
                                for _tp_attempt in range(5):
                                    try:
                                        time.sleep(3)
                                        close_order = self.client.get_order(close_order_id)
                                        if close_order:
                                            tp_status = close_order.get('status', '').upper()
                                            matched_size = float(close_order.get('matchedSize', 0) or 0)
                                            if tp_status in ('FILLED', 'MATCHED') or matched_size > 0:
                                                match_amount = float(close_order.get('matchAmount', 0) or 0)
                                                if matched_size > 0 and match_amount > 0:
                                                    actual_exit_price = match_amount / matched_size
                                                else:
                                                    p = close_order.get('price')
                                                    if p is not None:
                                                        actual_exit_price = float(p)
                                                print(f"       [LOCAL TP] ✅ 止盈实际成交价: {actual_exit_price:.4f} (尝试{_tp_attempt+1}次)")
                                                break
                                            else:
                                                print(f"       [LOCAL TP] ⏳ 止盈单未成交(status={tp_status})，继续等待({_tp_attempt+1}/5)...")
                                    except Exception as e:
                                        print(f"       [LOCAL TP] 查询成交价失败({_tp_attempt+1}/5): {e}")
                                else:
                                    print(f"       [LOCAL TP] ⚠️ 止盈单15秒内未确认成交，使用发单时价格: {actual_exit_price:.4f}")
                                print(f"       [LOCAL TP] 本地止盈执行完毕，成交价: {actual_exit_price:.4f}")
                            else:
                                print(f"       [LOCAL TP] 市价平仓失败(非余额原因)，下次继续尝试")

                    # 2. 检查止损（价格下跌触发）- 🔥 立即执行，不再等待最后5分钟
                    elif sl_price and pos_current_price <= sl_price:
                        print(f"       [LOCAL SL] 触发本地止损！当前价 {pos_current_price:.4f} <= 止损线 {sl_price:.4f}")
                        time_remaining = f"{int(seconds_left)}s" if seconds_left else "未知"
                        print(f"       [LOCAL SL] ⏰ 市场剩余 {time_remaining}，立即执行止损保护")

                        # 先撤止盈单，释放token（等待3秒让余额解冻）
                        if tp_order_id:
                            print(f"       [LOCAL SL] 撤销止盈单 {tp_order_id[-8:]}...")
                            self.cancel_order(tp_order_id)
                            time.sleep(3)  # 等待链上余额解冻，避免误判NO_BALANCE

                        # 市价平仓（止损模式，直接砸单不防插针）
                        close_market = self.get_market_data()
                        if close_market:
                            close_order_id = self.close_position(close_market, side, size, is_stop_loss=True)

                            # 💡 增加识别 "NO_BALANCE" 的逻辑
                            if close_order_id == "NO_BALANCE":
                                # 🔍 关键修复：止损时余额为0，同样需要区分两种情况
                                # 场景A：止盈限价单已提前成交（好事）
                                # 场景B：市场到期归零（坏事）
                                tp_actually_filled = False
                                tp_filled_price = None
                                if tp_order_id:
                                    try:
                                        tp_order_info = self.client.get_order(tp_order_id)
                                        if tp_order_info:
                                            tp_status = tp_order_info.get('status', '').upper()
                                            matched_size = float(tp_order_info.get('matchedSize', 0) or 0)
                                            if tp_status in ('MATCHED', 'FILLED') or matched_size > 0:
                                                tp_actually_filled = True
                                                p = tp_order_info.get('price')
                                                if p is not None:
                                                    tp_filled_price = float(p)
                                                print(f"       [LOCAL SL] ✅ 止盈单已提前成交 status={tp_status}，非归零")
                                            else:
                                                print(f"       [LOCAL SL] ❌ 止盈单未成交(status={tp_status})，市场到期归零！")
                                    except Exception as e:
                                        print(f"       [LOCAL SL] 查询止盈单状态失败: {e}，保守处理为归零")

                                if tp_actually_filled:
                                    exit_reason = 'AUTO_CLOSED_OR_MANUAL'
                                    actual_exit_price = tp_filled_price if tp_filled_price else pos_current_price
                                else:
                                    exit_reason = 'MARKET_SETTLED'
                                    actual_exit_price = 0.0
                                    print(f"       [LOCAL SL] 💀 仓位已归零，记录真实亏损")
                            elif close_order_id:
                                exit_reason = 'STOP_LOSS_LOCAL'
                                triggered_order_id = close_order_id
                                actual_exit_price = pos_current_price  # fallback
                                # 🔍 修复：重试查询实际成交价，避免滑点被掩盖
                                # 极端行情下2秒不够，最多等15秒（5次×3秒）
                                for _sl_attempt in range(5):
                                    try:
                                        time.sleep(3)
                                        close_order = self.client.get_order(close_order_id)
                                        if close_order:
                                            sl_status = close_order.get('status', '').upper()
                                            matched_size = float(close_order.get('matchedSize', 0) or 0)
                                            if sl_status in ('FILLED', 'MATCHED') or matched_size > 0:
                                                # 优先用 matchAmount/matchedSize 算加权均价
                                                match_amount = float(close_order.get('matchAmount', 0) or 0)
                                                if matched_size > 0 and match_amount > 0:
                                                    actual_exit_price = match_amount / matched_size
                                                else:
                                                    p = close_order.get('price')
                                                    if p is not None:
                                                        actual_exit_price = float(p)
                                                print(f"       [LOCAL SL] ✅ 止损实际成交价: {actual_exit_price:.4f} (尝试{_sl_attempt+1}次)")
                                                break
                                            else:
                                                print(f"       [LOCAL SL] ⏳ 止损单未成交(status={sl_status})，继续等待({_sl_attempt+1}/5)...")
                                    except Exception as e:
                                        print(f"       [LOCAL SL] 查询成交价失败({_sl_attempt+1}/5): {e}")
                                else:
                                    print(f"       [LOCAL SL] ⚠️ 止损单15秒内未确认成交，使用发单时价格: {actual_exit_price:.4f}")
                                print(f"       [LOCAL SL] 止损执行完毕，成交价: {actual_exit_price:.4f}")
                            else:
                                print(f"       [LOCAL SL] 市价平仓失败(非余额原因)，下次继续尝试")

                # 如果订单成交但没有获取到价格，使用当前价格作为fallback
                if exit_reason and actual_exit_price is None:
                    actual_exit_price = pos_current_price
                    print(f"       [POSITION WARNING] 订单成交但无法获取价格，使用当前价格: {actual_exit_price:.4f}")

                # 止盈止损完全依赖挂单成交，不做主动价格监控平仓

                # 检查市场是否即将到期（最后2分钟的智能平仓策略）
                if not exit_reason:
                    try:
                        from datetime import timezone
                        market = self.get_market_data()
                        if market:
                            end_date = market.get('endDate')
                            if end_date:
                                end_dt = datetime.strptime(end_date, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                                now_dt = datetime.now(timezone.utc)
                                seconds_left = (end_dt - now_dt).total_seconds()

                                # 🛡️ 市场已过期：直接标记为已结算，停止监控
                                if seconds_left < 0:
                                    print(f"       [EXPIRY] ⏰ 市场已过期({abs(seconds_left):.0f}秒)，标记为已结算")
                                    current_value = size * pos_current_price
                                    current_pnl = current_value - value_usdc
                                    print(f"       [EXPIRY] 最终盈亏: ${current_pnl:.2f}")
                                    exit_reason = 'MARKET_SETTLED'
                                    actual_exit_price = pos_current_price

                                # 计算当前盈亏（用于判断触发策略）
                                current_value = size * pos_current_price
                                current_pnl = current_value - value_usdc

                                # 💎 盈利情况：最后60秒提前锁定利润
                                if current_pnl >= 0 and seconds_left <= 60:
                                    print(f"       [EXPIRY] 💎 市场即将到期({seconds_left:.0f}秒)，当前盈利 ${current_pnl:.2f}")
                                    print(f"       [EXPIRY] 撤销止盈单，持有到结算锁定利润")

                                    # 撤销止盈单
                                    if tp_order_id:
                                        try:
                                            self.cancel_order(tp_order_id)
                                            print(f"       [EXPIRY] ✅ 已撤销止盈单")
                                        except:
                                            pass

                                    # 标记为持有到结算
                                    exit_reason = 'HOLD_TO_SETTLEMENT'
                                    actual_exit_price = pos_current_price

                                # 🩸 亏损情况：最后120秒强制止损
                                elif current_pnl < 0 and seconds_left <= 120:
                                    print(f"       [EXPIRY] ⏳ 市场即将到期({seconds_left:.0f}秒)，当前亏损 ${current_pnl:.2f}")
                                    print(f"       [EXPIRY] 🩸 执行强制市价平仓止损！")

                                    # 撤销止盈单
                                    if tp_order_id:
                                        try:
                                            self.cancel_order(tp_order_id)
                                            print(f"       [EXPIRY] 已撤销止盈单")
                                        except:
                                            pass

                                    # 市价平仓
                                    try:
                                        from py_clob_client.clob_types import OrderArgs
                                        close_price = max(0.01, min(0.99, pos_current_price * 0.97))

                                        close_order_args = OrderArgs(
                                            token_id=token_id,
                                            price=close_price,
                                            size=float(size),
                                            side=SELL
                                        )

                                        close_response = self.client.create_and_post_order(close_order_args)

                                        if close_response and 'orderID' in close_response:
                                            close_order_id = close_response['orderID']
                                            exit_reason = 'EXPIRY_FORCE_CLOSE'
                                            triggered_order_id = close_order_id
                                            actual_exit_price = pos_current_price
                                            print(f"       [EXPIRY] ✅ 强制平仓单已挂: {close_order_id[-8:]} @ {close_price:.4f}")
                                    except Exception as e:
                                        print(f"       [EXPIRY] ❌ 强制平仓失败: {e}")
                    except Exception as e:
                        pass  # 静默失败，不影响其他逻辑

                # 如果任一订单成交或市场结算，取消另一个订单并更新数据库
                # （对于MARKET_SETTLED情况，没有挂单需要取消）
                if exit_reason:
                    # 取消另一个订单
                    self.cancel_pair_orders(tp_order_id, sl_order_id, exit_reason)

                    # 计算实际盈亏
                    # LONG买YES，SHORT买NO，两者都是现货做多，公式统一：
                    # PnL = size * (exit_token_price - entry_token_price)
                    pnl_usd = size * (actual_exit_price - entry_token_price)
                    pnl_pct = (pnl_usd / value_usdc) * 100 if value_usdc > 0 else 0

                    # 更新持仓状态
                    cursor.execute("""
                        UPDATE positions
                        SET exit_time = ?, exit_token_price = ?, pnl_usd = ?,
                            pnl_pct = ?, exit_reason = ?, status = 'closed'
                        WHERE id = ?
                    """, (
                        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        actual_exit_price,  # 使用实际成交价格
                        pnl_usd,
                        pnl_pct,
                        exit_reason,
                        pos_id
                    ))

                    result_text = "盈利" if pnl_usd > 0 else "亏损"
                    print(f"       [POSITION] {exit_reason}: {side} {result_text} ${pnl_usd:+.2f} ({pnl_pct:+.1f}%) - 订单 {triggered_order_id}")
                    print(f"       [POSITION] 实际成交价: {actual_exit_price:.4f}")

                    # 更新 daily_loss 统计
                    if pnl_usd < 0:
                        self.stats['daily_loss'] += abs(pnl_usd)
                        print(f"       [STATS] 累计每日亏损: ${self.stats['daily_loss']:.2f} / ${self.position_mgr.get_max_daily_loss():.2f}")

                    # 回填学习系统退出结果
                    if self.learning_system:
                        try:
                            self.learning_system.update_exit_result(
                                market_slug=self._get_last_market_slug(pos_id),
                                exit_token_price=actual_exit_price,  # 使用实际成交价格
                                actual_pnl_pct=pnl_pct / 100,
                                exit_reason=exit_reason,
                            )
                        except Exception as le:
                            print(f"       [LEARNING EXIT ERROR] {le}")

            conn.commit()
            conn.close()

        except Exception as e:
            print(f"       [POSITION CHECK ERROR] {e}")

    def get_open_positions_count(self) -> int:
        """获取当前open持仓数量"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM positions WHERE status = 'open'")
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except:
            return 0

    def close_positions_by_signal_change(self, current_token_price: float, new_signal_direction: str):
        """信号改变时平掉所有相反方向的持仓，先取消止盈止损单，再市价平仓"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 确定需要平仓的方向（与当前信号相反）
            opposite_direction = 'SHORT' if new_signal_direction == 'LONG' else 'LONG'

            # 获取所有open状态的相反方向持仓（包括订单ID）
            cursor.execute("""
                SELECT id, entry_time, side, entry_token_price, value_usdc, size,
                       take_profit_order_id, stop_loss_order_id
                FROM positions
                WHERE status = 'open' AND side = ?
            """, (opposite_direction,))

            positions = cursor.fetchall()

            if not positions:
                conn.close()
                return

            closed_count = 0
            for pos in positions:
                pos_id, entry_time, side, entry_token_price, value_usdc, size, tp_order_id, sl_order_id = pos

                # 先取消止盈止损单
                if tp_order_id:
                    self.cancel_order(tp_order_id)
                if sl_order_id:
                    self.cancel_order(sl_order_id)

                # 实际调用API卖出平仓（带重试，最多3次）
                close_order_id = None
                for retry in range(3):
                    close_market = self.get_market_data()
                    if close_market:
                        close_order_id = self.close_position(close_market, side, size)
                        if close_order_id:
                            break
                        print(f"       [SIGNAL CHANGE] 平仓重试 {retry+1}/3 失败")
                        time.sleep(2)
                    else:
                        print(f"       [SIGNAL CHANGE] 无法获取市场数据，重试 {retry+1}/3")
                        time.sleep(2)

                if not close_order_id:
                    print(f"       [SIGNAL CHANGE] 平仓3次均失败，跳过此持仓，请手动处理！")
                    continue

                # 查询实际成交价格
                actual_exit_price = current_token_price  # fallback
                try:
                    time.sleep(2)  # 等待订单成交
                    close_order = self.client.get_order(close_order_id)
                    if close_order:
                        fetched_price = close_order.get('price')
                        if fetched_price is None and close_order.get('matchedSize'):
                            fetched_price = close_order.get('matchAmount') / close_order.get('matchedSize')
                        if fetched_price is not None:
                            actual_exit_price = float(fetched_price)
                            print(f"       [SIGNAL CHANGE] 实际成交价: {actual_exit_price:.4f}")
                        else:
                            print(f"       [SIGNAL CHANGE] 无法获取成交价，使用市场价: {actual_exit_price:.4f}")
                except Exception as e:
                    print(f"       [SIGNAL CHANGE] 查询成交价失败: {e}，使用市场价: {actual_exit_price:.4f}")

                # 用实际成交价计算盈亏
                # 统一算法：PnL = size * (exit_price - entry_price)
                pnl_usd = size * (actual_exit_price - entry_token_price)
                pnl_pct = (pnl_usd / value_usdc) * 100 if value_usdc > 0 else 0

                # 更新持仓状态（信号改变平仓）
                cursor.execute("""
                    UPDATE positions
                    SET exit_time = ?, exit_token_price = ?, pnl_usd = ?,
                        pnl_pct = ?, exit_reason = ?, status = 'closed'
                    WHERE id = ?
                """, (
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    actual_exit_price,
                    pnl_usd,
                    pnl_pct,
                    'SIGNAL_CHANGE',
                    pos_id
                ))

                result_text = "盈利" if pnl_usd > 0 else "亏损"
                print(f"       [SIGNAL CHANGE] 平仓 {side}: {result_text} ${pnl_usd:+.2f} ({pnl_pct:+.1f}%)")

                # 更新 daily_loss 统计
                if pnl_usd < 0:
                    self.stats['daily_loss'] += abs(pnl_usd)
                    print(f"       [STATS] 累计每日亏损: ${self.stats['daily_loss']:.2f} / ${self.position_mgr.get_max_daily_loss():.2f}")

                # 回填学习系统退出结果
                if self.learning_system:
                    try:
                        self.learning_system.update_exit_result(
                            market_slug=self._get_last_market_slug(pos_id),
                            exit_token_price=current_token_price,
                            actual_pnl_pct=pnl_pct / 100,
                            exit_reason='SIGNAL_CHANGE',
                        )
                    except Exception as le:
                        print(f"       [LEARNING EXIT ERROR] {le}")

                closed_count += 1

            if closed_count > 0:
                print(f"       [SIGNAL CHANGE] 共平仓 {closed_count} 个{opposite_direction}持仓")

            conn.commit()
            conn.close()

        except Exception as e:
            print(f"       [SIGNAL CHANGE ERROR] {e}")

    def run(self):
        print("=" * 70)
        print("STARTING AUTOMATED TRADING (CONTINUOUS MODE)")
        print("=" * 70)
        print()

        interval = CONFIG['system']['iteration_interval']
        i = 1

        try:
            while True:
                print(f"[Iter: {i}] {datetime.now().strftime('%H:%M:%S')}")

                market = self.get_market_data()
                if not market:
                    print("       No market")
                    time.sleep(interval)
                    i += 1
                    continue

                price = self.parse_price(market)
                if not price:
                    print("       No price")
                    time.sleep(interval)
                    i += 1
                    continue

                print(f"       Price: {price:.4f}")

                # 更新指标（RSI/VWAP/价格历史）- 在generate_signal之前调用
                try:
                    outcome_prices = market.get('outcomePrices', '[]')
                    if isinstance(outcome_prices, str):
                        outcome_prices = json.loads(outcome_prices)
                    best_bid = float(market.get('bestBid', price))
                    best_ask = float(market.get('bestAsk', price))
                    high = max(price, best_ask)
                    low = min(price, best_bid)
                except:
                    high = low = price
                self.update_indicators(price, high, low)

                # 检查持仓止盈止损（每次迭代都检查，利用WebSocket实时价格）
                self.check_positions(price)

                # 验证待验证的预测（每15秒检查一次）
                if i % 5 == 0:
                    self.verify_pending_predictions()

                # 生成信号
                new_signal = self.generate_signal(market, price)

                if new_signal:
                    # 增加信号计数器
                    self.stats['signal_count'] += 1

                    print(f"       Signal: {new_signal['direction']} | Score: {new_signal['score']:.1f}")

                    # 检测信号改变（作为止盈信号）
                    # 🔒 已禁用信号反转强制平仓 - 让仓位完全由止盈止损控制，避免频繁左右横跳
                    # if self.last_signal_direction and self.last_signal_direction != new_signal['direction']:
                    #     print(f"       [SIGNAL CHANGE] {self.last_signal_direction} → {new_signal['direction']}")
                    #     self.close_positions_by_signal_change(price, new_signal['direction'])

                    # 更新最后信号方向（不管是否交易）
                    self.last_signal_direction = new_signal['direction']

                    can_trade, reason = self.can_trade(new_signal, market)
                    if can_trade:
                        print(f"       Risk: {reason}")

                        order_result = self.place_order(market, new_signal)
                        self.record_trade(market, new_signal, order_result, was_blocked=False)

                        self.stats['total_trades'] += 1
                        self.stats['daily_trades'] += 1
                        self.stats['last_trade_time'] = datetime.now()
                    else:
                        print(f"       Risk: {reason}")
                        # 记录被拦截的信号到学习系统（was_blocked=True）
                        self.record_prediction_learning(market, new_signal, None, was_blocked=True)
                else:
                    print("       No signal")

                if self.learning_system:
                    if i % 10 == 0:
                        stats = self.learning_system.get_accuracy_stats(hours=24)
                        if stats['total'] > 0:
                            print(f"       [LEARNING] 准确率: {stats['accuracy']:.1f}% ({stats['total']}次)")

                    if i % 50 == 0:
                        print()
                        self.print_learning_reports()

                    # 验证待验证的预测（每10次迭代检查一次）
                    if i % 10 == 0:
                        self.learning_system.verify_pending_predictions()

                    # 自动参数调整（每20个信号检查一次）
                    if self.stats['signal_count'] > 0 and self.stats['signal_count'] % 20 == 0:
                        self.auto_adjust_parameters()

                time.sleep(interval)
                i += 1

        except KeyboardInterrupt:
            print()
            print("=" * 70)
            print(f"STOPPED BY USER - {self.stats['total_trades']} trades completed.")
            print("=" * 70)
            if self.learning_system:
                self.print_learning_reports()

    def _params_file(self) -> str:
        return os.path.join(os.path.dirname(self.db_path), 'dynamic_params.json')

    def load_dynamic_params(self):
        """启动时从文件恢复上次调整的参数"""
        try:
            path = self._params_file()
            if os.path.exists(path):
                with open(path, 'r') as f:
                    saved = json.load(f)
                keys = ['min_confidence', 'min_long_confidence', 'min_short_confidence', 'min_long_score', 'min_short_score', 'allow_long', 'allow_short']
                for k in keys:
                    if k in saved:
                        CONFIG['signal'][k] = saved[k]
                print(f"[OK] 动态参数已从文件恢复: {saved}")
        except Exception as e:
            print(f"[WARN] 动态参数加载失败: {e}")

    def save_dynamic_params(self):
        """将当前动态参数持久化到文件"""
        try:
            data = {
                'min_confidence': CONFIG['signal']['min_confidence'],
                'min_long_confidence': CONFIG['signal']['min_long_confidence'],
                'min_short_confidence': CONFIG['signal']['min_short_confidence'],
                'min_long_score': CONFIG['signal']['min_long_score'],
                'min_short_score': CONFIG['signal']['min_short_score'],
                'allow_long': CONFIG['signal']['allow_long'],
                'allow_short': CONFIG['signal']['allow_short'],
                'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            }
            with open(self._params_file(), 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[WARN] 动态参数保存失败: {e}")

    def auto_adjust_parameters(self):
        """根据学习系统建议自动调整参数"""
        if not self.learning_system:
            return

        try:
            recommended = self.learning_system.get_recommended_parameters()

            adjustments = []

            # 【注意】由于现在使用分别的置信度，禁用自动调整min_confidence
            # 只调整min_long_score和min_short_score
            # if recommended['min_confidence'] != CONFIG['signal']['min_confidence']:
            #     old_val = CONFIG['signal']['min_confidence']
            #     new_val = recommended['min_confidence']
            #     CONFIG['signal']['min_confidence'] = new_val
            #     adjustments.append(f"min_confidence: {old_val:.2f} → {new_val:.2f}")

            if recommended['min_long_score'] != CONFIG['signal']['min_long_score']:
                old_val = CONFIG['signal']['min_long_score']
                new_val = recommended['min_long_score']
                CONFIG['signal']['min_long_score'] = new_val
                adjustments.append(f"min_long_score: {old_val:.1f} → {new_val:.1f}")

            if recommended['min_short_score'] != CONFIG['signal']['min_short_score']:
                old_val = CONFIG['signal']['min_short_score']
                new_val = recommended['min_short_score']
                CONFIG['signal']['min_short_score'] = new_val
                adjustments.append(f"min_short_score: {old_val:.1f} → {new_val:.1f}")

            if 'allow_long' in recommended:
                if recommended['allow_long'] != CONFIG['signal']['allow_long']:
                    old_val = CONFIG['signal']['allow_long']
                    new_val = recommended['allow_long']
                    CONFIG['signal']['allow_long'] = new_val
                    adjustments.append(f"allow_long: {'启用' if new_val else '禁用'}")

            if 'allow_short' in recommended:
                if recommended['allow_short'] != CONFIG['signal']['allow_short']:
                    old_val = CONFIG['signal']['allow_short']
                    new_val = recommended['allow_short']
                    CONFIG['signal']['allow_short'] = new_val
                    adjustments.append(f"allow_short: {'启用' if new_val else '禁用'}")

            if adjustments:
                from colorama import Fore
                print(f"\n{Fore.CYAN}[AUTO-ADJUST] 参数已自动调整：{Fore.RESET}")
                for adj in adjustments:
                    print(f"  {Fore.GREEN}✓{Fore.RESET} {adj}")
                print()
                # 持久化到文件，重启后生效
                self.save_dynamic_params()

        except Exception as e:
            print(f"       [AUTO-ADJUST ERROR] {e}")

def main():
    trader = AutoTraderV5()
    trader.run()

if __name__ == "__main__":
    main()
