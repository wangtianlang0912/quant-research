from __future__ import annotations

from typing import Protocol


class NotificationPort(Protocol):
    def send_info(self, title: str, message: str) -> None:
        ...

    def send_warning(self, title: str, message: str) -> None:
        ...

    def send_error(self, title: str, message: str) -> None:
        ...
