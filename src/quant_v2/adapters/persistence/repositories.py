"""仓库实现（repository_port 的 SQLite 落地，T02.1）。

★ `SqliteLifecycleRepository.apply_transition` 是**全项目唯一写信号状态的地方**：
同事务更新 `signals.state` + 插入 `signal_transitions` 审计行（L-04）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from quant_v2.adapters.persistence.sqlite_store import SqliteStore, utc_now_iso
from quant_v2.domain.errors import IllegalTransitionError
from quant_v2.domain.models.bar import InstrumentType  # noqa: F401  (re-export convenience)
from quant_v2.domain.models.lifecycle import Actor, SignalState, TransitionRecord
from quant_v2.domain.models.signal import Signal
from quant_v2.domain.services.lifecycle_machine import require_transition

__all__ = [
    "PitRow",
    "PushReceipt",
    "SqliteHeartbeatRepository",
    "SqliteLifecycleRepository",
    "SqlitePitUniverseRepository",
    "SqlitePushReceiptRepository",
    "SqliteSignalRepository",
]


# ============================================================
# 信号主表
# ============================================================
class SqliteSignalRepository:
    """实现 `SignalRepository`。"""

    def __init__(self, store: SqliteStore) -> None:
        self.store = store

    def save(self, signal: Signal) -> None:
        """upsert 信号。"""
        payload = signal.model_dump_json()
        with self.store.conn:
            self.store.conn.execute(
                """
                INSERT INTO signals(signal_id, state, strategy_id, symbol, market,
                                     as_of, generated_at, updated_at, payload)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(signal_id) DO UPDATE SET
                    state=excluded.state, payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (
                    signal.signal_id,
                    signal.state.value,
                    signal.strategy_id,
                    signal.symbol,
                    signal.market,
                    signal.as_of.isoformat(),
                    signal.generated_at.isoformat(),
                    utc_now_iso(),
                    payload,
                ),
            )

    def get(self, signal_id: str) -> Signal | None:
        row = self.store.conn.execute(
            "SELECT payload FROM signals WHERE signal_id = ?", (signal_id,)
        ).fetchone()
        if row is None:
            return None
        return Signal.model_validate_json(row["payload"])

    def list_open(self, *, as_of: date) -> Sequence[Signal]:
        """非终止状态（需要继续跟踪）。`as_of` 参与 SQL 只是缩小扫描面。"""
        terminal = _terminal_state_values()
        placeholders = ",".join("?" * len(terminal))
        rows = self.store.conn.execute(
            f"SELECT payload FROM signals WHERE state NOT IN ({placeholders}) "  # noqa: S608 -- 仅拼接 ? 占位符，值全部参数绑定
            "AND as_of <= ? ORDER BY as_of, signal_id",
            (*terminal, as_of.isoformat()),
        ).fetchall()
        return [Signal.model_validate_json(r["payload"]) for r in rows]

    def list_by_state(self, state: SignalState) -> Sequence[Signal]:
        rows = self.store.conn.execute(
            "SELECT payload FROM signals WHERE state = ? ORDER BY generated_at, signal_id",
            (state.value,),
        ).fetchall()
        return [Signal.model_validate_json(r["payload"]) for r in rows]


# ============================================================
# 生命周期（唯一写状态的入口）
# ============================================================
class SqliteLifecycleRepository:
    """实现 `LifecycleRepository`。"""

    def __init__(self, store: SqliteStore) -> None:
        self.store = store

    def apply_transition(
        self,
        signal_id: str,
        to_state: SignalState,
        *,
        actor: Actor,
        reason: str,
        payload: Mapping[str, Any] | None = None,
        expected_from: SignalState | None = None,
    ) -> TransitionRecord:
        """同事务：读当前状态 → 校验迁移合法性 → 更新主表 → 落审计。

        Raises:
            KeyError: 信号不存在（对不存在的信号做迁移等于审计造假）。
            IllegalTransitionError: 迁移不合法 / 乐观并发冲突。
        """
        record = TransitionRecord(
            signal_id=signal_id,
            from_state=SignalState.GENERATED,  # 占位，事务内以真实值覆写
            to_state=to_state,
            actor=actor,
            reason=reason,
            at=datetime.now(UTC),
            payload=payload or {},
        )
        payload_json = json.dumps(dict(record.payload), ensure_ascii=False, default=str)

        with self.store.conn:  # ★ 同事务：状态 + 审计要么都成要么都不成
            row = self.store.conn.execute(
                "SELECT payload FROM signals WHERE signal_id = ?", (signal_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"信号不存在：{signal_id}（不能对不存在的信号做状态迁移）")
            current = Signal.model_validate_json(row["payload"])
            from_state = current.state

            if from_state is to_state:
                raise IllegalTransitionError(
                    f"不允许自迁移：{from_state.value} -> {to_state.value}"
                )
            if expected_from is not None and from_state is not expected_from:
                raise IllegalTransitionError(
                    f"乐观并发冲突：期望从 {expected_from.value} 迁移，"
                    f"实际当前状态 {from_state.value}"
                )
            require_transition(from_state, to_state)  # 领域迁移表二次把关

            updated = current.model_copy(update={"state": to_state})
            self.store.conn.execute(
                "UPDATE signals SET state = ?, payload = ?, updated_at = ? WHERE signal_id = ?",
                (to_state.value, updated.model_dump_json(), utc_now_iso(), signal_id),
            )
            self.store.conn.execute(
                """
                INSERT INTO signal_transitions(
                    signal_id, from_state, to_state, actor, reason, at, payload)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal_id,
                    from_state.value,
                    to_state.value,
                    actor.value,
                    reason,
                    record.at.isoformat(),
                    payload_json,
                ),
            )

        return TransitionRecord(
            signal_id=signal_id,
            from_state=from_state,
            to_state=to_state,
            actor=actor,
            reason=reason,
            at=record.at,
            payload=payload or {},
        )

    def history(self, signal_id: str) -> Sequence[TransitionRecord]:
        rows = self.store.conn.execute(
            "SELECT * FROM signal_transitions WHERE signal_id = ? ORDER BY at, id",
            (signal_id,),
        ).fetchall()
        return [
            TransitionRecord(
                signal_id=r["signal_id"],
                from_state=SignalState(r["from_state"]),
                to_state=SignalState(r["to_state"]),
                actor=Actor(r["actor"]),
                reason=r["reason"],
                at=datetime.fromisoformat(r["at"]),
                payload=json.loads(r["payload"]),
            )
            for r in rows
        ]

    def find_orphans(self, *, as_of: date, buffer_days: int = 5) -> Sequence[Signal]:
        """非终止 且 as_of 距今超过 max_holding_days + buffer 的信号。"""
        terminal = _terminal_state_values()
        placeholders = ",".join("?" * len(terminal))
        rows = self.store.conn.execute(
            f"SELECT payload FROM signals WHERE state NOT IN ({placeholders})",  # noqa: S608 -- 仅拼接 ? 占位符，值全部参数绑定
            (*terminal,),
        ).fetchall()
        orphans: list[Signal] = []
        for r in rows:
            sig = Signal.model_validate_json(r["payload"])
            age_days = (as_of - sig.as_of).days
            if age_days > sig.max_holding_days + buffer_days:
                orphans.append(sig)
        return orphans


# ============================================================
# 推送回执
# ============================================================
@dataclass(frozen=True)
class PushReceipt:
    """回执实体（适配层定义，领域层只见 `Any`）。"""

    day: date
    channel: str
    ok: bool
    signal_id: str | None = None
    detail: str = ""
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.created_at is None:
            object.__setattr__(self, "created_at", datetime.now(UTC))


class SqlitePushReceiptRepository:
    """实现 `PushReceiptRepository`。"""

    def __init__(self, store: SqliteStore) -> None:
        self.store = store

    def save(self, receipt: Any) -> None:
        """落一条回执。只接受 `PushReceipt` —— 收到别的类型直接炸，
        比静默丢弃强（那是 v1 式静默失败）。"""
        if not isinstance(receipt, PushReceipt):
            raise TypeError(
                f"SqlitePushReceiptRepository 只接受 PushReceipt，收到 {type(receipt).__name__}"
            )
        with self.store.conn:
            self.store.conn.execute(
                """
                INSERT INTO push_receipts(day, signal_id, channel, ok, detail, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.day.isoformat(),
                    receipt.signal_id,
                    receipt.channel,
                    1 if receipt.ok else 0,
                    receipt.detail,
                    (receipt.created_at or datetime.now(UTC)).isoformat(),
                ),
            )

    def success_rate(self, day: date) -> float:
        """当日推送成功率（无记录 → 0.0，绝不返回 NaN）。"""
        row = self.store.conn.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(ok), 0) AS ok_count "
            "FROM push_receipts WHERE day = ?",
            (day.isoformat(),),
        ).fetchone()
        total = int(row["total"])
        if total == 0:
            return 0.0
        return int(row["ok_count"]) / total


# ============================================================
# 心跳
# ============================================================
class SqliteHeartbeatRepository:
    """实现 `HeartbeatRepository`（N-03 自杀式心跳）。"""

    def __init__(self, store: SqliteStore) -> None:
        self.store = store

    def expect(self, job_name: str, scheduled_date: date, *, expected_by: datetime) -> None:
        """登记预期心跳（任务启动即写，不等结束）。重复登记 = 幂等 no-op。"""
        with self.store.conn:
            self.store.conn.execute(
                """
                INSERT INTO heartbeats(job_name, scheduled_date, expected_by,
                                       first_seen_at, status)
                VALUES(?, ?, ?, ?, 'PENDING')
                ON CONFLICT(job_name, scheduled_date) DO NOTHING
                """,
                (job_name, scheduled_date.isoformat(), expected_by.isoformat(), utc_now_iso()),
            )

    def mark_finished(self, job_name: str, scheduled_date: date, *, run_id: str) -> None:
        """标记完成。没有对应 PENDING 记录 → KeyError（凭空出现的 FINISHED 是数据损坏）。"""
        with self.store.conn:
            cur = self.store.conn.execute(
                """
                UPDATE heartbeats
                SET status = 'FINISHED', run_id = ?, finished_at = ?
                WHERE job_name = ? AND scheduled_date = ?
                """,
                (run_id, utc_now_iso(), job_name, scheduled_date.isoformat()),
            )
            if cur.rowcount == 0:
                raise KeyError(f"心跳不存在，无法标记完成：{job_name} @ {scheduled_date}")

    def missing(self, *, as_of: date) -> Sequence[dict[str, str]]:
        """缺失/超时的心跳（watchdog 每日检查的输入）。"""
        rows = self.store.conn.execute(
            "SELECT * FROM heartbeats WHERE scheduled_date <= ? AND status != 'FINISHED'",
            (as_of.isoformat(),),
        ).fetchall()
        return [dict(row) for row in rows]


def _terminal_state_values() -> tuple[str, ...]:
    """终止状态值（SQL IN 参数）。"""
    from quant_v2.domain.models.lifecycle import TERMINAL_STATES  # noqa: PLC0415

    return tuple(s.value for s in TERMINAL_STATES)


# ============================================================
# PIT 股票池（T02.5，D-05）
# ============================================================
@dataclass(frozen=True)
class PitRow:
    """`pit_universe` 表的一行（快照日 × 标的）。

    `is_st_source` 是 provenance：'NAME_PARSE'（M-20：从名称正则解析）、
    'OFFICIAL'（未来有独立 ST 字段的源）、'NONE'。
    `trade_status`：'TRADING' | 'SUSPENDED'（★ 停牌标记，不是 ST）。
    """

    as_of: date
    symbol: str  # 归一化代码（600000.SH）
    code_name: str
    is_st: bool
    is_st_source: str = "NAME_PARSE"
    trade_status: str = "TRADING"


class SqlitePitUniverseRepository:
    """PIT 池快照的读写（建池作业写 / provider 读缓存 / 名称突变检测读）。"""

    def __init__(self, store: SqliteStore) -> None:
        self.store = store

    def save_snapshot(self, rows: Sequence[PitRow]) -> None:
        """落一个快照日的全部行（INSERT OR REPLACE：重跑幂等，D-11 同款语义）。"""
        if not rows:
            raise ValueError("拒绝写入空快照（M-19：交易日 0 rows 是 P0，不是空池子）")
        with self.store.conn:
            self.store.conn.executemany(
                """
                INSERT OR REPLACE INTO pit_universe
                    (as_of, symbol, code_name, is_st, is_st_source, trade_status)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        r.as_of.isoformat(),
                        r.symbol,
                        r.code_name,
                        int(r.is_st),
                        r.is_st_source,
                        r.trade_status,
                    )
                    for r in rows
                ],
            )

    def load_snapshot(self, as_of: date) -> list[PitRow]:
        """读一个快照日（无快照返回空列表 —— 缓存未命中）。"""
        rows = self.store.conn.execute(
            """
            SELECT as_of, symbol, code_name, is_st, is_st_source, trade_status
            FROM pit_universe WHERE as_of = ? ORDER BY symbol
            """,
            (as_of.isoformat(),),
        ).fetchall()
        return [
            PitRow(
                as_of=date.fromisoformat(row["as_of"]),
                symbol=row["symbol"],
                code_name=row["code_name"],
                is_st=bool(row["is_st"]),
                is_st_source=row["is_st_source"],
                trade_status=row["trade_status"],
            )
            for row in rows
        ]

    def snapshot_dates(self) -> list[date]:
        """已落库的快照日（升序）—— 建池作业的断点续跑依据。"""
        rows = self.store.conn.execute(
            "SELECT DISTINCT as_of FROM pit_universe ORDER BY as_of"
        ).fetchall()
        return [date.fromisoformat(row["as_of"]) for row in rows]

    def previous_snapshot(self, as_of: date) -> tuple[date, list[PitRow]] | None:
        """严格早于 `as_of` 的最近一个快照（名称突变检测的对照基准）。

        无更早快照返回 None（首个采样日没有对照，不 diff）。
        """
        row = self.store.conn.execute(
            "SELECT MAX(as_of) AS d FROM pit_universe WHERE as_of < ?",
            (as_of.isoformat(),),
        ).fetchone()
        if row is None or row["d"] is None:
            return None
        prev_day = date.fromisoformat(row["d"])
        return prev_day, self.load_snapshot(prev_day)
