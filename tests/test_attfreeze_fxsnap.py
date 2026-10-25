#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from decimal import Decimal  # noqa: E402
from types import SimpleNamespace  # noqa: E402

json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import attfreeze  # noqa: E402
import db as dbm  # noqa: E402
import histcurve  # noqa: E402
import paths  # noqa: E402
import pricing  # noqa: E402
import statefile  # noqa: E402
import web  # noqa: E402

chk = T.chk
KST = timezone(timedelta(hours=9))
TOL = 0.011
CONN = dbm.open_db(paths.DB_PATH)
CONN.commit()
PD, D = "2026-09-19", "2026-09-20"
PF, CF = 1350.0, 1400.0
RATES = [1300.0, 1450.0]
TS = [int(datetime(2026, 9, 20, h, tzinfo=KST).timestamp()) for h in (10, 17)]
KEYS = [str(t * 1000 // 60000 * 60000) for t in TS]
P = paths.state(attfreeze.FILE)
open(paths.state("backfill_done"), "w").write("1")


def setup(ex, scale=1, cached=False):
    CONN.execute("DELETE FROM raw_ex")
    amounts = [1_300_000 * scale, -700_000 * scale]
    opening = 2_600_000 * scale
    for i, (ts, a) in enumerate(zip(TS, amounts)):
        when = datetime.fromtimestamp(ts, KST).isoformat()
        pl = {"currency": "KRW", "state": "ACCEPTED" if a > 0 else "DONE", "amount": str(abs(a)), "fee": "0", "created_at": when, "done_at": when, "txid": "t%d" % i}
        CONN.execute("INSERT INTO raw_ex(exchange, kind, uuid, revision, payload, observed_at) VALUES (?,?,?,?,?,?)",
                     (ex, "deposit" if a > 0 else "withdraw", "u%d" % i, 1, json.dumps(pl), ts))
    CONN.commit()
    ending = opening + sum(amounts)
    part = "ku" if ex == "upbit" else "kb"
    b = object.__new__(web.StateBuilder)
    b.daily = {}
    b.spot = SimpleNamespace(rate=CF, fx_basis=CF)
    b.px = pricing.PxCache(os.path.join(paths.STATE_DIR, "fxsnap_px_%s_%d.json" % (ex, scale)))
    b.px.nb_begin()
    b.px.d["fx"] = dict(zip(KEYS, RATES)) if cached else {}
    tl = list(zip(TS, map(Decimal, amounts))) if ex == "upbit" else []
    b._upbit_krw_tl = (None, tl, [])
    b.daily_px = {PD: {"p": {}, "x": round(opening / PF, 2), "xv": {"v": 2, "p": {part: [opening, "snap"]}, "fx": PF}},
                  D: {"p": {}, "x": round(ending / CF, 2), "xv": {"v": 2, "p": {part: [ending, "snap"]}, "fx": CF}}}
    extra = {"krw_up": ending if ex == "upbit" else 0.0, "krw_other": ending if ex == "bithumb" else 0.0, "krw_up_tl": tl, "rate": 1500.0}
    fk = {"today": "2026-10-23", "G": {}, "skip": frozenset(), "offc": frozenset(), "rate": CF, "transit": [], "wdt": {}}
    kit = {"groups": {}, "transit": [], "xk": {"sym_tl": {}}, "fk": fk}
    ctx = ({}, datetime(2026, 10, 23, 12, tzinfo=KST), {}, frozenset(), extra, {"rbd": {}, "lpf": {}, "stk": {}, "unv": {}}, None)
    return b, kit, ctx, opening, amounts


def expect(opening, amounts, used):
    ending = opening + sum(amounts)
    return {"val": ending / CF, "flow": sum(a / r for a, r in zip(amounts, used)),
            "kx": opening * (1 / CF - 1 / PF) + sum(a * (1 / CF - 1 / r) for a, r in zip(amounts, used)), "rest": 0.0}


def got_of(rec):
    r = rec["r"]
    return {"val": r["val"], "flow": r["flow"], "kx": r["att"]["kx"], "rest": r["att"]["rest"]}


def same(g, e):
    return all(abs(g[k] - e[k]) < TOL * max(1.0, abs(e[k]) / 1000) for k in e)


def gate_worker(b):
    release, started = threading.Event(), threading.Event()

    def fill(m):
        started.set()
        if not release.wait(10):
            raise AssertionError("worker release timeout")
        with b.px.lock:
            b.px.d["fx"][str(m)] = RATES[KEYS.index(str(m))]
        return b.px.d["fx"][str(m)]
    q = pricing.PxFetchQueue(SimpleNamespace(fx_at=fill, candle_usd=None, maybe_save=lambda: None))
    q.q = {("fx", "", int(k)) for k in KEYS}
    orig = b._daily_attrib

    def gated(*a, **k):
        release.set()
        th.join(10)
        return orig(*a, **k)
    b._daily_attrib = gated
    th = threading.Thread(target=q.drain)
    return th, started, release


for ex in ("upbit", "bithumb"):
    for mode in ("known", "missing", "cache_arrival"):
        b, kit, ctx, op, am = setup(ex, cached=(mode == "known"))
        if mode == "cache_arrival":
            orig = b.px.fx_at

            def fx_at(ms, _o=orig, _b=b):
                v = _o(ms)
                if v is None:
                    with _b.px.lock:
                        _b.px.d["fx"][str(ms // 60000 * 60000)] = RATES[TS.index(ms // 1000)]
                return v
            b.px.fx_at = fx_at
        rec = attfreeze.bf_records(b, CONN, ctx, (kit, b.daily_px, histcurve.HIST.flow_fn), [D], 1_900_000_000)[D]
        exp = expect(op, am, RATES if mode == "known" else [CF, CF])
        chk(same(got_of(rec), exp) and (rec.get("fxp") == (None if mode == "known" else 1)),
            "S1 %s/%s 입출금·환율 몫·나머지 = 같은 스냅숏 독립 기대값(나머지 0) · 대체 표식" % (ex, mode), {"got": got_of(rec), "exp": exp, "fxp": rec.get("fxp")})
        chk("_att_fx_at" not in b.__dict__, "S1 %s/%s 복원 환율 함수가 빌더에 남지 않음" % (ex, mode))
    b, kit, ctx, op, am = setup(ex)
    statefile.atomic_write_json(P, {"_v": 1, "d": {D: {"st": "b", "r": {"flow": -999, "att": {"rest": -999}}}}, "dm": [], "bf": {"v": 2}})
    th, started, release = gate_worker(b)
    th.start()
    started.wait(10)
    rep = attfreeze.backfill(b, CONN, lambda: kit, ctx, now=1_900_000_000)
    release.set()
    th.join(10)
    disk = statefile.read_json(P, {})
    rec = disk["d"][D]
    chk(same(got_of(rec), expect(op, am, [CF, CF])) and rec.get("fxp") == 1,
        "S1 %s/대기열 도착(입출금 뒤·분해 전) = 한 스냅숏(마감 환율 대체) · 가짜 나머지 없음" % ex, got_of(rec))
    chk(rep.get("pend") == 1 and disk["bf"].get("v") != attfreeze.BF_V and disk["bf"].get("pw") == 1 and b.__dict__.get("_att_frz_bf") != attfreeze.BF_V,
        "S2 %s 그 시각 환율 대기 = 미완(세대 봉인 안 함 · pw 1)" % ex, (rep, disk["bf"]))
    b._daily_attrib = type(b)._daily_attrib.__get__(b)
    rep2 = attfreeze.backfill(b, CONN, lambda: kit, ctx, now=1_900_000_000 + attfreeze.BF_PEND_GAP_S - 1)
    chk(rep2 == {"n": 0} and statefile.read_json(P, {})["d"][D] == rec, "S2 %s 간격 안 다음 빌드 = 안 함" % ex, rep2)
    b.px.nb_begin()
    rep3 = attfreeze.backfill(b, CONN, lambda: kit, ctx, now=1_900_000_000 + attfreeze.BF_PEND_GAP_S)
    disk = statefile.read_json(P, {})
    rec3 = disk["d"][D]
    chk(rep3.get("n") == 1 and not rep3.get("pend") and same(got_of(rec3), expect(op, am, RATES)) and "fxp" not in rec3
        and disk["bf"]["v"] == attfreeze.BF_V and b.__dict__.get("_att_frz_bf") == attfreeze.BF_V,
        "S2 %s 간격 뒤(캐시 따뜻) = 그 시각 환율로 다시 계산 · 봉인 · 나머지 0" % ex, (rep3, got_of(rec3), disk["bf"]))

b, kit, ctx, op, am = setup("upbit", scale=1000, cached=True)
rec = attfreeze.bf_records(b, CONN, ctx, (kit, b.daily_px, histcurve.HIST.flow_fn), [D], 1_900_000_000)[D]
chk(same(got_of(rec), expect(op, am, RATES)), "S1 금액 1,000배 = 같은 기대값", got_of(rec))

b, kit, ctx, op, am = setup("upbit")
statefile.atomic_write_json(P, {"_v": 1, "d": {}, "dm": []})
t = 1_900_100_000
reps = []
for i in range(attfreeze.BF_PEND_TRIES + 2):
    b.px.nb_begin()
    reps.append(attfreeze.backfill(b, CONN, lambda: kit, ctx, now=t + i * attfreeze.BF_PEND_GAP_S))
disk = statefile.read_json(P, {})
chk([bool(r.get("pend")) for r in reps] == [True] * attfreeze.BF_PEND_TRIES + [False, False] and reps[-1] == {"n": 0}
    and disk["bf"]["v"] == attfreeze.BF_V and disk["bf"].get("fb") == 1 and same(got_of(disk["d"][D]), expect(op, am, [CF, CF])),
    "S3 끝내 모름 = BF_PEND_TRIES 번 미완 뒤 마감 환율 대체로 봉인(fb) · 그 뒤 안 함 · 나머지 0", (reps, disk["bf"]))

b, kit, ctx, op, am = setup("upbit")
statefile.atomic_write_json(P, {"_v": 1, "d": {}, "dm": []})


def boom(*a, **k):
    raise RuntimeError("synthetic")


t = 1_900_300_000
seen = []
for i in range(12):
    b.px.nb_begin()
    r = attfreeze.backfill(b, CONN, lambda: kit, ctx, now=t + i * attfreeze.BF_PEND_GAP_S, records_fn=boom if i % 2 else None)
    seen.append((dict(statefile.read_json(P, {}).get("bf") or {}), r))
bf_end = statefile.read_json(P, {})["bf"]
chk(bf_end.get("v") == attfreeze.BF_V or int(bf_end.get("tries") or 0) >= attfreeze.BF_TRIES,
    "S3b 미완·예외 교차 = 상한에 닿아 멈춤(무한 재계산 고리 없음)", [x[0] for x in seen[-3:]])
chk(all(int(x[0].get("tries") or 0) == 0 or "pw" in x[0] for x in seen[2:] if x[0].get("v") == 0), "S3b 예외 기록이 미완 횟수 pw 를 지우지 않음",
    [x[0] for x in seen[:4]])

b, kit, ctx, op, am = setup("upbit", cached=True)
b.daily_px["2026-09-21"] = dict(b.daily_px[D])
b.daily_px["2026-09-22"] = dict(b.daily_px[D])
s_rec = {"st": "s", "st0": "b", "sx": "2026-05-01", "r": {"flow": 1.0, "att": {"rest": 88.66}}, "at": 1, "h": "s"}
n_rec = {"r": {"flow": 2.0, "att": {"rest": 3.0}}, "at": 1, "h": "n"}
statefile.atomic_write_json(P, {"_v": 1, "dm": [], "bf": {"v": 2, "at": 1, "n": 1, "want": 1, "re": 0},
                                "d": {D: {"st": "b", "r": {"flow": 428.57, "att": {"rest": 88.66}}, "at": 1, "h": "old"},
                                      "2026-09-21": s_rec, "2026-09-22": n_rec}})
rep = attfreeze.backfill(b, CONN, lambda: kit, ctx, now=1_900_200_000)
disk = statefile.read_json(P, {})
chk(attfreeze.BF_V >= 3 and rep.get("re", 0) >= 1 and same(got_of(disk["d"][D]), expect(op, am, RATES)) and disk["d"]["2026-09-21"] == s_rec
    and disk["d"]["2026-09-22"] == n_rec and disk["bf"]["v"] == attfreeze.BF_V,
    "S4 세대 2 'b'(가짜 나머지 가능) = 다시 계산 · 's'·정상 동결 = 그대로", (rep, disk["bf"]))

CONN.close()
T.finish()
