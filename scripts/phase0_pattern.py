#!/usr/bin/env python3
"""
Qullamaggie Phase 0 — PatternScorer 形态评分器
基于官网原文规则: 前段大涨 → 回调⅓ → MA企稳 → Higher Low → 波动收紧 → 放量突破

评分权重 (从25张官网图反推):
  A1 前段涨幅 (30-100%+) [原文]        max 8分
  A2 回调幅度 (⅓前段涨幅)  [原文]      max 8分  
  A3 MA企稳 (MA10/20附近)  [原文]      max 6分
  A4 Higher Low (低点抬升)  [原文]     max 6分
  A5 波动收紧 (ATR收敛)     [原文]     max 6分
  A6 缩量 (成交衰减)         [推断]    max 4分
  A7 股价位置 (中高位)       [推断]    max 3分
  A8 突破形态               [原文]     max 5分  (v2加入: 近2日涨幅>ATR)
  ════════════════════════════════════
  TOTAL                                 max 46分
  通过阈值: ≥ 24分
"""
from __future__ import annotations
import json, os, sys, time, requests
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

HEADERS = {'Referer': 'https://finance.sina.com.cn/'}

@dataclass
class PatternResult:
    code: str; name: str; price: float
    total_score: int = 0
    # 子项
    s1_surge: int = 0      # 前段涨幅
    s2_pullback: int = 0   # 回调
    s3_ma_support: int = 0 # MA支撑
    s4_higher_low: int = 0 # Higher Low
    s5_tightening: int = 0 # 波动收紧
    s6_volume: int = 0     # 缩量
    s7_position: int = 0   # 股价位置
    s8_breakout: int = 0   # 突破信号
    details: list = field(default_factory=list)  # 诊断详情

def fetch_kline_data(code: str, days: int = 300) -> Tuple[List[float], List[float], List[float], List[float], List[float]]:
    """返回 (close, high, low, volume_amt, volume_qty)"""
    url = (f'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/'
           f'CN_MarketData.getKLineData?symbol={code}&scale=240&ma=no&datalen={days}')
    for _ in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            data = r.json()
            if not data or not isinstance(data, list): continue
            closes, highs, lows, amts, qtys = [], [], [], [], []
            for bar in data:
                try:
                    closes.append(float(bar['close']))
                    highs.append(float(bar['high']))
                    lows.append(float(bar['low']))
                    amts.append(float(bar['volume']) * float(bar['close']) / 1e8)
                    qtys.append(float(bar['volume']) / 1e6)
                except: pass
            return closes, highs, lows, amts, qtys
        except: time.sleep(0.5)
    return [], [], [], [], []

def sma(data, period):
    if len(data) < period: return 0
    return sum(data[-period:]) / period

def atr(highs, lows, closes, period=14):
    if len(closes) < period + 1: return 0
    trs = []
    for i in range(-period, 0):
        c_prev = closes[i-1]
        trs.append(max(highs[i]-lows[i], abs(highs[i]-c_prev), abs(lows[i]-c_prev)))
    return sum(trs) / len(trs)

def score_pattern(code: str, name: str) -> PatternResult:
    """核心形态评分算法"""
    closes, highs, lows, amts, qtys = fetch_kline_data(code, 300)
    if len(closes) < 200:
        return PatternResult(code=code, name=name, price=0, details=['K线不足200条'])
    
    price = closes[-1]
    result = PatternResult(code=code, name=name, price=price)
    details = []
    
    # ── A1 前段大涨 (1-3月) ──
    # 原文: "big move higher something in past 1-3 months, 30-100%+"
    lookbacks = [22, 44, 66]  # 1/2/3月
    max_gain = 0
    for lb in lookbacks:
        if len(closes) >= lb + 1:
            gain = (closes[-1] - closes[-lb]) / closes[-lb] * 100
            max_gain = max(max_gain, gain)
    
    if max_gain >= 100:
        result.s1_surge = 8; details.append(f'前段涨幅{max_gain:.0f}% → +8分')
    elif max_gain >= 60:
        result.s1_surge = 6; details.append(f'前段涨幅{max_gain:.0f}% → +6分')
    elif max_gain >= 30:
        result.s1_surge = 4; details.append(f'前段涨幅{max_gain:.0f}% → +4分')
    elif max_gain >= 15:
        result.s1_surge = 2; details.append(f'前段涨幅{max_gain:.0f}% → +2分')
    else:
        details.append(f'前段涨幅{max_gain:.0f}% → 0分(<15%)')
    
    # ── A2 回调 (回吐前段涨幅⅓) ──
    # 原文: "pull back maybe retracing about a third of the move"
    if len(closes) >= 66:
        high_66 = max(closes[-66:])
        high_idx = closes[-66:].index(high_66)
        # 从高点回撤了多少
        drawdown = (high_66 - price) / high_66 * 100
        # 回吐相对前段涨幅的比例
        front_gain_pct = (high_66 - closes[-67]) / closes[-67] * 100 if len(closes)>67 else 0
        retrace_ratio = drawdown / max(front_gain_pct, 0.01)
        
        if 0.25 <= retrace_ratio <= 0.45:
            result.s2_pullback = 8; details.append(f'回调{drawdown:.1f}%(回吐{retrace_ratio:.0%}前段) → +8分')
        elif 0.15 <= retrace_ratio <= 0.55:
            result.s2_pullback = 6; details.append(f'回调{drawdown:.1f}%(回吐{retrace_ratio:.0%}前段) → +6分')
        elif 0.10 <= retrace_ratio <= 0.66:
            result.s2_pullback = 4; details.append(f'回调{drawdown:.1f}%(回吐{retrace_ratio:.0%}前段) → +4分')
        else:
            details.append(f'回调{drawdown:.1f}%(回吐{retrace_ratio:.0%}) → 0分(不在⅓±15%范围)')
    
    # ── A3 MA企稳 (价格在MA10/20附近构建平台) ──
    # 原文: "price surfs the rising 10- and 20-day moving average"
    ma10 = sma(closes, 10)
    ma20 = sma(closes, 20)
    dist10 = abs(price - ma10) / ma10 * 100 if ma10 > 0 else 999
    dist20 = abs(price - ma20) / ma20 * 100 if ma20 > 0 else 999
    
    # 连续3天收盘在MA10±2%内
    ma10_band = sum(1 for c in closes[-5:] if abs(c - ma10)/ma10 < 0.03)
    
    if ma10_band >= 3 and dist10 < 2:
        result.s3_ma_support = 6; details.append(f'MA10企稳(连续{ma10_band}日±2%内) → +6分')
    elif ma10_band >= 2 and dist10 < 4:
        result.s3_ma_support = 4; details.append(f'MA10附近(距{dist10:.1f}%) → +4分')
    elif dist10 < 6:
        result.s3_ma_support = 2; details.append(f'MA10可及(距{dist10:.1f}%) → +2分')
    else:
        details.append(f'MA10距{dist10:.1f}% → 0分(>6%)')
    
    # ── A4 Higher Low (低点抬升) ──
    # 原文: "higher lows and tightening range in consolidation"
    if len(closes) >= 60:
        # 切三段，每段20天
        seg1_low = min(lows[-60:-40]) if len(lows)>=60 else price
        seg2_low = min(lows[-40:-20])
        seg3_low = min(lows[-20:])
        
        steps = 0
        if seg2_low > seg1_low: steps += 1
        if seg3_low > seg2_low: steps += 1
        
        if steps == 2:
            result.s4_higher_low = 6; details.append('Higher Low ×2段 → +6分')
        elif steps == 1:
            result.s4_higher_low = 3; details.append(f'Higher Low ×1段 → +3分')
        else:
            details.append(f'低点未抬升 → 0分')
    
    # ── A5 波动收紧 (ATR缩小) ──
    # 原文: "tightening range"
    atr5 = atr(highs, lows, closes, 5) if len(closes)>5 else 0
    atr20 = atr(highs, lows, closes, 20) if len(closes)>20 else 0
    ratio = atr5 / atr20 if atr20 > 0 else 999
    
    if ratio < 0.6:
        result.s5_tightening = 6; details.append(f'ATR5/ATR20={ratio:.2f}(极度收紧) → +6分')
    elif ratio < 0.8:
        result.s5_tightening = 4; details.append(f'ATR5/ATR20={ratio:.2f}(收紧中) → +4分')
    elif ratio < 1.0:
        result.s5_tightening = 2; details.append(f'ATR5/ATR20={ratio:.2f}(持平) → +2分')
    else:
        details.append(f'ATR5/ATR20={ratio:.2f}(扩张) → 0分')
    
    # ── A6 缩量 ──
    if len(amts) >= 20:
        amt5 = sum(amts[-5:]) / 5
        amt20 = sum(amts[-20:]) / 20
        vol_ratio = amt5 / amt20 if amt20 > 0 else 999
        
        if vol_ratio < 0.5:
            result.s6_volume = 4; details.append(f'近5日量/20日均={vol_ratio:.2f}(极缩量) → +4分')
        elif vol_ratio < 0.7:
            result.s6_volume = 3; details.append(f'近5日量/20日均={vol_ratio:.2f}(缩量) → +3分')
        elif vol_ratio < 0.9:
            result.s6_volume = 2; details.append(f'近5日量/20日均={vol_ratio:.2f}(小幅缩) → +2分')
        else:
            details.append(f'量比={vol_ratio:.2f} → 0分')
    
    # ── A7 股价位置 ──
    # 原文: 不能太高(超买风险)也不能太低(无动量)
    if len(closes) >= 250:
        pct_rank = sum(1 for c in closes[-250:] if c < price) / 250 * 100
        if 60 <= pct_rank <= 95:
            result.s7_position = 3; details.append(f'股价位于60日分位{pct_rank:.0f}%(中高位) → +3分')
        elif 50 <= pct_rank <= 97:
            result.s7_position = 2; details.append(f'股价分位{pct_rank:.0f}% → +2分')
        elif pct_rank > 40:
            result.s7_position = 1; details.append(f'股价分位{pct_rank:.0f}% → +1分')
        else:
            details.append(f'股价分位{pct_rank:.0f}% → 0分')
    
    # ── A8 突破信号 ──
    # 原文: "enter on opening range highs" + "range expansion out of consolidation"
    if len(closes) >= 3:
        chg_1d = (closes[-1] - closes[-2]) / closes[-2] * 100
        chg_2d = (closes[-1] - closes[-3]) / closes[-3] * 100
        atr5_pct = atr5 / price * 100
        
        if chg_1d > atr5_pct * 1.5 and chg_2d > atr5_pct * 2:
            result.s8_breakout = 5; details.append(f'突破! 日涨幅{chg_1d:.1f}%>ATR{atr5_pct:.1f}% → +5分')
        elif chg_1d > atr5_pct and chg_2d > 0:
            result.s8_breakout = 3; details.append(f'初步突破 日涨{chg_1d:.1f}% → +3分')
        elif chg_1d > 0:
            result.s8_breakout = 1; details.append(f'微涨{chg_1d:.1f}% → +1分')
        else:
            details.append(f'日跌{chg_1d:.1f}% → 0分')
    
    result.total_score = (result.s1_surge + result.s2_pullback + 
                          result.s3_ma_support + result.s4_higher_low +
                          result.s5_tightening + result.s6_volume + 
                          result.s7_position + result.s8_breakout)
    result.details = details
    return result


if __name__ == '__main__':
    # 快速测试
    codes_test = ['sh600176','sh600487','sh600105','sh600519','sh601318']
    for c in codes_test:
        r = score_pattern(c, c)
        print(f'\n{c} ¥{r.price:.2f} 总分:{r.total_score}/46')
        print(f'  前涨:{r.s1_surge} 回调:{r.s2_pullback} MA:{r.s3_ma_support} HL:{r.s4_higher_low} 收紧:{r.s5_tightening} 量:{r.s6_volume} 位置:{r.s7_position} 突破:{r.s8_breakout}')
        for d in r.details: print(f'    {d}')
