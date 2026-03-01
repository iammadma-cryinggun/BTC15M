#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双核融合系统可视化流程图

使用方法: python dual_core_flowchart.py
"""

import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

try:
    from graphviz import Digraph
    GRAPHVIZ_AVAILABLE = True
except ImportError:
    GRAPHVIZ_AVAILABLE = False
    if sys.platform == 'win32':
        print("[WARN] graphviz not installed, skipping flowchart generation")
    else:
        print("⚠️  graphviz未安装，将跳过流程图生成")

def create_dual_core_diagram():
    dot = Digraph(comment='双核融合系统', format='png')
    dot.attr(rankdir='TB', fontsize='12')
    dot.attr('node', shape='box', style='rounded,filled', fontname='Arial')

    # 输入层
    dot.node('A', 'Polymarket市场\n(每3秒轮询)', fillcolor='#E8F4F8')
    dot.node('B', 'Binance Oracle\n(实时WebSocket)', fillcolor='#FFF4E8')

    # 核心A详细流程
    with dot.subgraph(name='cluster_0') as c:
        c.attr(label='核心A: Polymarket本地引擎', style='dashed', color='#4A90E2')
        c.attr('node', shape='box', fillcolor='#D6EAF8')
        c.node('A1', '价格动量\n(10周期)')
        c.node('A2', 'VWAP偏离\n(±0.5%)')
        c.node('A3', 'RSI状态\n(60/40)')
        c.node('A4', '趋势强度\n(3周期)')
        c.node('A5', '波动率调整')
        c.node('A_SCORE', '本地分数\n(±10)', shape='ellipse', fillcolor='#5DADE2')

    # 核心B详细流程
    with dot.subgraph(name='cluster_1') as c:
        c.attr(label='核心B: Binance Oracle引擎', style='dashed', color='#F39C12')
        c.attr('node', shape='box', fillcolor='#FCF3CF')
        c.node('B1', '1分钟CVD\n(即时窗口)')
        c.node('B2', '5分钟CVD\n(趋势窗口)')
        c.node('B3', '盘口不平衡\n(买卖墙)')
        c.node('B4', 'UT Bot+Hull\n(15m趋势)')
        c.node('B5', 'MACD+Z-Score\n(高级指标)')
        c.node('B_SCORE', 'Oracle分数\n(±10)', shape='ellipse', fillcolor='#F8C471')

    # 融合层
    dot.node('FUSION', '双核融合算法', shape='diamond', fillcolor='#D2B4DE')
    dot.node('F1', '同向共振\n÷5', shape='box', fillcolor='#E8DAEF')
    dot.node('F2', '反向背离\n÷10', shape='box', fillcolor='#E8DAEF')
    dot.node('F3', '核弹级VIP通道\n≥12.0', shape='box', fillcolor='#FADBD8')

    # 后处理层
    dot.node('MEMORY', 'Layer 1: Session Memory\n(先验偏差)', fillcolor='#D5F4E6')
    dot.node('TREND', '15m UT Bot趋势检查', fillcolor='#D5F4E6')
    dot.node('RSI_CHECK', 'RSI防呆\n(70/30)', fillcolor='#D5F4E6')
    dot.node('DEFENSE', 'Layer 3: Defense Sentinel\n(5因子风险评估)', fillcolor='#D5F4E6')

    # 输出层
    dot.node('OUTPUT', '最终信号\n(方向+分数+置信度)', shape='doublecircle', fillcolor='#82E0AA')

    # 连接线
    # Polymarket路径
    dot.edge('A', 'A1')
    dot.edge('A', 'A2')
    dot.edge('A', 'A3')
    dot.edge('A', 'A4')
    dot.edge('A1', 'A5')
    dot.edge('A2', 'A5')
    dot.edge('A3', 'A5')
    dot.edge('A4', 'A5')
    dot.edge('A5', 'A_SCORE')
    dot.edge('A_SCORE', 'FUSION', label='本地分')

    # Binance路径
    dot.edge('B', 'B1')
    dot.edge('B', 'B2')
    dot.edge('B', 'B3')
    dot.edge('B', 'B4')
    dot.edge('B', 'B5')
    dot.edge('B1', 'B_SCORE', label='30%')
    dot.edge('B2', 'B_SCORE', label='70%')
    dot.edge('B3', 'B_SCORE')
    dot.edge('B4', 'B_SCORE')
    dot.edge('B5', 'B_SCORE')
    dot.edge('B_SCORE', 'FUSION', label='Oracle分')

    # 融合路径
    dot.edge('FUSION', 'F1', label='同向×>0')
    dot.edge('FUSION', 'F2', label='同向×<0')
    dot.edge('FUSION', 'F3', label='Oracle≥12.0')
    dot.edge('F1', 'MEMORY')
    dot.edge('F2', 'MEMORY')
    dot.edge('F3', 'OUTPUT', label='VIP通道\n直接通过')

    # 后处理路径
    dot.edge('MEMORY', 'TREND')
    dot.edge('TREND', 'RSI_CHECK')
    dot.edge('RSI_CHECK', 'DEFENSE')
    dot.edge('DEFENSE', 'OUTPUT')

    # 保存图表
    dot.render('dual_core_flowchart', view=True, cleanup=True)
    print("✅ 流程图已生成: dual_core_flowchart.png")


def create_fusion_table():
    """创建融合规则表格"""
    print("\n" + "=" * 80)
    print("双核融合规则速查表")
    print("=" * 80)

    scenarios = [
        {
            'name': '完美共振',
            'local': '+4.0',
            'oracle': '+5.0',
            'check': '同向 × > 0',
            'formula': '4.0 + (5.0 ÷ 5) = 5.0',
            'result': '+5.0',
            'meaning': '两个系统都看涨 → 信心增强'
        },
        {
            'name': '谨慎背离',
            'local': '+4.0',
            'oracle': '-5.0',
            'check': '同向 × < 0',
            'formula': '4.0 + (-5.0 ÷ 10) = 3.5',
            'result': '+3.5',
            'meaning': 'Oracle削弱本地信号'
        },
        {
            'name': '核弹级VIP',
            'local': '-2.0',
            'oracle': '+12.5',
            'check': 'Oracle ≥ 12.0',
            'formula': 'VIP通道，跳过融合',
            'result': '+12.5',
            'meaning': '极端异常，独立通道'
        },
        {
            'name': '双核分歧',
            'local': '+3.0',
            'oracle': '-2.0',
            'check': '同向 × < 0',
            'formula': '3.0 + (-2.0 ÷ 10) = 2.8',
            'result': '+2.8',
            'meaning': '轻微削弱，保持本地判断'
        }
    ]

    for s in scenarios:
        print(f"\n【{s['name']}】")
        print(f"  本地分: {s['local']} | Oracle: {s['oracle']}")
        print(f"  检查: {s['check']}")
        print(f"  计算: {s['formula']}")
        print(f"  结果: {s['result']}")
        print(f"  含义: {s['meaning']}")

    print("\n" + "=" * 80)


def create_cvd_window_diagram():
    """创建CVD双窗口系统说明"""
    print("\n" + "=" * 80)
    print("CVD双窗口系统详解")
    print("=" * 80)

    print("""
┌─────────────────────────────────────────────────────────────┐
│  1分钟即时窗口 (CVD_SHORT)                                   │
│  ─────────────────────────────────                           │
│  时间范围: 最近60秒                                          │
│  用途: 捕捉瞬时资金流变化                                    │
│  评分: cvd_short / 50000.0                                  │
│  满分: ±5万USD = ±3分                                       │
│  权重: 30%                                                  │
│                                                              │
│  示例: +$45K → +0.9分                                       │
└─────────────────────────────────────────────────────────────┘

        ↕ 融合 (70% 长窗口 + 30% 短窗口)

┌─────────────────────────────────────────────────────────────┐
│  5分钟趋势窗口 (CVD_LONG)                                    │
│  ─────────────────────────────                               │
│  时间范围: 最近300秒                                         │
│  用途: 确认持续趋势方向                                      │
│  评分: cvd_long / 150000.0                                  │
│  满分: ±15万USD = ±5分                                      │
│  权重: 70%                                                  │
│                                                              │
│  示例: +$120K → +4.0分                                      │
└─────────────────────────────────────────────────────────────┘

融合计算:
  cvd_long_score = +4.0 (5分钟窗口)
  cvd_short_score = +0.9 (1分钟窗口)
  cvd_fused = 4.0 × 0.7 + 0.9 × 0.3 = 2.8 + 0.27 = 3.07

最终Oracle分数:
  CVD融合: +3.07
  盘口不平衡: +1.2
  ─────────────────
  Oracle总分: +4.27
    """)

    print("=" * 80)


if __name__ == "__main__":
    print("🎯 双核融合系统可视化\n")

    # 1. 创建融合规则表格
    create_fusion_table()

    # 2. 创建CVD窗口说明
    create_cvd_window_diagram()

    # 3. 创建流程图（需要graphviz库）
    if GRAPHVIZ_AVAILABLE:
        print("\n📊 正在生成流程图...")
        create_dual_core_diagram()
    else:
        print("\n⚠️  需要安装graphviz库来生成流程图:")
        print("   pip install graphviz")
        print("   并安装Graphviz软件: https://graphviz.org/download/")

    print("\n✅ 说明完成！")
    print("\n📚 相关文档:")
    print("   - DUAL_CORE_EXPLAINED.md (详细说明)")
    print("   - THREE_LAYER_ARCHITECTURE.md (三层架构)")
    print("   - session_memory.py (Layer 1代码)")
    print("   - binance_oracle.py (核心B代码)")
    print("   - auto_trader_ankr.py (融合逻辑)")
