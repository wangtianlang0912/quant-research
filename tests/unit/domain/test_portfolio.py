"""组合快照契约（E-02 风控输入）。

★ v1 缺陷对照：`basic_risk_manager.py` 把买入与卖出走同一套约束，
导致"现金 1 万 + 持仓 99 万时卖 1000 股被 reject"—— 超仓后永久无法减仓。

本模块本身只提供"一致快照"，分流的判定在 `RiskManager`（见 `test_ports_contract.py` 的
RiskDecision 契约）。这里锁死的是**估值口径**：市值/成本/盈亏全部用 `Decimal`，
且空仓（`quantity == 0`）不得产生除零。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from quant_v2.domain.models.portfolio import PortfolioSnapshot, Position

pytestmark = pytest.mark.unit

AS_OF = date(2026, 9, 5)


def d(value: str) -> Decimal:
    """构造 Decimal（测试里禁止 float 字面量）。"""
    return Decimal(value)


def make_position(
    *,
    symbol: str = "601186.SH",
    market: str = "cn_a",
    quantity: int = 100,
    avg_cost: str = "10",
    last_price: str = "12",
    currency: str = "CNY",
) -> Position:
    return Position(
        symbol=symbol,
        market=market,
        quantity=quantity,
        avg_cost=d(avg_cost),
        last_price=d(last_price),
        currency=currency,
    )


class TestPosition:
    def test_市值等于股数乘最近价(self) -> None:
        assert make_position(quantity=100, last_price="12").market_value == d("1200")

    def test_成本等于股数乘均价(self) -> None:
        assert make_position(quantity=100, avg_cost="10").cost_basis == d("1000")

    def test_未实现盈亏(self) -> None:
        position = make_position(quantity=100, avg_cost="10", last_price="12")
        assert position.unrealized_pnl == d("200")
        assert position.unrealized_pnl_pct == d("0.2")

    def test_浮亏为负(self) -> None:
        position = make_position(quantity=100, avg_cost="10", last_price="9.5")
        assert position.unrealized_pnl == d("-50")
        assert position.unrealized_pnl_pct == d("-0.05")

    def test_空仓盈亏为零且比例不除零(self) -> None:
        """★ 空仓时 cost_basis == 0，必须返回 0 而不是抛 ZeroDivisionError。"""
        position = make_position(quantity=0)
        assert position.market_value == d("0")
        assert position.cost_basis == d("0")
        assert position.unrealized_pnl == d("0")
        assert position.unrealized_pnl_pct == d("0")

    @pytest.mark.parametrize("quantity", [-1, -100])
    def test_股数不可为负(self, quantity: int) -> None:
        with pytest.raises(ValidationError):
            make_position(quantity=quantity)

    @pytest.mark.parametrize(("avg_cost", "last_price"), [("0", "12"), ("10", "0"), ("-1", "12")])
    def test_价格必须为正(self, avg_cost: str, last_price: str) -> None:
        """★ 禁止 0 / 负价：0 元估值会让风控算出"无限可买"的仓位。"""
        with pytest.raises(ValidationError):
            make_position(avg_cost=avg_cost, last_price=last_price)

    def test_冻结模型不可写(self) -> None:
        position = make_position()
        with pytest.raises(ValidationError):
            position.quantity = 200


class TestPortfolioSnapshot:
    def build(self) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            as_of=AS_OF,
            cash=d("5000"),
            positions=(
                make_position(symbol="601186.SH", quantity=100, avg_cost="10", last_price="12"),
                make_position(symbol="000001.SZ", quantity=0, avg_cost="10", last_price="10"),
            ),
        )

    def test_市值汇总(self) -> None:
        assert self.build().market_value == d("1200")

    def test_总资产等于现金加市值(self) -> None:
        assert self.build().equity_total == d("6200")

    def test_持仓数只计有仓位的标的(self) -> None:
        """空仓标的（quantity == 0）不计入"同时持仓数"，否则永远无法开新仓。"""
        assert self.build().open_positions == 1

    def test_无持仓时市值为零(self) -> None:
        snapshot = PortfolioSnapshot(as_of=AS_OF, cash=d("5000"), positions=())
        assert snapshot.market_value == d("0")
        assert snapshot.equity_total == d("5000")
        assert snapshot.open_positions == 0

    def test_按symbol与market查持仓(self) -> None:
        snapshot = self.build()
        found = snapshot.position_for("601186.SH", "cn_a")
        assert found is not None
        assert found.quantity == 100

    def test_市场不同则查不到(self) -> None:
        """同一代码在不同市场是不同标的，不能只看 symbol。"""
        assert self.build().position_for("601186.SH", "hk") is None

    def test_查不到的持仓返回None而不是空仓位(self) -> None:
        """★ 返回 None 而不是空 Position：空 Position 会让调用方误判"有持仓但价格是 0"。"""
        assert self.build().position_for("999999.SH", "cn_a") is None

    def test_取股数(self) -> None:
        snapshot = self.build()
        assert snapshot.quantity_of("601186.SH", "cn_a") == 100
        assert snapshot.quantity_of("000001.SZ", "cn_a") == 0
        assert snapshot.quantity_of("999999.SH", "cn_a") == 0

    def test_as_of原样保留(self) -> None:
        assert self.build().as_of == AS_OF
