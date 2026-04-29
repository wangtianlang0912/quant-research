from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.domain.enums import RiskAction
from src.domain.models.order import OrderIntent
from src.domain.models.portfolio import Portfolio
from src.domain.models.risk import RiskDecision
from src.domain.ports.risk_port import RiskPort


@dataclass
class BasicRiskManager(RiskPort):
    """提供MVP阶段最小可用的基础风控实现。"""

    max_order_quantity: Decimal = Decimal("1000")
    max_position_value_ratio: Decimal = Decimal("0.2")
    max_total_exposure_ratio: Decimal = Decimal("0.8")
    min_cash_reserve: Decimal = Decimal("50000")
    max_drawdown_ratio: Decimal = Decimal("0.15")
    enabled: bool = True
    kill_switch: bool = False

    def evaluate(
        self,
        portfolio: Portfolio,
        order_intents: list[OrderIntent],
    ) -> list[RiskDecision]:
        """对订单列表执行总开关、回撤、单笔数量、仓位比例和现金保留检查。"""
        decisions: list[RiskDecision] = []
        current_drawdown = self._calculate_current_drawdown(portfolio)
        for order in order_intents:
            if not self.enabled:
                decisions.append(
                    RiskDecision(
                        order_id=order.order_id,
                        action=RiskAction.REJECT,
                        approved_quantity=Decimal("0"),
                        reject_reason="风控模块未启用。",
                        triggered_rules=["risk_disabled"],
                    )
                )
                continue
            if self.kill_switch:
                decisions.append(
                    RiskDecision(
                        order_id=order.order_id,
                        action=RiskAction.REJECT,
                        approved_quantity=Decimal("0"),
                        reject_reason="Kill Switch 已触发，禁止继续下单。",
                        triggered_rules=["kill_switch"],
                    )
                )
                continue
            if current_drawdown >= self.max_drawdown_ratio:
                decisions.append(
                    RiskDecision(
                        order_id=order.order_id,
                        action=RiskAction.REJECT,
                        approved_quantity=Decimal("0"),
                        reject_reason="当前回撤超过阈值，禁止继续下单。",
                        triggered_rules=["max_drawdown_ratio"],
                    )
                )
                continue

            approved_quantity = min(order.quantity, self.max_order_quantity)
            triggered_rules: list[str] = []
            estimated_price = self._estimate_order_price(order)
            max_position_quantity = self._calculate_max_position_quantity(portfolio, order, estimated_price)
            if approved_quantity > max_position_quantity:
                approved_quantity = max_position_quantity
                triggered_rules.append("max_position_value_ratio")

            max_affordable_quantity = self._calculate_max_affordable_quantity(portfolio, estimated_price)
            if approved_quantity > max_affordable_quantity:
                approved_quantity = max_affordable_quantity
                triggered_rules.append("min_cash_reserve")

            max_exposure_quantity = self._calculate_max_exposure_quantity(portfolio, estimated_price)
            if approved_quantity > max_exposure_quantity:
                approved_quantity = max_exposure_quantity
                triggered_rules.append("max_total_exposure_ratio")

            if order.quantity > self.max_order_quantity:
                triggered_rules.append("max_order_quantity")

            if approved_quantity <= 0:
                decisions.append(
                    RiskDecision(
                        order_id=order.order_id,
                        action=RiskAction.REJECT,
                        approved_quantity=Decimal("0"),
                        reject_reason="订单未通过基础风控检查。",
                        triggered_rules=triggered_rules or ["risk_reject"],
                    )
                )
                continue

            action = RiskAction.APPROVE if approved_quantity == order.quantity else RiskAction.ADJUST
            decisions.append(
                RiskDecision(
                    order_id=order.order_id,
                    action=action,
                    approved_quantity=approved_quantity,
                    reject_reason=None,
                    triggered_rules=triggered_rules,
                )
            )
        return decisions

    def _estimate_order_price(self, order: OrderIntent) -> Decimal:
        """为基础风控计算估算成交价，优先使用限价，否则使用兜底价格。"""
        if order.limit_price is not None and order.limit_price > 0:
            return order.limit_price
        return Decimal("100")

    def _calculate_max_position_quantity(
        self,
        portfolio: Portfolio,
        order: OrderIntent,
        estimated_price: Decimal,
    ) -> Decimal:
        """结合已有持仓和单标的仓位上限估算最大允许下单数量。"""
        if estimated_price <= 0 or portfolio.total_value <= 0:
            return Decimal("0")
        current_position_value = Decimal("0")
        if order.symbol in portfolio.positions:
            current_position_value = portfolio.positions[order.symbol].market_value
        max_position_value = portfolio.total_value * self.max_position_value_ratio
        remaining_value = max_position_value - current_position_value
        if remaining_value <= 0:
            return Decimal("0")
        return remaining_value / estimated_price

    def _calculate_max_affordable_quantity(self, portfolio: Portfolio, estimated_price: Decimal) -> Decimal:
        """根据现金保留要求估算当前最多可买入数量。"""
        if estimated_price <= 0:
            return Decimal("0")
        available_cash = portfolio.cash - self.min_cash_reserve
        if available_cash <= 0:
            return Decimal("0")
        return available_cash / estimated_price

    def _calculate_max_exposure_quantity(self, portfolio: Portfolio, estimated_price: Decimal) -> Decimal:
        """根据组合总暴露上限估算当前还能新增的最大数量。"""
        if estimated_price <= 0 or portfolio.total_value <= 0:
            return Decimal("0")
        current_exposure = sum(position.market_value for position in portfolio.positions.values())
        max_total_exposure = portfolio.total_value * self.max_total_exposure_ratio
        remaining_exposure = max_total_exposure - current_exposure
        if remaining_exposure <= 0:
            return Decimal("0")
        return remaining_exposure / estimated_price

    def _calculate_current_drawdown(self, portfolio: Portfolio) -> Decimal:
        """根据组合净值和现金水平估算当前回撤比例。"""
        if portfolio.total_value <= 0:
            return Decimal("1")
        baseline = max(portfolio.total_value, portfolio.cash)
        if baseline <= 0:
            return Decimal("0")
        return max(Decimal("0"), (baseline - portfolio.total_value) / baseline)
