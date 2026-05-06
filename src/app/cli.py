from __future__ import annotations

import argparse

from src.app.backtest_app import run_backtest, run_param_scan
from src.domain.enums import Frequency


FREQUENCY_CHOICES = {
    Frequency.DAY_1.value: Frequency.DAY_1,
    Frequency.MIN_1.value: Frequency.MIN_1,
    Frequency.MIN_5.value: Frequency.MIN_5,
    Frequency.MIN_15.value: Frequency.MIN_15,
    Frequency.MIN_30.value: Frequency.MIN_30,
    Frequency.MIN_60.value: Frequency.MIN_60,
}


def main() -> int:
    """提供统一命令行入口，用于启动本地回测流程。"""
    parser = argparse.ArgumentParser(description="quant-research CLI")
    subparsers = parser.add_subparsers(dest="command")

    backtest_parser = subparsers.add_parser("backtest", help="运行本地回测")
    backtest_parser.add_argument("--data-path", required=True, help="本地历史数据目录")
    backtest_parser.add_argument("--symbol", required=True, help="回测标的代码")
    backtest_parser.add_argument("--strategy-name", default="trend_following",
        choices=["trend_following","mean_reversion","bollinger_bands","macd_rsi","vwap","donchian_channel"],
        help="策略名称")
    backtest_parser.add_argument("--frequency", default=Frequency.DAY_1.value, choices=sorted(FREQUENCY_CHOICES.keys()), help="回测频率")
    backtest_parser.add_argument("--market-data-source", default="local_csv", choices=["local_csv","akshare"], help="市场数据源")
    # 策略参数
    backtest_parser.add_argument("--short-window", type=int, default=None, help="趋势跟随: 短期均线窗口")
    backtest_parser.add_argument("--long-window", type=int, default=None, help="趋势跟随: 长期均线窗口")
    backtest_parser.add_argument("--lookback-window", type=int, default=None, help="均值回归: 历史窗口")
    backtest_parser.add_argument("--entry-zscore", type=float, default=None, help="均值回归: 入场 zscore 阈值")
    backtest_parser.add_argument("--exit-zscore", type=float, default=None, help="均值回归: 平仓 zscore 阈值")
    backtest_parser.add_argument("--bb-window", type=int, default=None, help="布林带: 窗口期")
    backtest_parser.add_argument("--bb-num-std", type=float, default=None, help="布林带: 标准差倍数")
    backtest_parser.add_argument("--bb-exit-threshold", type=float, default=None, help="布林带: 平仓阈值")
    backtest_parser.add_argument("--macd-fast", type=int, default=None, help="MACD+RSI: MACD快线")
    backtest_parser.add_argument("--macd-slow", type=int, default=None, help="MACD+RSI: MACD慢线")
    backtest_parser.add_argument("--macd-signal", type=int, default=None, help="MACD+RSI: MACD信号线")
    backtest_parser.add_argument("--rsi-period", type=int, default=None, help="MACD+RSI: RSI周期")
    backtest_parser.add_argument("--rsi-overbought", type=float, default=None, help="MACD+RSI: RSI超买阈值")
    backtest_parser.add_argument("--rsi-oversold", type=float, default=None, help="MACD+RSI: RSI超卖阈值")
    backtest_parser.add_argument("--vwap-deviation-pct", type=float, default=None, help="VWAP: 偏离百分比(%)")
    backtest_parser.add_argument("--dc-channel-period", type=int, default=None, help="唐奇安通道: 通道周期")
    backtest_parser.add_argument("--dc-exit-period", type=int, default=None, help="唐奇安通道: 退出周期")
    # 风控参数
    backtest_parser.add_argument("--commission-rate", type=float, default=None, help="佣金率(例: 0.0003)")
    backtest_parser.add_argument("--slippage-rate", type=float, default=None, help="滑点率(例: 0.0005)")
    backtest_parser.add_argument("--max-drawdown-ratio", type=float, default=None, help="最大回撤熔断阈值(例: 0.15)")

    args = parser.parse_args()

    if args.command == "backtest":
        summary = run_backtest(
            data_path=args.data_path,
            symbol=args.symbol,
            strategy_name=args.strategy_name,
            frequency=FREQUENCY_CHOICES[args.frequency],
            market_data_source=args.market_data_source,
            short_window=args.short_window,
            long_window=args.long_window,
            lookback_window=args.lookback_window,
            entry_zscore=args.entry_zscore,
            exit_zscore=args.exit_zscore,
            bb_window=args.bb_window,
            bb_num_std=args.bb_num_std,
            bb_exit_threshold=args.bb_exit_threshold,
            macd_fast=args.macd_fast,
            macd_slow=args.macd_slow,
            macd_signal=args.macd_signal,
            rsi_period=args.rsi_period,
            rsi_overbought=args.rsi_overbought,
            rsi_oversold=args.rsi_oversold,
            vwap_deviation_pct=args.vwap_deviation_pct,
            dc_channel_period=args.dc_channel_period,
            dc_exit_period=args.dc_exit_period,
            commission_rate=args.commission_rate,
            slippage_rate=args.slippage_rate,
            max_drawdown_ratio=args.max_drawdown_ratio,
        )
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
