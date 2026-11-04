from __future__ import annotations

from typing import Any

POINT_KRW = frozenset({("bithumb", "P")})


def own_px(spot: Any, ex: str, sym: str) -> float | None:
    if (ex, sym) in POINT_KRW:
        return 1.0 / spot.rate if spot.rate else None
    return spot.ex_price(ex, sym)
