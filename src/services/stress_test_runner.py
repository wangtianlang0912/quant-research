from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.domain.models.run import RunSummary


@dataclass(frozen=True)
class StressScenarioResult:
    """封装单个压力测试场景的运行摘要。"""

    scenario_name: str
    summary: RunSummary


@dataclass(frozen=True)
class StressTestReport:
    """封装多场景压力测试后的整体结论。"""

    scenario_count: int
    worst_drawdown: Decimal
    summary: str


class StressTestRunner:
    """负责汇总多个压力测试场景的回测摘要结果。"""

    def build_report(self, scenario_results: list[StressScenarioResult]) -> StressTestReport:
        """根据场景结果生成压力测试汇总报告。"""
        if not scenario_results:
            return StressTestReport(0, Decimal("0"), "No stress scenarios were executed.")
        drawdowns = [result.summary.max_drawdown or Decimal("0") for result in scenario_results]
        worst_drawdown = max(drawdowns)
        summary = "Stress test passed." if worst_drawdown < Decimal("0.35") else "Stress test exceeded drawdown threshold."
        return StressTestReport(len(scenario_results), worst_drawdown, summary)
