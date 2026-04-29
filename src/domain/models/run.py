from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from src.domain.enums import Frequency, RunMode
from src.domain.ids import RunId, StrategyId


@dataclass(frozen=True)
class RunContext:
    run_id: RunId
    mode: RunMode
    strategy_id: StrategyId
    symbols: list[str]
    frequency: Frequency
    start_date: date
    end_date: date
    created_at: datetime
    environment: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RunSummary:
    run_id: RunId
    mode: RunMode
    started_at: datetime
    finished_at: datetime | None
    status: str
    message: str = ""
    final_equity: Decimal | None = None
    total_return: Decimal | None = None
    max_drawdown: Decimal | None = None
    sharpe_ratio: Decimal | None = None
