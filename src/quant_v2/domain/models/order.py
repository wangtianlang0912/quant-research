"""订单、买卖方向与仓位计算契约（E-01 / E-04）。

★ 这个文件承载 v1 三个执行层 P0 的根治：

1. `order_pipeline.py:40` 的 `quantity = Decimal("100")` —— 每笔都买 100 股。
   v2 的解法：股数**只能**来自 `Sizer.size()` 返回的 `SizingResult.quantity`，
   构造 `OrderIntent` 时传入。代码里出现股数字面量由 `ARCH002` 静态扫描拦。
2. `basic_risk_manager.py:112-116` 用 `Decimal("100")` 兜底估值 —— 由 `PriceUnavailableError` 根治。
3. 限价单没有 `limit_price` —— `OrderIntent` 构造即失败（E-04）。

**v1 完全不做实盘下单**（OQ-4）：`OrderIntent` 只是"建议订单"，永不发送。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:  # pragma: no cover - 避免 models.order <-> models.market 运行时循环导入
    from quant_v2.domain.models.market import MarketProfile
    from quant_v2.domain.models.signal import RawSignal

__all__ = [
    "LiquiditySnapshot",
    "OrderIntent",
    "OrderSide",
    "OrderType",
    "SizingRequest",
    "SizingResult",
]

# SizingResult.capped_by 的全部取值 —— 显式穷举，禁止"其他"
CappedBy = Literal["RISK_BUDGET", "MAX_POSITION", "CASH", "LOT_SIZE", "LIQUIDITY"]

# 日均成交额（ADV）用于"单票不超过其 ADV 的 X%"这类流动性约束，
# 但样本太短时 ADV 本身就不成立。取 5 个交易日作最低门槛：
# 一周数据足够反映近期成交水平，又不会让次新股上市头两天被约束直接打成 0。
MIN_BARS_FOR_RELIABLE_ADV: int = 5


class OrderSide(str, Enum):
    """买卖方向。

    ★ 风控按 `side` 分流是 v1 的 P0 修复点：
    卖出**永不**因现金或仓位约束被拒（v1 反例：现金 1 万 + 持仓 99 万时卖 1000 股被 reject，
    超仓后永久无法减仓）。
    """

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """订单类型。"""

    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderIntent(BaseModel):
    """建议订单（**永不真正发送**，OQ-4）。

    `quantity` 必须来自 `Sizer.size()`。模型不做"是不是 100 的倍数"这类校验 ——
    那是 `MarketProfile.round_lot()` 的职责，留给 Sizer 调用。
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    signal_id: str
    symbol: str
    market: str
    side: OrderSide
    order_type: OrderType
    quantity: int = Field(gt=0)
    limit_price: Decimal | None = None
    notional: Decimal | None = None  # 预估名义金额（元）
    reason_human: str  # 人话，直接进前端与推送
    created_at: datetime
    run_id: str | None = None

    @model_validator(mode="after")
    def _validate_limit_price(self) -> OrderIntent:
        """★ E-04：限价单必须有 `limit_price`，否则构造即失败。"""
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError(
                f"限价单必须携带 limit_price（symbol={self.symbol}, side={self.side.value}）："
                "没有限价的限价单在撮合层会被静默当成市价，等于埋雷"
            )
        if self.limit_price is not None and self.limit_price <= 0:
            raise ValueError(f"limit_price 必须为正，收到 {self.limit_price}")
        if not self.reason_human.strip():
            raise ValueError("reason_human 不可为空：每一笔建议都必须告诉用户为什么")
        return self


@dataclass(frozen=True)
class LiquiditySnapshot:
    """流动性快照 —— Sizer 的流动性上限依据。

    ★ 没有流动性约束的仓位计算会给出"买下这只票 30% 的成交量"这种荒谬建议。
    """

    symbol: str
    market: str
    as_of: date
    adv_amount_20d: Decimal  # 近 20 日日均成交额（本币）
    adv_volume_20d: Decimal  # 近 20 日日均成交量（股）
    bars_available: int  # 实际可得 bar 数（用于判断 adv 是否可信）

    @property
    def adv_is_reliable(self) -> bool:
        """日均成交额是否可信（样本不足时不参与流动性上限计算）。"""
        return self.bars_available >= MIN_BARS_FOR_RELIABLE_ADV


@dataclass(frozen=True)
class SizingRequest:
    """★ `Sizer.size()` 的唯一入参 —— 所有约束显式携带，代码里零常量。

    `risk_per_trade_pct` / `max_position_pct` / `max_concurrent_positions` 来自 `configs/risk.yaml`
    （OQ-7：单笔 ≤ 总资金 10%、单笔最大亏损 ≤ 0.8%、同时持仓 ≤ 5）。
    """

    signal: RawSignal
    equity_total: Decimal  # 总资金（计价币种）
    cash_available: Decimal
    entry_price: Decimal  # ★ 必须来自真实最近价；缺失时上层已抛 PriceUnavailableError
    stop_loss_price: Decimal
    risk_per_trade_pct: Decimal  # 单笔最大亏损比例（0.008 = 0.8%）
    max_position_pct: Decimal  # 单笔仓位上限（0.10 = 10%）
    max_concurrent_positions: int  # ≤ 5
    open_positions: int
    market_profile: MarketProfile  # lot_size / tick
    liquidity: LiquiditySnapshot
    atr: Decimal | None = None  # 波动率目标 / 风险平价用


@dataclass(frozen=True)
class SizingResult:
    """`Sizer.size()` 的返回值。

    `rationale` 是给人看的完整推导，例如：

        按单笔最多亏 800 元反推可买 1000 股（约 8300 元），
        但受单笔上限 10%（10000 元）与 5 只持仓上限约束，最终 1000 股 ≈ 8300 元
    """

    notional: Decimal  # 建议投入金额（元）—— 前端"投入约 ¥5,000"
    quantity: int  # 股数，已按 lot_size 向下取整
    max_loss_yuan: Decimal  # "最多亏 400 元"
    expected_profit_yuan: Decimal  # "目标赚 750 元"
    pct_of_equity: Decimal
    capped_by: CappedBy
    rationale: str

    def __post_init__(self) -> None:
        """结果自洽性校验：金额、股数、占比都不能自相矛盾。"""
        if self.quantity <= 0:
            raise ValueError(f"SizingResult.quantity 必须为正，收到 {self.quantity}")
        if self.notional <= 0:
            raise ValueError(f"SizingResult.notional 必须为正，收到 {self.notional}")
        if self.max_loss_yuan <= 0:
            raise ValueError("SizingResult.max_loss_yuan 必须为正：零亏损预期是自欺欺人")
        if not self.rationale.strip():
            raise ValueError("SizingResult.rationale 不可为空：仓位推导必须向用户说清")
