#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time
import urllib.parse
from decimal import Decimal

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import common

assert T.TMP in common.STATE_DIR
import ex_foreign as EF
import fut_rcpt

chk = T.chk
DAY_MS = 86400 * 1000
MIN_MS = 60 * 1000
ENV = {"TJ_BYBIT_KEY": "k", "TJ_BYBIT_SECRET": "s"}
B = {"pos": [], "cp": [], "tl": [], "tl_err": None, "calls": []}
FP = os.path.join(common.STATE_DIR, "futures_bybit.json")
HAS = hasattr(EF, "BB_TLOG_TYPES")


def ok(rows, nxt=""):
    return {"retCode": 0, "retMsg": "OK", "result": {"list": rows, "nextPageCursor": nxt}}


def fake_http(url, headers=None, data=None, method=None, timeout=20):
    u = urllib.parse.urlsplit(url)
    q = dict(urllib.parse.parse_qsl(u.query))
    B["calls"].append((u.path, q))
    s9, e9 = int(q.get("startTime") or 0), int(q.get("endTime") or 0)
    if u.path == "/v5/position/list":
        return ok([dict(p) for p in B["pos"]])
    if u.path == "/v5/position/closed-pnl":
        return ok([dict(c) for c in B["cp"] if s9 <= int(c["updatedTime"]) <= e9])
    if u.path == "/v5/execution/list":
        return ok([])
    if u.path == "/v5/account/transaction-log":
        if B["tl_err"]:
            return {"retCode": B["tl_err"], "retMsg": "합성 오류"}
        if B.get("bad_off") is not None and int(q.get("cursor") or 0) == B["bad_off"]:
            B["bad_off"] = None
            return {"retCode": 0, "retMsg": "OK", "result": {"list": None}}
        assert q.get("accountType") == "UNIFIED" and q.get("category") == "linear" and 1 <= int(q["limit"]) <= 50 and 0 <= e9 - s9 <= 7 * DAY_MS, q
        rows = sorted((dict(r) for r in B["tl"] if r.get("category") == "linear" and s9 <= int(r["transactionTime"]) <= e9),
                      key=lambda r: -int(r["transactionTime"]))
        off = int(q.get("cursor") or 0)
        lim = int(q["limit"])
        return ok(rows[off:off + lim], str(off + lim) if off + lim < len(rows) else "")
    raise AssertionError("예상 밖 경로 " + u.path)


EF.http_json = fake_http
EF._gov_prepare = lambda *a, **k: None
EF._CLOCK_ON[0] = False
EF.PACE = 0
_REAL_TIME = time.time
CLK = [int(_REAL_TIME()) - 20 * 86400]
time.time = lambda: CLK[0] + 0.25


def run():
    B["calls"].clear()
    EF._fut_bybit(ENV)
    return json.load(open(FP))


def n_tl():
    return sum(1 for p, _q in B["calls"] if p == "/v5/account/transaction-log")


def tl(i, t_ms, typ="TRADE", cash="0", fee="0", fund="0", side="Buy", qty="10", size="10", px="1.0", oid=None, cat="linear", sym="ZZZUSDT", **kw):
    r = {"id": f"{i}_ZZZUSDT_9{i}", "symbol": sym, "category": cat, "side": side, "transactionTime": str(t_ms), "type": typ,
         "qty": qty, "size": size, "currency": "USDT", "tradePrice": px, "funding": fund, "fee": fee, "cashFlow": cash,
         "change": "", "cashBalance": "0", "orderId": oid or f"o{i}", "tradeId": f"x{i}"}
    r.update(kw)
    return r


def cp(oid, t_ms, net, lev="5", side="Sell", qty="10", px_in="1.0", px_out="2.2"):
    return {"orderId": oid, "updatedTime": str(t_ms), "symbol": "ZZZUSDT", "closedPnl": str(net), "side": side, "closedSize": qty, "qty": qty,
            "avgEntryPrice": px_in, "avgExitPrice": px_out, "leverage": lev, "openFee": "0.6", "closeFee": "0.55", "execType": "Trade"}


def tl_no(r):
    u = str(r.get("uid") or "")
    try:
        return int(u.split(":")[1].split("_")[0]) if u.startswith("bbt:") else -1
    except (IndexError, ValueError):
        return -1


def evs(d, kind=None):
    return [r for r in d.get("events") or () if kind is None or r.get("kind") == kind]


print("[L1] 거래 내역 조회 실패(권한) = 종전 closed-pnl 그대로")
now0 = CLK[0] * 1000
B["cp"] = [cp("oA", now0 - 2 * DAY_MS, "3.5")]
B["tl_err"] = 10005
d = run()
cur = d.get("cursor") or {}
chk([(r["kind"], r["amount"], r["uid"]) for r in evs(d)] == [("REALIZED", 3.5, f"bb:oA:{now0 - 2 * DAY_MS}")], "L1a 청산손익 = REALIZED(종전 그대로)", evs(d))
chk(HAS and "tlog_from" not in cur and cur.get("tlog_off", 0) > now0 and "inc_cov_ts" not in d and n_tl() == 1,
    "L1b 전환 안 함 · 6시간 쉼 표식 · 덮은 시각 칸 없음(종전 대사 규칙)", (cur, n_tl()))
CLK[0] += 3600
run()
chk(HAS and n_tl() == 0, "L1c 쉬는 동안 거래 내역 조회 0회", n_tl())

print("[L2] 전환 — 최근 5분 체결이 있으면 미룸 · 조용하면 전환")
CLK[0] += 6 * 3600
B["tl_err"] = None
nowA = CLK[0] * 1000
B["tl"] = [tl(1, nowA - 2 * MIN_MS, fee="0.1")]
d = run()
chk(HAS and "tlog_from" not in (d.get("cursor") or {}) and n_tl() == 1, "L2a 최근 2분 체결 = 전환 미룸", (d.get("cursor"), n_tl()))
CLK[0] += 600
B["pos"] = [{"symbol": "ZZZUSDT", "side": "Buy", "size": "10", "avgPrice": "1.0", "leverage": "5", "positionValue": "10", "markPrice": "1.0",
             "unrealisedPnl": "0", "liqPrice": "", "positionIM": "2", "positionMM": "0.1", "createdTime": "1", "updatedTime": "1"}]
d = run()
chk(HAS and "tlog_from" not in (d.get("cursor") or {}), "L2a2 미청산 linear 포지션 있음 = 전환 미룸(코덱스 it455 — 전환 전 진입 수수료가 사라지지 않게)", d.get("cursor"))
B["pos"] = []
CLK[0] += 600
TSW = CLK[0] * 1000 + 250
d = run()
cur = d.get("cursor") or {}
chk(cur.get("tlog_from") == TSW and cur.get("tlog") == TSW and d.get("inc_cov_ts") == (TSW - 120000) // 1000,
    "L2b 조용 = 전환(tlog_from = 그 주기 시각 · 덮은 시각 = 2분 앞)", (cur, d.get("inc_cov_ts")))
chk(len(evs(d)) == 1 and not any(str(r.get("uid", "")).startswith("bbt:") for r in evs(d)), "L2c 전환 앞 거래 내역 줄(진입 수수료)은 이벤트로 안 넣음(종전 대사가 흡수)", evs(d))

print("[L3] 전환 뒤 — 수수료·펀딩·실현을 각자 시각으로")
T_OPEN, T_F1, T_TR, T_F2, T_CL = TSW + MIN_MS, TSW + 2 * 3600 * 1000, TSW + 3 * 3600 * 1000, TSW + 10 * 3600 * 1000, TSW + 11 * 3600 * 1000
B["tl"] += [tl(2, T_OPEN, fee="0.6", side="Buy", qty="10", size="10", px="1.0", oid="oO"),
            tl(3, T_F1, typ="SETTLEMENT", fund="-0.2", side="Buy", qty="10", size="10", px="1.5"),
            tl(4, T_TR, typ="TRANSFER_IN", cash="100", side="None", qty="0", size="0", sym=""),
            tl(5, T_F2, typ="SETTLEMENT", fund="0.05", side="Buy", qty="10", size="10", px="1.9"),
            tl(6, T_CL, cash="12", fee="0.55", side="Sell", qty="10", size="0", px="2.2", oid="oC")]
NET = 12 - 0.6 - 0.55 - 0.2 + 0.05
B["cp"].append(cp("oC", T_CL + 5, f"{NET:.2f}"))
CLK[0] = (T_CL + 3600 * 1000) // 1000
d = run()
new = [(r["t"], r["kind"], r["amount"]) for r in evs(d) if str(r.get("uid", "")).startswith("bbt:")]
chk(sorted(new) == sorted([(T_OPEN, "FEE", -0.6), (T_F1, "FUNDING", -0.2), (T_F2, "FUNDING", 0.05), (T_CL, "REALIZED", 12.0), (T_CL, "FEE", -0.55)]),
    "L3a 진입 수수료·펀딩(내고 받음)·청산 실현·청산 수수료 = 각자 시각 · 부호(수수료 −, 받은 펀딩 +)", new)
rz = [r for r in evs(d, "REALIZED") if str(r.get("uid", "")).startswith("bbt:")]
chk(rz and rz[0].get("asset") == "USDT" and rz[0].get("oid") == "oC" and rz[0]["uid"] == "bbt:6_ZZZUSDT_96:p", "L3b 정산 자산 USDT · 주문 id · uid", rz)
mk = [r for r in evs(d) if r.get("uid") == f"bb:oC:{T_CL + 5}"]
chk(len(mk) == 1 and mk[0]["kind"] == "CLOSEDPNL" and mk[0]["amount"] == 0 and abs(mk[0]["net"] - NET) < 1e-9,
    "L3c 같은 청산의 closed-pnl = 금액 0 표식(CLOSEDPNL · 옛 수집기 uid 그대로 — 되돌려도 다시 안 넣음)", mk)
s_new = sum(r["amount"] for r in evs(d) if r.get("kind") in ("REALIZED", "FEE", "FUNDING") and r["t"] >= TSW)
chk(abs(s_new - NET) < 1e-9 and not any(r["t"] >= TSW and str(r.get("uid", "")).startswith("bb:") and r.get("kind") == "REALIZED" for r in evs(d)),
    "L3d 전환 뒤 정산 합 = closedPnl(같은 돈 한 번 · 이중 계상 없음)", (s_new, NET))
chk(not any(r["t"] == T_TR for r in evs(d)), "L3e 이체(TRANSFER_IN) 줄 = 선물 이벤트 아님", [r for r in evs(d) if r["t"] == T_TR])
chk(d.get("inc_cov_ts") == CLK[0] - 120 and (d.get("cursor") or {}).get("tlog") == CLK[0] * 1000 + 250, "L3f 덮은 시각 = 지금 − 2분 · 커서 = 지금", (d.get("inc_cov_ts"), d.get("cursor")))
n0 = len(evs(d))
CLK[0] += 600
d = run()
chk(len(evs(d)) == n0, "L3g 다시 돌려도 이벤트 수 그대로(멱등 · uid)", (len(evs(d)), n0))

print("[L4] 영수증 옆 파일 — 전환 뒤 청산 행 = 거래 내역 체결")
T_RV = CLK[0] * 1000 - 30 * MIN_MS
B["tl"].append(tl(7, T_RV, cash="20", fee="0.3", side="Sell", qty="15", size="-5", px="3", oid="oR"))
B["cp"].append(cp("oR", T_RV + 3, "19.7", lev="3", qty="10", px_out="3"))
run()
px = fut_rcpt.load("bybit").get("rows") or []
cl = {r["uid"]: r for r in px if r.get("role") == "close"}
r6, r7 = cl.get("bbt:6_ZZZUSDT_96:p"), cl.get("bbt:7_ZZZUSDT_97:p")
chk(r6 and abs(r6["entry_px"] - 1.0) < 1e-9 and r6["qty_base"] == 10 and r6["px"] == 2.2 and r6.get("lev") == 5 and r6.get("oid") == "oC",
    "L4a 청산 행(uid = 이벤트 uid · 진입가 = 청산가 − 실현 ÷ 수량 · 레버리지 = closed-pnl)", r6)
chk(r7 and r7["qty_base"] == 10 and abs(r7["entry_px"] - 1.0) < 1e-9, "L4b 반전 체결 = 닫은 몫(10)만 · 진입가 맞음", r7)
chk(f"bb:oA:{now0 - 2 * DAY_MS}" in cl and not any(u.startswith("bb:oC") or u.startswith("bb:oR") for u in cl),
    "L4c 전환 앞 closed-pnl 행은 그대로 · 전환 뒤 closed-pnl 행은 없음(같은 청산 두 번 안 걸음)", sorted(cl))
if HAS:
    g = fut_rcpt.assemble
    dd = json.load(open(FP))
    ev9 = [dict(r, ex="bybit") for r in dd["events"] if r.get("kind") in ("REALIZED", "FEE", "FUNDING") and r["t"] >= T_CL - 1000 and r["t"] <= T_CL + 1000]
    iso = time.strftime("%Y-%m-%d", time.gmtime(T_CL / 1000 + 9 * 3600))
    fev = [(iso, r["t"], r["amount"], r["amount"] * 1300, r) for r in ev9]
    rc = T.safe(g, iso, fev, {"bybit": fut_rcpt.load("bybit")}, {"bybit": "바이빗"}, lambda *a, **k: {}, T_CL + DAY_MS)
    txt = json.dumps(rc, ensure_ascii=False, default=str)
    chk(isinstance(rc, dict) and rc.get("ok") and "2.2" in txt and "거래소 값끼리 안 맞음" not in txt and "못 찾음" not in txt,
        "L4d 영수증: 청산가 2.2 · 진입가 확인 통과(가격 행과 이벤트가 짝지어짐)", txt[:600])

print("[L5] 전환 뒤 실패 = 포지션은 쓰고 덮은 시각은 받은 데까지")
prev_tl = int((json.load(open(FP)).get("cursor") or {}).get("tlog") or 0)
B["pos"] = [{"symbol": "ZZZUSDT", "side": "Buy", "size": "4", "avgPrice": "1.1", "markPrice": "1.2", "unrealisedPnl": "0.4", "leverage": "5", "liqPrice": "0.5"}]
B["tl_err"] = 10016
CLK[0] += 1800
T_LATE = CLK[0] * 1000 - 5 * MIN_MS
B["tl"].append(tl(8, T_LATE, typ="SETTLEMENT", fund="-0.07", side="Buy"))
d = run()
chk(d.get("ts") == CLK[0] and len(d.get("positions") or []) == 1 and d.get("inc_cov_ts") == (prev_tl - 120000) // 1000 and not any(r["t"] == T_LATE for r in evs(d)),
    "L5a 실패 주기: 포지션 = 지금 · 덮은 시각 = 지난번 끝(core 대사가 기다림) · 새 이벤트 없음", (d.get("ts"), d.get("inc_cov_ts"), prev_tl))
B["tl_err"] = None
CLK[0] += 600
d = run()
chk(any(r["t"] == T_LATE and r["amount"] == -0.07 for r in evs(d)) and d.get("inc_cov_ts") == CLK[0] - 120, "L5b 다음 주기 이어 받음 · 덮은 시각 회복", d.get("inc_cov_ts"))

print("[L6] 주기 쪽 상한 · 형식 이상 줄")
EF.BB_TLOG_CALLS_MAX = 2
base6 = CLK[0] * 1000 + 1000
B["tl"] += [tl(100 + i, base6 + i * 1000, typ="SETTLEMENT", fund="-0.001", side="Buy") for i in range(130)]
cov_before = d.get("inc_cov_ts")
CLK[0] += 600
d = run()
got = sum(1 for r in evs(d) if 100 <= tl_no(r) < 230) if HAS else 0
chk(HAS and got == 100 and d.get("inc_cov_ts") == cov_before and (d.get("cursor") or {}).get("tlog_pg"),
    "L6a 상한(2쪽) = 받은 100줄만 · 덮은 시각 그대로 · 쪽 커서 남김", (got, d.get("inc_cov_ts"), cov_before, (d.get("cursor") or {}).get("tlog_pg")))
CLK[0] += 600
d = run()
got = sum(1 for r in evs(d) if 100 <= tl_no(r) < 230) if HAS else 0
chk(got == 130 and d.get("inc_cov_ts") == CLK[0] - 120 and not (d.get("cursor") or {}).get("tlog_pg"), "L6b 다음 주기 같은 창·커서로 이어 끝냄 · 중복 없음", (got, d.get("inc_cov_ts")))
EF.BB_TLOG_CALLS_MAX = 40
T_BAD = CLK[0] * 1000 + 2000
B["tl"] += [tl(300, T_BAD, fee="abc"), tl(301, T_BAD + 1, fee="0.01")]
cov_before = d.get("inc_cov_ts")
CLK[0] += 600
d = run()
chk(HAS and not any(r["t"] == T_BAD for r in evs(d)) and any(r["t"] == T_BAD + 1 and r["kind"] == "FEE" for r in evs(d)) and d.get("inc_cov_ts") == CLK[0] - 120,
    "L6c 형식 이상 줄 = 그 줄만 뺌(대사 나머지가 흡수) · 같은 창 다른 줄은 넣음 · 수집은 멈추지 않음(덮은 시각 전진)", (d.get("inc_cov_ts"), cov_before))

print("[L7] (ex435 ①) 둘째 쪽 형식 오류 — 첫 쪽은 이벤트로 보존 · 덮은 시각 그대로 · 다음 주기에 빠짐 없이")
base7 = CLK[0] * 1000 + 3000
B["tl"] += [tl(400 + i, base7 + i * 1000, typ="SETTLEMENT", fund="-0.002", side="Buy") for i in range(60)]
B["bad_off"] = 50
cov_before = d.get("inc_cov_ts")
CLK[0] += 600
d = run()
got = sum(1 for r in evs(d) if 400 <= tl_no(r) < 460)
chk(got == 50 and d.get("inc_cov_ts") == cov_before and not (d.get("cursor") or {}).get("tlog_pg"),
    "L7a 첫 쪽 50줄 = 이벤트로 보존 · 덮은 시각 그대로 · 쪽 커서 버림(다음엔 창 처음부터)", (got, d.get("inc_cov_ts"), cov_before, (d.get("cursor") or {}).get("tlog_pg")))
CLK[0] += 600
d = run()
got = sum(1 for r in evs(d) if 400 <= tl_no(r) < 460)
chk(got == 60 and d.get("inc_cov_ts") == CLK[0] - 120, "L7b 다음 주기 = 60줄 전부 한 번씩 · 덮은 시각 전진", (got, d.get("inc_cov_ts")))

time.time = _REAL_TIME

print("[C] core 대사 — 수집기가 쓴 파일 그대로")
import core

core.dm = lambda *a, **k: None
C = core.Core(common.load_config())
C._quote_usd = lambda q, ts: Decimal(1)
C.EXF_INIT_PHASE = 5
E8 = 10 ** 8
NOW = int(_REAL_TIME())
SEQ = {"t": NOW - 1700}


def tick(dt=10):
    SEQ["t"] += dt
    return SEQ["t"]


def tick_min():
    SEQ["t"] += 60 - SEQ["t"] % 60 + 1
    return SEQ["t"]


def post(t, qty):
    aid = C._exf_asset("bybit", "USDT")
    qb = int(Decimal(str(qty)) * E8)
    C.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base,"
                   " cost_usd, cost_krw, leg_kind, event, classifier_ver) VALUES ('exchange','bybit:deposit',?,0,?,?,'exchange:bybit',?,NULL,NULL,'move_in','EXF_DEPOSIT',?)",
                   (f"bybit:d:{t}", int(t), aid, str(qb), core.CLASSIFIER_VER))
    C._bump_position(aid, qb, "exchange:bybit")
    C.conn.commit()


def recon(bal):
    bts = tick()
    st = common.read_json(os.path.join(common.STATE_DIR, "exf_state.json"), {})
    st.setdefault("bybit", {"seen": {}, "backfilled_until": NOW, "fills": {"backfilled_until": NOW}})
    common.atomic_write_json(os.path.join(common.STATE_DIR, "exf_state.json"), st)
    common.atomic_write_json(os.path.join(common.STATE_DIR, "exf_balances_bybit.json"), {"ts": bts, "balances": {"USDT": bal}, "sources": []})
    C._drain_at = bts + 5
    C._last_exfrecon = 0
    C.exf_recon_pass({"ex"})
    return bts


def lines(ns):
    return sorted((int(r[0]), Decimal(int(r[1])) / E8) for r in C.conn.execute(
        "SELECT p.event_ts, p.qty_base FROM postings p JOIN assets a USING(asset_id) WHERE p.source_ns=? AND p.event='EXF_ADJUST' AND upper(a.symbol)='USDT'",
        (f"bybit:{ns}",)).fetchall())


def total():
    v = C.conn.execute("SELECT SUM(CAST(p.qty_base AS INTEGER)) FROM postings p JOIN assets a USING(asset_id) WHERE p.location='exchange:bybit' AND upper(a.symbol)='USDT'").fetchone()[0]
    return Decimal(int(v or 0)) / E8


def collect():
    C.__dict__.pop("_exf_fut_cache", None)
    B["calls"].clear()
    EF._fut_bybit(ENV)


for p9 in (FP, fut_rcpt.px_path("bybit")):
    if os.path.exists(p9):
        os.remove(p9)
B.update(pos=[], cp=[], tl=[], tl_err=None)
TSW2 = (SEQ["t"] - 600) * 1000
common.atomic_write_json(FP, {"ts": SEQ["t"] - 600, "events": [], "positions": [], "wallet": {}, "cursor": {"tlog_from": TSW2, "tlog": TSW2, "closed_pnl": TSW2}})
t0 = tick()
post(t0, 1000)
collect()
b0 = recon("1000")
ta = tick_min()
B["tl"].append(tl(11, ta * 1000 + 7, fee="0.6", oid="cO"))
collect()
b1 = recon("999.4")
tf = tick_min()
B["tl"].append(tl(12, tf * 1000 + 7, typ="SETTLEMENT", fund="-0.2"))
collect()
b2 = recon("999.2")
tc = tick_min()
B["tl"].append(tl(13, tc * 1000 + 7, cash="12", fee="0.55", side="Sell", size="0", px="2.2", oid="cC"))
B["cp"].append(cp("cC", tc * 1000 + 9, "10.65"))
collect()
b3 = recon("1010.65")
fl = lines("futpnl")
chk(fl == [(ta, Decimal("-0.6")), (tf, Decimal("-0.2")), (tc, Decimal("11.45"))], "C1 선물 줄 = 진입 수수료(진입 시각)·펀딩(정산 시각)·청산(실현 − 청산 수수료)", fl)
rl = [x for x in lines("recon") if x[0] > b0]
chk(not rl, "C2 대사 보정 줄 없음(나머지 0 — 종전은 수수료·펀딩이 음수 정정 → 청산 때 되돌림)", rl)
chk(total() == Decimal("1010.65"), "C3 원장 = 실잔고 1010.65", total())
collect()
recon("1010.65")
chk(lines("futpnl") == fl and total() == Decimal("1010.65"), "C4 다시 수집·대사 = 무변(멱등)", lines("futpnl"))

T.finish()
sys.exit(1 if T.FAILS else 0)
