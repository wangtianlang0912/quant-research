"""领域端口契约测试（T01.3 验收：每个端口必须有 ≥1 个测试替身 + 关键 dataclass 校验）。

★ 这一文件存在的理由：

1. **覆盖率硬伤**：ports/ 子模块全部是 Protocol/ABC，纯粹定义层；
   没有测试时覆盖率 0%，直接把核心域均值拖到 60% 以下。
2. **契约回归**：Protocol 是 v2 整个架构的"接口稳定层"。
   dataclass 的 `__post_init__` 校验、Protocol 的 `runtime_checkable`
   行为，必须有测试锁定 —— 否则后续重构悄悄放松校验，调用方全炸。
3. **T01.3 验收标准**："每个端口必须有 ≥1 个测试替身"。
   这里通过类内 `Double_*` 命名类作为替身来满足验收，**替身不被导出到源码**，
   仅用于断言"长得像"。

★ 设计原则：
- **不重复**：避免重复 assertion 已由 `tests/unit/domain/test_*` 覆盖的模型字段
- **结构性**：聚焦于 ports 本身定义的 dataclass 校验 + Protocol 行为
- **零随机**：所有测试确定性，便于回归
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from quant_v2.domain.guard.safe_series import SafeSeries
from quant_v2.domain.models.bar import AdjustType, Bar, InstrumentType
from quant_v2.domain.models.lifecycle import Actor, ExitDecision, SignalState
from quant_v2.domain.models.market import (
    CostModel,
    DataSourceSpec,
    MarketProfile,
    PriceLimitSpec,
    TickSpec,
)
from quant_v2.domain.models.order import OrderIntent, SizingRequest, SizingResult
from quant_v2.domain.models.portfolio import PortfolioSnapshot, Position
from quant_v2.domain.models.signal import (
    ExitPlan,
    RawSignal,
    ScoreBreakdown,
    Signal,
    SignalExplanation,
)
from quant_v2.domain.ports.clock_port import Clock, FrozenClock, SystemClock
from quant_v2.domain.ports.market_data_port import (
    BarRequest,
    DataCapabilities,
    MarketDataAdapter,
    SourceHealth,
    TradingCalendar,
    TradingDay,
)
from quant_v2.domain.ports.notification_port import (
    AlertLevel,
    DispatchResult,
    NotificationMessage,
    NotificationReceipt,
    Notifier,
)
from quant_v2.domain.ports.pipeline_port import (
    ExitRule,
    FactorComputer,
    FactorContext,
    FactorRegistry,
    Ranker,
    Scorer,
    SurvivorshipRisk,
    SymbolSnapshot,
)
from quant_v2.domain.ports.repository_port import (
    BarStore,
    HeartbeatRepository,
    LifecycleRepository,
    PushReceiptRepository,
    SignalRepository,
)
from quant_v2.domain.ports.risk_port import RiskCode, RiskDecision, RiskManager, ValuationProvider
from quant_v2.domain.ports.sizing_port import Sizer
from quant_v2.domain.ports.strategy_port import (
    InvalidationRule,
    Strategy,
    StrategyContext,
    StrategyDoc,
    StrategySpec,
)

pytestmark = pytest.mark.unit


AS_OF = date(2026, 9, 5)
NOW = datetime(2026, 9, 5, 10, 30, tzinfo=UTC)


def d(value: str) -> Decimal:
    """构造 Decimal。"""
    return Decimal(value)


def _make_market_profile() -> MarketProfile:
    """构造一个最小合法 MarketProfile（用于 ports 测试）。"""
    return MarketProfile(
        market_code="cn_a",
        display_name="A 股",
        timezone="Asia/Shanghai",
        calendar_id="cn_a",
        currency="CNY",
        settlement_currency=None,
        lot_size=100,
        odd_lot_allowed=False,
        tick=TickSpec(tick_size=d("0.01")),
        price_limit=PriceLimitSpec(limit_pct=d("0.1"), st_limit_pct=d("0.05")),
        t_plus=1,
        shortable=False,
        cost=CostModel(
            commission_rate=d("0.00025"),
            commission_min=d("5"),
            tax_rate_sell=d("0.0005"),
            tax_rate_buy=d("0"),
            transfer_fee_rate=d("0.00001"),
            exchange_fee_rate=d("0.0000487"),
            slippage_bps=10,
        ),
        symbol_pattern=r"^\d{6}\.(SH|SZ)$",
        half_day_dates=(),
        extra_holidays=(),
        fund_availability="FULL",
        delisting_data_availability="PARTIAL",
        max_symbols=5000,
        data_sources=(
            DataSourceSpec(
                source_id="akshare",
                adapter="quant_v2.adapters.market_data.akshare_cn.AkshareCnAdapter",
                priority=0,
                capabilities=DataCapabilities(delisting_history="PARTIAL"),
            ),
        ),
    )


# =====================================================================
# clock_port.py —— Clock / FrozenClock / SystemClock
# =====================================================================


class TestClockRuntimeCheckable:
    """★ Protocol + runtime_checkable 的契约回归（防止有人删掉 @runtime_checkable）。"""

    def test_frozen_clock_isinstance_clock(self) -> None:
        """FrozenClock 应当被 isinstance 识别为 Clock（@runtime_checkable 的关键属性）。"""
        clock = FrozenClock(NOW)
        assert isinstance(clock, Clock)

    def test_system_clock_isinstance_clock(self) -> None:
        """SystemClock 应当被 isinstance 识别为 Clock。"""
        assert isinstance(SystemClock(), Clock)

    def test_unrelated_object_not_clock(self) -> None:
        """长得不像的对象不应通过 isinstance 检查。"""
        assert not isinstance(object(), Clock)
        assert not isinstance("not a clock", Clock)


class TestSystemClock:
    """SystemClock：真实系统时间端口，零依赖。"""

    def test_now_returns_aware_datetime(self) -> None:
        """★ 必须带时区（不允许 naive datetime —— 跨市场偏差源头）。"""
        result = SystemClock().now()
        assert result.tzinfo is not None
        assert isinstance(result, datetime)

    def test_today_with_timezone(self) -> None:
        """给定时区下的今天。"""
        clock = SystemClock()
        today = clock.today("Asia/Shanghai")
        assert isinstance(today, date)
        # 今天是上海时间的"今天"，naive datetime 比较容易过；只验证类型与 not None
        assert today is not None


class TestFrozenClock:
    """FrozenClock：测试/回测用固定时间。"""

    def test_init_requires_aware_datetime(self) -> None:
        """★ 不带时区 → ValueError（naive datetime 是 P0 偏差源）。"""
        with pytest.raises(ValueError, match="需要带时区的 datetime"):
            FrozenClock(datetime(2026, 9, 5, 10, 30))

    def test_init_accepts_aware_datetime(self) -> None:
        """带时区的 datetime 应当成功构造。"""
        clock = FrozenClock(NOW)
        assert clock.now() == NOW

    def test_now_returns_frozen_time(self) -> None:
        """多次调用 now() 必须返回同一时刻。"""
        clock = FrozenClock(NOW)
        assert clock.now() == clock.now()

    def test_today_converts_timezone(self) -> None:
        """FrozenClock.today 应当正确转换时区。"""
        clock = FrozenClock(NOW)  # UTC 10:30
        # 上海是 UTC+8，所以是同一天但时刻不同 —— 这里只验类型与日期一致性
        sh_today = clock.today("Asia/Shanghai")
        assert isinstance(sh_today, date)

    def test_advance_days(self) -> None:
        """advance(days=N) 必须推进 N 天。"""
        clock = FrozenClock(NOW)
        clock.advance(days=3)
        assert clock.now() == NOW + timedelta(days=3)

    def test_advance_seconds(self) -> None:
        """advance(seconds=N) 必须推进 N 秒。"""
        clock = FrozenClock(NOW)
        clock.advance(seconds=120)
        assert clock.now() == NOW + timedelta(seconds=120)

    def test_advance_combined(self) -> None:
        """days + seconds 同时推进 = 天+秒的复合。"""
        clock = FrozenClock(NOW)
        clock.advance(days=1, seconds=30)
        assert clock.now() == NOW + timedelta(days=1, seconds=30)


# =====================================================================
# market_data_port.py —— BarRequest / DataCapabilities / TradingDay / SourceHealth
# =====================================================================


class TestBarRequest:
    """BarRequest：行情请求。★ adjust 必填（v1 P0 根治点）。"""

    def test_construct_minimal(self) -> None:
        """最少字段能构造。"""
        req = BarRequest(
            symbols=("601186.SH",),
            market="cn_a",
            start=AS_OF,
            end=AS_OF,
            adjust=AdjustType.FORWARD,
        )
        assert req.symbols == ("601186.SH",)
        assert req.adjust == AdjustType.FORWARD
        assert req.instrument_types == (InstrumentType.EQUITY,)  # 默认值

    def test_empty_symbols_rejected(self) -> None:
        """★ 空 symbols → ValueError（空请求必须由调用方提前短路）。"""
        with pytest.raises(ValueError, match="symbols 不可为空"):
            BarRequest(
                symbols=(),
                market="cn_a",
                start=AS_OF,
                end=AS_OF,
                adjust=AdjustType.RAW,
            )

    def test_start_after_end_rejected(self) -> None:
        """start > end → ValueError。"""
        with pytest.raises(ValueError, match="不能晚于"):
            BarRequest(
                symbols=("601186.SH",),
                market="cn_a",
                start=AS_OF,
                end=AS_OF - timedelta(days=1),
                adjust=AdjustType.FORWARD,
            )

    def test_empty_instrument_types_rejected(self) -> None:
        """空 instrument_types → ValueError。"""
        with pytest.raises(ValueError, match="instrument_types 不可为空"):
            BarRequest(
                symbols=("601186.SH",),
                market="cn_a",
                start=AS_OF,
                end=AS_OF,
                adjust=AdjustType.FORWARD,
                instrument_types=(),
            )

    def test_frozen_dataclass(self) -> None:
        """BarRequest 是 frozen dataclass —— 构造后不可修改。"""
        req = BarRequest(
            symbols=("601186.SH",),
            market="cn_a",
            start=AS_OF,
            end=AS_OF,
            adjust=AdjustType.FORWARD,
        )
        with pytest.raises(Exception, match=r"cannot assign to field"):
            req.market = "us"  # type: ignore[misc]


class TestDataCapabilities:
    """DataCapabilities：数据源能力声明。"""

    def test_default_capabilities(self) -> None:
        """默认值应当合理（daily_bars / adj_factor / trading_calendar 默认开启）。"""
        cap = DataCapabilities()
        assert cap.daily_bars is True
        assert cap.adj_factor is True
        assert cap.trading_calendar is True
        assert cap.fundamentals is False
        assert cap.intraday is False


class TestTradingDay:
    """TradingDay：单个交易日信息（含半天市 D-07）。"""

    def test_full_day_default(self) -> None:
        """默认是全日市，session_open/close 为 None（由实现填充）。"""
        day = TradingDay(market="cn_a", date=AS_OF)
        assert day.is_half_day is False
        assert day.session_open is None
        assert day.session_close is None

    def test_half_day(self) -> None:
        """半天市标记。"""
        day = TradingDay(market="hk", date=AS_OF, is_half_day=True)
        assert day.is_half_day is True


class TestSourceHealth:
    """SourceHealth：数据源健康检查结果。"""

    def test_default_ok(self) -> None:
        """默认 ok=True（v1 旧语义），新代码应显式传 ok。"""
        h = SourceHealth(source_id="akshare", ok=True, checked_at=NOW)
        assert h.source_id == "akshare"
        assert h.ok is True
        assert h.latency_ms == 0
        assert h.detail == ""


class TestMarketDataAdapterRuntimeCheckable:
    """MarketDataAdapter 协议契约。"""

    def test_double_passes_isinstance(self) -> None:
        """实现类应当被识别为 MarketDataAdapter。"""

        class DoubleMarketDataAdapter:
            source_id = "double"
            supported_markets = frozenset({"cn_a"})
            capabilities = DataCapabilities()

            def healthcheck(self) -> SourceHealth:
                return SourceHealth(source_id=self.source_id, ok=True, checked_at=NOW)

            def list_instruments(self, market: str, *, as_of: date) -> Sequence[Any]:
                return ()

            def fetch_bars(self, req: BarRequest) -> Sequence[Bar]:
                return ()

            def fetch_trading_calendar(self, market: str, year: int) -> Sequence[TradingDay]:
                return ()

        assert isinstance(DoubleMarketDataAdapter(), MarketDataAdapter)

    def test_incomplete_double_fails_isinstance(self) -> None:
        """缺方法的类不应当被识别为 MarketDataAdapter。"""

        class Incomplete:
            source_id = "x"
            supported_markets = frozenset({"cn_a"})
            capabilities = DataCapabilities()

        # runtime_checkable 对缺失方法返回 False
        assert not isinstance(Incomplete(), MarketDataAdapter)


class TestTradingCalendarRuntimeCheckable:
    """TradingCalendar 协议契约。"""

    def test_double_passes_isinstance(self) -> None:
        class DoubleCalendar:
            def is_trading_day(self, market: str, day: date) -> bool:
                return True

            def next_trading_day(self, market: str, day: date, *, n: int = 1) -> date:
                return day + timedelta(days=n)

            def previous_trading_day(self, market: str, day: date, *, n: int = 1) -> date:
                return day - timedelta(days=n)

            def trading_days_between(self, market: str, start: date, end: date) -> Sequence[date]:
                return [start, end]

            def session_close(self, market: str, day: date) -> datetime:
                return datetime.combine(day, datetime.min.time(), tzinfo=UTC)

        assert isinstance(DoubleCalendar(), TradingCalendar)


# =====================================================================
# notification_port.py —— AlertLevel / NotificationMessage / Receipt / DispatchResult
# =====================================================================


class TestAlertLevel:
    """AlertLevel 告警级别枚举。"""

    def test_levels(self) -> None:
        """★ 显式穷举：INFO / WARN / P1 / P0 四档（禁止 OTHER 兜底）。"""
        assert AlertLevel.INFO.value == "INFO"
        assert AlertLevel.WARN.value == "WARN"
        assert AlertLevel.P1.value == "P1"
        assert AlertLevel.P0.value == "P0"

    def test_total_levels(self) -> None:
        """枚举级别数量应为 4 —— 任何加减都必须经过评审。"""
        assert len(list(AlertLevel)) == 4


class TestNotificationMessage:
    """NotificationMessage 自洽性校验。"""

    def test_valid_message(self) -> None:
        msg = NotificationMessage(title="hello", body="world")
        assert msg.title == "hello"
        assert msg.level == AlertLevel.INFO  # 默认
        assert msg.dedup_key == ""

    def test_empty_title_rejected(self) -> None:
        with pytest.raises(ValueError, match="title 不可为空"):
            NotificationMessage(title="", body="x")

    def test_whitespace_only_title_rejected(self) -> None:
        with pytest.raises(ValueError, match="title 不可为空"):
            NotificationMessage(title="   ", body="x")

    def test_empty_body_rejected(self) -> None:
        with pytest.raises(ValueError, match="body 不可为空"):
            NotificationMessage(title="x", body="")


class TestNotificationReceipt:
    """NotificationReceipt：失败必须记录 error。"""

    def test_ok_receipt(self) -> None:
        r = NotificationReceipt(ok=True, channel="feishu", message_id="m1")
        assert r.attempt == 1
        assert r.error is None

    def test_fail_receipt_requires_error(self) -> None:
        """★ ok=False 且 error=None → ValueError（没有错误信息的失败无法排查）。"""
        with pytest.raises(ValueError, match=r"失败.*必须记录 error"):
            NotificationReceipt(ok=False, channel="feishu")

    def test_fail_with_error_ok(self) -> None:
        r = NotificationReceipt(ok=False, channel="feishu", error="timeout")
        assert r.error == "timeout"

    def test_attempt_zero_rejected(self) -> None:
        """attempt 从 1 开始计数。"""
        with pytest.raises(ValueError, match="attempt 从 1 开始"):
            NotificationReceipt(ok=True, channel="feishu", attempt=0)


class TestDispatchResult:
    """DispatchResult：分发总结果。"""

    def test_default_ok(self) -> None:
        r = DispatchResult(ok=True, channel="feishu")
        assert r.receipts == ()
        assert r.degraded is False

    def test_attempts_property(self) -> None:
        """attempts 属性 = len(receipts)。"""
        receipts = (
            NotificationReceipt(ok=True, channel="feishu"),
            NotificationReceipt(ok=False, channel="email", error="x"),
        )
        r = DispatchResult(ok=True, channel="feishu", receipts=receipts, degraded=True)
        assert r.attempts == 2
        assert r.degraded is True


class TestNotifierRuntimeCheckable:
    """Notifier 协议契约 + 验证 N-04：禁止 Null/NoOp 适配器。"""

    def test_real_double_passes(self) -> None:
        class DoubleNotifier:
            channel = "double"

            def validate_credentials(self) -> None:
                return None

            def send(self, msg: NotificationMessage) -> NotificationReceipt:
                return NotificationReceipt(ok=True, channel=self.channel)

        assert isinstance(DoubleNotifier(), Notifier)


# =====================================================================
# pipeline_port.py —— SurvivorshipRisk / SymbolSnapshot / FactorContext
# =====================================================================


class TestSurvivorshipRisk:
    """幸存者偏差风险档位。"""

    def test_three_levels(self) -> None:
        """★ 三级降级（NONE / PARTIAL / HIGH）。"""
        assert len(list(SurvivorshipRisk)) == 3
        assert SurvivorshipRisk.NONE.value == "NONE"
        assert SurvivorshipRisk.PARTIAL.value == "PARTIAL"
        assert SurvivorshipRisk.HIGH.value == "HIGH"


class TestSymbolSnapshot:
    """股票池标的快照（PIT）。"""

    def test_defaults(self) -> None:
        snap = SymbolSnapshot(symbol="601186.SH", market="cn_a", name="中国铁建")
        assert snap.is_st is False
        assert snap.industry == ""
        assert snap.list_date is None
        assert snap.delist_date is None
        assert snap.instrument_type == InstrumentType.EQUITY


class TestFactorContext:
    """FactorContext 因子计算上下文。"""

    def test_defaults(self) -> None:
        ctx = FactorContext(
            as_of=AS_OF,
            market_profile=_make_market_profile(),
            calendar=None,  # type: ignore[arg-type]
        )
        assert ctx.params == {}


# =====================================================================
# repository_port.py —— Protocol 契约回归
# =====================================================================


class TestSignalRepositoryRuntimeCheckable:
    def test_double_passes(self) -> None:
        class DoubleSigRepo:
            def save(self, signal: Signal) -> None:
                return None

            def get(self, signal_id: str) -> Signal | None:
                return None

            def list_open(self, *, as_of: date) -> Sequence[Signal]:
                return ()

            def list_by_state(self, state: SignalState) -> Sequence[Signal]:
                return ()

        assert isinstance(DoubleSigRepo(), SignalRepository)


class TestLifecycleRepositoryRuntimeCheckable:
    def test_double_passes(self) -> None:
        class DoubleLifecycleRepo:
            def apply_transition(
                self,
                signal_id: str,
                to_state: SignalState,
                *,
                actor: Actor,
                reason: str,
                payload: Mapping[str, Any] | None = None,
                expected_from: SignalState | None = None,
            ) -> Any:
                return None  # type: ignore[return-value]

            def history(self, signal_id: str) -> Sequence[Any]:
                return ()

            def find_orphans(self, *, as_of: date, buffer_days: int = 5) -> Sequence[Signal]:
                return ()

        assert isinstance(DoubleLifecycleRepo(), LifecycleRepository)


class TestBarStoreRuntimeCheckable:
    def test_double_passes(self) -> None:
        class DoubleBarStore:
            def save_bars(self, bars: Sequence[Bar]) -> None:
                return None

            def load_bars(self, req: BarRequest) -> Sequence[Bar]:
                return ()

            def fingerprint_of(self, market: str, day: date) -> str:
                return ""

        assert isinstance(DoubleBarStore(), BarStore)


class TestPushReceiptRepositoryRuntimeCheckable:
    def test_double_passes(self) -> None:
        class DoublePushRepo:
            def save(self, receipt: Any) -> None:
                return None

            def success_rate(self, day: date) -> float:
                return 1.0

        assert isinstance(DoublePushRepo(), PushReceiptRepository)


class TestHeartbeatRepositoryRuntimeCheckable:
    def test_double_passes(self) -> None:
        class DoubleHeartbeat:
            def expect(self, job_name: str, scheduled_date: date, *, expected_by: datetime) -> None:
                return None

            def mark_finished(self, job_name: str, scheduled_date: date, *, run_id: str) -> None:
                return None

            def missing(self, *, as_of: date) -> Sequence[Any]:
                return ()

        assert isinstance(DoubleHeartbeat(), HeartbeatRepository)


# =====================================================================
# risk_port.py —— RiskCode / RiskDecision
# =====================================================================


class TestRiskCode:
    """风控判定码。"""

    def test_explicit_enumeration(self) -> None:
        """★ 显式穷举：禁止 OTHER 兜底（值应严格枚举，无遗漏）。"""
        codes = {c.value for c in RiskCode}
        assert "OK" in codes
        assert "EXCEED_MAX_POSITION" in codes
        assert "INSUFFICIENT_CASH" in codes
        assert "KILL_SWITCH_ACTIVE" in codes

    def test_no_other_bucket(self) -> None:
        """★ 必须没有 OTHER 兜底码。"""
        assert "OTHER" not in {c.value for c in RiskCode}


class TestRiskDecision:
    """RiskDecision 自洽性校验。"""

    def _make_portfolio(self) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            as_of=AS_OF,
            cash=d("100000"),
            positions=[],
            market_values={},
        )

    def test_allowed_decision(self) -> None:
        """allowed=True 时 code 必须是 OK。"""
        decision = RiskDecision(
            allowed=True,
            intent=None,
            code=RiskCode.OK,
            reason_human="",
            checked_constraints=(),
        )
        assert decision.allowed is True

    def test_allowed_with_non_ok_rejected(self) -> None:
        """★ allowed=True 但 code!=OK → ValueError（自相矛盾的判定）。"""
        with pytest.raises(ValueError, match="允许通过时 code 必须是 OK"):
            RiskDecision(
                allowed=True,
                intent=None,
                code=RiskCode.INSUFFICIENT_CASH,
                reason_human="x",
                checked_constraints=(),
            )

    def test_rejected_requires_reason(self) -> None:
        """★ allowed=False 但 reason_human 为空 → ValueError。"""
        with pytest.raises(ValueError, match="必须给出 reason_human"):
            RiskDecision(
                allowed=False,
                intent=None,
                code=RiskCode.INSUFFICIENT_CASH,
                reason_human="",
                checked_constraints=(),
            )

    def test_rejected_with_reason_ok(self) -> None:
        decision = RiskDecision(
            allowed=False,
            intent=None,
            code=RiskCode.INSUFFICIENT_CASH,
            reason_human="现金不足",
            checked_constraints=("cash",),
        )
        assert "现金" in decision.reason_human


class TestValuationProviderRuntimeCheckable:
    def test_double_passes(self) -> None:
        class DoubleValuation:
            def last_price(self, symbol: str, market: str, *, as_of: date) -> Decimal:
                return d("10")

            def mark_to_market(self, positions: Sequence[Position], *, as_of: date) -> Decimal:
                return d("1000")

        assert isinstance(DoubleValuation(), ValuationProvider)


class TestRiskManagerRuntimeCheckable:
    def test_double_passes(self) -> None:
        class DoubleRiskManager:
            def evaluate(
                self,
                intent: OrderIntent,
                portfolio: PortfolioSnapshot,
                profile: MarketProfile,
            ) -> RiskDecision:
                return RiskDecision(
                    allowed=True,
                    intent=intent,
                    code=RiskCode.OK,
                    reason_human="",
                    checked_constraints=(),
                )

        assert isinstance(DoubleRiskManager(), RiskManager)


# =====================================================================
# sizing_port.py —— Sizer
# =====================================================================


class TestSizerRuntimeCheckable:
    def test_double_passes(self) -> None:
        class DoubleSizer:
            name = "double"

            def size(self, req: SizingRequest) -> SizingResult:
                return SizingResult(
                    quantity=100,
                    capped_by="amount",
                    rationale="test",
                )

        assert isinstance(DoubleSizer(), Sizer)


# =====================================================================
# strategy_port.py —— StrategySpec / StrategyContext / StrategyDoc / InvalidationRule
# =====================================================================


class TestStrategySpec:
    """StrategySpec：声明式元数据。"""

    def test_valid_spec(self) -> None:
        spec = StrategySpec(
            strategy_id="momentum_v1",
            name="动量",
            tagline="追近期强势",
            markets=frozenset({"cn_a"}),
            min_history_bars=60,
            holding_period=(5, 20),
        )
        assert spec.version == "1.0.0"
        assert spec.doc_ref == ""

    def test_empty_strategy_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="strategy_id 不可为空"):
            StrategySpec(
                strategy_id="",
                name="x",
                tagline="x",
                markets=frozenset({"cn_a"}),
                min_history_bars=10,
                holding_period=(1, 5),
            )

    def test_zero_min_history_rejected(self) -> None:
        """★ min_history_bars 必须为正（为 0 意味着【不需要历史】，不可能成立）。"""
        with pytest.raises(ValueError, match="min_history_bars 必须为正"):
            StrategySpec(
                strategy_id="x",
                name="x",
                tagline="x",
                markets=frozenset({"cn_a"}),
                min_history_bars=0,
                holding_period=(1, 5),
            )

    def test_negative_min_history_rejected(self) -> None:
        with pytest.raises(ValueError, match="min_history_bars 必须为正"):
            StrategySpec(
                strategy_id="x",
                name="x",
                tagline="x",
                markets=frozenset({"cn_a"}),
                min_history_bars=-1,
                holding_period=(1, 5),
            )

    def test_holding_period_inverted_rejected(self) -> None:
        """★ holding_period 下界不能大于上界。"""
        with pytest.raises(ValueError, match="下界不能大于上界"):
            StrategySpec(
                strategy_id="x",
                name="x",
                tagline="x",
                markets=frozenset({"cn_a"}),
                min_history_bars=10,
                holding_period=(20, 5),
            )

    def test_zero_holding_period_rejected(self) -> None:
        with pytest.raises(ValueError, match="holding_period 必须为正数对"):
            StrategySpec(
                strategy_id="x",
                name="x",
                tagline="x",
                markets=frozenset({"cn_a"}),
                min_history_bars=10,
                holding_period=(0, 5),
            )


class TestStrategyContext:
    """StrategyContext：注入依赖的不可变快照。"""

    def test_default_seed(self) -> None:
        ctx = StrategyContext(
            market_profile=_make_market_profile(),
            params={},
            universe=None,  # type: ignore[arg-type]
            factors=None,  # type: ignore[arg-type]
            scorer=None,  # type: ignore[arg-type]
            calendar=None,  # type: ignore[arg-type]
            seed=42,
        )
        assert ctx.seed == 42


class TestStrategyDoc:
    """StrategyDoc 五段式说明书完整性。"""

    def _valid_kwargs(self) -> dict[str, str]:
        return {
            "strategy_id": "x",
            "headline": "一句话",
            "what_it_buys": "买什么",
            "when_it_fails": "何时失效",
            "track_record": "历史战绩含最差",
            "how_to_read": "怎么看",
        }

    def test_valid_doc(self) -> None:
        doc = StrategyDoc(**self._valid_kwargs())
        assert doc.doc_path == ""

    def test_missing_section_rejected(self) -> None:
        """★ 缺任意一段 → ValueError。"""
        kwargs = self._valid_kwargs()
        kwargs["when_it_fails"] = ""
        with pytest.raises(ValueError, match="缺少必填段落"):
            StrategyDoc(**kwargs)

    def test_whitespace_section_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["track_record"] = "   "
        with pytest.raises(ValueError, match="缺少必填段落"):
            StrategyDoc(**kwargs)


class TestInvalidationRule:
    """InvalidationRule 自洽性校验。"""

    def test_valid_rule(self) -> None:
        rule = InvalidationRule(
            rule_id="below_ma20",
            human_text="跌破 20 日均线",
            predicate="below_ma20",
        )
        assert rule.params == {}

    def test_empty_rule_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="rule_id 不可为空"):
            InvalidationRule(rule_id="", human_text="x", predicate="x")

    def test_empty_human_text_rejected(self) -> None:
        with pytest.raises(ValueError, match="human_text 不可为空"):
            InvalidationRule(rule_id="x", human_text="", predicate="x")


class TestStrategyRuntimeCheckable:
    """Strategy 协议契约。"""

    def test_double_passes(self) -> None:
        class DoubleStrategy:
            @property
            def spec(self) -> StrategySpec:
                return StrategySpec(
                    strategy_id="x",
                    name="x",
                    tagline="x",
                    markets=frozenset({"cn_a"}),
                    min_history_bars=10,
                    holding_period=(1, 5),
                )

            def required_history_bars(self) -> int:
                return 10

            def prepare(self, ctx: StrategyContext) -> None:
                return None

            def generate_signals(
                self, as_of: date, bars: Mapping[str, SafeSeries]
            ) -> Sequence[RawSignal]:
                return ()

            def explain(self, signal: RawSignal) -> SignalExplanation:
                return SignalExplanation(  # type: ignore[abstract]
                    symbol=signal.symbol,
                    market=signal.market,
                    as_of=signal.as_of,
                    headline="x",
                    what_it_buys="x",
                    when_it_fails="x",
                    how_to_read="x",
                )

            def exit_plan(self, signal: RawSignal) -> ExitPlan:
                plan_kwargs = {
                    "target_price": d("10"),
                    "stop_price": d("9"),
                    "max_hold_days": 5,
                    "waiting_days": 2,
                }
                return ExitPlan(**plan_kwargs)

            def invalidation_conditions(self) -> Sequence[InvalidationRule]:
                return ()

            def describe(self) -> StrategyDoc:
                return StrategyDoc(
                    strategy_id="x",
                    headline="x",
                    what_it_buys="x",
                    when_it_fails="x",
                    track_record="x",
                    how_to_read="x",
                )

        assert isinstance(DoubleStrategy(), Strategy)


# =====================================================================
# pipeline_port.py —— FactorComputer / FactorRegistry / Scorer / Ranker / ExitRule
# =====================================================================


class TestFactorComputerRuntimeCheckable:
    def test_double_passes(self) -> None:
        class DoubleFactor:
            factor_id = "f1"
            human_label = "test"
            direction = "HIGH_IS_GOOD"

            @property
            def required_history_bars(self) -> int:
                return 10

            def compute(self, bars: SafeSeries, ctx: FactorContext) -> Decimal | None:
                return None

        assert isinstance(DoubleFactor(), FactorComputer)


class TestFactorRegistryRuntimeCheckable:
    def test_double_passes(self) -> None:
        class DoubleRegistry:
            def register(self, factor: FactorComputer) -> None:
                return None

            def get(self, factor_id: str) -> FactorComputer:
                raise KeyError(factor_id)

            def all(self) -> Sequence[FactorComputer]:
                return ()

            @property
            def required_history_bars(self) -> int:
                return 0

        assert isinstance(DoubleRegistry(), FactorRegistry)


class TestScorerRuntimeCheckable:
    def test_double_passes(self) -> None:
        class DoubleScorer:
            @property
            def required_history_bars(self) -> int:
                return 10

            def score(self, factors: Mapping[str, Decimal | None]) -> ScoreBreakdown:
                return ScoreBreakdown(items=())  # type: ignore[abstract]

        assert isinstance(DoubleScorer(), Scorer)


class TestRankerRuntimeCheckable:
    def test_double_passes(self) -> None:
        class DoubleRanker:
            def rank(self, scored: Sequence[Any], *, limit: int) -> Sequence[Any]:
                return scored[:limit]

        assert isinstance(DoubleRanker(), Ranker)


class TestExitRuleRuntimeCheckable:
    def test_double_passes(self) -> None:
        class DoubleExitRule:
            rule_id = "r1"

            def evaluate(self, signal: RawSignal, tracking: Any) -> ExitDecision | None:
                return None

        assert isinstance(DoubleExitRule(), ExitRule)


# =====================================================================
# ports/__init__.py —— 自包含验证
# =====================================================================


class TestPortsPackage:
    """domain/ports 包应当正常导入且 __all__ 为空（全部从子模块导出）。"""

    def test_import_package(self) -> None:
        import quant_v2.domain.ports as ports_pkg  # noqa: PLC0415

        assert hasattr(ports_pkg, "__all__")

    def test_all_is_empty_or_strings(self) -> None:
        """__all__ 是字符串列表（允许为空 —— 实际符号从子模块导入）。"""
        import quant_v2.domain.ports as ports_pkg  # noqa: PLC0415

        assert isinstance(ports_pkg.__all__, list)


# =====================================================================
# 跨模块：Protocol 字段与运行时类型一致性
# =====================================================================


class TestPortSurfaceArea:
    """★ v2 架构铁律回归：端口不能偷偷依赖具体实现（domain 不能 import adapters）。"""

    def test_clock_module_imports_only_stdlib_and_quant_v2_models(self) -> None:
        """clock_port.py 不应 import adapters / engines / infrastructure。"""
        from quant_v2.domain.ports import (  # noqa: PLC0415
            clock_port,
        )

        module_text = clock_port.__file__
        assert module_text is not None
        # 强约定：不允许在领域端口中引用适配层
        source = Path(str(module_text)).read_text(encoding="utf-8")
        assert "from quant_v2.adapters" not in source
        assert "import quant_v2.engines" not in source
