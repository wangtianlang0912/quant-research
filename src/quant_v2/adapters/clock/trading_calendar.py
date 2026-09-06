"""交易日历适配器（T02.4 / D-07）。

## 数据流

```
种子交易日集（数据源同步落盘 / 测试用静态种子）
        │  减去
        ├── profile.extra_holidays + overrides.extra_holidays（临时休市）
        │  叠加
        └── profile.half_day_dates + overrides.half_day_dates（半天市，M-7 手工表）
                │
                ▼
        ProfileTradingCalendar —— TradingCalendar 端口实现
```

## 关键决策

1. **零市场分支（ARCH001 同源纪律）**：所有市场走同一条代码路径，
   差异全部表达为"每市场一份配置"（profile + overrides + 种子集）。
2. **半天市只能靠手工表（M-7）**：两个日历源都没有半天市标识，
   `configs/markets/*_calendar_overrides.yaml` 是唯一真源。
3. **种子集与判断分离**：本模块只做"判断"，种子集从哪来
   （akshare `tool_trade_date_hist_sina` / baostock / 测试静态表）是
   `MarketDataAdapter.fetch_trading_calendar` 与同步作业的职责。
   判断逻辑不碰网络 —— 可全量单测。
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field

from quant_v2.domain.models.market import MarketProfile

__all__ = [
    "CalendarOverrides",
    "ProfileTradingCalendar",
    "StaticCalendarSeed",
    "load_calendar_overrides",
]


# ============================================================
# overrides 配置模型
# ============================================================
class CalendarOverrides(BaseModel):
    """`configs/markets/*_calendar_overrides.yaml` 的模式。

    ★ 与 `MarketProfile.half_day_dates / extra_holidays` 合并去重后生效 ——
    profile 放"写画像时就已确定"的规则，overrides 放"每年手工维护"的表。
    两者职责不同，不是冗余。
    """

    # 非 strict：YAML 的 "15:00" 字符串 / 列表 → 元组 由 pydantic 宽松模式转换。
    # frozen + extra=forbid 保证"改不了 + 不认识的键即报错"。
    model_config = ConfigDict(frozen=True, extra="forbid")

    market_code: str
    session_open: time  # 开盘时刻（本地时区）
    session_close: time  # 收盘时刻（本地时区）
    half_day_close: time  # ★ 半天市提前收盘时刻（D-07）
    half_day_dates: tuple[date, ...] = Field(default=())
    extra_holidays: tuple[date, ...] = Field(default=())


def load_calendar_overrides(config_dir: Path, market_code: str) -> CalendarOverrides:
    """读取某市场的日历 overrides。

    Raises:
        FileNotFoundError: overrides 文件缺失 —— 每个实装市场必须显式给表，
        缺表不是"用默认值凑合"，是配置不完整（宁可炸）。
    """
    path = config_dir / f"{market_code}_calendar_overrides.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"日历 overrides 缺失：{path}。每个实装市场必须提供（半天市/临时休市手工表，M-7）。"
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    data = dict(raw) if raw else {}
    data.setdefault("market_code", market_code)
    return CalendarOverrides.model_validate(data)


# ============================================================
# 种子集
# ============================================================
class StaticCalendarSeed:
    """静态种子集（测试 / 已落盘日历的内存形态）。"""

    def __init__(self, days: Mapping[str, Sequence[date]]) -> None:
        """Args:
        days: market_code → 交易日序列（无需预排序，构造时排序去重）。
        """
        self._days = {market: tuple(sorted(set(days[market]))) for market in days}

    def trading_days(self, market: str) -> tuple[date, ...]:
        if market not in self._days:
            raise KeyError(f"日历种子中没有市场 {market}（先跑日历同步或补种子数据）")
        return self._days[market]


# ============================================================
# 端口实现
# ============================================================
class ProfileTradingCalendar:
    """实现 `TradingCalendar` 端口。

    构造时按市场预计算"有效交易日"（种子 - 临时休市）与"半天市"集合，
    查询全部走二分，零市场分支。
    """

    def __init__(
        self,
        profiles: Mapping[str, MarketProfile],
        seed: StaticCalendarSeed,
        overrides: Mapping[str, CalendarOverrides],
    ) -> None:
        """Args:
        profiles: market_code → MarketProfile（`load_all_market_profiles`）。
        seed: 种子交易日集。
        overrides: market_code → CalendarOverrides（`load_calendar_overrides`）。
        """
        self._tz: dict[str, ZoneInfo] = {}
        self._days: dict[str, tuple[date, ...]] = {}
        self._half_days: dict[str, frozenset[date]] = {}
        self._ov: dict[str, CalendarOverrides] = {}

        for market, profile in profiles.items():
            if market not in overrides:
                raise KeyError(f"市场 {market} 缺日历 overrides（每市场必须显式给表）")
            ov = overrides[market]

            holidays = frozenset(profile.extra_holidays) | frozenset(ov.extra_holidays)
            effective = tuple(d for d in seed.trading_days(market) if d not in holidays)

            self._tz[market] = ZoneInfo(profile.timezone)
            self._days[market] = effective
            self._half_days[market] = frozenset(profile.half_day_dates) | frozenset(
                ov.half_day_dates
            )
            self._ov[market] = ov

    # ----------------------------------------------------------
    # 内部工具
    # ----------------------------------------------------------
    def _require(self, market: str) -> tuple[tuple[date, ...], CalendarOverrides, ZoneInfo]:
        if market not in self._days:
            raise KeyError(f"未知市场：{market}（已注册：{sorted(self._days)}）")
        return self._days[market], self._ov[market], self._tz[market]

    # ----------------------------------------------------------
    # TradingCalendar 协议
    # ----------------------------------------------------------
    def is_trading_day(self, market: str, day: date) -> bool:
        days, _, _ = self._require(market)
        i = bisect_left(days, day)
        return i < len(days) and days[i] == day

    def next_trading_day(self, market: str, day: date, *, n: int = 1) -> date:
        """day 之后（不含 day）的第 n 个交易日。n<=0 是调用方错误。"""
        if n <= 0:
            raise ValueError(f"n 必须为正整数，收到 {n}")
        days, _, _ = self._require(market)
        i = bisect_right(days, day)  # 第一个 > day 的位置
        if i + n - 1 >= len(days):
            raise IndexError(
                f"日历覆盖范围不足：{market} 在 {day} 之后不足 {n} 个交易日"
                "（种子数据需要延伸或 n 过大）"
            )
        return days[i + n - 1]

    def previous_trading_day(self, market: str, day: date, *, n: int = 1) -> date:
        if n <= 0:
            raise ValueError(f"n 必须为正整数，收到 {n}")
        days, _, _ = self._require(market)
        i = bisect_left(days, day)  # 第一个 >= day 的位置
        if i - n < 0:
            raise IndexError(f"日历覆盖范围不足：{market} 在 {day} 之前不足 {n} 个交易日")
        return days[i - n]

    def trading_days_between(self, market: str, start: date, end: date) -> Sequence[date]:
        if start > end:
            raise ValueError(f"start({start}) 不能晚于 end({end})")
        days, _, _ = self._require(market)
        lo = bisect_left(days, start)
        hi = bisect_right(days, end)
        return days[lo:hi]

    def session_close(self, market: str, day: date) -> datetime:
        """收盘时刻。★ 半天市返回提前收盘（D-07）；非交易日抛 ValueError。"""
        if not self.is_trading_day(market, day):
            raise ValueError(f"{market} 的 {day} 不是交易日，没有收盘时刻")
        _, ov, tz = self._require(market)
        close = ov.half_day_close if day in self._half_days[market] else ov.session_close
        return datetime.combine(day, close, tzinfo=tz)
