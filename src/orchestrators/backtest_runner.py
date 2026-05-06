from __future__ import annotations

from decimal import Decimal

from src.domain.enums import EventType, RunMode
from src.domain.events import DomainEvent
from src.domain.models.portfolio import Portfolio, Position
from src.domain.models.run import RunContext, RunSummary
from src.domain.models.strategy import StrategyConfig, StrategyContext
from src.domain.ports.market_data_port import MarketDataPort
from src.engines.backtest import BacktestEngine, MetricsEngine
from src.engines.risk import BasicRiskManager
from src.orchestrators.order_pipeline import OrderPipeline
from src.orchestrators.signal_pipeline import SignalPipeline
from src.app.bootstrap import AppContainer


class BacktestRunner:
    """负责串联本地数据、策略、风控、执行与组合更新的最小回测运行器。"""

    def __init__(
        self,
        container: AppContainer,
        backtest_engine: BacktestEngine | None = None,
        metrics_engine: MetricsEngine | None = None,
    ) -> None:
        """初始化回测运行器。"""
        self.container = container
        self.backtest_engine = backtest_engine or BacktestEngine()
        self.metrics_engine = metrics_engine or MetricsEngine()
        self.signal_pipeline = SignalPipeline(
            strategy=container.strategy,
            event_repository=container.event_repository,
        )
        self.order_pipeline = OrderPipeline(
            risk_manager=container.risk_manager,
            execution_gateway=container.execution_gateway,
            event_repository=container.event_repository,
        )

    def run(self, context: RunContext) -> RunSummary:
        """执行回测：逐根K线迭代，每次喂 bars[:i+1] 给策略，复现真实顺序。"""
        self.container.run_repository.save_run_context(context)
        self.container.event_repository.append(
            DomainEvent(
                event_type=EventType.RUN_STARTED,
                run_id=context.run_id,
                strategy_id=context.strategy_id,
                timestamp=self.container.clock.now(),
                payload={"symbols": context.symbols, "frequency": context.frequency.value},
            )
        )

        portfolio = self.container.portfolio_repository.load_latest_portfolio(context.run_id)
        if portfolio is None:
            portfolio = Portfolio(
                cash=Decimal("1000000"),
                total_value=Decimal("1000000"),
                positions={},
                updated_at=self.container.clock.now(),
            )
        equity_curve = [portfolio.total_value]
        peak_equity = portfolio.total_value

        # 加载所有标的的K线
        symbol_bars: dict[str, list] = {}
        max_len = 0
        for symbol in context.symbols:
            bars = self._load_bars(self.container.market_data, symbol, context)
            if bars:
                symbol_bars[symbol] = bars
                max_len = max(max_len, len(bars))

        if max_len == 0:
            return self._build_empty_summary(context, portfolio)

        # 逐根K线迭代
        for i in range(max_len):
            if self._should_stop_for_drawdown(portfolio.total_value, peak_equity):
                break

            latest_prices: dict[str, Decimal] = {}

            for symbol, bars in symbol_bars.items():
                if i >= len(bars):
                    continue

                bar = bars[i]
                # 策略只能看到历史K线（不含当前），模拟"收盘前"决策
                historical = bars[:i]
                if not historical:
                    continue

                strategy_context = StrategyContext(
                    run_id=context.run_id,
                    as_of=bar.timestamp,
                    bars=historical,
                    portfolio=portfolio,
                    config=StrategyConfig(params={}),
                    metadata=self.container.strategy.metadata(),
                )
                outputs = self.signal_pipeline.run(strategy_context)
                orders = self.order_pipeline.build_order_intents(
                    outputs, self.container.strategy.metadata()
                )
                decisions = self.order_pipeline.evaluate_risk(portfolio, orders)
                self.order_pipeline.record_risk_event(
                    context.run_id, context.strategy_id, decisions
                )
                approved_orders = self.order_pipeline.filter_approved_orders(
                    orders, decisions
                )
                reports = self.order_pipeline.execute(approved_orders)
                self.order_pipeline.record_execution_event(
                    context.run_id, context.strategy_id, reports
                )
                latest_prices[symbol] = bar.close
                fills = self.backtest_engine.simulate_orders(
                    portfolio, approved_orders, latest_prices
                )
                portfolio = self.backtest_engine.apply_fills(portfolio, fills)
                self.container.portfolio_repository.save_portfolio(
                    context.run_id, portfolio
                )

            # 当日结束时，按收盘价更新持仓市值
            positions_snapshot: dict[str, Position] = {}
            for symbol, bars in symbol_bars.items():
                if i < len(bars) and symbol in portfolio.positions:
                    bar = bars[i]
                    pos = portfolio.positions[symbol]
                    # frozen dataclass，用构造创建新对象
                    positions_snapshot[symbol] = Position(
                        symbol=symbol,
                        quantity=pos.quantity,
                        avg_cost=pos.avg_cost,
                        market_value=bar.close * pos.quantity,
                        updated_at=bar.timestamp,
                    )
                elif symbol in portfolio.positions:
                    positions_snapshot[symbol] = portfolio.positions[symbol]

            # 用新positions重建portfolio（frozen，不能原地修改）
            new_positions = dict(portfolio.positions)
            new_positions.update(positions_snapshot)
            total_mv = sum(p.market_value for p in new_positions.values())
            portfolio = Portfolio(
                cash=portfolio.cash,
                total_value=portfolio.cash + total_mv,
                positions=new_positions,
                updated_at=portfolio.updated_at,
            )

            equity_curve.append(portfolio.total_value)
            if portfolio.total_value > peak_equity:
                peak_equity = portfolio.total_value

        metrics = self.metrics_engine.calculate(equity_curve)
        summary = RunSummary(
            run_id=context.run_id,
            mode=context.mode,
            started_at=context.created_at,
            finished_at=self.container.clock.now(),
            status="completed",
            message="Run finished successfully.",
            final_equity=portfolio.total_value,
            total_return=metrics.total_return,
            annualized_return=metrics.annualized_return,
            max_drawdown=metrics.max_drawdown,
            sharpe_ratio=metrics.sharpe_ratio,
        )
        self.container.run_repository.save_run_summary(summary)
        self.container.event_repository.append(
            DomainEvent(
                event_type=EventType.RUN_FINISHED,
                run_id=context.run_id,
                strategy_id=context.strategy_id,
                timestamp=self.container.clock.now(),
                payload={
                    "status": summary.status,
                    "final_equity": str(summary.final_equity),
                    "peak_equity": str(peak_equity),
                    "total_return": str(summary.total_return),
                    "annualized_return": str(summary.annualized_return),
                    "max_drawdown": str(summary.max_drawdown),
                    "sharpe_ratio": str(summary.sharpe_ratio),
                },
            )
        )
        return summary

    def _load_bars(
        self,
        market_data: MarketDataPort,
        symbol: str,
        context: RunContext,
    ):
        """加载单个标的在回测区间内的K线数据。"""
        from datetime import datetime, time

        start = datetime.combine(context.start_date, time.min)
        end = datetime.combine(context.end_date, time.max)
        return market_data.get_bars(symbol, start, end, context.frequency)

    def _should_stop_for_drawdown(self, current_equity: Decimal, peak_equity: Decimal) -> bool:
        """根据历史峰值净值判断是否需要触发回撤保护。"""
        if not isinstance(self.container.risk_manager, BasicRiskManager):
            return False
        triggered = self.container.risk_manager.should_trigger_drawdown_guard(current_equity, peak_equity)
        if triggered:
            self.container.risk_manager.kill_switch = True
        return triggered

    def _build_empty_summary(self, context: RunContext, portfolio: Portfolio) -> RunSummary:
        """没有数据时返回空摘要。"""
        return RunSummary(
            run_id=context.run_id,
            mode=context.mode,
            started_at=context.created_at,
            finished_at=self.container.clock.now(),
            status="no_data",
            message="No market data found for the given context.",
            final_equity=portfolio.total_value,
            total_return=Decimal("0"),
            annualized_return=Decimal("0"),
            max_drawdown=Decimal("0"),
            sharpe_ratio=Decimal("0"),
        )
