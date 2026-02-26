#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学习报告Web API
访问：http://your-zeabur-app-url/learning/report
"""

import sqlite3
import os
from datetime import datetime
from flask import Flask, jsonify
from colorama import Fore, init

init(autoreset=True)

app = Flask(__name__)

# 数据库路径
DATA_DIR = os.getenv('DATA_DIR', '/app/data')
prediction_db = os.path.join(DATA_DIR, 'btc_15min_predictionsv2.db')

def get_oracle_accuracy():
    """Oracle准确率分析"""
    if not os.path.exists(prediction_db):
        return None

    conn = sqlite3.connect(prediction_db, timeout=30.0)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT
            CASE
                WHEN oracle_score >= 5 THEN '强烈看涨 (≥5)'
                WHEN oracle_score >= 2 THEN '看涨 (2-5)'
                WHEN oracle_score <= -5 THEN '强烈看跌 (≤-5)'
                WHEN oracle_score <= -2 THEN '看跌 (-5~-2)'
                ELSE '中性 (-2~2)'
            END as oracle_range,
            COUNT(*) as total,
            SUM(correct) as correct,
            AVG(actual_pnl_pct) as avg_pnl
        FROM predictions
        WHERE verified = 1 AND oracle_score IS NOT NULL
        GROUP BY oracle_range
        ORDER BY MIN(oracle_score) DESC
    ''')

    rows = cursor.fetchall()
    conn.close()

    result = []
    for row in rows:
        oracle_range, total, correct, avg_pnl = row
        accuracy = (correct / total * 100) if total > 0 else 0
        result.append({
            'range': oracle_range,
            'total': total,
            'accuracy': round(accuracy, 1),
            'avg_pnl_pct': round((avg_pnl * 100) if avg_pnl else 0, 2)
        })

    return result

def get_threshold_search():
    """搜索最优阈值"""
    if not os.path.exists(prediction_db):
        return None

    conn = sqlite3.connect(prediction_db, timeout=30.0)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT score, direction, actual_pnl_pct, correct
        FROM predictions
        WHERE verified = 1 AND actual_pnl_pct IS NOT NULL
    ''')
    rows = cursor.fetchall()
    conn.close()

    if len(rows) < 20:
        return {'error': '数据样本不足（<20条）'}

    thresholds_long = [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0]
    thresholds_short = [-2.0, -2.5, -3.0, -3.5, -4.0, -4.5, -5.0, -5.5, -6.0]

    long_results = []
    for threshold in thresholds_long:
        filtered = [r for r in rows if r[0] >= threshold and r[1] == 'LONG']
        if len(filtered) >= 5:
            wins = sum(1 for r in filtered if r[3] == 1)
            total = len(filtered)
            win_rate = wins / total * 100
            avg_pnl = sum(r[2] for r in filtered) / total * 100
            long_results.append({
                'threshold': threshold,
                'trades': total,
                'win_rate': round(win_rate, 1),
                'avg_pnl_pct': round(avg_pnl, 2)
            })

    short_results = []
    for threshold in thresholds_short:
        filtered = [r for r in rows if r[0] <= threshold and r[1] == 'SHORT']
        if len(filtered) >= 5:
            wins = sum(1 for r in filtered if r[3] == 1)
            total = len(filtered)
            win_rate = wins / total * 100
            avg_pnl = sum(r[2] for r in filtered) / total * 100
            short_results.append({
                'threshold': threshold,
                'trades': total,
                'win_rate': round(win_rate, 1),
                'avg_pnl_pct': round(avg_pnl, 2)
            })

    best_long = max(long_results, key=lambda x: x['avg_pnl_pct'], default=None)
    best_short = max(short_results, key=lambda x: x['avg_pnl_pct'], default=None)

    return {
        'long_analysis': long_results,
        'short_analysis': short_results,
        'recommended': {
            'min_long_score': best_long['threshold'] if best_long else 4.0,
            'min_short_score': best_short['threshold'] if best_short else -4.0
        }
    }

def get_overall_stats():
    """总体统计"""
    if not os.path.exists(prediction_db):
        return None

    conn = sqlite3.connect(prediction_db, timeout=30.0)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT
            COUNT(*) as total,
            SUM(correct) as wins,
            AVG(actual_pnl_pct) as avg_pnl
        FROM predictions
        WHERE verified = 1
    ''')

    row = cursor.fetchone()
    conn.close()

    if not row or row[0] == 0:
        return None

    total, wins, avg_pnl = row
    accuracy = (wins / total * 100) if total > 0 else 0

    return {
        'total_predictions': total,
        'accuracy': round(accuracy, 1),
        'avg_pnl_pct': round((avg_pnl * 100) if avg_pnl else 0, 2)
    }

@app.route('/learning/report')
def learning_report():
    """学习报告API"""

    # 检查数据库是否存在
    if not os.path.exists(prediction_db):
        return jsonify({
            'error': '学习数据库尚不存在',
            'message': '系统运行一段时间后会自动创建数据库'
        }), 404

    # 收集所有数据
    overall = get_overall_stats()
    oracle = get_oracle_accuracy()
    threshold = get_threshold_search()

    # 生成HTML报告
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>学习系统报告</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
            .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; }}
            h1 {{ color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }}
            h2 {{ color: #666; margin-top: 30px; }}
            table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
            th {{ background: #4CAF50; color: white; padding: 12px; text-align: left; }}
            td {{ padding: 10px; border-bottom: 1px solid #ddd; }}
            tr:hover {{ background: #f5f5f5; }}
            .positive {{ color: #4CAF50; font-weight: bold; }}
            .negative {{ color: #f44336; font-weight: bold; }}
            .recommended {{ background: #e8f5e9; border-left: 4px solid #4CAF50; padding: 15px; margin: 20px 0; }}
            .update-time {{ color: #999; font-size: 0.9em; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎯 交易学习系统报告</h1>
            <p class="update-time">更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    """

    # 总体统计
    if overall:
        acc_class = 'positive' if overall['accuracy'] >= 60 else 'negative'
        pnl_class = 'positive' if overall['avg_pnl_pct'] > 0 else 'negative'

        html += f"""
            <h2>📊 总体统计</h2>
            <table>
                <tr>
                    <th>指标</th>
                    <th>数值</th>
                </tr>
                <tr>
                    <td>总预测次数</td>
                    <td>{overall['total_predictions']}</td>
                </tr>
                <tr>
                    <td>整体准确率</td>
                    <td class="{acc_class}">{overall['accuracy']}%</td>
                </tr>
                <tr>
                    <td>平均盈亏</td>
                    <td class="{pnl_class}">{overall['avg_pnl_pct']:+.2f}%</td>
                </tr>
            </table>
        """

    # Oracle准确率
    if oracle:
        html += """
            <h2>📈 Oracle数据准确率</h2>
            <table>
                <tr>
                    <th>Oracle评分区间</th>
                    <th>次数</th>
                    <th>胜率</th>
                    <th>平均盈亏</th>
                </tr>
        """
        for item in oracle:
            pnl_class = 'positive' if item['avg_pnl_pct'] > 0 else 'negative'
            html += f"""
                <tr>
                    <td>{item['range']}</td>
                    <td>{item['total']}</td>
                    <td>{item['accuracy']}%</td>
                    <td class="{pnl_class}">{item['avg_pnl_pct']:+.2f}%</td>
                </tr>
            """
        html += "</table>"

    # 阈值搜索
    if threshold and threshold.get('recommended'):
        rec = threshold['recommended']
        html += f"""
            <div class="recommended">
                <h3>💡 推荐参数调整</h3>
                <p><strong>min_long_score:</strong> {rec['min_long_score']}</p>
                <p><strong>min_short_score:</strong> {rec['min_short_score']}</p>
            </div>
        """

        if threshold.get('long_analysis'):
            html += """
                <h2>🔍 LONG阈值分析</h2>
                <table>
                    <tr>
                        <th>阈值</th>
                        <th>交易次数</th>
                        <th>胜率</th>
                        <th>平均盈亏</th>
                    </tr>
            """
            best_pnl = max(r['avg_pnl_pct'] for r in threshold['long_analysis'])
            for item in threshold['long_analysis']:
                pnl_class = 'positive' if item['avg_pnl_pct'] > 0 else 'negative'
                best_mark = ' ⭐' if item['avg_pnl_pct'] == best_pnl else ''
                html += f"""
                    <tr>
                        <td>{item['threshold']}{best_mark}</td>
                        <td>{item['trades']}</td>
                        <td>{item['win_rate']}%</td>
                        <td class="{pnl_class}">{item['avg_pnl_pct']:+.2f}%</td>
                    </tr>
                """
            html += "</table>"

    html += """
        </div>
    </body>
    </html>
    """

    return html

if __name__ == '__main__':
    port = int(os.getenv('LEARNING_PORT', 5002))
    print(f"学习报告API启动: http://0.0.0.0:{port}/learning/report")
    app.run(host='0.0.0.0', port=port)
