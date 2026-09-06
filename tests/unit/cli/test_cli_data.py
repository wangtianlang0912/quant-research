"""qv2 data CLI 测试（T02.7 交付验证的机械化）。

验收：`echo $?` = 0 或明确的 FAILED（非静默成功）——
每个命令都断言退出码与输出中的状态词。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from tests.conftest import make_bar
from typer.testing import CliRunner

from quant_v2.adapters.market_data.subprocess_worker import WorkerResult
from quant_v2.adapters.persistence.parquet_bar_store import ParquetBarStore
from quant_v2.adapters.persistence.sqlite_store import SqliteStore
from quant_v2.cli.commands import data as data_module
from quant_v2.cli.main import app
from quant_v2.domain.errors import SourceUnavailableError

DAY = date(2026, 9, 4)
NEXT = date(2026, 9, 5)

runner = CliRunner()


@pytest.fixture
def env(tmp_path: Path):
    """bars 根 + db 路径（CLI 参数注入，不依赖 cwd）。"""
    return tmp_path / "bars", tmp_path / "state.db"


def _write_day(root: Path, day: date, symbols_closes: dict[str, str]) -> None:
    bs = ParquetBarStore(root)
    bs.save_bars([make_bar(symbol=s, day=day, close=c) for s, c in symbols_closes.items()])


class TestFingerprint命令:
    def test_输出指纹并登记(self, env):
        bars_root, db = env
        _write_day(bars_root, NEXT, {"600000.SH": "10"})
        result = runner.invoke(
            app,
            [
                "data",
                "fingerprint",
                "--market",
                "cn_a",
                "--as-of",
                NEXT.isoformat(),
                "--bars-root",
                str(bars_root),
                "--db",
                str(db),
            ],
        )
        assert result.exit_code == 0
        store = SqliteStore(db)
        try:
            row = store.conn.execute(
                "SELECT fingerprint FROM partition_fingerprints WHERE dt=?",
                (NEXT.isoformat(),),
            ).fetchone()
        finally:
            store.close()
        assert row is not None
        assert row["fingerprint"] in result.output

    def test_同数据重算_指纹一致(self, env):
        bars_root, db = env
        _write_day(bars_root, NEXT, {"600000.SH": "10"})
        args = [
            "data",
            "fingerprint",
            "--as-of",
            NEXT.isoformat(),
            "--bars-root",
            str(bars_root),
            "--db",
            str(db),
        ]
        r1 = runner.invoke(app, args)
        r2 = runner.invoke(app, args)  # 同日重跑（D-11）
        assert r1.exit_code == 0 and r2.exit_code == 0
        fp1 = r1.output.strip().splitlines()[-1].strip()
        fp2 = r2.output.strip().splitlines()[-1].strip()
        assert fp1 == fp2 and len(fp1) == 64

    def test_分区缺失_退出码1_非静默(self, env):
        bars_root, db = env
        result = runner.invoke(
            app,
            [
                "data",
                "fingerprint",
                "--as-of",
                NEXT.isoformat(),
                "--bars-root",
                str(bars_root),
                "--db",
                str(db),
            ],
        )
        assert result.exit_code == 1
        assert "FAILED" in result.output


class TestQuality命令:
    def _quality_args(self, bars_root: Path, db: Path, *extra: str) -> list[str]:
        return [
            "data",
            "quality",
            "--as-of",
            NEXT.isoformat(),
            "--bars-root",
            str(bars_root),
            "--db",
            str(db),
            *extra,
        ]

    def test_门禁通过_退出码0(self, env, tmp_path):
        bars_root, db = env
        _write_day(bars_root, DAY, {"600000.SH": "10", "000001.SZ": "20"})
        _write_day(bars_root, NEXT, {"600000.SH": "10.1", "000001.SZ": "20.2"})
        result = runner.invoke(app, self._quality_args(bars_root, db))
        assert result.exit_code == 0
        assert "PASS" in result.output
        # 报告已落库
        store = SqliteStore(db)
        try:
            rows = store.conn.execute(
                "SELECT status FROM data_quality_reports WHERE as_of=?",
                (NEXT.isoformat(),),
            ).fetchall()
        finally:
            store.close()
        assert [r["status"] for r in rows] == ["PASS"]

    def test_覆盖暴跌_退出码2_FAILED_P0告警(self, env, tmp_path):
        bars_root, db = env
        full = {f"60000{i}.SH": "10" for i in range(10)}
        _write_day(bars_root, DAY, full)
        _write_day(bars_root, NEXT, {f"60000{i}.SH": "10" for i in range(3)})
        expected = tmp_path / "expected.txt"
        expected.write_text("\n".join(sorted(full)), encoding="utf-8")
        result = runner.invoke(
            app, self._quality_args(bars_root, db, "--expected-file", str(expected))
        )
        assert result.exit_code == 2  # ★ && 链必须在此断开
        assert "FAILED" in result.output
        assert "信号生成已中止" in result.output
        store = SqliteStore(db)
        try:
            alert = store.conn.execute(
                "SELECT level FROM alerts WHERE source='data_quality_gate'"
            ).fetchone()
            report_row = store.conn.execute(
                "SELECT status, report FROM data_quality_reports WHERE as_of=?",
                (NEXT.isoformat(),),
            ).fetchone()
        finally:
            store.close()
        assert alert is not None and alert["level"] == "P0"
        assert report_row["status"] == "FAIL"
        payload = json.loads(report_row["report"])
        assert len(payload["rules"]) == 7

    def test_无基线_退出码1_带指引(self, env):
        bars_root, db = env
        result = runner.invoke(app, self._quality_args(bars_root, db))
        assert result.exit_code == 1
        assert "FAILED" in result.output
        assert "期望标的清单" in result.output

    def test_日期格式错误_退出码2_param(self, env):
        bars_root, db = env
        result = runner.invoke(
            app,
            [
                "data",
                "quality",
                "--as-of",
                "2026/09/05",  # 错误格式
                "--bars-root",
                str(bars_root),
                "--db",
                str(db),
            ],
        )
        assert result.exit_code != 0
        assert "YYYY-MM-DD" in result.output


class TestSync命令:
    """qv2 data sync（T02.2/T02.3 接线）：PIT 池定清单 → ResilientSource → Parquet。"""

    DAY = date(2026, 9, 4)

    class FakeWorker:
        """FakeWorker：trade_dates/all_stock 走 run，bars/factors 走 run_batch。"""

        def __init__(self, *, bars_ok=True, trade_flags=None) -> None:
            self.bars_ok = bars_ok
            # (calendar_date, is_trading_day) 缺省：DAY 是交易日
            self.trade_flags = trade_flags or [
                (TestSync命令.DAY.isoformat(), "1"),
            ]

        def run(self, call):
            return self.run_batch([call])[call.call_id]

        def run_batch(self, calls, checkpoint_key=None):
            return {c.call_id: self._handle(c) for c in calls}

        def _handle(self, call):
            if call.kind == "trade_dates":
                payload = [{"calendar_date": d, "is_trading_day": f} for d, f in self.trade_flags]
            elif call.kind == "all_stock":
                payload = [
                    {"code": "sh.600000", "tradeStatus": "1", "code_name": "浦发银行"},
                    {"code": "sh.000001", "tradeStatus": "1", "code_name": "上证综指"},
                ]
            elif call.kind == "bars":
                if not self.bars_ok:
                    return WorkerResult(
                        call_id=call.call_id, ok=False, payload=[], error="模拟主源故障"
                    )
                payload = [
                    {
                        "date": call.start.isoformat(),
                        "open": "10",
                        "high": "11",
                        "low": "9",
                        "close": "10.5",
                        "volume": "1000",
                        "amount": "10500",
                        "tradestatus": "1",
                        "preclose": "10",
                    }
                ]
            else:  # factors
                payload = []
            return WorkerResult(call_id=call.call_id, ok=True, payload=payload, error=None)

        def close(self) -> None:
            pass

    def _invoke(self, tmp_path, monkeypatch, worker):
        class FakeCalendar:
            def __init__(self, days):
                self._days = set(days)

            def is_trading_day(self, market, day):
                return day in self._days

        monkeypatch.setattr(data_module, "SubprocessWorker", lambda: worker)
        monkeypatch.setattr(
            data_module,
            "_build_calendar",
            lambda _market, days, _config_dir: FakeCalendar(days),
        )
        db = tmp_path / "state.db"
        bars_root = tmp_path / "bars"
        result = runner.invoke(
            app,
            [
                "data",
                "sync",
                "--market",
                "cn_a",
                "--as-of",
                self.DAY.isoformat(),
                "--bars-root",
                str(bars_root),
                "--db",
                str(db),
            ],
        )
        return result, db, bars_root

    def test_同步成功_落库分区与PIT池(self, tmp_path, monkeypatch):
        """PIT 池定清单（指数被过滤）→ 主源抓 bars → Parquet 分区落库。"""
        result, db, bars_root = self._invoke(tmp_path, monkeypatch, self.FakeWorker())
        assert result.exit_code == 0, result.output
        assert "PASS" in result.output

        partition = bars_root / "market=cn_a" / f"dt={self.DAY.isoformat()}" / "bars.parquet"
        assert partition.exists()

        store = SqliteStore(db)
        try:
            rows = store.conn.execute(
                "SELECT symbol FROM pit_universe WHERE as_of=?",
                (self.DAY.isoformat(),),
            ).fetchall()
            assert [r["symbol"] for r in rows] == ["600000.SH"]  # 指数被 M-20 过滤
        finally:
            store.close()

    def test_非交易日_退出码1不查行情(self, tmp_path, monkeypatch):
        """as_of 非交易日 → NotTradingDayError → FAILED 退出码 1（M-19）。"""
        worker = self.FakeWorker(
            trade_flags=[
                (date(2026, 9, 3).isoformat(), "1"),  # 前一日是交易日
                (self.DAY.isoformat(), "0"),  # as_of 非交易日
            ]
        )
        result, _db, _ = self._invoke(tmp_path, monkeypatch, worker)
        assert result.exit_code == 1
        assert "FAILED" in result.output
        assert "交易日" in result.output

    def test_全源不可用_P0告警退出码1(self, tmp_path, monkeypatch):
        """主源 + 两个备源全挂 → P0 告警落库 + 退出码 1（D-10 非静默）。"""

        class DeadSource:
            source_id = "dead"
            capabilities = None

            def fetch_bars(self, req):
                raise SourceUnavailableError(f"{self.source_id} 模拟不可用")

        monkeypatch.setattr(data_module, "AkshareCnAdapter", DeadSource)
        monkeypatch.setattr(data_module, "TencentAdapter", DeadSource)
        worker = self.FakeWorker(bars_ok=False)
        result, db, _ = self._invoke(tmp_path, monkeypatch, worker)
        assert result.exit_code == 1
        assert "FAILED" in result.output

        store = SqliteStore(db)
        try:
            rows = store.conn.execute("SELECT level FROM alerts WHERE level='P0'").fetchall()
            assert rows  # ★ 降级告警必须落库（D-10：禁止静默降级）
        finally:
            store.close()


class TestBuildUniverse命令:
    """qv2 data build-universe（T02.5）：采样建池 + 断点续跑 + M-19/M-21 门禁。"""

    D1 = date(2024, 6, 3)  # 周一
    D2 = date(2024, 6, 4)
    D3 = date(2024, 6, 5)
    # 周六（非交易日，混进 trade_dates 结果里验证过滤）
    WEEKEND = date(2024, 6, 1)

    def _invoke(self, tmp_path, monkeypatch, worker, *, extra=None):
        class FakeCalendar:
            def __init__(self, days: list[date]) -> None:
                self._days = set(days)

            def is_trading_day(self, market: str, day: date) -> bool:
                return day in self._days

        trading_days = [self.WEEKEND, self.D1, self.D2, self.D3]
        monkeypatch.setattr(data_module, "SubprocessWorker", lambda: worker)
        monkeypatch.setattr(
            data_module,
            "_build_calendar",
            lambda _market, _days, _config_dir: FakeCalendar(trading_days),
        )
        db = tmp_path / "state.db"
        args = [
            "data",
            "build-universe",
            "--market",
            "cn_a",
            "--from",
            self.D1.isoformat(),
            "--to",
            self.D3.isoformat(),
            "--sampling",
            "daily",
            "--db",
            str(db),
        ]
        if extra:
            args.extend(extra)
        result = runner.invoke(app, args)
        return result, db

    @staticmethod
    def _alerts(db: Path) -> list[tuple[str, str]]:
        store = SqliteStore(db)
        try:
            rows = store.conn.execute(
                "SELECT level, message FROM alerts ORDER BY created_at"
            ).fetchall()
            return [(r["level"], r["message"]) for r in rows]
        finally:
            store.close()

    def test_建池成功_名称突变分级告警(self, tmp_path, monkeypatch):
        """ST 相关 → INFO；实质性突变 → P0（M-21）。"""
        cls = TestBuildUniverse命令

        class FakeWorker:
            def run(self, call):
                if call.kind == "trade_dates":
                    return WorkerResult(
                        call_id=call.call_id,
                        ok=True,
                        payload=[
                            {"calendar_date": d.isoformat(), "is_trading_day": "1" if flag else "0"}
                            for d, flag in [
                                (cls.WEEKEND, False),
                                (cls.D1, True),
                                (cls.D2, True),
                                (cls.D3, True),
                            ]
                        ],
                        error=None,
                    )
                assert call.kind == "all_stock"
                rows_by_day = {
                    cls.D1: [
                        {"code": "sh.600000", "tradeStatus": "1", "code_name": "浦发银行"},
                        {"code": "sz.000001", "tradeStatus": "1", "code_name": "平安银行"},
                    ],
                    cls.D2: [
                        # 戴帽（基名不变，仅 ST token 增删 → M-21 判 INFO）
                        {"code": "sh.600000", "tradeStatus": "1", "code_name": "*ST浦发银行"},
                        {"code": "sz.000001", "tradeStatus": "1", "code_name": "平安银行"},
                    ],
                    cls.D3: [
                        {"code": "sh.600000", "tradeStatus": "1", "code_name": "*ST浦发银行"},
                        {
                            "code": "sz.000001",
                            "tradeStatus": "1",
                            "code_name": "平银科技",
                        },  # 重组更名
                    ],
                }
                return WorkerResult(
                    call_id=call.call_id,
                    ok=True,
                    payload=rows_by_day.get(call.start, []),
                    error=None,
                )

            def close(self) -> None:
                pass

        result, db = self._invoke(tmp_path, monkeypatch, FakeWorker())
        assert result.exit_code == 0, result.output
        assert "PASS" in result.output

        store = SqliteStore(db)
        try:
            dates = [
                date.fromisoformat(r["as_of"])
                for r in store.conn.execute(
                    "SELECT DISTINCT as_of FROM pit_universe ORDER BY as_of"
                ).fetchall()
            ]
            assert dates == [self.D1, self.D2, self.D3]  # 周六被日历过滤
            st_rows = store.conn.execute(
                "SELECT symbol FROM pit_universe WHERE as_of=? AND is_st=1",
                (self.D2.isoformat(),),
            ).fetchall()
            assert [r["symbol"] for r in st_rows] == ["600000.SH"]
        finally:
            store.close()

        alerts = self._alerts(db)
        assert alerts[0][0] == "INFO"
        assert "ST 相关" in alerts[0][1]
        assert alerts[1][0] == "P0"
        assert "实质性" in alerts[1][1]

    def test_断点续跑_已落库跳过(self, tmp_path, monkeypatch):
        """重跑同一区间：已落库的采样日直接跳过，不重复抓源。"""
        cls = TestBuildUniverse命令
        calls = {"count": 0}

        class FakeWorker:
            def run(self, call):
                if call.kind == "trade_dates":
                    return WorkerResult(
                        call_id=call.call_id,
                        ok=True,
                        payload=[
                            {"calendar_date": d.isoformat(), "is_trading_day": "1"}
                            for d in [cls.D1, cls.D2, cls.D3]
                        ],
                        error=None,
                    )
                calls["count"] += 1
                return WorkerResult(
                    call_id=call.call_id,
                    ok=True,
                    payload=[{"code": "sh.600000", "tradeStatus": "1", "code_name": "浦发银行"}],
                    error=None,
                )

            def close(self) -> None:
                pass

        worker = FakeWorker()
        first, _db = self._invoke(tmp_path, monkeypatch, worker)
        assert first.exit_code == 0, first.output
        fetched_first = calls["count"]
        assert fetched_first == 3  # 3 个采样日各抓一次

        second, _db = self._invoke(tmp_path, monkeypatch, worker)
        assert second.exit_code == 0, second.output
        assert calls["count"] == fetched_first  # ★ 第二次全部命中缓存，零抓取
        assert "已落库跳过" in second.output

    def test_交易日零行_P0门禁_退出码2(self, tmp_path, monkeypatch):
        """M-19：交易日 + 0 rows → P0 告警 + 退出码 2（非静默成功）。"""
        cls = TestBuildUniverse命令

        class FakeWorker:
            def run(self, call):
                if call.kind == "trade_dates":
                    return WorkerResult(
                        call_id=call.call_id,
                        ok=True,
                        payload=[
                            {"calendar_date": d.isoformat(), "is_trading_day": "1"}
                            for d in [cls.D1, cls.D2, cls.D3]
                        ],
                        error=None,
                    )
                return WorkerResult(  # 快照永远 0 行
                    call_id=call.call_id, ok=True, payload=[], error=None
                )

            def close(self) -> None:
                pass

        result, db = self._invoke(tmp_path, monkeypatch, FakeWorker())
        assert result.exit_code == 2
        assert "FAILED" in result.output
        assert "0 行" in result.output
        assert any(level == "P0" for level, _ in self._alerts(db))

    def test_from早于开市日_参数错误(self, tmp_path, monkeypatch):
        """--from < 1990-12-19 → 参数错误（M-15）。"""

        class FakeWorker:
            def run(self, call):  # pragma: no cover - 参数校验在前，走不到
                raise AssertionError

            def close(self) -> None:
                pass

        result, _ = self._invoke(
            tmp_path, monkeypatch, FakeWorker(), extra=["--from", "1990-01-01"]
        )
        assert result.exit_code != 0
        assert "1990-12-19" in result.output
