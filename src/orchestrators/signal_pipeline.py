from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.domain.events import DomainEvent
from src.domain.ids import SignalId
from src.domain.models.signal import Signal, TargetPosition
from src.domain.models.strategy import StrategyContext
from src.domain.ports.repository_port import EventRepositoryPort
from src.domain.ports.strategy_port import StrategyPort
from src.domain.enums import EventType


@dataclass
class SignalPipeline:
    strategy: StrategyPort
    event_repository: EventRepositoryPort | None = None

    def run(self, context: StrategyContext) -> list[Signal] | list[TargetPosition]:
        outputs = self.strategy.on_bar(context)
        if self.event_repository is not None:
            payload = {
                "output_count": len(outputs),
                "symbols": sorted({getattr(item, "symbol", "") for item in outputs}),
            }
            self.event_repository.append(
                DomainEvent(
                    event_type=EventType.SIGNAL_GENERATED,
                    run_id=context.run_id,
                    strategy_id=context.metadata.strategy_id,
                    timestamp=datetime.now(),
                    payload=payload,
                )
            )
        return outputs
