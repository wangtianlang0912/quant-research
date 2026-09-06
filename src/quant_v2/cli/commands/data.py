"""qv2 data —— 数据同步 / 质量门禁 / 指纹 / PIT 建池（T02.5 / T02.7）。

## 退出码约定（★ 非静默成功是 T02 的验收标准）

- 0：成功（PASS / WARN）；
- 2：数据质量门禁 FAIL（已落 P0 告警 + 报告，`&&` 链在此断开）；
- 1：操作失败（分区缺失 / 无期望基线 / 配置错误等）。
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from quant_v2.adapters.clock.market_profile_loader import load_market_profile
from quant_v2.adapters.clock.trading_calendar import (
    ProfileTradingCalendar,
    StaticCalendarSeed,
    load_calendar_overrides,
)
from quant_v2.adapters.data_sources.pit_universe_provider import (
    BaostockPitUniverseProvider,
    default_all_stock_fetcher,
)
from quant_v2.adapters.market_data.akshare_cn import AkshareCnAdapter
from quant_v2.adapters.market_data.baostock_cn import BaostockCnAdapter
from quant_v2.adapters.market_data.resilient_source import ResilientSource
from quant_v2.adapters.market_data.subprocess_worker import (
    SubprocessWorker,
    WorkerCall,
    WorkerResult,
)
from quant_v2.adapters.market_data.tencent_fallback import TencentAdapter
from quant_v2.adapters.persistence.parquet_bar_store import ParquetBarStore
from quant_v2.adapters.persistence.quality_gate import (
    QualityGateRunner,
    resolve_expected_symbols,
)
from quant_v2.adapters.persistence.repositories import (
    SqlitePitUniverseRepository,
)
from quant_v2.adapters.persistence.sqlite_store import SqliteStore, utc_now_iso
from quant_v2.domain.errors import (
    DataQualityGateError,
    FingerprintError,
    NotTradingDayError,
    QuantV2Error,
    SourceUnavailableError,
)
from quant_v2.domain.models.bar import AdjustType
from quant_v2.domain.ports.market_data_port import BarRequest
from quant_v2.domain.services.data_quality_rules import RuleStatus
from quant_v2.domain.services.pit_universe import (
    PIT_EARLIEST_DATE,
    NameChangeKind,
    diff_snapshots,
    event_fill_dates,
    sample_dates,
)

app = typer.Typer(help="数据同步 / 质量门禁 / 指纹 / PIT 建池", no_args_is_help=True)
console = Console()


def _parse_as_of(value: str) -> date:
    """解析 YYYY-MM-DD（给清晰报错，不抛 argparse 味的堆栈）。"""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(f"as_of 必须是 YYYY-MM-DD，收到 {value!r}") from exc


def _open_store(db: Path) -> SqliteStore:
    """打开 SQLite（var/ 目录由 CLI 显式创建 —— 这是操作员明确指定的数据目录）。"""
    db.parent.mkdir(parents=True, exist_ok=True)
    return SqliteStore(db)


# ============================================================
# qv2 data sync
# ============================================================
@app.command("sync")
def sync(
    market: str = typer.Option("cn_a", "--market", help="市场代码"),
    *,
    as_of: str = typer.Option(..., "--as-of", help="同步日期 YYYY-MM-DD"),
    bars_root: Path = typer.Option(Path("var/bars"), "--bars-root"),
    db: Path = typer.Option(Path("var/state.db"), "--db"),
    config_dir: Path = typer.Option(Path("configs/markets"), "--config-dir"),
) -> None:
    """从数据源同步日线行情到本地分区（T02.2/T02.3 接线）。

    标的清单 = PIT 池当日快照（首次自动抓 `query_all_stock` 并落库）；
    行情经 `ResilientSource` 三级降级（baostock 主源 → akshare → tencent），
    降级即 P0 告警（D-10，非静默）。
    """
    day = _parse_as_of(as_of)
    store = _open_store(db)
    try:
        worker = SubprocessWorker()
        try:
            symbols = _sync_symbols(worker, store, market, day, config_dir)
            resilient = ResilientSource(
                [
                    BaostockCnAdapter(worker=worker),
                    AkshareCnAdapter(),
                    TencentAdapter(),
                ],
                alert_sink=store.record_alert,
            )
            bars = resilient.fetch_with_fallback(
                BarRequest(
                    symbols=symbols,
                    market=market,
                    start=day,
                    end=day,
                    adjust=AdjustType.RAW,
                )
            )
            if not bars:
                store.record_alert(
                    level="P0",
                    source="data.sync",
                    message=(
                        f"{market} {day} 是交易日但同步到 0 行行情 —— "
                        "拒绝落库（0 rows ≠ 空市场，非静默成功）"
                    ),
                )
                console.print(
                    f"[bold red]FAILED[/bold red] {market} {day} 同步到 0 行行情"
                    "（交易日 0 行 = P0，已拒绝落库）。"
                )
                raise typer.Exit(code=2)

            bar_store = ParquetBarStore(bars_root)
            bar_store.save_bars(bars)

            table = Table(title=f"数据同步 {market} @ {day}")
            table.add_column("项")
            table.add_column("值", justify="right")
            table.add_row("PIT 池标的", str(len(symbols)))
            table.add_row("抓取行数", str(len(bars)))
            table.add_row("落库分区", f"{bars_root}/market={market}/dt={day}")
            console.print(table)
            console.print("[green]PASS[/green] 同步完成。")
        finally:
            worker.close()
    except NotTradingDayError as exc:
        console.print(f"[bold red]FAILED[/bold red] {exc}")
        raise typer.Exit(code=1) from exc
    except DataQualityGateError as exc:
        store.record_alert(level="P0", source="pit_universe", message=str(exc))
        console.print(f"[bold red]FAILED[/bold red] {exc}")
        raise typer.Exit(code=2) from exc
    except SourceUnavailableError as exc:
        # P0 告警已由 ResilientSource 在切换时落库（D-10：降级必告警）
        console.print(f"[bold red]FAILED[/bold red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        store.close()


def _sync_symbols(
    worker: SubprocessWorker,
    store: SqliteStore,
    market: str,
    day: date,
    config_dir: Path,
) -> tuple[str, ...]:
    """同步标的清单 = PIT 池 `day` 当日快照（M-19 交易日校验内置于 provider）。"""
    trading_days = _fetch_trading_days(worker, market, day, day)
    calendar = _build_calendar(market, trading_days, config_dir)
    repo = SqlitePitUniverseRepository(store)
    provider = BaostockPitUniverseProvider(
        repo=repo,
        calendar=calendar,
        fetcher=default_all_stock_fetcher(worker),
        market=market,
    )
    snapshots = provider.symbols(as_of=day, market=market)
    return tuple(s.symbol for s in snapshots)


# ============================================================
# qv2 data build-universe（T02.5 PIT 建池，M-22 采样）
# ============================================================
@app.command("build-universe")
def build_universe(
    market: str = typer.Option("cn_a", "--market", help="市场代码"),
    *,
    from_day: str = typer.Option(..., "--from", help="起始日 YYYY-MM-DD（≥ 1990-12-19，M-15）"),
    to_day: str = typer.Option(..., "--to", help="截止日 YYYY-MM-DD"),
    sampling: str = typer.Option(
        "auto", "--sampling", help="auto=近2年逐日+更早按周（M-22）| daily | weekly"
    ),
    config_dir: Path = typer.Option(Path("configs/markets"), "--config-dir"),
    db: Path = typer.Option(Path("var/state.db"), "--db"),
) -> None:
    """建 PIT 股票池（纯日快照 + 采样 + 事件日补齐，断点续跑幂等）。

    M-19：非交易日跳过（不是错误）；交易日 0 rows → P0 门禁退出码 2。
    M-21：名称突变分类告警（ST 相关 = INFO，实质性 = P0）。
    """
    start = _parse_as_of(from_day)
    end = _parse_as_of(to_day)
    if sampling not in ("auto", "daily", "weekly"):
        raise typer.BadParameter(f"sampling 只支持 auto/daily/weekly，收到 {sampling!r}")
    if start > end:
        raise typer.BadParameter(f"--from({start}) 不得晚于 --to({end})")
    if start < PIT_EARLIEST_DATE:
        raise typer.BadParameter(
            f"--from({start}) 早于 A 股快照最早可用日 {PIT_EARLIEST_DATE}（M-15）"
        )

    store = _open_store(db)
    try:
        worker = SubprocessWorker()
        try:
            trading_days = _fetch_trading_days(worker, market, start, end)
            calendar = _build_calendar(market, trading_days, config_dir)
            market_days = [d for d in trading_days if start <= d <= end]
            if not market_days:
                console.print(
                    f"[bold red]FAILED[/bold red] {start} ~ {end} 区间内没有交易日"
                    "（日历源返回为空，拒绝建池）。"
                )
                raise typer.Exit(code=1)

            repo = SqlitePitUniverseRepository(store)
            provider = BaostockPitUniverseProvider(
                repo=repo,
                calendar=calendar,
                fetcher=default_all_stock_fetcher(worker),
                market=market,
            )

            samples = _plan_samples(market_days, start, end, sampling)
            fetched, cached, info_changes, material_changes = _build_pool(
                provider=provider,
                repo=repo,
                store=store,
                market=market,
                market_days=market_days,
                samples=samples,
                end=end,
            )

            _render_build_summary(
                market=market,
                start=start,
                end=end,
                sampling=sampling,
                market_days=len(market_days),
                samples=len(samples),
                fetched=fetched,
                cached=cached,
                total_snapshots=len(repo.snapshot_dates()),
                info_changes=info_changes,
                material_changes=material_changes,
            )
        finally:
            worker.close()
    except NotTradingDayError as exc:
        console.print(f"[bold red]FAILED[/bold red] {exc}")
        raise typer.Exit(code=1) from exc
    except DataQualityGateError as exc:
        store.record_alert(level="P0", source="pit_universe", message=str(exc))
        console.print(f"[bold red]FAILED[/bold red] {exc}")
        raise typer.Exit(code=2) from exc
    except SourceUnavailableError as exc:
        store.record_alert(level="P0", source="market_data.baostock", message=str(exc))
        console.print(f"[bold red]FAILED[/bold red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        store.close()


def _build_pool(
    *,
    provider: BaostockPitUniverseProvider,
    repo: SqlitePitUniverseRepository,
    store: SqliteStore,
    market: str,
    market_days: list[date],
    samples: list[date],
    end: date,
) -> tuple[int, int, int, int]:
    """执行采样循环：断点续跑 + M-21 告警 + M-22 事件日补齐。

    Returns: `(fetched, cached, info_changes, material_changes)`。
    """
    done_dates = set(repo.snapshot_dates())  # 断点续跑：已落库的不重抓

    prev = repo.previous_snapshot(end)  # 严格早于 end 的最近快照（可能 None）
    prev_date: date | None = None
    prev_pairs: list[tuple[str, str]] = []
    prev_symbols: list[str] = []
    if prev is not None:
        prev_date, prev_rows = prev
        prev_pairs = [(r.symbol, r.code_name) for r in prev_rows]
        prev_symbols = [r.symbol for r in prev_rows]

    fetched = cached = 0
    info_changes = material_changes = 0
    for day in samples:
        fetched += day not in done_dates
        cached += day in done_dates
        snapshots = provider.symbols(as_of=day, market=market)
        curr_pairs = [(s.symbol, s.name) for s in snapshots]
        curr_symbols = [s.symbol for s in snapshots]

        if prev_date is not None:
            day_info, day_material = _record_name_changes(store, prev_pairs, curr_pairs, day)
            info_changes += day_info
            material_changes += day_material

            # M-22 事件日补齐：池成员集合变了 → 抓中间日精确定位事件
            for mid in event_fill_dates(
                prev_date,
                day,
                market_days,
                previous_symbols=prev_symbols,
                current_symbols=curr_symbols,
            ):
                mid_snapshots = provider.symbols(as_of=mid, market=market)
                fetched += 1
                prev_date = mid
                prev_pairs = [(s.symbol, s.name) for s in mid_snapshots]
                prev_symbols = [s.symbol for s in mid_snapshots]

        prev_date = day
        prev_pairs = curr_pairs
        prev_symbols = curr_symbols

    return fetched, cached, info_changes, material_changes


def _record_name_changes(
    store: SqliteStore,
    prev_pairs: list[tuple[str, str]],
    curr_pairs: list[tuple[str, str]],
    as_of: date,
) -> tuple[int, int]:
    """相邻快照名称突变 → 分级落告警（M-21）。返回 `(INFO 数, P0 数)`。"""
    info = material = 0
    for change in diff_snapshots(prev_pairs, curr_pairs, as_of=as_of):
        if change.kind is NameChangeKind.ST:
            info += 1
            store.record_alert(
                level="INFO",
                source="pit_universe",
                message=(
                    f"{as_of} {change.symbol} 名称变化（ST 相关，M-21 白名单）:"
                    f" {change.old_name!r} → {change.new_name!r}"
                ),
            )
        else:
            material += 1
            store.record_alert(
                level="P0",
                source="pit_universe",
                message=(
                    f"{as_of} {change.symbol} 名称实质性突变（疑似代码复用/重组，M-21）:"
                    f" {change.old_name!r} → {change.new_name!r}"
                ),
            )
    return info, material


def _render_build_summary(
    *,
    market: str,
    start: date,
    end: date,
    sampling: str,
    market_days: int,
    samples: int,
    fetched: int,
    cached: int,
    total_snapshots: int,
    info_changes: int,
    material_changes: int,
) -> None:
    """建池汇总表 + PASS 结语（rich）。"""
    table = Table(title=f"PIT 建池 {market} {start} ~ {end}")
    table.add_column("项")
    table.add_column("值", justify="right")
    table.add_row("交易日（区间内）", str(market_days))
    table.add_row(f"采样计划（{sampling}）", str(samples))
    table.add_row("本次抓取", str(fetched))
    table.add_row("已落库跳过（断点续跑）", str(cached))
    table.add_row("库内快照日总数", str(total_snapshots))
    table.add_row("名称突变 ST 相关（INFO）", str(info_changes))
    table.add_row("名称实质突变（P0）", str(material_changes))
    console.print(table)
    console.print(
        "[green]PASS[/green] 建池完成（M-22 采样：未采样日由最近前一个"
        "采样快照下推，ST 状态延迟 ≤5 交易日，影响标的 <0.05%）。"
    )


def _fetch_trading_days(
    worker: SubprocessWorker,
    market: str,
    start: date,
    end: date,
) -> list[date]:
    """经隔离子进程拉交易日历（一次调用覆盖全区间，含首尾各留 10 天缓冲）。"""
    result: WorkerResult = worker.run(
        WorkerCall.trade_dates(
            f"trade_dates-{start}-{end}",
            start - timedelta(days=10),
            end,
        )
    )
    if not result.ok or not isinstance(result.payload, list):
        raise QuantV2Error(
            f"交易日历拉取失败（{market} {start}~{end}）: {result.error or '返回类型异常'}"
        )
    days = [
        date.fromisoformat(str(row["calendar_date"]))
        for row in result.payload
        if str(row.get("is_trading_day")) == "1"
    ]
    if not days:
        raise QuantV2Error(f"交易日历为空（{market} {start}~{end}）—— 拒绝建池，不猜测日历")
    return sorted(days)


def _build_calendar(
    market: str,
    trading_days: list[date],
    config_dir: Path,
) -> ProfileTradingCalendar:
    """种子日历 + 市场画像 + overrides → ProfileTradingCalendar。"""
    profile = load_market_profile(market, config_dir=config_dir)
    overrides = load_calendar_overrides(config_dir, market)
    seed = StaticCalendarSeed({market: trading_days})
    return ProfileTradingCalendar({market: profile}, seed, {market: overrides})


def _plan_samples(market_days: list[date], start: date, end: date, sampling: str) -> list[date]:
    """采样计划（M-22）：auto=近2年逐日+更早按周；daily=全量；weekly=纯按周。"""
    if sampling == "daily":
        return list(market_days)
    if sampling == "weekly":
        return market_days[::5]
    return sample_dates(market_days, start=start, end=end)


# ============================================================
# qv2 data fingerprint
# ============================================================
@app.command("fingerprint")
def fingerprint(
    market: str = typer.Option("cn_a", "--market"),
    as_of: str = typer.Option(..., "--as-of", help="分区日期 YYYY-MM-DD"),
    bars_root: Path = typer.Option(Path("var/bars"), "--bars-root"),
    db: Path = typer.Option(Path("var/state.db"), "--db"),
) -> None:
    """计算并登记分区逻辑指纹（D-11 幂等验收：同数据重算必一致）。"""
    day = _parse_as_of(as_of)
    bar_store = ParquetBarStore(bars_root)
    store = _open_store(db)
    try:
        try:
            fp = bar_store.fingerprint_of(market, day)
        except FingerprintError as exc:
            console.print(f"[bold red]FAILED[/bold red] {exc}")
            raise typer.Exit(code=1) from exc
        with store.conn:
            store.conn.execute(
                "INSERT OR REPLACE INTO partition_fingerprints"
                "(market, dt, fingerprint, computed_at) VALUES(?, ?, ?, ?)",
                (market, day.isoformat(), fp, utc_now_iso()),
            )
        console.print(f"market={market} dt={day.isoformat()} rows-fingerprint:")
        console.print(f"  [bold]{fp}[/bold]")
    finally:
        store.close()


# ============================================================
# qv2 data quality
# ============================================================
@app.command("quality")
def quality(
    as_of: str = typer.Option(..., "--as-of", help="门禁日期 YYYY-MM-DD"),
    market: str = typer.Option("cn_a", "--market"),
    expected_file: Path | None = typer.Option(
        None, "--expected-file", help="期望标的清单（一行一个代码）；缺省用 PIT 池/前一分区"
    ),
    bars_root: Path = typer.Option(Path("var/bars"), "--bars-root"),
    db: Path = typer.Option(Path("var/state.db"), "--db"),
) -> None:
    """数据质量门禁：7 项规则 → 可读报告。FAIL 落 P0 告警并退出码 2。"""
    day = _parse_as_of(as_of)
    bar_store = ParquetBarStore(bars_root)
    store = _open_store(db)
    try:
        try:
            expected = resolve_expected_symbols(
                store=store,
                bar_store=bar_store,
                market=market,
                as_of=day,
                expected_file=expected_file,
            )
        except FileNotFoundError as exc:
            console.print(f"[bold red]FAILED[/bold red] {exc}")
            raise typer.Exit(code=1) from exc

        runner = QualityGateRunner(bar_store=bar_store, store=store)
        report = runner.run(market=market, as_of=day, expected_symbols=expected)

        table = Table(
            title=f"数据质量门禁 {market} @ {day}（期望标的 {len(expected)} 只）",
            show_lines=False,
        )
        table.add_column("规则")
        table.add_column("状态")
        table.add_column("明细", overflow="fold")
        style = {
            RuleStatus.PASS: "green",
            RuleStatus.WARN: "yellow",
            RuleStatus.FAIL: "bold red",
        }
        for r in report.results:
            table.add_row(r.rule_id, f"[{style[r.status]}]{r.status.value}[/]", r.detail)
        console.print(table)

        if report.status is RuleStatus.FAIL:
            console.print(
                f"[bold red]FAILED[/bold red] 数据质量门禁 {report.market} @ {report.as_of}"
                " —— 信号生成已中止，P0 告警已落库（这是设计行为，不是故障）。"
            )
            raise typer.Exit(code=2)
        console.print(f"[green]{report.status.value}[/green] 数据质量门禁通过。")
    except DataQualityGateError as exc:  # evaluate_all 规则不完整等：门禁本身坏了
        console.print(f"[bold red]FAILED[/bold red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        store.close()
