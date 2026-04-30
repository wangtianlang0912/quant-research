from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
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


@dataclass
class BaseRemoteMarketDataAdapter(MarketDataPort):
    """外部数据源适配器骨架，供 Tushare / AKShare 适配器复用。"""

    token: str | None = None
    default_frequency: Frequency = Frequency.DAY_1

    def get_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        frequency: Frequency,
        adjust_type: AdjustType = AdjustType.NONE,
    ) -> list[Bar]:
        """MVP 阶段返回空列表，后续由真实 API 对接替换。"""
        return []

    def get_latest_bar(self, symbol: str, frequency: Frequency) -> Bar | None:
        """MVP 阶段返回空最新K线。"""
        return None

    def get_latest_quote(self, symbol: str) -> Quote | None:
        """MVP 阶段返回空最新报价。"""
        return None

    def list_trading_days(self, start: date, end: date) -> list[date]:
        """在未接入交易所日历前，先以工作日近似表示交易日。"""
        days: list[date] = []
        current = start
        while current <= end:
            if current.weekday() < 5:
                days.append(current)
            current += timedelta(days=1)
        return days
