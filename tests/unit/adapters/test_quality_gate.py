"""数据质量门禁执行器测试（T02.6 落地 / T02.7）。

覆盖：7 项规则取数与派生口径、三表落盘（报告/指纹/P0 告警）、
期望清单解析的三条路径与"无基线即炸"。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from tests.conftest import make_bar

from quant_v2.adapters.persistence.parquet_bar_store import ParquetBarStore
from quant_v2.adapters.persistence.quality_gate import (
    QualityGateRunner,
    QualityThresholds,
    resolve_expected_symbols,
)
from quant_v2.adapters.persistence.sqlite_store import SqliteStore
from quant_v2.domain.services.data_quality_rules import RuleStatus

DAY = date(2026, 9, 4)
NEXT = date(2026, 9, 5)  # 分区即事实，不依赖交易日历


@pytest.fixture
def bars_root(tmp_path: Path) -> Path:
    return tmp_path / "bars"


@pytest.fixture
def store(tmp_path: Path) -> SqliteStore:
    s = SqliteStore(tmp_path / "state.db")
    yield s
    s.close()


def _write_day(root: Path, day: date, symbols_closes: dict[str, str], *, factor: str = "1") -> None:
    """写一个分区：symbol → 收盘价。"""
    bs = ParquetBarStore(root)
    bs.save_bars(
        [
            make_bar(symbol=sym, day=day, close=close, adj_factor=factor)
            for sym, close in symbols_closes.items()
        ]
    )


def _runner(bars_root: Path, store: SqliteStore, thresholds: QualityThresholds | None = None):
    return QualityGateRunner(
        bar_store=ParquetBarStore(bars_root), store=store, thresholds=thresholds
    )


class Test门禁通过:
    def test_干净两日数据_全PASS_三表落盘(self, bars_root, store):
        _write_day(bars_root, DAY, {"600000.SH": "10", "000001.SZ": "20"})
        _write_day(bars_root, NEXT, {"600000.SH": "10.1", "000001.SZ": "20.2"})
        report = _runner(bars_root, store).run(
            market="cn_a", as_of=NEXT, expected_symbols=["600000.SH", "000001.SZ"]
        )
        assert report.status is RuleStatus.PASS
        assert len(report.results) == 7

        # 报告落盘
        rows = store.conn.execute(
            "SELECT * FROM data_quality_reports WHERE market='cn_a' AND as_of=?",
            (NEXT.isoformat(),),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["status"] == "PASS"
        payload = json.loads(rows[0]["report"])
        assert len(payload["rules"]) == 7

        # 指纹登记
        fp = store.conn.execute(
            "SELECT fingerprint FROM partition_fingerprints WHERE market='cn_a' AND dt=?",
            (NEXT.isoformat(),),
        ).fetchone()
        assert fp is not None and len(fp["fingerprint"]) == 64

        # 无 P0 告警
        alerts = store.conn.execute("SELECT * FROM alerts").fetchall()
        assert alerts == []

    def test_停牌标的当日有行_不算缺失(self, bars_root, store):
        bs = ParquetBarStore(bars_root)
        bs.save_bars([make_bar(symbol="600000.SH", day=DAY, close="10")])
        bs.save_bars(
            [
                # 停牌平铺行：零成交（有量会被 price_anomaly 判"停牌却有成交量"）
                make_bar(symbol="600000.SH", day=NEXT, close="10", volume="0", is_suspended=True),
                make_bar(symbol="000001.SZ", day=NEXT, close="20"),
            ]
        )
        report = _runner(bars_root, store).run(
            market="cn_a", as_of=NEXT, expected_symbols=["600000.SH", "000001.SZ"]
        )
        assert report.status is RuleStatus.PASS
        by_id = {r.rule_id: r for r in report.results}
        assert by_id["consecutive_missing"].status is RuleStatus.PASS


class Test门禁失败:
    def test_覆盖暴跌样本_门禁FAIL_P0告警落库(self, bars_root, store):
        """v1 实证回归（3025→990）在执行器层的完整路径：FAIL → alerts 表 P0。"""
        # 昨日 10 只全部有数据，今日只剩 3 只
        full = {f"60000{i}.SH": "10" for i in range(10)}
        _write_day(bars_root, DAY, full)
        dropped = {f"60000{i}.SH": "10" for i in range(3)}
        _write_day(bars_root, NEXT, dropped)
        report = _runner(bars_root, store).run(
            market="cn_a", as_of=NEXT, expected_symbols=sorted(full)
        )
        assert report.status is RuleStatus.FAIL
        alerts = store.conn.execute("SELECT * FROM alerts").fetchall()
        assert len(alerts) == 1
        assert alerts[0]["level"] == "P0"
        assert "coverage" in alerts[0]["message"]

    def test_当日分区整体缺失_覆盖FAIL(self, bars_root, store):
        _write_day(bars_root, DAY, {"600000.SH": "10"})
        report = _runner(bars_root, store).run(
            market="cn_a", as_of=NEXT, expected_symbols=["600000.SH"]
        )
        assert report.status is RuleStatus.FAIL
        by_id = {r.rule_id: r for r in report.results}
        assert by_id["coverage"].status is RuleStatus.FAIL
        assert by_id["coverage"].metrics["actual"] == 0
        # 分区缺失不落指纹（没有数据就没有指纹）
        fp = store.conn.execute("SELECT * FROM partition_fingerprints").fetchall()
        assert fp == []

    def test_环比跳变超限_FAIL(self, bars_root, store):
        _write_day(bars_root, DAY, {"600000.SH": "10"})
        _write_day(bars_root, NEXT, {"600000.SH": "25"})  # +150%
        report = _runner(bars_root, store).run(
            market="cn_a", as_of=NEXT, expected_symbols=["600000.SH"]
        )
        by_id = {r.rule_id: r for r in report.results}
        assert by_id["price_jump"].status is RuleStatus.FAIL

    def test_复权因子断裂_FAIL(self, bars_root, store):
        bs = ParquetBarStore(bars_root)
        bs.save_bars([make_bar(symbol="600000.SH", day=DAY, close="10", adj_factor="1")])
        bs.save_bars([make_bar(symbol="600000.SH", day=NEXT, close="10", adj_factor="9")])
        report = _runner(bars_root, store).run(
            market="cn_a", as_of=NEXT, expected_symbols=["600000.SH"]
        )
        by_id = {r.rule_id: r for r in report.results}
        assert by_id["adj_factor_continuity"].status is RuleStatus.FAIL

    def test_重复行_FAIL(self, bars_root, store):
        bs = ParquetBarStore(bars_root)
        bs.save_bars([make_bar(symbol="600000.SH", day=DAY, close="10")])
        bs.save_bars(
            [
                make_bar(symbol="600000.SH", day=NEXT, close="10.5"),
                make_bar(symbol="600000.SH", day=NEXT, close="10.8"),  # 同分区同日重复
            ]
        )
        report = _runner(bars_root, store).run(
            market="cn_a", as_of=NEXT, expected_symbols=["600000.SH"]
        )
        by_id = {r.rule_id: r for r in report.results}
        assert by_id["duplicate_rows"].status is RuleStatus.FAIL

    def test_连续缺失_FAIL(self, bars_root, store):
        # 600000.SH 只在 d1 有数据，d2/NEXT 两个分区都缺席 → 尾部连续缺失 2
        d1 = NEXT - timedelta(days=2)
        d2 = NEXT - timedelta(days=1)
        bs = ParquetBarStore(bars_root)
        bs.save_bars([make_bar(symbol="600000.SH", day=d1, close="10")])
        bs.save_bars([make_bar(symbol="000001.SZ", day=d2, close="20")])
        bs.save_bars([make_bar(symbol="000001.SZ", day=NEXT, close="20.2")])
        report = _runner(
            bars_root,
            store,
            QualityThresholds(max_consecutive_missing=1),
        ).run(market="cn_a", as_of=NEXT, expected_symbols=["600000.SH", "000001.SZ"])
        by_id = {r.rule_id: r for r in report.results}
        assert by_id["consecutive_missing"].status is RuleStatus.FAIL
        assert by_id["consecutive_missing"].metrics["max_consecutive"] == 2

    def test_阈值可配置放宽_原FAIL变PASS(self, bars_root, store):
        _write_day(bars_root, DAY, {"600000.SH": "10"})
        _write_day(bars_root, NEXT, {"600000.SH": "25"})
        report = _runner(
            bars_root,
            store,
            QualityThresholds(max_jump_pct=Decimal("200")),
        ).run(market="cn_a", as_of=NEXT, expected_symbols=["600000.SH"])
        assert report.status is RuleStatus.PASS


class Test环比基准:
    def test_与最近分区比_而不是自然昨日(self, bars_root, store):
        """中间隔一个缺分区日（周末/未同步）：基准是最近有数据的分区。"""
        prev = NEXT - timedelta(days=3)
        _write_day(bars_root, prev, {"600000.SH": "10"})
        _write_day(bars_root, NEXT, {"600000.SH": "10.2"})
        report = _runner(bars_root, store).run(
            market="cn_a", as_of=NEXT, expected_symbols=["600000.SH"]
        )
        assert report.status is RuleStatus.PASS  # +2% 在阈值内


class Test期望清单解析:
    def test_显式文件优先(self, bars_root, store, tmp_path):
        _write_day(bars_root, DAY, {"600000.SH": "10"})
        f = tmp_path / "expected.txt"
        f.write_text("600000.SH\n000001.SZ\n", encoding="utf-8")
        got = resolve_expected_symbols(
            store=store,
            bar_store=ParquetBarStore(bars_root),
            market="cn_a",
            as_of=NEXT,
            expected_file=f,
        )
        assert got == ["000001.SZ", "600000.SH"]

    def test_PIT池快照次优先(self, bars_root, store):
        with store.conn:
            store.conn.execute(
                "INSERT INTO pit_universe(as_of, symbol) VALUES(?, ?)",
                (DAY.isoformat(), "600000.SH"),
            )
            store.conn.execute(
                "INSERT INTO pit_universe(as_of, symbol) VALUES(?, ?)",
                (DAY.isoformat(), "000001.SZ"),
            )
        got = resolve_expected_symbols(
            store=store,
            bar_store=ParquetBarStore(bars_root),
            market="cn_a",
            as_of=NEXT,
        )
        assert got == ["000001.SZ", "600000.SH"]

    def test_无PIT池_退化为前一分区(self, bars_root, store):
        _write_day(bars_root, DAY, {"600000.SH": "10", "000001.SZ": "20"})
        got = resolve_expected_symbols(
            store=store,
            bar_store=ParquetBarStore(bars_root),
            market="cn_a",
            as_of=NEXT,
        )
        assert got == ["000001.SZ", "600000.SH"]

    def test_什么都没有_炸而非空清单(self, bars_root, store):
        with pytest.raises(FileNotFoundError, match="期望标的清单"):
            resolve_expected_symbols(
                store=store,
                bar_store=ParquetBarStore(bars_root),
                market="cn_a",
                as_of=NEXT,
            )

    def test_PIT池取早于as_of的最近快照_不取未来快照(self, bars_root, store):
        """PIT 纪律：不能用 as_of 之后的快照当基线（幸存者偏差）。"""
        with store.conn:
            store.conn.execute(
                "INSERT INTO pit_universe(as_of, symbol) VALUES(?, ?)",
                ((NEXT + timedelta(days=1)).isoformat(), "999999.SH"),  # 未来快照：不得使用
            )
        _write_day(bars_root, DAY, {"600000.SH": "10"})
        got = resolve_expected_symbols(
            store=store,
            bar_store=ParquetBarStore(bars_root),
            market="cn_a",
            as_of=NEXT,
        )
        assert got == ["600000.SH"]
