"""仓位计算端口（E-01）—— 根除 `quantity = Decimal("100")`。

★ v1 的 `order_pipeline.py:40` 写死了 `quantity = Decimal("100")`，
于是无论单笔预算多少、股价多少，每笔都买 100 股：
股价 3 元的票只买 300 元，股价 300 元的票却买 3 万元 —— 风控形同虚设。

v2 的解法：

1. 股数**只能**来自 `Sizer.size()` 的返回值
2. `SizingResult.quantity` 已按 `MarketProfile.lot_size` 向下取整
3. 代码里出现股数字面量由 `ARCH002` 静态扫描拦截
4. `SizingResult.capped_by` 强制说明"到底是被哪个约束卡住的"，
   `rationale` 强制给出人话推导 —— 这样"这仓位是怎么算出来的"永远有答案
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from quant_v2.domain.models.order import SizingRequest, SizingResult

__all__ = ["Sizer"]


@runtime_checkable
class Sizer(Protocol):
    """仓位计算端口。

    **内置实现**（T03 落地在 `engines/risk/sizers.py`）：

    - `FixedAmountSizer` —— 固定金额
    - `RiskParitySizer` —— 按止损幅度反推，使每笔最大亏损相等（**默认**）
    - `VolTargetSizer` —— 按 ATR 目标波动
    - `KellySizer` —— v1 提供但默认禁用，需在配置显式开启并打风险标

    默认 `RiskParitySizer`：它是 OQ-7「单笔最大亏损 ≤ 0.8%」的直接表达。
    """

    name: str

    def size(self, req: SizingRequest) -> SizingResult:
        """★ 唯一计算股数的入口。

        Args:
            req: 全部约束显式携带（`SizingRequest`），代码里零常量。

        Returns:
            `SizingResult`，含 `capped_by` 与 `rationale`。

        ★ 禁止任何实现使用数字字面量作为股数（ARCH002 静态扫描）。
        """
        ...
