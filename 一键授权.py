"""
一键授权脚本
解决 'not enough balance / allowance' 问题
运行一次即可，授权永久有效
"""
import os
from dotenv import load_dotenv

# 设置代理（与主程序一致）
os.environ['HTTP_PROXY'] = 'http://127.0.0.1:15236'
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:15236'

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import AssetType, BalanceAllowanceParams, RequestArgs
from py_clob_client.headers.headers import create_level_2_headers
from py_clob_client.http_helpers.helpers import get

UPDATE_BALANCE_ALLOWANCE = "/balance-allowance/update"

def build_allowance_url(host, asset_type, token_id=None, signature_type=2):
    url = "{}{}?asset_type={}&signature_type={}".format(
        host, UPDATE_BALANCE_ALLOWANCE, asset_type, signature_type
    )
    if token_id:
        url += "&token_id={}".format(token_id)
    return url

def update_allowance_fixed(client, asset_type, token_id=None):
    """授权：用 signer 地址（与 API key 绑定）"""
    request_args = RequestArgs(method="GET", request_path=UPDATE_BALANCE_ALLOWANCE)
    headers = create_level_2_headers(client.signer, client.creds, request_args)
    url = build_allowance_url(client.host, asset_type, token_id)
    print(f"       [DEBUG] POLY_ADDRESS={headers.get('POLY_ADDRESS')}, url={url}")
    return get(url, headers=headers)

load_dotenv()

PRIVATE_KEY = os.getenv('PRIVATE_KEY')
WALLET_ADDRESS = '0xd5d037390c6216CCFa17DFF7148549B9C2399BD3'
CLOB_HOST = 'https://clob.polymarket.com'
CHAIN_ID = 137

print("=" * 50)
print("Polymarket 一键授权")
print("=" * 50)

try:
    # 初始化客户端
    temp_client = ClobClient(
        CLOB_HOST,
        key=PRIVATE_KEY,
        chain_id=CHAIN_ID,
        signature_type=2,
        funder=WALLET_ADDRESS
    )
    api_creds = temp_client.create_or_derive_api_creds()
    print(f"✅ API Creds 派生成功: {api_creds.api_key}")

    client = ClobClient(
        CLOB_HOST,
        key=PRIVATE_KEY,
        chain_id=CHAIN_ID,
        creds=api_creds,
        signature_type=2,
        funder=WALLET_ADDRESS
    )

    # 1. 授权 USDC（抵押品）
    print("\n[1/2] 授权 USDC...")
    try:
        result = update_allowance_fixed(client, AssetType.COLLATERAL)
        print(f"✅ USDC 授权成功: {result}")
    except Exception as e:
        print(f"⚠️  USDC 授权: {e}")

    # 2. 授权 Conditional Token（YES/NO token）
    print("\n[2/2] 授权 Conditional Token...")
    try:
        result = update_allowance_fixed(client, AssetType.CONDITIONAL)
        print(f"✅ Conditional Token 授权成功: {result}")
    except Exception as e:
        print(f"⚠️  Conditional Token 授权: {e}")

    print("\n" + "=" * 50)
    print("授权完成！现在可以正常挂止盈止损单了。")
    print("=" * 50)

except Exception as e:
    print(f"❌ 错误: {e}")
    import traceback
    traceback.print_exc()
