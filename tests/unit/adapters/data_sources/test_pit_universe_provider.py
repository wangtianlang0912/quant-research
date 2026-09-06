"""PIT 池 provider 测试（T02.5 / D-05）。

验收用例直接引用架构文档 §9.4 T02.5 的实测样本行。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from quant_v2.adapters.data_sources.current_list_provider import CurrentListProvider
from quant_v2.adapters.data_sources.pit_universe_provider import (
    BaostockPitUniverseProvider,
    default_all_stock_fetcher,
)
from quant_v2.adapters.market_data.subprocess_worker import WorkerResult
from quant_v2.adapters.persistence.repositories import (
    PitRow,
    SqlitePitUniverseRepository,
)
from quant_v2.adapters.persistence.sqlite_store import SqliteStore
from quant_v2.domain.errors import (
    DataQualityGateError,
    NotTradingDayError,
    SourceUnavailableError,
    SurvivorshipBiasError,
)
from quant_v2.domain.ports.pipeline_port import SurvivorshipRisk, SymbolSnapshot

pytestmark = pytest.mark.unit

# 2007-12-28（周五，交易日）：实测当日快照必含这四只"当时在市、今已退市"
_2007_ROWS: list[dict[str, Any]] = [
    {"code": "sh.600485", "tradeStatus": "1", "code_name": "中昌数据"},
    {"code": "sh.600087", "tradeStatus": "1", "code_name": "南京水运"},
    {"code": "sz.000033", "tradeStatus": "1", "code_name": "新都酒店"},
    {"code": "sh.600069", "tradeStatus": "1", "code_name": "银鸽投资"},
    {"code": "sh.600000", "tradeStatus": "1", "code_name": "浦发银行"},
    {"code": "sz.000001", "tradeStatus": "1", "code_name": "平安银行"},
    # M-20：快照含指数，必须被过滤（上证综指 / 深证成指族）
    {"code": "sh.000001", "tradeStatus": "1", "code_name": "上证综指"},
    {"code": "sz.399001", "tradeStatus": "1", "code_name": "深证成指"},
]


class FakeFetcher:
    """按日期返回预设行；可注入异常、记录调用。"""

    def __init__(
        self,
        rows_by_day: dict[date, list[dict[str, Any]]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._rows = rows_by_day or {}
        self._error = error
        self.calls: list[date] = []

    def __call__(self, day: date) -> list[dict[str, Any]]:
        self.calls.append(day)
        if self._error is not None:
            raise self._error
        return list(self._rows.get(day, []))


class FakeCalendar:
    """最小交易日历：只实现 provider 用到的 `is_trading_day`。"""

    def __init__(self, days: list[date]) -> None:
        self._days = frozenset(days)

    def is_trading_day(self, market: str, day: date) -> bool:
        assert market == "cn_a"
        return day in self._days


def _make(
    tmp_path: Path,
    fetcher: FakeFetcher,
    *,
    trading_days: list[date] | None = None,
) -> tuple[BaostockPitUniverseProvider, SqlitePitUniverseRepository, SqliteStore]:
    store = SqliteStore(tmp_path / "q.db")
    repo = SqlitePitUniverseRepository(store)
    calendar = FakeCalendar(trading_days or [date(2007, 12, 28)])
    provider = BaostockPitUniverseProvider(repo=repo, calendar=calendar, fetcher=fetcher)
    return provider, repo, store


# ============================================================
# D-05 验收：实测样本
# ============================================================
def test_2007快照_必含当时在市的退市股(tmp_path: Path) -> None:
    """as_of=2007-12-28 必含 600485/600087/000033/600069（D-05 实测基准）。"""
    fetcher = FakeFetcher({date(2007, 12, 28): _2007_ROWS})
    provider, _, store = _make(tmp_path, fetcher)
    try:
        snapshots = provider.symbols(as_of=date(2007, 12, 28), market="cn_a")
        symbols = {s.symbol for s in snapshots}
        assert {"600485.SH", "600087.SH", "000033.SZ", "600069.SH"} <= symbols
        # 池子里不得含指数（M-20）
        assert "000001.SH" not in symbols  # 上证综指（归一化后与平安银行区分）
        assert "399001.SZ" not in symbols
        # sz.000001 是平安银行（个股），不能被 sh.00 过滤规则误伤
        assert "000001.SZ" in symbols
    finally:
        store.close()


def test_2021快照_退市股不在池(tmp_path: Path) -> None:
    """as_of=2021-06-02（600485 退市后）必不含 600485（D-05 实测基准）。"""
    day = date(2021, 6, 2)
    rows = [
        {"code": "sh.600000", "tradeStatus": "1", "code_name": "浦发银行"},
        {"code": "sz.000001", "tradeStatus": "1", "code_name": "平安银行"},
    ]
    fetcher = FakeFetcher({day: rows})
    provider, _, store = _make(tmp_path, fetcher, trading_days=[day])
    try:
        snapshots = provider.symbols(as_of=day, market="cn_a")
        assert {s.symbol for s in snapshots} == {"600000.SH", "000001.SZ"}
    finally:
        store.close()


def test_非交易日_抛错不查源(tmp_path: Path) -> None:
    """as_of=1991-06-01（周六）→ NotTradingDayError，不得返回空池子（M-19）。"""
    day = date(1991, 6, 1)  # 周六
    fetcher = FakeFetcher({day: []})
    provider, _, store = _make(tmp_path, fetcher, trading_days=[date(1991, 5, 31)])
    try:
        with pytest.raises(NotTradingDayError, match=r"不是.*交易日"):
            provider.symbols(as_of=day, market="cn_a")
        assert fetcher.calls == []  # ★ 前置校验拦住，根本没查源
    finally:
        store.close()


def test_早于开市日_抛错(tmp_path: Path) -> None:
    """as_of < 1990-12-19 → 抛错（M-15：上交所开市首日之前无快照）。"""
    day = date(1990, 1, 1)
    fetcher = FakeFetcher({day: []})
    provider, _, store = _make(tmp_path, fetcher, trading_days=[day])
    try:
        with pytest.raises(NotTradingDayError, match="1990-12-19"):
            provider.symbols(as_of=day, market="cn_a")
    finally:
        store.close()


def test_交易日零行_P0门禁拒绝写入(tmp_path: Path) -> None:
    """交易日 + 0 rows → DataQualityGateError，不落库（M-19 静默失败陷阱）。"""
    day = date(2005, 1, 4)
    fetcher = FakeFetcher({day: []})
    provider, repo, store = _make(tmp_path, fetcher, trading_days=[day])
    try:
        with pytest.raises(DataQualityGateError, match="0 行"):
            provider.symbols(as_of=day, market="cn_a")
        assert repo.snapshot_dates() == []  # ★ 拒绝写入
    finally:
        store.close()


# ============================================================
# M-20 字段处理
# ============================================================
def test_ST解析与停牌标记(tmp_path: Path) -> None:
    """is_st 从名称解析（is_st_source=NAME_PARSE）；tradeStatus 落停牌。"""
    day = date(2005, 1, 4)
    rows = [
        {"code": "sh.600000", "tradeStatus": "1", "code_name": "浦发银行"},
        {"code": "sz.000033", "tradeStatus": "0", "code_name": "S*ST新都"},  # 停牌 + ST
    ]
    fetcher = FakeFetcher({day: rows})
    provider, repo, store = _make(tmp_path, fetcher, trading_days=[day])
    try:
        snapshots = provider.symbols(as_of=day, market="cn_a")
        by_symbol = {s.symbol: s for s in snapshots}
        assert by_symbol["000033.SZ"].is_st is True
        assert by_symbol["600000.SH"].is_st is False
        saved = repo.load_snapshot(day)
        saved_map = {r.symbol: r for r in saved}
        assert saved_map["000033.SZ"].trade_status == "SUSPENDED"
        assert saved_map["600000.SH"].trade_status == "TRADING"
        assert all(r.is_st_source == "NAME_PARSE" for r in saved)
    finally:
        store.close()


def test_缺code_name_拒绝猜测(tmp_path: Path) -> None:
    """实测 code_name 100% 非空；缺失说明源格式变了，禁止默认值兜底。"""
    day = date(2005, 1, 4)
    rows = [{"code": "sh.600000", "tradeStatus": "1", "code_name": ""}]
    fetcher = FakeFetcher({day: rows})
    provider, _, store = _make(tmp_path, fetcher, trading_days=[day])
    try:
        with pytest.raises(DataQualityGateError, match="code_name"):
            provider.symbols(as_of=day, market="cn_a")
    finally:
        store.close()


def test_非法tradeStatus_拒绝猜测(tmp_path: Path) -> None:
    """tradeStatus 出现 '0'/'1' 之外的值 → 源格式漂移，禁止猜测。"""
    day = date(2005, 1, 4)
    rows = [{"code": "sh.600000", "tradeStatus": "2", "code_name": "浦发银行"}]
    fetcher = FakeFetcher({day: rows})
    provider, _, store = _make(tmp_path, fetcher, trading_days=[day])
    try:
        with pytest.raises(DataQualityGateError, match="tradeStatus"):
            provider.symbols(as_of=day, market="cn_a")
    finally:
        store.close()


def test_全部被指数过滤_P0门禁(tmp_path: Path) -> None:
    """快照有行但全被前缀过滤 → 过滤规则与源不符，拒绝写入。"""
    day = date(2005, 1, 4)
    rows = [{"code": "sh.000001", "tradeStatus": "1", "code_name": "上证综指"}]
    fetcher = FakeFetcher({day: rows})
    provider, repo, store = _make(tmp_path, fetcher, trading_days=[day])
    try:
        with pytest.raises(DataQualityGateError, match="过滤"):
            provider.symbols(as_of=day, market="cn_a")
        assert repo.snapshot_dates() == []
    finally:
        store.close()


# ============================================================
# 缓存与协议
# ============================================================
def test_缓存命中_不查源(tmp_path: Path) -> None:
    """已落库的快照直接返回，不再问源（provider 第 1 优先路径）。"""
    day = date(2005, 1, 4)
    fetcher = FakeFetcher(
        {day: [{"code": "sh.600000", "tradeStatus": "1", "code_name": "浦发银行"}]}
    )
    provider, _repo, store = _make(tmp_path, fetcher, trading_days=[day])
    try:
        first = provider.symbols(as_of=day, market="cn_a")
        assert len(fetcher.calls) == 1
        second = provider.symbols(as_of=day, market="cn_a")
        assert len(fetcher.calls) == 1  # ★ 第二次没查源
        assert [s.symbol for s in first] == [s.symbol for s in second]
    finally:
        store.close()


def test_缓存命中_优先于交易日校验(tmp_path: Path) -> None:
    """已落库的快照就是真相：日历校验只在**查源前**做，缓存路径直接返回。"""
    day = date(2005, 1, 4)
    store = SqliteStore(tmp_path / "q.db")
    try:
        repo = SqlitePitUniverseRepository(store)
        repo.save_snapshot(
            [PitRow(as_of=day, symbol="600000.SH", code_name="浦发银行", is_st=False)]
        )
        fetcher = FakeFetcher()  # 日历为空（任何日都不是交易日）+ 缓存命中 → 也不该查源
        provider = BaostockPitUniverseProvider(
            repo=repo,
            calendar=FakeCalendar([]),
            fetcher=fetcher,
        )
        snapshots = provider.symbols(as_of=day, market="cn_a")
        assert [s.symbol for s in snapshots] == ["600000.SH"]
        assert fetcher.calls == []
    finally:
        store.close()


def test_协议属性(tmp_path: Path) -> None:
    """Tier A：survivorship_risk=NONE；pool_build_date=1990-12-19（M-15）。"""
    fetcher = FakeFetcher()
    provider, _, store = _make(tmp_path, fetcher)
    try:
        assert provider.survivorship_risk is SurvivorshipRisk.NONE
        assert provider.pool_build_date == date(1990, 12, 19)
    finally:
        store.close()


def test_非cn_a市场_拒绝(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    provider, _, store = _make(tmp_path, fetcher)
    try:
        with pytest.raises(ValueError, match="未知市场"):
            provider.symbols(as_of=date(2024, 1, 2), market="hk")
    finally:
        store.close()


def test_构造时不支持的市场_拒绝(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "q.db")
    try:
        repo = SqlitePitUniverseRepository(store)
        with pytest.raises(ValueError, match="只支持"):
            BaostockPitUniverseProvider(
                repo=repo,
                calendar=FakeCalendar([]),
                fetcher=FakeFetcher(),
                market="hk",
            )
    finally:
        store.close()


def test_默认抓取器_ok透传(tmp_path: Path) -> None:
    """default_all_stock_fetcher：worker 结果 ok=False → SourceUnavailableError。"""

    class FakeWorker:
        def __init__(self, result_ok: bool) -> None:
            self._ok = result_ok

        def run(self, call: Any) -> Any:
            assert call.kind == "all_stock"
            return WorkerResult(
                call_id=call.call_id, ok=self._ok, payload=[] if not self._ok else [{}], error=None
            )

        def close(self) -> None:
            pass

    fetch_ok = default_all_stock_fetcher(FakeWorker(True))  # type: ignore[arg-type]
    assert fetch_ok(date(2024, 1, 2)) == [{}]

    fetch_bad = default_all_stock_fetcher(FakeWorker(False))  # type: ignore[arg-type]
    with pytest.raises(SourceUnavailableError, match="query_all_stock"):
        fetch_bad(date(2024, 1, 2))


# ============================================================
# Tier C：CurrentListProvider
# ============================================================
def test_tierC_早于构建日_硬拦截() -> None:
    """as_of < pool_build_date → SurvivorshipBiasError（不是警告，附录 B）。"""

    def fetch(market: str) -> list[SymbolSnapshot]:
        return [SymbolSnapshot(symbol="600000.SH", market=market, name="浦发银行")]

    provider = CurrentListProvider(pool_build_date=date(2026, 9, 5), fetch_current=fetch)
    with pytest.raises(SurvivorshipBiasError, match="幸存者偏差"):
        provider.symbols(as_of=date(2020, 1, 2), market="cn_a")


def test_tierC_构建日之后_返回当前名单() -> None:
    def fetch(market: str) -> list[SymbolSnapshot]:
        return [SymbolSnapshot(symbol="600000.SH", market=market, name="浦发银行")]

    provider = CurrentListProvider(pool_build_date=date(2026, 9, 5), fetch_current=fetch)
    snapshots = provider.symbols(as_of=date(2026, 9, 6), market="cn_a")
    assert [s.symbol for s in snapshots] == ["600000.SH"]
    assert provider.survivorship_risk is SurvivorshipRisk.HIGH
