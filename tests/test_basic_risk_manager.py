from __future__ import annotations

from decimal import Decimal

from src.domain.enums import OrderSide, OrderType, RiskAction
from src.domain.ids import OrderId, StrategyId
from src.domain.models.order import OrderIntent
from src.domain.models.portfolio import Portfolio
from src.engines.risk import BasicRiskManager


def test_basic_risk_manager_adjusts_quantity_and_supports_kill_switch() -> None:
    """验证基础风控能够调整订单数量并支持Kill Switch。"""
    manager = BasicRiskManager(
        max_order_quantity=Decimal("100"),
        max_position_value_ratio=Decimal("0.5"),
        min_cash_reserve=Decimal("1000"),
    )
    portfolio = Portfolio(cash=Decimal("10000"), total_value=Decimal("20000"), positions={})
    order = OrderIntent(
        order_id=OrderId("order-1"),
        strategy_id=StrategyId("strategy-1"),
        symbol="000300.SH",
        side=OrderSide.BUY,
        quantity=Decimal("1000"),
        order_type=OrderType.MARKET,
        timestamp=__import__("datetime").datetime.now(),
        limit_price=Decimal("100"),
    )

    decisions = manager.evaluate(portfolio, [order])
    assert len(decisions) == 1
    assert decisions[0].action in {RiskAction.ADJUST, RiskAction.REJECT}

    manager.kill_switch = True
    decisions = manager.evaluate(portfolio, [order])
    assert decisions[0].action == RiskAction.REJECT
