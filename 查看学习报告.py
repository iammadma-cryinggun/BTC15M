#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查看预测学习报告
随时运行此脚本查看最新的学习数据
"""

import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from prediction_learning_polymarket import PolymarketPredictionLearning

def main():
    print("=" * 80)
    print("Polymarket 预测学习报告查看器")
    print("=" * 80)
    print()

    # 初始化学习系统
    pls = PolymarketPredictionLearning()

    # 打印准确率报告
    pls.print_accuracy_report()

    # 打印优化建议
    pls.print_optimization_report()

    # 显示推荐的参数
    recommended = pls.get_recommended_parameters()

    print("=" * 80)
    print("如何调整参数")
    print("=" * 80)
    print()

    if recommended['reasons']:
        print("当前推荐参数：")
        print(f"  min_confidence: {recommended['min_confidence']:.2f}")
        print(f"  min_long_score: {recommended['min_long_score']:.1f}")
        print(f"  min_short_score: {recommended['min_short_score']:.1f}")
        print()
        print("如需调整，请编辑 auto_trader_ankr.py 中的 CONFIG 字典：")
        print()
        print("  'signal': {")
        print(f"      'min_confidence': {recommended['min_confidence']:.2f},      # 当前: 0.30")
        print(f"      'min_long_score': {recommended['min_long_score']:.1f},       # 当前: 2.5")
        print(f"      'min_short_score': {recommended['min_short_score']:.1f},     # 当前: -2.5")
        print("  }")
        print()
    else:
        print("当前数据不足，无需调整参数")
        print()

    print("=" * 80)
    print("数据库位置")
    print("=" * 80)
    print()
    print("  btc_15min_predictions.db")
    print()
    print("可以用 SQLite 工具查看原始数据")
    print()

if __name__ == "__main__":
    main()
