from __future__ import annotations

import pickle
import zlib
from dataclasses import dataclass, field, fields
from decimal import Decimal
from typing import Any, Callable


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


def check_pool_aliases(scope: dict, names: str, vals: tuple, where: str) -> None:
    keys = names.split()
    if len(keys) != len(vals):
        raise AssertionError(f"풀 별칭 확인({where}): 이름 {len(keys)}개 ≠ 값 {len(vals)}개")
    bad = [n for n, v in zip(keys, vals) if not scope[n] == v]
    if bad:
        raise AssertionError(f"풀 별칭 끊김({where}): {', '.join(bad)} — 앞 단계 별칭이 풀 객체 메서드와 다름")


OLD = {"ak": "_ak", "bf_since": "_bf_since", "debt_capg": "debt_capg9", "debt_neg": "debt_neg9", "debt_over": "debt_over9",
       "debt_take": "debt_take9", "dep_tr": "dep_tr9", "exb": "exb9", "fb_cov": "fb_cov9", "fs_floor": "fs_floor9",
       "hl_cash_syms": "hl_cash_syms9", "my_all": "my_all9", "of_dec": "of_dec9", "pv_dl": "pv_dl9", "pv_led": "pv_led9",
       "pv_unk": "pv_unk9", "qfmt": "_qfmt", "signer": "signer9", "tok_pairs": "tok_pairs9", "ub_snap": "ub_snap9", "uf_dl": "uf_dl9",
       "unv_fb": "unv_fb9", "xp_unk": "xp_unk9"}


@dataclass(frozen=True, eq=False, repr=False)
class ReplayResult:
    books: Books
    ctx: "accounting_ctx.ReplayCtx"   # noqa: F821
    G: Any
    bf_since: Any
    qfmt: Any
    backfill_t0: Any
    be_done: Any
    cost_be: Any
    cost_ov: Any
    cur_src: Any
    debt_capg: Any
    debt_neg: Any
    debt_over: Any
    debt_take: Any
    diag: Any
    ex_gid: Any
    ex_transit: Any
    exb: Any
    fb_cov: Any
    fee_diag: Any
    fs_floor: Any
    fs_need: Any
    fs_pin_new: Any
    fs_rbd: Any
    fs_sum: Any
    fx_dep_tx: Any
    fx_name: Any
    fx_transit: Any
    fx_wd: Any
    gid_pairs: Any
    hl_cash_syms: Any
    hl_neg: Any
    led_by_gid: Any
    led_upbit_gids: Any
    live: Any
    locs_by_gid: Any
    lp_by_tx: Any
    lp_meta_by: Any
    lp_mgrs: Any
    lp_pos_rows: Any
    lpb: Any
    my_all: Any
    noproc: Any
    ob: Any
    of_applied: Any
    of_bridge: Any
    of_cands: Any
    of_dec: Any
    of_deps: Any
    of_match: Any
    of_sends: Any
    offc_dep: Any
    offc_summary: Any
    offc_wd: Any
    offc_wd_addr: Any
    origin_cache: Any
    origin_pending: Any
    pid_row: Any
    pos_rows: Any
    price_groups: Any
    pv_dl: Any
    pv_led: Any
    pv_unk: Any
    resolve_origin: Any
    rows: Any
    sale_links: Any
    sale_lot_by: Any
    sale_lots: Any
    sale_rf_bid: Any
    sale_used: Any
    signer: Any
    spoof_keys: Any
    stake_inc: Any
    stake_rwd: Any
    tok_pairs: Any
    ub_snap: Any
    ub_wd_shown: Any
    ub_wd_tx: Any
    uf_dl: Any
    uncred_cost: Any
    uncred_fx: Any
    uncred_gid: Any
    uncred_known: Any
    unv_fb: Any
    unverified: Any
    upbit_transit_gids: Any
    wallet_label: Any
    wdt_all: Any
    wdt_gid: Any
    xc_cands: Any
    xc_used: Any
    xf_links: Any
    xp_unk: Any
    ak: Any
    be_until: Any
    extra_ev: Any
    oc_fresh: Any
    offc_self_wd: Any
    dep_tr: Any
    _scope: Any = field(default=None, compare=False, repr=False)
    _cb: Any = field(default=None, compare=False, repr=False)

    @classmethod
    def old_names(cls) -> tuple:
        return ("books", "ctx") + Books.names() + tuple(OLD.get(f, f) for f in _EDGE)

    @classmethod
    def from_scope(cls, scope: dict) -> ReplayResult:
        return cls(_scope=scope, _cb=scope.get("cb"), **{f: scope[OLD.get(f, f)] for f in _CONTRACT})

    def as_old_names(self) -> dict:
        out = {"books": self.books, "ctx": self.ctx}
        out.update((n, getattr(self.books, n)) for n in Books.names())
        out.update((OLD.get(f, f), getattr(self, f)) for f in _EDGE)
        return out

    def screen_scope(self, inval: Any) -> dict:
        out = self.as_old_names()
        out["daily_inval"] = inval
        return out


_CONTRACT = tuple(f.name for f in fields(ReplayResult) if f.name not in ("_scope", "_cb"))
_EDGE = _CONTRACT[2:]


def check_rr(rr: ReplayResult, scope: dict, where: str, check_ctx: Callable) -> None:
    check_aliases(rr.books, scope, where)
    check_ctx(rr.ctx, scope, where)
    bad = [f for f in _CONTRACT if OLD.get(f, f) not in scope or scope[OLD.get(f, f)] is not getattr(rr, f)]
    if bad:
        raise AssertionError(f"리플레이 결과 필드 끊김({where}): {', '.join(bad)} — 이름표 값과 같은 객체여야 함")


SCREEN_WRITES = {
    "_build_cards": frozenset({"realized_by_date", "realized_krw_by_date", "tax_rows"}),
    "_build_pendings": frozenset({"extra_events"}),
    "_build_outflows": frozenset({"extra_events", "cp_ev"}),
}
SCREEN_WRITES_DATA = {
    "_build_cards": frozenset({"fb_cov9", "unv_fb9", "diag"}),
    "_build_pendings": frozenset({"cur_src", "debt_over9"}),
    "_build_daily": frozenset({"fs_sum", "diag"}),
    "_build_tail": frozenset({"diag", "fs_sum"}),
}


def books_seal(books: Books) -> dict:
    out = {}
    for n in Books.names():
        b = pickle.dumps(getattr(books, n), protocol=5)
        out[n] = (len(b), zlib.crc32(b))
    return out


def books_check(seal: dict, books: Books, stage: str) -> dict:
    new = books_seal(books)
    bad = sorted(n for n in new if new[n] != seal.get(n) and n not in SCREEN_WRITES.get(stage, ()))
    if bad:
        raise AssertionError(f"화면 단계 장부 쓰기({stage}): {', '.join(bad)} — 선언(SCREEN_WRITES) 밖")
    return new


def screen_check(seal: dict, rr: ReplayResult, scope: dict, stage: str, check_ctx: Callable) -> dict:
    check_aliases(rr.books, scope, stage)
    check_ctx(rr.ctx, scope, stage)
    if callable(getattr(rr._cb, "check", None)):
        rr._cb.check(rr.G, stage)
    return books_check(seal, rr.books, stage)
