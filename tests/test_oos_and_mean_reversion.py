from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from src.domain.enums import Frequency, RunMode
from src.domain.ids import RunId, StrategyId
from src.domain.models.run import RunSummary
from src.services.oos_validator import OosValidator


def test_oos_validator_passes_when_metrics_are_consistent() -> None:
    """验证OOS验证器在样本内外结果接近时给出通过结论。"""
    validator = OosValidator()
    in_sample = RunSummary(
        run_id=RunId("is-1"),
        mode=RunMode.BACKTEST,
        started_at=datetime.now(),
        finished_at=datetime.now(),
        status="completed",
        message="is",
        final_equity=Decimal("1100000"),
        total_return=Decimal("0.10"),
        annualized_return=Decimal("0.16"),
        max_drawdown=Decimal("0.08"),
        sharpe_ratio=Decimal("1.20"),
    )
    out_of_sample = RunSummary(
        run_id=RunId("oos-1"),
        mode=RunMode.BACKTEST,
        started_at=datetime.now(),
        finished_at=datetime.now(),
        status="completed",
        message="oos",
        final_equity=Decimal("1080000"),
        total_return=Decimal("0.09"),
        annualized_return=Decimal("0.14"),
        max_drawdown=Decimal("0.09"),
        sharpe_ratio=Decimal("1.10"),
    )

    result = validator.validate(in_sample, out_of_sample)

    assert result.passed is True
    assert result.score >= Decimal("0.7")


def test_mean_reversion_strategy_generates_signal() -> None:
    """验证均值回归策略在价格显著偏离均值时能够产出信号。"""
    from src.domain.models.market import Bar
    from src.domain.models.portfolio import Portfolio
    from src.domain.models.strategy import StrategyConfig, StrategyContext, StrategyMetadata
    from src.strategies import MeanReversionStrategy

    strategy = MeanReversionStrategy(lookback_window=5, entry_zscore=Decimal("1.5"), exit_zscore=Decimal("0.5"))
    closes = [Decimal("10"), Decimal("10.2"), Decimal("10.1"), Decimal("10.3"), Decimal("8.8")]
    bars = [
        Bar(
            symbol="000300.SH",
            timestamp=datetime(2024, 1, index + 1),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=Decimal("100"),
            frequency=Frequency.DAY_1,
        )
        for index, close in enumerate(closes)
    ]
    context = StrategyContext(
        run_id=RunId("test-run"),
        as_of=bars[-1].timestamp,
        bars=bars,
        portfolio=Portfolio(cash=Decimal("100000"), total_value=Decimal("100000"), positions={}),
        config=StrategyConfig(params={}),
        metadata=StrategyMetadata(
            strategy_id=StrategyId("mean_reversion"),
            name="Mean Reversion",
            version="0.1.0",
        ),
    )

    signals = strategy.on_bar(context)

    assert len(signals) == 1
    assert signals[0].symbol == "000300.SH"
