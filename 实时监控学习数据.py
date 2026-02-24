#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时监控学习数据
每30秒刷新一次，显示最新的预测和准确率
"""

import sys
import io
import time
from datetime import datetime

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from prediction_learning_polymarket import PolymarketPredictionLearning

def clear_screen():
    """清屏"""
    import os
    os.system('cls' if os.name == 'nt' else 'clear')

def main():
    pls = PolymarketPredictionLearning()

    print("=" * 80)
    print("Polymarket 预测学习 - 实时监控")
    print("=" * 80)
    print()
    print("每30秒自动刷新，按 Ctrl+C 退出")
    print()

    try:
        iteration = 0
        while True:
            iteration += 1
            clear_screen()

            print("=" * 80)
            print(f"实时监控 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (第{iteration}次刷新)")
            print("=" * 80)
            print()

            # 获取统计数据
            stats = pls.get_accuracy_stats(hours=24)

            # 总体统计
            print("【最近24小时统计】")
            if stats['total'] > 0:
                acc_color = "✓" if stats['accuracy'] >= 60 else "⚠" if stats['accuracy'] >= 50 else "✗"
                print(f"  总预测: {stats['total']} 次")
                print(f"  正确: {stats['correct']} 次")
                print(f"  准确率: {acc_color} {stats['accuracy']:.1f}%")
                print()
                print(f"  做多: {stats['long_correct']}/{stats['long_total']} ({stats['long_accuracy']:.1f}%)")
                print(f"  做空: {stats['short_correct']}/{stats['short_total']} ({stats['short_accuracy']:.1f}%)")
                print()
                print(f"  平均评分: {stats['avg_score']:.1f}")
                print(f"  平均置信度: {stats['avg_confidence']*100:.1f}%")
            else:
                print("  暂无数据（需要至少15分钟验证时间）")
            print()

            # 按评分区间分析
            score_analysis = pls.analyze_by_score_range()
            if score_analysis:
                print("【按评分区间】")
                print(f"  {'区间':<15} {'次数':>6} {'准确率':>8}")
                print(f"  {'-'*15} {'-'*6} {'-'*8}")
                for item in score_analysis[:5]:  # 只显示前5个
                    acc_icon = "✓" if item['accuracy'] >= 60 else "⚠" if item['accuracy'] >= 50 else "✗"
                    print(f"  {item['score_range']:<15} {item['total']:>6} {acc_icon} {item['accuracy']:>6.1f}%")
            print()

            # 优化建议
            suggestions = pls.get_optimization_suggestions()
            if suggestions:
                print("【优化建议】")
                for i, suggestion in enumerate(suggestions[:3], 1):
                    print(f"  {i}. {suggestion}")
            else:
                print("【优化建议】")
                print("  数据不足，需要至少10条验证记录")
            print()

            # 推荐参数
            recommended = pls.get_recommended_parameters()
            if recommended['reasons']:
                print("【推荐参数】")
                print(f"  min_confidence: {recommended['min_confidence']:.2f}")
                print(f"  min_long_score: {recommended['min_long_score']:.1f}")
                print(f"  min_short_score: {recommended['min_short_score']:.1f}")
            print()

            print("=" * 80)
            print(f"下次刷新: 30秒后 | 已刷新: {iteration}次")
            print("=" * 80)

            time.sleep(30)

    except KeyboardInterrupt:
        print()
        print()
        print("监控已停止")
        print()

if __name__ == "__main__":
    main()
