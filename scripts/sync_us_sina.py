#!/usr/bin/env python3
"""美股代码同步 - 新浪财经API (更完整的覆盖率)"""
import json, os, time, re, requests

CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'cache')
os.makedirs(CACHE_DIR, exist_ok=True)

ses = requests.Session()
ses.headers.update({
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Referer': 'https://finance.sina.com.cn/',
})

# 新浪美股代码规则: gb_<ticker>  (不同于东方财富的 us<TICKER>)
# 我们要生成的是 us<TICKER> 格式 (和现有代码一致)

def fetch_sina_page(page=1, page_size=100):
    """新浪美股行情排行"""
    url = f'https://vip.stock.finance.sina.com.cn/q/go.php/vFinanceAnalyze/kind/stockp?p={page}&num={page_size}&symbol=gb'
    try:
        r = ses.get(url, timeout=15)
        r.encoding = 'gbk'
        return r.text
    except Exception as e:
        print(f"  第{page}页失败: {e}")
        return None

def parse_sina_page(html):
    """解析新浪股票列表页面"""
    results = []
    # 匹配行: <tr> ... <td>代码</td> ... </tr>
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    for row in rows:
        tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        if len(tds) >= 5:
            code_raw = re.sub(r'<[^>]+>', '', tds[0]).strip()
            name_raw = re.sub(r'<[^>]+>', '', tds[1]).strip()
            price_raw = re.sub(r'<[^>]+>', '', tds[2]).strip()
            change_raw = re.sub(r'<[^>]+>', '', tds[3]).strip()
            
            if not code_raw or not name_raw:
                continue
            # 新浪代码格式: gb_AAPL
            if code_raw.startswith('gb_'):
                ticker = code_raw[3:]
            else:
                ticker = code_raw
            
            try:
                price = float(price_raw.replace(',', ''))
            except:
                price = 0.0
            
            if price <= 0 or len(ticker) > 6:
                continue
            
            results.append({
                'code': f'us{ticker}',
                'name': name_raw,
                'price': price,
            })
    return results

# 抓取多页
all_stocks = []
for page in range(1, 200):
    html = fetch_sina_page(page, 100)
    if not html:
        break
    stocks = parse_sina_page(html)
    if not stocks:
        break
    all_stocks.extend(stocks)
    if page % 10 == 0:
        print(f"  已拉取 {len(all_stocks)} 只...")
    time.sleep(0.3)

# 去重
seen = set()
unique = []
for s in all_stocks:
    if s['code'] not in seen:
        seen.add(s['code'])
        unique.append(s)

print(f"  美股总数(新浪): {len(unique)} 只")

# 验证关键股票
targets = ['usAAPL','usMSFT','usGOOGL','usNVDA','usTSLA','usAMZN','usMETA','usNFLX','usBABA','usAMD']
found = {s['code']: s for s in unique}
print("  验证主流科技股:")
for t in targets:
    if t in found:
        print(f"    {t}: ✅ {found[t]['name']} ${found[t]['price']}")
    else:
        print(f"    {t}: ❌ 缺失")

with open(os.path.join(CACHE_DIR, 'us_codes.json'), 'w') as f:
    json.dump({'date': '2026-06-29', 'codes': unique}, f, ensure_ascii=False)
print(f"\n✅ 美股缓存已更新: {os.path.join(CACHE_DIR, 'us_codes.json')}")
