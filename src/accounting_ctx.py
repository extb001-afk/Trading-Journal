from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True, eq=False, repr=False)
class ReplayCtx:
    conn: Any
    prefs: dict
    fb_on: bool
    fs_pref: bool
    fs_on: bool
    gas_on: bool
    offc_on: Any
    offc_ans: Any
    offc_excl: Any
    now: float
    today_kst: Any
    fxb: Any

    @classmethod
    def names(cls) -> tuple:
        return tuple(f.name for f in fields(cls))


def check_ctx(ctx: ReplayCtx, scope: dict, where: str) -> None:
    bad = [n for n in ReplayCtx.names() if n in scope and scope[n] is not getattr(ctx, n)]
    if bad:
        raise AssertionError(f"입력 묶음 별칭 끊김({where}): {', '.join(bad)} — 읽기 전용 입력을 다시 묶지 말 것")
