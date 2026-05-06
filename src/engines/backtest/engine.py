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
        from src.domain.enums import OrderSide
        from src.domain.ids import BrokerOrderId

        fills: list[Fill] = []
        for order in orders:
            price = latest_prices.get(order.symbol)
            if price is None:
                continue
            # 买入加滑点，卖出减滑点（更真实的模拟）
            if order.side == OrderSide.BUY:
                fill_price = price * (Decimal("1") + self.slippage_rate)
            else:
                fill_price = price * (Decimal("1") - self.slippage_rate)
            commission = fill_price * order.quantity * self.commission_rate
            # 卖出时 fill_quantity 取负，方便 apply_fills 统一处理
            fill_qty = order.quantity if order.side == OrderSide.BUY else -order.quantity
            fills.append(
                Fill(
                    order_id=order.order_id,
                    broker_order_id=BrokerOrderId(order.order_id.value),
                    symbol=order.symbol,
                    fill_price=fill_price,
                    fill_quantity=fill_qty,
                    commission=commission,
                    slippage=abs(fill_price - price),
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
        for fill in fills:
            # fill_quantity: 正=买，负=卖
            if fill.fill_quantity >= 0:
                # 买入：扣 cash，加持仓
                cost = fill.fill_price * fill.fill_quantity + fill.commission
                cash -= cost
                existing = positions.get(fill.symbol)
                if existing is None:
                    qty = fill.fill_quantity
                else:
                    prev_cost = existing.avg_cost * existing.quantity
                    new_cost = fill.fill_price * fill.fill_quantity
                    total_qty = existing.quantity + fill.fill_quantity
                    qty = total_qty
                positions[fill.symbol] = Position(
                    symbol=fill.symbol,
                    quantity=qty,
                    avg_cost=fill.fill_price,
                    market_value=fill.fill_price * qty,
                    updated_at=fill.timestamp,
                )
            else:
                # 卖出：加 cash，减持仓（fill_quantity 为负，取绝对值）
                sell_qty = abs(fill.fill_quantity)
                existing = positions.get(fill.symbol)
                if existing is None:
                    continue  # 没有持仓，无法卖出
                proceeds = fill.fill_price * sell_qty - fill.commission
                cash += proceeds
                remaining = existing.quantity - sell_qty
                if remaining <= 0:
                    positions.pop(fill.symbol, None)
                else:
                    positions[fill.symbol] = Position(
                        symbol=fill.symbol,
                        quantity=remaining,
                        avg_cost=existing.avg_cost,
                        market_value=fill.fill_price * remaining,
                        updated_at=fill.timestamp,
                    )
        total_value = cash + sum(pos.market_value for pos in positions.values())
        return Portfolio(
            cash=cash,
            total_value=total_value,
            positions=positions,
            updated_at=fills[-1].timestamp if fills else portfolio.updated_at,
        )
