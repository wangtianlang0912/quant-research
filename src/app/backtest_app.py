from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.app.bootstrap import build_backtest_container
from src.domain.enums import Frequency, RunMode
from src.domain.ids import RunId
from src.domain.models.run import RunContext, RunSummary
from src.orchestrators import BacktestRunner
from src.strategies import MeanReversionStrategy, TrendFollowingStrategy
from src.adapters import AkshareAdapter, LocalCsvAdapter
from src.services.oos_validator import OosValidator
from src.services.reporting import BacktestReportWriter


# ─── 参数化回测入口 ────────────────────────────────────────────────────────

def run_backtest(
    data_path: str,
    symbol: str,
    strategy_name: str = "trend_following",
    frequency: Frequency = Frequency.DAY_1,
    market_data_source: str = "local_csv",
    # 策略参数
    short_window: int | None = None,
    long_window: int | None = None,
    lookback_window: int | None = None,
    entry_zscore: float | None = None,
    exit_zscore: float | None = None,
    bb_window: int | None = None,
    bb_num_std: float | None = None,
    bb_exit_threshold: float | None = None,
    macd_fast: int | None = None,
    macd_slow: int | None = None,
    macd_signal: int | None = None,
    rsi_period: int | None = None,
    rsi_overbought: float | None = None,
    rsi_oversold: float | None = None,
    vwap_deviation_pct: float | None = None,
    dc_channel_period: int | None = None,
    dc_exit_period: int | None = None,
    # 风控参数
    commission_rate: float | None = None,
    slippage_rate: float | None = None,
    max_drawdown_ratio: float | None = None,
) -> RunSummary:
    """使用指定数据源与频率运行回测并输出报告。"""
    from datetime import date, datetime

    strategy_params: dict[str, Any] = {}
    if short_window is not None:
        strategy_params["short_window"] = short_window
    if long_window is not None:
        strategy_params["long_window"] = long_window
    if lookback_window is not None:
        strategy_params["lookback_window"] = lookback_window
    if entry_zscore is not None:
        strategy_params["entry_zscore"] = Decimal(str(entry_zscore))
    if exit_zscore is not None:
        strategy_params["exit_zscore"] = Decimal(str(exit_zscore))
    if bb_window is not None:
        strategy_params["window"] = bb_window
    if bb_num_std is not None:
        strategy_params["num_std"] = bb_num_std
    if bb_exit_threshold is not None:
        strategy_params["exit_threshold"] = bb_exit_threshold
    if macd_fast is not None:
        strategy_params["macd_fast"] = macd_fast
    if macd_slow is not None:
        strategy_params["macd_slow"] = macd_slow
    if macd_signal is not None:
        strategy_params["macd_signal"] = macd_signal
    if rsi_period is not None:
        strategy_params["rsi_period"] = rsi_period
    if rsi_overbought is not None:
        strategy_params["rsi_overbought"] = rsi_overbought
    if rsi_oversold is not None:
        strategy_params["rsi_oversold"] = rsi_oversold
    if vwap_deviation_pct is not None:
        strategy_params["deviation_pct"] = vwap_deviation_pct
    if dc_channel_period is not None:
        strategy_params["channel_period"] = dc_channel_period
    if dc_exit_period is not None:
        strategy_params["exit_period"] = dc_exit_period

    risk_params: dict[str, Any] = {}
    if commission_rate is not None:
        risk_params["commission_rate"] = Decimal(str(commission_rate))
    if slippage_rate is not None:
        risk_params["slippage_rate"] = Decimal(str(slippage_rate))
    if max_drawdown_ratio is not None:
        risk_params["max_drawdown_ratio"] = Decimal(str(max_drawdown_ratio))

    strategy = _build_strategy(strategy_name, strategy_params)
    market_data = _build_market_data(data_path=data_path, market_data_source=market_data_source, frequency=frequency)
    container, backtest_engine = build_backtest_container(strategy=strategy, market_data=market_data, risk_params=risk_params)
    runner = BacktestRunner(container, backtest_engine=backtest_engine)
    context = RunContext(
        run_id=RunId(f"backtest-{strategy.metadata().strategy_id.value}-{frequency.value}-{symbol}"),
        mode=RunMode.BACKTEST,
        strategy_id=strategy.metadata().strategy_id,
        symbols=[symbol],
        frequency=frequency,
        start_date=date(2024, 4, 9),   # 数据实际起始日
        end_date=date(2026, 4, 30),    # 数据实际截止日
        created_at=datetime.now(),
        environment="dev",
        metadata={
            "data_path": data_path,
            "strategy_name": strategy_name,
            "market_data_source": market_data_source,
            "frequency": frequency.value,
        },
    )
    summary = runner.run(context)
    risk_summary = {
        "engine": container.risk_manager.__class__.__name__,
        "enabled": getattr(container.risk_manager, "enabled", None),
        "kill_switch": getattr(container.risk_manager, "kill_switch", None),
        "max_order_quantity": str(getattr(container.risk_manager, "max_order_quantity", "")),
        "max_position_value_ratio": str(getattr(container.risk_manager, "max_position_value_ratio", "")),
        "max_total_exposure_ratio": str(getattr(container.risk_manager, "max_total_exposure_ratio", "")),
        "max_drawdown_ratio": str(getattr(container.risk_manager, "max_drawdown_ratio", "")),
        "min_cash_reserve": str(getattr(container.risk_manager, "min_cash_reserve", "")),
    }
    strategy_metadata = {
        "strategy_id": strategy.metadata().strategy_id.value,
        "name": strategy.metadata().name,
        "version": strategy.metadata().version,
        "author": strategy.metadata().author,
    }
    event_summary = {
        "event_count": len(container.event_repository.list_by_run(context.run_id)),
        "frequency": frequency.value,
        "market_data_source": market_data_source,
    }
    report_writer = BacktestReportWriter()
    report_path = report_writer.write_json_report(
        output_dir="reports/backtest",
        context=context,
        summary=summary,
        risk_summary=risk_summary,
        strategy_metadata=strategy_metadata,
        event_summary=event_summary,
    )
    return RunSummary(
        run_id=summary.run_id,
        mode=summary.mode,
        started_at=summary.started_at,
        finished_at=summary.finished_at,
        status=summary.status,
        message=f"{summary.message} report_path={report_path}",
        final_equity=summary.final_equity,
        total_return=summary.total_return,
        annualized_return=summary.annualized_return,
        max_drawdown=summary.max_drawdown,
        sharpe_ratio=summary.sharpe_ratio,
    )


def run_oos_validation(data_path: str, symbol: str, strategy_name: str = "trend_following") -> dict[str, str]:
    """运行样本内外两段回测并输出最小OOS验证结果。"""
    from datetime import date, datetime

    strategy = _build_strategy(strategy_name)
    market_data = LocalCsvAdapter(base_path=data_path)
    validator = OosValidator()

    in_sample_container, in_sample_engine = build_backtest_container(strategy=strategy, market_data=market_data)
    in_sample_runner = BacktestRunner(in_sample_container, backtest_engine=in_sample_engine)
    in_sample_context = RunContext(
        run_id=RunId(f"oos-is-{strategy.metadata().strategy_id.value}-{symbol}"),
        mode=RunMode.BACKTEST,
        strategy_id=strategy.metadata().strategy_id,
        symbols=[symbol],
        frequency=Frequency.DAY_1,
        start_date=date(2024, 4, 9),
        end_date=date(2024, 12, 31),
        created_at=datetime.now(),
        environment="dev",
        metadata={"data_path": data_path, "dataset": "in_sample", "strategy_name": strategy_name},
    )
    in_sample_summary = in_sample_runner.run(in_sample_context)

    out_of_sample_container, out_of_sample_engine = build_backtest_container(strategy=_build_strategy(strategy_name), market_data=market_data)
    out_of_sample_runner = BacktestRunner(out_of_sample_container, backtest_engine=out_of_sample_engine)
    out_of_sample_context = RunContext(
        run_id=RunId(f"oos-oos-{strategy.metadata().strategy_id.value}-{symbol}"),
        mode=RunMode.BACKTEST,
        strategy_id=strategy.metadata().strategy_id,
        symbols=[symbol],
        frequency=Frequency.DAY_1,
        start_date=date(2025, 1, 1),
        end_date=date(2026, 4, 30),
        created_at=datetime.now(),
        environment="dev",
        metadata={"data_path": data_path, "dataset": "out_of_sample", "strategy_name": strategy_name},
    )
    out_of_sample_summary = out_of_sample_runner.run(out_of_sample_context)
    result = validator.validate(in_sample_summary, out_of_sample_summary)

    report_writer = BacktestReportWriter()
    report_path = report_writer.write_json_report(
        output_dir="reports/oos",
        context=out_of_sample_context,
        summary=out_of_sample_summary,
        risk_summary={"validation_score": str(result.score), "passed": str(result.passed)},
        strategy_metadata={
            "strategy_id": strategy.metadata().strategy_id.value,
            "name": strategy.metadata().name,
            "version": strategy.metadata().version,
            "author": strategy.metadata().author,
        },
        event_summary={
            "in_sample_run_id": in_sample_summary.run_id.value,
            "out_of_sample_run_id": out_of_sample_summary.run_id.value,
            "oos_summary": result.summary,
        },
    )
    return {
        "passed": str(result.passed),
        "score": str(result.score),
        "summary": result.summary,
        "report_path": report_path,
    }


# ─── 参数扫描 ───────────────────────────────────────────────────────────────

from itertools import product


def run_param_scan(
    data_path: str,
    symbol: str,
    strategy_name: str = "trend_following",
    scan_params: dict[str, list] | None = None,
) -> list[dict]:
    """遍历参数组合，批量运行回测，返回所有结果。"""
    from datetime import date, datetime

    scan_params = scan_params or {}
    results = []
    # 生成参数组合
    keys = list(scan_params.keys())
    combos = list(product(*scan_params.values())) if keys else [()]
    for combo in combos:
        params = dict(zip(keys, combo))
        # 分类参数
        strategy_kwargs = {k: v for k, v in params.items() if k in (
            "short_window", "long_window", "lookback_window", "entry_zscore", "exit_zscore"
        )}
        risk_kwargs = {k: v for k, v in params.items() if k in (
            "commission_rate", "slippage_rate", "max_drawdown_ratio"
        )}
        run_id_suffix = "-".join(f"{k}{v}" for k, v in params.items())
        strategy = _build_strategy(strategy_name, strategy_kwargs)
        market_data = _build_market_data(data_path=data_path, market_data_source="local_csv", frequency=Frequency.DAY_1)
        container, backtest_engine = build_backtest_container(strategy=strategy, market_data=market_data, risk_params=risk_kwargs)
        runner = BacktestRunner(container, backtest_engine=backtest_engine)
        context = RunContext(
            run_id=RunId(f"scan-{strategy_name}-{run_id_suffix}"),
            mode=RunMode.BACKTEST,
            strategy_id=strategy.metadata().strategy_id,
            symbols=[symbol],
            frequency=Frequency.DAY_1,
            start_date=date(2024, 4, 9),
            end_date=date(2026, 4, 30),
            created_at=datetime.now(),
            environment="dev",
            metadata={"data_path": data_path, "scan_params": params},
        )
        summary = runner.run(context)
        results.append({
            "params": params,
            "run_id": summary.run_id.value,
            "final_equity": str(summary.final_equity),
            "total_return": str(summary.total_return),
            "annualized_return": str(summary.annualized_return),
            "max_drawdown": str(summary.max_drawdown),
            "sharpe_ratio": str(summary.sharpe_ratio),
            "status": summary.status,
        })
    # 按总收益排序
    results.sort(key=lambda x: float(x["total_return"]), reverse=True)
    return results


def _build_market_data(data_path: str, market_data_source: str, frequency: Frequency):
    """根据数据源类型构造市场数据适配器。"""
    if market_data_source == "akshare":
        return AkshareAdapter(default_frequency=frequency)
    return LocalCsvAdapter(base_path=data_path)


def _build_strategy(strategy_name: str, params: dict | None = None):
    """根据策略名称构造具体策略实例。"""
    params = params or {}
    if strategy_name == "mean_reversion":
        return MeanReversionStrategy(
            lookback_window=params.get("lookback_window", 20),
            entry_zscore=params.get("entry_zscore", Decimal("1.0")),
            exit_zscore=params.get("exit_zscore", Decimal("0.3")),
        )
    if strategy_name == "bollinger_bands":
        from src.strategies.bollinger_bands import BollingerBandsStrategy
        return BollingerBandsStrategy(
            window=params.get("window", 20),
            num_std=params.get("num_std", 2.0),
            exit_threshold=params.get("exit_threshold", 0.0),
        )
    if strategy_name == "macd_rsi":
        from src.strategies.macd_rsi import MacdRsiStrategy
        return MacdRsiStrategy(
            macd_fast=params.get("macd_fast", 12),
            macd_slow=params.get("macd_slow", 26),
            macd_signal=params.get("macd_signal", 9),
            rsi_period=params.get("rsi_period", 14),
            rsi_overbought=params.get("rsi_overbought", 70.0),
            rsi_oversold=params.get("rsi_oversold", 30.0),
        )
    if strategy_name == "vwap":
        from src.strategies.vwap import VwapStrategy
        return VwapStrategy(
            deviation_pct=params.get("deviation_pct", 1.0),
        )
    if strategy_name == "donchian_channel":
        from src.strategies.donchian_channel import DonchianChannelStrategy
        return DonchianChannelStrategy(
            channel_period=params.get("channel_period", 20),
            exit_period=params.get("exit_period", 10),
        )
    # 默认：趋势跟随
    return TrendFollowingStrategy(
        short_window=params.get("short_window", 5),
        long_window=params.get("long_window", 20),
    )
