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

# 导入Session Memory系统（Layer 1）
try:
    from session_memory import SessionMemory
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    print("[WARN] Session Memory module not found, Layer 1 disabled")

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
        'base_position_pct': 0.10,      #  基础仓位10%（对应6手≈3U≈总资金10%）
        'max_position_pct': 0.30,       #  单笔最高仓位30%（信号很强时）
        'max_total_exposure_pct': 0.60,  #  同一窗口累计持仓上限60%（防止多笔累计超仓）
        'reserve_usdc': 0.0,             #  不保留余额，全仓利用
        'min_position_usdc': 2.0,        # Minimum 2 USDC per order
        'max_daily_trades': 96,          # 15min市场: 96次/天 = 每15分钟1次
        'max_daily_loss_pct': 1.0,      # 100% daily loss (禁用日亏损限制)
        'stop_loss_consecutive': 4,      # 提高到4（2太容易触发，错过机会）
        'pause_hours': 0.5,            # 缩短到0.5小时（2小时太长）
        'max_same_direction_bullets': 999,  # 10秒抢跑版：放开弹匣限制（快速进出）
        'same_direction_cooldown_sec': 60,  # 同市场同方向最小间隔秒数
        'max_trades_per_window': 999,     # 每个15分钟窗口最多开单总数（已放宽，仅最后3分钟限制）

        # [策略调整] 禁用止盈止损，持有到期（参考 @jtrevorchapman）
        # 理由：我们在3-6分钟开仓，就是赌15分钟到期结算，不应该中间退出
        'max_stop_loss_pct': 0.80,      # 80%止损（仅极端情况保护，基本不触发）
        'take_profit_pct': 0.90,        # 90%止盈（基本不触发，持有到期）
        'enable_stop_loss': False,      #  禁用止盈止损：持有到期，赌结算结果
    },

    'signal': {
        'min_confidence': 0.75,  # 默认置信度（保留用于兼容）
        'min_long_confidence': 0.60,   # LONG最小置信度
        'min_short_confidence': 0.60,  # SHORT最小置信度
        'min_long_score': 4.0,      #  提高到4.0（LONG胜率22%，减少低质量信号）
        'min_short_score': -3.0,    # SHORT保持-3.0（胜率69%）
        'balance_zone_min': 0.49,  # 平衡区间下限
        'balance_zone_max': 0.51,  # 平衡区间上限
        'allow_long': True,   # 允许做多（但会动态调整）
        'allow_short': True,  # 允许做空（但会动态调整）

        #  价格限制（允许追强势单，但拒绝极高位接盘）
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
        # [ROCKET] HTTP Session（复用TCP连接，提速Telegram通知）
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

            # [ROCKET] 使用Session复用TCP连接（提速Telegram通知）
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
        emoji = "" if side == 'LONG' else ""
        token_name = "YES" if side == 'LONG' else "NO"

        message = f"""{emoji} <b>开仓</b>

{emoji} 买入 {token_name}
[MONEY] {value_usdc:.2f} USDC
[UP] {size:.0f} 份 @ {entry_price:.4f}

[TARGET] 止盈: {tp_price:.4f}
[BLOCK] 止损: {sl_price:.4f}"""

        return self.send(message, parse_mode='HTML')

    def send_stop_order_failed(self, side: str, size: float, tp_price: float, sl_price: float, token_id: str, error: str):
        """（已弃用）"""
        return False

    def send_position_closed(self, side: str, entry_price: float, exit_price: float, pnl_usd: float, reason: str):
        """（已弃用）"""
        return False

class RealBalanceDetector:
    """Get REAL balance using Polygon RPC (with dual-node fallback)"""

    def __init__(self, wallet: str):
        self.wallet = wallet
        self.balance_usdc = 0.0
        self.balance_pol = 0.0
        # [ROCKET] HTTP Session（复用TCP连接，提速RPC调用）
        self.http_session = requests.Session()

        # [ROCKET] 性能优化：双节点容灾架构（Alchemy + QuickNode）
        # 从环境变量读取，避免硬编码密钥
        self.rpc_pool = []

        # 主力节点：Alchemy（从环境变量读取）
        alchemy_key = os.getenv('ALCHEMY_POLYGON_KEY')
        if alchemy_key:
            #  调试：检查密钥格式
            if len(alchemy_key) < 10:
                print(f"[RPC] ⚠  ALCHEMY_POLYGON_KEY格式异常（长度{len(alchemy_key)}），可能无效")
            else:
                alchemy_url = f"https://polygon-mainnet.g.alchemy.com/v2/{alchemy_key}"
                self.rpc_pool.append(alchemy_url)
                print(f"[RPC]  Alchemy节点已配置（密钥长度: {len(alchemy_key)}）")
        else:
            print("[RPC] ⚠  未设置ALCHEMY_POLYGON_KEY环境变量，跳过Alchemy节点")

        # 备用节点：QuickNode（从环境变量读取）
        quicknode_key = os.getenv('QUICKNODE_POLYGON_KEY')
        if quicknode_key:
            #  智能识别：完整URL直接用，只有密钥则拼接示例URL
            if quicknode_key.startswith('http'):
                quicknode_url = quicknode_key  # 用户提供了完整URL
            else:
                # 用户只提供了密钥，使用旧格式（注意：这需要您的endpoint匹配）
                quicknode_url = f"https://flashy-attentive-road.matic.quiknode.pro/{quicknode_key}/"
                print("[RPC] ⚠  检测到只提供了QuickNode密钥，使用默认URL格式（可能不匹配您的endpoint）")

            self.rpc_pool.append(quicknode_url)
            print(f"[RPC]  QuickNode节点已配置")
        else:
            print("[RPC] ⚠  未设置QUICKNODE_POLYGON_KEY环境变量，跳过QuickNode节点")

        # 公共备用节点（保底方案，速度慢但可用）
        self.rpc_pool.append("https://polygon-bor.publicnode.com")
        print(f"[RPC]  公共备用节点已配置（保底）")

        print(f"[RPC] [ROCKET] RPC节点池大小: {len(self.rpc_pool)} (双节点容灾架构)")

    def _rpc_call(self, payload: dict, timeout: float = 3.0) -> dict:
        """
        带有自动故障转移(Fallback)的 RPC 请求发送器

        Args:
            payload: JSON-RPC payload
            timeout: 请求超时时间（秒）

        Returns:
            响应JSON，如果所有节点都失败则返回None
        """
        for i, rpc_url in enumerate(self.rpc_pool):
            try:
                resp = self.http_session.post(
                    rpc_url,
                    json=payload,
                    proxies=CONFIG.get('proxy'),
                    timeout=timeout
                )
                resp.raise_for_status()
                result = resp.json()

                # 打印使用的节点（只在第一次成功时）
                if i == 0:
                    node_name = rpc_url.split('/')[2].split('.')[0]
                    print(f"[RPC]  使用节点: {node_name}")

                return result

            except Exception as e:
                node_name = rpc_url.split('/')[2].split('.')[0] if '/' in rpc_url else '未知'
                print(f"[RPC] ⚠  节点 {node_name} 失败: {str(e)[:50]}")
                continue

        print(f"[RPC]  所有RPC节点均不可用！")
        return None

    def fetch(self) -> Tuple[float, float]:
        """Fetch real balance from Polygon"""
        print()
        # --- 强制使用网页版代理钱包查余额 ---
        CONFIG['wallet_address'] = "0xd5d037390c6216CCFa17DFF7148549B9C2399BD3"
        print("[BALANCE] Fetching REAL balance from Polygon...")

        try:
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

            # [ROCKET] 使用双节点容灾架构（自动故障转移）
            result = self._rpc_call(payload, timeout=3.0)

            if result and 'result' in result and result['result']:
                result_hex = result['result']
                balance_wei = int(result_hex, 16)
                self.balance_usdc = balance_wei / 1e6  # USDC.e has 6 decimals
                print(f"[OK] USDC.e balance: {self.balance_usdc:.2f}")
            else:
                print("[WARN] No USDC.e found")
                self.balance_usdc = 0.0

            # Get POL balance
            payload2 = {
                "jsonrpc": "2.0",
                "method": "eth_getBalance",
                "params": [self.wallet, "latest"],
                "id": 2
            }

            # [ROCKET] 使用双节点容灾架构（自动故障转移）
            result2 = self._rpc_call(payload2, timeout=3.0)

            if result2 and 'result' in result2:
                balance_wei = int(result2['result'], 16)
                self.balance_pol = balance_wei / 1e18
                print(f"[OK] POL balance: {self.balance_pol:.4f}")

            print()
            return self.balance_usdc, self.balance_pol

        except Exception as e:
            print(f"[ERROR] Balance fetch failed: {e}")
            print()
            print("[FATAL] 无法获取余额，为安全起见停止运行")
            print("[INFO] 请检查RPC节点配置或网络连接")
            self.balance_usdc = 0.0
            self.balance_pol = 0.0
            return self.balance_usdc, self.balance_pol

class PositionManager:
    """Manage positions based on REAL balance"""

    def __init__(self, balance_usdc: float):
        self.balance = balance_usdc

    def calculate_position(self, confidence: float, score: float = 0.0) -> float:
        """
        智能动态仓位：根据信号强度（score）自动调整

        Args:
            confidence: 置信度（0-1）
            score: 信号分数（-10到+10）

        Returns:
            实际下单金额（USDC）
        """
        available = self.balance - CONFIG['risk']['reserve_usdc']

        if available <= CONFIG['risk']['min_position_usdc']:
            return 0.0  # Not enough to meet minimum

        # 基础仓位：30%（提升以适应12U小资金，确保能买6份）
        base = self.balance * 0.30

        # [TARGET] 根据信号分数分段调整（方案A：智能分段）
        abs_score = abs(score)

        if abs_score >= 6.0:
            #  超强信号：40%
            multiplier = 1.33
        elif abs_score >= 4.5:
            #  强信号：35%
            multiplier = 1.16
        elif abs_score >= 3.5:
            #  中等信号：32%
            multiplier = 1.06
        else:
            # ⚠ 弱信号：30%
            multiplier = 1.0

        # 结合confidence微调（±10%）
        confidence_adj = 0.9 + (confidence * 0.2)  # 0.9 - 1.1

        adjusted = base * multiplier * confidence_adj

        # 限制在30%-40%范围内
        min_pos = self.balance * 0.30
        max_pos = self.balance * 0.40
        final = max(min_pos, min(adjusted, max_pos))

        # IMPORTANT: Must be at least 2 USDC
        min_required = CONFIG['risk']['min_position_usdc']
        final = max(final, min_required)

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
            # 波动率只影响置信度倍数，不贡献方向分
            # 高波动时信号更可信（有趋势），低波动时信号弱（横盘）
            vol_multiplier = 0.5 + norm_vol * 0.5  # 0.5~1.0
            components['volatility'] = norm_vol
        else:
            vol_multiplier = 0.75
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
        # 波动率作为置信度倍数：高波动增强信号，低波动削弱信号
        score = score * vol_multiplier
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

        # [MEMORY] Layer 1: Session Memory System
        self.session_memory = None
        try:
            from session_memory import SessionMemory
            self.session_memory = SessionMemory()
            print("[MEMORY] Session Memory System (Layer 1) 已启用")
            print("    功能: 基于历史会话计算先验偏差")
        except Exception as e:
            print(f"[WARN] Session Memory初始化失败: {e}")
            self.session_memory = None

        # [VOTING] 投票系统（实验性，替换原评分系统）
        try:
            from voting_system import create_voting_system
            self.voting_system = create_voting_system(self.session_memory)
            self.use_voting_system = True  # 开关：True使用投票，False使用原系统
            print("[VOTING] 投票系统已启用（9个规则 + 超短动量）")
            print("    规则: Momentum 30s/60s/120s, Price, RSI, VWAP, Trend, Oracle CVD, UT Bot, Memory")
        except Exception as e:
            print(f"[WARN] 投票系统初始化失败: {e}")
            self.voting_system = None
            self.use_voting_system = False


        # [ROCKET] HTTP Session池（复用TCP连接，提速3-5倍）
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
        #  防止止盈止损重复触发的集合（存储正在处理的持仓ID）
        self.processing_positions = set()

        #  反追空装甲系统：单向连亏熔断器
        self.directional_circuit_breaker = {
            'LONG': {
                'consecutive_losses': 0,
                'timeout_until': 0,
                'last_entry_price': None,
                'last_loss_time': None
            },
            'SHORT': {
                'consecutive_losses': 0,
                'timeout_until': 0,
                'last_entry_price': None,
                'last_loss_time': None
            }
        }
        print("[ 反追空装甲] 单向连亏熔断器已启动")
        print("    配置: 连续3次同向亏损 → 锁定该方向30分钟")
        self.init_database()

        # 从数据库恢复当天的亏损和交易统计（防止重启后风控失效）
        self._restore_daily_stats()

        print("[OK] System Ready - Using REAL Balance!")
        print()

        # 恢复上次自动调整的参数
        self.load_dynamic_params()


        # 启动时清理过期持仓
        self.cleanup_stale_positions()

        #  启动时打印最近的交易记录（用于调试）
        self.print_recent_trades()

        # ==========================================
        #  智能防御层 (Sentinel) 状态记忆
        # ==========================================
        self.session_cross_count = 0
        self.last_cross_state = None
        self.last_session_id = -1
        print("[ 智能防御层] 混沌监测系统已启动")

    def cleanup_stale_positions(self):
        """启动时清理过期持仓（超过20分钟的open持仓自动平仓）

        优化逻辑：
        1. 先清理卡在'closing'状态的持仓（修复止损/止盈失败导致的bug）
        2. 然后处理超过20分钟的open持仓
        """
        try:
            if not self.client:
                print("[CLEANUP] 跳过：CLOB客户端未初始化")
                return

            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            #  激活WAL模式：多线程并发读写（防止database is locked）
            conn.execute('PRAGMA journal_mode=WAL;')
            cursor = conn.cursor()

            #  新增：清理卡在'closing'状态的持仓（修复止损/止盈失败bug）
            cursor.execute("""
                SELECT id, entry_time, side, entry_token_price, size
                FROM positions
                WHERE status = 'closing'
            """)
            closing_positions = cursor.fetchall()

            if closing_positions:
                print(f"[CLEANUP]  发现 {len(closing_positions)} 个卡在'closing'状态的持仓")

                for pos_id, entry_time, side, entry_price, size in closing_positions:
                    print(f"[CLEANUP] 处理持仓 #{pos_id}: {side} {size}份 @ ${entry_price:.4f}")

                    # 检查是否已经手动平仓或市场结算
                    try:
                        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

                        # 获取token_id（从数据库读取）
                        cursor.execute("SELECT token_id FROM positions WHERE id = ?", (pos_id,))
                        token_id_row = cursor.fetchone()
                        if not token_id_row:
                            print(f"[CLEANUP] ⚠ 持仓 #{pos_id} 没有token_id，跳过")
                            continue

                        token_id = str(token_id_row[0])

                        # 查询链上余额
                        params = BalanceAllowanceParams(
                            asset_type=AssetType.CONDITIONAL,
                            token_id=token_id,
                            signature_type=2
                        )
                        result = self.client.get_balance_allowance(params)

                        if result:
                            amount = float(result.get('balance', '0') or '0')
                            actual_size = amount / 1e6

                            if actual_size < 0.5:
                                # 余额为0，说明已手动平仓或市场结算
                                print(f"[CLEANUP]  持仓 #{pos_id} 余额为{actual_size:.2f}，已平仓")

                                # 判断是手动平仓还是市场结算
                                cursor.execute("SELECT exit_token_price FROM positions WHERE id = ?", (pos_id,))
                                exit_price_row = cursor.fetchone()
                                current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                                if not exit_price_row or not exit_price_row[0]:
                                    # 没有exit记录，标记为MARKET_SETTLED
                                    cursor.execute("""
                                        UPDATE positions
                                        SET exit_time = ?, exit_token_price = ?, exit_reason = ?, status = 'closed'
                                        WHERE id = ?
                                    """, (
                                        current_time,
                                        0.0,  # 市场结算价格为0
                                        'MARKET_SETTLED',
                                        pos_id
                                    ))
                                    print(f"[CLEANUP]  持仓 #{pos_id} 已标记为MARKET_SETTLED")
                                else:
                                    # 有exit记录，标记为MANUAL_CLOSED
                                    cursor.execute("""
                                        UPDATE positions
                                        SET status = 'closed', exit_reason = 'MANUAL_CLOSED'
                                        WHERE id = ?
                                    """, (pos_id,))
                                    print(f"[CLEANUP]  持仓 #{pos_id} 已标记为MANUAL_CLOSED")
                            else:
                                # 余额不为0，重置为open状态，让监控系统继续处理
                                print(f"[CLEANUP] [UNLOCK] 持仓 #{pos_id} 余额为{actual_size:.2f}，重置为'open'")
                                cursor.execute("UPDATE positions SET status = 'open' WHERE id = ?", (pos_id,))

                    except Exception as e:
                        print(f"[CLEANUP] ⚠ 处理持仓 #{pos_id} 失败: {e}，重置为'open'")
                        # 失败时也重置为open，避免卡住
                        cursor.execute("UPDATE positions SET status = 'open' WHERE id = ?", (pos_id,))

                self.safe_commit(conn)
                print(f"[CLEANUP]  'closing'状态持仓清理完成")

            # 原有逻辑：获取超过20分钟的open持仓
            cursor.execute("""
                SELECT id, entry_time, side, entry_token_price, size, value_usdc, token_id,
                       take_profit_order_id, stop_loss_order_id
                FROM positions
                WHERE status = 'open'
            """)
            positions = cursor.fetchall()
            cleaned = 0

            for pos_id, entry_time, side, entry_price, size, value_usdc, token_id, tp_order_id, sl_order_id in positions:
                try:
                    entry_dt = datetime.strptime(entry_time, '%Y-%m-%d %H:%M:%S')
                    elapsed = (datetime.now() - entry_dt).total_seconds()

                    if elapsed > 1200:  # 超过20分钟
                        print(f"[CLEANUP] 持仓 #{pos_id} 超过20分钟({elapsed/60:.1f}分钟)，执行清理")

                        # [ROCKET] 优化：先查询链上订单状态
                        orders_exist = False
                        orders_cancelled = False

                        # 检查止盈单状态
                        if tp_order_id:
                            try:
                                tp_order = self.client.get_order(tp_order_id)
                                if tp_order:
                                    status = tp_order.get('status', '').upper()
                                    if status in ('FILLED', 'MATCHED'):
                                        # 止盈单已成交，更新数据库
                                        print(f"[CLEANUP]  发现止盈单已成交: {tp_order_id[-8:]}")
                                        avg_price = tp_order.get('avgPrice') or tp_order.get('price')
                                        if avg_price:
                                            try:
                                                exit_p = float(avg_price)
                                                if 0.01 <= exit_p <= 0.99:
                                                    pnl_usd = size * (exit_p - entry_price)
                                                    pnl_pct = (pnl_usd / (size * entry_price)) * 100 if size * entry_price > 0 else 0

                                                    cursor.execute("""
                                                        UPDATE positions
                                                        SET status='closed', exit_reason='TAKE_PROFIT',
                                                            exit_time=?, exit_token_price=?, pnl_usd=?, pnl_pct=?
                                                        WHERE id=?
                                                    """, (
                                                        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                                        exit_p, pnl_usd, pnl_pct, pos_id
                                                    ))
                                                    self.safe_commit(conn)
                                                    print(f"[CLEANUP]  持仓 #{pos_id} 止盈成交: ${pnl_usd:+.2f} ({pnl_pct:+.1f}%) @ {exit_p:.4f}")
                                                    if pnl_usd < 0:
                                                        self.stats['daily_loss'] += abs(pnl_usd)
                                                    cleaned += 1
                                                    continue  # 跳过后续处理
                                            except:
                                                pass
                                    elif status in ('LIVE', 'OPEN'):
                                        orders_exist = True
                                        print(f"[CLEANUP] 止盈单仍存在: {tp_order_id[-8:]} ({status})")
                                    else:
                                        print(f"[CLEANUP] 止盈单状态: {status}")
                            except Exception as e:
                                err_str = str(e).lower()
                                if 'not found' in err_str or 'does not exist' in err_str:
                                    print(f"[CLEANUP] 止盈单不存在（可能已成交或取消）")
                                else:
                                    print(f"[CLEANUP] 查询止盈单失败: {e}")

                        # 检查止损单状态（如果止损单是订单ID而不是价格）
                        if sl_order_id and sl_order_id.startswith('0x'):
                            try:
                                sl_order = self.client.get_order(sl_order_id)
                                if sl_order:
                                    status = sl_order.get('status', '').upper()
                                    if status in ('LIVE', 'OPEN'):
                                        orders_exist = True
                                        print(f"[CLEANUP] 止损单仍存在: {sl_order_id[-8:]} ({status})")
                            except Exception as e:
                                err_str = str(e).lower()
                                if 'not found' in err_str or 'does not exist' in err_str:
                                    print(f"[CLEANUP] 止损单不存在")

                        # [TARGET] 关键优化：如果链上订单都不存在 → 市场已到期归零
                        if not orders_exist:
                            print(f"[CLEANUP] ⚠  链上订单已不存在，判断为市场到期归零")
                            pnl_usd = 0 - (size * entry_price)  # 全亏
                            pnl_pct = -100.0

                            cursor.execute("""
                                UPDATE positions
                                SET status='closed', exit_reason='MARKET_SETTLED',
                                    exit_time=?, exit_token_price=0, pnl_usd=?, pnl_pct=?
                                WHERE id=?
                            """, (
                                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                pnl_usd, pnl_pct, pos_id
                            ))
                            self.safe_commit(conn)
                            print(f"[CLEANUP]  持仓 #{pos_id} 已归零: ${pnl_usd:+.2f} ({pnl_pct:+.1f}%)")
                            if pnl_usd < 0:
                                self.stats['daily_loss'] += abs(pnl_usd)
                            cleaned += 1
                            continue

                        # 如果链上订单还存在，尝试取消并平仓
                        print(f"[CLEANUP] [RELOAD] 链上订单仍存在，尝试取消并平仓")

                        # 取消订单
                        if tp_order_id:
                            try:
                                self.cancel_order(tp_order_id)
                                print(f"[CLEANUP] 已取消止盈单: {tp_order_id[-8:]}")
                                orders_cancelled = True
                            except Exception as e:
                                print(f"[CLEANUP] 取消止盈单失败: {e}")

                        if sl_order_id and sl_order_id.startswith('0x'):
                            try:
                                self.cancel_order(sl_order_id)
                                print(f"[CLEANUP] 已取消止损单: {sl_order_id[-8:]}")
                                orders_cancelled = True
                            except Exception as e:
                                print(f"[CLEANUP] 取消止损单失败: {e}")

                        # 尝试市价平仓
                        try:
                            from py_clob_client.clob_types import OrderArgs
                            import time

                            # 获取当前市场价格
                            try:
                                current_price = self.get_order_book(token_id, side='BUY')
                                if not current_price or current_price <= 0.01:
                                    price_url = "https://clob.polymarket.com/price"
                                    price_resp = self.http_session.get(
                                        price_url,
                                        params={"token_id": token_id, "side": "BUY"},
                                        proxies=CONFIG['proxy'],
                                        timeout=10
                                    )
                                    if price_resp.status_code == 200:
                                        current_price = float(price_resp.json().get('price', entry_price))
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
                                            # 计算盈亏
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
                                            self.safe_commit(conn)
                                            print(f"[CLEANUP]  持仓 #{pos_id} 已平仓: ${pnl_usd:+.2f} ({pnl_pct:+.1f}%)")
                                            if pnl_usd < 0:
                                                self.stats['daily_loss'] += abs(pnl_usd)
                                            cleaned += 1
                                            break
                                    except:
                                        pass
                                else:
                                    # 等待超时，仍然标记为closed
                                    print(f"[CLEANUP] ⚠  平仓单未立即成交，标记为closed")
                                    cursor.execute("""
                                        UPDATE positions SET status='closed', exit_reason='STALE_CLEANUP',
                                        exit_time=? WHERE id=?
                                    """, (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), pos_id))
                                    self.safe_commit(conn)
                                    cleaned += 1
                            else:
                                print(f"[CLEANUP] [X] 平仓单失败，仅标记为closed")
                                cursor.execute("""
                                    UPDATE positions SET status='closed', exit_reason='STALE_CLEANUP',
                                    exit_time=? WHERE id=?
                                """, (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), pos_id))
                                self.safe_commit(conn)
                                cleaned += 1

                        except Exception as close_error:
                            err_msg = str(close_error)
                            # 即使平仓失败，也标记为closed
                            print(f"[CLEANUP] 平仓异常: {close_error}，标记为closed")
                            cursor.execute("""
                                UPDATE positions SET status='closed', exit_reason='STALE_CLEANUP',
                                exit_time=? WHERE id=?
                            """, (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), pos_id))
                            self.safe_commit(conn)
                            cleaned += 1

                except Exception as e:
                    print(f"[CLEANUP] 处理持仓 #{pos_id} 失败: {e}")
                    import traceback
                    print(f"[CLEANUP] Traceback: {traceback.format_exc()}")
                    pass

            conn.close()
            if cleaned > 0:
                print(f"[CLEANUP]  清理了 {cleaned} 笔过期持仓")
        except Exception as e:
            print(f"[CLEANUP ERROR] {e}")
            import traceback
            print(f"[CLEANUP] Traceback: {traceback.format_exc()}")

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

    def safe_commit(self, connection):
        """带有重试机制的安全数据库提交 (防止多线程高频并发锁死)"""
        import time
        import sqlite3
        for i in range(5):
            try:
                connection.commit()
                break
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower():
                    time.sleep(0.5)
                else:
                    raise e
                    
    def init_database(self):
        # 支持通过环境变量配置数据目录（用于Zeabur持久化存储）
        # 默认使用 /app/data (Zeabur持久化卷)，如果环境变量未设置则使用当前目录
        data_dir = os.getenv('DATA_DIR', '/app/data')
        self.db_path = os.path.join(data_dir, 'btc_15min_auto_trades.db')

        # 确保数据目录存在
        os.makedirs(data_dir, exist_ok=True)

        # ======== 核心修复：开启高并发数据库模式 ========
        # check_same_thread=False: 允许不同线程(下单线程和主线程)同时访问
        # timeout=20.0: 如果遇到锁，排队等20秒而不是直接报错
        self.conn = sqlite3.connect(
            self.db_path, 
            timeout=20.0, 
            check_same_thread=False
        )
        #  加这一行！让底下的 self.safe_commit(conn) 重新生效
        conn = self.conn
        
        cursor = self.conn.cursor()
        cursor.execute('PRAGMA journal_mode=WAL;')
        # ===============================================

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
                status TEXT DEFAULT 'open',
                score REAL DEFAULT 0.0,
                oracle_score REAL DEFAULT 0.0,
                oracle_1h_trend TEXT DEFAULT 'NEUTRAL',
                oracle_15m_trend TEXT DEFAULT 'NEUTRAL',
                merged_from INTEGER DEFAULT 0,
                strategy TEXT DEFAULT 'TREND_FOLLOWING'
            )
        """)

        #  数据库迁移：添加新列
        migrations = [
            ("score", "ALTER TABLE positions ADD COLUMN score REAL DEFAULT 0.0"),
            ("oracle_score", "ALTER TABLE positions ADD COLUMN oracle_score REAL DEFAULT 0.0"),
            ("oracle_1h_trend", "ALTER TABLE positions ADD COLUMN oracle_1h_trend TEXT DEFAULT 'NEUTRAL'"),
            ("oracle_15m_trend", "ALTER TABLE positions ADD COLUMN oracle_15m_trend TEXT DEFAULT 'NEUTRAL'"),
            ("highest_price", "ALTER TABLE positions ADD COLUMN highest_price REAL DEFAULT 0.0"),  # [ROCKET] 吸星大法：追踪止盈
        ]

        for column_name, alter_sql in migrations:
            try:
                cursor.execute(f"SELECT {column_name} FROM positions LIMIT 1")
            except sqlite3.OperationalError:
                cursor.execute(alter_sql)
                conn.commit()
                print(f"[MIGRATION] 数据库已升级：positions表添加{column_name}列")

        #  数据库迁移：添加 merged_from 列
        try:
            cursor.execute("SELECT merged_from FROM positions LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE positions ADD COLUMN merged_from INTEGER DEFAULT 0")
            conn.commit()
            print("[MIGRATION] 数据库已升级：positions表添加merged_from列")

        #  数据库迁移：添加 strategy 列（双轨制策略标记）
        try:
            cursor.execute("SELECT strategy FROM positions LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE positions ADD COLUMN strategy TEXT DEFAULT 'TREND_FOLLOWING'")
            conn.commit()
            print("[MIGRATION] 数据库已升级：positions表添加strategy列")

        self.safe_commit(conn)

        # 兼容旧数据库：添加 token_id 列（如果不存在）
        try:
            cursor.execute("ALTER TABLE positions ADD COLUMN token_id TEXT")
            self.safe_commit(conn)
        except:
            pass  # 列已存在，忽略

        #  F1修复：self.conn 是持久连接，不能在这里关闭
        # conn.close() 已移除，self.conn 在整个生命周期保持打开

    def _restore_daily_stats(self):
        """从数据库恢复当天的亏损和交易统计，防止重启后风控失效"""
        try:
            today = datetime.now().date().strftime('%Y-%m-%d')
            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            #  激活WAL模式：多线程并发读写（防止database is locked）
            conn.execute('PRAGMA journal_mode=WAL;')
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

    def print_recent_trades(self, days=3):
        """打印最近的交易记录（用于调试）"""
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            #  激活WAL模式：多线程并发读写（防止database is locked）
            conn.execute('PRAGMA journal_mode=WAL;')
            cursor = conn.cursor()

            # 查询最近的N天交易
            cursor.execute("""
                SELECT id, entry_time, side, entry_token_price, size, value_usdc,
                       exit_time, exit_token_price, exit_reason, pnl_pct, status
                FROM positions
                WHERE entry_time >= date('now', '-{} days')
                ORDER BY entry_time DESC
                LIMIT 20
            """.format(days))

            rows = cursor.fetchall()
            conn.close()

            if not rows:
                return

            print("\n" + "=" * 100)
            print(f"最近{days}天的交易记录 (最多20笔)")
            print("=" * 100)
            print(f"{'ID':<5} {'入场时间':<20} {'方向':<6} {'入场价':<8} {'数量':<8} {'出场价':<8} {'退出原因':<20} {'收益率':<8}")
            print("-" * 100)

            for row in rows:
                id, entry_time, side, entry_price, size, value_usdc, exit_time, exit_price, exit_reason, pnl_pct, status = row
                entry_price = float(entry_price) if entry_price else 0
                exit_price = float(exit_price) if exit_price else 0
                pnl_pct = float(pnl_pct) if pnl_pct else 0

                exit_reason = (exit_reason or '')[:20]
                print(f"{id:<5} {entry_time:<20} {side:<6} {entry_price:<8.4f} {size:<8.1f} {exit_price:<8.4f} {exit_reason:<20} {pnl_pct:>6.1f}%")

            print("=" * 100 + "\n")

        except Exception as e:
            print(f"[DEBUG] 打印交易记录失败: {e}")

    def print_trading_analysis(self):
        """打印交易分析报告（每60次迭代调用一次，约15分钟）"""
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            #  每次都打印最近的交易记录（自动导出到日志）
            cursor.execute("""
                SELECT
                    entry_time, side, entry_token_price, exit_token_price,
                    pnl_usd, pnl_pct, exit_reason, status,
                    score, oracle_score, oracle_1h_trend, oracle_15m_trend
                FROM positions
                WHERE status = 'closed'
                ORDER BY entry_time DESC
                LIMIT 10
            """)
            trades = cursor.fetchall()

            if trades:
                print("\n" + "="*140)
                print(f"【自动导出】最近{len(trades)}笔交易记录")
                print("="*140)

                total_pnl = 0
                win_count = 0
                loss_count = 0

                for i, t in enumerate(trades, 1):
                    pnl_icon = "盈利" if t['pnl_usd'] and t['pnl_usd'] > 0 else "[X]亏损"
                    exit_price = f"{t['exit_token_price']:.4f}" if t['exit_token_price'] else "N/A"

                    print(f"\n  {i}. [{t['entry_time']}] {t['side']:6s} {t['entry_token_price']:.4f}->{exit_price} {pnl_icon:8s} ${t['pnl_usd']:+.2f}")

                    # sqlite3.Row 不支持 .get() 方法，直接访问并检查 None
                    oracle_score = t['oracle_score']
                    if oracle_score is not None:
                        oracle_icon = "" if abs(oracle_score) >= 10 else "" if abs(oracle_score) >= 7 else ""
                        print(f"     Oracle:{oracle_icon} {oracle_score:+.2f} | 1H:{t['oracle_1h_trend']} 15m:{t['oracle_15m_trend']}")
                    else:
                        print(f"     Oracle: 未保存")

                    if t['pnl_usd']:
                        if t['pnl_usd'] > 0:
                            win_count += 1
                        else:
                            loss_count += 1
                        total_pnl += t['pnl_usd']

                print(f"\n  统计: 盈利{win_count}笔 亏损{loss_count}笔 净${total_pnl:+.2f}")
                print("="*140 + "\n")

            conn.close()
        except Exception as e:
            print(f"[ANALYSIS ERROR] {e}")
        """打印全面的交易分析（替代analyze_trades.py）"""
        print("[DEBUG] 开始执行交易分析...")
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            conn.execute('PRAGMA journal_mode=WAL;')
            cursor = conn.cursor()

            print("\n" + "=" * 100)
            print("[交易分析] Trading Performance Analysis")
            print("=" * 100)

            # 1. 最近20笔交易
            print("\n[1] 最近交易记录 (Last 20 Trades)")
            cursor.execute('''
                SELECT id, entry_time, side, entry_token_price, size, exit_token_price, exit_reason, pnl_usd, pnl_pct, merged_from
                FROM positions
                ORDER BY id DESC LIMIT 20
            ''')
            rows = cursor.fetchall()
            if rows:
                print(f"{'ID':<5} {'时间':<18} {'方向':<6} {'入场价':<8} {'数量':<8} {'出场价':<8} {'退出原因':<25} {'收益率':<10} {'合并':<6}")
                print("-" * 120)
                for row in rows:
                    id, ts, side, entry, size, exit_p, reason, pnl_usd, pnl_pct, merged_from = row
                    ts = ts[:16] if len(ts) > 16 else ts
                    reason = (reason or 'UNKNOWN')[:23]
                    pnl_str = f'{pnl_pct:+.1f}%' if pnl_pct is not None else 'N/A'
                    merge_str = '✓' if merged_from and merged_from > 0 else '-'
                    print(f"{id:<5} {ts:<18} {side:<6} {entry:<8.4f} {size:<8.1f} {exit_p or 0:<8.4f} {reason:<25} {pnl_str:<10} {merge_str:<6}")
            else:
                print("  无交易记录")

            # 2. 总体统计
            print("\n[2] 总体统计 (Overall Statistics)")
            cursor.execute('''
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
                    AVG(pnl_pct) as avg_pnl,
                    SUM(pnl_usd) as total_pnl
                FROM positions
                WHERE exit_reason IS NOT NULL
            ''')
            row = cursor.fetchone()
            if row and row[0] > 0:
                total, wins, avg_pnl, total_pnl = row
                win_rate = (wins / total * 100) if total > 0 else 0
                print(f"  总交易: {total}笔")
                print(f"  胜率: {win_rate:.1f}% ({wins}/{total})")
                print(f"  平均收益: {avg_pnl:+.2f}%")
                print(f"  总盈亏: {total_pnl:+.2f} USDC")
            else:
                print("  无已完成交易")

            # 3. 按方向统计
            print("\n[3] 按方向统计 (By Direction)")
            cursor.execute('''
                SELECT
                    side,
                    COUNT(*) as total,
                    SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
                    AVG(pnl_pct) as avg_pnl,
                    SUM(pnl_usd) as total_pnl
                FROM positions
                WHERE exit_reason IS NOT NULL
                GROUP BY side
            ''')
            rows = cursor.fetchall()
            if rows:
                print(f"{'方向':<8} {'交易':<8} {'盈利':<8} {'胜率':<10} {'平均收益':<12} {'总盈亏'}")
                print("-" * 70)
                for row in rows:
                    side, total, wins, avg_pnl, total_pnl = row
                    win_rate = (wins / total * 100) if total > 0 else 0
                    print(f"{side:<8} {total:<8} {wins:<8} {win_rate:<8.1f}% {avg_pnl:+.2f}% ({total_pnl:+.2f} USDC)")

            # 4. 按退出原因统计
            print("\n[4] 按退出原因统计 (By Exit Reason)")
            cursor.execute('''
                SELECT
                    exit_reason,
                    COUNT(*) as total,
                    AVG(pnl_pct) as avg_pnl,
                    SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins
                FROM positions
                WHERE exit_reason IS NOT NULL
                GROUP BY exit_reason
                ORDER BY total DESC
            ''')
            rows = cursor.fetchall()
            if rows:
                print(f"{'退出原因':<30} {'次数':<8} {'盈利':<8} {'胜率':<10} {'平均收益'}")
                print("-" * 80)
                for row in rows:
                    reason, total, wins, avg_pnl = row
                    reason = (reason or 'UNKNOWN')[:28]
                    win_rate = (wins / total * 100) if total > 0 else 0
                    print(f"{reason:<30} {total:<8} {wins:<8} {win_rate:<8.1f}% {avg_pnl:+.2f}%")

            # 5. 盈亏分布
            print("\n[5] 盈亏分布 (PnL Distribution)")
            cursor.execute('''
                SELECT
                    CASE
                        WHEN pnl_pct >= 20 THEN '>= +20%'
                        WHEN pnl_pct >= 10 THEN '+10% to +20%'
                        WHEN pnl_pct >= 0 THEN '0% to +10%'
                        WHEN pnl_pct >= -10 THEN '0% to -10%'
                        WHEN pnl_pct >= -20 THEN '-10% to -20%'
                        ELSE '< -20%'
                    END as pnl_range,
                    COUNT(*) as count,
                    AVG(pnl_pct) as avg_pnl
                FROM positions
                WHERE exit_reason IS NOT NULL
                GROUP BY pnl_range
                ORDER BY MIN(pnl_pct) DESC
            ''')
            rows = cursor.fetchall()
            if rows:
                print(f"{'盈亏区间':<15} {'次数':<8} {'平均收益'}")
                print("-" * 35)
                for row in rows:
                    pnl_range, count, avg_pnl = row
                    print(f"{pnl_range:<15} {count:<8} {avg_pnl:+.2f}%")

            # 6. 最近10笔表现
            print("\n[6] 最近表现 (Last 10 Trades)")
            cursor.execute('''
                SELECT entry_time, side, pnl_pct, exit_reason
                FROM positions
                WHERE exit_reason IS NOT NULL
                ORDER BY id DESC LIMIT 10
            ''')
            rows = cursor.fetchall()
            if rows:
                wins = sum(1 for _, _, pnl, _ in rows if pnl and pnl > 0)
                print(f"  最近10笔胜率: {wins}/10 ({wins*10}%)")
                print()
                print(f"{'时间':<18} {'方向':<8} {'收益率':<10} {'退出原因'}")
                print("-" * 60)
                for ts, side, pnl, reason in rows:
                    ts = ts[:16] if len(ts) > 16 else ts
                    pnl_str = f'{pnl:+.1f}%' if pnl else 'N/A'
                    reason = (reason or '')[:25]
                    print(f"{ts:<18} {side:<8} {pnl_str:<10} {reason}")

            # 7. 按信号强度统计（新增）
            print("\n[7] 按信号强度统计 (By Signal Strength)")
            cursor.execute('''
                SELECT
                    CASE
                        WHEN abs(score) >= 7.0 THEN '7.0+ (很强)'
                        WHEN abs(score) >= 5.0 THEN '5.0-6.9 (较强)'
                        WHEN abs(score) >= 4.0 THEN '4.0-4.9 (中等)'
                        WHEN abs(score) >= 3.0 THEN '3.0-3.9 (较弱)'
                        ELSE '< 3.0 (弱)'
                    END as score_range,
                    COUNT(*) as total,
                    SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
                    AVG(pnl_pct) as avg_pnl,
                    SUM(pnl_usd) as total_pnl
                FROM positions
                WHERE exit_reason IS NOT NULL AND score IS NOT NULL
                GROUP BY score_range
                ORDER BY MIN(abs(score)) DESC
            ''')
            rows = cursor.fetchall()
            if rows:
                print(f"{'信号强度':<15} {'交易数':<8} {'盈利':<8} {'胜率':<10} {'平均收益':<12} {'总盈亏'}")
                print("-" * 80)
                for row in rows:
                    score_range, total, wins, avg_pnl, total_pnl = row
                    win_rate = (wins / total * 100) if total > 0 else 0
                    print(f"{score_range:<15} {total:<8} {wins:<8} {win_rate:<8.1f}% {avg_pnl:+.2f}% ({total_pnl:+.2f} USDC)")
            else:
                print("  无数据（需要score字段）")

            conn.close()
            print("=" * 100 + "\n")

        except Exception as e:
            print(f"[ANALYSIS ERROR] {e}")

    def get_market_data(self) -> Optional[Dict]:
        try:
            now = int(time.time())
            aligned = (now // 900) * 900

            # 尝试当前窗口，如果过期则尝试下一个窗口
            for offset in [0, 900]:
                slug = f"btc-updown-15m-{aligned + offset}"

                # [ROCKET] 使用Session复用TCP连接（提速3-5倍）
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

    def calculate_defense_multiplier(self, current_price: float, oracle_score: float, score: float) -> float:
        """
         核心防御层 (Sentinel Dampening) - 灵感来自 @jtrevorchapman 的系统

        评估各项环境因子，返回仓位乘数 (1.0=全仓，0.0=一票否决)

        五大防御因子：
        1. 黄金6分钟法则 - session剩余时间
        2. 混沌过滤器 - 预言机报价反复穿越基准价格次数
        3. 利润空间防御 - 高价位压缩仓位
        4. CVD一致性检查 - Oracle与本地信号背离惩罚
        5. 距离基准价格风险 - 价格咬合度检查
        """
        from datetime import datetime
        now = datetime.now()
        current_session = now.minute // 15  # 划分 00, 15, 30, 45 的 Session

        # ========== 1. 重置混沌震荡计数器 ==========
        if current_session != self.last_session_id:
            self.session_cross_count = 0
            self.last_cross_state = None
            self.last_session_id = current_session
            print(f" [防御层] 新Session开始，混沌计数器重置")

        # ========== 2. 记录 0.50 基准线穿越 ==========
        current_state = 'UP' if current_price > 0.50 else 'DOWN'
        if self.last_cross_state and current_state != self.last_cross_state:
            self.session_cross_count += 1
            print(f"⚠ [混沌监测] 价格穿越基准线！当前Session穿越次数: {self.session_cross_count}")
        self.last_cross_state = current_state

        # ================= 开始计算防御系数 =================
        multiplier = 1.0
        defense_reasons = []

        # [ROCKET] 定义核弹级别（用于防御层穿透）
        is_nuke = abs(oracle_score) >= 6.0

        # ========== 因子A: 黄金时间窗口精细管理 (Time left to expiry) ==========
        # @jtrevorchapman 发现：session剩余6分钟后指标才开始可靠
        # 进一步优化：在3-6分钟窗口内细分仓位管理
        minutes_to_expiry = 15 - (now.minute % 15)

        if minutes_to_expiry > 6:
            if is_nuke:
                # [ROCKET] 核弹级巨鲸掀桌子，无视时间锁！
                print(f"[ROCKET] [防御穿透-A] 核弹级信号(Oracle={oracle_score:+.2f})！无视{minutes_to_expiry}分钟时间锁，全军出击！")
            else:
                print(f" [防御层-A] 拦截: 剩余{minutes_to_expiry}分钟(>6分钟)，处于无序震荡期")
                return 0.0

        # [精细仓位管理] 在黄金窗口内进一步细分
        elif minutes_to_expiry > 5:  # 5-6分钟
            multiplier *= 0.8  # 轻微压缩（刚进入窗口，信号尚不稳定）
            defense_reasons.append(f"早期窗口({minutes_to_expiry}分钟)")
            print(f" [防御层-A] 精细管理: {minutes_to_expiry}分钟剩余，仓位80%（刚进入窗口）")

        elif minutes_to_expiry < 2:  # < 2分钟（通常不会到达，因为can_trade已拦截）
            multiplier *= 0.5  # 大幅压缩（快到期，风险陡增）
            defense_reasons.append(f"晚期窗口({minutes_to_expiry}分钟)")
            print(f" [防御层-A] 精细管理: {minutes_to_expiry}分钟剩余，仓位50%（快到期）")

        else:  # 2-5分钟：最佳窗口，全仓执行
            print(f" [防御层-A] 黄金窗口: {minutes_to_expiry}分钟剩余，仓位100%（最佳时机）")

        # ========== 因子B: 混沌过滤器 + CVD否决权 ==========
        # 参考 @jtrevorchapman: "CVD是预测力最强的单一指标，在混沌市场甚至有投票否决权"
        # 反复穿越5次以上说明市场极度混乱，此时只有CVD强烈信号才能开仓
        if self.session_cross_count >= 5:
            if is_nuke:
                # 核弹级巨鲸掀桌子，无视混沌锁！
                print(f"[防御穿透-B] 核弹级信号(Oracle={oracle_score:+.2f})！无视{self.session_cross_count}次穿越混乱，强行突破！")
            else:
                # [CVD否决权] 混沌市场：检查CVD强度
                cvd_5m = oracle.get('cvd_5m', 0.0) if oracle else 0.0

                if abs(cvd_5m) >= 150000:  # CVD强烈信号（±15万）
                    if abs(oracle_score) >= 8.0:  # Oracle综合评分也支持
                        print(f"[CVD否决权-A] 市场混乱(session_cross_count={self.session_cross_count})但CVD极强({cvd_5m:+.0f})，强行开仓！")
                        # CVD否决权通过，继续评估其他因子
                    else:
                        print(f"[CVD否决权-B] 混乱市场且CVD强({cvd_5m:+.0f})但Oracle不够强({oracle_score:+.2f})，谨慎")
                        multiplier *= 0.3  # 大幅压缩仓位到30%
                        defense_reasons.append(f"混乱CVD强({cvd_5m:+.0f})")
                else:
                    print(f"[CVD否决权-C] 混乱市场(session_cross_count={self.session_cross_count})且CVD弱({cvd_5m:+.0f})，拒绝")
                    return 0.0
        elif self.session_cross_count >= 3:
            multiplier *= 0.5
            defense_reasons.append(f"混沌x{self.session_cross_count}")

        # ========== 因子C: 利润空间防御（基于175笔实盘数据优化）==========
        #  数据证明：入场价格≥0.50的胜率<5%，几乎全部MARKET_SETTLED
        # [TARGET] 黄金区间：0.28-0.43，胜率100%（在小样本中）

        if current_price >= 0.50:
            # [BLOCK] 死亡区间：0.50+几乎全部被套牢
            if abs(oracle_score) < 10.0:
                print(f" [防御层-C] 拦截: 入场价{current_price:.2f}处于死亡区间(≥0.50)，需Oracle≥10.0才可开单")
                return 0.0
            else:
                # 即使有极端核弹信号，也只给最小仓位
                multiplier *= 0.15  # 只给15%仓位
                defense_reasons.append(f"⚠死亡区间{current_price:.2f}(仅核弹)")

        elif current_price >= 0.45:
            #  高风险区间：胜率大幅下降
            multiplier *= 0.3  # 压缩到30%
            defense_reasons.append(f"高风险区{current_price:.2f}")

        elif current_price >= 0.43:
            #  中等风险区间：边界地带
            multiplier *= 0.7  # 轻微压缩
            defense_reasons.append(f"中风险区{current_price:.2f}")

        elif current_price < 0.28:
            #  过低区间：虽然便宜但说明市场一边倒
            if abs(oracle_score) < 5.0:
                print(f" [防御层-C] 拦截: 入场价{current_price:.2f}过低，市场一边倒，需Oracle≥5.0")
                return 0.0

        # ========== 因子D: CVD一致性检查（强化版）==========
        # [CVD强化] 参考 @jtrevorchapman: CVD是最强指标，背离时严厉惩罚
        # 如果Oracle（代表CVD方向）与本地信号背离，大幅压缩仓位
        if oracle_score * score < 0:
            multiplier *= 0.2  # 从0.5改为0.2（更严厉的惩罚）
            defense_reasons.append(f"CVD背离(本地{score:+.1f} vs Oracle{oracle_score:+.1f})")
            print(f"[CVD一致性] Oracle({oracle_score:+.1f})与本地({score:+.1f})背离，仓位压缩至20%")

        # ========== 因子E: 距离基准价格风险 ==========
        # 价格越接近0.50，翻转风险越大
        distance_from_baseline = abs(current_price - 0.50)
        if distance_from_baseline < 0.05:
            multiplier *= 0.6
            defense_reasons.append(f"接近基准({current_price:.2f})")
        elif distance_from_baseline < 0.10:
            multiplier *= 0.8
            defense_reasons.append(f"较近基准({current_price:.2f})")

        # 打印防御层决策
        if multiplier < 1.0:
            print(f" [防御层] 最终乘数: {multiplier:.2f} | 原因: {', '.join(defense_reasons)}")
        else:
            print(f" [防御层] 全仓通过 (乘数1.0)")

        return max(0.0, min(1.0, multiplier))

    def generate_signal(self, market: Dict, price: float, no_price: float = None) -> Optional[Dict]:
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
        # 低于0.20或高于0.80：风险收益比太差
        # 0.48~0.52：平衡区，信号不明确
        max_entry = CONFIG['signal'].get('max_entry_price', 0.80)
        min_entry = CONFIG['signal'].get('min_entry_price', 0.20)
        bal_min = CONFIG['signal']['balance_zone_min']
        bal_max = CONFIG['signal']['balance_zone_max']

        if price > max_entry:
            return None
        if price < min_entry:
            return None
        if bal_min <= price <= bal_max:
            return None

        # 获取NO价格，过滤市场一边倒情况
        # 优先用传入的实时no_price（V6 WebSocket），fallback到1-price推算
        try:
            _no_price = no_price if no_price and 0.01 <= no_price <= 0.99 else round(1.0 - price, 4)
            if price > 0.80:
                print(f"       [FILTER] YES价格 {price:.4f} > 0.80（市场过于看涨），跳过")
                return None
            if _no_price > 0.80:
                print(f"       [FILTER] NO价格 {_no_price:.4f} > 0.80（市场过于看跌），跳过")
                return None
        except:
            pass

        # 评分（ob_bias固定为0，orderbook_bias权重已禁用）
        score, components = self.scorer.calculate_score(price, rsi, vwap, price_hist)
        original_score = score  # 保存原始本地分

        # ==========================================
        # [ORACLE] 读取币安先知Oracle信号（移到Session Memory之前）
        # ==========================================
        # 理由：Session Memory需要oracle_score作为特征
        oracle = self._read_oracle_signal()
        oracle_score = 0.0
        ut_hull_trend = 'NEUTRAL'

        if oracle:
            oracle_score = oracle.get('signal_score', 0.0)
            ut_hull_trend = oracle.get('ut_hull_trend', 'NEUTRAL')

        print(f"       [ORACLE] 先知分:{oracle_score:+.2f} | 15m UT Bot:{ut_hull_trend}")

        # ==========================================
        # [MEMORY] Layer 1: Session Memory（先验偏差）
        # ==========================================
        # 在生成信号前，系统已经有了基于历史数据的"先验观点"
        prior_bias = 0.0
        if self.session_memory:
            try:
                market_features = {
                    'price': price,
                    'rsi': rsi,
                    'oracle_score': oracle_score,
                    'price_history': price_hist
                }

                current_features = self.session_memory.extract_session_features(market_features)
                prior_bias, memory_analysis = self.session_memory.calculate_prior_bias(current_features)

                # 每10次信号打印一次详细分析（避免日志刷屏）
                if self.stats.get('signal_count', 0) % 10 == 0:
                    self.session_memory.print_analysis(memory_analysis)
                elif abs(prior_bias) > 0.3:  # 强偏差时也打印
                    print(f" [MEM] 先验偏差: {prior_bias:+.2f} ({'倾向做多' if prior_bias > 0 else '倾向做空'})")

                # 应用先验偏差到本地分数（权重2.0，可调整）
                prior_adjustment = prior_bias * 2.0
                score += prior_adjustment

                if abs(prior_bias) > 0.2:
                    print(f"       [MEMORY应用] 先知偏差{prior_bias:+.2f} × 2.0 = {prior_adjustment:+.2f} → 本地分调整至{score:.2f}")

            except Exception as e:
                print(f"[WARN] Session Memory计算失败: {e}")

        # ==========================================
        # [VOTING] 投票系统（实验性替换原融合逻辑）
        # ==========================================
        if self.use_voting_system and self.voting_system:
            print(f"       [VOTING SYSTEM] 使用投票系统生成信号（9个规则 + 超短动量）")

            # 收集投票
            vote_result = self.voting_system.decide(
                min_confidence=0.60,
                min_votes=3,
                price=price,
                rsi=rsi,
                vwap=vwap,
                oracle_score=oracle_score,
                price_history=price_hist,
                oracle=oracle
            )

            if not vote_result or not vote_result.get('passed_gate', False):
                print(f"       [VOTE] 投票系统未产生明确信号")
                return None

            # 提取投票结果
            direction = vote_result['direction']
            confidence = vote_result['confidence']
            vote_details = vote_result
            score = 5.0 if direction == 'LONG' else -5.0  # 基准分（用于日志显示）

            print(f"\n       [VOTING RESULT] 最终方向: {direction} | 置信度: {confidence:.0%}")
            print(f"       [VOTE] 继续执行风控检查（RSI防呆、UT Bot趋势锁、防御层）...")

        else:
            # ==========================================
            #  原版Oracle融合逻辑（保留作为备份）
            # ==========================================
            print(f"       [ORACLE] 本地分:{score:.2f}")

            # [RELOAD] 恢复旧版Oracle融合：同向增强（权重20%），反向削弱（权重10%）
            if oracle and abs(oracle_score) > 0:
                if oracle_score * score > 0:
                    oracle_boost = oracle_score / 5.0   # 同向：最多±2
                    print(f"       [FUSION共振] 本地({score:+.2f})与Oracle同向，÷5: {oracle_score:+.2f} → {oracle_boost:+.2f}")
                else:
                    oracle_boost = oracle_score / 10.0  # 反向：最多±1，不轻易翻转本地判断
                    print(f"       [FUSION背离] 本地({score:+.2f})与Oracle反向，÷10: {oracle_score:+.2f} → {oracle_boost:+.2f}")
                score += oracle_boost
                score = round(max(-10, min(10, score)), 2)

            confidence = min(abs(score) / 5.0, 0.99)
            vote_details = None  # 原系统没有投票详情

        # 投票系统已经设置了 direction，原系统需要根据 score 计算
        if direction is None:
            direction = None
            min_long_score = CONFIG['signal']['min_long_score']
            min_short_score = CONFIG['signal']['min_short_score']

            # 常规做多信号
            if score >= min_long_score:
                direction = 'LONG'
            # 常规做空信号
            elif score <= min_short_score:
                direction = 'SHORT'

        if direction:
            # ==========================================
            #  极简风控：只保留基础RSI防呆
            # ==========================================
            # 彻底抛弃1H/15m UT Bot趋势锁，交由防御层裁决
            if direction == 'LONG' and rsi > 70:
                print(f"[BLOCK] [RSI防呆] 拒绝做多！RSI={rsi:.1f}>70（超买），追高风险！")
                return None
            elif direction == 'SHORT' and rsi < 30:
                print(f"[BLOCK] [RSI防呆] 拒绝做空！RSI={rsi:.1f}<30（超卖），反弹风险！")
                return None

            # ==========================================
            # [已禁用] UT Bot趋势过滤（因3-6分钟入场窗口太短，15m趋势过时）
            # 理由：
            #   1. 15m蜡烛图含11分钟历史（4分钟剩余入场时）
            #   2. 无法反映最近1-2分钟变化
            #   3. 超短动量（30s/60s/120s）已提供实时趋势
            #   4. CVD（3.0x权重）已是主导指标
            # ==========================================
            # if ut_hull_trend and ut_hull_trend != 'NEUTRAL':
            #     if direction == 'LONG' and ut_hull_trend == 'SHORT':
            #         print(f"[UT Bot趋势锁] 拒绝做多！15m趋势=SHORT与方向不符")
            #         return None
            #     elif direction == 'SHORT' and ut_hull_trend == 'LONG':
            #         print(f"[UT Bot趋势锁] 拒绝做空！15m趋势=LONG与方向不符")
            #         return None

            # [信息日志] 保留UT Bot趋势用于参考（但不作为过滤条件）
            if ut_hull_trend and ut_hull_trend != 'NEUTRAL':
                if direction == ut_hull_trend:
                    print(f" [UT Bot参考] 15m趋势={ut_hull_trend}，与方向一致")
                else:
                    print(f" [UT Bot参考] 15m趋势={ut_hull_trend}，与方向({direction})相反（已忽略）")
            else:
                print(f" [UT Bot参考] 15m趋势={ut_hull_trend}（不作为过滤条件）")

            # ==========================================
            #  智能防御层评估 (@jtrevorchapman 三层防御系统)
            # ==========================================
            # 防御层包含：时间锁、混沌过滤、利润空间、核弹穿透
            defense_multiplier = self.calculate_defense_multiplier(price, oracle_score, original_score)

            # 如果防御层返回0，直接拦截
            if defense_multiplier <= 0:
                print(f"[BLOCK] [防御层] 一票否决！信号被防御层拦截，放弃开单")
                return None

            # 所有风控通过，返回常规信号（带上防御层乘数）
            strategy_name = 'VOTING_SYSTEM' if vote_details else 'TREND_FOLLOWING'
            print(f" [{strategy_name}] {direction} 信号确认（15m趋势+防御层通过）")

            return {
                'direction': direction,
                'strategy': strategy_name,
                'score': score,
                'confidence': confidence,
                'rsi': rsi,
                'vwap': vwap,
                'price': price,
                'components': components,
                'oracle_score': oracle_score,
                'oracle_15m_trend': ut_hull_trend,
                'defense_multiplier': defense_multiplier,
                'vote_details': vote_details,  # 添加投票详情（原系统为None）
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

        # ==========================================
        #  仓位绝对锁定：禁止加仓/连续开单
        # ==========================================
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            conn.execute('PRAGMA journal_mode=WAL;')
            cursor = conn.cursor()

            # 检查是否有任何 open 状态的持仓（未过期市场）
            cutoff_time = (datetime.now() - timedelta(minutes=25)).strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute("""
                SELECT COUNT(*) FROM positions
                WHERE status = 'open' AND entry_time >= ?
            """, (cutoff_time,))

            open_positions_count = cursor.fetchone()[0]
            conn.close()

            if open_positions_count > 0:
                return False, f"[BLOCK] 仓位绝对锁定: 当前有 {open_positions_count} 个未平仓持仓，等待止盈止损，禁止重复开仓！"
        except Exception as e:
            print(f"       [POSITION LOCK CHECK ERROR] {e}")

        # ⏱ 【已禁用】5分钟全局冷却，使用弹匣微冷却（60秒）即可
        # 原因：仓位绝对锁定已经足够防止连续加仓，60秒微冷却防止同一市场疯狂交易
        # ==========================================
        # # 检查最后一次交易时间，强制冷却5分钟
        # if hasattr(self, 'stats') and 'last_trade_time' in self.stats:
        #     last_trade = self.stats['last_trade_time']
        #     if last_trade:
        #         time_passed = (datetime.now() - last_trade).total_seconds()
        #         cooldown_period = 300  # 5分钟 = 300秒
        #         if time_passed < cooldown_period:
        #             remaining = int(cooldown_period - time_passed)
        #             return False, f"⏱ [射击冷却] 刚交易完，强制冷却中... 剩余 {remaining} 秒"

        # 检查是否进入新的15分钟窗口（自动重置last_traded_market）
        if market and self.last_traded_market:
            current_slug = market.get('slug', '')
            if current_slug != self.last_traded_market:
                # 新的15分钟窗口，重置交易限制
                print(f"       [RESET] 新的15分钟窗口: {self.last_traded_market} → {current_slug}")
                self.last_traded_market = None

        # 【已解除】每个市场只交易一次的限制
        # 改为：通过弹匣限制、射击冷却、时间防火墙等精细风控来控制频率
        # if market and self.last_traded_market:
        #     current_slug = market.get('slug', '')
        #     if current_slug == self.last_traded_market:
        #         return False, f"已交易过该市场: {current_slug}"

        # --- 检查持仓冲突（双向检查：数据库 + 链上API）---
        #  加强版：同时检查数据库和链上持仓，防止并发订单绕过检查
        positions = self.get_positions()
        real_positions = self.get_real_positions()  # 查询链上实时持仓

        # 合并数据库和链上持仓
        all_long = positions.get('LONG', 0) + real_positions.get('LONG', 0)
        all_short = positions.get('SHORT', 0) + real_positions.get('SHORT', 0)

        if signal['direction'] == 'LONG' and all_short > 0:
            return False, f" [反向冲突] 已有 {all_short:.0f} 空头仓位，禁止同时做多！"
        if signal['direction'] == 'SHORT' and all_long > 0:
            return False, f" [反向冲突] 已有 {all_long:.0f} 多头仓位，禁止同时做空！"

        #  === 总持仓额度限制（防止多笔交易累计超仓）===
        # ⚠ 重要：只统计未过期市场的持仓（过期市场已结算，不应占用额度）
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            #  激活WAL模式
            conn.execute('PRAGMA journal_mode=WAL;')
            cursor = conn.cursor()

            #  查询未过期市场的持仓总价值（entry_time在最近25分钟内）
            # 15分钟市场通常在结束前2-3分钟有交易机会，所以25分钟是一个安全窗口
            cutoff_time = (datetime.now() - timedelta(minutes=25)).strftime('%Y-%m-%d %H:%M:%S')

            cursor.execute("""
                SELECT SUM(value_usdc)
                FROM positions
                WHERE status IN ('open', 'closing')
                  AND entry_time >= ?
            """, (cutoff_time,))

            total_exposure_row = cursor.fetchone()
            total_exposure = float(total_exposure_row[0]) if total_exposure_row and total_exposure_row[0] else 0.0

            # 获取当前余额（用于计算百分比）
            #  使用position_mgr中的余额（已通过Ankr API实时更新）
            current_balance = self.position_mgr.balance

            max_total_exposure = current_balance * CONFIG['risk']['max_total_exposure_pct']

            #  关键风控：未过期市场的总持仓不能超过max_total_exposure_pct（60%）
            if total_exposure >= max_total_exposure:
                conn.close()
                exposure_pct = (total_exposure / current_balance) * 100
                return False, f" 当前窗口持仓限制: 未过期市场持仓${total_exposure:.2f} ({exposure_pct:.1f}%)已达上限{CONFIG['risk']['max_total_exposure_pct']*100:.0f}%，拒绝开新仓"

            conn.close()
        except Exception as e:
            print(f"       [EXPOSURE CHECK ERROR] {e}")
            # 查询失败时为了安全，拒绝开仓
            return False, f"当前窗口持仓查询异常，拒绝交易: {e}"


        #  === 核心风控：同市场同向"弹匣限制"与"射击冷却" ===
        if market:
            token_ids = market.get('clobTokenIds', [])
            if isinstance(token_ids, str):
                import json
                token_ids = json.loads(token_ids)

            if token_ids:
                try:
                    conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
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

                    #  修复：60秒冷却查询最近1小时内的交易（不限当前窗口）
                    # 原bug：只查当前窗口导致跨窗口交易时冷却失效
                    cursor.execute("""
                        SELECT count(*), max(entry_time)
                        FROM positions
                        WHERE token_id = ? AND side = ?
                          AND entry_time >= datetime('now', '-1 hour')
                    """, (token_id, signal['direction']))

                    row = cursor.fetchone()
                    recent_count = row[0] if row else 0
                    last_entry_time_str = row[1] if row and row[1] else None

                    # 弹匣计数：当前窗口内的交易数（用于弹匣限制）
                    cursor.execute("""
                        SELECT count(*)
                        FROM positions
                        WHERE token_id = ? AND side = ?
                          AND entry_time >= ?
                    """, (token_id, signal['direction'], window_start_str))
                    window_count_row = cursor.fetchone()
                    open_count = window_count_row[0] if window_count_row else 0

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

                    if total_window_trades >= max_per_window:
                        conn.close()
                        return False, f"窗口限制: 本15分钟窗口已开{total_window_trades}单，最多{max_per_window}单"

                    #  禁止同时反向交易（不能同时持有多空）
                    #  修复：不限制token_id，检查所有市场的反向持仓
                    # 原因：市场切换后token_id会变，但反向持仓仍然是冲突
                    opposite_direction = 'SHORT' if signal['direction'] == 'LONG' else 'LONG'

                    cursor.execute("""
                        SELECT count(*) FROM positions
                        WHERE side = ? AND status = 'open'
                    """, (opposite_direction,))

                    opposite_row = cursor.fetchone()
                    opposite_count = opposite_row[0] if opposite_row else 0

                    if opposite_count > 0:
                        conn.close()
                        return False, f" 反向持仓冲突: 已有{opposite_direction}持仓({opposite_count}单)，禁止同时开{signal['direction']}"

                    # 弹匣限制：同一市场同一方向最多N发子弹
                    max_bullets = CONFIG['risk']['max_same_direction_bullets']
                    if open_count >= max_bullets:
                        conn.close()
                        return False, f"弹匣耗尽: {token_id[-8:]} {signal['direction']}已达最大持仓({max_bullets}单)"

                    # 射击冷却：距离上一单必须超过N秒
                    cooldown_sec = CONFIG['risk']['same_direction_cooldown_sec']
                    if last_entry_time_str:
                        last_entry_time = datetime.strptime(last_entry_time_str, '%Y-%m-%d %H:%M:%S')
                        seconds_since_last = (datetime.now() - last_entry_time).total_seconds()

                        if seconds_since_last < cooldown_sec:
                            remaining_sec = cooldown_sec - seconds_since_last
                            conn.close()
                            return False, f"⏳ 射击冷却中: 距离上一单仅{seconds_since_last:.0f}秒 (需>{cooldown_sec}s)"

                    #  === 反追空装甲三：同向点位防刷锁 ===
                    # 防止在亏损后，在同一价格区间反复开仓（报复性交易）
                    direction = signal['direction']
                    breaker = self.directional_circuit_breaker[direction]

                    # 获取当前价格和上次入场价格
                    current_price = signal.get('price', 0.5)
                    last_entry_price = breaker.get('last_entry_price')
                    last_loss_time = breaker.get('last_loss_time')

                    # 如果该方向最近有大亏损（10分钟内），检查价格防刷
                    if last_loss_time and last_entry_price:
                        time_since_loss = (datetime.now().timestamp() - last_loss_time)
                        if time_since_loss < 600:  # 10分钟内
                            price_diff_pct = abs(current_price - last_entry_price) / last_entry_price * 100
                            # 如果价格差距小于5%，说明在同一价位区间，禁止重复开仓
                            if price_diff_pct < 5:
                                conn.close()
                                return False, f" [点位防刷] 距离上次{direction}亏损仅{time_since_loss/60:.1f}分钟，价格区间{price_diff_pct:.1f}%<5%，禁止报复性开仓！"

                    # 所有风控检查通过，关闭连接
                    conn.close()

                except Exception as e:
                    print(f"       [RISK CHECK ERROR] {e}")
                    # 确保异常时也关闭连接
                    try:
                        conn.close()
                    except:
                        pass
                    return False, f"风控查询异常，拒绝交易: {e}"

        #  === 第一斧：时间防火墙（拒绝垃圾时间） ===
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
                return False, f" 时间防火墙: 无法解析市场时间({e})，拒绝开仓"

            if time_left is not None:
                if time_left < 0:
                    # 市场已过期，拒绝开仓
                    return False, f" 时间防火墙: 市场已过期({time_left:.0f}秒)，拒绝开仓"

                # [时间窗口] 参考 @jtrevorchapman: 只在剩余 3-6 分钟之间开仓
                # 早期指标不可靠，晚期风险太高
                if time_left > 360:
                    return False, f" [时间窗口] 指标尚未可靠，剩余{time_left:.0f}秒 > 6分钟，等待入场时机"

                if time_left < 180:
                    return False, f" 时间防火墙: 距离结算仅{time_left:.0f}秒 < 3分钟，拒绝开仓"
            else:
                return False, " 时间防火墙: 缺少市场结束时间，拒绝开仓"

        #  === 第二斧：拒绝极端价格（只做合理区间） ===
        # ⚠ 重要：收紧价格区间，避免垃圾赔率单
        # < 0.35: 胜率太低（<35%），波动风险极高，容易被扫损
        # > 0.85: 胜率太高（>85%），利润空间太小
        price = signal.get('price', 0.5)
        max_entry_price = 0.85  # 硬编码收紧上限（原0.80太宽松）
        min_entry_price = 0.35  # 硬编码收紧下限（原0.20太危险）

        if price > max_entry_price:
            return False, f"[BLOCK] [价格风控] 当前价格 {price:.2f} > {max_entry_price:.2f} (胜率>85%，利润空间太小)，放弃开仓！"
        if price < min_entry_price:
            return False, f"[BLOCK] [价格风控] 当前价格 {price:.2f} < {min_entry_price:.2f} (胜率<35%，波动风险极高)，放弃开仓！"

        # --- 检查是否允许做多/做空（动态调整）---
        if signal['direction'] == 'LONG' and not CONFIG['signal']['allow_long']:
            return False, "LONG disabled (low accuracy)"
        if signal['direction'] == 'SHORT' and not CONFIG['signal']['allow_short']:
            return False, "SHORT disabled (low accuracy)"

        #  === 反追空装甲一：单向连亏熔断器 ===
        direction = signal['direction']
        breaker = self.directional_circuit_breaker[direction]

        # 检查该方向是否在熔断冷却期
        current_time = datetime.now().timestamp()
        if current_time < breaker['timeout_until']:
            remaining_minutes = int((breaker['timeout_until'] - current_time) / 60)
            return False, f" [熔断器] {direction}方向冷却中（{remaining_minutes}分钟剩余），禁止追势！"

        # 检查是否触发熔断条件（连续3次同向大亏损）
        if breaker['consecutive_losses'] >= 3:
            breaker['timeout_until'] = current_time + 1800  # 锁定30分钟
            remaining_minutes = int((breaker['timeout_until'] - current_time) / 60)
            print(f" [系统级熔断] {direction}方向连续亏损{breaker['consecutive_losses']}次！触发30分钟冷静期！")
            return False, f" [熔断触发] {direction}方向已触发熔断，冷静{remaining_minutes}分钟"

        if self.is_paused:
            if self.pause_until and datetime.now() < self.pause_until:
                remaining = int((self.pause_until - datetime.now()).total_seconds() / 60)
                return False, f"Paused {remaining}m"
            else:
                self.is_paused = False
                self.pause_until = None
                self.stats['consecutive_losses'] = 0

        # 每日最大亏损检查 (⚠ 已临时禁用，测试巨鲸熔断功能)
        # max_loss = self.position_mgr.get_max_daily_loss()
        # if self.stats['daily_loss'] >= max_loss:
        #     # 检查是否是新的一天，如果是则重置
        #     if datetime.now().date() > self.last_reset_date:
        #         self.stats['daily_loss'] = 0.0
        #         self.stats['daily_trades'] = 0
        #         self.last_reset_date = datetime.now().date()
        #         print(f"       [RESET] 新的一天，每日亏损已重置")
        #     else:
        #         return False, f"Daily loss limit reached (${self.stats['daily_loss']:.2f}/${max_loss:.2f})"

        if self.stats['consecutive_losses'] >= CONFIG['risk']['stop_loss_consecutive']:
            self.is_paused = True
            self.pause_until = datetime.now() + timedelta(hours=CONFIG['risk']['pause_hours'])
            return False, f"3 losses - pause {CONFIG['risk']['pause_hours']}h"

        return True, "OK"

    def get_positions(self) -> Dict[str, float]:
        """查询当前持仓（从 positions 表）"""
        positions = {}  # {side: size}
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            #  激活WAL模式：多线程并发读写（防止database is locked）
            conn.execute('PRAGMA journal_mode=WAL;')
            cursor = conn.cursor()

            # 从 positions 表获取当前持仓
            #  修复：也包括'closing'状态的持仓（它们实际上还在持仓中）
            cursor.execute("""
                SELECT side, size
                FROM positions
                WHERE status IN ('open', 'closing')
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
            # [ROCKET] 使用Session复用TCP连接（提速持仓查询）
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
                    print(f"       [CANCEL]  订单已取消: {order_id[-8:]}")
                    return True
                else:
                    #  canceled=[] 时，查询订单状态确认（可能是已成交/已取消）
                    try:
                        order_info = self.client.get_order(order_id)
                        if order_info:
                            status = order_info.get('status', '').upper()
                            if status in ('FILLED', 'MATCHED', 'CANCELED', 'TRIGGERED'):
                                print(f"       [CANCEL] ℹ 订单已{status}，无需撤销: {order_id[-8:]}")
                                return True
                    except:
                        pass  # 查询失败，继续报错
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
                                print(f"       [ALLOWANCE]  余额和授权都足够")
                                return True
                            else:
                                # 尝试授权
                                print(f"       [ALLOWANCE] 授权中...")
                                self.update_allowance_fixed(AssetType.CONDITIONAL, token_id)
                                print(f"       [ALLOWANCE]  授权请求已发送，等待链上确认...")
                                # 等待授权在链上生效（增加等待时间）
                                import time
                                for auth_wait in range(10):
                                    time.sleep(1)
                                    try:
                                        result2 = self.client.get_balance_allowance(params)
                                        if result2:
                                            allowance2 = float(result2.get('allowance', 0))
                                            if allowance2 > 0:
                                                print(f"       [ALLOWANCE]  授权已生效: allowance={allowance2:.2f} (等待{auth_wait+1}秒)")
                                                break
                                        elif auth_wait < 9:
                                            print(f"       [ALLOWANCE] 等待授权生效... ({auth_wait+1}/10)")
                                    except:
                                        if auth_wait < 9:
                                            print(f"       [ALLOWANCE] 查询授权状态... ({auth_wait+1}/10)")
                                        time.sleep(1)
                                else:
                                    print(f"       [ALLOWANCE] ⚠  授权可能仍未生效，继续尝试挂单")
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
                            print(f"       [ALLOWANCE]  授权请求已发送，等待链上确认...")
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

            print(f"       [ALLOWANCE] [X] 等待超时，但仍尝试挂单")
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

            # --- 止盈计算 ---
            #  彻底解除 1U 封印，独立计算 30% 止盈
            tp_pct_max = CONFIG['risk'].get('take_profit_pct', 0.30)  
            tp_target_price = entry_price * (1 + tp_pct_max)          
            
            #  极限价格保护 + 精度控制（保留2位小数，最高不超过0.99）
            tp_target_price = round(min(tp_target_price, 0.99), 2)

            # --- 止损计算 ---
            #  彻底删除 1U 限制，默认 20% 触发（实盘防滑点）
            sl_pct_max = CONFIG['risk'].get('max_stop_loss_pct', 0.30)  
            sl_target_price = entry_price * (1 - sl_pct_max)  
            
            #  极限价格保护 + 精度控制（保留2位小数，最低不低于0.01）
            sl_target_price = round(max(sl_target_price, 0.01), 2)

            # --- 计算实际止盈止损百分比 ---
            actual_tp_pct = (tp_target_price - entry_price) / entry_price
            actual_sl_pct = (entry_price - sl_target_price) / entry_price

            # --- 打印完美日志 ---
            print(f"       [STOP ORDERS] entry={entry_price:.4f}, size={size}, value={value_usdc:.4f}")
            print(f"       [STOP ORDERS] tp={tp_target_price:.2f} (止盈{actual_tp_pct:.1%}), sl={sl_target_price:.2f} (止损{actual_sl_pct:.1%})")

            # 确保价格在 Polymarket 有效范围内，精度对齐 tick_size
            # 从市场数据获取 tick_size（默认 0.01）
            tick_size = float(market.get('orderPriceMinTickSize') or 0.01)

            def align_price(p: float) -> float:
                """对齐到 tick_size 精度，并限制在 tick_size ~ 1-tick_size"""
                p = round(round(p / tick_size) * tick_size, 4)
                return max(tick_size, min(1 - tick_size, p))

            tp_target_price = align_price(tp_target_price)
            sl_target_price = align_price(sl_target_price)

            # 注意：此处不做tp/sl方向校验，因为actual_entry_price还未确认
            # 校验在获取实际成交价并重算之后进行

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
                                print(f"       [STOP ORDERS]  入场订单已成交 ({status})")
                                print(f"       [STOP ORDERS] ⏳ 等待 10 秒，确保 Token 到达钱包...")
                                time.sleep(10)
                                # 获取实际成交价：优先avgPrice，fallback到entry_price
                                # 不用matchAmount/matchedSize，单位不确定容易算错
                                avg_price = entry_order.get('avgPrice')
                                if avg_price:
                                    try:
                                        parsed = float(avg_price)
                                        # 合理性校验：必须在0.01~0.99之间，且与entry_price偏差不超过30%
                                        if 0.01 <= parsed <= 0.99 and abs(parsed - entry_price) / entry_price < 0.20:
                                            actual_entry_price = parsed
                                            print(f"       [STOP ORDERS] 实际成交价(avgPrice): {actual_entry_price:.4f} (调整价格: {entry_price:.4f})")
                                        else:
                                            print(f"       [STOP ORDERS] avgPrice={parsed:.4f} 不合理，使用调整价格: {entry_price:.4f}")
                                    except:
                                        pass
                                # 基于最终确认的actual_entry_price统一重算止盈止损（对称30%逻辑）
                                value_usdc = size * actual_entry_price
                                tp_pct_max = CONFIG['risk'].get('take_profit_pct', 0.30)  # 修复：止盈应使用take_profit_pct
                                tp_by_pct = actual_entry_price * (1 + tp_pct_max)
                                tp_by_fixed = (value_usdc + 1.0) / max(size, 1)
                                tp_target_price = min(tp_by_fixed, tp_by_pct)
                                sl_pct_max = CONFIG['risk'].get('max_stop_loss_pct', 0.30)
                                sl_by_pct = actual_entry_price * (1 - sl_pct_max)
                                sl_original = (value_usdc - 1.0) / max(size, 1)
                                sl_target_price = max(sl_original, sl_by_pct)
                                tp_target_price = align_price(tp_target_price)
                                sl_target_price = align_price(sl_target_price)
                                print(f"       [STOP ORDERS] 止盈止损确认: entry={actual_entry_price:.4f}, tp={tp_target_price:.4f}, sl={sl_target_price:.4f}")
                                # 校验tp/sl方向（基于实际成交价）
                                if tp_target_price <= actual_entry_price or sl_target_price >= actual_entry_price:
                                    print(f"       [STOP ORDERS] ⚠ tp/sl方向异常，强制修正: tp={tp_target_price:.4f} sl={sl_target_price:.4f} entry={actual_entry_price:.4f}")
                                    tp_target_price = align_price(min(actual_entry_price * 1.20, actual_entry_price + 1.0 / max(size, 1)))
                                    sl_target_price = align_price(max(actual_entry_price * 0.80, actual_entry_price - 1.0 / max(size, 1)))
                                    print(f"       [STOP ORDERS] 修正后: tp={tp_target_price:.4f}, sl={sl_target_price:.4f}")
                                break
                            elif status in ['CANCELLED', 'EXPIRED']:
                                print(f"       [STOP ORDERS] [X] 入场订单已{status}，取消挂止盈止损单")
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
                    print(f"       [STOP ORDERS] ⚠  等待超时，进行最后检查...")
                    try:
                        entry_order = self.client.get_order(entry_order_id)
                        if entry_order and entry_order.get('status') in ['FILLED', 'MATCHED']:
                            print(f"       [STOP ORDERS]  最后检查发现订单已成交！")
                            status = entry_order.get('status')
                            filled_price = entry_order.get('price')
                            if filled_price:
                                actual_entry_price = float(filled_price)
                                print(f"       [STOP ORDERS] 实际成交价: {actual_entry_price:.4f} (调整价格: {entry_price:.4f})")
                                if abs(actual_entry_price - entry_price) > 0.001:
                                    value_usdc = size * actual_entry_price
                                    # 对称30%止盈止损
                                    tp_pct_max = CONFIG['risk'].get('take_profit_pct', 0.30)  # 修复：止盈应使用take_profit_pct
                                    tp_by_pct = actual_entry_price * (1 + tp_pct_max)
                                    tp_by_fixed = (value_usdc + 1.0) / max(size, 1)
                                    tp_target_price = min(tp_by_fixed, tp_by_pct)
                                    sl_pct_max = CONFIG['risk'].get('max_stop_loss_pct', 0.30)
                                    sl_by_pct = actual_entry_price * (1 - sl_pct_max)
                                    sl_original = (value_usdc - 1.0) / max(size, 1)
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
                                    print(f"       [STOP ORDERS]  撤单成功，安全放弃该笔交易")
                                    cancel_success = True
                                else:
                                    print(f"       [STOP ORDERS] ⚠  撤单请求返回失败，订单可能仍在")
                            except Exception as cancel_err:
                                print(f"       [STOP ORDERS] [X] 撤单异常: {cancel_err}")

                            # 【核心防御】撤单失败 = 订单可能还在 = 强制监控！
                            if not cancel_success:
                                print(f"       [STOP ORDERS]  无法确认订单状态，强制移交本地双向监控！")
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

                                    # 对称30%止盈止损
                                    tp_pct_max = CONFIG['risk'].get('take_profit_pct', 0.30)  # 修复：止盈应使用take_profit_pct
                                    tp_by_pct = entry_price * (1 + tp_pct_max)
                                    tp_by_fixed = (value_usdc + 1.0) / max(size, 1)
                                    tp_target_price = align_price_local(min(tp_by_fixed, tp_by_pct))
                                    sl_pct_max = CONFIG['risk'].get('max_stop_loss_pct', 0.30)
                                    sl_by_pct = entry_price * (1 - sl_pct_max)
                                    sl_original = (value_usdc - 1.0) / max(size, 1)
                                    sl_target_price = align_price_local(max(sl_original, sl_by_pct))
                                    actual_entry_price = entry_price
                                    print(f"       [STOP ORDERS]   强制监控: entry={entry_price:.4f}, tp={tp_target_price:.4f}, sl={sl_target_price:.4f}")
                                    # 返回None作为tp_order_id（止盈单需后续挂），但返回其他参数强制监控
                                    return None, sl_target_price, actual_entry_price
                                else:
                                    print(f"       [STOP ORDERS] [X] 无法获取价格信息，但为安全起见仍强制监控")
                                    # 即使没有价格信息，也返回原值强制监控
                                    return None, None, entry_price
                            else:
                                # 撤单成功，真的没成交，安全放弃
                                return None, None, None
                        else:
                            print(f"       [STOP ORDERS] [X] 订单状态: {entry_order.get('status', 'UNKNOWN')}，放弃")
                            return None, None, None
                    except Exception as e:
                        print(f"       [STOP ORDERS] [X] 最后检查失败: {e}")
                        return None, None, None

            # 确认token授权
            # 检查token授权
            print(f"       [STOP ORDERS] 检查token授权...")
            self.ensure_allowance(token_id, expected_size=stop_size)

            # ==========================================
            # [ROCKET] 强制止盈挂单（带动态退避与重试机制）
            # ==========================================
            print(f"       [STOP ORDERS] ⏳ 开始挂止盈单前的强制冷却 (等待 5 秒让Polygon同步余额)...")
            time.sleep(5)  # 【核心防御】：首次挂单前必须硬等待！防止 Polymarket 后端缓存你的0余额状态

            # 组装止盈单参数 (注意：无论是做多还是做空，平仓永远是 SELL 你手里的 Token)
            from py_clob_client.clob_types import OrderArgs

            tp_order_args = OrderArgs(
                token_id=token_id,
                price=tp_target_price,  # 这里的 tp_target_price 必须是你之前修改过的绝对价格
                size=stop_size,
                side='SELL'
            )

            max_retries = 6  # 增加重试次数，确保万无一失
            tp_order_id = None

            for attempt in range(1, max_retries + 1):
                print(f"       [STOP ORDERS] [TARGET] 尝试挂载限价止盈单 ({attempt}/{max_retries})... 目标价: {tp_target_price:.4f}")
                try:
                    # 向盘口发送限价挂单
                    tp_response = self.client.create_and_post_order(tp_order_args)

                    if tp_response and 'orderID' in tp_response:
                        tp_order_id = tp_response['orderID']
                        print(f"       [STOP ORDERS]  止盈挂单成功！订单已经躺在盘口等待暴涨。ID: {tp_order_id[-8:]}")
                        break  # 挂单成功，立刻跳出循环
                    else:
                        print(f"       [STOP ORDERS] ⚠  挂单未报错但未返回订单ID: {tp_response}")
                        time.sleep(2)

                except Exception as e:
                    error_msg = str(e).lower()
                    if 'balance' in error_msg or 'allowance' in error_msg:
                        wait_time = attempt * 3
                        print(f"       [STOP ORDERS] [RELOAD] 链上余额未同步，等待 {wait_time} 秒后重试...")
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
                                        side='SELL'
                                    )
                                    print(f"       [STOP ORDERS] [RELOAD] 更新余额: {stop_size}")
                        except Exception:
                            pass
                    else:
                        print(f"       [STOP ORDERS] [X] 挂单发生未知异常: {e}")
                        time.sleep(3)

            # 兜底机制：如果 6 次（总计等了约 1 分钟）还是没挂上去
            if not tp_order_id:
                print(f"       [STOP ORDERS]  止盈单挂载彻底失败！已无缝移交【本地双向监控】系统兜底。")

            # 止损不挂单，由本地轮询监控（策略一：只挂止盈Maker，止损用Taker）
            # sl_target_price 保存到数据库供轮询使用
            sl_order_id = None

            if tp_order_id:
                print(f"       [STOP ORDERS]  止盈单已挂 @ {tp_target_price:.4f}，止损线 @ {sl_target_price:.4f} 由本地监控")
            else:
                print(f"       [STOP ORDERS] [X] 止盈单挂单失败，将使用本地监控双向平仓")

            return tp_order_id, sl_target_price, actual_entry_price

        except Exception as e:
            print(f"       [STOP ORDERS ERROR] {e}")
            import traceback
            print(f"       [TRACEBACK] {traceback.format_exc()}")
            return None, None, entry_price

    def close_position(self, market: Dict, side: str, size: float, is_stop_loss: bool = False, entry_price: float = None, sl_price: float = None):
        """平仓函数

        Args:
            market: 市场数据
            side: LONG/SHORT
            size: 平仓数量
            is_stop_loss: 是否是止损调用（止损时直接市价，不防插针）
            entry_price: 入场价格（止损时需要，用于设置最低可接受价格）
            sl_price: 真实止损价（优先用于极端暴跌判断，替代 entry_price * 0.70）
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
            opposite_side = 'SELL'  # 平仓永远是SELL

            # 获取outcomePrices用于计算平仓价格
            outcome_prices = market.get('outcomePrices', [])
            if isinstance(outcome_prices, str):
                outcome_prices = json.loads(outcome_prices)

            # ==========  智能防插针止损保护 ==========
            # 获取公允价格（token_price）和实际买一价（best_bid），优先用WebSocket实时价
            best_bid = self.get_order_book(token_id, side='BUY')
            if best_bid and best_bid > 0.01:
                token_price = best_bid  # WebSocket实时价作为公允价
            else:
                # fallback到outcomePrices
                if side == 'LONG':
                    token_price = float(outcome_prices[0]) if outcome_prices and len(outcome_prices) > 0 else 0.5
                else:
                    token_price = float(outcome_prices[1]) if outcome_prices and len(outcome_prices) > 1 else 0.5
                best_bid = token_price

            #  防插针核心逻辑：最多允许折价5%，拒绝恶意接针
            min_acceptable_price = token_price * 0.95  # 公允价的95%作为底线

            #  止损场景：智能止损保护
            if is_stop_loss:
                # 检查entry_price是否提供
                if entry_price is None:
                    # 未提供entry_price，回退到原始市价逻辑
                    if best_bid and best_bid > 0.01:
                        close_price = best_bid
                    else:
                        close_price = token_price
                    use_limit_order = False
                    print(f"       [止损模式] ⚠ 无entry_price，市价砸单 @ {close_price:.4f}")
                else:
                    #  断臂求生：极端暴跌时放弃博反弹幻想，直接市价砸盘
                    # Polymarket 15分钟期权市场：价格=概率，暴跌=基本面变化，不会反弹
                    # 即使只能拿回10-30%本金，也比100%归零强！

                    # 计算止损线：优先用真实止损价，否则用入场价70%
                    sl_line = sl_price if sl_price else (entry_price * 0.70 if entry_price else 0.30)

                    if best_bid and best_bid > 0.01:
                        #  极端暴跌检测：best_bid已经远低于止损线
                        if best_bid < sl_line * 0.50:  # 低于止损线50%
                            print(f"       [断臂求生]  极端暴跌！best_bid({best_bid:.4f}) << 止损线({sl_line:.4f})")
                            print(f"       [断臂求生]  放弃博反弹幻想！执行断臂求生，市价砸盘！")
                            # 即使只能拿回10%本金，也比归零强
                            close_price = max(0.01, best_bid - 0.05)
                            use_limit_order = False
                            print(f"       [断臂求生]  砸盘价 @ {close_price:.4f} (能抢回多少是多少)")
                        elif best_bid < sl_line:
                            # best_bid低于止损线，但不是极端情况
                            close_price = max(0.01, best_bid - 0.05)
                            use_limit_order = False
                            print(f"       [止损模式]  best_bid低于止损线({best_bid:.4f}<{sl_line:.4f})，砸盘价 @ {close_price:.4f}")
                        else:
                            # best_bid正常，直接市价成交
                            close_price = best_bid
                            use_limit_order = False
                            print(f"       [止损模式]  市价砸单 @ {close_price:.4f} (止损线{sl_line:.4f})")
                    else:
                        # 无法获取best_bid，用入场价70%保守砸盘
                        close_price = max(0.01, entry_price * 0.70)
                        use_limit_order = False
                        print(f"       [止损模式]  无best_bid，保守砸盘价 @ {close_price:.4f}")

                # ========== 核心修复：止损前撤销所有挂单释放冻结余额 ==========
                print(f"       [LOCAL SL]  正在紧急撤销该Token的所有挂单，释放被冻结的余额...")
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
                    print(f"       [LOCAL SL] [UNLOCK] 余额释放成功，当前真实可用余额: {actual_balance:.2f} 份")
                    if actual_balance <= 0:
                        print(f"       [LOCAL SL] ⚠ 撤单后余额依然为0，确认已无持仓。")
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
                # ⚠ 买一价太黑（流动性断层）！限价单等待
                close_price = min_acceptable_price
                use_limit_order = True
                print(f"       [防插针] ⚠ 买一价({best_bid if best_bid else 0:.4f})远低于公允价({token_price:.4f})，改挂限价单 @ {close_price:.4f}")

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
            #  精准识别"余额不足"，并返回特殊标记
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
            # [ROCKET] 使用Session复用TCP连接（提速3-5倍）
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
            # [ROCKET] 使用Session复用TCP连接（提速订单簿查询）
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
                #  优先使用WebSocket实时价格（V6模式下是毫秒级数据）
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

            #  === 防弹衣：智能滑点保护（击破250ms做市商撤单）===
            # Polymarket有250ms延迟，做市商可在期间撤单。我们需要设定价格上限防止高位接盘
            MAX_SLIPPAGE_ABSOLUTE = 0.03  # 绝对滑点上限：3美分
            MAX_SAFE_ENTRY_PRICE = 0.70   # 安全入场价上限：超过70¢盈亏比太差

            # 基础滑点：2个tick（确保成交）
            slippage_ticks = 2
            adjusted_price = align_price(base_price + tick_size_float * slippage_ticks)

            #  关键：计算实际滑点并限制在3美分以内
            actual_slippage = adjusted_price - base_price
            if actual_slippage > MAX_SLIPPAGE_ABSOLUTE:
                # 滑点超过3美分，强制限制
                adjusted_price = align_price(base_price + MAX_SLIPPAGE_ABSOLUTE)
                print(f"       [ 防弹衣] 原滑点{actual_slippage:.3f}超过3¢，强制限制到3¢")

            #  极限保护：即使加上滑点，价格也不能超过70¢
            if adjusted_price > MAX_SAFE_ENTRY_PRICE:
                print(f"       [ 流动性保护] 算上滑点后成本达{adjusted_price:.2f}，盈亏比极差，拒绝抢跑！")
                return None

            # 二次检查：遵守配置文件的价格限制
            max_entry_price = CONFIG['signal'].get('max_entry_price', 0.80)
            min_entry_price = CONFIG['signal'].get('min_entry_price', 0.20)
            if adjusted_price > max_entry_price:
                print(f"       [RISK] ⚠ 调整后价格超限: {adjusted_price:.4f} > {max_entry_price:.2f}，拒绝开仓")
                return None
            if adjusted_price < min_entry_price:
                print(f"       [RISK] ⚠ 调整后价格过低: {adjusted_price:.4f} < {min_entry_price:.2f}，拒绝开仓")
                return None

            print(f"       [ 防弹衣] 盘口{base_price:.4f} → 设定吃单极限价{adjusted_price:.4f} (最高容忍{actual_slippage:.3f}滑点)")

            # Calculate based on REAL balance（每次开仓前刷新链上余额）
            fresh_usdc, _ = self.balance_detector.fetch()
            if fresh_usdc <= 0:
                print(f"       [RISK] 余额查询失败或余额为0，拒绝开仓（安全保护）")
                return None
            self.position_mgr.balance = fresh_usdc

            # [TARGET] 智能动态仓位：根据信号强度自动调整（15%-30%）
            base_position_value = self.position_mgr.calculate_position(signal['confidence'], signal['score'])

            #  应用防御层乘数 (@jtrevorchapman 三层防御系统)
            defense_multiplier = signal.get('defense_multiplier', 1.0)
            position_value = base_position_value * defense_multiplier

            if defense_multiplier < 1.0:
                print(f"       [防御层] 基础仓位${base_position_value:.2f} × {defense_multiplier:.2f} = ${position_value:.2f}")

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
            err_msg = str(e)
            print(f"       [ERROR] {e}")
            print(f"       [TRACEBACK] {traceback.format_exc()}")

            #  严重Bug修复：订单可能已成交但异常被捕获
            # 检查是否有 orderID，如果有则尝试查询订单状态
            if 'response' in locals() and response and isinstance(response, dict):
                order_id = response.get('orderID')
                if order_id:
                    print(f"       [RECOVERY] 检测到订单ID {order_id[-8:]}，尝试查询状态...")
                    try:
                        # 延迟1秒让订单上链
                        import time
                        time.sleep(1)

                        order_info = self.client.get_order(order_id)
                        if order_info:
                            status = order_info.get('status', '').upper()
                            print(f"       [RECOVERY] 订单状态: {status}")

                            # 如果订单已成交或部分成交，仍然返回订单信息（确保记录到数据库）
                            if status in ('FILLED', 'MATCHED'):
                                print(f"       [RECOVERY]  订单已成交！强制返回订单信息（即使有异常）")
                                return {'order_id': order_id, 'status': 'filled', 'value': position_value, 'price': adjusted_price, 'token_price': base_price, 'size': float(size)}
                            elif status == 'LIVE':
                                print(f"       [RECOVERY] ⚠  订单挂单中（LIVE），可能已成交")
                                # LIVE 状态也可能是已成交，保守处理，返回订单信息
                                return {'order_id': order_id, 'status': 'live', 'value': position_value, 'price': adjusted_price, 'token_price': base_price, 'size': float(size)}
                    except Exception as recovery_err:
                        print(f"       [RECOVERY] 查询订单失败: {recovery_err}")

            # 如果无法确认订单状态，返回 None
            return None

    def record_trade(self, market: Dict, signal: Dict, order_result: Optional[Dict], was_blocked: bool = False, merged_from: int = 0):
        try:
            #  防止数据库锁定：设置timeout和check_same_thread
            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            #  激活WAL模式：多线程并发读写（防止database is locked）
            conn.execute('PRAGMA journal_mode=WAL;')
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

                    #  反追空装甲：记录开仓价格（用于点位防刷锁）
                    direction = signal['direction']
                    entry_price = float(signal['price'])
                    self.directional_circuit_breaker[direction]['last_entry_price'] = entry_price
                    print(f"       [ 熔断器] 记录{direction}开仓价格: {entry_price:.4f}")

                # 记录持仓到positions表（使用实际下单价格，同时挂止盈止损单）
                actual_price = order_result.get('price', signal['price'])
                token_price = order_result.get('token_price', actual_price)  # 真实token价格

                # 固定0.5U止盈止损
                tp_usd = 0.5
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
                    print(f"       [POSITION] ⚠  订单状态不明，验证持仓...")
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
                            balance_shares = balance / 1e6  # 转换为份数
                            print(f"       [POSITION] Token余额: {balance_shares:.2f}份 (需要: {position_size:.0f})")
                            if balance_shares < position_size * 0.5:  # 余额不足一半，说明未成交
                                print(f"       [POSITION] [X] 确认未成交，放弃记录持仓")
                                self.safe_commit(conn)
                                conn.close()
                                return
                            else:
                                #  严重Bug修复：余额充足，说明订单已成交！
                                # 即使止盈止损单没挂上，也要记录到positions表
                                print(f"       [POSITION]  确认已成交！止盈止损单失败，但必须记录持仓")
                                # 继续执行后续的positions记录逻辑
                                pass
                    except Exception as verify_err:
                        print(f"       [POSITION] ⚠  无法验证余额: {verify_err}")
                        print(f"       [POSITION]   保守处理：假设已成交，记录持仓")
                        # 继续执行，确保不会漏记录持仓
                elif tp_order_id is None and sl_target_price is None and actual_entry_price is None:
                    print(f"       [POSITION] [X] 入场单未成交，放弃记录持仓")
                    self.safe_commit(conn)
                    conn.close()
                    return

                # 初始化position_value
                position_value = position_size * actual_price

                # 使用实际成交价格（如果获取到了的话）
                if actual_entry_price and abs(actual_entry_price - actual_price) > 0.0001:
                    print(f"       [POSITION] 使用实际成交价格: {actual_entry_price:.4f} (调整价格: {actual_price:.4f})")
                    actual_price = actual_entry_price
                    # 重新计算value
                    position_value = position_size * actual_price

                # 计算止盈止损百分比（用于数据库记录）
                # 直接使用 place_stop_orders 已返回的 sl_target_price，避免二次计算不一致
                tick_size = float(market.get('orderPriceMinTickSize') or 0.01)
                def align_price(p: float) -> float:
                    p = round(round(p / tick_size) * tick_size, 4)
                    return max(tick_size, min(1 - tick_size, p))

                real_value = position_size * actual_price
                # 止盈：与 place_stop_orders 保持相同公式
                tp_pct_max = CONFIG['risk'].get('take_profit_pct', 0.30)
                tp_by_pct = actual_price * (1 + tp_pct_max)
                tp_by_fixed = (real_value + 1.0) / max(position_size, 1)
                tp_target_price = align_price(min(tp_by_fixed, tp_by_pct))
                # 止损：直接使用 place_stop_orders 返回的价格，sl_target_price 为 None 时才兜底计算
                if sl_target_price is None:
                    sl_pct_max = CONFIG['risk'].get('max_stop_loss_pct', 0.30)
                    sl_by_pct = actual_price * (1 - sl_pct_max)
                    sl_by_fixed = (real_value - 1.0) / max(position_size, 1)
                    sl_target_price = align_price(max(sl_by_fixed, sl_by_pct))

                tp_pct = round((tp_target_price - actual_price) / actual_price, 4) if actual_price > 0 else None
                sl_pct = round((actual_price - float(sl_target_price)) / actual_price, 4) if actual_price > 0 and sl_target_price else None

                # 发送开仓Telegram通知
                if self.telegram.enabled:
                    try:
                        # 使用place_stop_orders内部计算的实际止盈止损价格（基于实际成交价）
                        tick_size = float(market.get('orderPriceMinTickSize') or 0.01)
                        def align_price(p: float) -> float:
                            p = round(round(p / tick_size) * tick_size, 4)
                            return max(tick_size, min(1 - tick_size, p))

                        # 基于实际成交价格计算止盈止损（对称30%逻辑）
                        tp_pct_max = CONFIG['risk'].get('take_profit_pct', 0.30)  # 修复：止盈应使用take_profit_pct
                        tp_by_pct = actual_price * (1 + tp_pct_max)
                        tp_by_fixed = (position_value + 1.0) / max(position_size, 1)
                        tp_price = align_price(min(tp_by_fixed, tp_by_pct))
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
                        print(f"       [TELEGRAM]  开仓通知已发送")
                    except Exception as tg_error:
                        print(f"       [TELEGRAM ERROR] 发送开仓通知失败: {tg_error}")

                #  从 market 中获取 token_id（修复：确保 token_id 在所有路径中都定义）
                token_ids = market.get('clobTokenIds', [])
                if isinstance(token_ids, str):
                    import json
                    token_ids = json.loads(token_ids)
                if token_ids and len(token_ids) >= 2:
                    token_id = str(token_ids[0] if signal['direction'] == 'LONG' else token_ids[1])
                else:
                    # 如果获取失败，使用默认值（这种情况不应该发生）
                    print(f"       [WARN] 无法从market获取token_id，使用默认值")
                    token_id = 'BTC_15M_YES' if signal['direction'] == 'LONG' else 'BTC_15M_NO'

                cursor.execute("""
                    INSERT INTO positions (
                        entry_time, side, entry_token_price,
                        size, value_usdc, take_profit_usd, stop_loss_usd,
                        take_profit_pct, stop_loss_pct,
                        take_profit_order_id, stop_loss_order_id, token_id, status,
                        score, oracle_score, oracle_1h_trend, oracle_15m_trend,
                        merged_from, strategy, highest_price
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    # ⚠ 此字段存的是止损价格字符串，不是订单ID！用于本地轮询止损
                    #  修复：sl_target_price为None时用入场价兜底计算，确保止损线永远存在
                    str(sl_target_price) if sl_target_price else str(round(max(0.01, actual_price * (1 - CONFIG['risk'].get('max_stop_loss_pct', 0.30))), 4)),
                    token_id,
                    'open',
                    signal['score'],  #  保存信号评分（本地融合分数）
                    signal.get('oracle_score', 0.0),  #  保存Oracle先知分
                    signal.get('oracle_1h_trend', 'NEUTRAL'),  #  保存1H趋势
                    signal.get('oracle_15m_trend', 'NEUTRAL'),  #  保存15m趋势
                    merged_from,  #  标记是否是合并交易（0=独立，>0=被合并的持仓ID）
                    signal.get('strategy', 'TREND_FOLLOWING'),  # [TARGET] 标记策略类型
                    actual_price  # [ROCKET] 吸星大法：初始化历史最高价为入场价
                ))
                print(f"       [POSITION] 记录持仓: {signal['direction']} {position_value:.2f} USDC @ {actual_price:.4f}")

                # 根据止盈止损单状态显示不同信息
                if tp_order_id:
                    sl_status = "已禁用" if not CONFIG['risk'].get('enable_stop_loss', False) else "本地监控"
                    print(f"       [POSITION]  止盈单已挂 @ {tp_target_price:.4f}，止损线 @ {sl_target_price:.4f} ({sl_status})")
                else:
                    print(f"       [POSITION] ⚠  止盈单挂单失败，将使用本地监控双向平仓")

            self.safe_commit(conn)
            conn.close()

        except Exception as e:
            print(f"       [DB ERROR] {e}")

    def merge_position_existing(self, market: Dict, signal: Dict, new_order_result: Dict):
        """合并新订单到已有持仓（解决连续开仓导致止盈止损混乱）

        返回：(是否合并, 被合并持仓ID)
        """
        """合并新订单到已有持仓（解决连续开仓导致止盈止损混乱）

        逻辑：
        1. 查找同方向OPEN持仓
        2.  检查弹匣限制（防止无限合并）
        3. 取消旧止盈止损单
        4. 合并持仓（加权平均计算新价格）
        5. 挂新止盈止损单
        6. 更新数据库记录
        """
        try:
            import time
            token_ids = market.get('clobTokens', [])
            if isinstance(token_ids, str):
                token_ids = json.loads(token_ids)
            token_id = str(token_ids[0] if signal['direction'] == 'LONG' else token_ids[1])

            # 获取当前15分钟窗口
            from datetime import timezone as tz
            now_utc = datetime.now(tz.utc)
            window_start_ts = (int(now_utc.timestamp()) // 900) * 900
            window_start_str = datetime.fromtimestamp(window_start_ts).strftime('%Y-%m-%d %H:%M:%S')

            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            #  激活WAL模式：多线程并发读写（防止database is locked）
            conn.execute('PRAGMA journal_mode=WAL;')
            cursor = conn.cursor()

            #  检查弹匣限制：查询当前窗口内已开单次数（包括已合并的）
            cursor.execute("""
                SELECT count(*)
                FROM positions
                WHERE side = ? AND entry_time >= ?
            """, (signal['direction'], window_start_str))

            open_count = cursor.fetchone()
            shots_fired = open_count[0] if open_count else 0

            max_bullets = CONFIG['risk']['max_same_direction_bullets']
            if shots_fired >= max_bullets:
                conn.close()
                print(f"       [MERGE] [BLOCK] 弹匣耗尽: {signal['direction']}已开{shots_fired}次（最多{max_bullets}次），禁止合并")
                return False, 0

            # 查找同方向OPEN持仓（不依赖token_id，因为每小时市场会切换）
            # 只使用 side 查询，取最新的一个持仓进行合并
            cursor.execute("""
                SELECT id, entry_token_price, size, value_usdc, take_profit_order_id, stop_loss_order_id, token_id
                FROM positions
                WHERE side = ? AND status = 'open'
                ORDER BY entry_time DESC
                LIMIT 1
            """, (signal['direction'],))

            row = cursor.fetchone()
            if not row:
                conn.close()
                print(f"       [MERGE] 没有找到{signal['direction']}持仓，无需合并")
                return False, 0

            pos_id = row[0]
            old_entry_price = float(row[1])
            old_size = float(row[2])
            old_value = float(row[3])
            old_tp_order_id = row[4]
            old_sl_order_id = row[5]
            old_token_id = row[6]  # 旧持仓的token_id

            # 获取新订单信息
            new_size = new_order_result.get('size', 0)
            if isinstance(new_size, str):
                new_size = float(new_size)
            new_value = new_order_result.get('value', 0)
            if isinstance(new_value, str):
                new_value = float(new_value)
            new_entry_price = new_value / max(new_size, 1)

            # 检查新旧token_id是否一致（不同时间窗口的市场）
            if old_token_id != token_id:
                print(f"       [MERGE] ⚠ 警告：新旧持仓在不同时间窗口市场！")
                print(f"       [MERGE]    旧市场token: {old_token_id[-8:]}")
                print(f"       [MERGE]    新市场token: {token_id[-8:]}")
                print(f"       [MERGE]    [X] 跨市场不能合并（不同资产），将作为独立持仓管理")
                conn.close()
                return False, 0  # 返回False，让record_trade正常记录新持仓

            print(f"       [MERGE] 旧持仓: {old_size}股 @ {old_entry_price:.4f} (${old_value:.2f})")
            print(f"       [MERGE] 新订单: {new_size}股 @ {new_entry_price:.4f} (${new_value:.2f})")

            # 取消旧止盈止损单（带验证，确保取消成功再挂新单）
            if old_tp_order_id:
                try:
                    self.cancel_order(old_tp_order_id)
                    time.sleep(1)
                    # 验证旧止盈单确实已取消/成交，防止双重卖出
                    tp_still_live = False
                    try:
                        tp_info = self.client.get_order(old_tp_order_id)
                        if tp_info and tp_info.get('status', '').upper() in ('LIVE', 'OPEN'):
                            tp_still_live = True
                            print(f"       [MERGE] ⚠ 旧止盈单仍在挂单中，再次尝试取消...")
                            self.cancel_order(old_tp_order_id)
                            time.sleep(2)
                    except Exception:
                        pass  # 查询失败视为已取消
                    if not tp_still_live:
                        print(f"       [MERGE]  已取消旧止盈单 {old_tp_order_id[-8:]}")
                except Exception as e:
                    print(f"       [MERGE] ⚠ 取消旧止盈单失败: {e}，放弃合并以防双重卖出")
                    conn.close()
                    return False, 0
            if old_sl_order_id and old_sl_order_id.startswith('0x'):
                try:
                    self.cancel_order(old_sl_order_id)
                    print(f"       [MERGE]  已取消旧止损单 {old_sl_order_id[-8:]}")
                    time.sleep(1)
                except Exception as e:
                    print(f"       [MERGE] ⚠ 取消旧止损单失败: {e}")

            # 合并持仓（加权平均）
            merged_size = old_size + new_size
            merged_value = old_value + new_value
            merged_entry_price = merged_value / merged_size

            print(f"       [MERGE] 合并后: {merged_size}股 @ {merged_entry_price:.4f} (${merged_value:.2f})")

            # 计算新的止盈止损价格（合并持仓只用百分比，不用固定金额）
            #  修复：移除固定金额逻辑，统一使用30%百分比
            # 原因：大仓位时+1U/-1U占比太小，会偏离设计意图
            tp_pct_max = CONFIG['risk'].get('take_profit_pct', 0.30)
            sl_pct_max = CONFIG['risk'].get('max_stop_loss_pct', 0.30)

            # 对齐价格精度
            tick_size = float(market.get('orderPriceMinTickSize') or 0.01)
            def align_price(p):
                p = round(round(p / tick_size) * tick_size, 4)
                return max(tick_size, min(1 - tick_size, p))

            # 止盈：统一用30%百分比
            tp_target_price = align_price(merged_entry_price * (1 + tp_pct_max))
            # 止损：统一用30%百分比
            sl_target_price = align_price(merged_entry_price * (1 - sl_pct_max))

            print(f"       [MERGE] 新止盈: {tp_target_price:.4f} ({tp_pct_max*100:.0f}%)")
            print(f"       [MERGE] 新止损: {sl_target_price:.4f} ({sl_pct_max*100:.0f}%)")

            # 挂新的止盈单
            new_tp_order_id = None
            try:
                from py_clob_client.clob_types import OrderArgs
                tp_args = OrderArgs(
                    token_id=token_id,
                    price=tp_target_price,
                    side=SELL,
                    size=merged_size
                )
                tp_order = self.client.create_and_post_order(tp_args)
                if tp_order:
                    new_tp_order_id = tp_order.get('orderID')
                    print(f"       [MERGE]  新止盈单已挂: {new_tp_order_id[-8:]}")
            except Exception as e:
                print(f"       [MERGE] ⚠ 挂新止盈单失败: {e}，将使用本地监控")

            # 更新数据库
            cursor.execute("""
                UPDATE positions
                SET entry_time = ?,
                    entry_token_price = ?,
                    size = ?,
                    value_usdc = ?,
                    take_profit_order_id = ?,
                    stop_loss_order_id = ?,
                    take_profit_usd = ?,
                    stop_loss_usd = ?
                WHERE id = ?
            """, (
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                merged_entry_price,
                merged_size,
                merged_value,
                new_tp_order_id,
                str(sl_target_price),  # 止损是价格字符串
                1.0,  # 止盈目标（30%或+1U取较小者）
                merged_value * sl_pct_max,  # 止损金额
                pos_id
            ))

            self.safe_commit(conn)
            conn.close()

            print(f"       [MERGE]  持仓合并完成！")
            return True, pos_id

        except Exception as e:
            print(f"       [MERGE ERROR] {e}")
            import traceback
            print(f"       [TRACEBACK] {traceback.format_exc()}")
            return False

    def check_positions(self, current_token_price: float = None, yes_price: float = None, no_price: float = None, market: Dict = None):
        """检查持仓状态，通过检查止盈止损单是否成交来判断
        
        注意：current_token_price 参数仅作备用，内部会对每个持仓单独查询准确价格。
        V6模式下由 get_order_book 覆盖返回 WebSocket 实时价格。
        market: 可选，传入已获取的市场数据避免重复请求。
        """
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            #  激活WAL模式：多线程并发读写（防止database is locked）
            conn.execute('PRAGMA journal_mode=WAL;')
            cursor = conn.cursor()

            # 获取所有open和closing状态的持仓（包括订单ID）
            #  修复：也查询'closing'状态，处理止损/止盈失败后卡住的持仓
            cursor.execute("""
                SELECT id, entry_time, side, entry_token_price,
                       size, value_usdc, take_profit_order_id, stop_loss_order_id, token_id
                FROM positions
                WHERE status IN ('open', 'closing')
            """)
            positions = cursor.fetchall()

            if not positions:
                conn.close()
                return

            for pos in positions:
                pos_id, entry_time, side, entry_token_price, size, value_usdc, tp_order_id, sl_order_id, token_id = pos
                entry_token_price = float(entry_token_price)
                size = float(size)
                value_usdc = float(value_usdc) if value_usdc else 0.0

                # 优先用WebSocket实时价（get_order_book），outcomePrices是REST旧数据不可靠
                #  关键修复：止盈止损监控必须用"对手价"（如果现在平仓能拿到的价格）
                # LONG平仓=卖出YES → 用YES的bid（买一价）
                # SHORT平仓=卖出NO → 用NO的bid（买一价）
                pos_current_price = None
                if token_id:
                    # 平仓都是SELL操作，用bid价格计算真实净值
                    pos_current_price = self.get_order_book(token_id, side='SELL')

                # 初始化退出变量（修复：必须在引用前定义）
                exit_reason = None
                triggered_order_id = None
                actual_exit_price = None  # 实际成交价格

                # fallback：传入的outcomePrices
                if pos_current_price is None:
                    if yes_price is not None and no_price is not None:
                        pos_current_price = yes_price if side == 'LONG' else no_price
                    elif current_token_price:
                        pos_current_price = current_token_price

                #  修复：价格获取完全失败时触发紧急止损（避免重复平仓）
                if pos_current_price is None:
                    # exit_reason 在此处尚未初始化，直接执行紧急平仓
                    if not getattr(self, f'_emergency_closed_{pos_id}', False):
                        print(f"       [EMERGENCY] ⚠ 价格获取失败（API超时/网络问题），立即市价平仓保护")
                        # 尝试紧急市价平仓
                        try:
                            close_market = market if market else self.get_market_data()
                            if close_market:
                                # 用入场价90%确保成交（快速止损）
                                close_price = max(0.01, min(0.99, entry_token_price * 0.90))
                                from py_clob_client.clob_types import OrderArgs
                                close_order_args = OrderArgs(
                                    token_id=token_id,
                                    price=close_price,
                                    size=float(size),
                                    side=SELL
                                )
                                close_response = self.client.create_and_post_order(close_order_args)
                                if close_response and 'orderID' in close_response:
                                    setattr(self, f'_emergency_closed_{pos_id}', True)
                                    exit_reason = 'EMERGENCY_PRICE_FAIL'
                                    triggered_order_id = close_response['orderID']
                                    actual_exit_price = close_price
                                    print(f"       [EMERGENCY]  紧急平仓成功 @ {close_price:.4f}")
                                else:
                                    print(f"       [EMERGENCY] ⚠ 紧急平仓失败（API返回空）")
                            else:
                                print(f"       [EMERGENCY] ⚠ 无法获取市场数据，紧急平仓跳过")
                        except Exception as e:
                            print(f"       [EMERGENCY] [X] 紧急平仓异常: {e}")

                    print(f"       [POSITION] 价格获取失败，本轮跳过（等待0.1秒后重试）")
                    continue

                print(f"       [POSITION] {side} token价格: {pos_current_price:.4f}")

                # [ROCKET] === 吸星大法：动态追踪止盈 (Trailing Take-Profit) ===
                # 配置参数
                TRAILING_ACTIVATION = 0.75  # 启动门槛：涨到75¢才激活追踪
                TRAILING_DRAWDOWN = 0.05    # 容忍回撤：从最高点回撤5¢直接砸盘走人

                # 读取数据库中的历史最高价
                try:
                    cursor.execute("SELECT highest_price FROM positions WHERE id = ?", (pos_id,))
                    hp_row = cursor.fetchone()
                    db_highest_price = float(hp_row[0]) if hp_row and hp_row[0] else float(entry_token_price)
                except:
                    db_highest_price = float(entry_token_price)

                # 更新历史最高价
                if pos_current_price > db_highest_price:
                    db_highest_price = pos_current_price
                    cursor.execute("UPDATE positions SET highest_price = ? WHERE id = ?", (db_highest_price, pos_id))
                    conn.commit()
                    # print(f"       [[UP] 追踪拔高] 历史最高价刷新: {db_highest_price:.4f}")

                # 检查追踪止盈触发条件
                trailing_triggered = False
                if db_highest_price >= TRAILING_ACTIVATION:
                    # 条件A：最高价已越过激活线（开始锁定利润）
                    if pos_current_price <= (db_highest_price - TRAILING_DRAWDOWN):
                        # 条件B：现价比最高价跌了超过5¢（动能衰竭，做市商开始反扑）
                        print(f"       [[ROCKET] 吸星大法] 追踪止盈触发！最高{db_highest_price:.2f}→现价{pos_current_price:.2f}，回撤达5¢，锁定暴利平仓！")
                        trailing_triggered = True
                        exit_reason = 'TRAILING_TAKE_PROFIT'
                        actual_exit_price = pos_current_price

                        # 立即市价平仓
                        try:
                            from py_clob_client.clob_types import OrderArgs
                            close_order_args = OrderArgs(
                                token_id=token_id,
                                price=max(0.01, min(0.99, pos_current_price)),
                                size=float(size),
                                side=SELL
                            )
                            close_response = self.client.create_and_post_order(close_order_args)
                            if close_response and 'orderID' in close_response:
                                triggered_order_id = close_response['orderID']
                                print(f"       [[ROCKET] 吸星大法]  追踪止盈平仓单已发送: {triggered_order_id[-8:]}")
                            else:
                                print(f"       [[ROCKET] 吸星大法] ⚠ 平仓单发送失败，继续监控")
                                trailing_triggered = False
                        except Exception as e:
                            print(f"       [[ROCKET] 吸星大法] [X] 平仓异常: {e}")
                            trailing_triggered = False

                # 超高位强制结算保护（防止最后1秒画门）
                if not trailing_triggered and pos_current_price >= 0.92:
                    print(f"       [[TARGET] 绝对止盈] 价格已达{pos_current_price:.2f}，不赌最后结算，落袋为安！")
                    trailing_triggered = True
                    exit_reason = 'ABSOLUTE_TAKE_PROFIT'
                    actual_exit_price = pos_current_price

                    # 立即市价平仓
                    try:
                        from py_clob_client.clob_types import OrderArgs
                        close_order_args = OrderArgs(
                            token_id=token_id,
                            price=max(0.01, min(0.99, pos_current_price)),
                            size=float(size),
                            side=SELL
                        )
                        close_response = self.client.create_and_post_order(close_order_args)
                        if close_response and 'orderID' in close_response:
                            triggered_order_id = close_response['orderID']
                            print(f"       [[TARGET] 绝对止盈]  平仓单已发送: {triggered_order_id[-8:]}")
                    except Exception as e:
                        print(f"       [[TARGET] 绝对止盈] [X] 平仓异常: {e}")
                        trailing_triggered = False

                # 如果追踪止盈已触发，跳过后续的止盈单检查
                if trailing_triggered:
                    # 计算盈亏并更新数据库
                    pnl_usd = float(size) * (float(actual_exit_price) - float(entry_token_price))
                    pnl_pct = (pnl_usd / float(value_usdc)) * 100 if value_usdc and float(value_usdc) > 0 else 0

                    cursor.execute("""
                        UPDATE positions
                        SET exit_time = ?, exit_token_price = ?, pnl_usd = ?,
                            pnl_pct = ?, exit_reason = ?, status = 'closed'
                        WHERE id = ? AND status IN ('open', 'closing')
                    """, (
                        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        actual_exit_price,
                        pnl_usd,
                        pnl_pct,
                        exit_reason,
                        pos_id
                    ))

                    # 取消原有的止盈止损单
                    self.cancel_pair_orders(tp_order_id, sl_order_id, exit_reason)

                    print(f"       [[ROCKET] 吸星大法] {exit_reason}: {side} 盈利 ${pnl_usd:+.2f} ({pnl_pct:+.1f}%)")
                    continue  # 跳过后续处理，进入下一个持仓

                # 获取止损价格（从字段读取）
                sl_price = None
                try:
                    if sl_order_id:
                        sl_price = float(sl_order_id)
                except (ValueError, TypeError):
                    pass

                # 获取市场剩余时间（优先用传入的market，避免重复REST请求）
                if tp_order_id:
                    for _attempt in range(3):
                        try:
                            tp_order = self.client.get_order(tp_order_id)
                            if tp_order:
                                # Polymarket 成交状态可能是 FILLED 或 MATCHED
                                if tp_order.get('status') in ('FILLED', 'MATCHED'):
                                    #  F2修复：检查部分成交 matchedSize vs size
                                    tp_matched = float(tp_order.get('matchedSize', 0) or 0)
                                    tp_order_size = float(tp_order.get('size', size) or size)
                                    if tp_matched < tp_order_size * 0.95:
                                        # 部分成交：更新剩余 size，保持 open 继续监控
                                        remaining_size = size - tp_matched
                                        print(f"       [TP PARTIAL] 部分成交: matched={tp_matched:.2f} / size={tp_order_size:.2f}，剩余={remaining_size:.2f}，继续监控")
                                        try:
                                            cursor.execute(
                                                "UPDATE positions SET size = ? WHERE id = ?",
                                                (remaining_size, pos_id)
                                            )
                                            conn.commit()
                                        except Exception as db_e:
                                            print(f"       [TP PARTIAL] 更新剩余size失败: {db_e}")
                                        # 不设置 exit_reason，让监控继续处理剩余仓位
                                    else:
                                        # 完全成交（>=95%）
                                        exit_reason = 'TAKE_PROFIT'
                                        triggered_order_id = tp_order_id
                                        # 优先用avgPrice，合理性校验
                                        avg_p = tp_order.get('avgPrice') or tp_order.get('price')
                                        if avg_p:
                                            parsed = float(avg_p)
                                            actual_exit_price = parsed if 0.01 <= parsed <= 0.99 else None
                                        if actual_exit_price is None:
                                            actual_exit_price = entry_token_price  # fallback入场价
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
                                #  关键修复：余额为0需区分两种情况
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
                                                avg_p = tp_order_info.get('avgPrice') or tp_order_info.get('price')
                                                if avg_p:
                                                    parsed = float(avg_p)
                                                    actual_exit_price = parsed if 0.01 <= parsed <= 0.99 else pos_current_price
                                                else:
                                                    actual_exit_price = pos_current_price
                                                print(f"       [POSITION]  确认止盈单已成交 status={tp_status} @ {actual_exit_price:.4f}")
                                            else:
                                                # 止盈单未成交，余额为0 = 市场到期归零
                                                exit_reason = 'MARKET_SETTLED'
                                                actual_exit_price = 0.0
                                                print(f"       [POSITION]  止盈单未成交(status={tp_status})，市场到期归零，记录真实亏损")
                                    except Exception as e:
                                        print(f"       [POSITION] 查询止盈单失败: {e}，保守处理为归零")
                                        exit_reason = 'MARKET_SETTLED'
                                        actual_exit_price = 0.0
                                elif not exit_reason:
                                    # 没有止盈单，余额为0 = 手动平仓
                                    print(f"       [POSITION] ⚠  Token余额为{actual_size:.2f}份，检测到已手动平仓，停止监控")
                                    exit_reason = 'MANUAL_CLOSED'
                                    actual_exit_price = pos_current_price
                            else:
                                print(f"       [POSITION] [DEBUG] 余额查询成功，balance={actual_size:.2f}份")
                except Exception as e:
                    print(f"       [POSITION] [DEBUG] 余额查询失败: {e}")
                    pass

                # 如果止盈单没成交，检查本地止盈止损价格（双向轮询模式）
                if not exit_reason:
                    #  关键修复：使用与开仓时相同的公式，确保一致性（对称30%逻辑）
                    tp_pct_max = CONFIG['risk'].get('take_profit_pct', 0.30)  # 修复：止盈应使用take_profit_pct
                    tp_by_pct = entry_token_price * (1 + tp_pct_max)
                    tp_by_fixed = (value_usdc + 1.0) / max(size, 1)
                    tp_target_price = min(tp_by_fixed, tp_by_pct)

                    # 确保止盈价格在合理范围内 (Polymarket 最高价格为 1.0)
                    tp_target_price = max(0.01, min(0.99, tp_target_price))

                    # 获取止损价格（从字段读取）
                    sl_price = None
                    try:
                        if sl_order_id:
                            sl_price = float(sl_order_id)
                    except (ValueError, TypeError):
                        pass

                    # 获取市场剩余时间（优先用传入的market，避免重复REST请求）
                    seconds_left = None
                    try:
                        from datetime import timezone
                        _market = market if market else self.get_market_data()
                        if _market:
                            end_date = _market.get('endDate')
                            if end_date:
                                end_dt = datetime.strptime(end_date, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                                now_dt = datetime.now(timezone.utc)
                                seconds_left = (end_dt - now_dt).total_seconds()
                    except:
                        pass

                    # [CHART] 显示双向监控状态
                    tp_gap = tp_target_price - pos_current_price
                    if sl_price:
                        sl_gap = pos_current_price - sl_price
                        time_info = f" | 剩余: {int(seconds_left)}s" if seconds_left else ""
                        if CONFIG['risk'].get('enable_stop_loss', False):
                            print(f"       [MONITOR] 当前价: {pos_current_price:.4f} | TP目标: {tp_target_price:.4f} (差{tp_gap:.4f}) | SL止损: {sl_price:.4f} (距{sl_gap:.4f}){time_info}")
                        else:
                            print(f"       [MONITOR] 当前价: {pos_current_price:.4f} | TP目标: {tp_target_price:.4f} (差{tp_gap:.4f}) | SL止损: {sl_price:.4f} (已禁用){time_info}")
                    else:
                        print(f"       [MONITOR] 当前价: {pos_current_price:.4f} | TP目标: {tp_target_price:.4f} (差{tp_gap:.4f})")

                    # 双向监控：止盈和止损
                    # 1. 检查止盈（价格上涨触发）
                    if pos_current_price >= tp_target_price:
                        print(f"       [LOCAL TP] 触发本地止盈！当前价 {pos_current_price:.4f} >= 目标 {tp_target_price:.4f}")

                        #  状态锁：立即更新数据库状态为 'closing'，防止重复触发
                        try:
                            cursor.execute("UPDATE positions SET status = 'closing' WHERE id = ?", (pos_id,))
                            conn.commit()
                            print(f"       [LOCAL TP] [LOCK] 状态已锁为 'closing'，防止重复触发")
                        except Exception as lock_e:
                            print(f"       [LOCAL TP] ⚠ 状态锁失败: {lock_e}")

                        #  关键修复：先查询止盈单状态，再决定是否撤销
                        # 避免撤销已成交的订单导致状态变成CANCELED，误判为"市场归零"
                        tp_already_filled = False
                        tp_filled_price = None

                        if tp_order_id:
                            try:
                                tp_order_info = self.client.get_order(tp_order_id)
                                if tp_order_info:
                                    tp_status = tp_order_info.get('status', '').upper()
                                    matched_size = float(tp_order_info.get('matchedSize', 0) or 0)
                                    if tp_status in ('MATCHED', 'FILLED') or matched_size > 0:
                                        tp_already_filled = True
                                        avg_p = tp_order_info.get('avgPrice') or tp_order_info.get('price')
                                        if avg_p:
                                            parsed = float(avg_p)
                                            if 0.01 <= parsed <= 0.99:
                                                tp_filled_price = parsed
                                        print(f"       [LOCAL TP]  检测到止盈单已成交 status={tp_status} @ {tp_filled_price or 'unknown'}")
                                    else:
                                        print(f"       [LOCAL TP]  止盈单未成交(status={tp_status})，准备撤销并市价平仓")
                            except Exception as e:
                                print(f"       [LOCAL TP] ⚠ 查询止盈单状态失败: {e}，继续尝试撤销")

                        # 如果止盈单已成交，直接记录盈利
                        if tp_already_filled:
                            exit_reason = 'AUTO_CLOSED_OR_MANUAL'
                            actual_exit_price = tp_filled_price if tp_filled_price else pos_current_price
                            print(f"       [LOCAL TP]  止盈单已成交，无需市价平仓")
                        else:
                            # 止盈单未成交，撤销后市价平仓
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

                                #  增加识别 "NO_BALANCE" 的逻辑
                                if close_order_id == "NO_BALANCE":
                                    #  再次确认：撤销后仍为NO_BALANCE，可能是真的市场归零
                                    # 或者止盈单在撤销操作期间成交了
                                    tp_actually_filled = False
                                    tp_check_price = None
                                    if tp_order_id:
                                        try:
                                            time.sleep(1)  # 等待1秒让链上状态同步
                                            tp_order_info = self.client.get_order(tp_order_id)
                                            if tp_order_info:
                                                tp_status = tp_order_info.get('status', '').upper()
                                                matched_size = float(tp_order_info.get('matchedSize', 0) or 0)
                                                if tp_status in ('MATCHED', 'FILLED') or matched_size > 0:
                                                    tp_actually_filled = True
                                                    p = tp_order_info.get('avgPrice') or tp_order_info.get('price')
                                                    if p:
                                                        parsed = float(p)
                                                        if 0.01 <= parsed <= 0.99:
                                                            tp_check_price = parsed
                                                    print(f"       [LOCAL TP]  复查确认止盈单已成交 status={tp_status}")
                                                else:
                                                    print(f"       [LOCAL TP] [X] 止盈单未成交(status={tp_status})，可能是市场到期归零")
                                        except Exception as e:
                                            print(f"       [LOCAL TP] ⚠ 复查止盈单状态失败: {e}")

                                    if tp_actually_filled:
                                        exit_reason = 'AUTO_CLOSED_OR_MANUAL'
                                        actual_exit_price = tp_check_price if tp_check_price else pos_current_price
                                        print(f"       [LOCAL TP]  止盈单在撤销期间成交，使用成交价: {actual_exit_price:.4f}")
                                    else:
                                        # 真正的市场归零
                                        exit_reason = 'MARKET_SETTLED'
                                        actual_exit_price = 0.0
                                        print(f"       [LOCAL TP]  确认市场归零，记录真实亏损")
                            elif close_order_id:
                                exit_reason = 'TAKE_PROFIT_LOCAL'
                                triggered_order_id = close_order_id
                                actual_exit_price = pos_current_price  # fallback

                                #  关键修复：平仓单已上链，立即更新数据库防止"幽灵归零"
                                # 即使后续查询成交价失败，至少status已不是'open'
                                try:
                                    cursor.execute("""
                                        UPDATE positions
                                        SET exit_time = ?, exit_token_price = ?,
                                            exit_reason = ?, status = 'closing'
                                        WHERE id = ?
                                    """, (
                                        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                        actual_exit_price,
                                        exit_reason,
                                        pos_id
                                    ))
                                    conn.commit()
                                    print(f"       [LOCAL TP]  平仓订单已上链，数据库状态已更新为'closing'")
                                except Exception as update_err:
                                    print(f"       [LOCAL TP] ⚠ 初步数据库更新失败: {update_err}")

                                #  修复：重试查询实际成交价（保守优化：3次×0.5秒=1.5秒）
                                # 确保订单有时间成交，同时减少监控阻塞
                                for _tp_attempt in range(3):
                                    try:
                                        time.sleep(0.5)  #  优化：从1秒缩短到0.5秒
                                        close_order = self.client.get_order(close_order_id)
                                        if close_order:
                                            tp_status = close_order.get('status', '').upper()
                                            matched_size = float(close_order.get('matchedSize', 0) or 0)
                                            if tp_status in ('FILLED', 'MATCHED') or matched_size > 0:
                                                avg_p = close_order.get('avgPrice') or close_order.get('price')
                                                if avg_p:
                                                    parsed = float(avg_p)
                                                    if 0.01 <= parsed <= 0.99:
                                                        actual_exit_price = parsed
                                                print(f"       [LOCAL TP]  止盈实际成交价: {actual_exit_price:.4f} (尝试{_tp_attempt+1}次)")
                                                break
                                            else:
                                                print(f"       [LOCAL TP] ⏳ 止盈单未成交(status={tp_status})，继续等待({_tp_attempt+1}/3)...")
                                    except Exception as e:
                                        print(f"       [LOCAL TP] 查询成交价失败({_tp_attempt+1}/3): {e}")
                                else:
                                    print(f"       [LOCAL TP] ⚠ 止盈单1.5秒内未确认成交，使用发单时价格: {actual_exit_price:.4f}")
                                print(f"       [LOCAL TP] 本地止盈执行完毕，成交价: {actual_exit_price:.4f}")
                            else:
                                #  修复：止盈平仓失败后，将status改回'open'，让下次继续处理
                                print(f"       [LOCAL TP] ⚠ 市价平仓失败，将在下次迭代时重试")
                                try:
                                    cursor.execute("UPDATE positions SET status = 'open' WHERE id = ?", (pos_id,))
                                    conn.commit()
                                    print(f"       [LOCAL TP] [UNLOCK] 状态已重置为 'open'，下次迭代将重试止盈")
                                except Exception as reset_err:
                                    print(f"       [LOCAL TP] [X] 状态重置失败: {reset_err}")

                    # 2. 检查止损（价格下跌触发）-  立即执行，不再等待最后5分钟
                    #  止损已禁用（数据证明止损胜率0%，纯亏损来源）
                    elif sl_price and pos_current_price < sl_price and CONFIG['risk'].get('enable_stop_loss', False):
                        print(f"       [LOCAL SL] 触发本地止损！当前价 {pos_current_price:.4f} < 止损线 {sl_price:.4f}")
                        time_remaining = f"{int(seconds_left)}s" if seconds_left else "未知"
                        print(f"       [LOCAL SL] [TIME] 市场剩余 {time_remaining}，立即执行止损保护")

                        #  状态锁：立即更新数据库状态为 'closing'，防止重复触发
                        try:
                            cursor.execute("UPDATE positions SET status = 'closing' WHERE id = ?", (pos_id,))
                            conn.commit()
                            print(f"       [LOCAL SL] [LOCK] 状态已锁为 'closing'，防止重复触发")
                        except Exception as lock_e:
                            print(f"       [LOCAL SL] ⚠ 状态锁失败: {lock_e}")

                        #  关键修复：先查询止盈单状态，避免撤销已成交订单导致误判
                        tp_already_filled = False
                        tp_filled_price = None

                        if tp_order_id:
                            try:
                                tp_order_info = self.client.get_order(tp_order_id)
                                if tp_order_info:
                                    tp_status = tp_order_info.get('status', '').upper()
                                    matched_size = float(tp_order_info.get('matchedSize', 0) or 0)
                                    if tp_status in ('MATCHED', 'FILLED') or matched_size > 0:
                                        tp_already_filled = True
                                        avg_p = tp_order_info.get('avgPrice') or tp_order_info.get('price')
                                        if avg_p:
                                            parsed = float(avg_p)
                                            if 0.01 <= parsed <= 0.99:
                                                tp_filled_price = parsed
                                        print(f"       [LOCAL SL]  检测到止盈单已成交 status={tp_status} @ {tp_filled_price or 'unknown'}")
                                    else:
                                        print(f"       [LOCAL SL]  止盈单未成交，准备撤销")
                            except Exception as e:
                                print(f"       [LOCAL SL] ⚠ 查询止盈单状态失败: {e}")

                        # 如果止盈单已成交，直接记录盈利（止损前已止盈）
                        if tp_already_filled:
                            exit_reason = 'AUTO_CLOSED_OR_MANUAL'
                            actual_exit_price = tp_filled_price if tp_filled_price else pos_current_price
                            print(f"       [LOCAL SL]  止盈单已成交，无需止损平仓")
                        else:
                            # 止盈单未成交，撤销并执行止损
                            if tp_order_id:
                                print(f"       [LOCAL SL] 撤销止盈单 {tp_order_id[-8:]}...")
                                self.cancel_order(tp_order_id)
                                time.sleep(1)  #  优化：从3秒缩短到1秒，减少监控阻塞

                            # 市价平仓（止损模式，直接砸单不防插针）
                            close_market = market if market else self.get_market_data()
                            if close_market:
                                close_order_id = self.close_position(close_market, side, size, is_stop_loss=True, entry_price=entry_token_price, sl_price=sl_price)

                                #  增加识别 "NO_BALANCE" 的逻辑
                                if close_order_id == "NO_BALANCE":
                                    #  再次确认：撤销后仍为NO_BALANCE，可能是真的市场归零
                                    # 或者止盈单在撤销操作期间成交了
                                    tp_actually_filled = False
                                    tp_check_price = None
                                    if tp_order_id:
                                        try:
                                            time.sleep(1)  # 等待1秒让链上状态同步
                                            tp_order_info = self.client.get_order(tp_order_id)
                                            if tp_order_info:
                                                tp_status = tp_order_info.get('status', '').upper()
                                                matched_size = float(tp_order_info.get('matchedSize', 0) or 0)
                                                if tp_status in ('MATCHED', 'FILLED') or matched_size > 0:
                                                    tp_actually_filled = True
                                                    avg_p = tp_order_info.get('avgPrice') or tp_order_info.get('price')
                                                    if avg_p:
                                                        parsed = float(avg_p)
                                                        if 0.01 <= parsed <= 0.99:
                                                            tp_check_price = parsed
                                                    print(f"       [LOCAL SL]  复查确认止盈单已成交 status={tp_status}")
                                                else:
                                                    print(f"       [LOCAL SL] [X] 止盈单未成交(status={tp_status})，可能是市场到期归零")
                                        except Exception as e:
                                            print(f"       [LOCAL SL] ⚠ 复查止盈单状态失败: {e}")

                                    if tp_actually_filled:
                                        exit_reason = 'AUTO_CLOSED_OR_MANUAL'
                                        actual_exit_price = tp_check_price if tp_check_price else pos_current_price
                                        print(f"       [LOCAL SL]  止盈单在撤销期间成交，止损前已盈利")
                                    else:
                                        # 真正的市场归零
                                        exit_reason = 'MARKET_SETTLED'
                                        actual_exit_price = 0.0
                                        print(f"       [LOCAL SL]  确认市场归零，记录真实亏损")
                            elif close_order_id:
                                exit_reason = 'STOP_LOSS_LOCAL'
                                triggered_order_id = close_order_id
                                actual_exit_price = pos_current_price  # fallback

                                #  关键修复：平仓单已上链，立即更新数据库防止"幽灵归零"
                                # 即使后续查询成交价失败，至少status已不是'open'
                                try:
                                    cursor.execute("""
                                        UPDATE positions
                                        SET exit_time = ?, exit_token_price = ?,
                                            exit_reason = ?, status = 'closing'
                                        WHERE id = ?
                                    """, (
                                        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                        actual_exit_price,
                                        exit_reason,
                                        pos_id
                                    ))
                                    conn.commit()
                                    print(f"       [LOCAL SL]  平仓订单已上链，数据库状态已更新为'closing'")
                                except Exception as update_err:
                                    print(f"       [LOCAL SL] ⚠ 初步数据库更新失败: {update_err}")

                                #  修复：重试查询实际成交价，避免滑点被掩盖
                                # 极端行情下快速重试，保守优化：3次×0.5秒=1.5秒
                                for _sl_attempt in range(3):
                                    try:
                                        time.sleep(0.5)  #  优化：从1秒缩短到0.5秒
                                        close_order = self.client.get_order(close_order_id)
                                        if close_order:
                                            sl_status = close_order.get('status', '').upper()
                                            matched_size = float(close_order.get('matchedSize', 0) or 0)
                                            if sl_status in ('FILLED', 'MATCHED') or matched_size > 0:
                                                avg_p = close_order.get('avgPrice') or close_order.get('price')
                                                if avg_p:
                                                    parsed = float(avg_p)
                                                    if 0.01 <= parsed <= 0.99:
                                                        actual_exit_price = parsed
                                                print(f"       [LOCAL SL]  止损实际成交价: {actual_exit_price:.4f} (尝试{_sl_attempt+1}次)")
                                                break
                                            else:
                                                print(f"       [LOCAL SL] ⏳ 止损单未成交(status={sl_status})，继续等待({_sl_attempt+1}/3)...")
                                    except Exception as e:
                                        print(f"       [LOCAL SL] 查询成交价失败({_sl_attempt+1}/3): {e}")
                                else:
                                    print(f"       [LOCAL SL] ⚠ 止损单1.5秒内未确认成交，使用发单时价格: {actual_exit_price:.4f}")
                                print(f"       [LOCAL SL] 止损执行完毕，成交价: {actual_exit_price:.4f}")
                            else:
                                #  修复：止损平仓失败后，将status改回'open'，让下次继续处理
                                print(f"       [LOCAL SL] ⚠ 市价平仓失败，将在下次迭代时重试")
                                try:
                                    cursor.execute("UPDATE positions SET status = 'open' WHERE id = ?", (pos_id,))
                                    conn.commit()
                                    print(f"       [LOCAL SL] [UNLOCK] 状态已重置为 'open'，下次迭代将重试止损")
                                except Exception as reset_err:
                                    print(f"       [LOCAL SL] [X] 状态重置失败: {reset_err}")

                # 如果订单成交但没有获取到价格，使用当前价格作为fallback
                if exit_reason and actual_exit_price is None:
                    actual_exit_price = pos_current_price
                    print(f"       [POSITION WARNING] 订单成交但无法获取价格，使用当前价格: {actual_exit_price:.4f}")

                # 止盈止损完全依赖挂单成交，不做主动价格监控平仓

                # 检查市场是否即将到期（最后2分钟的智能平仓策略）
                if not exit_reason:
                    try:
                        from datetime import timezone
                        expiry_market = market if market else self.get_market_data()
                        if expiry_market:
                            end_date = expiry_market.get('endDate')
                            if end_date:
                                end_dt = datetime.strptime(end_date, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                                now_dt = datetime.now(timezone.utc)
                                seconds_left = (end_dt - now_dt).total_seconds()

                                #  市场已过期：直接标记为已结算，停止监控
                                if seconds_left < 0:
                                    print(f"       [EXPIRY] [TIME] 市场已过期({abs(seconds_left):.0f}秒)，标记为已结算")
                                    current_value = size * pos_current_price
                                    current_pnl = current_value - value_usdc
                                    print(f"       [EXPIRY] 最终盈亏: ${current_pnl:.2f}")
                                    exit_reason = 'MARKET_SETTLED'
                                    actual_exit_price = pos_current_price

                                # 计算当前盈亏（用于判断触发策略）
                                # 用价格差计算，避免value_usdc浮点误差导致亏损被判为盈利
                                current_value = size * pos_current_price
                                current_pnl = size * (pos_current_price - entry_token_price)

                                # [DIAMOND] 盈利情况：最后60秒强制平仓锁定利润
                                if current_pnl >= 0 and seconds_left <= 60:
                                    print(f"       [EXPIRY] [DIAMOND] 市场即将到期({seconds_left:.0f}秒)，当前盈利 ${current_pnl:.2f}")
                                    print(f"       [EXPIRY] [RELOAD] 撤销止盈单，市价平仓锁定利润！")

                                    # 撤销止盈单
                                    if tp_order_id:
                                        try:
                                            self.cancel_order(tp_order_id)
                                            print(f"       [EXPIRY]  已撤销止盈单")
                                        except:
                                            pass

                                    # 市价平仓锁定利润
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
                                            print(f"       [EXPIRY]  强制平仓单已挂: {close_order_id[-8:]} @ {close_price:.4f}")
                                    except Exception as e:
                                        print(f"       [EXPIRY] [X] 强制平仓失败: {e}")
                                        # 平仓失败则持有到结算
                                        exit_reason = 'HOLD_TO_SETTLEMENT'
                                        actual_exit_price = pos_current_price

                                #  亏损情况：最后120秒强制止损
                                elif current_pnl < 0 and seconds_left <= 120:
                                    print(f"       [EXPIRY] ⏳ 市场即将到期({seconds_left:.0f}秒)，当前亏损 ${current_pnl:.2f}")
                                    print(f"       [EXPIRY]  执行强制市价平仓止损！")

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
                                            print(f"       [EXPIRY]  强制平仓单已挂: {close_order_id[-8:]} @ {close_price:.4f}")
                                    except Exception as e:
                                        print(f"       [EXPIRY] [X] 强制平仓失败: {e}")
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
                    pnl_usd = float(size) * (float(actual_exit_price) - float(entry_token_price))
                    pnl_pct = (pnl_usd / float(value_usdc)) * 100 if value_usdc and float(value_usdc) > 0 else 0

                    # 更新持仓状态为最终closed状态（覆盖之前的'closing'保险状态）
                    #  包含pnl_usd和pnl_pct的完整记录，确保不出现"幽灵归零"
                    cursor.execute("""
                        UPDATE positions
                        SET exit_time = ?, exit_token_price = ?, pnl_usd = ?,
                            pnl_pct = ?, exit_reason = ?, status = 'closed'
                        WHERE id = ? AND status IN ('open', 'closing')
                    """, (
                        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        actual_exit_price,  # 使用实际成交价格
                        pnl_usd,
                        pnl_pct,
                        exit_reason,
                        pos_id
                    ))

                    # 验证UPDATE是否成功
                    if cursor.rowcount == 0:
                        print(f"       [POSITION WARNING] 数据库UPDATE影响0行，可能已被其他进程处理")
                    else:
                        print(f"       [POSITION DB]  已更新数据库: status='closed', pnl=${pnl_usd:+.2f}")

                    result_text = "盈利" if pnl_usd > 0 else "亏损"
                    print(f"       [POSITION] {exit_reason}: {side} {result_text} ${pnl_usd:+.2f} ({pnl_pct:+.1f}%) - 订单 {triggered_order_id}")
                    print(f"       [POSITION] 实际成交价: {actual_exit_price:.4f}")

                    # 更新 daily_loss 统计
                    if pnl_usd < 0:
                        self.stats['daily_loss'] += abs(pnl_usd)
                        print(f"       [STATS] 累计每日亏损: ${self.stats['daily_loss']:.2f} / ${self.position_mgr.get_max_daily_loss():.2f}")

                        #  === 反追空装甲：更新单向连亏计数器 ===
                        # 定义大亏损：亏损比例超过50%（含归零）
                        if pnl_pct < -50:
                            breaker = self.directional_circuit_breaker[side]
                            breaker['consecutive_losses'] += 1
                            breaker['last_loss_time'] = datetime.now().timestamp()
                            breaker['last_entry_price'] = float(entry_token_price)

                            # 赢的方向重置
                            opposite = 'SHORT' if side == 'LONG' else 'LONG'
                            self.directional_circuit_breaker[opposite]['consecutive_losses'] = 0

                            print(f"       [ 熔断器] {side}方向连亏计数: {breaker['consecutive_losses']}/3")
                            if breaker['consecutive_losses'] >= 3:
                                print(f"       [ 熔断警告] {side}方向已连续亏损{breaker['consecutive_losses']}次！下次该方向信号将被锁定30分钟")

                    elif pnl_usd > 0:
                        #  反追空装甲：盈利时重置该方向的连亏计数
                        breaker = self.directional_circuit_breaker[side]
                        if breaker['consecutive_losses'] > 0:
                            print(f"       [ 熔断器] {side}方向盈利 ，连亏计数重置: {breaker['consecutive_losses']} → 0")
                            breaker['consecutive_losses'] = 0

            self.safe_commit(conn)
            conn.close()

        except Exception as e:
            print(f"       [POSITION CHECK ERROR] {e}")
            try:
                conn.close()
            except:
                pass

    def get_open_positions_count(self) -> int:
        """获取当前open持仓数量"""
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            #  激活WAL模式：多线程并发读写（防止database is locked）
            conn.execute('PRAGMA journal_mode=WAL;')
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
            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            #  激活WAL模式：多线程并发读写（防止database is locked）
            conn.execute('PRAGMA journal_mode=WAL;')
            cursor = conn.cursor()

            # 确定需要平仓的方向（与当前信号相反）
            opposite_direction = 'SHORT' if new_signal_direction == 'LONG' else 'LONG'

            # 获取所有open和closing状态的相反方向持仓（包括订单ID）
            #  修复：也包括'closing'状态的持仓（卡住的持仓也需要处理）
            cursor.execute("""
                SELECT id, entry_time, side, entry_token_price, value_usdc, size,
                       take_profit_order_id, stop_loss_order_id
                FROM positions
                WHERE status IN ('open', 'closing') AND side = ?
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
                            match_amount = float(close_order.get('matchAmount', 0) or 0)
                            matched_size = float(close_order.get('matchedSize', 0) or 0)
                            if matched_size > 0:
                                fetched_price = match_amount / matched_size
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

                closed_count += 1

            if closed_count > 0:
                print(f"       [SIGNAL CHANGE] 共平仓 {closed_count} 个{opposite_direction}持仓")

            self.safe_commit(conn)
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

                # 检查持仓止盈止损（check_positions内部优先用WebSocket实时价，outcomePrices仅作fallback）
                yes_price = float(outcome_prices[0]) if outcome_prices and len(outcome_prices) > 0 else None
                no_price = float(outcome_prices[1]) if outcome_prices and len(outcome_prices) > 1 else None
                self.check_positions(yes_price=yes_price, no_price=no_price, market=market)

                # 生成信号
                new_signal = self.generate_signal(market, price)

                if new_signal:
                    # 增加信号计数器
                    self.stats['signal_count'] += 1

                    print(f"       Signal: {new_signal['direction']} | Score: {new_signal['score']:.1f}")

                    # 检测信号改变（作为止盈信号）
                    # [LOCK] 已禁用信号反转强制平仓 - 让仓位完全由止盈止损控制，避免频繁左右横跳
                    # if self.last_signal_direction and self.last_signal_direction != new_signal['direction']:
                    #     print(f"       [SIGNAL CHANGE] {self.last_signal_direction} → {new_signal['direction']}")
                    #     self.close_positions_by_signal_change(price, new_signal['direction'])

                    # 更新最后信号方向（不管是否交易）
                    self.last_signal_direction = new_signal['direction']

                    can_trade, reason = self.can_trade(new_signal, market)
                    if can_trade:
                        print(f"       Risk: {reason}")

                        order_result = self.place_order(market, new_signal)

                        #  持仓合并：检查是否需要合并到已有持仓
                        if order_result:
                            merged, merged_from_id = self.merge_position_existing(market, new_signal, order_result)
                            #  无论是否合并，都记录这次交易（合并交易标记merged_from_id）
                            self.record_trade(market, new_signal, order_result, was_blocked=False, merged_from=merged_from_id)

                        self.stats['total_trades'] += 1
                        self.stats['daily_trades'] += 1
                        self.stats['last_trade_time'] = datetime.now()
                    else:
                        print(f"       Risk: {reason}")
                else:
                    print("       No signal")

                # 每60次迭代输出交易分析（约15分钟）
                if i % 60 == 0 and i > 0:
                    print()
                    self.print_trading_analysis()

                #  每30次迭代导出一次（约7.5分钟），确保能看到最新数据
                if i % 30 == 0 and i > 0:
                    print()
                    self.print_trading_analysis()

                time.sleep(interval)
                i += 1

        except KeyboardInterrupt:
            print()
            print("=" * 70)
            print(f"STOPPED BY USER - {self.stats['total_trades']} trades completed.")
            print("=" * 70)
            self.print_trading_analysis()

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

    # ── 轻量版存根：供 V6 调用，避免 AttributeError ──────────────────────────

    def auto_adjust_parameters(self):
        """轻量版无学习系统，跳过参数自动调整"""
        pass

    def verify_pending_predictions(self):
        """轻量版无学习系统，跳过预测验证"""
        return 0

    def record_prediction_learning(self, market, signal, order_result, was_blocked=False):
        """轻量版无学习系统，跳过预测记录"""
        pass

    def print_learning_reports(self):
        """轻量版无学习系统，跳过学习报告"""
        pass

    def _get_last_market_slug(self, pos_id=None):
        """轻量版无学习系统"""
        return self.last_traded_market or ''

    def _oracle_params_file(self):
        data_dir = os.getenv('DATA_DIR', os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(data_dir, 'oracle_params.json')

    def _adjust_ut_bot_params(self):
        """轻量版无学习系统，跳过UT Bot参数调整"""
        pass

def start_api_server(port=8888):
    """在后台线程启动HTTP API服务器"""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import sqlite3
    import threading

    class TradeAPIHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/health':
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'ok', 'timestamp': datetime.now().isoformat()}).encode())
                return

            if self.path == '/trades':
                data_dir = os.getenv('DATA_DIR', '/app/data')
                db_path = os.path.join(data_dir, 'btc_15min_auto_trades.db')

                try:
                    conn = sqlite3.connect(db_path, timeout=30.0)
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()

                    cursor.execute("""
                        SELECT
                            id,
                            entry_time,
                            side,
                            entry_token_price,
                            exit_token_price,
                            pnl_usd,
                            pnl_pct,
                            exit_reason,
                            value_usdc,
                            size
                        FROM positions
                        WHERE status = 'closed'
                        ORDER BY entry_time DESC
                        LIMIT 5
                    """)

                    trades = []
                    for row in cursor.fetchall():
                        trades.append({
                            'id': row['id'],
                            'entry_time': row['entry_time'],
                            'side': row['side'],
                            'entry_price': row['entry_token_price'],
                            'exit_price': row['exit_token_price'],
                            'pnl_usd': row['pnl_usd'],
                            'pnl_pct': row['pnl_pct'],
                            'exit_reason': row['exit_reason'],
                            'value_usdc': row['value_usdc'],
                            'size': row['size']
                        })

                    conn.close()

                    self.send_response(200)
                    self.send_header('Content-type', 'application/json; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(json.dumps(trades, ensure_ascii=False, indent=2).encode())
                except Exception as e:
                    self.send_response(500)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': str(e)}).encode())
                return

            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not Found')

        def log_message(self, format, *args):
            pass

    def run_server():
        server = HTTPServer(('0.0.0.0', port), TradeAPIHandler)
        server.serve_forever()

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    print(f"[API] HTTP API服务器已启动: http://0.0.0.0:{port}")
    print(f"[API] 端点: GET /health, GET /trades")

def main():
    # 启动API服务器（默认启用，用于查询交易数据）
    # 可通过环境变量 DISABLE_API=true 禁用
    if os.getenv('DISABLE_API', 'false').lower() != 'true':
        start_api_server(port=int(os.getenv('API_PORT', '8888')))

    # 启动主交易程序
    trader = AutoTraderV5()
    trader.run()

if __name__ == "__main__":
    main()
