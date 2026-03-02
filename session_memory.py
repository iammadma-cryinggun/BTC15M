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

        # Session预加载缓存
        self.current_session_id = None  # 当前session ID (格式: YYYYMMDD_HHMM)
        self.current_session_bias = 0.0  # 当前session的prior_bias
        self.current_session_analysis = {}  # 当前session的分析详情

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

        特征包括（热心哥原版要求）：
        1. 价格区间（5个bins）
        2. 时间段（00/15/30/45）
        3. RSI初始值
        4. CVD强度（替代Oracle分数）
        5. 5分钟价格趋势
        6. 波动率（Volatility）← 新增
        """
        price = market_data.get('price', 0.5)
        rsi = market_data.get('rsi', 50.0)
        oracle = market_data.get('oracle', {})
        cvd_5m = oracle.get('cvd_5m', 0.0)  # 使用CVD替代oracle_score
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

        # 4. CVD归一化（-1到+1），使用5分钟CVD范围[-150000, +150000]
        cvd_normalized = max(-1.0, min(1.0, cvd_5m / 150000.0))

        # 5. 5分钟价格趋势（如果有历史数据）
        price_trend = 0.0
        if len(price_history) >= 5:
            recent = price_history[-5:]
            trend = (recent[-1] - recent[0]) / recent[0] if recent[0] > 0 else 0
            price_trend = max(-1.0, min(1.0, trend / 0.1))  # 归一化到-1到+1

        # 6. 波动率（Volatility）← 新增特征
        # 计算价格历史的标准差作为波动率指标
        volatility = 0.0
        if len(price_history) >= 10:
            # 使用最近10个价格点计算波动率
            import statistics
            prices = price_history[-10:]
            # 标准差归一化：除以平均价格，得到相对波动率
            std_dev = statistics.stdev(prices)
            avg_price = statistics.mean(prices)
            volatility = std_dev / avg_price if avg_price > 0 else 0.0
            # 归一化到0-1范围（假设波动率范围0-0.3）
            volatility = min(1.0, volatility / 0.3)

        features = {
            'price_bin': price_bin,
            'time_slot': time_slot,
            'rsi': rsi_normalized,
            'cvd': cvd_normalized,
            'price_trend': price_trend,
            'volatility': volatility,  # ← 新增：波动率特征
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
            'cvd': 1.5,            # CVD强度重要
            'price_trend': 1.0,    # 价格趋势
            'volatility': 1.2      # 波动率（新增）
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

            # 查询已关闭的仓位（包含完整指标数据）
            sql = """
            SELECT
                entry_time,
                side,
                entry_token_price,
                exit_token_price,
                pnl_usd,
                status,
                score,
                rsi,
                vwap,
                cvd_5m,
                cvd_1m,
                prior_bias,
                defense_multiplier,
                minutes_to_expiry
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

                # 从数据库读取真实指标（用于相似度匹配）
                cvd_5m = row['cvd_5m'] or 0.0
                cvd_1m = row['cvd_1m'] or 0.0
                cvd_combined = cvd_5m * 0.7 + cvd_1m * 0.3  # 与防御层一致

                session = {
                    'entry_time': row['entry_time'],
                    'side': row['side'],
                    'entry_price': row['entry_token_price'],
                    'exit_price': row['exit_token_price'],
                    'pnl': row['pnl_usd'] or 0.0,
                    'is_win': is_win,
                    'is_long': is_long,
                    'score': row['score'] or 0.0,
                    'cvd': cvd_combined,  # 真实CVD数据
                    'rsi': row['rsi'] or 50.0,  # 真实RSI数据
                    'vwap': row['vwap'] or 0.0,  # 真实VWAP数据
                    'prior_bias': row['prior_bias'] or 0.0,  # 真实先验偏差
                    'defense_multiplier': row['defense_multiplier'] or 1.0,  # 真实防御乘数
                    'minutes_to_expiry': row['minutes_to_expiry'] or 0,  # Session剩余分钟数
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
                'cvd': max(-1.0, min(1.0, session['cvd'] / 150000.0)),
                'price_trend': 0.0,  # 历史数据没有价格趋势，设为0
                'volatility': 0.5  # 历史数据没有波动率，设为中性值（权重影响小）
            }

            similarity = self.calculate_similarity(current_features, hist_features)
            sessions_with_similarity.append({
                'session': session,
                'similarity': similarity
            })

        # 按相似度排序，选择最相似的min_sessions个
        sessions_with_similarity.sort(key=lambda x: x['similarity'], reverse=True)
        top_sessions = sessions_with_similarity[:min_sessions]

        # 🕐 Layer 1优化：最后6分钟加权优先
        # 回测数据显示：session最后6分钟指标最可靠，给予更高权重
        def get_time_weight(minutes_to_expiry: int) -> float:
            """根据session剩余时间返回权重（最后6分钟优先）"""
            if minutes_to_expiry <= 6:
                return 2.0  # 黄金6分钟：最高权重
            elif minutes_to_expiry <= 9:
                return 1.5  # 7-9分钟：中等权重
            else:
                return 1.0  # 10-14分钟：正常权重

        # 统计LONG/SHORT的加权胜率
        long_weighted_wins = 0.0
        long_total_weight = 0.0
        short_weighted_wins = 0.0
        short_total_weight = 0.0

        for item in top_sessions:
            session = item['session']
            weight = get_time_weight(session.get('minutes_to_expiry', 0))

            if session['is_long']:
                long_total_weight += weight
                if session['is_win']:
                    long_weighted_wins += weight
            else:
                short_total_weight += weight
                if session['is_win']:
                    short_weighted_wins += weight

        # 计算加权方向性胜率
        # 如果LONG胜率高 → 倾向做多（prior_bias > 0）
        # 如果SHORT胜率高 → 倾向做空（prior_bias < 0）
        if long_total_weight >= 5.0 and short_total_weight >= 5.0:
            long_win_rate = long_weighted_wins / long_total_weight
            short_win_rate = short_weighted_wins / short_total_weight

            # 方向偏差：LONG胜率 - SHORT胜率
            direction_bias = long_win_rate - short_win_rate

            # 转换为先验分数（-1到+1）
            prior_bias = max(-1.0, min(1.0, direction_bias * 2))  # 放大效果
        else:
            # 某个方向数据不足，使用总体加权胜率
            total_weighted_wins = long_weighted_wins + short_weighted_wins
            total_weight = long_total_weight + short_total_weight
            total_win_rate = total_weighted_wins / total_weight if total_weight > 0 else 0.5
            # 如果总体胜率>50%，使用LONG偏倚（保守策略）
            prior_bias = (total_win_rate - 0.5) * 0.5  # 缩小效果，更保守

        # 统计原始数量（用于显示）
        long_count = sum(1 for s in top_sessions if s['session']['is_long'])
        short_count = sum(1 for s in top_sessions if not s['session']['is_long'])

        # 统计最后6分钟的交易数量
        last_6min_sessions = [s for s in top_sessions if s['session'].get('minutes_to_expiry', 0) <= 6]
        last_6min_count = len(last_6min_sessions)

        # 构建分析报告
        analysis = {
            'status': 'success',
            'total_sessions_analyzed': len(historical_sessions),
            'similar_sessions': min_sessions,
            'long_sessions': long_count,
            'long_wins': sum(1 for s in top_sessions if s['session']['is_long'] and s['session']['is_win']),
            'long_win_rate': long_weighted_wins / long_total_weight if long_total_weight > 0 else 0,
            'short_sessions': short_count,
            'short_wins': sum(1 for s in top_sessions if not s['session']['is_long'] and s['session']['is_win']),
            'short_win_rate': short_weighted_wins / short_total_weight if short_total_weight > 0 else 0,
            'prior_bias': prior_bias,
            'avg_similarity': sum(s['similarity'] for s in top_sessions) / len(top_sessions),
            'last_6min_count': last_6min_count,  # 最后6分钟的交易数量
            'top_sessions': top_sessions[:5]  # 最相似的5个会话
        }

        # 缓存结果
        self.prior_cache[cache_key] = (prior_bias, analysis)

        return prior_bias, analysis

    def preload_session_bias(self, price: float, rsi: float, oracle: dict, price_history: list = None) -> bool:
        """
        在session开始时预加载prior_bias

        在每个15分钟session开始时调用，计算并缓存整个session的先验bias。
        之后同一session的信号生成直接使用缓存值，无需重新计算。

        Args:
            price: 当前价格
            rsi: 当前RSI
            oracle: Oracle数据字典（包含cvd_5m等）
            price_history: 价格历史列表

        Returns:
            bool: 是否成功预加载
        """
        try:
            # 计算当前session ID
            now = datetime.now()
            session_id = now.strftime('%Y%m%d_%H%M')

            # 检查是否是新的session
            if self.current_session_id == session_id:
                # 同一个session，已预加载过
                return True

            # 提取特征
            market_features = {
                'price': price,
                'rsi': rsi,
                'oracle': oracle or {},
                'price_history': price_history or []
            }

            features = self.extract_session_features(market_features)

            # 计算prior_bias
            prior_bias, analysis = self.calculate_prior_bias(features)

            # 缓存session级别的结果
            self.current_session_id = session_id
            self.current_session_bias = prior_bias
            self.current_session_analysis = analysis

            # 打印预加载结果
            self.print_preload_result(analysis)

            return True

        except Exception as e:
            print(f"[MEMORY ERROR] 预加载失败: {e}")
            # 使用中立先验
            self.current_session_bias = 0.0
            self.current_session_analysis = {'status': 'error', 'error': str(e)}
            return False

    def get_cached_bias(self) -> float:
        """
        获取当前session缓存的prior_bias

        在信号生成时调用，快速返回预计算的bias值。
        """
        return self.current_session_bias

    def get_cached_analysis(self) -> dict:
        """获取当前session缓存的analysis详情"""
        return self.current_session_analysis

    def print_preload_result(self, analysis: dict):
        """打印预加载结果"""
        if analysis.get('status') == 'insufficient_data':
            print(f"⚪ [MEMORY-L1] Session预加载: 历史数据不足，使用中立先验 (0.00)")
            return

        bias = analysis.get('prior_bias', 0.0)
        emoji = "🟢" if bias > 0.2 else "🔴" if bias < -0.2 else "⚪"

        long_wr = analysis.get('long_win_rate', 0.0)
        short_wr = analysis.get('short_win_rate', 0.0)
        similar = analysis.get('similar_sessions', 0)
        last_6min = analysis.get('last_6min_count', 0)

        print(f"{emoji} [MEMORY-L1] Session预加载完成")
        print(f"     基于过去{similar}个相似session(含{last_6min}个黄金6分钟)")
        print(f"     加权胜率: LONG={long_wr:.1%} SHORT={short_wr:.1%} (最后6分钟权重2x)")
        print(f"     先验bias: {bias:+.2f} {'(倾向做多)' if bias > 0.2 else '(倾向做空)' if bias < -0.2 else '(中立)'}")

    def print_analysis(self, analysis: dict):
        """打印先验分析报告"""
        if analysis['status'] == 'insufficient_data':
            print(f"📊 [MEMORY] {analysis['message']}")
            return

        status = "🟢" if analysis['prior_bias'] > 0.1 else "🔴" if analysis['prior_bias'] < -0.1 else "⚪"

        print(f"\n{status} [MEMORY] 先验记忆分析（Layer 1）")
        print("=" * 70)
        print(f"  分析样本: {analysis['similar_sessions']}个相似会话（平均相似度{analysis['avg_similarity']:.2%}）")
        print(f"  🕐 时间加权: {analysis['last_6min_count']}个黄金6分钟会话(权重2x) + {analysis['similar_sessions'] - analysis['last_6min_count']}个其他会话")
        print(f"  LONG: {analysis['long_wins']}/{analysis['long_sessions']} ({analysis['long_win_rate']:.1%} 加权)")
        print(f"  SHORT: {analysis['short_wins']}/{analysis['short_sessions']} ({analysis['short_win_rate']:.1%} 加权)")
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
            minutes = sess.get('minutes_to_expiry', 0)
            weight_icon = "⭐" if minutes <= 6 else ""
            print(f"    #{i} {sess['entry_time']} | {sess['side']} @ {sess['entry_price']:.2f} | {result} ${sess['pnl']:+.2f} | 相似度{sim:.2%} {weight_icon}")

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
