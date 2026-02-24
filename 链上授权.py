"""
链上授权脚本
直接调用 ERC1155 setApprovalForAll，授权 CTF Exchange 合约
运行一次即可，授权永久有效
"""
import os
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

PRIVATE_KEY = os.getenv('PRIVATE_KEY')
# Polymarket 代理钱包地址（funder）
WALLET_ADDRESS = '0xd5d037390c6216CCFa17DFF7148549B9C2399BD3'
# Polygon RPC
RPC_URL = 'https://polygon-rpc.com'
# Polymarket CTF Exchange 合约（需要授权的目标）
CTF_EXCHANGE = '0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E'
# Conditional Token Framework (ERC1155) 合约
CTF_CONTRACT = '0x4D97DCd97eC945f40cF65F87097ACe5EA0476045'

# ERC1155 setApprovalForAll ABI
ABI = [
    {
        "inputs": [
            {"name": "operator", "type": "address"},
            {"name": "approved", "type": "bool"}
        ],
        "name": "setApprovalForAll",
        "outputs": [],
        "type": "function"
    },
    {
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "operator", "type": "address"}
        ],
        "name": "isApprovedForAll",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
        "stateMutability": "view"
    }
]

print("=" * 50)
print("Polymarket 链上授权")
print("=" * 50)

w3 = Web3(Web3.HTTPProvider(RPC_URL))
print(f"连接状态: {'✅ 已连接' if w3.is_connected() else '❌ 未连接'}")

account = w3.eth.account.from_key(PRIVATE_KEY)
signer_address = account.address
print(f"签名地址: {signer_address}")
print(f"Funder地址: {WALLET_ADDRESS}")

contract = w3.eth.contract(address=Web3.to_checksum_address(CTF_CONTRACT), abi=ABI)

# 检查当前授权状态
try:
    is_approved = contract.functions.isApprovedForAll(
        Web3.to_checksum_address(WALLET_ADDRESS),
        Web3.to_checksum_address(CTF_EXCHANGE)
    ).call()
    print(f"\n当前授权状态: {'✅ 已授权' if is_approved else '❌ 未授权'}")
    if is_approved:
        print("已经授权，无需重复操作。")
        exit(0)
except Exception as e:
    print(f"查询授权状态失败: {e}")

# 发送 setApprovalForAll 交易
print("\n发送授权交易...")
try:
    nonce = w3.eth.get_transaction_count(signer_address)
    gas_price = w3.eth.gas_price

    tx = contract.functions.setApprovalForAll(
        Web3.to_checksum_address(CTF_EXCHANGE),
        True
    ).build_transaction({
        'from': signer_address,
        'nonce': nonce,
        'gasPrice': gas_price,
        'gas': 100000,
        'chainId': 137
    })

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"✅ 交易已发送: {tx_hash.hex()}")
    print("等待确认...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    print(f"✅ 授权成功！区块: {receipt['blockNumber']}")
except Exception as e:
    print(f"❌ 授权失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 50)
print("完成！")
print("=" * 50)
