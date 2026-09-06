"""交易成本求值单测 —— A 股口径逐项对账。

★ 为什么测这个（v1 的真实教训）：
成本模型曾散落在回测与风控两处、口径不一致，导致「回测收益」和「纸盘收益」
对不上，而没人能说清差在哪。v2 把公式收敛到 `domain/services/cost_model.py`
唯一一份，本文件就是这份公式的锁 —— 任何一项费率被改动，这里必须同步改。

★ 独立参考实现：
下面的期望值全部按 `cost_model.py` docstring 的 A 股费率表**手算**得出，
不调用被测代码任何函数推导，避免「自洽的往返测试」把公式写反还测不出来
（上一轮复权换算比值方向反了的 P0 就是这么漏掉的）。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from quant_v2.domain.models.market import CostModel
from quant_v2.domain.models.order import OrderSide
from quant_v2.domain.services.cost_model import CostBreakdown, commission_of, compute_cost

pytestmark = pytest.mark.unit

# ============================================================================
# A 股费率表（对照 configs/markets/cn_a.yaml 与 cost_model.py docstring）
# 这里故意**重新写一遍字面量**而不是从 YAML 读：两边独立，才能真正互相校验。
# ============================================================================

A_SHARE = CostModel(
    commission_rate=Decimal("0.00025"),  # 万分之 2.5
    commission_min=Decimal("5"),  # 最低佣金 5 元
    tax_rate_sell=Decimal("0.0005"),  # 卖出印花税 千分之 0.5
    tax_rate_buy=Decimal("0"),  # 买入无印花税
    transfer_fee_rate=Decimal("0.00001"),  # 过户费 十万分之 1
    exchange_fee_rate=Decimal("0.0000487"),  # 交易所规费
    slippage_bps=10,  # 默认滑点 10 bps = 0.10%
)

BIG_NOTIONAL = Decimal("100000")  # 10 万元：佣金按费率算，够不到最低佣金
SMALL_NOTIONAL = Decimal("5000")  # 5000 元：撞上最低佣金 5 元


class TestCommissionOf:
    """`commission_of`：`max(成交额 × 费率, 最低佣金)`。"""

    def test_大额按费率取(self) -> None:
        """100000 × 0.025% = 25 元，大于最低佣金 5 元。"""
        actual = commission_of(
            BIG_NOTIONAL, rate=A_SHARE.commission_rate, minimum=A_SHARE.commission_min
        )
        assert actual == Decimal("25")

    def test_小额触发最低佣金(self) -> None:
        """5000 × 0.025% = 1.25 元 < 5 元 → 取 5 元。

        ★ 这条是全文件最重要的一条：`commission_min` 一旦被改丢，
        小额交易的真实成本会被低估 4 倍，回测会系统性高估收益。
        """
        actual = commission_of(
            SMALL_NOTIONAL, rate=A_SHARE.commission_rate, minimum=A_SHARE.commission_min
        )
        assert actual == Decimal("5")

    def test_零成交额不收最低佣金(self) -> None:
        """★ 没有交易不该收最低佣金：0 元成交 → 0 元佣金，不是 5 元。

        否则「查询一次成本」就会被记上一笔不存在的费用，对账时永远差 5 元。
        """
        actual = commission_of(
            Decimal("0"), rate=A_SHARE.commission_rate, minimum=A_SHARE.commission_min
        )
        assert actual == Decimal("0")

    def test_负数成交额返回零而不是最低佣金(self) -> None:
        """实现是 `notional <= 0 → ZERO`，负号在这里被吞掉。

        ⚠ 这是**当前行为**的锁定测试，不是理想行为：
        负值本应被上游拦住（`compute_cost` 会抛 ValueError）。
        之所以写成断言而不是跳过，是为了让「这里会静默吞掉负数」这件事可见。
        """
        actual = commission_of(
            Decimal("-1"), rate=A_SHARE.commission_rate, minimum=A_SHARE.commission_min
        )
        assert actual == Decimal("0")


class TestBuySide:
    """买入：印花税必须为 0。"""

    def test_各项费用逐项对账(self) -> None:
        """100000 元买入：佣金 25 / 印花税 0 / 过户费 1 / 规费 4.87 / 滑点 100。"""
        cost = compute_cost(BIG_NOTIONAL, OrderSide.BUY, A_SHARE)
        assert cost.commission == Decimal("25")
        assert cost.tax == Decimal("0"), "A 股买入不收印花税"
        assert cost.transfer_fee == Decimal("1")
        assert cost.exchange_fee == Decimal("4.87")
        assert cost.slippage == Decimal("100")

    def test_显式成本为三十点八七元(self) -> None:
        """25 + 0 + 1 + 4.87 = 30.87 —— 这是券商账单上对得上的数字。"""
        cost = compute_cost(BIG_NOTIONAL, OrderSide.BUY, A_SHARE)
        assert cost.explicit_total == Decimal("30.87")

    def test_总成本含滑点为一百三十点八七元(self) -> None:
        """30.87 + 100 = 130.87 —— 回测撮合用这个。"""
        cost = compute_cost(BIG_NOTIONAL, OrderSide.BUY, A_SHARE)
        assert cost.total == Decimal("130.87")


class TestSellSide:
    """卖出：多一项印花税。"""

    def test_各项费用逐项对账(self) -> None:
        """100000 元卖出：佣金 25 / 印花税 50 / 过户费 1 / 规费 4.87 / 滑点 100。"""
        cost = compute_cost(BIG_NOTIONAL, OrderSide.SELL, A_SHARE)
        assert cost.commission == Decimal("25")
        assert cost.tax == Decimal("50"), "100000 × 0.05% = 50 元印花税"
        assert cost.transfer_fee == Decimal("1")
        assert cost.exchange_fee == Decimal("4.87")
        assert cost.slippage == Decimal("100")

    def test_显式成本为八十点八七元(self) -> None:
        cost = compute_cost(BIG_NOTIONAL, OrderSide.SELL, A_SHARE)
        assert cost.explicit_total == Decimal("80.87")

    def test_总成本含滑点为一百八十点八七元(self) -> None:
        cost = compute_cost(BIG_NOTIONAL, OrderSide.SELL, A_SHARE)
        assert cost.total == Decimal("180.87")

    def test_买卖差额恰为印花税(self) -> None:
        """★ 买卖两侧唯一的差异必须只有印花税一项。

        如果这里多出差额，说明「按方向分流」在某些项上重复计税 ——
        那正是 v1 两处成本口径对不上的典型症状。
        """
        buy = compute_cost(BIG_NOTIONAL, OrderSide.BUY, A_SHARE)
        sell = compute_cost(BIG_NOTIONAL, OrderSide.SELL, A_SHARE)
        assert sell.total - buy.total == Decimal("50")
        assert sell.commission == buy.commission
        assert sell.transfer_fee == buy.transfer_fee
        assert sell.exchange_fee == buy.exchange_fee
        assert sell.slippage == buy.slippage


class TestSmallOrder:
    """★ 5000 元小额买入 —— 防止后人把 `commission_min` 改丢的防线。

    删掉这一组用例，就等于放弃这条防线。
    """

    def test_佣金被抬到五元(self) -> None:
        cost = compute_cost(SMALL_NOTIONAL, OrderSide.BUY, A_SHARE)
        assert cost.commission == Decimal("5"), "最低佣金 5 元必须生效"

    def test_各项费用逐项对账(self) -> None:
        """5000 元：佣金 5 / 税 0 / 过户费 0.05 / 规费 0.2435 / 滑点 5。"""
        cost = compute_cost(SMALL_NOTIONAL, OrderSide.BUY, A_SHARE)
        assert cost.transfer_fee == Decimal("0.05")
        assert cost.exchange_fee == Decimal("0.2435")
        assert cost.slippage == Decimal("5")

    def test_实际费率远高于名义佣金率(self) -> None:
        """★ 关键断言：名义 0.025%，实际（佣金+税费）费率 > 0.1%，差 4 倍以上。

        这就是「小额交易成本高得离谱」的量化表达：
        5000 元买入的显式成本 5.2935 元 = 10.59 bps，是名义佣金率的 4.23 倍。
        """
        cost = compute_cost(SMALL_NOTIONAL, OrderSide.BUY, A_SHARE)
        assert cost.explicit_total == Decimal("5.2935")
        effective_rate = cost.explicit_total / SMALL_NOTIONAL
        assert effective_rate > A_SHARE.commission_rate * 4, (
            f"实际费率 {effective_rate} 未显著高于名义佣金率 {A_SHARE.commission_rate}，"
            "最低佣金可能被改丢了"
        )

    def test_去掉最低佣金后费率回落(self) -> None:
        """对照组：把 `commission_min` 设为 0，同一笔交易成本应显著下降。"""
        no_min = CostModel(
            commission_rate=A_SHARE.commission_rate,
            commission_min=Decimal("0"),
            tax_rate_sell=A_SHARE.tax_rate_sell,
            tax_rate_buy=A_SHARE.tax_rate_buy,
            transfer_fee_rate=A_SHARE.transfer_fee_rate,
            exchange_fee_rate=A_SHARE.exchange_fee_rate,
            slippage_bps=A_SHARE.slippage_bps,
        )
        with_min = compute_cost(SMALL_NOTIONAL, OrderSide.BUY, A_SHARE)
        without_min = compute_cost(SMALL_NOTIONAL, OrderSide.BUY, no_min)
        assert without_min.commission == Decimal("1.25")
        assert without_min.explicit_total < with_min.explicit_total


class TestExplicitTotalVsTotal:
    """`explicit_total`（券商账单）与 `total`（回测撮合）的语义差异。"""

    def test_差额恰为滑点(self) -> None:
        cost = compute_cost(BIG_NOTIONAL, OrderSide.SELL, A_SHARE)
        assert cost.total - cost.explicit_total == cost.slippage
        assert cost.slippage == Decimal("100")

    def test_滑点为零时两者相等(self) -> None:
        """对账场景（slippage_bps=0）：账单口径 == 撮合口径。"""
        cost = compute_cost(BIG_NOTIONAL, OrderSide.SELL, A_SHARE, slippage_bps=0)
        assert cost.slippage == Decimal("0")
        assert cost.total == cost.explicit_total == Decimal("80.87")

    def test_explicit_total不含滑点(self) -> None:
        """滑点是**估计值**（取决于当时盘口），不该混进可核对的账单数字。"""
        cost = compute_cost(BIG_NOTIONAL, OrderSide.SELL, A_SHARE)
        assert cost.explicit_total == (
            cost.commission + cost.tax + cost.transfer_fee + cost.exchange_fee
        )

    def test_滑点参数覆盖默认值(self) -> None:
        """20 bps = 0.20%：100000 × 0.002 = 200。"""
        cost = compute_cost(BIG_NOTIONAL, OrderSide.SELL, A_SHARE, slippage_bps=20)
        assert cost.slippage == Decimal("200")


class TestGuards:
    """边界与失败路径。"""

    def test_负成交额抛ValueError(self) -> None:
        with pytest.raises(ValueError, match="成交额不能为负"):
            compute_cost(Decimal("-1"), OrderSide.BUY, A_SHARE)

    def test_零成交额全部为零(self) -> None:
        """零成交额不产生任何费用（尤其是不能产生最低佣金）。"""
        cost = compute_cost(Decimal("0"), OrderSide.SELL, A_SHARE)
        assert cost.explicit_total == Decimal("0")
        assert cost.total == Decimal("0")
        assert cost.commission == Decimal("0")

    def test_费用全程为Decimal禁止float(self) -> None:
        """★ ARCH013：金额计算里不许出现 float，否则精度误差会渗进回测。"""
        cost = compute_cost(BIG_NOTIONAL, OrderSide.BUY, A_SHARE)
        for value in (
            cost.commission,
            cost.tax,
            cost.transfer_fee,
            cost.exchange_fee,
            cost.slippage,
            cost.explicit_total,
            cost.total,
        ):
            assert isinstance(value, Decimal), f"{value!r} 不是 Decimal"

    def test_CostBreakdown冻结(self) -> None:
        """成本明细不可变：任何人都不该在撮合途中改它。"""
        cost = compute_cost(BIG_NOTIONAL, OrderSide.BUY, A_SHARE)
        with pytest.raises(FrozenInstanceError):
            cost.commission = Decimal("0")  # type: ignore[misc]


class TestCostModelDelegation:
    """`MarketProfile.cost` 只做委托，不另写一份公式（v1 缺陷的根治点）。"""

    def test_total_cost等于compute_cost的total(self) -> None:
        assert A_SHARE.total_cost(BIG_NOTIONAL, OrderSide.SELL) == Decimal("180.87")

    def test_explicit_cost等于零滑点下的explicit_total(self) -> None:
        """`explicit_cost()` 必须显式把滑点设为 0，否则对账会差一个滑点。"""
        assert A_SHARE.explicit_cost(BIG_NOTIONAL, OrderSide.SELL) == Decimal("80.87")

    def test_total_cost支持滑点覆盖(self) -> None:
        assert A_SHARE.total_cost(BIG_NOTIONAL, OrderSide.SELL, slippage_bps=0) == Decimal("80.87")

    def test_小额交易委托路径同样走最低佣金(self) -> None:
        """委托路径也必须吃到 `commission_min`：v1 就是两处口径不一致。"""
        assert A_SHARE.explicit_cost(SMALL_NOTIONAL, OrderSide.BUY) == Decimal("5.2935")


def test_成本随成交额线性增长_除佣金下限区间外() -> None:
    """成交额翻倍 → 除佣金外各项翻倍（佣金在下限区间内不成立）。"""
    single = compute_cost(BIG_NOTIONAL, OrderSide.BUY, A_SHARE)
    double = compute_cost(BIG_NOTIONAL * 2, OrderSide.BUY, A_SHARE)
    assert double.transfer_fee == single.transfer_fee * 2
    assert double.exchange_fee == single.exchange_fee * 2
    assert double.slippage == single.slippage * 2
    assert isinstance(single, CostBreakdown)
