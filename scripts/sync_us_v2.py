#!/usr/bin/env python3
"""美股代码扫描 - 腾讯API批量探测 + 东方财富补充"""
import json, os, time, requests

CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'cache')
os.makedirs(CACHE_DIR, exist_ok=True)
DATE = '2026-06-29'

# ── 1. 东方财富全部美股代码 ──
print("[1/3] 东方财富获取美股代码...")
def fetch_em_all(fs, max_pages=50):
    items = []
    for page in range(1, max_pages+1):
        url = (f'https://push2.eastmoney.com/api/qt/clist/get'
               f'?pn={page}&pz=500&po=1&np=1&fltt=2&invt=2&fid=f12'
               f'&fs={fs}&fields=f12,f14,f2,f20')
        for retry in range(3):
            try:
                r = requests.get(url, headers={'User-Agent':'Mozilla/5.0','Referer':'https://quote.eastmoney.com/'}, timeout=20)
                if r.status_code != 200:
                    time.sleep(2); continue
                data = r.json()
                if data and data.get('data') and data['data'].get('diff'):
                    items.extend(data['data']['diff'])
                break
            except:
                time.sleep(2)
        if page % 10 == 0 and items:
            print(f"  已获取 {len(items)} 只...")
        time.sleep(0.3)
    return items

em_items = fetch_em_all('m:105+m:106+m:107')
print(f"  东方财富提供 {len(em_items)} 只")

# ── 2. 腾讯API批量探测（大小写不敏感） ──
print("\n[2/3] 腾讯API批量探测...")
BATCH = 800
results = {}  # code_upper -> {name, price, ...}

# 东方财富代码 → 市值映射
em_mc = {}
for it in em_items:
    ticker = it.get('f12', '').upper()
    mc = 0
    try: mc = float(it.get('f20', 0) or 0)
    except: pass
    if mc > 0:
        em_mc[ticker] = mc

em_tickers = list(em_mc.keys())
print(f"  有市值数据的: {len(em_tickers)} 只")

ETF_ETN_KW = [
    'ETF', 'ETN', 'ETRACS', 'PROSHARES', 'DIREXION', 'MICROSECTORS',
    'VELOCITYSHARES', 'LEVERAGED', 'LEVER', 'INVERSE', '2X', '3X', '4X',
    'ULTRA ', 'ULTRA PRO', 'BEAR', 'BULL', 'PREFERRED', 'WARRANT',
    'VANGUARD ', 'ISHARES ', 'SPDR ', 'INVESCO ', 'TOTAL MARKET',
    'S&P 500', 'MSCI', 'FTSE ', '-2X', '-3X', ' BULL ', ' BEAR ',
]

for i in range(0, len(em_tickers), BATCH):
    batch = em_tickers[i:i+BATCH]
    # 用大小写都试试——腾讯API实际不限大小写
    tencodes = [f'us{t}' for t in batch]
    try:
        url = 'http://qt.gtimg.cn/q=' + ','.join(tencodes)
        r = requests.get(url, timeout=30)
        text = r.content.decode('gbk', errors='replace')
        for line in text.strip().split('\n'):
            if not line.startswith('v_us'):
                continue
            try:
                data = line.split('="', 1)[1].rstrip('";')
                parts = data.split('~')
                if len(parts) < 10: continue
                code_raw = parts[2].lower()
                if '.' in code_raw:
                    code_raw = code_raw.split('.')[0]
                code = code_raw.upper()
                name = parts[1]
                price_str = parts[3]
                if not price_str: continue
                price = float(price_str)
                
                # ETF/ETN过滤
                name_upper = name.upper()
                skip = False
                for kw in ETF_ETN_KW:
                    if kw in name_upper:
                        skip = True; break
                if skip: continue
                
                results[code] = {
                    'code': f'us{code}',
                    'name': name,
                    'price': price,
                    'market_cap': em_mc.get(code, 0),
                }
            except: pass
    except Exception as e:
        print(f"  批次 {i//BATCH+1} 失败: {e}")
        continue
    if (i // BATCH + 1) % 5 == 0:
        print(f"  已探测 {min(i+BATCH, len(em_tickers))}/{len(em_tickers)}, 有效 {len(results)}")
    time.sleep(0.3)

print(f"  腾讯API有效: {len(results)} 只有效交易")

# ── 3. 合并保存 ──
print("\n[3/3] 合并保存...")
final = [info for info in results.values() if info['price'] > 0]
final.sort(key=lambda x: x.get('market_cap', 0), reverse=True)

with open(os.path.join(CACHE_DIR, 'us_codes.json'), 'w') as f:
    json.dump({'date': DATE, 'codes': final}, f, ensure_ascii=False)

print(f"\n{'='*50}")
print(f"✅ 美股同步完成! 共 {len(final)} 只")

# 验证主流科技股
targets = ['usAAPL','usMSFT','usGOOGL','usNVDA','usTSLA','usAMZN',
           'usMETA','usNFLX','usBABA','usAMD','usINTC','usCRM',
           'usADBE','usORCL','usQCOM','usAVGO','usPLTR','usSHOP',
           'usUBER','usCOIN','usSNOW','usSNPS','usPYPL','usSQ',
           'usRIVN','usLCID','usNIO']
code_map = {r['code']: r for r in final}
found = 0
missing = []
for t in targets:
    if t in code_map:
        found += 1
    else:
        missing.append(t)
print(f"  美科技股覆盖率: {found}/{len(targets)}")
if missing:
    print(f"  缺失: {missing[:5]}{'...' if len(missing)>5 else ''}")
