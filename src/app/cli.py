from __future__ import annotations

import argparse

from src.app.backtest_app import run_backtest


def main() -> int:
    """提供统一命令行入口，用于启动最小回测流程。"""
    parser = argparse.ArgumentParser(description="quant-research CLI")
    subparsers = parser.add_subparsers(dest="command")

    backtest_parser = subparsers.add_parser("backtest", help="运行本地回测")
    backtest_parser.add_argument("--data-path", required=True, help="本地历史数据目录")
    backtest_parser.add_argument("--symbol", required=True, help="回测标的代码")

    args = parser.parse_args()

    if args.command == "backtest":
        summary = run_backtest(data_path=args.data_path, symbol=args.symbol)
        print(
            f"run_id={summary.run_id.value} mode={summary.mode.value} status={summary.status} "
            f"final_equity={summary.final_equity} total_return={summary.total_return} "
            f"annualized_return={summary.annualized_return} max_drawdown={summary.max_drawdown} "
            f"sharpe_ratio={summary.sharpe_ratio} message={summary.message}"
        )
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
