"""订单与仓位计算契约（E-01 / E-04）。

★ 这里承载 v1 三个执行层 P0 的根治断言：

1. `order_pipeline.py:40` 的 `quantity = Decimal("100")` —— 每笔都买 100 股。
   v2：股数只来自 `Sizer.size()`，`SizingResult.quantity` 必须为正且带推导说明。
2. `basic_risk_manager.py:112-116` 用 `Decimal("100")` 兜底估值 —— 由 `PriceUnavailableError` 根治。
3. 限价单没有 `limit_price` —— `OrderIntent` 构造即失败（E-04）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from quant_v2.domain.models.market import CostModel, MarketProfile, PriceLimitSpec, TickSpec
from quant_v2.domain.models.order import (
    MIN_BARS_FOR_RELIABLE_ADV,
    CappedBy,
    LiquiditySnapshot,
    OrderIntent,
    OrderSide,
    OrderType,
    SizingRequest,
    SizingResult,
)
from quant_v2.domain.models.signal import RawSignal

pytestmark = pytest.mark.unit

CREATED_AT = datetime(2026, 9, 5, 1, 30, tzinfo=UTC)


def d(value: str) -> Decimal:
    """构造 Decimal（测试里禁止 float 字面量）。"""
    return Decimal(value)


def make_signal() -> RawSignal:
    return RawSignal(
        signal_id="sig-001",
        strategy_id="value_breakout",
        symbol="601186.SH",
        market="cn_a",
        as_of=date(2026, 9, 5),
        generated_at=CREATED_AT,
        score=d("72"),
        entry_low=d("10"),
        entry_high=d("10.5"),
        target_price=d("12"),
        stop_loss_price=d("9.5"),
        max_holding_days=20,
        suggested_notional=d("5000"),
        rationale="估值处于全市场最低 10%，且站上 20 日均线",
    )


def make_liquidity(*, bars_available: int = 20) -> LiquiditySnapshot:
    return LiquiditySnapshot(
        symbol="601186.SH",
        market="cn_a",
        as_of=date(2026, 9, 5),
        adv_amount_20d=d("300000000"),
        adv_volume_20d=d("30000000"),
        bars_available=bars_available,
    )


def make_market_profile() -> MarketProfile:
    """A 股最小画像：SizingRequest 只用它取 lot_size / tick。"""
    return MarketProfile(
        market_code="cn_a",
        display_name="中国 A 股",
        timezone="Asia/Shanghai",
        calendar_id="cn_a",
        currency="CNY",
        settlement_currency=None,
        lot_size=100,
        odd_lot_allowed=False,
        tick=TickSpec(tick_size=d("0.01")),
        price_limit=PriceLimitSpec(limit_pct=d("0.1"), st_limit_pct=d("0.05")),
        t_plus=1,
        shortable=False,
        cost=CostModel(
            commission_rate=d("0.00025"),
            commission_min=d("5"),
            tax_rate_sell=d("0.0005"),
            tax_rate_buy=d("0"),
            transfer_fee_rate=d("0.00001"),
            exchange_fee_rate=d("0.0000487"),
            slippage_bps=10,
        ),
        symbol_pattern=r"^\d{6}\.(SH|SZ)$",
        half_day_dates=(),
        extra_holidays=(),
        fund_availability="FULL",
        delisting_data_availability="PARTIAL",
        max_symbols=5000,
        data_sources=(),
    )


class TestOrderSide:
    def test_只有买卖两个方向(self) -> None:
        assert {side.value for side in OrderSide} == {"BUY", "SELL"}

    @pytest.mark.regression
    def test_卖出与买入是不同枚举值(self) -> None:
        """★ 风控按 side 分流的前提：两个方向必须是可区分的一等字段。

        v1 反例：现金 1 万 + 持仓 99 万时卖 1000 股被 reject —— 超仓后永久无法减仓。
        """
        assert OrderSide.BUY is not OrderSide.SELL


class TestOrderIntent:
    def make_intent(self, **overrides: object) -> OrderIntent:
        kwargs: dict[str, object] = {
            "signal_id": "sig-001",
            "symbol": "601186.SH",
            "market": "cn_a",
            "side": OrderSide.BUY,
            "order_type": OrderType.MARKET,
            "quantity": 100,
            "notional": d("1050"),
            "reason_human": "站上 20 日均线，估值处于全市场最低 10%",
            "created_at": CREATED_AT,
        }
        kwargs.update(overrides)
        return OrderIntent(**kwargs)  # type: ignore[arg-type]

    def test_市价单无需限价(self) -> None:
        intent = self.make_intent(order_type=OrderType.MARKET)
        assert intent.limit_price is None
        assert intent.run_id is None

    def test_限价单带限价合法(self) -> None:
        intent = self.make_intent(order_type=OrderType.LIMIT, limit_price=d("10.2"))
        assert intent.limit_price == d("10.2")

    @pytest.mark.regression
    def test_限价单缺限价构造即失败(self) -> None:
        """★ E-04：没有限价的限价单在撮合层会被静默当成市价，等于埋雷。"""
        with pytest.raises(ValidationError, match="限价单必须携带 limit_price"):
            self.make_intent(order_type=OrderType.LIMIT)

    @pytest.mark.parametrize("limit_price", ["0", "-1", "-0.01"])
    def test_限价必须为正(self, limit_price: str) -> None:
        with pytest.raises(ValidationError, match="limit_price 必须为正"):
            self.make_intent(order_type=OrderType.LIMIT, limit_price=d(limit_price))

    @pytest.mark.parametrize("reason_human", ["", "   ", "\t\n"])
    def test_理由不可为空(self, reason_human: str) -> None:
        """★ 每一笔建议都必须告诉用户为什么。"""
        with pytest.raises(ValidationError, match="reason_human 不可为空"):
            self.make_intent(reason_human=reason_human)

    @pytest.mark.parametrize("quantity", [0, -1, -100])
    def test_股数必须为正(self, quantity: int) -> None:
        with pytest.raises(ValidationError):
            self.make_intent(quantity=quantity)

    def test_股数可携带run_id(self) -> None:
        intent = self.make_intent(run_id="daily-scan-20260905T013000-abcdef12")
        assert intent.run_id == "daily-scan-20260905T013000-abcdef12"

    def test_冻结模型不可写(self) -> None:
        intent = self.make_intent()
        with pytest.raises(ValidationError):
            intent.quantity = 200


class TestLiquiditySnapshot:
    def test_常量为五个交易日(self) -> None:
        """一周数据足够反映近期成交水平，又不会让次新股头两天被约束打成 0。"""
        assert MIN_BARS_FOR_RELIABLE_ADV == 5

    def test_样本充足即可信(self) -> None:
        assert make_liquidity(bars_available=MIN_BARS_FOR_RELIABLE_ADV).adv_is_reliable is True

    def test_样本不足即不可信(self) -> None:
        """★ ADV 本身不成立时，不能拿它去卡仓位。"""
        assert make_liquidity(bars_available=MIN_BARS_FOR_RELIABLE_ADV - 1).adv_is_reliable is False

    def test_零根bar不可信(self) -> None:
        assert make_liquidity(bars_available=0).adv_is_reliable is False

    def test_字段保留(self) -> None:
        snapshot = make_liquidity()
        assert snapshot.symbol == "601186.SH"
        assert snapshot.market == "cn_a"
        assert snapshot.adv_amount_20d == d("300000000")
        assert snapshot.adv_volume_20d == d("30000000")
        assert snapshot.bars_available == 20


class TestSizingRequest:
    def test_全部约束显式携带(self) -> None:
        """★ 代码里零常量：风控口径全部来自配置并显式传入。"""
        req = SizingRequest(
            signal=make_signal(),
            equity_total=d("100000"),
            cash_available=d("50000"),
            entry_price=d("10.2"),
            stop_loss_price=d("9.5"),
            risk_per_trade_pct=d("0.008"),
            max_position_pct=d("0.10"),
            max_concurrent_positions=5,
            open_positions=2,
            market_profile=make_market_profile(),
            liquidity=make_liquidity(),
            atr=d("0.35"),
        )
        assert req.equity_total == d("100000")
        assert req.risk_per_trade_pct == d("0.008")
        assert req.max_position_pct == d("0.10")
        assert req.max_concurrent_positions == 5
        assert req.open_positions == 2
        assert req.entry_price == d("10.2")
        assert req.atr == d("0.35")

    def test_atr可缺省(self) -> None:
        req = SizingRequest(
            signal=make_signal(),
            equity_total=d("100000"),
            cash_available=d("50000"),
            entry_price=d("10.2"),
            stop_loss_price=d("9.5"),
            risk_per_trade_pct=d("0.008"),
            max_position_pct=d("0.10"),
            max_concurrent_positions=5,
            open_positions=0,
            market_profile=make_market_profile(),
            liquidity=make_liquidity(),
        )
        assert req.atr is None


class TestSizingResult:
    def make_result(self, **overrides: object) -> SizingResult:
        kwargs: dict[str, object] = {
            "notional": d("5000"),
            "quantity": 400,
            "max_loss_yuan": d("400"),
            "expected_profit_yuan": d("750"),
            "pct_of_equity": d("0.05"),
            "capped_by": "RISK_BUDGET",
            "rationale": "按单笔最多亏 800 元反推可买 1000 股，最终 400 股 ≈ 5000 元",
        }
        kwargs.update(overrides)
        return SizingResult(**kwargs)  # type: ignore[arg-type]

    def test_合法结果通过(self) -> None:
        result = self.make_result()
        assert result.quantity == 400
        assert result.notional == d("5000")
        assert result.pct_of_equity == d("0.05")
        assert result.capped_by == "RISK_BUDGET"

    @pytest.mark.parametrize("quantity", [0, -100])
    @pytest.mark.regression
    def test_股数必须为正(self, quantity: int) -> None:
        """★ ARCH002：股数只能是算出来的正数，绝不可能是 0 或硬编码字面量。"""
        with pytest.raises(ValueError, match="quantity 必须为正"):
            self.make_result(quantity=quantity)

    @pytest.mark.parametrize("notional", ["0", "-1"])
    def test_金额必须为正(self, notional: str) -> None:
        with pytest.raises(ValueError, match="notional 必须为正"):
            self.make_result(notional=d(notional))

    @pytest.mark.parametrize("max_loss_yuan", ["0", "-1"])
    def test_最大亏损必须为正(self, max_loss_yuan: str) -> None:
        """零亏损预期是自欺欺人 —— 那意味着这笔交易没有风险。"""
        with pytest.raises(ValueError, match="max_loss_yuan 必须为正"):
            self.make_result(max_loss_yuan=d(max_loss_yuan))

    @pytest.mark.parametrize("rationale", ["", "   "])
    def test_推导说明不可为空(self, rationale: str) -> None:
        """★ 仓位推导必须向用户说清，否则"这仓位怎么算出来的"永远没有答案。"""
        with pytest.raises(ValueError, match="rationale 不可为空"):
            self.make_result(rationale=rationale)

    @pytest.mark.parametrize(
        "capped_by", ["RISK_BUDGET", "MAX_POSITION", "CASH", "LOT_SIZE", "LIQUIDITY"]
    )
    def test_五种约束来源均合法(self, capped_by: CappedBy) -> None:
        """★ 显式穷举：禁止"其他"，否则说不清到底被哪个约束卡住。"""
        assert self.make_result(capped_by=capped_by).capped_by == capped_by
