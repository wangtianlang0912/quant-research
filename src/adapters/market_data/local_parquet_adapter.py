from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from src.domain.enums import AdjustType, Frequency
from src.domain.exceptions import DataError
from src.domain.models.market import Bar, Quote
from src.domain.ports.market_data_port import MarketDataPort


@dataclass
class LocalParquetAdapter(MarketDataPort):
    """基于本地CSV文件实现的简化行情适配器，用于MVP阶段快速打通回测。"""

    base_path: str

    def _csv_path(self, symbol: str, frequency: Frequency) -> Path:
        """根据标的和周期计算本地CSV文件路径。"""
        return Path(self.base_path) / frequency.value / f"{symbol}.csv"

    def get_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        frequency: Frequency,
        adjust_type: AdjustType = AdjustType.NONE,
    ) -> list[Bar]:
        """读取本地CSV中的历史K线并按时间区间过滤。"""
        path = self._csv_path(symbol, frequency)
        if not path.exists():
            raise DataError(f"Local market data file not found: {path}")

        bars: list[Bar] = []
        with path.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                ts = datetime.fromisoformat(row["timestamp"])
                if ts < start or ts > end:
                    continue
                bars.append(
                    Bar(
                        symbol=symbol,
                        timestamp=ts,
                        open=Decimal(row["open"]),
                        high=Decimal(row["high"]),
                        low=Decimal(row["low"]),
                        close=Decimal(row["close"]),
                        volume=Decimal(row.get("volume", "0")),
                        amount=Decimal(row["amount"]) if row.get("amount") else None,
                        frequency=frequency,
                        adjust_type=adjust_type,
                        source="local_csv",
                    )
                )
        return bars

    def get_latest_bar(self, symbol: str, frequency: Frequency) -> Bar | None:
        """获取本地数据中的最新一根K线。"""
        path = self._csv_path(symbol, frequency)
        if not path.exists():
            return None
        last_bar: Bar | None = None
        with path.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                last_bar = Bar(
                    symbol=symbol,
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    open=Decimal(row["open"]),
                    high=Decimal(row["high"]),
                    low=Decimal(row["low"]),
                    close=Decimal(row["close"]),
                    volume=Decimal(row.get("volume", "0")),
                    amount=Decimal(row["amount"]) if row.get("amount") else None,
                    frequency=frequency,
                    source="local_csv",
                )
        return last_bar

    def get_latest_quote(self, symbol: str) -> Quote | None:
        """使用最新日线收盘价构造一份简化报价。"""
        bar = self.get_latest_bar(symbol, Frequency.DAY_1)
        if bar is None:
            return None
        return Quote(
            symbol=symbol,
            timestamp=bar.timestamp,
            bid=bar.close,
            ask=bar.close,
            last=bar.close,
            volume=bar.volume,
            source="local_csv",
        )

    def list_trading_days(self, start: date, end: date) -> list[date]:
        """返回简化版交易日列表，当前以工作日近似表示。"""
        days: list[date] = []
        current = start
        while current <= end:
            if current.weekday() < 5:
                days.append(current)
            current += timedelta(days=1)
        return days
