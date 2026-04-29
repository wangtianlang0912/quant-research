from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from src.domain.ids import RunId, StrategyId
from src.domain.models.market import Bar
from src.domain.models.portfolio import Portfolio
from src.domain.models.strategy import StrategyConfig, StrategyContext, StrategyMetadata
from src.strategies import TrendFollowingStrategy


def test_trend_following_generates_signal() -> None:
    """验证趋势策略在均线上穿时能够产出信号。"""
    strategy = TrendFollowingStrategy(short_window=2, long_window=3)
    bars = [
        Bar(
            symbol="000300.SH",
            timestamp=datetime(2024, 1, index + 1),
            open=Decimal(str(price)),
            high=Decimal(str(price)),
            low=Decimal(str(price)),
            close=Decimal(str(price)),
            volume=Decimal("100"),
        )
        for index, price in enumerate([10, 11, 12])
    ]
    context = StrategyContext(
        run_id=RunId("test-run"),
        as_of=bars[-1].timestamp,
        bars=bars,
        portfolio=Portfolio(cash=Decimal("100000"), total_value=Decimal("100000"), positions={}),
        config=StrategyConfig(params={}),
        metadata=StrategyMetadata(
            strategy_id=StrategyId("trend_following"),
            name="Trend Following",
            version="0.1.0",
        ),
    )

    signals = strategy.on_bar(context)

    assert len(signals) == 1
    assert signals[0].symbol == "000300.SH"
