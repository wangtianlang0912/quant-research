"""BaostockCnAdapter 单元测试（FakeWorker 注入，零子进程零网络）。

★ 测试策略：适配器职责是**符号归一化、因子合并、Bar 组装、错误放大**，
这些全是纯逻辑 —— 用 FakeWorker（直接返回预设 WorkerResult）即可覆盖；
子进程与网络路径在 test_subprocess_worker.py 用真实子进程测过。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from quant_v2.adapters.market_data.baostock_cn import (
    BaostockCnAdapter,
    from_baostock_code,
    merge_adjust_factors,
    to_baostock_code,
)
from quant_v2.adapters.market_data.subprocess_worker import WorkerCall, WorkerResult
from quant_v2.domain.errors import SourceUnavailableError
from quant_v2.domain.models.bar import AdjustType
from quant_v2.domain.ports.market_data_port import BarRequest

pytestmark = pytest.mark.unit

DAY = date(2024, 6, 3)
NEXT = date(2024, 6, 4)
FIXED_AS_OF = datetime(2024, 6, 5, 0, 0, 0, tzinfo=UTC)


class FakeWorker:
    """按 call_id 返回预设结果的假 SubprocessWorker。"""

    def __init__(self, results: dict[str, WorkerResult]) -> None:
        self._results = results
        self.batches: list[Sequence[WorkerCall]] = []
        self.checkpoint_keys: list[str | None] = []

    def run(self, call: WorkerCall) -> WorkerResult:
        return self.run_batch([call])[call.call_id]

    def run_batch(
        self,
        calls: Sequence[WorkerCall],
        *,
        checkpoint_key: str | None = None,
    ) -> dict[str, WorkerResult]:
        self.batches.append(calls)
        self.checkpoint_keys.append(checkpoint_key)
        return {c.call_id: self._results[c.call_id] for c in calls if c.call_id in self._results}


_MISSING: Any = object()


def _ok(first: Any, second: Any = _MISSING) -> WorkerResult:
    """构造成功 WorkerResult。兼容两种调用：`_ok(payload)` / `_ok(call_id, payload)`。

    （FakeWorker 按 dict key 而非 result.call_id 索引，单参形态的 call_id 用占位即可。）
    """
    if second is _MISSING:
        return WorkerResult(call_id="<test>", ok=True, payload=first, error=None)
    return WorkerResult(call_id=first, ok=True, payload=second, error=None)


def _fail(call_id: str, error: str = "boom") -> WorkerResult:
    return WorkerResult(call_id=call_id, ok=False, payload=None, error=error)


def _bar_row(
    day: str,
    *,
    code: str = "sh.600000",
    open_: str = "10.0",
    high: str = "11.0",
    low: str = "9.5",
    close: str = "10.5",
    preclose: str = "10.0",
    volume: str = "1000",
    amount: str = "10500",
    tradestatus: str = "1",
) -> dict[str, str]:
    return {
        "date": day,
        "code": code,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "preclose": preclose,
        "volume": volume,
        "amount": amount,
        "tradestatus": tradestatus,
    }


def _factor_row(day: str, back: str) -> dict[str, str]:
    return {"dividOperateDate": day, "backAdjustFactor": back}


def _request(symbols: Sequence[str]) -> BarRequest:
    return BarRequest(
        symbols=tuple(symbols),
        market="cn_a",
        start=DAY,
        end=NEXT,
        adjust=AdjustType.RAW,
    )


# ============================================================================
# 符号归一化
# ============================================================================


def test_归一化代码_转_baostock_代码() -> None:
    assert to_baostock_code("600000.SH") == "sh.600000"
    assert to_baostock_code("000001.SZ") == "sz.000001"
    with pytest.raises(ValueError, match="只支持"):
        to_baostock_code("830001.BJ")  # 北交所：baostock 不覆盖


def test_baostock_代码_转_归一化代码() -> None:
    assert from_baostock_code("sh.600000") == "600000.SH"
    assert from_baostock_code("sz.000001") == "000001.SZ"
    with pytest.raises(ValueError, match="只支持"):
        from_baostock_code("bj.830001")


# ============================================================================
# 因子合并（M-5）
# ============================================================================


def test_因子合并_无除权事件_因子为1() -> None:
    assert merge_adjust_factors([], DAY) == Decimal("1")


def test_因子合并_取最近一条小于等于当日的事件() -> None:
    rows = [_factor_row("2024-01-01", "2.5"), _factor_row("2024-06-01", "4.5")]
    assert merge_adjust_factors(rows, date(2024, 6, 1)) == Decimal("4.5")
    assert merge_adjust_factors(rows, date(2024, 5, 31)) == Decimal("2.5")


def test_因子合并_早于首个除权日_因子为1() -> None:
    rows = [_factor_row("2024-06-01", "4.5")]
    assert merge_adjust_factors(rows, date(2024, 5, 31)) == Decimal("1")


def test_因子合并_乱序输入_结果稳定() -> None:
    """事件表顺序是源的实现细节，不是契约 —— 必须防御性排序。"""
    rows = [_factor_row("2024-06-01", "4.5"), _factor_row("2024-01-01", "2.5")]
    assert merge_adjust_factors(rows, date(2024, 6, 2)) == Decimal("4.5")


def test_因子合并_非法因子值_抛错() -> None:
    rows = [_factor_row("2024-01-01", "not-a-number")]
    with pytest.raises(ValueError, match="不是合法数值"):
        merge_adjust_factors(rows, DAY)


# ============================================================================
# fetch_bars
# ============================================================================


def test_fetch_bars_组装Bar_并合并有效因子() -> None:
    results = {
        "bars:600000.SH:2024-06-03:2024-06-04": _ok(
            "bars:600000.SH:2024-06-03:2024-06-04",
            [
                _bar_row("2024-06-03"),
                _bar_row("2024-06-04", open_="11.0", high="12.5", low="10.8", close="12.0"),
            ],
        ),
        "factors:600000.SH:2024-06-03:2024-06-04": _ok(
            "factors:600000.SH:2024-06-03:2024-06-04",
            [_factor_row("2024-06-03", "2.5")],
        ),
    }
    adapter = BaostockCnAdapter(worker=FakeWorker(results), as_of=FIXED_AS_OF)
    bars = adapter.fetch_bars(_request(["600000.SH"]))
    assert len(bars) == 2
    first, second = bars
    assert first.symbol == "600000.SH"
    assert first.close == Decimal("10.5")
    assert first.adj_factor == Decimal("2.5")  # 除权事件日当天即生效（dividOperateDate ≤ D）
    assert second.close == Decimal("12.0")
    assert second.adj_factor == Decimal("2.5")
    assert first.as_of == FIXED_AS_OF
    assert first.source == "baostock"


def test_fetch_bars_原始价乘因子等于后复权价() -> None:
    """D-03 核心恒等式：raw_close × adj_factor == hfq_close。"""
    results = {
        "bars:600000.SH:2024-06-03:2024-06-04": _ok(
            [_bar_row("2024-06-04", open_="11.8", high="12.5", low="11.2", close="12.0")]
        ),
        "factors:600000.SH:2024-06-03:2024-06-04": _ok([_factor_row("2024-01-01", "3.0")]),
    }
    adapter = BaostockCnAdapter(worker=FakeWorker(results), as_of=FIXED_AS_OF)
    (bar,) = adapter.fetch_bars(_request(["600000.SH"]))
    assert bar.close * bar.adj_factor == Decimal("12.0") * Decimal("3.0")


def test_fetch_bars_停牌日_空价格用前收平铺() -> None:
    row = _bar_row(
        "2024-06-03",
        open_="",
        high="",
        low="",
        close="",
        preclose="10.0",
        volume="0",
        amount="0",
        tradestatus="0",
    )
    results = {
        "bars:600000.SH:2024-06-03:2024-06-04": _ok([row]),
        "factors:600000.SH:2024-06-03:2024-06-04": _ok([]),
    }
    adapter = BaostockCnAdapter(worker=FakeWorker(results), as_of=FIXED_AS_OF)
    (bar,) = adapter.fetch_bars(_request(["600000.SH"]))
    assert bar.is_suspended is True
    assert bar.close == Decimal("10.0")  # 前收平铺（Bar 校验对停牌行不生效）


def test_fetch_bars_正常日空价格_抛错不兜底() -> None:
    """errors.py 设计原则：该抛的地方绝不编造默认价（v1 风控 100 元估值之鉴）。"""
    row = _bar_row("2024-06-03", close="", preclose="")
    results = {
        "bars:600000.SH:2024-06-03:2024-06-04": _ok([row]),
        "factors:600000.SH:2024-06-03:2024-06-04": _ok([]),
    }
    adapter = BaostockCnAdapter(worker=FakeWorker(results), as_of=FIXED_AS_OF)
    with pytest.raises(ValueError, match="禁止编造价格"):
        adapter.fetch_bars(_request(["600000.SH"]))


def test_fetch_bars_查询失败_抛_SourceUnavailableError() -> None:
    results = {
        "bars:600000.SH:2024-06-03:2024-06-04": _fail("bars:600000.SH:2024-06-03:2024-06-04"),
        "factors:600000.SH:2024-06-03:2024-06-04": _ok([]),
    }
    adapter = BaostockCnAdapter(worker=FakeWorker(results), as_of=FIXED_AS_OF)
    with pytest.raises(SourceUnavailableError, match=r"600000\.SH 查询失败"):
        adapter.fetch_bars(_request(["600000.SH"]))


def test_fetch_bars_结果缺失_抛_SourceUnavailableError() -> None:
    """FakeWorker 没返回 bars call 的结果 → 必须炸，禁止静默少一只股票。"""
    adapter = BaostockCnAdapter(worker=FakeWorker({}), as_of=FIXED_AS_OF)
    with pytest.raises(SourceUnavailableError, match="查询结果缺失"):
        adapter.fetch_bars(_request(["600000.SH"]))


def test_fetch_bars_非cn_a市场_拒绝() -> None:
    adapter = BaostockCnAdapter(worker=FakeWorker({}), as_of=FIXED_AS_OF)
    req = BarRequest(
        symbols=("0700.HK",),
        market="hk",
        start=DAY,
        end=NEXT,
        adjust=AdjustType.RAW,
    )
    with pytest.raises(ValueError, match="只服务 cn_a"):
        adapter.fetch_bars(req)


def test_fetch_bars_多标的_批量下发且checkpoint_key稳定() -> None:
    """每标的 2 个 call 一次下发；checkpoint key 由内容摘要派生（跨进程稳定）。"""
    results = {
        "bars:600000.SH:2024-06-03:2024-06-04": _ok([_bar_row("2024-06-03")]),
        "factors:600000.SH:2024-06-03:2024-06-04": _ok([]),
        "bars:000001.SZ:2024-06-03:2024-06-04": _ok(
            "bars:000001.SZ:2024-06-03:2024-06-04",
            [_bar_row("2024-06-03", code="sz.000001")],
        ),
        "factors:000001.SZ:2024-06-03:2024-06-04": _ok([]),
    }
    worker = FakeWorker(results)
    adapter = BaostockCnAdapter(worker=worker, as_of=FIXED_AS_OF)
    bars = adapter.fetch_bars(_request(["600000.SH", "000001.SZ"]))
    assert len(bars) == 2
    assert {b.symbol for b in bars} == {"600000.SH", "000001.SZ"}
    assert len(worker.batches) == 1
    assert len(worker.batches[0]) == 4  # 2 标的 × (bars + factors)
    key = worker.checkpoint_keys[0]
    assert key is not None
    assert key.startswith("baostock_bars_2024-06-03_2024-06-04_")
    # 同一请求再次构造 → key 相同（断点续跑的前提，内建 hash() 做不到）
    worker2 = FakeWorker(results)
    adapter2 = BaostockCnAdapter(worker=worker2, as_of=FIXED_AS_OF)
    adapter2.fetch_bars(_request(["600000.SH", "000001.SZ"]))
    assert worker2.checkpoint_keys[0] == key


# ============================================================================
# healthcheck
# ============================================================================


def test_healthcheck_成功() -> None:
    results = {
        "healthcheck-x": _ok([_factor_row("2020-01-02", "1.0")]),
    }

    class HealthWorker(FakeWorker):
        def run(self, call: WorkerCall) -> WorkerResult:
            # healthcheck 的 call_id 含时间戳 → 按前缀匹配
            assert call.kind == "factors"
            return _ok([])

    adapter = BaostockCnAdapter(worker=HealthWorker(results), as_of=FIXED_AS_OF)
    health = adapter.healthcheck()
    assert health.source_id == "baostock"
    assert health.reachable is True
    assert health.latency_s is not None and health.latency_s >= 0


def test_healthcheck_源不可达_返回_False_而非抛错() -> None:
    """失败必须可达编排层（D-10：降级决策与告警在编排层统一做）。"""

    class UnavailableWorker(FakeWorker):
        def run(self, call: WorkerCall) -> WorkerResult:
            raise SourceUnavailableError("连续 2 次失败")

    adapter = BaostockCnAdapter(worker=UnavailableWorker({}), as_of=FIXED_AS_OF)
    health = adapter.healthcheck()
    assert health.reachable is False
    assert "连续 2 次失败" in health.detail


def test_healthcheck_查询级失败_也判不可达() -> None:
    class FailingWorker(FakeWorker):
        def run(self, call: WorkerCall) -> WorkerResult:
            return _fail("hc", error="error_code=10001")

    adapter = BaostockCnAdapter(worker=FailingWorker({}), as_of=FIXED_AS_OF)
    health = adapter.healthcheck()
    assert health.reachable is False
    assert "10001" in health.detail
