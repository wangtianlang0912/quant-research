"""baostock 子进程隔离 worker（§5.11 / M-3 / M-9 / M-14 / M-16 / M-18）。

## 为什么必须子进程隔离

实测（架构文档 §5.11）：`bs.query_history_k_data_plus(adjustflag=1|2)` 在退市股上
**无限挂起**，卡在 C 扩展的裸 TCP 读里，`SIGALRM` 与 `signal.setitimer` 均无法打断；
且持续压测后会话劣化 **4.8 倍**（1.38 → 6.69 s/symbol），第 8 只直接挂死 >6 分钟，
**挂死后同进程内后续查询全部失败**。Python 层任何超时机制都无效。

因此本文件内部分成两个世界，物理上绝不允许越界：

- **父进程侧**（`SubprocessWorker`）：调度、分块、行级超时、kill -9 进程组、
  checkpoint、rate limit pacing。**永不 import baostock**（ARCH014）。
- **子进程侧**（`BaostockSession` + `child_main`）：通过
  `python -m quant_v2.adapters.market_data.subprocess_worker` 启动的独立进程，
  是全项目唯一 import baostock 的两个文件之一（另一个是 `baostock_cn.py`）。

## 线上协议（JSON-lines，stdin → stdout）

父 → 子（一行一个 batch 请求）::

    {"calls": [{"id": "...", "kind": "bars", "symbol": "sh.600000",
                "start": "2024-01-01", "end": "2024-06-30"}],
     "pacing_s": 1.5}

子 → 父（逐行事件，父进程对**每一行**执行 60s 超时）::

    {"event": "ready", "pid": 123, "max_session_queries": 200}
    {"event": "query_start", "id": "..."}
    {"event": "result", "id": "...", "ok": true, "payload": [...], "elapsed_s": 1.4}
    {"event": "result", "id": "...", "ok": false, "error": "...", "elapsed_s": 0.0}
    {"event": "batch_done", "count": 20}
    {"event": "session_end", "reason": "max_queries|degradation", "queries": 200}
    {"event": "fatal", "error": "login failed: ..."}

## ★★ 参数全部来自第二轮实测（M-14/M-16/M-17/M-18），不要凭直觉改 ★★

- `timeout_s = 60`：合法查询最长观测 16.3s，30s 会误杀；>60s 基本可判定挂死
- `batch_size = 20`：B=20 开销仅 3%（B=50 只再快 3%，但一次挂死要多重跑 50 只）
- `max_session_queries = 200`：会话劣化对策，跑满主动退出重建
- `rate_limit_per_min = 40`：含子进程隔离开销的真实吞吐（M-17）
"""

from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import sys
import time
from collections import deque
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal, TextIO

from quant_v2.domain.errors import SourceUnavailableError

__all__ = [
    "BaostockSession",
    "SubprocessWorker",
    "WorkerCall",
    "WorkerResult",
    "child_main",
]

# M-14：子进程连续故障 2 次 → 判源不可用，编排层切备源并当日拉黑
_MAX_CONSECUTIVE_FAILURES = 2

# ============================================================
# 父子进程共用的数据契约
# ============================================================


@dataclass(frozen=True)
class WorkerCall:
    """一次子进程查询请求。

    `symbol` 是 **baostock 原生代码**（如 `sh.600000`），归一化由
    `baostock_cn.py` 在调用侧完成 —— 子进程不做任何领域知识假设。
    `all_stock` / `trade_dates` 两种 kind 不用 symbol（置空串），
    只用 `start`（= 快照日 / 区间起点）；`trade_dates` 的 `end` 是区间终点。
    """

    call_id: str
    kind: Literal["bars", "factors", "all_stock", "trade_dates"]
    symbol: str
    start: date
    end: date

    def to_payload(self) -> dict[str, str]:
        """序列化为线上 JSON 形态（date → ISO 字符串）。"""
        return {
            "id": self.call_id,
            "kind": self.kind,
            "symbol": self.symbol,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }

    @classmethod
    def from_payload(cls, raw: dict[str, Any]) -> WorkerCall:
        """从线上 JSON 反序列化（子进程侧使用）。"""
        return cls(
            call_id=str(raw["id"]),
            kind=str(raw["kind"]),
            symbol=str(raw["symbol"]),
            start=date.fromisoformat(str(raw["start"])),
            end=date.fromisoformat(str(raw["end"])),
        )

    @classmethod
    def all_stock(cls, call_id: str, day: date) -> WorkerCall:
        """PIT 日快照请求（T02.5 / M-15）：`query_all_stock(day=day)`。"""
        return cls(call_id=call_id, kind="all_stock", symbol="", start=day, end=day)

    @classmethod
    def trade_dates(cls, call_id: str, start: date, end: date) -> WorkerCall:
        """交易日历请求（T02.5 配套）：`query_trade_dates(start, end)`。"""
        return cls(call_id=call_id, kind="trade_dates", symbol="", start=start, end=end)


@dataclass(frozen=True)
class WorkerResult:
    """一次子进程查询的结果。

    ★ `ok=False` 是**数据级失败**（如 baostock 返回 error_code != 0），
    会随批一起返回给调用方决定怎么处理；而**子进程级失败**（超时/挂死/fatal）
    由 `SubprocessWorker` 以重试 + `SourceUnavailableError` 表达，两者不混用。
    """

    call_id: str
    ok: bool
    payload: Any | None
    error: str | None
    timed_out: bool = False
    elapsed_s: float = 0.0


# ============================================================
# 子进程侧：BaostockSession（唯一允许 import baostock 的地方，ARCH014）
# ============================================================


class BaostockSession:
    """子进程侧的 baostock 会话：login 一次、跨 batch 复用、劣化/超限主动退出。

    ★ M-18 四条硬约束的执行者：
    1. 每次查询记录延迟；滑动窗口（50 次）均值 > 基线（前 5 次均值）的 2.5 倍
       → 判定会话劣化 → 本批做完后发 `session_end` 并退出，父进程下次重建；
    2. 查询满 `max_session_queries`（200）→ 同样主动退出重建。

    `bs` 参数用于测试注入 fake 模块；生产路径传 `None`，首次用时才
    `import baostock`（惰性导入保证父进程 import 本模块零副作用）。
    """

    def __init__(
        self,
        *,
        bs: Any | None = None,
        max_session_queries: int = 200,
        baseline_queries: int = 5,
        window_size: int = 50,
        degrade_ratio: float = 2.5,
    ) -> None:
        self._bs = bs
        self.max_session_queries = max_session_queries
        self._baseline_queries = baseline_queries
        self._window_size = window_size
        self._degrade_ratio = degrade_ratio
        self._latencies: deque[float] = deque(maxlen=window_size)
        self._queries = 0
        self._logged_in = False

    # -- 模块与生命周期 -------------------------------------

    @property
    def bs_module(self) -> Any:
        """baostock 模块（惰性导入；子进程才会走到这里）。"""
        if self._bs is None:
            import baostock as bs  # noqa: PLC0415  # ARCH014：唯一允许处之一

            self._bs = bs
        return self._bs

    @property
    def queries(self) -> int:
        """本会话累计查询次数。"""
        return self._queries

    @property
    def logged_in(self) -> bool:
        """是否已完成 login。"""
        return self._logged_in

    def login(self) -> None:
        """登录 baostock。失败抛 RuntimeError（fatal，子进程会退出）。"""
        result = self.bs_module.login()
        # baostock.login() 返回 (code, msg)；code '0' 为成功
        code = getattr(result, "error_code", None)
        if code is not None and str(code) != "0":
            raise RuntimeError(f"baostock login 失败: {getattr(result, 'error_msg', result)}")
        self._logged_in = True

    def logout(self) -> None:
        """登出（尽力而为：已退出登录的会话再调 logout 不报错）。"""
        if self._logged_in and self._bs is not None:
            try:  # noqa: SIM105 -- 收尾路径：logout 失败不值得再炸一次
                self.bs_module.logout()
            except Exception:  # noqa: ARCH005, S110 -- 收尾路径：logout 失败不值得再炸一次
                pass
            self._logged_in = False

    # -- 查询 -------------------------------------------------

    def query_daily_bars(self, symbol: str, start: date, end: date) -> list[dict[str, str]]:
        """拉原始日线。★ 只拉 adjustflag=3（M-3：1/2 在退市股上无限挂起）。

        Returns:
            每行一个 dict（字符串值原样透传，Decimal 换算在适配器做）。
        """
        fields = "date,code,open,high,low,close,preclose,volume,amount,tradestatus"
        t0 = time.perf_counter()
        rs = self.bs_module.query_history_k_data_plus(
            symbol,
            fields,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            frequency="d",
            adjustflag="3",  # ★ M-3：只拉不复权原始价，因子单独拉（M-5）
        )
        rows = _iterate_result_set(rs, context=f"bars({symbol})")
        self._record_latency(time.perf_counter() - t0)
        return rows

    def query_adjust_factors(self, symbol: str, start: date, end: date) -> list[dict[str, str]]:
        """拉复权因子。★ 只取 dividOperateDate + backAdjustFactor（M-5）。"""
        t0 = time.perf_counter()
        rs = self.bs_module.query_adjust_factor(
            code=symbol,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )
        raw_rows = _iterate_result_set(rs, context=f"factors({symbol})")
        self._record_latency(time.perf_counter() - t0)
        return [
            {
                "dividOperateDate": row["dividOperateDate"],
                "backAdjustFactor": row["backAdjustFactor"],
            }
            for row in raw_rows
        ]

    def query_all_stock(self, day: date) -> list[dict[str, str]]:
        """拉 `day` 当天的全市场日快照（T02.5 PIT 池，M-15/M-19/M-20）。

        ★ 非交易日返回 **0 rows**（M-19 实测）—— 调用方（PIT provider）
        必须先用交易日历把关，0 rows 不是"空池子"。
        ★ 返回字段只有 `code / tradeStatus / code_name`，且**含指数**
        （sh.00xxxx / sz.39xxxx），过滤是适配器的活。
        """
        t0 = time.perf_counter()
        rs = self.bs_module.query_all_stock(day=day.isoformat())
        rows = _iterate_result_set(rs, context=f"all_stock({day})")
        self._record_latency(time.perf_counter() - t0)
        return rows

    def query_trade_dates(self, start: date, end: date) -> list[dict[str, str]]:
        """拉交易日历（`calendar_date, is_trading_day` 两列，'1'/'0'）。"""
        t0 = time.perf_counter()
        rs = self.bs_module.query_trade_dates(
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )
        rows = _iterate_result_set(rs, context=f"trade_dates({start}~{end})")
        self._record_latency(time.perf_counter() - t0)
        return rows

    # -- 会话健康度（M-18） -----------------------------------

    def _record_latency(self, elapsed_s: float) -> None:
        self._latencies.append(elapsed_s)
        self._queries += 1

    @property
    def degraded(self) -> bool:
        """滑动窗口均值是否超过基线的 `degrade_ratio` 倍。"""
        if len(self._latencies) < self._baseline_queries:
            return False  # 基线尚未建立
        baseline = _mean(tuple(self._latencies)[: self._baseline_queries])
        if baseline <= 0:
            return False
        window_mean = _mean(tuple(self._latencies))
        return window_mean > self._degrade_ratio * baseline

    def should_rebuild(self) -> str | None:
        """本批结束后是否应重建会话。返回原因或 None。

        Returns:
            `'max_queries'` | `'degradation'` | None。
        """
        if self._queries >= self.max_session_queries:
            return "max_queries"
        if self.degraded:
            return "degradation"
        return None


def _iterate_result_set(rs: Any, *, context: str) -> list[dict[str, str]]:
    """消费一个 baostock 结果集，返回按 fields 命名的行 dict 列表。

    baostock 的惯用消费方式是 `while (rs.error_code == '0') & rs.next()`；
    这里加上字段名映射与显式错误检查（error_code != 0 时**抛错而非返回空** ——
    空结果会让上游以为"该标的没有数据"，掩盖真实故障）。
    """
    code = str(getattr(rs, "error_code", "0"))
    if code != "0":
        raise RuntimeError(f"baostock 查询失败 [{context}]: {getattr(rs, 'error_msg', code)}")
    fields = list(getattr(rs, "fields", []))
    rows: list[dict[str, str]] = []
    while rs.next():
        values = rs.get_row_data()
        rows.append(dict(zip(fields, values, strict=False)))
    return rows


def _mean(values: Sequence[float]) -> float:
    """算术均值（空序列返回 0，调用方已保证非空路径）。"""
    if not values:
        return 0.0
    return sum(values) / len(values)


# ============================================================
# 子进程侧：child_main（stdin/stdout JSON-lines 循环）
# ============================================================


def _emit(out: TextIO, obj: dict[str, Any]) -> None:
    """写一行 JSON 事件并立刻 flush（父进程靠行心跳判超时）。"""
    out.write(json.dumps(obj, ensure_ascii=False) + "\n")
    out.flush()


def _dispatch(session: BaostockSession, call: WorkerCall) -> Any:
    """按 kind 分发到会话查询。"""
    if call.kind == "bars":
        return session.query_daily_bars(call.symbol, call.start, call.end)
    if call.kind == "factors":
        return session.query_adjust_factors(call.symbol, call.start, call.end)
    if call.kind == "all_stock":
        return session.query_all_stock(call.start)
    if call.kind == "trade_dates":
        return session.query_trade_dates(call.start, call.end)
    raise ValueError(f"未知 call.kind: {call.kind!r}（id={call.call_id}）")


def child_main(
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    session_factory: Any | None = None,
) -> int:
    """子进程入口：读一行 batch 请求 → 逐 call 出事件 → 批末决定会话去留。

    退出码：0 = 正常结束（含主动 session_end）；1 = fatal（login 失败等）。
    """
    stream_in = stdin if stdin is not None else sys.stdin
    stream_out = stdout if stdout is not None else sys.stdout
    session: BaostockSession = (
        session_factory() if session_factory is not None else BaostockSession()
    )

    try:
        session.login()
    except Exception as exc:
        _emit(stream_out, {"event": "fatal", "error": f"login failed: {exc!r}"})
        return 1

    _emit(
        stream_out,
        {"event": "ready", "pid": os.getpid(), "max_session_queries": session.max_session_queries},
    )

    exit_code = 0
    try:
        for raw_line in stream_in:
            line = raw_line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                _emit(stream_out, {"event": "fatal", "error": f"bad request line: {exc}"})
                exit_code = 1
                break
            calls = [WorkerCall.from_payload(c) for c in request["calls"]]
            pacing_s = float(request.get("pacing_s", 0.0))

            for index, call in enumerate(calls):
                if index > 0 and pacing_s > 0:
                    time.sleep(pacing_s)  # rate limit pacing（M-17）
                _emit(stream_out, {"event": "query_start", "id": call.call_id})
                t0 = time.perf_counter()
                try:
                    payload = _dispatch(session, call)
                    _emit(
                        stream_out,
                        {
                            "event": "result",
                            "id": call.call_id,
                            "ok": True,
                            "payload": payload,
                            "elapsed_s": round(time.perf_counter() - t0, 6),
                        },
                    )
                except Exception as exc:  # 单 call 失败不炸整批
                    _emit(
                        stream_out,
                        {
                            "event": "result",
                            "id": call.call_id,
                            "ok": False,
                            "error": repr(exc),
                            "elapsed_s": round(time.perf_counter() - t0, 6),
                        },
                    )

            _emit(stream_out, {"event": "batch_done", "count": len(calls)})

            # ★ M-18：跑满 200 次或劣化 → 本批做完即退出，父进程下次重建会话
            reason = session.should_rebuild()
            if reason is not None:
                _emit(
                    stream_out,
                    {"event": "session_end", "reason": reason, "queries": session.queries},
                )
                break
    finally:
        session.logout()
    return exit_code


if __name__ == "__main__":  # pragma: no cover -- 由父进程 spawn 的真实入口
    raise SystemExit(child_main())


# ============================================================
# 父进程侧：SubprocessWorker（永不 import baostock）
# ============================================================


class _ChildEofError(Exception):
    """子进程 stdout 意外关闭（崩溃/被 kill）。"""


class _ChildFatalError(Exception):
    """子进程主动报告 fatal（如 login 失败）。"""


class _ChildTimeoutError(Exception):
    """行级超时：timeout_s 内没有任何新行（M-14：基本可判定挂死）。"""


class _ChildHandle:
    """一个存活子进程的句柄：行级超时读取 + 进程组硬 kill。"""

    def __init__(
        self,
        *,
        child_cmd: Sequence[str],
        cwd: Path | None = None,
    ) -> None:
        # start_new_session=True：子进程自成进程组 → killpg 一次带走全部后代
        self._proc = subprocess.Popen(  # noqa: S603 -- cmd 由调用方显式构造
            list(child_cmd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=False,
            cwd=cwd,
            start_new_session=True,
        )
        self._buf = b""
        self._eof = False
        self._selector = selectors.DefaultSelector()
        self._selector.register(self._proc.stdout, selectors.EVENT_READ)

    @property
    def pid(self) -> int:
        """子进程 PID。"""
        return self._proc.pid

    @property
    def exited(self) -> bool:
        """子进程是否已退出。"""
        return self._proc.poll() is not None

    def send_request(self, request: dict[str, Any]) -> None:
        """把一个 batch 请求写给子进程。"""
        stdin = self._proc.stdin
        if stdin is None or stdin.closed:
            raise _ChildEofError("子进程 stdin 未打开或已关闭")
        data = (json.dumps(request, ensure_ascii=False) + "\n").encode()
        try:
            stdin.write(data)
            stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise _ChildEofError(f"子进程 stdin 已关闭: {exc}") from exc

    def read_line(self, timeout_s: float) -> dict[str, Any]:
        """读一行事件 JSON。

        Raises:
            _ChildTimeoutError: timeout_s 内没有任何新行。
            _ChildEofError: 子进程 stdout 关闭且无残行。
        """
        deadline = time.monotonic() + timeout_s
        while True:
            newline_index = self._buf.find(b"\n")
            if newline_index >= 0:
                line, self._buf = self._buf[:newline_index], self._buf[newline_index + 1 :]
                return json.loads(line.decode())
            if self._eof:
                raise _ChildEofError("子进程 stdout 已关闭（无残行）")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _ChildTimeoutError(f"{timeout_s}s 内无任何输出，判定挂死（M-14）")
            events = self._selector.select(timeout=remaining)
            if not events:
                raise _ChildTimeoutError(f"{timeout_s}s 内无任何输出，判定挂死（M-14）")
            chunk = os.read(self._proc.stdout.fileno(), 65536)  # type: ignore[union-attr]
            if not chunk:
                self._eof = True
                continue
            self._buf += chunk  # ★ 拼回行缓冲（丢了这行 = 数据黑洞：读到的字节凭空消失）

    def read_event(self, expected: str, timeout_s: float) -> dict[str, Any]:
        """读一行事件并断言事件类型（协议状态机）。"""
        event = self.read_line(timeout_s)
        kind = event.get("event")
        if kind == "fatal":
            raise _ChildFatalError(str(event.get("error", "unknown fatal")))
        if kind != expected:
            raise _ChildFatalError(f"协议错误：期望 {expected}，实得 {kind}（{event}）")
        return event

    def kill(self) -> None:
        """kill -9 整个进程组并回收（M-3：C 扩展里的挂死只有 SIGKILL 能救）。"""
        try:  # noqa: SIM105 -- 收尾路径：selector 已关闭/句柄失效，无善后可做
            self._selector.close()
        except OSError:  # noqa: ARCH005 -- 收尾路径：selector 已关闭/句柄失效，无善后可做
            pass
        try:
            os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            self._proc.kill()  # 进程组已消失/不可用时退化为 kill 单进程
        try:  # noqa: SIM105 -- SIGKILL 后 5s 仍未退出：已僵尸化，交给 OS 回收
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # noqa: ARCH005 -- SIGKILL 后 5s 仍未退出：已僵尸化，交给 OS 回收
            pass  # pragma: no cover
        self._close_pipes()

    def close(self) -> None:
        """正常收尾：等子进程退出（子进程在 stdin EOF 后自行 logout 退出）。"""
        try:
            if self._proc.stdin is not None and not self._proc.stdin.closed:
                self._proc.stdin.close()
        except OSError:  # noqa: ARCH005 -- 收尾路径：selector 已关闭/句柄失效，无善后可做
            pass
        try:  # noqa: SIM105 -- 收尾路径：selector 已关闭/句柄失效，无善后可做
            self._selector.close()
        except OSError:  # noqa: ARCH005 -- 收尾路径：selector 已关闭/句柄失效，无善后可做
            pass
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            self.kill()
            return
        self._close_pipes()

    def _close_pipes(self) -> None:
        """关闭 stdin/stdout 管道（防止 ResourceWarning：GC 时未关闭句柄）。"""
        for pipe in (self._proc.stdin, self._proc.stdout):
            if pipe is not None and not pipe.closed:
                try:  # noqa: SIM105 -- 收尾路径
                    pipe.close()
                except OSError:  # noqa: ARCH005 -- 收尾路径
                    pass


class SubprocessWorker:
    """★ 主进程唯一入口：批量查询 + 断点续跑 + 超时硬 kill + 会话重建。

    **本类所在进程永不 import baostock**（ARCH014）—— 所有查询都发给
    子进程 `python -m quant_v2.adapters.market_data.subprocess_worker`。

    故障语义（M-14）：
    - 行级超时（timeout_s 无新行）→ kill -9 进程组 → 丢弃会话 → 重试 1 次；
    - 连续 2 次超时/fatal → 抛 `SourceUnavailableError`（该源当日拉黑）。

    断点续跑（M-18 第 4 条）：
    - `checkpoint_key` 非空时，每个 batch 完成后立刻把已完成 call_id 清单
      原子落盘 `checkpoint_dir/<key>.json`；进程崩溃后重跑自动跳过已完成部分。
    """

    def __init__(
        self,
        *,
        timeout_s: float = 60.0,  # ★ 不是 30（M-14：合法最长 16.3s）
        ready_timeout_s: float = 30.0,  # 冷启动（import + login）与查询延迟是两回事
        max_retries: int = 1,
        batch_size: int = 20,  # ★ M-16
        rate_limit_per_min: int = 40,  # ★ M-17
        max_session_queries: int = 200,  # ★ M-18
        checkpoint_dir: Path | None = None,
        child_cmd: Sequence[str] | None = None,
        python_exe: str | None = None,
    ) -> None:
        self._timeout_s = timeout_s
        self._ready_timeout_s = ready_timeout_s
        self._max_retries = max_retries
        self._batch_size = batch_size
        self._rate_limit_per_min = rate_limit_per_min
        self._max_session_queries = max_session_queries
        self._checkpoint_dir = checkpoint_dir
        self._child_cmd = tuple(child_cmd) if child_cmd else None
        self._python_exe = python_exe or sys.executable
        self._child: _ChildHandle | None = None

    # -- 派生参数（★ 由 capabilities 派生，不硬编码，§5.11） --

    @property
    def pacing_s(self) -> float:
        """相邻查询的最小间隔（秒）。"""
        if not self._rate_limit_per_min:
            return 0.0
        return 60.0 / self._rate_limit_per_min

    @property
    def concurrency(self) -> int:
        """并发子进程数。40 req/min 下瓶颈在服务端限流，并发 >1 无收益 → 1。"""
        return 1

    # -- 对外 API ---------------------------------------------

    def run(self, call: WorkerCall) -> WorkerResult:
        """单次查询（薄封装）。"""
        results = self.run_batch([call])
        return results[call.call_id]

    def run_batch(
        self,
        calls: Sequence[WorkerCall],
        *,
        checkpoint_key: str | None = None,
    ) -> dict[str, WorkerResult]:
        """批量查询 + 断点续跑。

        Args:
            calls: 全部请求（含可能已完成的）。
            checkpoint_key: 非空时启用断点续跑（文件 `checkpoint_dir/<key>.json`）。

        Returns:
            call_id → WorkerResult。**只含本次实际执行的 call**；
            checkpoint 跳过的部分不重复执行、不重复返回。
        """
        completed = self._load_checkpoint(checkpoint_key) if checkpoint_key else set()
        pending = [c for c in calls if c.call_id not in completed]
        results: dict[str, WorkerResult] = {}

        for chunk in _chunks(pending, self._batch_size):
            chunk_results = self._run_chunk_with_retry(chunk)
            results.update(chunk_results)
            if checkpoint_key:
                completed.update(r.call_id for r in chunk_results.values() if r.ok)
                self._save_checkpoint(checkpoint_key, completed)

        return results

    def close(self) -> None:
        """收尾：关闭当前子进程（幂等）。"""
        if self._child is not None:
            self._child.close()
            self._child = None

    # -- 内部：chunk 执行与重试 -------------------------------

    def _run_chunk_with_retry(self, chunk: Sequence[WorkerCall]) -> dict[str, WorkerResult]:
        """执行一个 chunk；子进程级故障（超时/fatal/EOF）重试，连续 2 次拉黑。"""
        consecutive_failures = 0
        attempt = 0
        while True:
            attempt += 1
            try:
                return self._exchange(chunk)
            except (_ChildTimeoutError, _ChildFatalError, _ChildEofError) as exc:
                self._destroy_child()
                consecutive_failures += 1
                if (
                    consecutive_failures >= _MAX_CONSECUTIVE_FAILURES
                    or attempt > self._max_retries + 1
                ):
                    raise SourceUnavailableError(
                        f"baostock 子进程连续 {consecutive_failures} 次失败"
                        f"（最近一次: {exc}），该源按 M-14 当日拉黑"
                    ) from exc

    def _exchange(self, chunk: Sequence[WorkerCall]) -> dict[str, WorkerResult]:
        """与子进程交换一个 chunk：发请求 → 收集 result 直到 batch_done。

        ★ 行级超时 = timeout_s + pacing_s：pacing 是**设计内的**批内查询间隔
        （子进程逐查询 sleep），不把它算进"无输出判定"，否则限流开启时
        每个批的第二次查询都会被误判挂死。
        """
        child = self._ensure_child()
        child.send_request(
            {
                "calls": [c.to_payload() for c in chunk],
                "pacing_s": round(self.pacing_s, 4),
            }
        )
        line_timeout = self._timeout_s + self.pacing_s
        results: dict[str, WorkerResult] = {}
        session_ended = False
        while True:
            event = child.read_line(line_timeout)
            kind = event.get("event")
            if kind == "fatal":
                raise _ChildFatalError(str(event.get("error", "unknown fatal")))
            if kind == "query_start":
                continue
            if kind == "result":
                result = WorkerResult(
                    call_id=str(event["id"]),
                    ok=bool(event.get("ok")),
                    payload=event.get("payload"),
                    error=event.get("error"),
                    elapsed_s=float(event.get("elapsed_s", 0.0)),
                )
                results[result.call_id] = result
                continue
            if kind == "batch_done":
                break
            if kind == "session_end":
                session_ended = True
                continue
            raise _ChildFatalError(f"协议错误：未知事件 {kind}（{event}）")

        if session_ended or child.exited:
            # 子进程已宣布退出（或已死）：正常关闭，下个 chunk 重建
            child.close()
            self._child = None
        return results

    def _ensure_child(self) -> _ChildHandle:
        """确保有一个存活子进程（惰性启动 + 死亡自动重建）。

        ★ ready 阶段（解释器启动 + import baostock + login）用独立的
        `ready_timeout_s` —— 它是冷启动开销（实测 ~0.9s，M-16），不是查询延迟，
        不应消耗查询超时预算（否则测试环境机器慢一点就误杀）。
        """
        if self._child is not None and not self._child.exited:
            return self._child
        child_cmd = self._child_cmd or [
            self._python_exe,
            "-m",
            "quant_v2.adapters.market_data.subprocess_worker",
        ]
        child = _ChildHandle(child_cmd=child_cmd)
        try:
            child.read_event("ready", self._ready_timeout_s)
        except BaseException:
            # ★ ready 都等不到（启动挂死/fatal）→ 必须当场 kill，
            #   否则这个孤儿进程谁也不持有引用，泄漏到测试/生产进程外。
            child.kill()
            raise
        self._child = child
        return child

    def _destroy_child(self) -> None:
        """硬 kill 当前子进程并置空（会话不可复用，M-18）。"""
        if self._child is not None:
            self._child.kill()
            self._child = None

    # -- checkpoint -------------------------------------------

    def _checkpoint_path(self, key: str) -> Path:
        base = self._checkpoint_dir if self._checkpoint_dir is not None else Path("var/checkpoints")
        return base / f"{key}.json"

    def _load_checkpoint(self, key: str) -> set[str]:
        """读取已完成 call_id 清单；不存在/损坏返回空集（损坏 = 从头跑，宁可重跑不可漏跑）。"""
        path = self._checkpoint_path(key)
        if not path.exists():
            return set()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return set()
        completed = data.get("completed", [])
        if not isinstance(completed, list):
            return set()
        return {str(item) for item in completed}

    def _save_checkpoint(self, key: str, completed: Iterable[str]) -> None:
        """原子落盘 checkpoint（tmp + replace，进程崩溃不会留下半截文件）。"""
        path = self._checkpoint_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        payload = json.dumps({"completed": sorted(completed)}, ensure_ascii=False)
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)


def _chunks(items: Sequence[WorkerCall], size: int) -> Iterator[Sequence[WorkerCall]]:
    """按 size 切块（最后一块可短）。"""
    for i in range(0, len(items), size):
        yield items[i : i + size]
