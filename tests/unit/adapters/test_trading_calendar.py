"""交易日历测试（T02.4 / D-07）。

种子集用合成的"周一至周五连续交易周"构造，覆盖 12 类边界：
跨周末 / 跨年 / 临时休市剔除 / 半天市仍是交易日 / 半天市提前收盘 /
n 步跳跃 / 非交易日两侧逼近 / 未知市场 / 非法 n / 区间含端点 / start>end /
overrides 缺表拒绝启动。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from quant_v2.adapters.clock.trading_calendar import (
    CalendarOverrides,
    ProfileTradingCalendar,
    StaticCalendarSeed,
    load_calendar_overrides,
)
from quant_v2.domain.models.market import (
    CostModel,
    DataSourceSpec,
    MarketProfile,
    PriceLimitSpec,
    TickSpec,
)
from quant_v2.domain.ports.market_data_port import TradingCalendar

pytestmark = pytest.mark.unit

CN_TZ = ZoneInfo("Asia/Shanghai")


def d(value: str) -> Decimal:
    return Decimal(value)


def make_profile(**overrides: object) -> MarketProfile:
    """A 股画像：profile 自带 2026-10-09 临时休市与 2026-02-16 半天市。"""
    base = MarketProfile(
        market_code="cn_a",
        display_name="中国 A 股",
        timezone="Asia/Shanghai",
        calendar_id="cn_a",
        currency="CNY",
        settlement_currency=None,
        lot_size=100,
        odd_lot_allowed=False,
        tick=TickSpec(tick_size=d("0.01")),
        price_limit=PriceLimitSpec(limit_pct=d("0.1"), st_limit_pct=d("0.05")),
        t_plus=1,
        shortable=False,
        cost=CostModel(
            commission_rate=d("0.00025"),
            commission_min=d("5"),
            tax_rate_sell=d("0.0005"),
            tax_rate_buy=d("0"),
            transfer_fee_rate=d("0.00001"),
            exchange_fee_rate=d("0.0000487"),
            slippage_bps=10,
        ),
        symbol_pattern=r"^\d{6}\.(SH|SZ)$",
        half_day_dates=(date(2026, 2, 16),),
        extra_holidays=(date(2026, 10, 9),),
        fund_availability="FULL",
        delisting_data_availability="PARTIAL",
        max_symbols=5000,
        data_sources=(DataSourceSpec(source_id="test", adapter="x.y.Z", priority=0),),
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def make_overrides(**overrides: object) -> CalendarOverrides:
    base = CalendarOverrides(
        market_code="cn_a",
        session_open=time(9, 30),
        session_close=time(15, 0),
        half_day_close=time(11, 30),
    )
    return base.model_copy(update=overrides)


def make_calendar(
    *,
    half_day_dates: tuple[date, ...] = (),
    extra_holidays: tuple[date, ...] = (),
) -> ProfileTradingCalendar:
    """种子 = 2025-12 ~ 2026-12 的全部工作日（周一~周五）。"""
    days: list[date] = []
    cur = date(2025, 12, 1)
    while cur <= date(2026, 12, 31):
        if cur.weekday() < 5:
            days.append(cur)
        cur += dt.timedelta(days=1)
    seed = StaticCalendarSeed({"cn_a": days})
    return ProfileTradingCalendar(
        {"cn_a": make_profile()},
        seed,
        {"cn_a": make_overrides(half_day_dates=half_day_dates, extra_holidays=extra_holidays)},
    )


@pytest.fixture()
def cal() -> ProfileTradingCalendar:
    return make_calendar()


class Test实现端口协议:
    def test_是TradingCalendar实例(self, cal: ProfileTradingCalendar) -> None:
        assert isinstance(cal, TradingCalendar)


class Test是否交易日:
    def test_工作日是交易日(self, cal: ProfileTradingCalendar) -> None:
        # 2026-01-05 是周一
        assert cal.is_trading_day("cn_a", date(2026, 1, 5)) is True

    def test_周末不是交易日(self, cal: ProfileTradingCalendar) -> None:
        # 2026-01-03 周六 / 01-04 周日
        assert cal.is_trading_day("cn_a", date(2026, 1, 3)) is False
        assert cal.is_trading_day("cn_a", date(2026, 1, 4)) is False

    def test_临时休市被剔除(self, cal: ProfileTradingCalendar) -> None:
        """★ profile.extra_holidays：2026-10-09 是周五但临时休市。"""
        assert date(2026, 10, 9).weekday() == 4  # 确认它本来是工作日
        assert cal.is_trading_day("cn_a", date(2026, 10, 9)) is False

    def test_半天市仍是交易日(self, cal: ProfileTradingCalendar) -> None:
        """★ 半天市 ≠ 休市：2026-02-16（周一）照常交易只是提前收盘。"""
        assert cal.is_trading_day("cn_a", date(2026, 2, 16)) is True

    def test_未知市场拒绝(self, cal: ProfileTradingCalendar) -> None:
        with pytest.raises(KeyError, match="未知市场"):
            cal.is_trading_day("us", date(2026, 1, 5))


class Test下一个交易日:
    def test_跨周末(self, cal: ProfileTradingCalendar) -> None:
        """周五 → 下周一。"""
        assert cal.next_trading_day("cn_a", date(2026, 1, 9)) == date(2026, 1, 12)

    def test_从周末出发取周一(self, cal: ProfileTradingCalendar) -> None:
        assert cal.next_trading_day("cn_a", date(2026, 1, 10)) == date(2026, 1, 12)

    def test_跨年(self, cal: ProfileTradingCalendar) -> None:
        """2026-01-01（周四，种子含）之后的下一交易日。"""
        assert cal.next_trading_day("cn_a", date(2026, 1, 1)) == date(2026, 1, 2)

    def test_跳过临时休市(self, cal: ProfileTradingCalendar) -> None:
        """10-08 → 10-09（休市）→ 10-12（周一）。"""
        assert cal.next_trading_day("cn_a", date(2026, 10, 8)) == date(2026, 10, 12)

    def test_n步跳跃(self, cal: ProfileTradingCalendar) -> None:
        """n=3：周三 → 下下周一。"""
        assert cal.next_trading_day("cn_a", date(2026, 1, 7), n=3) == date(2026, 1, 12)

    def test_非正n拒绝(self, cal: ProfileTradingCalendar) -> None:
        with pytest.raises(ValueError, match="n 必须为正"):
            cal.next_trading_day("cn_a", date(2026, 1, 7), n=0)

    def test_种子范围不足拒绝(self, cal: ProfileTradingCalendar) -> None:
        with pytest.raises(IndexError, match="覆盖范围不足"):
            cal.next_trading_day("cn_a", date(2026, 12, 31), n=1)


class Test上一个交易日:
    def test_跨周末回退(self, cal: ProfileTradingCalendar) -> None:
        assert cal.previous_trading_day("cn_a", date(2026, 1, 12)) == date(2026, 1, 9)

    def test_n步回退(self, cal: ProfileTradingCalendar) -> None:
        assert cal.previous_trading_day("cn_a", date(2026, 1, 12), n=2) == date(2026, 1, 8)

    def test_从交易日当天出发取前一日(self, cal: ProfileTradingCalendar) -> None:
        """day 本身是交易日时，previous 不含当天（2026-01-05 周一 → 周五 01-02）。"""
        assert cal.previous_trading_day("cn_a", date(2026, 1, 5)) == date(2026, 1, 2)


class Test区间:
    def test_含端点(self, cal: ProfileTradingCalendar) -> None:
        days = cal.trading_days_between("cn_a", date(2026, 1, 5), date(2026, 1, 9))
        assert days == (
            date(2026, 1, 5),
            date(2026, 1, 6),
            date(2026, 1, 7),
            date(2026, 1, 8),
            date(2026, 1, 9),
        )

    def test_端点是休市日则不含(self, cal: ProfileTradingCalendar) -> None:
        days = cal.trading_days_between("cn_a", date(2026, 10, 9), date(2026, 10, 12))
        assert days == (date(2026, 10, 12),)

    def test_start晚于end拒绝(self, cal: ProfileTradingCalendar) -> None:
        with pytest.raises(ValueError, match="不能晚于"):
            cal.trading_days_between("cn_a", date(2026, 1, 9), date(2026, 1, 5))


class Test收盘时刻:
    def test_正常收盘15点(self, cal: ProfileTradingCalendar) -> None:
        close = cal.session_close("cn_a", date(2026, 1, 5))
        assert close == datetime(2026, 1, 5, 15, 0, tzinfo=CN_TZ)

    def test_半天市提前收盘(self, cal: ProfileTradingCalendar) -> None:
        """★ D-07 验收标准原文：半天市返回提前收盘时间。"""
        close = cal.session_close("cn_a", date(2026, 2, 16))
        assert close == datetime(2026, 2, 16, 11, 30, tzinfo=CN_TZ)

    def test_非交易日无收盘时刻(self, cal: ProfileTradingCalendar) -> None:
        with pytest.raises(ValueError, match="不是交易日"):
            cal.session_close("cn_a", date(2026, 1, 3))


class TestOverrides:
    def test_合并去重_表与画像同时有半天市(self) -> None:
        """overrides 再补一天半天市 → 两天都提前收盘。"""
        cal = make_calendar(half_day_dates=(date(2026, 4, 30),))
        assert cal.session_close("cn_a", date(2026, 2, 16)).hour == 11
        assert cal.session_close("cn_a", date(2026, 4, 30)).hour == 11

    def test_overrides休市叠加(self) -> None:
        cal = make_calendar(extra_holidays=(date(2026, 4, 30),))
        assert cal.is_trading_day("cn_a", date(2026, 4, 30)) is False

    def test_缺overrides拒绝构造(self) -> None:
        """★ 每个实装市场必须显式给表 —— 缺表是配置不完整，宁可炸。"""
        seed = StaticCalendarSeed({"cn_a": [date(2026, 1, 5)]})
        with pytest.raises(KeyError, match="缺日历 overrides"):
            ProfileTradingCalendar({"cn_a": make_profile()}, seed, {})

    def test_读取真实A股票overrides(self) -> None:
        """仓库里的 cn_a_calendar_overrides.yaml 可解析且字段齐。"""
        config_dir = Path(__file__).resolve().parents[3] / "configs" / "markets"
        ov = load_calendar_overrides(config_dir, "cn_a")
        assert ov.market_code == "cn_a"
        assert ov.session_close == time(15, 0)
        assert ov.half_day_close == time(11, 30)
        assert ov.half_day_dates == ()
        assert ov.extra_holidays == ()

    def test_缺overrides文件显式报错(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="overrides 缺失"):
            load_calendar_overrides(tmp_path, "cn_a")


class Test种子:
    def test_种子自动排序去重(self) -> None:
        seed = StaticCalendarSeed({"cn_a": [date(2026, 1, 7), date(2026, 1, 5), date(2026, 1, 5)]})
        assert seed.trading_days("cn_a") == (date(2026, 1, 5), date(2026, 1, 7))

    def test_种子缺市场拒绝(self) -> None:
        seed = StaticCalendarSeed({"cn_a": [date(2026, 1, 5)]})
        with pytest.raises(KeyError, match="没有市场 hk"):
            seed.trading_days("hk")
