from __future__ import annotations

from dataclasses import dataclass, field, fields
from decimal import Decimal


def _gas_applied() -> dict:
    return {"buy": Decimal(0), "sell": Decimal(0), "n": 0}


@dataclass(eq=False, repr=False)
class Books:
    gas_applied: dict = field(default_factory=_gas_applied)
    gas_expense: dict = field(default_factory=dict)
    ex_fee: dict = field(default_factory=dict)
    ex_fee_m: dict = field(default_factory=dict)
    fee_day: dict = field(default_factory=dict)
    wd_fee: dict = field(default_factory=dict)
    wd_fee_m: dict = field(default_factory=dict)
    gas_by_chain: dict = field(default_factory=dict)
    gas_by_month: dict = field(default_factory=dict)
    gas_nopx: dict = field(default_factory=dict)
    tax_rows: list = field(default_factory=list)
    realized_by_date: dict = field(default_factory=dict)
    realized_krw_by_date: dict = field(default_factory=dict)
    realized_by_loc: dict = field(default_factory=dict)
    extra_events: list = field(default_factory=list)
    cp_ev: dict = field(default_factory=dict)
    lp_events: list = field(default_factory=list)

    @classmethod
    def names(cls) -> tuple:
        return tuple(f.name for f in fields(cls))


def check_aliases(books: Books, scope: dict, where: str) -> None:
    bad = [n for n in Books.names() if n in scope and scope[n] is not getattr(books, n)]
    if bad:
        raise AssertionError(f"결과 장부 별칭 끊김({where}): {', '.join(bad)} — 단계 사이에 이름을 다시 묶지 말 것(제자리 수정만)")
