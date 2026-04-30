from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.domain.models.run import RunSummary


@dataclass(frozen=True)
class PaperBacktestAlignmentResult:
    """封装纸盘与回测结果之间的吻合度分析。"""

    passed: bool
    alignment_score: Decimal
    metric_alignments: dict[str, Decimal]
    summary: str


class PaperBacktestAlignmentAnalyzer:
    """负责比较纸盘与回测结果在核心指标上的吻合度。"""

    def analyze(self, backtest_summary: RunSummary, paper_summary: RunSummary) -> PaperBacktestAlignmentResult:
        """根据核心指标计算纸盘与回测的吻合度。"""
        metric_alignments = {
            "total_return": self._alignment(backtest_summary.total_return, paper_summary.total_return),
            "annualized_return": self._alignment(backtest_summary.annualized_return, paper_summary.annualized_return),
            "max_drawdown": self._inverse_alignment(backtest_summary.max_drawdown, paper_summary.max_drawdown),
            "sharpe_ratio": self._alignment(backtest_summary.sharpe_ratio, paper_summary.sharpe_ratio),
        }
        alignment_score = sum(metric_alignments.values()) / Decimal(str(len(metric_alignments)))
        passed = alignment_score >= Decimal("0.7")
        summary = "Paper performance is aligned with backtest." if passed else "Paper performance deviates from backtest."
        return PaperBacktestAlignmentResult(
            passed=passed,
            alignment_score=alignment_score,
            metric_alignments=metric_alignments,
            summary=summary,
        )

    def _alignment(self, baseline, actual) -> Decimal:
        """计算收益类指标的吻合度。"""
        if baseline in (None, Decimal("0")) or actual is None:
            return Decimal("0")
        diff = abs(baseline - actual)
        score = Decimal("1") - diff / max(abs(baseline), Decimal("0.0001"))
        return max(Decimal("0"), min(Decimal("1"), score))

    def _inverse_alignment(self, baseline, actual) -> Decimal:
        """计算回撤类指标的吻合度。"""
        if baseline is None or actual is None:
            return Decimal("0")
        diff = abs(baseline - actual)
        score = Decimal("1") - diff / max(abs(baseline), Decimal("0.0001"))
        return max(Decimal("0"), min(Decimal("1"), score))
