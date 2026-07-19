#!/usr/bin/env python3
"""A股缓存补名称 — 新浪API批量查询"""
import json, os, time, requests

CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'cache')
HEADERS = {'Referer': 'https://finance.sina.com.cn/'}

a = json.load(open(os.path.join(CACHE_DIR, 'a_codes.json')))
codes = a['codes']

# 50只/批
BATCH = 50
name_map = {}
errors = 0

for i in range(0, len(codes), BATCH):
    batch = codes[i:i+BATCH]
    url = 'http://hq.sinajs.cn/list=' + ','.join(batch)
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        text = r.content.decode('gbk', errors='replace')
        for line in text.strip().split('\n'):
            if not line.startswith('var hq_str_'): continue
            try:
                name_part = line.split('=', 1)[0].replace('var hq_str_', '')
                data = line.split('="', 1)[1].rstrip('";')
                fields = data.split(',')
                name = fields[0].replace(' ', '')
                price = float(fields[3]) if len(fields) > 3 and fields[3] else 0
                name_map[name_part] = {'code': name_part, 'name': name, 'price': price}
            except: pass
    except Exception as e:
        errors += 1
    if (i // BATCH + 1) % 20 == 0:
        print(f'  {i+len(batch)}/{len(codes)}, 获名{len(name_map)}')
    time.sleep(0.3)

# 组装
enriched = []
for c in codes:
    m = name_map.get(c, {'code': c, 'name': c, 'price': 0})
    enriched.append(m)

with open(os.path.join(CACHE_DIR, 'a_codes.json'), 'w') as f:
    json.dump({'date': a['date'], 'codes': enriched}, f, ensure_ascii=False)
print(f'\n✅ A股缓存已补名称: {len(enriched)}只, 命中{len(name_map)}只, 错误{errors}批')
