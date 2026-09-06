"""SafeSeries —— 未来函数守卫（S-07）。

★ 这是 v2 继承 v1 的**正确资产**并提升为引擎级不变量的产物。

v1 的 `backtest_runner.py:90` 写的是 `historical = bars[:i]`：
信号用 `bar[i-1]` 收盘价计算，成交在 `bar[i]` 收盘价 —— T+1 对齐，**无未来函数**。
这比很多开源回测框架做得对。

v1 的问题在于这个正确性**没有任何机制保护**：任何人在策略里写 `bars[-1]`
就会拿到未来数据，而且不会有任何提示。v2 把它变成类型 + 守卫：

- 策略只能通过 `SafeSeries` 访问数据，拿不到全量数组的裸引用
- 越界访问一律抛 `LookaheadViolationError`（含 symbol / 索引 / as_of 日期）
- **引擎不得捕获该异常后继续执行**（`ARCH012` 静态扫描强制）

## 索引约定

`SafeSeries` 的下标与底层 `bars` 下标一致：`safe[i] is bars[i]`。
`last_valid_index = i - 1`（含）表示"当前决策时点只能看到 bar[i-1]"。
`len(safe) == last_valid_index + 1`，因此 `safe[-1]` 就是 `bar[i-1]`。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from quant_v2.domain.errors import InsufficientHistoryError, LookaheadViolationError
from quant_v2.domain.models.bar import Bar, BarPanel

__all__ = ["SafeSeries"]

# 允许通过 `field()` 取值的数值字段名（白名单：避免 getattr 成为任意属性访问的口子）
_NUMERIC_FIELDS: frozenset[str] = frozenset(
    {"open", "high", "low", "close", "volume", "amount", "adj_factor"}
)


class SafeSeries:
    """★ 只暴露 `[0..last_valid_index]` 的序列访问器。

    引擎持有全量数组以便 O(1) 切片，但策略拿到的永远是受限视图。

    Examples:
        >>> series = SafeSeries(symbol="601186.SH", bars=bars, last_valid_index=99)
        >>> series.last          # 即 bar[99]
        >>> series.close(20)     # 最近 20 根可见 bar 的收盘价
        >>> series[100]          # LookaheadViolationError
    """

    __slots__ = ("_bars", "_last", "_symbol")

    def __init__(
        self,
        *,
        symbol: str,
        bars: Sequence[Bar],
        last_valid_index: int,
    ) -> None:
        """构造受限视图。

        Args:
            symbol: 标的代码（错误信息里带上它，否则排查时不知道是哪只票）。
            bars: 全量 bar 序列（引擎持有，策略拿不到这个引用）。
            last_valid_index: 可见的最后一个下标（含）。传 `-1` 表示什么都还没看到。

        Raises:
            ValueError: `last_valid_index` 越界。
        """
        if not (-1 <= last_valid_index < len(bars)):
            raise ValueError(
                f"last_valid_index 越界：{last_valid_index}，"
                f"合法范围 [-1, {len(bars) - 1}]（symbol={symbol}）"
            )
        self._symbol: str = symbol
        self._bars: Sequence[Bar] = bars
        self._last: int = last_valid_index

    # ------------------------------------------------------------------ 基本信息

    @property
    def symbol(self) -> str:
        """标的代码。"""
        return self._symbol

    @property
    def last_valid_index(self) -> int:
        """可见的最后一个下标（含）。"""
        return self._last

    @property
    def as_of_date(self) -> date:
        """当前决策时点 = 可见最后一根 bar 的日期。

        Raises:
            InsufficientHistoryError: 一根 bar 都还没可见。
        """
        if self._last < 0:
            raise InsufficientHistoryError(
                f"symbol={self._symbol} 尚无任何可见 bar，无法确定 as_of 日期"
            )
        return self._bars[self._last].date

    def __len__(self) -> int:
        """可见 bar 数量（`last_valid_index + 1`）。"""
        return self._last + 1

    def __repr__(self) -> str:
        """可读表示（含 as_of，便于日志定位"哪一天看到了多少数据"）。"""
        as_of = self._bars[self._last].date.isoformat() if self._last >= 0 else "n/a"
        return (
            f"SafeSeries(symbol={self._symbol!r}, visible={len(self)}/{len(self._bars)}, "
            f"as_of={as_of})"
        )

    # ------------------------------------------------------------------ 越界守卫

    def _resolve(self, index: int) -> int:
        """把（可能为负的）下标解析成绝对下标，并做越界检查。"""
        resolved = index if index >= 0 else self._last + 1 + index
        if resolved > self._last:
            as_of = self._bars[self._last].date.isoformat() if self._last >= 0 else "n/a"
            raise LookaheadViolationError(
                f"未来函数：symbol={self._symbol} 请求下标 {index}"
                f"（绝对 {resolved}），但当前时点 as_of={as_of} 只可见到下标 {self._last}。"
                f"策略只能通过 SafeSeries 访问 as_of 之前的数据。"
            )
        if resolved < 0:
            raise IndexError(
                f"下标越界：symbol={self._symbol} 请求下标 {index}"
                f"（绝对 {resolved}），可见长度 {len(self)}"
            )
        return resolved

    def __getitem__(self, index: int | slice) -> Bar | list[Bar]:
        """取单根 bar 或切片。

        Raises:
            LookaheadViolationError: 触及未来数据。
            IndexError: 负向越界。
        """
        if isinstance(index, slice):
            start, stop, step = index.indices(self._last + 1)
            if step == 0:
                raise ValueError("slice step 不能为 0")
            # 切片被 indices() 截断到可见范围，等价于"只给可见部分"。
            # ★ 但如果调用方显式请求了超出可见范围的 stop，那是未来函数，必须报。
            if index.stop is not None and index.stop > self._last + 1:
                self._resolve(index.stop - 1)  # 触发 LookaheadViolationError
            return [self._bars[i] for i in range(start, stop, step)]
        return self._bars[self._resolve(index)]

    @property
    def last(self) -> Bar:
        """可见的最后一根 bar（即决策时点的 `bar[i-1]`）。

        Raises:
            InsufficientHistoryError: 一根 bar 都还没可见。
        """
        if self._last < 0:
            raise InsufficientHistoryError(
                f"symbol={self._symbol} 尚无任何可见 bar："
                "调用方应在数据长度校验之后再访问 SafeSeries"
            )
        return self._bars[self._last]

    # ------------------------------------------------------------------ 取序列

    def field(self, name: str, n: int | None = None) -> list[Decimal]:
        """取某个数值字段的最近 `n` 个值（按时间升序）。

        Args:
            name: 字段名，只接受 `open/high/low/close/volume/amount/adj_factor`。
            n: 取最近多少个值；`None` = 全部可见值。

        Returns:
            Decimal 列表（升序，最后一个是最新可见值）。

        Raises:
            ValueError: 字段名不在白名单内。
            InsufficientHistoryError: 可见长度不足 `n`。
        """
        if name not in _NUMERIC_FIELDS:
            raise ValueError(
                f"不允许取字段 {name!r}：只允许 {sorted(_NUMERIC_FIELDS)}。"
                "（白名单是为了避免 getattr 变成任意属性访问的口子）"
            )
        count = len(self) if n is None else n
        if count > len(self):
            raise InsufficientHistoryError(
                f"symbol={self._symbol} 历史不足：需要 {count} 根 bar，"
                f"as_of 可见 {len(self)} 根。"
                "请检查策略声明的 required_history_bars 与框架预取量是否一致"
            )
        start = len(self) - count
        return [getattr(self._bars[i], name) for i in range(start, self._last + 1)]

    def close(self, n: int | None = None) -> list[Decimal]:
        """收盘价序列（最近 `n` 个）。"""
        return self.field("close", n)

    def high(self, n: int | None = None) -> list[Decimal]:
        """最高价序列（最近 `n` 个）。"""
        return self.field("high", n)

    def low(self, n: int | None = None) -> list[Decimal]:
        """最低价序列（最近 `n` 个）。"""
        return self.field("low", n)

    def open(self, n: int | None = None) -> list[Decimal]:
        """开盘价序列（最近 `n` 个）。"""
        return self.field("open", n)

    def volume(self, n: int | None = None) -> list[Decimal]:
        """成交量序列（最近 `n` 个）。"""
        return self.field("volume", n)

    def amount(self, n: int | None = None) -> list[Decimal]:
        """成交额序列（最近 `n` 个）。"""
        return self.field("amount", n)

    @property
    def dates(self) -> list[date]:
        """可见 bar 的日期列表。"""
        return [self._bars[i].date for i in range(self._last + 1)]

    # ------------------------------------------------------------------ 派生视图

    def window(self, n: int, *, end_inclusive: int | None = None) -> SafeSeries:
        """取一个子窗口（返回新的 `SafeSeries`）。

        Args:
            n: 窗口长度（bar 数）。
            end_inclusive: 窗口的最后一个下标（相对底层 bars）。
                `None` = 当前可见的最后一根。

        Returns:
            新的 `SafeSeries`，其底层序列已被裁剪，长度恰为 `n`。

        Raises:
            LookaheadViolationError: `end_inclusive` 超过可见范围。
            InsufficientHistoryError: 窗口长度超过可见长度。
        """
        end = self._last if end_inclusive is None else end_inclusive
        if end > self._last:
            self._resolve(end)  # 触发 LookaheadViolationError（不可达，仅为类型明确）
        start = end - n + 1
        if start < 0:
            raise InsufficientHistoryError(
                f"symbol={self._symbol} 窗口长度不足：需要 {n} 根，end={end} 时只有 {end + 1} 根"
            )
        sliced = self._bars[start : end + 1]
        return SafeSeries(symbol=self._symbol, bars=sliced, last_valid_index=len(sliced) - 1)

    def to_panel(self) -> BarPanel:
        """转为 `BarPanel`（**仅可见窗口**），供指标库与复权换算使用。

        Raises:
            InsufficientHistoryError: 一根 bar 都还没可见（`BarPanel` 不接受空序列）。
        """
        if self._last < 0:
            raise InsufficientHistoryError(
                f"symbol={self._symbol} 尚无任何可见 bar，无法构造 BarPanel"
            )
        return BarPanel(self._bars[: self._last + 1])
