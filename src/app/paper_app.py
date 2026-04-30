from __future__ import annotations

import csv
from pathlib import Path

from src.app.bootstrap import build_paper_container
from src.domain.enums import Frequency, RunMode
from src.domain.ids import RunId
from src.domain.models.run import RunContext, RunSummary
from src.orchestrators import BacktestRunner
from src.strategies import MeanReversionStrategy, TrendFollowingStrategy
from src.adapters import LocalCsvAdapter
from src.services.reporting import BacktestReportWriter


def run_paper(data_path: str, symbol: str, strategy_name: str = "trend_following") -> RunSummary:
    """使用本地CSV数据运行指定策略的最小纸盘流程并输出报告。"""
    from datetime import date, datetime

    strategy = _build_strategy(strategy_name)
    market_data = LocalCsvAdapter(base_path=data_path)
    container = build_paper_container(strategy=strategy, market_data=market_data)
    runner = BacktestRunner(container)
    context = RunContext(
        run_id=RunId(f"paper-{strategy.metadata().strategy_id.value}-{symbol}"),
        mode=RunMode.PAPER,
        strategy_id=strategy.metadata().strategy_id,
        symbols=[symbol],
        frequency=Frequency.DAY_1,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        created_at=datetime.now(),
        environment="paper",
        metadata={"data_path": data_path, "strategy_name": strategy_name},
    )
    summary = runner.run(context)
    execution_gateway = container.execution_gateway
    portfolio_repository = container.portfolio_repository
    portfolio_history = (
        portfolio_repository.list_portfolio_history(context.run_id)
        if hasattr(portfolio_repository, "list_portfolio_history")
        else []
    )
    equity_log_path = _write_equity_log(context.run_id.value, portfolio_history)
    position_log_path = _write_position_log(context.run_id.value, portfolio_history)
    performance_report_path = _write_performance_report(context.run_id.value, summary, portfolio_history)
    event_summary = {
        "event_count": len(container.event_repository.list_by_run(context.run_id)),
        "paper_order_report_count": len(execution_gateway.list_reports()) if hasattr(execution_gateway, "list_reports") else 0,
        "equity_log_path": equity_log_path,
        "position_log_path": position_log_path,
        "performance_report_path": performance_report_path,
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


def _write_equity_log(run_id: str, portfolio_history: list) -> str:
    """将纸盘净值历史写入CSV日志。"""
    report_dir = Path("reports/paper/logs")
    report_dir.mkdir(parents=True, exist_ok=True)
    file_path = report_dir / f"{run_id}-equity.csv"
    with file_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "cash", "total_value"])
        for snapshot in portfolio_history:
            writer.writerow([
                snapshot.updated_at.isoformat() if snapshot.updated_at else "",
                str(snapshot.cash),
                str(snapshot.total_value),
            ])
    return str(file_path)


def _write_position_log(run_id: str, portfolio_history: list) -> str:
    """将纸盘持仓历史写入CSV日志。"""
    report_dir = Path("reports/paper/logs")
    report_dir.mkdir(parents=True, exist_ok=True)
    file_path = report_dir / f"{run_id}-positions.csv"
    with file_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "symbol", "quantity", "avg_cost", "market_value"])
        for snapshot in portfolio_history:
            timestamp = snapshot.updated_at.isoformat() if snapshot.updated_at else ""
            for position in snapshot.positions.values():
                writer.writerow([
                    timestamp,
                    position.symbol,
                    str(position.quantity),
                    str(position.avg_cost),
                    str(position.market_value),
                ])
    return str(file_path)


def _write_performance_report(run_id: str, summary: RunSummary, portfolio_history: list) -> str:
    """写出纸盘阶段性绩效摘要报告。"""
    report_writer = BacktestReportWriter()
    context = RunContext(
        run_id=RunId(f"performance-{run_id}"),
        mode=RunMode.PAPER,
        strategy_id=RunId(run_id),
        symbols=[],
        frequency=Frequency.DAY_1,
        start_date=summary.started_at.date(),
        end_date=(summary.finished_at or summary.started_at).date(),
        created_at=summary.started_at,
        environment="paper-report",
        metadata={"source_run_id": run_id},
    )
    return report_writer.write_json_report(
        output_dir="reports/paper/performance",
        context=context,
        summary=summary,
        risk_summary={"snapshot_count": len(portfolio_history)},
        strategy_metadata={},
        event_summary={"report_type": "paper_performance"},
    )


def _build_strategy(strategy_name: str):
    """根据策略名称构造纸盘运行所需的策略实例。"""
    if strategy_name == "mean_reversion":
        return MeanReversionStrategy()
    return TrendFollowingStrategy()
