"""测试公共夹具。

★ 为什么单独放 conftest：
Bar 的必填字段有 13 个，如果每个测试文件各写一份构造代码，
那么"改一个字段"会变成 17 个文件的同步修改 —— 这正是 v1 的那种维护债。
这里只提供**最小必需**的构造助手，不放业务语义假数据：
业务相关的 fixture 放在各自的测试文件里，让它离断言更近、更好读。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from quant_v2.domain.models.bar import Bar

# 固定抓取时点：指纹类测试需要可复现的 as_of，不能用 datetime.now()
FIXED_AS_OF = datetime(2026, 9, 5, 0, 0, 0, tzinfo=UTC)

# 测试专用起始日：刻意选一个非月初非月末的工作日，避免与"月末复权"之类逻辑撞车
START_DATE = date(2026, 1, 5)


def d(value: str) -> Decimal:
    """构造 Decimal（测试里禁止写 float 字面量，ARCH013 同样约束测试代码）。"""
    return Decimal(value)


def make_bar(
    *,
    symbol: str = "601186.SH",
    market: str = "cn_a",
    day: date,
    close: str,
    open_: str | None = None,
    high: str | None = None,
    low: str | None = None,
    volume: str = "1000000",
    amount: str | None = None,
    adj_factor: str = "1",
    currency: str = "CNY",
    source: str = "test",
    is_suspended: bool = False,
    is_trading_day: bool = True,
) -> Bar:
    """构造一根 Bar。

    未显式给出的 OHLC 由 `close` 派生（保证 OHLC 自洽性校验必过），
    这样"只关心收盘价"的测试不必写满 13 个字段。
    """
    c = d(close)
    o = d(open_) if open_ is not None else c
    h = d(high) if high is not None else max(o, c)
    lo = d(low) if low is not None else min(o, c)
    amt = d(amount) if amount is not None else (c * d(volume))
    return Bar(
        symbol=symbol,
        market=market,
        date=day,
        open=o,
        high=h,
        low=lo,
        close=c,
        volume=d(volume),
        amount=amt,
        adj_factor=d(adj_factor),
        currency=currency,
        source=source,
        as_of=FIXED_AS_OF,
        is_trading_day=is_trading_day,
        is_suspended=is_suspended,
    )


def make_bars(
    closes: list[str],
    *,
    symbol: str = "601186.SH",
    market: str = "cn_a",
    start: date = START_DATE,
    adj_factors: list[str] | None = None,
    step_days: int = 1,
) -> list[Bar]:
    """按收盘价序列构造连续 Bar（每个自然日 +step_days，测试里不关心真实交易日历）。"""
    factors = adj_factors or ["1"] * len(closes)
    if len(factors) != len(closes):
        raise ValueError(f"closes 与 adj_factors 长度不一致：{len(closes)} vs {len(factors)}")
    return [
        make_bar(
            symbol=symbol,
            market=market,
            day=start + timedelta(days=index * step_days),
            close=close,
            adj_factor=factor,
        )
        for index, (close, factor) in enumerate(zip(closes, factors, strict=True))
    ]


@pytest.fixture
def fixed_as_of() -> datetime:
    """固定的 as_of 时点（需要可复现指纹的测试用）。"""
    return FIXED_AS_OF


@pytest.fixture
def sample_closes() -> list[Decimal]:
    """一段带涨有跌的收盘价样本（50 根，覆盖全部指标的预热期）。"""
    # 用确定性公式生成：单调上行 + 小幅震荡，避免随机数据导致测试不可复现
    return [Decimal(100) + Decimal((i * 7) % 23) - Decimal(11) for i in range(50)]
