"""统一 Bar 契约（D-01）+ 复权三视图（D-03）。

**核心决策**：`Bar` 中的价格恒为**未复权原始价（RAW）**，`adj_factor` 为**累积后复权因子**。
三种价格视图由 `BarPanel.to_view()` 计算，不在 `Bar` 里存三份。

理由（根治 v1 的"复权零处理"）：

- v1 的 `local_csv_adapter.py:56` 只是把调用方传入的 `adjust_type` **当标签贴上**，
  数据原样返回（你请求 QFQ，它返回未复权数据并告诉你"这是 QFQ"）。
- 更糟的是 `backtest_runner.py:203` 调用 `get_bars` 时压根不传 `adjust_type`，
  默认 `AdjustType.NONE` —— **全项目 QFQ/HFQ 从未被请求过一次**。

v2 的解法：单一存储口径（RAW + 因子）+ 可互算 = 从类型与算法两层同时消灭这个 bug 类别。
配合 `BarRequest.adjust` **无默认值**，让"默认不复权"在类型层面就不可能。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期需要
    from quant_v2.domain.guard.safe_series import SafeSeries

__all__ = [
    "TRADABLE_INSTRUMENT_TYPES",
    "AdjustType",
    "Bar",
    "BarPanel",
    "InstrumentType",
    "PriceView",
]


class InstrumentType(str, Enum):
    """标的类型。

    ★ 可交易性是标的的**一等属性**（诊断 #10：v1 把沪深 300 指数当可交易标的，
    拿 `data/1d/000300.SH.csv` 当个股跑策略）。
    """

    EQUITY = "EQUITY"  # 可交易个股
    ETF = "ETF"  # 可交易基金
    INDEX = "INDEX"  # 不可直接交易，仅作基准
    FUTURE = "FUTURE"  # 期货（v2.0）


TRADABLE_INSTRUMENT_TYPES: frozenset[InstrumentType] = frozenset(
    {InstrumentType.EQUITY, InstrumentType.ETF}
)


class AdjustType(str, Enum):
    """复权口径。

    ★ 这个枚举在 `BarRequest` 中**无默认值**：不显式声明口径就构造不出请求。
    """

    RAW = "RAW"  # 未复权（原始成交价）
    FORWARD = "FORWARD"  # 前复权（以序列末日为基准，最新价 = 最新真实价）
    BACKWARD = "BACKWARD"  # 后复权（以上市首日为基准，历史价真实）


class Bar(BaseModel):
    """三市场共用的唯一日线契约。

    价格恒为 RAW；复权视图由 `BarPanel.to_view()` 换算，不在此处存多份。

    字段说明中标注 ★ 的是 v1 缺失、v2 新增的关键字段。
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    symbol: str  # 归一化代码，如 '601186.SH'
    market: str  # 'cn_a' | 'hk' | 'us'（★ 引擎禁止比较此值，ARCH001）
    date: date

    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    volume: Decimal = Field(ge=0)  # 成交量（恒为"股"，手数换算由 MarketProfile.lot_size 负责）
    amount: Decimal = Field(ge=0)  # 成交额（本币）
    adj_factor: Decimal = Field(gt=0)  # 累积后复权因子；无除权事件时保持不变

    currency: str  # ISO 4217: CNY / HKD / USD
    source: str  # 'akshare' | 'baostock' | 'tencent' | 'v1_legacy' | ...
    as_of: datetime  # 数据抓取时点（UTC）—— 数据新鲜度与 provenance 的依据

    is_trading_day: bool = True
    is_suspended: bool = False  # ★ 停牌标记（D-09）
    is_limit_up: bool | None = None  # ★ 涨停；源未提供时为 None，**不是 False**
    is_limit_down: bool | None = None  # ★ 跌停；同上
    instrument_type: InstrumentType = InstrumentType.EQUITY

    @property
    def tradable(self) -> bool:
        """可交易性判定：非交易日 / 停牌 / 非交易品种 均不可交易。"""
        return (
            self.is_trading_day
            and not self.is_suspended
            and self.instrument_type in TRADABLE_INSTRUMENT_TYPES
        )

    @model_validator(mode="after")
    def _validate_ohlc(self) -> Bar:
        """OHLC 自洽性校验。

        ★ 只在真实有成交时校验：停牌/非交易日的 bar 通常是前收盘价的平铺，
        强行校验会把正常数据判为异常。
        """
        if not self.is_trading_day or self.is_suspended:
            return self
        hi = max(self.open, self.close)
        lo = min(self.open, self.close)
        if self.high < hi:
            raise ValueError(f"high({self.high}) < max(open, close)({hi})")
        if self.low > lo:
            raise ValueError(f"low({self.low}) > min(open, close)({lo})")
        if self.high < self.low:
            raise ValueError(f"high({self.high}) < low({self.low})")
        return self


@dataclass(frozen=True)
class PriceView:
    """某复权口径下的 OHLCV 视图（不可变，纯数据）。

    换算口径（k 为价格缩放系数，见 `domain.services.adjustment.price_scale_factors`）：

    - `price'  = price  × k`   —— 价格可比
    - `volume' = volume ÷ k`   —— 股数可比（10 送 10 后历史股数口径统一）
    - `amount' = amount × k`   —— 金额口径统一到与调整后价格相同的尺度，跨期流动性可比

    ★ 注意：`amount' ≠ price' × volume'`（在除权点附近会偏离 k 倍），因为
    `amount` 是**真实成交金额**而非 `close × volume`。需要名义成交额时用 RAW 视图。
    """

    adjust: AdjustType
    symbol: str
    market: str
    currency: str
    dates: tuple[date, ...]
    open: tuple[Decimal, ...]
    high: tuple[Decimal, ...]
    low: tuple[Decimal, ...]
    close: tuple[Decimal, ...]
    volume: tuple[Decimal, ...]
    amount: tuple[Decimal, ...]

    def __len__(self) -> int:
        """可见 bar 数量。"""
        return len(self.close)

    def close_at(self, index: int) -> Decimal:
        """按下标取收盘价，越界抛 IndexError（不做任何兜底）。"""
        return self.close[index]


class BarPanel:
    """同一标的的有序 Bar 序列 + 复权三视图（D-03 的可测试落点）。

    构造时即校验：非空、单一标的、日期严格递增无重复。
    **校验前置**比"用到时再说"便宜得多 —— v1 的很多诡异结果源于脏序列一路流到指标层才炸。
    """

    __slots__ = ("_bars",)

    def __init__(self, bars: Sequence[Bar]) -> None:
        """构造 BarPanel。

        Args:
            bars: 按日期升序排列的 Bar 序列，必须属于同一 `symbol`。

        Raises:
            ValueError: 空序列 / 混合标的 / 日期非严格递增。
        """
        if not bars:
            raise ValueError("BarPanel 不接受空序列：空序列会让所有指标静默返回空，掩盖上游问题")
        symbol = bars[0].symbol
        prev_date: date | None = None
        for bar in bars:
            if bar.symbol != symbol:
                raise ValueError(f"BarPanel 只接受单一标的：{symbol} vs {bar.symbol}")
            if prev_date is not None and bar.date <= prev_date:
                raise ValueError(f"Bar 日期必须严格递增且无重复：{prev_date} -> {bar.date}")
            prev_date = bar.date
        self._bars: tuple[Bar, ...] = tuple(bars)

    @property
    def bars(self) -> tuple[Bar, ...]:
        """底层 Bar 元组（只读）。"""
        return self._bars

    @property
    def symbol(self) -> str:
        """标的代码。"""
        return self._bars[0].symbol

    @property
    def market(self) -> str:
        """市场代码。"""
        return self._bars[0].market

    @property
    def currency(self) -> str:
        """计价币种。"""
        return self._bars[0].currency

    @property
    def dates(self) -> tuple[date, ...]:
        """日期序列。"""
        return tuple(bar.date for bar in self._bars)

    def __len__(self) -> int:
        """Bar 数量。"""
        return len(self._bars)

    def to_view(self, adjust: AdjustType) -> PriceView:
        """按指定复权口径换算，返回不可变 `PriceView`。

        换算的数学部分在 `domain.services.adjustment`（纯函数，有 golden 测试），
        这里只负责组装视图。

        Args:
            adjust: 复权口径，**必须显式传入**。

        Returns:
            该口径下的 OHLCV 视图。
        """
        # 局部导入：避免 models.bar <-> services.adjustment 的运行时循环依赖。
        from quant_v2.domain.services.adjustment import price_scale_factors  # noqa: PLC0415

        factors = price_scale_factors(tuple(bar.adj_factor for bar in self._bars), adjust)
        return PriceView(
            adjust=adjust,
            symbol=self.symbol,
            market=self.market,
            currency=self.currency,
            dates=self.dates,
            open=tuple(bar.open * k for bar, k in zip(self._bars, factors, strict=True)),
            high=tuple(bar.high * k for bar, k in zip(self._bars, factors, strict=True)),
            low=tuple(bar.low * k for bar, k in zip(self._bars, factors, strict=True)),
            close=tuple(bar.close * k for bar, k in zip(self._bars, factors, strict=True)),
            volume=tuple(bar.volume / k for bar, k in zip(self._bars, factors, strict=True)),
            amount=tuple(bar.amount * k for bar, k in zip(self._bars, factors, strict=True)),
        )

    def as_safe_series(self, last_valid_index: int) -> SafeSeries:
        """★ 引擎唯一交给策略的数据形态（S-07 未来函数守卫）。

        Args:
            last_valid_index: 可见的最后一个下标（含）。

                v1 的正确资产：`backtest_runner.py:90` 的 `historical = bars[:i]` ——
                信号用 `bar[i-1]` 收盘、成交在 `bar[i]` 收盘，T+1 对齐，**无未来函数**。
                因此调用方应传 `i - 1`。
        """
        # 局部导入：safe_series 依赖 Bar，BarPanel 只依赖它的类型。
        from quant_v2.domain.guard.safe_series import SafeSeries  # noqa: PLC0415

        return SafeSeries(symbol=self.symbol, bars=self._bars, last_valid_index=last_valid_index)
