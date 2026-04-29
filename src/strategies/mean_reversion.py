from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import uuid

from src.domain.enums import SignalDirection
from src.domain.ids import SignalId, StrategyId
from src.domain.models.signal import Signal
from src.domain.models.strategy import StrategyContext, StrategyMetadata
from src.strategies.base import BaseStrategy


@dataclass
class MeanReversionStrategy(BaseStrategy):
    lookback_window: int = 20
    entry_zscore: Decimal = Decimal("2.0")
    exit_zscore: Decimal = Decimal("0.5")

    def __init__(
        self,
        strategy_id: str = "mean_reversion",
        name: str = "Mean Reversion",
        version: str = "0.1.0",
        lookback_window: int = 20,
        entry_zscore: Decimal = Decimal("2.0"),
        exit_zscore: Decimal = Decimal("0.5"),
    ) -> None:
        """初始化均值回归策略元数据与关键参数。"""
        super().__init__(
            _metadata=StrategyMetadata(
                strategy_id=StrategyId(strategy_id),
                name=name,
                version=version,
                author="copilot",
            )
        )
        self.lookback_window = lookback_window
        self.entry_zscore = entry_zscore
        self.exit_zscore = exit_zscore

    def on_bar(self, context: StrategyContext) -> list[Signal]:
        """基于价格相对均值的偏离程度生成均值回归信号。"""
        bars = context.bars
        if len(bars) < self.lookback_window:
            return []

        closes = [bar.close for bar in bars[-self.lookback_window:]]
        latest = bars[-1]
        mean_price = sum(closes) / Decimal(str(len(closes)))
        variance = sum((price - mean_price) ** 2 for price in closes) / Decimal(str(len(closes)))
        std_price = Decimal(str(float(variance) ** 0.5))
        if std_price == 0:
            return []

        zscore = (latest.close - mean_price) / std_price
        if zscore <= -self.entry_zscore:
            direction = SignalDirection.LONG
            reason = f"zscore({zscore}) <= -entry_zscore({self.entry_zscore})"
        elif zscore >= self.entry_zscore:
            direction = SignalDirection.SHORT
            reason = f"zscore({zscore}) >= entry_zscore({self.entry_zscore})"
        elif abs(zscore) <= self.exit_zscore:
            direction = SignalDirection.FLAT
            reason = f"abs(zscore({zscore})) <= exit_zscore({self.exit_zscore})"
        else:
            return []

        return [
            Signal(
                signal_id=SignalId(str(uuid.uuid4())),
                strategy_id=context.metadata.strategy_id,
                symbol=latest.symbol,
                timestamp=latest.timestamp,
                direction=direction,
                strength=Decimal("1.0"),
                reason=reason,
                metadata={
                    "lookback_window": str(self.lookback_window),
                    "entry_zscore": str(self.entry_zscore),
                    "exit_zscore": str(self.exit_zscore),
                    "zscore": str(zscore),
                },
            )
        ]
