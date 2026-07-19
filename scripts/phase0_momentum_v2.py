#!/usr/bin/env python3
"""
Qullamaggie Phase 0 — 全量动量扫描 (v2)
变更: 全量5052只 + ST过滤 + 名称缓存 + 价格/量能过滤
"""
import json, os, sys, time, requests
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

sys.path.insert(0, os.path.dirname(__file__) + '/..')
os.chdir(os.path.dirname(__file__) + '/..')

CACHE_DIR = 'data/cache'
REPORTS_DIR = 'reports/qullamaggie'
os.makedirs(REPORTS_DIR, exist_ok=True)
HEADERS = {'Referer': 'https://finance.sina.com.cn/'}

@dataclass
class MomentumScore:
    code: str; name: str; price: float
    mom_1m: float; mom_3m: float; mom_6m: float; mom_12m: float
    weighted_score: float
    volume_amount: float = 0  # 日均成交额(亿)

def fetch_kline_sina(code: str, days: int = 300):
    url = f'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code}&scale=240&ma=no&datalen={days}'
    for _ in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            data = r.json()
            if not data or not isinstance(data, list): continue
            closes, amounts = [], []
            for bar in data:
                try: closes.append(float(bar['close']))
                except: pass
                try: amounts.append(float(bar['volume']) * float(bar['close']) / 1e8)  # 亿
                except: pass
            return closes, amounts
        except: time.sleep(0.5)
    return [], []

def compute_momentum(closes, lookback_days):
    if len(closes) < lookback_days + 1: return None
    past = closes[-(lookback_days+1)]
    return (closes[-1] - past) / past * 100 if past > 0 else None

def run():
    a = json.load(open(f'{CACHE_DIR}/a_codes.json'))
    codes = a['codes']
    print(f'池: {len(codes)}只 | 时间: {datetime.now():%Y-%m-%d %H:%M}')

    # 预过滤 ST
    valid = []
    for s in codes:
        name = s['name'] if isinstance(s, dict) else s
        code = s['code'] if isinstance(s, dict) else s
        if not isinstance(s, dict): name = code
        if any(kw in name for kw in ['ST', '*ST', '退市', 'N ', 'C ']):
            continue
        valid.append(s)
    print(f'过滤ST后: {len(valid)}只')

    results, errors = [], 0
    t0 = time.time()

    for i, s in enumerate(valid):
        code = s['code'] if isinstance(s, dict) else s
        name = s.get('name', code) if isinstance(s, dict) else code
        closes, amounts = fetch_kline_sina(code, 300)

        if len(closes) < 200:
            errors += 1; continue

        # 日均成交额 (近20日)
        avg_amount = sum(amounts[-20:]) / len(amounts[-20:]) if amounts else 0
        if avg_amount < 0.3:  # < 3000万/日 → 流动性不足
            errors += 1; continue

        m1 = compute_momentum(closes, 22)
        m3 = compute_momentum(closes, 66)
        m6 = compute_momentum(closes, 132)
        m12 = compute_momentum(closes, 250)

        scores = []
        if m1 is not None: scores.append((m1, 0.4))
        if m3 is not None: scores.append((m3, 0.3))
        if m6 is not None: scores.append((m6, 0.2))
        if m12 is not None: scores.append((m12, 0.1))
        w = sum(w for _, w in scores)
        weighted = sum(v*w for v,w in scores)/w if w>0 else 0

        results.append(MomentumScore(
            code=code, name=name, price=closes[-1],
            mom_1m=m1 or 0, mom_3m=m3 or 0,
            mom_6m=m6 or 0, mom_12m=m12 or 0,
            weighted_score=weighted,
            volume_amount=avg_amount,
        ))

        if (i+1) % 500 == 0:
            e = time.time()-t0
            print(f'  {i+1}/{len(valid)} ({e:.0f}s, ETA {e/(i+1)*(len(valid)-i-1):.0f}s) 有效{len(results)}')

        time.sleep(0.06)

    elapsed = time.time() - t0
    results.sort(key=lambda x: x.weighted_score, reverse=True)

    # Top 2%
    top_n = max(20, int(len(results)*0.02))
    top = results[:top_n]

    print(f'\n⏱ {elapsed:.0f}s | 有效{len(results)} | Top {top_n} (2%)')
    print(f'{"代码":<14} {"名称":<10} {"价格":>7} {"1月%":>7} {"3月%":>7} {"6月%":>7} {"12月%":>7} {"加权":>7} {"日均亿":>7}')
    print('-'*80)
    for r in top[:20]:
        print(f'{r.code:<14} {r.name:<10} {r.price:>7.2f} {r.mom_1m:>7.1f} {r.mom_3m:>7.1f} {r.mom_6m:>7.1f} {r.mom_12m:>7.1f} {r.weighted_score:>7.1f} {r.volume_amount:>7.2f}')

    # 保存
    out = f'{REPORTS_DIR}/phase0_momentum_full.json'
    with open(out, 'w') as f:
        json.dump({
            'scan_time': datetime.now().isoformat(),
            'pool': len(codes), 'scanned': len(valid),
            'valid': len(results), 'top_n': top_n, 'elapsed_s': elapsed,
            'top': [{k: getattr(r,k) for k in ['code','name','price','mom_1m','mom_3m','mom_6m','mom_12m','weighted_score','volume_amount']} for r in top]
        }, f, ensure_ascii=False, indent=2)
    print(f'\n📄 {out}')

if __name__ == '__main__':
    run()
