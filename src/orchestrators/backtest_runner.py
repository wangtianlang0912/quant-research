from __future__ import annotations

from pathlib import Path

from src.app.bootstrap import AppContainer
from src.domain.enums import Frequency, RunMode
from src.domain.events import DomainEvent
from src.domain.ids import RunId
from src.domain.models.portfolio import Portfolio
from src.domain.models.run import RunContext, RunSummary
from src.domain.ports.market_data_port import MarketDataPort
from src.engines.backtest import BacktestEngine
from src.orchestrators import OrderPipeline, SignalPipeline


class BacktestRunner:
    """负责串联本地数据、策略、风控、执行与组合更新的最小回测运行器。"""

    def __init__(
        self,
        container: AppContainer,
        backtest_engine: BacktestEngine | None = None,
    ) -> None:
        """初始化回测运行器。"""
        self.container = container
        self.backtest_engine = backtest_engine or BacktestEngine()
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
        """执行一次最小可运行回测流程并返回运行摘要。"""
        self.container.run_repository.save_run_context(context)
        self.container.event_repository.append(
            DomainEvent(
                event_type=RunMode.BACKTEST and __import__("src.domain.enums", fromlist=["EventType"]).EventType.RUN_STARTED,
                run_id=context.run_id,
                strategy_id=context.strategy_id,
                timestamp=self.container.clock.now(),
                payload={"symbols": context.symbols, "frequency": context.frequency.value},
            )
        )

        portfolio = self.container.portfolio_repository.load_latest_portfolio(context.run_id)
        if portfolio is None:
            portfolio = Portfolio(cash=__import__("decimal").Decimal("1000000"), total_value=__import__("decimal").Decimal("1000000"), positions={})

        latest_prices = {}
        for symbol in context.symbols:
            bars = self._load_bars(self.container.market_data, symbol, context)
            if not bars:
                continue
            strategy_context = __import__("src.domain.models.strategy", fromlist=["StrategyContext", "StrategyConfig"]).StrategyContext(
                run_id=context.run_id,
                as_of=bars[-1].timestamp,
                bars=bars,
                portfolio=portfolio,
                config=__import__("src.domain.models.strategy", fromlist=["StrategyConfig"]).StrategyConfig(params={}),
                metadata=self.container.strategy.metadata(),
            )
            outputs = self.signal_pipeline.run(strategy_context)
            orders = self.order_pipeline.build_order_intents(outputs, self.container.strategy.metadata())
            decisions = self.order_pipeline.evaluate_risk(portfolio, orders)
            self.order_pipeline.record_risk_event(context.run_id, context.strategy_id, decisions)
            approved_orders = self.order_pipeline.filter_approved_orders(orders, decisions)
            reports = self.order_pipeline.execute(approved_orders)
            self.order_pipeline.record_execution_event(context.run_id, context.strategy_id, reports)
            latest_prices[symbol] = bars[-1].close
            fills = self.backtest_engine.simulate_orders(portfolio, approved_orders, latest_prices)
            portfolio = self.backtest_engine.apply_fills(portfolio, fills)
            self.container.portfolio_repository.save_portfolio(context.run_id, portfolio)

        summary = RunSummary(
            run_id=context.run_id,
            mode=RunMode.BACKTEST,
            started_at=context.created_at,
            finished_at=self.container.clock.now(),
            status="completed",
            message="Backtest finished successfully.",
        )
        self.container.run_repository.save_run_summary(summary)
        self.container.event_repository.append(
            DomainEvent(
                event_type=__import__("src.domain.enums", fromlist=["EventType"]).EventType.RUN_FINISHED,
                run_id=context.run_id,
                strategy_id=context.strategy_id,
                timestamp=self.container.clock.now(),
                payload={"status": summary.status},
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
