from __future__ import annotations

from typing import Any, Protocol


class ConfigPort(Protocol):
    def get(self, key: str, default: Any = None) -> Any:
        ...

    def require(self, key: str) -> Any:
        ...
