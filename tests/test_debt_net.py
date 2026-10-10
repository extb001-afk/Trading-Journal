#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import common
import core
import db as dbm
import histcurve
import netpace
import web

assert T.TMP in common.STATE_DIR
chk = T.chk
core.dm = lambda *a, **k: None
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
KST = timezone(timedelta(hours=9))
NOW = int(time.time())
DAY = 86400
E8 = 10 ** 8
C = core.Core(common.load_config())
C._quote_usd = lambda q, ts: Decimal(1)
SEQ = {"n": 0}


def post(ex, t, sym, qty, ev="EXF_DEPOSIT", lk="move_in", sid=None):
    aid = C._exf_asset(ex, sym)
    qb = int(Decimal(str(qty)) * E8)
    SEQ["n"] += 1
    C.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
                   " leg_kind, event, classifier_ver) VALUES ('exchange',?,?,0,?,?,?,?,?,NULL,?,?,?)",
                   (f"{ex}:{'trade' if ev.startswith('EXF_B') or ev.startswith('EXF_S') else 'deposit'}", sid or f"s{SEQ['n']}", int(t), aid,
                    f"exchange:{ex}", str(qb), repr(abs(float(qty))) if lk in ("acq", "disp") else None, lk, ev, core.CLASSIFIER_VER))
    C._bump_position(aid, qb, f"exchange:{ex}")


def move(t, sym, qty, src, dst):
    post(src, t, sym, -qty, "EXF_WITHDRAW", "move_out")
    post(dst, t + 600, sym, qty, "EXF_DEPOSIT", "move_in")


T_DEP = NOW - 20 * DAY
T_BUY = NOW - 10 * DAY
post("bybit", T_DEP, "USDT", 10000)
post("bybit", T_BUY, "USDT", -15000, "EXF_SELL", "disp")
post("bybit", T_BUY, "BTC", "0.25", "EXF_BUY", "acq")
move(T_BUY, "USDT", 5000, "gate", "kucoin")
post("okx", T_DEP, "ETH", 2)
move(T_BUY, "USDT", 200, "okx", "binance")
post("hyperliquid", T_DEP, "USDC", 1000)
post("hyperliquid", T_BUY, "USDC", -1700, "EXF_WITHDRAW", "move_out")
post("bybit", T_BUY + 600, "USDT", 700)
post("bybit", T_DEP, "ZZZ", "5")
post("bybit", T_BUY, "ZZZ", "-9.99", "EXF_WITHDRAW", "move_out")
post("binance", T_DEP, "NNN", "0.3")
post("binance", T_BUY, "NNN", "-1.3", "EXF_WITHDRAW", "move_out")
C.conn.commit()
for nm, q in (("QQQ", -3), ("QQQ#2", -4)):
    C.conn.execute("INSERT INTO asset_groups (name) VALUES (?)", (nm,))
    g9 = C.conn.execute("SELECT group_id FROM asset_groups WHERE name=?", (nm,)).fetchone()[0]
    C.conn.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed, group_id) VALUES ('exchange_currency',NULL,?,?,8,1,?)",
                   (f"bybit:QQQ{'' if nm == 'QQQ' else '2'}", "QQQ", g9))
    a9 = C.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    SEQ["n"] += 1
    C.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
                   " leg_kind, event, classifier_ver) VALUES ('exchange','bybit:deposit',?,0,?,?,'exchange:bybit',?,NULL,NULL,'move_out','EXF_WITHDRAW',?)",
                   (f"s{SEQ['n']}", T_BUY, a9, str(q * E8), core.CLASSIFIER_VER))
    C._bump_position(a9, q * E8, "exchange:bybit")
C.conn.commit()

BAL = {
    "bybit": {"balances": {"BTC": 0.25, "USDT": 700.0}, "debts": {"USDT": -5000.0, "QQQ": -5.0}},
    "gate": {"balances": {}, "debts": {"USDT": -5000.0}},
    "kucoin": {"balances": {"USDT": 5000.0}, "debts": {}},
    "okx": {"balances": {"ETH": 2.0, "USDT": 2800.0}, "debts": {"USDT": -3000.0},
            "loans": [{"src": "loan", "label": "담보대출", "debt": {"USDT": 3000.0}, "principal": {"USDT": 3000.0}, "collateral": {"ETH": 2.0},
                       "since": T_DEP}]},
    "binance": {"balances": {"USDT": 200.0}, "debts": {"NNN": -0.6}},
}


def write_bal(bal=BAL, ts=None):
    for ex, d in bal.items():
        common.atomic_write_json(os.path.join(common.STATE_DIR, f"exf_balances_{ex}.json"), dict(d, ts=int(ts or time.time()), sources=["spot"]))


write_bal(ts=NOW - 30)
st = {ex: {"seen": {}, "backfilled_until": NOW, "fills": {"backfilled_until": NOW}} for ex in ("bybit", "gate", "kucoin", "okx", "binance")}
common.atomic_write_json(os.path.join(common.STATE_DIR, "exf_state.json"), st)
n_adj0 = C.conn.execute("SELECT COUNT(*) FROM postings WHERE event='EXF_ADJUST'").fetchone()[0]
C._drain_at = NOW + 5
C._last_exfrecon = 0
C.exf_recon_pass({"ex"})
adj = C.conn.execute("SELECT a.symbol, p.location, p.qty_base FROM postings p JOIN assets a USING(asset_id) WHERE p.event='EXF_ADJUST'").fetchall()
adj_by = {(r[1], r[0]): Decimal(int(r[2])) / E8 for r in adj}
chk(all(k[1] in ("ZZZ", "NNN", "QQQ") for k in adj_by),
    "core 대사: 마진·대출 칸(USDT·BTC·ETH)은 원장 = 잔고 + 부채라 정정 없음(바이빗 USDT −5,000 · 게이트 −5,000 · OKX −200 그대로)", [n_adj0, adj_by])
if adj_by:
    for r in C.conn.execute("SELECT posting_id, asset_id, location, qty_base FROM postings WHERE event='EXF_ADJUST'").fetchall():
        C._bump_position(r[1], -int(r[3]), r[2])
    C.conn.execute("DELETE FROM postings WHERE event='EXF_ADJUST'")
    C.conn.commit()
C.conn.close()

px = {"BTC": 60000.0, "ETH": 3000.0, "NNN": 10.0, "QQQ": 2.0, "ZZZ": 1.0}
json.dump({"usd": px, "usd_ts": {k: NOW for k in px}, "rate": 1400.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": 1400.0, "ex_usd": {f"{e}:{k}": v for k, v in px.items() for e in ("bybit", "binance", "okx", "gate", "kucoin")},
           "ex_ts": {f"{e}:{k}": NOW for k in px for e in ("bybit", "binance", "okx", "gate", "kucoin")}}, open(web.SPOT_PATH, "w"))
web.pricing.PxCache.candle_usd = lambda self, sym, ms: None
web.pricing.PxCache.fx_at = lambda self, ms: 1400.0
web.pricing._gj = lambda url, timeout=10.0: None
DCP = {}


def _dc_lookup(spec, iso, now=None, w=0.0, ask=True, old=False):
    for k9, v9 in DCP.items():
        if k9 in str(spec):
            return v9, "ok"
    return None, "pending"


histcurve.DAYCLOSE.lookup = _dc_lookup
histcurve.DAYCLOSE.lookup._tj_test_mock = True
common.atomic_write_json(web.PREFS_PATH, {"plans": {}, "ignored": []})
with open(os.path.join(common.STATE_DIR, "backfill_done"), "w") as f0:
    f0.write(str(NOW - 40 * DAY))


def build(b=None, fresh=False):
    if fresh:
        for p9 in (web.DAILY_PATH, web.DAILY_PX_PATH):
            try:
                os.remove(p9)
            except FileNotFoundError:
                pass
    b = b or web.StateBuilder()
    b.skip_gen_check = True
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        return b, b._build(conn)
    finally:
        conn.close()


def tot(f):
    return round(sum(float(x.get("qty") or 0) * float(x.get("price") or 0) for x in (f.get("stables") or []) + (f.get("coins") or []))
                 + sum(float(x.get("krw") or 0) / (float(f.get("rate") or 0) or 1384.0) for x in f.get("fiats") or []), 2)


def rows(f, sym):
    return [x for x in (f.get("stables") or []) + (f.get("coins") or []) if str(x.get("sym") or "").upper() == sym]


def val(f, sym, loc_word=None):
    return round(sum(float(x.get("qty") or 0) * float(x.get("price") or 0) for x in rows(f, sym)
                     if loc_word is None or any(loc_word in str(l9.get("w") or "") for l9 in x.get("locs") or [])), 2)


b, out = build(fresh=True)
f = out["fields"]
EXP = 15000 - 4300 - 5000 + 5000 + 6000 - 200 + 200 - 700 - 6 - 10
chk(abs(tot(f) - EXP) < 0.01, f"T 총자산 = 순자산 ${EXP:,}(종전 = 빌린 몫이 빠져 부풀었다)", [tot(f), EXP])
usdt = sorted((round(float(x["qty"]), 4), [(l9.get("w"), round(float(l9.get("qty") or 0), 4)) for l9 in x.get("locs") or []]) for x in rows(f, "USDT"))
chk(any(q == -4300 for q, _ in usdt) and any(q == -5000 for q, _ in usdt) and any(q == -200 for q, _ in usdt),
    "S1·S2·S3 USDT 행 = 바이빗 −4,300(마진) · 게이트 −5,000(빌려 출금) · OKX −200(대출 3,000 중 잔고를 넘은 몫 — 대출을 또 빼지 않음)", usdt)
chk(all(abs(q - sum(lq for _w, lq in ls)) < 1e-6 for q, ls in usdt), "T 보관처 줄 합 = 행 수량(음수 차입 줄 포함)", usdt)
chk(val(f, "USDC") == -700, "S4 Hyperliquid 현금 음수 −700 = 종전 그대로 한 번", rows(f, "USDC"))
chk(not rows(f, "ZZZ"), "S5 부채 없는 음수(ZZZ) = 종전처럼 보유·총자산 밖", rows(f, "ZZZ"))
chk(val(f, "NNN") == -6.0, "S6 부채보다 큰 음수 = 부채 상한(−0.6 × $10)만 차감", rows(f, "NNN"))
chk(val(f, "QQQ") == -10.0, "S7 같은 거래소·코인 그룹 2개 = 상한 누적(−5 × $2 · 행마다 상한이면 −14)", rows(f, "QQQ"))
nh = f.get("negHoldings") or []
z5 = [n for n in nh if n.get("sym") == "ZZZ"]
n6 = [n for n in nh if n.get("sym") == "NNN" and not n.get("debt")]
chk(z5 and not z5[0].get("debt"), "S5 헬스 재료: 부채 없는 음수 = debt 아님(경고 대상)", z5)
chk(n6 and abs(float(n6[0]["qty"]) + 0.4) < 1e-9, "S6 헬스 재료: 부채를 넘친 0.4 = debt 아님(경고 대상)", n6)
chk(not [n for n in nh if n.get("sym") == "USDT" and not n.get("debt")], "부채 안의 음수 = 헬스 경고 재료 아님(이제 실제로 차감됨)",
    [n for n in nh if n.get("sym") == "USDT" and not n.get("debt")])
q7 = [n for n in nh if n.get("sym") == "QQQ" and not n.get("debt")]
chk(len(q7) == 1 and abs(float(q7[0]["qty"]) + 2) < 1e-9 and q7[0].get("over"), "S7 헬스 재료: 그룹 2개 합 −7 중 부채 5 를 넘친 2 만 경고(한 번)", q7)
ds = f.get("dailySeries") or []
chk(ds and abs(float(ds[-1]["val"]) - tot(f)) < 0.01, "T 오늘 일별값 = 화면 총자산", [ds[-1] if ds else None, tot(f)])
chk(abs(float((f.get("_diag") or {}).get("daily_today_gap_usd") or 0)) < 0.01, "T 정합 점검 차 0", (f.get("_diag") or {}).get("daily_today_gap_usd"))
hs = web._hero_summary(out)
hv = hs.get("total") if isinstance(hs, dict) else None
chk(hv is not None and abs(float(hv) - tot(f)) < 0.01, "T 첫 페인트 요약 총자산 = 화면 총자산", [hv, tot(f)])
xd = f.get("exDebts") or []
chk(any(d.get("kind") == "loan" and abs(float(d["qty"]) + 3000) < 1e-6 for d in xd) and any(abs(float(d.get("usd") or 0) + 5000) < 0.01 for d in xd),
    "T 빌린 돈 줄(exDebts) = 종전 그대로(OKX 담보대출 3,000 · 바이빗 마진 5,000 · 게이트 5,000 …)", xd)
pos = [p for p in (f.get("_positionsAll") or f.get("positions") or []) if p.get("sym") == "NNN"]
chk(all(float(p.get("held") or 0) >= 0 for p in pos), "보유 카드 보유량은 음수로 안 내려감(차입 몫은 보유 아님 — 종전 그대로)", [(p.get("held"), p.get("status")) for p in pos])

dpx = common.read_json(web.DAILY_PX_PATH, {}) or {}
d_after = datetime.fromtimestamp(T_BUY + 2 * DAY, KST).strftime("%Y-%m-%d")
d_before = datetime.fromtimestamp(T_DEP - 2 * DAY, KST).strftime("%Y-%m-%d")
row_a = next((r for r in ds if r.get("date") == d_after[5:]), None)
chk(row_a and abs(float(row_a["val"]) - EXP) < 0.01, "P 차입 뒤 지난날 = 부채 차감 값(오늘과 같은 원장)", [row_a, EXP])
chk(isinstance((dpx.get("_dbt") or {}).get(d_after), dict) and dpx["_dbt"][d_after], "P 그날 부채 기록(daily_px['_dbt']) 고정", (dpx.get("_dbt") or {}).get(d_after))
est_a = float((row_a or {}).get("est") or 0)
chk(abs(est_a - (15000 + 6000 + 6 + 10)) < 0.01, "H1 근사 몫 = 크기 합(BTC 15,000 + ETH 6,000 + 차입 NNN 6 + QQQ 10 — 음수가 근사 표시를 깎지 않음)", row_a)
row_b = next((r for r in ds if r.get("date") == d_before[5:]), None)
chk(row_b is not None and abs(float(row_b["val"]) - 12.99) < 0.01, "P 첫 입금 전 날 = 버린 음수 몫만(12.99 · 종전 = 차입 몫까지 $9,500 넘게)", row_b)
C = core.Core(common.load_config())
T_SELL = NOW - DAY
post("bybit", T_SELL, "BTC", "-0.25", "EXF_SELL", "disp")
post("bybit", T_SELL, "USDT", 15000, "EXF_BUY", "acq")
move(T_SELL, "USDT", 5000, "kucoin", "gate")
C.conn.commit()
C.conn.close()
BAL2 = dict(BAL, bybit={"balances": {"USDT": 10700.0}, "debts": {"QQQ": -5.0}}, gate={"balances": {}, "debts": {}}, kucoin={"balances": {}, "debts": {}})
write_bal(BAL2)
try:
    os.remove(web.DAILY_PATH)
except FileNotFoundError:
    pass
KITS = {}
_offer0 = histcurve.HIST.offer
histcurve.HIST.offer = lambda today_iso, kit_fn, now=None: KITS.update(fn=kit_fn) or False
b2, out2 = build()
histcurve.HIST.offer = _offer0
f2 = out2["fields"]
ds2 = f2.get("dailySeries") or []
row_a2 = next((r for r in ds2 if r.get("date") == d_after[5:]), None)
chk(row_a2 and abs(float(row_a2["val"]) - EXP) < 0.01, "P 갚은 뒤 무효화 재계산 = 차입 중이던 날 그날 부채 기록으로 같은 값", [row_a2, EXP])
chk(abs(float(ds2[-1]["val"]) - tot(f2)) < 0.01 and abs(tot(f2) - EXP) < 0.01, "P 오늘 = 판 돈 10,700 + 나머지(순자산 그대로 $15,984)", [ds2[-1], tot(f2)])
cdb = dbm.open_db(common.DB_PATH, readonly=True)
GID = {a: cdb.execute("SELECT group_id FROM assets WHERE lower(address)=?", (a.lower(),)).fetchone()[0] for a in ("bybit:USDT", "gate:USDT")}
cdb.close()
kit = KITS["fn"]() if KITS.get("fn") else {}
rq = histcurve.rewind(kit, [d_after]) if kit else {}
chk(d_after in (kit.get("dbt") or {}) and abs(((rq.get(GID["bybit:USDT"]) or {}).get(d_after) or 0) + 4300) < 1e-6
    and abs(((rq.get(GID["gate:USDT"]) or {}).get(d_after) or 0) + 5000) < 1e-6,
    "H2 장기 곡선 되감기 = 그날 부채 기록(갚은 뒤에도 바이빗 −4,300 · 게이트 −5,000)", [GID, {g: rq.get(g) for g in GID.values()}, sorted((kit.get("dbt") or {}))[:3]])
kit0 = dict(kit, dbt={k9: v9 for k9, v9 in (kit.get("dbt") or {}).items() if k9 != d_after})
rq0 = histcurve.rewind(kit0, [d_after]) if kit else {}
chk(kit and not (rq0.get(GID["bybit:USDT"]) or {}).get(d_after), "H2 (대조) 그날 기록이 없으면 지금 부채(없음) 기준 = 그 음수 버림(기록 시작 전 날의 한계)", rq0.get(GID["bybit:USDT"]))
dpx2 = common.read_json(web.DAILY_PX_PATH, {}) or {}
dpx2.get("_dbt", {}).pop(d_after, None)
dpx2.setdefault("_dbt", {})["2001-01-02"] = {"1": 1.0}
common.atomic_write_json(web.DAILY_PX_PATH, dpx2)
try:
    os.remove(web.DAILY_PATH)
except FileNotFoundError:
    pass
b2b, out2b = build()
row_a3 = next((r for r in (out2b["fields"].get("dailySeries") or []) if r.get("date") == d_after[5:]), None)
chk(row_a3 and abs(float(row_a3["val"]) - (EXP + 9300)) < 0.01,
    "P (대조 · 감수) 그날 기록이 없으면 지금 부채 기준 = 갚은 차입(바이빗 4,300 · 게이트 5,000)을 버려 그날 +9,300(기록 시작 전 날의 한계)", [row_a3, EXP + 9300])
chk("2001-01-02" in ((common.read_json(web.DAILY_PX_PATH, {}) or {}).get("_dbt") or {}), "H2 오래된 부채 기록 = daily_px 정리(45일)에 안 지워짐(장기 곡선 재료)",
    sorted(((common.read_json(web.DAILY_PX_PATH, {}) or {}).get("_dbt") or {}))[:3])
write_bal()

DCP["NNN"] = 30.0
b5, out5 = build(fresh=True)
r5 = next((r for r in (out5["fields"].get("dailySeries") or []) if r.get("date") == d_after[5:]), None)
chk(r5 and abs(float(r5["val"]) - (EXP - 12)) < 0.01 and abs(float(r5.get("est") or 0) - 21010) < 0.01,
    "H1 ① 처음 계산 = 그날 마감가(NNN −18) · 근사 몫 21,010(NNN 은 근사 아님)", [r5, EXP - 12])
DCP.clear()
b6, out6 = build(fresh=True)
r6 = next((r for r in (out6["fields"].get("dailySeries") or []) if r.get("date") == d_after[5:]), None)
DCP["NNN"] = 30.0
b7, out7 = build()
r7 = next((r for r in (out7["fields"].get("dailySeries") or []) if r.get("date") == d_after[5:]), None)
chk(r6 and abs(float(r6["val"]) - EXP) < 0.01 and r7 and abs(float(r7["val"]) - (EXP - 12)) < 0.01 and abs(float(r7.get("est") or 0) - 21010) < 0.01,
    "H1 ② 근사(NNN −6)로 동결 → 그날 마감가를 받으면 −18 로 고침 · 근사 몫 21,016 → 21,010", [r6, r7])
DCP.clear()

b3, out3 = build(fresh=True)
lv = dict(b3.daily.get("_live") or {})
chk(isinstance(lv.get("dbt"), dict) and lv.get("dbt"), "스냅숏(_live)에 부채 기록", lv.get("dbt"))
yd = (datetime.fromtimestamp(NOW, KST) - timedelta(days=1)).strftime("%Y-%m-%d")
end_y = datetime.strptime(yd, "%Y-%m-%d").replace(tzinfo=KST, hour=23, minute=59, second=0).timestamp()
lv.update(date=yd, ts=end_y - 30, defer=False)
b3.daily.pop(yd, None)
b3.daily_px.pop(yd, None)
(b3.daily_px.get("_dbt") or {}).pop(yd, None)
b3.daily["_live"] = lv
b3.daily.pop("_live_ok", None)
b3, out4 = build(b3)
c_y = b3.daily.get(yd) or {}
chk(c_y.get("src") == "live" and lv.get("dbt") and (b3.daily_px.get("_dbt") or {}).get(yd) == lv.get("dbt") and abs(float(c_y.get("val") or 0) - float(lv.get("val") or 0)) < 0.01,
    "마감 스냅숏으로 동결 = 그 값 그대로 · 부채 기록이 daily_px['_dbt'] 로", [c_y.get("src"), c_y.get("val"), lv.get("val"), (b3.daily_px.get("_dbt") or {}).get(yd)])

T.finish()
sys.exit(1 if T.FAILS else 0)
