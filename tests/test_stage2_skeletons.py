from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from src.domain.enums import RunMode
from src.domain.ids import RunId
from src.domain.models.run import RunSummary
from src.services.portfolio_backtest import PortfolioBacktestAggregator
from src.services.robustness_analyzer import ParameterRobustnessAnalyzer
from src.services.stress_test_runner import StressScenarioResult, StressTestRunner


def test_parameter_robustness_analyzer_builds_grid_and_summary() -> None:
    """验证参数稳健性分析器能够生成参数网格并输出摘要。"""
    analyzer = ParameterRobustnessAnalyzer()
    grid = analyzer.build_parameter_grid({"short_window": [3, 5], "long_window": [10, 20]})
    result = analyzer.analyze(
        [
            {"sharpe_ratio": Decimal("1.1"), "max_drawdown": Decimal("0.2")},
            {"sharpe_ratio": Decimal("0.9"), "max_drawdown": Decimal("0.15")},
        ]
    )

    assert len(grid) == 4
    assert result.scenario_count == 2
    assert result.best_score >= result.worst_score


def test_stress_test_runner_builds_report() -> None:
    """验证压力测试汇总器能够输出最差回撤与摘要。"""
    runner = StressTestRunner()
    report = runner.build_report(
        [
            StressScenarioResult(
                scenario_name="2018-bear",
                summary=RunSummary(
                    run_id=RunId("stress-1"),
                    mode=RunMode.BACKTEST,
                    started_at=datetime.now(),
                    finished_at=datetime.now(),
                    status="completed",
                    message="done",
                    final_equity=Decimal("950000"),
                    total_return=Decimal("-0.05"),
                    annualized_return=Decimal("-0.08"),
                    max_drawdown=Decimal("0.22"),
                    sharpe_ratio=Decimal("-0.3"),
                ),
            ),
            StressScenarioResult(
                scenario_name="2020-covid",
                summary=RunSummary(
                    run_id=RunId("stress-2"),
                    mode=RunMode.BACKTEST,
                    started_at=datetime.now(),
                    finished_at=datetime.now(),
                    status="completed",
                    message="done",
                    final_equity=Decimal("900000"),
                    total_return=Decimal("-0.10"),
                    annualized_return=Decimal("-0.12"),
                    max_drawdown=Decimal("0.30"),
                    sharpe_ratio=Decimal("-0.5"),
                ),
            ),
        ]
    )

    assert report.scenario_count == 2
    assert report.worst_drawdown == Decimal("0.30")


def test_portfolio_backtest_aggregator_aggregates_strategy_summaries() -> None:
    """验证组合回测聚合器能够输出平均收益与平均夏普。"""
    aggregator = PortfolioBacktestAggregator()
    result = aggregator.aggregate(
        [
            RunSummary(
                run_id=RunId("portfolio-1"),
                mode=RunMode.BACKTEST,
                started_at=datetime.now(),
                finished_at=datetime.now(),
                status="completed",
                message="done",
                final_equity=Decimal("1100000"),
                total_return=Decimal("0.10"),
                annualized_return=Decimal("0.16"),
                max_drawdown=Decimal("0.08"),
                sharpe_ratio=Decimal("1.2"),
            ),
            RunSummary(
                run_id=RunId("portfolio-2"),
                mode=RunMode.BACKTEST,
                started_at=datetime.now(),
                finished_at=datetime.now(),
                status="completed",
                message="done",
                final_equity=Decimal("1080000"),
                total_return=Decimal("0.08"),
                annualized_return=Decimal("0.12"),
                max_drawdown=Decimal("0.10"),
                sharpe_ratio=Decimal("1.0"),
            ),
        ]
    )

    assert result.strategy_count == 2
    assert result.average_total_return == Decimal("0.09")
    assert result.average_sharpe_ratio == Decimal("1.1")
