"""
布林带策略 (Bollinger Bands)
价格触及下轨买入，触及上轨卖出。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
import uuid

from src.domain.enums import SignalDirection
from src.domain.ids import SignalId, StrategyId
from src.domain.models.signal import Signal
from src.domain.models.strategy import StrategyMetadata, StrategyContext
from src.strategies.base import BaseStrategy


class BollingerBandsStrategy(BaseStrategy):
    def __init__(
        self,
        strategy_id: str = "bollinger_bands",
        name: str = "Bollinger Bands",
        version: str = "0.1.0",
        window: int = 20,
        num_std: float = 2.0,
        exit_threshold: float = 0.0,
    ) -> None:
        super().__init__(
            _metadata=StrategyMetadata(
                strategy_id=StrategyId(strategy_id), name=name, version=version, author="copilot",
            )
        )
        self.window = window
        self.num_std = num_std
        self.exit_threshold = exit_threshold
        self._current_direction: SignalDirection | None = None

    def on_bar(self, context: StrategyContext) -> list[Signal]:
        bars = context.bars
        if len(bars) < self.window:
            return []

        closes = [bar.close for bar in bars]
        sma = sum(closes[-self.window:]) / Decimal(str(self.window))
        variance = sum((c - sma) ** 2 for c in closes[-self.window:]) / Decimal(str(self.window))
        std = float(variance) ** 0.5

        latest = bars[-1]
        current = float(latest.close)
        upper = float(sma) + self.num_std * std
        lower = float(sma) - self.num_std * std

        if current <= lower:
            new_direction = SignalDirection.LONG
            reason = f"close({current:.2f}) <= lower_band({lower:.2f})"
        elif current >= upper:
            new_direction = SignalDirection.SHORT
            reason = f"close({current:.2f}) >= upper_band({upper:.2f})"
        elif self.exit_threshold > 0 and abs(current - float(sma)) < self.exit_threshold * std:
            new_direction = SignalDirection.FLAT
            reason = f"close({current:.2f})回归SMA({float(sma):.2f})"
        else:
            return []

        if new_direction == self._current_direction:
            return []
        self._current_direction = new_direction

        return [Signal(
            signal_id=SignalId(str(uuid.uuid4())),
            strategy_id=context.metadata.strategy_id,
            symbol=latest.symbol,
            timestamp=latest.timestamp,
            direction=new_direction,
            strength=Decimal("1.0"),
            reason=reason,
            metadata={"window": str(self.window), "num_std": str(self.num_std),
                      "sma": str(round(sma, 4)), "upper": f"{upper:.4f}", "lower": f"{lower:.4f}"},
        )]
