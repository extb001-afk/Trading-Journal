from __future__ import annotations

import types
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


def check_replay(ctx: ReplayCtx, scope: dict, where: str) -> None:
    check_ctx(ctx, scope, where)
    check_parts(scope["px"], scope, where)
    check_inputs(scope["px"], scope, where)


INJECT = {
    "cpx": ("kst_fmt", "krw_mix", "consume_krw", "krw_last", "oa_take", "cp_ev", "cp_pool", "cb"),
    "lpx": ("sb", "consume_krw", "cp_emit", "cp_sync", "cp_take", "cur_lab", "cur_row", "cur_src", "ev", "flow_of", "fxb", "krw_of", "lp_events", "note_unk", "realized_by_date", "realized_krw_by_date", "tax_krw_acq", "tax_rows", "cb"),
    "fsx": ("sb", "fs_sum", "fxb", "now", "krw_of", "fs_last", "kst_fmt", "cb"),
    "slx": ("sb", "cp_add_map", "cp_emit", "cp_merge", "cur_lab", "cur_row", "cur_src", "ev", "flow_of", "fs_last", "fs_mark", "fs_rec", "fx_name", "fxb", "krw_last", "krw_mix", "krw_of", "krw_stl", "note_unk", "oa_last", "offc_sold", "realized_by_date", "realized_by_loc", "realized_krw_by_date", "ret_pool", "stable_fx_mark", "tax_krw_acq", "tax_rows", "wd_raw9", "cb"),
    "lnx": ("consume_krw", "cp_emit", "cp_take", "cur_row", "cur_src", "ev", "fee_gain", "flow_of", "fs_sales", "fs_sum", "fx_name", "krw_mix", "krw_stl", "oa_take", "tax_rows", "cb"),
    "omx": ("sb", "consume", "cp_last", "cp_merge", "diag", "ev", "extra_events", "fs_on", "fs_rec", "fx_dep_tx", "fx_name", "krw_rec", "krw_took", "mv_note", "now", "ob", "of_pay_on", "of_pay_take", "ret_pool", "rt_out", "sale_lot_by", "sale_pay_take", "sale_rf_bid", "sale_rf_load", "stl_out", "up_dep_by_tx", "cb"),
}
HELD = {
    "fbx": ("cb",),
    "unx": ("cb",),
}

LATE_WIRES = {
    "fbx": ("wd_raw9", "fxb", "fs_last", "fs_mark", "stable_fx_mark", "flow_of", "WD_FEE_IN_AMT", "cur_lab"),
    "kpx": ("fs_last", "krw_mix", "krw_flow", "krw_stl", "krw_last", "STL_TOP", "tx_legsym"),
    "fsx": ("note_unk", "ub_wd_tx", "krw_last", "cp_add", "cp_add_map", "flow_of"),
    "cpx": ("xc_tok9", "xc_stx9", "xc_blk9", "cp_xrec", "cur_src", "cur_row"),
    "unx": ("fs_sum", "fs_why", "fs_conv", "_un", "ev"),
    "slx": ("sale_pay_q_d", "of_pay_on", "of_wd_cap", "of_pay_cap"),
    "lpx": ("lp_label",),
    "ofx": ("offc_sold",),
}
CYCLE = (("fsx", "note_unk", "unx"), ("unx", "fs_why", "fsx"), ("unx", "fs_conv", "fsx"))

ALIASES = {
    "ofx": ("offc_s", "offc_addr_add", "offc_add"),
}


class ReplayParts:
    __slots__ = ("sb", "ctx", "books", "cb", "fbx", "ofx", "kpx", "unx", "fsx", "orx", "cpx", "lpx", "slx", "lnx", "omx")

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

INPUTS = {
    "ofx": (
        ("offcin", (("fx_name", "fx_name"), ("offc_ans", "offc_ans"), ("offc_excl", "offc_excl"), ("offc_on", "offc_on"),
            ("offc_pool", "offc_pool"), ("offc_st", "offc_st"), ("offc_wd_addr", "offc_wd_addr"),)),
    ),
    "fsx": (
        ("fsin", (("conn", "conn"), ("fs_aux", "fs_aux"), ("fs_kit", "fs_kit"), ("fs_spec", "fs_spec9"), ("fs_floor", "fs_floor9"),
            ("fs_lo", "fs_lo9"), ("fs_memo", "fs_memo"), ("fs_need", "fs_need"), ("fs_sales", "fs_sales"), ("ret_kit", "ret_kit"),
            ("ret_pool", "ret_pool"), ("fs_pin", "fs_pin"), ("fs_pin_new", "fs_pin_new"), ("fs_pref", "fs_pref"), ("fx_wd", "fx_wd"),
            ("fs_okc", "fs_okc"),)),
    ),
    "orx": (
        ("originin", (("conn", "conn"), ("origin_cache", "origin_cache"), ("raw_chains", "raw_chains9"), ("snap_cache", "snap_cache"),)),
    ),
    "lpx": (
        ("lpin", (("lp_by_tx", "lp_by_tx"), ("lp_dep_seen", "lp_dep_seen"), ("lp_meta_by", "lp_meta_by"), ("lp_mgrs", "lp_mgrs"),
            ("lp_tx_rows", "lp_tx_rows"), ("lpb", "lpb"),)),
        ("fns", (("ak", "_ak"),)),
    ),
    "slx": (
        ("salein", (("ro", "_ro"), ("arr_tx_chain", "arr_tx_chain"), ("be_done", "be_done"), ("be_tax", "be_tax"), ("diag", "diag"),
            ("fx_dep_tx", "fx_dep_tx"), ("ob", "ob"), ("of_applied", "of_applied"), ("of_cands", "of_cands"), ("rt_out", "rt_out"),
            ("sale_links", "sale_links"), ("sale_lot_by", "sale_lot_by"), ("sale_pay_bid", "sale_pay_bid"), ("sale_pay_q", "sale_pay_q"),
            ("sale_pay_seq", "sale_pay_seq"), ("sale_rf_bid", "sale_rf_bid"), ("sale_rf_exit", "sale_rf_exit"), ("sale_used", "sale_used"),
            ("unverified", "unverified"), ("up_dep_by_tx", "up_dep_by_tx"), ("wd_tr", "wd_tr"), ("xf_wd", "xf_wd9"),)),
        ("fns", (("be_take", "be_take"), ("unk_tag", "unk_tag"),)),
    ),
    "omx": (
        ("movein", (("ro", "_ro"), ("br_transit", "br_transit"), ("ever_in", "ever_in"), ("ex_transit", "ex_transit"),
            ("fxdep_transit", "fxdep_transit"), ("my_all", "my_all9"), ("of_bridge", "of_bridge"), ("of_dec", "of_dec9"), ("of_match", "of_match"),
            ("of_noauto", "of_noauto"), ("rt_back", "rt_back"), ("rt_same", "rt_same"), ("rt_transit", "rt_transit"), ("sale_bid", "sale_bid9"),
            ("signer", "signer9"), ("up_dep_uid_ts", "up_dep_uid_ts"), ("up_win_t0", "up_win_t0"),)),
        ("fns", (("cv_label", "cv_label"), ("extra_ev", "extra_ev"),)),
    ),
}


def _same(a, b) -> bool:
    if isinstance(a, types.MethodType):
        return isinstance(b, types.MethodType) and a == b
    return a is b


def check_parts(px: ReplayParts, scope: dict, where: str) -> None:
    bad = []
    for table in (INJECT, LATE_WIRES, ALIASES, HELD):
        for slot, names in table.items():
            obj = getattr(px, slot)
            for n in names:
                loc = "self" if n == "sb" else n
                if loc not in scope:
                    bad.append(f"{slot}.{n}(이름표에 {loc} 없음)")
                elif not _same(getattr(obj, n), scope[loc]):
                    bad.append(f"{slot}.{n}")
    if bad:
        raise AssertionError(f"장부 묶음 주입·늦은 연결 신원 끊김({where}): {', '.join(bad)} — 주입 이름을 다시 묶거나 속성을 다시 대입하지 말 것")


def check_inputs(px: ReplayParts, scope: dict, where: str) -> None:
    bad = []
    for slot, ents in INPUTS.items():
        obj = getattr(px, slot)
        for bv, pairs in ents:
            if bv not in scope:
                bad.append(f"{bv}(이름표에 없음)")
                continue
            b = scope[bv]
            for f, loc in pairs:
                if loc not in scope:
                    bad.append(f"{bv}.{f}(이름표에 {loc} 없음)")
                elif getattr(b, f) is not scope[loc]:
                    bad.append(f"{bv}.{f}")
                elif getattr(obj, loc) is not scope[loc]:
                    bad.append(f"{slot}.{loc}")
    if bad:
        raise AssertionError(f"입력 묶음 신원 끊김({where}): {', '.join(bad)} — 묶음에 담은 이름을 다시 묶거나 장부 속성을 다시 대입하지 말 것")
