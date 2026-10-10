#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import copy
import json
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import common

json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import histcurve
import web
import xparts

chk = T.chk
S = common.STATE_DIR
open(os.path.join(S, "backfill_done"), "w").write("1")
KST = timezone(timedelta(hours=9))
FX = 1400.0
TODAY = datetime(2026, 10, 10, tzinfo=KST)
NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=KST).timestamp()


def E(m, d, h=23, mi=59, s=59):
    return datetime(2026, m, d, h, mi, s, tzinfo=KST).timestamp()


def iso(m, d):
    return "2026-%02d-%02d" % (m, d)


def days_back(n):
    return (TODAY - timedelta(days=n)).strftime("%Y-%m-%d")


class FakeSpot:
    rate = FX
    fx_basis = FX

    def price(self, sym):
        return None


class FakePx:
    def fx_at(self, ms):
        return FX

    def candle_usd(self, sym, ms):
        return None

    def flush(self):
        pass


def unit_builder():
    for p9 in (web.DAILY_PATH, web.DAILY_PX_PATH, os.path.join(S, common.HIST_DIRTY)):
        if os.path.exists(p9):
            os.remove(p9)
    b = object.__new__(web.StateBuilder)
    b.daily = {"_v": web.DAILY_V, "_risk_rev": ""}
    b.daily_px = {"_v": 1}
    b._daily_seed = {}
    b._upbit_krw_tl = None
    b.spot = FakeSpot()
    b.px = FakePx()
    return b


def mkx(now_ts):
    return {"ub": 0.0, "fiat": 0.0, "lp": 0.0, "ubs": {}, "ub_tl": {}, "krw_up": 0.0, "krw_other": 0.0, "rate": FX, "krw_up_tl": None,
            "xsrc": {"now": {"ts": now_ts, "ku": 0.0, "kb": 0.0, "ub": {}, "rest": 0.0},
                     "base": {"ku": [0.0, now_ts], "kb": [0.0, now_ts]}, "tl": {"ku": [], "kb": []}, "first": {}}}


XV = {"v": xparts.GEN, "p": {"ku": [0.0, "snap"], "kb": [0.0, "snap"], "ub": [{}, "snap"], "rest": [0.0, "snap"]}, "fx": FX, "how": "live"}


def pin_all(b, n=46):
    for i9 in range(1, n):
        b.daily_px[days_back(i9)] = {"p": {"2": 2.0}, "k": {"2": "live"}, "xv": copy.deepcopy(XV)}


def mkG(late_ts, late_q=50000, tkn=False):
    g1 = {"gid": 1, "sym": "USDC", "is_stable": True, "qty_timeline": [(int(E(7, 1)), Decimal(100000)), (int(late_ts), Decimal(late_q))]}
    G = {1: g1}
    if tkn:
        G[2] = {"gid": 2, "sym": "TKN", "is_stable": False, "qty_timeline": [(int(E(7, 1)), Decimal(1000))]}
    return G


def hold(late_q=50000, tkn=False):
    h9 = {1: Decimal(100000 + late_q)}
    if tkn:
        h9[2] = Decimal(1000)
    return h9


def run(b, G, marks, now_ts=NOW, hold_q=None, pend=(), tkn=False, nokw=False, ov=None):
    kw = {} if nokw else {"hist_late": copy.deepcopy(marks)}
    return b._daily_series(G, TODAY, dict(ov or {}), {2: 2.0}, ca_gids={2}, ex_gids=set(), skip_gids=set(), pending_gids=set(pend),
                           hold_qty=dict(hold_q or hold(tkn=tkn)), extra=copy.deepcopy(mkx(now_ts)), extra_ok=True, now_ts=now_ts, **kw)


def vals(ser):
    return {r["date"]: r["val"] for r in ser}


def close(a, b9, tol=0.01):
    return a is not None and b9 is not None and abs(float(a) - float(b9)) < tol


def frozen(b, n=46, val=100000.0, g=None, extra_g=None):
    for i9 in range(1, n):
        g9 = dict(g or {"1": val})
        if extra_g:
            g9.update(extra_g)
        b.daily[days_back(i9)] = {"val": float(val + sum(v for k, v in (extra_g or {}).items())), "usdt": FX, "kimp": None, "g": g9, "x": 0.0,
                                  "src": "calc", "st": "1", "xraw": 0.0}
    save(b)


def save(b):
    json.dump(b.daily, open(web.DAILY_PATH, "w"))


def dv(b, k):
    return (b.daily.get(k) or {}).get("val")


def mk(i, day, t1, t0=None):
    return [int(i), day, int(t0 if t0 is not None else t1), int(t1)]


b = unit_builder()
pin_all(b)
frozen(b)
TL = E(10, 5, 12, 0, 0)
G1 = mkG(TL)
ID1 = int((NOW - 400) * 1000)
try:
    run(b, G1, [mk(ID1, iso(10, 5), NOW - 400)])
    has_kw = True
except TypeError as e:
    has_kw = False
    chk(False, "W0 _daily_series 가 늦은 원장 행 표식(hist_late)을 받음", repr(e))
if not has_kw:
    T.finish()

b = unit_builder()
pin_all(b)
frozen(b)
json.dump(b.daily, open(web.DAILY_PATH, "w"))
busy = [mk(ID1, iso(10, 5), NOW - 60, NOW - 400)]
s0 = vals(run(b, G1, busy))
chk(all(close(s0.get("10-%02d" % d9), 100000) for d9 in range(5, 10)), "W1 표식이 붐비면(마지막 활동 300초 안) 아직 기다림 — 동결 값 그대로",
    {d9: s0.get("10-%02d" % d9) for d9 in range(4, 10)})
M1 = [mk(ID1, iso(10, 5), NOW - 400)]
s1 = vals(run(b, G1, M1))
chk(all(close(s1.get("10-%02d" % d9), 150000) for d9 in range(5, 10)) and close(s1.get("10-10"), 150000),
    "W1 조용해지면 사건 날(10/5)~어제 = 150,000 · 오늘 150,000(계단 없음)", {d9: s1.get("10-%02d" % d9) for d9 in range(4, 11)})
chk(all(close(s1.get(d9), 100000) for d9 in ("10-04", "10-01", "09-20")), "W1 사건 전 날 = 그대로 100,000", (s1.get("10-04"), s1.get("10-01"), s1.get("09-20")))
chk(all((b.daily.get(iso(10, d9)) or {}).get("hq") == ID1 for d9 in range(5, 10)) and "hq" not in (b.daily.get(iso(10, 4)) or {}),
    "W1 다시 굳힌 날 지문 hq = 표식 id · 사건 전 날은 손 안 댐", {d9: (b.daily.get(iso(10, d9)) or {}).get("hq") for d9 in range(3, 10)})
chk(all((b.daily_px.get(iso(10, d9)) or {}).get("xv") == XV and (b.daily_px.get(iso(10, d9)) or {}).get("p") == {"2": 2.0} for d9 in range(5, 10))
    and all((b.daily.get(iso(10, d9)) or {}).get("usdt") == FX for d9 in range(5, 10)),
    "W1 그날 가격·원장 밖 금액 구성요소(daily_px)·환율 = 보존(수량만 다시)", b.daily_px.get(iso(10, 6)))
fl = vals(run(b, G1, M1, NOW + 60))
pnl = {d9: round(fl["10-%02d" % d9] - fl["10-%02d" % (d9 - 1)] - (50000 if d9 == 5 else 0), 2) for d9 in range(5, 11)}
chk(all(abs(v) < 0.01 for v in pnl.values()), "W1 손익 쌍(사건 날 −50,000 · 따라잡은 날 +50,000) 사라짐 — 날별 (값 변화 − 순유입) = 0", pnl)

b.daily[iso(10, 7)]["val"] = 150001.0
json.dump(b.daily, open(web.DAILY_PATH, "w"))
s2 = vals(run(b, G1, M1, NOW + 120))
chk(close(s2.get("10-07"), 150001), "W2 두 번째 빌드 = 다시 계산 없음(같은 날 반복 없음)", s2.get("10-07"))
G2 = {1: dict(G1[1], qty_timeline=G1[1]["qty_timeline"] + [(int(E(10, 8, 9, 0, 0)), Decimal(7000))])}
ID2 = ID1 + 5000
for d9 in (8, 9):
    b.daily[iso(10, d9)]["val"] = 1.0
M2 = M1 + [mk(ID2, iso(10, 8), NOW - 400)]
s2b = vals(run(b, G2, M2, NOW + 180, hold_q={1: Decimal(157000)}))
chk(close(s2b.get("10-08"), 157000) and close(s2b.get("10-09"), 157000) and close(s2b.get("10-07"), 150001),
    "W2 새 표식(10/8) = 그 날부터만 다시(10/7 은 손 안 댐)", (s2b.get("10-07"), s2b.get("10-08"), s2b.get("10-09")))
ID3, ID4 = ID2 + 5000, ID2 + 9000
b.daily[iso(10, 6)]["val"] = 2.0
b.daily[iso(10, 9)]["val"] = 3.0
G3 = {1: dict(G2[1], qty_timeline=G2[1]["qty_timeline"] + [(int(E(10, 6, 9, 0, 0)), Decimal(1000)), (int(E(10, 9, 9, 0, 0)), Decimal(500))])}
M3 = M2 + [mk(ID3, iso(10, 6), NOW + 200 - web.HL_MAXWAIT_S - 100, NOW + 200 - web.HL_MAXWAIT_S - 100), mk(ID4, iso(10, 9), NOW + 190, NOW + 150)]
s2c = vals(run(b, G3, M3, NOW + 200, hold_q={1: Decimal(158500)}))
chk(close(s2c.get("10-06"), 151000) and close(s2c.get("10-09"), 158500) and (b.daily.get(iso(10, 6)) or {}).get("hq") == ID4,
    "W2 1시간 묵은 표식(10/6)은 붐벼도 처리 — 그 날부터 다시(같은 빌드 원장 = 붐비는 표식 몫도 포함 → hq = 본 최대 id)",
    (s2c.get("10-06"), s2c.get("10-09"), (b.daily.get(iso(10, 6)) or {}).get("hq")))

b = unit_builder()
pin_all(b)
frozen(b)
b.daily.pop(iso(10, 9))
save(b)
sn9 = {"date": iso(10, 9), "ts": E(10, 9, 23, 58, 0), "val": 100000.0, "usdt": FX, "kimp": None, "g": {"1": 100000.0}, "x": 0.0, "defer": False,
       "p": {}, "xv": {"v": 1, "p": {"kb": [0.0, "snap"], "rest": [0.0, "snap"]}, "fx": FX, "ts": int(E(10, 9, 23, 58, 0))}}
b.daily["_live_ok"] = dict(sn9)
b.daily["_live"] = dict(sn9)
G9 = mkG(E(10, 9, 23, 50, 0))
M9 = [mk(ID1, iso(10, 9), NOW - 60)]
s3 = vals(run(b, G9, M9))
chk(close(s3.get("10-09"), 150000) and (b.daily.get(iso(10, 9)) or {}).get("src") != "live" and (b.daily.get(iso(10, 9)) or {}).get("hq") == ID1,
    "W3 표식을 못 본 어제 마감 스냅숏 = 마감 재료로 안 씀 → 계산 150,000(종전이면 100,000 으로 굳음)", (s3.get("10-09"), b.daily.get(iso(10, 9))))
b = unit_builder()
pin_all(b)
frozen(b)
b.daily.pop(iso(10, 9))
save(b)
sn9b = dict(sn9, val=150000.0, g={"1": 150000.0}, hq=ID1)
b.daily["_live_ok"] = dict(sn9b)
b.daily["_live"] = dict(sn9b)
run(b, G9, M9)
chk((b.daily.get(iso(10, 9)) or {}).get("src") == "live" and close(dv(b, iso(10, 9)), 150000),
    "W3 표식을 본 스냅숏(hq ≥ id) = 종전대로 실시간 마감(live)", b.daily.get(iso(10, 9)))
chk((b.daily.get("_live") or {}).get("hq") == ID1, "W3 오늘 실시간 스냅숏도 본 표식 id(hq)를 지님", (b.daily.get("_live") or {}).get("hq"))

b = unit_builder()
pin_all(b)
frozen(b, extra_g={"2": 2000.0})
b.daily_px[iso(10, 6)] = {"p": {}, "k": {}, "xv": copy.deepcopy(XV)}
json.dump(b.daily, open(web.DAILY_PATH, "w"))
G4 = mkG(TL, tkn=True)
s4 = vals(run(b, G4, M1, pend={2}, tkn=True))
e46 = b.daily.get(iso(10, 6)) or {}
chk(close(e46.get("val"), 102000) and "hq" not in e46 and close(dv(b, iso(10, 7)), 152000),
    "W4 시세 대기인 날(10/6) = 옛 항목 그대로·지문 없음(다음 빌드에 다시) · 다른 날은 다시 계산", (e46, dv(b, iso(10, 7))))
chk(iso(10, 6) in (b.__dict__.get("_daily_nf") or set()), "W4 유예 날은 장기 곡선에 확정으로 안 넘김(nf)", b.__dict__.get("_daily_nf"))
s4b = vals(run(b, G4, M1, NOW + 600, tkn=True))
e46b = b.daily.get(iso(10, 6)) or {}
chk(close(e46b.get("val"), 152000) and e46b.get("hq") == ID1, "W4 시세가 오면(25분 뒤라도) 그 날도 다시 계산·지문 저장", e46b)

b = unit_builder()
pin_all(b)
frozen(b)
run(b, G1, M1)
b.daily[iso(10, 6)] = {"val": 100000.0, "usdt": FX, "kimp": None, "g": {"1": 100000.0}, "x": 0.0, "src": "calc", "st": "1", "xraw": 0.0}
json.dump(b.daily, open(web.DAILY_PATH, "w"))
s5 = vals(run(b, G1, M1, NOW + 60))
chk(close(s5.get("10-06"), 150000) and (b.daily.get(iso(10, 6)) or {}).get("hq") == ID1, "W5 롤백 중 옛 코드가 다시 굳힌 날(hq 없음) = 돌아오면 남은 표식만큼 1회 다시",
    (s5.get("10-06"), b.daily.get(iso(10, 6))))
for kw9, lab9 in ((dict(marks=[]), "표식 없음"), (dict(marks=None, nokw=True), "옛 호출(인자 없음)")):
    b = unit_builder()
    pin_all(b)
    frozen(b)
    s9 = vals(run(b, G1, kw9["marks"], nokw=kw9.get("nokw", False)))
    chk(all(close(s9.get("10-%02d" % d9), 100000) for d9 in range(5, 10)) and not any("hq" in (b.daily.get(iso(10, d9)) or {}) for d9 in range(1, 10)),
        f"W5 {lab9} = 종전 그대로(동결 값·지문 무변)", {d9: s9.get("10-%02d" % d9) for d9 in range(5, 10)})

b2 = unit_builder()
pin_all(b2)
frozen(b2)
run(b2, mkG(E(10, 5, 12, 0, 0)), [mk(ID1, iso(10, 5), NOW - 400)])
chk(not os.path.exists(os.path.join(S, common.HIST_DIRTY)) and (b2.daily_px.get("_hlf") or {}).get("id") == ID1,
    "W6 30일 창 안 표식 = 장기 곡선 표식 안 넘김(창 안은 30일 곡선 행을 받음) · 커서만", b2.daily_px.get("_hlf"))
b = unit_builder()
pin_all(b)
frozen(b)
T45 = datetime(2026, 8, 27, 12, 0, 0, tzinfo=KST).timestamp()
G6 = mkG(T45)
M6 = [mk(ID1, iso(8, 27), NOW - 400)]
run(b, G6, M6)
out9 = {k9: dv(b, k9) for k9 in (iso(8, 26), iso(8, 27), iso(9, 5), iso(9, 10), iso(9, 11), iso(10, 9))}
chk(close(out9[iso(8, 26)], 100000) and all(close(out9[k9], 150000) for k9 in (iso(8, 27), iso(9, 5), iso(9, 10), iso(9, 11), iso(10, 9))),
    "W6 45일 전 입금 = 30일 창 밖(일별 가격 보관 안) 동결 항목도 사건 날부터 150,000 · 그 전 100,000", out9)
hd9 = common.read_json(os.path.join(S, common.HIST_DIRTY), None)
chk(isinstance(hd9, dict) and hd9.get("from") == iso(8, 27) and len(hd9.get("marks") or []) == 1 and (b.daily_px.get("_hlf") or {}).get("id") == ID1,
    "W6 30일 창 밖 날 = 장기 곡선 다시 계산 표식(hist_dirty.json) 넘김 · 커서 daily_px['_hlf']", (hd9, b.daily_px.get("_hlf")))
run(b, G6, M6, NOW + 60)
hd9b = common.read_json(os.path.join(S, common.HIST_DIRTY), None)
chk(len((hd9b or {}).get("marks") or []) == 1, "W6 두 번째 빌드 = 다시 넘기지 않음(커서)", hd9b)
pth9, pxp9 = os.path.join(S, "chH.json"), os.path.join(S, "chH_px.json")
ser6 = run(b, G6, M6, NOW + 120)


def hrow(v, kind="hc"):
    return [float(v), None, 0, kind, 0]


xp0 = {"ku": [0.0, "snap"], "kb": [0.0, "snap"], "ub": [{}, "snap"], "rest": [0.0, "snap"]}
out_days = [iso(8, d9) for d9 in range(20, 32)] + [iso(9, d9) for d9 in range(1, 11)]
pre9 = {"_v": histcurve.HIST_V, "d": {k9: hrow(100000) for k9 in out_days},
        "s": {k9: [100000.0, 0.0, 0.0, 0, 0.0, histcurve.LQ_V, ""] for k9 in out_days},
        "x": {k9: {"p": xp0, "fx": FX, "cut": 0.0, "x": 0.0, "xc": 0.0, "uat": histcurve.day_end(k9) - 1} for k9 in out_days},
        "meta": {"pending": False, "flow_pending": False}}
common.atomic_write_json(pth9, pre9)
HH = histcurve.HistCurve(path=pth9, px_path=pxp9)
kH = histcurve.make_kit("2026-10-10", G6, hold(), set(), set(), {}, set(), {}, {}, {}, [], mkx(NOW), ser6, b.daily,
                        xkit=copy.deepcopy(b.__dict__.get("_x_kit")))
kH["made"] = time.time() + 2 * histcurve.DIRTY_MARGIN_S
daysH = histcurve.days_between("2026-07-01", "2026-10-10")
HH.px["fx"] = {"lo": "2026-07-01", "hi": "2026-10-10", "st": "ok", "p": {d9: FX for d9 in daysH}}
repH = HH.run_once(kH, cap=0, now=NOW + 200)
dH = HH.st.get("d") or {}
chk(repH.get("dirty_from") == iso(8, 27) and close((dH.get(iso(8, 27)) or [None])[0], 150000) and close((dH.get(iso(9, 5)) or [None])[0], 150000)
    and close((dH.get(iso(8, 26)) or [None])[0], 100000) and close((dH.get(iso(8, 20)) or [None])[0], 100000),
    "W6 장기 곡선 창 밖 행 = 사건 날(8/27)부터 150,000 · 그 전(8/20·8/26) 100,000 그대로",
    (repH.get("dirty_from"), dH.get(iso(8, 26)), dH.get(iso(8, 27)), dH.get(iso(9, 5))))
chk(not os.path.exists(os.path.join(S, common.HIST_DIRTY)), "W6 장기 곡선은 가져간 표식만 지움(원장 표식·30일 곡선 지문과 따로)", common.read_json(os.path.join(S, common.HIST_DIRTY), None))
b7 = unit_builder()
pin_all(b7)
os.remove(os.path.join(S, "backfill_done"))
s7 = vals(run(b7, G6, M6))
chk(close(s7.get("09-20"), 150000) and not os.path.exists(os.path.join(S, common.HIST_DIRTY)) and "_hlf" not in b7.daily_px and not any(
    "hq" in v for k, v in b7.daily.items() if not k.startswith("_") and isinstance(v, dict)),
    "W7 기초 대사 전(백필 완료 표식 없음) = 늘 지금 원장으로 계산 · 장기 곡선 넘김·지문 없음", (s7.get("09-20"), b7.daily_px.get("_hlf")))
open(os.path.join(S, "backfill_done"), "w").write("1")

b8 = unit_builder()
pin_all(b8)
frozen(b8, extra_g={"2": 2000.0})
G8 = mkG(T45, tkn=True)
H8 = hold(tkn=True)
OV8 = {2: 10.0}
ser8 = run(b8, G8, M6, ov=OV8, tkn=True)
chk(close(dv(b8, iso(9, 5)), 152000) and close(dv(b8, iso(8, 26)), 102000), "W8 준비: 일별 동결 항목(창 밖 9/5) = 152,000(고정가 $2 그대로) · 사건 전 8/26 = 102,000",
    (dv(b8, iso(9, 5)), dv(b8, iso(8, 26))))
RB = 10000.0
dc_days = [d9 for d9 in out_days if d9 >= iso(8, 26)]
hc_days = [d9 for d9 in out_days if d9 < iso(8, 26)]
pth8, pxp8 = os.path.join(S, "chW8.json"), os.path.join(S, "chW8_px.json")
pre8 = {"_v": histcurve.HIST_V, "d": dict({k9: hrow(102000) for k9 in hc_days}, **{k9: [102000.0 + RB, None, 0, "dc", 0] for k9 in dc_days}),
        "s": {k9: [102000.0, 0.0, 0.0, 0, 0.0, histcurve.LQ_V, ""] for k9 in hc_days},
        "x": {k9: {"p": xp0, "fx": FX, "cut": 0.0, "x": 0.0, "xc": 0.0, "uat": histcurve.day_end(k9) - 1} for k9 in hc_days},
        "dqd": {k9: "" for k9 in dc_days}, "meta": {"pending": False, "flow_pending": False}}
common.atomic_write_json(pth8, pre8)
H8c = histcurve.HistCurve(path=pth8, px_path=pxp8)
k8 = histcurve.make_kit("2026-10-10", G8, H8, set(), set(), {}, set(), OV8, {2: 10.0}, {}, [], mkx(NOW), ser8, b8.daily,
                        xkit=copy.deepcopy(b8.__dict__.get("_x_kit")), rb_days={k9: RB for k9 in dc_days})
k8["made"] = time.time() + 2 * histcurve.DIRTY_MARGIN_S
H8c.px["fx"] = {"lo": "2026-07-01", "hi": "2026-10-10", "st": "ok", "p": {d9: FX for d9 in daysH}}
rep8 = H8c.run_once(k8, cap=0, now=NOW + 300)
d8 = H8c.st.get("d") or {}
after8 = {k9: d8.get(k9) for k9 in (iso(8, 26), iso(8, 27), iso(9, 5), iso(9, 10))}
chk(rep8.get("dirty_from") == iso(8, 27) and all(close((d8.get(k9) or [None])[0], 162000) and (d8.get(k9) or [None] * 4)[3] == "dc"
                                                  for k9 in (iso(8, 27), iso(9, 5), iso(9, 10))),
    "W8 사건 뒤 창 밖 dc 행 = 30일 곡선이 고친 동결 값 162,000(USDC 150,000 + TKN 1,000 × 그날 고정가 $2 + Rabby 10,000) · 행 종류 dc 유지",
    (rep8.get("dirty_from"), after8))
chk(close((d8.get(iso(8, 26)) or [None])[0], 112000) and all(close((d8.get(k9) or [None])[0], 102000) and (d8.get(k9) or [None] * 4)[3] == "hc" for k9 in hc_days),
    "W8 사건 전 dc 행(8/26 112,000)·동결 항목 없는 더 옛 hc 행(8/20~8/25 102,000) = 그대로", {k9: d8.get(k9) for k9 in [iso(8, 26)] + hc_days[:2]})
b8.daily[iso(9, 5)]["val"] = 152500.0
k8b = histcurve.make_kit("2026-10-10", G8, H8, set(), set(), {}, set(), OV8, {2: 10.0}, {}, [], mkx(NOW), ser8, b8.daily,
                         xkit=copy.deepcopy(b8.__dict__.get("_x_kit")), rb_days={k9: RB for k9 in dc_days})
H8c.run_once(k8b, cap=0, now=NOW + 400)
chk(close(((H8c.st.get("d") or {}).get(iso(9, 5)) or [None])[0], 162500), "W8 30일 곡선이 나중에 굳힌 값도 다음 실행에 dc 행으로 받음(표식 없이 — 유예 날 수렴)",
    (H8c.st.get("d") or {}).get(iso(9, 5)))

import rabby
RBF = iso(9, 5)
json.dump({"first": RBF, "d": {RBF: RB}, "wf": {"0xw": RBF}, "n": {RBF: RB}}, open(os.path.join(S, rabby.DAILY_NAME), "w"))
rb9d = rabby.day_values(rabby.load_state(os.path.join(S, rabby.DAILY_NAME)), dc_days, "2026-10-10", 0.0)
pth9w, pxp9w = os.path.join(S, "chW9.json"), os.path.join(S, "chW9_px.json")
LBL = "Rabby 기준 첫 반영(봇 미추적 보유)"
pre9w = copy.deepcopy(pre8)
pre9w["d"] = dict(pre9w["d"], **{k9: [102000.0 + rb9d.get(k9, 0.0), None, 0, "dc", 0] for k9 in dc_days})
pre9w["f"] = {k9: [round(rb9d.get(k9, 0.0), 2) if k9 == RBF else 0.0, FX, [[LBL, RB]] if k9 == RBF else None, "dc"] for k9 in dc_days}
pre9w["fv"] = histcurve.FLOW_V
common.atomic_write_json(pth9w, pre9w)
common.mark_hist_dirty(int(T45))
H9 = histcurve.HistCurve(path=pth9w, px_path=pxp9w)


def led_flows(fk, days, dpx, fx_day):
    return {k9: (50000.0, [["외부 입금 USDC", 50000.0]]) for k9 in days if k9 == iso(8, 27)}


H9.flow_fn = led_flows
k9w = histcurve.make_kit("2026-10-10", G8, H8, set(), set(), {}, set(), OV8, {2: 10.0}, {}, [], mkx(NOW), ser8, b8.daily,
                         xkit=copy.deepcopy(b8.__dict__.get("_x_kit")), rb_days=rb9d, flow_kit={"dpx_dc": {}})
k9w["made"] = time.time() + 2 * histcurve.DIRTY_MARGIN_S
H9.px["fx"] = H8c.px["fx"]
rep9 = H9.run_once(k9w, cap=0, now=NOW + 500)
f9w = H9.st.get("f") or {}
chk(rep9.get("dirty_from") == iso(8, 27) and close((f9w.get(iso(8, 27)) or [None])[0], 50000) and close((f9w.get(RBF) or [None])[0], RB)
    and LBL in json.dumps(f9w.get(RBF), ensure_ascii=False) and close((f9w.get(iso(9, 6)) or [None])[0], 0),
    "W9 보존한 dc 행 순유입 다시 = 늦은 입금 날 50,000 · Rabby 첫 반영 날 10,000(기준 변경 — 시장 변동으로 안 보임) · 다른 날 0",
    {k9: f9w.get(k9) for k9 in (iso(8, 27), RBF, iso(9, 6))})
T.finish()
