"""当前在市名单提供者（Tier C，附录 B 三级降级的最后一档）。

## 为什么它存在

数据源完全拿不到退市股历史（`delisting_data_availability=NONE`）时，
池子只能 = "构建日在市的标的"。用它回测历史 = 幸存者偏差，
**结果系统性偏乐观且看不出来** —— 所以引擎侧是硬拦截
（`SurvivorshipBiasError`），不是警告（附录 B / OQ-8）。

A 股（baostock 有退市股历史）不落到这一档，本类保留给
其他市场 / 源能力降级场景。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from quant_v2.domain.errors import SurvivorshipBiasError
from quant_v2.domain.ports.pipeline_port import (
    SurvivorshipRisk,
    SymbolSnapshot,
)

__all__ = ["CurrentListProvider"]

# 取"当前在市名单"的函数：market → 名单（as_of 对它没有意义，这就是 Tier C）
CurrentListFetcher = Callable[[str], Sequence[SymbolSnapshot]]


@dataclass(frozen=True)
class CurrentListProvider:
    """池子 = '构建日'在市的标的。★ 构造时强制记录 pool_build_date。

    `symbols(as_of < pool_build_date)` → `SurvivorshipBiasError`
    （错误信息直接给出修复指引，不是甩一句"不行"）。
    """

    pool_build_date: date
    fetch_current: CurrentListFetcher
    market: str = "cn_a"
    survivorship_risk: SurvivorshipRisk = SurvivorshipRisk.HIGH

    def symbols(self, *, as_of: date, market: str) -> Sequence[SymbolSnapshot]:
        """仅 `as_of >= pool_build_date` 可用（forward-only，附录 B）。"""
        if market != self.market:
            raise ValueError(f"未知市场 {market!r}（本 provider 只服务 {self.market}）")
        if as_of < self.pool_build_date:
            raise SurvivorshipBiasError(
                f"请求 as_of={as_of} 早于池构建日 {self.pool_build_date}。"
                f"当前数据源无法提供退市股历史数据（delisting_data_availability=NONE），"
                f"用'构建日在市'的池子回测历史会产生幸存者偏差，结果不可信。"
                f"请改用 as_of >= {self.pool_build_date} 的前向池，"
                f"或升级数据源能力。"
            )
        return self.fetch_current(market)
