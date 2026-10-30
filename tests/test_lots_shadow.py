#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import os  # noqa: E402
from decimal import Decimal  # noqa: E402

import accounting_basis as B  # noqa: E402
import calcguard as CG  # noqa: E402

chk = T.chk
D = Decimal
CELLS = ("qty_known", "cost", "qty_unknown", "realized")


def _sell(cb, g, q, u=None):
    fk = min(q, g["qty_known"])
    return cb.release(g, fk, cb.wac(g) * fk, D(0) if u is None else u)


def _audit(cb, G):
    return cb.lots_audit(G, "t")


for strict in (False, True):
    cb = B.StrictCostBasis() if strict else B.CostBasis()
    G = {1: cb.new_group(1, "TKA", False, False), 2: cb.new_group(2, "TKA", False, False)}
    g1, g2 = G[1], G[2]
    cb.acquire(g1, D(10), D(100), ts=1000, src=11)
    cb.acquire(g1, D(5), D("75.5"), ts=2000, src=12)
    cb.acquire(g1, D(3), ts=3000, src=13, u=D(2))
    cb.capitalize(g1, D("33.3"), ts=3000, src=13)
    _sell(cb, g1, D(4))
    _sell(cb, g1, D("2.5"), u=D(1))
    fk = min(D(6), g1["qty_known"])
    fr = cb.release(g1, fk, cb.wac(g1) * fk, D(0), lots=True)
    moved_c = sum((c for _q, c, _t in fr), D(0))
    cb.acquire(g2, fk, ts=5000, src=21, lots=fr)
    cb.capitalize(g2, moved_c, ts=5000, src=21)
    a1 = _audit(cb, G)
    err = None
    if strict:
        try:
            cb.check(G, "t")
        except AssertionError as e:
            err = str(e)
    k2 = cb.lots_of(g2).eff()
    chk(not a1 and err is None and len(k2) == len(fr) and sorted(x.ts for x, _q, _c in k2) == sorted(t for _q, _c, t in fr)
        and [str(g1[k]) for k in CELLS] != ["0"] * 4,
        "L-a 매수 3·매도 2·이동 1 뒤 두 그룹 로트 합 = 칸(%s) · 받는 쪽 로트 = 조각마다(취득 시각 보존)" % ("엄격 check 포함" if strict else "일반"),
        (a1, err, [(str(q), str(c), x.ts) for x, q, c in k2]))

cb = B.CostBasis()
G = {1: cb.new_group(1, "TKC", False, False)}
g = G[1]
cb.acquire(g, u=D(4), ts=100, src=1)
cb.acquire(g, u=D(6), ts=200, src=2)
cb.acquire(g, u=D(5), ts=300, src=3)
bk = cb.lots_of(g)
u0 = sum(x.qty for x in bk.unknown)
cb.convert(g, D(8), D(16), ts=900)
k_ts = [(str(q), str(c), x.ts) for x, q, c in bk.eff()]
u1 = sum(x.qty for x in bk.unknown)
cb.convert(g, D(2), D(1), ts=901, src=1)
k_ts2 = [x.ts for x, _q, _c in bk.eff()][-1]
chk(u0 - u1 == D(8) and k_ts == [("5", "10", 300), ("3", "6", 200)] and k_ts2 == 100 and not _audit(cb, G)
    and [str(x.qty) for x in bk.unknown] == ["2", "3"],
    "L-c convert = 미확인 감소 == 확인 증가 · 확인 로트 시각 = 미확인 로트 시각(최신부터 · 같은 src 먼저) · 원가 = 조각 수량 비례", (k_ts, k_ts2, u0, u1))
g["qty_unknown"] += D(1)
cb.convert(g, D(6), D(4), ts=902)
chk(any("qty_unknown" in m for m in _audit(cb, G)), "L-c 미확인 로트 부족(칸 > 로트)은 convert 뒤에도 감사가 잡음(부족분 = ures)", _audit(cb, G))

cb = B.CostBasis()
G = {1: cb.new_group(1, "TKD", False, False)}
g = G[1]
n = B.LOT_MERGE_AT + 1
for i in range(n):
    cb.acquire(g, D(1), D(i + 1), ts=10_000 + i, src=i)
bk = cb.lots_of(g)
first = bk.known[0]
chk(len(bk.known) == B.LOT_MERGE_AT and bk.merges == 1 and str(first.qty) == "2" and str(first.cost) == "3" and first.ts == 10_000
    and str(g["qty_known"]) == str(n) and str(g["cost"]) == str(n * (n + 1) // 2) and not _audit(cb, G),
    "L-d 상한+1 번 취득 = 가장 오래 든 둘 합침(수량·원가 합 · 시각 = 이른 쪽) · 로트 수 = 상한 · 칸·로트 합 불변",
    (len(bk.known), bk.merges, str(first.qty), str(first.cost), first.ts))

cb = B.CostBasis()
G = {1: cb.new_group(1, "TKE", False, False)}
g = G[1]
cb.acquire(g, D(7), D(70), ts=50, src=99)
for q in (D(1), D(2), D(3)):
    cb.acquire(g, q, ts=60, src=500, u=D("0.5"))
cb.capitalize(g, D(12), ts=60, src=500)
bk = cb.lots_of(g)
ek = [(str(q), str(c), x.src) for x, q, c in bk.eff()]
chk(ek == [("7", "70", 99), ("1", "2", 500), ("2", "4", 500), ("3", "6", 500)] and bk.merges == 0 and len(bk.unknown) == 3 and not _audit(cb, G),
    "L-e 같은 posting_id acquire 3 + capitalize 1 = 합침 없음(로트 3) · 원가는 그 셋에 수량 비례 · 다른 src 로트 무변", ek)

cb = B.CostBasis()
G = {1: cb.new_group(1, "TKH", False, False)}
g = G[1]
cb.acquire(g, D(10), D(100), ts=1, src=1)
cb.acquire(g, D(30), D(600), ts=2, src=2)
bk = cb.lots_of(g)
raw0 = [(x.qty, x.cost) for x in bk.known]
_sell(cb, g, D(10))
raw1 = [(x.qty, x.cost) for x in bk.known]
eff1 = [(str(q), str(c)) for _x, q, c in bk.eff()]
chk(raw0 == raw1 and bk.qs == D("0.75") and bk.cs == D("0.75") and eff1 == [("7.50", "75.00"), ("22.50", "450.00")] and not _audit(cb, G),
    "L-h 부분 차감 = 원시값 무변 · 배율만(수량·원가 같은 비율 · O(1))", (bk.qs, bk.cs, eff1))
_sell(cb, g, g["qty_known"])
chk(not bk.known and bk.qs == 1 and bk.resid == g["cost"] and not _audit(cb, G), "L-h 전량 = 로트 비움 · 남은 원가(반올림 잔차) = resid", (bk.resid, g["cost"]))
gd = cb.new_group(2, "TKH2", False, False)
G[2] = gd
cb.acquire(gd, D("1e-10"), D("1e-8"), ts=3, src=3)
cb.release(gd, D("5e-11"), cb.wac(gd) * D("5e-11"), D(0))
bk2 = cb.lots_of(gd)
chk(gd["cost"] == D("1e-8") and not _audit(cb, G) and len(bk2.known) == 1, "L-h qk ≤ EPS 처분(c = 0 · 수량만 절반) = 원가 배율 1 · 감사 통과", _audit(cb, G))
gz = cb.new_group(3, "TKH3", False, False)
G[3] = gz
cb.acquire(gz, u=D(5), ts=4, src=4)
_sell(cb, gz, D(0), u=D(2))
cb.release(gz, D(0), D(0), D(1))
cb.capitalize(gz, D(9), ts=5, src=5)
cb.acquire(gz, D(2), ts=6, src=6)
r_keep = cb.lots_of(gz).resid
cb.capitalize(gz, D(4), ts=6, src=6)
cb.acquire(gz, D(1), D(1), ts=7, src=7)
bz = cb.lots_of(gz)
chk(r_keep == 9 and bz.resid == 0 and [(str(q), str(c)) for _x, q, c in bz.eff()] == [("2", "4"), ("1", "10")] and bz.broken is None
    and not _audit(cb, G),
    "L-h 로트 없을 때 원가 = resid · pending 취득은 resid 유지 · 다음 원가 있는 취득에 접힘 · k = 0 / qk = 0 처분 = 0 나누기 없음",
    (r_keep, bz.resid, bz.broken, [(str(q), str(c)) for _x, q, c in bz.eff()]))
gn = cb.new_group(4, "TKH4", False, False)
G[4] = gn
cb.acquire(gn, D(1), D(1), ts=8, src=8)
cb.acquire(gn, D(1), D(3), ts=9, src=9)
for _i in range(60):
    _sell(cb, gn, gn["qty_known"] * D("0.9"))
bn = cb.lots_of(gn)
chk(bn.norms >= 1 and bn.qs >= B.LOT_SCALE_NORM and not _audit(cb, G) and len(bn.known) == 2,
    "L-h 배율이 아주 작아지면 원시값에 접음(norm) · 감사 통과", (bn.norms, bn.qs, _audit(cb, G)))

cb = B.CostBasis()
G = {1: cb.new_group(1, "TKI", False, False)}
g = G[1]
cb.capitalize(g, D(5), ts=1, src=1)
r4 = cb.lots_of(g).resid
cb.acquire(g, D(4), D(40), ts=2, src=2)
cb.acquire(g, D(6), ts=3, src=3, lots=[(D(1), D(10), 100), (D(2), D(50), 200)])
cb.capitalize(g, D(120), ts=3, src=3)
e1 = [(str(q), str(c), x.ts) for x, q, c in cb.lots_of(g).eff()]
cb.capitalize(g, D(6), ts=3, src=3)
e2 = [str(c) for _x, _q, c in cb.lots_of(g).eff()]
cb.capitalize(g, D(-12), ts=4, src=777)
e3 = [str(c) for _x, _q, c in cb.lots_of(g).eff()]
chk(r4 == 5 and e1 == [("4", "45", 2), ("2", "20", 100), ("4", "100", 200)] and e2 == ["45", "22", "104"]
    and e3 == ["40.2", "19.6", "99.2"] and not _audit(cb, G),
    "L-i capitalize ④ resid → 접힘 · ① pending hint 비례(조각 운반 = 상대 몫 · 시각 보존) · ② 같은 src 수량 비례 · ③ 전부 수량 비례(음수 포함)",
    (r4, e1, e2, e3))

cb = B.CostBasis()
G = {1: cb.new_group(1, "TKS", False, False)}
ent = {"qty": D(0)}
for i in range(3 * B.LOT_FRAG_MAX):
    cb.pool_put(ent, [(D(1), D(i), 5000 + i)])
pf = cb.pool_lots(ent)
cb.acquire(G[1], D(30), ts=9000, src=1, lots=[(D(1), D(2), 100 + i) for i in range(5 * B.LOT_FRAG_MAX)])
cb.capitalize(G[1], D(60), ts=9000, src=1)
bs = cb.lots_of(G[1])
chk(len(pf) <= 2 * B.LOT_FRAG_MAX and sum(q for q, _c, _t in pf) == 3 * B.LOT_FRAG_MAX and min(t for _q, _c, t in pf) == 5000
    and len(bs.known) == B.LOT_FRAG_MAX and min(x.ts for x in bs.known) == 100 and not _audit(cb, G),
    "L-i 조각 상한 — 누적 풀 · 큰 조각 목록 수신 = 묶음 상한 이하 · 수량 합·가장 이른 시각 보존 · 감사 통과", (len(pf), len(bs.known)))

class _BadTs:
    def __int__(self):
        raise RuntimeError("시험 고장")


_env = os.environ.pop("TJ_STRICT", None)
try:
    cbs = {}
    for nm, cls in (("plain", B.CostBasis), ("live", B.CostBasis), ("strict", B.StrictCostBasis)):
        cb = cls()
        G = {1: cb.new_group(1, "TKJ", False, False)}
        g = G[1]
        cb.acquire(g, D(3), D(30), ts=1, src=1)
        cb.acquire(g, D("1.5"), D(9), ts=(2 if nm == "plain" else _BadTs()), src=2)
        cb.acquire(g, D(2), D(7), ts=3, src=3)
        _sell(cb, g, D(1))
        cbs[nm] = (cb, G, g)
finally:
    if _env is not None:
        os.environ["TJ_STRICT"] = _env
pl, lv, st = cbs["plain"], cbs["live"], cbs["strict"]
snap = CG.snapshot().get("accounting_basis.acquire[lots]") or {}
bkl = lv[0].lots_of(lv[2])
try:
    st[0].check(st[1], "t")
    ej = None
except AssertionError as e:
    ej = str(e)
chk([str(lv[2][k]) for k in CELLS] == [str(pl[2][k]) for k in CELLS] == [str(st[2][k]) for k in CELLS]
    and bkl.broken is not None and "RuntimeError" in bkl.broken and len(bkl.known) == 1 and snap.get("n", 0) >= 2
    and lv[0].lots_audit(lv[1], "t") and not pl[0].lots_audit(pl[1], "t") and ej is not None and "로트" in ej,
    "L-j 로트 연산 고장 = 원가 칸 str 같음(고장 없는 장부와) · calcguard 기록 · 그 그룹 고장 표시 뒤 로트 연산 건너뜀 · 감사 실패 · 엄격 check = AssertionError",
    (bkl.broken, snap.get("n"), ej))
class _BugTs:
    def __int__(self):
        raise NameError("시험 고장")


_env = os.environ.get("TJ_STRICT")
os.environ["TJ_STRICT"] = "1"
try:
    cb = B.CostBasis()
    gq = cb.new_group(1, "TKJ2", False, False)
    try:
        cb.acquire(gq, D(5), D(50), ts=_BugTs(), src=1)
        rq = None
    except NameError as e:
        rq = str(e)
finally:
    if _env is None:
        os.environ.pop("TJ_STRICT", None)
    else:
        os.environ["TJ_STRICT"] = _env
chk(rq == "시험 고장" and str(gq["qty_known"]) == "5" and str(gq["cost"]) == "50" and cb.lots_of(gq).broken is not None,
    "L-j 엄격 재던짐 때도 원가 칸은 먼저 반영(칸 문장 → 로트 연산 순서) · 그 그룹 고장 표시", (rq, str(gq["qty_known"]), str(gq["cost"])))

T.finish()
