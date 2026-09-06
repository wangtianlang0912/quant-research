"""数据质量门禁执行器（T02.6 落地 / T02.7 CLI 后端）。

## 职责边界

```
domain/services/data_quality_rules.py   纯规则（7 项，无 I/O，全量单测）
quality_gate.py（本模块）               取数 + 派生指标 + 落盘 + P0 告警
cli/commands/data.py                    人机界面（qv2 data quality）
```

## 派生指标的计算口径（★ 全部显式，禁止静默兜底）

- `coverage`：当日分区标的数 / 期望清单。**期望清单由调用方给**
  （PIT 池 / 前一分区引导），没有基线本身就是 FAIL。
- `price_jump` / `adj_factor_continuity`：与 **as_of 之前最近的一个分区** 比。
  不用交易日历 —— 分区即事实：最近有数据的那个交易日才是环比基准。
- `consecutive_missing`：从 as_of 往回扫最多 `missing_lookback_partitions`
  个分区，数每只标的的**尾部连续缺席**。整个回看窗口都没出现过的标的
  按"缺席满窗口"计 —— 新上市股票会被这样计入（见 docstring 注意事项），
  期望清单来自 PIT 池时应按 `ipo_date` 预过滤。
- `staleness`：当日分区每只标的的最新日期（就是 as_of 本身）。
  分区整体缺失时 staleness 平凡通过 —— **那种情况由 coverage FAIL 兜住**，
  不需要两条规则重复报同一件事。

## 落盘（一次门禁 = 三个表）

1. `data_quality_reports`：完整报告 JSON（逐指标明细）。
2. `partition_fingerprints`：当日分区逻辑指纹（D-11 幂等登记）。
3. `alerts`：FAIL 时落 **P0**（D-10：门禁失败禁止静默）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from quant_v2.adapters.persistence.parquet_bar_store import ParquetBarStore
from quant_v2.adapters.persistence.sqlite_store import SqliteStore, utc_now_iso
from quant_v2.domain.models.bar import Bar
from quant_v2.domain.services.data_quality_rules import (
    DataQualityReport,
    RuleResult,
    RuleStatus,
    adj_factor_continuity,
    consecutive_missing,
    coverage,
    duplicate_rows,
    evaluate_all,
    price_anomaly,
    price_jump,
    staleness,
)

__all__ = [
    "QualityGateRunner",
    "QualityThresholds",
    "resolve_expected_symbols",
]


# ============================================================
# 阈值（配置注入，不埋魔数；A 股默认值，其它市场显式给表）
# ============================================================
@dataclass(frozen=True)
class QualityThresholds:
    """7 项规则的阈值。★ 全部可被配置覆盖 —— 这里只是 A 股默认。"""

    min_coverage_ratio: Decimal = Decimal("0.95")  # 低于即 FAIL（v1：3025→990 = 0.328）
    warn_coverage_ratio: Decimal = Decimal("0.98")
    max_consecutive_missing: int = 10
    # A 股 ±10% 涨跌停下，|环比| > 11% 基本是复权错或脏数据
    max_jump_pct: Decimal = Decimal("11")
    # 除权日 backAdjustFactor 大幅变化是合法的（10 送 10 → 因子翻倍 = 100%），
    # 只拦"复权链断裂"级的荒谬变化
    max_factor_change_pct: Decimal = Decimal("300")
    max_lag_days: int = 3
    # 连续缺席的回看窗口（分区数）
    missing_lookback_partitions: int = 30


# ============================================================
# 期望清单解析（CLI / 编排层调用）
# ============================================================
def resolve_expected_symbols(
    *,
    store: SqliteStore,
    bar_store: ParquetBarStore,
    market: str,
    as_of: date,
    expected_file: Path | None = None,
) -> list[str]:
    """解析"期望标的清单"，优先级从高到低：

    1. 显式文件（一行一个代码）；
    2. PIT 池中 as_of 之前**最近一次**快照（T02.5 建池后生效）；
    3. as_of 之前最近一个分区的标的集（bootstrap：昨日全量 = 今日基线）；
    4. 都没有 → FileNotFoundError（**没有基线就不是"跳过检查"，
       是不知道该检查什么 —— 宁可炸**）。
    """
    if expected_file is not None:
        path = expected_file
        lines = [
            ln.strip()
            for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        if not lines:
            raise FileNotFoundError(f"期望清单文件为空：{path}")
        return sorted(set(lines))

    row = store.conn.execute(
        "SELECT as_of FROM pit_universe WHERE as_of <= ? ORDER BY as_of DESC LIMIT 1",
        (as_of.isoformat(),),
    ).fetchone()
    if row is not None:
        symbols = [
            r["symbol"]
            for r in store.conn.execute(
                "SELECT symbol FROM pit_universe WHERE as_of = ?", (row["as_of"],)
            )
        ]
        if symbols:
            return sorted(set(symbols))

    prior = [d for d in bar_store.partition_dates(market) if d < as_of]
    if prior:
        bars = bar_store.load_partition(market, prior[-1])
        symbols = sorted({b.symbol for b in bars})
        if symbols:
            return symbols

    raise FileNotFoundError(
        f"无法确定 {market} @ {as_of} 的期望标的清单："
        "PIT 池为空且没有更早的分区可做基线。"
        "先建池（qv2 data build-universe）或同步前一交易日，或用 --expected-file 显式给出。"
    )


# ============================================================
# 派生指标
# ============================================================
def _jump_pct(bars_day: list[Bar], bars_prev: list[Bar]) -> dict[str, Decimal]:
    """|收盘价环比| %（同标的两日都在且前收 > 0）。"""
    prev_close = {b.symbol: b.close for b in bars_prev if b.close > 0}
    out: dict[str, Decimal] = {}
    for b in bars_day:
        pc = prev_close.get(b.symbol)
        if pc is not None and pc > 0 and b.close > 0:
            out[b.symbol] = abs(b.close / pc - Decimal(1)) * Decimal(100)
    return out


def _factor_change_pct(bars_day: list[Bar], bars_prev: list[Bar]) -> dict[str, Decimal]:
    """|复权因子环比| %。"""
    prev_f = {b.symbol: b.adj_factor for b in bars_prev if b.adj_factor > 0}
    out: dict[str, Decimal] = {}
    for b in bars_day:
        pf = prev_f.get(b.symbol)
        if pf is not None and pf > 0 and b.adj_factor > 0:
            out[b.symbol] = abs(b.adj_factor / pf - Decimal(1)) * Decimal(100)
    return out


def _consecutive_missing(
    *,
    expected_symbols: list[str],
    bars_by_date: list[tuple[date, set[str]]],  # [(分区日, 当日标的集)]，按日期降序
) -> dict[str, int]:
    """每只期望标的的尾部连续缺席分区数。

    回看窗口内从未出现 → 记满窗口数（新上市股票会被计入，见模块 docstring）。
    """
    window = [symbols for _, symbols in bars_by_date]
    out: dict[str, int] = {}
    for symbol in expected_symbols:
        n = 0
        for present in window:
            if symbol in present:
                break
            n += 1
        if n > 0:
            out[symbol] = n
    return out


# ============================================================
# 门禁执行器
# ============================================================
class QualityGateRunner:
    """取数 → 派生 → 7 项规则 → 落盘（报告 / 指纹 / P0 告警）。"""

    def __init__(
        self,
        *,
        bar_store: ParquetBarStore,
        store: SqliteStore,
        thresholds: QualityThresholds | None = None,
    ) -> None:
        self._bars = bar_store
        self._store = store
        self._th = thresholds or QualityThresholds()

    def run(
        self,
        *,
        market: str,
        as_of: date,
        expected_symbols: list[str],
    ) -> DataQualityReport:
        """执行门禁。**FAIL 不在这里抛** —— 返回报告，由调用方（CLI/编排）
        决定渲染与退出码；本方法负责落盘与 P0 告警（副作用不依赖调用方自觉）。
        """
        th = self._th
        bars_day = self._bars.load_partition(market, as_of)

        prior_dates = [d for d in self._bars.partition_dates(market) if d < as_of]
        prior_day = prior_dates[-1] if prior_dates else None
        bars_prev = self._bars.load_partition(market, prior_day) if prior_day else []

        # 回看窗口：as_of（若有分区）+ 之前最多 lookback 个分区，按日期降序
        lookback_dates = prior_dates[-th.missing_lookback_partitions :]
        window: list[tuple[date, set[str]]] = [
            (d, {b.symbol for b in self._bars.load_partition(market, d)})
            for d in reversed(lookback_dates)
        ]
        if bars_day or self._bars.partition_path(market, as_of).exists():
            window.insert(0, (as_of, {b.symbol for b in bars_day}))

        results: list[RuleResult] = [
            coverage(
                bars_day,
                expected_symbols=expected_symbols,
                min_ratio=th.min_coverage_ratio,
                warn_ratio=th.warn_coverage_ratio,
            ),
            consecutive_missing(
                missing_by_symbol=_consecutive_missing(
                    expected_symbols=expected_symbols, bars_by_date=window
                ),
                max_consecutive=th.max_consecutive_missing,
            ),
            price_jump(
                jump_pct_by_symbol=_jump_pct(bars_day, bars_prev), max_jump_pct=th.max_jump_pct
            ),
            adj_factor_continuity(
                factor_change_pct_by_symbol=_factor_change_pct(bars_day, bars_prev),
                max_change_pct=th.max_factor_change_pct,
            ),
            price_anomaly(bars_day),
            duplicate_rows(bars_day),
            staleness(
                latest_date_by_symbol={b.symbol: b.date for b in bars_day},
                as_of=as_of,
                max_lag_days=th.max_lag_days,
            ),
        ]
        report = evaluate_all(results, market=market, as_of=as_of)
        self._persist(report=report, market=market, as_of=as_of, bars_day=bars_day)
        return report

    # ----------------------------------------------------------
    # 落盘
    # ----------------------------------------------------------
    def _persist(
        self,
        *,
        report: DataQualityReport,
        market: str,
        as_of: date,
        bars_day: list[Bar],
    ) -> None:
        payload = json.dumps(report.to_payload(), ensure_ascii=False)
        with self._store.conn:
            self._store.conn.execute(
                "INSERT INTO data_quality_reports(market, as_of, checked_at, status, report) "
                "VALUES(?, ?, ?, ?, ?)",
                (
                    market,
                    as_of.isoformat(),
                    report.checked_at.isoformat(),
                    report.status.value,
                    payload,
                ),
            )

        fingerprint: str | None = None
        if bars_day:
            fingerprint = self._bars.fingerprint_of(market, as_of)
            with self._store.conn:
                self._store.conn.execute(
                    "INSERT OR REPLACE INTO partition_fingerprints"
                    "(market, dt, fingerprint, computed_at) VALUES(?, ?, ?, ?)",
                    (market, as_of.isoformat(), fingerprint, utc_now_iso()),
                )

        if report.status is RuleStatus.FAIL:
            failed = "；".join(f"[{r.rule_id}] {r.detail}" for r in report.failed_rules())
            self._store.record_alert(
                level="P0",
                source="data_quality_gate",
                message=f"数据质量门禁 FAIL（{market} @ {as_of}）：{failed}",
                payload=payload,
            )
