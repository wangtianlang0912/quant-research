from __future__ import annotations

from typing import Protocol

from src.domain.enums import OrderStatus
from src.domain.models.execution import ExecutionReport, Fill
from src.domain.models.order import OrderIntent
from src.domain.models.portfolio import AccountState, Position


class ExecutionPort(Protocol):
    def submit_orders(self, orders: list[OrderIntent]) -> list[ExecutionReport]:
        ...

    def get_fills(self, order_ids: list[str]) -> list[Fill]:
        ...

    def cancel_order(self, broker_order_id: str) -> bool:
        ...

    def get_order_status(self, broker_order_id: str) -> OrderStatus:
        ...

    def get_account_state(self) -> AccountState:
        ...

    def get_positions(self) -> list[Position]:
        ...
