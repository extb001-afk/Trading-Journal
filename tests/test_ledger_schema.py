#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import sqlite3  # noqa: E402

import db  # noqa: E402
import paths  # noqa: E402

chk = T.chk
NAMES = [
    ("index", "postings_asset_leg"), ("index", "postings_loc_ts"),
    ("table", "alerts_sent"), ("table", "asset_groups"), ("table", "assets"), ("table", "decisions"), ("table", "exchange_addresses"),
    ("table", "exf_adj_tomb"), ("table", "exf_late_pending"), ("table", "inbox_offsets"), ("table", "journal"), ("table", "meta"),
    ("table", "positions"), ("table", "postings"), ("table", "raw_ex"), ("table", "raw_observations"), ("table", "raw_rewrites"),
    ("table", "raw_txs"), ("table", "snapshots"), ("table", "transfers"), ("table", "tx_class"), ("table", "wallets"),
    ("trigger", "raw_txs_rewrite_del"), ("trigger", "raw_txs_rewrite_upd"),
]
FP = "5d71b58de7b6a39bf6beff2ddd133e9e9e4aa9b4a23b40806bc098407534a450"


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def schema(conn):
    return sorted((r[0], r[1], r[2], norm(r[3])) for r in
                  conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))


def fingerprint(rows):
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()


p = os.path.join(T.TMP, "schema_new.db")
c = db.open_db(p)
rows = schema(c)
ver = c.execute("SELECT v FROM meta WHERE k='schema_version'").fetchone()
c.close()
chk(len(rows) == 24 and [(r[0], r[1]) for r in rows] == NAMES, "S1 새 원장 객체 24 · 이름 목록 고정", [(r[0], r[1]) for r in rows])
chk(sum(1 for r in rows if r[0] == "table") == 20 and sum(1 for r in rows if r[0] == "index") == 2
    and sum(1 for r in rows if r[0] == "trigger") == 2, "S1 표 20 · 인덱스 2 · 트리거 2")
fp = fingerprint(rows)
chk(fp == FP, "S2 스키마 지문 = 고정값(표·열·인덱스·트리거 글)", fp)
chk(db.SCHEMA_VERSION == 2 and ver is not None and str(ver[0]) == "2", "S3 schema_version = db.SCHEMA_VERSION = 2", ver and str(ver[0]))
ddl = [norm(x).upper() for x in db.DDL]
chk(len(ddl) == 25 and sum(1 for x in ddl if x.startswith("PRAGMA")) == 1
    and sum(1 for x in ddl if re.match(r"CREATE (TABLE|INDEX|UNIQUE INDEX|TRIGGER) IF NOT EXISTS ", x)) == 24
    and not any("ALTER " in x for x in ddl), "S3 DDL 25문장 = PRAGMA 1 + CREATE … IF NOT EXISTS 24 · ALTER 0", len(ddl))
c = db.open_db(p)
again = schema(c)
c.close()
chk(again == rows, "S3 같은 원장 다시 열어도 지문 같음(DDL 멱등)")

frozen = os.environ.get("TJ_TEST_FROZEN_LEDGER") or os.path.join(os.path.expanduser("~"), "tj_golden", "base0", "state", "ledger.db")
if os.path.isfile(frozen):
    ro = sqlite3.connect(paths.sqlite_ro_uri(frozen, immutable=True), uri=True)
    try:
        frows = schema(ro)
    finally:
        ro.close()
    chk(fingerprint(frows) == FP, "S4 내부 게이트: 동결 원장(immutable 읽기)도 같은 지문",
        {"원장에만": sorted(set((r[0], r[1]) for r in frows) - set(NAMES)), "새 원장에만": sorted(set(NAMES) - set((r[0], r[1]) for r in frows))})
else:
    print("SKIP S4 동결 원장 없음 — 내부 게이트 줄 건너뜀", flush=True)

T.finish()
