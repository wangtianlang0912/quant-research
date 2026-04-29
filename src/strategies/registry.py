from __future__ import annotations

from src.domain.exceptions import StrategyError
from src.domain.ports.strategy_port import StrategyPort


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, StrategyPort] = {}

    def register(self, name: str, strategy: StrategyPort) -> None:
        if not name:
            raise StrategyError("Strategy name cannot be empty.")
        self._strategies[name] = strategy

    def get(self, name: str) -> StrategyPort:
        try:
            return self._strategies[name]
        except KeyError as exc:
            raise StrategyError(f"Strategy not found: {name}") from exc

    def list_names(self) -> list[str]:
        return sorted(self._strategies.keys())
