"""领域数据契约 —— 不可变，三市场共用同一套。

全部为 Pydantic v2 的 `frozen=True, strict=True, extra="forbid"` 模型：

- `frozen`：契约对象一旦构造就不可改。可变的契约等于没有契约。
- `strict`：禁止隐式类型转换。`Decimal("1.5")` 传成 `1.5`（float）必须直接报错，
  否则浮点会在最不经意的地方渗进金额计算。
- `extra="forbid"`：字段拼错必须报错，而不是被静默丢弃。

**全程 Decimal**：金额与价格一律 `Decimal`，浮点只允许出现在绘图与统计展示层（ARCH013）。
"""

from __future__ import annotations

__all__: list[str] = []
