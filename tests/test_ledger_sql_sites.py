#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
from decimal import Decimal  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import config, paths  # noqa: E402
import core  # noqa: E402
import token_tables  # noqa: E402

assert T.TMP in paths.STATE_DIR
chk = T.chk
E8 = 10 ** 8
W1 = "0x00000000000000000000000000000000000000a1"

c = core.Core(config.load_config())
cx = c.conn


def leg_sums():
    out = {}
    for r in cx.execute("SELECT asset_id, location, qty_base FROM postings"):
        k = (int(r["asset_id"]), r["location"])
        out[k] = out.get(k, 0) + int(r["qty_base"])
    return {k: v for k, v in out.items() if v}


def pos_rows():
    return sorted(tuple(r) for r in cx.execute("SELECT group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd FROM positions"))


def ins(kind, ns, sid, seq, ts, aid, loc, qb, usd=None, krw=None, lk="opening", ev="EXF_ADJUST"):
    return cx.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
                      " leg_kind, event, classifier_ver) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)",
                      (kind, ns, sid, seq, ts, aid, loc, str(qb), usd, krw, lk, ev)).lastrowid


CA = sorted(token_tables.STABLE_CAS.get("eth") or {})[0]
WANT = token_tables.STABLE_CAS["eth"][CA]
a_st = c.asset_id("token", "eth", CA, "QSTB", 6)
cx.execute("INSERT OR IGNORE INTO asset_groups (name) VALUES (?)", (WANT,))
g_want = cx.execute("SELECT group_id FROM asset_groups WHERE name=?", (WANT,)).fetchone()[0]
cx.execute("INSERT INTO asset_groups (name) VALUES (?)", (f"QSTB#{a_st}",))
g_inst = cx.execute("SELECT group_id FROM asset_groups WHERE name=?", (f"QSTB#{a_st}",)).fetchone()[0]
cx.execute("UPDATE assets SET group_id=? WHERE asset_id=?", (g_inst, a_st))
L1, L2 = "wallet:eth:" + W1, "exchange:qx"
for g9, loc9, q9, u9, cst9 in ((g_inst, L1, "2.5", "0.5", "2.4"), (g_inst, L2, "1", "0", "1"), (g_want, L1, "10", "1", "9.9")):
    cx.execute("INSERT INTO positions (group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd) VALUES (?,?,?,?,?)", (g9, loc9, q9, u9, cst9))
cx.commit()


def loc_tot():
    out = {}
    for r in cx.execute("SELECT location, qty_norm, qty_unknown_norm, cost_alloc_usd FROM positions WHERE group_id IN (?,?)", (g_inst, g_want)):
        o = out.setdefault(r["location"], [Decimal(0)] * 3)
        for i in range(3):
            o[i] += Decimal(r[i + 1])
    return out


before = loc_tot()
moved = c._stable_regroup()
after = loc_tot()
rows = {r["location"]: (r["qty_norm"], r["qty_unknown_norm"], r["cost_alloc_usd"])
        for r in cx.execute("SELECT location, qty_norm, qty_unknown_norm, cost_alloc_usd FROM positions WHERE group_id=?", (g_want,))}
chk(len(moved) == 1 and before == after and not cx.execute("SELECT 1 FROM positions WHERE group_id=?", (g_inst,)).fetchone()
    and rows == {L1: ("12.5", "1.5", "12.3"), L2: ("1", "0", "1")}
    and cx.execute("SELECT group_id FROM assets WHERE asset_id=?", (a_st,)).fetchone()[0] == g_want,
    "Q1 _stable_regroup 더하기(UPDATE)·새 행(INSERT)·옛 행 지움(DELETE) · 위치별 포지션 합 전후 같음", (moved, rows))
chk(c._stable_regroup() == [] and loc_tot() == after, "Q1 두 번째 = 무동작(멱등)")

a_q = c.asset_id("native", "eth", None, "QETH", 8)
LQ = "exchange:qx"
p0 = ins("exchange", "qx:recon", "qx:recon:SYM:2000", 0, 1500, a_q, LQ, 100 * E8)
p1 = ins("exchange", "qx:recon", "qx:recon:SYM:2000", 1, 1600, a_q, LQ, 50 * E8)
cx.commit()
plan = [{"ns": "qx:recon", "sid": "qx:recon:SYM:2000", "asset_id": a_q, "loc": LQ, "cv": 1,
         "old": [{"leg": 0, "pid": p0, "ts": 1500, "qb": str(100 * E8)}, {"leg": 1, "pid": p1, "ts": 1600, "qb": str(50 * E8)}],
         "new": [{"leg": 0, "ts": 1200, "qb": str(120 * E8)}, {"leg": 3, "ts": 1300, "qb": str(30 * E8)}]}]
s0, ps0 = leg_sums(), pos_rows()
n = c.svc_exf._exf_fix_place_apply(plan)
cx.commit()
got = sorted((r["leg_seq"], r["event_ts"], r["qty_base"], r["posting_id"] == p0)
             for r in cx.execute("SELECT * FROM postings WHERE source_id='qx:recon:SYM:2000'"))
chk(n == 1 and got == [(0, 1200, str(120 * E8), True), (3, 1300, str(30 * E8), False)] and leg_sums() == s0 and pos_rows() == ps0,
    "Q2 _exf_fix_place_apply DELETE·UPDATE(posting_id 유지)·INSERT · 자산·위치별 qty_base 합 같음 · positions 무변", got)
bad = dict(plan[0], new=[{"leg": 0, "ts": 1200, "qb": str(1)}])
try:
    c.svc_exf._exf_fix_place_apply([bad])
    raised = False
except ValueError:
    raised = True
chk(raised and leg_sums() == s0, "Q2 합 안 맞는 계획 = 거부(쓰기 0)")

a_d = c.asset_id("native", "qd", None, "QUSD", 8)
LD = "exchange:qd"
T_FIRST, T_OLD = 5000, 9000
ins("exchange", "qd:deposit", "dep1", 0, 1000, a_d, LD, 200 * E8, lk="acq", ev="EXF_DEPOSIT")
pd = ins("exchange", "qd:recon", f"qd:recon:QUSD:{T_OLD}", 0, T_OLD, a_d, LD, -105 * E8)
cx.commit()
json.dump({"qd": {"QUSD": {"ts": T_FIRST, "qty": "100"}}}, open(os.path.join(T.TMP, "seed", "debt_first_seen_t.json"), "w"))
s0, ps0 = leg_sums(), pos_rows()
c.svc_exf._exf_debt_redate_once()
rows = sorted((r["leg_seq"], r["event_ts"], r["qty_base"]) for r in cx.execute("SELECT * FROM postings WHERE source_ns='qd:recon'"))
chk(rows == [(0, T_FIRST, str(-100 * E8)), (2, T_OLD, str(-5 * E8))] and leg_sums() == s0 and pos_rows() == ps0
    and cx.execute("SELECT posting_id FROM postings WHERE source_ns='qd:recon' AND leg_seq=0").fetchone()[0] == pd
    and c._meta_get("exf_debt_redate_t"),
    "Q3 _exf_debt_redate_once UPDATE(시각·수량)+이자 레그 INSERT · 자산·위치별 qty_base 합 같음 · positions 무변 · 완료 표식", rows)

a_v = c.asset_id("native", "qv", None, "QVV", 8)
LV = "exchange:qv"
pv = ins("exchange", "qv:recon", "qv:recon:QVV:90000", 0, 89990, a_v, LV, 3 * E8)
cx.commit()
s0 = leg_sums()
c.svc_exf._exf_ext_settle_plan = lambda ex, bts: [{"pid": pv, "old": 89990, "new": 70000}]
m1 = c.svc_exf._exf_ext_settle_repair("qv", {90000})
chk(m1 == 1 and cx.execute("SELECT event_ts FROM postings WHERE posting_id=?", (pv,)).fetchone()[0] == 70000 and leg_sums() == s0,
    "V1 _exf_ext_settle_repair UPDATE(시각만 · 옛 시각 조건)")

c.svc_exf._exf_ext_open_anchor = lambda ex, r, st: True
c.svc_exf._win_t0 = lambda b9, ex=None: 60000
st_ex = {"ext": {"target": 50000, "wd_from": 50000, "fills_from": 50000, "_psig": ["done", 50000, 50000, "", 50000]}}
m2 = c.svc_exf._exf_ext_redate("qv", 90000, st_ex)
chk(m2 == 1 and cx.execute("SELECT event_ts FROM postings WHERE posting_id=?", (pv,)).fetchone()[0] == 60000 and leg_sums() == s0,
    "V1 _exf_ext_redate UPDATE(넓힌 창 시작으로 · 시각만)")

a_r1 = c.asset_id("native", "qr", None, "QRA", 8)
a_r2 = c.asset_id("native", "qr2", None, "QRB", 8)
LR = "exchange:qr"
ins("exchange", "qr:recon", "qr:recon:QRA:100000", 0, 99990, a_r1, LR, 1 * E8)
pr = ins("exchange", "qr:recon", "qr:recon:QRB:500000", 0, 200000, a_r2, LR, 4 * E8)
cx.commit()
s0 = leg_sums()
c.svc_exf._exf_redate_once()
chk(cx.execute("SELECT event_ts FROM postings WHERE posting_id=?", (pr,)).fetchone()[0] == 500000 and leg_sums() == s0
    and c._meta_get("exf_redate_m"), "V1 _exf_redate_once UPDATE(창 시작 → 대사 시각 · 시각만) · 완료 표식")

a_o = c.asset_id("native", "qo", None, "QOO", 8)
po = ins("chain_tx", "qo", "0xq1", 0, 3000, a_o, "out:0xq", 2 * E8, usd="5", krw="7000", lk="move_in", ev="TRANSFER_OUT")
cx.commit()
c.svc_price._sym_px_token = lambda aid: aid == a_o
c.svc_price._ex_proven = lambda aid: False
c.svc_price._own_unit_cost = lambda aid: None
ch_o = c.svc_price._out_px_band_fix_once()
r9 = cx.execute("SELECT cost_usd, cost_krw, qty_base FROM postings WHERE posting_id=?", (po,)).fetchone()
chk([x[0] for x in ch_o] == [po] and tuple(r9) == (None, None, str(2 * E8)), "V1 _out_px_band_fix_once UPDATE(원가 NULL · 수량 무변)", tuple(r9))

pe = ins("exchange", "qe:trade", "qe1", 0, 4000, a_o, "exchange:qe", 1 * E8, usd=None, krw="13800", lk="acq", ev="EXF_BUY")
cx.commit()
c.px.fx_at = lambda ms: 1380.0
c.px.flush = lambda: None
c.svc_price._price_tx = lambda ch, h: False
c.svc_price._last_price_pass = 0
c.svc_price.price_pass()
r9 = cx.execute("SELECT cost_usd, qty_base FROM postings WHERE posting_id=?", (pe,)).fetchone()
chk(r9["cost_usd"] is not None and abs(float(r9["cost_usd"]) - 10.0) < 1e-9 and r9["qty_base"] == str(E8),
    "V1 price_pass 거래소 체결 USD 소급 UPDATE(cost_krw / 환율 · 수량 무변)", tuple(r9))

a_g = c.asset_id("native", "qg", None, "QGG", 18)
LG = "wallet:qg:" + W1
c.my_wallets.setdefault("qg", set()).add(W1)
for h9 in ("0xg1", "0xg2"):
    snap9 = {"tx": {"from": W1, "to": "0x00000000000000000000000000000000000000b2"}, "mgr": "0x00000000000000000000000000000000000000c3"}
    cx.execute("INSERT INTO raw_txs (chain, txhash, block, blockhash, ts, snapshot, wallets, ingested_at) VALUES ('qg', ?, 1, 'b', 6000, ?, '[]', 0)",
               (h9, json.dumps(snap9)))
    cx.execute("INSERT INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('qg', ?, 'BRIDGE', NULL, 1)", (h9,))
    c._post_leg("chain_tx", "qg", h9, 1, 6000, a_g, LG, -1000, "0.25", "345", "gas", "BRIDGE")
cx.commit()
redo = []


def _redo(ch, h):
    redo.append(h)
    cx.execute("UPDATE postings SET cost_usd=NULL, cost_krw=NULL WHERE source_ns=? AND source_id=? AND leg_kind='gas'", (ch, h))
    return "TRANSFER_OUT"


c._rederive_tx_anchor_safe = _redo
c.classify = lambda ch, h, snap: ("TRANSFER_OUT",)
s0 = leg_sums()
n1 = c._reclass_plain_xfer_once()
g1 = cx.execute("SELECT cost_usd, cost_krw FROM postings WHERE source_id='0xg1' AND leg_kind='gas'").fetchone()
chk(n1 == 2 and tuple(g1) == ("0.25", "345") and leg_sums() == s0 and c._meta_get("reclass_q_plainxfer"),
    "V1 _reclass_plain_xfer_once 가스 레그 원가 되살림 UPDATE(… AND cost_usd IS NULL · 수량 무변)", (n1, tuple(g1)))
c.lp_mgrs = {"qg": {"0x00000000000000000000000000000000000000c3": {"added": "2026-01-01", "proto": "uni_v4"}}}
redo.clear()
n2 = c._reclass_added_lp_mgrs_once()
g2 = cx.execute("SELECT cost_usd, cost_krw FROM postings WHERE source_id='0xg2' AND leg_kind='gas'").fetchone()
chk(n2 == 2 and redo == ["0xg1", "0xg2"] and tuple(g2) == ("0.25", "345") and leg_sums() == s0
    and c._meta_get("reclass_lp_mgr:qg:0x00000000000000000000000000000000000000c3"),
    "V1 _reclass_added_lp_mgrs_once 가스 레그 원가 되살림 UPDATE(시각순 · 수량 무변 · 관리자 표식)", (n2, redo, tuple(g2)))

T.finish()
