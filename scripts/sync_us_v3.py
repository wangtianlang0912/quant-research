#!/usr/bin/env python3
"""美股代码同步 v3 - 全量探测，不看市值"""
import json, os, time, requests

CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'cache')
os.makedirs(CACHE_DIR, exist_ok=True)
DATE = '2026-06-29'

print("[1/2] 东方财富全量 + 腾讯API逐批验证...")

# 东方财富全量
em_items = []
for page in range(1, 50):
    url = (f'https://push2.eastmoney.com/api/qt/clist/get'
           f'?pn={page}&pz=500&po=1&np=1&fltt=2&invt=2&fid=f12'
           f'&fs=m:105+m:106+m:107&fields=f12,f14,f2,f20')
    for retry in range(3):
        try:
            r = requests.get(url, headers={'User-Agent':'Mozilla/5.0','Referer':'https://quote.eastmoney.com/'}, timeout=20)
            if r.status_code != 200:
                time.sleep(2); continue
            data = r.json()
            if data and data.get('data') and data['data'].get('diff'):
                em_items.extend(data['data']['diff'])
            break
        except:
            time.sleep(2)
    if page % 10 == 0:
        print(f"  EM已拉取 {len(em_items)} 只...")
    time.sleep(0.3)

# 去重+取ticker
seen = set(); tickers = []
for it in em_items:
    t = it.get('f12', '').upper()
    if t and t not in seen:
        seen.add(t)
        tickers.append(t)

print(f"  EM去重后: {len(tickers)} 只")

# ETF/ETN关键词
SKIP_KW = ['ETF', 'ETN', 'ETRACS', 'PROSHARES', 'DIREXION', 'MICROSECTORS',
           'VELOCITYSHARES', 'LEVERAGED', 'LEVER', 'INVERSE', '2X', '3X', '4X',
           'ULTRA ', 'ULTRA PRO', 'BEAR', 'BULL', 'PREFERRED', 'WARRANT',
           'VANGUARD ', 'ISHARES ', 'SPDR ', 'INVESCO ', 'TOTAL MARKET',
           'S&P 500', 'MSCI', 'FTSE ', '--2X', '--3X']

# 腾讯API批量探测（全量，不预过滤）
BATCH = 800
results = []
for i in range(0, len(tickers), BATCH):
    batch = tickers[i:i+BATCH]
    tencodes = [f'us{t}' for t in batch]
    try:
        url = 'http://qt.gtimg.cn/q=' + ','.join(tencodes)
        r = requests.get(url, timeout=60)
        text = r.content.decode('gbk', errors='replace')
        for line in text.strip().split('\n'):
            if not line.startswith('v_us'):
                continue
            try:
                data = line.split('="', 1)[1].rstrip('";')
                parts = data.split('~')
                if len(parts) < 10:
                    continue
                code_raw = parts[2].lower()
                if '.' in code_raw:
                    code_raw = code_raw.split('.')[0]
                code = code_raw.upper()
                name = parts[1]
                price = float(parts[3]) if parts[3] else 0
                if price <= 0:
                    continue
                # 过滤ETF/ETN
                name_up = name.upper()
                if any(kw in name_up for kw in SKIP_KW):
                    continue
                # 排除含权证/收购壳等
                if any(c in code for c in ['_', '-W', '-R']):
                    continue
                results.append({
                    'code': f'us{code}',
                    'name': name,
                    'price': price,
                    'market_cap': 0,
                })
            except:
                pass
    except Exception as e:
        print(f"  批次 {i//BATCH+1} 失败: {e}")
    if (i // BATCH + 1) % 5 == 0:
        print(f"  已探测 {min(i+BATCH, len(tickers))}/{len(tickers)}, 有效 {len(results)}")
    time.sleep(0.5)

# 按价格(粗略排序)
results.sort(key=lambda x: x['price'], reverse=True)

with open(os.path.join(CACHE_DIR, 'us_codes.json'), 'w') as f:
    json.dump({'date': DATE, 'codes': results}, f, ensure_ascii=False)
ko = os.path.getsize(os.path.join(CACHE_DIR, 'us_codes.json')) / 1024
print(f"\n✅ 美股同步: {len(results)} 只 ({ko:.1f}KB)")

# 验证
targets = ['usAAPL','usMSFT','usGOOGL','usNVDA','usTSLA','usAMZN',
           'usMETA','usNFLX','usBABA','usAMD','usINTC','usCRM',
           'usADBE','usORCL','usQCOM','usAVGO','usPLTR','usSHOP',
           'usUBER','usCOIN']
code_map = {r['code']: r for r in results}
found, missing = 0, []
for t in targets:
    if t in code_map:
        found += 1
    else:
        missing.append(t)
print(f"主流科技股: {found}/{len(targets)}")
if missing:
    print(f"缺失: {missing}")
if found >= 15:
    print("✅ 覆盖率达标")
