from __future__ import annotations

from src.app.bootstrap import build_backtest_container
from src.domain.enums import Frequency, RunMode
from src.domain.ids import RunId
from src.domain.models.run import RunContext, RunSummary
from src.orchestrators import BacktestRunner
from src.strategies import TrendFollowingStrategy
from src.adapters import LocalCsvAdapter
from src.services.reporting import BacktestReportWriter


def run_backtest(data_path: str, symbol: str) -> RunSummary:
    """使用本地CSV数据运行一次趋势策略回测并输出报告。"""
    from datetime import date, datetime

    strategy = TrendFollowingStrategy()
    market_data = LocalCsvAdapter(base_path=data_path)
    container = build_backtest_container(strategy=strategy, market_data=market_data)
    runner = BacktestRunner(container)
    context = RunContext(
        run_id=RunId(f"backtest-{symbol}"),
        mode=RunMode.BACKTEST,
        strategy_id=strategy.metadata().strategy_id,
        symbols=[symbol],
        frequency=Frequency.DAY_1,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        created_at=datetime.now(),
        environment="dev",
        metadata={"data_path": data_path},
    )
    summary = runner.run(context)
    report_writer = BacktestReportWriter()
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
    report_path = report_writer.write_json_report(
        output_dir="reports/backtest",
        context=context,
        summary=summary,
        risk_summary=risk_summary,
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
