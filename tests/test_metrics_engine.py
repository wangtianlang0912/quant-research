from __future__ import annotations

from decimal import Decimal

from src.engines.backtest.metrics import MetricsEngine


def test_metrics_engine_calculates_core_metrics() -> None:
    """验证回测指标引擎能够输出核心绩效指标。"""
    engine = MetricsEngine()
    metrics = engine.calculate([
        Decimal("1000000"),
        Decimal("1010000"),
        Decimal("990000"),
        Decimal("1030000"),
    ])

    assert metrics.total_return > Decimal("0")
    assert metrics.annualized_return > Decimal("0")
    assert metrics.max_drawdown >= Decimal("0")
