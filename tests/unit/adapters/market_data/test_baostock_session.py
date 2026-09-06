"""BaostockSession / child_main 单元测试（fake bs 模块注入，零真实网络）。

★ 测试策略：`BaostockSession(bs=fake)` 注入假模块 —— 子进程侧逻辑
（adjustflag=3 纪律、因子裁剪、延迟监控、会话重建判定、JSON-lines 循环）
全部可以在本进程内验证，不需要 spawn 真实子进程（那在 test_subprocess_worker.py）。
"""

from __future__ import annotations

import io
import json
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from quant_v2.adapters.market_data.subprocess_worker import (
    BaostockSession,
    WorkerCall,
    child_main,
)

pytestmark = pytest.mark.unit

DAY = date(2024, 6, 3)
NEXT = date(2024, 6, 4)


# ============================================================================
# fake baostock 模块
# ============================================================================


class _FakeResultSet:
    """baostock 结果集的最小仿真：error_code / fields / next / get_row_data。"""

    def __init__(self, rows: list[list[str]], fields: list[str], error_code: str = "0") -> None:
        self.error_code = error_code
        self.error_msg = "fake error" if error_code != "0" else ""
        self.fields = fields
        self._rows = list(rows)
        self._index = 0

    def next(self) -> bool:
        if self._index < len(self._rows):
            self._index += 1
            return True
        return False

    def get_row_data(self) -> list[str]:
        return self._rows[self._index - 1]


BAR_FIELDS = [
    "date",
    "code",
    "open",
    "high",
    "low",
    "close",
    "preclose",
    "volume",
    "amount",
    "tradestatus",
]
FACTOR_FIELDS = [
    "code",
    "dividOperateDate",
    "foreAdjustFactor",
    "backAdjustFactor",
    "adjustFactor",
]

# query_all_stock 返回的三列（M-20 实测：只有这三列）
ALL_STOCK_FIELDS = ["code", "tradeStatus", "code_name"]

# query_trade_dates 返回的两列
TRADE_DATE_FIELDS = ["calendar_date", "is_trading_day"]

# 一行标准日线（10 列与 BAR_FIELDS 一一对应）
_STD_BAR_ROW = [
    "2024-06-03",
    "sh.600000",
    "10",
    "11",
    "9",
    "10.5",
    "10",
    "1000",
    "10500",
    "1",
]


class FakeBs:
    """记录调用参数的 baostock 假模块。"""

    def __init__(
        self,
        *,
        bar_rows: list[list[str]] | None = None,
        factor_rows: list[list[str]] | None = None,
        all_stock_rows: list[list[str]] | None = None,
        trade_date_rows: list[list[str]] | None = None,
        login_error: str = "0",
        query_error: str = "0",
        fail_login: bool = False,
    ) -> None:
        self.bar_rows = bar_rows or []
        self.factor_rows = factor_rows or []
        self.all_stock_rows = all_stock_rows or []
        self.trade_date_rows = trade_date_rows or []
        self.login_error = login_error
        self.query_error = query_error
        self.fail_login = fail_login
        self.bars_calls: list[dict[str, Any]] = []
        self.factor_calls: list[dict[str, Any]] = []
        self.all_stock_calls: list[dict[str, Any]] = []
        self.trade_dates_calls: list[dict[str, Any]] = []
        self.login_count = 0
        self.logout_count = 0

    def login(self) -> Any:
        self.login_count += 1
        if self.fail_login:
            return SimpleNamespace(error_code="1", error_msg="网络不通")
        return SimpleNamespace(error_code="0", error_msg="")

    def logout(self) -> None:
        self.logout_count += 1

    def query_history_k_data_plus(
        self,
        code: str,
        fields: str,
        *,
        start_date: str,
        end_date: str,
        frequency: str,
        adjustflag: str,
    ) -> _FakeResultSet:
        self.bars_calls.append(
            {
                "code": code,
                "fields": fields,
                "start": start_date,
                "end": end_date,
                "frequency": frequency,
                "adjustflag": adjustflag,
            }
        )
        return _FakeResultSet(self.bar_rows, fields.split(","), error_code=self.query_error)

    def query_adjust_factor(self, *, code: str, start_date: str, end_date: str) -> _FakeResultSet:
        self.factor_calls.append({"code": code, "start": start_date, "end": end_date})
        return _FakeResultSet(self.factor_rows, FACTOR_FIELDS, error_code=self.query_error)

    def query_all_stock(self, *, day: str) -> _FakeResultSet:
        self.all_stock_calls.append({"day": day})
        return _FakeResultSet(self.all_stock_rows, ALL_STOCK_FIELDS, error_code=self.query_error)

    def query_trade_dates(self, *, start_date: str, end_date: str) -> _FakeResultSet:
        self.trade_dates_calls.append({"start": start_date, "end": end_date})
        return _FakeResultSet(self.trade_date_rows, TRADE_DATE_FIELDS, error_code=self.query_error)


def _make_session(fake: FakeBs, **kwargs: Any) -> BaostockSession:
    return BaostockSession(bs=fake, **kwargs)


# ============================================================================
# 查询纪律（M-3 / M-5）
# ============================================================================


def test_日线查询_只允许_adjustflag_3() -> None:
    """★ M-3 回归：adjustflag=1/2 在退市股上无限挂起，必须恒为 '3'。"""
    fake = FakeBs()
    session = _make_session(fake)
    session.login()
    session.query_daily_bars("sh.600000", DAY, NEXT)
    assert fake.bars_calls[0]["adjustflag"] == "3"
    assert fake.bars_calls[0]["frequency"] == "d"


def test_日线查询_行按_fields_命名返回() -> None:
    fake = FakeBs(bar_rows=[_STD_BAR_ROW])
    session = _make_session(fake)
    rows = session.query_daily_bars("sh.600000", DAY, DAY)
    assert rows == [
        {
            "date": "2024-06-03",
            "code": "sh.600000",
            "open": "10",
            "high": "11",
            "low": "9",
            "close": "10.5",
            "preclose": "10",
            "volume": "1000",
            "amount": "10500",
            "tradestatus": "1",
        }
    ]


def test_因子查询_只保留_dividOperateDate_与_backAdjustFactor() -> None:
    """★ M-5 回归：foreAdjustFactor / adjustFactor 一律丢弃，防口径混用。"""
    fake = FakeBs(
        factor_rows=[
            ["sh.600000", "2024-01-01", "1.5", "2.5", "9.9"],
            ["sh.600000", "2024-06-01", "3.5", "4.5", "8.8"],
        ]
    )
    session = _make_session(fake)
    rows = session.query_adjust_factors("sh.600000", DAY, NEXT)
    assert rows == [
        {"dividOperateDate": "2024-01-01", "backAdjustFactor": "2.5"},
        {"dividOperateDate": "2024-06-01", "backAdjustFactor": "4.5"},
    ]


def test_查询失败_error_code_非0_必须抛错而非返回空() -> None:
    """空结果会被上游当成'该标的无数据'，掩盖真实故障。"""
    fake = FakeBs(query_error="10001")
    session = _make_session(fake)
    with pytest.raises(RuntimeError, match=r"10001|fake error"):
        session.query_daily_bars("sh.600000", DAY, DAY)


# ============================================================================
# 生命周期
# ============================================================================


def test_login_失败抛_RuntimeError() -> None:
    fake = FakeBs(fail_login=True)
    session = _make_session(fake)
    with pytest.raises(RuntimeError, match="login 失败"):
        session.login()


def test_logout_在_login_失败后调用是安全的() -> None:
    fake = FakeBs(fail_login=True)
    session = _make_session(fake)
    with pytest.raises(RuntimeError):
        session.login()
    session.logout()  # 未登录成功 → 不应炸
    assert fake.logout_count == 0


def test_惰性导入_构造时不触碰_baostock() -> None:
    """父进程可以安全 import 本模块 —— 构造 Session 不触发 baostock import。"""
    session = BaostockSession()
    assert session._bs is None  # 只有子进程首次查询时才会 import（ARCH014 隔离的前提）
    assert session.queries == 0


# ============================================================================
# 会话健康度（M-18）
# ============================================================================


def test_查询计数_随查询递增() -> None:
    fake = FakeBs()
    session = _make_session(fake)
    session.login()
    session.query_daily_bars("sh.600000", DAY, DAY)
    session.query_adjust_factors("sh.600000", DAY, DAY)
    assert session.queries == 2


def test_跑满_max_session_queries_应重建() -> None:
    fake = FakeBs()
    session = _make_session(fake, max_session_queries=2)
    session.login()
    session.query_daily_bars("sh.600000", DAY, DAY)
    assert session.should_rebuild() is None
    session.query_adjust_factors("sh.600000", DAY, DAY)
    assert session.should_rebuild() == "max_queries"


def test_延迟劣化_超基线2点5倍应重建() -> None:
    """基线（前 5 次）0.1s，滑动窗口均值被慢查询拉到 >0.25s → degradation。"""
    fake = FakeBs()
    session = _make_session(fake, baseline_queries=5, window_size=10, degrade_ratio=2.5)
    session._latencies.extend([0.1] * 5)
    assert session.degraded is False
    session._latencies.extend([1.0] * 5)  # 窗口均值 = (0.1×5 + 1.0×5)/10 = 0.55 > 0.25
    assert session.degraded is True
    assert session.should_rebuild() == "degradation"


def test_基线未建立时_不判劣化() -> None:
    fake = FakeBs()
    session = _make_session(fake, baseline_queries=5)
    session._latencies.extend([100.0] * 3)  # 样本不足 5 个
    assert session.degraded is False


# ============================================================================
# child_main：JSON-lines 循环（进程内驱动，stdout 用 StringIO 捕获）
# ============================================================================


def _run_child(fake: FakeBs, request_lines: list[str], **kwargs: Any) -> tuple[int, list[dict]]:
    """在本进程内跑 child_main，返回 (exit_code, 事件列表)。"""
    stdout = io.StringIO()
    stdin = io.StringIO("".join(line + "\n" for line in request_lines))

    def factory() -> BaostockSession:
        return BaostockSession(bs=fake, **kwargs)

    code = child_main(stdin=stdin, stdout=stdout, session_factory=factory)
    events = [json.loads(line) for line in stdout.getvalue().splitlines()]
    return code, events


def _bar_call(call_id: str = "c1") -> dict[str, str]:
    return {
        "id": call_id,
        "kind": "bars",
        "symbol": "sh.600000",
        "start": DAY.isoformat(),
        "end": DAY.isoformat(),
    }


def test_child_正常批次_事件序列完整() -> None:
    fake = FakeBs(bar_rows=[_STD_BAR_ROW])
    code, events = _run_child(fake, [json.dumps({"calls": [_bar_call()], "pacing_s": 0})])
    assert code == 0
    kinds = [e["event"] for e in events]
    assert kinds == ["ready", "query_start", "result", "batch_done"]
    assert events[0]["pid"] > 0
    result = events[2]
    assert result["ok"] is True
    assert result["id"] == "c1"
    assert result["payload"][0]["close"] == "10.5"


def test_child_单call失败_不炸整批() -> None:
    fake = FakeBs(query_error="10001")
    request = json.dumps({"calls": [_bar_call("bad"), _bar_call("good")], "pacing_s": 0})
    # fake 对所有查询都报错；good 也失败但批必须正常走完
    code, events = _run_child(fake, [request])
    assert code == 0
    results = [e for e in events if e["event"] == "result"]
    assert len(results) == 2
    assert all(e["ok"] is False and e["error"] for e in results)
    assert events[-1]["event"] == "batch_done"


def test_child_跑满查询数_批末发_session_end() -> None:
    fake = FakeBs()
    request = json.dumps({"calls": [_bar_call("a"), _bar_call("b")], "pacing_s": 0})
    code, events = _run_child(fake, [request] * 3, max_session_queries=4)
    # 前两批共 4 次查询；第三批开始前 should_rebuild 在批末判定：
    # 批 1（2 次）批末 queries=2 <4 继续；批 2（2 次）批末 queries=4 → session_end
    kinds = [e["event"] for e in events]
    assert "session_end" in kinds
    session_end = next(e for e in events if e["event"] == "session_end")
    assert session_end["reason"] == "max_queries"
    assert session_end["queries"] == 4
    assert kinds[-1] == "session_end"
    assert code == 0


def test_child_login失败_发_fatal_退出码1() -> None:
    fake = FakeBs(fail_login=True)
    code, events = _run_child(fake, [json.dumps({"calls": [_bar_call()], "pacing_s": 0})])
    assert code == 1
    assert events == [
        {
            "event": "fatal",
            "error": "login failed: RuntimeError('baostock login 失败: 网络不通')",
        }
    ]


def test_child_坏请求行_发_fatal() -> None:
    fake = FakeBs()
    code, events = _run_child(fake, ["not-json{{"])
    assert code == 1
    assert events[-1]["event"] == "fatal"
    assert "bad request line" in events[-1]["error"]


def test_child_未知kind_该call失败但不炸批() -> None:
    fake = FakeBs()
    bad_call = {
        "id": "x1",
        "kind": "unknown",
        "symbol": "sh.600000",
        "start": DAY.isoformat(),
        "end": DAY.isoformat(),
    }
    code, events = _run_child(fake, [json.dumps({"calls": [bad_call], "pacing_s": 0})])
    assert code == 0
    result = next(e for e in events if e["event"] == "result")
    assert result["ok"] is False
    assert "未知 call.kind" in result["error"]


def test_child_收尾时_logout() -> None:
    fake = FakeBs()
    _run_child(fake, [json.dumps({"calls": [_bar_call()], "pacing_s": 0})])
    assert fake.login_count == 1
    assert fake.logout_count == 1


# ============================================================================
# WorkerCall 序列化契约
# ============================================================================


def test_WorkerCall_序列化往返() -> None:
    call = WorkerCall(call_id="id-1", kind="bars", symbol="sh.600000", start=DAY, end=NEXT)
    assert WorkerCall.from_payload(call.to_payload()) == call


# ============================================================================
# T02.5：all_stock / trade_dates（PIT 池配套）
# ============================================================================


def test_query_all_stock_日快照透传() -> None:
    """★ M-20：只透传 code/tradeStatus/code_name 三列原始行，解析在适配器。"""
    fake = FakeBs(
        all_stock_rows=[
            ["sh.600000", "1", "浦发银行"],
            ["sh.000001", "1", "上证综指"],  # 指数也在快照里（过滤是适配器的活）
        ]
    )
    session = _make_session(fake)
    rows = session.query_all_stock(DAY)
    assert fake.all_stock_calls == [{"day": DAY.isoformat()}]
    assert rows == [
        {"code": "sh.600000", "tradeStatus": "1", "code_name": "浦发银行"},
        {"code": "sh.000001", "tradeStatus": "1", "code_name": "上证综指"},
    ]


def test_query_all_stock_错误码抛错不返回空() -> None:
    """error_code != 0 → 抛错（空结果会掩盖真实故障，M-19 同款陷阱）。"""
    fake = FakeBs(query_error="10001")
    session = _make_session(fake)
    with pytest.raises(RuntimeError, match="all_stock"):
        session.query_all_stock(DAY)


def test_query_trade_dates_区间透传与过滤前原始行() -> None:
    fake = FakeBs(
        trade_date_rows=[
            ["2024-06-01", "0"],  # 周六
            ["2024-06-03", "1"],
            ["2024-06-04", "1"],
        ]
    )
    session = _make_session(fake)
    rows = session.query_trade_dates(DAY, NEXT)
    assert fake.trade_dates_calls == [{"start": DAY.isoformat(), "end": NEXT.isoformat()}]
    assert rows == [
        {"calendar_date": "2024-06-01", "is_trading_day": "0"},
        {"calendar_date": "2024-06-03", "is_trading_day": "1"},
        {"calendar_date": "2024-06-04", "is_trading_day": "1"},
    ]


def test_WorkerCall_all_stock与trade_dates工厂() -> None:
    """工厂方法生成的 call 序列化往返后仍相等（线上协议契约）。"""
    all_stock = WorkerCall.all_stock("snap-1", DAY)
    assert all_stock.kind == "all_stock"
    assert all_stock.start == all_stock.end == DAY
    assert WorkerCall.from_payload(all_stock.to_payload()) == all_stock

    trade_dates = WorkerCall.trade_dates("cal-1", DAY, NEXT)
    assert trade_dates.kind == "trade_dates"
    assert WorkerCall.from_payload(trade_dates.to_payload()) == trade_dates


def test_child_分发_all_stock与trade_dates() -> None:
    """child_main 循环里两种新 kind 正常出 result 事件。"""
    fake = FakeBs(
        all_stock_rows=[["sh.600000", "1", "浦发银行"]],
        trade_date_rows=[["2024-06-03", "1"]],
    )
    request = {
        "calls": [
            WorkerCall.all_stock("snap-1", DAY).to_payload(),
            WorkerCall.trade_dates("cal-1", DAY, NEXT).to_payload(),
        ],
        "pacing_s": 0,
    }
    out = io.StringIO()
    exit_code = child_main(
        stdin=io.StringIO(json.dumps(request) + "\n"),
        stdout=out,
        session_factory=lambda: BaostockSession(bs=fake),
    )
    assert exit_code == 0
    events = [json.loads(line) for line in out.getvalue().splitlines()]
    results = {e["id"]: e for e in events if e["event"] == "result"}
    assert results["snap-1"]["ok"] is True
    assert results["snap-1"]["payload"] == [
        {"code": "sh.600000", "tradeStatus": "1", "code_name": "浦发银行"}
    ]
    assert results["cal-1"]["ok"] is True
    assert results["cal-1"]["payload"] == [{"calendar_date": "2024-06-03", "is_trading_day": "1"}]
