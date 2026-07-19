"""
Qullamaggie Breakout Strategy
实现 StrategyPort 协议，可接入回测引擎和信号管线。

核心参数 (Phase 0 扫描确定):
  score_min=28, max_positions=5, risk_per_trade=1%
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import List, Dict

from src.domain.enums import SignalDirection
from src.domain.ids import SignalId, StrategyId
from src.domain.models.signal import Signal, TargetPosition
from src.domain.models.strategy import StrategyContext, StrategyMetadata, StrategyConfig

from .breakout_scorer import is_breakout_signal

STRATEGY_ID = StrategyId("breakout-v1")
STRATEGY_META = StrategyMetadata(
    strategy_id=STRATEGY_ID,
    name="Qullamaggie Breakout",
    version="1.0.0",
    author="quant-research",
)

# Phase 0 最优参数
DEFAULT_MIN_SCORE = 28
DEFAULT_MAX_POS = 5
DEFAULT_RISK = Decimal("0.01")


@dataclass
class BreakoutStrategy:
    """Qullamaggie 台阶突破策略"""

    _metadata: StrategyMetadata = STRATEGY_META
    score_min: int = DEFAULT_MIN_SCORE
    max_positions: int = DEFAULT_MAX_POS
    risk_per_trade: Decimal = DEFAULT_RISK

    def metadata(self) -> StrategyMetadata:
        return self._metadata

    def on_bar(self, context: StrategyContext) -> List[Signal]:
        """
        逐日扫描持仓股，返回信号。

        每次调用只扫描 bars 中最后一根是否触发突破信号。
        """
        signals: List[Signal] = []
        config = context.config
        score_min = int(config.params.get("score_min", self.score_min))
        
        for bar in context.bars:
            # 这里只做单股单日扫描；批量和全市场扫描用 BreakoutScanner
            pass
        
        return signals

    def scan_symbol(
        self,
        candles: List[dict],
        symbol: str,
        timestamp: datetime,
    ) -> Signal | None:
        """
        扫描单只股票的 K 线序列，返回是否产生信号。
        
        Args:
            candles: 历史 K 线 (至少 lookback+1 根)
            symbol: 股票代码
            timestamp: 当前时间

        Returns:
            Signal 或 None
        """
        if len(candles) < 121:
            return None
        
        idx = len(candles) - 1
        ok, score, details, entry = is_breakout_signal(candles, idx, self.score_min)
        
        if not ok:
            return None
        
        return Signal(
            signal_id=SignalId(f"{symbol}_{timestamp.strftime('%Y%m%d')}"),
            strategy_id=self._metadata.strategy_id,
            symbol=symbol,
            timestamp=timestamp,
            direction=SignalDirection.LONG,
            strength=Decimal(str(round(score / 28.0, 4))),
            reason=" | ".join(details),
            metadata={
                "score": str(score),
                "entry": f"{entry:.2f}",
                "strategy": "breakout",
            },
        )
