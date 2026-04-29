from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.domain.enums import OrderStatus, RiskAction
from src.domain.events import DomainEvent
from src.domain.ids import BrokerOrderId, RunId
from src.domain.models.execution import ExecutionReport, Fill
from src.domain.models.order import Order, OrderIntent
from src.domain.models.portfolio import AccountState, Portfolio, Position
from src.domain.models.risk import RiskDecision
from src.domain.models.run import RunContext, RunSummary
from src.domain.ports.clock_port import ClockPort
from src.domain.ports.execution_port import ExecutionPort
from src.domain.ports.market_data_port import MarketDataPort
from src.domain.ports.notification_port import NotificationPort
from src.domain.ports.repository_port import (
    EventRepositoryPort,
    OrderRepositoryPort,
    PortfolioRepositoryPort,
    RunRepositoryPort,
)
from src.domain.ports.risk_port import RiskPort
from src.domain.ports.strategy_port import StrategyPort
from src.services.clock.system_clock import SystemClock


@dataclass
class AppContainer:
    market_data: MarketDataPort
    strategy: StrategyPort
    risk_manager: RiskPort
    execution_gateway: ExecutionPort
    run_repository: RunRepositoryPort
    portfolio_repository: PortfolioRepositoryPort
    order_repository: OrderRepositoryPort
    event_repository: EventRepositoryPort
    notifier: NotificationPort
    clock: ClockPort


class NullNotificationAdapter(NotificationPort):
    def send_info(self, title: str, message: str) -> None:
        return None

    def send_warning(self, title: str, message: str) -> None:
        return None

    def send_error(self, title: str, message: str) -> None:
        return None


class InMemoryRunRepository(RunRepositoryPort):
    def __init__(self) -> None:
        self._summaries: dict[str, RunSummary] = {}
        self._contexts: dict[str, RunContext] = {}

    def save_run_context(self, context: RunContext) -> None:
        self._contexts[context.run_id.value] = context

    def save_run_summary(self, summary: RunSummary) -> None:
        self._summaries[summary.run_id.value] = summary

    def get_run_summary(self, run_id: RunId) -> RunSummary | None:
        return self._summaries.get(run_id.value)


class InMemoryPortfolioRepository(PortfolioRepositoryPort):
    def __init__(self) -> None:
        self._data: dict[str, Portfolio] = {}

    def save_portfolio(self, run_id: RunId, portfolio: Portfolio) -> None:
        self._data[run_id.value] = portfolio

    def load_latest_portfolio(self, run_id: RunId) -> Portfolio | None:
        return self._data.get(run_id.value)


class InMemoryOrderRepository(OrderRepositoryPort):
    def __init__(self) -> None:
        self._orders: list[Order] = []

    def save_order(self, order: Order) -> None:
        self._orders.append(order)

    def list_orders(self, run_id: RunId) -> list[Order]:
        return list(self._orders)


class InMemoryEventRepository(EventRepositoryPort):
    def __init__(self) -> None:
        self._events: list[DomainEvent] = []

    def append(self, event: DomainEvent) -> None:
        self._events.append(event)

    def list_by_run(self, run_id: RunId) -> list[DomainEvent]:
        return [event for event in self._events if event.run_id == run_id]


class NoopRiskManager(RiskPort):
    def evaluate(
        self,
        portfolio: Portfolio,
        order_intents: list[OrderIntent],
    ) -> list[RiskDecision]:
        return [
            RiskDecision(
                order_id=order.order_id,
                action=RiskAction.APPROVE,
                approved_quantity=Decimal(order.quantity),
                reject_reason=None,
                triggered_rules=[],
            )
            for order in order_intents
        ]


class NoopExecutionGateway(ExecutionPort):
    def submit_orders(self, orders: list[OrderIntent]) -> list[ExecutionReport]:
        now = datetime.now()
        return [
            ExecutionReport(
                order_id=order.order_id,
                broker_order_id=BrokerOrderId(order.order_id.value),
                status=OrderStatus.SUBMITTED,
                message="accepted by noop execution gateway",
                timestamp=now,
            )
            for order in orders
        ]

    def get_fills(self, order_ids: list[str]) -> list[Fill]:
        return []

    def cancel_order(self, broker_order_id: str) -> bool:
        return True

    def get_order_status(self, broker_order_id: str) -> OrderStatus:
        return OrderStatus.SUBMITTED

    def get_account_state(self) -> AccountState:
        return AccountState(
            account_id="noop-account",
            cash_available=Decimal("1000000"),
            equity=Decimal("1000000"),
            positions={},
            updated_at=datetime.now(),
        )

    def get_positions(self) -> list[Position]:
        return []


def build_backtest_container(
    strategy: StrategyPort,
    market_data: MarketDataPort,
) -> AppContainer:
    return AppContainer(
        market_data=market_data,
        strategy=strategy,
        risk_manager=NoopRiskManager(),
        execution_gateway=NoopExecutionGateway(),
        run_repository=InMemoryRunRepository(),
        portfolio_repository=InMemoryPortfolioRepository(),
        order_repository=InMemoryOrderRepository(),
        event_repository=InMemoryEventRepository(),
        notifier=NullNotificationAdapter(),
        clock=SystemClock(),
    )


def build_paper_container(
    strategy: StrategyPort,
    market_data: MarketDataPort,
) -> AppContainer:
    return AppContainer(
        market_data=market_data,
        strategy=strategy,
        risk_manager=NoopRiskManager(),
        execution_gateway=NoopExecutionGateway(),
        run_repository=InMemoryRunRepository(),
        portfolio_repository=InMemoryPortfolioRepository(),
        order_repository=InMemoryOrderRepository(),
        event_repository=InMemoryEventRepository(),
        notifier=NullNotificationAdapter(),
        clock=SystemClock(),
    )
