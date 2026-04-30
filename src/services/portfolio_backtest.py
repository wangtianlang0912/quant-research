from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.domain.models.run import RunSummary


@dataclass(frozen=True)
class PortfolioBacktestResult:
    """封装组合回测的聚合结果。"""

    strategy_count: int
    average_total_return: Decimal
    average_sharpe_ratio: Decimal
    summary: str


class PortfolioBacktestAggregator:
    """负责聚合多个策略回测摘要，生成组合级别结果。"""

    def aggregate(self, summaries: list[RunSummary]) -> PortfolioBacktestResult:
        """根据多个策略摘要计算组合层面的平均收益与夏普。"""
        if not summaries:
            return PortfolioBacktestResult(0, Decimal("0"), Decimal("0"), "No strategy summaries were provided.")
        total_return_sum = sum((summary.total_return or Decimal("0")) for summary in summaries)
        sharpe_sum = sum((summary.sharpe_ratio or Decimal("0")) for summary in summaries)
        count = Decimal(str(len(summaries)))
        average_total_return = total_return_sum / count
        average_sharpe_ratio = sharpe_sum / count
        summary = "Portfolio backtest aggregated successfully."
        return PortfolioBacktestResult(len(summaries), average_total_return, average_sharpe_ratio, summary)
