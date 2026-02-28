#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import sys
from datetime import datetime

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\Users\Martin\Downloads\Polymarket-History-2026-02-28.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    trades = list(reader)

print('='*80)
print('Polymarket Actual Trading Analysis (1000 trades)')
print('='*80)

total_buy = sum(1 for t in trades if t['action'] == 'Buy')
total_sell = sum(1 for t in trades if t['action'] == 'Sell')
total_usdc_buy = sum(float(t['usdcAmount']) for t in trades if t['action'] == 'Buy')
total_usdc_sell = sum(float(t['usdcAmount']) for t in trades if t['action'] == 'Sell')

print(f'Total Buy: {total_buy} trades')
print(f'Total Sell: {total_sell} trades')
print(f'Buy Amount: ${total_usdc_buy:.2f}')
print(f'Sell Amount: ${total_usdc_sell:.2f}')
print(f'Net Invested: ${total_usdc_buy - total_usdc_sell:.2f}')

up_trades = [t for t in trades if t['tokenName'] == 'Up']
down_trades = [t for t in trades if t['tokenName'] == 'Down']

print(f'\nLONG (Up): {len(up_trades)} trades')
print(f'SHORT (Down): {len(down_trades)} trades')

first_trade = trades[-1]
last_trade = trades[0]

first_time = datetime.fromtimestamp(int(first_trade['timestamp']))
last_time = datetime.fromtimestamp(int(last_trade['timestamp']))

print(f'\nTime Range:')
print(f'  First: {first_time.strftime(\"%Y-%m-%d %H:%M\")}')
print(f'  Last: {last_time.strftime(\"%Y-%m-%d %H:%M\")}')

print(f'\nRecent 10 trades:')
for i, trade in enumerate(trades[:10], 1):
    action = trade['action']
    usdc = float(trade['usdcAmount'])
    tokens = float(trade['tokenAmount'])
    direction = trade['tokenName']
    time_str = datetime.fromtimestamp(int(trade['timestamp'])).strftime('%H:%M:%S')
    print(f'{i:2d}. [{time_str}] {action:4s} ${usdc:6.2f} -> {tokens:.2f} {direction}')
