#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
防御层 (Defense Layer) - Layer 3 of Three-Layer Architecture

热心哥的五因子防御系统：
1. CVD同不同意？（CVD一票否决权）
2. 距离基准价格多少？
3. session剩余时间？
4. 预言机穿越次数？（>5次混乱市场）
5. 入场价利润空间？（高价位高要求）

返回：0-1的仓位乘数
"""

import time
from typing import Dict, Tuple, List
from datetime import datetime, timezone


class DefenseLayer:
    """防御层：五因子风控系统"""

    def __init__(self):
        self.cross_count_history = {}  # 记录每个市场的穿越次数
        self.last_cross_check = {}     # 上次检查时间
        
    def calculate_defense_multiplier(
        self, 
        signal: Dict, 
        oracle: Dict, 
        market: Dict, 
        current_price: float
    ) -> Tuple[float, List[str]]:
        """
        计算防御层乘数（0-1）
        
        Args:
            signal: 信号字典 {'direction': 'LONG'/'SHORT', 'confidence': 0.0-1.0}
            oracle: Oracle数据 {'cvd_5m': float, 'cvd_1m': float, ...}
            market: 市场数据 {'endTimestamp': int, 'slug': str, ...}
            current_price: 当前入场价格
            
        Returns:
            (multiplier, reasons): 乘数和原因列表
        """
        multiplier = 1.0
        reasons = []
        
        # ==========================================
        # 因子1：CVD同不同意？（最重要，权重最高）
        # ==========================================
        cvd_5m = oracle.get('cvd_5m', 0) if oracle else 0
        cvd_1m = oracle.get('cvd_1m', 0) if oracle else 0
        
        # CVD强烈反对信号方向
        if signal['direction'] == 'LONG':
            if cvd_5m < -100000:  # 5分钟CVD强烈看空
                multiplier *= 0.3
                reasons.append(f"CVD-5m反对({cvd_5m/1000:.0f}k)")
            elif cvd_1m < -50000:  # 1分钟CVD看空
                multiplier *= 0.6
                reasons.append(f"CVD-1m反对({cvd_1m/1000:.0f}k)")
        else:  # SHORT
            if cvd_5m > 100000:  # 5分钟CVD强烈看多
                multiplier *= 0.3
                reasons.append(f"CVD-5m反对({cvd_5m/1000:.0f}k)")
            elif cvd_1m > 50000:  # 1分钟CVD看多
                multiplier *= 0.6
                reasons.append(f"CVD-1m反对({cvd_1m/1000:.0f}k)")
        
        # ==========================================
        # 因子2：距离基准价格多少？
        # ==========================================
        base_price = 0.50  # BTC 15分钟市场的基准价格
        distance = abs(current_price - base_price)
        
        if distance < 0.05:  # 距离基准价格<5%
            multiplier *= 0.5
            reasons.append(f"接近基准({distance:.2f})")
        elif distance < 0.10:  # 距离基准价格<10%
            multiplier *= 0.7
            reasons.append(f"靠近基准({distance:.2f})")
        
        # ==========================================
        # 因子3：session剩余时间？
        # ==========================================
        # 🔧 修复：使用绝对时间戳，避免本地时钟偏差
        end_ts = market.get('endTimestamp', 0) if market else 0
        if not end_ts:
            # 如果没有 endTimestamp，尝试从 endDate 解析
            end_date = market.get('endDate') if market else None
            if end_date:
                try:
                    from datetime import datetime as dt
                    end_dt = dt.strptime(end_date, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                    end_ts = int(end_dt.timestamp() * 1000)
                except:
                    pass
        
        if end_ts:
            now_ts = int(time.time() * 1000)
            minutes_left = (end_ts - now_ts) / 60000.0  # 转换为分钟
            
            # 大神金句："发现在会议剩下6分钟的时候指标才开始可靠...末日最后两三分钟任何突发都来不及反应"
            if minutes_left <= 3.0:
                multiplier = 0
                reasons.append(f"末日期({minutes_left:.1f}分钟)")
                print(f"       🛡️ [防御-时间] 拦截: 仅剩 {minutes_left:.1f} 分钟，进入末日抛硬币轮，风险陡增，一票否决！")
                return multiplier, reasons  # 直接返回，不再评估其他因子
            elif minutes_left > 9.0:
                # 前置期：剩余时间 > 9分钟（即前6分钟）
                multiplier *= 0.5
                reasons.append(f"前置期({minutes_left:.1f}分钟)")
                print(f"       🛡️ [防御-时间] 警告: 剩余 {minutes_left:.1f} 分钟，处于前置骗炮期，仓位前瞻性减半。")
        else:
            # 如果无法获取 endTimestamp，拒绝交易（安全第一）
            multiplier = 0
            reasons.append("无法获取市场结束时间")
            print(f"       🛡️ [防御-时间] 拦截: 无法获取市场结束时间，拒绝交易！")
            return multiplier, reasons
        
        # ==========================================
        # 因子4：预言机穿越次数？（CVD一票否决权）
        # ==========================================
        market_slug = market.get('slug', '') if market else ''
        cross_count = self._get_cross_count(market_slug, current_price, base_price)
        
        if cross_count > 5:
            # 混乱市场，CVD一票否决
            multiplier = 0
            reasons.append(f"混乱市场({cross_count}次穿越)")
            return multiplier, reasons  # 直接返回，不再评估其他因子
        elif cross_count > 3:
            multiplier *= 0.5
            reasons.append(f"市场波动({cross_count}次穿越)")
        
        # ==========================================
        # 因子5：入场价利润空间？
        # ==========================================
        if current_price > 0.85:
            # 极高价区（>0.85），利润空间极小
            multiplier *= 0.2
            reasons.append(f"极高价区({current_price:.2f})")
        elif current_price > 0.75:
            # 高价区（0.75-0.85），利润空间有限
            multiplier *= 0.3
            reasons.append(f"高价区({current_price:.2f})")
        elif current_price > 0.65:
            # 中高价区（0.65-0.75），利润空间一般
            multiplier *= 0.6
            reasons.append(f"中高价区({current_price:.2f})")
        elif current_price < 0.15:
            # 极低价区（<0.15），风险极高
            multiplier *= 0.2
            reasons.append(f"极低价区({current_price:.2f})")
        elif current_price < 0.25:
            # 低价区（0.15-0.25），风险较高
            multiplier *= 0.3
            reasons.append(f"低价区({current_price:.2f})")
        elif current_price < 0.35:
            # 中低价区（0.25-0.35），风险一般
            multiplier *= 0.6
            reasons.append(f"中低价区({current_price:.2f})")
        
        # 如果没有任何调整，说明是最佳入场区间（0.35-0.65）
        if not reasons:
            reasons.append(f"最佳区间({current_price:.2f})")
        
        return multiplier, reasons
    
    def _get_cross_count(self, market_slug: str, current_price: float, base_price: float) -> int:
        """
        计算预言机价格穿越基准价格的次数
        
        穿越定义：价格从基准价格一侧移动到另一侧
        """
        if not market_slug:
            return 0
        
        now = time.time()
        
        # 初始化市场记录
        if market_slug not in self.cross_count_history:
            self.cross_count_history[market_slug] = {
                'count': 0,
                'last_side': 'above' if current_price > base_price else 'below',
                'last_price': current_price
            }
            self.last_cross_check[market_slug] = now
            return 0
        
        # 获取历史记录
        history = self.cross_count_history[market_slug]
        last_side = history['last_side']
        current_side = 'above' if current_price > base_price else 'below'
        
        # 检测穿越
        if last_side != current_side:
            history['count'] += 1
            history['last_side'] = current_side
            print(f"       [CROSS] 检测到穿越: {last_side} → {current_side} (第{history['count']}次)")
        
        history['last_price'] = current_price
        self.last_cross_check[market_slug] = now
        
        return history['count']
    
    def reset_market(self, market_slug: str):
        """重置市场的穿越计数（切换市场时调用）"""
        if market_slug in self.cross_count_history:
            del self.cross_count_history[market_slug]
        if market_slug in self.last_cross_check:
            del self.last_cross_check[market_slug]
    
    def print_defense_report(self, multiplier: float, reasons: List[str]):
        """打印防御层评估报告"""
        if multiplier == 0:
            status = "🔴 拒绝"
        elif multiplier < 0.3:
            status = "🟠 极度压缩"
        elif multiplier < 0.5:
            status = "🟡 大幅压缩"
        elif multiplier < 0.7:
            status = "🟢 适度压缩"
        else:
            status = "✅ 正常"
        
        print(f"\n       [防御层] {status} | 最终乘数: {multiplier:.2f}")
        print(f"       [防御层] 原因: {', '.join(reasons)}")


# 测试代码
if __name__ == "__main__":
    defense = DefenseLayer()
    
    # 测试场景1：正常信号，最佳入场区间
    print("=" * 70)
    print("测试场景1：正常信号，最佳入场区间")
    print("=" * 70)
    signal = {'direction': 'LONG', 'confidence': 0.75}
    oracle = {'cvd_5m': 80000, 'cvd_1m': 30000}
    market = {'endTimestamp': int(time.time() * 1000) + 600000, 'slug': 'btc-test-1'}  # 10分钟后到期
    current_price = 0.45
    
    multiplier, reasons = defense.calculate_defense_multiplier(signal, oracle, market, current_price)
    defense.print_defense_report(multiplier, reasons)
    
    # 测试场景2：CVD强烈反对
    print("\n" + "=" * 70)
    print("测试场景2：CVD强烈反对")
    print("=" * 70)
    signal = {'direction': 'LONG', 'confidence': 0.75}
    oracle = {'cvd_5m': -150000, 'cvd_1m': -60000}  # CVD强烈看空
    market = {'endTimestamp': int(time.time() * 1000) + 600000, 'slug': 'btc-test-2'}
    current_price = 0.45
    
    multiplier, reasons = defense.calculate_defense_multiplier(signal, oracle, market, current_price)
    defense.print_defense_report(multiplier, reasons)
    
    # 测试场景3：混乱市场（>5次穿越）
    print("\n" + "=" * 70)
    print("测试场景3：混乱市场（模拟6次穿越）")
    print("=" * 70)
    signal = {'direction': 'LONG', 'confidence': 0.75}
    oracle = {'cvd_5m': 80000, 'cvd_1m': 30000}
    market = {'endTimestamp': int(time.time() * 1000) + 600000, 'slug': 'btc-test-3'}
    
    # 模拟6次穿越
    prices = [0.52, 0.48, 0.53, 0.47, 0.54, 0.46, 0.55]
    for i, price in enumerate(prices):
        print(f"\n价格更新 #{i+1}: {price:.2f}")
        multiplier, reasons = defense.calculate_defense_multiplier(signal, oracle, market, price)
        if i == len(prices) - 1:  # 最后一次打印完整报告
            defense.print_defense_report(multiplier, reasons)
    
    # 测试场景4：高价区 + 剩余时间少
    print("\n" + "=" * 70)
    print("测试场景4：高价区 + 剩余时间少")
    print("=" * 70)
    signal = {'direction': 'LONG', 'confidence': 0.75}
    oracle = {'cvd_5m': 80000, 'cvd_1m': 30000}
    market = {'endTimestamp': int(time.time() * 1000) + 150000, 'slug': 'btc-test-4'}  # 2.5分钟后到期
    current_price = 0.80
    
    multiplier, reasons = defense.calculate_defense_multiplier(signal, oracle, market, current_price)
    defense.print_defense_report(multiplier, reasons)
