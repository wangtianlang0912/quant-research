from __future__ import annotations

import json

from src.app.backtest_app import run_backtest
from src.app.paper_app import run_paper


def test_run_backtest_and_paper_use_distinct_modes(tmp_path, monkeypatch) -> None:
    """验证回测和纸盘入口能够返回不同模式的运行摘要。"""
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

    backtest_summary = run_backtest(data_path=str(tmp_path), symbol="000300.SH")
    paper_summary = run_paper(data_path=str(tmp_path), symbol="000300.SH")

    assert backtest_summary.mode.value == "backtest"
    assert paper_summary.mode.value == "paper"


def test_run_paper_writes_report_and_records_execution(tmp_path, monkeypatch) -> None:
    """验证纸盘入口会生成报告、净值日志、持仓日志和阶段性绩效报告。"""
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

    paper_summary = run_paper(data_path=str(tmp_path), symbol="000300.SH", strategy_name="mean_reversion")

    report_path = tmp_path / "reports" / "paper" / "paper-mean_reversion-000300.SH.json"
    equity_log_path = tmp_path / "reports" / "paper" / "logs" / "paper-mean_reversion-000300.SH-equity.csv"
    position_log_path = tmp_path / "reports" / "paper" / "logs" / "paper-mean_reversion-000300.SH-positions.csv"
    performance_report_path = tmp_path / "reports" / "paper" / "performance" / "performance-paper-mean_reversion-000300.SH.json"
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert paper_summary.mode.value == "paper"
    assert report_path.exists()
    assert equity_log_path.exists()
    assert position_log_path.exists()
    assert performance_report_path.exists()
    assert "event_summary" in report_payload
    assert "paper_order_report_count" in report_payload["event_summary"]
    assert "equity_log_path" in report_payload["event_summary"]
    assert "position_log_path" in report_payload["event_summary"]
    assert "performance_report_path" in report_payload["event_summary"]
