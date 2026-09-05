"""
Qullamaggie Breakout 形态评分器
从 phase0_backtest_v2.py 提炼，参数由 Phase 0 参数扫描确定。

评分维度 (6项, 满分28):
  S1: 前段涨幅 (15%+) —— 0-6分
  S2: 有序回调 (回调≤前涨1/3) —— 0-5分  
  S3: MA10/20附近企稳 —— 0-5分
  S4: Higher Low 构筑 —— 0-4分
  S5: 波动收窄 (ATR收缩) —— 0-5分
  S6: 成交量递减 —— 0-3分

当前参数 (v2 调优):
  SCORE_MIN = 18 (≥18 出买入信号, ≥24 强买入)
  MAX_POSITIONS = 5
  K 线最低: 60 根
  S1 前涨门槛: ≥15% 起计分（适配港股蓝筹特征）
  S5 ATR 收缩: ≤0.85 起计分（放宽版）
"""
from __future__ import annotations
from typing import List, Dict, Tuple, Optional
import math


def sma(values: List[float], n: int) -> Optional[float]:
    """简单移动平均"""
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def roc(values: List[float], n: int) -> Optional[float]:
    """Rate of Change: (current - n_ago) / n_ago"""
    if len(values) < n + 1:
        return None
    return (values[-1] - values[-n - 1]) / values[-n - 1]


def atr(highs: List[float], lows: List[float], closes: List[float], n: int = 14) -> float:
    """Average True Range"""
    if len(closes) < n + 1:
        return 0.0
    trs = []
    for i in range(1, min(len(closes), n * 3)):
        h = highs[-i]
        l = lows[-i]
        pc = closes[-i - 1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    trs = trs[:n]
    if not trs:
        return 0.0
    return sum(trs) / len(trs)


def score_pattern(
    candles: List[dict],
    idx: int,
    lookback: int = 60,
) -> Tuple[int, List[str]]:
    """
    对 candles[idx] 时刻做形态评分。
    
    返回 (总分, 细节描述列表)
    """
    if idx < lookback:
        return 0, ["数据不足"]

    # 提取数据
    closes = [c['close'] for c in candles[idx - lookback:idx + 1]]
    highs = [c['high'] for c in candles[idx - lookback:idx + 1]]
    lows = [c['low'] for c in candles[idx - lookback:idx + 1]]
    volumes = [c['volume'] for c in candles[idx - lookback:idx + 1]]
    
    total = 0
    details = []

    # ─── S1: 前段涨幅 (lookback的前半段) ───
    half = lookback // 2
    mid_price = closes[half]
    start_price = closes[0]
    prior_roc = (mid_price - start_price) / start_price if start_price > 0 else 0
    
    if prior_roc >= 1.0:
        s1 = 6
        details.append(f"前段+{prior_roc*100:.0f}%")
    elif prior_roc >= 0.90:
        s1 = 5
        details.append(f"前段+{prior_roc*100:.0f}%")
    elif prior_roc >= 0.70:
        s1 = 4
        details.append(f"前段+{prior_roc*100:.0f}%")
    elif prior_roc >= 0.50:
        s1 = 3
        details.append(f"前段+{prior_roc*100:.0f}%")
    elif prior_roc >= 0.30:
        s1 = 2
        details.append(f"前段+{prior_roc*100:.0f}%")
    elif prior_roc >= 0.15:
        s1 = 1
        details.append(f"前段+{prior_roc*100:.0f}%")
    else:
        s1 = 0
        details.append(f"前段不足({prior_roc*100:.0f}%)")
    total += s1

    # ─── S2: 有序回调 ───
    if prior_roc > 0:
        peak = max(closes[half:])
        current = closes[-1]
        drawdown = (peak - current) / peak
        if drawdown <= 0.33:
            s2 = 5 if drawdown <= 0.20 else 3
            details.append(f"回调{drawdown*100:.0f}%")
        elif drawdown <= 0.40:
            s2 = 1
            details.append(f"回调偏深{drawdown*100:.0f}%")
        else:
            s2 = 0
            details.append(f"回调过深{drawdown*100:.0f}%")
    else:
        s2 = 0
        details.append("无前涨")
    total += s2

    # ─── S3: MA10/20附近企稳 ───
    ma10 = sma(closes, 10)
    ma20 = sma(closes, 20)
    s3 = 0
    if ma10 and ma20:
        price = closes[-1]
        dist10 = abs(price - ma10) / ma10
        dist20 = abs(price - ma20) / ma20
        
        # 价格在MA10上方且靠近 → 强势
        if price >= ma10 and dist10 <= 0.02:
            s3 = 5
            details.append(f"MA10上方{price/ma10:.3f}")
        elif price >= ma10 and dist10 <= 0.04:
            s3 = 4
            details.append(f"MA10附近{price/ma10:.3f}")
        elif price >= ma20 and dist10 <= 0.06:
            s3 = 3
            details.append(f"MA10/20间")
        elif dist20 <= 0.06:
            s3 = 2
            details.append(f"MA20附近")
        elif dist20 <= 0.10:
            s3 = 1
            details.append(f"MA20边缘")
        else:
            details.append(f"离MA20过远({dist20*100:.0f}%)")
    total += s3

    # ─── S4: Higher Low ───
    # 在回调段找两个局部低点，判断是否上升
    recent_lows = lows[-40:]  # 最近40根
    if len(recent_lows) >= 20:
        first_half_min = min(recent_lows[:20])
        second_half_min = min(recent_lows[-20:])
        if second_half_min > first_half_min * 1.02:
            s4 = 4
            details.append("Higher Low↑")
        elif second_half_min > first_half_min * 1.005:
            s4 = 2
            details.append("微Higher Low")
        elif second_half_min >= first_half_min * 0.98:
            s4 = 1
            details.append("平坦Low")
        else:
            s4 = 0
            details.append("Lower Low")
    else:
        s4 = 0
    total += s4

    # ─── S5: 波动收窄 ───
    atr20 = atr(highs, lows, closes, 20)
    atr5 = atr(highs, lows, closes, 5)
    if atr20 > 0 and atr5 > 0:
        ratio = atr5 / atr20
        if ratio <= 0.55:
            s5 = 5
            details.append(f"ATR极窄({ratio:.2f})")
        elif ratio <= 0.70:
            s5 = 4
            details.append(f"ATR收缩({ratio:.2f})")
        elif ratio <= 0.85:
            s5 = 3
            details.append(f"ATR略收({ratio:.2f})")
        elif ratio <= 0.95:
            s5 = 2
            details.append(f"ATR正常({ratio:.2f})")
        elif ratio <= 1.10:
            s5 = 1
            details.append(f"ATR略扩({ratio:.2f})")
        else:
            s5 = 0
            details.append(f"ATR扩张({ratio:.2f})")
    else:
        s5 = 0
    total += s5

    # ─── S6: 成交量递减 ───
    vol_recent = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else 0
    vol_earlier = sum(volumes[-20:-5]) / 15 if len(volumes) >= 20 else 0
    if vol_earlier > 0 and vol_recent > 0:
        ratio = vol_recent / vol_earlier
        if ratio <= 0.60:
            s6 = 3
            details.append(f"量缩({ratio:.2f})")
        elif ratio <= 0.80:
            s6 = 2
            details.append(f"量略缩({ratio:.2f})")
        elif ratio <= 1.00:
            s6 = 1
            details.append(f"量平({ratio:.2f})")
        else:
            s6 = 0
    else:
        s6 = 0
    total += s6

    return total, details


def pattern_phase(score: int, details: List[str]) -> str:
    """判断当前形态处于 Qullamaggie 台阶模型的哪个阶段"""
    detail_str = ' '.join(details)
    
    # 通过检测各维度通过情况来判断
    has_rally = any('前段+' in d for d in details)
    has_pullback = any('回调' in d and '%' in d for d in details)
    has_ma = any('MA10' in d or 'MA20' in d for d in details)
    has_hl = 'Higher Low' in detail_str
    has_atr_tight = any('ATR' in d and ('极窄' in d or '收缩' in d or '略收' in d) for d in details)
    has_vol_contract = any('量' in d and ('缩' in d or '平' in d) for d in details)
    
    if has_rally and has_pullback and has_ma and has_hl and has_atr_tight and has_vol_contract:
        return 'Phase F → G: 蓄势待发，等待放量突破确认'
    elif has_rally and has_pullback and has_ma and has_hl and has_atr_tight:
        return 'Phase E→F: 波动收窄完毕，成交量仍在等待'
    elif has_rally and has_pullback and has_ma and has_hl:
        return 'Phase D→E: Higher Low确认，等待波动收窄'
    elif has_rally and has_pullback and has_ma:
        return 'Phase C→D: MA企稳中，Higher Low构筑中'
    elif has_rally and has_pullback:
        return 'Phase B→C: 回调完成，MA附近寻找支撑'
    elif has_rally:
        return 'Phase A→B: 前段暴涨后回撤中'
    else:
        return 'Phase A: 动量积累初期'


def pattern_similarity(score: int, details: List[str]) -> float:
    """
    计算当前形态与 Qullamaggie 标准台阶形态的相似度。
    
    标准形态评分体系满分28分，相似度 = 实际得分 / 28。
    额外考虑：各维度通过率（通过维度数 / 6）。
    """
    detail_str = ' '.join(details)
    
    # 6个维度各自的通过情况
    dims = [
        any('前段+' in d for d in details),           # S1: 前段涨幅
        any('回调' in d and '%' in d and '过深' not in d for d in details),  # S2: 回调
        any('MA10' in d or 'MA10/20' in d for d in details),  # S3: MA企稳
        'Higher Low' in detail_str,                    # S4: Higher Low
        any('ATR' in d and ('极窄' in d or '收缩' in d or '略收' in d or '正常' in d) for d in details),  # S5: ATR
        any('量' in d and ('缩' in d or '平' in d) for d in details),  # S6: 量
    ]
    dims_passed = sum(dims)
    
    # 综合: 得分比率 70% + 维度通过率 30%
    score_ratio = score / 28.0
    dims_ratio = dims_passed / 6.0
    similarity = score_ratio * 0.7 + dims_ratio * 0.3
    
    return round(similarity * 100, 1)


def historical_pattern_accuracy(
    candles: List[dict],
    lookback: int = 120,
    score_threshold: int = 18,
    forward_days: int = 20,
    win_threshold: float = 0.10,  # 10% 涨幅算命中
) -> Dict:
    """
    扫描该股历史K线，统计相似形态的历史命中率。
    
    遍历每根K线（排除最近forward_days根），对每根做形态评分，
    统计: 形态出现次数 / 后续forward_days内涨幅>win_threshold的次数
    
    返回: {'occurrences': N, 'hits': M, 'hit_rate': pct, 'avg_gain': avg_pct}
    """
    if len(candles) < lookback + forward_days + 10:
        return {'occurrences': 0, 'hits': 0, 'hit_rate': 0.0, 'avg_gain': 0.0}
    
    occurrences = 0
    hits = 0
    total_gain = 0.0
    
    # 从 lookback 天开始扫描到 倒数forward_days天
    for idx in range(lookback, len(candles) - forward_days):
        score, details = score_pattern(candles, idx, lookback)
        if score < score_threshold:
            continue
        
        occurrences += 1
        
        # 计算forward_days后的涨幅
        entry_price = candles[idx]['close']
        # 取forward_days内的最高价（模拟卖出）
        future_high = max(c['high'] for c in candles[idx+1:idx+forward_days+1])
        gain = (future_high / entry_price - 1)
        
        if gain >= win_threshold:
            hits += 1
            total_gain += gain
    
    hit_rate = (hits / occurrences * 100) if occurrences > 0 else 0.0
    avg_gain = (total_gain / hits * 100) if hits > 0 else 0.0
    
    return {
        'occurrences': occurrences,
        'hits': hits,
        'hit_rate': round(hit_rate, 1),
        'avg_gain': round(avg_gain, 1),
    }


def is_breakout_signal(
    candles: List[dict],
    idx: int,
    min_score: int = 28,
) -> Tuple[bool, int, List[str], float]:
    """
    判断 candles[idx] 是否为突破信号。

    返回: (是否信号, 得分, 细节, 建议入场价)
    """
    score, details = score_pattern(candles, idx)
    
    if score < min_score:
        return False, score, details, 0.0
    
    # 突破确认: 今日收盘 > 前5日最高
    if idx >= 5:
        recent_high = max(c['high'] for c in candles[idx-5:idx])
        entry = recent_high * 1.002  # 微突破
    else:
        entry = candles[idx]['close']
    
    # 量能确认（不低于均量即可，评分中已含量缩维度）
    vol_today = candles[idx]['volume']
    vol_avg = sum(c['volume'] for c in candles[idx-20:idx]) / 20 if idx >= 20 else vol_today
    if vol_avg > 0 and vol_today < vol_avg * 1.0:
        return False, score, details + [f"量不足({vol_today/vol_avg:.1f}x)"] if vol_avg > 0 else False, 0.0
    
    return True, score, details, entry
