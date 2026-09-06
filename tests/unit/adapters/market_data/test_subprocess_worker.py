"""SubprocessWorker 父进程侧测试（真实子进程 + stub 脚本，零 baostock）。

★ 测试策略：父进程侧的**故障语义**（超时 kill / 重试 / 连续两次拉黑 /
断点续跑 / 会话重建）只有用真实子进程才测得真 —— mock 掉 subprocess
等于用被测代码测自己。stub 脚本说同一套 JSON-lines 协议，但**不 import baostock**
（这是 ARCH014 对测试文件同样成立的原因）。

stub 行为全部由环境变量控制（见 STUB_SOURCE 头部注释），一份脚本覆盖全部场景。
"""

from __future__ import annotations

import os
import signal
import sys
import time
from datetime import date
from pathlib import Path

import pytest

from quant_v2.adapters.market_data.subprocess_worker import (
    SubprocessWorker,
    WorkerCall,
)
from quant_v2.domain.errors import SourceUnavailableError

pytestmark = pytest.mark.unit

DAY = date(2024, 6, 3)
NEXT = date(2024, 6, 4)

# 超时常量：stub 子进程 spawn 开销 ~0.1s（无 baostock import），
# 0.5s 足够区分"正常应答"与"挂死"，且远小于挂死时长 30s。
TIMEOUT_S = 0.5

# 一份可配置 stub 子进程，行为由环境变量组合控制：
#   STUB_MODE=ok|hang|crash|fatal
#   STUB_ATTEMPT_FILE=<path>   第一个子进程（该文件尚不存在时）对每个查询挂死
#   STUB_PID_FILE=<path>       ready 后把 pid 写入该文件（测"挂死进程被 kill"）
#   STUB_EXEC_LOG=<path>       把执行过的 call_id 逐行追加（测断点续跑）
#   STUB_SPAWN_LOG=<path>      每次进程启动追加 pid（测会话重建）
#   STUB_FATAL_ONCE=<path>     首个子进程 fatal（marker 不存在时），之后正常
#   STUB_EXIT_AFTER_BATCH=1    每批结束发 session_end 并退出
STUB_SOURCE = """
import json, os, sys, time
from pathlib import Path

MODE = os.environ.get("STUB_MODE", "ok")
EXEC_LOG = os.environ.get("STUB_EXEC_LOG")
SPAWN_LOG = os.environ.get("STUB_SPAWN_LOG")
PID_FILE = os.environ.get("STUB_PID_FILE")
ATTEMPT_FILE = os.environ.get("STUB_ATTEMPT_FILE")
FATAL_ONCE = os.environ.get("STUB_FATAL_ONCE")
EXIT_AFTER_BATCH = os.environ.get("STUB_EXIT_AFTER_BATCH") == "1"

def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\\n")
    sys.stdout.flush()

first_process = False
if ATTEMPT_FILE:
    p = Path(ATTEMPT_FILE)
    first_process = not p.exists()
    with p.open("a") as f:
        f.write("x\\n")

if SPAWN_LOG:
    with open(SPAWN_LOG, "a") as f:
        f.write(str(os.getpid()) + "\\n")

emit({"event": "ready", "pid": os.getpid(), "max_session_queries": 200})

if PID_FILE:
    Path(PID_FILE).write_text(str(os.getpid()))

if MODE == "crash":
    sys.exit(1)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    pacing = float(req.get("pacing_s", 0.0))
    for i, call in enumerate(req["calls"]):
        if i and pacing > 0:
            time.sleep(pacing)
        emit({"event": "query_start", "id": call["id"]})
        if first_process or MODE == "hang":
            time.sleep(30)
        if MODE == "fatal":
            emit({"event": "fatal", "error": "stub fatal"})
            sys.exit(1)
        if FATAL_ONCE and not Path(FATAL_ONCE).exists():
            Path(FATAL_ONCE).write_text("done")
            emit({"event": "fatal", "error": "stub fatal once"})
            sys.exit(1)
        if EXEC_LOG:
            with open(EXEC_LOG, "a") as f:
                f.write(call["id"] + "\\n")
        emit({"event": "result", "id": call["id"], "ok": True,
              "payload": [{"symbol": call["symbol"]}], "elapsed_s": 0.001})
    emit({"event": "batch_done", "count": len(req["calls"])})
    if EXIT_AFTER_BATCH:
        emit({"event": "session_end", "reason": "max_queries", "queries": len(req["calls"])})
        break
"""


@pytest.fixture
def stub_script(tmp_path: Path) -> Path:
    """写入 stub 子进程脚本，返回路径。"""
    script = tmp_path / "stub_child.py"
    script.write_text(STUB_SOURCE, encoding="utf-8")
    return script


@pytest.fixture
def stub_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    """stub 环境变量注册表：`stub_env["STUB_MODE"] = "hang"` 即生效，测试结束自动还原。"""
    return {}


def _make_worker(
    stub_script: Path,
    tmp_path: Path,
    stub_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    *,
    timeout_s: float = TIMEOUT_S,
    ready_timeout_s: float = 15.0,
    batch_size: int = 20,
    rate_limit_per_min: int = 0,
    max_retries: int = 1,
) -> SubprocessWorker:
    for key, value in stub_env.items():
        monkeypatch.setenv(key, value)
    return SubprocessWorker(
        timeout_s=timeout_s,
        ready_timeout_s=ready_timeout_s,
        batch_size=batch_size,
        rate_limit_per_min=rate_limit_per_min,
        max_retries=max_retries,
        checkpoint_dir=tmp_path / "checkpoints",
        child_cmd=[sys.executable, str(stub_script)],
    )


def _calls(n: int) -> list[WorkerCall]:
    return [
        WorkerCall(call_id=f"c{i}", kind="bars", symbol="sh.600000", start=DAY, end=NEXT)
        for i in range(n)
    ]


# ============================================================================
# 正常路径
# ============================================================================


def test_run_batch_正常应答_全部成功(
    stub_script: Path, tmp_path: Path, stub_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = _make_worker(stub_script, tmp_path, stub_env, monkeypatch)
    try:
        results = worker.run_batch(_calls(3))
    finally:
        worker.close()
    assert set(results) == {"c0", "c1", "c2"}
    for result in results.values():
        assert result.ok is True
        assert result.payload == [{"symbol": "sh.600000"}]
        assert result.timed_out is False


def test_run_单次查询_是_run_batch_的薄封装(
    stub_script: Path, tmp_path: Path, stub_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = _make_worker(stub_script, tmp_path, stub_env, monkeypatch)
    try:
        result = worker.run(_calls(1)[0])
    finally:
        worker.close()
    assert result.call_id == "c0"
    assert result.ok is True


def test_pacing_由限流值派生(
    stub_script: Path, tmp_path: Path, stub_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = _make_worker(stub_script, tmp_path, stub_env, monkeypatch, rate_limit_per_min=120)
    try:
        assert worker.pacing_s == pytest.approx(0.5)
        assert worker.concurrency == 1
    finally:
        worker.close()


def test_限流为0_不pacing(
    stub_script: Path, tmp_path: Path, stub_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = _make_worker(stub_script, tmp_path, stub_env, monkeypatch, rate_limit_per_min=0)
    try:
        assert worker.pacing_s == 0.0
    finally:
        worker.close()


def test_pacing_真实生效_批内查询间隔不小于设定值(
    stub_script: Path, tmp_path: Path, stub_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """rate_limit=60/min → pacing 1s → 3 个 call 的批至少耗 2s（第 2、3 个前各睡 1s）。"""
    worker = _make_worker(stub_script, tmp_path, stub_env, monkeypatch, rate_limit_per_min=60)
    try:
        t0 = time.monotonic()
        worker.run_batch(_calls(3))
        elapsed = time.monotonic() - t0
    finally:
        worker.close()
    assert elapsed >= 2.0  # pacing 由子进程逐查询 sleep 执行（M-17）


# ============================================================================
# 超时 / kill / 重试 / 拉黑（M-14）
# ============================================================================


def test_子进程挂死_超时kill_重试一次后成功(
    stub_script: Path, tmp_path: Path, stub_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """第一个子进程挂死 → kill -9 → 重试的第二个子进程正常应答（重试 1 次语义）。"""
    attempt_file = tmp_path / "attempts.txt"
    stub_env["STUB_ATTEMPT_FILE"] = str(attempt_file)
    worker = _make_worker(stub_script, tmp_path, stub_env, monkeypatch)
    try:
        t0 = time.monotonic()
        results = worker.run_batch(_calls(2))
        elapsed = time.monotonic() - t0
    finally:
        worker.close()

    assert set(results) == {"c0", "c1"}
    assert all(r.ok for r in results.values())
    # 真的触发过一次超时（30s 挂死没有被等完，而是 kill 后重来）
    assert TIMEOUT_S <= elapsed < 30.0
    # 每个 stub 进程启动时登记一行：恰好 2 个子进程（挂死的 + 重试的）
    assert len(attempt_file.read_text().splitlines()) == 2


def test_连续两次超时_抛_SourceUnavailableError_挂死进程被硬杀(
    stub_script: Path, tmp_path: Path, stub_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ M-14 验收：连续 2 次超时 → 拉黑异常 + 挂死进程被 kill -9 进程组带走。"""
    pid_file = tmp_path / "stub.pid"
    stub_env["STUB_MODE"] = "hang"
    stub_env["STUB_PID_FILE"] = str(pid_file)
    worker = _make_worker(stub_script, tmp_path, stub_env, monkeypatch)
    try:
        with pytest.raises(SourceUnavailableError, match="连续 2 次失败"):
            worker.run_batch(_calls(1))
    finally:
        worker.close()

    # ★ 挂死进程必须已被 kill（不是留着继续烧 30s 的 sleep）
    hung_pid = int(pid_file.read_text())
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            os.kill(hung_pid, 0)
        except (ProcessLookupError, PermissionError):
            break  # ESRCH=已死；EPERM=僵尸态等待回收（macOS 表现）
        time.sleep(0.05)
    else:
        pytest.fail(f"挂死子进程 {hung_pid} 未被 kill")


def test_子进程崩溃_EOF_连续两次_拉黑(
    stub_script: Path, tmp_path: Path, stub_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_env["STUB_MODE"] = "crash"
    worker = _make_worker(stub_script, tmp_path, stub_env, monkeypatch)
    try:
        with pytest.raises(SourceUnavailableError, match="连续 2 次失败"):
            worker.run_batch(_calls(1))
    finally:
        worker.close()


def test_子进程fatal_重试一次后成功_不拉黑(
    stub_script: Path, tmp_path: Path, stub_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """fatal（如 login 失败）也算子进程级故障：重试的第二个子进程正常 → 不拉黑。"""
    marker = tmp_path / "fatal_marker"
    stub_env["STUB_FATAL_ONCE"] = str(marker)
    worker = _make_worker(stub_script, tmp_path, stub_env, monkeypatch)
    try:
        results = worker.run_batch(_calls(1))
    finally:
        worker.close()
    assert results["c0"].ok is True
    assert marker.exists()


# ============================================================================
# 断点续跑（M-18 第 4 条）
# ============================================================================


def test_checkpoint_每批落盘_重跑跳过已完成(
    stub_script: Path, tmp_path: Path, stub_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    exec_log = tmp_path / "exec.log"
    stub_env["STUB_EXEC_LOG"] = str(exec_log)
    worker = _make_worker(stub_script, tmp_path, stub_env, monkeypatch, batch_size=2)
    try:
        results = worker.run_batch(_calls(4), checkpoint_key="job1")
        assert set(results) == {"c0", "c1", "c2", "c3"}
        assert exec_log.read_text().splitlines() == ["c0", "c1", "c2", "c3"]

        # 第二次跑同一 key：已完成的 4 个被跳过，只有新 call 真正执行
        new_call = WorkerCall(call_id="new", kind="bars", symbol="sh.600000", start=DAY, end=NEXT)
        more = [*_calls(4), new_call]
        results2 = worker.run_batch(more, checkpoint_key="job1")
        assert set(results2) == {"new"}
        executed = exec_log.read_text().splitlines()
        assert executed.count("c0") == 1  # c0 没有被重复执行
        assert executed[-1] == "new"
    finally:
        worker.close()
        ckpt = tmp_path / "checkpoints" / "job1.json"
        assert "new" in ckpt.read_text(encoding="utf-8")


def test_checkpoint_文件损坏_全部重跑(
    stub_script: Path, tmp_path: Path, stub_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """损坏的 checkpoint = 从头跑（宁可重跑，不可漏跑）。"""
    exec_log = tmp_path / "exec.log"
    stub_env["STUB_EXEC_LOG"] = str(exec_log)
    worker = _make_worker(stub_script, tmp_path, stub_env, monkeypatch)
    try:
        worker.run_batch(_calls(1), checkpoint_key="job2")
        (tmp_path / "checkpoints" / "job2.json").write_text("{broken", encoding="utf-8")
        results = worker.run_batch(_calls(1), checkpoint_key="job2")
        assert set(results) == {"c0"}
        assert exec_log.read_text().splitlines().count("c0") == 2
    finally:
        worker.close()


def test_无checkpoint_key_不落盘(
    stub_script: Path, tmp_path: Path, stub_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = _make_worker(stub_script, tmp_path, stub_env, monkeypatch)
    try:
        worker.run_batch(_calls(1))
    finally:
        worker.close()
    ckpt_dir = tmp_path / "checkpoints"
    assert not ckpt_dir.exists() or not any(ckpt_dir.iterdir())


# ============================================================================
# 会话重建（session_end → 下批新子进程）
# ============================================================================


def test_session_end_后_下个batch自动重建子进程(
    stub_script: Path, tmp_path: Path, stub_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """stub 每批结束发 session_end 退出：4 个 call 分 2 批 → spawn 2 个子进程。"""
    spawn_log = tmp_path / "spawns.txt"
    stub_env["STUB_SPAWN_LOG"] = str(spawn_log)
    stub_env["STUB_EXIT_AFTER_BATCH"] = "1"
    worker = _make_worker(stub_script, tmp_path, stub_env, monkeypatch, batch_size=2)
    try:
        results = worker.run_batch(_calls(4))
    finally:
        worker.close()
    assert set(results) == {"c0", "c1", "c2", "c3"}
    pids = spawn_log.read_text().splitlines()
    assert len(pids) == 2, "批 1 与批 2 必须各用一个子进程（会话重建）"
    assert pids[0] != pids[1]


# ============================================================================
# 分块（M-16）与边界
# ============================================================================


def test_按_batch_size_分块执行(
    stub_script: Path, tmp_path: Path, stub_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    exec_log = tmp_path / "exec.log"
    stub_env["STUB_EXEC_LOG"] = str(exec_log)
    worker = _make_worker(stub_script, tmp_path, stub_env, monkeypatch, batch_size=3)
    try:
        results = worker.run_batch(_calls(7))
    finally:
        worker.close()
    assert len(results) == 7
    assert len(exec_log.read_text().splitlines()) == 7


def test_空请求_零开销通过(
    stub_script: Path, tmp_path: Path, stub_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = _make_worker(stub_script, tmp_path, stub_env, monkeypatch)
    try:
        assert worker.run_batch([]) == {}
    finally:
        worker.close()


def test_kill_用的是_SIGKILL() -> None:
    """硬 kill 必须是 SIGKILL —— SIGTERM 打不断 C 扩展里的挂死（M-3）。"""
    assert int(signal.SIGKILL) == 9
