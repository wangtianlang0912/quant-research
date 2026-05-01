from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from src.domain.enums import AdjustType, Frequency
from src.domain.exceptions import DataError
from src.domain.models.market import Bar, Quote
from src.domain.ports.market_data_port import BaseRemoteMarketDataAdapter


@dataclass
class AkshareAdapter(BaseRemoteMarketDataAdapter):
    """AKShare 外部数据源适配器最小可用实现。"""

    source_name: str = "akshare"

    def _client(self):
        try:
            import akshare as ak  # type: ignore
        except ImportError as exc:
            raise DataError("akshare is not installed. Please install akshare before using AkshareAdapter.") from exc
        return ak

    def get_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        frequency: Frequency,
        adjust_type: AdjustType = AdjustType.NONE,
    ) -> list[Bar]:
        ak = self._client()
        interval = self._to_akshare_interval(frequency)
        try:
            if frequency == Frequency.DAY_1:
                frame = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust=self._to_akshare_adjust(adjust_type),
                )
            else:
                frame = ak.stock_zh_a_hist_min_em(
                    symbol=symbol,
                    period=interval,
                    start_date=start.strftime("%Y-%m-%d %H:%M:%S"),
                    end_date=end.strftime("%Y-%m-%d %H:%M:%S"),
                    adjust=self._to_akshare_adjust(adjust_type),
                )
        except Exception as exc:  # pragma: no cover - external dependency branch
            raise DataError(f"Failed to fetch bars from AKShare for {symbol}: {exc}") from exc
        if frame is None or frame.empty:
            return []
        return [self._row_to_bar(symbol, row, frequency, adjust_type) for _, row in frame.iterrows()]

    def get_latest_bar(self, symbol: str, frequency: Frequency) -> Bar | None:
        end = datetime.now()
        start = end - timedelta(days=7 if frequency == Frequency.DAY_1 else 2)
        bars = self.get_bars(symbol=symbol, start=start, end=end, frequency=frequency)
        return bars[-1] if bars else None

    def get_latest_quote(self, symbol: str) -> Quote | None:
        bar = self.get_latest_bar(symbol, self.default_frequency)
        if bar is None:
            return None
        return Quote(
            symbol=symbol,
            timestamp=bar.timestamp,
            bid=bar.close,
            ask=bar.close,
            last=bar.close,
            volume=bar.volume,
            source=self.source_name,
        )

    def list_trading_days(self, start: date, end: date) -> list[date]:
        ak = self._client()
        try:
            frame = ak.tool_trade_date_hist_sina()
        except Exception:
            return super().list_trading_days(start, end)
        if frame is None or frame.empty:
            return super().list_trading_days(start, end)
        results: list[date] = []
        for value in frame.iloc[:, 0].tolist():
            current = value.date() if hasattr(value, "date") else datetime.fromisoformat(str(value)).date()
            if start <= current <= end:
                results.append(current)
        return results or super().list_trading_days(start, end)

    def _row_to_bar(self, symbol: str, row, frequency: Frequency, adjust_type: AdjustType) -> Bar:
        timestamp_value = row.get("日期") or row.get("时间") or row.get("datetime") or row.get("timestamp")
        ts = timestamp_value if isinstance(timestamp_value, datetime) else datetime.fromisoformat(str(timestamp_value))
        return Bar(
            symbol=symbol,
            timestamp=ts,
            open=Decimal(str(row.get("开盘", row.get("open", 0)))),
            high=Decimal(str(row.get("最高", row.get("high", 0)))),
            low=Decimal(str(row.get("最低", row.get("low", 0)))),
            close=Decimal(str(row.get("收盘", row.get("close", 0)))),
            volume=Decimal(str(row.get("成交量", row.get("volume", 0)))),
            amount=Decimal(str(row.get("成交额", row.get("amount", 0)))) if row.get("成交额", row.get("amount")) is not None else None,
            frequency=frequency,
            adjust_type=adjust_type,
            source=self.source_name,
            metadata={"provider": self.source_name},
        )

    def _to_akshare_interval(self, frequency: Frequency) -> str:
        mapping = {
            Frequency.DAY_1: "daily",
            Frequency.MIN_1: "1",
            Frequency.MIN_5: "5",
            Frequency.MIN_15: "15",
            Frequency.MIN_30: "30",
            Frequency.MIN_60: "60",
        }
        return mapping[frequency]

    def _to_akshare_adjust(self, adjust_type: AdjustType) -> str:
        mapping = {
            AdjustType.NONE: "",
            AdjustType.QFQ: "qfq",
            AdjustType.HFQ: "hfq",
        }
        return mapping[adjust_type]
