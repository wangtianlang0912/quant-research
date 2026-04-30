from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.domain.models.run import RunSummary


@dataclass(frozen=True)
class OosValidationResult:
    """封装样本内与样本外结果对比后的验证结论。"""

    passed: bool
    score: Decimal
    summary: str


class OosValidator:
    """负责根据样本内与样本外摘要评估策略泛化表现。"""

    def validate(self, in_sample: RunSummary, out_of_sample: RunSummary) -> OosValidationResult:
        """根据核心指标吻合度计算OOS验证结果。"""
        metrics = [
            self._alignment(in_sample.total_return, out_of_sample.total_return),
            self._alignment(in_sample.annualized_return, out_of_sample.annualized_return),
            self._inverse_alignment(in_sample.max_drawdown, out_of_sample.max_drawdown),
            self._alignment(in_sample.sharpe_ratio, out_of_sample.sharpe_ratio),
        ]
        score = sum(metrics) / Decimal(str(len(metrics)))
        passed = score >= Decimal("0.7")
        summary = "OOS validation passed." if passed else "OOS validation failed."
        return OosValidationResult(passed=passed, score=score, summary=summary)

    def build_report_payload(
        self,
        in_sample: RunSummary,
        out_of_sample: RunSummary,
        result: OosValidationResult,
    ) -> dict[str, object]:
        """构造OOS验证报告所需的结构化摘要字段。"""
        total_return_alignment = self._alignment(in_sample.total_return, out_of_sample.total_return)
        annualized_return_alignment = self._alignment(in_sample.annualized_return, out_of_sample.annualized_return)
        max_drawdown_alignment = self._inverse_alignment(in_sample.max_drawdown, out_of_sample.max_drawdown)
        sharpe_ratio_alignment = self._alignment(in_sample.sharpe_ratio, out_of_sample.sharpe_ratio)
        metric_alignments = {
            "total_return": str(total_return_alignment),
            "annualized_return": str(annualized_return_alignment),
            "max_drawdown": str(max_drawdown_alignment),
            "sharpe_ratio": str(sharpe_ratio_alignment),
        }
        passed_checks = [name for name, value in metric_alignments.items() if Decimal(value) >= Decimal("0.7")]
        failed_checks = [name for name, value in metric_alignments.items() if Decimal(value) < Decimal("0.7")]
        return {
            "in_sample_run_id": in_sample.run_id.value,
            "out_of_sample_run_id": out_of_sample.run_id.value,
            "validation_score": str(result.score),
            "passed": str(result.passed),
            "summary": result.summary,
            "metric_alignments": metric_alignments,
            "passed_checks": passed_checks,
            "failed_checks": failed_checks,
        }

    def _alignment(self, in_sample_value, out_of_sample_value) -> Decimal:
        """计算收益类指标在样本内外之间的吻合度��"""
        if in_sample_value in (None, Decimal("0")) or out_of_sample_value is None:
            return Decimal("0")
        baseline = abs(in_sample_value)
        if baseline == 0:
            return Decimal("0")
        diff = abs(in_sample_value - out_of_sample_value)
        score = Decimal("1") - diff / baseline
        return max(Decimal("0"), min(Decimal("1"), score))

    def _inverse_alignment(self, in_sample_value, out_of_sample_value) -> Decimal:
        """计算越低越好的风险指标在样本内外之间的吻合度。"""
        if in_sample_value is None or out_of_sample_value is None:
            return Decimal("0")
        baseline = max(abs(in_sample_value), Decimal("0.0001"))
        diff = abs(in_sample_value - out_of_sample_value)
        score = Decimal("1") - diff / baseline
        return max(Decimal("0"), min(Decimal("1"), score))
