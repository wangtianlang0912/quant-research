#!/usr/bin/env python3
"""
全市场股票代码同步脚本
- A股：刷新缓存（排除ST/停牌/新股未开板）
- 港股：东方财富API获取全量港股（主板+创业板）
- 美股：东方财富API获取全量美股（NASDAQ+NYSE+AMEX）
"""
import json
import os
import time
import requests
from datetime import date

CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'cache')
os.makedirs(CACHE_DIR, exist_ok=True)
DATE = date.today().isoformat()

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Referer': 'https://quote.eastmoney.com/',
}

# ──────── 工具函数 ────────

def fetch_em_list(fs_filter: str, fields: str, page_size=500, max_pages=30) -> list:
    """通用东方财富列表拉取"""
    all_data = []
    for page in range(1, max_pages + 1):
        url = (
            f'https://push2.eastmoney.com/api/qt/clist/get'
            f'?pn={page}&pz={page_size}&po=1&np=1&fltt=2&invt=2'
            f'&fid=f12&fs={fs_filter}&fields={fields}'
        )
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            data = r.json()
            items = data.get('data', {}).get('diff', [])
            if not items:
                break
            all_data.extend(items)
        except Exception as e:
            print(f"  第{page}页失败: {e}")
            break
        if page % 5 == 0:
            print(f"  已拉取 {len(all_data)} 只...")
        time.sleep(0.3)
    return all_data

# ──────── A股：刷新缓存 ────────

def sync_a_codes():
    print("\n=== A股代码同步 ===")
    cache_file = os.path.join(CACHE_DIR, 'a_codes.json')
    
    # 先读旧缓存
    old_codes = set()
    if os.path.exists(cache_file):
        with open(cache_file) as f:
            old_codes = set(json.load(f).get('codes', []))
    
    # 扩展探测范围，cover 所有合理范围
    ranges = [
        ('sh', 600000, 684000),   # 沪市主板
        ('sh', 688000, 689500),   # 科创板
        ('sz', 0, 5000),          # 深市主板(000+001+002)
        ('sz', 300000, 301500),   # 创业板
    ]
    
    all_codes = set()
    for market, start, end in ranges:
        codes = [f"{market}{i:06d}" for i in range(start, end)]
        for i in range(0, len(codes), 800):
            batch = codes[i:i+800]
            try:
                url = f"http://qt.gtimg.cn/q={','.join(batch)}"
                r = requests.get(url, timeout=15)
                text = r.content.decode('gbk', errors='replace')
                for line in text.strip().split('\n'):
                    if line.startswith('v_'):
                        try:
                            data = line.split('="', 1)[1].rstrip('";')
                            parts = data.split('~')
                            if len(parts) >= 5:
                                price = float(parts[3]) if parts[3] else 0
                                name = parts[1] if len(parts) > 1 else ''
                                if price > 0 and 'ST' not in name and '退市' not in name:
                                    code = parts[2].lower()
                                    if not code.startswith(('sh', 'sz')):
                                        code = f"{market}{code.zfill(6)}"
                                    all_codes.add(code)
                        except Exception:
                            pass
                    elif 'strerr' in line:
                        # 探测到空范围，提前跳出当前batch
                        pass
            except Exception as e:
                print(f"  A股探测失败 {market} batch {i}: {e}")
            time.sleep(0.15)
    
    codes_list = sorted(all_codes)
    with open(cache_file, 'w') as f:
        json.dump({'date': DATE, 'codes': codes_list}, f, ensure_ascii=False)
    
    new_count = len(all_codes - old_codes)
    removed = len(old_codes - all_codes)
    print(f"  A股总数: {len(codes_list)} (新增 {new_count}，剔除/停牌 {removed})")
    return codes_list

# ──────── 港股：全量获取 ────────

def sync_hk_codes():
    print("\n=== 港股代码同步 ===")
    cache_file = os.path.join(CACHE_DIR, 'hk_codes.json')
    
    # 东方财富港股板块: m:128 港股 + t:3 主板 + t:4 创业板
    fs_filters = [
        'm:128+t:3',   # 港股主板
        'm:128+t:4',   # 港股创业板
        'm:128+t:1',   # 港股ETF
        'm:128+t:2',   # 港股窝轮/牛熊证 → 需要排除
    ]
    
    all_items = []
    for fs_filter in fs_filters:
        items = fetch_em_list(fs_filter, 'f2,f3,f4,f12,f14')
        all_items.extend(items)
    
    codes = []
    seen = set()
    excluded_types = {'牛熊证', '界内证', '杠杆及反向产品'}
    for item in all_items:
        code = item.get('f12', '')
        name = item.get('f14', '')
        price = item.get('f2', 0) or 0
        market_cap = item.get('f20', 0) or 0
        
        if code in seen:
            continue
        seen.add(code)
        
        # 排除窝轮牛熊等衍生产品（名称含"购"/"沽"/"牛"/"熊"）
        if any(kw in name for kw in ['购', '沽', '牛', '熊', '轮']):
            continue
        # 价格 > 0
        if price <= 0:
            continue
        # 排除市值太小的仙股（< 1亿港元）
        if market_cap > 0 and market_cap < 1e8:
            continue
        
        codes.append({
            'code': f'hk{code}',
            'name': name,
            'market_cap': market_cap,
        })
    
    # 按市值降序排列
    codes.sort(key=lambda x: x.get('market_cap', 0), reverse=True)
    
    with open(cache_file, 'w') as f:
        json.dump({'date': DATE, 'codes': codes}, f, ensure_ascii=False)
    
    print(f"  港股总数: {len(codes)} (排除窝轮/仙股)")
    return codes

# ──────── 美股：全量获取 ────────

def sync_us_codes():
    print("\n=== 美股代码同步 ===")
    cache_file = os.path.join(CACHE_DIR, 'us_codes.json')
    
    # 东方财富美股板块
    fs_filters = [
        'm:105+m:106+m:107',  # 全部美股
    ]
    
    all_items = []
    for fs_filter in fs_filters:
        items = fetch_em_list(fs_filter, 'f2,f3,f4,f12,f14,f20', max_pages=40)
        all_items.extend(items)
    
    codes = []
    seen = set()
    for item in all_items:
        code = item.get('f12', '')
        name = item.get('f14', '')
        price = item.get('f2', 0) or 0
        market_cap = item.get('f20', 0) or 0
        
        if code in seen:
            continue
        seen.add(code)
        
        if price <= 0:
            continue
        # 排除市值过小（< 1亿美元）
        if market_cap > 0 and market_cap < 1e8:
            continue
        # 排除含特殊字符的代码
        if any(c in code for c in ['.', '^', '/']):
            continue
        
        codes.append({
            'code': f'us{code}',
            'name': name,
            'market_cap': market_cap,
        })
    
    codes.sort(key=lambda x: x.get('market_cap', 0), reverse=True)
    
    with open(cache_file, 'w') as f:
        json.dump({'date': DATE, 'codes': codes}, f, ensure_ascii=False)
    
    print(f"  美股总数: {len(codes)} (排除细价股)")
    return codes

# ──────── 主流程 ────────

if __name__ == '__main__':
    print(f"全市场代码同步 - {DATE}")
    print("=" * 50)
    
    a = sync_a_codes()
    hk = sync_hk_codes()
    us = sync_us_codes()
    
    print("\n" + "=" * 50)
    print(f"✅ 同步完成!")
    print(f"  A股: {len(a)} 只")
    print(f"  港股: {len(hk)} 只")
    print(f"  美股: {len(us)} 只")
    print(f"  合计: {len(a) + len(hk) + len(us)} 只")
    print(f"\n缓存文件:")
    for f in ['a_codes.json', 'hk_codes.json', 'us_codes.json']:
        path = os.path.join(CACHE_DIR, f)
        if os.path.exists(path):
            size_kb = os.path.getsize(path) / 1024
            print(f"  {CACHE_DIR}/{f} ({size_kb:.1f} KB)")
