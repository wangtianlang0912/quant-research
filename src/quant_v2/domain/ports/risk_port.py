"""风控与估值端口（E-02 / E-03 / E-04）。

★ 这个文件承载 v1 三个执行层 P0 的根治契约。

## 三条铁律（写进 docstring，由守卫测试断言）

1. **`side == BUY`**：受现金 / 单笔仓位上限 / 同时持仓数 / 涨停 / 停牌 约束。
2. **`side == SELL`**：★ **永不**因现金或仓位约束被拒。
   仅校验：持仓数量充足、跌停不可卖、停牌不可卖、KillSwitch。

   v1 反例：现金 1 万 + 持仓 99 万时卖 1000 股被 reject ——
   **超仓后永久无法减仓**，这是能亏光的那类 bug。
3. **估值一律走 `ValuationProvider.last_price()`**；
   ★ 取不到即抛 `PriceUnavailableError`，**禁止任何默认值兜底**
   （v1 反例：`basic_risk_manager.py:112-116` 用 `Decimal("100")` 兜底）。
4. 限价单必须有 `limit_price`，否则 `OrderIntent` 构造即失败（E-04）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Protocol, runtime_checkable

from quant_v2.domain.models.market import MarketProfile
from quant_v2.domain.models.order import OrderIntent
from quant_v2.domain.models.portfolio import PortfolioSnapshot, Position

__all__ = ["RiskCode", "RiskDecision", "RiskManager", "ValuationProvider"]


class RiskCode(str, Enum):
    """风控判定码。

    ★ 显式穷举，**禁止 OTHER 兜底** —— 一个"其他"码会让所有未建模的
    拒绝原因沉进黑洞，用户只会看到"被拒绝了"而不知道为什么。
    """

    OK = "OK"
    EXCEED_MAX_POSITION = "EXCEED_MAX_POSITION"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    EXCEED_MAX_CONCURRENT = "EXCEED_MAX_CONCURRENT"
    EXCEED_DAILY_LOSS = "EXCEED_DAILY_LOSS"
    LIMIT_UP_NO_BUY = "LIMIT_UP_NO_BUY"  # 涨停无法买入（D-09）
    LIMIT_DOWN_NO_SELL = "LIMIT_DOWN_NO_SELL"  # 跌停无法卖出（D-09）
    SUSPENDED = "SUSPENDED"
    INSUFFICIENT_HOLDING = "INSUFFICIENT_HOLDING"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"


@dataclass(frozen=True)
class RiskDecision:
    """风控判定结果。"""

    allowed: bool
    intent: OrderIntent | None  # 可能被削减数量（partial fill 场景）
    code: RiskCode
    reason_human: str  # 人话，直接进前端与推送
    checked_constraints: tuple[str, ...]  # 审计：本次实际走了哪些约束

    def __post_init__(self) -> None:
        """判定结果自洽性校验。

        ★ `allowed == False` 时 `reason_human` 必须非空：
        用户被拒绝了却不知道为什么，会直接放弃使用这个系统。
        """
        if not self.allowed and not self.reason_human.strip():
            raise ValueError("拒绝时必须给出 reason_human：用户有权知道为什么被拒绝")
        if self.allowed and self.code is not RiskCode.OK:
            raise ValueError(
                f"允许通过时 code 必须是 OK，收到 {self.code.value}：自相矛盾的判定会让下游无所适从"
            )


@runtime_checkable
class ValuationProvider(Protocol):
    """估值端口。

    ★ 这是 v1 最严重 P0 的根治点：`basic_risk_manager.py:112-116`
    取不到价格时用 `Decimal("100")` 兜底，导致风控永远按 100 元估值。
    """

    def last_price(self, symbol: str, market: str, *, as_of: date) -> Decimal:
        """★ 取不到真实最近价 → **raise `PriceUnavailableError`**。

        禁止实现返回 0 / 100 / prev_close 作为兜底
        （`ARCH003` 静态扫描 + `tests/architecture/test_no_price_fallback.py` 双重强制）。
        """
        ...

    def mark_to_market(self, positions: Sequence[Position], *, as_of: date) -> Decimal:
        """组合市值。

        ★ 任一标的取价失败即**整体抛出**，不允许跳过或填默认值 ——
        跳过一个取不到价的标的，等于假设它的市值为 0，那是最坏的一种兜底。
        """
        ...


@runtime_checkable
class RiskManager(Protocol):
    """风控端口。三条铁律见本模块 docstring。"""

    def evaluate(
        self,
        intent: OrderIntent,
        portfolio: PortfolioSnapshot,
        profile: MarketProfile,
    ) -> RiskDecision:
        """评估一笔建议订单是否可执行。

        Args:
            intent: 建议订单。
            portfolio: 组合快照（一致快照，不可变）。
            profile: 市场画像（涨跌停 / 停牌 / lot_size 等规则来源）。

        Returns:
            `RiskDecision`。
        """
        ...
