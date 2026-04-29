from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from src.adapters.market_data import LocalCsvAdapter
from src.app.bootstrap import build_backtest_container
from src.domain.enums import Frequency, RunMode
from src.domain.ids import RunId
from src.domain.models.run import RunContext
from src.orchestrators import BacktestRunner
from src.strategies import TrendFollowingStrategy


def test_backtest_runner_completes_with_local_data(tmp_path: Path) -> None:
    """验证最小回测运行器能够基于本地CSV完成一次回测。"""
    data_dir = tmp_path / "1d"
    data_dir.mkdir(parents=True, exist_ok=True)
    file_path = data_dir / "000300.SH.csv"
    file_path.write_text(
        "timestamp,open,high,low,close,volume,amount\n"
        "2024-01-02T00:00:00,10,10,9,9,1000,9000\n"
        "2024-01-03T00:00:00,9,11,9,11,1100,12100\n"
        "2024-01-04T00:00:00,11,12,10,12,1200,14400\n",
        encoding="utf-8",
    )

    strategy = TrendFollowingStrategy(short_window=2, long_window=3)
    market_data = LocalCsvAdapter(base_path=str(tmp_path))
    container = build_backtest_container(strategy=strategy, market_data=market_data)
    runner = BacktestRunner(container)
    context = RunContext(
        run_id=RunId("backtest-000300.SH"),
        mode=RunMode.BACKTEST,
        strategy_id=strategy.metadata().strategy_id,
        symbols=["000300.SH"],
        frequency=Frequency.DAY_1,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        created_at=datetime.now(),
        environment="test",
        metadata={},
    )

    summary = runner.run(context)

    assert summary.status == "completed"
    portfolio = container.portfolio_repository.load_latest_portfolio(context.run_id)
    assert portfolio is not None
    assert portfolio.total_value > Decimal("0")
