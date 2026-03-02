#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
虚拟交易系统 - 使用真实价格模拟交易

特点：
1. 使用真实市场价格（WebSocket/REST API）
2. 模拟下单、成交、止盈止损
3. 完整记录到数据库
4. 不执行真实交易（不消耗资金）

用途：
- 回测策略
- 验证系统逻辑
- 无风险测试
"""

import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import os
import time
import json
import sqlite3
from datetime import datetime
from typing import Optional, Dict, List

# 复用主系统的配置和类
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auto_trader_ankr import AutoTraderV5, CONFIG


class VirtualTrader:
    """虚拟交易系统 - 模拟真实交易但不执行"""

    def __init__(self, db_path: str = "virtual_trades.db"):
        self.db_path = db_path
        self.real_trader = AutoTraderV5()  # 复用真实交易器的所有逻辑

        # 覆盖关键方法，阻止真实交易
        self.real_trader.place_order = self._mock_place_order
        self.real_trader.place_stop_orders = self._mock_place_stop_orders

        # 虚拟持仓跟踪
        self.virtual_positions = {}  # {token_id: position_data}

        # 初始化数据库
        self._init_db()

        print("=" * 70)
        print("虚拟交易系统已启动")
        print("=" * 70)
        print("模式：模拟交易（使用真实价格，不执行真实下单）")
        print(f"数据库：{db_path}")
        print()

    def _init_db(self):
        """初始化虚拟交易数据库"""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        cursor = conn.cursor()

        # 交易记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS virtual_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                side TEXT,
                entry_price REAL,
                exit_price REAL,
                size REAL,
                value_usdc REAL,
                pnl_usd REAL,
                pnl_pct REAL,
                exit_reason TEXT,
                vote_details TEXT,
                oracle_score REAL,
                confidence REAL
            )
        """)

        # 持仓表（实时跟踪）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS virtual_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_time TEXT,
                side TEXT,
                entry_price REAL,
                size REAL,
                value_usdc REAL,
                take_profit_price REAL,
                stop_loss_price REAL,
                token_id TEXT,
                status TEXT DEFAULT 'open',
                vote_details TEXT,
                oracle_score REAL,
                confidence REAL
            )
        """)

        conn.commit()
        conn.close()
        print("[DB] 虚拟交易数据库已初始化")

    def _mock_place_order(self, market: Dict, signal: Dict) -> Optional[Dict]:
        """模拟下单（不执行真实交易）"""
        try:
            # 获取真实价格
            price = signal.get('price', 0.5)
            side = signal.get('direction', 'LONG')

            # 计算虚拟仓位
            base_value = 3.0  # 固定3 USDC测试
            size = 6  # 固定6份
            actual_price = price

            print(f"       [VIRTUAL] 模拟下单: {side} {size}份 @ {actual_price:.4f}")
            print(f"       [VIRTUAL] 价值: ${base_value:.2f} USDC")

            # 返回模拟订单结果
            return {
                'order_id': f"VIRTUAL_{int(time.time())}",
                'status': 'filled',
                'value': base_value,
                'price': actual_price,
                'size': float(size),
                'token_price': price
            }
        except Exception as e:
            print(f"       [VIRTUAL ERROR] {e}")
            return None

    def _mock_place_stop_orders(self, market, side, size, entry_price, value_usdc, entry_order_id=None):
        """模拟止盈止损单（不执行真实挂单）"""
        try:
            # 计算止盈止损价格
            take_profit_pct = CONFIG['risk'].get('take_profit_pct', 0.20)
            stop_loss_pct = CONFIG['risk'].get('max_stop_loss_pct', 0.50)

            if side == 'LONG':
                tp_price = entry_price * (1 + take_profit_pct)
                sl_price = entry_price * (1 - stop_loss_pct)
            else:
                tp_price = entry_price * (1 - take_profit_pct)
                sl_price = entry_price * (1 + stop_loss_pct)

            print(f"       [VIRTUAL] 止盈: {tp_price:.4f} | 止损: {sl_price:.4f}")

            return None, sl_price, entry_price
        except Exception as e:
            print(f"       [VIRTUAL ERROR] {e}")
            return None, None, None

    def run_virtual_cycle(self):
        """执行一次虚拟交易循环"""
        print("\n" + "=" * 70)
        print("虚拟交易循环开始")
        print("=" * 70)

        # 获取市场数据
        market = self.real_trader.get_market_data()
        if not market:
            print("[ERROR] 无法获取市场数据")
            return

        # 获取真实价格
        price = self.real_trader.parse_price(market)
        if not price:
            print("[ERROR] 无法获取价格")
            return

        print(f"[PRICE] 当前价格: {price:.4f}")

        # 更新指标
        self.real_trader.update_indicators(price, price, price)

        # 生成信号（复用真实交易逻辑）
        signal = self.real_trader.generate_signal(market, price)

        if signal:
            print(f"\n[SIGNAL] {signal['direction']} | 置信度: {signal['confidence']:.0%}")
            print(f"         Score: {signal['score']:.2f} | Oracle: {signal.get('oracle_score', 0):+.2f}")

            # 记录投票详情
            vote_details = signal.get('vote_details', {})
            if vote_details:
                print(f"\n[VOTE DETAILS]")
                print(f"  LONG票: {vote_details.get('long_votes', 0)}")
                print(f"  SHORT票: {vote_details.get('short_votes', 0)}")
                votes = vote_details.get('votes', [])
                for vote in votes[:5]:  # 只显示前5个
                    print(f"  - {vote.get('rule', 'Unknown')}: {vote.get('direction', 'N/A')} ({vote.get('confidence', 0):.0%})")

            # 执行虚拟下单
            order_result = self.real_trader.place_order(market, signal)

            if order_result and order_result.get('status') == 'filled':
                # 记录虚拟交易
                self._record_virtual_trade(market, signal, order_result, price)

        # 检查现有虚拟持仓的止盈止损
        self._check_virtual_positions(market, price)

        # 显示统计
        self._print_statistics()

    def _record_virtual_trade(self, market: Dict, signal: Dict, order_result: Dict, current_price: float):
        """记录虚拟交易到数据库"""
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            cursor = conn.cursor()

            # 保存到持仓表
            token_id = market.get('clobTokenIds', ['UNKNOWN'])[0]
            cursor.execute("""
                INSERT INTO virtual_positions (
                    entry_time, side, entry_price, size, value_usdc,
                    take_profit_price, stop_loss_price, token_id, status,
                    vote_details, oracle_score, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                signal['direction'],
                order_result['price'],
                order_result['size'],
                order_result['value'],
                0.0,  # take_profit_price（稍后计算）
                0.0,  # stop_loss_price（稍后计算）
                str(token_id),
                'open',
                json.dumps(signal.get('vote_details', {}), ensure_ascii=False),
                signal.get('oracle_score', 0.0),
                signal['confidence']
            ))

            conn.commit()
            conn.close()

            print(f"\n[RECORD] 虚拟交易已记录")
            print(f"  方向: {signal['direction']}")
            print(f"  入场价: {order_result['price']:.4f}")
            print(f"  数量: {order_result['size']}")
            print(f"  价值: ${order_result['value']:.2f} USDC")

        except Exception as e:
            print(f"[DB ERROR] {e}")

    def _check_virtual_positions(self, market: Dict, current_price: float):
        """检查虚拟持仓的止盈止损"""
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            cursor = conn.cursor()

            # 获取所有开仓持仓
            cursor.execute("""
                SELECT id, entry_time, side, entry_price, size, value_usdc,
                       oracle_score, confidence
                FROM virtual_positions
                WHERE status = 'open'
            """)

            positions = cursor.fetchall()

            if not positions:
                conn.close()
                return

            print(f"\n[CHECK] 检查{len(positions)}个虚拟持仓...")

            for pos in positions:
                pos_id, entry_time, side, entry_price, size, value_usdc, oracle_score, confidence = pos

                # 计算止盈止损价格
                take_profit_pct = CONFIG['risk'].get('take_profit_pct', 0.20)
                stop_loss_pct = CONFIG['risk'].get('max_stop_loss_pct', 0.50)

                if side == 'LONG':
                    pnl_pct = (current_price - entry_price) / entry_price
                    tp_price = entry_price * (1 + take_profit_pct)
                    sl_price = entry_price * (1 - stop_loss_pct)
                else:
                    pnl_pct = (entry_price - current_price) / entry_price
                    tp_price = entry_price * (1 - take_profit_pct)
                    sl_price = entry_price * (1 + stop_loss_pct)

                # 检查是否触发止盈止损
                exit_reason = None
                if side == 'LONG':
                    if current_price >= tp_price:
                        exit_reason = 'TAKE_PROFIT'
                    elif current_price <= sl_price:
                        exit_reason = 'STOP_LOSS'
                else:
                    if current_price <= tp_price:
                        exit_reason = 'TAKE_PROFIT'
                    elif current_price >= sl_price:
                        exit_reason = 'STOP_LOSS'

                if exit_reason:
                    # 平仓
                    pnl_usd = value_usdc * pnl_pct
                    self._close_virtual_position(pos_id, current_price, pnl_usd, pnl_pct, exit_reason, cursor)
                else:
                    # 显示未平仓的浮盈浮亏
                    print(f"  [POSITION #{pos_id}] {side}: {entry_price:.4f}→{current_price:.4f} ({pnl_pct:+.1%})")

            conn.commit()
            conn.close()

        except Exception as e:
            print(f"[CHECK ERROR] {e}")

    def _close_virtual_position(self, pos_id: int, exit_price: float, pnl_usd: float, pnl_pct: float, reason: str, cursor):
        """平仓虚拟持仓"""
        try:
            # 更新持仓状态
            cursor.execute("""
                UPDATE virtual_positions
                SET status = 'closed'
                WHERE id = ?
            """, (pos_id,))

            # 记录到交易历史表
            cursor.execute("""
                INSERT INTO virtual_trades (
                    timestamp, side, entry_price, exit_price, size, value_usdc,
                    pnl_usd, pnl_pct, exit_reason
                )
                SELECT entry_time, side, entry_price, size, value_usdc
                FROM virtual_positions
                WHERE id = ?
            """, (pos_id,))

            # 获取详细信息
            cursor.execute("""
                SELECT side, entry_price, exit_price, pnl_pct, exit_reason
                FROM virtual_trades
                WHERE id = (SELECT MAX(id) FROM virtual_trades)
            """)
            result = cursor.fetchone()

            if result:
                side, entry_price, exit_price, pnl_pct, exit_reason = result
                emoji = "💰" if pnl_usd > 0 else "📉"
                print(f"  [{emoji}] 平仓: {side} {entry_price:.4f}→{exit_price:.4f} | {pnl_pct:+.1%} | {reason}")

        except Exception as e:
            print(f"[CLOSE ERROR] {e}")

    def _print_statistics(self):
        """打印统计信息"""
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            cursor = conn.cursor()

            # 总交易数
            cursor.execute("SELECT COUNT(*) FROM virtual_trades")
            total_trades = cursor.fetchone()[0]

            # 胜率
            cursor.execute("SELECT COUNT(*) FROM virtual_trades WHERE pnl_usd > 0")
            win_trades = cursor.fetchone()[0]
            win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0

            # 总盈亏
            cursor.execute("SELECT SUM(pnl_usd) FROM virtual_trades")
            total_pnl = cursor.fetchone()[0] or 0.0

            # 平均收益
            cursor.execute("SELECT AVG(pnl_pct) FROM virtual_trades")
            avg_return = cursor.fetchone()[0] or 0.0

            print(f"\n[STATISTICS]")
            print(f"  总交易: {total_trades}")
            print(f"  胜率: {win_rate:.1f}%")
            print(f"  总盈亏: ${total_pnl:+.2f} USDC")
            print(f"  平均收益: {avg_return:+.1%}")

            # 最近10笔交易
            cursor.execute("""
                SELECT timestamp, side, entry_price, exit_price, pnl_pct, exit_reason
                FROM virtual_trades
                ORDER BY id DESC
                LIMIT 10
            """)
            recent = cursor.fetchall()

            if recent:
                print(f"\n[最近10笔交易]")
                for trade in recent:
                    timestamp, side, entry_price, exit_price, pnl_pct, exit_reason = trade
                    emoji = "✅" if pnl_pct > 0 else "❌"
                    print(f"  {emoji} {timestamp} {side} {entry_price:.4f}→{exit_price:.4f} ({pnl_pct:+.1%}) {exit_reason}")

            conn.close()

        except Exception as e:
            print(f"[STATS ERROR] {e}")


def main():
    """主函数 - 虚拟交易循环"""
    trader = VirtualTrader()

    print("\n按Ctrl+C停止\n")

    try:
        while True:
            trader.run_virtual_cycle()

            # 等待15分钟（下一个交易窗口）
            print(f"\n[WAIT] 等待下一个15分钟窗口...")
            time.sleep(15 * 60)  # 15分钟 = 900秒

    except KeyboardInterrupt:
        print("\n\n[STOP] 虚拟交易系统已停止")
        trader._print_statistics()


if __name__ == "__main__":
    main()
