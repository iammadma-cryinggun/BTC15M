#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Polymarket预测学习系统
功能：
1. 记录每次预测（15分钟市场）
2. 自动验证预测准确性
3. 统计分析准确率
4. 按评分区间分析
5. 自动调整参数
6. 生成优化建议
"""

import sqlite3
import json
import requests  # 新增：用于请求历史市场的结算结果
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from colorama import Fore, Style, init

init(autoreset=True)


@dataclass
class PredictionRecord:
    """预测记录"""
    id: int
    timestamp: str
    price: float
    score: float
    rsi: float
    vwap: float
    confidence: float

    # 预测信息
    direction: str  # 'LONG' or 'SHORT'
    recommendation: str
    components: dict

    # 验证信息（15分钟后）
    verified: bool = False
    actual_price: float = 0.0
    actual_change_pct: float = 0.0
    correct: bool = False


class PolymarketPredictionLearning:
    """Polymarket预测学习系统"""

    def __init__(self, db_path='btc_15min_predictionsv2.db', current_params=None):
        self.db_path = db_path
        self.current_params = current_params or {
            'min_confidence': 0.30,
            'min_long_score': 2.5,
            'min_short_score': -2.5
        }
        # 🚀 HTTP Session（复用TCP连接，提速API请求）
        self.http_session = requests.Session()
        self._init_db()

    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 预测记录表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                price REAL NOT NULL,
                score REAL NOT NULL,
                rsi REAL NOT NULL,
                vwap REAL NOT NULL,
                confidence REAL NOT NULL,

                direction TEXT NOT NULL,
                recommendation TEXT,
                components TEXT,

                verified INTEGER DEFAULT 0,
                actual_price REAL,
                actual_change_pct REAL,
                correct INTEGER DEFAULT 0,

                market_slug TEXT,
                order_value_usdc REAL,
                order_status TEXT,

                was_blocked INTEGER DEFAULT 0,

                -- 止盈止损百分比记录（新增）
                tp_pct REAL,
                sl_pct REAL,
                entry_token_price REAL,
                exit_token_price REAL,
                actual_pnl_pct REAL,
                exit_reason TEXT
            )
        ''')

        # 参数调整历史表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS parameter_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                parameter_name TEXT NOT NULL,
                old_value REAL,
                new_value REAL,
                reason TEXT,
                accuracy_before REAL,
                accuracy_after REAL
            )
        ''')

        # 每日统计表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_stats (
                date TEXT PRIMARY KEY,
                total_predictions INTEGER,
                verified_predictions INTEGER,
                correct_predictions INTEGER,
                accuracy_pct REAL,

                long_correct INTEGER,
                long_total INTEGER,
                short_correct INTEGER,
                short_total INTEGER,

                avg_score REAL,
                avg_confidence REAL,
                total_trades_executed INTEGER
            )
        ''')

        conn.commit()
        conn.close()

    def record_prediction(self,
                         price: float,
                         score: float,
                         rsi: float,
                         vwap: float,
                         confidence: float,
                         direction: str,
                         recommendation: str,
                         components: dict,
                         market_slug: str = None,
                         order_value: float = 0,
                         order_status: str = 'none',
                         was_blocked: bool = False,
                         tp_pct: float = None,
                         sl_pct: float = None,
                         entry_token_price: float = None) -> int:
        """
        记录一次预测（基于Polymarket token价格）

        参数:
            price: YES token价格
            was_blocked: 信号是否被风险控制拦截（未交易）
            tp_pct: 止盈百分比（如 0.05 = 5%）
            sl_pct: 止损百分比（如 0.03 = 3%）
            entry_token_price: 实际入场价格（下单后的成交价）

        返回: 记录ID
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute('''
            INSERT INTO predictions (
                timestamp, price, score, rsi, vwap, confidence,
                direction, recommendation, components,
                market_slug, order_value_usdc, order_status,
                was_blocked, tp_pct, sl_pct, entry_token_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            timestamp, price, score, rsi, vwap, confidence,
            direction, recommendation, json.dumps(components, ensure_ascii=False),
            market_slug, order_value, order_status,
            1 if was_blocked else 0,
            tp_pct, sl_pct, entry_token_price if entry_token_price else price
        ))

        record_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return record_id

    def verify_prediction(self, record_id: int, current_token_price: float) -> Optional[Dict]:
        """
        验证预测准确性（15分钟后，基于Polymarket token价格）

        参数:
            record_id: 预测记录ID
            current_token_price: 当前YES token价格

        返回: 验证结果
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 获取预测记录
        cursor.execute('SELECT * FROM predictions WHERE id = ?', (record_id,))
        record = cursor.fetchone()

        if not record:
            conn.close()
            return None

        # 解析数据
        pred_token_price = record[2]  # 预测时的YES token价格
        direction = record[7]  # LONG or SHORT

        # 判断是否正确 - 基于YES token价格变化
        # LONG: YES价格涨 → 正确
        # SHORT: YES价格跌 → 正确

        token_change_pct = ((current_token_price - pred_token_price) / pred_token_price) * 100

        if direction == 'LONG':
            # 做多：YES涨了就正确
            correct = current_token_price > pred_token_price
        else:  # SHORT
            # 做空：YES跌了就正确
            correct = current_token_price < pred_token_price

        verification_method = 'TOKEN_PRICE'

        # 更新数据库
        cursor.execute('''
            UPDATE predictions
            SET verified = 1,
                actual_price = ?,
                actual_change_pct = ?,
                correct = ?
            WHERE id = ?
        ''', (current_token_price, token_change_pct, 1 if correct else 0, record_id))

        conn.commit()
        conn.close()

        return {
            'predicted_token_price': pred_token_price,
            'actual_token_price': current_token_price,
            'token_change_pct': token_change_pct,
            'predicted_direction': direction,
            'correct': correct,
            'verification_method': verification_method
        }

    def update_exit_result(self, market_slug: str, exit_token_price: float,
                           actual_pnl_pct: float, exit_reason: str):
        """
        止盈/止损/信号反转触发时，回填实际退出价格和盈亏百分比
        找最近一条该市场的未退出预测记录更新

        参数:
            market_slug: 市场标识
            exit_token_price: 实际退出时的 YES token 价格
            actual_pnl_pct: 实际盈亏百分比（正=盈利，负=亏损）
            exit_reason: 'TAKE_PROFIT' / 'STOP_LOSS' / 'SIGNAL_CHANGE'
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE predictions
                SET exit_token_price = ?,
                    actual_pnl_pct = ?,
                    exit_reason = ?
                WHERE id = (
                    SELECT id FROM predictions
                    WHERE market_slug = ?
                      AND order_status = 'posted'
                      AND exit_token_price IS NULL
                    ORDER BY timestamp DESC
                    LIMIT 1
                )
            ''', (exit_token_price, actual_pnl_pct, exit_reason, market_slug))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[LEARNING] update_exit_result 失败: {e}")
    def get_accuracy_stats(self, hours: int = 24) -> Dict:
        """
        获取准确率统计
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        time_threshold = datetime.now() - timedelta(hours=hours)

        # 获取已验证的预测
        cursor.execute('''
            SELECT direction, correct, score, confidence
            FROM predictions
            WHERE verified = 1 AND timestamp >= ?
        ''', (time_threshold.strftime('%Y-%m-%d %H:%M:%S'),))

        results = cursor.fetchall()
        conn.close()

        if not results:
            return {
                'total': 0,
                'correct': 0,
                'accuracy': 0,
                'long_correct': 0,
                'long_total': 0,
                'short_correct': 0,
                'short_total': 0,
                'avg_score': 0,
                'avg_confidence': 0
            }

        total = len(results)
        correct = sum(1 for r in results if r[1] == 1)
        accuracy = (correct / total) * 100 if total > 0 else 0

        # 分类统计
        long_correct = sum(1 for r in results if r[0] == 'LONG' and r[1] == 1)
        long_total = sum(1 for r in results if r[0] == 'LONG')
        short_correct = sum(1 for r in results if r[0] == 'SHORT' and r[1] == 1)
        short_total = sum(1 for r in results if r[0] == 'SHORT')

        avg_score = sum(r[2] for r in results) / total
        avg_confidence = sum(r[3] for r in results) / total

        return {
            'total': total,
            'correct': correct,
            'accuracy': accuracy,
            'long_correct': long_correct,
            'long_total': long_total,
            'short_correct': short_correct,
            'short_total': short_total,
            'long_accuracy': (long_correct / long_total * 100) if long_total > 0 else 0,
            'short_accuracy': (short_correct / short_total * 100) if short_total > 0 else 0,
            'avg_score': avg_score,
            'avg_confidence': avg_confidence
        }

    def analyze_by_score_range(self) -> List[Dict]:
        """按评分区间分析准确率（8档精细分析）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT
                CASE
                    WHEN score >= 12 THEN '极强多 (≥12)'
                    WHEN score >= 10 THEN '强多 (10-12)'
                    WHEN score >= 7  THEN '中多 (7-10)'
                    WHEN score >= 5  THEN '弱多 (5-7)'
                    WHEN score >= -5 THEN '震荡 (-5~5)'
                    WHEN score >= -7 THEN '弱空 (-7~-5)'
                    WHEN score >= -10 THEN '中空 (-10~-7)'
                    ELSE '强空 (<-10)'
                END as score_range,
                COUNT(*) as total,
                SUM(correct) as correct,
                AVG(confidence) as avg_confidence,
                AVG(actual_pnl_pct) as avg_pnl
            FROM predictions
            WHERE verified = 1
            GROUP BY score_range
            ORDER BY MIN(score) DESC
        ''')

        results = cursor.fetchall()
        conn.close()

        analysis = []
        for row in results:
            score_range, total, correct, avg_conf, avg_pnl = row
            accuracy = (correct / total * 100) if total > 0 else 0
            analysis.append({
                'score_range': score_range,
                'total': total,
                'correct': correct,
                'accuracy': accuracy,
                'avg_confidence': avg_conf or 0,
                'avg_pnl': avg_pnl or 0,
            })

        return analysis

    def find_best_confidence_threshold(self) -> float:
        """遍历50%-90%找最优置信度阈值"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT confidence, correct FROM predictions WHERE verified = 1')
            rows = cursor.fetchall()
            conn.close()

            if len(rows) < 10:
                return 0.70

            best_threshold = 0.70
            best_accuracy = 0

            for t in range(50, 91, 5):
                threshold = t / 100.0
                filtered = [r for r in rows if r[0] >= threshold]
                if len(filtered) >= 5:
                    accuracy = sum(1 for r in filtered if r[1] == 1) / len(filtered) * 100
                    if accuracy > best_accuracy:
                        best_accuracy = accuracy
                        best_threshold = threshold

            return best_threshold
        except:
            return 0.70

    def analyze_tp_sl_performance(self) -> Dict:
        """
        分析历史止盈止损百分比表现
        返回：各退出原因的统计、推荐最优 tp_pct / sl_pct
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 按退出原因统计
            cursor.execute('''
                SELECT exit_reason,
                       COUNT(*) as total,
                       AVG(actual_pnl_pct) as avg_pnl,
                       AVG(tp_pct) as avg_tp,
                       AVG(sl_pct) as avg_sl
                FROM predictions
                WHERE exit_reason IS NOT NULL
                  AND actual_pnl_pct IS NOT NULL
                GROUP BY exit_reason
            ''')
            by_reason = {}
            for row in cursor.fetchall():
                reason, total, avg_pnl, avg_tp, avg_sl = row
                by_reason[reason] = {
                    'total': total,
                    'avg_pnl_pct': round(avg_pnl or 0, 4),
                    'avg_tp_pct': round(avg_tp or 0, 4),
                    'avg_sl_pct': round(avg_sl or 0, 4),
                }

            # 找出盈利交易的平均 tp_pct（用于推荐）
            # 只统计真正的止盈止损退出，不包括MARKET_SETTLED
            cursor.execute('''
                SELECT COUNT(*) as total, AVG(tp_pct), AVG(sl_pct)
                FROM predictions
                WHERE actual_pnl_pct > 0
                  AND exit_reason IN ('TAKE_PROFIT', 'STOP_LOSS', 'SIGNAL_CHANGE')
            ''')
            row = cursor.fetchone()
            total_count = row[0] if row else 0
            # 只有当有足够样本（>=10笔真正的TP/SL交易）时才推荐
            if total_count >= 10:
                recommended_tp = round((row[1] or 0.05), 4) if row else 0.05
                recommended_sl = round((row[2] or 0.03), 4) if row else 0.03
            else:
                recommended_tp = None
                recommended_sl = None

            # 按评分区间分析盈亏
            cursor.execute('''
                SELECT
                    CASE
                        WHEN ABS(score) >= 7 THEN '极强(≥7)'
                        WHEN ABS(score) >= 5 THEN '强(5-7)'
                        WHEN ABS(score) >= 3 THEN '中(3-5)'
                        ELSE '弱(<3)'
                    END as score_range,
                    COUNT(*) as total,
                    AVG(actual_pnl_pct) as avg_pnl,
                    SUM(CASE WHEN actual_pnl_pct > 0 THEN 1 ELSE 0 END) as wins
                FROM predictions
                WHERE actual_pnl_pct IS NOT NULL
                GROUP BY score_range
                ORDER BY ABS(score) DESC
            ''')
            by_score = []
            for row in cursor.fetchall():
                score_range, total, avg_pnl, wins = row
                by_score.append({
                    'score_range': score_range,
                    'total': total,
                    'avg_pnl_pct': round(avg_pnl or 0, 4),
                    'win_rate': round((wins / total * 100) if total > 0 else 0, 1),
                })

            conn.close()
            return {
                'by_reason': by_reason,
                'by_score': by_score,
                'recommended_tp_pct': recommended_tp,
                'recommended_sl_pct': recommended_sl,
            }
        except Exception as e:
            return {'error': str(e)}

    def print_tp_sl_report(self):
        """打印止盈止损百分比分析报告"""
        from colorama import Fore, Style
        result = self.analyze_tp_sl_performance()
        if 'error' in result:
            print(f"[TP/SL] 分析失败: {result['error']}")
            return

        print(f"\n{Fore.CYAN}{'='*80}{Fore.RESET}")
        print(f"{Fore.CYAN}【止盈止损百分比分析报告】{Fore.RESET}")

        by_reason = result.get('by_reason', {})
        if by_reason:
            print(f"\n{Fore.WHITE}【按退出原因统计】{Fore.RESET}")
            print(f"  {'退出原因':<20} {'次数':>6} {'平均盈亏%':>10} {'平均TP%':>8} {'平均SL%':>8}")
            print(f"  {'-'*20} {'-'*6} {'-'*10} {'-'*8} {'-'*8}")
            for reason, s in by_reason.items():
                color = Fore.GREEN if s['avg_pnl_pct'] > 0 else Fore.RED
                print(f"  {reason:<20} {s['total']:>6} "
                      f"{color}{s['avg_pnl_pct']*100:>+9.2f}%{Fore.RESET} "
                      f"{s['avg_tp_pct']*100:>7.2f}% {s['avg_sl_pct']*100:>7.2f}%")

        by_score = result.get('by_score', [])
        if by_score:
            print(f"\n{Fore.WHITE}【按评分区间盈亏】{Fore.RESET}")
            print(f"  {'评分区间':<12} {'次数':>6} {'胜率':>8} {'平均盈亏%':>10}")
            print(f"  {'-'*12} {'-'*6} {'-'*8} {'-'*10}")
            for s in by_score:
                color = Fore.GREEN if s['avg_pnl_pct'] > 0 else Fore.RED
                print(f"  {s['score_range']:<12} {s['total']:>6} "
                      f"{s['win_rate']:>7.1f}% "
                      f"{color}{s['avg_pnl_pct']*100:>+9.2f}%{Fore.RESET}")

        print(f"\n{Fore.YELLOW}【推荐参数】{Fore.RESET}")
        if result['recommended_tp_pct'] is not None:
            print(f"  推荐 tp_pct: {result['recommended_tp_pct']*100:.2f}%")
            print(f"  推荐 sl_pct: {result['recommended_sl_pct']*100:.2f}%")
        else:
            print(f"  推荐 tp_pct: 暂无足够数据（需要>=10笔真正的止盈止损交易）")
            print(f"  推荐 sl_pct: 暂无足够数据（需要>=10笔真正的止盈止损交易）")
        print(f"{Fore.CYAN}{'='*80}{Fore.RESET}\n")

    def get_optimization_suggestions(self) -> List[str]:
        """
        分析历史数据，提供优化建议
        """
        suggestions = []
        stats = self.get_accuracy_stats(hours=24)
        score_analysis = self.analyze_by_score_range()

        # 建议1: 哪个方向更准确
        if stats['total'] > 10:
            if stats['long_accuracy'] > stats['short_accuracy'] + 10:
                suggestions.append("✓ 做多信号准确率更高，做多信号更可靠")
            elif stats['short_accuracy'] > stats['long_accuracy'] + 10:
                suggestions.append("✓ 做空信号准确率更高，做空信号更可靠")

        # 建议2: 找出最可靠的评分区间
        if score_analysis:
            best_ranges = [r for r in score_analysis if r['total'] >= 3]
            if best_ranges:
                best = max(best_ranges, key=lambda x: x['accuracy'])
                if best['accuracy'] >= 70:
                    suggestions.append(f"✓ 评分区间 '{best['score_range']}' 准确率最高 ({best['accuracy']:.1f}%)，建议重点关注")

        # 建议3: 置信度阈值建议（直接查询数据库）
        if stats['total'] > 10:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) as total, SUM(correct) as correct
                FROM predictions
                WHERE verified=1 AND confidence >= 0.70
            ''')
            row = cursor.fetchone()
            conn.close()

            if row and row[0] >= 3:
                high_conf_total, high_conf_correct = row
                avg_high_acc = (high_conf_correct / high_conf_total * 100) if high_conf_total > 0 else 0
                if avg_high_acc >= 70:
                    suggestions.append(f"✓ 高置信度(≥70%)预测平均准确率 {avg_high_acc:.1f}%，建议只在置信度≥70%时交易")

        # 建议4: 评分阈值建议
        if score_analysis:
            high_score = [r for r in score_analysis if '极强' in r['score_range'] or '强' in r['score_range']]
            if high_score and sum(r['total'] for r in high_score) >= 5:
                avg_high_score_acc = sum(r['accuracy'] * r['total'] for r in high_score) / sum(r['total'] for r in high_score)
                if avg_high_score_acc >= 70:
                    suggestions.append(f"✓ 高评分信号(≥7)平均准确率 {avg_high_score_acc:.1f}%，建议提高评分阈值至7")

        return suggestions

    def print_accuracy_report(self):
        """打印准确率报告"""
        stats = self.get_accuracy_stats(hours=24)
        score_analysis = self.analyze_by_score_range()

        print(f"\n{Fore.CYAN}{'='*80}{Fore.RESET}")
        print(f"{Fore.CYAN}{'📊 预测学习报告':^80}{Fore.RESET}")
        print(f"{Fore.CYAN}{'='*80}{Fore.RESET}")
        print(f"{Fore.CYAN}统计时间: 最近24小时 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{Fore.RESET}\n")

        # 总体准确率
        print(f"{Fore.WHITE}【总体准确率】{Fore.RESET}")
        if stats['total'] > 0:
            acc_color = Fore.GREEN if stats['accuracy'] >= 60 else Fore.YELLOW if stats['accuracy'] >= 50 else Fore.RED
            print(f"  总预测: {stats['total']} 次")
            print(f"  正确: {stats['correct']} 次")
            print(f"  准确率: {acc_color}{stats['accuracy']:.1f}%{Fore.RESET}")
        else:
            print(f"  {Fore.YELLOW}暂无数据（需要至少15分钟验证时间）{Fore.RESET}")

        # 分类准确率
        if stats['total'] > 0:
            print(f"\n{Fore.WHITE}【分类准确率】{Fore.RESET}")
            if stats['long_total'] > 0:
                long_acc_color = Fore.GREEN if stats['long_accuracy'] >= 60 else Fore.YELLOW
                print(f"  做多(UP): {stats['long_correct']}/{stats['long_total']} ({long_acc_color}{stats['long_accuracy']:.1f}%{Fore.RESET})")
            if stats['short_total'] > 0:
                short_acc_color = Fore.GREEN if stats['short_accuracy'] >= 60 else Fore.YELLOW
                print(f"  做空(DOWN): {stats['short_correct']}/{stats['short_total']} ({short_acc_color}{stats['short_accuracy']:.1f}%{Fore.RESET})")

            print(f"\n  平均评分: {stats['avg_score']:.1f}")
            print(f"  平均置信度: {stats['avg_confidence']*100:.1f}%")

        # 按评分区间分析
        if score_analysis:
            print(f"\n{Fore.WHITE}【按评分区间分析】{Fore.RESET}")
            print(f"  {'评分区间':<15} {'次数':>6} {'正确':>6} {'准确率':>8} {'平均置信度':>10}")
            print(f"  {'-'*15} {'-'*6} {'-'*6} {'-'*8} {'-'*10}")

            for item in score_analysis:
                acc_color = Fore.GREEN if item['accuracy'] >= 60 else Fore.YELLOW if item['accuracy'] >= 50 else Fore.RED
                print(f"  {item['score_range']:<15} {item['total']:>6} {item['correct']:>6} "
                      f"{acc_color}{item['accuracy']:>7.1f}%{Fore.RESET} {item['avg_confidence']*100:>9.1f}%")

        print(f"{Fore.CYAN}{'='*80}{Fore.RESET}\n")

    def get_recommended_parameters(self) -> Dict:
        """
        根据历史表现推荐参数调整（基于当前实际参数）
        """
        stats = self.get_accuracy_stats(hours=24)
        score_analysis = self.analyze_by_score_range()
        suggestions = []

        # 使用当前实际参数
        current_min_conf = self.current_params.get('min_confidence', 0.30)
        current_min_long_score = self.current_params.get('min_long_score', 2.5)
        current_min_short_score = self.current_params.get('min_short_score', -2.5)

        recommended = {
            'min_confidence': current_min_conf,
            'min_long_score': current_min_long_score,
            'min_short_score': current_min_short_score,
            'reasons': []
        }

        # 分析置信度（自动搜索最优阈值）
        if stats['total'] >= 10:
            best_threshold = self.find_best_confidence_threshold()
            if best_threshold != current_min_conf:
                recommended['min_confidence'] = best_threshold
                recommended['reasons'].append(f"自动搜索最优置信度阈值: {current_min_conf:.2f} → {best_threshold:.2f}")

        # 分析评分阈值
        if score_analysis:
            # 检查高评分区间表现
            high_score_ranges = [r for r in score_analysis if '极强' in r['score_range'] or '强' in r['score_range']]
            if high_score_ranges and sum(r['total'] for r in high_score_ranges) >= 5:
                high_score_total = sum(r['total'] for r in high_score_ranges)
                high_score_correct = sum(r['correct'] for r in high_score_ranges)
                high_score_acc = (high_score_correct / high_score_total * 100)

                if high_score_acc >= 70 and stats['accuracy'] < high_score_acc:
                    recommended['min_long_score'] = 7.0
                    recommended['min_short_score'] = -7.0
                    recommended['reasons'].append(f"高评分(≥7)准确率 {high_score_acc:.1f}% vs 总体 {stats['accuracy']:.1f}%")

        # 动态调整 allow_long（基于做多准确率）
        if stats['long_total'] >= 10:  # 至少10次做多信号
            long_acc = stats['long_accuracy']
            if long_acc < 50:
                # 做多准确率低于50%，禁用做多
                recommended['allow_long'] = False
                recommended['reasons'].append(f"做多准确率 {long_acc:.1f}% < 50%，建议禁用做多")
            elif long_acc >= 60:
                # 做多准确率高于60%，重新启用做多
                recommended['allow_long'] = True
                recommended['reasons'].append(f"做多准确率 {long_acc:.1f}% ≥ 60%，建议启用做多")

        # 动态调整 allow_short（基于做空准确率）
        if stats['short_total'] >= 10:  # 至少10次做空信号
            short_acc = stats['short_accuracy']
            if short_acc < 50:
                # 做空准确率低于50%，禁用做空
                recommended['allow_short'] = False
                recommended['reasons'].append(f"做空准确率 {short_acc:.1f}% < 50%，建议禁用做空")
            elif short_acc >= 60:
                # 做空准确率高于60%，重新启用做空
                recommended['allow_short'] = True
                recommended['reasons'].append(f"做空准确率 {short_acc:.1f}% ≥ 60%，建议启用做空")

        return recommended

    def verify_pending_predictions(self) -> int:
        """
        验证所有未验证的预测

        参数:
            current_btc_price: 当前BTC价格（如果为0则从API获取）
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 找出15分钟前未验证的记录
        time_threshold = datetime.now() - timedelta(minutes=15)
        cursor.execute('''
            SELECT id, price, market_slug FROM predictions
            WHERE verified = 0 AND datetime(timestamp) < ?
        ''', (time_threshold.strftime('%Y-%m-%d %H:%M:%S'),))

        pending = cursor.fetchall()
        verified_count = 0

        if not pending:
            conn.close()
            return 0

        proxies = {'http': 'http://127.0.0.1:15236', 'https': 'http://127.0.0.1:15236'}

        # 缓存已查询的市场价格，避免重复请求
        slug_price_cache = {}

        def get_token_price_for_slug(slug: str) -> Optional[float]:
            """从 Polymarket Gamma API 获取市场当前 YES token 价格"""
            if slug in slug_price_cache:
                return slug_price_cache[slug]
            try:
                # 🚀 使用Session复用TCP连接（提速API请求）
                resp = self.http_session.get(
                    "https://gamma-api.polymarket.com/markets",
                    params={'slug': slug},
                    proxies=proxies,
                    timeout=10
                )
                if resp.status_code == 200:
                    markets = resp.json()
                    if markets:
                        outcome_prices = markets[0].get('outcomePrices', '[]')
                        if isinstance(outcome_prices, str):
                            outcome_prices = json.loads(outcome_prices)
                        if outcome_prices:
                            price = float(outcome_prices[0])
                            slug_price_cache[slug] = price
                            return price
            except Exception as e:
                # 网络错误静默处理，下次再试
                slug_price_cache[slug] = None
            return None

        # 验证所有待验证的预测
        for record_id, pred_token_price, market_slug in pending:
            try:
                token_price = None

                # 优先用对应市场的 YES token 价格
                if market_slug:
                    token_price = get_token_price_for_slug(market_slug)

                # 如果市场已结算（价格为0或1），直接用结算价
                # 如果获取失败，跳过本条（不用错误数据污染学习）
                if token_price is None:
                    continue

                if self.verify_prediction(record_id, token_price):
                    verified_count += 1
            except Exception as e:
                pass

        conn.close()

        if verified_count > 0:
            from colorama import Fore
            print(f"\n{Fore.CYAN}[LEARNING] 成功验证了 {verified_count} 条预测（基于 YES token 价格）{Fore.RESET}\n")

        return verified_count

    def print_optimization_report(self):
        """打印优化建议报告"""
        suggestions = self.get_optimization_suggestions()

        print(f"\n{Fore.CYAN}{'='*80}{Fore.RESET}")
        print(f"{Fore.CYAN}{'🎯 优化建议':^80}{Fore.RESET}")
        print(f"{Fore.CYAN}{'='*80}{Fore.RESET}\n")

        if suggestions:
            for i, suggestion in enumerate(suggestions, 1):
                print(f"  {Fore.GREEN}{i}. {suggestion}{Fore.RESET}")

            # 推荐参数
            recommended = self.get_recommended_parameters()
            if recommended['reasons']:
                print(f"\n{Fore.WHITE}【推荐参数调整】{Fore.RESET}")
                current = self.current_params

                if recommended['min_confidence'] != current['min_confidence']:
                    print(f"  min_confidence: {current['min_confidence']:.2f} → {recommended['min_confidence']:.2f}")
                if recommended['min_long_score'] != current['min_long_score']:
                    print(f"  min_long_score: {current['min_long_score']:.1f} → {recommended['min_long_score']:.1f}")
                if recommended['min_short_score'] != current['min_short_score']:
                    print(f"  min_short_score: {current['min_short_score']:.1f} → {recommended['min_short_score']:.1f}")

                print(f"\n{Fore.CYAN}调整原因：{Fore.RESET}")
                for reason in recommended['reasons']:
                    print(f"  • {reason}")
        else:
            print(f"  {Fore.YELLOW}暂无足够数据生成优化建议（需要至少10条验证记录）{Fore.RESET}")

        print(f"\n{Fore.CYAN}{'='*80}{Fore.RESET}\n")


def main():
    """测试函数"""
    pls = PolymarketPredictionLearning()

    # 模拟记录预测
    components = {
        'price_momentum': 2.5,
        'volatility': 1.0,
        'vwap_status': 0.5,
        'rsi_status': 0.0,
        'trend_strength': 0.2
    }

    record_id = pls.record_prediction(
        price=0.5000,
        score=4.2,
        rsi=55.0,
        vwap=0.5050,
        confidence=0.84,
        direction='LONG',
        recommendation='看涨 (做多YES)',
        components=components,
        market_slug='btc-updown-15m-1771521300',
        order_value=2.75,
        order_status='posted'
    )

    print(f"✓ 预测已记录，ID: {record_id}")

    # 打印报告
    pls.print_accuracy_report()
    pls.print_optimization_report()


if __name__ == "__main__":
    main()