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
            # 从oracle中提取oracle_score
            oracle_score = 0.0
            if oracle:
                oracle_score = oracle.get('signal_score', 0.0)

            market_features = {
                'price': price,
                'rsi': rsi,
                'oracle_score': oracle_score,
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

        # 计算加速度（60s相对于30s的变化率）
        accel_1 = (mom_60 - mom_30) / 30.0 if mom_30 != 0 else 0

        # 计算加速度（120s相对于60s的变化率）
        accel_2 = (mom_120 - mom_60) / 60.0 if mom_60 != 0 else 0

        # 综合加速度
        acceleration = (accel_1 + accel_2) / 2.0

        # 加速度阈值（0.05%每秒的平方）
        threshold = 0.05

        if abs(acceleration) < threshold:
            return None

        direction = 'LONG' if acceleration > 0 else 'SHORT'
        confidence = min(abs(acceleration) / 0.5, 0.99)
        reason = f'加速度{acceleration:+.3f}%/s²'

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

        Histogram > 0: 牛市
        Histogram < 0: 熊市
        Histogram柱子增长：趋势加强
        """
        if len(price_history) < self.slow_period + self.signal_period:
            return None

        # 计算快慢EMA
        ema_fast = self._calculate_ema(price_history, self.fast_period)
        ema_slow = self._calculate_ema(price_history, self.slow_period)

        # MACD线
        macd_line = ema_fast - ema_slow

        # 需要历史MACD值来计算信号线
        # 这里简化处理：使用当前MACD作为信号线估计
        signal_line = macd_line * 0.8  # 简化估计

        # MACD柱状图
        histogram = macd_line - signal_line

        # 柱状图阈值
        if abs(histogram) < 0.001:
            return None

        direction = 'LONG' if histogram > 0 else 'SHORT'
        confidence = min(abs(histogram) / 0.01, 0.99)
        reason = f'MACD柱{histogram:+.4f}'

        return {
            'direction': direction,
            'confidence': confidence,
            'reason': reason,
            'raw_value': histogram
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

        # 波动率阈值
        if volatility < 0.005:  # 0.5%以下为低波动
            return None  # 波动率太低，不投票

        # 当前价格动量
        recent_returns = returns[-5:] if len(returns) >= 5 else returns
        momentum = sum(recent_returns) / len(recent_returns)

        # 波动率越高，跟随趋势的置信度越高
        if abs(momentum) < 0.001:
            return None

        direction = 'LONG' if momentum > 0 else 'SHORT'
        confidence = min(volatility / 0.02, 0.99)
        reason = f'波动率{volatility:.2%} 动量{momentum:+.2%}'

        return {
            'direction': direction,
            'confidence': confidence,
            'reason': reason,
            'raw_value': volatility
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

    def evaluate(self, **kwargs) -> Optional[Dict]:
        """
        检测买墙（大单支撑）

        [占位规则] 需要Polymarket订单簿数据，暂时不投票
        """
        # TODO: 实现买墙检测逻辑
        # 需要订单簿数据： bids at different price levels
        return None  # 不投票（占位）


class AskWallsRule(VotingRule):
    """卖墙规则（需要订单簿数据）"""

    def __init__(self, weight: float = 1.0):
        super().__init__('Ask Walls', weight)

    def evaluate(self, **kwargs) -> Optional[Dict]:
        """
        检测卖墙（大单阻力）

        [占位规则] 需要Polymarket订单簿数据，暂时不投票
        """
        # TODO: 实现卖墙检测逻辑
        # 需要订单簿数据： asks at different price levels
        return None  # 不投票（占位）


class OBIRule(VotingRule):
    """订单簿失衡规则（需要订单簿数据）"""

    def __init__(self, weight: float = 1.0):
        super().__init__('Orderbook Imbalance', weight)

    def evaluate(self, **kwargs) -> Optional[Dict]:
        """
        计算订单簿失衡（OBI）

        OBI = (买量 - 卖量) / (买量 + 卖量)

        [占位规则] 需要Polymarket订单簿数据，暂时不投票
        """
        # TODO: 实现OBI计算逻辑
        return None  # 不投票（占位）


class PMSpreadRule(VotingRule):
    """PM价差异常规则（需要Polymarket数据）"""

    def __init__(self, weight: float = 1.0):
        super().__init__('PM Spread Dev', weight)

    def evaluate(self, price: float = None, no_price: float = None, **kwargs) -> Optional[Dict]:
        """
        检测YES/NO价差异常

        正常情况：YES + NO ≈ 1.00
        异常情况：YES + NO > 1.00（套利机会）

        [占位规则] 需要Polymarket YES/NO实时价格，暂时不投票
        """
        # TODO: 实现价差异常检测
        # if no_price:
        #     spread = price + no_price
        #     if spread > 1.02:  # 价差异常
        #         return {'direction': ..., 'confidence': ...}
        return None  # 不投票（占位）


class PMSentimentRule(VotingRule):
    """PM情绪规则（需要Polymarket数据）"""

    def __init__(self, weight: float = 1.0):
        super().__init__('PM Sentiment', weight)

    def evaluate(self, **kwargs) -> Optional[Dict]:
        """
        分析Polymarket市场情绪

        基于交易量、持仓量、价格变化等

        [占位规则] 需要Polymarket历史数据，暂时不投票
        """
        # TODO: 实现情绪分析逻辑
        return None  # 不投票（占位）



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


def create_voting_system(session_memory=None) -> VotingSystem:
    """
    创建投票系统实例（按照@jtrevorchapman的21个指标设计）

    总计21个规则：
    - 已实现（16个）：超短动量x3、价格动量、RSI、VWAP、趋势强度、CVDx2、UT Bot、Session Memory、
                      动量加速度、MACD柱状图、EMA交叉、波动率、Delta Z-Score、价格趋势x5、交易强度
    - 占位规则（5个）：买墙、卖墙、订单簿失衡、PM价差、PM情绪
    """
    system = VotingSystem()

    # ==========================================
    # 超短动量规则（使用币安真实数据：30s/60s/120s）
    # ==========================================
    system.add_rule(UltraShortMomentumRule(30, 'Momentum 30s', weight=0.8))    # 30秒精确时间窗口
    system.add_rule(UltraShortMomentumRule(60, 'Momentum 60s', weight=0.9))    # 60秒精确时间窗口
    system.add_rule(UltraShortMomentumRule(120, 'Momentum 120s', weight=1.0))  # 120秒精确时间窗口

    # ==========================================
    # 标准技术指标
    # ==========================================
    system.add_rule(PriceMomentumRule(weight=1.0))      # 价格动量（10周期）
    system.add_rule(PriceTrendRule(weight=0.8))         # 价格趋势（5周期，短期）
    system.add_rule(RSIRule(weight=1.0))                # RSI 14
    system.add_rule(VWAPRule(weight=1.0))               # VWAP偏离
    system.add_rule(TrendStrengthRule(weight=1.0))      # 趋势强度（3周期）

    # ==========================================
    # [CVD强化] 参考 @jtrevorchapman: CVD是预测力最强的单一指标
    # ==========================================
    system.add_rule(OracleCVDRule('5m', weight=3.0))    # 5分钟CVD：最强指标（3.0x权重）
    system.add_rule(OracleCVDRule('1m', weight=1.5))    # 1分钟CVD：即时动量
    system.add_rule(DeltaZScoreRule(weight=1.2))        # Delta Z-Score：CVD标准化

    # ==========================================
    # 高级技术指标（新增7个）
    # ==========================================
    system.add_rule(MomentumAccelerationRule(weight=1.2))   # 动量加速度：超短动量的变化率
    system.add_rule(MACDHistogramRule(weight=1.0))          # MACD柱状图：趋势转折点
    system.add_rule(EMACrossRule(weight=0.9))               # EMA交叉：EMA9/21
    system.add_rule(VolatilityRegimeRule(weight=0.8))       # 波动率制度：高/低波动
    system.add_rule(TradingIntensityRule(weight=1.0))       # 交易强度：成交量变化

    # ==========================================
    # 趋势指标
    # ==========================================
    system.add_rule(UTBotTrendRule(weight=1.0))         # UT Bot 15m趋势（已禁用硬锁，仅投票）
    system.add_rule(SessionMemoryRule(session_memory, weight=1.0))  # Session Memory：30场先验

    # ==========================================
    # 占位规则（需要Polymarket订单簿数据，暂时不投票）
    # ==========================================
    system.add_rule(BidWallsRule(weight=1.0))           # 买墙：需要订单簿数据
    system.add_rule(AskWallsRule(weight=1.0))           # 卖墙：需要订单簿数据
    system.add_rule(OBIRule(weight=1.0))                # 订单簿失衡：需要订单簿数据
    system.add_rule(PMSpreadRule(weight=1.0))           # PM价差异常：需要YES/NO价格
    system.add_rule(PMSentimentRule(weight=1.0))        # PM情绪：需要Polymarket历史数据

    # 总权重：22.3x（未激活的占位规则不影响）
    # CVD权重占比：4.5x / 22.3x = 20.2%（主导地位）

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
