#!/usr/bin/env python3
# 从全量A股池选成交额Top200替代HS300
import json, os, time, sys
sys.path.insert(0, '/Users/leihen/.qclaw/workspace/quant-research')
from src.data.akshare_client import TencentClient

client = TencentClient()

# 加载全量A股
a_path = 'data/cache/a_codes.json'
with open(a_path) as f:
    a_data = json.load(f)
a_codes = a_data['codes']
print(f"全量A股: {len(a_codes)} 只")

# 采样测今日成交额
amounts = []
for i, code in enumerate(a_codes[:2000]):  # 只测前2000只
    try:
        result = client.get_quote(code)
        if result and result['amount'] and result['amount'] > 0:
            amounts.append((code, result['name'], result['amount'], result['price']))
    except:
        pass
    if (i+1) % 500 == 0:
        print(f'  进度 {i+1}/2000, 有效 {len(amounts)}')
    time.sleep(0.06)

amounts.sort(key=lambda x: x[2], reverse=True)
print(f"\n有效: {len(amounts)} 只")

# 取Top200+去ST
top200 = []
for code, name, amt, price in amounts:
    if 'ST' in name or '退市' in name:
        continue
    if price > 5:
        top200.append([code, name])
    if len(top200) >= 200:
        break

print(f"Top200 (成交额最高): {len(top200)} 只")
with open('data/cache/hs300_pool.json', 'w') as f:
    json.dump(top200, f, ensure_ascii=False)

for i, (c, n) in enumerate(top200[:10]):
    print(f'  {i+1}. {c} {n}')
print(f'  ...')
