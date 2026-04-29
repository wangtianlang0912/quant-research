from __future__ import annotations

from datetime import datetime

from src.domain.ports.clock_port import ClockPort


class SystemClock(ClockPort):
    def now(self) -> datetime:
        return datetime.now()
