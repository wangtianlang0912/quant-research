from __future__ import annotations

from typing import Protocol

from src.domain.events import DomainEvent
from src.domain.ids import RunId
from src.domain.models.order import Order
from src.domain.models.portfolio import Portfolio
from src.domain.models.run import RunContext, RunSummary


class RunRepositoryPort(Protocol):
    def save_run_context(self, context: RunContext) -> None:
        ...

    def save_run_summary(self, summary: RunSummary) -> None:
        ...

    def get_run_summary(self, run_id: RunId) -> RunSummary | None:
        ...


class PortfolioRepositoryPort(Protocol):
    def save_portfolio(self, run_id: RunId, portfolio: Portfolio) -> None:
        ...

    def load_latest_portfolio(self, run_id: RunId) -> Portfolio | None:
        ...


class OrderRepositoryPort(Protocol):
    def save_order(self, order: Order) -> None:
        ...

    def list_orders(self, run_id: RunId) -> list[Order]:
        ...


class EventRepositoryPort(Protocol):
    def append(self, event: DomainEvent) -> None:
        ...

    def list_by_run(self, run_id: RunId) -> list[DomainEvent]:
        ...
