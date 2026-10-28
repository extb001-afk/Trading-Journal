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


class ReplayParts:
    __slots__ = ("sb", "ctx", "books", "cb", "fbx", "ofx", "kpx", "unx", "fsx", "orx", "cpx", "lpx", "slx", "lnx", "omx",
                 "flow_of", "tx_legsym", "xc_stx9", "xc_blk9", "of_pay_on")

    def __init__(self, sb, books):
        self.sb = sb
        self.books = books


@dataclass(frozen=True, eq=False, repr=False)
class OffcIn:
    fx_name: Any
    offc_ans: Any
    offc_excl: Any
    offc_on: Any
    offc_pool: Any
    offc_st: Any
    offc_wd_addr: Any


@dataclass(frozen=True, eq=False, repr=False)
class FsIn:
    conn: Any
    fs_aux: Any
    fs_kit: Any
    fs_spec: Any
    fs_floor: Any
    fs_lo: Any
    fs_memo: Any
    fs_need: Any
    fs_sales: Any
    ret_kit: Any
    ret_pool: Any
    fs_pin: Any
    fs_pin_new: Any
    fs_pref: Any
    fx_wd: Any
    fs_okc: Any


@dataclass(frozen=True, eq=False, repr=False)
class OriginIn:
    conn: Any
    origin_cache: Any
    raw_chains: Any
    snap_cache: Any


@dataclass(frozen=True, eq=False, repr=False)
class ReplayFns:
    be_take: Any
    ak: Any
    extra_ev: Any
    cv_label: Any
    unk_tag: Any


@dataclass(frozen=True, eq=False, repr=False)
class LpIn:
    lp_by_tx: Any
    lp_dep_seen: Any
    lp_meta_by: Any
    lp_mgrs: Any
    lp_tx_rows: Any
    lpb: Any


@dataclass(frozen=True, eq=False, repr=False)
class SaleIn:
    ro: Any
    arr_tx_chain: Any
    be_done: Any
    be_tax: Any
    diag: Any
    fx_dep_tx: Any
    ob: Any
    of_applied: Any
    of_cands: Any
    rt_out: Any
    sale_links: Any
    sale_lot_by: Any
    sale_pay_bid: Any
    sale_pay_q: Any
    sale_pay_seq: Any
    sale_rf_bid: Any
    sale_rf_exit: Any
    sale_used: Any
    unverified: Any
    up_dep_by_tx: Any
    wd_tr: Any
    xf_wd: Any


@dataclass(frozen=True, eq=False, repr=False)
class MoveIn:
    ro: Any
    br_transit: Any
    ever_in: Any
    ex_transit: Any
    fxdep_transit: Any
    my_all: Any
    of_bridge: Any
    of_dec: Any
    of_match: Any
    of_noauto: Any
    rt_back: Any
    rt_same: Any
    rt_transit: Any
    sale_bid: Any
    signer: Any
    up_dep_uid_ts: Any
    up_win_t0: Any
