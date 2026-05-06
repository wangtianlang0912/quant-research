"""
简化扫描器 - 仅用实时行情，不依赖历史K线
"""
from __future__ import annotations
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, field
import logging

from src.data.akshare_client import TencentClient, StockQuote

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """扫描结果"""
    code: str
    name: str
    score: float
    price: float
    change_pct: float
    reasons: List[str]
    factors: Dict[str, float] = field(default_factory=dict)
    suggested_entry: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0


@dataclass
class ScanConfig:
    """扫描配置"""
    min_amount: float = 3e8      # 最小成交额3亿
    max_amount: float = 50e8     # 最大成交额50亿
    min_turnover: float = 3.0    # 最小换手率
    max_turnover: float = 15.0   # 最大换手率
    min_change: float = 1.0      # 最小涨跌幅（正收益）
    max_change: float = 6.0      # 最大涨跌幅（不追涨停）
    min_pe: float = 0            # 最小PE
    max_pe: float = 100          # 最大PE（排除超高估值）
    exclude_st: bool = True
    exclude_new_high: bool = True  # 排除近期涨幅过大
    top_n: int = 10


class SimpleScanner:
    """简化扫描器 - 实时数据筛选"""
    
    def __init__(self, config: Optional[ScanConfig] = None):
        self.cfg = config or ScanConfig()
        self.client = TencentClient()
    
    def scan(self) -> List[ScanResult]:
        """执行扫描"""
        logger.info("开始扫描...")
        
        # 获取A股行情（分批获取主要股票）
        stocks = self._get_main_stocks()
        if not stocks:
            logger.error("获取股票失败")
            return []
        
        logger.info(f"获取 {len(stocks)} 只股票")
        
        # 过滤筛选
        candidates = self._filter(stocks)
        logger.info(f"过滤后 {len(candidates)} 只")
        
        # 打分排序
        results = []
        for s in candidates:
            try:
                score, reasons, factors = self._score(s)
                if score > 30:  # 最低得分阈值
                    results.append(ScanResult(
                        code=s.code,
                        name=s.name,
                        score=score,
                        price=s.price,
                        change_pct=s.change_pct,
                        reasons=reasons,
                        factors=factors,
                        suggested_entry=s.price * 0.98,
                        stop_loss=s.price * 0.93,
                        take_profit=s.price * 1.08
                    ))
            except Exception:
                continue
        
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:self.cfg.top_n]
    
    def _get_main_stocks(self) -> List[StockQuote]:
        """获取主要A股（沪深300成分股+热门股）"""
        # 沪深300主要代码（前100个代表性股票）
        main_codes = [
            # 沪市蓝筹
            'sh600000', 'sh600009', 'sh600010', 'sh600011', 'sh600015',
            'sh600016', 'sh600017', 'sh600018', 'sh600019', 'sh600028',
            'sh600029', 'sh600030', 'sh600031', 'sh600033', 'sh600036',
            'sh600048', 'sh600050', 'sh600104', 'sh600109', 'sh600111',
            'sh600115', 'sh600118', 'sh600150', 'sh600176', 'sh600183',
            'sh600196', 'sh600208', 'sh600233', 'sh600276', 'sh600309',
            'sh600332', 'sh600346', 'sh600352', 'sh600406', 'sh600436',
            'sh600438', 'sh600482', 'sh600486', 'sh600489', 'sh600519',
            'sh600547', 'sh600570', 'sh600585', 'sh600588', 'sh600600',
            'sh600660', 'sh600703', 'sh600745', 'sh600809', 'sh600837',
            'sh600887', 'sh600893', 'sh600900', 'sh600919', 'sh600926',
            'sh600941', 'sh601012', 'sh601066', 'sh601088', 'sh601111',
            'sh601138', 'sh601166', 'sh601169', 'sh601186', 'sh601211',
            'sh601225', 'sh601238', 'sh601288', 'sh601318', 'sh601328',
            'sh601336', 'sh601377', 'sh601390', 'sh601398', 'sh601601',
            'sh601628', 'sh601668', 'sh601669', 'sh601688', 'sh601728',
            'sh601808', 'sh601818', 'sh601857', 'sh601888', 'sh601899',
            'sh601918', 'sh601919', 'sh601939', 'sh601988', 'sh601989',
            # 深市蓝筹
            'sz000001', 'sz000002', 'sz000063', 'sz000066', 'sz000069',
            'sz000100', 'sz000157', 'sz000333', 'sz000338', 'sz000425',
            'sz000538', 'sz000568', 'sz000596', 'sz000625', 'sz000651',
            'sz000661', 'sz000671', 'sz000703', 'sz000708', 'sz000725',
            'sz000768', 'sz000776', 'sz000783', 'sz000786', 'sz000858',
            'sz000876', 'sz000895', 'sz000938', 'sz000963', 'sz001979',
            'sz002001', 'sz002007', 'sz002008', 'sz002027', 'sz002030',
            'sz002044', 'sz002049', 'sz002050', 'sz002057', 'sz002060',
            'sz002129', 'sz002142', 'sz002153', 'sz002230', 'sz002236',
            'sz002241', 'sz002271', 'sz002304', 'sz002311', 'sz002352',
            'sz002371', 'sz002384', 'sz002410', 'sz002415', 'sz002475',
            'sz002594', 'sz002600', 'sz002601', 'sz002602', 'sz002607',
            'sz002624', 'sz002648', 'sz002670', 'sz002714', 'sz002821',
            'sz002841', 'sz002920', 'sz003816',
            # 创业板龙头
            'sz300003', 'sz300014', 'sz300015', 'sz300033', 'sz300059',
            'sz300124', 'sz300142', 'sz300408', 'sz300450', 'sz300750'
        ]
        
        return self.client._get_quotes(main_codes)
    
    def _filter(self, stocks: List[StockQuote]) -> List[StockQuote]:
        """初步过滤"""
        filtered = []
        for s in stocks:
            # 排除ST
            if self.cfg.exclude_st and 'ST' in s.name:
                continue
            # 排除退市/停牌（价格为0）
            if s.price <= 0:
                continue
            # 成交额过滤
            # 注意：腾讯返回的amount单位可能是"万"，需要转换
            amount = s.amount * 10000  # 万 -> 元
            if amount < self.cfg.min_amount:
                continue
            if amount > self.cfg.max_amount:
                continue
            # 换手率
            if not (self.cfg.min_turnover <= s.turnover_rate <= self.cfg.max_turnover):
                continue
            # 涨跌幅（寻找上涨但未涨停）
            if not (self.cfg.min_change <= s.change_pct <= self.cfg.max_change):
                continue
            # PE过滤
            if s.pe > self.cfg.max_pe or (s.pe < self.cfg.min_pe and s.pe > 0):
                continue
            filtered.append(s)
        return filtered
    
    def _score(self, s: StockQuote) -> tuple:
        """打分"""
        score = 0.0
        reasons = []
        factors = {}
        
        # 涨幅得分（3-5%最佳）
        if 3.0 <= s.change_pct <= 5.0:
            score += 30
            reasons.append("涨幅适中")
            factors['涨幅'] = 30
        elif 2.0 <= s.change_pct <= 6.0:
            score += 20
            reasons.append("涨幅合理")
            factors['涨幅'] = 20
        elif s.change_pct >= 1.0:
            score += 10
            factors['涨幅'] = 10
        
        # 成交额得分（活跃度）
        amount = s.amount * 10000
        if amount >= 10e8:  # 10亿+
            score += 25
            reasons.append(f"成交额{amount/1e8:.1f}亿")
            factors['成交额'] = 25
        elif amount >= 5e8:
            score += 15
            factors['成交额'] = 15
        
        # 换手率得分
        if 5.0 <= s.turnover_rate <= 10.0:
            score += 20
            reasons.append(f"换手率{s.turnover_rate:.1f}%")
            factors['换手率'] = 20
        elif 3.0 <= s.turnover_rate <= 12.0:
            score += 10
            factors['换手率'] = 10
        
        # PE得分（估值合理）
        if 10 <= s.pe <= 30:
            score += 15
            reasons.append(f"PE={s.pe:.0f}")
            factors['估值'] = 15
        elif s.pe > 0 and s.pe <= 50:
            score += 8
            factors['估值'] = 8
        
        return score, reasons, factors


# 兼容别名
FactorScanner = SimpleScanner