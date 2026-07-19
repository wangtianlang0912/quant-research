"""
Qullamaggie Breakout 全市场扫描器 v2.0

两阶段全市场扫描:
  Phase 1: 成交量过滤 → Top 300 活跃股 → 批量K线预热 (~30s)
  Phase 2: 形态评分 (6维) → 行业去重 → 输出候选列表

数据源: 新浪K线 (akshare_client) + 新浪行情批量接口
覆盖: 全市场 4700+ A股
"""

from __future__ import annotations
import json, os, time, logging
from datetime import date, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Optional

from src.data.akshare_client import TencentClient
from src.strategies.breakout_scorer import is_breakout_signal, pattern_phase, pattern_similarity, historical_pattern_accuracy, sma, roc

logger = logging.getLogger(__name__)

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_DIR = os.path.join(BASE, 'data', 'cache')

# ─── 配置 ───
SCORE_MIN = 28              # 严格入场阈值
TOP_N = 8                   # 最终输出
MIN_KLINE_BARS = 120        # 最少K线数
MIN_DAILY_AMOUNT = 1e8      # 最低成交额 (1亿)
TOP_VOLUME = 300            # 取成交量前N只
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


@dataclass
class BreakoutCandidate:
    code: str
    name: str
    score: int
    entry_price: float
    price: float
    volume_ratio: float
    change_pct: float
    industry: str
    reasons: List[str] = field(default_factory=list)
    momentum_pct: float = 0.0
    atr_value: float = 0.0
    # 🆕 三个量化维度
    phase: str = ''                    # 形态阶段 (A→B→C→D→E→F→G→突破)
    similarity: float = 0.0            # 标准形态相似度 (0-100%)
    hist_occurrences: int = 0          # 历史同形态出现次数
    hist_hits: int = 0                 # 历史命中次数
    hist_hit_rate: float = 0.0        # 历史命中率（20日>10%涨幅）
    hist_avg_gain: float = 0.0        # 历史命中平均收益


class BreakoutScanner:
    """两阶段全市场突破扫描器"""
    
    def __init__(self, score_min: int = SCORE_MIN, top_n: int = TOP_N):
        self.client = TencentClient()
        self.score_min = score_min
        self.top_n = top_n
    
    def run(self) -> List[BreakoutCandidate]:
        t0 = time.time()
        
        # Phase 1: 成交量筛选 + K线预热
        pool = self._warmup_pool()
        logger.info(f"Phase 1: {len(pool)} 只活跃股入池, {time.time()-t0:.0f}s")
        
        # Phase 2: 形态评分
        candidates = []
        for i, code in enumerate(pool):
            candles = self._get_candles(code)
            if not candles:
                continue
            
            ok, score, details, entry = is_breakout_signal(candles, len(candles)-1, self.score_min)
            if ok and score >= self.score_min:
                bar = candles[-1]
                vol_avg = sum(c['volume'] for c in candles[-20:]) / 20
                mid = len(candles) // 2
                mom = (bar['close'] / candles[mid]['close'] - 1) * 100 if mid > 0 else 0
                
                phase = pattern_phase(score, details)
                sim = pattern_similarity(score, details)
                hist = historical_pattern_accuracy(candles, score_threshold=18)
                
                candidates.append(BreakoutCandidate(
                    code=code,
                    name=self._get_name(code),
                    score=score,
                    entry_price=entry,
                    price=bar['close'],
                    volume_ratio=bar['volume'] / vol_avg if vol_avg > 0 else 1,
                    change_pct=(bar['close'] - bar['open']) / bar['open'] * 100,
                    industry=self._get_industry(code),
                    reasons=details,
                    momentum_pct=mom,
                    phase=phase,
                    similarity=sim,
                    hist_occurrences=hist['occurrences'],
                    hist_hits=hist['hits'],
                    hist_hit_rate=hist['hit_rate'],
                    hist_avg_gain=hist['avg_gain'],
                ))
            
            if (i+1) % 50 == 0:
                logger.info(f"  评分 {i+1}/{len(pool)}, 候选 {len(candidates)}")
            time.sleep(0.03)
        
        result = self._dedup(candidates)
        logger.info(f"完成: {len(result)} 只候选, 耗时 {time.time()-t0:.0f}s")
        return result[:self.top_n]
    
    def _warmup_pool(self) -> List[str]:
        """成交量Top 300 + 按需拉K线"""
        quotes_path = os.path.join(CACHE_DIR, 'all_quotes.json')
        if not os.path.exists(quotes_path):
            return self._fallback_codes()
        
        with open(quotes_path) as f:
            quotes = json.load(f)['quotes']
        
        # 过滤: 成交额>1亿, 非ST
        active = [(c, q) for c, q in quotes.items()
                  if q.get('amount', 0) > MIN_DAILY_AMOUNT / 10000  # 存储单位万
                  and 'ST' not in q.get('name', '')]
        
        active.sort(key=lambda x: x[1]['amount'], reverse=True)
        
        pull = 0
        codes = []
        for code, _ in active[:TOP_VOLUME]:
            cache_path = os.path.join(CACHE_DIR, f'klines_{code}.json')
            fresh = False
            
            if os.path.exists(cache_path):
                try:
                    data = json.load(open(cache_path))
                    candles = data.get('candles', [])
                    if candles and len(candles) >= MIN_KLINE_BARS:
                        if candles[-1].get('date', '') >= YESTERDAY:
                            fresh = True
                except:
                    pass
            
            if not fresh:
                try:
                    bars = self.client.get_kline(code, days=600)
                    if bars and len(bars) >= MIN_KLINE_BARS:
                        candles = [{'date': b.date, 'open': b.open, 'high': b.high,
                                   'low': b.low, 'close': b.close, 'volume': b.volume}
                                  for b in bars]
                        json.dump({'date': date.today().isoformat(), 'candles': candles},
                                 open(cache_path, 'w'))
                        pull += 1
                        fresh = True
                except:
                    pass
                time.sleep(0.04)
            
            if fresh:
                codes.append(code)
        
        logger.info(f"  新拉 {pull}, 缓存 {len(codes)-pull}, 合计 {len(codes)}")
        return codes
    
    def _fallback_codes(self) -> List[str]:
        """Fallback: 从a_codes取前500"""
        a_path = os.path.join(CACHE_DIR, 'a_codes.json')
        if os.path.exists(a_path):
            raw = json.load(open(a_path)).get('codes', [])
            return [c['code'] for c in raw if c.get('price', 0) > 0][:500]
        return []
    
    def _get_candles(self, code: str) -> List[dict] | None:
        cache_path = os.path.join(CACHE_DIR, f'klines_{code}.json')
        if not os.path.exists(cache_path):
            return None
        try:
            data = json.load(open(cache_path))
            candles = data.get('candles', [])
            if len(candles) < MIN_KLINE_BARS:
                return None
            latest = candles[-1].get('date', '')
            from datetime import datetime
            if latest < (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'):
                return None  # 僵尸股
            return candles
        except:
            return None
    
    def _get_name(self, code: str) -> str:
        quotes_path = os.path.join(CACHE_DIR, 'all_quotes.json')
        if os.path.exists(quotes_path):
            try:
                quotes = json.load(open(quotes_path))['quotes']
                return quotes.get(code, {}).get('name', code)
            except:
                pass
        return code
    
    def _get_industry(self, code: str) -> str:
        """简单版: 暂无行业数据, 后续挂接东方财富行业API"""
        return ''
    
    def _dedup(self, candidates: List[BreakoutCandidate]) -> List[BreakoutCandidate]:
        """行业去重 + 按得分降序"""
        seen = set()
        deduped = []
        for c in sorted(candidates, key=lambda x: x.score, reverse=True):
            ind = c.industry or c.code
            if ind not in seen:
                seen.add(ind)
                deduped.append(c)
        return deduped
