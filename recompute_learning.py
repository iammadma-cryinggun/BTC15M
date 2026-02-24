#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重新计算历史预测学习结果
- 从 Polymarket Gamma API 获取每个市场的结算价（YES token 价格）
- 用正确的 token 价格重新计算 correct 字段
- 更新数据库
"""

import sqlite3
import json
import time
import requests
from datetime import datetime

DB_PATH = 'btc_15min_predictionsv2.db'
PROXIES = {'http': 'http://127.0.0.1:15236', 'https': 'http://127.0.0.1:15236'}
GAMMA_API = 'https://gamma-api.polymarket.com/markets'


def get_market_resolution(slug: str) -> float | None:
    """
    获取市场 YES token 价格（已结算返回0或1，未结算返回当前价）
    优先用 resolutionPrice，其次用 outcomePrices[0]
    """
    try:
        resp = requests.get(
            GAMMA_API,
            params={'slug': slug},
            proxies=PROXIES,
            timeout=10
        )
        if resp.status_code != 200:
            return None
        markets = resp.json()
        if not markets:
            return None
        market = markets[0]

        # 已结算市场优先用 resolutionPrice
        resolution = market.get('resolutionPrice')
        if resolution is not None:
            return float(resolution)

        # 未结算用当前 outcomePrices[0]
        outcome_prices = market.get('outcomePrices', '[]')
        if isinstance(outcome_prices, str):
            outcome_prices = json.loads(outcome_prices)
        if outcome_prices:
            return float(outcome_prices[0])

        return None
    except Exception as e:
        print(f"  [ERROR] {slug}: {e}")
        return None


def recompute():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 获取所有已验证的记录
    cursor.execute('''
        SELECT id, timestamp, price, direction, market_slug, actual_price, correct
        FROM predictions
        WHERE verified = 1
        ORDER BY id
    ''')
    records = cursor.fetchall()
    print(f"共找到 {len(records)} 条已验证记录，开始重新计算...\n")

    slug_cache = {}
    updated = 0
    skipped = 0
    changed = 0

    for rec in records:
        rec_id, timestamp, pred_price, direction, market_slug, old_actual_price, old_correct = rec

        if not market_slug:
            skipped += 1
            continue

        # 从缓存或 API 获取结算价
        if market_slug not in slug_cache:
            token_price = get_market_resolution(market_slug)
            slug_cache[market_slug] = token_price
            time.sleep(0.2)  # 避免请求过快
        else:
            token_price = slug_cache[market_slug]

        if token_price is None:
            print(f"  [SKIP] ID={rec_id} slug={market_slug} 无法获取价格")
            skipped += 1
            continue

        # 重新计算 correct
        if direction == 'LONG':
            new_correct = 1 if token_price > pred_price else 0
        else:  # SHORT
            new_correct = 1 if token_price < pred_price else 0

        # 计算新的 change_pct
        new_change_pct = ((token_price - pred_price) / pred_price) * 100 if pred_price > 0 else 0

        # 更新数据库
        cursor.execute('''
            UPDATE predictions
            SET actual_price = ?,
                actual_change_pct = ?,
                correct = ?
            WHERE id = ?
        ''', (token_price, new_change_pct, new_correct, rec_id))

        if new_correct != old_correct:
            changed += 1
            print(f"  [CHANGED] ID={rec_id} {direction} pred={pred_price:.4f} actual={token_price:.4f} "
                  f"old_correct={old_correct} → new_correct={new_correct}")

        updated += 1

    conn.commit()
    conn.close()

    print(f"\n{'='*60}")
    print(f"完成！共处理 {updated} 条，跳过 {skipped} 条")
    print(f"修正了 {changed} 条错误记录")
    print(f"{'='*60}")

    # 打印新的准确率统计
    print_new_stats()


def print_new_stats():
    """打印重新计算后的准确率"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT direction, correct, score, confidence
        FROM predictions
        WHERE verified = 1
    ''')
    results = cursor.fetchall()
    conn.close()

    if not results:
        print("无数据")
        return

    total = len(results)
    correct = sum(1 for r in results if r[1] == 1)
    long_total = sum(1 for r in results if r[0] == 'LONG')
    long_correct = sum(1 for r in results if r[0] == 'LONG' and r[1] == 1)
    short_total = sum(1 for r in results if r[0] == 'SHORT')
    short_correct = sum(1 for r in results if r[0] == 'SHORT' and r[1] == 1)

    print(f"\n【重新计算后准确率】")
    print(f"  总体: {correct}/{total} = {correct/total*100:.1f}%")
    if long_total > 0:
        print(f"  做多: {long_correct}/{long_total} = {long_correct/long_total*100:.1f}%")
    if short_total > 0:
        print(f"  做空: {short_correct}/{short_total} = {short_correct/short_total*100:.1f}%")


if __name__ == '__main__':
    recompute()
