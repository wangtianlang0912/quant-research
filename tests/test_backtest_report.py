from __future__ import annotations

from pathlib import Path

import json

from src.app.backtest_app import run_backtest, run_oos_validation


def test_run_backtest_writes_json_report(tmp_path: Path, monkeypatch) -> None:
    """验证回测入口会生成包含风控和策略摘要的JSON报告文件。"""
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
    report_path = report_dir / "backtest-trend_following-000300.SH.json"
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert summary.status == "completed"
    assert report_path.exists()
    assert "report_path=" in summary.message
    assert "risk_summary" in report_payload
    assert "strategy_metadata" in report_payload
    assert "event_summary" in report_payload


def test_run_oos_validation_writes_report(tmp_path: Path, monkeypatch) -> None:
    """验证OOS验证入口会生成最小验证报告。"""
    data_dir = tmp_path / "1d"
    data_dir.mkdir(parents=True, exist_ok=True)
    file_path = data_dir / "000300.SH.csv"
    file_path.write_text(
        "timestamp,open,high,low,close,volume,amount\n"
        "2024-01-02T00:00:00,10,10,9,9,1000,9000\n"
        "2024-03-01T00:00:00,9,11,9,11,1100,12100\n"
        "2024-06-01T00:00:00,11,12,10,12,1200,14400\n"
        "2024-10-01T00:00:00,12,13,11,12.5,1300,16250\n"
        "2024-12-01T00:00:00,12.5,13.5,12,13,1400,18200\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = run_oos_validation(data_path=str(tmp_path), symbol="000300.SH", strategy_name="mean_reversion")

    report_path = tmp_path / "reports" / "oos" / "oos-oos-mean_reversion-000300.SH.json"
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_path.exists()
    assert "summary" in result
    assert "validation_score" in report_payload["risk_summary"]
