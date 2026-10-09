#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time
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
core.Core.EXF_REVERT_LOG = os.path.join(common.STATE_DIR, "exf_recon_revert.jsonl")
sys.path.insert(0, os.path.join(T.ROOT, "tools"))
import exf_fut_place

chk = T.chk
C = core.Core(common.load_config())
os.makedirs(os.path.join(common.STATE_DIR, "backups"), exist_ok=True)
open(os.path.join(common.STATE_DIR, "backups", "ledger_test.db"), "w").close()
common.atomic_write_json(os.path.join(common.STATE_DIR, "backups", "backup_status.json"),
                         {"last_ok": int(time.time()) + 86400 * 30, "last_path": os.path.join(common.STATE_DIR, "backups", "ledger_test.db")})
C._quote_usd = lambda q, ts: Decimal(1)
C.EXF_INIT_PHASE = 5
NOW = int(time.time())
E8 = 10 ** 8
SEQ = {"t": NOW - 1700}


def tick(d=10):
    SEQ["t"] += d
    return SEQ["t"]


def tick_min():
    SEQ["t"] += 60 - SEQ["t"] % 60 + 1
    return SEQ["t"]


def post(ex, t, sym, qty, ev="EXF_DEPOSIT", lk="move_in", sid=None):
    aid = C._exf_asset(ex, sym)
    qb = int(Decimal(str(qty)) * E8)
    C.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base,"
                   " cost_usd, cost_krw, leg_kind, event, classifier_ver) VALUES ('exchange',?,?,0,?,?,?,?,NULL,NULL,?,?,?)",
                   (f"{ex}:{'deposit' if qty > 0 else 'withdraw'}", sid or f"{ex}:{t}:{sym}:{qty}", int(t), aid, f"exchange:{ex}", str(qb), lk, ev,
                    core.CLASSIFIER_VER))
    C._bump_position(aid, qb, f"exchange:{ex}")
    C.conn.commit()


def futfile(ex, events, ts=None):
    common.atomic_write_json(os.path.join(common.STATE_DIR, f"futures_{ex}.json"), {
        "ts": int(ts if ts is not None else time.time()),
        "events": [{"t": int(t) * 1000 + 123, "symbol": s, "kind": k, "amount": a, "uid": f"u{i}"} for i, (t, s, k, a) in enumerate(events)]})
    C.__dict__.pop("_exf_fut_cache", None)


def recon(ex, bal, sources=("futures",), bts=None):
    bts = bts or tick()
    st = common.read_json(os.path.join(common.STATE_DIR, "exf_state.json"), {})
    st.setdefault(ex, {"seen": {}, "backfilled_until": NOW, "fills": {"backfilled_until": NOW}})
    common.atomic_write_json(os.path.join(common.STATE_DIR, "exf_state.json"), st)
    common.atomic_write_json(os.path.join(common.STATE_DIR, f"exf_balances_{ex}.json"),
                             {"ts": bts, "balances": bal, "sources": list(sources)})
    C._drain_at = bts + 5
    C._last_exfrecon = 0
    C.exf_recon_pass({"ex"})
    return bts


def rows(ex, sym, ns="recon"):
    return sorted((int(r[0]), int(r[1]), Decimal(int(r[2])) / E8) for r in C.conn.execute(
        "SELECT p.event_ts, p.leg_seq, p.qty_base FROM postings p JOIN assets a USING(asset_id) WHERE p.source_ns=? AND p.event='EXF_ADJUST'"
        " AND upper(a.symbol)=? AND p.location=?", (f"{ex}:{ns}", sym, f"exchange:{ex}")).fetchall())


def total(ex, sym, t=None):
    q = ("SELECT SUM(CAST(p.qty_base AS INTEGER)) FROM postings p JOIN assets a USING(asset_id) WHERE p.location=? AND upper(a.symbol)=?"
         + (" AND p.event_ts<=?" if t is not None else ""))
    v = C.conn.execute(q, (f"exchange:{ex}", sym) + ((int(t),) if t is not None else ())).fetchone()[0]
    return Decimal(int(v or 0)) / E8


def pos_ok(ex, sym):
    aid = C._exf_asset(ex, sym)
    g = C._group_of(aid)
    r = C.conn.execute("SELECT qty_norm FROM positions WHERE group_id=? AND location=?", (g, f"exchange:{ex}")).fetchone()
    return Decimal(r[0] if r else 0) == total(ex, sym)


def scene(ex, sym_c, fut=True):
    t0 = tick(0) - 5000
    post(ex, t0, "USDT", 1000, sid=f"{ex}:d0")
    b0 = recon(ex, {"USDT": 1000})
    t1 = t0 + 100
    post(ex, t1, "USDT", -1200, ev="EXF_WITHDRAW", lk="move_out", sid=f"{ex}:w1")
    post(ex, t1 + 7300, "USDT", 500, sid=f"{ex}:d1")
    b1 = recon(ex, {"USDT": 300})
    b2 = recon(ex, {"USDT": 250})
    tf1 = tick(5)
    evs = [(tf1, sym_c, "FEE", -5.0)]
    if fut:
        futfile(ex, evs)
    b3 = recon(ex, {"USDT": 245})
    tf2 = tick_min()
    evs += [(tf2, sym_c, "REALIZED", 400.0), (tf2 + 1, sym_c, "REALIZED", 201.0), (tf2 + 2, sym_c, "FEE", -1.0)]
    if fut:
        futfile(ex, evs)
    b4 = recon(ex, {"USDT": 845})
    return dict(t0=t0, t1=t1, b0=b0, b1=b1, b2=b2, b3=b3, b4=b4, tf1=tf1, tf2=tf2, evs=evs)


print("[S] 정산 통화 · 같은 분 묶음")
chk(C._exf_fut_sym("binance", "NMRUSDT") == "USDT" and C._exf_fut_sym("binance", "BTCUSDC") == "USDC" and C._exf_fut_sym("binance", "BTCUSD_PERP") == ""
    and C._exf_fut_sym("okx", "AA-USDT-SWAP") == "USDT" and C._exf_fut_sym("okx", "BTC-USD-SWAP") == "" and C._exf_fut_sym("bybit", "BTCPERP") == "USDC"
    and C._exf_fut_sym("bybit", "BTCUSD") == "", "S1 정산 통화: USDT·USDC 계약만 · 코인 정산(인버스) = 모름")
lg = C._exf_fut_legs([(120, Decimal("1.5")), (130, Decimal("-0.5")), (179, Decimal("2")), (180, Decimal("1")), (181, Decimal("-1"))], Decimal(E8))
chk(lg == [(179, 3 * E8)], "S2 같은 분 = 한 줄(시각 = 그 분 마지막 정산) · 합 0 인 분 빠짐", lg)

print("[A] 바이낸스 — 선물 정산 = 정산 시각")
A = scene("binance", "AAAUSDT")
fa = rows("binance", "USDT", "futpnl")
chk(fa == [(A["tf1"], 0, Decimal(-5)), (A["tf2"] + 2, 0, Decimal(600))], "A1 선물 줄 = 정산 시각(수수료 −5 · 같은 분 +600) · 대사마다 leg 0", fa)
ra = rows("binance", "USDT")
chk((A["b2"], 0, Decimal(-50)) in ra, "A2 지난 음수 정정 −50 그대로(되돌림 없음)", ra)
chk(not any(t < A["b0"] for t, _l, _q in ra) and total("binance", "USDT", A["t1"] + 1) == -200,
    "A3 결손 구간 소급 없음 — 지난날 원장 그대로(−200)", (ra, total("binance", "USDT", A["t1"] + 1)))
chk(total("binance", "USDT") == 845 and pos_ok("binance", "USDT"), "A4 원장 = 실잔고 845 · 보유(positions) = 원장 합", total("binance", "USDT"))
chk(not any(t in (A["b3"], A["b4"]) for t, _l, _q in ra), "A5 정산 대사의 나머지 0 → 대사 보정 줄 없음", ra)
chk(json.loads(C._meta_get("exf_fut_cur_binance")) == {"t": A["b4"]}, "A6 커서 = 마지막 대사 시각", C._meta_get("exf_fut_cur_binance"))
print("[A0] 대조: 선물 파일 없는 거래소(바이비트) = 종전 규칙")
Z = scene("bybit", "AAAUSDT", fut=False)
rz = rows("bybit", "USDT")
chk(not rows("bybit", "USDT", "futpnl") and (Z["b2"], 0, Decimal(-50)) not in rz and any(t < Z["b0"] and q == 200 for t, _l, q in rz),
    "A0 종전: 이익이 지난 정정(−50·−5)을 지우고 결손 구간으로 +200 소급", rz)
chk(total("bybit", "USDT") == 845 and pos_ok("bybit", "USDT"), "A0' 종전도 원장 = 실잔고", total("bybit", "USDT"))

print("[B] (fr297 #1) 선물 파일이 잔고 시각을 못 덮으면 그 거래소 대사 보류 → 덮으면 정산 시각 · 상한(EXF_FUT_WAIT_S) 넘으면 종전 규칙 · 이중 계상 없음")
tf3 = tick(5)
evs = A["evs"] + [(tf3, "AAAUSDT", "REALIZED", 100.0)]
futfile("binance", A["evs"], ts=tf3 - 1)
d0 = C._meta_get("recon_done_exf_binance")
recon("binance", {"USDT": 945})
chk(C._meta_get("recon_done_exf_binance") == d0 and total("binance", "USDT") == 845 and len(rows("binance", "USDT", "futpnl")) == 2,
    "B1 대사 보류(대사 표식·원장·커서 그대로 — 종전 = 나머지로 소급 + 커서 전진 → 그 정산 영구 누락)", (C._meta_get("recon_done_exf_binance"), d0))
futfile("binance", evs)
b6 = recon("binance", {"USDT": 945})
chk((tf3, 0, Decimal(100)) in rows("binance", "USDT", "futpnl") and not any(t == b6 for t, _l, _q in rows("binance", "USDT"))
    and total("binance", "USDT") == 945 and pos_ok("binance", "USDT"), "B2 파일이 덮으면 +100 = 정산 시각 · 대사 줄 없음 · 원장 = 실잔고", rows("binance", "USDT", "futpnl"))
tf3b = tick(5)
futfile("binance", evs, ts=tf3b - 1)
C.EXF_FUT_WAIT_S = 0
b7 = recon("binance", {"USDT": 955})
chk(C._meta_get("recon_done_exf_binance") == str(b7) and total("binance", "USDT") == 955 and not any(t == tf3b for t, _l, _q in rows("binance", "USDT", "futpnl")),
    "B3 상한 넘으면 종전 규칙으로 대사(원장 = 실잔고)", (C._meta_get("recon_done_exf_binance"), b7, total("binance", "USDT")))
evs += [(tf3b, "AAAUSDT", "REALIZED", 10.0)]
futfile("binance", evs)
recon("binance", {"USDT": 955})
chk(not any(t == tf3b for t, _l, _q in rows("binance", "USDT", "futpnl")) and total("binance", "USDT") == 955 and pos_ok("binance", "USDT"),
    "B4 그 뒤 온 정산은 다시 안 뗌(이중 계상 없음)", rows("binance", "USDT", "futpnl")[-2:])
del C.EXF_FUT_WAIT_S

print("[C] 떼지 않는 경우")
tf4 = tick(5)
evs += [(tf4, "AAAUSDT", "REALIZED", 30.0)]
futfile("binance", evs)
recon("binance", {"USDT": 985}, sources=())
chk(len(rows("binance", "USDT", "futpnl")) == 3 and total("binance", "USDT") == 985, "C1 잔고에 선물 지갑 소스 없음 = 안 뗌(종전)", rows("binance", "USDT", "futpnl"))
tf5 = tick(5)
evs += [(tf5, "AAAUSD_PERP", "REALIZED", 7.0)]
futfile("binance", evs)
recon("binance", {"USDT": 985, "AAA": 7})
chk(len(rows("binance", "USDT", "futpnl")) == 3 and not rows("binance", "AAA", "futpnl"), "C2 코인 정산 계약 = 안 뗌", rows("binance", "AAA", "futpnl"))
chk(C._exf_fut_window("hyperliquid", {"sources": ["futures"]}, NOW, NOW - 100) == {}, "C3 Hyperliquid = 대상 밖(종전 '지금 손익' 규칙 그대로)")

print("[E] 나머지 초소액이어도 선물 정산은 적는다")
tf6 = tick(5)
evs += [(tf6, "AAAUSDT", "FUNDING", -0.3)]
futfile("binance", evs)
b7e = recon("binance", {"USDT": 984.9, "AAA": 7})
chk((tf6, 0, Decimal("-0.3")) in rows("binance", "USDT", "futpnl") and not any(t == b7e for t, _l, _q in rows("binance", "USDT")),
    "E1 펀딩 −0.3 = 정산 시각 · 나머지 +0.2 = 보류(대사 줄 없음)", (rows("binance", "USDT", "futpnl")[-1:], rows("binance", "USDT")[-2:]))

print("[G] 배포 전 대사 다시 놓기(1회)")
G = scene("okx", "AAA-USDT-SWAP", fut=False)
before = rows("okx", "USDT")
chk(any(t < G["b0"] and q == 200 for t, _l, q in before) and (G["b2"], 0, Decimal(-50)) not in before, "G0 전제: 종전 대사 = 소급 +200 · −50 지워짐", before)
futfile("okx", G["evs"])
C.conn.execute("DELETE FROM meta WHERE k IN ('exf_fut_place_v', 'exf_fut_cur_okx', 'exf_fut_from_okx')")
C.conn.commit()
plan, curs = C._exf_fut_place_plan()
po = [m for m in plan if m["ex"] == "okx"]
chk(len(po) == 1 and po[0]["cands"] == [G["b3"], G["b4"]] and not po[0]["skip"], "G1 후보 = 선물 정산 낀 대사 2건", [(m["ex"], m.get("cands"), m.get("skip")) for m in plan])
snap0 = sorted(tuple(r) for r in C.conn.execute("SELECT source_ns, source_id, leg_seq, event_ts, qty_base FROM postings WHERE location='exchange:okx'").fetchall())
n = C._exf_fut_place_once()
after = rows("okx", "USDT")
chk(n == 1 and rows("okx", "USDT", "futpnl") == [(G["tf1"], 0, Decimal(-5)), (G["tf2"] + 2, 0, Decimal(600))], "G2 선물 줄 = 정산 시각", rows("okx", "USDT", "futpnl"))
chk((G["b2"], 0, Decimal(-50)) in after and not any(t < G["b0"] for t, _l, _q in after) and not any(t in (G["b3"], G["b4"]) for t, _l, _q in after),
    "G3 소급 +200 지움 · 되돌린 −50 복원 · 정산 대사 줄 없음(나머지 0)", after)
chk(total("okx", "USDT") == 845 and pos_ok("okx", "USDT") and total("okx", "USDT", G["t1"] + 1) == -200, "G4 원장 합·보유 무변 · 지난날 = 소급 전", total("okx", "USDT"))
chk(C._exf_fut_place_once() is None and rows("okx", "USDT") == after, "G5 두 번 = 무변(세대 표식)")
cur = json.loads(C._meta_get("exf_fut_cur_okx") or "{}")
chk(cur.get("t") == int(C._meta_get("recon_done_exf_okx")) and cur.get("s", {}).get("USDT") in (None, G["b4"])
    and C._meta_get("exf_fut_from_okx") == C._meta_get("recon_done_exf_okx"), "G6 커서 = 마지막 대사 · 통화별 시작 · 새 규칙 시작 표식", cur)
chk(any(int(b) == G["b3"] for b, in C.conn.execute("SELECT bts FROM exf_adj_tomb WHERE ex='okx' AND sym='USDT'")), "G7 지운 대사 경계 기록(tomb)")
rc = exf_fut_place._undo(os.path.join(common.STATE_DIR, "exf_fut_place_v1.json"))
snap1 = sorted(tuple(r) for r in C.conn.execute("SELECT source_ns, source_id, leg_seq, event_ts, qty_base FROM postings WHERE location='exchange:okx'").fetchall())
chk(rc == 0 and snap1 == snap0 and pos_ok("okx", "USDT") and str(C._meta_get("exf_fut_place_v")).startswith("1:undone:"),
    "G8 되돌리기 = 재배치 전 줄 그대로 · 표식 = '1:undone:시각'(NB2 — 자동 적용 금지)", C._meta_get("exf_fut_place_v"))

print("[G9] 후보가 만든 행을 후보 아닌 것이 줄였으면 그 후보는 건너뜀")
t0 = tick(0) - 4000
post("bybit", t0, "USDT", 1000, sid="bybit2:d0")
H = {}
H["b3"] = recon("bybit", {"USDT": 845 + 1000 - 25})
H["tf1"] = H["b3"] - 3
H["b5"] = recon("bybit", {"USDT": 845 + 1000 - 15})
H["tf2"] = tick(3)
H["b4"] = recon("bybit", {"USDT": 845 + 1000 + 585})
futfile("bybit", Z["evs"] + [(H["tf1"], "BBBUSDT", "FEE", -5.0), (H["tf2"], "BBBUSDT", "REALIZED", 600.0)])
C.conn.execute("DELETE FROM meta WHERE k IN ('exf_fut_place_v', 'exf_fut_cur_bybit', 'exf_fut_from_bybit')")
C.conn.commit()
tot0 = total("bybit", "USDT")
plan, _c = C._exf_fut_place_plan()
pb = next((m for m in plan if m["ex"] == "bybit"), {})
chk(any(b == H["b3"] for b, _w in pb.get("skip") or ()) and H["b4"] in (pb.get("cands") or []), "G9 −25 대사 = 건너뜀(후보 아닌 대사가 줄임) · +600 대사 = 다시 놓음",
    (pb.get("cands"), pb.get("skip")))
C._exf_fut_place_once()
chk(total("bybit", "USDT") == tot0 and pos_ok("bybit", "USDT") and any(t == H["tf2"] and q == 600 for t, _l, q in rows("bybit", "USDT", "futpnl")),
    "G10 건너뛴 후보가 있어도 원장 합·보유 무변 · 다시 놓은 대사의 선물 줄", (tot0, total("bybit", "USDT")))

print("[G11] 새 규칙이 이미 돈 대사 = 이관 대상 아님(이중 계상 방지)")
C.conn.execute("DELETE FROM meta WHERE k='exf_fut_place_v'")
C.conn.commit()
plan, _c = C._exf_fut_place_plan()
chk(not [m for m in plan if m.get("cands")], "G11 바이낸스(새 규칙 대사)·OKX·바이빗(이미 다시 놓음) = 후보 0 — 새 규칙 시작 표식", [(m["ex"], m.get("cands")) for m in plan])
C.conn.execute("DELETE FROM meta WHERE k IN ('exf_fut_from_okx', 'exf_fut_from_bybit')")
C.conn.commit()
plan, _c = C._exf_fut_place_plan()
chk(not [m for m in plan if m["ex"] in ("okx", "bybit") and m.get("cands")], "G12 표식이 지워져도 선물 줄 있는 대사 = 후보 아님(두 번 놓지 않음)",
    [(m["ex"], m.get("cands")) for m in plan])
C.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('exf_fut_place_v', '1:0:0')")
C.conn.commit()

print("[H] 종전 코드 이력(소액 보류 포함) → 도구 미리보기·적용(가짜 pm2) → 첫 새 대사가 통화별 시작부터 뗌 · 끝전 허용")
import subprocess
FAKE = os.path.join(T.TMP, "fakebin")
os.makedirs(FAKE, exist_ok=True)
with open(os.path.join(FAKE, "pm2"), "w") as fh:
    fh.write("#!/bin/sh\necho '[]'\n")
os.chmod(os.path.join(FAKE, "pm2"), 0o755)


WRAP = os.path.join(T.TMP, "fp_wrap.py")
with open(WRAP, "w") as fh:
    fh.write("import runpy, sys\nsys.dont_write_bytecode = True\nsys.path.insert(0, sys.argv[1])\nimport core\ncore.Core.EXF_INIT_PHASE = 5\n"
             "tool = sys.argv[2]\nsys.argv = [tool] + sys.argv[3:]\nrunpy.run_path(tool, run_name='__main__')\n")


def tool(*args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
    env.update(TJ_BASE=T.TMP, PM2_BIN=os.path.join(FAKE, "pm2"), PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, WRAP, T.SRC, os.path.join(T.ROOT, "tools", "exf_fut_place.py")] + list(args), env=env,
                       capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


C.EXF_FUT_EX = ()
tA = tick(5)
post("okx", tA, "USDC", 1000, sid="okx:usdc:d0")
hA = recon("okx", {"USDT": 845, "USDC": 990})
tF = tick(5)
hB = recon("okx", {"USDT": 845, "USDC": 989.7})
tR = tick_min()
hC = recon("okx", {"USDT": 845, "USDC": 1039.700000006})
tF2 = tick(5)
hD = recon("okx", {"USDT": 845, "USDC": 1039.5})
del C.EXF_FUT_EX
chk(not any(t == hA for t, _l, _q in rows("okx", "USDC")) and any(t == hC for t, _l, _q in rows("okx", "USDC")), "H0 전제: 종전 = −10 되돌림 · 대사 시각 +",
    rows("okx", "USDC"))
futfile("okx", G["evs"] + [(tF, "AAA-USDC-SWAP", "FUNDING", -0.3), (tR, "AAA-USDC-SWAP", "REALIZED", 50.0), (tF2, "AAA-USDC-SWAP", "FUNDING", -0.2)])
C.conn.execute("DELETE FROM meta WHERE k IN ('exf_fut_place_v', 'exf_fut_cur_okx', 'exf_fut_from_okx')")
C.conn.commit()
tot_u0 = total("okx", "USDC")
pj = os.path.join(T.TMP, "fp_plan.json")
rc, out = tool("--json", pj)
pl = json.load(open(pj)) if os.path.exists(pj) else {}
po = [m for m in pl.get("plan") or [] if m["ex"] == "okx"]
chk(rc == 0 and [m["sym"] for m in po if m.get("cands")] == ["USDC"] and next(m for m in po if m["sym"] == "USDC")["cands"] == [hC]
    and (pl.get("curs") or {}).get("okx", {}).get("USDC") == hC,
    "H1 미리보기: OKX USDC 대사 1건만(USDT = 선물 줄 있어 제외 · 끝전 허용) · 통화별 시작 = 그 통화 마지막 대사", (rc, out[-600:], pl.get("curs")))
rc, out = tool("--apply", "--expect", pj)
chk(rc == 0 and "일치 검사 통과" in out, "H2 적용(가짜 pm2 = core 없음) · 일치 검사 통과", out[-600:])
fu = rows("okx", "USDC", "futpnl")
chk(fu == [(tF, 0, Decimal("-0.3")), (tR, 1, Decimal(50))] and (hA, 0, Decimal(-10)) in rows("okx", "USDC")
    and not any(t == hC for t, _l, _q in rows("okx", "USDC")) and total("okx", "USDC") == tot_u0 and pos_ok("okx", "USDC"),
    "H3 펀딩·실현 = 정산 시각 · −10 복원 · 대사 시각 줄 없음 · 합·보유 무변", (fu, rows("okx", "USDC")))
hE = recon("okx", {"USDT": 845, "USDC": 1039.5})
chk((tF2, 0, Decimal("-0.2")) in rows("okx", "USDC", "futpnl") and not any(t == hE for t, _l, _q in rows("okx", "USDC"))
    and total("okx", "USDC") == Decimal("1039.5") and pos_ok("okx", "USDC"),
    "H4 첫 새 대사 = 통화별 시작(그 통화 마지막 대사) 뒤 소액 보류된 펀딩 −0.2 를 정산 시각에", (rows("okx", "USDC", "futpnl"), rows("okx", "USDC")[-2:]))
chk(json.loads(C._meta_get("exf_fut_cur_okx")) == {"t": hE}, "H5 첫 새 대사 뒤 커서 = 대사 시각(통화별 시작 지움)", C._meta_get("exf_fut_cur_okx"))
rc, out = tool("--json", pj)
chk(rc == 0 and not [m for m in json.load(open(pj))["plan"] if m.get("cands")], "H6 적용 뒤 미리보기 = 바뀌는 대사 0", out[-300:])
with open(os.path.join(FAKE, "pm2"), "w") as fh:
    fh.write("#!/bin/sh\necho '[{\"name\": \"tj-core\", \"pm2_env\": {\"status\": \"online\"}}]'\n")
rc, out = tool("--apply")
chk(rc == 1 and "거부" in out, "H7 core 가 떠 있으면 적용 거부", out[-200:])
with open(os.path.join(FAKE, "pm2"), "w") as fh:
    fh.write("#!/bin/sh\necho '[]'\n")
ej = os.path.join(T.TMP, "fp_err.json")
with open(ej, "w") as fh:
    json.dump({"plan": [{"ex": "okx", "sym": "USDT", "err": "합 불일치 1 ≠ 2", "skip": []}], "curs": {}}, fh)
v0 = C._meta_get("exf_fut_place_v")
rc, out = tool("--apply", "--expect", ej)
chk(rc == 1 and "거부" in out and C._meta_get("exf_fut_place_v") == v0, "H8 계획 못 세운 통화가 든 계획 = 적용 거부(원장·표식 무변)", out[-200:])

print("[I] (fr296 #2) 감사 기록이 빠진 지운 대사 = 이관 계획 못 세움(통화 err · 도구 미리보기 종료 1 · 적용 안 함)")
LOG = core.Core.EXF_REVERT_LOG
C.EXF_FUT_EX = ()
post("bybit", tick(0) - 600, "USDC", 1000, sid="bybit:usdc:d0")
iA = recon("bybit", {"USDT": 845 + 1000 + 585, "USDC": 950})
iF = tick(5)
iB = recon("bybit", {"USDT": 845 + 1000 + 585, "USDC": 1050})
del C.EXF_FUT_EX
bb_evs = Z["evs"] + [(H["tf1"], "BBBUSDT", "FEE", -5.0), (H["tf2"], "BBBUSDT", "REALIZED", 600.0), (iF, "CCCUSDC", "REALIZED", 100.0)]
futfile("bybit", bb_evs)
C.conn.execute("DELETE FROM meta WHERE k IN ('exf_fut_place_v', 'exf_fut_cur_bybit', 'exf_fut_from_bybit')")
C.conn.commit()
log_all = open(LOG, encoding="utf-8").read().splitlines(True)
gone = [ln for ln in log_all if f'"exfrecon:USDC:{iA}"' in ln]
with open(LOG, "w", encoding="utf-8") as fh:
    fh.writelines(ln for ln in log_all if ln not in gone)
plan, _c = C._exf_fut_place_plan()
pu = next((m for m in plan if m["ex"] == "bybit" and m["sym"] == "USDC"), {})
chk(len(gone) == 1 and pu.get("hold") and not pu.get("cands"), "I1 지운 −50 의 감사 줄 없음 → bybit USDC = 보류(근거 부족 — 옛 배치 유지)",
    (len(gone), pu.get("hold"), pu.get("cands")))
rc, out = tool("--json", pj)
chk(rc == 0 and "보류(옛 배치 유지" in out and "보류 통화 1" in out, "I2 (fr299) 도구 미리보기 = 보류 표시 · 종료 0(다른 통화는 옮김)", out[-300:])
n0 = len(rows("bybit", "USDC", "futpnl"))
snapI = sorted(tuple(r) for r in C.conn.execute("SELECT source_ns, source_id, leg_seq, event_ts, qty_base FROM postings p JOIN assets a USING(asset_id)"
                                                " WHERE p.location='exchange:bybit' AND upper(a.symbol)='USDC'"))
r9 = C._exf_fut_place_once()
snapI2 = sorted(tuple(r) for r in C.conn.execute("SELECT source_ns, source_id, leg_seq, event_ts, qty_base FROM postings p JOIN assets a USING(asset_id)"
                                                 " WHERE p.location='exchange:bybit' AND upper(a.symbol)='USDC'"))
chk(r9 is not None and C._meta_get("exf_fut_place_v") is not None and snapI2 == snapI and len(rows("bybit", "USDC", "futpnl")) == n0,
    "I3 core 자동 경로 = 보류 통화(bybit USDC) 줄 그대로 · 이관 완료 표식", (r9, C._meta_get("exf_fut_place_v")))
with open(LOG, "w", encoding="utf-8") as fh:
    fh.writelines(log_all)
plan, _c = C._exf_fut_place_plan()
pu = next((m for m in plan if m["ex"] == "bybit" and m["sym"] == "USDC"), {})
chk(not pu.get("err") and pu.get("cands") == [iB], "I4 감사 줄이 있으면 정상 계획(후보 = 그 대사)", (pu.get("err"), pu.get("cands")))
with open(LOG, "a", encoding="utf-8") as fh:
    fh.write('{"ts": 1, "loc": "exchange:bybit", "source_id": "exfrecon:USDC:' + str(iA) + '", "old_qty_ba\n')
rc, out = tool("--json", pj)
chk(rc == 1 and "감사 기록" in out, "I5 감사 기록에 깨진 줄 = 미리보기 거부(종료 1)", out[-300:])
with open(LOG, "w", encoding="utf-8") as fh:
    fh.writelines(log_all)

print("[J] (fr296 #3) 바이낸스 잔고 소스에 선물 지갑이 없으면 이관 대상 아님(대사와 같은 조건)")
C.conn.execute("DELETE FROM meta WHERE k IN ('exf_fut_from_binance')")
C.conn.commit()
plan, _c = C._exf_fut_place_plan()
jb = [m for m in plan if m["ex"] == "binance" and m.get("cands")]
src0 = C._meta_get("recon_src_exf_binance")
C.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_src_exf_binance', '[\"funding\", \"margin\"]')")
C.conn.commit()
plan, _c = C._exf_fut_place_plan()
chk(jb and not [m for m in plan if m["ex"] == "binance" and m.get("cands")], "J1 선물 지갑 소스 있음 = 후보 있음 · 없음 = 바이낸스 제외",
    ([m.get("cands") for m in jb], [(m["ex"], m.get("cands")) for m in plan]))
C.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_src_exf_binance', ?)", (src0,))
C.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('exf_fut_from_binance', ?)", (str(A["b0"]),))
C.conn.execute("DELETE FROM meta WHERE k='exf_fut_place_v'")
C.conn.commit()

print("[K] (fr296 #4) 미리보기 --json 출력 = state·설정 경로 거부 · 미리보기 계획 아닌 기존 파일 거부 · 심볼릭 링크로 state 가리켜도 거부")
ldb = common.DB_PATH
sz0 = os.path.getsize(ldb)
rc1, out1 = tool("--json", ldb)
rc2, out2 = tool("--json", os.path.join(common.STATE_DIR, "fp_x.json"))
other = os.path.join(T.TMP, "not_plan.json")
with open(other, "w") as fh:
    fh.write('{"keep": 1}')
rc3, out3 = tool("--json", other)
lnk = os.path.join(T.TMP, "plan_link.json")
os.symlink(ldb, lnk)
rc4, out4 = tool("--json", lnk)
chk(rc1 == 1 and rc2 == 1 and rc3 == 1 and rc4 == 1 and os.path.getsize(ldb) == sz0 and not os.path.exists(os.path.join(common.STATE_DIR, "fp_x.json"))
    and open(other).read() == '{"keep": 1}', "K1 원장·state·남의 파일·링크 = 거부(원장 크기 그대로)", (rc1, rc2, rc3, rc4, out1[-120:]))
rc5, out5 = tool("--json", pj)
chk(rc5 == 0 and json.load(open(pj)).get("plan") is not None, "K2 기존 미리보기 계획 파일 = 덮어씀(원자)", out5[-200:])

print("[L] (fr296 #5) --undo = 되돌리기 자료 검증 · 원장 세대 확인 · 커밋 전 합·보유 불변")
C.conn.execute("DELETE FROM meta WHERE k IN ('exf_fut_place_v', 'exf_fut_cur_bybit', 'exf_fut_from_bybit')")
C.conn.commit()
rc, out = tool("--json", pj)
rc, out = tool("--apply", "--expect", pj)
undo_p = os.path.join(common.STATE_DIR, f"exf_fut_place_v{core.Core.EXF_FUT_V}.json")
ud = json.load(open(undo_p))
snapL = sorted(tuple(r) for r in C.conn.execute("SELECT source_ns, source_id, leg_seq, event_ts, qty_base FROM postings WHERE location='exchange:bybit'"))
bad = json.loads(json.dumps(ud))
for m in bad["plan"]:
    m["ins"] = []
bp = os.path.join(T.TMP, "undo_bad.json")
json.dump(bad, open(bp, "w"))
rcb, outb = tool("--undo", bp)
snapL2 = sorted(tuple(r) for r in C.conn.execute("SELECT source_ns, source_id, leg_seq, event_ts, qty_base FROM postings WHERE location='exchange:bybit'"))
chk(rc == 0 and rcb == 1 and snapL2 == snapL and pos_ok("bybit", "USDC"), "L1 복원 항목 빠진 되돌리기 자료 = 거부(원장 무변)", (rc, rcb, outb[-300:]))
wv = json.loads(json.dumps(ud))
wv["v"] = 99
json.dump(wv, open(bp, "w"))
rcv, outv = tool("--undo", bp)
chk(rcv == 1, "L2 다른 세대 자료 = 거부", outv[-200:])
cp = json.loads(json.dumps(ud))
cp["ts"] = int(cp.get("ts") or 0) + 1
json.dump(cp, open(bp, "w"))
rcc, outc = tool("--undo", bp)
mk0 = C._meta_get("exf_fut_place_v")
C.conn.execute("UPDATE meta SET v=? WHERE k='exf_fut_place_v'", (":".join(mk0.split(":")[:2] + [str(int(mk0.split(":")[2]) + 1)]),))
C.conn.commit()
rcn, outn = tool("--undo", undo_p)
C.conn.execute("UPDATE meta SET v=? WHERE k='exf_fut_place_v'", (mk0,))
C.conn.commit()
chk(rcc == 1 and rcn == 1 and C._meta_get("exf_fut_place_v") == mk0, "L2b (fr297 #3) 정본과 다른 자료 · 원장 표식의 통화 수와 다른 자료 = 거부", (outc[-150:], outn[-150:]))
rcu, outu = tool("--undo", undo_p)
chk(rcu == 0 and pos_ok("bybit", "USDC") and str(C._meta_get("exf_fut_place_v")).startswith("1:undone:"), "L3 정본 되돌리기 자료 = 되돌림(합·보유 무변 · 표식 undone)",
    outu[-200:])
rcu2, outu2 = tool("--undo", undo_p)
chk(rcu2 == 1 and "이미 되돌린 원장" in outu2, "L4 이미 되돌린 원장(표식 undone)에 다시 = 거부", outu2[-200:])
C.conn.execute("DELETE FROM meta WHERE k='exf_fut_place_v'")
C.conn.commit()

print("[N] 감사 기록 쓰기 실패 = 같은 트랜잭션에 표식(meta exf_revert_log_fail '<누계>:<시각>') → 이관 미리보기 종료 1 · 자동 경로 보류")
C.EXF_FUT_EX = ()
post("kucoin", tick(0) - 500, "USDT", 100, sid="kc:d0")
recon("kucoin", {"USDT": 90})
C.EXF_REVERT_LOG = os.path.join(T.TMP, "no_such_dir", "x.jsonl")
recon("kucoin", {"USDT": 120})
del C.EXF_REVERT_LOG
del C.EXF_FUT_EX
lf = C._meta_get("exf_revert_log_fail")
chk(lf is not None and lf.split(":")[0] == "1" and total("kucoin", "USDT") == 120, "N1 쓰기 실패 1건 = 표식 '1:<시각>'(기장은 진행)", lf)
rc, out = tool("--json", pj)
chk(rc == 1 and "감사 기록 쓰기 실패" in out, "N2 표식 있으면 미리보기 종료 1(배포 중단)", out[-300:])
C.conn.execute("DELETE FROM meta WHERE k='exf_fut_place_v'")
C.conn.commit()
chk(C._exf_fut_place_once() is None and C._meta_get("exf_fut_place_v") is None, "N3 core 자동 경로도 보류(완료 표식 없음)")
C.conn.execute("DELETE FROM meta WHERE k='exf_revert_log_fail'")
C.conn.commit()

print("[R] (fr296 #1) 재구축(rebuild2 앵커 재계산) = 선물 정산 줄 금액 그대로 · 재파생 차이는 대사 줄로")
import importlib.util
import db as dbm
spec = importlib.util.spec_from_file_location("rb2", os.path.join(T.ROOT, "tools", "rebuild2.py"))
rb2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rb2)
gaid = C._exf_asset("gate", "USDT")
gdec = C.conn.execute("SELECT decimals FROM assets WHERE asset_id=?", (gaid,)).fetchone()[0]
GL = "exchange:gate"
rT = tick(0) - 300
rT2 = rT + 100
BP = os.path.join(T.TMP, "rb_live.db")
cb = dbm.open_db(BP)
cb.execute("INSERT INTO assets (asset_id, kind, chain, address, symbol, decimals, confirmed) VALUES (?, 'exchange_currency', NULL, 'gate:USDT', 'USDT', ?, 1)", (gaid, gdec))
cb.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('gate', 'deposit', 'gd2', 1, '{}', ?)", (rT + 50,))


def bpost(ns, sid, seq, t, q, lk, ev):
    cb.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event,"
               " classifier_ver) VALUES ('exchange',?,?,?,?,?,?,?,NULL,NULL,?,?,?)", (ns, sid, seq, t, gaid, GL, str(int(Decimal(q) * 10 ** gdec)), lk, ev, core.CLASSIFIER_VER))


bpost("gate:deposit", "gd1", 0, rT - 1000, "1000", "move_in", "EXF_DEPOSIT")
bpost("gate:futpnl", f"exfrecon:USDT:{rT}", 0, rT - 30, "100", "opening", "EXF_ADJUST")
bpost("gate:recon", f"exfrecon:USDT:{rT}", 0, rT, "-10", "opening", "EXF_ADJUST")
bpost("gate:deposit", "gd2", 0, rT + 40, "20", "move_in", "EXF_DEPOSIT")
bpost("gate:futpnl", f"exfrecon:USDT:{rT2}", 0, rT2 - 5, "50", "opening", "EXF_ADJUST")
cb.commit()
anchors = [tuple(r) for r in cb.execute(rb2.ANCHOR_SQL).fetchall()]
cb.close()
C.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind,"
               " event, classifier_ver) VALUES ('exchange','gate:deposit','gd1',0,?,?,?,?,NULL,NULL,'move_in','EXF_DEPOSIT',?)",
               (rT - 1000, gaid, GL, str(900 * 10 ** gdec), core.CLASSIFIER_VER))
C._bump_position(gaid, 900 * 10 ** gdec, GL)
C.conn.commit()
try:
    rb2.recompute_anchors(BP, C.conn, C, anchors, {}, {})
    rex = None
except Exception as e:
    rex = repr(e)
fr = sorted((int(r[0]), Decimal(int(r[1])) / 10 ** gdec) for r in C.conn.execute(
    "SELECT event_ts, qty_base FROM postings WHERE location=? AND source_ns='gate:futpnl'", (GL,)))
rr = {str(r[0]): Decimal(int(r[1])) / 10 ** gdec for r in C.conn.execute(
    "SELECT source_id, SUM(CAST(qty_base AS INTEGER)) FROM postings WHERE location=? AND source_ns='gate:recon' GROUP BY source_id", (GL,))}
tg = total("gate", "USDT")
chk(rex is None and fr == [(rT - 30, Decimal(100)), (rT2 - 5, Decimal(50))], "R1 선물 정산 줄 = 금액·시각 그대로(+100 · +50 — 종전 = δ 를 받아 +200)", (rex, fr))
rts = {str(r[0]): int(r[1]) for r in C.conn.execute("SELECT source_id, event_ts FROM postings WHERE location=? AND source_ns='gate:recon'", (GL,))}
chk(rts.get(f"exfrecon:USDT:{rT}") == rT and rts.get(f"exfrecon:USDT:{rT2}") == rT2,
    "R3 (fr297 #5) 부호가 바뀐 대사 줄·지은 0 앵커 = 그 대사 시각 그대로(창 시작으로 소급 안 함)", rts)
chk(rr.get(f"exfrecon:USDT:{rT}") == Decimal(90) and rr.get(f"exfrecon:USDT:{rT2}") == Decimal(20) and tg == Decimal(1000 - 100 + 100 + 90 + 50 + 20) - Decimal(0),
    "R2 재파생 차이 = 같은 대사 시각의 대사 줄(−10 → +90) · 선물만 있던 대사 = 대사 줄 새로(+20) · 합 = 라이브 관측", (rr, tg))

T.finish()
