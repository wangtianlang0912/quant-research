from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from src.domain.exceptions import ConfigError
from src.domain.ports.config_port import ConfigPort


@dataclass
class DictConfig(ConfigPort):
    values: dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, os.getenv(key, default))

    def require(self, key: str) -> Any:
        value = self.get(key)
        if value is None:
            raise ConfigError(f"Missing required config: {key}")
        return value
