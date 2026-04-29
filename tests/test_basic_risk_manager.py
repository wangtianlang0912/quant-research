from __future__ import annotations

from decimal import Decimal

from src.domain.enums import OrderSide, OrderType, RiskAction
from src.domain.ids import OrderId, StrategyId
from src.domain.models.order import OrderIntent
from src.domain.models.portfolio import Portfolio, Position
from src.engines.risk import BasicRiskManager


def test_basic_risk_manager_adjusts_quantity_and_supports_kill_switch() -> None:
    """验证基础风控能够调整订单数量并支持Kill Switch。"""
    manager = BasicRiskManager(
        max_order_quantity=Decimal("100"),
        max_position_value_ratio=Decimal("0.5"),
        max_total_exposure_ratio=Decimal("0.8"),
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


def test_basic_risk_manager_limits_total_exposure() -> None:
    """验证基础风控能够限制组合总暴露比例。"""
    manager = BasicRiskManager(
        max_order_quantity=Decimal("1000"),
        max_position_value_ratio=Decimal("0.8"),
        max_total_exposure_ratio=Decimal("0.5"),
        min_cash_reserve=Decimal("0"),
    )
    portfolio = Portfolio(
        cash=Decimal("50000"),
        total_value=Decimal("100000"),
        positions={
            "000001.SH": Position(
                symbol="000001.SH",
                quantity=Decimal("300"),
                avg_cost=Decimal("100"),
                market_value=Decimal("30000"),
                updated_at=__import__("datetime").datetime.now(),
            )
        },
    )
    order = OrderIntent(
        order_id=OrderId("order-2"),
        strategy_id=StrategyId("strategy-2"),
        symbol="000300.SH",
        side=OrderSide.BUY,
        quantity=Decimal("500"),
        order_type=OrderType.MARKET,
        timestamp=__import__("datetime").datetime.now(),
        limit_price=Decimal("100"),
    )

    decisions = manager.evaluate(portfolio, [order])
    assert len(decisions) == 1
    assert decisions[0].approved_quantity <= Decimal("200")
