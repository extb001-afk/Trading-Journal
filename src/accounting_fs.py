from __future__ import annotations

import bisect
import logging
import math
from decimal import Decimal
from decimal import InvalidOperation

import acct_norm
import calcguard
import logs
import histcurve
import rawtx_cache
import spamguard
from view_common import DAYCLOSE_ON
from view_common import EPS
from view_common import EX_CANDLE_SYMS
from view_common import CHAIN_NAME
from view_common import STABLE_GROUPS
from view_fspin import FS_CAP_X
from view_fspin import FS_EX
from view_misc import _fx_candle_near
from view_txkey import _txk

log = logging.getLogger('tj-web')


class FirstSeen:

    def __init__(fsx, px, *, rows, be_until, fs_pkey, fsin):
        fsx.px = px
        fsx.sb = px.sb
        fsx.conn = fsin.conn
        fsx.fs_aux = fsin.fs_aux
        fsx.rows = rows
        fsx.fs_kit = fsin.fs_kit
        fsx.fs_spec9 = fsin.fs_spec
        fsx.fs_floor9 = fsin.fs_floor
        fsx.fs_lo9 = fsin.fs_lo
        fsx.fs_memo = fsin.fs_memo
        fsx.fs_need = fsin.fs_need
        fsx.fxb = px.ctx.fxb
        fsx.now = px.ctx.now
        fsx.fs_sales = fsin.fs_sales
        fsx.ret_kit = fsin.ret_kit
        fsx.ret_pool = fsin.ret_pool
        fsx.be_until = be_until
        fsx.fs_pin = fsin.fs_pin
        fsx.fs_pin_new = fsin.fs_pin_new
        fsx.fs_pref = fsin.fs_pref
        fsx.fx_wd = fsin.fx_wd
        fsx.fs_okc = fsin.fs_okc
        fsx.fs_pkey = fs_pkey
        fsx.cb = px.cb
        fsx.ub_wd_tx = set()

    def fs_hold(fsx, g9, why9, q9):
        if q9 > EPS:
            h9 = g9.setdefault("_fsh", {})
            h9[why9] = h9.get(why9, Decimal(0)) + q9
            fsx.px.unx.fs_sum["hold"][why9] = fsx.px.unx.fs_sum["hold"].get(why9, 0) + 1

    def fs_sale_idx(fsx, gid9):
        sl9 = fsx.fs_aux.get("sale")
        if sl9 is None:
            acc9 = {}
            for r7 in fsx.rows:
                if r7["leg_kind"] != "disp" or r7["cost_usd"] is None or r7["event"] not in ("SWAP", "EX_SELL", "EXF_SELL"):
                    continue
                q7 = -fsx.sb._norm(r7)
                if q7 <= EPS:
                    continue
                try:
                    u7 = float(Decimal(r7["cost_usd"]) / q7)
                except (InvalidOperation, ArithmeticError, TypeError, ValueError):
                    continue
                if u7 > 0 and math.isfinite(u7):
                    acc9.setdefault(r7["group_id"] or -r7["asset_id"], []).append((int(r7["event_ts"]), u7))
            sl9 = fsx.fs_aux["sale"] = {}
            for g7, l7 in acc9.items():
                l7.sort()
                mx7, suf7 = 0.0, [0.0] * len(l7)
                for i7 in range(len(l7) - 1, -1, -1):
                    mx7 = max(mx7, l7[i7][1])
                    suf7[i7] = mx7
                sl9[g7] = ([t7 for t7, _u7 in l7], [u7 for _t7, u7 in l7], suf7)
        return sl9.get(gid9)

    def fs_sameday(fsx, g9, ts9):
        s9 = fsx.fs_sale_idx(g9["gid"])
        if not s9:
            return None
        i9 = bisect.bisect_left(s9[0], int(ts9))
        if i9 < len(s9[0]) and acct_norm.iso_day(s9[0][i9]) == acct_norm.iso_day(ts9):
            return s9[1][i9]
        return None

    def fs_senders(fsx, chain9, txh9):
        if "from" not in fsx.ret_kit:
            dests9 = sorted({d9 for p9 in fsx.ret_pool.values() for d9 in p9})
            frm9 = {}
            try:
                for d9, ks9 in fsx.sb._inflow_senders(fsx.conn, dests9).items():
                    for k9 in ks9:
                        frm9.setdefault((k9[0], k9[1]), set()).add(d9)
            except Exception as e9:   # noqa: BLE001 [optional]
                calcguard.swallowed("view_b_replay:ReplayMixin._build_replay.fs_senders[d9]", e9)
                log.warning("돌아온 코인 발신자 색인 실패: %s", logs.safe_err(e9)[:160])
            fsx.ret_kit["from"] = frm9
            fsx.ret_kit["snd"] = {}
        k9 = (chain9, txh9)
        if k9 in fsx.ret_kit["from"]:
            return fsx.ret_kit["from"][k9]
        if k9 in fsx.ret_kit["snd"]:
            return fsx.ret_kit["snd"][k9]
        out9 = None
        try:
            inf9 = (fsx.sb._rtxc().infl or {}).get(k9)
            if inf9:
                out9 = set(inf9)
            else:
                sn9 = rawtx_cache.RawTxCache._big_shape(fsx.conn, chain9, txh9)
                if isinstance(sn9, dict):
                    mine9 = rawtx_cache.mine_wallets(fsx.sb.cfg)
                    if chain9 == "sol" or sn9.get("kind") == "sol_tx":
                        out9 = {a7 for a7 in (sn9.get("counterparties") or []) if isinstance(a7, str) and a7 not in mine9} or None
                    else:
                        tx7 = sn9.get("tx") if isinstance(sn9.get("tx"), dict) else {}
                        legs7 = [t7 for k7 in ("token_transfers", "internal") if isinstance(sn9.get(k7), list) for t7 in sn9[k7] if isinstance(t7, dict)]
                        s7 = {rawtx_cache._ad(t7.get("from")) for t7 in legs7 if rawtx_cache._ad(t7.get("to")) in mine9}
                        f7 = rawtx_cache._ad(tx7.get("from"))
                        if rawtx_cache._ad(tx7.get("to")) in mine9 and f7:
                            try:
                                if int(tx7.get("value") or 0) > 0:
                                    s7.add(f7)
                            except (TypeError, ValueError):
                                pass
                        out9 = {a7 for a7 in s7 if a7 and a7 not in mine9} or None
        except Exception as e9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_b_replay:ReplayMixin._build_replay.fs_senders[inf9]", e9)
            log.warning("돌아온 코인 발신자 판정 실패(%s): %s", chain9, logs.safe_err(e9)[:120])
            out9 = None
        fsx.ret_kit["snd"][k9] = out9
        return out9

    def fs_spec(fsx, g9):
        gid9 = g9["gid"]
        if gid9 in fsx.fs_spec9:
            return fsx.fs_spec9[gid9]
        if not fsx.fs_kit:
            ex9, pr9 = {}, {}
            for r7 in fsx.conn.execute("SELECT group_id, address FROM assets WHERE kind='exchange_currency' AND group_id IS NOT NULL"):
                ad7 = str(r7["address"] or "")
                if ":" in ad7:
                    ex9[r7["group_id"]] = ad7.split(":", 1)[0]
            for r7 in fsx.conn.execute("SELECT group_id, chain, address FROM assets WHERE kind='token' AND address IS NOT NULL AND group_id IS NOT NULL"):
                pr9.setdefault(r7["group_id"], []).append((r7["chain"], r7["address"]))
            ov9 = {}
            for k7, v7 in (fsx.sb.cfg.get("price_overrides") or {}).items():
                if isinstance(k7, str) and ":" in k7:
                    c7, a7 = k7.split(":", 1)
                    r7 = fsx.conn.execute("SELECT group_id FROM assets WHERE chain=? AND address=?", (c7, a7 if c7 == "sol" else a7.lower())).fetchone()
                    if r7 and r7["group_id"]:
                        ov9[r7["group_id"]] = v7
            fsx.fs_kit.update(ex=ex9, pairs=pr9, ov=ov9, nat={r7[0] for r7 in fsx.conn.execute(
                "SELECT DISTINCT group_id FROM assets WHERE kind='native' AND group_id IS NOT NULL")})
        sym9 = str(g9.get("sym") or "")
        m9 = spamguard.major_of(sym9)
        prs9 = fsx.fs_kit["pairs"].get(gid9) or []
        ca9, maj9 = bool(prs9), False
        if (gid9 in fsx.fs_kit["nat"] and prs9 and m9 and m9 == sym9.upper() and m9 not in STABLE_GROUPS
                and all(spamguard.is_genuine(c9, a9) for c9, a9 in prs9)):
            ca9, maj9 = False, True
        if gid9 in fsx.fs_kit["ex"] and not g9.get("is_stable") and not g9.get("is_fiat") and (
                sym9.upper() in EX_CANDLE_SYMS or (m9 and m9 == sym9.upper() and "USD" not in m9 and m9 != "DAI")):
            maj9 = True
        try:
            sp9 = histcurve.spec_of(histcurve.group_desc(gid9, g9, {gid9} if ca9 else set(), fsx.fs_kit["ex"], {gid9} if maj9 else set(),
                                                         fsx.fs_kit["ov"], fsx.fs_kit["pairs"], STABLE_GROUPS))
        except Exception as _cg9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_b_replay:ReplayMixin._build_replay.fs_spec", _cg9)
            sp9 = None
        fsx.fs_spec9[gid9] = sp9
        return sp9

    def fs_px(fsx, g9, ts9):
        sp9 = fsx.fs_spec(g9)
        if not sp9 or sp9 in ("stable", "ov"):
            return None, "nospec"
        if sp9.startswith("sym:"):
            p9 = _fx_candle_near(fsx.fxb, sp9[4:], ts9, 3600)
            if p9:
                return p9, "minute"
        if not DAYCLOSE_ON:
            return None, "off"
        iso9 = acct_norm.iso_day(ts9)
        k9 = (sp9, iso9)
        if k9 not in fsx.fs_memo:
            try:
                fsx.fs_memo[k9] = histcurve.DAYCLOSE.lookup(sp9, iso9, fsx.now, 0.0, ask=fsx.fs_lo9 <= iso9)
            except Exception as _cg9:   # noqa: BLE001 [fallback]
                calcguard.swallowed("view_b_replay:ReplayMixin._build_replay.fs_px", _cg9)
                fsx.fs_memo[k9] = (None, "err")
        p9, st9 = fsx.fs_memo[k9]
        if not (p9 and p9 > 0) and fsx.fs_floor9 <= iso9 < fsx.fs_lo9 and st9 in ("pending", "retry"):
            n9 = fsx.fs_need.setdefault(k9, [g9["gid"], Decimal(0)])
            n9[1] = max(n9[1], g9["qty_unknown"])
        return (float(p9), "close") if p9 and p9 > 0 else (None, st9)

    def fs_flow(fsx, fl9, pend9):
        ts9, take, unit_d, badd9 = pend9
        c9 = take * unit_d
        fl9["cost"] += c9
        fl9["cost_krw"] += fsx.px.kpx.krw_of(c9, ts9)
        fl9["bought"] += badd9
        fl9["fs_c"] = fl9.get("fs_c", Decimal(0)) + c9
        fl9["fs_q"] = fl9.get("fs_q", Decimal(0)) + take

    def fs_why(fsx, g9, why9, kind9, q9):
        if q9 > EPS:
            w9 = fsx.px.unx.fs_sum["ur"].setdefault(str(g9["gid"]), {})
            k9 = f"{why9}|{kind9}"
            w9[k9] = w9.get(k9, 0.0) + float(q9)

    def fs_mark(fsx, g9, fl9, tax9, cmp9, fk9, pk9, cc9, rate9, dk9):
        if g9["is_stable"]:
            c9 = fsx.px.kpx.fs_last[0]
            if c9 <= 0 or cc9 <= 0 or c9 < cc9 * Decimal("0.01"):
                return False
            tax9["ex"] = str(tax9.get("ex") or "") + FS_EX
            fsx.px.unx.fs_sum["rows"] += 1
            fsx.px.unx.fs_sum["rows_st"] = fsx.px.unx.fs_sum.get("rows_st", 0) + 1
            return True
        if not cmp9 or cc9 <= 0 or fk9 <= 0:
            return False
        q9 = c9 = 0.0
        for _e9, k9, qq9, cq9 in cmp9.get("o") or ():
            if isinstance(k9, tuple) and k9 and k9[0] == "fs":
                q9 += float(qq9)
                c9 += float(cq9)
        if q9 <= 0:
            return False
        fsx.fs_sales.append((fl9, tax9, min(1.0, q9 / float(fk9)), c9, rate9, dk9))
        fsx.px.unx.fs_sum["c_sold"] = fsx.px.unx.fs_sum.get("c_sold", 0.0) + c9
        if c9 >= 0.01 * float(cc9):
            tax9["ex"] = str(tax9.get("ex") or "") + FS_EX
            fsx.px.unx.fs_sum["rows"] += 1
            return True
        return False

    def fs_ok_ca(fsx, g9):
        gid9 = g9["gid"]
        v9 = fsx.fs_okc.get(gid9)
        if v9 is not None:
            return v9
        if "exg" not in fsx.fs_aux:
            fsx.fs_aux["exg"] = {r7["group_id"] or -r7["asset_id"] for r7 in fsx.rows
                             if (r7["event"] == "TRANSFER_OUT_EX" and r7["leg_kind"] == "move_out")
                             or (r7["leg_kind"] == "acq" and r7["event"] in ("TRANSFER_IN", "PROGRAM_IN")
                                 and (_txk(r7["source_id"] or "") in fsx.fx_wd or _txk(r7["source_id"] or "") in fsx.ub_wd_tx))}
            fsx.fs_aux["conf"] = {r7[0] for r7 in fsx.conn.execute(
                "SELECT DISTINCT group_id FROM assets WHERE confirmed=1 AND kind='token' AND group_id IS NOT NULL")}
        prs9 = fsx.fs_kit.get("pairs", {}).get(gid9) or []
        v9 = bool(gid9 in fsx.fs_aux["exg"] or gid9 in fsx.fs_aux["conf"]
                  or any(spamguard.is_genuine(c9, a9) for c9, a9 in prs9)
                  or any(float(fsx.sb.spot.dex_res.get(f"{c9}:{a9 if c9 == 'sol' else str(a9).lower()}") or 0) >= float(fsx.sb.spot.min_reserve_usd)
                         for c9, a9 in prs9))
        fsx.fs_okc[gid9] = v9
        return v9

    def fs_ret(fsx, g9, ts9, q9, chain9, txh9, flow9):
        pools9 = fsx.ret_pool.get(g9["gid"])
        live9 = {d9: e9 for d9, e9 in (pools9 or {}).items() if e9["left"] > EPS}
        if not live9:
            return None
        snd9 = fsx.fs_senders(chain9, txh9)
        if snd9 is None:
            fsx.cb.add_unknown(g9, q9)
            fsx.px.unx.note_unk(g9, ts9, f"{CHAIN_NAME.get(chain9, chain9)} 외부 유입(원가 없음 · 보냈던 코인이 돌아온 것인지 확인 못 함 — 최초 인식 시가 보류)",
                     q9, txh9, chain9=chain9, fs9=0)
            fsx.fs_hold(g9, "ret", q9)
            return " · 보냈던 코인인지 확인 못 함(최초 인식 시가 보류)"
        hit9 = [d9 for d9 in sorted(live9) if d9 in snd9]
        if not hit9:
            return None
        rem9 = q9
        inh9 = kn9 = un9 = kr9 = Decimal(0)
        for d9 in hit9:
            e9 = live9[d9]
            tk9 = min(rem9, e9["left"])
            if tk9 <= EPS:
                continue
            sc9 = min(Decimal(1), tk9 / e9["qty"]) if e9["qty"] > 0 else Decimal(1)
            c9r, k9r, u9r, w9r = e9["cost"] * sc9, e9["known"] * sc9, e9["unknown"] * sc9, e9["krw"] * sc9
            inh9 += c9r
            kn9 += k9r
            un9 += u9r
            kr9 += w9r
            fsx.px.cpx.cp_add_map(g9, e9.get("_cmp"), float(sc9))
            if sc9 >= 1:
                for k7 in ("qty", "left", "cost", "known", "unknown", "krw"):
                    e9[k7] = Decimal(0)
                e9["_cmp"] = {}
            else:
                e9["qty"] -= tk9
                e9["left"] = e9["qty"]
                e9["cost"] -= c9r
                e9["known"] -= k9r
                e9["unknown"] -= u9r
                e9["krw"] -= w9r
                if e9.get("_cmp"):
                    e9["_cmp"] = {k7: [v7[0] * (1 - float(sc9)), v7[1] * (1 - float(sc9))] for k7, v7 in e9["_cmp"].items()}
            rem9 -= tk9
            if rem9 <= EPS:
                break
        took9 = q9 - rem9
        fsx.cb.add_known(g9, kn9)
        fsx.cb.add_cost(g9, inh9)
        fsx.cb.add_unknown(g9, un9 + rem9)
        flow9["bought"] += took9
        flow9["cost"] += inh9
        flow9["cost_krw"] += kr9
        if un9 + rem9 > EPS:
            fsx.px.unx.note_unk(g9, ts9, f"{CHAIN_NAME.get(chain9, chain9)} 외부 유입 · 보냈던 주소에서 돌아옴(보낼 때부터 원가 미상 몫 · 보낸 것보다 많은 몫)",
                     un9 + rem9, txh9, chain9=chain9, unc9=rem9, fs9=rem9)
        fsx.px.unx.fs_sum["ret_n"] += 1
        fsx.px.unx.fs_sum["ret_q"] += float(took9)
        return f" · 보냈던 주소에서 돌아옴 · 원가 승계 (${float(inh9):,.2f})"

    def fs_conv(fsx, g9, ts9, fq9, dq9, unc9, kind9=""):
        take = min(fq9, g9["qty_unknown"])
        if take <= EPS:
            return None
        if g9.get("_wc"):
            fsx.px.unx.fs_sum["wc_skip"] = fsx.px.unx.fs_sum.get("wc_skip", 0) + 1
            fsx.fs_why(g9, "wc", kind9, take)
            return None
        u9 = fsx.be_until(g9["gid"])
        if u9 is not None and ts9 <= u9:
            fsx.px.unx.fs_sum["be_skip"] += 1
            fsx.fs_why(g9, "be", kind9, take)
            return None
        sp9 = str(fsx.fs_spec(g9) or "")
        pk9 = fsx.fs_pkey(g9)
        pin9 = fsx.fs_pin.get(pk9) if pk9 else None
        if pin9 is not None:
            px9, src9 = pin9[0], pin9[1] or "pin"
            fsx.px.unx.fs_sum["pin"] += 1
        else:
            px9 = src9 = None
            sd9 = fsx.fs_sameday(g9, ts9)
            if sd9 is not None and sp9.startswith("sym:"):
                pm9 = _fx_candle_near(fsx.fxb, sp9[4:], ts9, 3600)
                if pm9:
                    px9, src9 = pm9, "minute"
            if px9 is None and sd9 is not None:
                px9, src9 = sd9, "sameday"
            if px9 is None and sp9.startswith("ca:") and not fsx.fs_ok_ca(g9):
                px9, src9 = None, "unverified"
            elif px9 is None:
                px9, src9 = fsx.fs_px(g9, ts9)
        if px9 and sp9.startswith("ca:") and src9 != "sameday":
            s9c = fsx.fs_sale_idx(g9["gid"])
            i9c = bisect.bisect_left(s9c[0], int(ts9)) if s9c else 0
            if s9c and i9c < len(s9c[0]) and float(px9) > FS_CAP_X * s9c[2][i9c]:
                px9, src9 = None, "cap"
        if not px9:
            fsx.fs_why(g9, f"miss-{src9}-{'old' if acct_norm.iso_day(ts9) < fsx.fs_lo9 else 'new'}-{fsx.fs_spec(g9) or '-'}", kind9, take)
            fsx.px.unx.fs_sum["miss"] += 1
            fsx.px.unx.fs_sum["miss_q"][str(src9)] = fsx.px.unx.fs_sum["miss_q"].get(str(src9), 0) + 1
            mk9 = f"{kind9}|{fsx.px.fbx.kst_fmt(ts9, '%Y-%m')}|{src9}"
            fsx.px.unx.fs_sum["mk"][mk9] = fsx.px.unx.fs_sum["mk"].get(mk9, 0) + 1
            fsx.fs_hold(g9, {"pending": "wait", "retry": "wait", "wait": "wait", "unverified": "unv", "cap": "cap"}.get(str(src9), "none"), take)
            return None
        if pin9 is None and pk9:
            fsx.fs_pin_new[pk9] = [float(px9), str(src9), acct_norm.iso_day(ts9), int(fsx.now)]
        if src9 == "sameday":
            fsx.px.unx.fs_sum["sd"] += 1
        unit_d = Decimal(str(px9))
        fsx.cb.sub_unknown(g9, take)
        fsx.cb.add_known(g9, take)
        fsx.cb.add_cost(g9, take * unit_d)
        fsx.px.cpx.cp_add(g9, ("fs", g9["gid"]), take, take * unit_d)
        unc_d = dq9 if unc9 is None else max(Decimal(0), min(dq9, Decimal(str(unc9))))
        pend9 = (ts9, take, unit_d, take * unc_d / dq9 if dq9 > 0 else Decimal(0))
        if g9.get("cur") is not None:
            fsx.fs_flow(g9["cur"], pend9)
        else:
            g9.setdefault("_fs_pend", []).append(pend9)
        fsx.px.unx.fs_sum["n"] += 1
        fsx.px.unx.fs_sum["q"] += take
        fsx.px.unx.fs_sum["usd"] += take * unit_d
        fsx.px.unx.fs_sum["src"][src9] = fsx.px.unx.fs_sum["src"].get(src9, 0) + 1
        b9 = fsx.px.unx.fs_sum["bk"].setdefault(f"{kind9}|{fsx.px.fbx.kst_fmt(ts9, '%Y-%m')}", [0, 0.0])
        b9[0] += 1
        b9[1] += float(take * unit_d)
        gg9 = fsx.px.unx.fs_sum["g"].setdefault(str(g9["gid"]), [g9["sym"], 0, 0.0])
        gg9[1] += 1
        gg9[2] += float(take * unit_d)
        return take, px9

    def fs_st(fsx, g9, ts9, q9, ch9):
        if not fsx.fs_pref or q9 <= EPS:
            return
        rt9, src9 = fsx.fxb.rate_src(ts9)
        if src9 not in ("minute", "close", "near36h") or not rt9:
            fsx.px.unx.fs_sum["st_miss"] += 1
            return
        fl9 = fsx.px.flow_of(g9, ts9, ch9)
        fl9["cost"] += q9
        fl9["cost_krw"] += q9 * Decimal(str(rt9))
        fl9["fs_kc"] = fl9.get("fs_kc", Decimal(0)) + q9
        fsx.px.unx.fs_sum["st_n"] += 1
        fsx.px.unx.fs_sum["st_usd"] += q9

    def fs_rec(fsx):
        return fsx.px.kpx.fs_last[0] if fsx.px.kpx.krw_last[0] is not None else Decimal(0)
