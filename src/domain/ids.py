from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RunId:
    value: str


@dataclass(frozen=True)
class StrategyId:
    value: str


@dataclass(frozen=True)
class SignalId:
    value: str


@dataclass(frozen=True)
class OrderId:
    value: str


@dataclass(frozen=True)
class BrokerOrderId:
    value: str | None = None
