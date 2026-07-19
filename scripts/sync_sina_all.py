#!/usr/bin/env python3
"""
美股+港股代码同步 — 新浪财经API
策略：东方财富获取全量代码 → 新浪API逐批验证（价格/名称/过滤）
"""
import json, os, time, requests

CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'cache')
os.makedirs(CACHE_DIR, exist_ok=True)
DATE = '2026-06-29'

HEADERS = {'Referer': 'https://finance.sina.com.cn/'}

# ═══════ 东方财富全量代码 ═══════
def fetch_em_tickers(fs, max_pages=50):
    items = []
    for page in range(1, max_pages+1):
        url = (f'https://push2.eastmoney.com/api/qt/clist/get'
               f'?pn={page}&pz=500&po=1&np=1&fltt=2&invt=2&fid=f12'
               f'&fs={fs}&fields=f12,f14')
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
            print(f"    EM: {len(items)} 只...")
        time.sleep(0.3)
    # 去重
    seen = set(); tickers = []
    for it in items:
        t = it.get('f12', '').upper()
        if t and t not in seen:
            seen.add(t)
            tickers.append(t)
    return tickers

# ═══════ 新浪批量查询 ═══════
def sina_batch_query(codes_sina_fmt, batch=800):
    """codes_sina_fmt: ['gb_aapl','hk00700',...]"""
    results = []
    for i in range(0, len(codes_sina_fmt), batch):
        sub = codes_sina_fmt[i:i+batch]
        try:
            url = 'http://hq.sinajs.cn/list=' + ','.join(sub)
            r = requests.get(url, headers=HEADERS, timeout=60)
            text = r.content.decode('gbk', errors='replace')
            for line in text.strip().split('\n'):
                if not line.startswith('var hq_str_'):
                    continue
                try:
                    name_part = line.split('=', 1)[0].replace('var hq_str_', '')
                    data = line.split('="', 1)[1].rstrip('";')
                    fields = data.split(',')
                    yield (name_part, fields)
                except:
                    pass
        except Exception as e:
            print(f"    batch {i//batch+1} error: {e}")
        time.sleep(0.3)

# ═══════ 美股 ═══════
def sync_us():
    print("\n=== 美股 (新浪API) ===")
    print("[1/2] 东方财富取代码列表...")
    tickers = fetch_em_tickers('m:105+m:106+m:107')
    print(f"    EM代码: {len(tickers)} 只")
    
    # ETF/ETN 筛选关键词
    SKIP_KW = [
        'ETF', 'ETN', 'ETRACS', 'PROSHARES', 'DIREXION', 'MICROSECTORS',
        'VELOCITYSHARES', 'LEVERAGED', 'LEVER', 'INVERSE', '2X', '3X', '4X',
        'ULTRA ', 'ULTRA PRO', 'BEAR', 'BULL', 'PREFERRED', 'WARRANT',
        'VANGUARD ', 'ISHARES ', 'SPDR ', 'INVESCO ', 'TOTAL MARKET',
        'S&P 500', 'MSCI', 'FTSE ', '-2X', '-3X', 'NOTES', 'TRUST',
    ]
    
    print("[2/2] 新浪API逐批验证...")
    sina_codes = [f'gb_{t.lower()}' for t in tickers]
    
    stock_map = {}  # usTICKER -> {code, name, price}
    for name_part, fields in sina_batch_query(sina_codes):
        try:
            ticker = name_part.replace('gb_', '').upper()
            if not ticker: continue
            name = fields[0]
            price = float(fields[1]) if fields[1] != '0.0000' and fields[1] else 0
            if price <= 0: continue
            
            # ETF 过滤
            name_up = name.upper()
            if any(kw in name_up for kw in SKIP_KW): continue
            # 排除含特殊字符的
            if any(c in ticker for c in ['_', '-']): continue
            # 价格太离谱（可能是penny stock计算问题）
            if price > 50000: continue
            
            stock_map[f'us{ticker}'] = {
                'code': f'us{ticker}',
                'name': name,
                'price': price,
                'market_cap': 0,
            }
        except: pass
        if len(stock_map) % 500 == 0:
            print(f"    已验证: {len(stock_map)} 只...")
    
    results = sorted(stock_map.values(), key=lambda x: x['price'], reverse=True)
    
    with open(os.path.join(CACHE_DIR, 'us_codes.json'), 'w') as f:
        json.dump({'date': DATE, 'codes': results}, f, ensure_ascii=False, indent=2)
    
    ko = os.path.getsize(os.path.join(CACHE_DIR, 'us_codes.json')) / 1024
    print(f"    ✅ 美股: {len(results)} 只 ({ko:.1f}KB)")
    
    # 验证主流科技股
    targets = ['usAAPL','usMSFT','usGOOGL','usNVDA','usTSLA','usAMZN',
               'usMETA','usNFLX','usBABA','usAMD','usINTC','usCRM',
               'usADBE','usORCL','usQCOM','usAVGO']
    code_map = {r['code']: r for r in results}
    found = [t for t in targets if t in code_map]
    missing = [t for t in targets if t not in code_map]
    print(f"    科技股: {len(found)}/{len(targets)}")
    if missing:
        print(f"    缺失: {missing[:5]}{'...' if len(missing)>5 else ''}")
    
    return results

# ═══════ 港股 ═══════
def sync_hk():
    print("\n=== 港股 (新浪API) ===")
    print("[1/2] 东方财富取代码列表...")
    tickers = fetch_em_tickers('m:128+t:3')
    tickers += fetch_em_tickers('m:128+t:4')
    # 去重
    tickers = list(set(tickers))
    print(f"    EM代码: {len(tickers)} 只")
    
    print("[2/2] 新浪API逐批验证...")
    # 新浪港股格式: hk<5位数字> (不带市场后缀)
    sina_codes = [f'hk{int(t):05d}' for t in tickers if t.isdigit()]
    
    stock_map = {}
    for name_part, fields in sina_batch_query(sina_codes):
        try:
            code = name_part.replace('hk', '')
            name = fields[0]
            price = float(fields[1]) if fields[1] != '0.0000' and fields[1] else 0
            if price <= 0: continue
            if price > 100000: continue  # 异常价格
            
            # 排除窝轮/牛熊
            if any(kw in name for kw in ['购', '沽', '牛', '熊', '轮']):
                continue
            
            stock_map[f'hk{code}'] = {
                'code': f'hk{code}',
                'name': name,
                'price': price,
                'market_cap': 0,
            }
        except: pass
        if len(stock_map) % 500 == 0:
            print(f"    已验证: {len(stock_map)} 只...")
    
    results = sorted(stock_map.values(), key=lambda x: x['price'], reverse=True)
    
    with open(os.path.join(CACHE_DIR, 'hk_codes.json'), 'w') as f:
        json.dump({'date': DATE, 'codes': results}, f, ensure_ascii=False, indent=2)
    
    ko = os.path.getsize(os.path.join(CACHE_DIR, 'hk_codes.json')) / 1024
    print(f"    ✅ 港股: {len(results)} 只 ({ko:.1f}KB)")
    
    # 验证
    targets = ['hk00700','hk09988','hk01810','hk03690','hk00941','hk00005','hk02318']
    code_map = {r['code']: r for r in results}
    found = [t for t in targets if t in code_map]
    print(f"    核心蓝筹: {len(found)}/{len(targets)}")
    
    return results

# ═══════ 主流程 ═══════
if __name__ == '__main__':
    us = sync_us()
    hk = sync_hk()
    
    # A股计数
    a_path = os.path.join(CACHE_DIR, 'a_codes.json')
    a_count = len(json.load(open(a_path))['codes']) if os.path.exists(a_path) else 0
    
    print(f"\n{'='*50}")
    print(f"✅ 新浪API全市场同步完成!")
    print(f"  A股:   {a_count:>6} 只")
    print(f"  港股:   {len(hk):>6} 只")
    print(f"  美股:   {len(us):>6} 只")
    print(f"  合计:   {a_count+len(hk)+len(us):>6} 只")
