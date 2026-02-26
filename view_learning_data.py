#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学习系统数据查看工具
用法: python view_learning_data.py
"""

import sqlite3
import json
from datetime import datetime

DB_PATH = 'btc_15min_predictionsv2.db'

def analyze_predictions():
    """分析预测数据"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # 检查表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='predictions'")
        if not cursor.fetchone():
            return {"error": "数据库表不存在，学习系统尚未记录数据"}

        # 总体统计
        cursor.execute('SELECT COUNT(*) FROM predictions')
        total = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM predictions WHERE verified = 1')
        verified = cursor.fetchone()[0]

        result = {
            "总预测数": total,
            "已验证": verified,
            "未验证": total - verified,
            "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        # 准确率分析
        if verified > 0:
            cursor.execute('''
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END) as correct
                FROM predictions
                WHERE verified = 1
            ''')
            row = cursor.fetchone()
            accuracy = row[1] / row[0] * 100 if row[0] > 0 else 0
            result.update({
                "准确率": f"{accuracy:.1f}%",
                "已验证预测": row[0],
                "正确预测": row[1]
            })

            # 按分数分组统计
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
            score_analysis = []
            for row in cursor.fetchall():
                score, total, correct = row
                acc = correct / total * 100 if total > 0 else 0
                score_analysis.append({
                    "分数区间": int(score),
                    "总数": total,
                    "正确": correct,
                    "准确率": f"{acc:.1f}%"
                })
            result["按分数统计"] = score_analysis

            # 最近5条记录
            cursor.execute('''
                SELECT timestamp, direction, score, verified, correct, recommendation
                FROM predictions
                ORDER BY id DESC
                LIMIT 5
            ''')
            recent = []
            for row in cursor.fetchall():
                ts, direction, score, verified, correct, rec = row
                status = '✓' if verified else '待验证'
                result_str = '正确' if correct == 1 else '错误' if verified else '-'
                recent.append({
                    "时间": ts,
                    "方向": direction,
                    "分数": score,
                    "状态": status,
                    "结果": result_str
                })
            result["最近5条"] = recent

        conn.close()
        return result

    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    print("=" * 70)
    print("学习系统数据分析")
    print("=" * 70)
    print()

    data = analyze_predictions()

    if "error" in data:
        print(f"❌ 错误: {data['error']}")
        print()
        print("💡 提示：如果是在Zeabur上运行，请将此脚本集成到web服务中访问")
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))
