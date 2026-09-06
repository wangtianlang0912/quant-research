"""数据质量门禁测试（T02.6）。

★ 核心回归：v1 实证缺陷"覆盖数从 3025 掉到 990 时任务照常 completed"
—— 本文件用同规模样本注入，门禁必须 FAIL 且 `require_pass` 抛错。
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from tests.conftest import FIXED_AS_OF, make_bar

from quant_v2.domain.errors import DataQualityGateError
from quant_v2.domain.services.data_quality_rules import (
    RuleResult,
    RuleStatus,
    adj_factor_continuity,
    consecutive_missing,
    coverage,
    duplicate_rows,
    evaluate_all,
    price_anomaly,
    price_jump,
    require_pass,
    staleness,
)

pytestmark = pytest.mark.unit

DAY = date(2026, 1, 5)
DAY_PREV = date(2026, 1, 2)


def d(value: str) -> Decimal:
    return Decimal(value)


def full_report() -> list[RuleResult]:
    """构造一份全 PASS 的 7 项结果（单项覆盖测试在其上做替换）。"""

    def ok(rule_id: str) -> RuleResult:
        return RuleResult(rule_id=rule_id, status=RuleStatus.PASS, detail="ok")

    return [
        ok(r)
        for r in (
            "coverage",
            "consecutive_missing",
            "price_jump",
            "adj_factor_continuity",
            "price_anomaly",
            "duplicate_rows",
            "staleness",
        )
    ]


class Test覆盖率:
    def test_覆盖暴跌必须FAIL(self) -> None:
        """★ v1 实证回归：3025 只 → 990 只（32.8%）静默通过的事故。"""
        expected = [f"{i:06d}.SH" for i in range(3025)]
        bars = []
        for i in range(990):  # 只有 990 只有数据
            bars.append(make_bar(symbol=f"{i:06d}.SH", day=DAY, close="10"))
        result = coverage(bars, expected_symbols=expected, min_ratio=d("0.95"))
        assert result.status is RuleStatus.FAIL
        assert result.metrics["actual"] == 990
        assert result.metrics["expected"] == 3025

    def test_正常覆盖PASS(self) -> None:
        expected = [f"{i:06d}.SH" for i in range(100)]
        bars = [make_bar(symbol=s, day=DAY, close="10") for s in expected[:99]]
        result = coverage(bars, expected_symbols=expected, min_ratio=d("0.95"))
        assert result.status is RuleStatus.PASS

    def test_预警区间WARN(self) -> None:
        expected = [f"{i:06d}.SH" for i in range(100)]
        bars = [make_bar(symbol=s, day=DAY, close="10") for s in expected[:96]]
        result = coverage(
            bars, expected_symbols=expected, min_ratio=d("0.95"), warn_ratio=d("0.99")
        )
        assert result.status is RuleStatus.WARN

    def test_基线为空即FAIL(self) -> None:
        """没有基线就没有门禁：宁可 FAIL 不放行。"""
        result = coverage([], expected_symbols=[], min_ratio=d("0.95"))
        assert result.status is RuleStatus.FAIL


class Test连续缺失:
    def test_超限FAIL(self) -> None:
        result = consecutive_missing(
            missing_by_symbol={"600001.SH": 3, "600002.SH": 7}, max_consecutive=5
        )
        assert result.status is RuleStatus.FAIL
        assert result.metrics["max_consecutive"] == 7

    def test_全部达标PASS(self) -> None:
        result = consecutive_missing(missing_by_symbol={"600001.SH": 2}, max_consecutive=5)
        assert result.status is RuleStatus.PASS


class Test环比跳变:
    def test_涨跌停外跳变FAIL(self) -> None:
        """A 股 ±10% 限制下 15% 的环比跳变 = 复权错或脏数据。"""
        result = price_jump(
            jump_pct_by_symbol={"600001.SH": d("15.2"), "600002.SH": d("3")},
            max_jump_pct=d("11"),
        )
        assert result.status is RuleStatus.FAIL

    def test_正常波动PASS(self) -> None:
        result = price_jump(
            jump_pct_by_symbol={"600001.SH": d("9.8"), "600002.SH": d("-9.9")},
            max_jump_pct=d("11"),
        )
        assert result.status is RuleStatus.PASS


class Test复权连续性:
    def test_因子断裂FAIL(self) -> None:
        result = adj_factor_continuity(
            factor_change_pct_by_symbol={"600519.SH": d("3.2")},
            max_change_pct=d("0.5"),
        )
        assert result.status is RuleStatus.FAIL

    def test_因子平稳PASS(self) -> None:
        result = adj_factor_continuity(
            factor_change_pct_by_symbol={"600519.SH": d("0")},
            max_change_pct=d("0.5"),
        )
        assert result.status is RuleStatus.PASS


class Test价格异常:
    def test_非正价格FAIL(self) -> None:
        bar = make_bar(symbol="600001.SH", day=DAY, close="0")
        result = price_anomaly([bar])
        assert result.status is RuleStatus.FAIL

    def test_停牌却有成交量FAIL(self) -> None:
        bar = make_bar(symbol="600001.SH", day=DAY, close="10", is_suspended=True)
        result = price_anomaly([bar])
        assert result.status is RuleStatus.FAIL

    def test_正常行PASS(self) -> None:
        bar = make_bar(symbol="600001.SH", day=DAY, close="10")
        result = price_anomaly([bar])
        assert result.status is RuleStatus.PASS

    def test_停牌零成交平铺行PASS(self) -> None:
        """停牌日的正常平铺行（volume=0）不能被误报。"""
        bar = make_bar(symbol="600001.SH", day=DAY, close="10", is_suspended=True, volume="0")
        result = price_anomaly([bar])
        assert result.status is RuleStatus.PASS


class Test重复行:
    def test_重复FAIL(self) -> None:
        bar = make_bar(symbol="600001.SH", day=DAY, close="10")
        result = duplicate_rows([bar, bar])
        assert result.status is RuleStatus.FAIL

    def test_无重复PASS(self) -> None:
        bars = [
            make_bar(symbol="600001.SH", day=DAY, close="10"),
            make_bar(symbol="600001.SH", day=DAY_PREV, close="9.9"),
        ]
        result = duplicate_rows(bars)
        assert result.status is RuleStatus.PASS


class Test陈旧:
    def test_数据滞后FAIL(self) -> None:
        result = staleness(
            latest_date_by_symbol={"600001.SH": DAY - __import__("datetime").timedelta(days=10)},
            as_of=DAY,
            max_lag_days=3,
        )
        assert result.status is RuleStatus.FAIL

    def test_新鲜PASS(self) -> None:
        result = staleness(latest_date_by_symbol={"600001.SH": DAY_PREV}, as_of=DAY, max_lag_days=3)
        assert result.status is RuleStatus.PASS


class Test聚合与门禁:
    def test_缺规则即抛错(self) -> None:
        """★ 少一条规则 = 门禁有洞。宁可炸。"""
        results = [RuleResult(rule_id="coverage", status=RuleStatus.PASS, detail="ok")]
        with pytest.raises(DataQualityGateError, match="门禁规则不完整"):
            evaluate_all(results, market="cn_a", as_of=DAY)

    def test_整体状态取最差(self) -> None:
        report = evaluate_all(
            [
                *full_report()[:6],
                RuleResult(rule_id="staleness", status=RuleStatus.WARN, detail="w"),
            ],
            market="cn_a",
            as_of=DAY,
        )
        assert report.status is RuleStatus.WARN

    def test_FAIL必须中止(self) -> None:
        """★ 门禁 FAIL → require_pass 抛错，调用方中止信号生成 + P0。"""
        results = list(full_report())
        results[0] = RuleResult(
            rule_id="coverage", status=RuleStatus.FAIL, detail="覆盖 990/3025 = 32.7%"
        )
        report = evaluate_all(results, market="cn_a", as_of=DAY)
        with pytest.raises(DataQualityGateError, match="信号生成已中止"):
            require_pass(report)

    def test_全PASS放行(self) -> None:
        report = evaluate_all(full_report(), market="cn_a", as_of=DAY)
        require_pass(report)  # 不抛即通过

    def test_报告可JSON序列化(self) -> None:
        report = evaluate_all(full_report(), market="cn_a", as_of=DAY, checked_at=FIXED_AS_OF)
        payload = json.dumps(report.to_payload(), ensure_ascii=False, default=str)
        assert "coverage" in payload
        assert payload.count('"PASS"') >= 7

    def test_checked_at默认UTC(self) -> None:
        report = evaluate_all(full_report(), market="cn_a", as_of=DAY)
        assert report.checked_at.tzinfo is not None
        assert isinstance(report.checked_at, datetime)
        assert report.checked_at.tzinfo == UTC


class Test端到端注入回归:
    """★ v1 事故复盘：模拟"任务成功但覆盖掉到 1/3"的完整门禁链路。"""

    def test_覆盖暴跌样本_门禁FAIL_信号生成中止(self) -> None:
        expected = [f"{i:06d}.SH" for i in range(3025)]
        bars_today = [make_bar(symbol=f"{i:06d}.SH", day=DAY, close="10") for i in range(990)]

        cov = coverage(bars_today, expected_symbols=expected, min_ratio=d("0.95"))
        report = evaluate_all(
            [
                cov,
                consecutive_missing(missing_by_symbol={}, max_consecutive=5),
                price_jump(jump_pct_by_symbol={}, max_jump_pct=d("11")),
                adj_factor_continuity(factor_change_pct_by_symbol={}, max_change_pct=d("0.5")),
                price_anomaly(bars_today),
                duplicate_rows(bars_today),
                staleness(
                    latest_date_by_symbol={b.symbol: DAY for b in bars_today},
                    as_of=DAY,
                    max_lag_days=3,
                ),
            ],
            market="cn_a",
            as_of=DAY,
        )
        assert report.status is RuleStatus.FAIL
        assert [r.rule_id for r in report.failed_rules()] == ["coverage"]
        with pytest.raises(DataQualityGateError, match="990/3025"):
            require_pass(report)
