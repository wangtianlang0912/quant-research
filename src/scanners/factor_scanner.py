"""
多市场因子扫描器 - 支持A股/港股/美股 + 技术指标
"""
from __future__ import annotations
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
import logging

from src.data.akshare_client import TencentClient, StockQuote, KlineBar

logger = logging.getLogger(__name__)


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
        
        return all_results[:self.cfg.top_n]
    
    def _scan_a(self) -> List[ScanResult]:
        """扫描A股"""
        codes = self._get_a_codes()
        quotes = self.client._get_quotes(codes)
        
        results = []
        for q in quotes:
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
                        stop_loss=q.price * 0.93,
                        take_profit=q.price * 1.08,
                        rsi=tech.get('rsi', 50),
                        macd_signal=tech.get('macd_signal', '')
                    ))
        
        results.sort(key=lambda x: x.score, reverse=True)
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
                        stop_loss=q.price * 0.93,
                        take_profit=q.price * 1.08,
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
                        stop_loss=q.price * 0.93,
                        take_profit=q.price * 1.08,
                        rsi=tech.get('rsi', 50),
                        macd_signal=tech.get('macd_signal', '')
                    ))
        
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:self.cfg.top_n_per_market]
    
    def _get_a_codes(self) -> List[str]:
        """A股股票池 - 沪深300主要成分股"""
        return [
            # 沪市蓝筹
            'sh600000', 'sh600009', 'sh600010', 'sh600015', 'sh600016',
            'sh600017', 'sh600019', 'sh600028', 'sh600030', 'sh600036',
            'sh600048', 'sh600050', 'sh600104', 'sh600111', 'sh600150',
            'sh600176', 'sh600196', 'sh600276', 'sh600309', 'sh600332',
            'sh600346', 'sh600406', 'sh600436', 'sh600438', 'sh600519',
            'sh600585', 'sh600588', 'sh600660', 'sh600703', 'sh600745',
            'sh600809', 'sh600887', 'sh600893', 'sh600900', 'sh600941',
            'sh601012', 'sh601066', 'sh601088', 'sh601111', 'sh601138',
            'sh601166', 'sh601169', 'sh601186', 'sh601211', 'sh601225',
            'sh601288', 'sh601318', 'sh601328', 'sh601336', 'sh601390',
            'sh601398', 'sh601601', 'sh601628', 'sh601668', 'sh601669',
            'sh601688', 'sh601728', 'sh601808', 'sh601818', 'sh601857',
            'sh601888', 'sh601899', 'sh601919', 'sh601939', 'sh601988',
            'sh601989',
            # 深市蓝筹
            'sz000001', 'sz000002', 'sz000063', 'sz000069', 'sz000100',
            'sz000157', 'sz000333', 'sz000338', 'sz000425', 'sz000538',
            'sz000568', 'sz000596', 'sz000625', 'sz000651', 'sz000661',
            'sz000671', 'sz000703', 'sz000725', 'sz000768', 'sz000776',
            'sz000783', 'sz000786', 'sz000858', 'sz000876', 'sz000895',
            'sz000938', 'sz000963', 'sz001979', 'sz002001', 'sz002007',
            'sz002008', 'sz002027', 'sz002030', 'sz002049', 'sz002050',
            'sz002129', 'sz002142', 'sz002230', 'sz002241', 'sz002271',
            'sz002304', 'sz002311', 'sz002352', 'sz002371', 'sz002384',
            'sz002410', 'sz002415', 'sz002475', 'sz002594', 'sz002600',
            'sz002601', 'sz002607', 'sz002624', 'sz002648', 'sz002714',
            'sz002821', 'sz002841', 'sz003816',
            # 创业板龙头
            'sz300003', 'sz300014', 'sz300015', 'sz300033', 'sz300059',
            'sz300124', 'sz300142', 'sz300408', 'sz300450', 'sz300750'
        ]
    
    def _get_hk_codes(self) -> List[str]:
        """港股股票池 - 主要蓝筹+科技"""
        return [
            'hk00700',  # 腾讯控股
            'hk00941',  # 中国移动
            'hk01810',  # 小米集团
            'hk03690',  # 美团
            'hk09988',  # 阿里巴巴
            'hk02318',  # 中国平安
            'hk02628',  # 中国人寿
            'hk00398',  # 中国银行
            'hk02328',  # 中国财险
            'hk00688',  # 中国海外发展
            'hk00883',  # 中国海洋石油
            'hk00005',  # 汇丰控股
            'hk00011',  # 恒生银行
            'hk01299',  # 友邦保险
            'hk02313',  # 申洲国际
            'hk02269',  # 药明生物
            'hk01093',  # 石药集团
            'hk00669',  # 创科实业
            'hk00268',  # 金利来
            'hk00960',  # 龙湖集团
        ]
    
    def _get_us_codes(self) -> List[str]:
        """美股股票池 - 科技龙头"""
        return [
            'usAAPL',   # 苹果
            'usMSFT',   # 微软
            'usGOOGL',  # 谷歌
            'usAMZN',   # 亚马逊
            'usNVDA',   # 英伟达
            'usMETA',   # Meta
            'usTSLA',   # 特斯拉
            'usAMD',    # AMD
            'usAVGO',   # 博通
            'usORCL',   # 甲骨文
            'usNFLX',   # 奈飞
            'usQCOM',   # 高通
            'usINTC',   # 英特尔
            'usCRM',    # Salesforce
            'usADBE',   # Adobe
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
