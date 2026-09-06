-- ============================================================
-- 001_init.sql —— v2 初始 schema（T02.1）
--
-- ★ 设计纪律：
--   1. SQLite 只存"小而行数可控"的数据（信号/审计/心跳/回执/告警/检查点）。
--      行情大数据一律走 Parquet（parquet_bar_store.py），不进 SQLite。
--   2. WAL 必开（连接工厂里 PRAGMA journal_mode=WAL）—— 单人内网部署，
--      读写并发场景是"每日任务写 + 人肉查库"，WAL 足够且免锁库。
--   3. 时间戳一律存 ISO8601 UTC 字符串：SQLite 没有原生时间类型，
--      字符串排序 == 时间排序，且跨语言可读。
--   4. 复杂实体（Signal 等）主列 + payload JSON 双写：
--      主列供 SQL 过滤（state/symbol/as_of），payload 保完整实体。
-- ============================================================

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL,
    applied_at TEXT    NOT NULL
);

-- ------------------------------------------------------------
-- 信号主表（SignalRepository）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signals (
    signal_id    TEXT PRIMARY KEY,
    state        TEXT NOT NULL,
    strategy_id  TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    market       TEXT NOT NULL,
    as_of        TEXT NOT NULL,            -- ISO 日期
    generated_at TEXT NOT NULL,            -- ISO 时间戳（UTC）
    updated_at   TEXT NOT NULL,
    payload      TEXT NOT NULL             -- Signal 完整 JSON（pydantic 序列化）
);
CREATE INDEX IF NOT EXISTS idx_signals_state   ON signals(state);
CREATE INDEX IF NOT EXISTS idx_signals_as_of   ON signals(as_of);
CREATE INDEX IF NOT EXISTS idx_signals_symbol  ON signals(symbol);

-- ------------------------------------------------------------
-- 状态迁移审计（LifecycleRepository）—— 与 signals.state 同事务写
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signal_transitions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id   TEXT NOT NULL REFERENCES signals(signal_id),
    from_state  TEXT NOT NULL,
    to_state    TEXT NOT NULL,
    actor       TEXT NOT NULL,
    reason      TEXT NOT NULL,
    at          TEXT NOT NULL,
    payload     TEXT NOT NULL DEFAULT '{}'  -- 触发时的价格/阈值快照
);
CREATE INDEX IF NOT EXISTS idx_transitions_signal ON signal_transitions(signal_id, at);

-- ------------------------------------------------------------
-- 推送回执（PushReceiptRepository / N-02 送达率观测）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS push_receipts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    day         TEXT NOT NULL,             -- 归属日（统计口径，ISO 日期）
    signal_id   TEXT,
    channel     TEXT NOT NULL,             -- 'feishu' | 'email' | ...
    ok          INTEGER NOT NULL,          -- 0/1
    detail      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_receipts_day ON push_receipts(day);

-- ------------------------------------------------------------
-- 心跳（HeartbeatRepository / N-03 自杀式心跳）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS heartbeats (
    job_name       TEXT NOT NULL,
    scheduled_date TEXT NOT NULL,          -- 计划归属日（ISO 日期）
    expected_by    TEXT NOT NULL,
    first_seen_at  TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING | FINISHED
    run_id         TEXT,
    finished_at    TEXT,
    PRIMARY KEY (job_name, scheduled_date)
);

-- ------------------------------------------------------------
-- 告警（D-10 禁止静默降级 —— 降级/门禁失败必须落表）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    level      TEXT NOT NULL,              -- 'P0' | 'P1' | 'P2'
    source     TEXT NOT NULL,              -- 'resilient_source' | 'data_quality' | ...
    message    TEXT NOT NULL,
    payload    TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts_level ON alerts(level, created_at);

-- ------------------------------------------------------------
-- 数据同步运行与检查点（T02.2 断点续跑）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sync_runs (
    run_id      TEXT PRIMARY KEY,
    market      TEXT NOT NULL,
    as_of       TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL DEFAULT 'RUNNING',  -- RUNNING | COMPLETED | COMPLETED_WITH_WARNINGS | HALTED | FAILED
    stats       TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS sync_checkpoints (
    market     TEXT NOT NULL,
    as_of      TEXT NOT NULL,
    batch_no   INTEGER NOT NULL,
    last_symbol TEXT,
    done_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (market, as_of, batch_no)
);

-- ------------------------------------------------------------
-- 运行清单（run_manifest / D-04 可复现性）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS run_manifests (
    run_id           TEXT PRIMARY KEY,
    git_sha          TEXT NOT NULL,
    dirty            INTEGER NOT NULL DEFAULT 0,
    data_fingerprint TEXT NOT NULL,
    config_hash      TEXT NOT NULL,
    seed             INTEGER,
    payload          TEXT NOT NULL DEFAULT '{}',
    created_at       TEXT NOT NULL
);

-- ------------------------------------------------------------
-- 数据质量报告（T02.6 门禁落盘）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS data_quality_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    market      TEXT NOT NULL,
    as_of       TEXT NOT NULL,
    checked_at  TEXT NOT NULL,
    status      TEXT NOT NULL,             -- PASS | WARN | FAIL
    report      TEXT NOT NULL              -- 完整 JSON（逐指标明细）
);
CREATE INDEX IF NOT EXISTS idx_dq_market_day ON data_quality_reports(market, as_of);

-- ------------------------------------------------------------
-- 分区指纹登记（D-11 幂等验收：同日重跑指纹必须一致）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS partition_fingerprints (
    market     TEXT NOT NULL,
    dt         TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (market, dt)
);

-- ------------------------------------------------------------
-- PIT 股票池日快照（T02.5）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pit_universe (
    as_of         TEXT NOT NULL,           -- 快照日（必须是交易日）
    symbol        TEXT NOT NULL,
    code_name     TEXT NOT NULL DEFAULT '',
    is_st         INTEGER NOT NULL DEFAULT 0,
    is_st_source  TEXT NOT NULL DEFAULT 'NAME_PARSE',  -- NAME_PARSE | OFFICIAL | NONE
    trade_status  TEXT NOT NULL DEFAULT 'TRADING',     -- TRADING | SUSPENDED
    ipo_date      TEXT,
    out_date      TEXT,
    PRIMARY KEY (as_of, symbol)
);
CREATE INDEX IF NOT EXISTS idx_pit_symbol ON pit_universe(symbol, as_of);
