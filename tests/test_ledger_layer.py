#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import ast
import glob
import json
import os
import sqlite3
from decimal import Decimal

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import common
import core

assert T.TMP in common.STATE_DIR
core.dm = lambda *a, **k: None
T.patch_moved("dm", core.dm)
chk = T.chk
LAYER = {"_post_leg", "_post_legs_strict", "_amend_leg", "_unpost_source"}

bad = []
for f in sorted(glob.glob(os.path.join(T.SRC, "*.py"))):
    tree = ast.parse(open(f, encoding="utf-8").read(), f)
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "_bump_position":
                if not (os.path.basename(f) == "core_post.py" and fn.name in LAYER):
                    bad.append(f"{os.path.basename(f)}:{n.lineno} {fn.name}")
chk(not bad, "L1 _bump_position 호출 = 원장 계층 함수 안에만", bad)

c = core.Core(common.load_config())
aid = c.asset_id("native", "eth", None, symbol="ETH", decimals=18)
LOC = "wallet:eth:0x00000000000000000000000000000000000000aa"
E18 = 10 ** 18


def pos():
    r = c.conn.execute("SELECT qty_norm FROM positions WHERE group_id=? AND location=?", (c._group_of(aid), LOC)).fetchone()
    return Decimal(r["qty_norm"]) if r else Decimal(0)


def led():
    s = sum(int(r[0]) for r in c.conn.execute("SELECT qty_base FROM postings WHERE asset_id=? AND location=?", (aid, LOC)))
    return Decimal(s) / Decimal(E18)


ok1 = c._post_leg("exchange", "t:trade", "f1", 0, 1000, aid, LOC, 3 * E18, None, None, "acq", "EXF_BUY")
ok2 = c._post_leg("exchange", "t:trade", "f1", 0, 1000, aid, LOC, 3 * E18, None, None, "acq", "EXF_BUY")
chk(ok1 is True and ok2 is False and pos() == 3 and led() == 3, "L2 _post_leg 두 번째 = 무동작(포지션 한 번)", (ok1, ok2, pos(), led()))
c._post_legs_strict([("chain_tx", "eth", "0xt1", 0, 1100, aid, LOC, 2 * E18, None, None, "in", "TRANSFER_IN"),
                     ("chain_tx", "eth", "0xt1", 1, 1100, aid, LOC, -1 * E18, None, None, "gas", "TRANSFER_IN")])
chk(pos() == 4 and led() == 4, "L2 _post_legs_strict 두 줄 = 포지션 +1", (pos(), led()))
c.conn.execute("SAVEPOINT l2")
try:
    c._post_legs_strict([("chain_tx", "eth", "0xt1", 0, 1100, aid, LOC, 2 * E18, None, None, "in", "TRANSFER_IN")])
    raised = False
except sqlite3.IntegrityError:
    raised = True
c.conn.execute("ROLLBACK TO l2")
c.conn.execute("RELEASE l2")
chk(raised and pos() == 4 and led() == 4, "L2 엄격 충돌 = IntegrityError(롤백 뒤 그대로)", (raised, pos(), led()))

c._post_leg_strict("opening", "eth", "op1", 0, 900, aid, LOC, 5 * E18, None, None, "opening", "OPENING", ver=4)
pid = c.conn.execute("SELECT posting_id, classifier_ver FROM postings WHERE source_id='op1'").fetchone()
chk(pid["classifier_ver"] == 4 and pos() == 9 and led() == 9, "L3 _post_leg_strict ver 그대로", (dict(pid), pos()))
c._amend_leg(pid["posting_id"], aid, LOC, -2 * E18, qb_new=3 * E18, ts=950)
r = c.conn.execute("SELECT qty_base, event_ts FROM postings WHERE posting_id=?", (pid["posting_id"],)).fetchone()
chk(r["qty_base"] == str(3 * E18) and r["event_ts"] == 950 and pos() == 7 and led() == 7, "L3 _amend_leg 수량·시각 = 포지션 짝", (dict(r), pos()))
c._amend_leg(pid["posting_id"], aid, LOC, 1 * E18, qb_new=4 * E18)
r = c.conn.execute("SELECT qty_base, event_ts FROM postings WHERE posting_id=?", (pid["posting_id"],)).fetchone()
chk(r["qty_base"] == str(4 * E18) and r["event_ts"] == 950 and pos() == 8 and led() == 8, "L3 _amend_leg 수량만(시각 그대로)", (dict(r), pos()))
c._amend_leg(pid["posting_id"], aid, LOC, -4 * E18)
chk(not c.conn.execute("SELECT 1 FROM postings WHERE posting_id=?", (pid["posting_id"],)).fetchone() and pos() == 4 and led() == 4,
    "L3 _amend_leg 삭제 = 포지션 짝", pos())
gone = c._unpost_source("chain_tx", "eth", "0xt1")
chk(len(gone) == 2 and {int(g["event_ts"]) for g in gone} == {1100} and pos() == 3 and led() == 3, "L3 _unpost_source 되감기 = 지운 줄 반환 · 포지션 짝",
    (len(gone), pos(), led()))
chk(c._unpost_source("chain_tx", "eth", "0xnone") == [] and pos() == 3, "L3 없는 출처 되감기 = 무동작")
c.conn.rollback()

T.finish()
