"""PIT 池仓库测试（T02.5 / D-05）。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from quant_v2.adapters.persistence.repositories import (
    PitRow,
    SqlitePitUniverseRepository,
)
from quant_v2.adapters.persistence.sqlite_store import SqliteStore

pytestmark = pytest.mark.unit

DAY = date(2005, 1, 4)
NEXT = date(2005, 1, 5)


def _rows(day: date, *, st: bool = False) -> list[PitRow]:
    return [
        PitRow(
            as_of=day,
            symbol="600000.SH",
            code_name="*ST浦发" if st else "浦发银行",
            is_st=st,
            is_st_source="NAME_PARSE",
            trade_status="SUSPENDED" if st else "TRADING",
        )
    ]


@pytest.fixture
def repo(tmp_path: Path) -> tuple[SqlitePitUniverseRepository, SqliteStore]:
    store = SqliteStore(tmp_path / "q.db")
    yield SqlitePitUniverseRepository(store), store
    store.close()


def test_保存与读取_往返(repo: tuple[SqlitePitUniverseRepository, SqliteStore]) -> None:
    pit, _ = repo
    pit.save_snapshot(
        [
            *_rows(DAY),
            PitRow(as_of=DAY, symbol="000001.SZ", code_name="平安银行", is_st=False),
        ]
    )
    loaded = pit.load_snapshot(DAY)
    assert {(r.symbol, r.code_name, r.is_st, r.trade_status) for r in loaded} == {
        ("600000.SH", "浦发银行", False, "TRADING"),
        ("000001.SZ", "平安银行", False, "TRADING"),
    }


def test_空快照_拒绝写入(repo: tuple[SqlitePitUniverseRepository, SqliteStore]) -> None:
    """M-19：0 rows 是 P0 信号，落库层再拦一道（防御深度）。"""
    pit, _ = repo
    with pytest.raises(ValueError, match="空快照"):
        pit.save_snapshot([])


def test_重跑幂等(repo: tuple[SqlitePitUniverseRepository, SqliteStore]) -> None:
    """同一天重复保存不产生重复行（INSERT OR REPLACE，主键 as_of+symbol）。"""
    pit, _ = repo
    pit.save_snapshot(_rows(DAY, st=True))
    pit.save_snapshot(_rows(DAY, st=True))  # 重跑
    loaded = pit.load_snapshot(DAY)
    assert len(loaded) == 1
    assert loaded[0].is_st is True


def test_快照日列表_升序去重(repo: tuple[SqlitePitUniverseRepository, SqliteStore]) -> None:
    pit, _ = repo
    pit.save_snapshot(_rows(NEXT))
    pit.save_snapshot(_rows(DAY))
    assert pit.snapshot_dates() == [DAY, NEXT]


def test_前一快照(repo: tuple[SqlitePitUniverseRepository, SqliteStore]) -> None:
    """严格早于给定日的最近快照（名称突变检测的对照基准）。"""
    pit, _ = repo
    assert pit.previous_snapshot(DAY) is None  # 库为空
    pit.save_snapshot(_rows(DAY))
    pit.save_snapshot(_rows(NEXT))
    prev = pit.previous_snapshot(NEXT)
    assert prev is not None
    prev_day, prev_rows = prev
    assert prev_day == DAY
    assert [r.symbol for r in prev_rows] == ["600000.SH"]
    # 自己不算"前一快照"
    assert pit.previous_snapshot(DAY) is None


def test_无快照返回空列表(repo: tuple[SqlitePitUniverseRepository, SqliteStore]) -> None:
    pit, _ = repo
    assert pit.load_snapshot(DAY) == []
    assert pit.snapshot_dates() == []
