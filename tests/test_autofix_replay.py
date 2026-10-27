#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _costsim as S  # noqa: E402

import json  # noqa: E402
import time  # noqa: E402

DAY = 86400
LAB = "자동 처리 · 창 안 미확인 유출"


def near(a, b, tol=0.01):
    return a is not None and abs(float(a) - float(b)) <= tol


def scen(mode):
    c = S.reset(px={"USDT": 1., "ETH": 2000.})
    t0 = S.NOW - 20 * DAY
    S.PXF[0] = lambda sym, ts: {"ETH": 2000.}.get(sym)
    S.ex("bybit", deposits=[S.norm_row("bybit", "fund", "USDT", "10000", 0, "f1", "ACCEPTED", t0, t0)])
    S.fills("bybit", [S.norm_fill("bybit", "b0", (t0 + DAY) * 1000, "ETH", "USDT", "buy", "2000", "1.01", "0", "")])
    ts = t0 + 3 * DAY
    aid = c.svc_exf._exf_asset("bybit", "ETH")
    ns, sid = ("bybit:autofix", f"exfauto:ETH:{ts + 5 * DAY}") if mode == "auto" else ("bybit:recon", f"exfrecon:ETH:{ts}")
    c._post_leg("exchange", ns, sid, 0, ts, aid, "exchange:bybit", -1000000, None, None, "opening", "EXF_ADJUST")
    S.fills("bybit", [S.norm_fill("bybit", "s1", (t0 + 5 * DAY) * 1000, "ETH", "USDT", "sell", "2500", "1", "0", "")])
    f, G, _rr = S.build()
    blob = json.dumps(f, ensure_ascii=False, default=str)
    day = time.strftime("%Y-%m-%d", time.localtime(ts + 9 * 3600 - time.localtime(ts).tm_gmtoff))
    return {"rz": round(S.realized(f), 4), "tax": round(S.tax_sum(f), 4), "lab": LAB in blob, "day": day,
            "lab_day": any(LAB in json.dumps(e, ensure_ascii=False, default=str) and day in json.dumps(e, ensure_ascii=False, default=str)
                           for e in (f.get("extraEvents") or f.get("extra_events") or [])),
            "old": "잔고 정정(감소)" in blob}


ra = T.safe(scen, "auto") or {}
rr = T.safe(scen, "recon") or {}
T.chk(near(ra.get("rz"), 500) and near(ra.get("rz"), rr.get("rz")) and near(ra.get("tax"), ra.get("rz")),
      "R1 자동 행 = 소진만 · 실현 $500 = 일반 정정과 같음 · 명세 = 실현", (ra, rr))
T.chk(ra.get("lab") is True, "R2 자동 처리 문구가 기록 줄에", ra)
T.chk(rr.get("lab") is False and rr.get("old") is True, "R3 기존 대사 음수 정정 = 종전 문구 · 자동 처리 문구 없음", rr)
T.finish()
