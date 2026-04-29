from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from src.domain.enums import RiskAction
from src.domain.ids import OrderId


@dataclass(frozen=True)
class RiskDecision:
    order_id: OrderId
    action: RiskAction
    approved_quantity: Decimal
    reject_reason: str | None = None
    triggered_rules: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RiskRuleResult:
    rule_name: str
    action: RiskAction
    message: str
