from __future__ import annotations

from decimal import Decimal
from typing import Any, List, Optional, Set, Tuple, TypedDict

from view_common import EPS

__all__ = ["GroupState", "CostBasis", "StrictCostBasis"]


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


class CostBasis:

    def new_group(self, gid: int, sym: str, is_stable: bool, is_fiat: bool) -> dict:
        return {
            "gid": gid, "sym": sym, "chains": set(), "is_stable": is_stable, "is_fiat": is_fiat,
            "qty_known": Decimal(0), "cost": Decimal(0), "qty_unknown": Decimal(0),
            "realized": Decimal(0), "flows": [], "cur": None, "transit": Decimal(0),
            "qty_timeline": [],
        }

    def add_known(self, g: dict, q: Decimal) -> None:
        g["qty_known"] += q

    def add_unknown(self, g: dict, q: Decimal) -> None:
        g["qty_unknown"] += q

    def add_cost(self, g: dict, c: Decimal) -> None:
        g["cost"] += c

    def acquire(self, g: dict, q: Decimal, c: Decimal) -> None:
        g["qty_known"] += q
        g["cost"] += c

    def sub_known(self, g: dict, q: Decimal) -> None:
        g["qty_known"] -= q

    def sub_unknown(self, g: dict, q: Decimal) -> None:
        g["qty_unknown"] -= q

    def sub_cost(self, g: dict, c: Decimal) -> None:
        g["cost"] -= c

    def release(self, g: dict, k: Decimal, c: Decimal, u: Decimal) -> None:
        g["qty_known"] -= k
        g["cost"] -= c
        g["qty_unknown"] = max(Decimal(0), g["qty_unknown"] - u)

    def floor_sub_unknown(self, g: dict, u: Decimal) -> None:
        g["qty_unknown"] = max(Decimal(0), g["qty_unknown"] - u)

    def convert(self, g: dict, q: Decimal, c: Decimal) -> None:
        g["qty_unknown"] -= q
        g["qty_known"] += q
        g["cost"] += c

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

    def note_cost(self, g: dict, q: Decimal, unit: float) -> None:
        pass


class StrictCostBasis(CostBasis):

    def __init__(self) -> None:
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

    def note_cost(self, g: dict, q: Decimal, unit: float) -> None:
        sh = self._sh(g)
        sh["cost"] += q * Decimal(str(unit))

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


_FIVE = ("qty_known", "cost", "qty_unknown", "realized", "qty_timeline")
_WRITES = ("add_known", "add_unknown", "add_cost", "acquire", "sub_known", "sub_unknown", "sub_cost", "release", "floor_sub_unknown",
           "convert", "realize", "unrealize", "snapshot")


def _blank() -> dict:
    return {"qty_known": Decimal(0), "cost": Decimal(0), "qty_unknown": Decimal(0), "realized": Decimal(0), "qty_timeline": []}


def _twin(name: str) -> Any:
    base = getattr(CostBasis, name)

    def twin(self: StrictCostBasis, g: dict, *args: Any) -> None:
        base(self, g, *args)
        base(self, self._sh(g), *args)
    twin.__name__, twin.__qualname__ = name, f"StrictCostBasis.{name}"
    twin.__doc__ = f"{base.__doc__} + 그림자 장부에 같은 연산."
    return twin


for _n in _WRITES:
    setattr(StrictCostBasis, _n, _twin(_n))
del _n
