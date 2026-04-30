from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import product
from typing import Any

from src.domain.models.run import RunSummary


@dataclass(frozen=True)
class RobustnessResult:
    """封装参数稳健性分析后的摘要结果。"""

    scenario_count: int
    best_score: Decimal
    worst_score: Decimal
    summary: str


class ParameterRobustnessAnalyzer:
    """负责基于参数网格结果生成稳健性分析摘要。"""

    def analyze(self, scenario_metrics: list[dict[str, Any]]) -> RobustnessResult:
        """根据多组参数场景的夏普与回撤结果输出稳健性摘要。"""
        if not scenario_metrics:
            return RobustnessResult(0, Decimal("0"), Decimal("0"), "No robustness scenarios were provided.")
        scores = [self._score_scenario(item) for item in scenario_metrics]
        best_score = max(scores)
        worst_score = min(scores)
        stable = worst_score >= Decimal("0.3")
        summary = "Robustness analysis passed." if stable else "Robustness analysis needs review."
        return RobustnessResult(len(scenario_metrics), best_score, worst_score, summary)

    def build_parameter_grid(self, parameter_space: dict[str, list[Any]]) -> list[dict[str, Any]]:
        """根据参数空间生成笛卡尔积形式的参数组合列表。"""
        if not parameter_space:
            return []
        keys = list(parameter_space.keys())
        values = [parameter_space[key] for key in keys]
        return [dict(zip(keys, combination)) for combination in product(*values)]

    def _score_scenario(self, scenario_metric: dict[str, Any]) -> Decimal:
        """根据收益与回撤粗略计算单个参数场景的质量分数。"""
        sharpe_ratio = Decimal(str(scenario_metric.get("sharpe_ratio", 0)))
        max_drawdown = Decimal(str(scenario_metric.get("max_drawdown", 0)))
        drawdown_penalty = min(Decimal("1"), max_drawdown)
        raw_score = sharpe_ratio - drawdown_penalty
        return max(Decimal("0"), raw_score)
