from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import math


@dataclass(frozen=True)
class PerformanceMetrics:
    """封装回测结果的核心绩效指标。"""

    total_return: Decimal
    annualized_return: Decimal
    max_drawdown: Decimal
    sharpe_ratio: Decimal


class MetricsEngine:
    """负责根据净值序列计算MVP阶段的基础回测指标。"""

    def calculate(self, equity_curve: list[Decimal]) -> PerformanceMetrics:
        """根据净值曲线计算总收益、年化收益、最大回撤和夏普比率。"""
        if len(equity_curve) < 2:
            return PerformanceMetrics(
                total_return=Decimal("0"),
                annualized_return=Decimal("0"),
                max_drawdown=Decimal("0"),
                sharpe_ratio=Decimal("0"),
            )

        total_return = self._calculate_total_return(equity_curve)
        annualized_return = self._calculate_annualized_return(equity_curve)
        max_drawdown = self._calculate_max_drawdown(equity_curve)
        sharpe_ratio = self._calculate_sharpe_ratio(equity_curve)
        return PerformanceMetrics(
            total_return=total_return,
            annualized_return=annualized_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
        )

    def _calculate_total_return(self, equity_curve: list[Decimal]) -> Decimal:
        """计算净值曲线起点到终点的总收益率。"""
        initial_equity = equity_curve[0]
        if initial_equity == 0:
            return Decimal("0")
        return (equity_curve[-1] - initial_equity) / initial_equity

    def _calculate_annualized_return(self, equity_curve: list[Decimal]) -> Decimal:
        """使用252个交易日假设估算年化收益率。"""
        initial_equity = equity_curve[0]
        final_equity = equity_curve[-1]
        periods = len(equity_curve) - 1
        if initial_equity <= 0 or final_equity <= 0 or periods <= 0:
            return Decimal("0")
        years = Decimal(periods) / Decimal("252")
        if years <= 0:
            return Decimal("0")
        annualized = (final_equity / initial_equity) ** (Decimal("1") / years) - Decimal("1")
        return annualized

    def _calculate_max_drawdown(self, equity_curve: list[Decimal]) -> Decimal:
        """遍历净值曲线并计算最大回撤。"""
        peak = equity_curve[0]
        max_drawdown = Decimal("0")
        for equity in equity_curve:
            if equity > peak:
                peak = equity
            if peak == 0:
                continue
            drawdown = (peak - equity) / peak
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        return max_drawdown

    def _calculate_sharpe_ratio(self, equity_curve: list[Decimal]) -> Decimal:
        """基于日收益序列估算简化夏普比率。"""
        returns = self._daily_returns(equity_curve)
        if not returns:
            return Decimal("0")
        mean_return = sum(returns) / Decimal(len(returns))
        variance = sum((value - mean_return) ** 2 for value in returns) / Decimal(len(returns))
        if variance <= 0:
            return Decimal("0")
        std_return = Decimal(str(math.sqrt(float(variance))))
        if std_return == 0:
            return Decimal("0")
        sharpe = mean_return / std_return * Decimal(str(math.sqrt(252)))
        return sharpe

    def _daily_returns(self, equity_curve: list[Decimal]) -> list[Decimal]:
        """将净值曲线转换为逐期收益率序列。"""
        returns: list[Decimal] = []
        for previous, current in zip(equity_curve[:-1], equity_curve[1:]):
            if previous == 0:
                continue
            returns.append((current - previous) / previous)
        return returns
