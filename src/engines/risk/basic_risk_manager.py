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
    enabled: bool = True

    def evaluate(
        self,
        portfolio: Portfolio,
        order_intents: list[OrderIntent],
    ) -> list[RiskDecision]:
        """对订单列表执行数量上限与全局开���检查。"""
        decisions: list[RiskDecision] = []
        for order in order_intents:
            if not self.enabled:
                decisions.append(
                    RiskDecision(
                        order_id=order.order_id,
                        action=RiskAction.REJECT,
                        approved_quantity=Decimal("0"),
                        reject_reason="风控总开关已关闭。",
                        triggered_rules=["risk_disabled"],
                    )
                )
                continue
            approved_quantity = min(order.quantity, self.max_order_quantity)
            action = RiskAction.APPROVE if approved_quantity == order.quantity else RiskAction.ADJUST
            decisions.append(
                RiskDecision(
                    order_id=order.order_id,
                    action=action,
                    approved_quantity=approved_quantity,
                    reject_reason=None,
                    triggered_rules=[] if action == RiskAction.APPROVE else ["max_order_quantity"],
                )
            )
        return decisions
