#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投票系统引擎 - 模仿图片平台的简单投票机制

每个规则独立投票 -> 聚合 -> 最终决策
"""

import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from typing import Dict, List, Optional, Tuple
from datetime import datetime
import math


class VotingRule:
    """投票规则基类"""

    def __init__(self, name: str, weight: float = 1.0):
        self.name = name
        self.weight = weight
        self.enabled = True

    def evaluate(self, **kwargs) -> Optional[Dict]:
        """
        评估并投票

        返回:
            {
                'direction': 'LONG' or 'SHORT' or 'NEUTRAL',
                'confidence': 0.0-1.0,
                'reason': '投票原因'
            }
            或 None（不投票）
        """
        raise NotImplementedError

    def __call__(self, **kwargs) -> Optional[Dict]:
        return self.evaluate(**kwargs)


class UltraShortMomentumRule(VotingRule):
    """超短动量规则（使用币安真实数据：30s/60s/120s）"""

    def __init__(self, period_seconds: int, name: str, weight: float = 1.0):
        """
        Args:
            period_seconds: 时间窗口秒数（30/60/120）
            name: 规则名称
            weight: 权重
        """
        super().__init__(name, weight)
        self.period_seconds = period_seconds

    def evaluate(self, oracle: Dict = None, **kwargs) -> Optional[Dict]:
        """
        从币安 Oracle 读取超短动量数据

        Args:
            oracle: Oracle 信号字典（包含 momentum_30s, momentum_60s, momentum_120s）
        """
        if not oracle:
            return None

        # 根据时间窗口选择对应的动量字段
        momentum_key = f'momentum_{self.period_seconds}s'
        momentum_pct = oracle.get(momentum_key, 0.0)

        # 如果币安数据不可用（0.0），返回None（不投票）
        if abs(momentum_pct) < 0.01:
            return None

        # 降低阈值（超短动量更敏感）
        threshold = 0.2  # 0.2% 就算有动量

        if abs(momentum_pct) < threshold:
            return None  # 动量太小，不投票

        direction = 'LONG' if momentum_pct > 0 else 'SHORT'
        confidence = min(abs(momentum_pct) / 3.0, 0.99)  # 超短动量更敏感
        reason = f'{self.period_seconds}s动量 {momentum_pct:+.2f}%'

        return {
            'direction': direction,
            'confidence': confidence,
            'reason': reason,
            'raw_value': momentum_pct
        }


class PriceMomentumRule(VotingRule):
    """标准价格动量规则"""

    def __init__(self, weight: float = 1.0):
        super().__init__('Price Momentum', weight)

    def evaluate(self, price_history: List[float], **kwargs) -> Optional[Dict]:
        if len(price_history) < 10:
            return None

        # 计算动量
        recent = price_history[-10:]
        momentum_pct = (recent[-1] - recent[0]) / recent[0] * 100

        # 转换为方向和置信度
        if momentum_pct > 1.0:
            direction = 'LONG'
            confidence = min(abs(momentum_pct) / 5.0, 0.99)
            reason = f'上涨{momentum_pct:+.2f}%'
        elif momentum_pct < -1.0:
            direction = 'SHORT'
            confidence = min(abs(momentum_pct) / 5.0, 0.99)
            reason = f'下跌{momentum_pct:+.2f}%'
        else:
            return None  # 动量太小，不投票

        return {
            'direction': direction,
            'confidence': confidence,
            'reason': reason,
            'raw_value': momentum_pct
        }


class RSIRule(VotingRule):
    """RSI规则"""

    def __init__(self, weight: float = 1.0):
        super().__init__('RSI', weight)

    def evaluate(self, rsi: float, **kwargs) -> Optional[Dict]:
        if rsi > 60:
            direction = 'SHORT'
            confidence = (rsi - 60) / 40.0  # 60→0%, 100→100%
            reason = f'RSI {rsi:.1f} (超买)'
        elif rsi < 40:
            direction = 'LONG'
            confidence = (40 - rsi) / 40.0  # 40→0%, 0→100%
            reason = f'RSI {rsi:.1f} (超卖)'
        else:
            return None  # RSI中性，不投票

        return {
            'direction': direction,
            'confidence': confidence,
            'reason': reason,
            'raw_value': rsi
        }


class VWAPRule(VotingRule):
    """VWAP偏离规则"""

    def __init__(self, weight: float = 1.0):
        super().__init__('VWAP', weight)

    def evaluate(self, price: float, vwap: float, **kwargs) -> Optional[Dict]:
        if vwap <= 0:
            return None

        vwap_dist_pct = ((price - vwap) / vwap * 100)

        if vwap_dist_pct > 0.5:
            direction = 'SHORT'
            confidence = min(abs(vwap_dist_pct) / 2.0, 0.99)
            reason = f'高于VWAP {vwap_dist_pct:+.2f}%'
        elif vwap_dist_pct < -0.5:
            direction = 'LONG'
            confidence = min(abs(vwap_dist_pct) / 2.0, 0.99)
            reason = f'低于VWAP {vwap_dist_pct:+.2f}%'
        else:
            return None  # 接近VWAP，不投票

        return {
            'direction': direction,
            'confidence': confidence,
            'reason': reason,
            'raw_value': vwap_dist_pct
        }


class TrendStrengthRule(VotingRule):
    """趋势强度规则"""

    def __init__(self, weight: float = 1.0):
        super().__init__('Trend Strength', weight)

    def evaluate(self, price_history: List[float], **kwargs) -> Optional[Dict]:
        if len(price_history) < 3:
            return None

        recent = price_history[-3:]
        trend_pct = (recent[-1] - recent[0]) / recent[0] * 100

        if trend_pct > 0.5:
            direction = 'LONG'
            confidence = min(abs(trend_pct) / 3.0, 0.99)
            reason = f'3周期上涨{trend_pct:+.2f}%'
        elif trend_pct < -0.5:
            direction = 'SHORT'
            confidence = min(abs(trend_pct) / 3.0, 0.99)
            reason = f'3周期下跌{trend_pct:+.2f}%'
        else:
            return None  # 趋势不明显，不投票

        return {
            'direction': direction,
            'confidence': confidence,
            'reason': reason,
            'raw_value': trend_pct
        }


class OracleCVDRule(VotingRule):
    """Oracle CVD规则"""

    def __init__(self, window: str, weight: float = 1.0):
        super().__init__(f'Oracle {window} CVD', weight)
        self.window = window

    def evaluate(self, oracle: Dict, **kwargs) -> Optional[Dict]:
        if not oracle:
            return None

        # 根据窗口选择CVD值
        if self.window == '5m':
            cvd_key = 'cvd_5m'
            threshold = 50000
            max_score = 150000
        elif self.window == '1m':
            cvd_key = 'cvd_1m'
            threshold = 20000
            max_score = 50000
        else:
            return None

        cvd_value = oracle.get(cvd_key, 0.0)

        if abs(cvd_value) < threshold:
            return None  # CVD太小，不投票

        direction = 'LONG' if cvd_value > 0 else 'SHORT'
        confidence = min(abs(cvd_value) / max_score, 0.99)
        reason = f'{self.window} CVD {cvd_value:+.0f}'

        return {
            'direction': direction,
            'confidence': confidence,
            'reason': reason,
            'raw_value': cvd_value
        }


class UTBotTrendRule(VotingRule):
    """UT Bot趋势规则"""

    def __init__(self, weight: float = 1.0):
        super().__init__('UT Bot 15m', weight)

    def evaluate(self, oracle: Dict, **kwargs) -> Optional[Dict]:
        if not oracle:
            return None

        trend = oracle.get('ut_hull_trend', 'NEUTRAL')

        if trend == 'NEUTRAL':
            return None  # 趋势中性，不投票

        # UT Bot趋势比较可靠，给较高置信度
        confidence = 0.70

        return {
            'direction': trend,
            'confidence': confidence,
            'reason': f'15m UT Bot {trend}',
            'raw_value': trend
        }


class SessionMemoryRule(VotingRule):
    """Session Memory规则"""

    def __init__(self, session_memory, weight: float = 1.0):
        super().__init__('Session Memory', weight)
        self.session_memory = session_memory

    def evaluate(self, price: float, rsi: float, oracle: Dict = None,
                 price_history: List[float] = None, **kwargs) -> Optional[Dict]:
        if not self.session_memory:
            return None

        try:
            market_features = {
                'price': price,
                'rsi': rsi,
                'oracle': oracle or {},  # 传递完整的oracle字典（包含cvd_5m等）
                'price_history': price_history or []
            }

            features = self.session_memory.extract_session_features(market_features)
            prior_bias, _ = self.session_memory.calculate_prior_bias(features)

            if abs(prior_bias) < 0.3:
                return None  # 先验偏差太小，不投票

            direction = 'LONG' if prior_bias > 0 else 'SHORT'
            confidence = min(abs(prior_bias), 0.99)
            reason = f'历史先验 {prior_bias:+.2f}'

            return {
                'direction': direction,
                'confidence': confidence,
                'reason': reason,
                'raw_value': prior_bias
            }
        except Exception as e:
            # Session Memory失败，不投票
            return None


class MomentumAccelerationRule(VotingRule):
    """动量加速度规则（超短动量的变化率）"""

    def __init__(self, weight: float = 1.0):
        super().__init__('Momentum Acceleration', weight)

    def evaluate(self, oracle: Dict = None, **kwargs) -> Optional[Dict]:
        """
        计算动量加速度：30s→60s→120s的变化趋势

        加速度 > 0: 动量在增强
        加速度 < 0: 动量在减弱
        """
        if not oracle:
            return None

        mom_30 = oracle.get('momentum_30s', 0.0)
        mom_60 = oracle.get('momentum_60s', 0.0)
        mom_120 = oracle.get('momentum_120s', 0.0)

        # 如果任何一个动量为0，无法计算加速度
        if mom_30 == 0.0 or mom_60 == 0.0 or mom_120 == 0.0:
            return None

        # 计算加速度（60s相对于30s的变化）
        accel_1 = mom_60 - mom_30

        # 计算加速度（120s相对于60s的变化）
        accel_2 = mom_120 - mom_60

        # 综合加速度（平均变化）
        acceleration = (accel_1 + accel_2) / 2.0

        # 加速度阈值（0.1%的动量变化）
        threshold = 0.1

        if abs(acceleration) < threshold:
            return None

        direction = 'LONG' if acceleration > 0 else 'SHORT'
        confidence = min(abs(acceleration) / 1.0, 0.99)  # 1.0%变化为满分
        reason = f'加速度{acceleration:+.2f}%'

        return {
            'direction': direction,
            'confidence': confidence,
            'reason': reason,
            'raw_value': acceleration
        }


class MACDHistogramRule(VotingRule):
    """MACD柱状图规则"""

    def __init__(self, weight: float = 1.0):
        super().__init__('MACD Histogram', weight)
        self.fast_period = 12
        self.slow_period = 26
        self.signal_period = 9

    def _calculate_ema(self, data: List[float], period: int) -> float:
        """计算EMA"""
        if len(data) < period:
            return data[-1] if data else 0.0

        multiplier = 2 / (period + 1)
        ema = data[0]
        for price in data[1:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        return ema

    def evaluate(self, price_history: List[float], **kwargs) -> Optional[Dict]:
        """
        计算MACD柱状图

        简化版本：直接使用 MACD 线（快慢 EMA 差值）
        MACD > 0: 牛市
        MACD < 0: 熊市
        """
        if len(price_history) < self.slow_period:
            return None

        # 计算快慢EMA
        ema_fast = self._calculate_ema(price_history, self.fast_period)
        ema_slow = self._calculate_ema(price_history, self.slow_period)

        # MACD线（简化版：不计算信号线和柱状图）
        macd_line = ema_fast - ema_slow

        # MACD阈值
        if abs(macd_line) < 0.001:
            return None

        direction = 'LONG' if macd_line > 0 else 'SHORT'
        confidence = min(abs(macd_line) / 0.01, 0.99)
        reason = f'MACD{macd_line:+.4f}'

        return {
            'direction': direction,
            'confidence': confidence,
            'reason': reason,
            'raw_value': macd_line
        }


class EMACrossRule(VotingRule):
    """EMA交叉规则"""

    def __init__(self, weight: float = 1.0):
        super().__init__('EMA Cross', weight)
        self.ema_fast_period = 9
        self.ema_slow_period = 21

    def _calculate_ema(self, data: List[float], period: int) -> float:
        """计算EMA"""
        if len(data) < period:
            return data[-1] if data else 0.0

        multiplier = 2 / (period + 1)
        ema = data[0]
        for price in data[1:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        return ema

    def evaluate(self, price_history: List[float], **kwargs) -> Optional[Dict]:
        """
        EMA 9/21 交叉信号

        快线 > 慢线: 做多
        快线 < 慢线: 做空
        """
        if len(price_history) < self.ema_slow_period:
            return None

        ema_fast = self._calculate_ema(price_history, self.ema_fast_period)
        ema_slow = self._calculate_ema(price_history, self.ema_slow_period)

        # EMA差值
        ema_diff = ema_fast - ema_slow

        # EMA差值阈值（相对于价格）
        price = price_history[-1]
        ema_diff_pct = (ema_diff / price) * 100 if price > 0 else 0

        if abs(ema_diff_pct) < 0.1:
            return None

        direction = 'LONG' if ema_fast > ema_slow else 'SHORT'
        confidence = min(abs(ema_diff_pct) / 1.0, 0.99)
        reason = f'EMA{self.ema_fast_period}/{self.ema_slow_period} {ema_diff_pct:+.2f}%'

        return {
            'direction': direction,
            'confidence': confidence,
            'reason': reason,
            'raw_value': ema_diff_pct
        }


class VolatilityRegimeRule(VotingRule):
    """波动率制度规则"""

    def __init__(self, weight: float = 1.0):
        super().__init__('Volatility Regime', weight)
        self.lookback = 20

    def evaluate(self, price_history: List[float], **kwargs) -> Optional[Dict]:
        """
        判断市场波动率制度

        高波动率: 趋势可能延续
        低波动率: 可能突破
        """
        if len(price_history) < self.lookback:
            return None

        # 计算历史收益率
        returns = []
        for i in range(1, len(price_history)):
            if price_history[i-1] > 0:
                ret = (price_history[i] - price_history[i-1]) / price_history[i-1]
                returns.append(ret)

        if len(returns) < 10:
            return None

        # 计算波动率（标准差）
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        volatility = math.sqrt(variance)

        # 波动率阈值：至少 0.5% 才有意义
        if volatility < 0.005:
            return None  # 波动率太低，不投票

        # 当前价格动量
        recent_returns = returns[-5:] if len(returns) >= 5 else returns
        momentum = sum(recent_returns) / len(recent_returns)

        # 动量阈值：至少 0.1% 才有方向
        if abs(momentum) < 0.001:
            return None

        # 方向基于动量，置信度基于动量强度（不是波动率）
        direction = 'LONG' if momentum > 0 else 'SHORT'
        
        # 置信度 = 动量强度 × 波动率因子
        # 波动率越高，动量越可靠（趋势延续性强）
        volatility_factor = min(volatility / 0.01, 1.5)  # 1% 波动率 = 1.0x, 1.5% = 1.5x
        confidence = min(abs(momentum) / 0.005 * volatility_factor, 0.99)
        
        reason = f'波动率{volatility:.2%} 动量{momentum:+.2%}'

        return {
            'direction': direction,
            'confidence': confidence,
            'reason': reason,
            'raw_value': momentum
        }


class DeltaZScoreRule(VotingRule):
    """Delta Z-Score规则（CVD标准化）"""

    def __init__(self, weight: float = 1.0):
        super().__init__('Delta Z-Score', weight)

    def evaluate(self, oracle: Dict = None, **kwargs) -> Optional[Dict]:
        """
        计算CVD的Z-Score（标准化分数）

        Z-Score > 2: 极度买入压力
        Z-Score < -2: 极度卖出压力
        """
        if not oracle:
            return None

        cvd_5m = oracle.get('cvd_5m', 0.0)

        # CVD均值和标准差（基于历史经验）
        # 5分钟CVD的典型分布：均值0，标准差50000
        cvd_mean = 0.0
        cvd_std = 50000.0

        # 计算Z-Score
        z_score = (cvd_5m - cvd_mean) / cvd_std if cvd_std > 0 else 0

        # Z-Score阈值
        if abs(z_score) < 1.0:
            return None

        direction = 'LONG' if z_score > 0 else 'SHORT'
        confidence = min(abs(z_score) / 3.0, 0.99)
        reason = f'Z-Score{z_score:+.2f}'

        return {
            'direction': direction,
            'confidence': confidence,
            'reason': reason,
            'raw_value': z_score
        }


class PriceTrendRule(VotingRule):
    """价格趋势规则（5周期动量）"""

    def __init__(self, weight: float = 1.0):
        super().__init__('Price Trend 5', weight)
        self.period = 5

    def evaluate(self, price_history: List[float], **kwargs) -> Optional[Dict]:
        """
        5周期价格趋势

        与TrendStrengthRule类似，但更短周期
        """
        if len(price_history) < self.period + 1:
            return None

        recent = price_history[-(self.period+1):]
        trend_pct = (recent[-1] - recent[0]) / recent[0] * 100

        if abs(trend_pct) < 0.3:
            return None

        direction = 'LONG' if trend_pct > 0 else 'SHORT'
        confidence = min(abs(trend_pct) / 2.0, 0.99)
        reason = f'5周期趋势{trend_pct:+.2f}%'

        return {
            'direction': direction,
            'confidence': confidence,
            'reason': reason,
            'raw_value': trend_pct
        }


class TradingIntensityRule(VotingRule):
    """交易强度规则（成交量变化）"""

    def __init__(self, weight: float = 1.0):
        super().__init__('Trading Intensity', weight)

    def evaluate(self, oracle: Dict = None, **kwargs) -> Optional[Dict]:
        """
        交易强度：基于CVD变化率

        CVD快速变化：交易活跃
        CVD缓慢变化：交易平淡
        """
        if not oracle:
            return None

        cvd_1m = oracle.get('cvd_1m', 0.0)
        cvd_5m = oracle.get('cvd_5m', 0.0)

        # 1分钟CVD代表短期强度
        if abs(cvd_1m) < 10000:
            return None  # 交易强度太低

        # 5分钟CVD代表趋势
        if abs(cvd_5m) < 30000:
            return None

        # 计算强度比率
        intensity_ratio = abs(cvd_1m) / max(abs(cvd_5m), 1)

        direction = 'LONG' if cvd_1m > 0 else 'SHORT'

        # 强度比率越高，置信度越高
        confidence = min(intensity_ratio / 0.5, 0.99)
        reason = f'1m CVD{cvd_1m:+.0f} 强度{intensity_ratio:.2f}'

        return {
            'direction': direction,
            'confidence': confidence,
            'reason': reason,
            'raw_value': intensity_ratio
        }


class BidWallsRule(VotingRule):
    """买墙规则（需要订单簿数据）"""

    def __init__(self, weight: float = 1.0):
        super().__init__('Bid Walls', weight)

    def evaluate(self, orderbook: Dict = None, price: float = None, **kwargs) -> Optional[Dict]:
        """
        检测买墙（大单支撑）
        
        买墙：在当前价格下方有大量买单堆积
        意义：强支撑，价格不易下跌
        
        Args:
            orderbook: {'bids': [(price, size), ...], 'asks': [(price, size), ...]}
            price: 当前价格
        """
        if not orderbook or not price:
            return None
        
        bids = orderbook.get('bids', [])
        if not bids or len(bids) < 5:
            return None
        
        # 计算买单总量
        total_bid_size = sum(size for _, size in bids)
        if total_bid_size == 0:
            return None
        
        # 检测买墙：前5档买单中是否有单档占比超过30%
        top_5_bids = bids[:5]
        max_bid_size = max(size for _, size in top_5_bids)
        max_bid_ratio = max_bid_size / total_bid_size
        
        # 买墙阈值：单档占比 > 30%
        if max_bid_ratio < 0.30:
            return None
        
        # 买墙存在 → 支撑强 → 做多
        confidence = min(max_bid_ratio / 0.5, 0.99)  # 30%→60%, 50%→100%
        reason = f'买墙{max_bid_ratio:.0%}（强支撑）'
        
        return {
            'direction': 'LONG',
            'confidence': confidence,
            'reason': reason,
            'raw_value': max_bid_ratio
        }


class AskWallsRule(VotingRule):
    """卖墙规则（需要订单簿数据）"""

    def __init__(self, weight: float = 1.0):
        super().__init__('Ask Walls', weight)

    def evaluate(self, orderbook: Dict = None, price: float = None, **kwargs) -> Optional[Dict]:
        """
        检测卖墙（大单阻力）
        
        卖墙：在当前价格上方有大量卖单堆积
        意义：强阻力，价格不易上涨
        
        Args:
            orderbook: {'bids': [(price, size), ...], 'asks': [(price, size), ...]}
            price: 当前价格
        """
        if not orderbook or not price:
            return None
        
        asks = orderbook.get('asks', [])
        if not asks or len(asks) < 5:
            return None
        
        # 计算卖单总量
        total_ask_size = sum(size for _, size in asks)
        if total_ask_size == 0:
            return None
        
        # 检测卖墙：前5档卖单中是否有单档占比超过30%
        top_5_asks = asks[:5]
        max_ask_size = max(size for _, size in top_5_asks)
        max_ask_ratio = max_ask_size / total_ask_size
        
        # 卖墙阈值：单档占比 > 30%
        if max_ask_ratio < 0.30:
            return None
        
        # 卖墙存在 → 阻力强 → 做空
        confidence = min(max_ask_ratio / 0.5, 0.99)  # 30%→60%, 50%→100%
        reason = f'卖墙{max_ask_ratio:.0%}（强阻力）'
        
        return {
            'direction': 'SHORT',
            'confidence': confidence,
            'reason': reason,
            'raw_value': max_ask_ratio
        }


class OBIRule(VotingRule):
    """订单簿失衡规则（需要订单簿数据）"""

    def __init__(self, weight: float = 1.0):
        super().__init__('Orderbook Imbalance', weight)

    def evaluate(self, orderbook: Dict = None, **kwargs) -> Optional[Dict]:
        """
        计算订单簿失衡（OBI）

        OBI = (买量 - 卖量) / (买量 + 卖量)
        
        OBI > 0.3: 买盘强势，做多
        OBI < -0.3: 卖盘强势，做空
        
        Args:
            orderbook: {'bids': [(price, size), ...], 'asks': [(price, size), ...]}
        """
        if not orderbook:
            return None
        
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])
        
        if not bids or not asks:
            return None
        
        # 计算前10档的买卖量
        top_bids = bids[:10] if len(bids) >= 10 else bids
        top_asks = asks[:10] if len(asks) >= 10 else asks
        
        total_bid_size = sum(size for _, size in top_bids)
        total_ask_size = sum(size for _, size in top_asks)
        
        if total_bid_size + total_ask_size == 0:
            return None
        
        # 计算OBI
        obi = (total_bid_size - total_ask_size) / (total_bid_size + total_ask_size)
        
        # OBI阈值：±0.3
        if abs(obi) < 0.3:
            return None
        
        direction = 'LONG' if obi > 0 else 'SHORT'
        confidence = min(abs(obi) / 0.6, 0.99)  # 0.3→50%, 0.6→100%
        reason = f'OBI{obi:+.2f}（{"买盘" if obi > 0 else "卖盘"}强势）'
        
        return {
            'direction': direction,
            'confidence': confidence,
            'reason': reason,
            'raw_value': obi
        }


class PMSpreadRule(VotingRule):
    """PM价差异常规则（需要Polymarket YES/NO价格）"""

    def __init__(self, weight: float = 1.0):
        super().__init__('PM Spread Dev', weight)

    def evaluate(self, price: float = None, no_price: float = None, **kwargs) -> Optional[Dict]:
        """
        检测YES/NO价差异常

        正常情况：YES + NO ≈ 1.00（允许微小套利空间）
        异常情况：YES + NO > 1.02（价差异常，市场流动性问题）

        价差异常说明市场存在套利机会或流动性不足
        """
        if not price or not no_price:
            return None

        # 计算价差
        spread = price + no_price
        deviation = spread - 1.0

        # 价差异常阈值：> 2%
        if abs(deviation) < 0.02:
            return None

        # 价差过大说明市场不稳定，降低置信度
        confidence = min(abs(deviation) / 0.05, 0.99)  # 2%→40%, 5%→100%

        # 价差异常时，倾向于不做交易（中性投票）
        # 但如果一定要选，选择价格较低的一边（更安全）
        direction = 'LONG' if price < 0.5 else 'SHORT'

        reason = f'价差异常{deviation*100:+.1f}%（YES={price:.2f}+NO={no_price:.2f}）'

        return {
            'direction': direction,
            'confidence': confidence * 0.3,  # 降低置信度（价差异常时风险高）
            'reason': reason,
            'raw_value': deviation
        }


class PMSentimentRule(VotingRule):
    """PM情绪规则（需要Polymarket数据）"""

    def __init__(self, weight: float = 1.0):
        super().__init__('PM Sentiment', weight)

    def evaluate(self, price: float = None, price_history: List[float] = None, **kwargs) -> Optional[Dict]:
        """
        分析Polymarket市场情绪
        
        基于价格变化速度和方向判断市场情绪
        快速上涨 → 乐观情绪 → 做多
        快速下跌 → 悲观情绪 → 做空
        
        Args:
            price: 当前价格
            price_history: 价格历史（最近20个数据点）
        """
        if not price or not price_history or len(price_history) < 10:
            return None
        
        # 计算最近10个周期的价格变化
        recent = price_history[-10:]
        
        # 计算价格变化速度（每周期平均变化）
        price_changes = []
        for i in range(1, len(recent)):
            change_pct = (recent[i] - recent[i-1]) / recent[i-1] * 100
            price_changes.append(change_pct)
        
        if not price_changes:
            return None
        
        # 平均变化率
        avg_change = sum(price_changes) / len(price_changes)
        
        # 变化率标准差（波动性）
        variance = sum((c - avg_change) ** 2 for c in price_changes) / len(price_changes)
        volatility = variance ** 0.5
        
        # 情绪强度 = 平均变化率 × 一致性（低波动 = 高一致性）
        consistency = max(0, 1.0 - volatility / 2.0)  # 波动越小，一致性越高
        sentiment_strength = abs(avg_change) * consistency
        
        # 情绪阈值：0.5%
        if sentiment_strength < 0.5:
            return None
        
        direction = 'LONG' if avg_change > 0 else 'SHORT'
        confidence = min(sentiment_strength / 2.0, 0.99)  # 0.5%→25%, 2.0%→100%
        
        sentiment_label = "乐观" if avg_change > 0 else "悲观"
        reason = f'市场{sentiment_label}（{avg_change:+.2f}%/周期）'
        
        return {
            'direction': direction,
            'confidence': confidence,
            'reason': reason,
            'raw_value': sentiment_strength
        }


class CLDataAgeRule(VotingRule):
    """数据延迟规则（CL = Chainlink）"""

    def __init__(self, weight: float = 0.5):
        super().__init__('CL Data Age', weight)

    def evaluate(self, oracle: Dict = None, **kwargs) -> Optional[Dict]:
        """
        检测Oracle数据延迟

        数据新鲜度影响信号可靠性
        """
        if not oracle:
            return None

        # 检查时间戳
        timestamp = oracle.get('timestamp', 0)
        if timestamp == 0:
            return None

        # 计算数据年龄（秒）
        import time
        data_age = time.time() - timestamp

        # 数据年龄阈值
        if data_age > 10.0:  # 超过10秒，数据过时
            return None  # 不投票（数据不可靠）

        # 数据越新鲜，给予越高置信度
        # 数据年龄 < 3秒：优秀
        # 数据年龄 3-6秒：良好
        # 数据年龄 6-10秒：一般
        if data_age < 3.0:
            # 数据很新鲜，不投票（只是质量检查，不产生方向）
            return None
        elif data_age > 6.0:
            # 数据有点旧，轻微惩罚
            return None

        # 这个规则主要用于数据质量检查，不产生方向性投票
        return None


class PMYesRule(VotingRule):
    """Polymarket YES价格规则"""

    def __init__(self, weight: float = 1.0):
        super().__init__('PM YES', weight)

    def evaluate(self, price: float, **kwargs) -> Optional[Dict]:
        """
        基于YES价格判断市场情绪

        YES价格 > 0.70: 极度看涨
        YES价格 < 0.30: 极度看跌
        """
        if price <= 0 or price >= 1.0:
            return None

        # 价格区间判断
        if price > 0.70:
            # 极度看涨
            confidence = (price - 0.70) / 0.30  # 0.70→0%, 1.00→100%
            confidence = min(confidence, 0.99)
            return {
                'direction': 'LONG',
                'confidence': confidence,
                'reason': f'YES价格{price:.2f}（极度看涨）',
                'raw_value': price
            }
        elif price < 0.30:
            # 极度看跌
            confidence = (0.30 - price) / 0.30  # 0.30→0%, 0.00→100%
            confidence = min(confidence, 0.99)
            return {
                'direction': 'SHORT',
                'confidence': confidence,
                'reason': f'YES价格{price:.2f}（极度看跌）',
                'raw_value': price
            }

        # 价格在中性区间（0.30-0.70），不投票
        return None


class BiasScoreRule(VotingRule):
    """综合偏差分数规则"""

    def __init__(self, weight: float = 1.0):
        super().__init__('Bias Score', weight)

    def evaluate(self, rsi: float = None, vwap: float = None,
                 price: float = None, price_history: List[float] = None,
                 **kwargs) -> Optional[Dict]:
        """
        综合多个指标的偏差分数

        考虑因素：
        1. RSI偏离50的程度
        2. 价格偏离VWAP的程度
        3. 价格动量趋势
        """
        if rsi is None or vwap is None or price is None:
            return None

        bias = 0.0
        factors = 0

        # 1. RSI偏差
        if rsi > 50:
            rsi_bias = (rsi - 50) / 50.0  # 0 to +1
            bias += rsi_bias * 2.0  # 权重2.0
            factors += 1
        elif rsi < 50:
            rsi_bias = (50 - rsi) / 50.0  # 0 to +1
            bias -= rsi_bias * 2.0  # 负向
            factors += 1

        # 2. VWAP偏离
        if vwap > 0:
            vwap_dev_pct = ((price - vwap) / vwap) * 100
            # 标准化：±5%为极限
            vwap_bias = max(-1.0, min(1.0, vwap_dev_pct / 5.0))
            bias += vwap_bias * 1.5  # 权重1.5
            factors += 1

        # 3. 价格动量（如果有历史数据）
        if price_history and len(price_history) >= 5:
            recent = price_history[-5:]
            momentum = (recent[-1] - recent[0]) / recent[0] * 100
            # 标准化：±3%为极限
            momentum_bias = max(-1.0, min(1.0, momentum / 3.0))
            bias += momentum_bias * 1.0  # 权重1.0
            factors += 1

        if factors == 0:
            return None

        # 综合偏差
        bias_score = bias / factors

        # 偏差阈值
        if abs(bias_score) < 0.5:
            return None

        direction = 'LONG' if bias_score > 0 else 'SHORT'
        confidence = min(abs(bias_score) / 2.0, 0.99)
        reason = f'综合偏差{bias_score:+.2f}'

        return {
            'direction': direction,
            'confidence': confidence,
            'reason': reason,
            'raw_value': bias_score
        }


class PMSpreadDevRule(VotingRule):
    """YES/NO价差异常规则"""

    def __init__(self, weight: float = 0.8):
        super().__init__('PM Spread Dev', weight)

    def evaluate(self, price: float = None, no_price: float = None, **kwargs) -> Optional[Dict]:
        """
        检测YES/NO价差异常

        正常情况：YES + NO ≈ 1.00
        异常情况：YES + NO > 1.02（市场低效，套利机会）

        异常价差意味着市场低效，可能反转
        """
        if price is None:
            return None

        # 如果没有传入no_price，计算它
        if no_price is None:
            no_price = 1.0 - price

        # 计算价差
        spread = price + no_price

        # 价差异常阈值
        if spread < 1.01:
            return None  # 价差正常，不投票

        if spread > 1.02:
            # 价差异常（市场低效）
            # 当价差异常时，倾向于SHORT（反转信号）
            confidence = min((spread - 1.02) / 0.05, 0.99)
            return {
                'direction': 'SHORT',
                'confidence': confidence,
                'reason': f'价差异常{spread:.3f}（市场低效）',
                'raw_value': spread
            }

        # 价差1.01-1.02：轻微异常
        return None


class NaturalPriceRule(VotingRule):
    """自然价格规则（需要订单簿数据）"""

    def __init__(self, weight: float = 1.0):
        super().__init__('NATURAL', weight)

    def evaluate(self, orderbook: Dict = None, price: float = None, **kwargs) -> Optional[Dict]:
        """
        计算自然价格（远离大单的价格）
        
        自然价格：排除异常大单后的加权平均价格
        如果当前价格偏离自然价格，可能是大单操纵
        
        Args:
            orderbook: {'bids': [(price, size), ...], 'asks': [(price, size), ...]}
            price: 当前价格
        """
        if not orderbook or not price:
            return None
        
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])
        
        if not bids or not asks:
            return None
        
        # 计算买卖单的加权平均价格（排除前2档大单）
        filtered_bids = bids[2:12] if len(bids) > 2 else bids
        filtered_asks = asks[2:12] if len(asks) > 2 else asks
        
        if not filtered_bids or not filtered_asks:
            return None
        
        # 加权平均价格
        bid_weighted_sum = sum(p * s for p, s in filtered_bids)
        bid_total_size = sum(s for _, s in filtered_bids)
        
        ask_weighted_sum = sum(p * s for p, s in filtered_asks)
        ask_total_size = sum(s for _, s in filtered_asks)
        
        if bid_total_size == 0 or ask_total_size == 0:
            return None
        
        avg_bid = bid_weighted_sum / bid_total_size
        avg_ask = ask_weighted_sum / ask_total_size
        
        # 自然价格 = 买卖加权平均的中点
        natural_price = (avg_bid + avg_ask) / 2.0
        
        # 计算偏离度
        deviation_pct = ((price - natural_price) / natural_price) * 100
        
        # 偏离阈值：±1%
        if abs(deviation_pct) < 1.0:
            return None
        
        # 当前价格 > 自然价格：被拉高，做空
        # 当前价格 < 自然价格：被压低，做多
        direction = 'SHORT' if deviation_pct > 0 else 'LONG'
        confidence = min(abs(deviation_pct) / 3.0, 0.99)  # 1%→33%, 3%→100%
        reason = f'偏离自然价{deviation_pct:+.2f}%'
        
        return {
            'direction': direction,
            'confidence': confidence,
            'reason': reason,
            'raw_value': deviation_pct
        }


class NaturalAbsRule(VotingRule):
    """自然价格绝对值规则（需要订单簿数据）"""

    def __init__(self, weight: float = 1.0):
        super().__init__('NAT ABS', weight)

    def evaluate(self, orderbook: Dict = None, **kwargs) -> Optional[Dict]:
        """
        自然价格的绝对值判断
        
        基于自然价格本身的高低判断市场情绪
        自然价格 > 0.60: 市场看涨
        自然价格 < 0.40: 市场看跌
        
        Args:
            orderbook: {'bids': [(price, size), ...], 'asks': [(price, size), ...]}
        """
        if not orderbook:
            return None
        
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])
        
        if not bids or not asks:
            return None
        
        # 计算自然价格（同NaturalPriceRule）
        filtered_bids = bids[2:12] if len(bids) > 2 else bids
        filtered_asks = asks[2:12] if len(asks) > 2 else asks
        
        if not filtered_bids or not filtered_asks:
            return None
        
        bid_weighted_sum = sum(p * s for p, s in filtered_bids)
        bid_total_size = sum(s for _, s in filtered_bids)
        
        ask_weighted_sum = sum(p * s for p, s in filtered_asks)
        ask_total_size = sum(s for _, s in filtered_asks)
        
        if bid_total_size == 0 or ask_total_size == 0:
            return None
        
        avg_bid = bid_weighted_sum / bid_total_size
        avg_ask = ask_weighted_sum / ask_total_size
        natural_price = (avg_bid + avg_ask) / 2.0
        
        # 基于自然价格绝对值判断
        if natural_price > 0.60:
            # 自然价格高 → 市场看涨 → 跟随做多
            confidence = (natural_price - 0.60) / 0.40  # 0.60→0%, 1.00→100%
            confidence = min(confidence, 0.99)
            return {
                'direction': 'LONG',
                'confidence': confidence,
                'reason': f'自然价{natural_price:.2f}（看涨）',
                'raw_value': natural_price
            }
        elif natural_price < 0.40:
            # 自然价格低 → 市场看跌 → 跟随做空
            confidence = (0.40 - natural_price) / 0.40  # 0.40→0%, 0.00→100%
            confidence = min(confidence, 0.99)
            return {
                'direction': 'SHORT',
                'confidence': confidence,
                'reason': f'自然价{natural_price:.2f}（看跌）',
                'raw_value': natural_price
            }
        
        # 自然价格在中性区间（0.40-0.60），不投票
        return None


class BufferTicketsRule(VotingRule):
    """缓冲订单数量规则（需要订单簿数据）"""

    def __init__(self, weight: float = 1.0):
        super().__init__('BUFFER TICKETS', weight)

    def evaluate(self, orderbook: Dict = None, price: float = None, **kwargs) -> Optional[Dict]:
        """
        统计缓冲区订单数量
        
        缓冲订单：接近当前价格（±2%）的未成交订单
        缓冲订单多 → 流动性好 → 价格稳定
        
        Args:
            orderbook: {'bids': [(price, size), ...], 'asks': [(price, size), ...]}
            price: 当前价格
        """
        if not orderbook or not price:
            return None
        
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])
        
        if not bids or not asks:
            return None
        
        # 定义缓冲区：当前价格 ±2%
        buffer_range = price * 0.02
        lower_bound = price - buffer_range
        upper_bound = price + buffer_range
        
        # 统计缓冲区内的订单数量
        buffer_bids = [s for p, s in bids if lower_bound <= p <= price]
        buffer_asks = [s for p, s in asks if price <= p <= upper_bound]
        
        buffer_bid_count = len(buffer_bids)
        buffer_ask_count = len(buffer_asks)
        total_buffer_count = buffer_bid_count + buffer_ask_count
        
        # 缓冲订单阈值：至少5个订单
        if total_buffer_count < 5:
            return None
        
        # 计算买卖缓冲订单的不平衡
        if buffer_bid_count + buffer_ask_count == 0:
            return None
        
        buffer_imbalance = (buffer_bid_count - buffer_ask_count) / (buffer_bid_count + buffer_ask_count)
        
        # 不平衡阈值：±0.4
        if abs(buffer_imbalance) < 0.4:
            return None
        
        # 买单多 → 支撑强 → 做多
        # 卖单多 → 阻力强 → 做空
        direction = 'LONG' if buffer_imbalance > 0 else 'SHORT'
        confidence = min(abs(buffer_imbalance) / 0.6, 0.99)  # 0.4→67%, 0.6→100%
        reason = f'缓冲订单{total_buffer_count}个（{"买" if buffer_imbalance > 0 else "卖"}盘多）'
        
        return {
            'direction': direction,
            'confidence': confidence,
            'reason': reason,
            'raw_value': buffer_imbalance
        }


class PositionsRule(VotingRule):
    """持仓分析规则（基于Polymarket Data API）"""

    def __init__(self, weight: float = 1.0, wallet_address: str = None, http_session=None):
        super().__init__('POSITIONS', weight)
        self.wallet_address = wallet_address
        self.http_session = http_session

    def evaluate(self, price: float = None, side: str = None, **kwargs) -> Optional[Dict]:
        """
        分析当前持仓状态（避免过度暴露和风险集中）

        使用Polymarket Data API: GET /positions

        策略：
        - 获取当前所有持仓的PnL状态
        - 如果正在连败（连续亏损）→ 降低新开仓置信度
        - 如果当前已有大额持仓 → 降低加仓置信度
        - 如果正在连胜 → 可以适当提高置信度（趋势跟随）

        注意：这个规则返回的是"仓位调整建议"，不是方向性信号
        """
        if not self.wallet_address or not self.http_session:
            return None  # 没有配置钱包地址或HTTP会话，无法获取持仓数据

        try:
            # 获取当前持仓
            url = "https://data-api.polymarket.com/positions"
            params = {"user": self.wallet_address}

            response = self.http_session.get(url, params=params, timeout=3)
            if response.status_code != 200:
                return None

            positions = response.json()

            # 过滤出BTC 15min市场的持仓
            # （通过条件ID匹配，或者检查是否是相关市场）
            total_exposure = 0.0
            winning_positions = 0
            losing_positions = 0
            current_pnl = 0.0

            for pos in positions:
                # 计算总暴露
                size = pos.get('currentValue', 0)
                total_exposure += size

                # 统计盈亏
                pnl = pos.get('cashPnl', 0)
                current_pnl += pnl

                if pnl > 0:
                    winning_positions += 1
                else:
                    losing_positions += 1

            # 如果没有持仓，返回中性
            if total_exposure == 0:
                return None

            # 策略1：检查总暴露（避免过度杠杆）
            max_exposure = 1000  # 最大总暴露（USDC）
            exposure_ratio = min(total_exposure / max_exposure, 1.0)

            # 策略2：检查当前盈亏状态
            total_positions = winning_positions + losing_positions
            win_rate = winning_positions / total_positions if total_positions > 0 else 0.5

            # 策略3：连败检测（最近5笔）
            # 简化版本：如果当前PnL为负且亏损仓位多，降低置信度
            is_drawing_down = current_pnl < -50  # 亏损超过50美元
            is_on_tear = win_rate > 0.6 and total_positions >= 3  # 胜率>60%且至少3笔

            # 生成调整建议
            adjustment = 1.0
            reasons = []

            if exposure_ratio > 0.8:
                adjustment *= 0.5  # 暴露过高，大幅降低
                reasons.append(f"高暴露({total_exposure:.0f}USDC)")
            elif exposure_ratio > 0.5:
                adjustment *= 0.7  # 暴露较高，适度降低
                reasons.append(f"中等暴露({total_exposure:.0f}USDC)")

            if is_drawing_down:
                adjustment *= 0.6  # 正在回撤，降低
                reasons.append(f"回撤中({current_pnl:+.0f})")
            elif is_on_tear:
                adjustment *= 1.2  # 连胜中，可以提高
                reasons.append(f"连胜中({win_rate:.0%})")

            # 如果没有调整，返回中性
            if adjustment >= 0.95 and adjustment <= 1.05:
                return None

            # 返回调整后的置信度（保持原有方向）
            confidence = min(adjustment, 0.99)

            # 注意：这个规则不改变方向，只调整置信度
            # 但为了让投票系统工作，我们需要返回一个方向
            # 这里返回当前建议的方向，置信度已经调整过了
            direction = side or 'LONG'

            reason = f"持仓调整 {adjustment:.0%} ({', '.join(reasons)})"

            return {
                'direction': direction,
                'confidence': confidence,
                'reason': reason,
                'raw_value': adjustment,
                'is_adjustment': True  # 标记这是调整规则，不是方向规则
            }

        except Exception as e:
            # API调用失败，静默返回None
            return None



class VotingSystem:
    """投票系统引擎"""

    def __init__(self):
        self.rules = []
        self.enabled_rule_count = 0

    def add_rule(self, rule: VotingRule):
        """添加规则"""
        self.rules.append(rule)
        if rule.enabled:
            self.enabled_rule_count += 1

    def collect_votes(self, **kwargs) -> List[Dict]:
        """
        收集所有规则的投票

        返回: [
            {
                'rule_name': 'Price Momentum',
                'direction': 'LONG',
                'confidence': 0.70,
                'reason': '上涨+2.5%',
                'weight': 1.0
            },
            ...
        ]
        """
        votes = []

        for rule in self.rules:
            if not rule.enabled:
                continue

            try:
                vote = rule.evaluate(**kwargs)
                if vote and vote['direction'] != 'NEUTRAL':
                    votes.append({
                        'rule_name': rule.name,
                        'direction': vote['direction'],
                        'confidence': vote['confidence'],
                        'reason': vote.get('reason', ''),
                        'weight': rule.weight
                    })
            except Exception as e:
                # 规则评估失败，跳过
                print(f"  [WARN] Rule {rule.name} failed: {e}")
                continue

        return votes

    def aggregate_votes(self, votes: List[Dict]) -> Optional[Dict]:
        """
        聚合投票结果（图片平台方式）

        步骤：
        1. 按方向分组
        2. 计算每个方向的加权平均置信度
        3. 赢家方向 = 投票数更多的方向（多数投票）
        4. 最终置信度 = 赢家方向的加权平均置信度

        返回: {
            'direction': 'LONG',
            'confidence': 0.68,
            'long_votes': 6,
            'short_votes': 2,
            'long_confidence': 0.70,
            'short_confidence': 0.45,
            'total_votes': 8
        }
        """
        if not votes:
            return None

        # 按方向分组
        long_votes = [v for v in votes if v['direction'] == 'LONG']
        short_votes = [v for v in votes if v['direction'] == 'SHORT']

        # 计算加权平均置信度
        long_weighted_sum = sum(v['confidence'] * v['weight'] for v in long_votes)
        long_total_weight = sum(v['weight'] for v in long_votes)
        long_confidence = long_weighted_sum / long_total_weight if long_total_weight > 0 else 0

        short_weighted_sum = sum(v['confidence'] * v['weight'] for v in short_votes)
        short_total_weight = sum(v['weight'] for v in short_votes)
        short_confidence = short_weighted_sum / short_total_weight if short_total_weight > 0 else 0

        # 赢家方向 = 投票数更多的方向（多数投票原则）
        # 如果投票数相同，置信度高的方向赢
        if len(long_votes) > len(short_votes):
            final_direction = 'LONG'
            final_confidence = long_confidence
        elif len(short_votes) > len(long_votes):
            final_direction = 'SHORT'
            final_confidence = short_confidence
        else:
            # 投票数相同，置信度高的方向赢
            if long_confidence >= short_confidence:
                final_direction = 'LONG'
                final_confidence = long_confidence
            else:
                final_direction = 'SHORT'
                final_confidence = short_confidence

        return {
            'direction': final_direction,
            'confidence': final_confidence,
            'long_votes': len(long_votes),
            'short_votes': len(short_votes),
            'long_confidence': long_confidence,
            'short_confidence': short_confidence,
            'total_votes': len(votes)
        }

    def decide(self, min_confidence: float = 0.60,
               min_votes: int = 3, **kwargs) -> Optional[Dict]:
        """
        最终决策

        返回: {
            'direction': 'LONG',
            'confidence': 0.68,
            'vote_details': {...},
            'passed_gate': True
        }
        """
        # 收集投票
        votes = self.collect_votes(**kwargs)

        if not votes:
            return None

        # 打印投票结果
        print(f"\n       [VOTING] 规则投票 ({len(votes)}个规则参与):")
        for i, vote in enumerate(votes, 1):
            icon = "" if vote['direction'] == 'LONG' else ""
            print(f"         {i}. {icon} {vote['rule_name']:15s}: {vote['direction']:4s} {vote['confidence']:>6.0%} - {vote['reason']}")

        # 聚合投票
        result = self.aggregate_votes(votes)

        if not result:
            return None

        # 打印聚合结果
        print(f"\n       [AGGREGATION] 投票统计:")
        print(f"         LONG:  {result['long_votes']}票 (加权置信度{result['long_confidence']:.0%})")
        print(f"         SHORT: {result['short_votes']}票 (加权置信度{result['short_confidence']:.0%})")
        print(f"         最终方向: {result['direction']:4s} | 置信度: {result['confidence']:.0%}")

        # 检查门槛
        if result['total_votes'] < min_votes:
            print(f"         [REJECT] 投票数{result['total_votes']} < 门槛{min_votes}")
            return None

        if result['confidence'] < min_confidence:
            print(f"         [REJECT] 置信度{result['confidence']:.0%} < 门槛{min_confidence:.0%}")
            return None

        result['passed_gate'] = True
        result['all_votes'] = votes

        return result


def create_voting_system(session_memory=None, wallet_address=None, http_session=None) -> VotingSystem:
    """
    创建投票系统实例（Layer 2: 信号层）

    三层架构：
    - Layer 1: Session Memory (先验层) - 在auto_trader_ankr.py中独立调用
    - Layer 2: 投票系统 (信号层) - 本函数创建的30个规则
    - Layer 3: 防御层 (风险控制) - 在auto_trader_ankr.py中独立调用

    总计30个规则（全部激活）：
    - 超短动量x3：30s/60s/120s 精确时间窗口
    - 技术指标x8：Price Momentum, Price Trend, RSI, VWAP, Trend Strength, MACD, EMA, 波动率
    - CVD指标x3：5m CVD (3.0x权重), 1m CVD, Delta Z-Score
    - 高级指标x2：动量加速度, 交易强度
    - PM指标x6：CL Data Age, PM YES, Bias Score, PM Spread Dev, PM Sentiment, PM Spread
    - 趋势指标x1：UT Bot（Session Memory已移至Layer 1）
    - 订单簿x7：买墙, 卖墙, OBI, 自然价格, 自然绝对值, 缓冲订单
    - 持仓规则x1：Positions（当前暴露管理）

    Args:
        session_memory: SessionMemory实例（已废弃，保留参数仅为兼容性）
        wallet_address: Polymarket钱包地址（用于PositionsRule）
        http_session: requests.Session实例（用于PositionsRule的API调用）
    """
    system = VotingSystem()

    # ==========================================
    # 超短动量规则（使用币安真实数据：30s/60s/120s）
    # ==========================================
    system.add_rule(UltraShortMomentumRule(30, 'Momentum 30s', weight=0.8))    # 30秒精确时间窗口
    system.add_rule(UltraShortMomentumRule(60, 'Momentum 60s', weight=0.9))    # 60秒精确时间窗口
    system.add_rule(UltraShortMomentumRule(120, 'Momentum 120s', weight=1.0))  # 120秒精确时间窗口

    # ==========================================
    # 标准技术指标（低权重）
    # ==========================================
    system.add_rule(PriceMomentumRule(weight=1.0))      # 价格动量（10周期）
    system.add_rule(PriceTrendRule(weight=0.8))         # 价格趋势（5周期，短期）
    system.add_rule(RSIRule(weight=0.3))                # RSI 14（降为低权重）
    system.add_rule(VWAPRule(weight=0.3))               # VWAP偏离（降为低权重）
    system.add_rule(TrendStrengthRule(weight=0.3))      # 趋势强度（降为低权重）

    # ==========================================
    # [CVD强化] 参考 @jtrevorchapman: CVD是预测力最强的单一指标
    # ==========================================
    system.add_rule(OracleCVDRule('5m', weight=3.0))    # 5分钟CVD：最强指标（3.0x权重）
    system.add_rule(OracleCVDRule('1m', weight=1.5))    # 1分钟CVD：即时动量
    system.add_rule(DeltaZScoreRule(weight=1.2))        # Delta Z-Score：CVD标准化

    # ==========================================
    # 高级技术指标（降为低权重）
    # ==========================================
    system.add_rule(MomentumAccelerationRule(weight=1.2))   # 动量加速度：超短动量的变化率
    system.add_rule(MACDHistogramRule(weight=0.3))          # MACD柱状图：趋势转折点（降为低权重）
    system.add_rule(EMACrossRule(weight=0.3))               # EMA交叉：EMA9/21（降为低权重）
    system.add_rule(VolatilityRegimeRule(weight=0.3))       # 波动率制度：高/低波动（降为低权重）
    system.add_rule(TradingIntensityRule(weight=0.3))       # 交易强度：成交量变化（降为低权重）

    # ==========================================
    # 新增指标（降为低权重）
    # ==========================================
    system.add_rule(CLDataAgeRule(weight=0.3))         # 数据延迟（降为低权重）
    system.add_rule(PMYesRule(weight=0.3))             # PM YES价格情绪（降为低权重）
    system.add_rule(BiasScoreRule(weight=1.0))         # 综合偏差分数（保持中等权重）
    system.add_rule(PMSpreadDevRule(weight=0.3))       # YES/NO价差异常（降为低权重）

    # ==========================================
    # 趋势指标
    # ==========================================
    # 注意：Session Memory已移至Layer 1（独立先验层），不再是投票规则之一
    system.add_rule(UTBotTrendRule(weight=0.3))  # UT Bot 15m趋势（降为低权重）

    # ==========================================
    # 市场微观结构规则（保持OBI中等，其他降为低权重）
    # ==========================================
    system.add_rule(BidWallsRule(weight=0.3))           # 买墙（降为低权重）
    system.add_rule(AskWallsRule(weight=0.3))           # 卖墙（降为低权重）
    system.add_rule(OBIRule(weight=1.0))                # 订单簿失衡：买卖力量对比（保持中等）
    system.add_rule(NaturalPriceRule(weight=0.3))       # 自然价格（降为低权重）
    system.add_rule(NaturalAbsRule(weight=0.3))         # 自然价格绝对值（降为低权重）
    system.add_rule(BufferTicketsRule(weight=0.3))      # 缓冲订单（降为低权重）

    # ==========================================
    # Polymarket特定规则（降为低权重）
    # ==========================================
    system.add_rule(PMSpreadRule(weight=0.3))           # PM价差异常（降为低权重）
    system.add_rule(PMSentimentRule(weight=0.3))        # PM情绪（降为低权重）
    system.add_rule(PositionsRule(weight=0.3, wallet_address=wallet_address, http_session=http_session))  # 持仓分析（降为低权重）

    # 总权重：25.5x（全部30个规则已激活，Session Memory已移至Layer 1）
    # CVD权重占比：5.7x / 25.5x = 22.4%（仍然主导）

    return system



# 测试代码
if __name__ == "__main__":
    # 模拟数据（Polymarket 价格历史）
    price_history = [
        0.320, 0.325, 0.330, 0.335, 0.340,  # 1-5 (上升)
        0.338, 0.342, 0.345, 0.350, 0.355,  # 6-10 (继续上升)
        0.352, 0.358, 0.360, 0.365, 0.370,  # 11-15 (加速上升)
        0.368, 0.372, 0.375, 0.378, 0.380   # 16-20 (稳定上升)
    ]

    #  模拟币安超短动量数据（真实精确时间）
    oracle = {
        'signal_score': 4.27,
        'cvd_5m': 120000,
        'cvd_1m': 45000,
        'ut_hull_trend': 'LONG',
        #  新增：币安超短动量（精确30s/60s/120s）- 强动量场景
        'momentum_30s': 1.25,   # 30秒内上涨1.25%（强动量）
        'momentum_60s': 2.48,   # 60秒内上涨2.48%（强动量）
        'momentum_120s': 3.82,  # 120秒内上涨3.82%（强动量）
    }

    print(f"Polymarket价格历史趋势: {price_history[0]:.3f} → {price_history[-1]:.3f} ({((price_history[-1]-price_history[0])/price_history[0]*100):+.1f}%)")
    print(f"\n 币安超短动量（真实精确时间）:")
    print(f"  30s动量: {oracle['momentum_30s']:+.2f}%")
    print(f"  60s动量: {oracle['momentum_60s']:+.2f}%")
    print(f"  120s动量: {oracle['momentum_120s']:+.2f}%")

    # 创建投票系统（不使用Session Memory，避免数据库错误）
    system = create_voting_system(session_memory=None)

    # 决策
    result = system.decide(
        min_confidence=0.60,
        min_votes=3,
        price=0.38,
        rsi=42.0,
        vwap=0.35,
        price_history=price_history,
        oracle=oracle
    )

    if result:
        print(f"\n✅ 最终决策: {result['direction']} | 置信度: {result['confidence']:.0%}")
    else:
        print(f"\n❌ 无明确信号")
