from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.domain.ids import RunId, StrategyId
from src.domain.models.market import Bar
from src.domain.models.portfolio import Portfolio


@dataclass(frozen=True)
class StrategyMetadata:
    strategy_id: StrategyId
    name: str
    version: str
    author: str = ""


@dataclass(frozen=True)
class StrategyConfig:
    params: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyContext:
    run_id: RunId
    as_of: datetime
    bars: list[Bar]
    portfolio: Portfolio
    config: StrategyConfig
    metadata: StrategyMetadata
