#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 0 Step 5 — Qullamaggie 回测 v2 (修正版)
================================================================
修正:
  1. 入场: 次日开盘价 (消除正向偏差)
  2. 股票池: 全量HS300重试 + 动量Top200
  3. 分段测试: 2025牛 + 2024震荡 + 2022熊 三段独立回测
"""
from __future__ import annotations
import json, os, sys, time, math
from dataclasses import dataclass
from typing import List, Dict, Optional
from collections import Counter

sys.path.insert(0, '/Users/leihen/.qclaw/workspace/quant-research')
from src.data.akshare_client import TencentClient

# ─── 配置 ───
MIN_SCORE  = 24
MAX_POSITIONS = 5
RISK_PER_TRADE = 0.01
INITIAL_CAPITAL = 1_000_000
COMMISSION = 0.0003
SLIPPAGE = 0.001

CACHE_DIR = 'data/cache'
REPORT_DIR = 'reports/qullamaggie'
os.makedirs(REPORT_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

client = TencentClient()

# ─── 辅助函数 (同前) ───
def sma(values, n):
    if len(values) < n: return None
    return sum(values[-n:]) / n

def ema(values, n):
    if len(values) < n: return None
    k = 2 / (n + 1)
    ema_val = values[0]
    for v in values[1:]:
        ema_val = v * k + ema_val * (1 - k)
    return ema_val

def atr(highs, lows, closes, n=14):
    if len(closes) < n + 1: return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs.append(tr)
    if len(trs) < n: return None
    return ema(trs[-n:], n)

def roc(values, n):
    if len(values) < n + 1 or values[-n-1] == 0: return 0
    return (values[-1] - values[-n-1]) / values[-n-1]

def pattern_score_daily(candles, idx):
    """单日形态评分 — 只用 idx 及之前的数据"""
    if idx < 120: return 0, {}
    closes = [c['close'] for c in candles[:idx+1]]
    highs  = [c['high']  for c in candles[:idx+1]]
    lows   = [c['low']   for c in candles[:idx+1]]
    vols   = [c['volume'] for c in candles[:idx+1]]
    
    detail = {}; total = 0
    
    # S1: 前段涨幅 (3月)
    surge_63 = roc(closes, 63)
    if   surge_63 >= 1.0:  s1 = 8
    elif surge_63 >= 0.6:  s1 = 6
    elif surge_63 >= 0.3:  s1 = 4
    elif surge_63 >= 0.15: s1 = 2
    else:                  s1 = 0
    detail['surge'] = s1; total += s1
    
    # S2: 回调幅度
    peak_63 = max(highs[-63:]) if len(highs) >= 63 else max(highs)
    drawdown = (peak_63 - closes[-1]) / peak_63 if peak_63 > 0 else 0
    retrace = drawdown / (surge_63 + 0.01) if surge_63 > 0 else 999
    if   0.25 <= retrace <= 0.55:  s2 = 8
    elif 0.15 <= retrace < 0.25 or 0.55 < retrace <= 0.70: s2 = 4
    elif 0.05 <= retrace <= 0.85:  s2 = 1
    else:                          s2 = 0
    detail['pullback'] = s2; total += s2
    
    # S3: MA10附近企稳
    ma10 = sma(closes, 10)
    if ma10:
        near_days = 0
        for d in range(min(5, len(closes))):
            m10 = sma(closes[:len(closes)-d], 10)
            if m10 and abs(closes[-1-d] - m10) / m10 <= 0.03:
                near_days += 1
            else: break
        if   near_days >= 5:  s3 = 6
        elif near_days >= 3:  s3 = 4
        elif abs(closes[-1]-ma10)/ma10 <= 0.06: s3 = 2
        else: s3 = 0
    else: s3 = 0
    detail['ma_support'] = s3; total += s3
    
    # S4: Higher Low
    half_lows = lows[-40:] if len(lows) >= 40 else lows
    hl_count = 0
    seg_size = max(3, len(half_lows) // 5)
    for i in range(len(half_lows) - seg_size, 0, -seg_size):
        prev_min = min(half_lows[max(0,i-seg_size):i])
        curr_min = min(half_lows[i:i+seg_size])
        if curr_min > prev_min * 0.98: hl_count += 1
    if   hl_count >= 3: s4 = 6
    elif hl_count >= 2: s4 = 4
    elif hl_count >= 1: s4 = 2
    else:               s4 = 0
    detail['higher_low'] = s4; total += s4
    
    # S5: 波动收窄
    atr5  = atr(highs, lows, closes, 5)
    atr20 = atr(highs, lows, closes, 20)
    if atr5 and atr20 and atr20 > 0:
        ratio = atr5 / atr20
        if   ratio <= 0.65: s5 = 4
        elif ratio <= 0.85: s5 = 3
        elif ratio <= 1.0:  s5 = 2
        else:               s5 = 0
    else: s5 = 0
    detail['tightening'] = s5; total += s5
    
    # S6: 成交量衰减
    vol_ma5  = sma(vols, 5)
    vol_ma20 = sma(vols, 20)
    if vol_ma5 and vol_ma20 and vol_ma20 > 0:
        ratio = vol_ma5 / vol_ma20
        if   ratio <= 0.6:  s6 = 3
        elif ratio <= 0.9:  s6 = 2
        elif ratio <= 1.1:  s6 = 1
        else:               s6 = 0
    else: s6 = 0
    detail['volume_decay'] = s6; total += s6
    
    # S7: 价格位置
    if len(closes) >= 60:
        low_60, high_60 = min(lows[-60:]), max(highs[-60:])
        if high_60 > low_60:
            pos = (closes[-1] - low_60) / (high_60 - low_60)
            if   0.70 <= pos <= 0.95: s7 = 3
            elif 0.50 <= pos <= 1.0:  s7 = 2
            elif pos >= 0.30:         s7 = 1
            else:                     s7 = 0
        else: s7 = 0
    else: s7 = 0
    detail['position'] = s7; total += s7
    
    # S8: 突破 (不需要当日突破，只需次日确认 → 此评分用前日数据)
    atr20_val = atr20 if atr20 else 0.03
    day_chg = (closes[-1] - closes[-2]) / closes[-2] if len(closes) >= 2 and closes[-2] > 0 else 0
    if day_chg > 0 and atr20_val > 0:
        bs = day_chg / atr20_val
        if   bs >= 1.5:  s8 = 5
        elif bs >= 1.0:  s8 = 3
        elif day_chg >= 0.01: s8 = 1
        else: s8 = 0
    else: s8 = 0
    detail['breakout'] = s8; total += s8
    
    return total, detail

# ─── 数据加载 ───
def load_full_hs300():
    """全量获取沪深300只K线，重试失败的"""
    pool_file = os.path.join(CACHE_DIR, 'hs300_pool.json')
    if not os.path.exists(pool_file):
        import requests
        url = 'https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=500&po=1&np=1&fltt=2&invt=2&fid=f12&fs=b:MK0201&fields=f12,f14'
        r = requests.get(url, headers={'User-Agent':'Mozilla/5.0','Referer':'https://quote.eastmoney.com/'}, timeout=15)
        data = r.json()
        codes = []
        for item in data.get('data',{}).get('diff',[]):
            code = item['f12']
            name = item.get('f14','')
            mkt = 'sh' if code.startswith('6') else 'sz'
            codes.append((f'{mkt}{code}', name))
        with open(pool_file, 'w') as f:
            json.dump(codes, f)
        print(f"HS300 成分股: {len(codes)} 只")
    else:
        with open(pool_file) as f:
            codes = json.load(f)
        print(f"HS300 成分股 (缓存): {len(codes)} 只")
    return codes

def fetch_history(code):
    """获取K线缓存或下载，重试3次"""
    cache_file = os.path.join(CACHE_DIR, f'klines_{code}.json')
    if os.path.exists(cache_file):
        with open(cache_file) as f:
            data = json.load(f)
            if len(data.get('candles', [])) >= 500:
                return data['candles']
    
    for retry in range(3):
        try:
            bars = client.get_kline(code, days=800)
            if not bars or len(bars) < 200:
                time.sleep(0.5)
                continue
            candles = [{
                'date': b.date, 'open': b.open, 'high': b.high,
                'low': b.low, 'close': b.close, 'volume': b.volume,
            } for b in bars]
            with open(cache_file, 'w') as f:
                json.dump({'code': code, 'candles': candles}, f)
            return candles
        except Exception as e:
            time.sleep(1)
    return None

# ─── 回测引擎 ───
@dataclass
class Trade:
    code: str
    entry_date: str
    entry_price: float
    shares: int
    stop_price: float
    entry_score: int
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    reason: str = ''

def run_backtest_v2(start_date, end_date, label, all_candles):
    """修正版回测：次日开盘入场"""
    # Union all stock dates for holiday-tolerant calendar
    all_dates = set()
    for candles in all_candles.values(): all_dates |= set(c["date"] for c in candles)
    trading_days = sorted([d for d in all_dates if start_date <= d <= end_date])
    if len(trading_days) < 50:
        print(f"  {label}: 交易日不足 ({len(trading_days)}), 跳过")
        return None
    
    cash = INITIAL_CAPITAL
    positions: List[Trade] = []
    closed_trades: List[Trade] = []
    equity_curve = []
    
    # 按股票索引缓存
    date_index = {code: {c['date']: i for i, c in enumerate(candles)} 
                  for code, candles in all_candles.items()}
    
    for day_idx, today in enumerate(trading_days):
        # ═══ 1. 检查出场 ═══
        for trade in list(positions):
            if trade.code not in date_index or today not in date_index[trade.code]:
                continue
            c_idx = date_index[trade.code][today]
            candles = all_candles[trade.code]
            c = candles[c_idx]
            
            # 止损
            if c['low'] <= trade.stop_price:
                trade.exit_date = today
                trade.exit_price = trade.stop_price
                trade.pnl = (trade.stop_price - trade.entry_price) * trade.shares
                trade.pnl_pct = (trade.stop_price - trade.entry_price) / trade.entry_price
                trade.reason = '止损'
                positions.remove(trade)
                closed_trades.append(trade)
                cash += trade.shares * trade.stop_price
                continue
            
            # 持仓天数
            hold_days = sum(1 for d in trading_days if trade.entry_date < d <= today)
            
            # 第5日卖30%
            if hold_days == 5 and trade.reason != 'partial_sold':
                sell_shares = int(trade.shares * 0.3)
                sell_amount = sell_shares * c['close'] * (1 - COMMISSION - SLIPPAGE)
                cash += sell_amount
                trade.shares -= sell_shares
                trade.reason = 'partial_sold'
                trade.stop_price = trade.entry_price  # 移动止损至盈亏平衡
            
            # MA10跌破
            if hold_days >= 3:
                closes = [cc['close'] for cc in candles[:c_idx+1]]
                ma10 = sma(closes, 10)
                if ma10 and c['close'] < ma10:
                    trade.exit_date = today
                    trade.exit_price = c['close']
                    trade.pnl = (c['close'] - trade.entry_price) * trade.shares
                    trade.pnl_pct = (c['close'] - trade.entry_price) / trade.entry_price
                    trade.reason = 'MA10跌破'
                    positions.remove(trade)
                    closed_trades.append(trade)
                    cash += trade.shares * c['close']
        
        # ═══ 2. 扫描信号 (使用昨天数据) ═══
        if len(positions) < MAX_POSITIONS and day_idx >= 1:
            prev_day = trading_days[day_idx - 1]
            candidates = []
            
            for code, candles in all_candles.items():
                if prev_day not in date_index[code]:
                    continue
                c_idx = date_index[code][prev_day]
                if c_idx < 120:
                    continue
                
                # ⭐ 关键修正: 用前一日收盘数据评分
                score, detail = pattern_score_daily(candles, c_idx)
                if score < MIN_SCORE:
                    continue
                
                # 是否已有该股持仓
                if any(t.code == code for t in positions):
                    continue
                
                # 突破确认: 今日开盘 > 昨日收盘 × 1.005
                if today in date_index[code]:
                    t_idx = date_index[code][today]
                    prev_close = candles[c_idx]['close']
                    today_open = candles[t_idx]['open']
                    if today_open <= prev_close * 1.005:  # 突破验证
                        continue
                    # ⭐ 入场价 = 今日开盘价 (修正正向偏差)
                    entry_price = today_open
                else:
                    continue
                
                candidates.append((code, score, detail, entry_price, c_idx, today))
            
            candidates.sort(key=lambda x: x[1], reverse=True)
            
            for code, score, detail, entry_price, c_idx, today in candidates[:MAX_POSITIONS - len(positions)]:
                candles = all_candles[code]
                
                # 止损设置
                atr_val = atr(
                    [cc['high'] for cc in candles[:c_idx+1]],
                    [cc['low']  for cc in candles[:c_idx+1]],
                    [cc['close'] for cc in candles[:c_idx+1]]
                ) or (entry_price * 0.05)
                
                prev_low = candles[c_idx]['low']
                stop1 = prev_low
                stop2 = entry_price * (1 - atr_val/entry_price) if entry_price > 0 else entry_price * 0.95
                stop_price = max(stop1, stop2)
                
                # 仓位
                risk_per_share = entry_price - stop_price
                if risk_per_share <= 0: continue
                total_equity = cash + sum(t.shares * all_candles[t.code][
                    date_index[t.code].get(today, 0)
                ]['close'] for t in positions if t.code in date_index and today in date_index[t.code])
                risk_amount = total_equity * RISK_PER_TRADE / min(MAX_POSITIONS - len(positions) + 1, 3)
                shares = int(risk_amount / risk_per_share)
                if shares < 100: continue
                
                cost = shares * entry_price * (1 + COMMISSION + SLIPPAGE)
                max_cost = cash * 0.25
                if cost > max_cost:
                    shares = int(max_cost / (entry_price * (1 + COMMISSION + SLIPPAGE)))
                    if shares < 100: continue
                    cost = shares * entry_price * (1 + COMMISSION + SLIPPAGE)
                
                cash -= cost
                positions.append(Trade(code=code, entry_date=today, entry_price=entry_price,
                                        shares=shares, stop_price=stop_price, entry_score=score))
        
        # ═══ 3. 记录净值 ═══
        pos_value = 0
        for t in positions:
            if t.code in date_index and today in date_index[t.code]:
                t_idx = date_index[t.code][today]
                pos_value += t.shares * all_candles[t.code][t_idx]['close']
        equity = cash + pos_value
        equity_curve.append({'date': today, 'equity': equity, 'cash': cash, 'positions': len(positions)})
        
        if day_idx % 80 == 0:
            ret = (equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
            print(f"  [{label}] {today} | 净值:{equity:.0f} | 收益:{ret:+.1f}% | 持仓:{len(positions)} | 已平:{len(closed_trades)}", flush=True)
    
    # ─── 计算指标 ───
    final_equity = equity_curve[-1]['equity'] if equity_curve else INITIAL_CAPITAL
    total_return = (final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL
    
    days = len(trading_days)
    years = days / 252
    annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
    
    daily_returns = []
    for i in range(1, len(equity_curve)):
        r = (equity_curve[i]['equity'] - equity_curve[i-1]['equity']) / equity_curve[i-1]['equity']
        daily_returns.append(r)
    
    if daily_returns and len(daily_returns) > 1:
        avg_dr = sum(daily_returns) / len(daily_returns)
        std_dr = math.sqrt(sum((r - avg_dr)**2 for r in daily_returns) / max(len(daily_returns) - 1, 1))
        sharpe = (avg_dr / std_dr * math.sqrt(252)) if std_dr > 0 else 0
    else:
        sharpe = 0
    
    peak = INITIAL_CAPITAL
    max_dd = 0
    for e in equity_curve:
        if e['equity'] > peak: peak = e['equity']
        dd = (peak - e['equity']) / peak
        max_dd = max(max_dd, dd)
    
    wins = [t for t in closed_trades if t.pnl > 0]
    win_rate = len(wins) / len(closed_trades) if closed_trades else 0
    avg_win = sum(t.pnl for t in wins) / len(wins) if wins else 0
    losses = [t for t in closed_trades if t.pnl <= 0]
    avg_loss = sum(t.pnl for t in losses) / len(losses) if losses else 0
    profit_factor = abs(avg_win * len(wins) / (avg_loss * len(losses))) if losses and avg_loss != 0 else float('inf')
    
    reasons = Counter(t.reason for t in closed_trades)
    
    result = {
        'label': label, 'start': start_date, 'end': end_date,
        'days': days, 'stocks': len(all_candles),
        'total_return': round(total_return, 6),
        'annual_return': round(annual_return, 6),
        'sharpe': round(sharpe, 4),
        'max_drawdown': round(max_dd, 6),
        'total_trades': len(closed_trades),
        'win_rate': round(win_rate, 6),
        'profit_factor': round(profit_factor, 4),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'reasons': {r: c for r, c in reasons.most_common()},
        'reasons_pnl': {r: round(sum(t.pnl for t in closed_trades if t.reason == r), 2) for r in reasons},
    }
    
    # 打印摘要
    print(f"\n── {label} ──")
    print(f"  区间:{start_date}~{end_date}, {days}天, {len(all_candles)}只")
    print(f"  总收益:{total_return*100:+.1f}% 年化:{annual_return*100:+.1f}% 夏普:{sharpe:.2f} 回撤:{max_dd*100:.1f}%")
    print(f"  交易:{len(closed_trades)}笔 胜率:{win_rate*100:.1f}% 盈亏比:{profit_factor:.2f}")
    for r, c in reasons.most_common():
        pnl_sum = sum(t.pnl for t in closed_trades if t.reason == r)
        print(f"    {r}: {c}笔, 盈亏{'+' if pnl_sum>=0 else ''}{pnl_sum:,.0f}")
    
    return result

# ─── 主流程 ───
print("=" * 60)
print("Phase 0 v2 — 修正回测 (次日开盘入场 + 全量HS300 + 分段)")
print("=" * 60)

# 1. 数据加载
print("\n[1/3] 加载沪深300股票池...")
hs300 = load_full_hs300()

print("\n[2/3] 获取K线 (全量重试)...")
all_candles = {}
failures = []
for i, code in enumerate(hs300):
    candles = fetch_history(code)
    if candles and len(candles) >= 250:
        all_candles[code] = candles
    else:
        failures.append(code)
    if (i+1) % 50 == 0:
        print(f"  进度 {i+1}/{len(hs300)}, 有效 {len(all_candles)}, 失败 {len(failures)}")
    time.sleep(0.12)

print(f"\n有效K线: {len(all_candles)} 只")
if failures:
    pass
    print(f"K线不足 (<250): {len(failures)} 只")

# 2. 分段回测
print(f"\n[3/3] 分段回测...")
segments = [
    ('2022熊市', '2022-01-04', '2022-12-30'),
    ('2023震荡', '2023-01-03', '2023-12-29'),
    ('2024复苏', '2024-01-02', '2024-12-31'),
    ('2025牛',   '2025-01-02', '2026-06-26'),
]

results = []
for label, start, end in segments:
    res = run_backtest_v2(start, end, label, all_candles)
    if res:
        results.append(res)

# 3. 汇总
print(f"\n{'='*60}")
print(f"📊 分段对比总览")
print(f"{'='*60}")
print(f"{'区间':<12} {'天数':>5} {'收益':>10} {'年化':>10} {'夏普':>6} {'回撤':>8} {'交易':>5} {'胜率':>7} {'盈亏比':>6}")
for r in results:
    print(f"{r['label']:<12} {r['days']:>5} {r['total_return']*100:>+9.1f}% {r['annual_return']*100:>+9.1f}% "
          f"{r['sharpe']:>6.2f} {r['max_drawdown']*100:>7.1f}% {r['total_trades']:>5} "
          f"{r['win_rate']*100:>6.1f}% {r['profit_factor']:>5.2f}")

# 4. 保存
out_path = os.path.join(REPORT_DIR, 'phase0_backtest_v2.json')
with open(out_path, 'w') as f:
    json.dump({
        'config': {'min_score': MIN_SCORE, 'capital': INITIAL_CAPITAL,
                   'stocks_loaded': len(all_candles), 'stocks_failed': len(failures)},
        'pool_failures': [(c, n) for c, n in failures[:20]],
        'segments': results,
    }, f, ensure_ascii=False, indent=2)
print(f"\n📄 结果: {out_path}")
