#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import copy  # noqa: E402
import os  # noqa: E402

import paths  # noqa: E402
import histcurve as H  # noqa: E402
import view_pxfix as V  # noqa: E402

chk = T.chk
S = paths.STATE_DIR
CA = "0x" + "ab" * 20
SP = "ca:base:" + CA
D = "2026-08-10"
TODAY = "2026-08-20"
NOW = H.day_end(TODAY) - 40000
DAYS = H.days_between("2026-08-01", "2026-08-19")
G = {7: {"sym": "TKJ"}}
PAIRS = {7: [("base", CA)]}


class FakeHist:
    px = {"specs": {}, "fx": None}
    pending = False


def setup(name, px, src="geckoterminal", dcn=None):
    dc = H.DayClose(path=os.path.join(S, name + ".json"), hist=FakeHist())
    dc.st["s"][SP] = {"lo": DAYS[0], "hi": DAYS[-1], "st": "ok", "p": dict.fromkeys(DAYS, px) if px else {}, "src": [src], "at": NOW}
    daily = {D: {"val": 2000.0, "g": {"7": 1000.0}, "est": 1000.0, "src": "calc"}}
    dpx = {D: {"p": {"7": 1.0}, "k": {}}}
    if dcn:
        dpx[D]["dcn"] = list(dcn)
    return dc, daily, dpx


def build(dc, daily, dpx, now):
    f = dc.resolver(G, {7}, {}, set(), {}, PAIRS, now=now)
    V._px1004_reset(daily, dpx, G, TODAY, f, live_px={7: 1.0}, skip_gids=set(), now_ts=now, backup=lambda _: [])
    return V._reprice_now_days(daily, dpx, G, TODAY, now, f, set(), backup=lambda _: [])


def strong(dc, px, now):
    dc.st["s"][SP].update(p=dict.fromkeys(DAYS, px), src=["coingecko"])
    dc.st.setdefault("chg", {})[SP] = {D: now}
    dc.gen += 1


def state(daily, dpx):
    c, e = daily[D], dpx[D]
    return c["val"], c.get("est"), sorted(e.get("dcn") or ()), (e.get("k") or {}).get("7")


dc, daily, dpx = setup("sA", 4.0)
build(dc, daily, dpx, NOW)
a1 = state(daily, dpx)
chk(a1 == (2000.0, 1000.0, [], None), "A DEX 일봉 4(근사의 4배) = 의심 — 근사 그대로(2,000 · est 1,000) · 확정(dcn) 안 함", a1)
strong(dc, 4.0, NOW + 1)
build(dc, daily, dpx, NOW + 2)
a2 = state(daily, dpx)
chk(a2 == (5000.0, None, [], "d"), "A 코인게코 4 도착(변경 표식) = 손 안 대고 5,000 · 근사 몫 정리 · 그날 마감가(d)", a2)

dc, daily, dpx = setup("sB1", 2.9)
build(dc, daily, dpx, NOW)
b1 = state(daily, dpx)
chk(b1[0] == 3900.0 and b1[3] == "d", "B DEX 2.9(3배 안) = 재평가 3,900", b1)
dc, daily, dpx = setup("sB2", 3.1)
build(dc, daily, dpx, NOW)
b2 = state(daily, dpx)
chk(b2 == (2000.0, 1000.0, [], None), "B DEX 3.1(3배 밖) = 의심 — 근사 그대로 · 확정 안 함", b2)

dc, daily, dpx = setup("sC", 4.0, src="coingecko")
build(dc, daily, dpx, NOW)
c1 = state(daily, dpx)
chk(c1 == (5000.0, None, [], "d"), "C 코인게코 4(근사의 4배 · 정상 변동) = 바로 5,000", c1)

dc, daily, dpx = setup("sD", 4000.0)
for i in range(3):
    dc.gen += 1
    build(dc, daily, dpx, NOW + i * 3600)
d1 = state(daily, dpx)
chk(d1 == (2000.0, 1000.0, [], None), "D 얇은 풀 DEX 4,000 = 몇 번 다시 봐도 값 안 씀 · 근사 표식(est) 그대로", d1)

dc, daily, dpx = setup("sE", 4.0, dcn=["7"])
build(dc, daily, dpx, NOW)
e1 = state(daily, dpx)
chk(e1 == (2000.0, 1000.0, ["7"], None) or e1 == (2000.0, 1000.0, [], None), "E 준비 — 옛 확정 그룹은 약한 값으로 매기지 않음", e1)
strong(dc, 4.0, NOW + 1)
build(dc, daily, dpx, NOW + 2)
e2 = state(daily, dpx)
chk(e2 == (5000.0, None, [], "d"), "E 옛 확정(dcn) 그룹도 강한 출처 도착 = 저절로 5,000(dcn 손으로 안 지움)", e2)

dc, daily, dpx = setup("sF", None)
build(dc, daily, dpx, NOW)
f1 = state(daily, dpx)
chk(f1 == (2000.0, 1000.0, ["7"], None), "F 그날 값 없는 최종 항목 = 확정(dcn) · 근사 그대로", f1)
snap = copy.deepcopy((daily, dpx))
dc.gen += 1
build(dc, daily, dpx, NOW + 3600)
chk((daily, dpx) == snap, "F 다시 봐도 그대로(멱등)", None)

dc, daily, dpx = setup("sG", 4.0, src="coingecko", dcn=["7"])
dc.st["s"][SP].update(lo=DAYS[0], hi="2026-08-05")
build(dc, daily, dpx, NOW)
g1 = state(daily, dpx)
chk(g1 == (2000.0, 1000.0, ["7"], None) and not dc.want and not dc.want_old, "G 옛 확정 그룹 = 저장본에 그날 없으면 그대로 · 받기 요청 0", (g1, dc.want))

T.finish()
