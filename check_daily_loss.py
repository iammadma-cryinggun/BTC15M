#!/usr/bin/env python3
"""检查并修复daily_loss问题"""

# 显示当前的配置
balance = 10.0  # 你需要确认实际余额
max_loss_pct = 0.50
max_loss = balance * max_loss_pct

print("=" * 60)
print("每日亏损限制配置")
print("=" * 60)
print(f"余额: ${balance:.2f}")
print(f"最大每日亏损比例: {max_loss_pct*100}%")
print(f"最大每日亏损金额: ${max_loss:.2f}")
print()

print("问题分析:")
print("- daily_loss 初始值: 0.0")
print("- daily_loss 应该永远保持 0.0 (因为没有代码更新它)")
print("- 如果触发了 'Daily loss limit reached'，可能是bug")
print()

print("解决方案:")
print("1. 重启程序（会重置stats）")
print("2. 或者修复代码：移除daily_loss检查或正确实现它")
print()

# 建议的代码修复
print("建议的代码修复:")
print("-" * 60)
print("""
# 方案1：完全移除daily_loss检查（推荐）
# 在 can_trade 函数中注释掉这段代码：

# max_loss = self.position_mgr.get_max_daily_loss()
# if self.stats['daily_loss'] >= max_loss:
#     ...
#     return False, f"Daily loss limit reached"

# 方案2：正确实现daily_loss统计
# 在记录平仓结果时添加：
if pnl_usd < 0:
    self.stats['daily_loss'] += abs(pnl_usd)
""")
print("=" * 60)
