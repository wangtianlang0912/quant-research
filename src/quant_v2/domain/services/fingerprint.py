"""数据指纹（D-04）—— `sha256(规范化行集 + source + as_of)`。

**为什么需要它**：v1 的回测结果无法复现，因为没人知道某次运行用的到底是哪份数据。
数据会变（数据源修正历史行情、补抓缺失日、切换主备源），
如果没有指纹，"这次回测收益为什么和上周不一样"永远查不出原因。

## 设计要点

1. **行集先规范化再哈希**：排序（symbol, date）+ 数值规范化（`Decimal.normalize()`），
   保证"同样的数据以不同顺序写入"得到同一个指纹。
2. **`source` 与 `as_of` 进头部**：同一批行情换源抓取 = 不同的数据集，
   指纹必须变 —— 这正是我们要发现的差异。
3. **改一行数据指纹必变**：由 `tests/unit/test_fingerprint.py` 参数化覆盖。
4. **不用 `pandas`**：领域层禁止依赖 pandas，纯标准库实现，
   代价是慢一点（A 股 5000 行 ≈ 毫秒级），完全可接受。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from quant_v2.domain.errors import FingerprintError
from quant_v2.domain.models.bar import Bar

__all__ = [
    "canonical_row",
    "fingerprint_bars",
    "fingerprint_mapping",
    "fingerprint_rows",
    "normalize_decimal",
    "verify_fingerprint",
]

# 字段分隔符用控制字符：行情里不可能出现，避免歧义拼接
_FIELD_SEP: str = "\x1f"
_ROW_SEP: str = "\x1e"


def normalize_decimal(value: Decimal) -> str:
    """把 Decimal 规范化为稳定字符串。

    `Decimal("100.00")` 与 `Decimal("100")` 必须产生同一个字符串 ——
    它们数值相等，只是精度表示不同，不该让指纹变化。
    """
    if not isinstance(value, Decimal):
        raise FingerprintError(
            f"只能是 Decimal（禁止 float 进入金额口径），收到 {type(value).__name__}"
        )
    normalized = value.normalize()
    # normalize() 对 1E+2 这类值会给出科学计数法，用 'f' 展开成定点表示
    return format(normalized, "f")


def canonical_row(row: Mapping[str, Any]) -> str:
    """把一行规范化为字符串。

    字段顺序由本函数固定，与 dict 的插入顺序无关。
    """
    parts: list[str] = []
    for key in sorted(row):
        value = row[key]
        if isinstance(value, Decimal):
            parts.append(f"{key}={normalize_decimal(value)}")
        elif isinstance(value, bool):
            parts.append(f"{key}={'1' if value else '0'}")
        elif value is None:
            parts.append(f"{key}=")
        else:
            parts.append(f"{key}={value}")
    return _FIELD_SEP.join(parts)


def fingerprint_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    source: str,
    as_of: datetime,
) -> str:
    """对规范化行集计算 sha256。

    Args:
        rows: 每行是一个字段名 → 值的映射。
        source: 数据来源标识（进头部）。
        as_of: 数据抓取时点（进头部，统一转 UTC）。

    Returns:
        十六进制 sha256 字符串。

    Raises:
        FingerprintError: 行集为空。
    """
    if not rows:
        raise FingerprintError("空数据集没有指纹：空集意味着上游没取到数据，应当被当作故障处理")

    as_of_utc = as_of.astimezone(UTC).isoformat()
    header = f"quant_v2/1{_FIELD_SEP}source={source}{_FIELD_SEP}as_of={as_of_utc}"
    body = _ROW_SEP.join(canonical_row(row) for row in rows)

    digest = hashlib.sha256()
    digest.update(header.encode("utf-8"))
    digest.update(_ROW_SEP.encode("utf-8"))
    digest.update(body.encode("utf-8"))
    return digest.hexdigest()


def fingerprint_bars(bars: Sequence[Bar], *, source: str, as_of: datetime) -> str:
    """对 `Bar` 序列计算指纹。

    只纳入"影响回测结果"的字段（`source` 与 `as_of` 由参数统一提供，不逐行纳入），
    这样同一批行情换源抓取时指纹变化可归因，而不是被逐行 source 干扰。
    """
    if not bars:
        raise FingerprintError("空数据集没有指纹")

    rows: list[Mapping[str, Any]] = [
        {
            "symbol": bar.symbol,
            "market": bar.market,
            "date": bar.date.isoformat(),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "amount": bar.amount,
            "adj_factor": bar.adj_factor,
            "currency": bar.currency,
            "is_trading_day": bar.is_trading_day,
            "is_suspended": bar.is_suspended,
            "instrument_type": bar.instrument_type.value,
        }
        for bar in bars
    ]
    # ★ 排序：保证"同样的数据以不同顺序写入"得到同一个指纹
    rows.sort(key=lambda row: (str(row["symbol"]), str(row["date"])))
    return fingerprint_rows(rows, source=source, as_of=as_of)


def fingerprint_mapping(payload: Mapping[str, Any]) -> str:
    """对配置字典计算指纹（用于 `run_manifest.config_hash`）。

    用 `sort_keys=True` 保证键顺序无关；`default=str` 让 date/Decimal 等类型安全序列化。
    ★ 不做"取不到就跳过"：序列化失败必须抛，否则配置漂移会被静默忽略。
    """
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_fingerprint(expected: str, actual: str) -> None:
    """指纹比对；不一致时抛出（**不返回 False 让调用方决定是否忽略**）。

    ★ 幂等验收（D-11）的关键：同日重跑必须指纹一致。
    如果调用方可以忽略不一致，那这个校验迟早会被忽略。
    """
    if expected != actual:
        raise FingerprintError(
            f"数据指纹不一致：期望 {expected}，实际 {actual}。"
            "同一份数据重算必须得到同一个指纹，否则说明上游写入不幂等或数据已变更。"
        )
