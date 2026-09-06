"""行情数据与交易日历端口（§5.2）。

★ **`BarRequest.adjust` 无默认值** —— 这是根治 v1「全项目从未请求过复权」的**类型层**手段。

v1 的 `backtest_runner.py:203` 调用 `get_bars` 时不传 `adjust_type`，
默认 `AdjustType.NONE`，于是 QFQ/HFQ 从未被真正使用过；
而 `local_csv_adapter.py:56` 又把传入的 `adjust_type` 当标签贴上、数据原样返回。
两层失效叠加，导致 v1 的所有回测都跑在未复权数据上，除权日全是假跳空。

v2：不显式声明口径就构造不出请求 —— "默认不复权"从此不可能。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable

from quant_v2.domain.models.bar import AdjustType, Bar, InstrumentType
from quant_v2.domain.models.instrument import Instrument
from quant_v2.domain.models.market import Availability

__all__ = [
    "BarRequest",
    "DataCapabilities",
    "MarketDataAdapter",
    "SourceHealth",
    "TradingCalendar",
    "TradingDay",
]


@dataclass(frozen=True)
class BarRequest:
    """行情请求。

    ★ `adjust` **无默认值**：调用方必须显式声明复权口径。
    """

    symbols: tuple[str, ...]
    market: str
    start: date
    end: date
    adjust: AdjustType  # ★ 必填，无默认
    instrument_types: tuple[InstrumentType, ...] = (InstrumentType.EQUITY,)

    def __post_init__(self) -> None:
        """请求自洽性校验。"""
        if not self.symbols:
            raise ValueError("BarRequest.symbols 不可为空：空请求应该由调用方提前短路")
        if self.start > self.end:
            raise ValueError(f"start({self.start}) 不能晚于 end({self.end})")
        if not self.instrument_types:
            raise ValueError("BarRequest.instrument_types 不可为空")


@dataclass(frozen=True)
class DataCapabilities:
    """数据源能力声明。

    复用 `domain.models.market.DataCapabilities` 的定义，
    这里再导出一次是为了让端口文件自包含（读端口的人不必跳去 models）。
    """

    daily_bars: bool = True
    adj_factor: bool = True
    delisting_history: Availability = "NONE"  # ★ OQ-8 关键开关
    delisting_list: bool = False
    trading_calendar: bool = True
    fundamentals: bool = False
    intraday: bool = False
    rate_limit_per_min: int | None = None


@dataclass(frozen=True)
class SourceHealth:
    """数据源健康检查结果 —— `healthcheck()` 的返回值。"""

    source_id: str
    ok: bool
    checked_at: datetime
    latency_ms: int = 0
    detail: str = ""


@dataclass(frozen=True)
class TradingDay:
    """单个交易日的会话信息（含半天市，D-07）。"""

    market: str
    date: date
    is_half_day: bool = False
    session_open: datetime | None = None
    session_close: datetime | None = None


@runtime_checkable
class MarketDataAdapter(Protocol):
    """行情数据源端口。

    **实现类放在 `adapters/market_data/`**，引擎与策略只依赖这个 Protocol。
    """

    source_id: str
    supported_markets: frozenset[str]
    capabilities: DataCapabilities

    def healthcheck(self) -> SourceHealth:
        """健康检查：启动与每次调用前执行；失败即降级**并告警**（D-10）。

        ★ 失败必须告警：v1 的静默降级让"主源挂了 40 天"这件事无人知晓。
        """
        ...

    def list_instruments(self, market: str, *, as_of: date) -> Sequence[Instrument]:
        """列出标的。

        ★ `as_of` 语义：返回"**当时**在市"的标的。
        能力不足时必须在 `capabilities.delisting_history` 如实声明，
        **不许假装能给**（那是幸存者偏差的入口）。
        """
        ...

    def fetch_bars(self, req: BarRequest) -> Sequence[Bar]:
        """取日线。

        返回的 `Bar` 价格恒为 RAW，`adj_factor` 必填。
        缺 `adj_factor` 时必须把 `source` 标记为 `legacy` 并告警。
        """
        ...

    def fetch_trading_calendar(self, market: str, year: int) -> Sequence[TradingDay]:
        """取交易日历（含半天市）。"""
        ...


@runtime_checkable
class TradingCalendar(Protocol):
    """交易日历端口。

    **实现要点**：日历数据来自 `MarketProfile.calendar_id` + `extra_holidays`
    + `half_day_dates`（YAML），**零 if 分支**。
    """

    def is_trading_day(self, market: str, day: date) -> bool:
        """是否为交易日。"""
        ...

    def next_trading_day(self, market: str, day: date, *, n: int = 1) -> date:
        """第 n 个交易日之后（n=1 即下一个交易日）。"""
        ...

    def previous_trading_day(self, market: str, day: date, *, n: int = 1) -> date:
        """往前数第 n 个交易日。"""
        ...

    def trading_days_between(self, market: str, start: date, end: date) -> Sequence[date]:
        """区间内的全部交易日（含端点）。"""
        ...

    def session_close(self, market: str, day: date) -> datetime:
        """收盘时刻。★ 半天市返回提前收盘时间（D-07）。"""
        ...
