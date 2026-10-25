from __future__ import annotations
import accounting_basis
import accounting_books
import accounting_cp
import accounting_ctx
import accounting_fee
import accounting_fs
import accounting_index
import accounting_krw
import accounting_loan
import accounting_lp
import accounting_offc
import accounting_origin
import accounting_outmove
import accounting_sale
import accounting_unk
import accounting_util
import acct_norm
import bf_engine
import bisect
import buychart
import histmark, logs, paths, statefile
import depaddr
import flow_trace
import flowev
import histcurve
import json
import lpdec
import lpsol
import math
import os
import outflow_match
import pricing
import provbal
import rawtx_cache
import re
import sale_match
import salelink
import spamguard
import time
import xchain_match
import xfer_match
from datetime import datetime
from datetime import timedelta
from decimal import Decimal
from decimal import InvalidOperation
from view_common import CHAIN_NAME
from view_common import DAYCLOSE_ON
from view_common import DISC_OPEN_KO
from view_common import DISC_OPEN_KO_UNK
from view_common import EPS
from view_common import EX_CANDLE_SYMS
from timeutil import KST
from view_common import LP_CONV_MIN_USD
from view_common import OF_BASIS_KO
from view_common import OF_NATIVE_SYMS
from view_common import STABLE_GROUPS
from view_common import SUB_SID_RE
from view_common import _ex_stable_sym
from view_common import _f
from view_common import _hl_cash_syms
from view_common import _px_tables
from view_fspin import FS_CAP_X
from view_fspin import FS_EX
from view_fspin import _fs_pin_load
from view_misc import _BuildObsolete
from view_misc import _fx_candle_near
from view_misc import _recon_q
from view_offc import _offc_answered
from view_offc import _offc_excl
from view_offc import _offc_on
from view_offc import _offc_tx
from view_order import NOPX_LEGS_MAX
from view_order import _ord_pair_moves
from view_order import _ord_splice
from view_plans import BR_UNIQ_LO
from view_plans import LOAN_SKIP_EX
from view_plans import _bridge_plan
from view_plans import _loan_plan
from view_plans import _loan_windows
from view_tax import _tax_add
from view_text import _scam_name
from view_txkey import _ton_hash_uids
from view_txkey import _txk
from view_txkey import _wd_txk
import logging
import calcguard  # noqa: E402

log = logging.getLogger('tj-web')


def _sell_pre(fl, evs, *, sell_wm):
    w = sell_wm.get(id(fl))
    if w is None or w[0] is not fl or w[1] is not evs:
        return 0, 0
    first, last, n = w[2], w[3], w[4]
    for k in range(len(evs) - n + 1):
        if evs[k] is first:
            return (k, n) if evs[k + n - 1] is last else (0, 0)
    return 0, 0


def _sell_mark(fl, *, sell_wm):
    evs = fl["events"]
    if evs:
        sell_wm[id(fl)] = (fl, evs, evs[0], evs[-1], len(evs))
    else:
        sell_wm.pop(id(fl), None)


def _load_exf_loans_debts(ex_loan, ex_debt):
    for ex in ("binance", "bybit", "okx", "kucoin", "gate", "bithumb", "coinbase"):
        bp = paths.state(f"exf_balances_{ex}.json")
        if not os.path.exists(bp):
            continue
        bd = statefile.read_json(bp, {}) or {}
        for ln in (bd.get("loans") if isinstance(bd.get("loans"), list) else ()):
            if isinstance(ln, dict) and isinstance(ln.get("debt"), dict):
                for s in ln["debt"]:
                    ex_loan.setdefault(f"{ex}:recon", {})[str(s).upper()] = str(ln.get("label") or "담보대출")
        dd = bd.get("debts")
        for s, v in (dd.items() if isinstance(dd, dict) else ()):
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv < 0:
                ex_debt.setdefault(f"{ex}:recon", {})[str(s).upper()] = Decimal(str(fv))


def _index_exf_deposits(conn, offc_dep, dep_net, fx_dep_tx, fx_dep_uid_tx):
    for rf in conn.execute(
            "SELECT exchange, uuid, payload FROM raw_ex WHERE kind='deposit'"
            " AND exchange != 'upbit'"
            " GROUP BY exchange, uuid HAVING revision = MAX(revision)").fetchall():
        try:
            pw = json.loads(rf["payload"])
        except json.JSONDecodeError:
            continue
        t = str(pw.get("txid") or "")
        if _offc_tx(t):
            offc_dep.add((rf["exchange"], rf["uuid"]))
        if t and str(pw.get("network") or pw.get("net_type") or "").strip():
            dep_net[t.lower()] = (str(pw.get("network") or pw.get("net_type")).strip(), pw.get("currency"))
        if t and str(pw.get("state") or "").upper() == "ACCEPTED":
            t9n = _txk(t)
            fx_dep_tx[t9n] = rf["exchange"]
            fx_dep_uid_tx[rf["uuid"]] = t9n


def _index_upbit_deposits(conn, dep_net, up_dep_uid_tx, up_dep_uid_ts):
    for rf in conn.execute(
            "SELECT uuid, payload FROM raw_ex WHERE kind='deposit' AND exchange='upbit'"
            " GROUP BY uuid HAVING revision = MAX(revision)").fetchall():
        try:
            pw = json.loads(rf["payload"])
        except json.JSONDecodeError:
            continue
        t = str(pw.get("txid") or "")
        if t and str(pw.get("net_type") or pw.get("network") or "").strip():
            dep_net[t.lower()] = (str(pw.get("net_type") or pw.get("network")).strip(), pw.get("currency"))
        if t and str(pw.get("state") or "").upper() == "ACCEPTED":
            up_dep_uid_tx[rf["uuid"]] = _txk(t)
            try:
                up_dep_uid_ts[rf["uuid"]] = datetime.fromisoformat(str(pw.get("done_at") or pw.get("created_at"))).timestamp()
            except (ValueError, TypeError):
                pass


def _collect_of_deposits(conn, offc_on, offc_dep, origin_cache, of_deps, wallet_label):
    for rf in conn.execute("SELECT exchange, uuid, payload FROM raw_ex WHERE kind='deposit'"
                           " GROUP BY exchange, uuid HAVING revision = MAX(revision)").fetchall():
        if rf["exchange"] in offc_on and (rf["exchange"], rf["uuid"]) in offc_dep:
            continue
        try:
            pw = json.loads(rf["payload"])
            if str(pw.get("state") or "").upper() != "ACCEPTED":
                continue
            ts0 = None
            for k0 in ("created_at", "done_at"):
                if pw.get(k0):
                    ts0 = int(datetime.fromisoformat(str(pw[k0]).replace("Z", "+00:00")).timestamp())
                    break
            amt0 = Decimal(str(pw.get("amount") or 0))
        except (ValueError, TypeError, InvalidOperation):
            continue
        t0 = str(pw.get("txid") or "")
        oc0 = origin_cache.get(t0) or origin_cache.get(t0.lower()) or {}
        of0 = oc0.get("from") if isinstance(oc0, dict) else None
        of0 = (of0.lower() if str(of0).startswith("0x") else of0) if of0 else None
        of_deps.append({"ex": rf["exchange"], "uuid": rf["uuid"], "cur": pw.get("currency") or "", "amt": amt0, "ts": ts0,
                        "txn": outflow_match.norm_txid(t0), "origin_from": of0,
                        "origin_mine": bool(of0) and of0.lower() in wallet_label})


def _load_position_rows(conn, lp_pos_rows, pos_rows, G, by_symloc):
    for row in conn.execute("SELECT group_id, location, qty_norm FROM positions").fetchall():
        try:
            qn0 = Decimal(row["qty_norm"])
        except (InvalidOperation, TypeError, ValueError):
            continue
        if (row["location"] or "").startswith("lp:"):
            lp_pos_rows.append((row["group_id"], row["location"], qn0))
            continue
        if (row["location"] or "").startswith("out:"):
            continue
        d0 = {"gid": row["group_id"], "location": row["location"] or "", "qty": qn0}
        pos_rows.append(d0)
        if d0["location"].startswith("exchange:"):
            sym0 = ((G.get(d0["gid"]) or {}).get("sym") or "").upper()
            if sym0:
                by_symloc.setdefault((sym0, d0["location"]), []).append(d0)


class ReplayMixin:

    def _build_replay(self, conn) -> accounting_books.ReplayResult:
        _bs9 = self._replay_prep(conn)
        self._replay_rt(_bs9)
        self._replay_links(_bs9)
        self._replay_main(_bs9)
        rr = accounting_books.ReplayResult.from_scope(_bs9)
        if calcguard.strict():
            accounting_books.check_rr(rr, _bs9, "replay", accounting_ctx.check_replay)
            if not isinstance(rr._cb, accounting_basis.StrictCostBasis):
                raise AssertionError("원가 장부(cb)가 StrictCostBasis 아님(replay) — 엄격 빌드의 원가 칸 그림자 검사 빠짐")
            rr._cb.check(rr.G, "replay")
        return rr

    def _replay_prep(self, conn) -> dict:
        if not self.skip_gen_check:
            v9 = conn.execute("SELECT v FROM meta WHERE k='schema_version'").fetchone()
            if v9 is None or int(v9["v"] if hasattr(v9, "keys") else v9[0]) != self.LEDGER_GEN:
                raise RuntimeError(f"원장 세대 불일치: DB={v9[0] if v9 else None} web={self.LEDGER_GEN} — 마이그레이션 상태 확인")
        self._ph("prep")
        rows = self._drop_cancelled_openings(self._load(conn))
        rows = self._replay_order(conn, rows)
        prefs = self._prefs_ident(conn, self.prefs())
        fb_on = bool(prefs.get("fallback_avg"))
        fs_pref = prefs.get("first_seen_px")
        if fs_pref is None:
            fs_pref = self.cfg.get("first_seen_px", True)
        fs_pref = bool(fs_pref)
        fs_on = fs_pref and not fb_on
        offc_on = _offc_on(prefs)
        offc_ans = _offc_answered(prefs)
        offc_excl = _offc_excl(prefs)
        gas_on = prefs.get("gas_in_cost")
        if gas_on is None:
            gas_on = self.cfg.get("gas_in_cost", True)
        gas_on = bool(gas_on)
        books = accounting_books.Books()
        px = accounting_ctx.ReplayParts(sb=self, books=books)
        cb = px.cb = accounting_basis.StrictCostBasis() if calcguard.strict() else accounting_basis.CostBasis()
        gas_applied = books.gas_applied
        gas_expense = books.gas_expense
        ex_fee = books.ex_fee
        ex_fee_m = books.ex_fee_m
        up_fee = {}
        up_mkt = {}
        krw_mkt = {(r0["source_ns"], r0["source_id"]) for r0 in rows
                   if r0["leg_seq"] == 1 and str(r0["source_ns"] or "").endswith(":trade") and str(r0["symbol"] or "").upper() == "KRW"}
        try:
            for uid9, pl9 in conn.execute(
                    "SELECT uuid, payload FROM raw_ex WHERE exchange='upbit' AND kind='order'"
                    " GROUP BY uuid HAVING revision = MAX(revision)").fetchall():
                o9 = json.loads(pl9)
                mk9 = str(o9.get("market") or "").upper()
                if mk9.startswith("KRW-"):
                    krw_mkt.add(("upbit:order", uid9))
                if "-" in mk9:
                    up_mkt[uid9] = mk9.split("-", 1)[0]
                    f9, e9 = Decimal(str(o9.get("executed_funds") or "0")), Decimal(str(o9.get("paid_fee") or "0"))
                    if f9 > 0 and e9 > 0:
                        up_fee[uid9] = (f9, e9)
        except (ValueError, TypeError, InvalidOperation) as e9:
            log.warning("업비트 수수료 원본 읽기 실패(수수료 열 0 유지): %s", e9)

        kst_fm = {}

        def kst_fmt(ts9, fmt9):
            t9 = type(ts9)
            k9 = ("m", fmt9, ts9 // 60) if t9 is int else ("f", fmt9, ts9) if t9 is float else None
            if k9 is None:
                return datetime.fromtimestamp(ts9, KST).strftime(fmt9)
            v9 = kst_fm.get(k9)
            if v9 is None:
                v9 = kst_fm[k9] = datetime.fromtimestamp(ts9, KST).strftime(fmt9)
            return v9

        fee_day = books.fee_day

        fbx = px.fbx = accounting_fee.FeeBook(sb=self, books=books, kst_fmt=kst_fmt, cb=cb)
        fee_day_add = fbx.fee_day_add
        ex_fee_add = fbx.ex_fee_add
        wd_fee, wd_fee_m = books.wd_fee, books.wd_fee_m

        wd_fee_add = fbx.wd_fee_add
        cost_ov = prefs.get("cost_overrides") or {}
        cost_be = prefs.get("cost_breakeven") if isinstance(prefs.get("cost_breakeven"), dict) else {}

        def be_until(gid9):
            v9 = cost_be.get(f"g{gid9}")
            try:
                t9 = float(v9.get("until")) if isinstance(v9, dict) and v9.get("until") is not None else None
            except (TypeError, ValueError, OverflowError):
                return None
            return t9 if t9 is not None and 0 < t9 < 1e11 else None
        be_cap_of = accounting_util.be_cap_of
        cost_be = {k9: dict({"until": be_until(k9[1:])},
                            **({"qty": str(be_cap_of(cost_be[k9]))} if be_cap_of(cost_be[k9]) is not None else {}))
                   for k9 in cost_be
                   if isinstance(k9, str) and re.fullmatch(r"g[0-9]+", k9)
                   and be_until(k9[1:]) is not None}
        be_cap = {k9[1:]: be_cap_of(v9) for k9, v9 in cost_be.items()}
        be_used = {}
        def be_take(gid9, ts9, q9):
            u9 = be_until(gid9)
            if u9 is None or ts9 > u9:
                return False
            cap9 = be_cap.get(str(gid9))
            used9 = be_used.get(str(gid9), Decimal(0))
            if cap9 is not None and (cap9 <= 0 or used9 + q9 > cap9 * (1 + Decimal("1e-12")) + EPS):
                return False
            be_used[str(gid9)] = used9 + q9
            return True
        be_done = {}
        be_tax = []
        now = time.time()
        today_kst = datetime.now(KST)
        backfill_t0 = now - float(self.cfg.get("backfill_months") or 5) * 30 * 86400
        _bf_since = bf_engine.SINCE.target(None)
        if _bf_since and not self.cfg.get("backfill_full_history"):
            backfill_t0 = min(backfill_t0, float(_bf_since))
        exf_first = {}
        for r9 in rows:
            if r9["event"] == "EXF_ADJUST":
                try:
                    b9 = int(str(r9["source_id"]).rsplit(":", 1)[1])
                except (IndexError, ValueError):
                    continue
                exf_first[r9["source_ns"]] = min(exf_first.get(r9["source_ns"], b9), b9)
        for ex9, b9 in (conn.execute("SELECT ex, min(bts) FROM exf_adj_tomb GROUP BY ex").fetchall() if conn.execute("SELECT 1 FROM sqlite_master WHERE name='exf_adj_tomb'").fetchone() else ()):
            exf_first[f"{ex9}:recon"] = min(exf_first.get(f"{ex9}:recon", int(b9)), int(b9))
        exf_open_span = float(self.cfg.get("backfill_months") or 5) * 30 * 86400
        ex_debt9 = {}
        ex_loan9 = {}
        _load_exf_loans_debts(ex_loan9, ex_debt9)
        def exf_kind(r9):
            if r9["event"] != "EXF_ADJUST":
                return None
            if histmark.exf_is_fut(r9["event"], r9["source_ns"]):
                return "fix"
            try:
                b9 = int(str(r9["source_id"]).rsplit(":", 1)[1])
            except (IndexError, ValueError):
                return None
            if int(r9["event_ts"]) <= b9 - exf_open_span + 86400:
                return "open"
            return "init" if b9 <= exf_first.get(r9["source_ns"], b9) + 72 * 3600 else "fix"
        G = {}
        gas_by_chain = books.gas_by_chain
        gas_by_month = books.gas_by_month
        tax_rows = books.tax_rows
        realized_by_date = books.realized_by_date
        realized_by_loc = books.realized_by_loc
        extra_events = books.extra_events
        stake_rwd = {}
        stake_inc = {}
        ub_wd_shown = set()
        swap_dep = {}
        unverified = {}
        noproc = {}
        unv_fb9 = {}
        fb_cov9 = {}
        bridge_outs = []
        fx_wd = {}
        fx_uid_tx = {}
        fx_name = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX",
                   "kucoin": "쿠코인", "gate": "게이트", "bithumb": "빗썸", "upbit": "업비트", "hyperliquid": "Hyperliquid", "coinbase": "코인베이스"}
        wd_raw9 = {}
        fbx.wd_raw9 = wd_raw9
        offc_wd, offc_dep = set(), set()
        offc_wd_addr = {}
        offc_pool = {}
        offc_st = {}

        def offc_self_wd(ex9, uid9):
            return (ex9 in offc_on and (ex9, uid9) in offc_wd
                    and not (offc_wd_addr.get((ex9, uid9)) and offc_wd_addr[(ex9, uid9)] in offc_excl.get(ex9, ())))

        offcin = accounting_ctx.OffcIn(fx_name=fx_name, offc_ans=offc_ans, offc_excl=offc_excl, offc_on=offc_on, offc_pool=offc_pool, offc_st=offc_st, offc_wd_addr=offc_wd_addr)
        ofx = px.ofx = accounting_offc.OffcView(offcin=offcin)
        offc_s = ofx.offc_s
        offc_addr_add = ofx.offc_addr_add
        offc_add = ofx.offc_add
        offc_summary = ofx.offc_summary
        ton_h2u9 = _ton_hash_uids(conn)
        for rf in conn.execute(
                "SELECT exchange, uuid, payload FROM raw_ex WHERE kind='withdraw'"
                " GROUP BY exchange, uuid HAVING revision = MAX(revision)").fetchall():
            try:
                pw = json.loads(rf["payload"])
            except json.JSONDecodeError:
                continue
            if isinstance(pw, dict):
                wd_raw9[(rf["exchange"], rf["uuid"])] = pw
            if isinstance(pw, dict) and _offc_tx(pw.get("txid")):
                offc_wd.add((rf["exchange"], rf["uuid"]))
                offc_wd_addr[(rf["exchange"], rf["uuid"])] = xfer_match.norm_addr(pw.get("address")) if pw.get("address") else ""
            t9 = str(pw.get("txid") or "")
            if t9 and str(pw.get("state") or "").upper() == "DONE":
                t9n = _wd_txk(t9, pw.get("network") or pw.get("net_type"), ton_h2u9)
                fx_wd[t9n] = fx_name.get(rf["exchange"], rf["exchange"])
                fx_uid_tx[rf["uuid"]] = t9n
        try:
            for u9h, t9h in self._hl_bridge_links(conn, wd_raw9).items():
                fx_uid_tx[u9h] = _txk(t9h)
                fx_wd[_txk(t9h)] = fx_name.get("hyperliquid", "Hyperliquid")
        except Exception as e9h:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_b_replay:ReplayMixin._build_replay[u9h]", e9h)
            log.warning("Hyperliquid 출금 ↔ 지갑 도착 연결 실패(이번 빌드 생략): %s", logs.safe_err(e9h)[:160])
        fx_transit = {}
        wd_tr = []
        fx_dep_tx = {}
        fx_dep_uid_tx = {}
        dep_net9 = {}
        _index_exf_deposits(conn, offc_dep, dep_net9, fx_dep_tx, fx_dep_uid_tx)
        diag = {"ex_out_cost": Decimal(0), "ex_out_n": 0, "ex_dep_inh_cost": Decimal(0), "ex_dep_inh_n": 0,
                "ex_dep_unlinked_n": 0, "ex_transit_unused_cost": Decimal(0),
                "ex_dep_fee_resid_cost": Decimal(0),
                "exf_dep_inh_cost": Decimal(0), "exf_dep_inh_n": 0,
                "of_bridge_inh_cost": Decimal(0), "of_bridge_inh_n": 0,
                "xc_inh_cost": Decimal(0), "xc_inh_n": 0, "xc_link_n": 0, "xc_sale_drop_n": 0, "xc_hop_drop_n": 0}
        up_dep_uid_tx = {}
        up_dep_uid_ts = {}
        wallet_label = {}
        for w9 in self._hist_wallets():
            wallet_label[str(w9.get("address") or "").lower()] = str(w9.get("label") or w9.get("chain") or "내 지갑")
        exf_dep_tx = {}
        for rf9 in conn.execute("SELECT exchange, uuid, payload FROM raw_ex WHERE kind='deposit' AND exchange!='upbit'"
                                " GROUP BY exchange, uuid HAVING revision = MAX(revision)"):
            try:
                t9x = str(json.loads(rf9["payload"]).get("txid") or "")
            except (json.JSONDecodeError, TypeError):
                continue
            if t9x:
                exf_dep_tx[(rf9["exchange"], rf9["uuid"])] = t9x
        origin_cache = statefile.read_json(paths.state("tx_origin_cache.json"), {})
        origin_pending = set()
        now_oc = int(time.time())

        def oc_fresh(k9):
            oc9 = origin_cache.get(k9)
            return isinstance(oc9, dict) and bool(oc9.get("from") or oc9.get("na") or now_oc - int(oc9.get("t") or 0) < 86400)

        snap_cache = {}
        raw_chains9 = [r9[0] for r9 in conn.execute("SELECT DISTINCT chain FROM raw_txs").fetchall()]
        fx_tab, web_candle9 = _px_tables(self.px)
        fxb = acct_norm.FxBook(fx_tab, paths.state("px_cache_core.json"), self.spot.rate or None,
                               web_candle=web_candle9)
        fbx.fxb = fxb
        ctx = px.ctx = accounting_ctx.ReplayCtx(conn=conn, prefs=prefs, fb_on=fb_on, fs_pref=fs_pref, fs_on=fs_on, gas_on=gas_on, offc_on=offc_on,
                                       offc_ans=offc_ans, offc_excl=offc_excl, now=now, today_kst=today_kst, fxb=fxb)
        realized_krw_by_date = books.realized_krw_by_date
        fee_disp, fee_acq = {}, {}
        fee_diag = {"n": 0, "usd_cost": Decimal(0), "usd_realized": Decimal(0), "usd_unv": Decimal(0), "no_px": 0, "wd_no_px": 0}

        kpx = px.kpx = accounting_krw.KrwPools(fxb=fxb, krw_mkt=krw_mkt, up_mkt=up_mkt, fx_name=fx_name)
        krw_of = kpx.krw_of

        _AK_TRADE = frozenset(("EX_BUY", "EX_SELL", "EXF_BUY", "EXF_SELL", "SWAP"))
        _AK_RE = re.compile(r"^\$([\d,]+(?:\.\d+)?)$")

        def _ak(a9, ts9, row9=None):
            m9 = _AK_RE.match(str(a9 or ""))
            if not m9:
                return None
            try:
                u9 = float(m9.group(1).replace(",", ""))
                r9 = None
                if row9 is not None and row9["event"] in _AK_TRADE and int(row9["event_ts"] or 0) == int(ts9 or 0):
                    r9 = row9
                return int(round(u9 * float(fxb.rate_at(ts9, r9))))
            except (KeyError, IndexError, TypeError, ValueError):
                return None

        unx = px.unx = accounting_unk.UnkBook(sb=self, cost_ov=cost_ov, fs_on=fs_on, krw_of=krw_of, cb=cb)
        apply_ov = unx.apply_ov

        fs_sum = {"n": 0, "q": Decimal(0), "usd": Decimal(0), "miss": 0, "miss_q": {}, "src": {}, "rows": 0, "real": Decimal(0),
                  "st_n": 0, "st_usd": Decimal(0), "st_miss": 0, "be_skip": 0,
                  "bk": {}, "g": {}, "mk": {}, "ur": {}, "up": {}}
        unx.fs_sum = fs_sum
        fs_sales = []
        fs_last = [Decimal(0)]
        kpx.fs_last = fs_last
        fbx.fs_last = fs_last
        fs_rbd = {}
        fs_kit = {}
        fs_spec9 = {}
        fs_memo = {}
        fs_need = {}
        fs_lo9 = (datetime.fromtimestamp(now, KST) - timedelta(days=histcurve.DC_KEEP_DAYS)).strftime("%Y-%m-%d")
        fs_floor9 = acct_norm.iso_day(backfill_t0)
        fs_pin = _fs_pin_load() if fs_on else {}
        fs_pin_new = {}
        fs_aux = {}
        fs_okc = {}
        ret_pool = {}
        ret_kit = {}
        gas_nopx = books.gas_nopx
        for k9 in ("pin", "sd", "ret", "ret_n", "ret_q"):
            fs_sum[k9] = 0
        fs_sum["hold"] = {}

        def fs_pkey(g9):
            try:
                r9 = cur_row[0]
            except NameError:
                return None
            if r9 is None:
                return None
            k9 = f"{r9['source_ns']}|{r9['source_id']}|{r9['leg_seq']}|{r9['asset_id']}"
            return k9 if (r9["group_id"] or -r9["asset_id"]) == g9["gid"] else f"{k9}|g{g9['gid']}"

        fsin = accounting_ctx.FsIn(conn=conn, fs_aux=fs_aux, fs_kit=fs_kit, fs_spec=fs_spec9, fs_floor=fs_floor9, fs_lo=fs_lo9, fs_memo=fs_memo, fs_need=fs_need, fs_sales=fs_sales, ret_kit=ret_kit, ret_pool=ret_pool, fs_pin=fs_pin, fs_pin_new=fs_pin_new, fs_pref=fs_pref, fx_wd=fx_wd, fs_okc=fs_okc)
        fsx = px.fsx = accounting_fs.FirstSeen(px, rows=rows, be_until=be_until, fs_pkey=fs_pkey, fsin=fsin)
        fs_hold = fsx.fs_hold
        fs_sale_idx = fsx.fs_sale_idx
        fs_sameday = fsx.fs_sameday
        fs_ok_ca = fsx.fs_ok_ca
        fs_senders = fsx.fs_senders
        fs_ret = fsx.fs_ret
        fs_spec = fsx.fs_spec
        fs_px = fsx.fs_px
        fs_flow = fsx.fs_flow
        fs_why = fsx.fs_why
        unx.fs_why = fs_why
        fs_conv = fsx.fs_conv
        unx.fs_conv = fs_conv
        fs_st = fsx.fs_st
        fs_mark = fsx.fs_mark
        fbx.fs_mark = fs_mark
        note_unk = unx.note_unk
        fsx.note_unk = note_unk
        oc_names9 = set(self._origin_chain_names())
        def _net_na(k9):
            h9 = dep_net9.get(k9)
            if not h9:
                return ""
            return h9[0] if depaddr.chain_of(h9[0], h9[1]) not in oc_names9 else ""
        originin = accounting_ctx.OriginIn(conn=conn, origin_cache=origin_cache, raw_chains=raw_chains9, snap_cache=snap_cache)
        orx = px.orx = accounting_origin.OriginLookup(_net_na=_net_na, oc_fresh=oc_fresh, origin_pending=origin_pending, originin=originin)
        resolve_origin = orx.resolve_origin
        _index_upbit_deposits(conn, dep_net9, up_dep_uid_tx, up_dep_uid_ts)
        fxdep_transit = {}
        ub_wd_tx = set()
        fsx.ub_wd_tx = ub_wd_tx
        for rf in conn.execute(
                "SELECT uuid, payload FROM raw_ex WHERE kind='withdraw'"
                " AND exchange='upbit'"
                " GROUP BY uuid HAVING revision = MAX(revision)").fetchall():
            try:
                pw = json.loads(rf["payload"])
            except json.JSONDecodeError:
                continue
            t9 = str(pw.get("txid") or "")
            if t9:
                ub_wd_tx.add(_txk(t9))
        xc_cache = xchain_match.load_cache(paths.STATE_DIR)
        xc_ext = frozenset(xchain_match.norm(a9) for a9, v9 in self.outflow_decisions().items()
                           if isinstance(v9, dict) and v9.get("verdict") == "external")
        xc_off = frozenset(xchain_match.norm(t9) for t9 in (prefs.get("xchain_off") or []))
        xc_transit = xchain_match.transit_for(rows, xc_cache, xc_off, xc_ext)
        xc_stable = frozenset(r0["group_id"] for r0 in rows if (r0["gname"] or "") in STABLE_GROUPS and r0["group_id"] is not None)
        xc_cands = xchain_match.send_candidates(rows, xc_cache, xchain_match.load_seed(paths.BASE_DIR)) + \
            xchain_match.candidates(rows, xc_cache, frozenset(set(fx_wd) | ub_wd_tx), xc_stable)
        xc_off9 = set(self.cfg.get("_disabled_chains") or ())
        if xc_off9:
            xc_cands = [c9 for c9 in xc_cands if c9.get("chain") not in xc_off9]
        if hasattr(self, "_xc_lock"):
            with self._xc_lock:
                self._xc_pending = xc_cands[:50]
        xc_used = {}
        self._ph("load·replay")
        to_dest9 = self._transfer_out_dest(conn)
        ex_transit = {}
        uuid2txh = {}
        for r9 in conn.execute(
                "SELECT ex_uuid, chain_txhash FROM transfers WHERE ex_uuid IS NOT NULL").fetchall():
            if r9["ex_uuid"] and r9["chain_txhash"]:
                uuid2txh[r9["ex_uuid"]] = r9["chain_txhash"]

        _un = accounting_util._un
        unx._un = _un

        def extra_ev(ts, sym, k, d, q, a, tx, un=None, vq=None):
            gid_e = None
            if isinstance(sym, dict):
                gid_e, sym = sym.get("gid"), sym.get("sym")
            e0 = {
                "t": kst_fmt(ts, "%m-%d %H:%M"),
                "sym": sym, "k": k, "d": d, "q": q, "a": a, "_gid": gid_e,
                "tx": (tx[:6] + "…" + tx[-4:]) if tx else "—", "src": cur_src[0],
                "_ts": int(ts or 0),
                "_pid": cur_row[0]["posting_id"] if cur_row[0] is not None else None}
            if un is not None:
                e0["un"] = un
            ak9 = _ak(a, ts, cur_row[0])
            if ak9 is not None:
                e0["aK"] = ak9
            if vq is not None:
                e0["_vq"] = vq
            extra_events.append(e0)

        def gstate(row):
            gid = row["group_id"] or -row["asset_id"]
            if gid not in G:
                G[gid] = cb.new_group(
                    gid, self._gsym(row),
                    is_stable=((row["gname"] or "") in STABLE_GROUPS
                               or (row["kind"] == "exchange_currency"
                                   and _ex_stable_sym(row["symbol"]))),
                    is_fiat=(row["kind"] == "exchange_currency"
                             and (row["symbol"] or "").upper() in ("KRW",)))
            return G[gid]

        krw_mix = [Decimal(0)]
        kpx.krw_mix = krw_mix
        krw_flow = [None]
        kpx.krw_flow = krw_flow
        krw_stl = [None]
        kpx.krw_stl = krw_stl

        consume_krw = kpx.consume_krw

        tax_krw_acq = fbx.tax_krw_acq

        stable_fx_mark = accounting_util.stable_fx_mark
        fbx.stable_fx_mark = stable_fx_mark

        offc_sold = [0, Decimal(0)]
        ofx.offc_sold = offc_sold
        krw_last = [None]
        kpx.krw_last = krw_last
        fsx.krw_last = krw_last
        oa_last = [Decimal(0)]

        oa_take = accounting_util.oa_take

        CP_EMIT_MAX = 64
        cp_last = [None]
        cp_ev = books.cp_ev

        cp_pool = accounting_util.cp_pool

        cpx = px.cpx = accounting_cp.CostPools(px, G=G, _ak=_ak, oa_last=oa_last, CP_EMIT_MAX=CP_EMIT_MAX, cp_last=cp_last)
        cp_add = cpx.cp_add
        fsx.cp_add = cp_add

        cp_add_map = cpx.cp_add_map
        fsx.cp_add_map = cp_add_map

        cp_sync = cpx.cp_sync

        cp_take = cpx.cp_take

        cp_emit = cpx.cp_emit

        cp_merge = accounting_util.cp_merge

        xc_tok9 = {}
        cpx.xc_tok9 = xc_tok9
        for v9 in (xc_cache.get("ws") or {}).values():
            for w9 in (v9 if isinstance(v9, list) else ()):
                if isinstance(w9, dict) and w9.get("src_tx") and w9.get("token"):
                    xc_tok9.setdefault(str(w9["src_tx"]).lower(), (str(w9.get("token_chain") or w9.get("src_chain") or ""), str(w9["token"])))
        xc_stx9 = xc_cache.get("stx") if isinstance(xc_cache.get("stx"), dict) else {}
        cpx.xc_stx9 = xc_stx9
        xc_blk9 = xc_cache.get("blk") if isinstance(xc_cache.get("blk"), dict) else {}
        cpx.xc_blk9 = xc_blk9
        cp_xrec = {}
        cpx.cp_xrec = cp_xrec

        cp_xc = cpx.cp_xc

        def cv_label(mp9, sym9):
            out9, own9 = [], False
            for k9, (q9, _c9) in (mp9 or {}).items():
                e9 = cp_ev.get(k9)
                if q9 > 0 and e9 is not None and e9.get("_cv"):
                    l9 = f"{e9['_cv']['from']} → {sym9}"
                    if l9 not in out9:
                        out9.append(l9)
                elif q9 > 0:
                    own9 = True
            return " · ".join(out9 + ([sym9] if (own9 or not out9) else []))

        consume = cpx.consume

        krw_took = kpx.krw_took

        krw_rec = kpx.krw_rec

        fs_rec = fsx.fs_rec

        krw_inh = kpx.krw_inh

        def flow_of(g, ts, chain):
            if g["cur"] is None:
                g["cur"] = {"opened": ts, "chain": chain, "bought": Decimal(0),
                            "cost": Decimal(0), "realized": Decimal(0), "fee": Decimal(0),
                            "proceeds": Decimal(0),
                            "cost_krw": Decimal(0), "proceeds_krw": Decimal(0),
                            "events": [], "sold_dates": [],
                            "moved_qty": Decimal(0), "moved_cost": Decimal(0),
                            "sold": Decimal(0),
                            "rbd": {}, "ubd": {}, "rbdk": {},
                            "chl": ({cur_lab[0]: 1} if cur_lab[0] else {}), "rch": {}}
                g["cur"]["_gid"] = g["gid"]
                g["flows"].append(g["cur"])
                for pend9 in g.pop("_ov_pend", []):
                    apply_ov(g["cur"], pend9)
                for pend9 in g.pop("_fs_pend", []):
                    fs_flow(g["cur"], pend9)
            return g["cur"]
        fbx.flow_of = flow_of
        fsx.flow_of = flow_of

        STL_TOP = 8
        kpx.STL_TOP = STL_TOP

        stl_krw_mkt = kpx.stl_krw_mkt

        stl_ex = kpx.stl_ex

        stl_src = kpx.stl_src

        stl_use = kpx.stl_use

        stl_add = kpx.stl_add

        stl_take = kpx.stl_take

        stl_out = kpx.stl_out

        stl_carry = kpx.stl_carry

        stl_in = kpx.stl_in

        def st_flow_in(g9, e9, sc9, ts9, chain9):
            kc9 = (e9.get("kc") or Decimal(0)) * sc9
            if kc9 <= EPS:
                return
            fl9 = flow_of(g9, ts9, chain9)
            fl9["cost"] += kc9
            fl9["cost_krw"] += (e9.get("kk") or Decimal(0)) * sc9
            stl_in(fl9, e9, sc9)
            fs_in(fl9, e9, sc9)

        fs_in = accounting_util.fs_in


        fee_unit = fbx.fee_unit

        WD_FEE_IN_AMT = frozenset(("gate", "bithumb", "hyperliquid"))
        fbx.WD_FEE_IN_AMT = WD_FEE_IN_AMT

        wd_fee_q = fbx.wd_fee_q

        fee_expense = fbx.fee_expense

        br_fee_add = fbx.br_fee_add

        fee_gain = fbx.fee_gain

        cur_src = [None]
        cpx.cur_src = cur_src
        cur_row = [None]
        cpx.cur_row = cur_row
        cur_lab = [None]
        fbx.cur_lab = cur_lab

        _qfmt = accounting_util._qfmt

        def unk_tag(fk, fu, proceeds, qty, stable, be=False):
            if fu <= 0 or stable:
                return ""
            pu = proceeds * fu / qty if qty > 0 else Decimal(0)
            if pu < 1:
                return ""
            if be:
                return (f" · 매수가 = 매도가로 처리 ${float(pu):,.2f} (직접 정함 · 손익 없음)" if fk <= 0
                        else f" · 일부 {_qfmt(fu)}개 매수가 = 매도가로 처리 ${float(pu):,.2f} (직접 정함 · 손익 없음)")
            if fk <= 0:
                return f" · 원가미상 ${float(pu):,.2f} (미확인 분류)"
            return f" · 일부 원가미상 {_qfmt(fu)}개 ${float(pu):,.2f} (미확인 분류)"

        ev = cpx.ev
        unx.ev = ev

        mv_note = accounting_util.mv_note

        def in_note(fl, label, q, cost, ts, story=None, cost_krw=None):
            if fl is None:
                return
            if label and q > 0:
                a = fl.setdefault("in_from", {}).setdefault(label, [Decimal(0), Decimal(0), 0.0])
                a[0] += q
                a[1] += cost
                a[2] += float(krw_of(cost, ts) if cost_krw is None else cost_krw)
            if story:
                fl["story_n"] = fl.get("story_n", 0) + len(story)

        credited_txh, credited_gid, _lk9 = accounting_index.credited_index(conn)
        if "r0" in _lk9:
            r0 = _lk9["r0"]
        if "gid0" in _lk9:
            gid0 = _lk9["gid0"]
        if "qn0" in _lk9:
            qn0 = _lk9["qn0"]

        bridge_dep_ts, _lk9 = accounting_index.bridge_dep_index(rows, self._gsym)
        if "r" in _lk9:
            r = _lk9["r"]

        conv_cp, tx_legsym, pay_pid, _lk9 = accounting_index.pay_index(rows, self._gsym)
        kpx.tx_legsym = tx_legsym
        if "r" in _lk9:
            r = _lk9["r"]
        if "cp9" in _lk9:
            cp9 = _lk9["cp9"]
        if "s9" in _lk9:
            s9 = _lk9["s9"]
        if "legs9" in _lk9:
            legs9 = _lk9["legs9"]
        if "acq9" in _lk9:
            acq9 = _lk9["acq9"]
        if "p9" in _lk9:
            p9 = _lk9["p9"]
        if "lk9" in _lk9:
            lk9 = _lk9["lk9"]
        if "c9" in _lk9:
            c9 = _lk9["c9"]
        tx_group, swap_gas, swap_recv, swap_pay, swap_wd_pre, _lk9 = accounting_index.swap_index(rows, self._gsym, self._norm, fx_uid_tx, pay_pid)
        if "key" in _lk9:
            key = _lk9["key"]
        if "r" in _lk9:
            r = _lk9["r"]
        if "sg9" in _lk9:
            sg9 = _lk9["sg9"]
        nopx_swap, zv_leg, nopx_px_ok, _lk9 = accounting_index.nopx_index(rows, self._gsym, self._norm, fxb)
        if "a9" in _lk9:
            a9 = _lk9["a9"]
        if "ag9" in _lk9:
            ag9 = _lk9["ag9"]
        if "est9" in _lk9:
            est9 = _lk9["est9"]
        if "fx9" in _lk9:
            fx9 = _lk9["fx9"]
        if "gpx9" in _lk9:
            gpx9 = _lk9["gpx9"]
        if "gq9" in _lk9:
            gq9 = _lk9["gq9"]
        if "gs9" in _lk9:
            gs9 = _lk9["gs9"]
        if "gz9" in _lk9:
            gz9 = _lk9["gz9"]
        if "k9" in _lk9:
            k9 = _lk9["k9"]
        if "key9" in _lk9:
            key9 = _lk9["key9"]
        if "legs9" in _lk9:
            legs9 = _lk9["legs9"]
        if "p9" in _lk9:
            p9 = _lk9["p9"]
        if "q9" in _lk9:
            q9 = _lk9["q9"]
        if "r" in _lk9:
            r = _lk9["r"]
        if "r9" in _lk9:
            r9 = _lk9["r9"]
        if "v9" in _lk9:
            v9 = _lk9["v9"]
        if "w9" in _lk9:
            w9 = _lk9["w9"]
        if "zc9" in _lk9:
            zc9 = _lk9["zc9"]
        swap_fill, swap_fill_est, swap_fill_zero, sw9, _lk9 = accounting_index.swap_fill_index(rows, self._gsym, self._norm, fxb, zv_leg, nopx_px_ok, swap_gas, pay_pid, tx_group)
        if "b9" in _lk9:
            b9 = _lk9["b9"]
        if "k9" in _lk9:
            k9 = _lk9["k9"]
        if "key9" in _lk9:
            key9 = _lk9["key9"]
        if "legs9" in _lk9:
            legs9 = _lk9["legs9"]
        if "lk9" in _lk9:
            lk9 = _lk9["lk9"]
        if "n9" in _lk9:
            n9 = _lk9["n9"]
        if "o9" in _lk9:
            o9 = _lk9["o9"]
        if "og9" in _lk9:
            og9 = _lk9["og9"]
        if "p9" in _lk9:
            p9 = _lk9["p9"]
        if "q9" in _lk9:
            q9 = _lk9["q9"]
        if "r" in _lk9:
            r = _lk9["r"]
        if "r0" in _lk9:
            r0 = _lk9["r0"]
        if "r9" in _lk9:
            r9 = _lk9["r9"]
        if "s9" in _lk9:
            s9 = _lk9["s9"]
        if "sg9" in _lk9:
            sg9 = _lk9["sg9"]
        if "sv9" in _lk9:
            sv9 = _lk9["sv9"]
        if "v9" in _lk9:
            v9 = _lk9["v9"]
        if "zg9" in _lk9:
            zg9 = _lk9["zg9"]
        br_legs9, _lk9 = accounting_index.bridge_rcpt_index(rows, self._gsym, self._norm, zv_leg, nopx_swap)
        if "i9" in _lk9:
            i9 = _lk9["i9"]
        if "k9" in _lk9:
            k9 = _lk9["k9"]
        if "key9" in _lk9:
            key9 = _lk9["key9"]
        if "ks9" in _lk9:
            ks9 = _lk9["ks9"]
        if "legs9" in _lk9:
            legs9 = _lk9["legs9"]
        if "lo9" in _lk9:
            lo9 = _lk9["lo9"]
        if "o9" in _lk9:
            o9 = _lk9["o9"]
        if "og9" in _lk9:
            og9 = _lk9["og9"]
        if "r" in _lk9:
            r = _lk9["r"]
        if "r9" in _lk9:
            r9 = _lk9["r9"]
        nopx_carry = {}
        arr_groups, arr_tx_chain, _lk9 = accounting_index.arr_index(rows)
        if "r" in _lk9:
            r = _lk9["r"]

        lp_mgrs = lpdec.lp_managers(paths.BASE_DIR)
        lp_by_tx, lp_meta_by, _lk9 = accounting_index.lp_index(conn)
        if "ch9" in _lk9:
            ch9 = _lk9["ch9"]
        if "d9" in _lk9:
            d9 = _lk9["d9"]
        if "g9" in _lk9:
            g9 = _lk9["g9"]
        if "m9" in _lk9:
            m9 = _lk9["m9"]
        if "mm9" in _lk9:
            mm9 = _lk9["mm9"]
        if "r9" in _lk9:
            r9 = _lk9["r9"]
        if "t9" in _lk9:
            t9 = _lk9["t9"]
        lp_tx_rows, _lk9 = accounting_index.lp_rows_index(rows)
        if "r0" in _lk9:
            r0 = _lk9["r0"]
        lp_done = set()
        lpb = {}
        lp_events = books.lp_events
        lp_dep_seen = set()

        fns = accounting_ctx.ReplayFns(be_take=be_take, ak=_ak, extra_ev=extra_ev, cv_label=cv_label, unk_tag=unk_tag)
        lpin = accounting_ctx.LpIn(lp_by_tx=lp_by_tx, lp_dep_seen=lp_dep_seen, lp_meta_by=lp_meta_by, lp_mgrs=lp_mgrs, lp_tx_rows=lp_tx_rows, lpb=lpb)
        lpx = px.lpx = accounting_lp.LpBook(px, _un=_un, gstate=gstate, lpin=lpin, fns=fns)
        lp_bucket = lpx.lp_bucket
        lp_label = accounting_util.lp_label
        lpx.lp_label = lp_label
        lp_event = lpx.lp_event

        lp_move = lpx.lp_move

        lp_tx = lpx.lp_tx

        ob = {}
        up_dep_by_tx = {t9: u9 for u9, t9 in up_dep_uid_tx.items()}
        up_win_t0 = min((r0["event_ts"] for r0 in rows if r0["event"] == "EX_DEPOSIT"
                         and str(r0["source_ns"] or "").startswith("upbit")), default=None)
        ever_in = {r0["group_id"] or -r0["asset_id"] for r0 in rows
                   if int(r0["qty_base"]) > 0 and r0["event"] != "TRANSFER_OUT"
                   and str(r0["location"] or "").startswith(("wallet:", "exchange:"))}
        of_noauto = {a for a, v in self.outflow_decisions().items() if isinstance(v, dict) and v.get("noAuto")}
        of_dec9 = self.outflow_decisions()
        rt_pair, rt_transit, rt_back, rt_out, _lk9 = accounting_index.roundtrip_index(rows, self._norm)
        if "_ro" in _lk9:
            _ro = _lk9["_ro"]
        if "loc0" in _lk9:
            loc0 = _lk9["loc0"]
        if "r0" in _lk9:
            r0 = _lk9["r0"]
        self._ph("outflow_dest·match")
        return dict(locals())

    def _replay_rt(self, _bs9):
        (conn, diag, ever_in, fx_dep_uid_tx, fx_wd, of_noauto, offc_dep, offc_on, origin_cache, rows, rt_pair, ub_wd_tx, uuid2txh, wallet_label, xc_cache,) = (_bs9["ctx"].conn, _bs9["diag"], _bs9["ever_in"], _bs9["fx_dep_uid_tx"], _bs9["fx_wd"], _bs9["of_noauto"], _bs9["offc_dep"], _bs9["ctx"].offc_on, _bs9["origin_cache"], _bs9["rows"], _bs9["rt_pair"], _bs9["ub_wd_tx"], _bs9["uuid2txh"], _bs9["wallet_label"], _bs9["xc_cache"],)
        rt_same = self._rt_same_dest(conn, rt_pair)
        of_sends, of_arr, of_comp = [], [], []
        for r0 in rows:
            loc0 = r0["location"] or ""
            if loc0.startswith("out:") and r0["leg_kind"] == "move_in":
                gid0, gn0, sym0 = r0["group_id"] or -r0["asset_id"], r0["gname"] or "", self._gsym(r0)
                of_sends.append({"pid": r0["posting_id"], "txn": outflow_match.norm_txid(r0["source_id"]), "txh": r0["source_id"],
                                 "chain": r0["source_ns"], "dest": loc0.split(":", 2)[2] if loc0.count(":") >= 2 else "?",
                                 "sym": sym0, "qty": self._norm(r0), "ts": int(r0["event_ts"]),
                                 "ok": gid0 in ever_in and not (sym0.upper() in STABLE_GROUPS and gn0 not in STABLE_GROUPS),
                                 "stable": gn0 in STABLE_GROUPS,
                                 "ca": str(r0["address"] or "").lower()})
            elif loc0.startswith("wallet:") and r0["leg_kind"] == "acq" and \
                    r0["event"] in ("TRANSFER_IN", "PROGRAM_IN") and int(r0["qty_base"]) > 0:
                t0 = r0["source_id"] or ""
                if t0 in fx_wd or t0.lower() in fx_wd or t0 in ub_wd_tx or t0.lower() in ub_wd_tx:
                    continue
                of_arr.append({"key": r0["posting_id"], "chain": r0["source_ns"], "ts": int(r0["event_ts"]),
                               "sym": self._gsym(r0), "qty": self._norm(r0), "tx": t0, "gid": r0["group_id"] or -r0["asset_id"],
                               "gname": r0["gname"] or "", "native": r0["address"] in (None, "", "native"),
                               "stable": (r0["gname"] or "") in STABLE_GROUPS,
                               "ca": f"{r0['source_ns']}:{(r0['address'] or '').lower()}",
                               "wallet": loc0.split(":", 2)[2] if loc0.count(":") >= 2 else ""})
            elif r0["event"] == "BRIDGE" and r0["leg_kind"] == "move_out" and loc0.startswith("wallet:"):
                of_comp.append({"pid": r0["posting_id"], "chain": r0["source_ns"], "dest": "", "sym": self._gsym(r0),
                                "qty": -self._norm(r0), "ts": int(r0["event_ts"]), "ok": True,
                                "txn": outflow_match.norm_txid(r0["source_id"])})
        for s0 in of_sends:
            if not flow_trace.is_burn(s0["dest"]) or s0["chain"] == "sol":
                continue
            try:
                x0 = conn.execute("SELECT json_extract(snapshot, '$.tx.raw_input'), COALESCE(json_extract(snapshot, '$.tx.to.hash'),"
                                  " json_extract(snapshot, '$.tx.to')), json_extract(snapshot, '$.tx.fee.value') FROM raw_txs"
                                  " WHERE chain=? AND txhash=? AND json_valid(snapshot)", (s0["chain"], s0["txh"])).fetchone()
            except Exception as _cg9:   # noqa: BLE001 [fallback]
                calcguard.swallowed("view_b_replay:ReplayMixin._build_replay[x0]", _cg9)
                x0 = None
            if x0 and str(x0[0] or "")[:10].lower() == outflow_match.OFT_SEND_SEL and not spamguard.snapshot_synth(x0[2], x0[0]) \
                    and str(x0[1] or "").lower() not in ("", s0.get("ca") or ""):
                s0["oft"] = True
        of_deps = []
        _collect_of_deposits(conn, offc_on, offc_dep, origin_cache, of_deps, wallet_label)
        self._of_deps_origin = {}
        for d0 in of_deps:
            if d0.get("origin_from") and not d0.get("origin_mine"):
                self._of_deps_origin.setdefault(d0["origin_from"], []).append(d0)
        dep_txn9 = {d0["txn"] for d0 in of_deps if d0.get("txn")}
        of_comp_n0 = len(of_comp)
        of_comp = [c0 for c0 in of_comp if c0.get("txn") not in dep_txn9]
        self._of_comp_exdep_drop = of_comp_n0 - len(of_comp)
        of_mine = {outflow_match.norm_txid(r0["txhash"]) for r0 in conn.execute("SELECT txhash FROM raw_txs").fetchall()}
        of_chain = frozenset(of_mine)
        for rf in conn.execute("SELECT payload FROM raw_ex WHERE kind='withdraw'").fetchall():
            try:
                tw9 = outflow_match.norm_txid(json.loads(rf["payload"]).get("txid"))
            except (ValueError, TypeError, AttributeError):
                continue
            if tw9:
                of_mine.add(tw9)
        self._depx_idx = self._deposit_exchange_index()
        of_match, of_sugg, of_proven = outflow_match.match(of_sends, of_deps, of_mine, self._deposit_exchange, of_noauto)
        priced_gid = {r0["group_id"] or -r0["asset_id"] for r0 in rows
                      if r0["cost_usd"] is not None or (r0["event"] == "TRANSFER_OUT_EX" and r0["leg_kind"] == "move_out")}
        priced_gid |= {r0["group_id"] or -r0["asset_id"] for r0 in conn.execute(
            "SELECT asset_id, group_id FROM assets WHERE confirmed=1").fetchall()}
        try:
            gp9 = statefile.read_json(paths.state("goplus_cache.json"), {}) if os.path.exists(paths.state("goplus_cache.json")) else {}
        except BaseException as _cg9:  # noqa: BLE001 [fallback]
            calcguard.swallowed("view_b_replay:ReplayMixin._build_replay[gp9]", _cg9)
            gp9 = {}
        for a0 in of_arr:
            strong9 = bool(((gp9.get(a0["ca"]) or {}).get("risk") or {}).get("strong")) if isinstance(gp9, dict) else False
            stable_name9 = outflow_match.canon_sym(a0["sym"]) in STABLE_GROUPS
            a0["ok"] = not strong9 and (a0["gname"] in STABLE_GROUPS if stable_name9 else (a0["native"] or a0["gid"] in priced_gid))
        of_bridge, of_bridge_amb = outflow_match.bridge_match(of_sends, of_arr, of_comp, skip=set(of_match), no_auto=of_noauto)
        xc_links, xc_barr = xchain_match.links_for(xc_cache), xchain_match.bridge_arrivals(xc_cache)
        if xc_links or xc_barr:
            used9 = {a9["key"]: p9 for p9, a9 in of_bridge.items()}
            sends9 = [s9 for s9 in of_sends if s9["dest"] not in of_noauto]
            for p9, (a9, bs9) in xchain_match.match_pairs(sends9, of_arr, xc_links, xc_barr, outflow_match.family,
                                                           frozenset(outflow_match.STABLES), skip=set(of_match)).items():
                if bs9 == "window" and (p9 in of_bridge or a9["key"] in used9):
                    continue
                if bs9 == "id" and used9.get(a9["key"]) not in (None, p9):
                    of_bridge.pop(used9[a9["key"]], None)
                of_bridge[p9] = a9
                used9[a9["key"]] = p9
                if bs9 == "id":
                    a9["id_link"] = True
                of_bridge_amb.pop(p9, None)
                diag["xc_link_n"] += 1
        br_transit = {}

        def _of_uids(m0):
            return [m0["uuid"]] if m0.get("uuid") else list(m0.get("uuids") or [])
        for s0 in of_sends:
            m0 = of_match.get(s0["pid"])
            if not m0:
                continue
            for u0 in _of_uids(m0):
                if m0["ex"] == "upbit":
                    uuid2txh.setdefault(u0, s0["txh"])
                else:
                    fx_dep_uid_tx[u0] = s0["txn"]
        self._of_auto = {"sugg": of_sugg, "proven": of_proven, "bridge": of_bridge, "bridge_amb": of_bridge_amb,
                         "sends": {s0["pid"]: s0 for s0 in of_sends}}
        self._ph("rt_same")
        _bs9.update((k9, v9) for k9, v9 in locals().items() if k9 != "_bs9")
        if "_cg9" not in locals():
            _bs9.pop("_cg9", None)

    def _replay_links(self, _bs9):
        (_of_uids, _qfmt, _ro, _un, arr_tx_chain, backfill_t0, be_done, be_take, be_tax, conn, cp_merge, cur_lab, cur_row, cur_src, diag, flow_of, fs_last, fs_on, fs_sales, fs_sum, fx_dep_tx, fx_name, fx_uid_tx, fxb, gstate, krw_last, krw_mix, krw_stl, now, oa_last, oa_take, ob, oc_fresh, of_bridge, of_chain, of_match, offc_self_wd, offc_sold, origin_cache, origin_pending, prefs, realized_by_date, realized_by_loc, realized_krw_by_date, ret_pool, rows, rt_out, rt_pair, stable_fx_mark, sw9, tax_rows, unk_tag, unverified, up_dep_by_tx, uuid2txh, wd_raw9, wd_tr, xc_transit, cpx, fbx, fsx, kpx, unx, px, fns, cb,) = (_bs9["_of_uids"], _bs9["_qfmt"], _bs9["_ro"], _bs9["_un"], _bs9["arr_tx_chain"], _bs9["backfill_t0"], _bs9["be_done"], _bs9["be_take"], _bs9["be_tax"], _bs9["ctx"].conn, _bs9["cp_merge"], _bs9["cur_lab"], _bs9["cur_row"], _bs9["cur_src"], _bs9["diag"], _bs9["flow_of"], _bs9["fs_last"], _bs9["ctx"].fs_on, _bs9["fs_sales"], _bs9["fs_sum"], _bs9["fx_dep_tx"], _bs9["fx_name"], _bs9["fx_uid_tx"], _bs9["ctx"].fxb, _bs9["gstate"], _bs9["krw_last"], _bs9["krw_mix"], _bs9["krw_stl"], _bs9["ctx"].now, _bs9["oa_last"], _bs9["oa_take"], _bs9["ob"], _bs9["oc_fresh"], _bs9["of_bridge"], _bs9["of_chain"], _bs9["of_match"], _bs9["offc_self_wd"], _bs9["offc_sold"], _bs9["origin_cache"], _bs9["origin_pending"], _bs9["ctx"].prefs, _bs9["realized_by_date"], _bs9["realized_by_loc"], _bs9["realized_krw_by_date"], _bs9["ret_pool"], _bs9["rows"], _bs9["rt_out"], _bs9["rt_pair"], _bs9["stable_fx_mark"], _bs9["sw9"], _bs9["tax_rows"], _bs9["unk_tag"], _bs9["unverified"], _bs9["up_dep_by_tx"], _bs9["uuid2txh"], _bs9["wd_raw9"], _bs9["wd_tr"], _bs9["xc_transit"], _bs9["cpx"], _bs9["fbx"], _bs9["fsx"], _bs9["kpx"], _bs9["unx"], _bs9["px"], _bs9["fns"], _bs9["cb"],)
        (consume_krw, cp_add_map, cp_emit, cp_take, ev, fee_gain, fs_mark, fs_rec, krw_of, note_unk, tax_krw_acq,) = (kpx.consume_krw, cpx.cp_add_map, cpx.cp_emit, cpx.cp_take, cpx.ev, fbx.fee_gain, fsx.fs_mark, fsx.fs_rec, kpx.krw_of, unx.note_unk, fbx.tax_krw_acq,)
        if calcguard.strict():
            accounting_books.check_pool_aliases(_bs9, "consume_krw cp_add_map cp_emit cp_take ev fee_gain fs_mark fs_rec krw_of note_unk tax_krw_acq", (consume_krw, cp_add_map, cp_emit, cp_take, ev, fee_gain, fs_mark, fs_rec, krw_of, note_unk, tax_krw_acq,), "links")
        x0: object
        xf_links = self._xfer_links(conn, of_chain, set(uuid2txh) | {u0 for m0 in of_match.values() for u0 in _of_uids(m0)}, prefs,
                                    origin_cache, origin_pending)
        for xl9 in xf_links.values():
            if xl9["key"].startswith("amt:"):
                fx_uid_tx[xl9["wd_uuid"]] = xl9["key"]
        xf_wd9 = {xl9["wd_uuid"] for xl9 in xf_links.values()}
        def _sale_px(sym9, ts9):
            try:
                return float(self.px.candle_usd(sym9, int(ts9) * 1000) or 0) or None
            except Exception as _cg9:  # noqa: BLE001 [fallback]
                calcguard.swallowed("view_b_replay:ReplayMixin._build_replay._sale_px", _cg9)
                return None
        sale_lots = []
        sale_links = {}
        own_dep9 = set()
        try:
            of_man = self._of_manual_resolve(rows)
        except Exception as e:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_b_replay:ReplayMixin._build_replay[of_man]", e)
            log.warning("보낸 내역 수동 연결 풀이 실패(이번 빌드 미적용): %s", e)
            of_man = {"dests": {}, "pids": set(), "dup": set(), "claims": {}}
            self._of_claims = {}
        try:
            sale_lots = sale_match.build_lots(statefile.read_json(paths.state("sale_bids.json"), {}) or {}, _sale_px, prefs.get("sale_link_off") or ())
            my9 = {str(w9.get("address") or "").lower() for w9 in self._hist_wallets() if isinstance(w9, dict)}
            sale_in, sale_need = sale_match.collect_inflows(conn, sale_lots, origin_cache, my9)
            own_dep9 = set(uuid2txh) | set(xf_links) | {u0 for m0 in of_match.values() for u0 in _of_uids(m0)}
            sale_in = [x9 for x9 in sale_in
                       if not (x9["kind"] == "ex" and x9.get("src") in own_dep9)
                       and not (x9["kind"] == "chain" and (x9["chain"], x9["ref"]) in rt_pair)
                       and x9["pid"] not in of_man["pids"]]
            sale_links = sale_match.match(sale_lots, sale_in)
            origin_pending |= {t9 for t9 in sale_need if not oc_fresh(t9)}
        except Exception as e:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_b_replay:ReplayMixin._build_replay[sale_lots]", e)
            log.warning("토큰 세일 연결 계산 실패(이번 빌드 미적용): %s", e)
            sale_lots, sale_links = [], {}
        sale_lot_by = {l9["id"]: l9 for l9 in sale_lots}
        try:
            of_lots9, of_links9 = self._of_manual_lots(conn, of_man, krw_of, own_dep9, rt_pair)
        except Exception as e:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_b_replay:ReplayMixin._build_replay[of_lots9]", e)
            log.warning("보낸 내역 수동 연결 원가 계산 실패(이번 빌드 미적용): %s", e)
            of_lots9, of_links9 = {}, {}
            self._of_man_state = {}
        sale_lot_by.update(of_lots9)
        sale_links.update(of_links9)
        redeem_tx = {}
        try:
            rpairs9 = sale_match.redeem_pairs(sale_lots)
            if rpairs9:
                sw9 = {}
                for r0 in rows:
                    if r0["event"] == "SWAP" and r0["leg_kind"] in ("acq", "disp"):
                        sw9.setdefault((r0["source_ns"], r0["source_id"]), []).append(r0)
                for k0, legs0 in sw9.items():
                    d0 = [x0 for x0 in legs0 if x0["leg_kind"] == "disp"]
                    a0 = [x0 for x0 in legs0 if x0["leg_kind"] == "acq"]
                    if len(d0) != 1 or len(a0) != 1 or d0[0]["location"] != a0[0]["location"] or d0[0]["chain"] != a0[0]["chain"]:
                        continue
                    pr0 = rpairs9.get((d0[0]["chain"], str(d0[0]["address"] or "").lower()))
                    if not pr0 or str(a0[0]["address"] or "").lower() != pr0["to"]:
                        continue
                    qd0, qa0 = -self._norm(d0[0]), self._norm(a0[0])
                    exp0 = qd0 * pr0["ratio"]
                    if qd0 <= 0 or qa0 <= 0 or abs(qa0 - exp0) > max(qa0, exp0) * Decimal("0.000001"):
                        continue
                    redeem_tx[k0] = {"disp": d0[0]["posting_id"], "acq": a0[0]["posting_id"], "ratio": pr0["ratio"], "carry": None}
        except Exception as e:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_b_replay:ReplayMixin._build_replay[rpairs9]", e)
            log.warning("세일 영수증 교환 판정 실패(이번 빌드 미적용): %s", e)
            redeem_tx = {}
        diag["sale_redeem_n"] = len(redeem_tx)
        sale_bid9 = {}
        for l9 in sale_lots:
            if not l9["off"]:
                for t9 in l9["bid_tx"]:
                    sale_bid9[(l9["chain"], str(t9).lower(), l9["auction"])] = l9
        sale_rf_bid, sale_rf_exit = {}, {}
        for l9 in sale_lots:
            if l9["off"]:
                continue
            for b9 in l9.get("bid_d") or ():
                if b9.get("refunded") is None or b9["refunded"] <= 0 or not b9.get("bid_tx") or not b9.get("exit_tx"):
                    continue
                e9 = {"lot": l9["id"], "id": b9.get("id"), "owner": l9["bidder"], "auction": l9["auction"], "cur": l9.get("cur_addr") or "",
                      "amt": b9["amount"], "ref": b9["refunded"], "used": Decimal(0), "pool": None}
                sale_rf_bid.setdefault((l9["chain"], b9["bid_tx"]), []).append(e9)
                sale_rf_exit.setdefault((l9["chain"], b9["exit_tx"]), []).append(e9)
        try:
            for s9 in sale_match.build_settlements(statefile.read_json(paths.state("sale_bids.json"), {}) or {}, prefs.get("sale_link_off") or (), {l9["id"] for l9 in sale_lots}):
                for b9 in s9["bid_d"]:
                    e9 = {"lot": s9["id"], "id": b9.get("id"), "owner": s9["bidder"], "auction": s9["auction"], "cur": s9.get("cur_addr") or "",
                          "amt": b9["amount"], "ref": b9["refunded"], "used": Decimal(0), "pool": None, "solo": True}
                    sale_rf_bid.setdefault((s9["chain"], b9["bid_tx"]), []).append(e9)
                    sale_rf_exit.setdefault((s9["chain"], b9["exit_tx"]), []).append(e9)
        except Exception as e:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_b_replay:ReplayMixin._build_replay[build_settlements]", e)
            log.warning("토큰 세일 정산(로트 없는 경매) 색인 실패(이번 빌드 미적용): %s", logs.safe_err(e)[:160])
        diag["sale_refund_n"], diag["sale_refund_q"], diag["sale_refund_cost"] = 0, Decimal(0), Decimal(0)
        sale_pay_bid, sale_pay_q, sale_pay_seq = {}, [], [0]
        for l9 in sale_lots:
            if l9["off"]:
                continue
            txa9 = {}
            for b9 in l9.get("bid_d") or ():
                if b9.get("bid_tx"):
                    txa9[b9["bid_tx"]] = txa9.get(b9["bid_tx"], Decimal(0)) + b9["amount"]
            for b9 in l9.get("bid_d") or ():
                if b9.get("use_usd") is None or b9.get("refunded") is None or not b9.get("bid_tx") or b9["amount"] <= 0:
                    continue
                u9 = b9["amount"] - b9["refunded"]
                if u9 <= EPS:
                    continue
                xt9 = max(int(b9.get("exit_ts") or 0), int(b9.get("bid_ts") or 0))
                if not (1_400_000_000 <= xt9 <= now + 2 * 86400):
                    continue
                try:
                    rx9 = Decimal(str(fxb.rate_at(xt9)))
                except Exception as _cg9:   # noqa: BLE001 [isolate]
                    calcguard.swallowed("view_b_replay:ReplayMixin._build_replay[rx9]", _cg9)
                    continue
                kb9 = l9.setdefault("_pay_basis", {"usd": Decimal(0), "krw": Decimal(0)})
                kb9["usd"] += b9["use_usd"]
                kb9["krw"] += b9["use_usd"] * rx9
                sale_pay_bid.setdefault((l9["chain"], b9["bid_tx"]), []).append(
                    {"lot": l9, "auction": l9["auction"], "cur": l9.get("cur_addr") or "", "txamt": txa9[b9["bid_tx"]], "use": u9, "left": u9,
                     "usd": b9["use_usd"], "ts": xt9, "exit_tx": b9.get("exit_tx") or ""})
        for p9, a9 in list(of_bridge.items()):
            if a9["key"] in sale_links:
                of_bridge.pop(p9, None)
                diag["xc_sale_drop_n"] += 1
        br_arr9 = {a9["key"] for a9 in of_bridge.values()}
        xc_pids9 = set(xc_transit)
        xc_exp9 = set()
        if xc_pids9 or sale_links or br_arr9:
            for r0 in rows:
                pid0 = r0["posting_id"]
                done0 = pid0 in sale_links or pid0 in br_arr9
                if done0:
                    xc_exp9.add((r0["source_ns"], xchain_match.norm(r0["source_id"])))
                if pid0 in xc_pids9 and (done0 or (r0["source_ns"], r0["source_id"]) in rt_pair):
                    xc_transit.pop(pid0, None)
                    diag["xc_hop_drop_n"] += 1
        if xc_exp9 and hasattr(self, "_xc_lock"):
            with self._xc_lock:
                self._xc_pending = [c9 for c9 in self._xc_pending
                                    if c9.get("kind") == "send" or (c9.get("chain"), xchain_match.norm(c9.get("tx"))) not in xc_exp9]
        sale_used = {}
        of_applied = {}
        of_cands = {}

        salein = accounting_ctx.SaleIn(ro=_ro, arr_tx_chain=arr_tx_chain, be_done=be_done, be_tax=be_tax, diag=diag, fx_dep_tx=fx_dep_tx, ob=ob, of_applied=of_applied, of_cands=of_cands, rt_out=rt_out, sale_links=sale_links, sale_lot_by=sale_lot_by, sale_pay_bid=sale_pay_bid, sale_pay_q=sale_pay_q, sale_pay_seq=sale_pay_seq, sale_rf_bid=sale_rf_bid, sale_rf_exit=sale_rf_exit, sale_used=sale_used, unverified=unverified, up_dep_by_tx=up_dep_by_tx, wd_tr=wd_tr, xf_wd=xf_wd9)
        slx = px.slx = accounting_sale.SaleBook(px, _un=_un, salein=salein, fns=fns)
        of_cand = slx.of_cand
        of_finalize = slx.of_finalize

        sale_book = slx.sale_book

        sale_refund = slx.sale_refund

        sale_pay_take = slx.sale_pay_take

        sale_pay_q_d = {}
        slx.sale_pay_q_d = sale_pay_q_d

        sale_pay_flush = slx.sale_pay_flush

        sale_pay_emit = slx.sale_pay_emit

        of_pay_on = any(str(k9).startswith("of:") for k9 in sale_lot_by)
        slx.of_pay_on = of_pay_on
        of_pay_cap, of_wd_cap = {}, {}
        slx.of_wd_cap = of_wd_cap
        slx.of_pay_cap = of_pay_cap

        of_pay_take = slx.of_pay_take

        of_wd_take = slx.of_wd_take

        of_pay_plan = slx.of_pay_plan

        sale_rf_load = slx.sale_rf_load

        loan_wd, loan_fill, loan_fsum, loan_px, lf_pend, loan_unp = {}, {}, {}, {}, [], {}

        lnx = px.lnx = accounting_loan.LoanBook(px, _qfmt=_qfmt, lf_pend=lf_pend, loan_px=loan_px)
        loan_settle = lnx.loan_settle

        loan_win = _loan_windows(self.cfg.get("loan_short"))
        if fs_on and loan_win:
            try:
                it9, lsym9 = [], {}
                for r in rows:
                    l9 = r["location"] or ""
                    if not l9.startswith("exchange:") or l9.split(":")[1] in LOAN_SKIP_EX:
                        continue
                    s9 = (l9.split(":")[1], (r["symbol"] or "").upper())
                    if s9 not in loan_win and (s9[0], "*") not in loan_win:
                        continue
                    if (r["gname"] or "") in STABLE_GROUPS or (r["kind"] == "exchange_currency" and (
                            _ex_stable_sym(r["symbol"]) or (r["symbol"] or "").upper() == "KRW")):
                        continue
                    lk9, ev9 = r["leg_kind"], r["event"]
                    k9 = ("wd" if (lk9 == "move_out" and ev9 in ("EXF_WITHDRAW", "EX_WITHDRAW")
                                   and not (ev9 == "EXF_WITHDRAW" and offc_self_wd(l9.split(":")[1], r["source_id"])))
                          or (lk9 == "disp" and ev9 == "EXF_SELL")
                          else "in" if lk9 in ("move_in", "acq") else "x")
                    kk9 = (r["group_id"] or -r["asset_id"], l9)
                    lsym9.setdefault(kk9, s9)
                    it9.append((r["posting_id"], kk9, k9, int(r["event_ts"]), self._norm(r)))

                def _lw_ok(kk9, t_wd9, t_fill9):
                    s9 = lsym9.get(kk9)
                    return bool(s9) and any(f9 <= t_wd9 and t_fill9 <= e9 for f9, e9 in (loan_win.get(s9, []) + loan_win.get((s9[0], "*"), [])))
                loan_wd, loan_fill = _loan_plan(it9, allow=_lw_ok)
                loan_fsum = {p9: sum((x9[1] for x9 in v9), Decimal(0)) for p9, v9 in loan_fill.items()}
            except Exception as e9:   # noqa: BLE001 [fallback]
                calcguard.swallowed("view_b_replay:ReplayMixin._build_replay[it9]", e9)
                log.warning("거래소 대출(공매도) 원가 계획 실패(이번 빌드 종전): %s", logs.safe_err(e9)[:160])
                loan_wd, loan_fill, loan_fsum = {}, {}, {}
        fs_sum["loan"] = {"wd": len(loan_wd), "fill": len(loan_fill), "q": float(sum(loan_wd.values(), Decimal(0))), "priced": 0, "settled": 0,
                          "v0": 0.0, "gain": 0.0}
        win_cut = {}
        qn_all9 = []
        for r in rows:
            q_w = self._norm(r)
            qn_all9.append((r, q_w))
            if r["leg_kind"] == "opening" and q_w < 0:
                continue
            if r["event"] == "TRANSFER_OUT":
                continue
            st_w = win_cut.get(r["group_id"] or -r["asset_id"])
            if st_w is None:
                st_w = win_cut[r["group_id"] or -r["asset_id"]] = [Decimal(0), Decimal(0), None]
            if loan_wd and (r["posting_id"] in loan_wd or r["posting_id"] in loan_fsum):
                q_w = q_w + loan_wd.get(r["posting_id"], Decimal(0)) - loan_fsum.get(r["posting_id"], Decimal(0))
            st_w[0] += q_w
            if st_w[0] < st_w[1]:
                st_w[1] = st_w[0]
                st_w[2] = r["event_ts"]
        win_cut_d = {}
        for r in rows:
            gid_w = r["group_id"] or -r["asset_id"]
            if gid_w in win_cut_d:
                continue
            st_w = win_cut.get(gid_w)
            if st_w is None or st_w[1] >= -EPS:
                win_cut_d[gid_w] = None
                continue
            g_w = gstate(r)
            if g_w["is_stable"] or g_w.get("is_fiat"):
                win_cut_d[gid_w] = None
                continue
            d_w = -st_w[1]
            win_cut_d[gid_w] = (d_w, st_w[2])
            cb.add_unknown(g_w, d_w)
            g_w["_wc"] = True
            note_unk(g_w, backfill_t0, "창 이전 보유분 · 창 절단 추정(원가 없음)", d_w, "", chain9=r["chain"] or "?", fs9=0)

        my_evm9 = {str(w9.get("address") or "").lower() for w9 in self._hist_wallets() if w9.get("type") != "sol"}
        my_all9 = my_evm9 | {str(w9.get("address") or "") for w9 in self._hist_wallets() if w9.get("type") == "sol"}
        spoof_keys = set()
        wbal9 = {}
        self._ph("xfer_links·positions")
        _bs9.update((k9, v9) for k9, v9 in locals().items() if k9 != "_bs9")
        if "_cg9" not in locals():
            _bs9.pop("_cg9", None)
        if "e" not in locals():
            _bs9.pop("e", None)
        if "e9" not in locals():
            _bs9.pop("e9", None)

    def _replay_main(self, _bs9):
        (G, _of_uids, _qfmt, _ro, _un, arr_groups, arr_tx_chain, backfill_t0, be_done, be_take, be_tax, br_arr9, br_transit, bridge_dep_ts, bridge_outs, conn, conv_cp, cp_ev, cp_last, cp_merge, credited_txh, cur_lab, cur_row, cur_src, cv_label, diag, ever_in, ex_debt9, ex_loan9, ex_transit, exf_dep_tx, exf_kind, extra_ev, extra_events, fee_acq, fee_diag, fee_disp, flow_of, fs_in, fs_on, fs_rbd, fs_sales, fs_sum, fx_dep_tx, fx_dep_uid_tx, fx_name, fx_transit, fx_uid_tx, fx_wd, fxb, fxdep_transit, gas_applied, gas_by_chain, gas_by_month, gas_expense, gas_nopx, gas_on, gstate, in_note, krw_last, krw_mix, krw_mkt, krw_stl, kst_fmt, lf_pend, loan_fill, loan_px, loan_unp, loan_wd, lp_done, mv_note, my_all9, my_evm9, noproc, nopx_carry, nopx_swap, now, oa_last, oa_take, ob, of_bridge, of_chain, of_dec9, of_match, of_noauto, of_pay_on, offc_add, offc_addr_add, offc_dep, offc_on, offc_pool, offc_s, offc_self_wd, offc_sold, offc_wd, pay_pid, qn_all9, realized_by_date, realized_by_loc, realized_krw_by_date, redeem_tx, ret_pool, rows, rt_back, rt_out, rt_pair, rt_same, rt_transit, sale_bid9, sale_links, sale_lot_by, sale_pay_q, sale_rf_bid, sale_rf_exit, spoof_keys, st_flow_in, stable_fx_mark, stake_inc, stake_rwd, sw9, swap_dep, swap_fill, swap_fill_est, swap_fill_zero, swap_gas, swap_pay, swap_recv, swap_wd_pre, tax_rows, to_dest9, today_kst, ton_h2u9, tx_group, ub_wd_shown, ub_wd_tx, unk_tag, unverified, up_dep_by_tx, up_dep_uid_ts, up_dep_uid_tx, up_fee, up_mkt, up_win_t0, uuid2txh, wbal9, wd_raw9, wd_tr, win_cut_d, xc_barr, xc_links, xc_transit, xc_used, xf_links, gp9, cpx, fbx, fsx, kpx, lnx, lpx, slx, unx, px, fns, cb,) = (_bs9["G"], _bs9["_of_uids"], _bs9["_qfmt"], _bs9["_ro"], _bs9["_un"], _bs9["arr_groups"], _bs9["arr_tx_chain"], _bs9["backfill_t0"], _bs9["be_done"], _bs9["be_take"], _bs9["be_tax"], _bs9["br_arr9"], _bs9["br_transit"], _bs9["bridge_dep_ts"], _bs9["bridge_outs"], _bs9["ctx"].conn, _bs9["conv_cp"], _bs9["cp_ev"], _bs9["cp_last"], _bs9["cp_merge"], _bs9["credited_txh"], _bs9["cur_lab"], _bs9["cur_row"], _bs9["cur_src"], _bs9["cv_label"], _bs9["diag"], _bs9["ever_in"], _bs9["ex_debt9"], _bs9["ex_loan9"], _bs9["ex_transit"], _bs9["exf_dep_tx"], _bs9["exf_kind"], _bs9["extra_ev"], _bs9["extra_events"], _bs9["fee_acq"], _bs9["fee_diag"], _bs9["fee_disp"], _bs9["flow_of"], _bs9["fs_in"], _bs9["ctx"].fs_on, _bs9["fs_rbd"], _bs9["fs_sales"], _bs9["fs_sum"], _bs9["fx_dep_tx"], _bs9["fx_dep_uid_tx"], _bs9["fx_name"], _bs9["fx_transit"], _bs9["fx_uid_tx"], _bs9["fx_wd"], _bs9["ctx"].fxb, _bs9["fxdep_transit"], _bs9["gas_applied"], _bs9["gas_by_chain"], _bs9["gas_by_month"], _bs9["gas_expense"], _bs9["gas_nopx"], _bs9["ctx"].gas_on, _bs9["gstate"], _bs9["in_note"], _bs9["krw_last"], _bs9["krw_mix"], _bs9["krw_mkt"], _bs9["krw_stl"], _bs9["kst_fmt"], _bs9["lf_pend"], _bs9["loan_fill"], _bs9["loan_px"], _bs9["loan_unp"], _bs9["loan_wd"], _bs9["lp_done"], _bs9["mv_note"], _bs9["my_all9"], _bs9["my_evm9"], _bs9["noproc"], _bs9["nopx_carry"], _bs9["nopx_swap"], _bs9["ctx"].now, _bs9["oa_last"], _bs9["oa_take"], _bs9["ob"], _bs9["of_bridge"], _bs9["of_chain"], _bs9["of_dec9"], _bs9["of_match"], _bs9["of_noauto"], _bs9["of_pay_on"], _bs9["offc_add"], _bs9["offc_addr_add"], _bs9["offc_dep"], _bs9["ctx"].offc_on, _bs9["offc_pool"], _bs9["offc_s"], _bs9["offc_self_wd"], _bs9["offc_sold"], _bs9["offc_wd"], _bs9["pay_pid"], _bs9["qn_all9"], _bs9["realized_by_date"], _bs9["realized_by_loc"], _bs9["realized_krw_by_date"], _bs9["redeem_tx"], _bs9["ret_pool"], _bs9["rows"], _bs9["rt_back"], _bs9["rt_out"], _bs9["rt_pair"], _bs9["rt_same"], _bs9["rt_transit"], _bs9["sale_bid9"], _bs9["sale_links"], _bs9["sale_lot_by"], _bs9["sale_pay_q"], _bs9["sale_rf_bid"], _bs9["sale_rf_exit"], _bs9["spoof_keys"], _bs9["st_flow_in"], _bs9["stable_fx_mark"], _bs9["stake_inc"], _bs9["stake_rwd"], _bs9["sw9"], _bs9["swap_dep"], _bs9["swap_fill"], _bs9["swap_fill_est"], _bs9["swap_fill_zero"], _bs9["swap_gas"], _bs9["swap_pay"], _bs9["swap_recv"], _bs9["swap_wd_pre"], _bs9["tax_rows"], _bs9["to_dest9"], _bs9["ctx"].today_kst, _bs9["ton_h2u9"], _bs9["tx_group"], _bs9["ub_wd_shown"], _bs9["ub_wd_tx"], _bs9["unk_tag"], _bs9["unverified"], _bs9["up_dep_by_tx"], _bs9["up_dep_uid_ts"], _bs9["up_dep_uid_tx"], _bs9["up_fee"], _bs9["up_mkt"], _bs9["up_win_t0"], _bs9["uuid2txh"], _bs9["wbal9"], _bs9["wd_raw9"], _bs9["wd_tr"], _bs9["win_cut_d"], _bs9["xc_barr"], _bs9["xc_links"], _bs9["xc_transit"], _bs9["xc_used"], _bs9["xf_links"], _bs9["gp9"], _bs9["cpx"], _bs9["fbx"], _bs9["fsx"], _bs9["kpx"], _bs9["lnx"], _bs9["lpx"], _bs9["slx"], _bs9["unx"], _bs9["px"], _bs9["fns"], _bs9["cb"],)
        (br_fee_add, consume, consume_krw, cp_add, cp_add_map, cp_emit, cp_sync, cp_take, cp_xc, ev, ex_fee_add, fee_day_add, fee_expense, fee_gain, fee_unit, fs_mark, fs_rec, fs_ret, fs_st, krw_inh, krw_of, krw_rec, krw_took, loan_settle, lp_move, lp_tx, note_unk, of_cand, of_pay_take, of_wd_take, sale_book, sale_pay_flush, sale_pay_take, sale_refund, sale_rf_load, stl_add, stl_carry, stl_in, stl_krw_mkt, stl_out, stl_src, stl_use, tax_krw_acq, wd_fee_add, wd_fee_q,) = (fbx.br_fee_add, cpx.consume, kpx.consume_krw, cpx.cp_add, cpx.cp_add_map, cpx.cp_emit, cpx.cp_sync, cpx.cp_take, cpx.cp_xc, cpx.ev, fbx.ex_fee_add, fbx.fee_day_add, fbx.fee_expense, fbx.fee_gain, fbx.fee_unit, fsx.fs_mark, fsx.fs_rec, fsx.fs_ret, fsx.fs_st, kpx.krw_inh, kpx.krw_of, kpx.krw_rec, kpx.krw_took, lnx.loan_settle, lpx.lp_move, lpx.lp_tx, unx.note_unk, slx.of_cand, slx.of_pay_take, slx.of_wd_take, slx.sale_book, slx.sale_pay_flush, slx.sale_pay_take, slx.sale_refund, slx.sale_rf_load, kpx.stl_add, kpx.stl_carry, kpx.stl_in, kpx.stl_krw_mkt, kpx.stl_out, kpx.stl_src, kpx.stl_use, fbx.tax_krw_acq, fbx.wd_fee_add, fbx.wd_fee_q,)
        if calcguard.strict():
            accounting_books.check_pool_aliases(_bs9, "br_fee_add consume consume_krw cp_add cp_add_map cp_emit cp_sync cp_take cp_xc ev ex_fee_add fee_day_add fee_expense fee_gain fee_unit fs_mark fs_rec fs_ret fs_st krw_inh krw_of krw_rec krw_took loan_settle lp_move lp_tx note_unk of_cand of_pay_take of_wd_take sale_book sale_pay_flush sale_pay_take sale_refund sale_rf_load stl_add stl_carry stl_in stl_krw_mkt stl_out stl_src stl_use tax_krw_acq wd_fee_add wd_fee_q", (br_fee_add, consume, consume_krw, cp_add, cp_add_map, cp_emit, cp_sync, cp_take, cp_xc, ev, ex_fee_add, fee_day_add, fee_expense, fee_gain, fee_unit, fs_mark, fs_rec, fs_ret, fs_st, krw_inh, krw_of, krw_rec, krw_took, loan_settle, lp_move, lp_tx, note_unk, of_cand, of_pay_take, of_wd_take, sale_book, sale_pay_flush, sale_pay_take, sale_refund, sale_rf_load, stl_add, stl_carry, stl_in, stl_krw_mkt, stl_out, stl_src, stl_use, tax_krw_acq, wd_fee_add, wd_fee_q,), "main")
        fx9: object
        ks9: object
        l9: object
        ln9: object
        mk9: object
        if "r" in _bs9:
            r = _bs9["r"]
        sg9: object
        sv9: object
        u9: object
        signer9 = self._signer_map(conn, rows)
        movein = accounting_ctx.MoveIn(ro=_ro, br_transit=br_transit, ever_in=ever_in, ex_transit=ex_transit, fxdep_transit=fxdep_transit, my_all=my_all9, of_bridge=of_bridge, of_dec=of_dec9, of_match=of_match, of_noauto=of_noauto, rt_back=rt_back, rt_same=rt_same, rt_transit=rt_transit, sale_bid=sale_bid9, signer=signer9, up_dep_uid_ts=up_dep_uid_ts, up_win_t0=up_win_t0)
        omx = px.omx = accounting_outmove.OutMove(px, _un=_un, movein=movein, fns=fns)
        out_move = omx.out_move
        pid_row = {}
        sell_wm = {}
        bo_pid = {}
        br_plan = {}
        br_amb = {}
        br_sum = {}
        br_natfee = set()
        self._br_early = None
        try:
            br_deps9, br_arrs9 = [], []
            links9 = {k9: (v9[0], xchain_match.norm(v9[1])) for k9, v9 in xc_links.items()}
            K9 = (lambda c9: c9) if (not rows or isinstance(rows[0], dict)) else list(rows[0].keys()).index
            iEV9, iLK9 = K9("event"), K9("leg_kind")
            for o9, r9 in enumerate(rows):
                lk9 = r9[iLK9]
                if lk9 != "move_out" and lk9 != "acq":
                    continue
                ev9 = r9[iEV9]
                if ev9 == "BRIDGE" and lk9 == "move_out":
                    t9 = str(r9["source_id"] or "")
                    if t9.lower() in fx_dep_tx or t9 in fx_dep_tx or int(r9["qty_base"]) >= 0 or (r9["source_ns"], t9) in nopx_swap:
                        continue
                    br_deps9.append({"pid": r9["posting_id"], "ord": o9, "sym": self._gsym(r9), "qty": -self._norm(r9), "ts": int(r9["event_ts"]),
                                     "chain": r9["chain"] or "?", "addr": str(r9["address"] or "").lower(),
                                     "link": (r9["source_ns"], xchain_match.norm(t9))})
                    br_deps9[-1]["nat"] = (r9["kind"] or "") == "native"
                elif lk9 == "acq" and ev9 in ("TRANSFER_IN", "PROGRAM_IN") and r9["cost_usd"] is None and int(r9["qty_base"]) > 0:
                    if ((r9["gname"] or "") in STABLE_GROUPS or (r9["kind"] == "exchange_currency" and _ex_stable_sym(r9["symbol"]))) \
                            and (r9["source_ns"], xchain_match.norm(str(r9["source_id"] or ""))) not in links9:
                        continue
                    t9 = str(r9["source_id"] or "")
                    p9 = r9["posting_id"]
                    if (p9 in xc_transit or p9 in br_arr9 or p9 in sale_links
                            or (r9["source_ns"], t9) in rt_pair or _txk(t9) in fx_wd or _txk(t9) in ub_wd_tx):
                        continue
                    ca9 = f"{r9['source_ns']}:{(r9['address'] or '').lower()}"
                    strong9 = bool(((gp9.get(ca9) or {}).get("risk") or {}).get("strong")) if isinstance(gp9, dict) else False
                    br_arrs9.append({"pid": p9, "ord": o9, "sym": self._gsym(r9), "qty": self._norm(r9), "ts": int(r9["event_ts"]),
                                     "chain": r9["chain"] or "?", "addr": str(r9["address"] or "").lower(),
                                     "link": (r9["source_ns"], xchain_match.norm(t9)),
                                     "spam": strong9 or bool(spamguard.impostor_of(r9["symbol"])),
                                     "bridge": (r9["source_ns"], xchain_match.norm(t9)) in xc_barr})
            tok_links = {d9["link"] for d9 in br_deps9 if not d9.get("nat")}
            br_natfee = {d9["pid"] for d9 in br_deps9 if d9.get("nat") and d9["link"] in tok_links}
            if br_natfee:
                nat_linked = {(links9[a9["link"]], a9["sym"]) for a9 in br_arrs9 if a9["link"] in links9}
                br_natfee = {d9["pid"] for d9 in br_deps9 if d9["pid"] in br_natfee and (d9["link"], d9["sym"]) not in nat_linked}
            if br_deps9 and br_arrs9:
                br_plan = _bridge_plan(br_deps9, br_arrs9, links9, br_amb)
                ba9 = {a9["pid"]: a9 for a9 in br_arrs9}
                bd9 = {d9["pid"]: d9["ord"] for d9 in br_deps9}
                for ap9, dp9 in br_plan.items():
                    br_sum[dp9] = br_sum.get(dp9, Decimal(0)) + ba9[ap9]["qty"]
                early9 = [(ba9[ap9]["ord"], bd9[dp9]) for ap9, dp9 in br_plan.items() if ba9[ap9]["ord"] < bd9[dp9]]
                if early9:
                    mv9, kept9 = _ord_pair_moves(rows, early9)
                    if mv9:
                        rows = _ord_splice(rows, mv9)
                    self._br_early = (len(early9), len(mv9), kept9)
            self._br_plan_n = len(br_plan)
        except Exception as e9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_b_replay:ReplayMixin._build_replay[br_deps9#1]", e9)
            log.warning("브릿지 도착 짝 계산 실패(이번 빌드 대체 매칭 없음): %s", logs.safe_err(e9)[:160])
            br_plan, br_amb, br_sum, br_natfee = {}, {}, {}, set()
        self._disc_back = disc_bk9 = set()
        try:
            balw_disc9 = {r9[0] for r9 in conn.execute("SELECT obs_id FROM raw_observations WHERE obs_id LIKE 'recon:%:disc:%'"
                                                        " AND instr(payload, ?) > 0", ('"bsc_balance_watch"',))}
        except Exception as _cg9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_b_replay:ReplayMixin._build_replay[br_deps9#2]", _cg9)
            balw_disc9 = set()
        g0_9, n9i = self.__dict__.get("_ph_gen0"), 0
        F9: object; _rl9: object; arr_gid: object; chg9f: object; cv9: object; cvk9: object; d5: object; d6: object
        e4: object; e5: object; ex_fee9: object; flow: object; fu9: object; g2: object; gn9: object; hl9: object
        ikr7: object; inh7: object; k2: object; kd9: object; kg9: object; lab9: object; lb9: object; mc9: object
        mu9: object; np9: object; nx9: object; qty: object; rb9: object; rd9: object; sc7: object; so9: object
        sp9: object; st7: object; st9: object; take7: object; take9: object; td9: object; tk9: object; u: object
        unit9: object

        def _h_opening():
            nonlocal hl9, lab9, ln9, rb9
            disc9 = ":disc:" in str(r["source_id"] or "")
            back_o = q < 0 and (r["source_ns"] or "") != "upbit:recon_comp" and not disc9
            xk9 = exf_kind(r)
            late9 = evk == "EXF_ADJUST" and str(r["source_id"] or "").startswith("exflate:")
            if xk9 == "fix" or late9:
                back_o = False
            try:
                rb9 = int(str(r["source_id"]).rsplit(":", 1)[1])
            except (IndexError, ValueError):
                rb9 = ts
            at9 = "대사 시각" if ts >= rb9 - 60 else ("원장이 처음 모자란 때로 당김" if q > 0 else "잔고가 남던 구간 시작으로 당김")
            hl9 = xk9 == "fix" and (r["source_ns"] or "") == "hyperliquid:recon" and (r["symbol"] or "").upper() in _hl_cash_syms()
            hl_lab9 = "Hyperliquid 무기한 손익·펀딩 정산 (그 대사 구간 합 — 대사 시각)"
            fut9 = histmark.exf_is_fut(evk, r["source_ns"])
            fut_lab9 = "선물 정산 · 실현 손익·수수료·펀딩 (선물 지갑 잔고 — 정산 시각)"
            disc_b9 = disc9 and q > 0 and not _scam_name(r["symbol"]) and str(r["source_id"] or "") not in balw_disc9
            t_tl9 = min(ts, backfill_t0) if (back_o or disc_b9) else ts
            cb.snapshot(g, t_tl9, q)
            if disc_b9 or (disc9 and q > 0 and str(r["source_id"] or "") in balw_disc9):
                g.setdefault("disc_tl", []).append((ts, q))
            if disc_b9:
                disc_bk9.add(g["gid"])
            if evk == "OPENING":
                g.setdefault("open_tl", []).append((t_tl9, q))
            if q > 0:
                if g["is_stable"]:
                    cb.acquire(g, q, q)
                    fs_st(g, ts, q, chain)
                else:
                    cb.add_unknown(g, q)
                    if late9:
                        note_unk(g, ts, "늦게 찾은 과거 체결 상쇄 유입(원가 없음)", q, "", chain9=chain)
                    elif evk in ("EXF_ADJUST", "EX_ADJUST"):
                        note_unk(g, ts, "거래소 잔고 정정 유입(원가 없음)", q, "", chain9=chain)
                    elif ":stake:" in (r["location"] or ""):
                        note_unk(g, ts, "솔라나 스테이킹 기초 잔고 · 수집 시작 이전 위임분(원가 없음)", q, "", chain9=chain)
                    elif disc9:
                        note_unk(g, ts, (f"{CHAIN_NAME.get(chain, chain)} " if chain and chain != "?" else "") + DISC_OPEN_KO_UNK, q, "", chain9=chain)
                    else:
                        note_unk(g, ts, (f"{CHAIN_NAME.get(chain, chain)} " if chain and chain != "?" else "") + "기초 잔고 · 수집 시작 이전 보유분(원가 없음)", q, "", chain9=chain)
                if late9:
                    extra_ev(ts, g, "전송", f"{cur_lab[0] or CHAIN_NAME.get(chain, chain)} · {type(self).LATE_OFFSET_KO}",
                             _recon_q(q), "—", txh, vq=q)
                elif xk9 == "fix" or (xk9 == "init" and ts > backfill_t0 + 86400):
                    lab9 = ("원화 정산 · 체결 원화 순지출(예수금에서 나감)·코인 모으기·은행 입금 (원화는 원장 밖 — 예수금은 따로 표시)"
                            if g.get("is_fiat") else fut_lab9 if fut9 else hl_lab9 if hl9 else
                            f"잔고 정정 · 수집 누락 추정 (원인 모름 — 수집 밖 유입, 예: 이자·내부 이체 · {at9})")
                    extra_ev(ts, g, "전송", f"{cur_lab[0] or CHAIN_NAME.get(chain, chain)} · {lab9}",
                             _recon_q(q), "—", txh, vq=q)
                else:
                    extra_ev(ts, g, "전송", f"{cur_lab[0] or CHAIN_NAME.get(chain, chain)} · "
                             + (DISC_OPEN_KO if disc9 else "기초 잔고 (백필 창 이전 보유분)"),
                             _recon_q(q), "—", txh, vq=q)
            else:
                is_int = not g.get("is_fiat") and histmark.exf_is_debt_int(evk, r["leg_seq"], r["source_ns"], r["source_id"])
                is_futfee = fut9 and not g["is_stable"] and not g.get("is_fiat")
                u9o = None
                if is_int or is_futfee:
                    u9o = Decimal(1) if g["is_stable"] else None
                    if u9o is None:
                        cp9o = _fx_candle_near(fxb, g["sym"], ts)
                        u9o = Decimal(str(cp9o)) if cp9o else (g["cost"] / g["qty_known"] if g["qty_known"] > EPS else None)
                    if u9o is not None and u9o <= 0:
                        u9o = None
                if u9o is None:
                    consume(g, -q, cp=False)
                else:
                    ex9o = (r["location"] or "").split(":")[-1]
                    if is_int and gas_on:
                        fee_expense((-q) * u9o, ts, dkey, "LOAN_INT", fx_name.get(ex9o, ex9o))
                    mc_o, mk_o, mu_o = consume(g, -q)
                    fee_gain(g, u9o, mk_o, mc_o, ts, dkey, chain, krw_last[0], mix9=krw_mix[0], stl9=krw_stl[0],
                             cmp9=cp_emit(cp_last[0], mu_o, mk_o + mu_o, mc_o),
                             lab9="대출 이자로 쓴 코인(처분)" if is_int else "선물 정산 수수료로 쓴 코인(처분)")
                if late9:
                    extra_ev(ts, g, "전송", f"{cur_lab[0] or CHAIN_NAME.get(chain, chain)} · {type(self).LATE_OFFSET_KO}",
                             _recon_q(q), "—", txh, vq=q)
                elif xk9 == "fix":
                    db9 = (ex_debt9.get(r["source_ns"]) or {}).get((r["symbol"] or "").upper())
                    ln9 = (ex_loan9.get(r["source_ns"]) or {}).get((r["symbol"] or "").upper())
                    try:
                        rb9 = int(str(r["source_id"]).rsplit(":", 1)[1])
                    except (IndexError, ValueError):
                        rb9 = ts
                    if histmark.exf_is_debt_int(evk, r["leg_seq"], r["source_ns"], r["source_id"]):
                        lab9 = f"{ln9 + ' 이자' if ln9 else '마진 차입 이자'} · 부채 이자 누적 {_recon_q(-q)} (비용 — 총자산에서 뺌, 대사 시각)"
                    elif db9 is not None and -db9 * Decimal("0.5") <= -q <= -db9 * Decimal("1.01") + EPS:
                        if ts < rb9 - 60:
                            lab9 = f"기존 부채 첫 반영 · {ln9 or '마진 차입'} {_recon_q(-q)} — 이때부터 보유 (총자산에서 뺌)"
                        else:
                            lab9 = f"{ln9 + ' 부채' if ln9 else '마진 부채'} 반영 · 차입 {_recon_q(-q)} 차감 (총자산에서 뺌 — 대사 시각)"
                    elif g.get("is_fiat"):
                        lab9 = "원화 잔고 정정(감소) · 수집 밖 출금·결제 추정 (대사 시각)"
                    elif fut9:
                        lab9 = fut_lab9
                    elif hl9:
                        lab9 = hl_lab9
                    else:
                        lab9 = f"잔고 정정(감소) · 원인 모름 — 수집 밖 이동 추정 (예: 예치·내부 이체 · {at9})"
                    extra_ev(ts, g, "전송", f"{cur_lab[0] or CHAIN_NAME.get(chain, chain)} · {lab9}",
                             _recon_q(q), "—", txh, vq=q)
                elif str(r["location"] or "").startswith("exchange:") and (r["source_ns"] or "") != "upbit:recon_comp":
                    extra_ev(ts, g, "전송", f"{cur_lab[0] or CHAIN_NAME.get(chain, chain)} · 잔고 정정(감소) · 원장에만 있던 수량 제거"
                             " (수집 밖 유출·예치 추정 — 과거 창 정착)", _recon_q(q), "—", txh, vq=q)
            return

        def _h_gas_exf_wd_fee():
            fq9w = -q
            unit9w = Decimal(1) if g["is_stable"] else None
            if unit9w is None and not g.get("is_fiat"):
                cp9w = _fx_candle_near(fxb, g["sym"], ts)
                if cp9w:
                    unit9w = Decimal(str(cp9w))
            if unit9w is None and g["qty_known"] > EPS:
                unit9w = g["cost"] / g["qty_known"]
            if unit9w is None and fq9w > 0:
                fee_diag["wd_no_px"] += 1
            usd9w = fq9w * unit9w if (unit9w is not None and fq9w > 0) else Decimal(0)
            wd_fee_add((r["location"] or "").split(":")[-1], usd9w, ts)
            if gas_on and usd9w > 0:
                rt9w = fxb.rate_at(ts)
                realized_by_date[dkey] = realized_by_date.get(dkey, 0) - float(usd9w)
                realized_krw_by_date[dkey] = realized_krw_by_date.get(dkey, 0) - float(usd9w) * rt9w
                ge9w = gas_expense.setdefault(dkey, [Decimal(0), 0, 0.0, {}])
                ge9w[0] += usd9w
                ge9w[1] += 1
                ge9w[2] += float(usd9w) * rt9w
                kd9w = ge9w[3].setdefault("EXF_WD_FEE", [Decimal(0), 0, Decimal(0), 0, ""])
                kd9w[0] += usd9w
                kd9w[1] += 1
                if usd9w > kd9w[2]:
                    kd9w[2], kd9w[3], kd9w[4] = usd9w, int(ts or 0), (r["location"] or "").split(":")[-1]
            fw9 = usd9w > 0
            mcw9, mkw9, _muw9 = consume(g, -q, cp=fw9)
            if fw9:
                fee_gain(g, unit9w, mkw9, mcw9, ts, dkey, chain, krw_last[0], mix9=krw_mix[0], stl9=krw_stl[0],
                         cmp9=cp_emit(cp_last[0], _muw9, mkw9 + _muw9, mcw9))
            cb.snapshot(g, ts, q)
            return

        def _h_gas():
            nonlocal g2, gn9, kd9, mk9
            usd = cost or Decimal(0)
            if gas_on and usd > 0 and not (evk == "SWAP" and (swap_gas.get((r["source_ns"], txh)) or {}).get("done")):
                rt9g = fxb.rate_at(ts)
                realized_by_date[dkey] = realized_by_date.get(dkey, 0) - float(usd)
                realized_krw_by_date[dkey] = realized_krw_by_date.get(dkey, 0) - float(usd) * rt9g
                ge9 = gas_expense.setdefault(dkey, [Decimal(0), 0, 0.0, {}])
                ge9[0] += usd
                ge9[1] += 1
                ge9[2] += float(usd) * rt9g
                kd9 = ge9[3].setdefault(evk or "?", [Decimal(0), 0, Decimal(0), 0, ""])
                kd9[0] += usd
                kd9[1] += 1
                if usd > kd9[2]:
                    kd9[2], kd9[3], kd9[4] = usd, int(ts or 0), chain
            cinfo = gas_by_chain.setdefault(chain, {"usd": Decimal(0), "tx": 0})
            cinfo["usd"] += usd
            cinfo["tx"] += 1
            mk9 = kst_fmt(ts, "%Y-%m")
            mi9 = gas_by_month.setdefault(mk9, {}).setdefault(
                chain, {"usd": Decimal(0), "tx": 0})
            mi9["usd"] += usd
            mi9["tx"] += 1
            fee_day_add(usd, ts)
            ent2 = tx_group.get((r["source_ns"], txh))
            if ent2 is not None and ent2[0] in G:
                g2 = G[ent2[0]]
                tgt = g2["cur"] or (g2["flows"][-1] if g2["flows"] else None)
                if tgt:
                    tgt["fee"] += usd
            fg9 = usd > 0 and q < 0
            mcg9, mkg9, _mug9 = consume(g, -q, cp=fg9)
            if usd <= 0 and q < 0 and mcg9 > EPS:
                gn9 = gas_nopx.setdefault(g["gid"], {"sym": g["sym"], "n": 0, "qty": Decimal(0), "cost": Decimal(0), "first": ts, "last": ts, "chains": set()})
                gn9["n"] += 1; gn9["qty"] += -q; gn9["cost"] += mcg9; gn9["last"] = max(gn9["last"], ts); gn9["chains"].add(chain)
            if fg9:
                fee_gain(g, usd / (-q), mkg9, mcg9, ts, dkey, chain, krw_last[0], mix9=krw_mix[0], stl9=krw_stl[0],
                         cmp9=cp_emit(cp_last[0], _mug9, mkg9 + _mug9, mcg9))
            cb.snapshot(g, ts, q)
            return

        def _h_ex_deposit():
            nonlocal d5, e2, ikr7, inh7, old9, sc7, st7, take7
            g.setdefault("ex_dep", set()).add("upbit")
            cb.snapshot(g, ts, q)
            txh2 = uuid2txh.get(r["source_id"])
            all5 = ex_transit.get(txh2, []) if txh2 else []
            syms5 = {acct_norm.canon(e2.get("raw_sym", "")) for e2 in all5}
            cur5 = acct_norm.canon(g["sym"], "upbit")
            cands5 = [e2 for e2 in all5
                      if not e2["used"] and e2["qty"] > 0 and (len(syms5) <= 1 or acct_norm.canon(e2.get("raw_sym", "")) == cur5)]
            ents = []
            tot5 = sum((e2["qty"] for e2 in cands5), Decimal(0))
            sp5 = any(e2.get("split") for e2 in cands5)
            if cands5 and not sp5 and abs(q - tot5) <= tot5 * Decimal("0.01"):
                ents = cands5
            else:
                for e2 in (sorted(cands5, key=lambda e9: abs(q - e9["qty"])) if sp5 else cands5):
                    if abs(q - e2["qty"]) <= e2["qty"] * Decimal("0.01"):
                        ents = [e2]
                        break
            ent = ents[0] if ents else None
            qs5 = f"{q:,.4f}".rstrip("0").rstrip(".")
            lnk5 = None
            e7u = xl7 = None
            if not ent:
                t7u = up_dep_uid_tx.get(r["source_id"])
                if t7u:
                    e7u = fx_transit.get(t7u) or fx_transit.get(t7u.lower())
                    if e7u and (e7u.get("ambiguous") or e7u.get("ex") == "upbit" or e7u["left"] <= 0
                                or q > e7u["left"] * Decimal("1.02")
                                or not (acct_norm.same_asset(e7u.get("sym"), e7u.get("ex"), g["sym"], "upbit")
                                        or acct_norm.qty_close(q, e7u["left"]))):
                        e7u = None
                if not e7u and r["source_id"] in xf_links:
                    xl7 = xf_links[r["source_id"]]
                    e7u = fx_transit.get(xl7["key"])
                    if e7u and (e7u.get("ambiguous") or not acct_norm.same_asset(e7u.get("sym"), e7u.get("ex"), g["sym"], "upbit")
                                or e7u.get("ex") == "upbit" or e7u["left"] <= 0
                                or q > e7u["left"] * Decimal("1.02")):
                        e7u = None
            if ent:
                tot_e = sum((e2["qty"] for e2 in ents), Decimal(0))
                ratio5 = min(q / tot_e, Decimal(1)) if tot_e > 0 else Decimal(1)
                inh5 = Decimal(0)
                ikr5 = Decimal(0)
                kc5s = kk5s = fk5s = Decimal(0)
                for e2 in ents:
                    e2["used"] = True
                    if e2.get("gid") in G:
                        G[e2["gid"]]["risk_allow"] = True
                    cb.add_known(g, e2["known"] * ratio5)
                    cp_add_map(g, e2.get("_cmp"), ratio5)
                    cb.add_unknown(g, e2["unknown"] * ratio5)
                    note_unk(g, ts, "업비트 입금 · 내 지갑 출금 승계(원가 없음)", e2["unknown"] * ratio5, txh2, ex9="upbit", up_gid=e2.get("gid"), unc9=Decimal(0), fs9=0)
                    inh5 += e2["cost"] * ratio5
                    ikr5 += krw_inh(e2, e2["cost"] * ratio5, ts)
                    kc5s += (e2.get("kc") or Decimal(0)) * ratio5
                    kk5s += (e2.get("kk") or Decimal(0)) * ratio5
                    fk5s += (e2.get("fk") or Decimal(0)) * ratio5
                    diag["ex_dep_fee_resid_cost"] += e2["cost"] * (Decimal(1) - ratio5)
                cb.add_unknown(g, max(Decimal(0), q - tot_e))
                note_unk(g, ts, "업비트 입금 초과분(원가 없음)", max(Decimal(0), q - tot_e), txh2 or r["source_id"], ex9="upbit", unc9=Decimal(0))
                cb.add_cost(g, inh5)
                diag["ex_dep_inh_cost"] += inh5
                diag["ex_dep_inh_n"] += 1
                flow5 = flow_of(g, ts, chain)
                flow5["bought"] += q
                flow5["cost"] += kc5s if g["is_stable"] else inh5
                flow5["cost_krw"] += kk5s if g["is_stable"] else ikr5
                if g["is_stable"]:
                    for e2 in ents:
                        stl_in(flow5, e2, ratio5)
                    fs_in(flow5, {"fk": fk5s}, Decimal(1))
                in_note(flow5, "내 지갑", q, inh5, ts, cost_krw=ikr5)
                known5 = sum((e2["known"] for e2 in ents), Decimal(0)) * ratio5
                lnk5 = [(sp9, float(ratio5) * w9) for e2 in ents for sp9, w9 in e2.get("_src", ())]
                d5 = (f"업비트 입금 완료 · 원장 이관 (원가 승계 ${float(inh5):,.2f})" if known5 > EPS
                      else "업비트 입금 완료 · 원장 이관 (원가 미상 승계)")
            elif e7u:
                take7 = min(q, e7u["left"])
                e7u["left"] -= take7
                sc7 = take7 / e7u["qty"] if e7u["qty"] > 0 else Decimal(1)
                inh7 = e7u["cost"] * sc7
                lnk5 = [(sp9, float(sc7) * w9) for sp9, w9 in e7u.get("_src", ())]
                if e7u.get("oa"):
                    g["oa"] = (g.get("oa") or Decimal(0)) + e7u["oa"] * sc7
                cb.add_known(g, e7u["known"] * sc7)
                cp_add_map(g, e7u.get("_cmp"), sc7)
                cb.add_unknown(g, e7u["unknown"] * sc7 + (q - take7))
                note_unk(g, ts, "업비트 입금 · 해외거래소 출금 승계 잔여(원가 없음)", e7u["unknown"] * sc7 + (q - take7), up_dep_uid_tx.get(r["source_id"]) or r["source_id"], ex9="upbit", unc9=q - take7, fs9=q - take7,
                         up_gid=e7u.get("gid"), via9=f"{fx_name.get(e7u.get('ex'), e7u.get('ex'))} 출금 승계 (그 거래소 {e7u.get('sym')} 의 원가 미상분)")
                cb.add_cost(g, inh7)
                flow5 = flow_of(g, ts, chain)
                flow5["bought"] += take7
                ikr7 = krw_inh(e7u, inh7, ts)
                if g["is_stable"]:
                    flow5["cost"] += (e7u.get("kc") or Decimal(0)) * sc7
                    flow5["cost_krw"] += (e7u.get("kk") or Decimal(0)) * sc7
                    stl_in(flow5, e7u, sc7)
                    fs_in(flow5, e7u, sc7)
                else:
                    flow5["cost"] += inh7
                    flow5["cost_krw"] += ikr7
                st7 = e7u.pop("story", None)
                if st7:
                    flow5["events"][:0] = st7
                in_note(flow5, fx_name.get(e7u["ex"], e7u["ex"]), take7, inh7, ts, st7, cost_krw=ikr7)
                d5 = (f"업비트 입금 완료 · {fx_name.get(e7u['ex'], e7u['ex'])}"
                      + (f" 출금 원가 승계 (${float(inh7):,.2f})" if e7u["known"] * sc7 > EPS
                         else " 출금 이관 (원가 미상 승계)")
                      + (f" · {xl7['label']}" if xl7 else ""))
            elif of_cand(r, g, q, ts, up_dep_uid_tx.get(r["source_id"]) or r["source_id"]):
                pass
            elif (not g["is_stable"] and r["posting_id"] in sale_links
                  and sale_book(g, r, q, ts, chain, up_dep_uid_tx.get(r["source_id"]) or r["source_id"])):
                d5 = "업비트 입금 완료 · 토큰 세일 원가 (입찰 지갑에서 직접 입금)"
            elif g["is_stable"]:
                cb.acquire(g, q, q)
                fs_st(g, ts, q, chain)
                d5 = "업비트 입금 완료 (스테이블 액면)"
            elif (up_dep_uid_tx.get(r["source_id"]) or "").startswith("swap_") and \
                    up_dep_uid_tx[r["source_id"]] in swap_wd_pre and up_dep_uid_tx[r["source_id"]] not in swap_dep:
                t9s = up_dep_uid_tx[r["source_id"]]
                old9 = swap_wd_pre[t9s]
                e9s = fx_transit.get(t9s)
                if e9s and e9s.get("ex") == "upbit" and not e9s.get("ambiguous") and e9s["left"] > 0 and e9s["qty"] > 0:
                    sc9s = e9s["left"] / e9s["qty"]
                    e9s["left"] = Decimal(0)
                    kq9s = q * min(Decimal(1), e9s["known"] / e9s["qty"])
                    c9s = e9s["cost"] * sc9s
                    cb.add_known(g, kq9s)
                    cb.add_unknown(g, q - kq9s)
                    cb.add_cost(g, c9s)
                    fl9s = flow_of(g, ts, chain)
                    fl9s["bought"] += q
                    fl9s["cost"] += c9s
                    fl9s["cost_krw"] += krw_inh(e9s, c9s, ts)
                    note_unk(g, ts, f"업비트 토큰 전환 입금 · {old9['sym']} → {g['sym']} (구 토큰 원가 없음)", q - kq9s, t9s, ex9="upbit", fs9=0,
                             up_gid=old9["gid"], unc9=Decimal(0), via9=f"업비트 토큰 전환 ({old9['sym']} 출금)")
                else:
                    cb.add_unknown(g, q)
                    note_unk(g, ts, f"업비트 토큰 전환 입금 · {old9['sym']} → {g['sym']} (구 토큰 원가 없음)", q, t9s, ex9="upbit", fs9=0,
                             up_gid=old9["gid"], via9=f"업비트 토큰 전환 ({old9['sym']} 출금)")
                    lst9s = g.get("unk_src") or []
                    swap_dep[t9s] = {"g": g, "q": q, "ent": lst9s[-1] if lst9s and lst9s[-1].get("ref") == t9s else None}
                d5 = f"업비트 토큰 전환 입금 ({old9['sym']} → {g['sym']} · 구 토큰 원가 승계)"
            else:
                cb.add_unknown(g, q)
                note_unk(g, ts, "업비트 입금(원가 없음 · 링크 없음)", q, up_dep_uid_tx.get(r["source_id"]) or r["source_id"], ex9="upbit")
                diag["ex_dep_unlinked_n"] += 1
                d5 = "업비트 입금 완료 (원가 미상)"
            if g["is_stable"] or not g["cur"]:
                extra_ev(ts, g, "입금 확인", d5, qs5, "—", txh2 or "—")
            else:
                ev(g["cur"], ts, "입금 확인", d5, qs5, "—", txh2 or "—")
                if lnk5:
                    g["cur"]["events"][-1]["_lnk"] = lnk5
            return

        def _short_fee(tr, left_before, took, grp, t, exk, tid):
            rem = left_before - took
            if rem <= EPS or took < left_before * Decimal("0.98") or tr["qty"] <= 0:
                return
            if tid and any(o["leg_kind"] == "move_in" and o["event"] == "EXF_DEPOSIT" and (o["group_id"] or -o["asset_id"]) == grp["gid"]
                           and fx_dep_uid_tx.get(o["source_id"]) == tid for o in rows[n9i:]):
                return
            share = rem / tr["qty"]
            rcost = tr["cost"] * share
            rknown = min(rem, tr["known"] * share)
            unit = fee_unit(grp, t, rcost / rknown if rknown > EPS else None)
            if unit is None or unit <= 0:
                return
            tr["left"] = max(Decimal(0), tr["left"] - rem)
            wd_fee_add(exk, rem * unit, t)
            if gas_on:
                fee_expense(rem * unit, t, dkey, "EXF_WD_FEE", fx_name.get(exk, exk))
            if rknown > EPS:
                rkrw = tr["krw"] * share if (tr.get("krw") is not None and not grp["is_stable"]) else None
                fee_gain(grp, unit, rknown, rcost, t, dkey, chain, rkrw)
            diag["arr_short_n"] = diag.get("arr_short_n", 0) + 1

        def _h_exf_deposit():
            nonlocal d6, ikr7, inh7, l9, sc7, sc9, so9, st7, take7, tk9
            cb.snapshot(g, ts, q)
            ex6 = (r["location"] or "").split(":")[-1]
            g.setdefault("ex_dep", set()).add(ex6)
            offc_pk9, offc_av9 = None, Decimal(0)
            if (ex6, r["source_id"]) in offc_dep:
                offc_s(ex6)["depN"] += 1
                offc_add(ex6, g["sym"], g["is_stable"], dep=True)
                if ex6 in offc_on:
                    offc_pk9 = (ex6, acct_norm.canon(g["sym"], ex6))
                    offc_av9 = sum((l9["left"] for l9 in offc_pool.get(offc_pk9, ()) if l9["left"] > EPS and l9["ts"] <= ts), Decimal(0))
            t6 = fx_dep_uid_tx.get(r["source_id"])
            e6 = fxdep_transit.get((t6, g["sym"])) if t6 else None
            if t6 and e6 is None:
                c6 = [e9 for (t9, _s9), e9 in fxdep_transit.items() if t9 == t6 and e9["left"] > 0]
                s6 = [e9 for e9 in c6 if acct_norm.same_asset(e9.get("sym"), None, g["sym"], ex6)]
                if len(s6) == 1:
                    e6 = s6[0]
                elif len(c6) == 1 and acct_norm.qty_close(q, c6[0]["left"]):
                    e6 = c6[0]
            qs6 = f"{q:,.4f}".rstrip("0").rstrip(".")
            e7 = None
            if t6 and not (e6 and e6["left"] > 0):
                e7 = fx_transit.get(t6) or fx_transit.get(t6.lower())
                if e7 and (e7.get("ambiguous") or e7.get("ex") == ex6
                           or not (acct_norm.same_asset(e7.get("sym"), e7.get("ex"), g["sym"], ex6)
                                   or acct_norm.qty_close(q, e7["left"]))):
                    e7 = None
            xl6 = None
            if not e7 and not (e6 and e6["left"] > 0) and r["source_id"] in xf_links:
                xl6 = xf_links[r["source_id"]]
                e7 = fx_transit.get(xl6["key"])
                if e7 and (e7.get("ambiguous") or not acct_norm.same_asset(e7.get("sym"), e7.get("ex"), g["sym"], ex6)
                           or e7.get("ex") == ex6):
                    e7 = None
            lnk6 = None
            if e6 and e6["left"] > 0 and q <= e6["left"] * Decimal("1.02"):
                take6 = min(q, e6["left"])
                e6["left"] -= take6
                lb6 = take6 + e6["left"]
                sc6 = take6 / e6["qty"] if e6["qty"] > 0 else Decimal(1)
                lnk6 = [(sp9, float(sc6) * w9) for sp9, w9 in e6.get("_src", ())]
                inh6 = e6["cost"] * sc6
                cb.add_known(g, e6["known"] * sc6)
                cp_add_map(g, e6.get("_cmp"), sc6)
                cb.add_unknown(g, e6["unknown"] * sc6 + (q - take6))
                unc6 = None
                if g["is_stable"]:
                    st_flow_in(g, e6, sc6, ts, chain)
                if not g["is_stable"]:
                    flow6 = flow_of(g, ts, chain)
                    flow6["bought"] += take6
                    flow6["cost"] += inh6
                    ikr6 = krw_inh(e6, inh6, ts)
                    flow6["cost_krw"] += ikr6
                    in_note(flow6, "내 지갑", take6, inh6, ts, cost_krw=ikr6)
                    unc6 = q - take6
                note_unk(g, ts, f"{fx_name.get(ex6, ex6)} 입금 · 내 지갑 출금 승계(원가 없음)", e6["unknown"] * sc6 + (q - take6), t6, ex9=ex6, up_gid=e6.get("gid"), unc9=unc6, fs9=q - take6)
                cb.add_cost(g, inh6)
                _short_fee(e6, lb6, take6, g, ts, ex6, t6)
                d6 = f"{fx_name.get(ex6, ex6)} 입금 완료 · 원가 승계 (${float(inh6):,.2f})"
                diag["exf_dep_inh_cost"] += inh6
                diag["exf_dep_inh_n"] += 1
            elif e7 and e7["left"] > 0 and q <= e7["left"] * Decimal("1.02"):
                take7 = min(q, e7["left"])
                e7["left"] -= take7
                lb7 = take7 + e7["left"]
                sc7 = take7 / e7["qty"] if e7["qty"] > 0 else Decimal(1)
                inh7 = e7["cost"] * sc7
                lnk6 = [(sp9, float(sc7) * w9) for sp9, w9 in e7.get("_src", ())]
                if e7.get("oa"):
                    g["oa"] = (g.get("oa") or Decimal(0)) + e7["oa"] * sc7
                cb.add_known(g, e7["known"] * sc7)
                cp_add_map(g, e7.get("_cmp"), sc7)
                cb.add_unknown(g, e7["unknown"] * sc7 + (q - take7))
                note_unk(g, ts, f"{fx_name.get(ex6, ex6)} 입금 · 출금 승계 잔여(원가 없음)", e7["unknown"] * sc7 + (q - take7), exf_dep_tx.get((ex6, r["source_id"])) or r["source_id"], ex9=ex6, unc9=q - take7, fs9=q - take7,
                         up_gid=e7.get("gid"), via9=f"{fx_name.get(e7.get('ex'), e7.get('ex'))} 출금 승계 (그 거래소 {e7.get('sym')} 의 원가 미상분)")
                cb.add_cost(g, inh7)
                flow7 = flow_of(g, ts, chain)
                flow7["bought"] += take7
                ikr7 = krw_inh(e7, inh7, ts)
                if g["is_stable"]:
                    flow7["cost"] += (e7.get("kc") or Decimal(0)) * sc7
                    flow7["cost_krw"] += (e7.get("kk") or Decimal(0)) * sc7
                    stl_in(flow7, e7, sc7)
                    fs_in(flow7, e7, sc7)
                else:
                    flow7["cost"] += inh7
                    flow7["cost_krw"] += ikr7
                _short_fee(e7, lb7, take7, g, ts, e7.get("ex") or ex6, t6)
                st7 = e7.pop("story", None)
                if st7:
                    flow7["events"][:0] = st7
                in_note(flow7, fx_name.get(e7["ex"], e7["ex"]), take7, inh7, ts, st7, cost_krw=ikr7)
                d6 = (f"{fx_name.get(ex6, ex6)} 입금 완료 · {fx_name.get(e7['ex'], e7['ex'])}"
                      + (f" 출금 원가 승계 (${float(inh7):,.2f})" if e7["known"] * sc7 > EPS
                         else " 출금 이관 (원가 미상 승계)")
                      + (f" · {xl6['label']}" if xl6 else ""))
            elif of_cand(r, g, q, ts, exf_dep_tx.get((ex6, r["source_id"])) or r["source_id"]):
                pass
            elif (not g["is_stable"] and r["posting_id"] in sale_links
                  and sale_book(g, r, q, ts, chain, exf_dep_tx.get((ex6, r["source_id"])) or r["source_id"])):
                d6 = f"{fx_name.get(ex6, ex6)} 입금 완료 · 토큰 세일 원가 (입찰 지갑에서 직접 입금)"
            elif offc_pk9 is not None and offc_av9 > EPS:
                exn6 = fx_name.get(ex6, ex6)
                ref6 = exf_dep_tx.get((ex6, r["source_id"])) or r["source_id"]
                need6, ck6, kk6, uu6, ckr6 = q, Decimal(0), Decimal(0), Decimal(0), Decimal(0)
                kcs6 = kks6 = fks6 = Decimal(0)
                stl6 = []
                cmp6 = {}
                for l9 in offc_pool.get(offc_pk9, ()):
                    if need6 <= EPS:
                        break
                    if l9["left"] <= EPS or l9["ts"] > ts:
                        continue
                    tk9 = min(need6, l9["left"])
                    l9["left"] -= tk9
                    need6 -= tk9
                    sc9 = tk9 / l9["qty"] if l9["qty"] > 0 else Decimal(1)
                    ck6 += l9["cost"] * sc9
                    ckr6 += l9["cost_krw"] * sc9
                    kcs6 += (l9.get("kc") or Decimal(0)) * sc9
                    kks6 += (l9.get("kk") or Decimal(0)) * sc9
                    fks6 += (l9.get("fk") or Decimal(0)) * sc9
                    stl6.extend([[x9[0], x9[1]] + [v9 * float(sc9) for v9 in x9[2:]] for x9 in l9.get("_stl") or ()])
                    cmp6 = cp_merge(cmp6, l9.get("_cmp"), float(sc9))
                    kk6 += l9["known"] * sc9
                    uu6 += l9["unknown"] * sc9
                need6 = max(Decimal(0), need6)
                take6 = q - need6
                so9 = offc_s(ex6)
                so9["inhN"] += 1
                so9["inhQty"] += take6
                so9["inhUnkQty"] += uu6
                if need6 > EPS:
                    so9["excessQty"] += need6
                    so9["excessN"] += 1
                if g["is_stable"]:
                    fq6 = q - kk6
                    cb.add_known(g, q)
                    cb.add_cost(g, ck6 + fq6)
                    fs_st(g, ts, fq6, chain)
                    if kcs6 > EPS and take6 > EPS:
                        fl6o = flow_of(g, ts, chain)
                        fl6o["cost"] += kcs6
                        fl6o["cost_krw"] += kks6
                        stl_in(fl6o, {"_stl": stl6}, Decimal(1))
                        fs_in(fl6o, {"fk": fks6}, Decimal(1))
                    so9["inhCost"] += ck6 + (take6 - kk6)
                    offc_add(ex6, g["sym"], True, inh=ck6 + (take6 - kk6))
                    d6 = (f"{exn6} 입금 완료 · 내 다른 {exn6} 계정에서 돌아옴(오프체인 · 내 계정으로 가정 · 원가 이어받음 ${float(ck6 + fq6):,.2f})"
                          + (f" · 초과 {_qfmt(need6)}개 액면" if need6 > EPS else ""))
                else:
                    so9["inhCost"] += ck6
                    offc_add(ex6, g["sym"], False, inh=ck6)
                    g["oa"] = (g.get("oa") or Decimal(0)) + kk6
                    cp_add_map(g, cmp6, 1.0)
                    cb.add_known(g, kk6)
                    cb.add_unknown(g, uu6 + need6)
                    cb.add_cost(g, ck6)
                    flow6 = flow_of(g, ts, chain)
                    flow6["bought"] += take6
                    flow6["cost"] += ck6
                    flow6["cost_krw"] += ckr6
                    in_note(flow6, f"내 다른 {exn6} 계정", take6, ck6, ts, cost_krw=ckr6)
                    note_unk(g, ts, f"{exn6} 입금 · 내 다른 {exn6} 계정에서 돌아옴(보낼 때부터 원가 미상)", uu6, ref6, ex9=ex6, unc9=Decimal(0), fs9=0,
                             via9=f"내 다른 {exn6} 계정 이동분(오프체인) — 보낼 때 이 계정에서도 원가 미상이던 몫")
                    note_unk(g, ts, f"{exn6} 입금(오프체인 · 보낸 것보다 많이 돌아옴 — 초과분 원가 없음)", need6, ref6, ex9=ex6, unc9=need6)
                    d6 = (f"{exn6} 입금 완료 · 내 다른 {exn6} 계정에서 돌아옴(오프체인 · 내 계정으로 가정 · 원가 이어받음 ${float(ck6):,.2f})"
                          + (f" · 초과 {_qfmt(need6)}개 원가 미상" if need6 > EPS else ""))
            elif g["is_stable"]:
                cb.acquire(g, q, q)
                fs_st(g, ts, q, chain)
                d6 = f"{fx_name.get(ex6, ex6)} 입금 완료 (스테이블 액면)"
            else:
                cb.add_unknown(g, q)
                note_unk(g, ts, f"{fx_name.get(ex6, ex6)} 입금(원가 없음 · 링크 없음)", q, exf_dep_tx.get((ex6, r["source_id"])) or r["source_id"], ex9=ex6)
                d6 = f"{fx_name.get(ex6, ex6)} 입금 완료 (원가 미상)"
            if g["is_stable"] or not g["cur"]:
                extra_ev(ts, g, "입금 확인", d6, qs6, "—", t6 or "—")
            else:
                ev(g["cur"], ts, "입금 확인", d6, qs6, "—", t6 or "—")
                if lnk6:
                    g["cur"]["events"][-1]["_lnk"] = lnk6
            return

        def _h_move():
            nonlocal c9, cy9, e4, e5, e9, fl9, g2, k2, lb9, mv9
            nonlocal nx9, so9, sw9
            qs = f"{-q:,.4f}".rstrip("0").rstrip(".")
            fl_wd9 = None
            wdt9 = None
            if lk == "move_out":
                if evk == "TRANSFER_OUT_EX" and not ((txh or "").lower() in fx_dep_tx or txh in fx_dep_tx):
                    k2, d2 = "전송", f"{CHAIN_NAME.get(chain, chain)} 지갑 → 업비트 입금 주소"
                    mc2, mk2, mu2 = consume(g, -q)
                    cp_o2 = cp_last[0]
                    kr2 = krw_took(mc2, ts)
                    kc2r, kk2r = krw_rec(mc2)
                    fk2r = fs_rec()
                    stl2r = stl_out(kc2r)
                    cb.snapshot(g, ts, q)
                    ex_transit.setdefault(txh, []).append(
                        {"gid": g["gid"], "sym": g["sym"], "qty": -q, "cost": mc2, "krw": kr2, "kc": kc2r, "kk": kk2r, "fk": fk2r, "_stl": stl2r,
                         "known": mk2, "unknown": mu2 + max(Decimal(0), (-q) - (mk2 + mu2)),
                         "raw_sym": (r["symbol"] or "").upper(),
                         "credited": txh in credited_txh, "used": False, "cyc": g["cur"], "ts": int(ts or 0),
                         "_src": [(r["posting_id"], 1.0)], "_cmp": cp_merge({}, cp_o2)})
                    diag["ex_out_cost"] += mc2
                    diag["ex_out_n"] += 1
                    if g["cur"] is not None:
                        g["cur"]["moved_qty"] += -q
                        g["cur"]["moved_cost"] += mc2
                        mv_note(g["cur"], "업비트", -q)
                    g["last_out"] = {"ex": "upbit", "tx": txh}
                elif evk == "EXF_WITHDRAW" and offc_self_wd((r["location"] or "").split(":")[-1], r["source_id"]):
                    ex9o = (r["location"] or "").split(":")[-1]
                    exn9o = fx_name.get(ex9o, ex9o)
                    k2 = "전송"
                    d2 = f"{exn9o} 출금 → 내 다른 {exn9o} 계정으로 이동(오프체인 · 내 계정으로 가정 · 원가 이동)"
                    mco, mko, muo = consume(g, -q)
                    cp_oo = cp_last[0]
                    mkrwo = krw_took(mco, ts)
                    kco, kko = krw_rec(mco)
                    fko = fs_rec()
                    cb.snapshot(g, ts, q)
                    fl_wd9 = g["cur"]
                    offc_pool.setdefault((ex9o, acct_norm.canon(g["sym"], ex9o)), []).append(
                        {"ts": int(ts), "qty": -q, "left": -q, "cost": mco, "cost_krw": mkrwo, "kc": kco, "kk": kko, "fk": fko, "_stl": stl_out(kco), "known": mko,
                         "unknown": muo + max(Decimal(0), (-q) - (mko + muo)), "gid": g["gid"], "sym": g["sym"], "_cmp": cp_merge({}, cp_oo)})
                    so9 = offc_s(ex9o)
                    so9["wdN"] += 1
                    so9["wdCost"] += mco
                    so9["wdUnkQty"] += (-q) - mko
                    so9["syms"].add(g["sym"])
                    offc_add(ex9o, g["sym"], g["is_stable"], wd=mco)
                    offc_addr_add(ex9o, r["source_id"], mco)
                    if g["cur"] is not None:
                        g["cur"]["moved_qty"] += -q
                        g["cur"]["moved_cost"] += mco
                        mv_note(g["cur"], f"내 다른 {exn9o} 계정", -q)
                        if g["qty_known"] + g["qty_unknown"] <= Decimal("0.000001"):
                            g["cur"] = None
                elif evk in ("EXF_WITHDRAW", "EX_WITHDRAW"):
                    ex9w = (r["location"] or "").split(":")[-1]
                    k2 = "전송"
                    t4 = fx_uid_tx.get(r["source_id"])
                    if ex9w == "upbit":
                        ub_wd_shown.add(r["source_id"])
                    sw9 = swap_dep.pop(t4, None) if (ex9w == "upbit" and t4 and t4.startswith("swap_")) else None
                    dst9 = ("업비트 입금" if t4 in up_dep_by_tx and ex9w != "upbit"
                            else f"{fx_name.get(fx_dep_tx[t4], fx_dep_tx[t4])} 입금"
                            if t4 in fx_dep_tx and fx_dep_tx[t4] != ex9w
                            else f"내 지갑 ({CHAIN_NAME.get(arr_tx_chain[t4], arr_tx_chain[t4])})" if t4 in arr_tx_chain
                            else "온체인") if t4 else ""
                    d2 = (f"{fx_name.get(ex9w, ex9w)} 토큰 전환 출금 ({g['sym']} → {sw9['g']['sym']} · 원가 이동)" if sw9
                          else f"{fx_name.get(ex9w, ex9w)} 출금 → {dst9} (원가 이동)" if t4
                          else f"{fx_name.get(ex9w, ex9w)} 출금 (txid 없음 · 원가 소실)")
                    lb9 = loan_wd.get(r["posting_id"]) if loan_wd else None
                    if lb9:
                        cb.add_unknown(g, lb9)
                        k09, c09 = g["qty_known"], g["cost"]
                        note_unk(g, ts, f"{fx_name.get(ex9w, ex9w)} 대출로 빌린 코인(출금 · 그 시각 시가 추정)", lb9, t4 or "", ex9=ex9w, chain9=chain, unc9=lb9)
                        if g["qty_known"] - k09 > EPS:
                            loan_px[r["posting_id"]] = (g["cost"] - c09) / (g["qty_known"] - k09)
                            fs_sum["loan"]["priced"] += 1
                        else:
                            loan_unp[g["gid"]] = loan_unp.get(g["gid"], [Decimal(0), int(ts)])
                            loan_unp[g["gid"]][0] += lb9
                    mc4, mk4, mu4 = consume(g, -q)
                    cp_o4 = cp_last[0]
                    kr4 = krw_took(mc4, ts)
                    kc4r, kk4r = krw_rec(mc4)
                    fk4r = fs_rec()
                    stl4r = stl_out(kc4r)
                    oa4 = oa_last[0]
                    pk4 = (krw_last[0], krw_mix[0], krw_stl[0]) if of_pay_on else None
                    cb.snapshot(g, ts, q)
                    nq4 = -q
                    fq4 = wd_fee_q(ex9w, r["source_id"], evk, -q) if not (sw9 or str(t4 or "").startswith("swap_")) else Decimal(0)
                    if fq4 > 0:
                        s4 = fq4 / (-q)
                        fmc4, fmk4 = mc4 * s4, mk4 * s4
                        fkr4 = krw_last[0] * s4 if krw_last[0] is not None else None
                        fmix4 = krw_mix[0] * s4
                        ffs4 = fk4r * s4
                        fstl4 = ({"l": [x9[:2] + (x9[2] * float(s4), x9[3] * float(s4), x9[4], x9[5] * float(s4)) for x9 in krw_stl[0]["l"]], "o": krw_stl[0]["o"]}
                                 if krw_stl[0] else None)
                        fcmp4 = cp_emit(cp_merge({}, cp_o4, float(s4)), mu4 * s4, fmk4 + mu4 * s4, fmc4) if cp_o4 else None
                        nq4 = -q - fq4
                        mc4, mk4, mu4 = mc4 - fmc4, mk4 - fmk4, mu4 * (1 - s4)
                        kr4, oa4 = kr4 * (1 - s4), oa4 * (1 - s4)
                        kc4r, kk4r, fk4r = kc4r * (1 - s4), kk4r * (1 - s4), fk4r * (1 - s4)
                        stl4r = [[x9[0], x9[1]] + [v9 * float(1 - s4) for v9 in x9[2:]] for x9 in stl4r]
                        cp_o4 = cp_merge({}, cp_o4, float(1 - s4)) if cp_o4 else cp_o4
                        u4f = fee_unit(g, ts, (fmc4 / fmk4) if fmk4 > EPS else None)
                        if u4f is not None:
                            wd_fee_add(ex9w, fq4 * u4f, ts)
                            if gas_on:
                                fee_expense(fq4 * u4f, ts, dkey, "EXF_WD_FEE", ex9w)
                            fee_gain(g, u4f, fmk4, fmc4, ts, dkey, chain, fkr4, mix9=fmix4, stl9=fstl4, cmp9=fcmp4, fs9=ffs4)
                        d2 += f" · 출금 수수료 {_qfmt(fq4)} {g['sym']}"
                    if evk == "EXF_WITHDRAW" and (ex9w, r["source_id"]) in offc_wd:
                        so9 = offc_s(ex9w)
                        so9["wdN"] += 1
                        so9["wdCost"] += mc4
                        so9["wdUnkQty"] += nq4 - mk4
                        so9["syms"].add(g["sym"])
                        offc_add(ex9w, g["sym"], g["is_stable"], wd=mc4)
                        offc_addr_add(ex9w, r["source_id"], mc4)
                    fl_wd9 = g["cur"]
                    if not sw9 and not g.get("is_fiat") and nq4 > 0:
                        wdt9 = {"gid": g["gid"], "sym": g["sym"], "qty": nq4, "ts": int(ts), "ex": ex9w, "uuid": r["source_id"],
                                "txid": t4, "cost": mc4, "known": mk4, "cyc": g["cur"], "stable": bool(g["is_stable"]), "ev": None,
                                "held": mk4 + mu4}
                        wd_tr.append(wdt9)
                        if pk4 is not None:
                            try:
                                of_wd_take(g, r, nq4, -q, mc4, mk4, pk4, fk4r, oa4, cp_o4, ts, ex9w, t4)
                            except Exception as e9:   # noqa: BLE001 [optional]
                                calcguard.swallowed("view_b_replay:ReplayMixin._build_replay[blk]", e9)
                                log.warning("수동 참가금 출금 처분 재료 실패(종전 경로): %s", logs.safe_err(e9)[:160])
                    if g["cur"] is not None:
                        g["cur"]["moved_qty"] += nq4
                        g["cur"]["moved_cost"] += mc4
                        if sw9:
                            mv_note(g["cur"], f"{sw9['g']['sym']} 전환", nq4)
                        elif t4 and t4 in arr_tx_chain and dst9.startswith("내 지갑"):
                            mv_note(g["cur"], f"{CHAIN_NAME.get(arr_tx_chain[t4], arr_tx_chain[t4])} 지갑", nq4)
                        elif t4 and dst9.endswith(" 입금"):
                            mv_note(g["cur"], dst9[:-3], nq4)
                        elif t4:
                            mv_note(g["cur"], "온체인 주소", nq4, own=False)
                    if sw9:
                        g2, q2 = sw9["g"], sw9["q"]
                        kf9 = (mk4 / (-q)) if -q > 0 else Decimal(0)
                        want9 = q2 * min(kf9, Decimal(1))
                        mv9 = min(want9, g2["qty_unknown"])
                        c9 = mc4 * (mv9 / want9) if want9 > 0 else Decimal(0)
                        if mv9 > 0:
                            cb.convert(g2, mv9, c9)
                            fl9 = flow_of(g2, ts, chain)
                            fl9["bought"] += mv9
                            fl9["cost"] += c9
                            fl9["cost_krw"] += kr4 * c9 / mc4 if mc4 > 0 else krw_of(c9, ts)
                            if sw9.get("ent") is not None:
                                sw9["ent"]["qty"] = max(0.0, sw9["ent"]["qty"] - float(mv9))
                        t4 = None
                    if t4:
                        e4 = fx_transit.setdefault(
                            t4, {"qty": Decimal(0), "cost": Decimal(0),
                                 "known": Decimal(0), "unknown": Decimal(0),
                                 "left": Decimal(0), "ex": ex9w,
                                 "sym": g["sym"], "gid": g["gid"]})
                        if e4.get("sym") != g["sym"] or e4.get("ex") != ex9w:
                            e4["ambiguous"] = True
                        e4["qty"] += nq4
                        e4["left"] += nq4
                        e4.setdefault("_src", []).append((r["posting_id"], 1.0))
                        e4["_cmp"] = cp_merge(e4.get("_cmp") or {}, cp_o4)
                        e4["cost"] += mc4
                        e4["krw"] = e4.get("krw", Decimal(0)) + kr4
                        e4["kc"] = e4.get("kc", Decimal(0)) + kc4r; e4["kk"] = e4.get("kk", Decimal(0)) + kk4r
                        e4["fk"] = e4.get("fk", Decimal(0)) + fk4r
                        if stl4r:
                            e4.setdefault("_stl", []).extend(stl4r)
                        e4["known"] += mk4
                        if oa4 > 0:
                            e4["oa"] = e4.get("oa", Decimal(0)) + oa4
                        e4["unknown"] += mu4 + max(Decimal(0), nq4 - (mk4 + mu4))
                        if g["cur"] is not None:
                            evs4w = g["cur"]["events"]
                            k4w, n4w = _sell_pre(g["cur"], evs4w, sell_wm=sell_wm)
                            hd4w, tl4w = evs4w[:k4w], evs4w[k4w + n4w:]
                            mv4 = [e9 for e9 in hd4w if "매도" not in str(e9.get("k") or "")] + [e9 for e9 in tl4w if "매도" not in str(e9.get("k") or "")]
                            if mv4:
                                for e9 in mv4:
                                    e9.setdefault("_mv", r["posting_id"])
                                e4.setdefault("story", []).extend(mv4)
                                e4["story_flow"] = g["cur"]
                                g["cur"]["events"] = ([e9 for e9 in hd4w if "매도" in str(e9.get("k") or "")] + evs4w[k4w:k4w + n4w]
                                                      + [e9 for e9 in tl4w if "매도" in str(e9.get("k") or "")])
                            _sell_mark(g["cur"], sell_wm=sell_wm)
                            if g["qty_known"] + g["qty_unknown"] <= Decimal("0.000001"):
                                g["cur"] = None
                elif evk in ("BRIDGE", "TRANSFER_OUT_EX") and \
                        ((txh or "").lower() in fx_dep_tx or txh in fx_dep_tx):
                    ex5 = fx_dep_tx.get((txh or "").lower()) or fx_dep_tx.get(txh)
                    k2 = "전송"
                    d2 = f"{CHAIN_NAME.get(chain, chain)} 지갑 → {fx_name.get(ex5, ex5)} 입금 주소"
                    mc5, mk5, mu5 = consume(g, -q)
                    cp_o5 = cp_last[0]
                    kr5 = krw_took(mc5, ts)
                    kc5r, kk5r = krw_rec(mc5)
                    fk5r = fs_rec()
                    cb.snapshot(g, ts, q)
                    t5 = (txh or "").lower() if (txh or "").startswith("0x") else txh
                    e5 = fxdep_transit.setdefault(
                        (t5, g["sym"]), {"qty": Decimal(0), "cost": Decimal(0),
                                         "known": Decimal(0), "unknown": Decimal(0),
                                         "left": Decimal(0), "gid": g["gid"], "sym": g["sym"], "ex": ex5})
                    e5["ts"] = max(int(e5.get("ts") or 0), int(ts or 0))
                    e5["qty"] += -q
                    e5["left"] += -q
                    e5.setdefault("_src", []).append((r["posting_id"], 1.0))
                    e5["_cmp"] = cp_merge(e5.get("_cmp") or {}, cp_o5)
                    e5["cost"] += mc5
                    e5["krw"] = e5.get("krw", Decimal(0)) + kr5
                    e5["kc"] = e5.get("kc", Decimal(0)) + kc5r; e5["kk"] = e5.get("kk", Decimal(0)) + kk5r
                    e5["fk"] = e5.get("fk", Decimal(0)) + fk5r
                    stl_carry(e5, kc5r)
                    e5["known"] += mk5
                    e5["unknown"] += mu5 + max(Decimal(0), (-q) - (mk5 + mu5))
                    g["last_out"] = {"ex": ex5, "tx": txh}
                    if g["cur"] is not None and not g["is_stable"]:
                        e5.setdefault("cycs", []).append((g["cur"], -q, mc5))
                        g["cur"]["moved_qty"] += -q
                        g["cur"]["moved_cost"] += mc5
                        mv_note(g["cur"], fx_name.get(ex5, ex5), -q)
                elif evk == "BRIDGE" and (nopx_swap.get((r["source_ns"], txh)) or {}).get("rcpt"):
                    nx9 = nopx_swap[(r["source_ns"], txh)]
                    mc3, mk3, mu3 = consume(g, -q)
                    cb.snapshot(g, ts, q)
                    cy9 = nopx_carry.setdefault((r["source_ns"], txh), {"q": Decimal(0), "mc": Decimal(0), "mk": Decimal(0), "krw": Decimal(0),
                                                                         "sym": g["sym"], "src": []})
                    cy9["q"] += -q
                    cy9["mc"] += mc3
                    cy9["mk"] += mk3
                    cy9["krw"] += krw_took(mc3, ts)
                    cy9["src"].append((r["posting_id"], 1.0))
                    if g["cur"] is not None:
                        g["cur"]["moved_qty"] += -q
                        g["cur"]["moved_cost"] += mc3
                        mv_note(g["cur"], f"{nx9['asym']} 증서", -q)
                    k2, d2 = "전송", (f"{CHAIN_NAME.get(chain, chain)} → 브릿지 예치 · 증서 {nx9['asym']} 로 "
                                      + (f"원가 이관 (${float(mc3):,.2f} · 손익 없음)" if mk3 > EPS else "원가 미상 이관"))
                elif evk == "BRIDGE":
                    k2, d2 = "전송", f"{CHAIN_NAME.get(chain, chain)} → 브릿지 · 위치 이동(손익 없음)"
                    mc3, mk3, mu3 = consume(g, -q)
                    cp_o3 = cp_last[0]
                    kc3r, kk3r = krw_rec(mc3)
                    cb.snapshot(g, ts, q)
                    sq3 = -q
                    sa3 = br_sum.get(r["posting_id"])
                    if sa3 is None and r["posting_id"] in br_natfee:
                        u3n = fee_unit(g, ts, (mc3 / mk3) if mk3 > EPS else None)
                        if u3n is not None:
                            br_fee_add(chain, (-q) * u3n, ts)
                            if gas_on:
                                fee_expense((-q) * u3n, ts, dkey, "BRIDGE_FEE", CHAIN_NAME.get(chain, chain))
                            fee_gain(g, u3n, mk3, mc3, ts, dkey, chain, krw_last[0], mix9=krw_mix[0], stl9=krw_stl[0],
                                     cmp9=cp_emit(cp_o3, mu3, mk3 + mu3, mc3) if cp_o3 else None, fs9=fs_rec())
                            d2 += f" · 메시징 수수료 {_qfmt(-q)} {g['sym']}(도착 짝 없음 — 비용)"
                            mc3, mk3, mu3, sq3, cp_o3 = Decimal(0), Decimal(0), Decimal(0), Decimal(0), None
                            kc3r = kk3r = Decimal(0)
                    if sa3 is not None and (-q) * BR_UNIQ_LO <= sa3 < -q:
                        fq3 = -q - sa3
                        s3 = fq3 / (-q)
                        fmc3, fmk3 = mc3 * s3, mk3 * s3
                        fkr3 = krw_last[0] * s3 if krw_last[0] is not None else None
                        fmix3 = krw_mix[0] * s3
                        ffs3 = fs_rec() * s3
                        fstl3 = ({"l": [x9[:2] + (x9[2] * float(s3), x9[3] * float(s3), x9[4], x9[5] * float(s3)) for x9 in krw_stl[0]["l"]], "o": krw_stl[0]["o"]}
                                 if krw_stl[0] else None)
                        fcmp3 = cp_emit(cp_merge({}, cp_o3, float(s3)), mu3 * s3, fmk3 + mu3 * s3, fmc3) if cp_o3 else None
                        mc3, mk3, mu3 = mc3 - fmc3, mk3 - fmk3, mu3 * (1 - s3)
                        kc3r, kk3r = kc3r * (1 - s3), kk3r * (1 - s3)
                        cp_o3 = cp_merge({}, cp_o3, float(1 - s3)) if cp_o3 else cp_o3
                        sq3 = sa3
                        u3f = fee_unit(g, ts, (fmc3 / fmk3) if fmk3 > EPS else None)
                        if u3f is not None:
                            br_fee_add(chain, fq3 * u3f, ts)
                            if gas_on:
                                fee_expense(fq3 * u3f, ts, dkey, "BRIDGE_FEE", CHAIN_NAME.get(chain, chain))
                            fee_gain(g, u3f, fmk3, fmc3, ts, dkey, chain, fkr3, mix9=fmix3, stl9=fstl3, cmp9=fcmp3, fs9=ffs3)
                        d2 += f" · 브릿지 수수료 {_qfmt(fq3)} {g['sym']}"
                    bridge_outs.append({"sym": g["sym"], "qty": sq3, "ts": ts, "_src": [(r["posting_id"], 1.0)], "_cmp": cp_merge({}, cp_o3),
                                        "cost": mc3, "known": mk3, "kc": kc3r, "kk": kk3r,
                                        "unknown": mu3 + max(Decimal(0), sq3 - (mk3 + mu3)),
                                        "left": sq3,
                                        "gid": r["group_id"] or -r["asset_id"], "chain": chain, "pid": r["posting_id"]})
                    bo_pid[r["posting_id"]] = bridge_outs[-1]
                elif evk == "TRANSFER_SELF":
                    k2, d2 = "전송", f"{CHAIN_NAME.get(chain, chain)} · 내 지갑 간 이동 (±0 · 손익 없음)"
                elif evk == "CONVERT":
                    k2, d2 = "전송", f"{CHAIN_NAME.get(chain, chain)} · 랩/언랩 전환 (평단 불변)"
                else:
                    k2, d2 = None, None
                if k2:
                    fl_ev9 = g["cur"] or fl_wd9
                    if g["is_stable"] or not fl_ev9:
                        extra_ev(ts, g, k2, d2, qs, "—", txh)
                        if wdt9 is not None and extra_events:
                            wdt9["ev"] = extra_events[-1]
                    else:
                        ev(fl_ev9, ts, k2, d2, qs, "—", txh)
                        if wdt9 is not None and fl_ev9["events"]:
                            wdt9["ev"] = fl_ev9["events"][-1]
            return

        def _h_stake_reward():
            nonlocal st9
            ex_income = str(r["location"] or "").startswith("exchange:")
            cb.snapshot(g, ts, q)
            st9 = stake_rwd.setdefault(r["location"] or "", [Decimal(0), Decimal(0)])
            st9[0] += q
            if cost is not None:
                cb.acquire(g, q, cost)
                if ex_income and g["is_stable"]:
                    fs_st(g, ts, q, chain)
                st9[1] += cost
                dk9s = acct_norm.iso_day(ts)
                rt9s = fxb.rate_at(ts)
                realized_by_date[dk9s] = realized_by_date.get(dk9s, 0) + float(cost)
                realized_krw_by_date[dk9s] = realized_krw_by_date.get(dk9s, 0) + float(cost) * rt9s
                si9 = stake_inc.setdefault(dk9s, {}).setdefault(g["sym"], [Decimal(0), Decimal(0), 0, 0.0])
                si9[0] += cost; si9[1] += q; si9[2] += 1; si9[3] += float(cost) * rt9s
            else:
                cb.add_unknown(g, q)
                note_unk(g, ts, ("거래소 지급(배당·에어드랍·Earn 이자) · 시가 없음(원가 없음)" if ex_income else "솔라나 스테이킹 보상 · 시가 대기(원가 없음)"),
                         q, "" if ex_income else txh, chain9=chain, fs9=0)
            if ex_income:
                extra_ev(ts, g, "전송", f"{cur_lab[0] or '거래소'} · 지급 내역(배당·에어드랍·런치풀·Earn 이자 — 받은 시각 시가 = 소득)",
                         f"{q:,.6f}".rstrip("0").rstrip("."), f"${float(cost):,.2f}" if cost is not None else "—", "")
                return
            mev9 = not (r["source_id"] or "").startswith("stakerwd:")
            ep9 = "" if mev9 else (r["source_id"] or "").rsplit(":", 1)[-1]
            extra_ev(ts, g, "전송", f"{CHAIN_NAME.get(chain, chain)} · 스테이킹 보상"
                     + (f" (에폭 {ep9})" if ep9 else " (MEV 팁)"),
                     f"{q:,.6f}".rstrip("0").rstrip("."), f"${float(cost):,.2f}" if cost is not None else "—",
                     txh if mev9 else "")
            return

        def _stable_bridge_in(link, grp, row, qty_in, t, chain_, tx):
            src = G.get(link.get("gid"))
            if src is None:
                return False
            if (src.get("is_stable") and not link.get("_cv") and link is br_transit.get(row["posting_id"])
                    and not link.get("id_link")):
                return False
            took = min(qty_in, link["left"])
            if took <= EPS:
                return False
            link["left"] -= took
            share = took / link["qty"] if link["qty"] > 0 else Decimal(1)
            inh = link["cost"] * share
            kshare = share
            if link is br_transit.get(row["posting_id"]) and link["left"] > 0 and took >= link["qty"] * BR_UNIQ_LO:
                inh = link["cost"] * (took + link["left"]) / link["qty"]
                kshare = (took + link["left"]) / link["qty"]
                link["left"] = Decimal(0)
            kq = min(took, link.get("known", link["qty"]) * share)
            grp["risk_allow"] = True
            if src.get("is_stable") and not link.get("_cv"):
                cb.add_known(grp, qty_in)
                cb.add_cost(grp, inh + (qty_in - kq))
                st_flow_in(grp, link, kshare, t, chain_)
                fs_st(grp, t, qty_in - kq, chain_)
                diag["st_br_inh_n"] = diag.get("st_br_inh_n", 0) + 1
                extra_ev(t, grp, "전송", f"{CHAIN_NAME.get(chain_, chain_)} 브릿지 도착 · 원가 이관 (${float(inh + (qty_in - kq)):,.2f})",
                         f"{qty_in:,.4f}".rstrip("0").rstrip("."), "—", tx)
                return True
            ratio = Decimal(str((link.get("_cv") or {}).get("ratio") or 1))
            dep_known = kq / ratio if ratio > 0 else kq
            mck = (link["krw"] * inh / link["cost"] if (link.get("krw") is not None and link["cost"] > 0 and not src.get("is_stable"))
                   else None)
            gain = (fee_gain(src, ratio, dep_known, inh, t, acct_norm.iso_day(t), chain_, mck,
                             lab9="브릿지 전환(다른 자산 도착 · 스테이블 수령 = 매도)") if dep_known > EPS else Decimal(0))
            cb.acquire(grp, qty_in, qty_in)
            fs_st(grp, t, qty_in, chain_)
            diag["st_br_cv_n"] = diag.get("st_br_cv_n", 0) + 1
            extra_ev(t, grp, "전송", f"{CHAIN_NAME.get(chain_, chain_)} 브릿지 도착 · {src['sym']} → {grp['sym']} 전환(= {src['sym']} 매도 · 실현 "
                     f"{'+' if gain >= 0 else '−'}${abs(float(gain)):,.2f})", f"{qty_in:,.4f}".rstrip("0").rstrip("."), "—", tx)
            return True

        def _h_acq():
            nonlocal arr_gid, c9, cv9, cvk9, cy9, e4, ex9, ex_fee9, flow, fx9
            nonlocal k9, kg9, mc9, mk9, mu9, nx9, rd9, rt9, sc9, sg9
            nonlocal sh9, sv9, take9, td9, u9
            flow = flow_of(g, ts, chain)
            cb.snapshot(g, ts, q)
            rd9 = redeem_tx.get((r["source_ns"], txh))
            if rd9 and rd9["acq"] == r["posting_id"] and rd9["carry"] is not None:
                mc9, mk9, mu9 = rd9["carry"]
                k9 = min(q, mk9 * rd9["ratio"])
                u9 = q - k9
                cb.add_known(g, k9)
                cb.add_unknown(g, u9)
                cb.add_cost(g, mc9)
                if u9 > EPS:
                    note_unk(g, ts, "세일 영수증 교환 · 승계(원가 없음)", u9, txh, chain9=chain, fs9=0)
                g["risk_allow"] = True
                flow["bought"] += k9
                flow["cost"] += mc9
                flow["cost_krw"] += rd9["carry_krw"] if rd9.get("carry_krw") is not None else krw_of(mc9, ts)
                ev(flow, ts, "전송", f"{CHAIN_NAME.get(chain, chain)} · 세일 영수증 → {g['sym']} 교환 · 원가 승계 (${float(mc9):,.2f})",
                   f"{q:,.4f}".rstrip("0").rstrip("."), "—", txh)
                return
            nx9 = nopx_swap.get((r["source_ns"], txh)) if cost is None else None
            cy9 = nopx_carry.get((r["source_ns"], txh)) if nx9 is not None else None
            gw9 = nx9["gw"].get(g["gid"]) if nx9 is not None else None
            if cy9 is not None and gw9 is not None and gw9[1] > 0 and cy9["q"] > 0 and q > 0:
                w9g = gw9[0]
                fx9 = nx9.get("fx")
                if fx9:
                    sv9 = sum(fx9.values(), Decimal(0))
                    if g["gid"] in fx9:
                        w9g = fx9[g["gid"]] / max(cy9["mc"], sv9) if max(cy9["mc"], sv9) > 0 else Decimal(0)
                    elif cy9["mc"] > 0:
                        w9g = gw9[0] * max(Decimal(0), cy9["mc"] - sv9) / cy9["mc"]
                sh9 = w9g * q / gw9[1]
                kg9 = [min(Decimal(1), a9 / b9) for a9, b9 in (cy9.get("kg") or {}).values() if b9 > 0]
                k9 = q * (sum(kg9, Decimal(0)) / len(kg9) if len(kg9) > 1 else min(Decimal(1), cy9["mk"] / cy9["q"]))
                zv9g = g["gid"] in (nx9.get("z") or ())
                if g["is_stable"] or zv9g:
                    k9 = q
                c9 = cy9["mc"] * sh9
                cb.add_known(g, k9)
                cb.add_unknown(g, q - k9)
                cb.add_cost(g, c9)
                if q - k9 > EPS:
                    note_unk(g, ts, f"스왑(양쪽 시세 없음) {cy9['sym']} → {g['sym']} · 승계(원가 없음)", q - k9, txh, chain9=chain, fs9=0)
                flow["bought"] += k9
                flow["cost"] += c9
                flow["cost_krw"] += cy9["krw"] * sh9
                ev(flow, ts, "전송", f"{CHAIN_NAME.get(chain, chain)} · "
                   + ("브릿지 예치 증서" if nx9.get("rcpt") else "스왑(양쪽 시세 없음)") + f" {cy9['sym']} → {g['sym']} · "
                   + (f"원가 승계 (${float(c9):,.2f})" if k9 > EPS else "원가 미상 승계")
                   + (" · 동반 토큰(경제 가치 없음 목록) — 원가 0" if zv9g else
                      (" · 원가 나눔(시세 있는 코인 = 그 시각 시가 · 나머지 = 남은 원가" + (" 균등 · 추정)" if nx9.get("est") else ")")) if nx9.get("fx")
                      else (" · 원가 나눔 추정(받은 코인 수로 균등)" if nx9.get("est") else (" · 원가 나눔(시세 비례)" if len(nx9["gw"]) > 1 else ""))),
                   f"{q:,.4f}".rstrip("0").rstrip("."), "—", txh)
                flow["events"][-1]["_lnk"] = [(sp9, float(sh9) * w9) for sp9, w9 in cy9["src"]]
                return
            xc9 = xc_transit.get(r["posting_id"]) if cost is None and not g["is_stable"] and evk in ("TRANSFER_IN", "PROGRAM_IN") else None
            if xc9 and xc9["qty"] > 0:
                sc9 = q / xc9["qty"]
                cov9 = min(q, xc9["cov"] * sc9)
                inh9 = xc9["cost"] * sc9
                cb.add_known(g, cov9)
                cb.add_unknown(g, q - cov9)
                if q - cov9 > 0:
                    note_unk(g, ts, f"{xc9['label']} · 일부 원가 미상", q - cov9, txh, chain9=chain, fs9=0)
                cb.add_cost(g, inh9)
                g["risk_allow"] = True
                flow["bought"] += cov9
                flow["cost"] += inh9
                flow["cost_krw"] += krw_of(inh9, ts)
                diag["xc_inh_n"] += 1
                diag["xc_inh_cost"] += inh9
                cp_xc(g, r, xc9, cov9, inh9, chain, ts)
                xc_used[r["posting_id"]] = {"tx": txh, "chain": chain, "sym": g["sym"], "qty": float(q), "cov": float(cov9),
                                            "cost": round(float(inh9), 2), "label": xc9["label"], "via": xc9["via"], "ts": int(ts)}
                ev(flow, ts, "전송", f"{xc9['label']} · 원가 이관 (${float(inh9):,.2f})",
                   f"{q:,.4f}".rstrip("0").rstrip("."), "—", txh)
                return
            if cost is None:
                linked = None
                take = Decimal(0)
                rk9 = (rt_pair.get((r["source_ns"], txh)) if evk == "PROGRAM_IN" and not (g["is_stable"] and (
                    fx_wd.get(txh) or fx_wd.get((txh or "").lower()) or txh in ub_wd_tx or (txh or "").lower() in ub_wd_tx)) else None)
                rt9 = rt_transit.get((rk9[0], rk9[1], g["gid"])) if rk9 else None
                if rt9 and rt9["left"] > 0 and q <= rt9["left"] * Decimal("1.005") and g["is_stable"]:
                    take9 = min(q, rt9["left"])
                    rt9["left"] -= take9
                    sc9 = take9 / rt9["qty"] if rt9["qty"] > 0 else Decimal(1)
                    inh9 = rt9["cost"] * sc9
                    kq9s = min(take9, rt9["known"] * sc9)
                    cb.add_known(g, q)
                    cb.add_cost(g, inh9 + (q - kq9s))
                    st_flow_in(g, rt9, sc9, ts, chain)
                    fs_st(g, ts, q - kq9s, chain)
                    g["risk_allow"] = True
                    extra_ev(ts, g, "전송", f"{CHAIN_NAME.get(chain, chain)} 프로그램 예치 복귀 · 원가 복원 (${float(inh9 + (q - kq9s)):,.2f})",
                             f"{q:,.4f}".rstrip("0").rstrip("."), "—", txh)
                    return
                if rt9 and rt9["left"] > 0 and q <= rt9["left"] * Decimal("1.005"):
                    take9 = min(q, rt9["left"])
                    rt9["left"] -= take9
                    sc9 = take9 / rt9["qty"] if rt9["qty"] > 0 else Decimal(1)
                    inh9 = rt9["cost"] * sc9
                    cb.add_known(g, rt9["known"] * sc9)
                    cp_add_map(g, rt9.get("_cmp"), sc9)
                    cb.add_unknown(g, rt9["unknown"] * sc9 + (q - take9))
                    note_unk(g, ts, "프로그램 예치 복귀 · 승계(원가 없음)", rt9["unknown"] * sc9 + (q - take9), txh, chain9=chain, unc9=q - take9, fs9=q - take9)
                    cb.add_cost(g, inh9)
                    g["risk_allow"] = True
                    flow["bought"] += take9
                    flow["cost"] += inh9
                    flow["cost_krw"] += krw_inh(rt9, inh9, ts)
                    ev(flow, ts, "전송", f"{CHAIN_NAME.get(chain, chain)} 프로그램 예치 복귀 · 원가 복원 (${float(inh9):,.2f})",
                       f"{q:,.4f}".rstrip("0").rstrip("."), "—", txh)
                    flow["events"][-1]["_lnk"] = [(sp9, float(sc9) * w9) for sp9, w9 in rt9.get("_src", ())]
                    return
                if not g["is_stable"] and evk in ("TRANSFER_IN", "PROGRAM_IN"):
                    arr_gid = r["group_id"] or -r["asset_id"]
                    bt9 = br_transit.get(r["posting_id"])
                    if bt9 and bt9["left"] > 0:
                        linked, take = bt9, min(q, bt9["left"])
                        diag["of_bridge_inh_n"] += 1
                        diag["of_bridge_inh_cost"] += bt9["cost"] * (take / bt9["qty"] if bt9["qty"] > 0 else Decimal(1))
                    bo9 = None if linked else bo_pid.get(br_plan.get(r["posting_id"]))
                    if (bo9 is not None and bo9["sym"] == g["sym"] and bo9.get("left", Decimal(0)) > 0
                            and bo9.get("chain") != chain and q <= bo9["left"] * Decimal("1.02")):
                        linked = bo9
                        take = min(q, bo9["left"])
                if g["is_stable"] and evk in ("TRANSFER_IN", "PROGRAM_IN"):
                    lk9s = br_transit.get(r["posting_id"])
                    if not (lk9s and lk9s["left"] > 0):
                        lk9s = bo_pid.get(br_plan.get(r["posting_id"]))
                        if not (lk9s is not None and lk9s["sym"] == g["sym"] and lk9s.get("left", Decimal(0)) > 0
                                and lk9s.get("chain") != chain):
                            lk9s = None
                    if lk9s is not None and _stable_bridge_in(lk9s, g, r, q, ts, chain, txh):
                        return
                if g["is_stable"] and evk in ("TRANSFER_IN", "PROGRAM_IN"):
                    e4s = fx_transit.get(txh) or fx_transit.get((txh or "").lower())
                    if e4s and (e4s.get("ambiguous") or not (G.get(e4s.get("gid")) or {}).get("is_stable")
                                or (len(arr_groups.get((r["source_ns"], txh), ())) > 1 and e4s.get("sym") != g["sym"])):
                        e4s = None
                    if e4s and e4s["left"] > 0 and q <= e4s["left"] * Decimal("1.02"):
                        g["risk_allow"] = True
                        take4 = min(q, e4s["left"])
                        e4s["left"] -= take4
                        sc4 = take4 / e4s["qty"] if e4s["qty"] > 0 else Decimal(1)
                        inh_c4 = e4s["cost"] * sc4
                        kq4 = min(take4, e4s["known"] * sc4)
                        if e4s.get("oa"):
                            g["oa"] = (g.get("oa") or Decimal(0)) + e4s["oa"] * sc4
                        cb.add_known(g, q)
                        cb.add_cost(g, inh_c4 + (q - kq4))
                        st_flow_in(g, e4s, sc4, ts, chain)
                        diag["st_wd_inh_n"] = diag.get("st_wd_inh_n", 0) + 1
                        diag["st_wd_inh_gap"] = diag.get("st_wd_inh_gap", Decimal(0)) + (inh_c4 - kq4)
                        extra_ev(ts, g, "전송", f"{fx_name.get(e4s['ex'], e4s['ex'])} 출금 도착 · {CHAIN_NAME.get(chain, chain)} · 원가 승계"
                                 f" (${float(inh_c4 + (q - kq4)):,.2f})", f"{q:,.4f}".rstrip("0").rstrip("."), "—", txh)
                        return
                if not g["is_stable"] and evk in ("TRANSFER_IN", "PROGRAM_IN"):
                    e4 = fx_transit.get(txh) or fx_transit.get((txh or "").lower())
                    if e4 and (e4.get("ambiguous")
                               or (len(arr_groups.get((r["source_ns"], txh), ())) > 1
                                   and e4.get("sym") != g["sym"])):
                        e4 = None
                    if e4 and e4["left"] > 0 and q <= e4["left"] * Decimal("1.02"):
                        g["risk_allow"] = True
                        g["wd_seen"] = True
                        take4 = min(q, e4["left"])
                        e4["left"] -= take4
                        sc4 = take4 / e4["qty"] if e4["qty"] > 0 else Decimal(1)
                        inh_c4 = e4["cost"] * sc4
                        if e4.get("oa"):
                            g["oa"] = (g.get("oa") or Decimal(0)) + e4["oa"] * sc4
                        cb.add_known(g, e4["known"] * sc4)
                        cp_add_map(g, e4.get("_cmp"), sc4)
                        cb.add_unknown(g, e4["unknown"] * sc4 + (q - take4))
                        note_unk(g, ts, "거래소 출금 도착 · 승계(원가 없음)", e4["unknown"] * sc4 + (q - take4), txh, chain9=chain, up_gid=e4.get("gid"), unc9=q - take4, fs9=q - take4)
                        cb.add_cost(g, inh_c4)
                        flow = flow_of(g, ts, chain)
                        flow["bought"] += take4
                        flow["cost"] += inh_c4
                        ikr4 = krw_inh(e4, inh_c4, ts)
                        flow["cost_krw"] += ikr4
                        st4 = e4.pop("story", None)
                        if st4:
                            flow["events"][:0] = st4
                        in_note(flow, fx_name.get(e4["ex"], e4["ex"]), take4, inh_c4, ts, st4, cost_krw=ikr4)
                        ev(flow, ts, "전송",
                           f"{fx_name.get(e4['ex'], e4['ex'])} 출금 도착 ·"
                           f" {CHAIN_NAME.get(chain, chain)} · 원가 승계"
                           f" (${float(inh_c4):,.2f})",
                           f"{q:,.4f}".rstrip("0").rstrip("."), "—", txh)
                        flow["events"][-1]["_lnk"] = [(sp9, float(sc4) * w9) for sp9, w9 in e4.get("_src", ())]
                        return
                if linked:
                    if linked.get("gid") == arr_gid:
                        g["risk_allow"] = True
                    else:
                        g["risk_allow_bridge"] = True
                    linked["left"] -= take
                    scale = take / linked["qty"] if linked["qty"] > 0 else Decimal(1)
                    inh_cost = linked["cost"] * scale
                    if (linked is br_transit.get(r["posting_id"]) and not linked.get("_cv") and linked["qty"] > 0 and linked["left"] > 0
                            and take >= linked["qty"] * BR_UNIQ_LO):
                        inh_cost = linked["cost"] * (take + linked["left"]) / linked["qty"]
                        linked["left"] = Decimal(0)
                    cb.add_known(g, linked.get("known", linked["qty"]) * scale)
                    cv9 = linked.get("_cv")
                    if cv9 and linked.get("_cmp"):
                        cvk9 = ("cv", r["posting_id"], g["gid"])
                        cp_add(g, cvk9, sum(v9[0] for v9 in linked["_cmp"].values()) * cv9["ratio"] * float(scale),
                               sum(v9[1] for v9 in linked["_cmp"].values()) * float(scale))
                    else:
                        cp_add_map(g, linked.get("_cmp"), scale)
                    cb.add_unknown(g, linked.get("unknown", Decimal(0)) * scale + (q - take))
                    note_unk(g, ts, "브릿지 도착 · 승계(원가 없음)", linked.get("unknown", Decimal(0)) * scale + (q - take), txh, chain9=chain, up_gid=linked.get("gid"), fs9=q - take)
                    cb.add_cost(g, inh_cost)
                    flow = flow_of(g, ts, chain)
                    ev(flow, ts, "전송",
                       f"{CHAIN_NAME.get(chain, chain)} 브릿지 도착 · 원가 이관"
                       f" (${float(inh_cost):,.2f})",
                       f"{q:,.4f}".rstrip("0").rstrip("."), "—", txh)
                    flow["events"][-1]["_lnk"] = [(sp9, float(scale) * w9) for sp9, w9 in linked.get("_src", ())]
                    if cv9 and linked.get("_cmp"):
                        flow["events"][-1]["_cv"] = cv9
                        cp_ev[cvk9] = flow["events"][-1]
                    return
                if evk in ("TRANSFER_IN", "PROGRAM_IN"):
                    of_cand(r, g, q, ts, txh, own9=bool(fx_wd.get(txh) or fx_wd.get((txh or "").lower())
                                                        or txh in ub_wd_tx or (txh or "").lower() in ub_wd_tx))
                if (not g["is_stable"] and evk in ("TRANSFER_IN", "PROGRAM_IN") and r["posting_id"] in sale_links
                        and sale_book(g, r, q, ts, chain, txh)):
                    return
                ret9 = None
                rf_face = [Decimal(0)]
                if sale_rf_exit and not g.get("is_fiat") and evk in ("TRANSFER_IN", "PROGRAM_IN"):
                    ret9 = sale_refund(g, r, q, ts, chain, txh, flow, rf_face)
                if g["is_stable"]:
                    if ret9 is None:
                        cb.acquire(g, q, q)
                    fs_st(g, ts, q if ret9 is None else rf_face[0], chain)
                elif ret9 is None:
                    if fs_on and evk in ("TRANSFER_IN", "PROGRAM_IN") and not g.get("is_fiat") and r["posting_id"] not in br_amb:
                        ret9 = fs_ret(g, ts, q, chain, txh, flow)
                    if ret9 is None:
                        cb.add_unknown(g, q)
                        if r["posting_id"] in br_amb:
                            note_unk(g, ts, f"{CHAIN_NAME.get(chain, chain)} 브릿지 도착 후보 여러 개(컨트랙트 다름 · 원가 연결 보류 — 진짜 도착이면 원가 지정)",
                                     q, r["source_id"], chain9=chain, fs9=0)
                        else:
                            note_unk(g, ts, f"{CHAIN_NAME.get(chain, chain)} 브릿지/유입(원가 없음 · 링크 없음)", q, r["source_id"], chain9=chain)
                if evk in ("TRANSFER_IN", "PROGRAM_IN"):
                    qs2 = f"{q:,.4f}".rstrip("0").rstrip(".")
                    src_ex = fx_wd.get(txh) or fx_wd.get((txh or "").lower())
                    if src_ex:
                        d3 = f"{src_ex} 출금 유입 · {CHAIN_NAME.get(chain, chain)} (원가 연결 대기)"
                        g.setdefault("origin_ex", set()).add(src_ex)
                        g["risk_allow"] = True
                        g["wd_seen"] = True
                    elif txh in ub_wd_tx or (txh or "").lower() in ub_wd_tx:
                        g["risk_allow"] = True
                        g["wd_seen"] = True
                        d3 = f"{CHAIN_NAME.get(chain, chain)} 외부 유입 (원가 미상)"
                    else:
                        near_bo = any(t9b - 600 <= ts <= t9b + 21600
                                      for t9b in bridge_dep_ts.get(g["sym"], ()))
                        td9 = to_dest9.get((g["sym"] or "").upper())
                        tls9 = (td9 or {}).get("ts_list") or []
                        near_to = bool(td9) and (
                            bool(td9.get("no_ts")) or not tls9
                            or any(t9c - 600 <= ts <= t9c + 21600 for t9c in tls9))
                        if not (near_bo or near_to):
                            s9a = signer9.get((r["source_ns"], txh))
                            if s9a and spamguard.signer_mine(*s9a, my_all9):
                                g["risk_airdrop_signed"] = g.get("risk_airdrop_signed", 0) + 1
                            else:
                                g["risk_airdrop"] = True
                        d3 = (f"{CHAIN_NAME.get(chain, chain)} 프로그램 경유 수령 (체결/에어드랍 검토)"
                              if evk == "PROGRAM_IN"
                              else f"{CHAIN_NAME.get(chain, chain)} 외부 유입 (원가 미상)")
                    if g["is_stable"]:
                        extra_ev(ts, g, "전송", d3 + (ret9 or ""), qs2, "—", txh)
                    else:
                        ev(flow, ts, "전송", d3 + (ret9 or ""), qs2, "—", txh)
                else:
                    cb.add_known(g, 0)
                    ev(flow, ts, "온체인 매수",
                       f"{CHAIN_NAME.get(chain, chain)} · 스왑 (원가 산정 중)",
                       f"{q:,.4f}".rstrip("0").rstrip("."), "—", txh)
            else:
                cb.acquire(g, q, cost)
                flow["bought"] += q
                flow["cost"] += cost
                k9acq = krw_of(cost, ts, r)
                flow["cost_krw"] += k9acq
                if g["is_stable"]:
                    stl_add(flow, acct_norm.iso_day(ts), stl_src(r, evk), cost, k9acq, q)
                if (r["source_ns"], r["source_id"]) in krw_mkt:
                    flow["kmc"] = flow.get("kmc", Decimal(0)) + cost
                sg9 = swap_gas.get((r["source_ns"], txh)) if (gas_on and evk == "SWAP") else None
                if sg9 and not sg9["done"] and sg9["sell"] is None and sg9["buy"] == g["gid"] and sg9["usd"] > 0:
                    sg9["done"] = True
                    cb.add_cost(g, sg9["usd"])
                    flow["cost"] += sg9["usd"]
                    flow["cost_krw"] += krw_of(sg9["usd"], ts, r)
                    gas_applied["buy"] += sg9["usd"]
                    gas_applied["n"] += 1
                if evk == "EX_BUY":
                    ex_fee9 = up_fee.get(r["source_id"])
                    if ex_fee9 and r["source_ns"] == "upbit:order" and int(r["leg_seq"] or 0) == 0:
                        ex_fee_add("upbit", cost * ex_fee9[1] / (ex_fee9[0] + ex_fee9[1]), ts)
                    ev(flow, ts, "거래소 매수", f"업비트 · {up_mkt.get(r['source_id'], 'KRW')} 마켓 체결",
                       f"{q:,.4f}".rstrip("0").rstrip("."), f"${float(cost):,.2f}", txh, un=_un(q, cost))
                elif evk == "EXF_BUY":
                    fee_acq[(r["source_ns"], txh)] = {"g": g, "gid": g["gid"], "flow": flow, "row": r, "qty": q, "usd": cost}
                    ex9 = (r["location"] or "").split(":")[-1]
                    ev(flow, ts, "거래소 매수",
                       f"{fx_name.get(ex9, ex9)} · 현물 체결",
                       f"{q:,.4f}".rstrip("0").rstrip("."), f"${float(cost):,.2f}", txh, un=_un(q, cost))
                else:
                    pay9 = [p9 for p9 in (swap_pay.get((r["source_ns"], txh)) or []) if p9[1] > 0] if evk == "SWAP" else []
                    ev(flow, ts, "온체인 매수", f"{CHAIN_NAME.get(chain, chain)} · 스왑"
                       + ((" · 지불 " + " + ".join(f"{_qfmt(p9[1])} {p9[0]}" for p9 in pay9[:3]) + (f" 외 {len(pay9) - 3}" if len(pay9) > 3 else ""))
                          if pay9 else "")
                       + ((" · 동반 토큰(경제 가치 없음 목록) — 원가 0" if r["posting_id"] in swap_fill_zero else
                           " · 원가 = 낸 쪽 시가 나눔" + (" 추정(받은 코인 수로 균등)" if r["posting_id"] in swap_fill_est else ""))
                          if r["cost_usd"] is None else ""),
                       f"{q:,.4f}".rstrip("0").rstrip("."), f"${float(cost):,.2f}", txh, un=_un(q, cost))
            return

        def _h_disp():
            nonlocal _rl9, cv9, cy9, ex_fee9, flow, fu9, kg9, ks9, mc9, mk9
            nonlocal mu9, np9, nx9, qty, rd9, sg9, take9, u
            qty = -q
            cb.snapshot(g, ts, q)
            if g.get("is_fiat"):
                consume(g, qty, cp=False)
                if evk == "EXF_SELL":
                    fee_disp[(r["source_ns"], txh)] = {"g": g, "gid": g["gid"], "qty": qty, "usd": cost, "fiat": True}
                return
            rd9 = redeem_tx.get((r["source_ns"], txh))
            if rd9 and rd9["disp"] == r["posting_id"]:
                mc9, mk9, mu9 = consume(g, qty)
                rd9["carry"] = (mc9, mk9, mu9 + max(Decimal(0), qty - (mk9 + mu9)))
                rd9["carry_krw"] = krw_took(mc9, ts)
                flow = g["cur"] or flow_of(g, ts, chain)
                ev(flow, ts, "전송", f"{CHAIN_NAME.get(chain, chain)} · 세일 영수증 교환 → 본 토큰 · 원가 이관 (${float(mc9):,.2f})",
                   f"{qty:,.4f}".rstrip("0").rstrip("."), "—", txh)
                if g["qty_known"] + g["qty_unknown"] <= Decimal("0.000001"):
                    g["cur"] = None
                return
            nx9 = nopx_swap.get((r["source_ns"], txh)) if cost is None else None
            if nx9 is not None:
                mc9, mk9, mu9 = consume(g, qty)
                cy9 = nopx_carry.setdefault((r["source_ns"], txh), {"q": Decimal(0), "mc": Decimal(0), "mk": Decimal(0), "krw": Decimal(0),
                                                                     "sym": g["sym"], "src": []})
                if g["sym"] not in cy9["sym"].split(" + "):
                    cy9["sym"] += " + " + g["sym"]
                kg9 = cy9.setdefault("kg", {}).setdefault(g["gid"], [Decimal(0), Decimal(0)])
                kg9[0] += mk9
                kg9[1] += qty
                cy9["q"] += qty
                cy9["mc"] += mc9
                cy9["mk"] += mk9
                cy9["krw"] += krw_took(mc9, ts)
                cy9["src"].append((r["posting_id"], 1.0))
                flow = g["cur"] or flow_of(g, ts, chain)
                flow["moved_qty"] += qty
                flow["moved_cost"] += mc9
                mv_note(flow, f"{nx9['asym']} 전환", qty)
                ev(flow, ts, "전송", f"{CHAIN_NAME.get(chain, chain)} · 스왑(양쪽 시세 없음) {g['sym']} → {nx9['asym']} · "
                   + (f"원가 이관 (${float(mc9):,.2f})" if mk9 > EPS else "원가 미상 이관"),
                   f"{qty:,.4f}".rstrip("0").rstrip("."), "—", txh)
                if g["qty_known"] + g["qty_unknown"] <= Decimal("0.000001"):
                    g["cur"] = None
                return
            lb9s = loan_wd.get(r["posting_id"]) if (loan_wd and evk == "EXF_SELL") else None
            if lb9s:
                ex9s = (r["location"] or "").split(":")[-1]
                cb.add_unknown(g, lb9s)
                k09s, c09s = g["qty_known"], g["cost"]
                note_unk(g, ts, f"{fx_name.get(ex9s, ex9s)} 대출로 빌린 코인(바로 매도 · 그 시각 시가 추정)", lb9s, txh or "", ex9=ex9s, chain9=chain, unc9=lb9s)
                if g["qty_known"] - k09s > EPS:
                    loan_px[r["posting_id"]] = (g["cost"] - c09s) / (g["qty_known"] - k09s)
                    fs_sum["loan"]["priced"] += 1
                else:
                    loan_unp[g["gid"]] = loan_unp.get(g["gid"], [Decimal(0), int(ts)])
                    loan_unp[g["gid"]][0] += lb9s
            flow = g["cur"] or flow_of(g, ts, chain)
            is_pay9 = r["posting_id"] in pay_pid
            if is_pay9:
                flow["paid"] = flow.get("paid", Decimal(0)) + qty
            else:
                flow["sold"] += qty
            if evk in ("EX_SELL", "EXF_SELL"):
                short = qty - (g["qty_known"] + g["qty_unknown"])
                if short > EPS:
                    p9s = (r["location"] or "").split(":")
                    sell_ex9 = p9s[1] if evk == "EXF_SELL" and len(p9s) > 1 else "upbit"
                    donors = [g2 for gid2, g2 in G.items()
                              if gid2 != g["gid"] and g2["sym"] == g["sym"]
                              and not g2["is_stable"]
                              and sell_ex9 in (g2.get("ex_dep") or set())
                              and g2["qty_known"] + g2["qty_unknown"] > EPS]
                    if len(donors) == 1:
                        dn = donors[0]
                        take9 = min(short, dn["qty_known"] + dn["qty_unknown"])
                        bc, bk, bu = consume(dn, take9)
                        cp_dn9 = cp_last[0]
                        cb.snapshot(dn, ts, -take9)
                        if dn["qty_known"] + dn["qty_unknown"] <= Decimal("0.000001"):
                            dn["cur"] = None
                        cb.add_known(g, bk)
                        cp_add_map(g, cp_dn9, 1.0)
                        cb.add_unknown(g, bu)
                        note_unk(g, ts, "동일 심볼 원장 정정 · 기증자 승계(원가 없음)", bu, txh, chain9=chain, up_gid=dn.get("gid"), fs9=0)
                        cb.add_cost(g, bc)
                        ev(flow, ts, "전송",
                           "동일 심볼 원장 정정 · 브릿지 인스턴스에서 원가 이관"
                           f" (${float(bc):,.2f})",
                           f"{take9:,.4f}".rstrip("0").rstrip("."), "—", txh)
            from_known = min(qty, g["qty_known"])
            from_unknown = qty - from_known
            wac = cb.wac(g)
            consumed_cost = wac * from_known
            consumed_cost_krw = consume_krw(g, consumed_cost)
            mix9s = krw_mix[0]
            stl9s = krw_stl[0]
            oa9 = oa_take(g, from_known)
            cmp9s = cp_emit(cp_take(g, from_known, consumed_cost), from_unknown, qty, consumed_cost)
            cb.release(g, from_known, consumed_cost, from_unknown)
            if cost is not None:
                is_ex = evk in ("EX_SELL", "EXF_SELL")
                ex_label = "업비트"
                if evk == "EXF_SELL":
                    ex9s = (r["location"] or "").split(":")[-1]
                    ex_label = fx_name.get(ex9s, ex9s)
                rate_s, rsrc_s = fxb.rate_src(ts, r)
                tax9 = u = ud = fu9 = None
                be_sale9 = fsm9 = False
                if from_known > 0:
                    proceeds_known = cost * from_known / qty if qty > 0 else Decimal(0)
                    pnl = proceeds_known - consumed_cost
                    cb.realize(g, pnl)
                    flow["realized"] += pnl
                    if is_pay9:
                        flow["pay_real"] = flow.get("pay_real", Decimal(0)) + pnl
                    flow["rbd"][dkey] = flow["rbd"].get(dkey, Decimal(0)) + pnl
                    flow["rbdk"][dkey] = flow["rbdk"].get(dkey, 0.0) + float(pnl) * rate_s
                    flow.setdefault("rch", {}).setdefault(dkey, set()).add(cur_lab[0] or "?")
                    realized_by_date[dkey] = realized_by_date.get(dkey, 0) + float(pnl)
                    realized_krw_by_date[dkey] = realized_krw_by_date.get(dkey, 0) + float(pnl) * rate_s
                    _rl9 = realized_by_loc.setdefault((loc9, dkey), [0.0, 0.0]); _rl9[0] += float(pnl); _rl9[1] += float(pnl) * rate_s
                    tax9 = {"sold": dkey, "sym": g["sym"], "ticker": g["sym"],
                            "ex": ex_label if is_ex else "온체인(DEX)",
                            "qty": _f(from_known, 4),
                            "acq": _f(consumed_cost, 2),
                            "disp": _f(proceeds_known, 2), "fee": 0, "rate": round(rate_s, 4), "rateSrc": rsrc_s,
                            "_acq": float(consumed_cost), "_disp": float(proceeds_known),
                            "_qty": float(from_known)}
                    if oa9 > EPS:
                        tax9["oa"] = _f(oa9, 4)
                        flow["oa_sold"] = flow.get("oa_sold", Decimal(0)) + oa9
                        flow["oa_real"] = flow.get("oa_real", Decimal(0)) + pnl * oa9 / from_known
                        offc_sold[0] += 1
                        offc_sold[1] += pnl * oa9 / from_known
                    tax_krw_acq(tax9, g, flow, consumed_cost, consumed_cost_krw, rate_s, dkey, venue_loc=loc9, mix9=mix9s)
                    fsm9 = fs_mark(g, flow, tax9, cmp9s, from_known, proceeds_known, consumed_cost, rate_s, dkey)
                    if g["is_stable"]:
                        ks9 = stl_krw_mkt(r)
                        stable_fx_mark(tax9, consumed_cost, ks9, stl9=stl9s, cck9=consumed_cost_krw, mix9=mix9s, use9=stl_use(r, ks9))
                    tax_rows.append(tax9)
                if from_unknown > 0 and g["is_stable"]:
                    pass
                elif from_unknown > 0 and be_take(g["gid"], ts, from_unknown):
                    proceeds_unk = cost * from_unknown / qty if qty > 0 else Decimal(0)
                    be_sale9 = True
                    u = be_done.setdefault(g["gid"], {"sym": g["sym"], "qty": Decimal(0), "proceeds": Decimal(0), "n": 0,
                                                      "first": dkey, "last": dkey, "sales": []})
                    ud = {"qty": from_unknown, "proceeds": proceeds_unk}
                    u["qty"] += from_unknown
                    u["proceeds"] += proceeds_unk
                    u["n"] += 1
                    u["last"] = dkey
                    u["sales"].append(ud)
                    fu9 = [0, Decimal(0)]
                    be_tax.append((ud, {"sold": dkey, "sym": g["sym"], "ticker": g["sym"],
                                        "ex": (ex_label if is_ex else "온체인(DEX)") + " · 매수가=매도가",
                                        "qty": _f(from_unknown, 4), "acq": 0, "disp": 0, "fee": 0, "rate": round(rate_s, 4), "rateSrc": rsrc_s, "be": 1,
                                        "_qty": float(from_unknown)}))
                    tax_rows.append(be_tax[-1][1])
                elif from_unknown > 0:
                    proceeds_unk = cost * from_unknown / qty if qty > 0 else Decimal(0)
                    u = unverified.setdefault(g["gid"], {"sym": g["sym"],
                                                         "qty": Decimal(0),
                                                         "proceeds": Decimal(0), "n": 0,
                                                         "last": dkey, "by_date": {}})
                    u["qty"] += from_unknown
                    u["proceeds"] += proceeds_unk
                    u["n"] += 1
                    u["last"] = dkey
                    ud = u["by_date"].setdefault(dkey, {"qty": Decimal(0), "proceeds": Decimal(0)})
                    ud["qty"] += from_unknown
                    ud["proceeds"] += proceeds_unk
                    fu9 = flow["ubd"].setdefault(dkey, [0, Decimal(0)])
                    fu9[0] += 1
                    fu9[1] += proceeds_unk
                    ubq9 = flow.setdefault("ubq", {})
                    ubq9[dkey] = ubq9.get(dkey, Decimal(0)) + from_unknown
                if evk == "EXF_SELL":
                    fee_disp[(r["source_ns"], txh)] = {"g": g, "gid": g["gid"], "flow": flow, "dkey": dkey, "qty": qty, "usd": cost,
                                                       "fk": qty if g["is_stable"] else from_known, "tax": tax9, "u": u, "ud": ud,
                                                       "fu9": fu9, "rate": rate_s, "loc": loc9}
                if is_pay9:
                    flow.setdefault("pay_dates", []).append(dkey)
                    flow["paid_usd"] = flow.get("paid_usd", Decimal(0)) + cost
                else:
                    flow["sold_dates"].append(dkey)
                    flow["proceeds"] = flow.get("proceeds", Decimal(0)) + cost
                    flow["proceeds_krw"] = flow.get("proceeds_krw", Decimal(0)) + krw_of(cost, ts, r)
                if evk == "EX_SELL" and tax9 is not None and r["source_ns"] == "upbit:order" and int(r["leg_seq"] or 0) == 0:
                    ex_fee9 = up_fee.get(r["source_id"])
                    if ex_fee9 and ex_fee9[0] > ex_fee9[1]:
                        fu_all9 = cost * ex_fee9[1] / (ex_fee9[0] - ex_fee9[1])
                        fk9 = fu_all9 * from_known / qty if qty > 0 else Decimal(0)
                        _tax_add(tax9, "disp", fk9)
                        _tax_add(tax9, "fee", fk9)
                        if tax9.get("fx") is not None and float(tax9.get("_qty") or 0) > 0:
                            tax9["fx"]["d"] = round(float(tax9["_disp"]) * float(tax9.get("rate") or 0) / float(tax9["_qty"]), 2)
                        ex_fee_add("upbit", fu_all9, ts)
                elif evk == "EX_SELL" and r["source_ns"] == "upbit:order" and up_fee.get(r["source_id"]) and int(r["leg_seq"] or 0) == 0:
                    ex_fee9 = up_fee[r["source_id"]]
                    if ex_fee9[0] > ex_fee9[1]:
                        ex_fee_add("upbit", cost * ex_fee9[1] / (ex_fee9[0] - ex_fee9[1]), ts)
                sg9 = swap_gas.get((r["source_ns"], txh)) if (gas_on and evk == "SWAP") else None
                if sg9 and not sg9["done"] and sg9["sell"] == g["gid"] and sg9["usd"] > 0 and (tax9 is not None or u is not None):
                    sg9["done"] = True
                    G9 = sg9["usd"]
                    Gk9 = G9 * from_known / qty if (qty > 0 and tax9 is not None) else Decimal(0)
                    Gu9 = G9 - Gk9 if u is not None else Decimal(0)
                    if Gk9 > 0:
                        cb.unrealize(g, Gk9)
                        flow["realized"] -= Gk9
                        flow["rbd"][dkey] = flow["rbd"].get(dkey, Decimal(0)) - Gk9
                        flow["rbdk"][dkey] = flow["rbdk"].get(dkey, 0.0) - float(Gk9) * rate_s
                        realized_by_date[dkey] = realized_by_date.get(dkey, 0) - float(Gk9)
                        realized_krw_by_date[dkey] = realized_krw_by_date.get(dkey, 0) - float(Gk9) * rate_s
                        _rl9 = realized_by_loc.setdefault((loc9, dkey), [0.0, 0.0]); _rl9[0] -= float(Gk9); _rl9[1] -= float(Gk9) * rate_s
                        _tax_add(tax9, "fee", Gk9)
                    if Gu9 > 0:
                        u["proceeds"] -= Gu9
                        ud["proceeds"] -= Gu9
                        fu9[1] -= Gu9
                    gas_applied["sell"] += Gk9 + Gu9
                    gas_applied["n"] += 1
                cv9 = conv_cp.get((r["source_ns"], txh)) if (g["is_stable"] and not is_pay9) else None
                cv9 = [s9 for s9 in (cv9 or ()) if s9 != g["sym"]]
                ev(flow, ts, "거래소 매도" if is_ex else "온체인 매도",
                   (f"{ex_label} · " + (f"{up_mkt.get(r['source_id'], 'KRW')} 마켓 체결" if evk == "EX_SELL" else "현물 체결")
                    if is_ex
                    else f"{CHAIN_NAME.get(chain, chain)} · 스왑 매도")
                   + (" · 매수 대금 지불(스왑 지불 레그)" if is_pay9 else "")
                   + (f" · {g['sym']} → {' · '.join(cv9)} 전환" if cv9 else "")
                   + unk_tag(from_known, from_unknown, cost, qty, g["is_stable"], be_sale9)
                   + ((" · 원화 원가 일부 최초 인식 시가(그때 환율)" if g["is_stable"] else " · 원가 일부 최초 인식 시가") if fsm9 else "")
                   + (f" · 원가 {'전부' if oa9 >= from_known - EPS else '일부'} 오프체인 이어받음(내 계정으로 가정)" if oa9 > EPS else "")
                   + ((" · 동반 토큰(경제 가치 없음 목록) — 정산액 0" if r["posting_id"] in swap_fill_zero else
                       " · 정산액 = 받은 쪽 시가 나눔" + (" 추정(낸 코인 수로 균등)" if r["posting_id"] in swap_fill_est else ""))
                      if r["cost_usd"] is None and r["posting_id"] in swap_fill else ""),
                   f"{qty:,.4f}".rstrip("0").rstrip("."), f"${float(cost):,.2f}", txh, un=_un(qty, cost))
                if cmp9s is not None:
                    flow["events"][-1]["_cmp"] = cmp9s
                flow["events"][-1]["_tax"] = tax9 if tax9 is not None else (be_tax[-1][1] if be_sale9 and be_tax else None)
                if is_pay9:
                    flow["events"][-1]["_pay"] = True
                elif cv9:
                    flow["events"][-1]["_conv"] = "원화 환전" if cv9 == ["원화"] else "스테이블 교환"
            else:
                ev(flow, ts, "온체인 매도", f"{CHAIN_NAME.get(chain, chain)} · 정산액 산정 중"
                   + (" · 매수 대금 지불(스왑 지불 레그)" if is_pay9 else ""),
                   f"{qty:,.4f}".rstrip("0").rstrip("."), "—", txh)
                flow["events"][-1]["_tax"] = None
                np9 = noproc.setdefault(g["gid"], {"sym": g["sym"], "n": 0, "qty": Decimal(0), "cost": Decimal(0), "unk": Decimal(0),
                                                   "first": dkey, "last": dkey, "where": set(), "tx": [], "old": False})
                np9["old"] = np9["old"] or (time.time() - float(ts or 0) > 3600)
                np9["n"] += 1
                np9["qty"] += qty
                np9["cost"] += consumed_cost
                np9["unk"] += from_unknown
                np9["last"] = max(np9["last"], dkey)
                if evk == "EXF_SELL":
                    exn9 = (r["location"] or "").split(":")[-1]
                    np9["where"].add(fx_name.get(exn9, exn9))
                elif evk == "EX_SELL":
                    np9["where"].add("업비트")
                else:
                    np9["where"].add(CHAIN_NAME.get(chain, chain))
                if len(np9["tx"]) < 5:
                    np9["tx"].append(str(txh or ""))
                if cmp9s is not None:
                    flow["events"][-1]["_cmp"] = cmp9s
                if is_pay9:
                    flow["events"][-1]["_pay"] = True
            if g["qty_known"] + g["qty_unknown"] <= Decimal("0.000001"):
                g["cur"] = None
            return

        def _h_exf_fee():
            nonlocal F9, _rl9, chg9f, cp9, sh9, sp9, unit9
            fq9 = -q
            k9f = (r["source_ns"], txh)
            a9f, d9f = fee_acq.get(k9f), fee_disp.get(k9f)
            chg9f = False
            unit9 = None
            for c9f in (a9f, d9f):
                if unit9 is None and c9f and c9f["gid"] == g["gid"] and c9f["qty"] > 0 and c9f["usd"] is not None:
                    unit9 = c9f["usd"] / c9f["qty"]
            if unit9 is None and g["is_stable"]:
                unit9 = Decimal(1)
            if unit9 is None and not g.get("is_fiat"):
                cp9 = _fx_candle_near(fxb, g["sym"], ts)
                if cp9:
                    unit9 = Decimal(str(cp9))
            if unit9 is None and g["qty_known"] > EPS:
                unit9 = g["cost"] / g["qty_known"]
            F9 = fq9 * unit9 if (unit9 is not None and fq9 != 0) else Decimal(0)
            if unit9 is None and fq9 > 0:
                fee_diag["no_px"] += 1
            if F9 != 0 and (a9f or d9f):
                fee_diag["n"] += 1
                if a9f and not a9f["g"]["is_stable"] and not a9f["g"].get("is_fiat"):
                    chg9f = True
                    ga9 = a9f["g"]
                    cb.add_cost(ga9, F9)
                    a9f["flow"]["cost"] += F9
                    a9f["flow"]["cost_krw"] += krw_of(F9, ts, a9f["row"])
                    if k9f in krw_mkt:
                        a9f["flow"]["kmc"] = a9f["flow"].get("kmc", Decimal(0)) + F9
                    fee_diag["usd_cost"] += F9
                elif a9f and a9f["g"]["is_stable"] and d9f and d9f.get("fiat"):
                    chg9f = True
                    ga9 = a9f["g"]
                    cb.add_cost(ga9, F9)
                    a9f["flow"]["cost"] += F9
                    a9f["flow"]["cost_krw"] += krw_of(F9, ts, a9f["row"])
                    fee_diag["usd_cost"] += F9
                elif d9f and not d9f.get("fiat"):
                    chg9f = True
                    rt9f = d9f["rate"]
                    sh9 = (d9f["fk"] / d9f["qty"]) if d9f["qty"] > 0 else Decimal(1)
                    Fk9, Fu9 = F9 * sh9, F9 - F9 * sh9
                    fl9f, dk9f = d9f["flow"], d9f["dkey"]
                    if Fk9 != 0:
                        cb.unrealize(d9f["g"], Fk9)
                        fl9f["realized"] -= Fk9
                        fl9f["rbd"][dk9f] = fl9f["rbd"].get(dk9f, Decimal(0)) - Fk9
                        fl9f["rbdk"][dk9f] = fl9f["rbdk"].get(dk9f, 0.0) - float(Fk9) * rt9f
                        realized_by_date[dk9f] = realized_by_date.get(dk9f, 0) - float(Fk9)
                        realized_krw_by_date[dk9f] = realized_krw_by_date.get(dk9f, 0) - float(Fk9) * rt9f
                        if d9f.get("loc") is not None:
                            _rl9 = realized_by_loc.setdefault((d9f["loc"], dk9f), [0.0, 0.0]); _rl9[0] -= float(Fk9); _rl9[1] -= float(Fk9) * rt9f
                        if d9f["tax"] is not None:
                            _tax_add(d9f["tax"], "fee", Fk9)
                        fee_diag["usd_realized"] += Fk9
                    if Fu9 != 0 and d9f["u"] is not None:
                        d9f["u"]["proceeds"] -= Fu9
                        d9f["ud"]["proceeds"] -= Fu9
                        d9f["fu9"][1] -= Fu9
                        fee_diag["usd_unv"] += Fu9
                    fl9f["proceeds"] = fl9f.get("proceeds", Decimal(0)) - F9
                    fl9f["proceeds_krw"] = fl9f.get("proceeds_krw", Decimal(0)) - F9 * Decimal(str(rt9f))

        for r in rows:
            if lf_pend and (r["source_ns"], r["source_id"]) != lf_pend[-1][7]:
                loan_settle()
            if sale_pay_q and sale_pay_q[0][0] <= r["event_ts"]:
                sale_pay_flush(r["event_ts"])
            n9i += 1
            if not (n9i & 4095) and g0_9 is not None and self._inval_now() != g0_9:
                raise _BuildObsolete("replay")
            g = gstate(r)
            chain = r["chain"] or "?"
            g["chains"].add(chain)
            qn9 = qn_all9[n9i - 1] if n9i <= len(qn_all9) else None
            q = qn9[1] if qn9 is not None and qn9[0] is r else self._norm(r)
            ts = r["event_ts"]
            lk, evk = r["leg_kind"], r["event"]
            cur_row[0] = r
            cp_sync(g)
            pid_row[r["posting_id"]] = r
            if lk in ("acq", "disp") and r["cost_usd"] is not None:
                g["px_seen"] = True
            if evk in ("EX_DEPOSIT", "EXF_DEPOSIT", "EX_SELL", "EXF_SELL", "EX_BUY", "EXF_BUY", "EX_WITHDRAW", "EXF_WITHDRAW"):
                g["ex_seen"] = True
            elif evk in ("TRANSFER_OUT_EX", "BRIDGE", "TRANSFER_SELF") and lk in ("move_out", "move_in"):
                g["mv_seen"] = True
            if (r["location"] or "").startswith("wallet:"):
                wk9 = (r["asset_id"], r["location"])
                held9 = wbal9.get(wk9, Decimal(0))
                if lk == "move_out" and q < 0:
                    g["sent_n"] = g.get("sent_n", 0) + 1
                if q != 0 and (lk in ("disp", "move_out") or (lk == "acq" and evk == "SWAP")) \
                        and (r["source_ns"], r["source_id"]) in signer9 \
                        and spamguard.signer_mine(*signer9[(r["source_ns"], r["source_id"])], my_all9):
                    g["cg_mine"] = True
                if lk == "move_out" and q < 0 and chain != "sol" and r["kind"] == "token" \
                        and evk in ("TRANSFER_OUT", "BRIDGE", "TRANSFER_SELF", "TRANSFER_OUT_EX") \
                        and -q > max(held9, Decimal(0)) * Decimal("1.000001") + EPS \
                        and not spamguard.is_genuine(chain, r["address"]) \
                        and (r["source_ns"], r["source_id"]) in signer9 \
                        and spamguard.signer_known_other(*signer9[(r["source_ns"], r["source_id"])], my_evm9):
                    spoof_keys.add((r["source_ns"], r["source_id"], r["asset_id"]))
                    g["spoof_n"] = g.get("spoof_n", 0) + 1
                elif lk == "move_out" and q < 0 and chain != "sol" and r["kind"] == "token" \
                        and evk in ("TRANSFER_OUT", "BRIDGE", "TRANSFER_SELF", "TRANSFER_OUT_EX") \
                        and not spamguard.is_genuine(chain, r["address"]) and (r["source_ns"], r["source_id"]) in signer9 \
                        and spamguard.signer_known_other(*signer9[(r["source_ns"], r["source_id"])], my_evm9):
                    g["spoof_soft"] = g.get("spoof_soft", 0) + 1
                wbal9[wk9] = held9 + q
            loc9 = r["location"] or ""
            if loc9.startswith("lp:"):
                g.setdefault("lp_tl", []).append((ts, q))
            if loc9.startswith("wallet:"):
                p9 = loc9.split(":")
                cur_src[0] = f"w:{p9[2]}" if len(p9) >= 3 and p9[2] else "w:?"
            elif loc9.startswith("exchange:"):
                cur_src[0] = "ex:" + loc9.split(":")[1]
            else:
                cur_src[0] = None
            cur_lab[0] = (CHAIN_NAME.get(chain, chain) if chain != "?"
                          else fx_name.get(loc9.split(":")[1], loc9.split(":")[1]) if loc9.startswith("exchange:") else None)
            if g["cur"] is not None and cur_lab[0] and lk != "gas":
                chl9 = g["cur"].setdefault("chl", {})
                chl9[cur_lab[0]] = chl9.get(cur_lab[0], 0) + 1
            cost = Decimal(r["cost_usd"]) if r["cost_usd"] is not None else swap_fill.get(r["posting_id"])
            dkey = acct_norm.iso_day(ts)
            txh = r["source_id"]
            if loan_fill and r["posting_id"] in loan_fill:
                lf_pend.append((g, loan_fill[r["posting_id"]], ts, dkey, chain, txh, loc9, (r["source_ns"], txh), r))

            if r["kind"] in ("native", "exchange_currency"):
                g["risk_allow"] = True
            if lk == "disp" and evk == "SWAP" and r["cost_usd"] is not None and q < 0:
                for cp9 in swap_recv.get((r["source_ns"], txh)) or ():
                    if cp9[0] != g["gid"]:
                        g.setdefault("risk_disp_cp", set()).add(cp9)
            if evk in ("EX_BUY", "EXF_BUY", "TRANSFER_SELF", "CONVERT", "BRIDGE",
                       "EX_DEPOSIT", "EX_SELL") or \
                    (lk == "acq" and evk == "SWAP"):
                g["risk_allow"] = True
            elif lk == "acq" and evk in ("TRANSFER_IN", "PROGRAM_IN") and q > 0:
                if r["cost_usd"] is not None:
                    g["risk_allow"] = True
                elif len(g.setdefault("risk_srcs", [])) < 50 and r["address"] \
                        and (chain, txh, r["address"]) not in g.setdefault("risk_srcs_seen", set()):
                    g["risk_srcs_seen"].add((chain, txh, r["address"]))
                    g["risk_srcs"].append((chain, txh, r["address"]))
            elif lk == "opening" and evk == "OPENING":
                if q > 0:
                    g["risk_open_unk"] = True
                elif q < 0 and str(txh).startswith("rebal"):
                    g["risk_rebal_neg"] = True

            if str(evk or "").startswith("LP_") and lk in ("disp", "acq"):
                if (r["source_ns"], txh) not in lp_done:
                    lp_done.add((r["source_ns"], txh))
                    lp_tx(r)
                continue

            if lk == "gas" and evk == "EXF_WD_FEE":
                _h_gas_exf_wd_fee()
                continue
            if lk == "gas" and evk == "EXF_FEE":
                _h_exf_fee()
            if lk == "gas" and evk == "EXF_FEE":
                ex_fee_add((r["location"] or "").split(":")[-1], F9, ts)
                if q > 0:
                    if unit9 is None:
                        kb_rb, cb_rb = g["qty_known"], g["cost"]
                        cb.add_unknown(g, q)
                        note_unk(g, ts, f"{fx_name.get((r['location'] or '').split(':')[-1], (r['location'] or '').split(':')[-1])} 체결 수수료 환급(리베이트)"
                                 " · 시세 없음(원가 없음)", q, txh, ex9=(r["location"] or "").split(":")[-1])
                        dk_rb, dc_rb = g["qty_known"] - kb_rb, g["cost"] - cb_rb
                        if dk_rb > EPS and dc_rb > 0:
                            fee_gain(g, dc_rb / dk_rb, dk_rb, Decimal(0), ts, dkey, chain, lab9="체결 수수료 환급(리베이트 · 지정·인식 원가 = 소득)")
                    else:
                        cb.acquire(g, q, q * unit9)
                        if g["is_stable"]:
                            fs_st(g, ts, q * unit9, chain)
                        else:
                            st_flow_in(g, {"kc": q * unit9, "kk": krw_of(q * unit9, ts)}, Decimal(1), ts, chain)
                        if not chg9f:
                            fee_gain(g, unit9, q, Decimal(0), ts, dkey, chain, lab9="체결 수수료 환급(리베이트 · 짝 체결 없음 = 소득)")
                    cb.snapshot(g, ts, q)
                    continue
                mcf9, mkf9, _muf9 = consume(g, -q, cp=bool(chg9f))
                if chg9f:
                    fee_gain(g, unit9, mkf9, mcf9, ts, dkey, chain, krw_last[0], mix9=krw_mix[0], stl9=krw_stl[0],
                             cmp9=cp_emit(cp_last[0], _muf9, mkf9 + _muf9, mcf9))
                cb.snapshot(g, ts, q)
                continue
            if lk == "gas":
                _h_gas()
                continue

            if lk == "move_in" and evk == "EX_DEPOSIT":
                _h_ex_deposit()
                continue

            if lk == "move_in" and evk == "EXF_DEPOSIT":
                _h_exf_deposit()
                continue

            if evk == "TRANSFER_OUT" and lk in ("move_out", "move_in"):
                if loc9.startswith("out:") and lk == "move_in":
                    out_move(r, g, q, ts, chain, txh)
                continue

            if lk in ("move_out", "move_in") and str(evk or "").startswith("LP_"):
                lp_move(r, g, q, ts, lk, chain, txh)
                continue

            if lk == "move_in" and evk == "BRIDGE" and q > 0:
                lk, evk = "acq", "TRANSFER_IN"

            if lk in ("move_out", "move_in"):
                _h_move()
                continue

            if lk == "opening":
                _h_opening()
                continue

            if lk == "acq" and evk == "STAKE_REWARD":
                _h_stake_reward()
                continue

            if lk == "acq":
                _h_acq()
                continue

            if lk == "disp":
                _h_disp()
                continue

        if lf_pend:
            loan_settle()
        for gid_u9, (q_u9, ts_u9) in loan_unp.items():
            g_u9 = G.get(gid_u9)
            if g_u9 is None:
                continue
            c_u9, k_u9, _x9 = consume(g_u9, q_u9)
            if k_u9 > EPS:
                o_u9 = g_u9.get("unv_lost") or (Decimal(0), Decimal(0), ts_u9)
                g_u9["unv_lost"] = (o_u9[0] + k_u9, o_u9[1] + c_u9, min(int(o_u9[2] or ts_u9), ts_u9))
        sale_pay_flush(None)
        cur_row[0] = None
        for fl9, tx9, sh9, c9, rt9, dk9 in fs_sales:
            est9 = (float(tx9.get("_disp", tx9.get("disp")) or 0) - float(tx9.get("_fee", tx9.get("fee")) or 0)) * sh9 - c9
            a9 = fs_rbd.setdefault(dk9, [0.0, 0.0])
            a9[0] += est9
            a9[1] += est9 * rt9
            fl9["fs_rz"] = fl9.get("fs_rz", 0.0) + est9
            fs_sum["real"] += Decimal(str(est9))
        for ud9, t9 in be_tax:
            p9 = float(ud9["proceeds"])
            t9.update({"acq": _f(p9, 2), "disp": _f(p9, 2), "_acq": p9, "_disp": p9, "_akr": p9 * float(t9["rate"] or 0)})
            t9["akr"] = float(t9["disp"]) * float(t9["rate"] or 0)
        for gid_w, dw in win_cut_d.items():
            if not dw:
                continue
            g_w = G.get(gid_w)
            if g_w is None:
                continue
            c_lost, k_lost, _u_lost = consume(g_w, dw[0])
            if k_lost > EPS:
                g_w["unv_lost"] = (k_lost, c_lost, dw[1])

        exb9 = type(self)._exf_bal_view()
        pvc_cs9, pvc_xs9 = {}, {}
        try:
            pvc_cs9, pvc_xs9 = self._prov_seen(conn, exb9)
        except Exception as e9:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_b_replay:ReplayMixin._build_replay[pvc_cs9]", e9)
            log.warning("첫 대사 전 잔고 관측 시각 읽기 실패(전송 중 종전대로): %s", logs.safe_err(e9)[:160])
        uncred_gid = {}
        dep_tr9 = []
        uncred_fx = {}
        uncred_known = {}
        uncred_cost = {}
        for lst in ex_transit.values():
            for e2 in lst:
                if not e2["credited"] and not e2["used"]:
                    gk = e2["gid"]
                    uncred_gid[gk] = uncred_gid.get(gk, Decimal(0)) + e2["qty"]
                    if e2.get("ts"):
                        dep_tr9.append({"gid": gk, "ts": int(e2["ts"]), "qty": e2["qty"]})
                    cy2 = e2.get("cyc")
                    if cy2 is not None:
                        cy2["moved_qty"] -= e2["qty"]
                        cy2["moved_cost"] -= e2.get("cost", Decimal(0))
                    uncred_known[gk] = uncred_known.get(gk, Decimal(0)) + e2.get("known", Decimal(0))
                    uncred_cost[gk] = uncred_cost.get(gk, Decimal(0)) + e2.get("cost", Decimal(0))
        for e9 in fxdep_transit.values():
            if (e9.get("ex") in pvc_xs9 and e9.get("ts") and int(pvc_xs9[e9["ex"]]) >= int(e9["ts"])
                    and str(e9.get("sym") or "").upper() not in ((self.__dict__.get("_prov_xblk") or {}).get(e9["ex"]) or ())):
                continue
            if e9["left"] > EPS and e9["qty"] > 0:
                sc9 = e9["left"] / e9["qty"]
                gk9 = e9.get("gid")
                if gk9 is not None:
                    if e9.get("ex"):
                        uncred_fx[gk9] = e9["ex"]
                    uncred_gid[gk9] = uncred_gid.get(gk9, Decimal(0)) + e9["left"]
                    if e9.get("ts"):
                        dep_tr9.append({"gid": gk9, "ts": int(e9["ts"]), "qty": e9["left"]})
                    for cy9, q9c, c9c in e9.get("cycs") or ():
                        if cy9 is not None:
                            cy9["moved_qty"] -= q9c * sc9
                            cy9["moved_cost"] -= c9c * sc9
                    uncred_known[gk9] = uncred_known.get(gk9, Decimal(0)) + e9["known"] * sc9
                    uncred_cost[gk9] = uncred_cost.get(gk9, Decimal(0)) + e9["cost"] * sc9
        try:
            wdt_all = self._wd_transit_resolve(wd_tr, rows, wd_raw9, fx_transit, xf_links, up_dep_uid_tx, exf_dep_tx, G,
                                               skip_tx=frozenset(of_chain) | frozenset(fx_wd), now=now, ton_h2u=ton_h2u9,
                                               skip_deps=frozenset(uuid2txh) | frozenset(
                                                   u9 for m9 in of_match.values() for u9 in _of_uids(m9))
                                               | frozenset(u9 for e9, u9 in offc_dep if e9 in offc_on))
        except Exception as e9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_b_replay:ReplayMixin._build_replay[wdt_all]", e9)
            log.warning("거래소 출금 전송 중 판정 실패(종전대로 즉시 차감): %s", e9)
            wdt_all = []
        self._wd_transit_wake(wdt_all)
        if pvc_cs9 or pvc_xs9:
            type(self)._wdt_prov_mark(wdt_all, pvc_cs9, pvc_xs9, self.__dict__.get("_prov_xblk"))
        wdt_gid = {}
        for e9 in wdt_all:
            if e9["state"] != "pending":
                continue
            gk9 = e9["gid"]
            uncred_gid[gk9] = uncred_gid.get(gk9, Decimal(0)) + e9["qty"]
            uncred_known[gk9] = uncred_known.get(gk9, Decimal(0)) + e9["known"]
            uncred_cost[gk9] = uncred_cost.get(gk9, Decimal(0)) + e9["cost"]
            wdt_gid.setdefault(gk9, []).append(e9)
            cy9 = e9.get("cyc")
            if cy9 is not None and (G.get(gk9) or {}).get("cur") is cy9:
                cy9["moved_qty"] -= e9["qty"]
                cy9["moved_cost"] -= e9["cost"]
            if isinstance(e9.get("ev"), dict):
                e9["ev"]["d"] = f"{e9['src']} 출금 → " + (f"{e9['dst']} " if e9.get("dst") else "") + "전송 중 (도착 확인 대기)"
        if self.KEEP_DIAG:
            self._wd_transit_last = wdt_all
        pos_rows = []
        by_symloc = {}
        lp_pos_rows = []
        _load_position_rows(conn, lp_pos_rows, pos_rows, G, by_symloc)
        ex_resid9 = {}
        for key0, rows0 in by_symloc.items():
            neg0 = sum((-r["qty"] for r in rows0 if r["qty"] < 0), Decimal(0))
            if neg0 <= 0:
                continue
            for r in sorted((r for r in rows0 if r["qty"] > 0),
                            key=lambda r: (-r["qty"], r["gid"])):
                take0 = min(r["qty"], neg0)
                r["qty"] -= take0
                neg0 -= take0
                if neg0 <= 0:
                    break
            if neg0 > 0:
                ex_resid9[key0] = neg0
        debt_cap9 = {}
        for ex9, (_bp9, bd9) in exb9.items():
            for s9, v9 in ((bd9.get("debts") or {}).items() if isinstance(bd9.get("debts"), dict) else ()):
                try:
                    fv9 = Decimal(str(v9))
                except (InvalidOperation, ValueError, TypeError):
                    continue
                su9 = str(s9).upper()
                if fv9.is_finite() and fv9 < 0 and su9 not in ("KRW", "USD"):
                    debt_cap9[(f"exchange:{ex9}", su9)] = debt_cap9.get((f"exchange:{ex9}", su9), Decimal(0)) - fv9
        debt_take9 = {}
        debt_over9 = {}
        for (sym0, loc0), rem0 in sorted(ex_resid9.items()):
            cap0 = debt_cap9.get((loc0, sym0))
            if not cap0:
                continue
            left0 = min(rem0, cap0)
            if rem0 > cap0:
                debt_over9[(loc0, sym0)] = rem0 - cap0
            for r in sorted((r for r in by_symloc[(sym0, loc0)] if r["qty"] < 0), key=lambda r: (r["qty"], r["gid"])):
                t0 = min(-r["qty"], left0)
                if t0 > 0:
                    debt_take9[(r["gid"], loc0)] = t0
                    left0 -= t0
                if left0 <= 0:
                    break
        debt_capg9 = {}
        for d0 in pos_rows:
            k0 = (d0["location"], ((G.get(d0["gid"]) or {}).get("sym") or "").upper())
            if k0 in debt_cap9 and not (G.get(d0["gid"]) or {}).get("is_fiat"):
                debt_capg9[d0["gid"]] = debt_capg9.get(d0["gid"], Decimal(0)) + debt_cap9[k0]
        pv_its9 = []
        try:
            pv_its9 = self._prov_items(conn)
        except Exception as e9:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_b_replay:ReplayMixin._build_replay[pv_its9]", e9)
            log.warning("지금 잔고(첫 대사 전) 읽기 실패(원장 숫자만): %s", logs.safe_err(e9)[:160])
        if pv_its9:
            nsym9 = dict(self.cfg.get("native_symbol") or {})
            pv_its9 = provbal.net_pending(pv_its9, wdt_all, chain_of=depaddr.chain_of, norm=xfer_match.norm_addr,
                                          native_sym=lambda c9: nsym9.get(c9))
        xp_its9 = []
        try:
            xp_its9 = self._exf_prov_items(conn, exb9)
        except Exception as e9:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_b_replay:ReplayMixin._build_replay[xp_its9]", e9)
            log.warning("거래소 지금 잔고(첫 대사 전) 읽기 실패(원장 숫자만): %s", logs.safe_err(e9)[:160])
        pv_adj9 = {}
        pv_unk9 = []
        xp_unk9 = []
        for it9 in pv_its9:
            g9 = G.get(it9["gid"]) if it9["gid"] is not None else None
            if g9 is not None and not g9.get("is_fiat"):
                k9 = (it9["gid"], it9["loc"])
                pv_adj9[k9] = pv_adj9.get(k9, Decimal(0)) + it9["qty"]
            elif g9 is None and it9["qty"] > 0:
                pv_unk9.append(it9)
        pv_dl9 = {}
        pos_disp9 = pos_rows
        if pv_adj9:
            pos_disp9 = []
            for r in pos_rows:
                k9 = (r["gid"], r["location"])
                if k9 in pv_adj9 and k9 not in pv_dl9:
                    q09 = r["qty"]
                    r = dict(r, qty=q09 + pv_adj9[k9])
                    pv_dl9[k9] = max(r["qty"], Decimal(0)) - max(q09, Decimal(0))
                pos_disp9.append(r)
            for k9, d9 in sorted(pv_adj9.items(), key=lambda kv: (kv[0][0], kv[0][1])):
                if k9 not in pv_dl9:
                    pos_disp9.append({"gid": k9[0], "location": k9[1], "qty": d9})
                    pv_dl9[k9] = max(d9, Decimal(0))
        if xp_its9:
            xp_tgt9, xp_sym9 = {}, {}
            for it9 in xp_its9:
                g9 = G.get(it9["gid"]) if it9["gid"] is not None else None
                if g9 is None:
                    if it9["qty"] != 0:
                        xp_unk9.append(it9)
                    continue
                if g9.get("is_fiat"):
                    continue
                for gg9 in it9.get("gids") or ():
                    if gg9 in G and (gg9, it9["loc"]) not in xp_tgt9:
                        xp_tgt9[(gg9, it9["loc"])] = Decimal(0)
                        xp_sym9[(gg9, it9["loc"])] = it9["sym"]
                xp_tgt9[(it9["gid"], it9["loc"])] = it9["qty"] + it9["now"]
                xp_sym9[(it9["gid"], it9["loc"])] = it9["sym"]
            if xp_tgt9:
                hlc9 = {str(x9).upper() for x9 in _hl_cash_syms()}
                old9, new9 = {}, []
                for r in pos_disp9:
                    k9 = (r["gid"], r["location"])
                    if k9 in xp_tgt9 and k9 not in old9:
                        old9[k9] = r["qty"]
                        r = dict(r, qty=xp_tgt9[k9])
                    new9.append(r)
                for k9, q9 in sorted(xp_tgt9.items(), key=lambda kv: (kv[0][1], kv[0][0])):
                    if k9 not in old9:
                        new9.append({"gid": k9[0], "location": k9[1], "qty": q9})
                        old9[k9] = Decimal(0)
                pos_disp9 = new9
                for k9, q9 in sorted(xp_tgt9.items(), key=lambda kv: (kv[0][1], kv[0][0])):
                    dt0 = debt_take9.pop(k9, Decimal(0))
                    dt1 = Decimal(0)
                    cap9 = debt_cap9.get((k9[1], xp_sym9[k9]))
                    if q9 < 0 and cap9:
                        dt1 = min(-q9, cap9)
                        debt_take9[k9] = dt1
                    if k9[1] == "exchange:hyperliquid" and str(xp_sym9[k9]).upper() in hlc9:
                        d9 = q9 - old9[k9]
                    else:
                        d9 = (max(q9, Decimal(0)) - dt1) - (max(old9[k9], Decimal(0)) - dt0)
                    if d9:
                        pv_dl9[k9] = pv_dl9.get(k9, Decimal(0)) + d9
        pv_led9 = {}
        for (gid9, _l9), d9 in pv_dl9.items():
            pv_led9[gid9] = pv_led9.get(gid9, Decimal(0)) + d9
        locs_by_gid = {}
        led_by_gid = {}
        led_upbit_gids = set()
        upbit_transit_gids = {
            e2["gid"] for lst in ex_transit.values() for e2 in lst
            if not e2["credited"] and not e2["used"]}
        ub_path9 = paths.state("upbit_balances.json")
        ub_snap9 = None
        uf_dl9, uf_kc9, self._ub_fill_info = {}, {}, {"why": "none", "n": 0, "ts": 0}
        try:
            ub_snap9 = statefile.read_json(ub_path9, {}) if os.path.exists(ub_path9) else {}
            pos_disp9, uf_dl9, uf_kc9, self._ub_fill_info = self._ub_fill_view(conn, ub_snap9, pos_disp9, G, upbit_transit_gids, now)
        except Exception as e9:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_b_replay:ReplayMixin._build_replay[ub_snap9]", e9)
            log.warning("업비트 미체결 주문 체결분 보정 실패(원장 수량 그대로): %s", logs.safe_err(e9)[:160])
        for gid9, (k9, c9) in uf_kc9.items():
            uncred_known[gid9] = uncred_known.get(gid9, Decimal(0)) + k9
            uncred_cost[gid9] = uncred_cost.get(gid9, Decimal(0)) + c9
        hl_neg = {}
        debt_neg9 = {}
        hl_cash_syms9 = _hl_cash_syms()
        for r in pos_disp9:
            locs_by_gid.setdefault(r["gid"], []).append(
                {"location": r["location"], "qty_norm": str(r["qty"])})
            if r["qty"] > 0:
                led_by_gid[r["gid"]] = led_by_gid.get(r["gid"], Decimal(0)) + r["qty"]
                if r["location"] == "exchange:upbit":
                    led_upbit_gids.add(r["gid"])
            elif (r["qty"] < -EPS and r["location"] == "exchange:hyperliquid"
                  and str((G.get(r["gid"]) or {}).get("sym") or "").upper() in hl_cash_syms9):
                led_by_gid[r["gid"]] = led_by_gid.get(r["gid"], Decimal(0)) + r["qty"]
                hl_neg[r["gid"]] = led_by_gid[r["gid"]]
            elif r["qty"] < -EPS and (r["gid"], r["location"]) in debt_take9:
                led_by_gid[r["gid"]] = led_by_gid.get(r["gid"], Decimal(0)) - debt_take9[(r["gid"], r["location"])]
                debt_neg9[r["gid"]] = debt_neg9.get(r["gid"], Decimal(0)) + debt_take9[(r["gid"], r["location"])]

        live = {gid: g for gid, g in G.items()
                if not g.get("is_fiat")
                and (led_by_gid.get(gid, Decimal(0)) + uncred_gid.get(gid, Decimal(0)) > EPS or gid in hl_neg or gid in debt_neg9)}
        price_groups = dict(live)
        price_t0 = (today_kst - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        for gid, g in G.items():
            if gid in price_groups or g.get("is_fiat"):
                continue
            if (sum((dq for ts, dq in g["qty_timeline"] if ts < price_t0), Decimal(0)) > EPS
                    or any(ts >= price_t0 and dq > 0 for ts, dq in g["qty_timeline"])):
                price_groups[gid] = g
        self.spot.want([g["sym"] for g in G.values()])
        ex_gid = {}
        for r7 in conn.execute("SELECT group_id, address FROM assets"
                               " WHERE kind='exchange_currency' AND group_id IS NOT NULL"):
            ad7 = str(r7["address"] or "")
            if ":" in ad7:
                ex_gid[r7["group_id"]] = ad7.split(":", 1)[0]
        self.spot.want_ex({ex for gid, ex in ex_gid.items() if gid in price_groups})
        tok_pairs9 = {}
        for r2 in conn.execute("SELECT group_id, chain, address FROM assets WHERE kind='token'"
                               " AND address IS NOT NULL AND group_id IS NOT NULL").fetchall():
            tok_pairs9.setdefault(r2["group_id"], []).append((r2["chain"], r2["address"]))
        gid_pairs = {}
        for gid in price_groups:
            pairs = list(tok_pairs9.get(gid) or ())
            if pairs:
                gid_pairs[gid] = pairs
        self.spot.want_tokens([p for gid, ps in gid_pairs.items() if not (G.get(gid) or {}).get("is_stable") for p in ps])
        self._ph("signer·cards")
        _bs9.update((k9, v9) for k9, v9 in locals().items() if k9 != "_bs9")
        if "_cg9" not in locals():
            _bs9.pop("_cg9", None)
        if "e9" not in locals():
            _bs9.pop("e9", None)
