from __future__ import annotations

from src.app.bootstrap import build_paper_container
from src.domain.enums import Frequency, RunMode
from src.domain.ids import RunId
from src.domain.models.run import RunContext, RunSummary
from src.orchestrators import BacktestRunner
from src.strategies import TrendFollowingStrategy
from src.adapters import LocalCsvAdapter
from src.services.reporting import BacktestReportWriter


def run_paper(data_path: str, symbol: str) -> RunSummary:
    """使用本地CSV数据运行一次最小纸盘流程并输出报告。"""
    from datetime import date, datetime

    strategy = TrendFollowingStrategy()
    market_data = LocalCsvAdapter(base_path=data_path)
    container = build_paper_container(strategy=strategy, market_data=market_data)
    runner = BacktestRunner(container)
    context = RunContext(
        run_id=RunId(f"paper-{symbol}"),
        mode=RunMode.PAPER,
        strategy_id=strategy.metadata().strategy_id,
        symbols=[symbol],
        frequency=Frequency.DAY_1,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        created_at=datetime.now(),
        environment="paper",
        metadata={"data_path": data_path},
    )
    summary = runner.run(context)
    execution_gateway = container.execution_gateway
    event_summary = {
        "event_count": len(container.event_repository.list_by_run(context.run_id)),
        "paper_order_report_count": len(execution_gateway.list_reports()) if hasattr(execution_gateway, "list_reports") else 0,
    }
    report_writer = BacktestReportWriter()
    report_path = report_writer.write_json_report(
        output_dir="reports/paper",
        context=context,
        summary=summary,
        risk_summary={
            "engine": container.risk_manager.__class__.__name__,
            "kill_switch": getattr(container.risk_manager, "kill_switch", None),
            "max_drawdown_ratio": str(getattr(container.risk_manager, "max_drawdown_ratio", "")),
        },
        strategy_metadata={
            "strategy_id": strategy.metadata().strategy_id.value,
            "name": strategy.metadata().name,
            "version": strategy.metadata().version,
            "author": strategy.metadata().author,
        },
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
