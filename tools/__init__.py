"""仓库级的自研静态扫描工具包（`tools/`）。

放在 `src/` 之外是因为它**不是交付物的一部分**：
它是对交付物做检查的量具，量具不该被量具量。
"""

from __future__ import annotations

__all__ = ["arch_lint"]
