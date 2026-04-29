from __future__ import annotations

from dataclasses import dataclass

from src.domain.models.signal import Signal, TargetPosition
from src.domain.models.strategy import StrategyContext, StrategyMetadata
from src.domain.ports.strategy_port import StrategyPort


@dataclass
class BaseStrategy(StrategyPort):
    _metadata: StrategyMetadata

    def metadata(self) -> StrategyMetadata:
        return self._metadata

    def on_bar(self, context: StrategyContext) -> list[Signal] | list[TargetPosition]:
        raise NotImplementedError("Strategy must implement on_bar().")
