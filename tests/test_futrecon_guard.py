#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import subprocess
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
LOG = core.Core.EXF_REVERT_LOG
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
EVS = {}


def tick(d=10):
    SEQ["t"] += d
    return SEQ["t"]


def post(ex, t, sym, qty, ns=None, sid=None, ev="EXF_DEPOSIT", lk="move_in"):
    aid = C._exf_asset(ex, sym)
    qb = int(Decimal(str(qty)) * E8)
    C.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
                   " leg_kind, event, classifier_ver) VALUES ('exchange',?,?,0,?,?,?,?,NULL,NULL,?,?,?)",
                   (ns or f"{ex}:deposit", sid or f"{ex}:{t}:{sym}:{qty}", int(t), aid, f"exchange:{ex}", str(qb), lk, ev, core.CLASSIFIER_VER))
    C._bump_position(aid, qb, f"exchange:{ex}")
    C.conn.commit()


def futfile(ex, add=(), ts=None):
    EVS.setdefault(ex, []).extend(add)
    common.atomic_write_json(os.path.join(common.STATE_DIR, f"futures_{ex}.json"), {
        "ts": int(ts if ts is not None else SEQ["t"] + 10 ** 6),
        "events": [{"t": int(t) * 1000, "symbol": s, "kind": k, "amount": a, "uid": f"u{i}"} for i, (t, s, k, a) in enumerate(EVS[ex])]})
    C.__dict__.pop("_exf_fut_cache", None)


def recon(ex, bal, sources=("futures",)):
    bts = tick()
    st = common.read_json(os.path.join(common.STATE_DIR, "exf_state.json"), {})
    st.setdefault(ex, {"seen": {}, "backfilled_until": NOW, "fills": {"backfilled_until": NOW}})
    common.atomic_write_json(os.path.join(common.STATE_DIR, "exf_state.json"), st)
    common.atomic_write_json(os.path.join(common.STATE_DIR, f"exf_balances_{ex}.json"), {"ts": bts, "balances": {k: float(v) for k, v in bal.items()},
                                                                                       "sources": list(sources)})
    C._drain_at = bts + 5
    C._last_exfrecon = 0
    C.exf_recon_pass({"ex"})
    return bts


def rows(ex, sym, ns="recon", like="exfrecon:%"):
    return sorted((int(r[0]), int(r[1]), Decimal(int(r[2])) / E8, r[3]) for r in C.conn.execute(
        "SELECT p.event_ts, p.leg_seq, p.qty_base, p.source_id FROM postings p JOIN assets a USING(asset_id) WHERE p.source_ns=? AND p.event='EXF_ADJUST'"
        " AND upper(a.symbol)=? AND p.location=? AND p.source_id LIKE ?", (f"{ex}:{ns}", sym, f"exchange:{ex}", like)).fetchall())


def total(ex, sym):
    v = C.conn.execute("SELECT SUM(CAST(p.qty_base AS INTEGER)) FROM postings p JOIN assets a USING(asset_id) WHERE p.location=? AND upper(a.symbol)=?",
                       (f"exchange:{ex}", sym)).fetchone()[0]
    return Decimal(int(v or 0)) / E8


def pos_ok(ex, sym):
    g = C._group_of(C._exf_asset(ex, sym))
    r = C.conn.execute("SELECT qty_norm FROM positions WHERE group_id=? AND location=?", (g, f"exchange:{ex}")).fetchone()
    return Decimal(r[0] if r else 0) == total(ex, sym)


def unmark(*exs):
    C.conn.execute("DELETE FROM meta WHERE k IN ('exf_fut_place_v', 'exf_fut_place_wait')")
    for ex in exs:
        C.conn.execute("DELETE FROM meta WHERE k IN (?, ?)", (f"exf_fut_from_{ex}", f"exf_fut_cur_{ex}"))
    C.conn.commit()


def pm(ex, sym):
    plan, curs = C._exf_fut_place_plan()
    return next((m for m in plan if m["ex"] == ex and m["sym"] in (sym, "*")), {}), curs


FAKE = os.path.join(T.TMP, "fakebin")
os.makedirs(FAKE, exist_ok=True)
with open(os.path.join(FAKE, "pm2"), "w") as fh:
    fh.write("#!/bin/sh\necho '[]'\n")
os.chmod(os.path.join(FAKE, "pm2"), 0o755)
WRAP = os.path.join(T.TMP, "fp_wrap.py")
with open(WRAP, "w") as fh:
    fh.write("import runpy, sys\nsys.dont_write_bytecode = True\nsys.path.insert(0, sys.argv[1])\nimport core\ncore.Core.EXF_INIT_PHASE = 5\n"
             "tool = sys.argv[2]\nsys.argv = [tool] + sys.argv[3:]\nrunpy.run_path(tool, run_name='__main__')\n")
PJ = os.path.join(T.TMP, "plan.json")


def tool(*args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
    env.update(TJ_BASE=T.TMP, PM2_BIN=os.path.join(FAKE, "pm2"), PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, WRAP, T.SRC, os.path.join(T.ROOT, "tools", "exf_fut_place.py")] + list(args), env=env,
                       capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


C.EXF_FUT_EX = ()
for ex9 in ("binance", "bybit", "okx"):
    post(ex9, tick(0) - 90 * 86400, "USDT", 10000, sid=f"{ex9}:d0")
recon("binance", {"USDT": 10000})
recon("bybit", {"USDT": 10000})
recon("okx", {"USDT": 10000})
tick(30)

print("[Y] 되살리는 음수 = 늦은 옛 체결 묶음 상쇄 → 묶음 직후 상쇄 줄")
tL = NOW - 40 * 86400
bY0 = recon("binance", {"USDT": 9990})
oL = tick(30)
for i9, (side, qty, px) in enumerate((("buy", "100", "10"), ("sell", "100", "13"))):
    fid = f"lateY{i9}"
    pay = {"id": fid, "late": 1, "ts": (tL + 60 * i9) * 1000, "qty": qty, "price": px, "side": side, "base": "XXX", "quote": "USDT", "fee": "0", "fee_ccy": "USDT"}
    C.conn.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('binance','trade',?,1,?,?)", (fid, json.dumps(pay), oL))
    sg = 1 if side == "buy" else -1
    post("binance", tL + 60 * i9, "XXX", sg * int(qty), ns="binance:trade", sid=fid, ev="EXF_BUY" if side == "buy" else "EXF_SELL", lk="acq" if side == "buy" else "disp")
    C.conn.execute("UPDATE postings SET leg_seq=0 WHERE source_id=?", (fid,))
    aid = C._exf_asset("binance", "USDT")
    qb = -sg * int(Decimal(qty) * Decimal(px) * E8)
    C.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind,"
                   " event, classifier_ver) VALUES ('exchange','binance:trade',?,1,?,?,'exchange:binance',?,NULL,NULL,?,?,?)",
                   (fid, tL + 60 * i9, aid, str(qb), "disp" if side == "buy" else "acq", "EXF_BUY" if side == "buy" else "EXF_SELL", core.CLASSIFIER_VER))
    C._bump_position(aid, qb, "exchange:binance")
C.conn.commit()
bYr = recon("binance", {"USDT": 9990})
tP = tick(5)
bYp = recon("binance", {"USDT": 10490})
del C.EXF_FUT_EX
chk(any(t == bYr and q == -300 for t, _l, q, _s in rows("binance", "USDT")) is False and total("binance", "USDT") == 10490, "Y0 전제: −300 이 되돌림으로 지워짐",
    rows("binance", "USDT"))
import importlib.util
_sp = importlib.util.spec_from_file_location("lfm", os.path.join(T.ROOT, "tools", "latefix_move.py"))
lfm = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(lfm)
_mv, _rj = lfm.plan(lfm._ro(), 0)
chk(any("되돌림으로 0" in x and "USDT" in x for x in _rj), "Y1 latefix_move: 대사 줄이 되돌림으로 0 = '수동 처리' 목록(조용히 넘기지 않음)", _rj)
futfile("binance", [(tP, "AAAUSDT", "REALIZED", 500.0)])
unmark("binance", "bybit", "okx")
m, _c = pm("binance", "USDT")
lt = m.get("late") or []
toff = tL + 60 + C.EXF_LATE_DT
chk(m.get("cands") == [bYp] and len(lt) == 1 and lt[0]["parts"][0]["ts"] == toff and lt[0]["parts"][0]["sid"].startswith(f"exflate:USDT:{toff}:b")
    and int(lt[0]["parts"][0]["qb"]) == -300 * E8 and int(lt[0]["rem"]) == 0, "Y2 계획: 되살릴 −300 = 묶음 직후(마지막 체결 + 1초) 상쇄 줄 · 대사 시각 남는 몫 0", (m.get("cands"), lt))
tot0 = total("binance", "USDT")
rc, out = tool("--json", PJ)
rc2, out2 = tool("--apply", "--expect", PJ)
ry = rows("binance", "USDT", like="exflate:%")
chk(rc == 0 and rc2 == 0 and [(t, q) for t, _l, q, _s in ry] == [(toff, Decimal(-300))] and not any(t == bYr for t, _l, _q, _s in rows("binance", "USDT"))
    and (tP, 0, Decimal(500)) in [(t, l, q) for t, l, q, _s in rows("binance", "USDT", ns="futpnl")] and total("binance", "USDT") == tot0 and pos_ok("binance", "USDT"),
    "Y3 적용: 상쇄 −300 @ 묶음 직후 · 대사 시각 줄 없음 · 선물 +500 정산 시각 · 합·보유 무변", (rc, rc2, out2[-200:], ry))

print("[Z] 대사 되돌림은 부채 이자 레그(leg 2)를 지우지 않음")
aidZ = C._exf_asset("bybit", "USDT")
bZ = tick(0) - 5
for leg9, q9 in ((0, -5), (2, -1)):
    C.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event,"
                   " classifier_ver) VALUES ('exchange','bybit:recon',?,?,?,?,'exchange:bybit',?,NULL,NULL,'opening','EXF_ADJUST',?)",
                   (f"exfrecon:USDT:{bZ}", leg9, bZ, aidZ, str(q9 * E8), core.CLASSIFIER_VER))
    C._bump_position(aidZ, q9 * E8, "exchange:bybit")
C.conn.commit()
rem, nrv = C._exf_reverse("bybit", "USDT", Decimal(10), tick())
C.conn.commit()
rz = [(l, q) for t, l, q, _s in rows("bybit", "USDT") if t == bZ]
chk(rz == [(2, Decimal(-1))] and rem == Decimal(5), "Z1 양수 차이 10 = leg 0 −5 만 되돌림 · 이자 −1 그대로 · 남는 5", (rz, rem))

print("[T] 커서 뒤 정산 합 $1 이상인데 흔적 없음(일부만 줄인 되돌림의 감사 줄 누락) = 보류")
C.EXF_FUT_EX = ()
bTa = recon("bybit", {"USDT": total("bybit", "USDT") - 100})
tT = tick(5)
bTb = recon("bybit", {"USDT": total("bybit", "USDT") + 50})
del C.EXF_FUT_EX
futfile("bybit", [(tT, "BBBUSDT", "REALIZED", 50.0)])
unmark("bybit")
la = open(LOG, encoding="utf-8").read().splitlines(True)
gone = [x for x in la if f"대사 {bTb} " in x]
with open(LOG, "w", encoding="utf-8") as fh:
    fh.writelines(x for x in la if x not in gone)
m, curs = pm("bybit", "USDT")
chk(len(gone) == 1 and m.get("hold") and "흔적" in m["hold"] and "USDT" not in (curs.get("bybit") or {}),
    "T1 감사 줄 누락(일부 줄임 — 경계 없음) = bybit USDT 보류 · 그 통화 시작 커서 안 남김", (len(gone), m, curs))
with open(LOG, "w", encoding="utf-8") as fh:
    fh.writelines(la)
m, curs = pm("bybit", "USDT")
chk(not m.get("err") and not m.get("hold") and bTb in (m.get("cands") or []), "T2 감사 줄 있으면 그 대사 = 후보", (m.get("hold"), m.get("cands")))

print("[U] 감사 줄 사유·수량이 깨지면 = 미리보기 거부")
la = open(LOG, encoding="utf-8").read().splitlines(True)
d9 = json.loads(la[-1])
d9["why"] = ""
with open(LOG, "w", encoding="utf-8") as fh:
    fh.writelines(la[:-1] + [json.dumps(d9, ensure_ascii=False) + "\n"])
rc, out = tool("--json", PJ)
chk(rc == 1 and "사유 손상" in out, "U1 사유 빈 줄 = 거부", out[-200:])
d9 = json.loads(la[-1])
d9["new_qty_base"] = str(-int(d9["old_qty_base"]) * 2)
with open(LOG, "w", encoding="utf-8") as fh:
    fh.writelines(la[:-1] + [json.dumps(d9, ensure_ascii=False) + "\n"])
rc, out = tool("--json", PJ)
chk(rc == 1 and "수량 손상" in out, "U2 줄인 뒤 수량이 더 커짐 = 거부", out[-200:])
with open(LOG, "w", encoding="utf-8") as fh:
    fh.writelines(la)

print("[V] 바이낸스: 대사 차이가 선물 정산으로 설명 안 됨 = 보류")
C.EXF_FUT_EX = ()
post("binance", tick(0) - 86400, "USDC", 1000, sid="bn:usdc0")
recon("binance", {"USDT": float(total("binance", "USDT")), "USDC": 990})
tV = tick(5)
bV = recon("binance", {"USDT": float(total("binance", "USDT")), "USDC": 1010})
del C.EXF_FUT_EX
futfile("binance", [(tV, "VVVUSDC", "REALIZED", 100.0)])
unmark("binance")
m, _c = pm("binance", "USDC")
chk(m.get("hold") and "근거 부족" in m["hold"], "V1 남는 몫 −80(선물 100) = 바이낸스 USDC 보류", m)
C.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('exf_fut_from_binance', ?)", (C._meta_get("recon_done_exf_binance"),))
C.conn.commit()

print("[Q] (fr299 #2) 바이빗·OKX 도: 대사 차이가 선물 정산으로 설명 안 되면 보류(뒤 대사가 가린 일부 줄임 감사 누락 등)")
C.EXF_FUT_EX = ()
post("bybit", tick(0) - 86400, "USDC", 1000, sid="bb:usdc0")
recon("bybit", {"USDT": float(total("bybit", "USDT")), "USDC": 990})
tQ = tick(5)
bQ = recon("bybit", {"USDT": float(total("bybit", "USDT")), "USDC": 1010})
del C.EXF_FUT_EX
futfile("bybit", [(tQ, "QQQPERP", "REALIZED", 100.0)])
unmark("bybit")
m, _c = pm("bybit", "USDC")
chk(m.get("hold") and "근거 부족" in m["hold"], "Q1 바이빗 USDC 남는 몫 −80(선물 100) = 보류", m)
rc, out = tool("--json", PJ)
chk(rc == 0 and "보류 통화" in out, "Q2 보류는 미리보기 종료 0(다른 통화는 옮김 · 보류 줄 표시)", out[-250:])
C.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('exf_fut_from_bybit', ?)", (C._meta_get("recon_done_exf_bybit"),))
C.conn.commit()

print("[W] 원장에 자산 없는 통화의 정산 = 읽기 전용 미리보기 정상")
C.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('exf_fut_place_v', '1:0:0')")
C.conn.commit()
tW = tick(5)
recon("okx", {"USDT": 9999})
futfile("okx", [(tW, "WWW-USDC-SWAP", "REALIZED", 5.0)])
unmark("okx")
chk(C.conn.execute("SELECT count(*) FROM assets WHERE address='okx:USDC'").fetchone()[0] == 0, "W0 전제: 원장에 OKX USDC 자산 없음")
rc, out = tool("--json", PJ)
chk("Traceback" not in out and "readonly" not in out.lower(), "W1 OKX USDC(원장에 없음) 미리보기가 쓰기 시도 없이 끝남", out[-300:])

print("[X] 마지막 후보 대사 자신의 줄이 뒤 대사에 지워졌는데 감사 기록 없음 = 보류")
C.EXF_FUT_EX = ()
recon("okx", {"USDT": 9998})
tX = tick(5)
bX = recon("okx", {"USDT": 9993})
bX2 = recon("okx", {"USDT": 9998})
del C.EXF_FUT_EX
futfile("okx", [(tX, "XXX-USDT-SWAP", "FEE", -5.0)])
unmark("okx")
la = open(LOG, encoding="utf-8").read().splitlines(True)
with open(LOG, "w", encoding="utf-8") as fh:
    fh.writelines(x for x in la if f'"exfrecon:USDT:{bX}"' not in x)
m, _c = pm("okx", "USDT")
chk(m.get("hold") and "감사 기록 없음" in m["hold"], "X1 마지막 후보(bX)의 지운 줄 기록 없음 = OKX USDT 보류", m)
with open(LOG, "w", encoding="utf-8") as fh:
    fh.writelines(la)

print("[F] 선물 정산 파일이 마지막 대사보다 낡음 = 그 거래소 보류")
futfile("okx", [], ts=int(C._meta_get("recon_done_exf_okx")) - 100)
m, _c = pm("okx", "USDT")
chk(m.get("err") and "낡음" in m["err"], "F1 파일 시각 < 마지막 대사 = OKX 보류(완료 표식 없이)", m)

print("[P] 상태 패널: 선물 정산 기다리며 대사 미룸 1시간 넘으면 주의 · 상한 넘겨 종전 규칙이면 하루 주의(알림 없음)")
import health
WP = os.path.join(common.STATE_DIR, "exf_fut_wait.json")
futfile("bybit", [], ts=SEQ["t"] - 5)
dP = C._meta_get("recon_done_exf_bybit")
recon("bybit", {"USDT": float(total("bybit", "USDT"))})
wd = json.load(open(WP)) if os.path.exists(WP) else {}
t_now = time.time()
warns = lambda lst: [c["cid"] for c in lst if c["level"] == "warn" and c["cid"].startswith("futwait")]
it0 = health.collect_fut_wait(t_now + 100)
wd2 = dict(wd, ts=int(t_now) + 3600)
common.atomic_write_json(WP, wd2)
it1 = health.collect_fut_wait(t_now + 3700)
w1 = [c for c in it1 if c["level"] == "warn" and c["cid"].startswith("futwait")]
chk(C._meta_get("recon_done_exf_bybit") == dP and "bybit" in (wd.get("wait") or {}) and not warns(it0)
    and [c["cid"] for c in w1] == ["futwait:bybit"] and w1[0]["notify"] is False and all(c["notify"] is False for c in it1),
    "P1 대사 미룸 표식 · 1시간 전엔 주의 없음 · 1시간 넘으면 '주의'(알림 없음)", (wd, warns(it0), warns(it1)))
chk(not warns(health.collect_fut_wait(t_now + 3600 + health.FUT_WAIT_FRESH_S + 1)), "P2 표식이 오래됨(재시작 등 — 끝난 대기) = 주의 없음")
hst = {}
hh = dict(health.DEFAULTS, units=["tj-core"])
for dt9 in (3700, 3710):
    health.step(hst, health.evaluate({"now": t_now + dt9}, hh), t_now + dt9, hh)
opened = "futwait:bybit" in (hst.get("incidents") or {})
C.EXF_FUT_WAIT_S = 0
recon("bybit", {"USDT": float(total("bybit", "USDT"))})
del C.EXF_FUT_WAIT_S
it2 = health.collect_fut_wait(time.time())
chk(warns(it2) == ["futwait:fb:bybit"] and C._meta_get("recon_done_exf_bybit") != dP, "P3 상한 넘겨 종전 규칙 = '주의' 한 줄(대기 줄은 ok)", warns(it2))
for dt9 in (3760, 3770):
    health.step(hst, health.evaluate({"now": t_now + dt9}, hh), t_now + dt9, hh)
chk(opened and "futwait:bybit" not in (hst.get("incidents") or {}) and "futwait:fb:bybit" in (hst.get("incidents") or {}),
    "P3b (fr303) 평가→사건: 대기 사건은 상한 전환 때 바로 닫히고 '종전 규칙' 사건이 열림(1시간 유예 없음)", sorted(hst.get("incidents") or {}))
futfile("bybit", [])
recon("bybit", {"USDT": float(total("bybit", "USDT"))})
wd = json.load(open(WP))
chk(not wd.get("wait") and warns(health.collect_fut_wait(time.time())) == ["futwait:fb:bybit"]
    and not warns(health.collect_fut_wait(time.time() + health.FUT_FB_SHOW_S + 10)), "P4 대기 끝 = 대기 주의 없음 · 종전 규칙 기록은 하루 뒤 ok", wd)
t9 = time.time() + health.FUT_FB_SHOW_S + 10
for dt9 in (0, 10):
    health.step(hst, health.evaluate({"now": t9 + dt9}, hh), t9 + dt9, hh)
chk(not any(k.startswith("futwait") for k in (hst.get("incidents") or {})), "P4b (fr303) 하루 지나면 '종전 규칙' 사건도 바로 닫힘", sorted(hst.get("incidents") or {}))

print("[K9] (fr299 #3) 바이낸스 선물 정산 수집이 5쪽 상한에서 멈추면 파일 시각 = 확인된 정산 끝(지금 아님)")
import ex_foreign
FB = os.path.join(common.STATE_DIR, "futures_binance.json")
fb_keep = open(FB, encoding="utf-8").read()
T0K = (int(time.time()) - 30 * 86400) * 1000
CALLS = {"n": 0}


def _fake(url, headers=None, *a, **k):
    if "/fapi/v2/account" in url:
        return {"totalWalletBalance": "0", "availableBalance": "0", "totalInitialMargin": "0", "positions": []}
    if "/fapi/v2/positionRisk" in url:
        return []
    if "/fapi/v1/income" in url:
        CALLS["n"] += 1
        base = T0K + CALLS["n"] * 1000 * 60000
        return [{"tranId": f"{CALLS['n']}-{i}", "incomeType": "FUNDING_FEE", "time": base + i * 60000, "income": "-0.01", "symbol": "AAAUSDT"}
                for i in range(1000)]
    return []


_fake._tj_test_mock = True
ex_foreign._http_json_err = _fake
ex_foreign._gov_prepare = lambda *a, **k: None
ex_foreign.PACE = 0
common.atomic_write_json(FB, {"ts": 0, "events": [], "cursor": {"income": T0K}})
ex_foreign._fut_binance({"TJ_BINANCE_KEY": "k", "TJ_BINANCE_SECRET": "s"})
fk = json.load(open(FB))
last_t = max(int(e["t"]) for e in fk["events"])
C.__dict__.pop("_exf_fut_cache", None)
chk(CALLS["n"] == 5 and abs(fk["ts"] - time.time()) < 60 and fk.get("inc_cov_ts") == (last_t - 1) // 1000 and len(fk["events"]) == 5000
    and C._exf_fut_events("binance")[0] == (last_t - 1) // 1000,
    "K9a 5쪽 꽉 참 = 정산 확인 끝(inc_cov_ts) = 마지막 정산 직전 · 대사는 그 시각까지만 덮은 것으로 · 파일 ts 는 조회 시각(fr303) · 5,000건 보존",
    (CALLS["n"], fk["ts"], fk.get("inc_cov_ts"), last_t, C._exf_fut_events("binance")[0]))
fk["positions"] = [{"symbol": "AAAUSDT", "side": "LONG", "qty": 1.0, "entry": 10.0, "mark": 11.0, "upnl": 1.0, "leverage": "5", "liq": 1.0}]
common.atomic_write_json(FB, fk)
import web
import types
_wb = web.StateBuilder.__new__(web.StateBuilder)
_wb.cfg = {}
_wb.spot = types.SimpleNamespace(rate=1380.0, fx_basis=1380.0, price=lambda s9: None)
try:
    _fv = web.StateBuilder._futures_view(_wb)
except Exception as e:
    _fv = {"_exc": repr(e)}
chk(any(p.get("exKey") == "binance" for p in (_fv.get("positions") or [])),
    "K9c (fr303) 부분 수집 파일도 화면에선 신선 — 방금 읽은 바이낸스 포지션이 빠지지 않음", {k: _fv.get(k) for k in ("staleEx", "positions", "_exc")})


def _fake2(url, headers=None, *a, **k):
    if "/fapi/v1/income" in url:
        return [{"tranId": "x1", "incomeType": "FUNDING_FEE", "time": T0K + 10, "income": "-0.01", "symbol": "AAAUSDT"}]
    return _fake(url, headers)


_fake2._tj_test_mock = True
ex_foreign._http_json_err = _fake2
ex_foreign._fut_binance({"TJ_BINANCE_KEY": "k", "TJ_BINANCE_SECRET": "s"})
chk(abs(json.load(open(FB))["ts"] - time.time()) < 60, "K9b 끝까지 받음(마지막 쪽 1000건 미만) = 파일 ts = 지금(종전)", json.load(open(FB))["ts"])
with open(FB, "w", encoding="utf-8") as fh:
    fh.write(fb_keep)

T.finish()
