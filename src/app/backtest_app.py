from __future__ import annotations

from decimal import Decimal

from src.app.bootstrap import build_backtest_container
from src.domain.enums import Frequency, RunMode
from src.domain.ids import RunId
from src.domain.models.run import RunContext, RunSummary
from src.orchestrators import BacktestRunner
from src.strategies import MeanReversionStrategy, TrendFollowingStrategy
from src.adapters import LocalCsvAdapter
from src.services.oos_validator import OosValidator
from src.services.portfolio_backtest import PortfolioBacktestAggregator
from src.services.reporting import BacktestReportWriter
from src.services.robustness_analyzer import ParameterRobustnessAnalyzer
from src.services.stress_test_runner import StressScenarioResult, StressTestRunner


def run_backtest(data_path: str, symbol: str, strategy_name: str = "trend_following") -> RunSummary:
    """使用本地CSV数据运行指定策略回测并输出报告。"""
    from datetime import date, datetime

    strategy = _build_strategy(strategy_name)
    market_data = LocalCsvAdapter(base_path=data_path)
    container = build_backtest_container(strategy=strategy, market_data=market_data)
    runner = BacktestRunner(container)
    context = RunContext(
        run_id=RunId(f"backtest-{strategy.metadata().strategy_id.value}-{symbol}"),
        mode=RunMode.BACKTEST,
        strategy_id=strategy.metadata().strategy_id,
        symbols=[symbol],
        frequency=Frequency.DAY_1,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        created_at=datetime.now(),
        environment="dev",
        metadata={"data_path": data_path, "strategy_name": strategy_name},
    )
    summary = runner.run(context)
    risk_summary = {
        "engine": container.risk_manager.__class__.__name__,
        "enabled": getattr(container.risk_manager, "enabled", None),
        "kill_switch": getattr(container.risk_manager, "kill_switch", None),
        "max_order_quantity": str(getattr(container.risk_manager, "max_order_quantity", "")),
        "max_position_value_ratio": str(getattr(container.risk_manager, "max_position_value_ratio", "")),
        "max_total_exposure_ratio": str(getattr(container.risk_manager, "max_total_exposure_ratio", "")),
        "max_drawdown_ratio": str(getattr(container.risk_manager, "max_drawdown_ratio", "")),
        "min_cash_reserve": str(getattr(container.risk_manager, "min_cash_reserve", "")),
    }
    strategy_metadata = {
        "strategy_id": strategy.metadata().strategy_id.value,
        "name": strategy.metadata().name,
        "version": strategy.metadata().version,
        "author": strategy.metadata().author,
    }
    event_summary = {
        "event_count": len(container.event_repository.list_by_run(context.run_id)),
    }
    report_writer = BacktestReportWriter()
    report_path = report_writer.write_json_report(
        output_dir="reports/backtest",
        context=context,
        summary=summary,
        risk_summary=risk_summary,
        strategy_metadata=strategy_metadata,
        event_summary=event_summary,
    )
    return RunSummary(
        run_id=summary.run_id,
        mode=summary.mode,
        started_at=summary.started_at,
        finished_at=summary.finished_at,
        status=summary.status,
        message=f"{summary.message} report_path={report_path}",
        final_equity=summary.final_equity,
        total_return=summary.total_return,
        annualized_return=summary.annualized_return,
        max_drawdown=summary.max_drawdown,
        sharpe_ratio=summary.sharpe_ratio,
    )


def run_oos_validation(data_path: str, symbol: str, strategy_name: str = "trend_following") -> dict[str, str]:
    """运行样本内外两段回测并输出最小OOS验证结果。"""
    from datetime import date, datetime

    strategy = _build_strategy(strategy_name)
    market_data = LocalCsvAdapter(base_path=data_path)
    validator = OosValidator()

    in_sample_container = build_backtest_container(strategy=strategy, market_data=market_data)
    in_sample_runner = BacktestRunner(in_sample_container)
    in_sample_context = RunContext(
        run_id=RunId(f"oos-is-{strategy.metadata().strategy_id.value}-{symbol}"),
        mode=RunMode.BACKTEST,
        strategy_id=strategy.metadata().strategy_id,
        symbols=[symbol],
        frequency=Frequency.DAY_1,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 9, 30),
        created_at=datetime.now(),
        environment="dev",
        metadata={"data_path": data_path, "dataset": "in_sample", "strategy_name": strategy_name},
    )
    in_sample_summary = in_sample_runner.run(in_sample_context)

    out_of_sample_container = build_backtest_container(strategy=_build_strategy(strategy_name), market_data=market_data)
    out_of_sample_runner = BacktestRunner(out_of_sample_container)
    out_of_sample_context = RunContext(
        run_id=RunId(f"oos-oos-{strategy.metadata().strategy_id.value}-{symbol}"),
        mode=RunMode.BACKTEST,
        strategy_id=strategy.metadata().strategy_id,
        symbols=[symbol],
        frequency=Frequency.DAY_1,
        start_date=date(2024, 10, 1),
        end_date=date(2024, 12, 31),
        created_at=datetime.now(),
        environment="dev",
        metadata={"data_path": data_path, "dataset": "out_of_sample", "strategy_name": strategy_name},
    )
    out_of_sample_summary = out_of_sample_runner.run(out_of_sample_context)
    result = validator.validate(in_sample_summary, out_of_sample_summary)
    payload = validator.build_report_payload(in_sample_summary, out_of_sample_summary, result)

    report_writer = BacktestReportWriter()
    report_path = report_writer.write_json_report(
        output_dir="reports/oos",
        context=out_of_sample_context,
        summary=out_of_sample_summary,
        risk_summary={"validation_score": payload["validation_score"], "passed": payload["passed"]},
        strategy_metadata={
            "strategy_id": strategy.metadata().strategy_id.value,
            "name": strategy.metadata().name,
            "version": strategy.metadata().version,
            "author": strategy.metadata().author,
        },
        event_summary=payload,
    )
    return {
        "passed": str(result.passed),
        "score": str(result.score),
        "summary": result.summary,
        "report_path": report_path,
    }


def run_stress_test(data_path: str, symbol: str, strategy_name: str = "trend_following") -> dict[str, str]:
    """运行多个预设时间场景的压力测试并输出报告。"""
    scenarios = [
        ("2018-bear", "2018-01-01", "2018-12-31"),
        ("2020-covid", "2020-01-01", "2020-12-31"),
    ]
    scenario_results: list[StressScenarioResult] = []
    for scenario_name, start, end in scenarios:
        summary = _run_backtest_for_period(data_path, symbol, strategy_name, start, end, run_prefix=f"stress-{scenario_name}")
        scenario_results.append(StressScenarioResult(scenario_name=scenario_name, summary=summary))
    runner = StressTestRunner()
    report = runner.build_report(scenario_results)
    return {
        "scenario_count": str(report.scenario_count),
        "worst_drawdown": str(report.worst_drawdown),
        "summary": report.summary,
    }


def run_parameter_robustness(data_path: str, symbol: str, strategy_name: str = "trend_following") -> dict[str, str]:
    """基于参数网格运行多组回测并输出稳健性分析摘要。"""
    analyzer = ParameterRobustnessAnalyzer()
    parameter_space = (
        analyzer.build_mean_reversion_parameter_space()
        if strategy_name == "mean_reversion"
        else analyzer.build_trend_parameter_space()
    )
    parameter_grid = analyzer.build_parameter_grid(parameter_space)
    scenario_metrics: list[dict[str, str]] = []
    for index, params in enumerate(parameter_grid[:4], start=1):
        summary = _run_backtest_for_period(
            data_path,
            symbol,
            strategy_name,
            "2024-01-01",
            "2024-12-31",
            run_prefix=f"robustness-{index}",
            strategy_params=params,
        )
        scenario_metrics.append(
            {
                "sharpe_ratio": str(summary.sharpe_ratio or Decimal("0")),
                "max_drawdown": str(summary.max_drawdown or Decimal("0")),
            }
        )
    result = analyzer.analyze(scenario_metrics)
    return {
        "scenario_count": str(result.scenario_count),
        "best_score": str(result.best_score),
        "worst_score": str(result.worst_score),
        "summary": result.summary,
    }


def run_portfolio_backtest(data_path: str, symbol: str) -> dict[str, str]:
    """运行多策略回测并输出组合级别聚合结果。"""
    summaries = [
        run_backtest(data_path=data_path, symbol=symbol, strategy_name="trend_following"),
        run_backtest(data_path=data_path, symbol=symbol, strategy_name="mean_reversion"),
    ]
    aggregator = PortfolioBacktestAggregator()
    result = aggregator.aggregate(summaries)
    return {
        "strategy_count": str(result.strategy_count),
        "average_total_return": str(result.average_total_return),
        "average_sharpe_ratio": str(result.average_sharpe_ratio),
        "summary": result.summary,
    }


def _run_backtest_for_period(
    data_path: str,
    symbol: str,
    strategy_name: str,
    start_date_text: str,
    end_date_text: str,
    run_prefix: str,
    strategy_params: dict | None = None,
) -> RunSummary:
    """在指定时间区间内运行单次回测，供阶段二执行流程复用。"""
    from datetime import datetime

    strategy = _build_strategy(strategy_name, strategy_params)
    market_data = LocalCsvAdapter(base_path=data_path)
    container = build_backtest_container(strategy=strategy, market_data=market_data)
    runner = BacktestRunner(container)
    context = RunContext(
        run_id=RunId(f"{run_prefix}-{strategy.metadata().strategy_id.value}-{symbol}"),
        mode=RunMode.BACKTEST,
        strategy_id=strategy.metadata().strategy_id,
        symbols=[symbol],
        frequency=Frequency.DAY_1,
        start_date=datetime.fromisoformat(start_date_text).date(),
        end_date=datetime.fromisoformat(end_date_text).date(),
        created_at=datetime.now(),
        environment="dev",
        metadata={"data_path": data_path, "strategy_name": strategy_name},
    )
    return runner.run(context)


def _build_strategy(strategy_name: str, strategy_params: dict | None = None):
    """根据策略名称与可选参数构造具体策略实例。"""
    params = strategy_params or {}
    if strategy_name == "mean_reversion":
        return MeanReversionStrategy(
            lookback_window=params.get("lookback_window", 20),
            entry_zscore=params.get("entry_zscore", Decimal("2.0")),
            exit_zscore=params.get("exit_zscore", Decimal("0.5")),
        )
    return TrendFollowingStrategy(
        short_window=params.get("short_window", 5),
        long_window=params.get("long_window", 20),
    )
