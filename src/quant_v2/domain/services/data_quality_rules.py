"""数据质量门禁规则（T02.6，纯逻辑，无 I/O）。

## 7 项指标（逐一落盘）

| # | 规则 | 检什么 | 失败含义 |
|---|---|---|---|
| 1 | `coverage` | 当日分区标的数 / 预期标的数 | 覆盖暴跌 = 数据源抽风（v1 实证：3025 → 990） |
| 2 | `consecutive_missing` | 标的连续缺失交易日数 | 停牌 vs 数据丢失必须区分 |
| 3 | `price_jump` | 收盘价环比跳变幅度 | 异常跳变 = 复权错或脏数据 |
| 4 | `adj_factor_continuity` | 因子单日跳变幅度 | 因子断层 = 复权链断裂（M-5 类问题） |
| 5 | `price_anomaly` | OHLC 自洽 / 非正价格 | 源端脏行 |
| 6 | `duplicate_rows` | (symbol, date) 重复 | 写入不幂等的直接证据 |
| 7 | `staleness` | 最新数据日期距 as_of 的滞后 | 任务"成功"但数据是旧的 |

## 铁律

- **FAIL 必须中止信号生成并 P0 告警**（`require_pass` 抛 `DataQualityGateError`）。
  v1 实证缺陷：覆盖数从 3025 掉到 990，任务照常 completed，
  策略在 1/3 的股票池上跑出了"正常"结果 —— 静默失败最贵。
- **规则全部纯函数**：输入是已取出的数据，输出是 `RuleResult`。
  取数是适配层的职责，规则不碰 I/O 才能全量单测。
- 阈值全部显式参数化（配置注入），不埋魔数。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from quant_v2.domain.errors import DataQualityGateError
from quant_v2.domain.models.bar import Bar

__all__ = [
    "DataQualityReport",
    "RuleResult",
    "RuleStatus",
    "adj_factor_continuity",
    "consecutive_missing",
    "coverage",
    "duplicate_rows",
    "evaluate_all",
    "price_anomaly",
    "price_jump",
    "require_pass",
    "staleness",
]


class RuleStatus(str, Enum):
    """PASS < WARN < FAIL。"""

    PASS = "PASS"  # noqa: S105 -- 枚举值，不是密码
    WARN = "WARN"
    FAIL = "FAIL"


_SEVERITY_ORDER = {RuleStatus.PASS: 0, RuleStatus.WARN: 1, RuleStatus.FAIL: 2}


@dataclass(frozen=True)
class RuleResult:
    """单条规则的结果。"""

    rule_id: str
    status: RuleStatus
    detail: str  # 人话（直接进报告）
    metrics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DataQualityReport:
    """一次门禁执行的完整结果（落 `data_quality_reports.report` 的形态）。"""

    market: str
    as_of: date
    checked_at: datetime
    results: tuple[RuleResult, ...]

    @property
    def status(self) -> RuleStatus:
        """整体状态 = 最差的那条。"""
        return max((r.status for r in self.results), key=lambda s: _SEVERITY_ORDER[s])

    def failed_rules(self) -> tuple[RuleResult, ...]:
        return tuple(r for r in self.results if r.status is RuleStatus.FAIL)

    def to_payload(self) -> dict[str, Any]:
        """JSON 可序列化形态（SQLite 落盘）。"""
        return {
            "market": self.market,
            "as_of": self.as_of.isoformat(),
            "checked_at": self.checked_at.isoformat(),
            "status": self.status.value,
            "rules": [
                {
                    "rule_id": r.rule_id,
                    "status": r.status.value,
                    "detail": r.detail,
                    "metrics": dict(r.metrics),
                }
                for r in self.results
            ],
        }


# ============================================================
# 规则 1：覆盖率
# ============================================================
def coverage(
    bars_of_day: Sequence[Bar],
    *,
    expected_symbols: Sequence[str],
    min_ratio: Decimal,
    warn_ratio: Decimal | None = None,
) -> RuleResult:
    """当日分区标的覆盖数 / 预期标的数。

    ★ v1 实证缺陷的直接回归：覆盖数从 3025 掉到 990（32.8%）
    在 v1 里静默通过；这里 min_ratio 低于即 FAIL。
    """
    expected = len(set(expected_symbols))
    actual = len({bar.symbol for bar in bars_of_day})
    if expected == 0:
        return RuleResult(
            rule_id="coverage",
            status=RuleStatus.FAIL,
            detail="预期标的清单为空：没有基线就无法判断覆盖暴跌，视为门禁失败",
            metrics={"expected": 0, "actual": actual},
        )
    ratio = Decimal(actual) / Decimal(expected)
    status = RuleStatus.PASS
    if ratio < min_ratio:
        status = RuleStatus.FAIL
    elif warn_ratio is not None and ratio < warn_ratio:
        status = RuleStatus.WARN
    return RuleResult(
        rule_id="coverage",
        status=status,
        detail=f"覆盖 {actual}/{expected} = {ratio:.1%}",
        metrics={"expected": expected, "actual": actual, "ratio": str(ratio)},
    )


# ============================================================
# 规则 2：连续缺失
# ============================================================
def consecutive_missing(
    *,
    missing_by_symbol: Mapping[str, int],
    max_consecutive: int,
) -> RuleResult:
    """各标的的连续缺失交易日数（由调用方按日历算好，规则只判阈值）。

    连续缺失与"停牌"的区别由调用方负责（停牌标的不应进 missing 统计）。
    """
    worst_symbol = ""
    worst = 0
    for symbol, n in missing_by_symbol.items():
        if n > worst:
            worst, worst_symbol = n, symbol
    status = RuleStatus.PASS if worst <= max_consecutive else RuleStatus.FAIL
    detail = f"最大连续缺失 {worst} 天（{worst_symbol or '无'}），上限 {max_consecutive}"
    return RuleResult(
        rule_id="consecutive_missing",
        status=status,
        detail=detail,
        metrics={"max_consecutive": worst, "worst_symbol": worst_symbol},
    )


# ============================================================
# 规则 3：环比跳变
# ============================================================
def price_jump(
    *,
    jump_pct_by_symbol: Mapping[str, Decimal],
    max_jump_pct: Decimal,
) -> RuleResult:
    """收盘价环比跳变幅度（调用方给出 |Δ%|，规则只判阈值）。

    A 股 ±10% 涨跌停下，|跳变| > 11% 基本可断定复权错或脏数据
    （阈值可配置：无涨跌停市场放宽）。
    """
    offenders = {s: p for s, p in jump_pct_by_symbol.items() if p > max_jump_pct}
    status = RuleStatus.FAIL if offenders else RuleStatus.PASS
    if offenders:
        worst = max(offenders.items(), key=lambda kv: kv[1])
        detail = f"{len(offenders)} 只标的环比跳变超限，最差 {worst[0]} = {worst[1]:.2f}%"
    else:
        detail = f"全部 {len(jump_pct_by_symbol)} 只标的环比跳变在 {max_jump_pct}% 以内"
    return RuleResult(
        rule_id="price_jump",
        status=status,
        detail=detail,
        metrics={"offenders": len(offenders), "max_jump_pct": str(max_jump_pct)},
    )


# ============================================================
# 规则 4：复权连续性
# ============================================================
def adj_factor_continuity(
    *,
    factor_change_pct_by_symbol: Mapping[str, Decimal],
    max_change_pct: Decimal,
) -> RuleResult:
    """adj_factor 单日变化幅度（|Δ%|）。因子链断裂会让全部历史价格错位。"""
    offenders = {s: p for s, p in factor_change_pct_by_symbol.items() if p > max_change_pct}
    status = RuleStatus.FAIL if offenders else RuleStatus.PASS
    detail = (
        f"{len(offenders)} 只标的复权因子单日变化超 {max_change_pct}%（除权日外不该发生）"
        if offenders
        else f"复权因子连续性正常（{len(factor_change_pct_by_symbol)} 只标的）"
    )
    return RuleResult(
        rule_id="adj_factor_continuity",
        status=status,
        detail=detail,
        metrics={"offenders": len(offenders)},
    )


# ============================================================
# 规则 5：价格异常
# ============================================================
def price_anomaly(bars: Sequence[Bar]) -> RuleResult:
    """非正价格 / high < low / 零成交但有价格跳动等脏行。

    OHLC 自洽性已在 `Bar` 构造期校验（活跃 bar），
    这里补的是"停牌平铺行混入异常值"与"零/负价格"。
    """
    bad: list[str] = []
    for bar in bars:
        if bar.open <= 0 or bar.high <= 0 or bar.low <= 0 or bar.close <= 0:
            bad.append(f"{bar.symbol}@{bar.date}: 非正价格")
        elif bar.high < bar.low:
            bad.append(f"{bar.symbol}@{bar.date}: high < low")
        elif bar.is_suspended and bar.volume > 0:
            bad.append(f"{bar.symbol}@{bar.date}: 停牌却有成交量")
    status = RuleStatus.FAIL if bad else RuleStatus.PASS
    detail = f"{len(bad)} 行价格异常" if bad else f"{len(bars)} 行价格正常"
    return RuleResult(
        rule_id="price_anomaly",
        status=status,
        detail=detail,
        metrics={"bad_rows": len(bad), "sample": bad[:5]},
    )


# ============================================================
# 规则 6：重复行
# ============================================================
def duplicate_rows(bars: Sequence[Bar]) -> RuleResult:
    """同 (symbol, date) 重复 —— 写入不幂等的直接证据（D-11 反向守卫）。"""
    seen: set[tuple[str, date]] = set()
    dups: list[str] = []
    for bar in bars:
        key = (bar.symbol, bar.date)
        if key in seen:
            dups.append(f"{bar.symbol}@{bar.date}")
        seen.add(key)
    status = RuleStatus.FAIL if dups else RuleStatus.PASS
    detail = f"{len(dups)} 行重复" if dups else "无重复行"
    return RuleResult(
        rule_id="duplicate_rows",
        status=status,
        detail=detail,
        metrics={"duplicates": len(dups), "sample": dups[:5]},
    )


# ============================================================
# 规则 7：陈旧
# ============================================================
def staleness(
    *,
    latest_date_by_symbol: Mapping[str, date],
    as_of: date,
    max_lag_days: int,
) -> RuleResult:
    """标的最新数据日期距 as_of 的自然日滞后。"""
    stale = {
        s: (as_of - d).days
        for s, d in latest_date_by_symbol.items()
        if (as_of - d).days > max_lag_days
    }
    status = RuleStatus.FAIL if stale else RuleStatus.PASS
    if stale:
        worst = max(stale.items(), key=lambda kv: kv[1])
        detail = f"{len(stale)} 只标的数据滞后超 {max_lag_days} 天，最差 {worst[0]} = {worst[1]} 天"
    else:
        detail = (
            f"数据新鲜度正常（{len(latest_date_by_symbol)} 只标的，滞后上限 {max_lag_days} 天）"
        )
    return RuleResult(
        rule_id="staleness",
        status=status,
        detail=detail,
        metrics={"stale": len(stale)},
    )


# ============================================================
# 聚合与门禁
# ============================================================
def evaluate_all(
    results: Sequence[RuleResult],
    *,
    market: str,
    as_of: date,
    checked_at: datetime | None = None,
) -> DataQualityReport:
    """聚合为报告。不做任何"取不到就跳过"—— 调用方必须给出全部 7 项。"""
    rule_ids = {r.rule_id for r in results}
    required = {
        "coverage",
        "consecutive_missing",
        "price_jump",
        "adj_factor_continuity",
        "price_anomaly",
        "duplicate_rows",
        "staleness",
    }
    missing_rules = required - rule_ids
    if missing_rules:
        raise DataQualityGateError(
            f"门禁规则不完整：缺 {sorted(missing_rules)}。少一条规则 = 门禁有洞，宁可在这里炸。"
        )
    return DataQualityReport(
        market=market,
        as_of=as_of,
        checked_at=checked_at or datetime.now(UTC),
        results=tuple(results),
    )


def require_pass(report: DataQualityReport) -> None:
    """★ FAIL 必须中止：抛 `DataQualityGateError`，调用方捕获后 P0 告警 + 退出非零。

    **不提供"降级继续跑"的选项** —— v1 的教训是任何可以忽略的门禁
    迟早会被忽略。
    """
    failed = report.failed_rules()
    if failed:
        summary = "；".join(f"[{r.rule_id}] {r.detail}" for r in failed)
        raise DataQualityGateError(
            f"数据质量门禁 FAIL（{report.market} @ {report.as_of}）：{summary}。"
            "信号生成已中止 —— 这是设计行为，不是故障。"
        )
