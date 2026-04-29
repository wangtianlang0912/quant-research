from __future__ import annotations

from typing import Protocol

from src.domain.models.signal import Signal, TargetPosition
from src.domain.models.strategy import StrategyContext, StrategyMetadata


class StrategyPort(Protocol):
    def metadata(self) -> StrategyMetadata:
        ...

    def on_bar(self, context: StrategyContext) -> list[Signal] | list[TargetPosition]:
        ...
