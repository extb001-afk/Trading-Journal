#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402

import paths  # noqa: E402
import bsc_watch  # noqa: E402

W = "0x" + "a1" * 20
con = sqlite3.connect(paths.DB_PATH)
con.execute("CREATE TABLE raw_ex (exchange TEXT NOT NULL, kind TEXT NOT NULL, uuid TEXT NOT NULL, revision INTEGER NOT NULL,"
            " payload TEXT NOT NULL, observed_at INTEGER NOT NULL, PRIMARY KEY (exchange, kind, uuid, revision))")


def tx(n):
    return "0x" + ("%064x" % n)


def wd(ex, uid, rev, txid, done):
    con.execute("INSERT INTO raw_ex VALUES (?,?,?,?,?,?)", (ex, "withdraw", uid, rev, json.dumps(
        {"currency": "BNB", "state": "DONE", "txid": txid, "network": "BSC", "address": W, "created_at": done, "done_at": done}), 1))


for i in range(15):
    wd("binance", f"o{i}", 1, tx(i + 1), f"2026-05-{i + 1:02d}T00:00:00Z")
NEW = tx(0xffff)
wd("binance", "n1", 1, NEW, "2026-10-01T09:00:00Z")
wd("bybit", "n1b", 1, NEW, "2026-10-01T09:05:00Z")
con.commit()

w = bsc_watch.BscWatcher.__new__(bsc_watch.BscWatcher)
w.wallets = [W]
c = w._xin_cands()
T.chk(c and c[0] == NEW, "X1 후보 순서 = 최신 출금 먼저", c[:3])
T.chk(len(c) == 16 and len(set(c)) == 16, "X3 같은 txid 하나로(16건)", len(c))

seen = []
w.conf_depth = 20
w.cursor = {"_cov": 1000, "from_block": 3000}
w.emitted = set()
w.emitted_path = os.path.join(paths.STATE_DIR, "emitted_bsc.json")


def details(hs):
    seen.extend(hs)
    return {h: RuntimeError("시험: 상세 없음") for h in hs}


w.fetch_details = details
T.patch_moved("_now", lambda: 1_800_000_000.0, ("bsc_",))
w._xin_pass(5000)
T.chk(NEW in seen and len(seen) == bsc_watch.XIN_MAX_NEW, f"X2 한 번 실행({bsc_watch.XIN_MAX_NEW}건) 안에 방금 출금 확인", seen[:3])
T.finish()
