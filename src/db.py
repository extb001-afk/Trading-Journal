"""SQLite ledger schema and access helpers."""
import sqlite3

import common

SCHEMA_VERSION = 2

DDL = [
    "PRAGMA journal_mode=WAL",
    """CREATE TABLE IF NOT EXISTS meta (
        k TEXT PRIMARY KEY, v TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS raw_txs (
        chain TEXT NOT NULL, txhash TEXT NOT NULL,
        block INTEGER, blockhash TEXT, ts INTEGER,
        snapshot TEXT NOT NULL,             -- 완전 스냅샷 json
        wallets TEXT NOT NULL,              -- 관점 지갑 json 배열
        ingested_at INTEGER NOT NULL,
        PRIMARY KEY (chain, txhash))""",
    """CREATE TABLE IF NOT EXISTS raw_ex (
        exchange TEXT NOT NULL, kind TEXT NOT NULL,
        uuid TEXT NOT NULL,                 -- 어댑터 합성 정규화 이벤트 ID
        revision INTEGER NOT NULL,
        payload TEXT NOT NULL, observed_at INTEGER NOT NULL,
        PRIMARY KEY (exchange, kind, uuid, revision))""",
    """CREATE TABLE IF NOT EXISTS raw_observations (
        obs_id TEXT PRIMARY KEY,            -- 등록 스냅샷·주기 대사 관측 (opening/adjustment 재파생 근거)
        kind TEXT NOT NULL, venue TEXT NOT NULL,
        payload TEXT NOT NULL, observed_at INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS decisions (
        decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL, target TEXT NOT NULL,
        payload TEXT NOT NULL, created_at INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS wallets (
        chain TEXT NOT NULL, address TEXT NOT NULL,
        label TEXT, added_at INTEGER NOT NULL,
        PRIMARY KEY (chain, address))""",
    """CREATE TABLE IF NOT EXISTS assets (
        asset_id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,                 -- native|token|fiat|exchange_currency
        chain TEXT,                         -- native/token 만
        address TEXT,                       -- token CA / mint (소문자 정규화)
        symbol TEXT, decimals INTEGER,
        confirmed INTEGER NOT NULL DEFAULT 0,
        hidden INTEGER NOT NULL DEFAULT 0,
        group_id INTEGER,
        UNIQUE (kind, chain, address))""",
    """CREATE TABLE IF NOT EXISTS asset_groups (
        group_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE, norm_decimals INTEGER NOT NULL DEFAULT 18)""",
    """CREATE TABLE IF NOT EXISTS exchange_addresses (
        exchange TEXT NOT NULL, chain TEXT NOT NULL, address TEXT NOT NULL,
        currency TEXT, memo TEXT, sync_state TEXT NOT NULL DEFAULT 'manual',
        PRIMARY KEY (exchange, chain, address))""",
    """CREATE TABLE IF NOT EXISTS postings (
        posting_id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_kind TEXT NOT NULL, source_ns TEXT NOT NULL,
        source_id TEXT NOT NULL, leg_seq INTEGER NOT NULL,
        event_ts INTEGER NOT NULL,
        asset_id INTEGER NOT NULL,
        location TEXT NOT NULL,
        qty_base TEXT NOT NULL,             -- base-unit 정수 문자열(부호 포함)
        cost_usd TEXT,                      -- NULL = 원가 미상
        cost_krw TEXT,
        leg_kind TEXT NOT NULL,             -- acq|disp|move_in|move_out|fee|gas|adj|opening
        event TEXT NOT NULL,                -- SWAP|CONVERT|TRANSFER_SELF|... (5장)
        classifier_ver INTEGER NOT NULL,
        UNIQUE (source_kind, source_ns, source_id, leg_seq))""",
    """CREATE TABLE IF NOT EXISTS tx_class (
        chain TEXT NOT NULL, txhash TEXT NOT NULL,
        event TEXT NOT NULL, detail TEXT, classifier_ver INTEGER NOT NULL,
        PRIMARY KEY (chain, txhash))""",
    """CREATE TABLE IF NOT EXISTS transfers (
        transfer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        state TEXT NOT NULL,                -- sent|credited|bridging|arrived
        asset_id INTEGER NOT NULL, qty_base TEXT NOT NULL,
        src TEXT NOT NULL, dst TEXT,
        chain_txhash TEXT, ex_uuid TEXT, updated_at INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS positions (
        group_id INTEGER NOT NULL, location TEXT NOT NULL,
        qty_norm TEXT NOT NULL,             -- 정규화 Decimal 문자열
        qty_unknown_norm TEXT NOT NULL DEFAULT '0',
        cost_alloc_usd TEXT NOT NULL DEFAULT '0',
        PRIMARY KEY (group_id, location))""",
    """CREATE TABLE IF NOT EXISTS snapshots (
        day TEXT NOT NULL, group_id INTEGER NOT NULL, location TEXT NOT NULL,
        qty_norm TEXT NOT NULL, px_usd TEXT, px_stale INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (day, group_id, location))""",
    """CREATE TABLE IF NOT EXISTS journal (
        flow_id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL, state TEXT NOT NULL,   -- open|closed
        opened_ts INTEGER, closed_ts INTEGER, detail TEXT)""",
    """CREATE TABLE IF NOT EXISTS alerts_sent (
        key TEXT PRIMARY KEY, sent_at INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS inbox_offsets (
        stream TEXT PRIMARY KEY, seg INTEGER NOT NULL, off INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS raw_rewrites (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        chain TEXT NOT NULL, txhash TEXT NOT NULL, at INTEGER NOT NULL)""",
    """CREATE TRIGGER IF NOT EXISTS raw_txs_rewrite_upd AFTER UPDATE OF snapshot, chain, txhash ON raw_txs
        BEGIN
            INSERT INTO raw_rewrites (chain, txhash, at) VALUES (NEW.chain, NEW.txhash, CAST(strftime('%s', 'now') AS INTEGER));
            INSERT INTO raw_rewrites (chain, txhash, at) SELECT OLD.chain, OLD.txhash, CAST(strftime('%s', 'now') AS INTEGER)
                WHERE OLD.chain IS NOT NEW.chain OR OLD.txhash IS NOT NEW.txhash;
        END""",
    """CREATE TRIGGER IF NOT EXISTS raw_txs_rewrite_del AFTER DELETE ON raw_txs
        BEGIN
            INSERT INTO raw_rewrites (chain, txhash, at) VALUES (OLD.chain, OLD.txhash, CAST(strftime('%s', 'now') AS INTEGER));
        END""",
    """CREATE TABLE IF NOT EXISTS exf_late_pending (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ex TEXT NOT NULL, lb TEXT NOT NULL, lbi INTEGER NOT NULL,
        lbn INTEGER NOT NULL, sym TEXT, ts INTEGER, amt TEXT, at INTEGER NOT NULL, lc TEXT)""",
    """CREATE TABLE IF NOT EXISTS exf_adj_tomb (
        ex TEXT NOT NULL, sym TEXT NOT NULL, bts INTEGER NOT NULL, PRIMARY KEY (ex, sym, bts))""",
    "CREATE INDEX IF NOT EXISTS postings_asset_leg ON postings(asset_id, leg_kind)",
    "CREATE INDEX IF NOT EXISTS postings_loc_ts ON postings(location, event_ts)",
]


def open_db(path: str, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(common.sqlite_ro_uri(path), uri=True, timeout=10)
    else:
        conn = sqlite3.connect(path, timeout=30)
        has_meta = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
        row = conn.execute("SELECT v FROM meta WHERE k='schema_version'").fetchone() if has_meta else None
        if row is not None and int(row[0]) > SCHEMA_VERSION:
            conn.close()
            raise SystemExit(f"DB 스키마({row[0]})가 코드({SCHEMA_VERSION})보다 최신 — 전진만 허용")
        for ddl in DDL:
            conn.execute(ddl)
        if row is None:
            conn.execute("INSERT OR IGNORE INTO meta (k, v) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        conn.commit()
    conn.row_factory = sqlite3.Row
    return conn
