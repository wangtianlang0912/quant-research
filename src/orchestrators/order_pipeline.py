from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.domain.enums import EventType, OrderSide, OrderType, RiskAction, SignalDirection
from src.domain.events import DomainEvent
from src.domain.ids import OrderId
from src.domain.models.execution import ExecutionReport
from src.domain.models.order import OrderIntent
from src.domain.models.portfolio import Portfolio
from src.domain.models.risk import RiskDecision
from src.domain.models.signal import Signal, TargetPosition
from src.domain.models.strategy import StrategyMetadata
from src.domain.ports.execution_port import ExecutionPort
from src.domain.ports.repository_port import EventRepositoryPort
from src.domain.ports.risk_port import RiskPort


@dataclass
class OrderPipeline:
    risk_manager: RiskPort
    execution_gateway: ExecutionPort
    event_repository: EventRepositoryPort | None = None

    def build_order_intents(
        self,
        outputs: list[Signal] | list[TargetPosition],
        metadata: StrategyMetadata,
    ) -> list[OrderIntent]:
        """根据策略输出构造订单意图列表。"""
        orders: list[OrderIntent] = []
        now = datetime.now()
        for idx, item in enumerate(outputs, start=1):
            if isinstance(item, Signal):
                if item.direction == SignalDirection.FLAT:
                    continue
                side = OrderSide.BUY if item.direction == SignalDirection.LONG else OrderSide.SELL
                quantity = Decimal("100")
                orders.append(
                    OrderIntent(
                        order_id=OrderId(f"{metadata.strategy_id.value}-{int(now.timestamp())}-{idx}"),
                        strategy_id=metadata.strategy_id,
                        symbol=item.symbol,
                        side=side,
                        quantity=quantity,
                        order_type=OrderType.MARKET,
                        timestamp=item.timestamp,
                        source_signal_id=item.signal_id,
                        metadata={"reason": item.reason},
                    )
                )
            elif isinstance(item, TargetPosition):
                if item.target_quantity is None or item.target_quantity == Decimal("0"):
                    continue
                side = OrderSide.BUY if item.target_quantity > 0 else OrderSide.SELL
                orders.append(
                    OrderIntent(
                        order_id=OrderId(f"{metadata.strategy_id.value}-{int(now.timestamp())}-{idx}"),
                        strategy_id=metadata.strategy_id,
                        symbol=item.symbol,
                        side=side,
                        quantity=abs(item.target_quantity),
                        order_type=OrderType.MARKET,
                        timestamp=item.timestamp,
                        metadata={"reason": item.reason},
                    )
                )
        return orders

    def evaluate_risk(
        self,
        portfolio: Portfolio,
        order_intents: list[OrderIntent],
    ) -> list[RiskDecision]:
        """调用风控模块对订单意图进行审核。"""
        decisions = self.risk_manager.evaluate(portfolio, order_intents)
        return decisions

    def filter_approved_orders(
        self,
        order_intents: list[OrderIntent],
        decisions: list[RiskDecision],
    ) -> list[OrderIntent]:
        """根据风控决策筛选并调整允许执行的订单列表。"""
        decision_map = {decision.order_id: decision for decision in decisions}
        approved: list[OrderIntent] = []
        for order in order_intents:
            decision = decision_map.get(order.order_id)
            if decision is None:
                continue
            if decision.action == RiskAction.REJECT or decision.approved_quantity <= 0:
                continue
            approved.append(
                OrderIntent(
                    order_id=order.order_id,
                    strategy_id=order.strategy_id,
                    symbol=order.symbol,
                    side=order.side,
                    quantity=decision.approved_quantity,
                    order_type=order.order_type,
                    timestamp=order.timestamp,
                    limit_price=order.limit_price,
                    source_signal_id=order.source_signal_id,
                    metadata=order.metadata,
                )
            )
        return approved

    def execute(self, approved_orders: list[OrderIntent]) -> list[ExecutionReport]:
        """将通过风控的订单提交给执行网关。"""
        reports = self.execution_gateway.submit_orders(approved_orders)
        return reports

    def record_risk_event(
        self,
        run_id,
        strategy_id,
        decisions: list[RiskDecision],
    ) -> None:
        """记录一次风控评估事件，便于后续审计和排查。"""
        if self.event_repository is None:
            return
        reject_reasons = [decision.reject_reason for decision in decisions if decision.reject_reason]
        adjusted_order_count = sum(1 for decision in decisions if decision.action == RiskAction.ADJUST)
        self.event_repository.append(
            DomainEvent(
                event_type=EventType.RISK_EVALUATED,
                run_id=run_id,
                strategy_id=strategy_id,
                timestamp=datetime.now(),
                payload={
                    "decision_count": len(decisions),
                    "approved_count": sum(1 for d in decisions if d.action != RiskAction.REJECT),
                    "rejected_count": sum(1 for d in decisions if d.action == RiskAction.REJECT),
                    "adjusted_order_count": adjusted_order_count,
                    "triggered_rules": [rule for d in decisions for rule in d.triggered_rules],
                    "reject_reasons": reject_reasons,
                },
            )
        )

    def record_execution_event(
        self,
        run_id,
        strategy_id,
        reports: list[ExecutionReport],
    ) -> None:
        """记录一次订单提交事件，便于后续追踪执行结果。"""
        if self.event_repository is None:
            return
        self.event_repository.append(
            DomainEvent(
                event_type=EventType.ORDER_SUBMITTED,
                run_id=run_id,
                strategy_id=strategy_id,
                timestamp=datetime.now(),
                payload={
                    "report_count": len(reports),
                    "submitted_count": len(reports),
                },
            )
        )
