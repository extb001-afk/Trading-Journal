#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _gate as _x
from _gate import check, done
import glob
import json
import math
import os
import subprocess
import time
import common
import core
import ops_requests as O
assert _x.TMP in common.STATE_DIR
core.dm = lambda *a, **k: None
c = core.Core(common.load_config())
S = common.STATE_DIR
APV = os.path.join(S, "rebuild_pnl_approve.json")
GATE = os.path.join(S, "rebuild_pnl_gate.json")
BASE = {"realized_by_month_baseline": {}, "realized_by_month_shadow": {}, "unverified_baseline": {"sum": 0, "rows": 0, "by": {}},
        "unverified_shadow": {"sum": 0, "rows": 0, "by": {}}, "open_cost_baseline": {}, "open_cost_shadow": {},
        "open_cost_held_cards": [0, 0], "open_cost_missing_groups": [0, 0]}
LOST0 = {"n": 0, "usd": 0, "top": [], "keys_sha": None}


def rp(g4=None, lost=None, dun=None, tag=""):
    d = {"G4_vs_baseline": dict(BASE, **(g4 or {})), "cost_lost": lost if lost is not None else LOST0,
         "decimals_unresolved": dun if dun is not None else [], "meta": {"tag": tag, "t": time.time_ns()}}
    p = os.path.join(_x.TMP, "a_%d.report.json" % time.time_ns())
    open(p, "w").write(json.dumps(d))
    return p


def gate(p, bcfg=None):
    return c._ext_pnl_gate(p, bcfg or {}, "시험")


def approve_last():
    g = O.pending_gate() or {}
    return O.approve(g.get("report_sha") or "", "시험")


def clear_apv():
    try:
        os.remove(APV)
    except OSError:
        pass


def ev(g4=None, lost=None):
    return O.gate_eval({"G4_vs_baseline": dict(BASE, **(g4 or {})), "cost_lost": lost if lost is not None else LOST0,
                        "decimals_unresolved": []}, 50, 0.01)


miss = {"open_cost_held_cards": [2, 2], "open_cost_missing_groups": [1, 1], "open_cost_baseline": {"12": 1000.0}}
A = rp(dict(miss, open_cost_shadow={"12": 1100.0}), tag="A")
gA = gate(A)
clear_apv()
okA, msgA = approve_last()
if not os.path.exists(APV) and gA.get("report_sha"):
    json.dump({"report_sha": gA["report_sha"], "until": int(time.time()) + 3600, "at": int(time.time()), "by": "시험"}, open(APV, "w"))
B = rp(dict(miss, open_cost_shadow={"12": 9000.0}), tag="B")
gB = gate(B)
check("[1] 같은 누락 표식 · 열린 원가 1100→9000 으로 바뀜 = 승인 통과 아님", not gB["ok"] and not gB.get("approved"), gB)
ev_a, ev_b = O.gate_eval(json.load(open(A)), 50, 0.01), O.gate_eval(json.load(open(B)), 50, 0.01)
check("[1] covers: 어느 쪽이든 빠진 재료가 있으면 덮지 않음", O.covers(ev_a, ev_b, 50, 0.01) != "" and O.covers(ev_a, ev_a, 50, 0.01) != "",
      (O.covers(ev_a, ev_b, 50, 0.01), O.covers(ev_a, ev_a, 50, 0.01)))

clear_apv()
gate(rp(dict(miss, open_cost_shadow={"12": 1100.0}), tag="A2"))
ok2, msg2 = approve_last()
st2 = O.status()
check("[2] 빠진 재료 보류 결과 → approve 거절 · 승인 파일 없음", not ok2 and not os.path.exists(APV), (ok2, msg2))
check("[2] 상태 패널 approvable=False · 빠진 재료 목록", (st2.get("pnl") or {}).get("approvable") is False and (st2.get("pnl") or {}).get("missing"),
      st2.get("pnl"))
t2 = subprocess.run([sys.executable, os.path.join(_x.TREE, "tools", "rebuild_approve.py"), "--yes"], env=dict(os.environ, TJ_BASE=_x.TMP),
                    capture_output=True, text=True, timeout=60)
check("[2] 도구 --yes 도 거절(rc≠0 · 승인 파일 없음)", t2.returncode != 0 and not os.path.exists(APV), (t2.returncode, t2.stdout[-300:], t2.stderr[-300:]))
gate(rp({"realized_by_month_baseline": {"2026-01": 0.0}, "realized_by_month_shadow": {"2026-01": 900.0}}, tag="ok2"))
ok2b, _m = approve_last()
check("[2] 재료가 다 있는 보류 결과는 승인 가능(기준)", ok2b and os.path.exists(APV), _m)
st2b = O.status()
check("[2] 그때 approvable=True", (st2b.get("pnl") or {}).get("approvable") is True, st2b.get("pnl"))
clear_apv()

u7 = {"unverified_baseline": {"sum": 0, "rows": 0, "by": {}}, "unverified_shadow": {"sum": 500, "rows": 1, "by": {"7": 500.0}}}
u8 = {"unverified_baseline": {"sum": 0, "rows": 0, "by": {}}, "unverified_shadow": {"sum": 500, "rows": 1, "by": {"8": 500.0}}}
u7b = {"unverified_baseline": {"sum": 30, "rows": 1, "by": {"9": 30.0}}, "unverified_shadow": {"sum": 530, "rows": 2, "by": {"9": 30.0, "7": 500.0}}}
unob = {"unverified_baseline": {"sum": 0, "rows": 0}, "unverified_shadow": {"sum": 500, "rows": 1}}
e7, e8, e7b, eno = ev(u7), ev(u8), ev(u7b), ev(unob)
check("[3] 같은 금액이 다른 그룹(7→8)에서 늘면 승인 아님", O.covers(e7, e8, 50, 0.01) != "", O.covers(e7, e8, 50, 0.01))
check("[3] 같은 그룹 증가(다른 그룹은 그대로) = 승인", O.covers(e7, e7b, 50, 0.01) == "", O.covers(e7, e7b, 50, 0.01))
check("[3] 그룹 재료(by) 없는 결과 = 승인 아님(비교 재료 없음)", O.covers(e7, eno, 50, 0.01) != "" and O.covers(eno, eno, 50, 0.01) != "",
      (O.covers(e7, eno, 50, 0.01), O.covers(eno, eno, 50, 0.01)))
unan = {"unverified_baseline": {"sum": 0, "rows": 0, "by": {}}, "unverified_shadow": {"sum": 500, "rows": 1, "by": {"7": float("nan")}}}
check("[3] 그룹 재료에 NaN = 승인 아님", O.covers(e7, ev(unan), 50, 0.01) != "", O.covers(e7, ev(unan), 50, 0.01))

k1 = {"n": 1, "usd": 200.0, "top": [{"key": ["exchange", "upbit", "t1", 0], "sym": "AAA", "cost_baseline": 200.0}], "keys_sha": "a" * 64}
k2 = {"n": 1, "usd": 200.0, "top": [{"key": ["exchange", "upbit", "t2", 0], "sym": "AAA", "cost_baseline": 200.0}], "keys_sha": "b" * 64}
k1n = dict(k1, keys_sha=None)
check("[4] 같은 개수·금액 · 다른 칸 = 승인 아님", O.covers(ev(lost=k1), ev(lost=k2), 50, 0.01) != "", O.covers(ev(lost=k1), ev(lost=k2), 50, 0.01))
check("[4] 같은 칸 = 승인", O.covers(ev(lost=k1), ev(lost=dict(k1)), 50, 0.01) == "", O.covers(ev(lost=k1), ev(lost=dict(k1)), 50, 0.01))
check("[4] 해시 없어도 10칸 이하 전체 목록이 같으면 승인", O.covers(ev(lost=k1n), ev(lost=k1n), 50, 0.01) == "", O.covers(ev(lost=k1n), ev(lost=k1n), 50, 0.01))
big = {"n": 12, "usd": 1200.0, "top": [{"key": ["exchange", "upbit", "t%d" % i, 0], "cost_baseline": 100.0} for i in range(10)]}
check("[4] 10칸 넘는데 전체 해시 없음 = 승인 아님", O.covers(ev(lost=big), ev(lost=dict(big)), 50, 0.01) != "", O.covers(ev(lost=big), ev(lost=dict(big)), 50, 0.01))
check("[4] 10칸 넘어도 전체 해시(칸·칸별 금액) 같음 = 승인 · 다르면 아님",
      O.covers(ev(lost=dict(big, keys_sha="c" * 64, costs_sha="e" * 64)), ev(lost=dict(big, keys_sha="c" * 64, costs_sha="e" * 64)), 50, 0.01) == ""
      and O.covers(ev(lost=dict(big, keys_sha="c" * 64, costs_sha="e" * 64)), ev(lost=dict(big, keys_sha="d" * 64, costs_sha="e" * 64)), 50, 0.01) != "")

tv = [O.tol_of({"rebuild_pnl_tol_usd": float("nan"), "rebuild_pnl_tol_pct": float("nan")}),
      O.tol_of({"rebuild_pnl_tol_usd": float("inf"), "rebuild_pnl_tol_pct": float("inf")}),
      O.tol_of({"rebuild_pnl_tol_usd": -5, "rebuild_pnl_tol_pct": -1}), O.tol_of({"rebuild_pnl_tol_usd": True})]
check("[5] tol NaN·inf·음수·bool = 기본(50, 0.01)", all(t == (50.0, 0.01) for t in tv), tv)
check("[5] 정상 tol 은 그대로", O.tol_of({"rebuild_pnl_tol_usd": 10, "rebuild_pnl_tol_pct": 0.02}) == (10.0, 0.02))
gnan = gate(rp({"realized_by_month_baseline": {"2026-01": 0.0}, "realized_by_month_shadow": {"2026-01": 900.0}}), {"rebuild_pnl_tol_usd": float("nan")})
check("[5] tol NaN 설정 → 차이가 '임계 안'으로 통과하지 않음", not gnan["ok"], gnan)

gate(rp({"realized_by_month_baseline": {"2026-01": 0.0}, "realized_by_month_shadow": {"2026-01": 900.0}}, tag="s6"))
ok6, _ = approve_last()
apv = json.load(open(APV))
e6 = O.gate_eval({"G4_vs_baseline": dict(BASE, realized_by_month_baseline={"2026-01": 0.0}, realized_by_month_shadow={"2026-01": 900.0}),
                  "cost_lost": LOST0, "decimals_unresolved": []}, 50, 0.01)
r6 = {}
for nm, until in (("기준(정상)", apv["until"]), ("NaN", float("nan")), ("inf", float("inf")), ("상한 넘음", time.time() + 30 * 86400), ("문자", "x")):
    open(APV, "w").write(json.dumps(dict(apv, until=until)))
    r6[nm] = O.approval_check(e6, 50, 0.01)[0]
    try:
        st6 = O.status()
        r6[nm + ":status"] = isinstance(st6, dict)
    except Exception as e:
        r6[nm + ":status"] = repr(e)
check("[6] until 정상 = 승인 · NaN·inf·상한 넘음·문자 = 승인 아님", ok6 and r6["기준(정상)"] is True and not any(r6[k] for k in ("NaN", "inf", "상한 넘음", "문자")), r6)
check("[6] status() 가 이상한 기한에 죽지 않음", all(r6[k] is True for k in r6 if k.endswith(":status")), r6)
clear_apv()

pz = os.path.join(S, "poison.jsonl")
open(pz, "w").write(json.dumps({"ts": 1, "err": "x", "rec": {"kind": "evm_tx", "chain": "base", "hash": "0x" + "ab" * 32}}) + "\n")
seen7 = []
c._consume_record = lambda rec: seen7.append(rec)
json.dump({"all": "false", "ids": []}, open(os.path.join(S, "poison_replay_request.json"), "w"))
c.poison_replay_pass()
check("[7] all=\"false\"(문자열) → 전체 재처리 안 함", seen7 == [], seen7)
json.dump({"all": True, "ids": []}, open(os.path.join(S, "poison_replay_request.json"), "w"))
c.poison_replay_pass()
check("[7] all=true → 전체 재처리(기준)", len(seen7) == 1, seen7)

calls9 = []
c._ext_rebuild = lambda need, ex_done: calls9.append(1)
c._ext_items = lambda now: ([], [], [])


def pass9(apv9):
    c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_prewindow:decimals_fix', '1')")
    c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuild_fail_at', ?)", (str(int(time.time() - 700)),))
    c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuild_fails', '3')")
    c.conn.execute("DELETE FROM meta WHERE k IN ('ext_rebuild_started_at', 'ext_rebuilt_at', 'rebuild_not_before')")
    c.conn.commit()
    c._last_ext_check = 0
    open(APV, "w").write(json.dumps(apv9))
    n0 = len(calls9)
    c.ext_rebuild_pass(set(c.EXT_STREAMS))
    return len(calls9) > n0


g9 = gate(rp({"realized_by_month_baseline": {"2026-05": 0.0}, "realized_by_month_shadow": {"2026-05": 700.0}}, tag="g9"))
n9 = int(time.time())
base9 = {"report_sha": g9.get("report_sha"), "until": n9 + 3600, "at": n9, "by": "시험"}
r9 = {"정상": pass9(base9), "at inf": pass9(dict(base9, at=float("inf"))), "at NaN": pass9(dict(base9, at=float("nan"))),
      "at 미래": pass9(dict(base9, at=n9 + 86400)), "until 상한 넘음": pass9(dict(base9, until=n9 + 30 * 86400)), "until inf": pass9(dict(base9, until=float("inf")))}
check("[9] 정상 승인만 재시도 · at inf/NaN/미래 · until 상한 넘음/inf = 재시도 안 함", r9["정상"] and not any(v for k, v in r9.items() if k != "정상"), r9)
clear_apv()

import rebuild2
import sqlite3
a8, b8 = sqlite3.connect(":memory:"), sqlite3.connect(":memory:")
for cx in (a8, b8):
    cx.execute("CREATE TABLE postings (source_kind, source_ns, source_id, leg_seq, leg_kind, event, cost_usd, asset_id)")
    cx.execute("CREATE TABLE assets (asset_id, symbol)")
a8.executemany("INSERT INTO postings VALUES (?,?,?,?,?,?,?,?)", [("exchange", "upbit", "t%d" % i, 0, "in", "buy", 10.0 + i, 1) for i in range(12)])
b8.executemany("INSERT INTO postings VALUES (?,?,?,?,?,?,?,?)", [("exchange", "upbit", "t%d" % i, 0, "in", "buy", None, 1) for i in range(12)])
cl8 = rebuild2.cost_lost(a8, b8)
b8.execute("UPDATE postings SET cost_usd=1 WHERE source_id='t3'")
cl8b = rebuild2.cost_lost(a8, b8)
check("[8] rebuild2.cost_lost keys_sha(전체 칸 집합 · 칸 바뀌면 다름)", isinstance(cl8.get("keys_sha"), str) and len(cl8["keys_sha"]) == 64
      and cl8b.get("keys_sha") != cl8["keys_sha"] and cl8["n"] == 12, (cl8.get("keys_sha"), cl8b.get("keys_sha")))
u8r = rebuild2._unv_all({"_diag": {"unv_all": {"rows": 2, "proceeds": 30.0, "by": {"7": 10.0, "9": 20.0}}}}, [], float)
check("[8] _unv_all 이 그룹별 by 를 넘김", u8r.get("by") == {"7": 10.0, "9": 20.0}, u8r)
wsrc = open(os.path.join(_x.TREE, "src", "web.py"), encoding="utf-8").read()
check("[8] web diag unv_all 에 그룹별 by(정적)", '"by": {str(' in wsrc[wsrc.find('diag_out["unv_all"]'):wsrc.find('diag_out["unv_all"]') + 400], "")
done()
