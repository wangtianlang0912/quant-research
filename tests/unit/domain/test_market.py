"""市场画像（D-02）—— 市场差异的唯一落点。

★ 抽象纪律三条（ARCH001 强制）：

1. **配置优先于分支**：差异表达为"数值不同"
2. **`None` 优先于特例**：无涨跌停 = `limit_pct: None`
3. **极端特例用类路径注入**：`hooks` 里的 dotted path

这里逐一锁死这些表达，尤其是 **`None` 必须真的是 `None`**
（`limit_prices()` 返回 `None` 而不是 `(+inf, -inf)`，
`TickSpec.tick_for()` 返回 `None` 而不是默认 0.01 —— "不知道"和"0.01"是两件事）。
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from quant_v2.domain.models.market import (
    ONE,
    ZERO,
    CostModel,
    DataCapabilities,
    DataSourceSpec,
    MarketProfile,
    PriceLimitSpec,
    TickSpec,
)
from quant_v2.domain.models.order import OrderSide

pytestmark = pytest.mark.unit


def d(value: str) -> Decimal:
    """构造 Decimal（测试里禁止 float 字面量）。"""
    return Decimal(value)


def make_cost() -> CostModel:
    """A 股口径成本（与 `configs/markets/cn_a.yaml` 对齐）。"""
    return CostModel(
        commission_rate=d("0.00025"),
        commission_min=d("5"),
        tax_rate_sell=d("0.0005"),
        tax_rate_buy=d("0"),
        transfer_fee_rate=d("0.00001"),
        exchange_fee_rate=d("0.0000487"),
        slippage_bps=10,
    )


def make_profile(**overrides: object) -> MarketProfile:
    """构造一个 A 股风格的市场画像；用 `replace` 逐项覆盖以测异常分支。"""
    base = MarketProfile(
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
        cost=make_cost(),
        symbol_pattern=r"^\d{6}\.(SH|SZ)$",
        half_day_dates=(date(2026, 2, 16),),
        extra_holidays=(date(2026, 10, 9),),
        fund_availability="FULL",
        delisting_data_availability="PARTIAL",
        max_symbols=5000,
        data_sources=(
            DataSourceSpec(
                source_id="akshare",
                adapter="quant_v2.adapters.market_data.akshare_cn.AkshareCnAdapter",
                priority=0,
                capabilities=DataCapabilities(delisting_history="PARTIAL"),
            ),
            DataSourceSpec(
                source_id="baostock",
                adapter="quant_v2.adapters.market_data.baostock_cn.BaostockCnAdapter",
                priority=1,
            ),
        ),
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


class TestCostModel:
    """成本公式只有一份（`domain/services/cost_model.py`），这里只验委托与口径分流。"""

    def test_买入含滑点总成本(self) -> None:
        """5000 元买入：佣金被最低 5 元兜住，买入无印花税。"""
        cost = make_cost()
        # 佣金 max(5000×0.00025=1.25, 5)=5；过户费 0.05；规费 0.2435；滑点 5
        assert cost.total_cost(d("5000"), OrderSide.BUY) == d("10.2935")

    def test_卖出多一笔印花税(self) -> None:
        """★ 买卖分流只靠两个配置数值，不靠 `if market == 'cn_a'`。"""
        cost = make_cost()
        # 印花税 5000×0.0005 = 2.5
        assert cost.total_cost(d("5000"), OrderSide.SELL) == d("12.7935")

    def test_显式成本不含滑点(self) -> None:
        """显式成本用于对账券商账单，滑点是估计值必须排除。"""
        cost = make_cost()
        assert cost.explicit_cost(d("5000"), OrderSide.BUY) == d("5.2935")
        assert cost.explicit_cost(d("5000"), OrderSide.SELL) == d("7.7935")

    def test_可覆盖默认滑点(self) -> None:
        cost = make_cost()
        assert cost.total_cost(d("5000"), OrderSide.BUY, slippage_bps=0) == d("5.2935")
        assert cost.total_cost(d("5000"), OrderSide.BUY, slippage_bps=20) == d("15.2935")

    def test_大额交易佣金按费率而非下限(self) -> None:
        cost = make_cost()
        # 佣金 100000×0.00025 = 25；过户费 1；规费 4.87
        assert cost.explicit_cost(d("100000"), OrderSide.BUY) == d("30.87")


class TestPriceLimitSpec:
    def test_普通股取普通涨跌幅(self) -> None:
        spec = PriceLimitSpec(limit_pct=d("0.1"), st_limit_pct=d("0.05"))
        assert spec.pct_for(is_st=False) == d("0.1")

    def test_ST股取ST涨跌幅(self) -> None:
        spec = PriceLimitSpec(limit_pct=d("0.1"), st_limit_pct=d("0.05"))
        assert spec.pct_for(is_st=True) == d("0.05")

    def test_ST股但未配置ST档位时回落到普通档(self) -> None:
        """★ 用数值回落而不是写 `if is_st else` 分支。"""
        spec = PriceLimitSpec(limit_pct=d("0.1"), st_limit_pct=None)
        assert spec.pct_for(is_st=True) == d("0.1")

    def test_无涨跌停市场返回None(self) -> None:
        """★ `None` 优先于特例：美股/港股没有涨跌停就是 `None`。"""
        assert PriceLimitSpec().pct_for(is_st=False) is None
        assert PriceLimitSpec().pct_for(is_st=True) is None

    def test_次新股无涨跌幅天数默认零(self) -> None:
        assert PriceLimitSpec().new_listing_free_days == 0
        assert PriceLimitSpec().ipo_first_day_pct is None


class TestTickSpec:
    def test_固定tick(self) -> None:
        assert TickSpec(tick_size=d("0.01")).tick_for(d("10")) == d("0.01")

    def test_分段tick按价格上界取档(self) -> None:
        """港股式分段表：无需任何市场特例代码，一张表即可。"""
        spec = TickSpec(tick_table=((d("10"), d("0.01")), (d("100"), d("0.05"))))
        assert spec.tick_for(d("5")) == d("0.01")
        assert spec.tick_for(d("50")) == d("0.05")

    def test_价格超过全部分段上界取最后一档(self) -> None:
        spec = TickSpec(tick_table=((d("10"), d("0.01")), (d("100"), d("0.05"))))
        assert spec.tick_for(d("500")) == d("0.05")

    def test_无tick约束时返回None(self) -> None:
        """★ 返回 None 而不是默认 0.01：混在一起会让价格精度问题静默消失。"""
        assert TickSpec().tick_for(d("10")) is None

    def test_取整到最近的tick(self) -> None:
        spec = TickSpec(tick_size=d("0.01"))
        assert spec.round_price(d("10.004")) == d("10")
        assert spec.round_price(d("10.005")) == d("10.01")
        assert spec.round_price(d("10.006")) == d("10.01")

    def test_无tick约束时原样返回(self) -> None:
        """这不是兜底，而是该市场本就允许任意精度报价。"""
        assert TickSpec().round_price(d("10.123456")) == d("10.123456")

    def test_分段tick下的取整(self) -> None:
        spec = TickSpec(tick_table=((d("10"), d("0.01")), (d("100"), d("0.05"))))
        assert spec.round_price(d("50.03")) == d("50.05")


class TestDataCapabilities:
    def test_默认值即最低能力档(self) -> None:
        caps = DataCapabilities()
        assert caps.daily_bars is True
        assert caps.adj_factor is True
        assert caps.delisting_history == "NONE"
        assert caps.delisting_list is False
        assert caps.trading_calendar is True
        assert caps.fundamentals is False
        assert caps.intraday is False
        assert caps.rate_limit_per_min is None

    @pytest.mark.regression
    def test_退市历史默认NONE(self) -> None:
        """★ OQ-8：默认"拿不到退市历史"，谁声称能给谁必须显式改。

        v1 的教训是所有适配器都假装自己什么都能给，于是"退市股数据拿不到"
        在数据层被吞掉，到回测层变成一个偏乐观的结论。
        """
        assert DataCapabilities().delisting_history == "NONE"


class TestDataSourceSpec:
    def test_字段保留(self) -> None:
        spec = DataSourceSpec(source_id="akshare", adapter="a.b.C", priority=0)
        assert spec.source_id == "akshare"
        assert spec.adapter == "a.b.C"
        assert spec.priority == 0


class TestMarketProfileValidation:
    """★ 早失败：写错的正则留到运行时才炸，排查成本极高。"""

    def test_合法正则通过(self) -> None:
        assert make_profile().market_code == "cn_a"

    def test_非法正则在构造期即失败(self) -> None:
        with pytest.raises(re.error):
            make_profile(symbol_pattern="[")

    @pytest.mark.parametrize("lot_size", [0, -100])
    def test_lot_size必须为正(self, lot_size: int) -> None:
        with pytest.raises(ValueError, match="lot_size 必须为正"):
            make_profile(lot_size=lot_size)

    def test_t_plus不可为负(self) -> None:
        with pytest.raises(ValueError, match="t_plus 不能为负"):
            make_profile(t_plus=-1)

    def test_t_plus为零合法(self) -> None:
        """美股 T+0 是合法配置，不能一刀切要求为正。"""
        assert make_profile(t_plus=0).t_plus == 0

    @pytest.mark.parametrize("max_symbols", [0, -1])
    def test_max_symbols必须为正(self, max_symbols: int) -> None:
        with pytest.raises(ValueError, match="max_symbols 必须为正"):
            make_profile(max_symbols=max_symbols)

    def test_滑点不可为负(self) -> None:
        negative = CostModel(
            commission_rate=d("0.00025"),
            commission_min=d("5"),
            tax_rate_sell=d("0.0005"),
            tax_rate_buy=d("0"),
            transfer_fee_rate=d("0.00001"),
            exchange_fee_rate=d("0.0000487"),
            slippage_bps=-1,
        )
        with pytest.raises(ValueError, match="slippage_bps 不能为负"):
            make_profile(cost=negative)


class TestRoundLot:
    @pytest.mark.parametrize(
        ("quantity", "expected"), [(250, 200), (100, 100), (99, 0), (0, 0), (199, 100)]
    )
    def test_向下取整到手数(self, quantity: int, expected: int) -> None:
        """★ 向下而不是四舍五入：多买一手就可能突破单笔仓位上限。"""
        assert make_profile(lot_size=100).round_lot(quantity) == expected

    def test_零股市场手数为一(self) -> None:
        assert make_profile(lot_size=1).round_lot(37) == 37


class TestSymbolMatching:
    def test_合规代码匹配(self) -> None:
        profile = make_profile()
        assert profile.matches_symbol("601186.SH") is True
        assert profile.matches_symbol("000001.SZ") is True

    def test_不合规代码不匹配(self) -> None:
        profile = make_profile()
        assert profile.matches_symbol("AAPL") is False
        assert profile.matches_symbol("601186.BJ") is False


class TestCalendarRelated:
    def test_半天市(self) -> None:
        profile = make_profile()
        assert profile.is_half_day(date(2026, 2, 16)) is True
        assert profile.is_half_day(date(2026, 2, 17)) is False

    def test_临时休市(self) -> None:
        profile = make_profile()
        assert profile.is_extra_holiday(date(2026, 10, 9)) is True
        assert profile.is_extra_holiday(date(2026, 10, 10)) is False


class TestLimitPrices:
    def test_普通股涨跌停(self) -> None:
        profile = make_profile()
        assert profile.limit_prices(d("10"), is_st=False, listing_days=100) == (d("11"), d("9"))

    def test_ST股涨跌停更窄(self) -> None:
        profile = make_profile()
        assert profile.limit_prices(d("10"), is_st=True, listing_days=100) == (
            d("10.5"),
            d("9.5"),
        )

    def test_涨跌停按tick取整(self) -> None:
        """前收盘 10.03 × 1.1 = 11.033 → 取整到 11.03。"""
        profile = make_profile()
        limit_up, limit_down = profile.limit_prices(d("10.03"), is_st=False, listing_days=100) or (
            d("0"),
            d("0"),
        )
        assert limit_up == d("11.03")
        assert limit_down == d("9.03")

    def test_次新股无涨跌幅(self) -> None:
        """创业板/科创板上市前 5 日无涨跌幅 —— 用数值表达，不写市场分支。"""
        profile = make_profile(
            price_limit=PriceLimitSpec(
                limit_pct=d("0.2"),
                st_limit_pct=d("0.05"),
                new_listing_free_days=5,
            )
        )
        assert profile.limit_prices(d("10"), is_st=False, listing_days=5) is None
        assert profile.limit_prices(d("10"), is_st=False, listing_days=6) is not None

    @pytest.mark.regression
    def test_无涨跌停市场返回None而不是无穷大(self) -> None:
        """★ 返回 None 强迫调用方显式处理"无约束"；无穷大会静默通过所有比较。"""
        profile = make_profile(
            price_limit=PriceLimitSpec(),
            tick=TickSpec(tick_size=d("0.01")),
        )
        assert profile.limit_prices(d("10"), is_st=False, listing_days=100) is None

    def test_无tick约束时按原精度返回(self) -> None:
        profile = make_profile(tick=TickSpec())
        limit_up, _ = profile.limit_prices(d("10"), is_st=False, listing_days=100) or (
            d("0"),
            d("0"),
        )
        assert limit_up == d("11.0")


class TestPrimarySource:
    def test_取优先级数值最小者(self) -> None:
        assert make_profile().primary_source().source_id == "akshare"

    def test_乱序配置仍取最小优先级(self) -> None:
        profile = make_profile(
            data_sources=(
                DataSourceSpec(source_id="slow", adapter="a.b.C", priority=7),
                DataSourceSpec(source_id="fast", adapter="a.b.D", priority=2),
            )
        )
        assert profile.primary_source().source_id == "fast"

    @pytest.mark.regression
    def test_无数据源时抛异常而不是返回None(self) -> None:
        """★ 没有数据源的市场无法取数，"让它跑起来再说"只会推迟故障。"""
        profile = make_profile(data_sources=())
        with pytest.raises(ValueError, match="未配置任何 data_sources"):
            profile.primary_source()


class TestMisc:
    def test_cost_model返回同一实例(self) -> None:
        profile = make_profile()
        assert profile.cost_model() is profile.cost

    def test_常量口径(self) -> None:
        assert d("0") == ZERO
        assert d("1") == ONE

    def test_hooks默认空(self) -> None:
        assert make_profile().hooks == {}

    def test_可得性档位原样保留(self) -> None:
        profile = make_profile()
        assert profile.fund_availability == "FULL"
        assert profile.delisting_data_availability == "PARTIAL"
        assert profile.settlement_currency is None
