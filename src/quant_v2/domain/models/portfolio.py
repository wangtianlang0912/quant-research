"""组合快照契约（E-02 风控输入）。

★ v1 缺陷对照：`basic_risk_manager.py` 把买入与卖出走同一套约束，
导致"现金 1 万 + 持仓 99 万时卖 1000 股被 reject"—— 超仓后永久无法减仓。
v2 的解法是让风控按 `side` 分流，而这个分流的依据就是本模块的 `PortfolioSnapshot`。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["PortfolioSnapshot", "Position"]


class Position(BaseModel):
    """单个持仓。

    ★ `last_price` 必须来自 `ValuationProvider.last_price()` 的真实最近价；
    取不到必须抛 `PriceUnavailableError`，**禁止任何默认值兜底**（ARCH003）。
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    symbol: str
    market: str
    quantity: int = Field(ge=0)
    avg_cost: Decimal = Field(gt=0)
    last_price: Decimal = Field(gt=0)
    currency: str

    @property
    def market_value(self) -> Decimal:
        """市值 = 股数 × 最近价。"""
        return Decimal(self.quantity) * self.last_price

    @property
    def cost_basis(self) -> Decimal:
        """成本 = 股数 × 均价。"""
        return Decimal(self.quantity) * self.avg_cost

    @property
    def unrealized_pnl(self) -> Decimal:
        """未实现盈亏（本币）。"""
        return self.market_value - self.cost_basis

    @property
    def unrealized_pnl_pct(self) -> Decimal:
        """未实现盈亏比例。"""
        if self.cost_basis == 0:
            return Decimal("0")
        return self.unrealized_pnl / self.cost_basis


@dataclass(frozen=True)
class PortfolioSnapshot:
    """组合快照 —— `RiskManager.evaluate()` 的输入。

    设计为不可变：风控判定必须基于"某一时刻的一致快照"，
    可变的快照会让同一笔订单在校验过程中看到不同的世界。
    """

    as_of: date
    cash: Decimal
    positions: tuple[Position, ...]

    @property
    def market_value(self) -> Decimal:
        """持仓总市值。"""
        return sum((p.market_value for p in self.positions), Decimal("0"))

    @property
    def equity_total(self) -> Decimal:
        """总资产 = 现金 + 持仓市值。"""
        return self.cash + self.market_value

    @property
    def open_positions(self) -> int:
        """当前持仓数量（只计有持仓的标的）。"""
        return sum(1 for p in self.positions if p.quantity > 0)

    def position_for(self, symbol: str, market: str) -> Position | None:
        """按 symbol + market 查持仓；没有返回 `None`（不返回空 Position）。"""
        for position in self.positions:
            if position.symbol == symbol and position.market == market:
                return position
        return None

    def quantity_of(self, symbol: str, market: str) -> int:
        """某标的的持仓股数；无持仓返回 0。"""
        position = self.position_for(symbol, market)
        return position.quantity if position is not None else 0
