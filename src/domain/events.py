from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.domain.enums import EventType
from src.domain.ids import RunId, StrategyId


@dataclass(frozen=True)
class DomainEvent:
    event_type: EventType
    run_id: RunId
    strategy_id: StrategyId | None
    timestamp: datetime
    payload: dict[str, object] = field(default_factory=dict)
