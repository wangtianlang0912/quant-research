from __future__ import annotations

from enum import Enum


class RunMode(str, Enum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class Frequency(str, Enum):
    DAY_1 = "1d"
    MIN_1 = "1m"
    MIN_5 = "5m"
    MIN_15 = "15m"
    MIN_30 = "30m"
    MIN_60 = "60m"


class AdjustType(str, Enum):
    NONE = "none"
    QFQ = "qfq"
    HFQ = "hfq"


class SignalDirection(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


class RiskAction(str, Enum):
    APPROVE = "approve"
    ADJUST = "adjust"
    REJECT = "reject"


class EventType(str, Enum):
    DATA_LOADED = "data_loaded"
    SIGNAL_GENERATED = "signal_generated"
    RISK_EVALUATED = "risk_evaluated"
    ORDER_SUBMITTED = "order_submitted"
    ORDER_FILLED = "order_filled"
    PORTFOLIO_UPDATED = "portfolio_updated"
    RUN_STARTED = "run_started"
    RUN_FINISHED = "run_finished"
    ERROR_RAISED = "error_raised"
