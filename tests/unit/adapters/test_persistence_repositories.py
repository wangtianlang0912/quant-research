"""SQLite 仓库实现测试（T02.1）。

验收点：
- Signal save / get / list_open / list_by_state
- ★ apply_transition 同事务写状态 + 审计（L-04）；
  非法迁移 / 乐观并发冲突 / 不存在的信号全部显式抛错
- find_orphans 孤儿巡检
- 心跳：expect 幂等、mark_finished、missing
- 推送回执：save / success_rate（无记录返回 0.0 不是 NaN）
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from quant_v2.adapters.persistence.repositories import (
    PushReceipt,
    SqliteHeartbeatRepository,
    SqliteLifecycleRepository,
    SqlitePushReceiptRepository,
    SqliteSignalRepository,
)
from quant_v2.adapters.persistence.sqlite_store import SqliteStore
from quant_v2.domain.errors import IllegalTransitionError
from quant_v2.domain.models.lifecycle import Actor, SignalState
from quant_v2.domain.models.signal import Signal

pytestmark = pytest.mark.unit

AS_OF = date(2026, 1, 5)
GENERATED_AT = datetime(2026, 1, 5, 23, 50, tzinfo=UTC)


def d(value: str) -> Decimal:
    return Decimal(value)


def make_signal(**overrides: object) -> Signal:
    kwargs: dict[str, object] = {
        "signal_id": "sig-001",
        "strategy_id": "value_breakout",
        "symbol": "601186.SH",
        "market": "cn_a",
        "as_of": AS_OF,
        "generated_at": GENERATED_AT,
        "score": d("72"),
        "entry_low": d("10"),
        "entry_high": d("10.5"),
        "target_price": d("12"),
        "stop_loss_price": d("9.5"),
        "max_holding_days": 20,
        "suggested_notional": d("5000"),
        "rationale": "估值便宜且趋势转强",
    }
    kwargs.update(overrides)
    return Signal(**kwargs)  # type: ignore[arg-type]


@pytest.fixture()
def store(tmp_path: Path) -> SqliteStore:
    return SqliteStore(tmp_path / "q.db")


# ============================================================
# 信号主表
# ============================================================
class TestSignalRepository:
    def test_保存读取往返(self, store: SqliteStore) -> None:
        repo = SqliteSignalRepository(store)
        sig = make_signal()
        repo.save(sig)
        loaded = repo.get("sig-001")
        assert loaded == sig  # pydantic 逐字段等值（Decimal JSON 序列化无损）

    def test_不存在的信号返回None(self, store: SqliteStore) -> None:
        repo = SqliteSignalRepository(store)
        assert repo.get("ghost") is None

    def test_upsert后只有一行且状态最新(self, store: SqliteStore) -> None:
        repo = SqliteSignalRepository(store)
        repo.save(make_signal(state=SignalState.GENERATED))
        repo.save(make_signal(state=SignalState.PENDING_PUSH))
        assert repo.get("sig-001").state is SignalState.PENDING_PUSH
        count = store.conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        assert count == 1

    def test_list_open排除终止状态(self, store: SqliteStore) -> None:
        repo = SqliteSignalRepository(store)
        repo.save(make_signal(signal_id="s1", state=SignalState.WATCHING))
        repo.save(make_signal(signal_id="s2", state=SignalState.ARCHIVED))
        repo.save(make_signal(signal_id="s3", state=SignalState.REJECTED))
        open_ids = {s.signal_id for s in repo.list_open(as_of=AS_OF)}
        assert open_ids == {"s1"}

    def test_list_open按as_of过滤(self, store: SqliteStore) -> None:
        repo = SqliteSignalRepository(store)
        repo.save(make_signal(signal_id="old", as_of=AS_OF - timedelta(days=3)))
        repo.save(make_signal(signal_id="future", as_of=AS_OF + timedelta(days=1)))
        open_ids = {s.signal_id for s in repo.list_open(as_of=AS_OF)}
        assert open_ids == {"old"}

    def test_list_by_state(self, store: SqliteStore) -> None:
        repo = SqliteSignalRepository(store)
        repo.save(make_signal(signal_id="s1", state=SignalState.WATCHING))
        repo.save(make_signal(signal_id="s2", state=SignalState.ACTIVE))
        assert [s.signal_id for s in repo.list_by_state(SignalState.ACTIVE)] == ["s2"]


# ============================================================
# 生命周期（★ 唯一写状态入口）
# ============================================================
class TestLifecycleRepository:
    def test_合法迁移_状态与审计同落(self, store: SqliteStore) -> None:
        sig_repo = SqliteSignalRepository(store)
        repo = SqliteLifecycleRepository(store)
        sig_repo.save(make_signal())

        record = repo.apply_transition(
            "sig-001",
            SignalState.PENDING_PUSH,
            actor=Actor.SYSTEM,
            reason="解释门禁通过，进入待推送",
        )
        assert record.from_state is SignalState.GENERATED
        assert record.to_state is SignalState.PENDING_PUSH

        # 主表状态已更新
        assert sig_repo.get("sig-001").state is SignalState.PENDING_PUSH
        # 审计行已落
        history = repo.history("sig-001")
        assert len(history) == 1
        assert history[0].reason == "解释门禁通过，进入待推送"
        assert history[0].actor is Actor.SYSTEM

    def test_迁移链路多步_历史按时间升序(self, store: SqliteStore) -> None:
        sig_repo = SqliteSignalRepository(store)
        repo = SqliteLifecycleRepository(store)
        sig_repo.save(make_signal())
        repo.apply_transition("sig-001", SignalState.PENDING_PUSH, actor=Actor.SYSTEM, reason="r1")
        repo.apply_transition("sig-001", SignalState.WATCHING, actor=Actor.SYSTEM, reason="r2")
        repo.apply_transition("sig-001", SignalState.ACTIVE, actor=Actor.SYSTEM, reason="r3")

        history = repo.history("sig-001")
        assert [h.to_state for h in history] == [
            SignalState.PENDING_PUSH,
            SignalState.WATCHING,
            SignalState.ACTIVE,
        ]

    def test_非法迁移被拒_状态回滚审计不留痕(self, store: SqliteStore) -> None:
        """★ GENERATED -> TAKE_PROFIT 不在迁移表：必须显式失败。"""
        sig_repo = SqliteSignalRepository(store)
        repo = SqliteLifecycleRepository(store)
        sig_repo.save(make_signal())

        with pytest.raises(IllegalTransitionError):
            repo.apply_transition(
                "sig-001", SignalState.TAKE_PROFIT, actor=Actor.SYSTEM, reason="跳变"
            )
        # 事务回滚：状态没变、审计没落
        assert sig_repo.get("sig-001").state is SignalState.GENERATED
        assert repo.history("sig-001") == []

    def test_乐观并发冲突(self, store: SqliteStore) -> None:
        sig_repo = SqliteSignalRepository(store)
        repo = SqliteLifecycleRepository(store)
        sig_repo.save(make_signal())

        with pytest.raises(IllegalTransitionError, match="乐观并发冲突"):
            repo.apply_transition(
                "sig-001",
                SignalState.PENDING_PUSH,
                actor=Actor.SYSTEM,
                reason="r",
                expected_from=SignalState.WATCHING,  # 期望值与实际不符
            )

    def test_不存在的信号拒绝迁移(self, store: SqliteStore) -> None:
        repo = SqliteLifecycleRepository(store)
        with pytest.raises(KeyError, match="ghost"):
            repo.apply_transition("ghost", SignalState.PENDING_PUSH, actor=Actor.SYSTEM, reason="r")

    def test_自迁移被拒(self, store: SqliteStore) -> None:
        sig_repo = SqliteSignalRepository(store)
        repo = SqliteLifecycleRepository(store)
        sig_repo.save(make_signal(state=SignalState.WATCHING))
        with pytest.raises(IllegalTransitionError, match="自迁移"):
            repo.apply_transition("sig-001", SignalState.WATCHING, actor=Actor.SYSTEM, reason="r")

    def test_孤儿巡检(self, store: SqliteStore) -> None:
        """as_of 距今 > max_holding_days + buffer 的非终止信号是孤儿。"""
        sig_repo = SqliteSignalRepository(store)
        repo = SqliteLifecycleRepository(store)
        today = date(2026, 3, 1)

        # 孤儿：as_of 在 40 天前，max_holding_days=20，buffer=5 → 40 > 25
        sig_repo.save(
            make_signal(
                signal_id="orphan", as_of=today - timedelta(days=40), state=SignalState.ACTIVE
            )
        )
        # 正常：3 天前
        sig_repo.save(
            make_signal(
                signal_id="fresh", as_of=today - timedelta(days=3), state=SignalState.ACTIVE
            )
        )
        # 终止信号（ARCHIVED）即使超龄也不算孤儿（已有始有终）
        # ★ TAKE_PROFIT 是"业务终态但未归档"，仍需后续处理，所以仍会出现在孤儿里 ——
        #   这是有意为之：孤儿巡检的职责是"该收尾没收尾"的信号。
        sig_repo.save(
            make_signal(
                signal_id="closed",
                as_of=today - timedelta(days=40),
                state=SignalState.ARCHIVED,
            )
        )

        orphans = repo.find_orphans(as_of=today, buffer_days=5)
        assert [s.signal_id for s in orphans] == ["orphan"]


# ============================================================
# 推送回执
# ============================================================
class TestPushReceiptRepository:
    def test_成功率统计(self, store: SqliteStore) -> None:
        repo = SqlitePushReceiptRepository(store)
        repo.save(PushReceipt(day=AS_OF, channel="feishu", ok=True, signal_id="s1"))
        repo.save(PushReceipt(day=AS_OF, channel="feishu", ok=False, signal_id="s2", detail="超时"))
        assert repo.success_rate(AS_OF) == 0.5

    def test_无记录返回零而非NaN(self, store: SqliteStore) -> None:
        repo = SqlitePushReceiptRepository(store)
        assert repo.success_rate(AS_OF) == 0.0

    def test_按日隔离(self, store: SqliteStore) -> None:
        repo = SqlitePushReceiptRepository(store)
        repo.save(PushReceipt(day=AS_OF, channel="feishu", ok=False))
        repo.save(PushReceipt(day=AS_OF + timedelta(days=1), channel="feishu", ok=True))
        assert repo.success_rate(AS_OF) == 0.0
        assert repo.success_rate(AS_OF + timedelta(days=1)) == 1.0

    def test_拒绝非回执类型(self, store: SqliteStore) -> None:
        """静默丢弃陌生类型 = v1 式静默失败，宁可炸。"""
        repo = SqlitePushReceiptRepository(store)
        with pytest.raises(TypeError, match="只接受 PushReceipt"):
            repo.save({"day": AS_OF, "ok": True})  # type: ignore[arg-type]


# ============================================================
# 心跳
# ============================================================
class TestHeartbeatRepository:
    def test_登记与完成(self, store: SqliteStore) -> None:
        repo = SqliteHeartbeatRepository(store)
        repo.expect("morning_scan", AS_OF, expected_by=datetime(2026, 1, 5, 7, 30, tzinfo=UTC))
        repo.mark_finished("morning_scan", AS_OF, run_id="run-123")

        assert repo.missing(as_of=AS_OF) == []
        row = store.conn.execute("SELECT status, run_id FROM heartbeats").fetchone()
        assert row["status"] == "FINISHED"
        assert row["run_id"] == "run-123"

    def test_未完成的心跳出现在missing(self, store: SqliteStore) -> None:
        """★ 自杀式心跳：任务没跑/没跑完，watchdog 必须能看到。"""
        repo = SqliteHeartbeatRepository(store)
        repo.expect("morning_scan", AS_OF, expected_by=datetime(2026, 1, 5, 7, 30, tzinfo=UTC))
        # 不 mark_finished
        missing = repo.missing(as_of=AS_OF)
        assert len(missing) == 1
        assert missing[0]["job_name"] == "morning_scan"

    def test_重复登记幂等(self, store: SqliteStore) -> None:
        repo = SqliteHeartbeatRepository(store)
        repo.expect("job", AS_OF, expected_by=datetime(2026, 1, 5, 7, 30, tzinfo=UTC))
        repo.expect("job", AS_OF, expected_by=datetime(2026, 1, 5, 7, 30, tzinfo=UTC))
        count = store.conn.execute("SELECT COUNT(*) FROM heartbeats").fetchone()[0]
        assert count == 1

    def test_完成不存在的heartbeat拒绝(self, store: SqliteStore) -> None:
        repo = SqliteHeartbeatRepository(store)
        with pytest.raises(KeyError, match="不存在"):
            repo.mark_finished("ghost", AS_OF, run_id="r")

    def test_未来日期的心跳不算缺失(self, store: SqliteStore) -> None:
        repo = SqliteHeartbeatRepository(store)
        future = AS_OF + timedelta(days=2)
        repo.expect("job", future, expected_by=datetime(2026, 1, 7, 7, 30, tzinfo=UTC))
        assert repo.missing(as_of=AS_OF) == []
