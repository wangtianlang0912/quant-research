from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from src.domain.enums import AdjustType, Frequency
from src.domain.models.market import Bar, Quote


class MarketDataPort(Protocol):
    def get_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        frequency: Frequency,
        adjust_type: AdjustType = AdjustType.NONE,
    ) -> list[Bar]:
        ...

    def get_latest_bar(self, symbol: str, frequency: Frequency) -> Bar | None:
        ...

    def get_latest_quote(self, symbol: str) -> Quote | None:
        ...

    def list_trading_days(self, start: date, end: date) -> list[date]:
        ...
