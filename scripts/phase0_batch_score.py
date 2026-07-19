#!/usr/bin/env python3
# Phase 0 Step 3 — PatternScorer批量评分 (Top 94动量股)
import json, os, sys, time
sys.path.insert(0, '.')
from scripts.phase0_pattern import score_pattern

# 加载Top 2%结果
top = json.load(open('reports/qullamaggie/phase0_momentum_full.json'))
candidates = top['top']
print(f"候选池: {len(candidates)} 只")

results = []
for i, c in enumerate(candidates):
    code = c['code']
    name = c['name']
    r = score_pattern(code, name)
    
    if r.total_score >= 20:  # 降低阈值看信号分布
        results.append(r)
        print(f"\n✅ {code} {name} ¥{r.price:.2f} 总分:{r.total_score}/46")
        for d in r.details:
            print(f"   {d}")
    
    if (i+1) % 20 == 0:
        print(f"   进度 {i+1}/{len(candidates)}", flush=True)
    time.sleep(0.5)  # 限速

# 排序
results.sort(key=lambda x: x.total_score, reverse=True)

print(f"\n{'='*60}")
print(f"PatternScorer 最终结果: {len(results)}/{len(candidates)} 只 ≥20分")
print(f"{'='*60}")
print(f"{'代码':<14} {'名称':<10} {'价格':>8} {'总分':>4} 前涨 回调  MA  HL  收紧 量 位置 突破")
for r in results:
    print(f"{r.code:<14} {r.name:<10} {r.price:>8.2f} {r.total_score:>4}"
          f"  {r.s1_surge:>2}  {r.s2_pullback:>2}  {r.s3_ma_support:>2}"
          f"  {r.s4_higher_low:>2}  {r.s5_tightening:>2}"
          f"  {r.s6_volume:>2}  {r.s7_position:>2}  {r.s8_breakout:>2}")

# 保存
out = 'reports/qullamaggie/phase0_pattern_results.json'
with open(out, 'w') as f:
    json.dump([{
        'code': r.code, 'name': r.name, 'price': r.price,
        'total_score': r.total_score,
        's1_surge': r.s1_surge, 's2_pullback': r.s2_pullback,
        's3_ma_support': r.s3_ma_support, 's4_higher_low': r.s4_higher_low,
        's5_tightening': r.s5_tightening, 's6_volume': r.s6_volume,
        's7_position': r.s7_position, 's8_breakout': r.s8_breakout,
        'details': r.details,
    } for r in results], f, ensure_ascii=False, indent=2)
print(f"\n📄 {out}")
