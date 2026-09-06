"""数据指纹单测（D-04）。

★ 为什么测这个（v1 的真实教训）：
回测结果无法复现，因为没人知道某次运行用的到底是哪份数据 ——
数据源会修正历史行情、补抓缺失日、切换主备源。

本文件锁死四条不变量：

1. **顺序无关**：同样的数据以不同顺序写入 → 同一个指纹（设计要点第 1 条）
2. **敏感**：改一行数据（哪怕只改一个字段、只改精度表示）→ 指纹必变
3. **来源敏感**：`source` / `as_of` 变了 → 指纹变
4. **失败即抛**：空数据集、float 混入 → 抛 `FingerprintError`，绝不静默返回空指纹
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from itertools import permutations
from typing import Any

import pytest
from tests.conftest import FIXED_AS_OF, make_bar, make_bars

from quant_v2.domain.errors import FingerprintError
from quant_v2.domain.models.bar import Bar, InstrumentType
from quant_v2.domain.services.fingerprint import (
    canonical_row,
    fingerprint_bars,
    fingerprint_mapping,
    fingerprint_rows,
    normalize_decimal,
    verify_fingerprint,
)

pytestmark = pytest.mark.unit

SOURCE = "akshare"

# 沪京广深两个代码，用于「多标的顺序无关」用例
SYM_A = "601186.SH"
SYM_B = "600519.SH"


def two_symbol_bars() -> list[Bar]:
    """两个标的各两根，共 4 根 Bar。"""
    return [
        *make_bars(["10", "11"], symbol=SYM_A),
        *make_bars(["20", "21"], symbol=SYM_B),
    ]


class TestNormalizeDecimal:
    """数值规范化：`Decimal("100.00")` 与 `Decimal("100")` 必须同一字符串。"""

    def test_精度表示不同但数值相同(self) -> None:
        assert normalize_decimal(Decimal("100.00")) == normalize_decimal(Decimal("100"))

    def test_展开科学计数法(self) -> None:
        """.normalize() 会给出 `1E+2`，必须展开成定点 `100`。

        否则同一数值会因构造方式不同（`Decimal("1E+2")` vs `Decimal(100)`）得到不同指纹。
        """
        assert normalize_decimal(Decimal("1E+2")) == "100"

    def test_零的不同表示一致(self) -> None:
        assert normalize_decimal(Decimal("0")) == normalize_decimal(Decimal("0.000"))

    def test_小数尾部零被去掉(self) -> None:
        assert normalize_decimal(Decimal("10.50")) == "10.5"

    def test_float传入抛FingerprintError(self) -> None:
        """★ 禁止 float 进入金额口径：0.1 的二进制误差会让指纹不可复现。"""
        with pytest.raises(FingerprintError, match="禁止 float"):
            normalize_decimal(1.0)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", ["100", 100, None])
    def test_非Decimal一律抛(self, bad: Any) -> None:
        with pytest.raises(FingerprintError, match="只能是 Decimal"):
            normalize_decimal(bad)


class TestCanonicalRow:
    """行规范化：字段顺序由函数固定，与 dict 插入顺序无关。"""

    def test_键顺序无关(self) -> None:
        assert canonical_row({"a": 1, "b": 2}) == canonical_row({"b": 2, "a": 1})

    def test_键按字典序排列(self) -> None:
        assert canonical_row({"b": 2, "a": 1}) == "a=1\x1fb=2"

    def test_Decimal走规范化(self) -> None:
        assert canonical_row({"v": Decimal("1.500")}) == "v=1.5"

    def test_布尔转成一与零(self) -> None:
        """True/False 必须落成 `1`/`0`，否则 `True` 与 `1` 会撞车。"""
        assert canonical_row({"f": True}) == "f=1"
        assert canonical_row({"f": False}) == "f=0"

    def test_None落成空串(self) -> None:
        assert canonical_row({"f": None}) == "f="


class TestOrderIndependence:
    """★ 设计要点第 1 条：同样的数据以不同顺序写入 → 同一个指纹。"""

    def test_反转整个序列(self) -> None:
        bars = two_symbol_bars()
        assert fingerprint_bars(bars, source=SOURCE, as_of=FIXED_AS_OF) == fingerprint_bars(
            list(reversed(bars)), source=SOURCE, as_of=FIXED_AS_OF
        )

    @pytest.mark.parametrize("order_index", [0, 1, 2, 3, 4, 5])
    def test_任意排列同一指纹(self, order_index: int) -> None:
        """穷举 3 根 Bar 的全部 6 种排列，逐一验证。"""
        bars = make_bars(["10", "11", "12"], symbol=SYM_A)
        expected = fingerprint_bars(bars, source=SOURCE, as_of=FIXED_AS_OF)
        ordered = list(permutations(bars))[order_index]
        assert fingerprint_bars(list(ordered), source=SOURCE, as_of=FIXED_AS_OF) == expected

    def test_跨标的交错写入(self) -> None:
        """A B A B 与 A A B B 必须同指纹（排序键是 symbol+date）。"""
        a = make_bars(["10", "11"], symbol=SYM_A)
        b = make_bars(["20", "21"], symbol=SYM_B)
        interleaved = [a[0], b[0], a[1], b[1]]
        grouped = [*a, *b]
        assert fingerprint_bars(interleaved, source=SOURCE, as_of=FIXED_AS_OF) == (
            fingerprint_bars(grouped, source=SOURCE, as_of=FIXED_AS_OF)
        )


class TestSensitivity:
    """★ 改一行数据指纹必变。"""

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("symbol", "600520.SH"),
            ("market", "hk"),
            ("open", Decimal("999")),
            ("high", Decimal("999")),
            ("low", Decimal("0.01")),
            ("close", Decimal("999")),
            ("volume", Decimal("1")),
            ("amount", Decimal("1")),
            ("adj_factor", Decimal("2")),
            ("currency", "HKD"),
            ("is_trading_day", False),
            ("is_suspended", True),
            ("instrument_type", InstrumentType.INDEX),
        ],
    )
    def test_改任一纳入字段指纹必变(self, field: str, value: Any) -> None:
        bars = make_bars(["10", "11"], symbol=SYM_A)
        baseline = fingerprint_bars(bars, source=SOURCE, as_of=FIXED_AS_OF)
        mutated = list(bars)
        mutated[1] = mutated[1].model_copy(update={field: value})
        assert fingerprint_bars(mutated, source=SOURCE, as_of=FIXED_AS_OF) != baseline, (
            f"修改 {field} 后指纹未变 —— 该字段没进指纹，换源/补数会查不出来"
        )

    def test_改日期指纹变(self) -> None:
        bars = make_bars(["10", "11"], symbol=SYM_A)
        baseline = fingerprint_bars(bars, source=SOURCE, as_of=FIXED_AS_OF)
        mutated = list(bars)
        mutated[1] = make_bar(symbol=SYM_A, day=mutated[1].date + timedelta(days=30), close="11")
        assert fingerprint_bars(mutated, source=SOURCE, as_of=FIXED_AS_OF) != baseline

    def test_只改精度表示指纹不变(self) -> None:
        """`Decimal("10.00")` 与 `Decimal("10")` 是同一个数，不该让指纹变化。

        否则「源 A 返回 10.00，源 B 返回 10」会被误判成数据变更，
        交叉校验天天报假警，最后没人看。
        """
        bars = make_bars(["10", "11"], symbol=SYM_A)
        baseline = fingerprint_bars(bars, source=SOURCE, as_of=FIXED_AS_OF)
        mutated = [
            bar.model_copy(update={"close": bar.close.quantize(Decimal("0.0001"))}) for bar in bars
        ]
        assert fingerprint_bars(mutated, source=SOURCE, as_of=FIXED_AS_OF) == baseline

    def test_行数变化指纹变(self) -> None:
        short = make_bars(["10", "11"], symbol=SYM_A)
        long_ = make_bars(["10", "11", "12"], symbol=SYM_A)
        assert fingerprint_bars(short, source=SOURCE, as_of=FIXED_AS_OF) != fingerprint_bars(
            long_, source=SOURCE, as_of=FIXED_AS_OF
        )

    def test_source变了指纹变(self) -> None:
        """★ 同一批行情换源抓取 = 不同的数据集，指纹必须变。"""
        bars = two_symbol_bars()
        assert fingerprint_bars(bars, source="akshare", as_of=FIXED_AS_OF) != fingerprint_bars(
            bars, source="baostock", as_of=FIXED_AS_OF
        )

    def test_as_of变了指纹变(self) -> None:
        bars = two_symbol_bars()
        later = FIXED_AS_OF + timedelta(hours=1)
        assert fingerprint_bars(bars, source=SOURCE, as_of=FIXED_AS_OF) != fingerprint_bars(
            bars, source=SOURCE, as_of=later
        )

    def test_同一时刻不同时区指纹相同(self) -> None:
        """`as_of` 统一转 UTC：东八区 08:00 == UTC 00:00。"""
        bars = two_symbol_bars()
        shanghai = FIXED_AS_OF.astimezone(timezone(timedelta(hours=8)))
        assert fingerprint_bars(bars, source=SOURCE, as_of=FIXED_AS_OF) == fingerprint_bars(
            bars, source=SOURCE, as_of=shanghai
        )

    def test_逐行source不进指纹(self) -> None:
        """设计如此：`source` 由参数统一提供，避免被逐行 source 干扰归因。"""
        bars = two_symbol_bars()
        baseline = fingerprint_bars(bars, source=SOURCE, as_of=FIXED_AS_OF)
        mutated = [bar.model_copy(update={"source": "tencent"}) for bar in bars]
        assert fingerprint_bars(mutated, source=SOURCE, as_of=FIXED_AS_OF) == baseline


class TestRows:
    """`fingerprint_rows` 的通用行集入口。"""

    def test_空行集抛FingerprintError(self) -> None:
        """★ 空集意味着上游没取到数据，必须当故障处理，不能静默返回空指纹。"""
        with pytest.raises(FingerprintError, match="空数据集没有指纹"):
            fingerprint_rows([], source=SOURCE, as_of=FIXED_AS_OF)

    def test_空Bar序列抛FingerprintError(self) -> None:
        with pytest.raises(FingerprintError, match="空数据集没有指纹"):
            fingerprint_bars([], source=SOURCE, as_of=FIXED_AS_OF)

    def test_行内键顺序无关(self) -> None:
        rows_a = [{"symbol": SYM_A, "close": Decimal("10")}]
        rows_b = [{"close": Decimal("10"), "symbol": SYM_A}]
        assert fingerprint_rows(rows_a, source=SOURCE, as_of=FIXED_AS_OF) == fingerprint_rows(
            rows_b, source=SOURCE, as_of=FIXED_AS_OF
        )

    def test_空字符串行集不视为空(self) -> None:
        """一行「全空」也是一行数据，不该被当成空集。"""
        rows: list[dict[str, Any]] = [{"symbol": "", "close": Decimal("0")}]
        assert fingerprint_rows(rows, source=SOURCE, as_of=FIXED_AS_OF)


class TestFingerprintMapping:
    """配置字典指纹（`run_manifest.config_hash`）。"""

    def test_键顺序无关(self) -> None:
        assert fingerprint_mapping({"a": 1, "b": 2}) == fingerprint_mapping({"b": 2, "a": 1})

    def test_嵌套结构键顺序无关(self) -> None:
        left = {"x": {"a": 1, "b": [1, 2]}, "y": "z"}
        right = {"y": "z", "x": {"b": [1, 2], "a": 1}}
        assert fingerprint_mapping(left) == fingerprint_mapping(right)

    def test_改一个值指纹变(self) -> None:
        assert fingerprint_mapping({"a": 1}) != fingerprint_mapping({"a": 2})

    def test_空字典也有指纹(self) -> None:
        """配置字典允许为空（与行集不同：空配置是合法的）。"""
        assert fingerprint_mapping({}) == fingerprint_mapping({})

    def test_Decimal按字符串序列化(self) -> None:
        """`default=str` 让 Decimal/date 安全序列化，不抛异常。"""
        payload = {"rate": Decimal("0.00025"), "day": FIXED_AS_OF.date()}
        assert fingerprint_mapping(payload) == fingerprint_mapping(payload)


class TestVerifyFingerprint:
    """指纹比对：不一致必须**抛**，不返回 False。"""

    def test_一致时不抛(self) -> None:
        bars = two_symbol_bars()
        digest = fingerprint_bars(bars, source=SOURCE, as_of=FIXED_AS_OF)
        assert verify_fingerprint(digest, digest) is None

    def test_不一致时抛而不是返回False(self) -> None:
        """★ 返回 False 的校验早晚会被调用方忽略 —— 那就等于没有校验。"""
        with pytest.raises(FingerprintError, match="数据指纹不一致"):
            verify_fingerprint("a" * 64, "b" * 64)

    def test_异常信息带上两个指纹便于排查(self) -> None:
        with pytest.raises(FingerprintError) as info:
            verify_fingerprint("expected", "actual")
        message = str(info.value)
        assert "expected" in message
        assert "actual" in message

    def test_重算同一批数据指纹稳定(self) -> None:
        """幂等验收（D-11）：同日重跑必须指纹一致。"""
        bars = two_symbol_bars()
        first = fingerprint_bars(bars, source=SOURCE, as_of=FIXED_AS_OF)
        second = fingerprint_bars(list(reversed(bars)), source=SOURCE, as_of=FIXED_AS_OF)
        verify_fingerprint(first, second)

    def test_指纹为六十四位十六进制(self) -> None:
        digest = fingerprint_bars(two_symbol_bars(), source=SOURCE, as_of=FIXED_AS_OF)
        assert len(digest) == 64
        assert set(digest) <= set("0123456789abcdef")


def test_as_of为朴素时间也不抛() -> None:
    """朴素 datetime 会被 `astimezone(UTC)` 按本地时区解释，不抛异常。

    ⚠ 这是当前行为的锁定：生产上必须传带时区的 as_of，
    否则同一份数据在 UTC+8 与 UTC+0 的机器上会算出不同指纹。
    """
    naive = datetime(2026, 9, 5, 0, 0, 0)
    digest = fingerprint_bars(two_symbol_bars(), source=SOURCE, as_of=naive)
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")
