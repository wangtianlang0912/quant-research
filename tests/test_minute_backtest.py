from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.app.backtest_app import run_backtest, run_minute_backtest
from src.domain.enums import Frequency


def _write_minute_csv(data_dir: Path, symbol: str, frequency: str) -> Path:
    """写入模拟分钟线 CSV 文件用于测试。"""
    freq_dir = data_dir / frequency
    freq_dir.mkdir(parents=True, exist_ok=True)
    file_path = freq_dir / f"{symbol}.csv"
    file_path.write_text(
        "timestamp,open,high,low,close,volume,amount\n"
        "2024-01-02T09:31:00,10,10.1,9.9,10.05,500,5025\n"
        "2024-01-02T09:32:00,10.05,10.2,10.0,10.15,600,6090\n"
        "2024-01-02T09:33:00,10.15,10.3,10.1,10.25,700,7175\n",
        encoding="utf-8",
    )
    return file_path


def _write_daily_csv(data_dir: Path, symbol: str) -> Path:
    """写入模拟日线 CSV 文件用于测试。"""
    freq_dir = data_dir / "1d"
    freq_dir.mkdir(parents=True, exist_ok=True)
    file_path = freq_dir / f"{symbol}.csv"
    file_path.write_text(
        "timestamp,open,high,low,close,volume,amount\n"
        "2024-01-02T00:00:00,10,10,9,9,1000,9000\n"
        "2024-01-03T00:00:00,9,11,9,11,1100,12100\n"
        "2024-01-04T00:00:00,11,12,10,12,1200,14400\n",
        encoding="utf-8",
    )
    return file_path


# ---------------------------------------------------------------------------
# run_backtest with frequency parameter
# ---------------------------------------------------------------------------

class TestRunBacktestWithFrequency:
    """验证 run_backtest 的 frequency 参数正确传递给 RunContext。"""

    def test_default_frequency_is_daily(self, tmp_path: Path, monkeypatch) -> None:
        """默认频率应为日线 1d。"""
        _write_daily_csv(tmp_path, "000300.SH")
        monkeypatch.chdir(tmp_path)

        summary = run_backtest(data_path=str(tmp_path), symbol="000300.SH")
        assert summary.status == "completed"
        # 报告应含 frequency=1d
        report_path = tmp_path / "reports" / "backtest" / "backtest-trend_following-000300.SH.json"
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert payload["context"]["frequency"] == "1d"

    def test_minute_frequency_recorded_in_report(self, tmp_path: Path, monkeypatch) -> None:
        """分钟线频率应记录在回测报告中。"""
        _write_minute_csv(tmp_path, "000300.SH", "1m")
        monkeypatch.chdir(tmp_path)

        summary = run_backtest(
            data_path=str(tmp_path),
            symbol="000300.SH",
            frequency=Frequency.MIN_1,
        )
        assert summary.status == "completed"
        report_path = tmp_path / "reports" / "backtest" / "backtest-trend_following-000300.SH.json"
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert payload["context"]["frequency"] == "1m"


# ---------------------------------------------------------------------------
# run_minute_backtest
# ---------------------------------------------------------------------------

class TestRunMinuteBacktest:
    """验证分钟线回测入口 run_minute_backtest。"""

    @pytest.mark.parametrize("freq", ["1m", "5m", "15m", "30m", "60m"])
    def test_supported_frequencies(self, freq: str, tmp_path: Path, monkeypatch) -> None:
        """所有支持的分钟频率都应能正常进入回测流程并生成报告。"""
        _write_minute_csv(tmp_path, "000300.SH", freq)
        monkeypatch.chdir(tmp_path)

        summary = run_minute_backtest(
            data_path=str(tmp_path),
            symbol="000300.SH",
            frequency=freq,
        )
        assert summary.status == "completed"
        report_dir = tmp_path / "reports" / "backtest"
        assert report_dir.exists()
        # 验证报告中频率字段
        report_path = report_dir / "backtest-trend_following-000300.SH.json"
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert payload["context"]["frequency"] == freq

    def test_raises_value_error_for_unsupported_frequency(self, tmp_path: Path) -> None:
        """传入不支持的频率字符串时，应抛出 ValueError。"""
        with pytest.raises(ValueError, match="不支持的频率"):
            run_minute_backtest(
                data_path=str(tmp_path),
                symbol="000300.SH",
                frequency="99m",
            )

    def test_daily_frequency_falls_back_to_run_backtest(self, tmp_path: Path, monkeypatch) -> None:
        """传入 '1d' 时应等价于调用 run_backtest（日线）。"""
        _write_daily_csv(tmp_path, "000300.SH")
        monkeypatch.chdir(tmp_path)

        summary = run_minute_backtest(
            data_path=str(tmp_path),
            symbol="000300.SH",
            frequency="1d",
        )
        assert summary.status == "completed"
        report_path = tmp_path / "reports" / "backtest" / "backtest-trend_following-000300.SH.json"
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert payload["context"]["frequency"] == "1d"

    def test_report_contains_frequency_metadata(self, tmp_path: Path, monkeypatch) -> None:
        """回测报告的 context.metadata 中应含有 frequency 字段。"""
        _write_minute_csv(tmp_path, "000300.SH", "5m")
        monkeypatch.chdir(tmp_path)

        run_minute_backtest(
            data_path=str(tmp_path),
            symbol="000300.SH",
            frequency="5m",
        )
        report_path = tmp_path / "reports" / "backtest" / "backtest-trend_following-000300.SH.json"
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        # metadata 中也应含 frequency
        metadata = payload.get("context", {}).get("metadata", {})
        assert metadata.get("frequency") == "5m"
