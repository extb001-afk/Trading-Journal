#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import copy
import json
import os
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


def E(m, d, h=23, mi=59, s=59):
    return datetime(2026, m, d, h, mi, s, tzinfo=KST).timestamp()


def D(m, d):
    return datetime(2026, m, d, tzinfo=KST)


def iso(m, d):
    return "2026-%02d-%02d" % (m, d)


class FakeSpot:
    rate = FX
    fx_basis = FX

    def price(self, sym):
        return None


class FakePx:
    fx_none = False

    def fx_at(self, ms):
        return FX

    def candle_usd(self, sym, ms):
        return None

    def flush(self):
        pass


def unit_builder():
    b = object.__new__(web.StateBuilder)
    b.daily = {"_v": web.DAILY_V}
    b.daily_px = {"_v": 1}
    b._daily_seed = {}
    b._upbit_krw_tl = None
    b.spot = FakeSpot()
    b.px = FakePx()
    return b


def reset_files():
    for p9 in (web.DAILY_PATH, web.DAILY_PX_PATH):
        if os.path.exists(p9):
            os.remove(p9)


def mkx(now_ts):
    return {"ub": 0.0, "fiat": 0.0, "lp": 0.0, "ubs": {}, "ub_tl": {}, "krw_up": 0.0, "krw_other": 0.0, "rate": FX, "krw_up_tl": None,
            "xsrc": {"now": {"ts": now_ts, "ku": 0.0, "kb": 0.0, "ub": {}, "rest": 0.0},
                     "base": {"ku": [0.0, now_ts], "kb": [0.0, now_ts]}, "tl": {"ku": [], "kb": []}, "first": {}}}


def pin_x(b, m, d):
    xv = {"v": xparts.GEN, "p": {"ku": [0.0, "snap"], "kb": [0.0, "snap"], "ub": [{}, "snap"], "rest": [0.0, "snap"]}, "fx": FX, "how": "live"}
    b.daily_px[iso(m, d)] = {"p": {}, "k": {}, "xv": xv}


def run(b, G, hold, today, now_ts, dep=None):
    kw = {} if dep is None else {"dep_transit": dep}
    return b._daily_series(G, today, {}, {}, ca_gids=set(), ex_gids=set(), skip_gids=set(), pending_gids=set(),
                           hold_qty=hold, extra=copy.deepcopy(mkx(now_ts)), extra_ok=True, now_ts=now_ts, **kw)


def val_of(series, m, d):
    k = "%02d-%02d" % (m, d)
    return next((r["val"] for r in series if r["date"] == k), None)


def close(a, b9, tol=0.01):
    return a is not None and b9 is not None and abs(float(a) - float(b9)) < tol


def stable(gid, tl, sym="USDC"):
    return {"gid": gid, "sym": sym, "is_stable": True, "qty_timeline": [(int(t), Decimal(str(q))) for t, q in tl]}


def pins(b):
    for d9 in range(11, 31):
        pin_x(b, 9, d9)
    for d9 in range(1, 15):
        pin_x(b, 10, d9)


NOW = E(10, 15, 13, 45, 0)
TB, TS = E(10, 15, 13, 40, 0), E(10, 15, 13, 42, 0)
GA = {1: stable(1, [(E(9, 1), 5000)]),
      2: stable(2, [(TB, 1000), (TS, -1000)], sym="USDT")}
HA = {1: Decimal(5000), 2: Decimal(1000)}
DEP_A = [{"gid": 2, "ts": int(TS), "qty": Decimal(1000)}]
reset_files()
b = unit_builder()
pins(b)
s0 = run(b, GA, HA, D(10, 15), NOW)
chk(close(val_of(s0, 10, 14), 6000), "A0 (종전 재현) 대기 정보 없음 = 어제 $6,000 — 송신 레그 되감기 + hold 대기 가산 = 두 번", val_of(s0, 10, 14))
reset_files()
b = unit_builder()
pins(b)
sA = run(b, GA, HA, D(10, 15), NOW, DEP_A)
chk(close(val_of(sA, 10, 14), 5000) and close(val_of(sA, 10, 1), 5000), "A 어제·지난날 = 원래 보유 $5,000 (대기 몫 없음)", (val_of(sA, 10, 14), val_of(sA, 10, 1)))
chk(close(val_of(sA, 10, 15), 6000), "A 오늘 = 보유 5,000 + 입금 대기 1,000", val_of(sA, 10, 15))
chk(close(((b.daily.get(iso(10, 14)) or {}).get("g") or {}).get("2") or 0, 0), "A 동결 항목에 대기 그룹 몫 없음", b.daily.get(iso(10, 14)))

TB2, TS2 = E(10, 13, 10, 0, 0), E(10, 14, 22, 0, 0)
GB = {1: stable(1, [(E(9, 1), 5000)]), 2: stable(2, [(TB2, 1000), (TS2, -1000)], sym="USDT")}
DEP_B = [{"gid": 2, "ts": int(TS2), "qty": Decimal(1000)}]
reset_files()
b = unit_builder()
pins(b)
sB = run(b, GB, HA, D(10, 15), NOW, DEP_B)
chk(close(val_of(sB, 10, 12), 5000) and close(val_of(sB, 10, 13), 6000) and close(val_of(sB, 10, 14), 6000),
    "B 산 전날 5,000 · 산 날(송신 전) 6,000 · 송신 날 마감(대기 중) 6,000", (val_of(sB, 10, 12), val_of(sB, 10, 13), val_of(sB, 10, 14)))

kit = {"groups": {2: {"hold": 1000.0, "tl": [(int(TB), 1000.0), (int(TS), -1000.0)]},
                  1: {"hold": 5000.0, "tl": [(int(E(9, 1)), 5000.0)]}},
       "transit": [(2, int(TS), 1000.0)]}
rw = histcurve.rewind(kit, [iso(10, 14), iso(10, 13)])
chk(not (rw.get(2) or {}) and close((rw.get(1) or {}).get(iso(10, 14)), 5000), "C 장기 곡선 = 송신 전 날 대기 그룹 0 · 원래 보유 그대로", rw)
kit["transit"] = []
rw0 = histcurve.rewind(kit, [iso(10, 14)])
chk(close((rw0.get(2) or {}).get(iso(10, 14)), 1000), "C0 (종전 재현) transit 에 대기 없음 = 송신 전 날 1,000 부풂", rw0)

src_r = T.web_src()
src_d = open(os.path.join(T.SRC, "view_b_daily.py"), encoding="utf-8").read()
chk(src_r.count('dep_tr9.append(') == 2 and src_r.count('"ts": int(ts9 or 0),') == 1 and src_r.count('"ts": int(ts or 0),') == 1,
    "D 리플레이: 업비트 대기·해외 대기 두 곳에서 입금 대기 목록 · 대기 될 수 있는 업비트 트랜짓 두 곳에 송신 시각")
chk('dep_transit=_bs9.get("dep_tr9")' in src_d and 'list(_bs9.get("dep_tr9") or ())' in src_d, "D 30일 곡선·장기 곡선 둘 다 입금 대기 넘김")

reset_files()
T.finish()
