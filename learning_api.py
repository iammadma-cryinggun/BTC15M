#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学习系统API - 通过HTTP查看学习数据
用法: 在start.sh中启动此服务
"""

from flask import Flask, jsonify
import sys
import os

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)

LEARNING_SYSTEM = None

def init_learning():
    """初始化学习系统"""
    global LEARNING_SYSTEM
    try:
        from prediction_learning_polymarket import PolymarketPredictionLearning
        LEARNING_SYSTEM = PolymarketPredictionLearning()
        return True
    except Exception as e:
        print(f"[ERROR] 学习系统初始化失败: {e}")
        return False

@app.route('/')
def home():
    """首页"""
    return """
    <h1>BTC 15min 学习系统API</h1>
    <ul>
        <li><a href="/api/stats">/api/stats - 查看统计数据</a></li>
        <li><a href="/api/predictions">/api/predictions - 查看预测记录</a></li>
        <li><a href="/api/accuracy">/api/accuracy - 查看准确率分析</a></li>
    </ul>
    """

@app.route('/api/stats')
def get_stats():
    """获取统计概览"""
    if not LEARNING_SYSTEM:
        return jsonify({"error": "学习系统未初始化"}), 500

    try:
        stats = LEARNING_SYSTEM.get_accuracy_stats(hours=24*7)  # 最近7天
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/accuracy')
def get_accuracy():
    """获取准确率详情"""
    if not LEARNING_SYSTEM:
        return jsonify({"error": "学习系统未初始化"}), 500

    try:
        import sqlite3
        from datetime import datetime, timedelta

        conn = sqlite3.connect(LEARNING_SYSTEM.db_path)
        cursor = conn.cursor()

        # 总体准确率
        cursor.execute('''
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END) as correct
            FROM predictions
            WHERE verified = 1
        ''')
        total, correct = cursor.fetchone()
        accuracy = (correct / total * 100) if total > 0 else 0

        # 按分数分组
        cursor.execute('''
            SELECT
                CAST(score AS INTEGER) as score_range,
                COUNT(*) as total,
                SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END) as correct
            FROM predictions
            WHERE verified = 1
            GROUP BY score_range
            ORDER BY score_range DESC
        ''')
        by_score = []
        for score, total, correct in cursor.fetchall():
            acc = (correct / total * 100) if total > 0 else 0
            by_score.append({
                "score_range": int(score),
                "total": total,
                "correct": correct,
                "accuracy": round(acc, 1)
            })

        # 最近10条预测
        cursor.execute('''
            SELECT timestamp, direction, score, verified, correct, recommendation
            FROM predictions
            ORDER BY id DESC
            LIMIT 10
        ''')
        recent = []
        for ts, direction, score, verified, correct, rec in cursor.fetchall():
            status = '✓' if verified else '待验证'
            result = '正确' if correct == 1 else '错误' if verified else '-'
            recent.append({
                "time": ts,
                "direction": direction,
                "score": score,
                "status": status,
                "result": result
            })

        conn.close()

        return jsonify({
            "overall": {
                "total": total,
                "correct": correct,
                "accuracy": round(accuracy, 1)
            },
            "by_score": by_score,
            "recent": recent
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("=" * 70)
    print("学习系统API服务启动中...")
    print("=" * 70)

    if init_learning():
        print("[OK] 学习系统已连接")
        print()
        print("服务地址: http://0.0.0.0:5000")
        print("查看统计: http://0.0.0.0:5000/api/stats")
        print("查看准确率: http://0.0.0.0:5000/api/accuracy")
        print()
        print("按 Ctrl+C 停止服务")
        print("=" * 70)
        app.run(host='0.0.0.0', port=5000, debug=False)
    else:
        print("[ERROR] 无法启动服务")
        sys.exit(1)
