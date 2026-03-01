#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投票系统引擎 - 模仿图片平台的简单投票机制

每个规则独立投票 -> 聚合 -> 最终决策
"""

import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from typing import Dict, List, Optional
from datetime import datetime


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
    """创建投票系统实例"""
    system = VotingSystem()

    #  超短动量规则（使用币安真实数据：30s/60s/120s）
    system.add_rule(UltraShortMomentumRule(30, 'Momentum 30s', weight=0.8))    # 30秒精确时间窗口
    system.add_rule(UltraShortMomentumRule(60, 'Momentum 60s', weight=0.9))    # 60秒精确时间窗口
    system.add_rule(UltraShortMomentumRule(120, 'Momentum 120s', weight=1.0))  # 120秒精确时间窗口

    # 标准规则
    system.add_rule(PriceMomentumRule(weight=1.0))
    system.add_rule(RSIRule(weight=1.0))
    system.add_rule(VWAPRule(weight=1.0))
    system.add_rule(TrendStrengthRule(weight=1.0))

    # [CVD强化] 参考 @jtrevorchapman: CVD是预测力最强的单一指标
    # 大幅提高CVD权重：从1.2x提升到3.0x（2.5倍）
    system.add_rule(OracleCVDRule('5m', weight=3.0))  # 5分钟CVD：最强指标
    system.add_rule(OracleCVDRule('1m', weight=1.5))  # 1分钟CVD：即时动量

    system.add_rule(UTBotTrendRule(weight=1.0))
    system.add_rule(SessionMemoryRule(session_memory, weight=1.0))

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
