#!/usr/bin/env python3
"""
Qullamaggie Phase 0 — MomentumScanner 回测验证
步骤:
1. 从新浪API拉A股近12月K线 (日期+收盘价)
2. 计算1/3/6月动量百分比
3. 加权排序，Top 2% 输出
4. (后续) 形态评分卡 + 回测
"""
from __future__ import annotations
import json, os, sys, time, requests
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.chdir(os.path.join(os.path.dirname(__file__), '..'))

CACHE_DIR = os.path.join('data', 'cache')
REPORTS_DIR = os.path.join('reports', 'qullamaggie')
os.makedirs(REPORTS_DIR, exist_ok=True)

HEADERS = {'Referer': 'https://finance.sina.com.cn/'}

@dataclass
class MomentumScore:
    code: str
    name: str
    price: float
    mom_1m: float   # 1个月收益率%
    mom_3m: float   # 3个月
    mom_6m: float   # 6个月
    mom_12m: float  # 12个月
    weighted_score: float  # 加权: 1m*0.4 + 3m*0.3 + 6m*0.2 + 12m*0.1
    has_data: bool = True

# ═══ K线获取 ═══
def fetch_kline_sina(code: str, days: int = 300) -> list[float]:
    """新浪日K线API → [(date,close), ...]"""
    # A股: sh600000 / sz000001
    url = f'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code}&scale=240&ma=no&datalen={days}'
    for retry in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200: continue
            data = r.json()
            if not data or not isinstance(data, list): continue
            closes = []
            for bar in data:
                try: closes.append(float(bar['close']))
                except: pass
            return closes
        except:
            time.sleep(0.5)
    return []

# ═══ 动量计算 ═══
def compute_momentum(closes: list[float], lookback_days: int) -> Optional[float]:
    """给定收盘价列表，计算期末/期初收益率"""
    if len(closes) < lookback_days + 1:
        return None
    today = closes[-1]
    past = closes[-(lookback_days+1)]
    if past <= 0:
        return None
    return (today - past) / past * 100

# ═══ 主扫描 ═══
def run_scan():
    print("=" * 60)
    print("Qullamaggie MomentumScanner — Phase 0")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    
    # 加载A股池
    pool_data = json.load(open(os.path.join(CACHE_DIR, 'a_codes.json')))
    raw_codes = pool_data['codes']
    print(f"\n📊 A股池: {len(raw_codes)} 只")
    
    # 解析代码（可能是str列表或dict列表）
    if isinstance(raw_codes[0], str):
        codes_only = raw_codes
        names_map = {}
    else:
        codes_only = [s['code'] for s in raw_codes]
        names_map = {s['code']: s.get('name','') for s in raw_codes}
    
    # 采样扫描
    sample = codes_only[:500]
    print(f"   扫描样本: {len(sample)} 只 (首500)")
    
    results: List[MomentumScore] = []
    errors = 0
    t0 = time.time()
    
    for i, code in enumerate(sample):
        name = names_map.get(code, code)
        closes = fetch_kline_sina(code, days=300)
        
        if len(closes) < 250:
            errors += 1
            continue
        
        mom_1m = compute_momentum(closes, 22)   # 约1月交易日
        mom_3m = compute_momentum(closes, 66)
        mom_6m = compute_momentum(closes, 132)
        mom_12m = compute_momentum(closes, 250)
        
        # 加权得分: 1m*0.4 + 3m*0.3 + 6m*0.2 + 12m*0.1
        # 缺失的周期按0处理
        scores = []
        if mom_1m is not None: scores.append((mom_1m, 0.4))
        if mom_3m is not None: scores.append((mom_3m, 0.3))
        if mom_6m is not None: scores.append((mom_6m, 0.2))
        if mom_12m is not None: scores.append((mom_12m, 0.1))
        
        if scores:
            total_w = sum(w for _, w in scores)
            weighted = sum(v*w for v,w in scores) / total_w if total_w > 0 else 0
        else:
            weighted = 0
        
        results.append(MomentumScore(
            code=code, name=name, price=closes[-1] if closes else 0,
            mom_1m=mom_1m or 0, mom_3m=mom_3m or 0,
            mom_6m=mom_6m or 0, mom_12m=mom_12m or 0,
            weighted_score=weighted,
        ))
        
        if (i+1) % 100 == 0:
            elapsed = time.time() - t0
            eta = elapsed / (i+1) * (len(sample) - i - 1)
            print(f"  进度 {i+1}/{len(sample)} ({elapsed:.0f}s, ETA {eta:.0f}s)")
        
        time.sleep(0.08)  # 新浪限速
    
    elapsed = time.time() - t0
    print(f"\n⏱  扫描完成: {elapsed:.0f}s, 有效{len(results)}只, 错误{errors}只")
    
    # 排序
    results.sort(key=lambda x: x.weighted_score, reverse=True)
    
    # Top 2% = Top 10 (500*2%)
    top_n = max(10, int(len(results) * 0.02))
    top = results[:top_n]
    
    print(f"\n{'='*60}")
    print(f"🏆 Top {top_n} 动量股 (加权得分 1m*0.4+3m*0.3+6m*0.2+12m*0.1)")
    print(f"{'='*60}")
    print(f"{'代码':<14} {'名称':<12} {'价格':>8} {'1月%':>7} {'3月%':>7} {'6月%':>7} {'12月%':>7} {'加权':>7}")
    print("-" * 74)
    for r in top:
        print(f"{r.code:<14} {r.name:<12} {r.price:>8.2f} {r.mom_1m:>7.1f} {r.mom_3m:>7.1f} {r.mom_6m:>7.1f} {r.mom_12m:>7.1f} {r.weighted_score:>7.1f}")
    
    # 保存
    out_path = os.path.join(REPORTS_DIR, 'phase0_momentum_top.json')
    report = {
        'scan_time': datetime.now().isoformat(),
        'sample_size': len(sample),
        'pool_size': len(raw_codes),
        'top_n': top_n,
        'elapsed_s': elapsed,
        'results': [
            {k:v for k,v in r.__dict__.items()} for r in top
        ]
    }
    with open(out_path, 'w') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n📄 结果已保存: {out_path}")
    
    return top

if __name__ == '__main__':
    run_scan()
