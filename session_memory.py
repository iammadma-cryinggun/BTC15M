#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Session Memory System - Layer 1 of Three-Layer Architecture

在生成任何信号之前，系统就已经有了"先验观点"。
扫描过去30+个已完成的15分钟会话，计算：
"当过去的会话看起来像当前会话时，哪边赢了？"

历史数据会生成方向性先验（prior bias），作为当前会话的起点。
"""

import sqlite3
import os
import json
import numpy as np
from datetime import datetime
from collections import deque
from typing import Optional, Tuple, List


class SessionMemory:
    """
    会话记忆系统：基于历史数据的先验概率计算

    核心功能：
    1. 存储每个15分钟会话的特征和结果
    2. 匹配相似的历史会话
    3. 计算先验胜率（prior bias）
    """

    def __init__(self, db_path: str = None):
        if db_path is None:
            data_dir = os.getenv('DATA_DIR', os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(data_dir, 'btc_15min_auto_trades.db')

        self.db_path = db_path
        self.session_cache = deque(maxlen=100)  # 缓存最近100个会话特征
        self.prior_cache = {}  # 缓存先验计算结果

        print("[MEMORY] Session Memory System initialized")
        print(f"[MEMORY] Database: {db_path}")

    def _get_db_connection(self):
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def extract_session_features(self, market_data: dict) -> dict:
        """
        提取当前会话的特征向量

        特征包括：
        1. 价格区间（5个bins）
        2. 时间段（00/15/30/45）
        3. RSI初始值
        4. Oracle初始分数
        5. 5分钟价格趋势
        """
        price = market_data.get('price', 0.5)
        rsi = market_data.get('rsi', 50.0)
        oracle_score = market_data.get('oracle_score', 0.0)
        price_history = market_data.get('price_history', [])

        # 1. 价格区间（0.00-0.20, 0.20-0.40, 0.40-0.60, 0.60-0.80, 0.80-1.00）
        if price < 0.20:
            price_bin = 0
        elif price < 0.40:
            price_bin = 1
        elif price < 0.60:
            price_bin = 2
        elif price < 0.80:
            price_bin = 3
        else:
            price_bin = 4

        # 2. 时间段（0-3）
        now = datetime.now()
        time_slot = (now.minute // 15) % 4

        # 3. RSI归一化（0-1）
        rsi_normalized = rsi / 100.0

        # 4. Oracle归一化（-1到+1）
        oracle_normalized = max(-1.0, min(1.0, oracle_score / 10.0))

        # 5. 5分钟价格趋势（如果有历史数据）
        price_trend = 0.0
        if len(price_history) >= 5:
            recent = price_history[-5:]
            trend = (recent[-1] - recent[0]) / recent[0] if recent[0] > 0 else 0
            price_trend = max(-1.0, min(1.0, trend / 0.1))  # 归一化到-1到+1

        features = {
            'price_bin': price_bin,
            'time_slot': time_slot,
            'rsi': rsi_normalized,
            'oracle': oracle_normalized,
            'price_trend': price_trend,
            'timestamp': now.isoformat()
        }

        return features

    def calculate_similarity(self, features1: dict, features2: dict) -> float:
        """
        计算两个会话特征的相似度（欧氏距离）

        返回0-1的相似度分数（1=完全相同，0=完全不同）
        """
        # 特征权重（可调整）
        weights = {
            'price_bin': 2.0,      # 价格区间最重要
            'time_slot': 1.0,      # 时间段次之
            'rsi': 0.5,            # RSI权重
            'oracle': 1.5,         # Oracle分数重要
            'price_trend': 1.0     # 价格趋势
        }

        # 计算加权欧氏距离
        distance = 0.0
        for key, weight in weights.items():
            if key in features1 and key in features2:
                diff = features1[key] - features2[key]
                distance += weight * (diff ** 2)

        distance = np.sqrt(distance)

        # 转换为相似度（距离越小，相似度越高）
        # 最大可能距离约为 sqrt(2^2 + 1^2 + 0.5^2 + 1.5^2 + 1^2) ≈ 3.0
        similarity = max(0.0, 1.0 - distance / 3.0)

        return similarity

    def get_historical_sessions(self, limit: int = 100) -> List[dict]:
        """从数据库获取历史会话数据"""
        if not os.path.exists(self.db_path):
            print(f"[MEMORY] 数据库不存在: {self.db_path}")
            return []

        conn = self._get_db_connection()
        cursor = conn.cursor()

        try:
            # 检查表是否存在
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='positions'")
            if not cursor.fetchone():
                print("[MEMORY] positions表不存在")
                return []

            # 查询已关闭的仓位
            sql = """
            SELECT
                entry_time,
                side,
                entry_token_price,
                exit_token_price,
                pnl_usd,
                status,
                score,
                oracle_score,
                rsi
            FROM positions
            WHERE status = 'closed'
            ORDER BY entry_time DESC
            LIMIT ?
            """
            cursor.execute(sql, (limit,))
            rows = cursor.fetchall()

            sessions = []
            for row in rows:
                # 判断胜负
                is_win = row['pnl_usd'] and row['pnl_usd'] > 0
                is_long = row['side'] == 'LONG'

                session = {
                    'entry_time': row['entry_time'],
                    'side': row['side'],
                    'entry_price': row['entry_token_price'],
                    'exit_price': row['exit_token_price'],
                    'pnl': row['pnl_usd'] or 0.0,
                    'is_win': is_win,
                    'is_long': is_long,
                    'score': row['score'] or 0.0,
                    'oracle_score': row['oracle_score'] or 0.0,
                    'rsi': row.get('rsi', 50.0)
                }
                sessions.append(session)

            return sessions

        except Exception as e:
            print(f"[MEMORY] 获取历史会话失败: {e}")
            return []
        finally:
            conn.close()

    def calculate_prior_bias(self, current_features: dict, min_sessions: int = 30) -> Tuple[float, dict]:
        """
        计算先验偏差（prior bias）

        流程：
        1. 获取历史会话数据
        2. 为每个历史会话提取特征
        3. 计算与当前会话的相似度
        4. 选择最相似的min_sessions个会话
        5. 计算这些会话的YES胜率
        6. 转换为先验偏差分数（-1到+1）

        返回：(prior_bias, analysis_dict)
        - prior_bias: -1.0（强烈倾向NO）到+1.0（强烈倾向YES）
        - analysis_dict: 详细分析数据
        """

        # 检查缓存
        cache_key = json.dumps(current_features, sort_keys=True)
        if cache_key in self.prior_cache:
            return self.prior_cache[cache_key]

        # 获取历史会话
        historical_sessions = self.get_historical_sessions(limit=200)

        if len(historical_sessions) < min_sessions:
            # 数据不足，返回中立先验
            return 0.0, {
                'status': 'insufficient_data',
                'total_sessions': len(historical_sessions),
                'required': min_sessions,
                'message': f'历史数据不足（{len(historical_sessions)} < {min_sessions}），使用中立先验'
            }

        # 计算每个历史会话的相似度
        sessions_with_similarity = []
        for session in historical_sessions:
            # 为历史会话重建特征
            hist_features = {
                'price_bin': int(session['entry_price'] * 5),  # 近似价格区间
                'time_slot': 0,  # 历史数据没有精确时间，设为0（权重低，影响小）
                'rsi': session['rsi'] / 100.0,
                'oracle': max(-1.0, min(1.0, session['oracle_score'] / 10.0)),
                'price_trend': 0.0  # 历史数据没有价格趋势，设为0
            }

            similarity = self.calculate_similarity(current_features, hist_features)
            sessions_with_similarity.append({
                'session': session,
                'similarity': similarity
            })

        # 按相似度排序，选择最相似的min_sessions个
        sessions_with_similarity.sort(key=lambda x: x['similarity'], reverse=True)
        top_sessions = sessions_with_similarity[:min_sessions]

        # 统计YES/LONG的胜率
        long_sessions = [s for s in top_sessions if s['session']['is_long']]
        long_wins = sum(1 for s in long_sessions if s['session']['is_win'])
        long_total = len(long_sessions)

        short_sessions = [s for s in top_sessions if not s['session']['is_long']]
        short_wins = sum(1 for s in short_sessions if s['session']['is_win'])
        short_total = len(short_sessions)

        # 计算方向性胜率
        # 如果LONG胜率高 → 倾向做多（prior_bias > 0）
        # 如果SHORT胜率高 → 倾向做空（prior_bias < 0）
        if long_total >= 5 and short_total >= 5:
            long_win_rate = long_wins / long_total
            short_win_rate = short_wins / short_total

            # 方向偏差：LONG胜率 - SHORT胜率
            direction_bias = long_win_rate - short_win_rate

            # 转换为先验分数（-1到+1）
            prior_bias = max(-1.0, min(1.0, direction_bias * 2))  # 放大效果
        else:
            # 某个方向数据不足，使用总体胜率
            total_wins = sum(1 for s in top_sessions if s['session']['is_win'])
            total_win_rate = total_wins / len(top_sessions)
            # 如果总体胜率>50%，使用LONG偏倚（保守策略）
            prior_bias = (total_win_rate - 0.5) * 0.5  # 缩小效果，更保守

        # 构建分析报告
        analysis = {
            'status': 'success',
            'total_sessions_analyzed': len(historical_sessions),
            'similar_sessions': min_sessions,
            'long_sessions': long_total,
            'long_wins': long_wins,
            'long_win_rate': long_wins / long_total if long_total > 0 else 0,
            'short_sessions': short_total,
            'short_wins': short_wins,
            'short_win_rate': short_wins / short_total if short_total > 0 else 0,
            'prior_bias': prior_bias,
            'avg_similarity': sum(s['similarity'] for s in top_sessions) / len(top_sessions),
            'top_sessions': top_sessions[:5]  # 最相似的5个会话
        }

        # 缓存结果
        self.prior_cache[cache_key] = (prior_bias, analysis)

        return prior_bias, analysis

    def print_analysis(self, analysis: dict):
        """打印先验分析报告"""
        if analysis['status'] == 'insufficient_data':
            print(f"📊 [MEMORY] {analysis['message']}")
            return

        status = "🟢" if analysis['prior_bias'] > 0.1 else "🔴" if analysis['prior_bias'] < -0.1 else "⚪"

        print(f"\n{status} [MEMORY] 先验记忆分析（Layer 1）")
        print("=" * 70)
        print(f"  分析样本: {analysis['similar_sessions']}个相似会话（平均相似度{analysis['avg_similarity']:.2%}）")
        print(f"  LONG: {analysis['long_wins']}/{analysis['long_sessions']} ({analysis['long_win_rate']:.1%})")
        print(f"  SHORT: {analysis['short_wins']}/{analysis['short_sessions']} ({analysis['short_win_rate']:.1%})")
        print(f"  先验偏差: {analysis['prior_bias']:+.2f} ", end="")

        if analysis['prior_bias'] > 0.2:
            print("→ 倾向做多 (历史数据显示LONG胜率更高)")
        elif analysis['prior_bias'] < -0.2:
            print("→ 倾向做空 (历史数据显示SHORT胜率更高)")
        else:
            print("→ 中立 (历史数据无明显偏向)")

        print(f"  最相似的会话:")
        for i, item in enumerate(analysis['top_sessions'][:3], 1):
            sess = item['session']
            sim = item['similarity']
            result = "✅盈利" if sess['is_win'] else "❌亏损"
            print(f"    #{i} {sess['entry_time']} | {sess['side']} @ {sess['entry_price']:.2f} | {result} ${sess['pnl']:+.2f} | 相似度{sim:.2%}")

        print("=" * 70)

    def save_session(self, market_data: dict, side: str, entry_price: float, result: dict):
        """
        保存当前会话的特征到缓存

        注意：实际的交易结果由主系统保存到数据库
        这个方法只用于更新内存缓存
        """
        features = self.extract_session_features(market_data)
        features['side'] = side
        features['entry_price'] = entry_price
        features['result'] = result

        self.session_cache.append(features)

        # 清除先验缓存（因为新数据已添加）
        self.prior_cache.clear()


if __name__ == "__main__":
    # 测试Session Memory系统
    memory = SessionMemory()

    # 模拟当前市场数据
    current_market = {
        'price': 0.35,
        'rsi': 45.0,
        'oracle_score': 3.5,
        'price_history': [0.32, 0.33, 0.34, 0.35, 0.36]
    }

    features = memory.extract_session_features(current_market)
    print("\n当前会话特征:")
    print(json.dumps(features, indent=2))

    prior_bias, analysis = memory.calculate_prior_bias(features)
    memory.print_analysis(analysis)

    print(f"\n先验偏差分数: {prior_bias:+.2f}")
    print("使用方式: signal_score += prior_bias * 2.0  (调整权重)")
