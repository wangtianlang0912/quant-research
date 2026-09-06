"""qv2 ops —— 部署与运维命令（T02.2b）。

## 退出码约定（与 `qv2 data` 一致：非静默成功）

- 0：探活通过（满足最低可用条件）；
- 1：探活失败（无任何源能给日线 / 复权因子 → 拒绝启动，已落 P0 告警）。
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from quant_v2.adapters.market_data.akshare_cn import AkshareCnAdapter
from quant_v2.adapters.market_data.baostock_cn import BaostockCnAdapter
from quant_v2.adapters.market_data.source_probe import (
    ProbeEndpoint,
    SourceProbe,
    assert_minimum_viable,
)
from quant_v2.adapters.market_data.tencent_fallback import TencentAdapter
from quant_v2.adapters.persistence.sqlite_store import SqliteStore
from quant_v2.domain.errors import SourceUnavailableError

app = typer.Typer(help="部署探活 / 运维状态", no_args_is_help=True)
console = Console()

# TCP 端点清单：只登记实测确定的主机（§5.12）。
# ★ baostock 无 HTTP 端点（裸 TCP 私有协议，M-9），只做语义探活（healthcheck）。
# ★ 禁用端点（东财 push2 系）不探测不登记 —— ResilientSource 直接跳过它们。
_PROBE_ENDPOINTS = {
    "akshare": (ProbeEndpoint(source_id="akshare", host="finance.sina.com.cn", port=443),),
    "tencent": (ProbeEndpoint(source_id="tencent", host="web.ifzq.gtimg.cn", port=443),),
}


# ============================================================
# qv2 ops probe-sources
# ============================================================
@app.command("probe-sources")
def probe_sources(
    db: Path = typer.Option(Path("var/state.db"), "--db", help="告警落库位置"),
    attempts: int = typer.Option(3, "--attempts", help="每个源的重试次数"),
    timeout_s: float = typer.Option(5.0, "--timeout", help="单次探测超时（秒）"),
) -> None:
    """部署前探活全部数据源（§5.12 部署清单第一步）。

    不满足最低可用条件（≥1 源给日线 且 ≥1 源给复权因子）→ P0 告警 + 退出码 1。
    """
    adapters = (BaostockCnAdapter(), AkshareCnAdapter(), TencentAdapter())
    probe = SourceProbe(
        adapters,
        endpoints=_PROBE_ENDPOINTS,
        attempts=attempts,
        timeout_s=timeout_s,
    )
    report = probe.probe_all()

    table = Table(title=f"数据源探活 @ {report.checked_at.isoformat()}", show_lines=True)
    table.add_column("源")
    table.add_column("语义探活")
    table.add_column("端点")
    table.add_column("明细", overflow="fold")
    for result in report.results:
        ok = f"{result.ok_attempts}/{result.attempts}"
        style = "green" if result.reachable else "bold red"
        table.add_row(
            result.source_id,
            f"[{style}]{ok}[/]",
            "\n".join(result.endpoints) or "—（无 HTTP 端点，仅语义探活）",
            result.detail or "OK",
        )
    console.print(table)

    db.parent.mkdir(parents=True, exist_ok=True)
    store = SqliteStore(db)
    try:
        for result in report.results:
            if not result.reachable:
                detail = result.detail or "无成功尝试"
                store.record_alert(
                    level="P0",
                    source=f"market_data.{result.source_id}",
                    message=f"探活失败：{result.source_id} 不可用（{detail}）",
                )
        try:
            assert_minimum_viable(report)
        except SourceUnavailableError as exc:
            store.record_alert(
                level="P0",
                source="ops.probe_sources",
                message=f"拒绝启动：{exc}",
            )
            console.print(f"[bold red]FAILED[/bold red] {exc}")
            raise typer.Exit(code=1) from exc
    finally:
        store.close()
    console.print("[green]PASS[/green] 数据源探活通过（最低可用条件满足）。")
