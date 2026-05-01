from __future__ import annotations

from pathlib import Path

import json

from src.app.backtest_app import (
    run_backtest,
    run_oos_validation,
    run_parameter_robustness,
    run_portfolio_backtest,
    run_stage2_report,
    run_stress_test,
)
from src.domain.enums import Frequency


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
    report_path = report_dir / "backtest-trend_following-1d-000300.SH.json"
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert summary.status == "completed"
    assert report_path.exists()
    assert "report_path=" in summary.message
    assert "risk_summary" in report_payload
    assert "strategy_metadata" in report_payload
    assert "event_summary" in report_payload


def test_run_backtest_supports_intraday_frequency(tmp_path: Path, monkeypatch) -> None:
    """验证回测入口支持分钟线频率并正确写出报告。"""
    data_dir = tmp_path / "5m"
    data_dir.mkdir(parents=True, exist_ok=True)
    file_path = data_dir / "000300.SH.csv"
    file_path.write_text(
        "timestamp,open,high,low,close,volume,amount\n"
        "2024-01-02T09:35:00,10,10,9,9.5,1000,9500\n"
        "2024-01-02T09:40:00,9.5,10.2,9.4,10.1,1100,11110\n"
        "2024-01-02T09:45:00,10.1,10.5,10,10.4,1200,12480\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    summary = run_backtest(
        data_path=str(tmp_path),
        symbol="000300.SH",
        frequency=Frequency.MIN_5,
    )

    report_path = tmp_path / "reports" / "backtest" / "backtest-trend_following-5m-000300.SH.json"
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert summary.status == "completed"
    assert report_path.exists()
    assert report_payload["context"]["frequency"] == "5m"
    assert report_payload["event_summary"]["frequency"] == "5m"


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
    assert "failed_checks" in report_payload["risk_summary"]


def test_run_stage2_execution_flows(tmp_path: Path, monkeypatch) -> None:
    """验证阶段二真实执行入口能够返回压力测试、稳健性分析和组合回测结果。"""
    data_dir = tmp_path / "1d"
    data_dir.mkdir(parents=True, exist_ok=True)
    file_path = data_dir / "000300.SH.csv"
    file_path.write_text(
        "timestamp,open,high,low,close,volume,amount\n"
        "2018-01-02T00:00:00,10,10,9,9,1000,9000\n"
        "2018-06-01T00:00:00,9,10,8,8.5,1100,9350\n"
        "2020-03-01T00:00:00,8.5,9,7.5,7.8,1200,9360\n"
        "2020-10-01T00:00:00,7.8,8.5,7.7,8.3,1300,10790\n"
        "2024-01-02T00:00:00,8.3,9,8.1,8.9,1400,12460\n"
        "2024-06-01T00:00:00,8.9,9.4,8.8,9.2,1500,13800\n"
        "2024-12-01T00:00:00,9.2,9.8,9.1,9.6,1600,15360\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    stress_result = run_stress_test(data_path=str(tmp_path), symbol="000300.SH", strategy_name="trend_following")
    robustness_result = run_parameter_robustness(data_path=str(tmp_path), symbol="000300.SH", strategy_name="trend_following")
    portfolio_result = run_portfolio_backtest(data_path=str(tmp_path), symbol="000300.SH")
    stage2_result = run_stage2_report(data_path=str(tmp_path), symbol="000300.SH")

    assert "scenario_count" in stress_result
    assert "best_score" in robustness_result
    assert portfolio_result["strategy_count"] == "2"
    assert "report_path" in stage2_result
