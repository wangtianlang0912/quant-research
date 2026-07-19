#!/usr/bin/env python3
"""Phase 0 v3 — Breakout 参数扫描优化
扫描: 入场阈值 / 跟踪均线 / 部分平仓日 / 最大持仓数
"""
import json, os, sys, time, itertools
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from statistics import mean, stdev

sys.path.insert(0, '/Users/leihen/.qclaw/workspace/quant-research')

INITIAL_CAPITAL = 1000000
COMMISSION = 0.0003
SLIPPAGE = 0.001

@dataclass
class Trade:
    code: str; entry_date: str; exit_date: str = ""
    entry_price: float = 0; exit_price: float = 0
    shares: int = 0; pnl: float = 0; pnl_pct: float = 0
    stop_price: float = 0; reason: str = ""

def sma(values, period):
    if len(values) < period: return None
    return sum(values[-period:]) / period

def fetch_history(code: str) -> list:
    cf = f'data/cache/klines_{code}.json'
    if not os.path.exists(cf): return []
    with open(cf) as f:
        return json.load(f)['candles']

def compute_atr(candles, period=14):
    if len(candles) < period + 1: return 0
    trs = []
    for i in range(1, len(candles)):
        h, l = candles[i]['high'], candles[i]['low']
        pc = candles[i-1]['close']
        tr = max(h-l, abs(h-pc), abs(l-pc))
        trs.append(tr)
    if len(trs) < period: return sum(trs)/len(trs)
    return sum(trs[-period:]) / period

def score_pattern(code, candles, idx):
    """形态评分（同 Phase 0 v1）"""
    if idx < 120: return 0, {}
    window = candles[:idx+1]
    close_now = window[-1]['close']
    details = {}
    total = 0
    
    # 1. 前段涨幅 (1-3月前的大涨)
    pre_start = max(0, idx-90)
    pre_end = max(0, idx-50)
    if pre_end - pre_start > 10:
        pre_prices = [c['close'] for c in window[pre_start:pre_end]]
        gain = (max(pre_prices) - min(pre_prices)) / min(pre_prices)
        if gain > 1.0: p = 8
        elif gain > 0.8: p = 6
        elif gain > 0.5: p = 4
        elif gain > 0.3: p = 2
        else: p = 0
        details['surge'] = p; total += p
    
    # 2. 回调幅度（从前高）
    peak_after_surge = max(c['close'] for c in window[pre_end:idx])
    drawdown = (peak_after_surge - close_now) / peak_after_surge
    if 0.20 <= drawdown <= 0.40: p = 8
    elif 0.15 <= drawdown <= 0.50: p = 4
    elif 0.10 <= drawdown <= 0.55: p = 2
    else: p = 0
    details['drawdown'] = p; total += p
    
    # 3. MA支撑
    closes = [c['close'] for c in window]
    ma10 = sma(closes, 10)
    if ma10:
        dist = abs(close_now - ma10) / ma10
        if dist < 0.02:
            recent = [abs(c['close']-ma10)/ma10 for c in window[-4:]]
            if all(r < 0.02 for r in recent): p = 6
            else: p = 4
        elif dist < 0.04: p = 2
        elif dist < 0.06: p = 1
        else: p = 0
        details['ma_support'] = p; total += p
    
    # 4. Higher Low
    lows = [c['low'] for c in window[-60:]]
    hl_count = 0
    cur_min = float('inf')
    for i in range(len(lows)-1, -1, -1):
        if lows[i] < cur_min:
            hl_count += 1
            cur_min = lows[i]
    if hl_count >= 3: p = 6
    elif hl_count >= 2: p = 3
    elif hl_count >= 1: p = 1
    else: p = 0
    details['higher_low'] = p; total += p
    
    # 5. 波动收窄 (ATR5/ATR20)
    atr5 = compute_atr(window, 5)
    atr20 = compute_atr(window, 20)
    if atr20 > 0 and close_now > 0:
        ratio = atr5 / max(atr20, 0.01*close_now)
        if ratio < 0.7: p = 4
        elif ratio < 0.85: p = 2
        elif ratio < 1.0: p = 1
        else: p = 0
        details['vol_squeeze'] = p; total += p
    
    # 6. 成交量衰减
    vols = [c['volume'] for c in window]
    vol5_avg = sum(vols[-5:])/5 if vols[-5:] else 1
    vol20_avg = sum(vols[-20:])/20 if vols[-20:] else 1
    vol_ratio = vol5_avg / vol20_avg if vol20_avg > 0 else 1
    if vol_ratio < 0.7: p = 3
    elif vol_ratio < 0.85: p = 2
    elif vol_ratio < 1.0: p = 0
    else: p = 0
    details['vol_decay'] = p; total += p
    
    # 7. 所处位置
    if ma10:
        peak60 = max(closes[-60:])
        pct_range = (close_now - ma10) / (peak60 - ma10) if peak60 != ma10 else 0.5
        if 0.5 <= pct_range <= 0.95: p = 3
        elif 0.3 <= pct_range <= 0.97: p = 2
        elif pct_range <= 0.99: p = 1
        else: p = 0
        details['position'] = p; total += p
    else:
        details['position'] = 0
    
    # 8. 突破信号
    if idx >= 1:
        prev_close = window[-2]['close']
        daily_change = (close_now - prev_close) / prev_close
        atr_pct = compute_atr(window, 10) / close_now
        if daily_change > atr_pct * 1.5 and vol_ratio > 1.5: p = 5
        elif daily_change > atr_pct * 1.0: p = 3
        elif daily_change > atr_pct * 0.5: p = 1
        else: p = 0
        details['breakout'] = p; total += p
    
    return total, details

def run_param_backtest(all_candles, params):
    """跑一组参数的完整回测"""
    score_min = params['score_min']
    ma_track = params['ma_track']
    partial_day = params['partial_day']
    partial_pct = params['partial_pct']
    max_positions = params['max_positions']
    atr_stop_mul = params['atr_stop_mul']
    
    # 交易日历
    all_dates = set()
    for c in all_candles.values():
        all_dates |= set(x['date'] for x in c)
    trading_days = sorted([d for d in all_dates if '2025-01-02' <= d <= '2026-06-26'])
    
    cash = INITIAL_CAPITAL
    positions: List[Trade] = []
    closed: List[Trade] = []
    equity = []
    
    date_idx_map = {code: {c['date']: i for i, c in enumerate(candles)}
                    for code, candles in all_candles.items()}
    
    for today in trading_days:
        # 更新止损 = 当日低点
        for t in positions:
            c = all_candles[t.code][date_idx_map[t.code][today]]
            ma = sma([x['close'] for x in all_candles[t.code][:date_idx_map[t.code][today]+1]], ma_track)
            new_stop = c['low']
            if ma: new_stop = max(new_stop, ma * (1 - 0.01 * atr_stop_mul))
            if new_stop > t.stop_price:
                t.stop_price = new_stop
        
        # 止损检查
        to_remove = []
        for t in positions:
            idx_t = date_idx_map.get(t.code, {}).get(today)
            if idx_t is None: continue
            c = all_candles[t.code][idx_t]
            if c['low'] <= t.stop_price:
                t.exit_date = today
                t.exit_price = t.stop_price
                t.pnl = (t.stop_price - t.entry_price) * t.shares
                t.pnl_pct = t.pnl / (t.entry_price * t.shares)
                t.reason = '止损'
                closed.append(t)
                cash += t.shares * t.stop_price
                to_remove.append(t)
        for t in to_remove: positions.remove(t)
        
        # 部分平仓 / MA跟踪出场
        to_remove = []
        for t in positions:
            idx_t = date_idx_map[t.code][today]
            c = all_candles[t.code][idx_t]
            entry_idx = date_idx_map[t.code][t.entry_date]
            hold_days = idx_t - entry_idx
            
            # 部分平仓
            if hold_days >= partial_day and t.reason == 'entry':
                sell_shares = int(t.shares * partial_pct)
                cash += sell_shares * c['close'] * (1 - COMMISSION - SLIPPAGE)
                t.shares -= sell_shares
                t.stop_price = t.entry_price
                t.reason = 'partial'
            
            # MA下穿
            if hold_days >= ma_track // 2:
                closes = [x['close'] for x in all_candles[t.code][:idx_t+1]]
                ma = sma(closes, ma_track)
                if ma and c['close'] < ma:
                    t.exit_date = today
                    t.exit_price = c['close'] * (1 - SLIPPAGE)
                    t.pnl = (t.exit_price - t.entry_price) * t.shares
                    t.pnl_pct = t.pnl / (t.entry_price * t.shares)
                    t.reason = 'MA跌破'
                    closed.append(t)
                    cash += t.shares * t.exit_price
                    to_remove.append(t)
        for t in to_remove: positions.remove(t)
        
        # 入场扫描
        if cash > INITIAL_CAPITAL * 0.1 and len(positions) < max_positions:
            candidates = []
            for code, candles in all_candles.items():
                if code in [t.code for t in positions]: continue
                idx_d = date_idx_map[code].get(today)
                if idx_d is None or idx_d < 120: continue
                s, _ = score_pattern(code, candles, idx_d)
                if s >= score_min:
                    c = candles[idx_d]
                    candidates.append((code, s, c['close'], c['volume']))
            
            candidates.sort(key=lambda x: x[1], reverse=True)
            slots = max_positions - len(positions)
            for code, sc, price, vol in candidates[:slots]:
                if price <= 0: continue
                atr = compute_atr(all_candles[code], 10)
                stop_price = price - atr_stop_mul * atr
                risk = price - stop_price
                if risk <= 0: continue
                risk_pct = 0.008
                position_size = cash * risk_pct / risk
                shares = int(position_size / (price * (1 + COMMISSION)))
                if shares < 100: continue
                cost = shares * price * (1 + COMMISSION)
                if cost > cash * 0.15:  # 单票 ≤15%
                    shares = int(cash * 0.15 / (price * (1 + COMMISSION)))
                    cost = shares * price * (1 + COMMISSION)
                if cost > cash: continue
                cash -= cost
                positions.append(Trade(code=code, entry_date=today, entry_price=price,
                                       shares=shares, stop_price=stop_price, reason='entry'))
        
        total_equity = cash + sum(t.shares * all_candles[t.code][date_idx_map[t.code][today]]['close']
                                  for t in positions)
        equity.append(total_equity)
    
    # 清算未平仓
    last_day = trading_days[-1]
    for t in positions:
        idx = date_idx_map[t.code].get(last_day, -1)
        if idx >= 0:
            t.exit_date = last_day
            t.exit_price = all_candles[t.code][idx]['close'] * (1 - SLIPPAGE)
            t.pnl = (t.exit_price - t.entry_price) * t.shares
            t.pnl_pct = t.pnl / (t.entry_price * t.shares)
            t.reason = '到期清算'
            closed.append(t)
    
    # 指标
    if not equity or len(equity) < 2: return None
    final_eq = equity[-1]
    total_return = (final_eq - INITIAL_CAPITAL) / INITIAL_CAPITAL
    returns = [(equity[i]-equity[i-1])/equity[i-1] for i in range(1, len(equity))]
    if not returns: return None
    
    ann_return = (1 + total_return) ** (252/len(trading_days)) - 1
    rf_daily = 0.03/252
    excess = [r - rf_daily for r in returns]
    sharpe = (mean(excess) / stdev(excess) * (252**0.5)) if stdev(excess) > 0 else 0
    peak = INITIAL_CAPITAL
    max_dd = 0
    for e in equity:
        if e > peak: peak = e
        dd = (peak - e) / peak
        if dd > max_dd: max_dd = dd
    
    wins = [t for t in closed if t.pnl > 0]
    win_rate = len(wins)/len(closed) if closed else 0
    avg_win = mean([t.pnl_pct for t in wins]) if wins else 0
    avg_loss = mean([t.pnl_pct for t in closed if t.pnl <= 0]) if [t for t in closed if t.pnl <= 0] else 0
    profit_factor = abs(sum(t.pnl for t in wins) / sum(t.pnl for t in closed if t.pnl < 0)) if any(t.pnl < 0 for t in closed) else 99
    
    equity.sort()
    return {
        'params': params,
        'total_return': round(total_return*100, 2),
        'ann_return': round(ann_return*100, 2),
        'sharpe': round(sharpe, 2),
        'max_dd': round(max_dd*100, 2),
        'trades': len(closed),
        'win_rate': round(win_rate*100, 1),
        'avg_win': round(avg_win*100, 2),
        'avg_loss': round(avg_loss*100, 2),
        'profit_factor': round(profit_factor, 2),
        'final_equity': round(final_eq),
    }

# ─── 主流程 ───
print("=" * 60)
print("Phase 0 v3 — Breakout 参数扫描")
print("=" * 60)

# 加载数据
hs300 = json.load(open('data/cache/hs300_pool.json'))
all_candles = {}
for code in hs300:
    c = fetch_history(code)
    if c and len(c) >= 250: all_candles[code] = c
print(f"K线: {len(all_candles)} 只")

# 参数网格
param_grid = list(itertools.product(
    [18, 20, 22, 25],          # score_min
    [10, 20],                   # ma_track
    [3, 5, 7],                  # partial_day
    [0.3, 0.5],                 # partial_pct
    [3, 5],                     # max_positions
    [1.0, 1.5, 2.0],           # atr_stop_mul
))
# Filter reasonable combos
param_grid = [(s,m,pd,pp,mp,atr) for s,m,pd,pp,mp,atr in param_grid
              if not (pp > 0.3 and pd < 5)  # 早卖不用50%比例
              and not (mp == 3 and s > 22)]  # 少仓位放宽门槛
print(f"参数组合: {len(param_grid)} 组")

results = []
for i, (score_min, ma_track, partial_day, partial_pct, max_pos, atr_stop) in enumerate(param_grid):
    params = {
        'score_min': score_min, 'ma_track': ma_track,
        'partial_day': partial_day, 'partial_pct': partial_pct,
        'max_positions': max_pos, 'atr_stop_mul': atr_stop
    }
    r = run_param_backtest(all_candles, params)
    if r: results.append(r)
    if (i+1) % 50 == 0:
        top = sorted(results, key=lambda x: x['sharpe'], reverse=True)[:3]
        print(f"  进度 {i+1}/{len(param_grid)} | Top3 Sharpe: {[(x['sharpe'],x['total_return']) for x in top]}")

# 排名
results.sort(key=lambda x: x['sharpe'], reverse=True)
print(f"\n{'='*60}")
print("📊 TOP 20 参数组合 (按夏普排名)")
print(f"{'='*60}")
print(f"{'得分':>4} {'MA':>3} {'平仓日':>5} {'比例':>4} {'持仓':>4} {'ATR':>4} | {'收益':>7} {'夏普':>5} {'回撤':>5} {'交易':>4} {'胜率':>4} {'盈比':>5}")
print("-"*70)
for r in results[:20]:
    p = r['params']
    print(f"{p['score_min']:>4} {p['ma_track']:>3} {p['partial_day']:>5} {p['partial_pct']:>4} {p['max_positions']:>4} {p['atr_stop_mul']:>4} | {r['total_return']:>6.1f}% {r['sharpe']:>4.1f} {r['max_dd']:>4.1f}% {r['trades']:>4} {r['win_rate']:>4.1f}% {r['profit_factor']:>5.1f}")

# 保存
out = {'date': '2026-06-29', 'top': results[:50], 'baseline': next((r for r in results
    if r['params'] == {'score_min':20,'ma_track':10,'partial_day':5,'partial_pct':0.3,'max_positions':5,'atr_stop_mul':1.0}), None)}
with open('reports/qullamaggie/phase0_param_scan.json', 'w') as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(f"\n📄 结果已保存: reports/qullamaggie/phase0_param_scan.json")
