from __future__ import annotations

from src.app.bootstrap import build_paper_container
from src.domain.enums import Frequency, RunMode
from src.domain.ids import RunId
from src.domain.models.run import RunContext, RunSummary
from src.orchestrators import BacktestRunner
from src.strategies import TrendFollowingStrategy
from src.adapters import LocalCsvAdapter


def run_paper(data_path: str, symbol: str) -> RunSummary:
    """使用本地CSV数据运行一次最小纸盘流程。"""
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
    return runner.run(context)
