"""交易成本求值（纯函数）—— 有"对账券商实盘"测试。

★ v1 缺陷：成本模型散落在回测与风控两处，且口径不一致，
导致回测收益与纸盘收益对不上，而没人能说清差在哪。

v2 的做法：公式只此一份（`domain/services/cost_model.py`），
`MarketProfile.cost_model()` 只做委托，回测撮合也调同一个函数。

## A 股口径（configs/markets/cn_a.yaml）

| 项目 | 买入 | 卖出 |
| --- | --- | --- |
| 佣金 | `max(成交额 × 0.025%, 5 元)` | 同 |
| 印花税 | 0 | `成交额 × 0.05%` |
| 过户费 | `成交额 × 0.001%` | 同 |
| 交易所规费 | `成交额 × 0.00487%` | 同 |
| 滑点 | 默认 10 bps | 同 |

★ `commission_min` 的存在是为什么"小额交易成本高得离谱"——
测试里专门有一组 5000 元的小额买入用例，防止后人把这个下限改丢。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from quant_v2.domain.models.order import OrderSide

if TYPE_CHECKING:  # pragma: no cover - 避免与 models.market 的运行时循环导入
    from quant_v2.domain.models.market import CostModel

__all__ = ["ZERO", "CostBreakdown", "commission_of", "compute_cost"]

ZERO: Decimal = Decimal("0")


@dataclass(frozen=True)
class CostBreakdown:
    """成本明细 —— 每一项单列，便于对账与前端展示。

    `total = explicit_total + slippage`。
    之所以分开：滑点是**估计值**（取决于当时的盘口），
    佣金税费是**确定值**（券商账单上查得到）。混在一起就无法对账。
    """

    commission: Decimal
    tax: Decimal
    transfer_fee: Decimal
    exchange_fee: Decimal
    slippage: Decimal

    @property
    def explicit_total(self) -> Decimal:
        """显式成本（佣金 + 税费）—— 对应券商账单上的数字。"""
        return self.commission + self.tax + self.transfer_fee + self.exchange_fee

    @property
    def total(self) -> Decimal:
        """总成本（含滑点）—— 回测撮合用这个。"""
        return self.explicit_total + self.slippage


def commission_of(notional: Decimal, *, rate: Decimal, minimum: Decimal) -> Decimal:
    """佣金 = `max(成交额 × 费率, 最低佣金)`。

    ★ 零成交额返回 0，不是返回最低佣金 —— 没有交易不该收最低佣金。
    """
    if notional <= 0:
        return ZERO
    return max(notional * rate, minimum)


def compute_cost(
    notional: Decimal,
    side: OrderSide,
    cost_model: CostModel,
    *,
    slippage_bps: int | None = None,
) -> CostBreakdown:
    """计算一笔交易的全部成本。

    Args:
        notional: 成交额（本币，正数）。
        side: 买卖方向 —— 决定适用哪个印花税率。
        cost_model: 来自 `MarketProfile.cost`。
        slippage_bps: 覆盖默认滑点（基点）。传 `0` 表示不计滑点（对账用）。

    Returns:
        成本明细。

    Raises:
        ValueError: 成交额为负。
    """
    if notional < 0:
        raise ValueError(f"成交额不能为负，收到 {notional}")

    # ★ 买卖方向的分流只在这里发生一次。
    #   用两个配置文件里的数值（tax_rate_buy / tax_rate_sell）而不是 if 判断市场，
    #   新增"双边征税"市场时只需改 YAML，不动代码。
    tax_rate = cost_model.tax_rate_sell if side is OrderSide.SELL else cost_model.tax_rate_buy

    bps = cost_model.slippage_bps if slippage_bps is None else slippage_bps
    slippage_rate = Decimal(bps) / Decimal(10000)

    return CostBreakdown(
        commission=commission_of(
            notional, rate=cost_model.commission_rate, minimum=cost_model.commission_min
        ),
        tax=notional * tax_rate,
        transfer_fee=notional * cost_model.transfer_fee_rate,
        exchange_fee=notional * cost_model.exchange_fee_rate,
        slippage=notional * slippage_rate,
    )
