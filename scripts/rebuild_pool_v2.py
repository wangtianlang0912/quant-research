#!/usr/bin/env python3
# 快速重建股票池：用Phase 0动量Top200 + 已缓存的K线
import json, os

# 读取今天动量扫描结果
momentum_path = 'reports/qullamaggie/phase0_momentum_full.json'
with open(momentum_path) as f:
    data = json.load(f)

# 取Top200
pool = [item['code'] for item in data.get('top', [])[:200]]
print(f"动量Top200: {len(pool)} 只")

# 同时合并已有K线缓存中的代码
cache_dir = 'data/cache'
import glob
cached_codes = set()
for f in glob.glob(f'{cache_dir}/klines_*.json'):
    code = os.path.splitext(os.path.basename(f))[0].replace('klines_', '')
    cached_codes.add(code)

print(f"已有K线缓存: {len(cached_codes)} 只")

# 取并集
all_uniq = list(dict.fromkeys(pool + sorted(cached_codes)))[:300]
with open(f'{cache_dir}/hs300_pool.json', 'w') as f:
    json.dump(all_uniq, f)
print(f"最终股票池: {len(all_uniq)} 只")
