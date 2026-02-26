#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导出学习系统数据为JSON
用法: python export_learning_data.py > learning_data.json
"""

import sys
import os

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from prediction_learning_polymarket import PolymarketPredictionLearning

    learning = PolymarketPredictionLearning()
    stats = learning.get_accuracy_stats(hours=24*30)  # 最近30天

    import json
    print(json.dumps(stats, indent=2, ensure_ascii=False))

except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
