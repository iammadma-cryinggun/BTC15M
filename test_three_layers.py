#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三层架构测试脚本
Layer 1: Memory (Session Memory - 先验偏差)
Layer 2: Signals (实时信号投票)
Layer 3: Defense (防御层 - 仓位控制)
"""

import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from session_memory import SessionMemory
import json

def test_layer1_memory():
    """测试Layer 1: Session Memory"""
    print("=" * 80)
    print("🧠 测试 Layer 1: Session Memory（先验偏差）")
    print("=" * 80)

    memory = SessionMemory()

    # 模拟三种不同的市场场景
    scenarios = [
        {
            'name': '场景1: 低位上涨趋势',
            'market': {
                'price': 0.28,
                'rsi': 35.0,
                'oracle_score': 4.5,
                'price_history': [0.25, 0.26, 0.27, 0.28, 0.29]
            }
        },
        {
            'name': '场景2: 高位下跌趋势',
            'market': {
                'price': 0.72,
                'rsi': 65.0,
                'oracle_score': -5.2,
                'price_history': [0.75, 0.74, 0.73, 0.72, 0.71]
            }
        },
        {
            'name': '场景3: 中性震荡',
            'market': {
                'price': 0.50,
                'rsi': 50.0,
                'oracle_score': 0.5,
                'price_history': [0.49, 0.51, 0.49, 0.51, 0.50]
            }
        }
    ]

    for scenario in scenarios:
        print(f"\n{'=' * 80}")
        print(f"测试: {scenario['name']}")
        print(f"{'=' * 80}")

        # 提取特征
        features = memory.extract_session_features(scenario['market'])
        print("\n📊 会话特征:")
        print(json.dumps(features, indent=2))

        # 计算先验偏差
        prior_bias, analysis = memory.calculate_prior_bias(features)

        # 打印分析
        memory.print_analysis(analysis)

        print(f"\n💡 先验应用示例:")
        print(f"   原始信号分数: +3.0")
        print(f"   先验偏差: {prior_bias:+.2f} × 2.0 = {prior_bias * 2:+.2f}")
        print(f"   调整后分数: {3.0 + prior_bias * 2:+.2f}")

    print("\n" + "=" * 80)
    print("✅ Layer 1 测试完成")
    print("=" * 80)


def simulate_three_layers():
    """模拟完整的三层决策流程"""
    print("\n" + "=" * 80)
    print("🎯 完整三层决策流程模拟")
    print("=" * 80)

    # Layer 1: Memory（先验）
    print("\n📋 Layer 1: Session Memory")
    print("-" * 80)
    memory = SessionMemory()

    current_market = {
        'price': 0.35,
        'rsi': 42.0,
        'oracle_score': 3.8,
        'price_history': [0.32, 0.33, 0.34, 0.35, 0.36]
    }

    features = memory.extract_session_features(current_market)
    prior_bias, analysis = memory.calculate_prior_bias(features)

    print(f"  先验偏差: {prior_bias:+.2f}")
    if prior_bias > 0.2:
        print(f"  → 历史数据显示: 做多胜率更高")
    elif prior_bias < -0.2:
        print(f"  → 历史数据显示: 做空胜率更高")
    else:
        print(f"  → 历史数据显示: 无明显偏向")

    # Layer 2: Signals（实时投票）
    print("\n📊 Layer 2: Real-time Signal Voting")
    print("-" * 80)

    # 模拟8-12个信号规则投票
    signals = [
        {'rule': '本地Momentum', 'direction': 'LONG', 'confidence': 0.65},
        {'rule': 'RSI防呆', 'direction': 'LONG', 'confidence': 0.70},
        {'rule': 'VWAP偏离', 'direction': 'LONG', 'confidence': 0.55},
        {'rule': 'Binance Oracle (5m CVD)', 'direction': 'LONG', 'confidence': 0.78},
        {'rule': 'Binance Oracle (1m CVD)', 'direction': 'LONG', 'confidence': 0.72},
        {'rule': 'UT Bot 15m趋势', 'direction': 'LONG', 'confidence': 0.60},
        {'rule': 'MACD Histogram', 'direction': 'LONG', 'confidence': 0.58},
        {'rule': 'Delta Z-Score', 'direction': 'LONG', 'confidence': 0.50},
    ]

    # 计算加权投票
    long_votes = [s['confidence'] for s in signals if s['direction'] == 'LONG']
    short_votes = [s['confidence'] for s in signals if s['direction'] == 'SHORT']

    if long_votes:
        long_confidence = sum(long_votes) / len(long_votes)
    else:
        long_confidence = 0.0

    if short_votes:
        short_confidence = sum(short_votes) / len(short_votes)
    else:
        short_confidence = 0.0

    # 融合Layer 1的先验偏差
    prior_adjustment = prior_bias * 0.2  # 先验偏差影响置信度

    if long_confidence > short_confidence:
        final_direction = 'LONG'
        base_confidence = long_confidence + prior_adjustment
    else:
        final_direction = 'SHORT'
        base_confidence = short_confidence + prior_adjustment

    base_confidence = max(0.0, min(1.0, base_confidence))

    print(f"  信号规则数量: {len(signals)}个")
    print(f"  LONG投票: {len(long_votes)}个 (平均置信度{long_confidence:.1%})")
    print(f"  SHORT投票: {len(short_votes)}个 (平均置信度{short_confidence:.1%})")
    print(f"  先验调整: {prior_adjustment:+.2%}")
    print(f"  🎯 最终方向: {final_direction}")
    print(f"  📊 基础置信度: {base_confidence:.1%}")

    # Layer 3: Defense（防御层）
    print("\n🛡️ Layer 3: Defense Sentinel（风险控制）")
    print("-" * 80)

    # 5个风险因子评估
    risk_factors = [
        {
            'name': 'CVD一致性',
            'status': '✅ 通过',
            'score': 1.0,
            'reason': 'Oracle CVD与信号方向一致'
        },
        {
            'name': '价格-基准距离',
            'status': '⚠️ 警告',
            'score': 0.8,
            'reason': '入场价0.35，距离基准0.50较远（良好）'
        },
        {
            'name': '时间剩余',
            'status': '✅ 通过',
            'score': 1.0,
            'reason': '会话刚开始（剩余12分钟）'
        },
        {
            'name': '市场混乱度',
            'status': '⚠️ 警告',
            'score': 0.7,
            'reason': '已检测到2次价格穿越'
        },
        {
            'name': '利润空间',
            'status': '✅ 通过',
            'score': 0.9,
            'reason': '入场价0.35，最大收益65%'
        }
    ]

    # 计算综合风险分数
    defense_multiplier = 1.0
    for factor in risk_factors:
        defense_multiplier *= factor['score']
        print(f"  {factor['name']}: {factor['status']} (乘数{factor['score']:.2f})")
        print(f"    └─ {factor['reason']}")

    print(f"\n  🎯 防御层最终乘数: {defense_multiplier:.2f}")

    # 最终仓位计算
    base_position = 5.0  # 假设基础仓位$5
    final_position = base_position * base_confidence * defense_multiplier

    print("\n" + "=" * 80)
    print("📈 最终决策总结")
    print("=" * 80)
    print(f"  基础仓位: ${base_position:.2f}")
    print(f"  Layer 2置信度: {base_confidence:.1%}")
    print(f"  Layer 3防御乘数: {defense_multiplier:.2f}")
    print(f"  🎯 最终仓位: ${final_position:.2f}")
    print(f"  交易方向: {final_direction}")
    print("\n💡 三层系统优势:")
    print(f"  - Layer 1 (Memory): 提供先验知识，避免盲目入场")
    print(f"  - Layer 2 (Signals): 多规则投票，提高信号准确性")
    print(f"  - Layer 3 (Defense): 风险控制，确保长期生存")
    print(f"  - 结论: 'Offense generates signals, Defense generates alpha'")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    test_layer1_memory()
    simulate_three_layers()

    print("\n✅ 所有测试完成！")
    print("\n下一步：启动实际交易系统，观察三层系统协同工作")
    print("启动命令: python auto_trader_ankr.py")
