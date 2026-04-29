from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from src.domain.models.execution import Fill
from src.domain.models.order import OrderIntent
from src.domain.models.portfolio import Portfolio, Position


@dataclass
class BacktestEngine:
    commission_rate: Decimal = Decimal("0.0003")
    slippage_rate: Decimal = Decimal("0.0005")

    def simulate_orders(
        self,
        portfolio: Portfolio,
        orders: list[OrderIntent],
        latest_prices: dict[str, Decimal],
    ) -> list[Fill]:
        from datetime import datetime
        from src.domain.ids import BrokerOrderId

        fills: list[Fill] = []
        for order in orders:
            price = latest_prices.get(order.symbol)
            if price is None:
                continue
            fill_price = price * (Decimal("1") + self.slippage_rate)
            commission = fill_price * order.quantity * self.commission_rate
            fills.append(
                Fill(
                    order_id=order.order_id,
                    broker_order_id=BrokerOrderId(order.order_id.value),
                    symbol=order.symbol,
                    fill_price=fill_price,
                    fill_quantity=order.quantity,
                    commission=commission,
                    slippage=fill_price - price,
                    timestamp=datetime.now(),
                )
            )
        return fills

    def apply_fills(
        self,
        portfolio: Portfolio,
        fills: list[Fill],
    ) -> Portfolio:
        positions = dict(portfolio.positions)
        cash = portfolio.cash
        total_value = portfolio.total_value
        for fill in fills:
            cost = fill.fill_price * fill.fill_quantity + fill.commission
            cash -= cost
            positions[fill.symbol] = Position(
                symbol=fill.symbol,
                quantity=fill.fill_quantity,
                avg_cost=fill.fill_price,
                market_value=fill.fill_price * fill.fill_quantity,
                updated_at=fill.timestamp,
            )
        total_value = cash + sum(position.market_value for position in positions.values())
        return Portfolio(cash=cash, total_value=total_value, positions=positions, updated_at=fills[-1].timestamp if fills else portfolio.updated_at)
