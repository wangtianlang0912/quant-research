from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.domain.enums import EventType, OrderStatus
from src.domain.events import DomainEvent
from src.domain.ids import BrokerOrderId, RunId
from src.domain.models.execution import ExecutionReport, Fill
from src.domain.models.order import Order, OrderIntent
from src.domain.models.portfolio import AccountState, Portfolio, Position
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
from src.engines.risk import BasicRiskManager
from src.engines.backtest import BacktestEngine
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
        """忽略普通通知消息。"""
        return None

    def send_warning(self, title: str, message: str) -> None:
        """忽略告警通知消息。"""
        return None

    def send_error(self, title: str, message: str) -> None:
        """忽略错误通知消息。"""
        return None


class InMemoryRunRepository(RunRepositoryPort):
    def __init__(self) -> None:
        """初始化运行记录的内存存储。"""
        self._summaries: dict[str, RunSummary] = {}
        self._contexts: dict[str, RunContext] = {}

    def save_run_context(self, context: RunContext) -> None:
        """保存运行上下文到内存。"""
        self._contexts[context.run_id.value] = context

    def save_run_summary(self, summary: RunSummary) -> None:
        """保存运行摘要到内存。"""
        self._summaries[summary.run_id.value] = summary

    def get_run_summary(self, run_id: RunId) -> RunSummary | None:
        """根据运行ID获取运行摘要。"""
        return self._summaries.get(run_id.value)


class InMemoryPortfolioRepository(PortfolioRepositoryPort):
    def __init__(self) -> None:
        """初始化组合状态的内存存储。"""
        self._data: dict[str, Portfolio] = {}
        self._history: dict[str, list[Portfolio]] = {}

    def save_portfolio(self, run_id: RunId, portfolio: Portfolio) -> None:
        """保存指定运行的组合快照。"""
        self._data[run_id.value] = portfolio
        self._history.setdefault(run_id.value, []).append(portfolio)

    def load_latest_portfolio(self, run_id: RunId) -> Portfolio | None:
        """读取指定运行最近一次保存的组合状态。"""
        return self._data.get(run_id.value)

    def list_portfolio_history(self, run_id: RunId) -> list[Portfolio]:
        """返回指定运行下保存过的全部组合快照。"""
        return list(self._history.get(run_id.value, []))


class InMemoryOrderRepository(OrderRepositoryPort):
    def __init__(self) -> None:
        """初始化订单内存存储。"""
        self._orders: list[Order] = []

    def save_order(self, order: Order) -> None:
        """保存订单记录到内存。"""
        self._orders.append(order)

    def list_orders(self, run_id: RunId) -> list[Order]:
        """返回当前内存中的全部订单记录。"""
        return list(self._orders)


class InMemoryEventRepository(EventRepositoryPort):
    def __init__(self) -> None:
        """初始化事件日志的内存存储。"""
        self._events: list[DomainEvent] = []

    def append(self, event: DomainEvent) -> None:
        """追加一条领域事件。"""
        self._events.append(event)

    def list_by_run(self, run_id: RunId) -> list[DomainEvent]:
        """按运行ID筛选相关领域事件。"""
        return [event for event in self._events if event.run_id == run_id]


class NoopExecutionGateway(ExecutionPort):
    def submit_orders(self, orders: list[OrderIntent]) -> list[ExecutionReport]:
        """接收订单并返回已提交状态的模拟回��。"""
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
        """返回空成交列表，供MVP阶段占位使用。"""
        return []

    def cancel_order(self, broker_order_id: str) -> bool:
        """模拟撤单成功。"""
        return True

    def get_order_status(self, broker_order_id: str) -> OrderStatus:
        """返回模拟订单状态。"""
        return OrderStatus.SUBMITTED

    def get_account_state(self) -> AccountState:
        """返回默认模拟账户状态。"""
        return AccountState(
            account_id="noop-account",
            cash_available=Decimal("1000000"),
            equity=Decimal("1000000"),
            positions={},
            updated_at=datetime.now(),
        )

    def get_positions(self) -> list[Position]:
        """返回空持仓列表。"""
        return []


class PaperExecutionGateway(ExecutionPort):
    def __init__(self) -> None:
        """初始化纸盘执行网关的订单回报内存存储。"""
        self._reports: dict[str, ExecutionReport] = {}

    def submit_orders(self, orders: list[OrderIntent]) -> list[ExecutionReport]:
        """在纸盘模式下记录订单已提交状态并返回提交回报。"""
        now = datetime.now()
        reports = [
            ExecutionReport(
                order_id=order.order_id,
                broker_order_id=BrokerOrderId(f"paper-{order.order_id.value}"),
                status=OrderStatus.SUBMITTED,
                message="accepted by paper execution gateway",
                timestamp=now,
            )
            for order in orders
        ]
        for report in reports:
            self._reports[report.broker_order_id.value] = report
        return reports

    def get_fills(self, order_ids: list[str]) -> list[Fill]:
        """纸盘模式下暂不返回真实成交。"""
        return []

    def cancel_order(self, broker_order_id: str) -> bool:
        """模拟纸盘撤单成功，并将状态��新为已取消。"""
        if broker_order_id not in self._reports:
            return False
        report = self._reports[broker_order_id]
        self._reports[broker_order_id] = ExecutionReport(
            order_id=report.order_id,
            broker_order_id=report.broker_order_id,
            status=OrderStatus.CANCELED,
            message="cancelled by paper execution gateway",
            timestamp=datetime.now(),
        )
        return True

    def get_order_status(self, broker_order_id: str) -> OrderStatus:
        """返回纸盘订单当前状态，未找到时默认返回已提交。"""
        report = self._reports.get(broker_order_id)
        if report is None:
            return OrderStatus.SUBMITTED
        return report.status

    def get_account_state(self) -> AccountState:
        """返回默认纸盘账户状态。"""
        return AccountState(
            account_id="paper-account",
            cash_available=Decimal("1000000"),
            equity=Decimal("1000000"),
            positions={},
            updated_at=datetime.now(),
        )

    def get_positions(self) -> list[Position]:
        """返回纸盘持仓列表，当前为占位实现。"""
        return []

    def list_reports(self) -> list[ExecutionReport]:
        """返回当前纸盘执行网关已记录的全部订单回报。"""
        return list(self._reports.values())


def build_backtest_container(
    strategy: StrategyPort,
    market_data: MarketDataPort,
    risk_params: dict | None = None,
) -> tuple[AppContainer, BacktestEngine]:
    """构建用于本地回测的应用容器，返回 (容器, 回测引擎)。"""
    risk_params = risk_params or {}
    risk_kwargs = {}
    engine_kwargs = {}
    for k, v in risk_params.items():
        if hasattr(BasicRiskManager, k):
            risk_kwargs[k] = v
        elif hasattr(BacktestEngine, k):
            engine_kwargs[k] = v
    backtest_engine = BacktestEngine(**engine_kwargs)
    return AppContainer(
        market_data=market_data,
        strategy=strategy,
        risk_manager=BasicRiskManager(**risk_kwargs),
        execution_gateway=NoopExecutionGateway(),
        run_repository=InMemoryRunRepository(),
        portfolio_repository=InMemoryPortfolioRepository(),
        order_repository=InMemoryOrderRepository(),
        event_repository=InMemoryEventRepository(),
        notifier=NullNotificationAdapter(),
        clock=SystemClock(),
    ), backtest_engine


def build_paper_container(
    strategy: StrategyPort,
    market_data: MarketDataPort,
) -> AppContainer:
    """构建用于纸盘模式的应用容器。"""
    return AppContainer(
        market_data=market_data,
        strategy=strategy,
        risk_manager=BasicRiskManager(),
        execution_gateway=PaperExecutionGateway(),
        run_repository=InMemoryRunRepository(),
        portfolio_repository=InMemoryPortfolioRepository(),
        order_repository=InMemoryOrderRepository(),
        event_repository=InMemoryEventRepository(),
        notifier=NullNotificationAdapter(),
        clock=SystemClock(),
    )
