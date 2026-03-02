#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投票系统规则配置
每个规则独立投票 YES/NO + 置信度
"""

import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# 规则配置模板
SIGNAL_RULES = [
    {
        'name': 'Price Momentum',
        'description': '10周期价格动量',
        'enabled': True,
        'min_confidence_to_vote': 0.3,
        'weight': 0.8  # 🔧 降低技术指标权重
    },
    {
        'name': 'RSI Status',
        'description': 'RSI超买超卖判断',
        'enabled': True,
        'min_confidence_to_vote': 0.3,
        'weight': 0.5  # 🔧 RSI只是辅助防呆，降低权重
    },
    {
        'name': 'VWAP Deviation',
        'description': 'VWAP偏离度',
        'enabled': True,
        'min_confidence_to_vote': 0.3,
        'weight': 0.8  # 🔧 降低技术指标权重
    },
    {
        'name': 'Trend Strength',
        'description': '3周期趋势强度',
        'enabled': True,
        'min_confidence_to_vote': 0.3,
        'weight': 0.5  # 🔧 趋势只是辅助，降低权重
    },
    {
        'name': 'Oracle 5m CVD',
        'description': 'Oracle 5分钟CVD - 真金白银的主力动向',
        'enabled': True,
        'min_confidence_to_vote': 0.4,
        'weight': 3.0  # 🚀 CVD统治级权重！预测力最强的单一指标
    },
    {
        'name': 'Oracle 1m CVD',
        'description': 'Oracle 1分钟CVD - 即时订单流',
        'enabled': True,
        'min_confidence_to_vote': 0.3,
        'weight': 1.5  # 🚀 1分钟CVD也要提升权重
    },
    {
        'name': 'UT Bot 15m',
        'description': '15分钟UT Bot趋势',
        'enabled': True,
        'min_confidence_to_vote': 0.5,
        'weight': 1.0
    },
    {
        'name': 'Session Memory',
        'description': '历史会话先验',
        'enabled': True,
        'min_confidence_to_vote': 0.3,
        'weight': 1.0
    },
]

# 投票系统配置
VOTING_CONFIG = {
    'min_total_confidence': 0.60,  # 最终置信度门槛（60%）
    'min_votes_required': 3,       # 最少需要3个规则投票
    'majority_threshold': 0.60,    # 需要60%以上的规则同向
}
