"""标的定义 PIT 上市状态。

★ 对应 v1 诊断 #10：v1 没有"当时是否上市 / 是否退市"的概念，
回测时拿"今天在市的池子"当历史池 → 幸存者偏差。

这里锁死的重点是 **"没有退市信息" ≠ "已退市"**：
`list_date` / `delist_date` 为 `None` 是**能力声明**，不是"永不过期"。
真正的拦截在 `UniverseProvider.survivorship_risk` 与 `SurvivorshipBiasError`，
`Instrument.is_listed_on()` 必须不擅自把"缺失"解释成"死掉"。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from quant_v2.domain.models.bar import TRADABLE_INSTRUMENT_TYPES, InstrumentType
from quant_v2.domain.models.instrument import Instrument

pytestmark = pytest.mark.unit

AS_OF = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)

LIST_DATE = date(2026, 1, 1)
DELIST_DATE = date(2026, 12, 31)


def make_instrument(
    *,
    instrument_type: InstrumentType = InstrumentType.EQUITY,
    list_date: date | None = LIST_DATE,
    delist_date: date | None = DELIST_DATE,
    is_st: bool = False,
    lot_size_override: int | None = None,
    industry: str = "建筑装饰",
) -> Instrument:
    """构造一个测试用标的（默认 CNY、cn_a、2026 全年在市）。"""
    return Instrument(
        symbol="601186.SH",
        market="cn_a",
        name="中国铁建",
        instrument_type=instrument_type,
        currency="CNY",
        list_date=list_date,
        delist_date=delist_date,
        is_st=is_st,
        industry=industry,
        lot_size_override=lot_size_override,
        source="test",
        as_of=AS_OF,
    )


class TestTradableType:
    """★ 可交易性是标的的一等属性（v1 把沪深 300 指数当个股跑策略）。"""

    @pytest.mark.parametrize(
        "instrument_type", sorted(TRADABLE_INSTRUMENT_TYPES, key=lambda item: item.value)
    )
    def test_可交易类型返回真(self, instrument_type: InstrumentType) -> None:
        assert make_instrument(instrument_type=instrument_type).tradable_type is True

    @pytest.mark.parametrize("instrument_type", [InstrumentType.INDEX, InstrumentType.FUTURE])
    def test_不可交易类型返回假(self, instrument_type: InstrumentType) -> None:
        assert make_instrument(instrument_type=instrument_type).tradable_type is False


class TestIsListedOn:
    def test_上市日之前未上市(self) -> None:
        inst = make_instrument()
        assert inst.is_listed_on(date(2025, 12, 31)) is False

    def test_上市日当天算已上市(self) -> None:
        """边界：`day == list_date` 应算在市（当天可交易）。"""
        assert make_instrument().is_listed_on(LIST_DATE) is True

    def test_退市日当天仍算在市(self) -> None:
        """边界：`day == delist_date` 还没退（最后一天仍在市）。"""
        assert make_instrument().is_listed_on(DELIST_DATE) is True

    def test_退市日之后已退市(self) -> None:
        assert make_instrument().is_listed_on(date(2027, 1, 1)) is False

    @pytest.mark.regression
    def test_缺失上市退市信息时不拒不上市(self) -> None:
        """★ 缺失是能力声明，不是"已退市"。

        若这里返回 False，那么数据源未提供退市信息的市场（OQ-8 的 NONE 档）
        会被整体判为不可交易 —— 那是把"我不知道"当成了"它死了"。
        """
        inst = make_instrument(list_date=None, delist_date=None)
        assert inst.is_listed_on(date(1990, 1, 1)) is True
        assert inst.is_listed_on(date(2099, 12, 31)) is True

    def test_只有上市日时按上市日单边判定(self) -> None:
        inst = make_instrument(list_date=LIST_DATE, delist_date=None)
        assert inst.is_listed_on(date(2025, 12, 31)) is False
        assert inst.is_listed_on(date(2026, 6, 1)) is True

    def test_只有退市日时按退市日单边判定(self) -> None:
        inst = make_instrument(list_date=None, delist_date=DELIST_DATE)
        assert inst.is_listed_on(date(2026, 6, 1)) is True
        assert inst.is_listed_on(date(2027, 1, 1)) is False


class TestTradableOn:
    def test_可交易类型且在市即True(self) -> None:
        assert make_instrument().tradable_on(date(2026, 6, 1)) is True

    def test_不可交易类型直接False(self) -> None:
        inst = make_instrument(instrument_type=InstrumentType.INDEX)
        assert inst.tradable_on(date(2026, 6, 1)) is False

    def test_在市但类型不可交易仍False(self) -> None:
        """类型与上市状态是"与"关系，任一不满足即不可交易。"""
        inst = make_instrument(instrument_type=InstrumentType.ETF)
        assert inst.tradable_on(date(2027, 6, 1)) is False


class TestHasDelistingInfo:
    def test_有退市日期即为真(self) -> None:
        assert make_instrument(delist_date=DELIST_DATE).has_delisting_info is True

    def test_无退市日期即为假(self) -> None:
        assert make_instrument(delist_date=None).has_delisting_info is False


class TestModelContract:
    def test_字段原样保留(self) -> None:
        inst = make_instrument(is_st=True, lot_size_override=200, industry="")
        assert inst.is_st is True
        assert inst.lot_size_override == 200
        assert inst.industry == ""
        assert inst.source == "test"
        assert inst.as_of == AS_OF

    def test_冻结模型不可写(self) -> None:
        """frozen：标的是事实，不该被下游就地改写。"""
        inst = make_instrument()
        with pytest.raises(Exception, match="frozen"):
            inst.name = "别的名字"  # type: ignore[misc]

    def test_禁止额外字段(self) -> None:
        """extra="forbid"：拼错字段名必须炸，而不是静默多存一个字段。"""
        with pytest.raises(Exception, match="extra"):
            Instrument(
                symbol="601186.SH",
                market="cn_a",
                name="中国铁建",
                currency="CNY",
                source="test",
                as_of=AS_OF,
                namee="typo",
            )
