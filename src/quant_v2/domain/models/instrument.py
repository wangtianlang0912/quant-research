"""标的定义 —— 可交易性与 PIT（point-in-time）基础信息是一等属性。

★ v1 教训（诊断 #10）：v1 没有 `Instrument` 的"当时是否上市/是否退市"概念，
回测时拿"今天在市的池子"当历史池 → 幸存者偏差。
`list_date` / `delist_date` 因此是**必填语义字段**，缺失要明确表达而不是留空字符串。
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from quant_v2.domain.models.bar import TRADABLE_INSTRUMENT_TYPES, InstrumentType

__all__ = ["Instrument"]


class Instrument(BaseModel):
    """一个可交易（或仅作基准）的标的。

    `list_date` / `delist_date` 为 `None` 表示"数据源未提供"，
    ★ 这是**能力声明**，不是"永不过期"——
    下游若用 `delist_date is None` 推断"还活着"，必须先看
    `MarketProfile.delisting_data_availability`（OQ-8）。
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    symbol: str
    market: str
    name: str
    instrument_type: InstrumentType = InstrumentType.EQUITY
    currency: str

    list_date: date | None = None  # None = 数据源未提供（不是"永不过期"）
    delist_date: date | None = None  # None = 未退市 或 数据源未提供，取决于 delisting 能力档位

    is_st: bool = False  # ST / *ST（中国大陆特有；用数值字段消费，不进 if 分支）
    industry: str = ""  # 行业分类（源未提供时为空串而非 None：便于直接落 SQLite TEXT）
    lot_size_override: int | None = None  # None = 跟随 MarketProfile.lot_size

    source: str  # 数据来源标识（provenance）
    as_of: datetime  # 该元数据的抓取时点（UTC）

    @property
    def tradable_type(self) -> bool:
        """标的类型本身是否可交易（不含时间维度）。"""
        return self.instrument_type in TRADABLE_INSTRUMENT_TYPES

    def is_listed_on(self, day: date) -> bool:
        """在给定日期是否处于上市状态。

        当 `list_date` / `delist_date` 缺失时返回 `True` —— "没有退市信息"
        不代表"已退市"。真正的拦截在 `UniverseProvider.survivorship_risk` 与
        `SurvivorshipBiasError`，而不是在这里猜。
        """
        not_yet_listed = self.list_date is not None and day < self.list_date
        already_delisted = self.delist_date is not None and day > self.delist_date
        return not (not_yet_listed or already_delisted)

    def tradable_on(self, day: date) -> bool:
        """在给定日期是否可交易（类型 + 上市状态）。"""
        return self.tradable_type and self.is_listed_on(day)

    @property
    def has_delisting_info(self) -> bool:
        """是否具备退市信息（用于判断 PIT 池的可信档位）。"""
        return self.delist_date is not None
