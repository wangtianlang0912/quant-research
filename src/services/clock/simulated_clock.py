from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.domain.ports.clock_port import ClockPort


@dataclass
class SimulatedClock(ClockPort):
    current_time: datetime

    def now(self) -> datetime:
        return self.current_time
