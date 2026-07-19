"""
多市场因子扫描器 - 支持A股/港股/美股 + 技术指标
"""
from __future__ import annotations
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
import logging
import os
import json
import time

from src.data.akshare_client import TencentClient, StockQuote, KlineBar

logger = logging.getLogger(__name__)

# 缓存目录
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'cache')


def calc_rsi(closes: List[float], period: int = 14) -> float:
    """计算RSI"""
    if len(closes) < period + 1:
        return 50.0  # 数据不足返回中性值
    
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))
    
    if len(gains) < period:
        return 50.0
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_macd(closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[float, float, float]:
    """计算MACD，返回(dif, dea, macd柱)"""
    if len(closes) < slow + signal:
        return 0.0, 0.0, 0.0
    
    # EMA计算
    def ema(data, period):
        k = 2 / (period + 1)
        ema_val = data[0]
        for price in data[1:]:
            ema_val = price * k + ema_val * (1 - k)
        return ema_val
    
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    dif = ema_fast - ema_slow
    
    # 简化：用最近的dif序列计算dea
    difs = []
    for i in range(slow, len(closes)):
        ef = ema(closes[:i+1], fast)
        es = ema(closes[:i+1], slow)
        difs.append(ef - es)
    
    if len(difs) < signal:
        return dif, 0.0, dif
    
    dea = ema(difs, signal)
    macd_bar = 2 * (dif - dea)
    
    return dif, dea, macd_bar


def calc_ma(closes: List[float], period: int) -> float:
    """计算均线"""
    if len(closes) < period:
        return closes[-1] if closes else 0
    return sum(closes[-period:]) / period


@dataclass
class ScanResult:
    """扫描结果"""
    code: str
    name: str
    market: str  # 'A', 'HK', 'US'
    score: float
    price: float
    change_pct: float
    reasons: List[str]
    industry: str = ""  # 所属行业
    factors: Dict[str, float] = field(default_factory=dict)
    suggested_entry: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    # 技术指标
    rsi: float = 50.0
    macd_signal: str = ""  # '金叉', '死叉', ''


@dataclass
class ScanConfig:
    """扫描配置"""
    # A股参数
    a_min_amount: float = 3e8      # 最小成交额3亿
    a_max_amount: float = 50e8     # 最大成交额50亿
    a_min_turnover: float = 3.0    # 最小换手率
    a_max_turnover: float = 15.0   # 最大换手率
    a_min_change: float = 1.0      # 最小涨跌幅
    a_max_change: float = 6.0      # 最大涨跌幅
    a_max_pe: float = 100          # 最大PE
    
    # 港股参数（成交额用亿港元）
    hk_min_amount: float = 5e8     # 最小成交额5亿港元
    hk_max_amount: float = 100e8
    hk_min_turnover: float = 0.5
    hk_max_turnover: float = 10.0
    hk_min_change: float = 1.0
    hk_max_change: float = 6.0
    hk_max_pe: float = 50
    
    # 美股参数（成交额用美元）
    us_min_amount: float = 10e8    # 最小成交额10亿美元
    us_max_amount: float = 500e8
    us_min_turnover: float = 1.0
    us_max_turnover: float = 15.0
    us_min_change: float = 1.0
    us_max_change: float = 6.0
    us_max_pe: float = 200
    
    exclude_st: bool = True
    top_n: int = 10
    top_n_per_market: int = 2  # 每市场最多推荐数量


class MultiMarketScanner:
    """多市场因子扫描器"""
    
    def __init__(self, config: Optional[ScanConfig] = None):
        self.cfg = config or ScanConfig()
        self.client = TencentClient()
        self._industry_cache = {}  # 行业信息缓存
    
    def scan(self) -> List[ScanResult]:
        """执行扫描"""
        logger.info("开始多市场扫描...")
        
        all_results = []
        
        # 扫描A股
        a_stocks = self._scan_a()
        all_results.extend(a_stocks)
        logger.info(f"A股扫描完成: {len(a_stocks)} 只")
        
        # 扫描港股
        hk_stocks = self._scan_hk()
        all_results.extend(hk_stocks)
        logger.info(f"港股扫描完成: {len(hk_stocks)} 只")
        
        # 扫描美股
        us_stocks = self._scan_us()
        all_results.extend(us_stocks)
        logger.info(f"美股扫描完成: {len(us_stocks)} 只")
        
        # 按得分排序
        all_results.sort(key=lambda x: x.score, reverse=True)
        
        # 获取行业信息并去重（同行业只保留最高分）
        for result in all_results[:self.cfg.top_n * 2]:
            if result.market == 'A' and not result.industry:
                result.industry = self._get_industry(result.code, result.market)
        
        # 行业去重：每个行业只保留得分最高的1只
        seen_industries = set()
        filtered_results = []
        for result in all_results:
            if result.industry:
                if result.industry not in seen_industries:
                    seen_industries.add(result.industry)
                    filtered_results.append(result)
            else:
                filtered_results.append(result)
        
        all_results = filtered_results
        
        return all_results[:self.cfg.top_n]
    
    def _get_industry(self, code: str, market: str) -> str:
        """
        获取股票所属行业（仅A股支持）
        使用缓存避免重复API调用
        """
        cache_key = f"{market}:{code}"
        if cache_key in self._industry_cache:
            return self._industry_cache[cache_key]
        
        industry = ""
        if market == 'A':
            try:
                import akshare as ak
                df = ak.stock_individual_info_em(symbol=code)
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        if row['item'] == '行业':
                            industry = str(row['value'])
                            break
            except Exception as e:
                print(f"获取行业信息失败 {code}: {e}")
        
        self._industry_cache[cache_key] = industry
        return industry
    def _scan_a(self) -> List[ScanResult]:
        """扫描A股 - 分批获取行情，先filter再K线打分"""
        codes = self._get_a_codes()
        all_quotes = []

        # 分批获取行情（每批800只）
        for i in range(0, len(codes), 800):
            batch = codes[i:i+800]
            quotes = self.client._get_quotes(batch)
            all_quotes.extend(quotes)
            if i + 800 < len(codes):
                time.sleep(0.3)

        print(f"[A股扫描] 获取行情 {len(all_quotes)}/{len(codes)} 只")

        results = []
        for q in all_quotes:
            if self._filter_a(q):
                score, reasons, factors, tech = self._score_with_tech(q, 'A')
                if score > 30:
                    results.append(ScanResult(
                        code=q.code,
                        name=q.name,
                        market='A',
                        score=score,
                        price=q.price,
                        change_pct=q.change_pct,
                        reasons=reasons,
                        factors=factors,
                        suggested_entry=q.price * 0.98,
                        stop_loss=q.price * 0.94,
                        take_profit=q.price * 1.15,
                        rsi=tech.get('rsi', 50),
                        macd_signal=tech.get('macd_signal', '')
                    ))

        results.sort(key=lambda x: x.score, reverse=True)
        print(f"[A股扫描] 符合条件 {len(results)} 只，取前 {min(len(results), self.cfg.top_n_per_market)} 只")
        return results[:self.cfg.top_n_per_market]
    
    def _scan_hk(self) -> List[ScanResult]:
        """扫描港股"""
        codes = self._get_hk_codes()
        quotes = self.client._get_quotes(codes)
        
        results = []
        for q in quotes:
            if self._filter_hk(q):
                score, reasons, factors, tech = self._score_with_tech(q, 'HK')
                if score > 30:
                    results.append(ScanResult(
                        code=q.code,
                        name=q.name,
                        market='HK',
                        score=score,
                        price=q.price,
                        change_pct=q.change_pct,
                        reasons=reasons,
                        factors=factors,
                        suggested_entry=q.price * 0.98,
                        stop_loss=q.price * 0.94,
                        take_profit=q.price * 1.15,
                        rsi=tech.get('rsi', 50),
                        macd_signal=tech.get('macd_signal', '')
                    ))
        
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:self.cfg.top_n_per_market]
    
    def _scan_us(self) -> List[ScanResult]:
        """扫描美股"""
        codes = self._get_us_codes()
        quotes = self.client._get_quotes(codes)
        
        results = []
        for q in quotes:
            if self._filter_us(q):
                score, reasons, factors, tech = self._score_with_tech(q, 'US')
                if score > 30:
                    results.append(ScanResult(
                        code=q.code,
                        name=q.name,
                        market='US',
                        score=score,
                        price=q.price,
                        change_pct=q.change_pct,
                        reasons=reasons,
                        factors=factors,
                        suggested_entry=q.price * 0.98,
                        stop_loss=q.price * 0.94,
                        take_profit=q.price * 1.15,
                        rsi=tech.get('rsi', 50),
                        macd_signal=tech.get('macd_signal', '')
                    ))
        
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:self.cfg.top_n_per_market]
    
    def _get_a_codes(self) -> List[str]:
        """A股股票池 - 动态获取全量A股代码（带本地文件缓存）"""
        cache_file = os.path.join(_CACHE_DIR, 'a_codes.json')
        today = date.today().isoformat()

        # 检查缓存：当天有效则直接返回
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    cached = json.load(f)
                if cached.get('date') == today:
                    return cached['codes']
            except Exception:
                pass

        # 动态探测全量A股代码
        print("[全量股票池] 正在探测A股代码，首次运行约需30秒...")
        all_codes = []
        ranges = [
            ('sh', 600000, 605000),   # 沪市主板
            ('sh', 688000, 689000),   # 科创板
            ('sz', 0, 5000),          # 深市主板
            ('sz', 300000, 301500),   # 创业板
        ]

        import requests as _req
        for market, start, end in ranges:
            codes = [f"{market}{i:06d}" for i in range(start, end)]
            for i in range(0, len(codes), 800):
                batch = codes[i:i+800]
                try:
                    url = f"http://qt.gtimg.cn/q={','.join(batch)}"
                    r = _req.get(url, timeout=10)
                    text = r.content.decode('gbk', errors='replace')
                    for line in text.strip().split('\n'):
                        if line.startswith('v_'):
                            try:
                                data = line.split('="', 1)[1].rstrip('";')
                                parts = data.split('~')
                                if len(parts) >= 35:
                                    price = float(parts[3]) if parts[3] else 0
                                    name = parts[1] if len(parts) > 1 else ''
                                    # 排除ST、停牌(价格>0即可交易)
                                    if price > 0 and 'ST' not in name:
                                        raw = parts[2]  # 如 sh600000 或 sz000001
                                        code = raw.lower()
                                        # 确保带市场前缀
                                        if not code.startswith(('sh', 'sz')):
                                            code = market + code.zfill(6)
                                        all_codes.append(code)
                            except Exception:
                                pass
                except Exception as e:
                    logger.debug(f"探测失败 {market}{start}: {e}")
                time.sleep(0.3)

        # 去重并保存缓存
        all_codes = list(set(all_codes))
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        with open(cache_file, 'w') as f:
            json.dump({'date': today, 'codes': all_codes}, f)
        print(f"[全量股票池] 探测完成，共 {len(all_codes)} 只A股")
        return all_codes
    
    def _get_hk_codes(self) -> List[str]:
        """港股股票池 - 从动态缓存读取"""
        cache_file = os.path.join(_CACHE_DIR, 'hk_codes.json')
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    cached = json.load(f)
                # 返回所有代码（由 syncing script 过滤）
                codes = [c['code'] if isinstance(c, dict) else c for c in cached.get('codes', [])]
                logger.info(f"港股股票池: {len(codes)} 只 (缓存日期: {cached.get('date', '?')})")
                return codes
            except Exception as e:
                logger.warning(f"港股缓存读取失败: {e}")
        # fallback: 核心蓝筹
        return [
            'hk00700','hk00941','hk01810','hk03690','hk09988','hk02318',
            'hk02628','hk00398','hk02328','hk00688','hk00883','hk00005',
            'hk00011','hk01299','hk02269','hk01093','hk00669','hk00960','hk02313'
        ]
    
    def _get_us_codes(self) -> List[str]:
        """美股股票池 - 从动态缓存读取"""
        cache_file = os.path.join(_CACHE_DIR, 'us_codes.json')
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    cached = json.load(f)
                codes = [c['code'] if isinstance(c, dict) else c for c in cached.get('codes', [])]
                logger.info(f"美股股票池: {len(codes)} 只 (缓存日期: {cached.get('date', '?')})")
                return codes
            except Exception as e:
                logger.warning(f"美股缓存读取失败: {e}")
        # fallback: 核心科技龙头
        return [
            'usAAPL','usMSFT','usGOOGL','usAMZN','usNVDA','usMETA',
            'usTSLA','usAMD','usAVGO','usORCL','usNFLX','usQCOM',
            'usINTC','usCRM','usADBE',
        ]
    
    def _filter_a(self, q: StockQuote) -> bool:
        """A股过滤"""
        if self.cfg.exclude_st and 'ST' in q.name:
            return False
        if q.price <= 0:
            return False
        amount = q.amount  # 已经是元
        if not (self.cfg.a_min_amount <= amount <= self.cfg.a_max_amount):
            return False
        if not (self.cfg.a_min_turnover <= q.turnover_rate <= self.cfg.a_max_turnover):
            return False
        if not (self.cfg.a_min_change <= q.change_pct <= self.cfg.a_max_change):
            return False
        if q.pe > self.cfg.a_max_pe:
            return False
        return True
    
    def _filter_hk(self, q: StockQuote) -> bool:
        """港股过滤"""
        if q.price <= 0:
            return False
        amount = q.amount  # 港元
        if not (self.cfg.hk_min_amount <= amount <= self.cfg.hk_max_amount):
            return False
        if not (self.cfg.hk_min_turnover <= q.turnover_rate <= self.cfg.hk_max_turnover):
            return False
        if not (self.cfg.hk_min_change <= q.change_pct <= self.cfg.hk_max_change):
            return False
        if q.pe > self.cfg.hk_max_pe:
            return False
        return True
    
    def _filter_us(self, q: StockQuote) -> bool:
        """美股过滤"""
        if q.price <= 0:
            return False
        amount = q.amount  # 美元
        if not (self.cfg.us_min_amount <= amount <= self.cfg.us_max_amount):
            return False
        if not (self.cfg.us_min_turnover <= q.turnover_rate <= self.cfg.us_max_turnover):
            return False
        if not (self.cfg.us_min_change <= q.change_pct <= self.cfg.us_max_change):
            return False
        if q.pe > self.cfg.us_max_pe:
            return False
        return True
    
    def _score_with_tech(self, q: StockQuote, market: str) -> Tuple[float, List[str], Dict, Dict]:
        """打分 + 技术指标"""
        score = 0.0
        reasons = []
        factors = {}
        tech = {}
        
        # 基础因子打分（沿用原逻辑）
        # 涨幅得分
        if 3.0 <= q.change_pct <= 5.0:
            score += 30
            reasons.append("涨幅适中")
            factors['涨幅'] = 30
        elif 2.0 <= q.change_pct <= 6.0:
            score += 20
            reasons.append("涨幅合理")
            factors['涨幅'] = 20
        elif q.change_pct >= 1.0:
            score += 10
            factors['涨幅'] = 10
        
        # 成交额得分（港股美股已是元/美元，A股需要计算）
        amount_yi = q.amount / 1e8
        if market == 'A' and q.volume > 0:
            # A股amount字段是股数，需要用价格计算
            amount_yi = (q.price * q.amount) / 1e8
        
        if amount_yi >= 10:
            score += 25
            reasons.append(f"成交额{amount_yi:.0f}亿")
            factors['成交额'] = 25
        elif amount_yi >= 5:
            score += 15
            factors['成交额'] = 15
        
        # 换手率得分
        if 5.0 <= q.turnover_rate <= 10.0:
            score += 20
            reasons.append(f"换手率{q.turnover_rate:.1f}%")
            factors['换手率'] = 20
        elif 3.0 <= q.turnover_rate <= 12.0:
            score += 10
            factors['换手率'] = 10
        
        # PE得分
        if 10 <= q.pe <= 30:
            score += 15
            reasons.append(f"PE={q.pe:.0f}")
            factors['估值'] = 15
        elif q.pe > 0 and q.pe <= 50:
            score += 8
            factors['估值'] = 8
        
        # 技术指标（尝试获取K线，失败则跳过）
        try:
            klines = self._get_klines(q.code, market)
            if klines and len(klines) >= 26:
                closes = [k.close for k in klines]
                
                # RSI
                rsi = calc_rsi(closes, 14)
                tech['rsi'] = rsi
                
                # RSI得分：30-50区间（超卖反弹）加分
                if 30 <= rsi <= 50:
                    score += 15
                    reasons.append(f"RSI={rsi:.0f}超卖反弹")
                    factors['RSI'] = 15
                elif 50 <= rsi <= 70:
                    score += 10
                    factors['RSI'] = 10
                elif rsi > 80:
                    score -= 10  # 超买扣分
                    factors['RSI'] = -10
                
                # MACD
                dif, dea, macd_bar = calc_macd(closes)
                if macd_bar > 0 and dif > dea:
                    tech['macd_signal'] = '金叉'
                    score += 15
                    reasons.append("MACD金叉")
                    factors['MACD'] = 15
                elif macd_bar < 0 and dif < dea:
                    tech['macd_signal'] = '死叉'
                    score -= 5
                    factors['MACD'] = -5
                
                # MA支撑
                ma5 = calc_ma(closes, 5)
                ma10 = calc_ma(closes, 10)
                ma20 = calc_ma(closes, 20)
                
                if q.price > ma5 > ma10 > ma20:
                    score += 10
                    reasons.append("均线多头排列")
                    factors['均线'] = 10
            else:
                # 无K线数据时，用简化版得分（基于涨幅趋势）
                if q.change_pct >= 3.0:
                    score += 5
                    factors['趋势'] = 5
        except Exception as e:
            logger.debug(f"技术指标计算跳过 {q.code}: {e}")
            # 简化版得分
            if q.change_pct >= 3.0:
                score += 5
                factors['趋势'] = 5
        
        return score, reasons, factors, tech
    
    def _get_klines(self, code: str, market: str) -> List[KlineBar]:
        """获取K线数据"""
        # 根据市场构造完整代码
        if market == 'A':
            full_code = code  # 已经是 sh600000 格式
        elif market == 'HK':
            full_code = code  # 已经是 hk00700 格式
        elif market == 'US':
            full_code = code  # 已经是 usAAPL 格式
        else:
            return []
        
        return self.client.get_kline(full_code, days=60)


# 兼容别名
SimpleScanner = MultiMarketScanner
FactorScanner = MultiMarketScanner
