"""时钟端口 —— 可注入的时间源。

★ 为什么需要它：v1 到处直接调 `datetime.now()`，
于是"回测到历史某天"和"今天真的跑了"走的是两套时间，
回测里那些依赖"今天"的逻辑（比如"最近 20 天"）在历史上根本没法验证。

有了 `Clock`，测试可以固定时间，回测可以推进时间，生产用真实时钟 —— **同一套代码**。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

__all__ = ["Clock", "FrozenClock", "SystemClock"]


@runtime_checkable
class Clock(Protocol):
    """时间源端口。"""

    def now(self) -> datetime:
        """当前时刻（**带时区**）。

        ★ 必须带时区：不带时区的 datetime 在跨市场（A 股/港股/美股）场景下
        会悄悄产生 8~15 小时的偏差，而这种偏差不会报错，只会让数据"差一天"。
        """
        ...

    def today(self, timezone_name: str) -> date:
        """给定时区下的"今天"。

        Args:
            timezone_name: IANA 时区名，如 `'Asia/Shanghai'`。
                ★ 传时区而不是用本机时区：生产机跑在 UTC，
                但 A 股的"今天"是上海时间的今天。
        """
        ...


class SystemClock:
    """生产用时钟 —— 真实系统时间。

    这是**适配层意义上**的实现（碰了系统时钟），但它零依赖、无 I/O，
    所以放在端口文件里，避免为 20 行代码单开一个模块。
    """

    __slots__ = ()

    def now(self) -> datetime:
        """当前时刻（本地时区感知）。"""
        return datetime.now().astimezone()

    def today(self, timezone_name: str) -> date:
        """给定时区下的今天。"""
        return datetime.now(ZoneInfo(timezone_name)).date()


class FrozenClock:
    """测试用时钟 —— 时间固定，可手动推进。

    放在这里而不是 `tests/doubles/` 的理由：回测引擎（T04）也需要它
    —— 回测的"当前时间"就是被推进的时间，不是 mock。
    """

    __slots__ = ("_current",)

    def __init__(self, current: datetime) -> None:
        """构造固定时钟。

        Args:
            current: 初始时刻，**必须带时区**。
        """
        if current.tzinfo is None:
            raise ValueError(f"FrozenClock 需要带时区的 datetime，收到 {current!r}")
        self._current: datetime = current

    def now(self) -> datetime:
        """当前固定时刻。"""
        return self._current

    def today(self, timezone_name: str) -> date:
        """固定时刻在给定时区下的日期。"""
        return self._current.astimezone(ZoneInfo(timezone_name)).date()

    def advance(self, *, days: int = 0, seconds: int = 0) -> None:
        """推进时间（原地修改，便于回测逐日推进）。"""
        self._current = self._current + timedelta(days=days, seconds=seconds)
