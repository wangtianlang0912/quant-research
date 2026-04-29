from __future__ import annotations

from pathlib import Path

from src.app.backtest_app import run_backtest


def test_run_backtest_writes_json_report(tmp_path: Path, monkeypatch) -> None:
    """验证回测入口会生成可归档的JSON报告文件。"""
    data_dir = tmp_path / "1d"
    data_dir.mkdir(parents=True, exist_ok=True)
    file_path = data_dir / "000300.SH.csv"
    file_path.write_text(
        "timestamp,open,high,low,close,volume,amount\n"
        "2024-01-02T00:00:00,10,10,9,9,1000,9000\n"
        "2024-01-03T00:00:00,9,11,9,11,1100,12100\n"
        "2024-01-04T00:00:00,11,12,10,12,1200,14400\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    summary = run_backtest(data_path=str(tmp_path), symbol="000300.SH")

    report_dir = tmp_path / "reports" / "backtest"
    report_files = list(report_dir.glob("backtest-000300.SH.json"))
    assert summary.status == "completed"
    assert len(report_files) == 1
    assert "report_path=" in summary.message
