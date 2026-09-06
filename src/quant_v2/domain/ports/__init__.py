"""领域端口 —— 全部外部能力的 Protocol 定义。

★ **全部用 `Protocol`，不用 ABC**（v1 混用两者，是设计不一致的源头之一）。

选 Protocol 而不是 ABC 的三个理由：

1. **结构化子类型**：实现类不需要继承任何基类，
   测试替身只要"长得像"就能用，不需要 import 基类。
2. **`@runtime_checkable`**：可以在测试里 `isinstance(double, Sizer)` 断言
   "这个替身真的实现了端口契约"—— 由 `tests/unit/test_ports_have_doubles.py` 强制。
3. **依赖方向天然向下**：端口在领域层，实现在适配层，适配层 import 端口，
   领域层完全不知道谁实现了自己。

**每个端口必须有 ≥1 个测试替身**（`tests/doubles/`）—— 这是 T01.3 的验收标准。
端口若没有替身，说明没人真的用过它，那它大概率是过度设计。
"""

from __future__ import annotations

__all__: list[str] = []
