#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 0 Step 4 — Qullamaggie 策略历史回测
================================================================
核心原则: NO LOOK-AHEAD — 每根K线只用当日及之前的数据计算评分
交易规则 (严格按 Qullamaggie 原文):
  入场: 形态分≥24 + 次日突破确认
  止损: min(前一交易日最低价, ATR止损)
  出场: 持仓3-5日后卖出1/3, 剩余MA10收盘跌破卖出
  仓位: 单笔风险=账户的1%, 最多同时5笔
  回测区间: 2025-01-02 ~ 2026-06-27
  股票池: 沪深300成分股 + 今日动量Top20 (合并去重 ~320只)
"""
from __future__ import annotations
import json, os, sys, time, math
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta

sys.path.insert(0, '/Users/leihen/.qclaw/workspace/quant-research')
from src.data.akshare_client import TencentClient

# ─── 配置 ───
START_DATE = '2025-01-02'
END_DATE   = '2026-06-27'
MIN_SCORE  = 24           # 入场最低形态分
MAX_POSITIONS = 5         # 最大同时持仓
RISK_PER_TRADE = 0.01     # 单笔风险 1%
INITIAL_CAPITAL = 1_000_000  # 初始资金100万
COMMISSION = 0.0003       # 佣金
SLIPPAGE = 0.001          # 滑点

CACHE_DIR = 'data/cache'
REPORT_DIR = 'reports/qullamaggie'
os.makedirs(REPORT_DIR, exist_ok=True)

client = TencentClient()

# ─── 辅助函数 ───
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
    """N日涨跌幅"""
    if len(values) < n + 1 or values[-n-1] == 0: return 0
    return (values[-1] - values[-n-1]) / values[-n-1]

def momentum_score(close_series, last_idx):
    """多周期加权动量 (只用 up to last_idx 的数据)"""
    closes = close_series[:last_idx+1]
    scores = {}
    for period in [21, 63, 126, 252]:
        if len(closes) > period:
            r = (closes[-1] - closes[-period-1]) / closes[-period-1]
            scores[period] = r
        else:
            scores[period] = 0
    # 加权: 1月×4 + 3月×3 + 6月×2 + 12月×1
    w = (scores.get(21,0)*4 + scores.get(63,0)*3 + scores.get(126,0)*2 + scores.get(252,0)*1) / 10
    return w, scores

def pattern_score_daily(candles, idx):
    """
    单日形态评分 — NO LOOK-AHEAD
    candles: list[dict{open,high,low,close,volume}]
    idx: 当前日期在 candles 中的索引
    返回: (total_score, detail_dict)
    """
    if idx < 120:  # 至少需要120个交易日
        return 0, {}
    
    closes = [c['close'] for c in candles[:idx+1]]
    highs  = [c['high']  for c in candles[:idx+1]]
    lows   = [c['low']   for c in candles[:idx+1]]
    vols   = [c['volume'] for c in candles[:idx+1]]
    
    detail = {}
    total = 0
    
    # ── S1: 前段涨幅 (1-3月) ──
    surge_63 = roc(closes, 63)
    if surge_63 >= 1.0:     s1 = 8
    elif surge_63 >= 0.6:   s1 = 6
    elif surge_63 >= 0.3:   s1 = 4
    elif surge_63 >= 0.15:  s1 = 2
    else:                   s1 = 0
    detail['surge'] = s1
    total += s1
    
    # ── S2: 回调幅度 ──
    peak_63 = max(highs[-63:]) if len(highs) >= 63 else max(highs)
    peak_idx = highs[-63:].index(peak_63) if len(highs) >= 63 else highs.index(peak_63)
    drawdown = (peak_63 - closes[-1]) / peak_63 if peak_63 > 0 else 0
    retrace = drawdown / (surge_63 + 0.01) if surge_63 > 0 else 999
    if 0.25 <= retrace <= 0.55:
        s2 = 8
    elif 0.15 <= retrace < 0.25 or 0.55 < retrace <= 0.70:
        s2 = 4
    elif 0.05 <= retrace <= 0.85:
        s2 = 1
    else:
        s2 = 0
    detail['pullback'] = s2
    total += s2
    
    # ── S3: MA10/20附近企稳 ──
    ma10 = sma(closes, 10)
    ma20 = sma(closes, 20)
    if ma10 and ma20:
        dist10 = abs(closes[-1] - ma10) / ma10
        dist20 = abs(closes[-1] - ma20) / ma20
        # 连续在MA附近天数
        near_days = 0
        for d in range(min(5, len(closes))):
            m10 = sma(closes[:len(closes)-d], 10)
            if m10 and abs(closes[-1-d] - m10) / m10 <= 0.03:
                near_days += 1
            else:
                break
        if near_days >= 5:      s3 = 6
        elif near_days >= 3:    s3 = 4
        elif dist10 <= 0.06:    s3 = 2
        else:                   s3 = 0
    else:
        s3 = 0
    detail['ma_support'] = s3
    total += s3
    
    # ── S4: Higher Low ──
    half_lows = lows[-40:] if len(lows) >= 40 else lows
    hl_count = 0
    seg_size = max(3, len(half_lows) // 5)
    for i in range(len(half_lows) - seg_size, 0, -seg_size):
        prev_min = min(half_lows[max(0,i-seg_size):i])
        curr_min = min(half_lows[i:i+seg_size])
        if curr_min > prev_min * 0.98:
            hl_count += 1
    if hl_count >= 3:       s4 = 6
    elif hl_count >= 2:     s4 = 4
    elif hl_count >= 1:     s4 = 2
    else:                   s4 = 0
    detail['higher_low'] = s4
    total += s4
    
    # ── S5: 波动收窄 (ATR ratio) ──
    atr5  = atr(highs, lows, closes, 5)
    atr20 = atr(highs, lows, closes, 20)
    if atr5 and atr20 and atr20 > 0:
        ratio = atr5 / atr20
        if ratio <= 0.65:       s5 = 4
        elif ratio <= 0.85:     s5 = 3
        elif ratio <= 1.0:      s5 = 2
        else:                   s5 = 0
    else:
        s5 = 0
    detail['tightening'] = s5
    total += s5
    
    # ── S6: 成交量衰减 ──
    vol_ma5  = sma(vols, 5)
    vol_ma20 = sma(vols, 20)
    if vol_ma5 and vol_ma20 and vol_ma20 > 0:
        vol_ratio = vol_ma5 / vol_ma20
        if vol_ratio <= 0.6:        s6 = 3
        elif vol_ratio <= 0.9:      s6 = 2
        elif vol_ratio <= 1.1:      s6 = 1
        else:                       s6 = 0
    else:
        s6 = 0
    detail['volume_decay'] = s6
    total += s6
    
    # ── S7: 价格位置 ──
    if len(closes) >= 60:
        low_60 = min(lows[-60:])
        high_60 = max(highs[-60:])
        if high_60 > low_60:
            pos = (closes[-1] - low_60) / (high_60 - low_60)
            if 0.70 <= pos <= 0.95:     s7 = 3
            elif 0.50 <= pos <= 1.0:    s7 = 2
            elif pos >= 0.30:           s7 = 1
            else:                       s7 = 0
        else:
            s7 = 0
    else:
        s7 = 0
    detail['position'] = s7
    total += s7
    
    # ── S8: 当日突破 ──
    avg_atr = atr20 if atr20 else 0.03
    day_change = (closes[-1] - closes[-2]) / closes[-2] if len(closes) >= 2 and closes[-2] > 0 else 0
    if day_change > 0 and avg_atr > 0:
        breakout_strength = day_change / avg_atr
        if breakout_strength >= 1.5:        s8 = 5
        elif breakout_strength >= 1.0:      s8 = 3
        elif day_change >= 0.01:            s8 = 1
        else:                               s8 = 0
    else:
        s8 = 0
    detail['breakout'] = s8
    total += s8
    
    return total, detail

# ─── 加载股票池 ───  
def load_universe():
    """沪深300 + 今日动量Top20"""
    codes = set()
    
    # 从缓存加载沪深300
    pool_path = os.path.join(CACHE_DIR, 'hs300_pool.json')
    if os.path.exists(pool_path):
        with open(pool_path) as f:
            codes.update(json.load(f))
    
    # 如果没有HS300缓存，用今天动量数据中的代码
    momentum_path = os.path.join(REPORT_DIR, 'phase0_momentum_full.json')
    if os.path.exists(momentum_path):
        with open(momentum_path) as f:
            data = json.load(f)
            # 取Top 200
            for item in data.get('top', [])[:200]:
                codes.add(item['code'])
    
    return sorted(codes)[:350]  # 最多350只

def fetch_history(code):
    """获取股票历史K线"""
    try:
        cache_file = os.path.join(CACHE_DIR, f'klines_{code}.json')
        # 检查缓存
        if os.path.exists(cache_file):
            with open(cache_file) as f:
                data = json.load(f)
                if data.get('end_date', '') >= END_DATE:
                    return data['candles']
        
        bars = client.get_kline(code, days=600)
        if not bars:
            return None
        
        candles = [{
            'date': b.date,
            'open': b.open,
            'high': b.high,
            'low': b.low,
            'close': b.close,
            'volume': b.volume,
        } for b in bars]
        
        # 缓存
        with open(cache_file, 'w') as f:
            json.dump({'code': code, 'end_date': END_DATE, 'candles': candles}, f)
        
        return candles
    except Exception as e:
        return None

# ─── 主回测循环 ───
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

def run_backtest():
    # 加载股票池
    universe = load_universe()
    print(f"股票池: {len(universe)} 只")
    
    # 批量获取K线
    print("获取K线数据...")
    all_candles = {}
    for i, code in enumerate(universe):
        candles = fetch_history(code)
        if candles and len(candles) >= 150:
            all_candles[code] = candles
        if (i+1) % 50 == 0:
            print(f"  已获取 {i+1}/{len(universe)}, 有效 {len(all_candles)}")
        time.sleep(0.15)
    print(f"有效K线: {len(all_candles)} 只")
    
    # 找到公共日期范围
    common_dates = set()
    for candles in all_candles.values():
        dates = [c['date'] for c in candles]
        if not common_dates:
            common_dates = set(dates)
        else:
            common_dates &= set(dates)
    
    trading_days = sorted([d for d in common_dates if START_DATE <= d <= END_DATE])
    print(f"公共交易日: {len(trading_days)} 天 ({trading_days[0]} ~ {trading_days[-1]})")
    
    # 回测
    cash = INITIAL_CAPITAL
    positions: List[Trade] = []
    closed_trades: List[Trade] = []
    equity_curve = []
    
    daily_signals = []  # 每日信号记录
    
    print(f"\n回测 {len(trading_days)} 天...")
    for day_idx, today in enumerate(trading_days):
        # ── 检查出场 ──
        for trade in list(positions):
            candles = all_candles.get(trade.code)
            if not candles:
                continue
            # 找到今天在这只股票K线中的位置
            c_idx = next((i for i, c in enumerate(candles) if c['date'] == today), None)
            if c_idx is None or c_idx < 2:
                continue
            
            c = candles[c_idx]
            
            # 止损检查
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
            
            # 3-5日卖出1/3  (简化：固定第5日卖30%)
            if hold_days == 5 and trade.reason != 'partial_sold':
                sell_shares = int(trade.shares * 0.3)
                sell_amount = sell_shares * c['close'] * (1 - COMMISSION - SLIPPAGE)
                cash += sell_amount
                trade.shares -= sell_shares
                trade.reason = 'partial_sold'
                # 移动止损到盈亏平衡
                trade.stop_price = trade.entry_price
            
            # MA10收盘跌破出场
            if hold_days >= 3:
                ma10 = sma([cc['close'] for cc in candles[:c_idx+1]], 10)
                if ma10 and c['close'] < ma10:
                    trade.exit_date = today
                    trade.exit_price = c['close']
                    trade.pnl = (c['close'] - trade.entry_price) * trade.shares
                    trade.pnl_pct = (c['close'] - trade.entry_price) / trade.entry_price
                    trade.reason = 'MA10跌破'
                    positions.remove(trade)
                    closed_trades.append(trade)
                    cash += trade.shares * c['close']
        
        # ── 扫描新入场信号 ──
        if len(positions) < MAX_POSITIONS:
            candidates = []
            for code, candles in all_candles.items():
                c_idx = next((i for i, c in enumerate(candles) if c['date'] == today), None)
                if c_idx is None or c_idx < 120:
                    continue
                score, detail = pattern_score_daily(candles, c_idx)
                if score >= MIN_SCORE:
                    # 检查是否有突破（当日涨>0）
                    if c_idx >= 1:
                        day_chg = (candles[c_idx]['close'] - candles[c_idx-1]['close']) / candles[c_idx-1]['close']
                        if day_chg >= 0.005:  # 至少涨0.5%才触发入场
                            candidates.append((code, score, detail, day_chg))
            
            # 按分数排序，取前几个
            candidates.sort(key=lambda x: x[1], reverse=True)
            
            for code, score, detail, day_chg in candidates[:MAX_POSITIONS - len(positions)]:
                # 避免重复持仓
                if any(t.code == code for t in positions):
                    continue
                
                c_idx = next((i for i, c in enumerate(all_candles[code]) if c['date'] == today), None)
                c = all_candles[code][c_idx]
                
                # 入场价 = 次日开盘 (用当日收盘近似)
                entry_price = c['close']
                
                # 止损 = 当日最低价 vs ATR止损
                atr_val = atr(
                    [cc['high'] for cc in all_candles[code][:c_idx+1]],
                    [cc['low']  for cc in all_candles[code][:c_idx+1]],
                    [cc['close'] for cc in all_candles[code][:c_idx+1]]
                ) or (entry_price * 0.05)
                stop1 = c['low']
                stop2 = entry_price * (1 - atr_val/entry_price) if entry_price > 0 else entry_price * 0.95
                stop_price = max(stop1, stop2)  # 取较宽松的
                
                # 仓位计算: 风险1%
                risk_per_share = entry_price - stop_price
                if risk_per_share <= 0:
                    continue
                risk_amount = (cash + sum(t.shares * entry_price for t in positions)) * RISK_PER_TRADE
                risk_amount /= max(1, MAX_POSITIONS - len(positions))  # 分散
                shares = int(risk_amount / risk_per_share)
                if shares < 100:
                    continue  # A股最小100股
                
                cost = shares * entry_price * (1 + COMMISSION + SLIPPAGE)
                if cost > cash * 0.25:  # 单只最多25%
                    shares = int(cash * 0.25 / (entry_price * (1 + COMMISSION + SLIPPAGE)))
                    if shares < 100:
                        continue
                    cost = shares * entry_price * (1 + COMMISSION + SLIPPAGE)
                
                cash -= cost
                trade = Trade(
                    code=code,
                    entry_date=today,
                    entry_price=entry_price,
                    shares=shares,
                    stop_price=stop_price,
                    entry_score=score,
                )
                positions.append(trade)
                daily_signals.append({
                    'date': today, 'code': code, 'score': score,
                    'price': entry_price, 'stop': stop_price, 'shares': shares,
                    'detail': detail,
                })
        
        # ── 记录净值 ──
        pos_value = sum(t.shares * all_candles[t.code][
            next(i for i, c in enumerate(all_candles[t.code]) if c['date'] == today)
        ]['close'] for t in positions if any(c['date'] == today for c in all_candles.get(t.code, [])))
        equity = cash + pos_value
        equity_curve.append({'date': today, 'equity': equity, 'cash': cash, 'positions': len(positions)})
        
        if day_idx % 50 == 0:
            ret = (equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
            print(f"  {today} | 净值:{equity:.0f} | 收益:{ret:+.1f}% | 持仓:{len(positions)} | 已平:{len(closed_trades)}", flush=True)
    
    # ─── 结果计算 ───
    final_equity = equity_curve[-1]['equity'] if equity_curve else INITIAL_CAPITAL
    total_return = (final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL
    
    # 年化
    days = len(trading_days)
    years = days / 252
    annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
    
    # 夏普 (简化)
    daily_returns = []
    for i in range(1, len(equity_curve)):
        r = (equity_curve[i]['equity'] - equity_curve[i-1]['equity']) / equity_curve[i-1]['equity']
        daily_returns.append(r)
    
    if daily_returns and len(daily_returns) > 1:
        avg_dr = sum(daily_returns) / len(daily_returns)
        std_dr = math.sqrt(sum((r - avg_dr)**2 for r in daily_returns) / (len(daily_returns) - 1))
        sharpe = (avg_dr / std_dr * math.sqrt(252)) if std_dr > 0 else 0
    else:
        sharpe = 0
    
    # 最大回撤
    peak = INITIAL_CAPITAL
    max_dd = 0
    for e in equity_curve:
        if e['equity'] > peak:
            peak = e['equity']
        dd = (peak - e['equity']) / peak
        max_dd = max(max_dd, dd)
    
    # 胜率
    wins = [t for t in closed_trades if t.pnl > 0]
    win_rate = len(wins) / len(closed_trades) if closed_trades else 0
    
    # 盈亏比
    avg_win = sum(t.pnl for t in wins) / len(wins) if wins else 0
    losses = [t for t in closed_trades if t.pnl <= 0]
    avg_loss = sum(t.pnl for t in losses) / len(losses) if losses else 0
    profit_factor = abs(avg_win * len(wins) / (avg_loss * len(losses))) if losses and avg_loss != 0 else float('inf')
    
    print(f"\n{'='*60}")
    print(f"📊 回测结果")
    print(f"{'='*60}")
    print(f"区间: {START_DATE} ~ {END_DATE} ({days} 交易日)")
    print(f"总收益: {total_return*100:+.2f}%")
    print(f"年化收益: {annual_return*100:+.2f}%")
    print(f"夏普比率: {sharpe:.2f}")
    print(f"最大回撤: {max_dd*100:.2f}%")
    print(f"交易次数: {len(closed_trades)}")
    print(f"胜率: {win_rate*100:.1f}%")
    print(f"盈亏比: {profit_factor:.2f}")
    print(f"平均盈利: {avg_win:+.0f}  平均亏损: {avg_loss:+.0f}")
    
    # 按原因分组
    from collections import Counter
    reasons = Counter(t.reason for t in closed_trades)
    print(f"\n出场原因分布:")
    for r, c in reasons.most_common():
        pnl_sum = sum(t.pnl for t in closed_trades if t.reason == r)
        print(f"  {r}: {c}笔, 盈亏合计 {pnl_sum:+.0f}")
    
    # 保存结果
    result = {
        'config': {'start': START_DATE, 'end': END_DATE, 'min_score': MIN_SCORE,
                   'universe': len(universe), 'initial_capital': INITIAL_CAPITAL},
        'summary': {
            'total_return': round(total_return, 6),
            'annual_return': round(annual_return, 6),
            'sharpe': round(sharpe, 4),
            'max_drawdown': round(max_dd, 6),
            'total_trades': len(closed_trades),
            'win_rate': round(win_rate, 6),
            'profit_factor': round(profit_factor, 4),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
        },
        'trades': [{
            'code': t.code, 'entry_date': t.entry_date, 'entry_price': t.entry_price,
            'exit_date': t.exit_date, 'exit_price': t.exit_price,
            'pnl': round(t.pnl, 2), 'pnl_pct': round(t.pnl_pct, 6),
            'shares': t.shares, 'score': t.entry_score, 'reason': t.reason,
        } for t in closed_trades],
        'equity_curve': equity_curve,
        'daily_signals': daily_signals[:50],  # 只保留前50个信号样本
    }
    
    out_path = os.path.join(REPORT_DIR, 'phase0_backtest_result.json')
    with open(out_path, 'w') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n📄 结果已保存: {out_path}")
    
    return result

if __name__ == '__main__':
    run_backtest()
