"""
低量价值发现扫描器 — 捕捉底部缩量蓄势品种

补盲多因子扫描器(≥3亿成交额)和突破扫描器(放量新高)的覆盖盲区。
目标品种: 底部缩量盘整、低估值、刚出现放量异动的股票(类似海正药业6月)。

评分维度:
  1. 价值因子(40分) — PE低 + PB低 + 股息率
  2. 蓄势因子(35分) — 波动率收窄 + 横盘天数 + 距高点回撤
  3. 异动因子(25分) — 今日放量倍数 + 振幅

输出: TOP 5 候选 (行业去重后)
"""

from __future__ import annotations
import json, os, time, logging
from datetime import date, datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

from src.data.akshare_client import TencentClient, StockQuote, KlineBar

logger = logging.getLogger(__name__)

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_DIR = os.path.join(BASE, 'data', 'cache')


# ─── 配置 ───────────────────────────────────────────
@dataclass
class LowVolumeConfig:
    """低量价值发现配置"""
    # 成交额门槛 (低量: 1-5亿)
    min_amount: float = 1e8       # 最小成交额 1亿
    max_amount: float = 5e8       # 最大成交额 5亿
    # 估值门槛
    max_pe: float = 20            # 最大PE(动)
    max_pb: float = 3.0           # 最大PB
    # 波动率门槛
    max_daily_volatility: float = 2.5  # 横盘阶段最大日振幅(%)
    min_sideways_days: int = 10        # 最少横盘天数
    # 异动门槛
    min_volume_ratio: float = 1.5      # 今日量 / 20日均量 ≥ 1.5倍
    min_amplitude: float = 3.0         # 今日振幅 ≥ 3%
    # 回调确认
    max_high_drawdown_pct: float = 40  # 距120日高点最大回撤 ≥ 某% 说明深度回调过
    # 输出
    top_n: int = 5
    exclude_st: bool = True


@dataclass
class LowVolumeResult:
    """低量价值发现结果"""
    code: str
    name: str
    score: float            # 综合得分 0-100
    price: float
    change_pct: float
    pe: float
    pb: float
    industry: str = ""
    factors: Dict[str, float] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    # 入场参数
    suggested_entry: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    # 技术指标
    volume_ratio: float = 0.0       # 今日量/20日均量
    sideways_days: int = 0          # 横盘天数
    avg_amplitude: float = 0.0      # 横盘期平均振幅
    drawdown_pct: float = 0.0       # 距120日高点回撤
    ma20: float = 0.0               # 20日均线


class LowVolumeScanner:
    """低量价值发现扫描器"""

    def __init__(self, config: Optional[LowVolumeConfig] = None):
        self.cfg = config or LowVolumeConfig()
        self.client = TencentClient()
        self._industry_cache = {}
        self._name_cache = {}

    def scan(self) -> List[LowVolumeResult]:
        t0 = time.time()
        logger.info("开始低量价值扫描...")

        # 获取行情
        codes = self._get_a_codes()
        all_quotes = []
        for i in range(0, len(codes), 800):
            batch = codes[i:i+800]
            quotes = self.client._get_quotes(batch)
            all_quotes.extend(quotes)
            if i + 800 < len(codes):
                time.sleep(0.3)

        print(f"[低量扫描] 获取行情 {len(all_quotes)}/{len(codes)} 只")

        results = []
        for q in all_quotes:
            if not self._pass_quick_filter(q):
                continue

            # 拉K线
            klines = self._get_klines(q.code)
            if not klines or len(klines) < 60:
                continue

            score, reasons, factors, meta = self._score(q, klines)

            if score >= 40:  # 综合得分门槛 (低量品种天然弱信号)
                results.append(LowVolumeResult(
                    code=q.code,
                    name=q.name,
                    score=score,
                    price=q.price,
                    change_pct=q.change_pct,
                    pe=q.pe,
                    pb=q.pb,
                    factors=factors,
                    reasons=reasons,
                    suggested_entry=q.price * 0.98,
                    stop_loss=q.price * 0.93,
                    take_profit=q.price * 1.15,
                    volume_ratio=meta.get('volume_ratio', 0),
                    sideways_days=meta.get('sideways_days', 0),
                    avg_amplitude=meta.get('avg_amplitude', 0),
                    drawdown_pct=meta.get('drawdown_pct', 0),
                    ma20=meta.get('ma20', 0),
                ))

        # 排序 + 行业去重 + 截取
        results.sort(key=lambda x: x.score, reverse=True)

        # 获取行业信息（只对前N*2只做，节约API）
        for r in results[:self.cfg.top_n * 3]:
            if not r.industry:
                r.industry = self._get_industry(r.code)

        # 行业去重
        seen_industries = set()
        filtered = []
        for r in results:
            key = r.industry or r.code
            if key not in seen_industries:
                seen_industries.add(key)
                filtered.append(r)

        elapsed = time.time() - t0
        print(f"[低量扫描] 候选{len(results)}只, 去重后{len(filtered)}只, "
              f"取TOP {min(len(filtered), self.cfg.top_n)}, 耗时{elapsed:.0f}s")

        return filtered[:self.cfg.top_n]

    # ─── 快速过滤 ─────────────────────────────────────

    def _pass_quick_filter(self, q: StockQuote) -> bool:
        """前K线快速过滤 — 排除ST、停牌、成交额不符"""
        if q.price <= 0:
            return False
        if self.cfg.exclude_st and 'ST' in q.name:
            return False
        amount = q.amount  # 元
        if not (self.cfg.min_amount <= amount <= self.cfg.max_amount):
            return False
        if q.pe <= 0 or q.pe > self.cfg.max_pe:
            return False
        # PB暂不可用(SockQuote.pb=0), 跳过PB过滤
        return True

    # ─── 综合评分 ─────────────────────────────────────

    def _score(self, q: StockQuote, klines: List[KlineBar]) -> Tuple[float, List[str], Dict, Dict]:
        """
        三维评分:
          1. 价值因子 (40分)  — 越便宜越好
          2. 蓄势因子 (35分)  — 缩量横盘
          3. 异动因子 (25分)  — 今日放量异动
        """
        score = 0.0
        reasons = []
        factors = {}
        meta = {}

        closes = [k.close for k in klines]
        vols = [k.volume for k in klines]
        highs = [k.high for k in klines]
        prices = closes

        # ── 1. 价值因子 (40分) ──
        val_score = 0.0

        # PE得分: 越低越加分, 0-10倍最好
        if 0 < q.pe <= 10:
            val_score += 20
            reasons.append(f"PE={q.pe:.0f}极低")
        elif 10 < q.pe <= 15:
            val_score += 15
            reasons.append(f"PE={q.pe:.0f}低")
        elif 15 < q.pe <= 20:
            val_score += 10
            reasons.append(f"PE={q.pe:.0f}合理")

        # PB得分 (pb=0时跳过，数据暂不可用)
        pb = getattr(q, 'pb', 0) or 0
        if pb > 0:
            if pb <= 1.0:
                val_score += 12
                reasons.append(f"PB={pb:.2f}破净")
            elif pb <= 1.5:
                val_score += 8
                reasons.append(f"PB={pb:.1f}低估")
            elif pb <= 2.5:
                val_score += 5

        # 距120日高点回撤
        high_120 = max(highs[-120:]) if len(highs) >= 120 else max(highs)
        drawdown = (high_120 - q.price) / high_120 * 100 if high_120 > 0 else 0
        meta['drawdown_pct'] = drawdown

        if drawdown >= 30:
            val_score += 8
            reasons.append(f"回撤{drawdown:.0f}%深调")

        score += min(val_score, 40)
        factors['价值'] = min(val_score, 40)

        # ── 2. 蓄势因子 (35分) — 横盘收窄 ──
        accum_score = 0.0

        # 检测横盘区间: 最近N天价格波动范围
        # 用最近20天检测横盘
        recent = prices[-20:]
        price_range = (max(recent) - min(recent)) / max(recent) * 100 if max(recent) > 0 else 0
        meta['price_range_20d'] = price_range

        # 计算日均振幅(横盘期)
        amps = []
        for i in range(len(klines) - 20, len(klines)):
            if i >= 0 and klines[i].open > 0:
                amp = abs(klines[i].high - klines[i].low) / klines[i].open * 100
                amps.append(amp)
        avg_amp = sum(amps) / len(amps) if amps else 0
        meta['avg_amplitude'] = avg_amp

        # 检测连续横盘天数(波动率<阈值)
        sideways_count = 0
        for i in range(len(klines) - 1, max(len(klines) - 60, 0), -1):
            if i >= 1 and klines[i].open > 0:
                day_amp = abs(klines[i].high - klines[i].low) / klines[i].open * 100
                if day_amp < self.cfg.max_daily_volatility:
                    sideways_count += 1
                else:
                    break
        meta['sideways_days'] = sideways_count

        # 横盘得分
        if sideways_count >= 20:
            accum_score += 20
            reasons.append(f"横盘{sideways_count}天蓄势充分")
        elif sideways_count >= 10:
            accum_score += 15
            reasons.append(f"横盘{sideways_count}天蓄势")
        elif sideways_count >= 5:
            accum_score += 8
            reasons.append(f"横盘{sideways_count}天")

        # 波动率收窄得分
        if avg_amp <= 1.5:
            accum_score += 10
            reasons.append(f"振幅{avg_amp:.1f}%极窄")
        elif avg_amp <= 2.0:
            accum_score += 6

        # 20日价格通道收窄
        if price_range <= 5:
            accum_score += 5
            reasons.append(f"价格通道{price_range:.0f}%收窄")

        score += min(accum_score, 35)
        factors['蓄势'] = min(accum_score, 35)

        # ── 3. 异动因子 (25分) — 今日放量 ──
        anomaly_score = 0.0

        # 量比: 今日量 / 20日均量
        vol_20 = sum(vols[-21:-1]) / 20 if len(vols) >= 21 else (sum(vols[:-1]) / (len(vols)-1) if len(vols) > 1 else 1)
        vol_ratio = q.volume / vol_20 if vol_20 > 0 else 1
        meta['volume_ratio'] = vol_ratio

        if vol_ratio >= 3.0:
            anomaly_score += 15
            reasons.append(f"放量{vol_ratio:.1f}倍显著异动")
        elif vol_ratio >= 2.0:
            anomaly_score += 10
            reasons.append(f"放量{vol_ratio:.1f}倍")
        elif vol_ratio >= 1.5:
            anomaly_score += 6
            reasons.append(f"量比{vol_ratio:.1f}")
        elif vol_ratio < 0.8:
            # 极度缩量: 还没有异动, 但有价值底
            anomaly_score += 3

        # 今日振幅得分 (用最后一天K线的高/低/开)
        today_bar = klines[-1]
        today_amp = abs(today_bar.high - today_bar.low) / today_bar.open * 100 if today_bar.open > 0 else 0
        if today_amp >= 5:
            anomaly_score += 8
            reasons.append(f"振幅{today_amp:.1f}%异动")
        elif today_amp >= 3:
            anomaly_score += 5

        # 价格站上5日均线 = 短期转强
        ma5 = sum(prices[-5:]) / 5 if len(prices) >= 5 else q.price
        ma20 = sum(prices[-20:]) / 20 if len(prices) >= 20 else q.price
        meta['ma20'] = ma20

        if q.price > ma5:
            anomaly_score += 2

        score += min(anomaly_score, 25)
        factors['异动'] = min(anomaly_score, 25)

        return score, reasons, factors, meta

    # ─── 数据获取 ─────────────────────────────────────

    def _get_a_codes(self) -> List[str]:
        """从缓存读取全量A股代码（确保带sh/sz前缀）"""
        cache_file = os.path.join(CACHE_DIR, 'a_codes.json')
        today = date.today().isoformat()

        codes = []
        if os.path.exists(cache_file):
            try:
                with open(cache_file) as f:
                    cached = json.load(f)
                raw_codes = cached.get('codes', [])
                # 确保代码带 sh/sz 前缀
                for c in raw_codes:
                    if c.startswith(('sh', 'sz')):
                        codes.append(c)
                    elif c.startswith(('6', '68')):
                        codes.append('sh' + c)
                    elif c.startswith(('0', '3')):
                        codes.append('sz' + c)
                    else:
                        codes.append(c)
            except:
                pass

        if not codes:
            logger.warning("A股代码缓存为空，请先运行 scripts/rebuild_pool_v2.py")
        return codes

    def _get_klines(self, code: str) -> Optional[List[KlineBar]]:
        """获取K线 (缓存优先, 自动建缓存)"""
        cache_path = os.path.join(CACHE_DIR, f'klines_{code}.json')
        
        # 先读缓存
        if os.path.exists(cache_path):
            try:
                data = json.load(open(cache_path))
                candles = data.get('candles', [])
                if len(candles) >= 60:
                    bars = []
                    for c in candles:
                        bars.append(KlineBar(
                            date=c.get('date', ''),
                            open=c.get('open', 0),
                            high=c.get('high', 0),
                            low=c.get('low', 0),
                            close=c.get('close', 0),
                            volume=c.get('volume', 0),
                            amount=c.get('amount', 0)
                        ))
                    return bars
            except:
                pass

        # 缓存无/过期 → 直接拉并写缓存
        try:
            bars = self.client.get_kline(code, days=120)
            if bars and len(bars) >= 60:
                # 写回缓存供后续策略复用
                candles = [{
                    'date': b.date, 'open': b.open, 'high': b.high,
                    'low': b.low, 'close': b.close, 'volume': b.volume,
                    'amount': b.amount if hasattr(b, 'amount') else 0
                } for b in bars]
                try:
                    json.dump({'date': date.today().isoformat(), 'candles': candles},
                             open(cache_path, 'w'))
                except:
                    pass
                return bars
        except:
            pass

        return None

    def _get_industry(self, code: str) -> str:
        if code in self._industry_cache:
            return self._industry_cache[code]
        # 暂无行业API, 留空
        self._industry_cache[code] = ''
        return ''


# ─── 便捷函数 ─────────────────────────────────────────

def run_low_volume_scan(top_n: int = 5) -> List[LowVolumeResult]:
    """一键执行低量价值扫描"""
    config = LowVolumeConfig(top_n=top_n)
    scanner = LowVolumeScanner(config)
    return scanner.scan()


def format_results(results: List[LowVolumeResult]) -> str:
    """格式化输出"""
    if not results:
        return "🔍 低量价值发现：今日无符合条件的底部蓄势品种"

    date_str = datetime.now().strftime('%m月%d日')
    lines = [f"🔍 低量价值发现 | {date_str}\n"]
    lines.append("底部缩量蓄势 + 低估值 + 今日异动\n")

    for i, r in enumerate(results, 1):
        emoji = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣'][i-1] if i <= 5 else f'{i}.'
        status = ''
        if r.volume_ratio >= 2:
            status = ' 🔥放量异动'
        elif r.sideways_days >= 15:
            status = ' ⏳蓄势充分'

        lines.append(f"{emoji} **{r.code} {r.name}**{status}")
        lines.append(f"   💰 {r.price:.2f} ({r.change_pct:+.1f}%)  │  PE {r.pe:.0f}  PB {r.pb:.1f}")
        lines.append(f"   📊 得分 {r.score:.0f}/100  │  {' | '.join(r.reasons[:3])}")
        lines.append(f"   📈 横盘 {r.sideways_days}天  │  量比 {r.volume_ratio:.1f}x  │  振幅 {r.avg_amplitude:.1f}%")
        lines.append(f"   🎯 入场 {r.suggested_entry:.2f}  │  止损 {r.stop_loss:.2f}  │  止盈 {r.take_profit:.2f}")
        if r.industry:
            lines.append(f"   🏭 {r.industry}")
        lines.append("")

    lines.append("⚠️ 低量品种流动性较差，仓位减半，仅供参考")
    return '\n'.join(lines)
