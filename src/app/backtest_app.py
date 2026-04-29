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
from src.services.reporting import BacktestReportWriter


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

    report_writer = BacktestReportWriter()
    report_path = report_writer.write_json_report(
        output_dir="reports/oos",
        context=out_of_sample_context,
        summary=out_of_sample_summary,
        risk_summary={"validation_score": str(result.score), "passed": str(result.passed)},
        strategy_metadata={
            "strategy_id": strategy.metadata().strategy_id.value,
            "name": strategy.metadata().name,
            "version": strategy.metadata().version,
            "author": strategy.metadata().author,
        },
        event_summary={
            "in_sample_run_id": in_sample_summary.run_id.value,
            "out_of_sample_run_id": out_of_sample_summary.run_id.value,
            "oos_summary": result.summary,
        },
    )
    return {
        "passed": str(result.passed),
        "score": str(result.score),
        "summary": result.summary,
        "report_path": report_path,
    }


def _build_strategy(strategy_name: str):
    """根据策略名称构造具体策略实例。"""
    if strategy_name == "mean_reversion":
        return MeanReversionStrategy()
    return TrendFollowingStrategy()
