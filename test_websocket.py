#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket连接测试脚本
测试Polymarket WebSocket API是否可访问
"""

import asyncio
import websockets
import json
import time
from datetime import datetime


async def test_polymarket_websocket():
    """测试Polymarket WebSocket连接"""
    print("=" * 60)
    print("Polymarket WebSocket 连接测试")
    print("=" * 60)

    # 1. 先通过REST API获取当前市场的token ID
    print("\n[步骤1] 获取市场信息...")
    import requests

    now = int(time.time())
    aligned = (now // 900) * 900
    slug = f"btc-will-go-up-or-down-in-the-next-15m-starting-{aligned}"

    try:
        response = requests.get(
            "https://gamma-api.polymarket.com/markets",
            params={'slug': slug},
            timeout=10
        )

        if response.status_code != 200:
            print(f"❌ REST API请求失败: {response.status_code}")
            return

        markets = response.json()
        if not markets or len(markets) == 0:
            print(f"❌ 市场未找到: {slug}")
            print(f"   可能原因：市场未开放或已结算")
            return

        market = markets[0]
        token_ids = market.get('clobTokenIds', [])
        if isinstance(token_ids, str):
            token_ids = json.loads(token_ids)

        if len(token_ids) < 2:
            print("❌ Token ID不完整")
            return

        token_yes_id = token_ids[0]
        token_no_id = token_ids[1]

        print(f"✅ 市场信息获取成功")
        print(f"   Slug: {slug}")
        print(f"   YES Token: {token_yes_id}")
        print(f"   NO Token: {token_no_id}")

    except Exception as e:
        print(f"❌ 获取市场信息失败: {e}")
        return

    # 2. 测试WebSocket连接
    print("\n[步骤2] 测试WebSocket连接...")
    wss_uri = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    try:
        async with websockets.connect(wss_uri, close_timeout=10) as ws:
            print(f"✅ WebSocket连接成功！")

            # 订阅订单簿
            sub_msg = {
                "type": "market",
                "assets_ids": [token_yes_id, token_no_id]
            }
            await ws.send(json.dumps(sub_msg))
            print(f"✅ 订阅请求已发送")

            # 接收10条消息
            print(f"\n[步骤3] 接收实时数据（10秒）...")
            print("-" * 60)

            message_count = 0
            start_time = time.time()

            while time.time() - start_time < 10:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    data = json.loads(msg)
                    message_count += 1

                    # 解析价格
                    if "bids" in data and "asks" in data:
                        bids = data.get("bids", [])
                        asks = data.get("asks", [])

                        if len(bids) > 0 and len(asks) > 0:
                            # ✅ 修复: Polymarket格式是字典 {"price": "0.54", "size": "100"}
                            best_bid = float(bids[0]['price'])
                            best_ask = float(asks[0]['price'])
                            mid_price = (best_bid + best_ask) / 2

                            asset_id = data.get("asset_id", "")
                            token_type = "YES" if asset_id == token_yes_id else "NO"

                            print(f"[{message_count:2d}] {token_type} | 买一:{best_bid:.4f} | 卖一:{best_ask:.4f} | 中间:{mid_price:.4f}")

                except asyncio.TimeoutError:
                    print("   等待数据...")
                    continue

            print("-" * 60)
            print(f"\n✅ 测试完成！共接收 {message_count} 条消息")
            print(f"✅ WebSocket连接正常，可以使用V6引擎")

    except websockets.exceptions.ConnectionClosed as e:
        print(f"❌ WebSocket连接被关闭: {e}")
    except Exception as e:
        print(f"❌ WebSocket连接失败: {e}")
        print(f"\n可能原因：")
        print(f"  1. Zeabur/本地网络无法访问WebSocket端口")
        print(f"  2. 需要配置代理")
        print(f"  3. Polymarket WebSocket API变更")


if __name__ == "__main__":
    print("\n开始测试...")
    print("时间:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print()

    try:
        asyncio.run(test_polymarket_websocket())
    except KeyboardInterrupt:
        print("\n\n测试被用户中断")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
