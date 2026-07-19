#!/usr/bin/env python3
"""港股美股代码同步（A股已完成）"""
import json, os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'cache')
os.makedirs(CACHE_DIR, exist_ok=True)
DATE = '2026-06-29'

# 带重试的 session
def make_session():
    s = requests.Session()
    retry = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    s.mount('http://', adapter)
    s.mount('https://', adapter)
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer': 'https://quote.eastmoney.com/',
    })
    return s

def fetch_em_list(s: requests.Session, fs_filter: str, fields: str, page_size=500, max_pages=40):
    all_data = []
    for page in range(1, max_pages + 1):
        url = (
            f'https://push2.eastmoney.com/api/qt/clist/get'
            f'?pn={page}&pz={page_size}&po=1&np=1&fltt=2&invt=2'
            f'&fid=f12&fs={fs_filter}&fields={fields}'
        )
        for attempt in range(3):
            try:
                r = s.get(url, timeout=20)
                if r.status_code != 200:
                    print(f"  第{page}页 HTTP {r.status_code}，重试{attempt+1}...")
                    time.sleep(2)
                    continue
                data = r.json()
                if data is None or data.get('data') is None:
                    break
                items = data['data'].get('diff') or []
                if not items:
                    break
                all_data.extend(items)
                break
            except requests.exceptions.SSLError:
                print(f"  第{page}页 SSL错误，重试{attempt+1}...")
                time.sleep(3)
            except Exception as e:
                if attempt == 2:
                    print(f"  第{page}页失败(已重试3次): {e}")
                else:
                    time.sleep(2)
        else:
            # 3次都失败，跳过这页
            continue
        
        if page % 5 == 0:
            print(f"  已拉取 {len(all_data)} 只...")
        time.sleep(0.3)
    return all_data

def safe_float(v):
    try:
        if v == '-' or v is None or v == '':
            return 0.0
        return float(v)
    except (ValueError, TypeError):
        return 0.0

# ─── 港股 ───
print("=== 港股代码同步 ===")
s = make_session()

# 只抓主板（m:128+t:3），创业板量少合并
fs_list = ['m:128+t:3', 'm:128+t:4']
all_items = []
for fs in fs_list:
    items = fetch_em_list(s, fs, 'f2,f3,f4,f12,f14,f20')
    all_items.extend(items)

codes = []
seen = set()
for item in all_items:
    code = item.get('f12', '')
    name = item.get('f14', '')
    price = safe_float(item.get('f2'))
    mc = safe_float(item.get('f20'))
    
    if code in seen:
        continue
    seen.add(code)
    
    # 排除窝轮等衍生产品
    if any(kw in name for kw in ['购', '沽', '牛', '熊', '轮']):
        continue
    if price <= 0:
        continue
    if mc > 0 and mc < 1e8:  # < 1亿港元
        continue
    
    codes.append({'code': f'hk{code}', 'name': name, 'market_cap': mc})

hk_codes_list = codes
hk_codes_list.sort(key=lambda x: x.get('market_cap', 0), reverse=True)

with open(os.path.join(CACHE_DIR, 'hk_codes.json'), 'w') as f:
    json.dump({'date': DATE, 'codes': hk_codes_list}, f, ensure_ascii=False)
print(f"  港股总数: {len(hk_codes_list)}")

# ─── 美股 ───
print("\n=== 美股代码同步 ===")
s2 = make_session()

items = fetch_em_list(s2, 'm:105+m:106+m:107', 'f2,f3,f4,f12,f14,f20', max_pages=50)

codes = []
seen = set()
for item in items:
    code = item.get('f12', '')
    name = item.get('f14', '')
    price = safe_float(item.get('f2'))
    mc = safe_float(item.get('f20'))
    
    if code in seen:
        continue
    seen.add(code)
    
    if price <= 0:
        continue
    if mc > 0 and mc < 1e8:
        continue
    if any(c in code for c in ['.', '^', '/']):
        continue
    # 排除ETN/ETF/杠杆产品/优先股
    name_upper = name.upper()
    if any(kw in name_upper or kw in name for kw in [
        'ETRACS', 'ETN', 'LEVER', 'LEVERAGED', '2X', '3X', '4X',
        'ULTRA', 'ULTRA PRO', 'INVERSE', 'BEAR', 'BULL', 'SHORT',
        'PREFERRED', 'PFD', 'PERP', 'WARRANT', '"',
        'ETF', 'INDEX', 'TOTAL MARKET', 'S&P', 'MSCI', 'FTSE',
        'NASDAQ', 'VANGUARD', 'ISHARES', 'SPDR', 'INVESCO',
        'DIREXION', 'PROSHARES', 'VELOCITYSHARES',
    ]):
        continue
    
    codes.append({'code': f'us{code}', 'name': name, 'market_cap': mc})

us_codes_list = codes
us_codes_list.sort(key=lambda x: x.get('market_cap', 0), reverse=True)

with open(os.path.join(CACHE_DIR, 'us_codes.json'), 'w') as f:
    json.dump({'date': DATE, 'codes': us_codes_list}, f, ensure_ascii=False)
print(f"  美股总数: {len(us_codes_list)}")

# ─── 汇总 ───
a_path = os.path.join(CACHE_DIR, 'a_codes.json')
a_count = len(json.load(open(a_path))['codes']) if os.path.exists(a_path) else 0
print(f"\n{'='*40}")
print(f"✅ 全市场代码同步完成!")
print(f"  A股: {a_count} 只")
print(f"  港股: {len(hk_codes_list)} 只")
print(f"  美股: {len(us_codes_list)} 只")
print(f"  合计: {a_count + len(hk_codes_list) + len(us_codes_list)} 只")
