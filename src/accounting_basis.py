from __future__ import annotations

from collections import deque
from decimal import Decimal
from itertools import count, islice
from typing import Any, Callable, Deque, List, Optional, Set, Tuple, TypedDict

import calcguard
from view_common import EPS

__all__ = ["GroupState", "CostBasis", "StrictCostBasis", "Lot", "LotBook", "LotMismatch"]

LOT_MERGE_AT = 128
LOT_SCALE_NORM = Decimal("1e-40")
LOT_TOL_ABS = Decimal("1e-9")
LOT_TOL_REL = Decimal("1e-20")
LOT_SRC_WIN = 16
LOT_FRAG_MAX = 8
Frag = Tuple[Decimal, Optional[Decimal], Optional[int]]
_ZERO, _ONE = Decimal(0), Decimal(1)
_NORM_HI = 1 / LOT_SCALE_NORM


class _GroupCore(TypedDict):
    gid: int
    sym: str
    chains: Set[str]
    is_stable: bool
    is_fiat: bool
    qty_known: Decimal
    cost: Decimal
    qty_unknown: Decimal
    realized: Decimal
    flows: List[dict]
    cur: Optional[dict]
    transit: Decimal
    qty_timeline: List[Tuple[Any, Decimal]]


class GroupState(_GroupCore, total=False):
    oa: Any
    _cp: Any


class LotMismatch(ValueError):
    pass


class Lot:
    __slots__ = ("qty", "cost", "ts", "src", "seq", "hint", "unit_cost_krw")

    def __init__(self, qty: Decimal, cost: Optional[Decimal], ts: Any, src: Any, seq: int, hint: Optional[Decimal] = None) -> None:
        self.qty, self.cost, self.ts, self.src, self.seq, self.hint = qty, cost, ts, src, seq, hint
        self.unit_cost_krw: Optional[Decimal] = None

    def unit_cost(self, qs: Decimal = _ONE, cs: Decimal = _ONE) -> Optional[Decimal]:
        if self.cost is None or self.qty <= 0:
            return None
        return (self.cost * cs) / (self.qty * qs)


def _ts(ts: Any) -> Optional[int]:
    return int(ts) if ts is not None else None


def _hints(lots: List[Lot]) -> List[Decimal]:
    ws = [x.hint for x in lots]
    return [w for w in ws if w is not None] if all(w is not None for w in ws) and sum((w for w in ws if w is not None), _ZERO) != 0 \
        else [x.qty for x in lots]


def _spread(lots: List[Lot], amt: Decimal, ws: List[Decimal], cs: Decimal) -> None:
    tot = sum(ws, _ZERO)
    if tot == 0:
        ws, tot = [_ONE] * len(lots), Decimal(len(lots))
    left = amt
    for i, (lot, w) in enumerate(zip(lots, ws)):
        part = left if i == len(lots) - 1 else amt * w / tot
        left -= part
        lot.cost = (lot.cost if lot.cost is not None else _ZERO) + part / cs


def _squash(frags: List[Frag]) -> List[Frag]:
    n = len(frags)
    if n <= LOT_FRAG_MAX:
        return list(frags)
    out: List[Frag] = []
    for b in range(LOT_FRAG_MAX):
        part = frags[b * n // LOT_FRAG_MAX:(b + 1) * n // LOT_FRAG_MAX]
        cs = [c for _q, c, _t in part if c is not None]
        ts = [t for _q, _c, t in part if t is not None]
        out.append((sum((q for q, _c, _t in part), _ZERO), sum(cs, _ZERO) if cs else None, min(ts) if ts else None))
    return out


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= max(LOT_TOL_ABS, abs(b) * LOT_TOL_REL)


class LotBook:
    __slots__ = ("g", "known", "unknown", "qs", "cs", "resid", "ures", "broken", "merges", "norms", "fr")

    def __init__(self, g: dict) -> None:
        self.g = g
        self.known: Deque[Lot] = deque()
        self.unknown: Deque[Lot] = deque()
        self.qs, self.cs, self.resid, self.ures = _ONE, _ONE, _ZERO, _ZERO
        self.broken: Optional[str] = None
        self.merges = self.norms = 0
        self.fr: Optional[List[Frag]] = None

    def eff(self) -> List[Tuple[Lot, Decimal, Optional[Decimal]]]:
        return [(x, x.qty * self.qs, None if x.cost is None else x.cost * self.cs) for x in self.known]

    def norm(self) -> None:
        for x in self.known:
            x.qty *= self.qs
            if x.cost is not None:
                x.cost *= self.cs
        self.qs = self.cs = _ONE
        self.norms += 1

    def _merge(self, dq: Deque[Lot]) -> None:
        while len(dq) > LOT_MERGE_AT:
            a, b = dq.popleft(), dq.popleft()
            a.qty += b.qty
            a.cost = None if a.cost is None and b.cost is None else (a.cost or _ZERO) + (b.cost or _ZERO)
            a.ts = b.ts if a.ts is None or (b.ts is not None and b.ts < a.ts) else a.ts
            a.hint = None
            dq.appendleft(a)
            self.merges += 1

    def rescale(self, qk0: Decimal, qk1: Decimal, c0: Decimal, c1: Decimal) -> None:
        if qk1 <= 0 or not self.known or qk0 <= 0:
            self.known.clear()
            self.qs, self.cs, self.resid = _ONE, _ONE, c1
            return
        self.qs *= qk1 / qk0
        if c0 != 0:
            f = c1 / c0
            self.cs *= f
            self.resid *= f
        else:
            self.resid += c1 - c0
        if self.cs == 0:
            for x in self.known:
                x.cost = None if x.cost is None else _ZERO
            self.cs = _ONE
        if not (LOT_SCALE_NORM <= self.qs <= _NORM_HI and LOT_SCALE_NORM <= abs(self.cs) <= _NORM_HI):
            self.norm()

    def frags(self, r: Decimal) -> List[Frag]:
        n = len(self.known)
        nb = min(n, LOT_FRAG_MAX)
        out: List[Frag] = []
        it = iter(self.known)
        for b in range(nb):
            part = list(islice(it, (b + 1) * n // nb - b * n // nb))
            cl = [x.cost for x in part if x.cost is not None]
            hl = [x.hint for x in part if x.cost is None and x.hint is not None]
            ce = sum(cl, _ZERO) * self.cs * r if cl else (sum(hl, _ZERO) * r if hl else None)
            out.append((sum([x.qty for x in part], _ZERO) * self.qs * r, ce, min((x.ts for x in part if x.ts is not None), default=None)))
        return out

    def put_known(self, q: Decimal, c: Optional[Decimal], ts: Any, src: Any, nxt: Callable[[], int], frags: Optional[List[Frag]]) -> None:
        if not frags:
            lot = Lot(q / self.qs, None if c is None else (c + self.resid) / self.cs, None if ts is None else int(ts), src, nxt())
            if c is not None:
                self.resid = _ZERO
            self.known.append(lot)
            if len(self.known) > LOT_MERGE_AT:
                self._merge(self.known)
            return
        fs = _squash(frags)
        fq = sum((f[0] for f in fs), _ZERO)
        if fq > 0:
            k = q / fq
            new = [Lot(fqty * k / self.qs, None, fts, src, nxt(), None if fcost is None else fcost * k) for fqty, fcost, fts in fs]
        else:
            new = [Lot(q / self.qs, None, _ts(ts), src, nxt())]
        self.known.extend(new)
        if c is not None:
            _spread(new, c + self.resid, _hints(new), self.cs)
            self.resid = _ZERO
        self._merge(self.known)

    def capitalize(self, c: Decimal, src: Any) -> None:
        if c == 0:
            return
        if not self.known:
            self.resid += c
            return
        tail: List[Lot] = []
        if src is not None:
            for i, x in enumerate(reversed(self.known)):
                if x.src == src:
                    tail.append(x)
                elif tail or i >= LOT_SRC_WIN:
                    break
        pend = [x for x in tail if x.cost is None]
        if pend:
            _spread(pend, c, _hints(pend), self.cs)
            return
        pick = tail or list(self.known)
        _spread(pick, c, [x.qty for x in pick], self.cs)

    def take_unknown(self, d: Decimal) -> None:
        dq = self.unknown
        while d > 0 and dq:
            x = dq[0]
            if x.qty <= d:
                d -= x.qty
                dq.popleft()
            else:
                x.qty -= d
                d = _ZERO
        self.ures -= d

    def put_unknown(self, u: Decimal, ts: Any, src: Any, nxt: Callable[[], int]) -> None:
        if u > 0:
            self.unknown.append(Lot(u, None, _ts(ts), src, nxt()))
            self._merge(self.unknown)
        elif u < 0:
            self.take_unknown(-u)

    def convert(self, q: Decimal, c: Decimal, ts: Any, src: Any, nxt: Callable[[], int]) -> None:
        dq, left, pcs = self.unknown, q, []
        if src is not None:
            for i in range(len(dq) - 1, max(-1, len(dq) - 1 - LOT_SRC_WIN), -1):
                x = dq[i]
                if x.src == src and left > 0 and x.qty > 0:
                    t = min(left, x.qty)
                    pcs.append((t, x.ts, x.src))
                    x.qty -= t
                    left -= t
        while left > 0 and dq:
            x = dq[-1]
            t = min(left, x.qty)
            if t > 0:
                pcs.append((t, x.ts, x.src))
            x.qty -= t
            left -= t
            if x.qty <= 0:
                dq.pop()
        if src is not None and any(x.qty <= 0 for x in dq):
            self.unknown = deque(x for x in dq if x.qty > 0)
        if left > 0:
            pcs.append((left, _ts(ts), src))
            self.ures -= left
        new = [Lot(t / self.qs, None, t_ts, t_src, nxt()) for t, t_ts, t_src in pcs]
        self.known.extend(new)
        _spread(new, c, [t for t, _a, _b in pcs], self.cs)
        self._merge(self.known)

    def audit(self, g: dict) -> List[str]:
        if self.broken is not None:
            return ["로트 고장(%s)" % self.broken]
        out = []
        sk = sum((x.qty for x in self.known), _ZERO) * self.qs
        sc = sum((x.cost for x in self.known if x.cost is not None), _ZERO) * self.cs + self.resid
        su = sum((x.qty for x in self.unknown), _ZERO) + self.ures
        for name, s, cell in (("qty_known", sk, g["qty_known"]), ("cost", sc, g["cost"]), ("qty_unknown", su, g["qty_unknown"])):
            if not _close(s, cell):
                out.append("%s 로트 %s ≠ 칸 %s" % (name, s, cell))
        return out


def _broke(bk: LotBook, site: str, e: Exception) -> Exception:
    bk.broken = "%s: %s" % (site, type(e).__name__)
    return e


def _guard(bk: LotBook, site: str, fn: Callable[..., Any], *a: Any) -> Any:
    try:
        return fn(*a)
    except Exception as e:  # noqa: BLE001 [isolate]
        calcguard.swallowed("accounting_basis.convert[lots]", _broke(bk, site, e))
        return None


class CostBasis:

    def __init__(self) -> None:
        self._lots: dict = {}
        self._pool: dict = {}
        self._nxt = count(1).__next__

    def _bk(self, g: dict) -> Optional[LotBook]:
        bk = self._lots.get(id(g))
        return bk if bk is not None and bk.g is g and bk.broken is None else None

    def new_group(self, gid: int, sym: str, is_stable: bool, is_fiat: bool) -> dict:
        g = {
            "gid": gid, "sym": sym, "chains": set(), "is_stable": is_stable, "is_fiat": is_fiat,
            "qty_known": Decimal(0), "cost": Decimal(0), "qty_unknown": Decimal(0),
            "realized": Decimal(0), "flows": [], "cur": None, "transit": Decimal(0),
            "qty_timeline": [],
        }
        self._lots[id(g)] = LotBook(g)
        return g

    def lots_of(self, g: dict) -> Optional[LotBook]:
        bk = self._lots.get(id(g))
        return bk if bk is not None and bk.g is g else None

    def pool_put(self, ent: dict, frags: Optional[List[Frag]]) -> None:
        if frags:
            old = self._pool.get(id(ent))
            if old is not None and old[0] is ent:
                old[1].extend(frags)
                if len(old[1]) > 2 * LOT_FRAG_MAX:
                    old[1][:] = _squash(old[1])
            else:
                self._pool[id(ent)] = (ent, list(frags))

    def pool_lots(self, ent: Any) -> Optional[List[Frag]]:
        hit = self._pool.get(id(ent))
        if hit is None or hit[0] is not ent:
            return None
        lf = ent.get("left")
        if ent.get("used") or (lf is not None and lf <= 0):
            del self._pool[id(ent)]
        return hit[1]

    def take_frags(self, g: dict) -> Optional[List[Frag]]:
        bk = self._bk(g)
        if bk is None:
            return None
        fr, bk.fr = bk.fr, None
        return fr

    def acquire(self, g: dict, q: Optional[Decimal] = None, c: Optional[Decimal] = None, *, ts: Any = None, src: Any = None,
                u: Optional[Decimal] = None, lots: Optional[List[Frag]] = None) -> None:
        bk = self._bk(g)
        neg = bk is not None and q is not None and q < 0
        qk0, c0 = (g["qty_known"], g["cost"]) if neg else (_ZERO, _ZERO)
        if q is not None:
            g["qty_known"] += q
        if c is not None:
            g["cost"] += c
        if u is not None:
            g["qty_unknown"] += u
        if bk is None:
            return
        try:
            if q is not None and q > 0:
                bk.put_known(q, c, ts, src, self._nxt, lots)
            elif neg:
                bk.rescale(qk0, g["qty_known"], c0, g["cost"])
            elif c is not None:
                bk.capitalize(c, src)
            if u is not None:
                bk.put_unknown(u, ts, src, self._nxt)
        except Exception as e:  # noqa: BLE001 [isolate]
            calcguard.swallowed("accounting_basis.acquire[lots]", _broke(bk, "acquire", e))

    def capitalize(self, g: dict, c: Decimal, *, ts: Any = None, src: Any = None) -> None:
        g["cost"] += c
        bk = self._bk(g)
        if bk is not None:
            try:
                bk.capitalize(c, src)
            except Exception as e:  # noqa: BLE001 [isolate]
                calcguard.swallowed("accounting_basis.capitalize[lots]", _broke(bk, "capitalize", e))

    def release(self, g: dict, k: Optional[Decimal], c: Optional[Decimal], u: Decimal, *, floor: bool = True,
                lots: bool = False) -> Optional[List[Frag]]:
        bk = self._bk(g)
        s0 = (g["qty_known"], g["cost"], g["qty_unknown"]) if bk is not None else None
        if k is not None:
            g["qty_known"] -= k
        if c is not None:
            g["cost"] -= c
        g["qty_unknown"] = max(Decimal(0), g["qty_unknown"] - u) if floor else g["qty_unknown"] - u
        if bk is None or s0 is None:
            return None
        try:
            fr = _lot_release(bk, g, s0, (k, k is not None or c is not None), lots)
        except Exception as e:  # noqa: BLE001 [isolate]
            calcguard.swallowed("accounting_basis.release[lots]", _broke(bk, "release", e))
            return None
        return fr if lots else None

    def convert(self, g: dict, q: Decimal, c: Decimal, *, ts: Any = None, src: Any = None) -> None:
        bk = self._bk(g)
        s0 = (g["qty_known"], g["cost"], g["qty_unknown"]) if bk is not None else None
        g["qty_unknown"] -= q
        g["qty_known"] += q
        g["cost"] += c
        if bk is not None:
            _guard(bk, "convert", _lot_convert, bk, g, s0, (q, c, ts, src), self._nxt)

    def realize(self, g: dict, p: Decimal) -> None:
        g["realized"] += p

    def unrealize(self, g: dict, p: Decimal) -> None:
        g["realized"] -= p

    def snapshot(self, g: dict, ts: Any, dq: Decimal) -> None:
        g["qty_timeline"].append((ts, dq))

    def wac(self, g: dict) -> Decimal:
        return (g["cost"] / g["qty_known"]) if g["qty_known"] > EPS else Decimal(0)

    def wac_or_none(self, g: dict) -> Optional[Decimal]:
        return (g["cost"] / g["qty_known"]) if g["qty_known"] > EPS else None

    def lots_audit(self, G: dict, where: str) -> List[str]:
        bad = []
        for gid, g in G.items():
            bk = self.lots_of(g)
            for m in (["로트 장부 없음"] if bk is None else bk.audit(g)):
                bad.append("%s 그룹 %s: %s" % (where, gid, m))
        return bad

    def lots_live(self, G: dict, where: str) -> None:
        bad = self.lots_audit(G, where)
        if bad:
            calcguard.swallowed("accounting_basis.lots_audit[replay]", LotMismatch("%s %d건: %s" % (where, len(bad), " · ".join(bad[:3]))))

    def lots_stats(self, G: dict) -> dict:
        st = {"known": 0, "unknown": 0, "max": 0, "pending": 0, "merges": 0, "norms": 0, "broken": 0}
        for g in G.values():
            bk = self.lots_of(g)
            if bk is None:
                continue
            nk, nu = len(bk.known), len(bk.unknown)
            st["known"] += nk
            st["unknown"] += nu
            st["max"] = max(st["max"], nk + nu)
            st["pending"] += sum(1 for x in bk.known if x.cost is None)
            st["merges"] += bk.merges
            st["norms"] += bk.norms
            st["broken"] += bk.broken is not None
        return st


def _lot_release(bk: LotBook, g: dict, s0: Tuple[Decimal, Decimal, Decimal], kt: Tuple[Optional[Decimal], bool], lots: bool) -> List[Frag]:
    fr: List[Frag] = []
    k, touched = kt
    if touched:
        if lots and k is not None and k > 0 and s0[0] > 0 and bk.known:
            fr = bk.frags(min(k / s0[0], _ONE))
        bk.rescale(s0[0], g["qty_known"], s0[1], g["cost"])
    d = s0[2] - g["qty_unknown"]
    if d != 0:
        bk.take_unknown(d)
    bk.fr = fr if lots else None
    return fr


def _lot_convert(bk: LotBook, g: dict, s0: Tuple[Decimal, Decimal, Decimal], a: tuple, nxt: Callable[[], int]) -> None:
    q, c, ts, src = a
    if q > 0:
        bk.convert(q, c, ts, src, nxt)
        return
    bk.rescale(s0[0], g["qty_known"], s0[1], g["cost"])
    bk.take_unknown(s0[2] - g["qty_unknown"])


class StrictCostBasis(CostBasis):

    def __init__(self) -> None:
        super().__init__()
        self.shadow: dict = {}
        self.stray: set = set()

    def _sh(self, g: dict) -> dict:
        sh = self.shadow.get(id(g))
        if sh is None:
            self.stray.add(id(g))
            return _blank()
        return sh

    def new_group(self, gid: int, sym: str, is_stable: bool, is_fiat: bool) -> dict:
        g = super().new_group(gid, sym, is_stable, is_fiat)
        self.shadow[id(g)] = {k: (list(g[k]) if k == "qty_timeline" else g[k]) for k in _FIVE}
        return g

    def check(self, G: dict, where: str) -> None:
        bad = []
        for gid, g in G.items():
            sh = self.shadow.get(id(g))
            if sh is None or [str(g[k]) for k in _FIVE[:4]] != [str(sh[k]) for k in _FIVE[:4]] \
                    or len(g["qty_timeline"]) != len(sh["qty_timeline"]):
                bad.append(f"{gid}{'(new_group 밖)' if sh is None else ''}")
        if bad or self.stray:
            raise AssertionError(f"원가 칸 우회 쓰기({where}): 그룹 {', '.join(bad[:20])}{' …' if len(bad) > 20 else ''}"
                                 f"{f' · new_group 밖 그룹 쓰기 {len(self.stray)}' if self.stray else ''} — 원가 칸은 CostBasis 로만")
        lb = self.lots_audit(G, where)
        if lb:
            raise AssertionError(f"로트 합 ≠ 원가 칸({where}) {len(lb)}건: {' · '.join(lb[:10])}{' …' if len(lb) > 10 else ''}")


_FIVE = ("qty_known", "cost", "qty_unknown", "realized", "qty_timeline")
_WRITES = ("acquire", "capitalize", "release", "convert", "realize", "unrealize", "snapshot")


def _blank() -> dict:
    return {"qty_known": Decimal(0), "cost": Decimal(0), "qty_unknown": Decimal(0), "realized": Decimal(0), "qty_timeline": []}


def _twin(name: str) -> Any:
    base = getattr(CostBasis, name)

    def twin(self: StrictCostBasis, g: dict, *args: Any, **kw: Any) -> Any:
        out = base(self, g, *args, **kw)
        base(self, self._sh(g), *args, **kw)
        return out
    twin.__name__, twin.__qualname__ = name, f"StrictCostBasis.{name}"
    twin.__doc__ = f"{base.__doc__} + 그림자 장부에 같은 연산(반환 = 원본 쪽)."
    return twin


for _n in _WRITES:
    setattr(StrictCostBasis, _n, _twin(_n))
del _n
