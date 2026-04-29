from __future__ import annotations

from typing import Protocol

from src.domain.models.order import OrderIntent
from src.domain.models.portfolio import Portfolio
from src.domain.models.risk import RiskDecision


class RiskPort(Protocol):
    def evaluate(
        self,
        portfolio: Portfolio,
        order_intents: list[OrderIntent],
    ) -> list[RiskDecision]:
        ...
