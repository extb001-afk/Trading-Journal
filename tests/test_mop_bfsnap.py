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
import web
import xparts

chk = T.chk
S = common.STATE_DIR
MARK = os.path.join(S, "backfill_done")
KST = timezone(timedelta(hours=9))
FX = 1400.0


def E(m, d, h=23, mi=59, s=59):
    return datetime(2026, m, d, h, mi, s, tzinfo=KST).timestamp()


def iso(m, d):
    return "2026-%02d-%02d" % (m, d)


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


def unit_builder(pin_p=True):
    b = object.__new__(web.StateBuilder)
    b.daily = {"_v": web.DAILY_V, "_risk_rev": ""}
    b.daily_px = {"_v": 1}
    b._daily_seed = {}
    b._upbit_krw_tl = None
    b.spot = FakeSpot()
    b.px = FakePx()
    for d9 in range(1, 10):
        b.daily_px[iso(10, d9)] = {"p": {"2": 2.0} if pin_p else {}, "k": {"2": "live"} if pin_p else {},
                                   "xv": {"v": xparts.GEN, "p": {"ku": [0.0, "snap"], "kb": [0.0, "snap"], "ub": [{}, "snap"], "rest": [0.0, "snap"]},
                                          "fx": FX, "how": "live"}}
    return b


def mkx(now_ts):
    return {"ub": 0.0, "fiat": 0.0, "lp": 0.0, "ubs": {}, "ub_tl": {}, "krw_up": 0.0, "krw_other": 0.0, "rate": FX, "krw_up_tl": None,
            "xsrc": {"now": {"ts": now_ts, "ku": 0.0, "kb": 0.0, "ub": {}, "rest": 0.0},
                     "base": {"ku": [0.0, now_ts], "kb": [0.0, now_ts]}, "tl": {"ku": [], "kb": []}, "first": {}}}


NOW = E(10, 10, 12, 0, 0)
T0 = E(8, 1, 0, 0, 0)
G = {1: {"gid": 1, "sym": "USDC", "is_stable": True, "qty_timeline": [(int(T0), Decimal(100000))]},
     2: {"gid": 2, "sym": "TKN", "is_stable": False, "qty_timeline": [(int(E(10, 5, 12, 0, 0)), Decimal(1000))]}}
HOLD = {1: Decimal(100000), 2: Decimal(1000)}
SN = {"date": iso(10, 9), "ts": E(10, 9, 23, 58, 0), "val": 2000.0, "usdt": FX, "kimp": None, "g": {"1": 0.0, "2": 2000.0}, "x": 0.0, "defer": False,
      "p": {"2": 2.0}, "xv": {"v": 1, "p": {"kb": [0.0, "snap"], "rest": [0.0, "snap"]}, "fx": FX, "ts": int(E(10, 9, 23, 58, 0))}}


def run(mark_txt, pin_p=True, live=2.0, sn_ts=None):
    for p9 in (web.DAILY_PATH, web.DAILY_PX_PATH):
        if os.path.exists(p9):
            os.remove(p9)
    with open(MARK, "w") as f:
        f.write(mark_txt)
    b = unit_builder(pin_p)
    sn = dict(SN, ts=sn_ts) if sn_ts else dict(SN)
    b.daily["_live_ok"] = dict(sn)
    b.daily["_live"] = dict(sn)
    ser = b._daily_series(G, datetime(2026, 10, 10, tzinfo=KST), {}, {2: live}, ca_gids={2}, ex_gids=set(), skip_gids=set(), pending_gids=set(),
                          hold_qty=dict(HOLD), extra=copy.deepcopy(mkx(NOW)), extra_ok=True, now_ts=NOW)
    return {r["date"]: r["val"] for r in ser}, b.daily.get(iso(10, 9)) or {}, b.daily_px.get(iso(10, 9)) or {}


v1, e1, _p1 = run(str(int(E(10, 10, 0, 30, 0))))
chk(abs(float(v1.get("10-09") or 0) - 102000) < 0.01 and e1.get("src") != "live",
    "B1 표식 전 스냅숏 = 마감 재료 아님 → 다시 계산 100,000 + 1,000 × $2 = 102,000(수정 전 2,000 으로 굳음)", (v1.get("10-09"), e1.get("src")))
v2, e2, _p2 = run(str(int(E(10, 1, 0, 0, 0))))
chk(abs(float(v2.get("10-09") or 0) - 2000) < 0.01 and e2.get("src") == "live", "B2 표식 뒤 스냅숏 = 종전대로 실시간 마감(live)", (v2.get("10-09"), e2.get("src")))
v3, e3, _p3 = run("")
chk(e3.get("src") == "live", "B3 표식 내용 못 읽음(빈 내용) = 종전대로 스냅숏 사용", e3.get("src"))
v4, e4, p4 = run(str(int(E(10, 10, 0, 30, 0))), pin_p=False, live=3.0)
chk(abs(float(v4.get("10-09") or 0) - 102000) < 0.01 and (p4.get("p") or {}).get("2") == 2.0,
    "B4 그날 고정 가격 없음 + 지금 시세 $3 → 버린 스냅숏의 관측가 $2 로 102,000 · 그날 가격 고정", (v4.get("10-09"), p4.get("p")))
T5 = E(10, 9, 23, 59, 30)
v5, e5, _p5 = run(repr(T5 + 0.8), sn_ts=T5 + 0.2)
chk(abs(float(v5.get("10-09") or 0) - 102000) < 0.01 and e5.get("src") != "live", "B5 같은 초 안 표식 전 스냅숏(소수 초 비교) = 버림", (v5.get("10-09"), e5.get("src")))
T.finish()
