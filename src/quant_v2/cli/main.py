"""qv2 主入口。

```
qv2 data quality --as-of 2026-09-05          # 数据质量门禁（FAIL → 退出码 2）
qv2 data fingerprint --market cn_a --as-of X # 分区逻辑指纹（D-11 幂等登记）
qv2 data sync --market cn_a --as-of X        # 数据同步（T02.2 接入 baostock 后可用）
qv2 ops probe-sources                        # 部署前数据源探活（§5.12）
```
"""

from __future__ import annotations

import typer

from quant_v2.cli.commands import data as data_commands
from quant_v2.cli.commands import ops as ops_commands

app = typer.Typer(
    help="quant_research v2 —— 个人级可解释投研助手",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(data_commands.app, name="data", help="数据同步 / 质量门禁 / 指纹")
app.add_typer(ops_commands.app, name="ops", help="部署探活 / 运维状态")


def main() -> None:  # pragma: no cover —— 入口薄壳，逻辑在各命令内
    app()


if __name__ == "__main__":
    main()
