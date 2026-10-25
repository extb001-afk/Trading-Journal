from __future__ import annotations
import acct_norm
import attfreeze
import buychart
import candles
import paths
import day_memo
import db as dbm
import json
import re
import sellchart
import spamguard
import threading
import time
from datetime import datetime
from datetime import timedelta
from timeutil import KST
from view_evals import DAY_MEMOS
from view_fut import FUT_FEE_SYM
from view_fut import PERP_NAMES
from view_fut import _fut_by_date_ex
from view_fut import fut_sym
from view_tax import _tax_fee_merge
import calcguard  # noqa: E402
try:
    import fut_rcpt
except Exception as e_cg:   # noqa: BLE001 [optional]
    calcguard.swallowed("view_detail:<module>[fut_rcpt]", e_cg)
    fut_rcpt = None
import logging

log = logging.getLogger('tj-web')


class DetailApiMixin:

    @staticmethod
    def _krw_rows(idx, d_from, d_to):
        out = []
        for d, lst in (idx.get("krw") or {}).items():
            if d_from <= d <= d_to:
                for ts, e in lst:
                    o = dict(e)
                    o["ts"], o["iso"], o["kind"] = ts, d, "krw"
                    out.append(o)
        out.sort(key=lambda o: -o["ts"])
        return out

    def day_events(self, d_from, d_to, limit=None, offset=0):
        idx = getattr(self, "_day_idx", None)
        if not idx:
            return None
        if limit is not None:
            return self._day_events_page(idx, d_from, d_to, int(limit), int(offset or 0))
        ix = idx["ix"]
        days = sorted(d for d in ix if d_from <= d <= d_to)
        vis, hid, per = [], [], {}
        for d in days:
            a = {"n": 0, "b": 0, "s": 0, "dep": 0, "h": 0}
            for ts, kind, e, meta in ix[d]:
                o = {k: v for k, v in e.items() if not k.startswith("_")}
                o["ts"], o["iso"], o["kind"] = ts, d, kind
                if meta is not None:
                    o["pkey"], o["sym"], o["chain"] = meta
                (hid if kind == "hidden" else vis).append(o)
            per[d] = {"realized": round(float(idx["rbd"].get(d) or 0), 2),
                      "realizedFut": round(float(idx["fut"].get(d) or 0), 2)}
        vis.sort(key=lambda o: -o["ts"])
        hid.sort(key=lambda o: -o["ts"])
        try:
            spamguard.annotate(vis)
            spamguard.annotate(hid)
        except Exception as e9:  # noqa: BLE001 [optional]
            calcguard.swallowed("view_detail:DetailApiMixin.day_events", e9)
            log.warning("심볼 정리 실패(무시): %s", e9)
        counts = {}
        for o in vis:
            counts[o.get("k") or "?"] = counts.get(o.get("k") or "?", 0) + 1
        return {"ok": True, "from": d_from, "to": d_to, "builtAt": idx["builtAt"], "n": len(vis),
                "counts": counts, "days": per, "events": vis, "hidden": hid,
                "conv": self._conv_rows(idx, d_from, d_to),
                "krw": type(self)._krw_rows(idx, d_from, d_to)}

    def _day_events_page(self, idx, d_from, d_to, limit, offset):
        ix = idx["ix"]
        limit = max(1, min(self.DAY_EV_LIMIT_MAX, limit))
        offset = max(0, offset)
        days = sorted((d for d in ix if d_from <= d <= d_to), reverse=True)
        per, counts, n_vis, n_hid, hid_kinds = {}, {}, 0, 0, {}
        for d in days:
            for ts, kind, e, meta in ix[d]:
                if kind == "hidden":
                    n_hid += 1
                    hk = str(e.get("hideKind") or "?")
                    hid_kinds[hk] = hid_kinds.get(hk, 0) + 1
                else:
                    n_vis += 1
                    k9 = e.get("k") or "?"
                    counts[k9] = counts.get(k9, 0) + 1
            per[d] = {"realized": round(float(idx["rbd"].get(d) or 0), 2),
                      "realizedFut": round(float(idx["fut"].get(d) or 0), 2)}
        vis, hid = [], []
        need_v, need_h = offset + limit, (limit if offset == 0 else 0)
        for d in days:
            if len(vis) >= need_v and len(hid) >= need_h:
                break
            dv, dh = [], []
            for ts, kind, e, meta in ix[d]:
                if kind == "hidden" and len(hid) >= need_h:
                    continue
                if kind != "hidden" and len(vis) >= need_v:
                    continue
                o = {k: v for k, v in e.items() if not k.startswith("_")}
                o["ts"], o["iso"], o["kind"] = ts, d, kind
                if meta is not None:
                    o["pkey"], o["sym"], o["chain"] = meta
                (dh if kind == "hidden" else dv).append(o)
            dv.sort(key=lambda o: -o["ts"])
            dh.sort(key=lambda o: -o["ts"])
            vis.extend(dv)
            hid.extend(dh)
        full = vis
        vis = vis[offset:offset + limit]
        hid = hid[:need_h]
        more = offset + len(vis) < n_vis
        hi9 = full[offset - 1]["ts"] if 0 < offset <= len(full) else None
        lo9 = vis[-1]["ts"] if (more and vis) else None

        def keep9(o):
            if offset > 0 and hi9 is None:
                return False
            return (hi9 is None or o["ts"] < hi9) and (lo9 is None or o["ts"] >= lo9)
        try:
            spamguard.annotate(vis)
            spamguard.annotate(hid)
        except Exception as e9:  # noqa: BLE001 [optional]
            calcguard.swallowed("view_detail:DetailApiMixin._day_events_page", e9)
            log.warning("심볼 정리 실패(무시): %s", e9)
        return {"ok": True, "from": d_from, "to": d_to, "builtAt": idx["builtAt"], "n": n_vis, "counts": counts, "days": per,
                "events": vis, "hidden": hid, "nHidden": n_hid, "hiddenKinds": hid_kinds,
                "offset": offset, "limit": limit, "more": more,
                "conv": [o for o in self._conv_rows(idx, d_from, d_to) if keep9(o)],
                "krw": [o for o in type(self)._krw_rows(idx, d_from, d_to) if keep9(o)]}

    def tax_rows(self, ym, sym, offset=0):
        idx = getattr(self, "_day_idx", None)
        if not idx or idx.get("tax") is None:
            return None
        today9 = idx.get("taxToday")
        if sym and (sym.endswith(" 무기한") or sym == FUT_FEE_SYM):
            return self._tax_rows_fut(idx, ym, sym, offset)
        rows = [r for r in idx["tax"] if (not sym or (r.get("sym") or "?") == sym) and acct_norm.month_of(r.get("sold"), today9) == ym]
        rows = _tax_fee_merge(rows)
        rows.sort(key=lambda r: str(r.get("sold") or ""), reverse=True)
        off9 = max(0, int(offset or 0))
        yms9 = idx.get("_taxYms")
        if yms9 is None:
            yms9 = idx["_taxYms"] = sorted({m9 for m9 in (acct_norm.month_of(r.get("sold"), today9) for r in idx["tax"] if not r.get("fut")) if m9})
        return {"ok": True, "ym": ym, "sym": sym, "builtAt": idx["builtAt"], "total": len(rows), "offset": off9, "yms": yms9,
                "rows": [self._tax_row_out(r) for r in rows[off9:off9 + self.TAX_ROWS_MAX]]}

    def _tax_rows_fut(self, idx, ym, sym, offset=0):
        fd = idx.get("futDetail") or {}
        out = []
        if sym == FUT_FEE_SYM:
            for x9 in fd.get("fee") or []:
                dt9 = datetime.fromtimestamp(x9["_ts"] / 1000, KST)
                if dt9.strftime("%Y-%m") != ym:
                    continue
                out.append({"sold": dt9.strftime("%Y-%m-%d"), "t": dt9.strftime("%H:%M"), "sym": sym, "ticker": str(x9["sym"]) + " · 선물",
                            "ex": str(x9["ex"] or "선물") + (" 펀딩" if x9["kind"] == "FUNDING" else " 수수료"),
                            "qty": 0, "acq": 0, "disp": 0, "fee": round(-x9["amt"], 4), "fut": True, "futFee": True})
        else:
            for x9 in fd.get("rows") or []:
                dt9 = datetime.fromtimestamp(x9["_ts"] / 1000, KST)
                if dt9.strftime("%Y-%m") != ym or fut_sym(x9.get("sym")) != sym:
                    continue
                p9 = float(x9.get("pnl") or 0)
                out.append({"sold": dt9.strftime("%Y-%m-%d"), "t": dt9.strftime("%H:%M"), "sym": sym, "ticker": str(x9.get("sym")) + " · 선물",
                            "ex": x9.get("ex"), "qty": 0, "acq": -p9 if p9 < 0 else 0, "disp": p9 if p9 > 0 else 0, "fee": 0, "fut": True,
                            **({"liq": True} if x9.get("liq") else {})})
        off9 = max(0, int(offset or 0))
        return {"ok": True, "ym": ym, "sym": sym, "builtAt": idx["builtAt"], "total": len(out), "offset": off9, "fut": True,
                "rows": out[off9:off9 + self.TAX_ROWS_MAX]}

    @staticmethod
    def _tax_row_out(r):
        o = {k: v for k, v in r.items() if not k.startswith("_")}
        for k9, x9 in (("_acq", "xa"), ("_disp", "xd"), ("_fee", "xf")):
            v9 = r.get(k9)
            if isinstance(v9, (int, float)) and v9 == v9 and abs(v9) != float("inf"):
                o[x9] = v9
        return o

    def receipt(self, iso, sym):
        idx = getattr(self, "_day_idx", None)
        if not idx or idx.get("pos") is None:
            return None
        import review_daily as rd
        raw = []
        for ts, kind, e, meta in (idx["ix"].get(iso) or ()):
            if kind == "hidden":
                continue
            o = {k: v for k, v in e.items() if not k.startswith("_")}
            o["ts"], o["kind"] = ts, kind
            if meta is not None:
                o["pkey"], o["sym"], o["chain"] = meta
            raw.append(o)
        def _norm_px(raw9):
            n9 = rd._norm_events(raw9, iso)
            for o9, i9 in zip(n9, sorted(range(len(raw9)), key=lambda i: int(raw9[i].get("ts") or 0))):
                try:
                    un9 = float(raw9[i9].get("un")) if raw9[i9].get("un") not in (None, "") else None
                except (TypeError, ValueError):
                    un9 = None
                if un9 and un9 > 0 and o9.get("q"):
                    o9["_px"] = un9
                    inf9 = float(o9["q"]) * un9
                    if o9.get("usd") is not None and abs(inf9 - float(o9["usd"])) <= 0.005 + 1e-9:
                        o9["_usd"] = inf9
            return n9
        norm = _norm_px(raw)
        pos = [p for p in idx["pos"] if p.get("kind") != "gas"]
        syms9 = {o["sym"] for o in norm if not o["lp"]} | {p.get("sym") for p in pos if (p.get("realizedByDay") or {}).get(iso)}
        canon = rd._canon_map(syms9)
        want = canon.get(sym, sym)
        raw_syms = {s for s in (syms9 | {sym}) if s and canon.get(s, s) == want}
        for o in norm:
            if o["sym"] in canon:
                o["sym_raw"], o["sym"] = o["sym"], canon[o["sym"]]
        rd._mark_dca(norm)
        ev = [o for o in norm if not o["lp"] and o["sym"] == want]
        st_raw = []
        for ts, e, meta in ((idx.get("stab") or {}).get(iso) or ()):
            if meta[1] not in raw_syms:
                continue
            o = {k: v for k, v in e.items() if not k.startswith("_")}
            o["ts"], o["kind"] = ts, "stab"
            o["pkey"], o["sym"], o["chain"] = meta
            if e.get("_conv"):
                o["conv"] = str(e["_conv"])
            st_raw.append(o)
        if st_raw:
            st_norm = _norm_px(st_raw)
            for o9, i9 in zip(st_norm, sorted(range(len(st_raw)), key=lambda i: int(st_raw[i].get("ts") or 0))):
                if st_raw[i9].get("conv"):
                    o9["conv"] = st_raw[i9]["conv"]
            for o in st_norm:
                if o["sym"] != want:
                    o["sym_raw"], o["sym"] = o["sym"], want
            rd._mark_dca(st_norm)
            ev = sorted(ev + st_norm, key=lambda o: o["ts"])
        cards = [p for p in pos if p.get("sym") in raw_syms and (p.get("realizedByDay") or {}).get(iso)]
        r_usd = sum(float((p.get("realizedByDay") or {}).get(iso) or 0) for p in cards)
        rk = [(p.get("realizedKrwByDay") or {}).get(iso) for p in cards]
        r_krw = sum(float(x) for x in rk) if cards and all(x is not None for x in rk) else None
        if not ev and not cards:
            return {"ok": True, "empty": True, "date": iso, "sym": sym, "builtAt": idx["builtAt"]}
        sells = [o for o in ev if o["side"] == "sell"]
        buys = [o for o in ev if o["side"] == "buy"]
        deps = [o for o in ev if o["k"] == "입금 확인"]
        tx9 = [r for r in (idx.get("tax") or ()) if r.get("sold") == iso and (r.get("sym") or "?") in raw_syms]
        disp = sum(float(r.get("_disp", r.get("disp")) or 0) for r in tx9)
        disp_krw = sum(float(r.get("_disp", r.get("disp")) or 0) * float(r.get("rate") or 0) for r in tx9) if tx9 and all(r.get("rate") for r in tx9) else None
        tpnl = sum(float(r.get("_disp", r.get("disp")) or 0) - float(r.get("_acq", r.get("acq")) or 0) - float(r.get("fee") or 0) for r in tx9)
        acq_krw = sum(float(r.get("_akr", r.get("akr")) if r.get("_akr", r.get("akr")) is not None
                            else float(r.get("_acq", r.get("acq")) or 0) * float(r.get("rate") or 0)) for r in tx9) if disp_krw is not None else None
        fee_krw = sum(float(r.get("fee") or 0) * float(r.get("rate") or 0) for r in tx9) if disp_krw is not None else None
        pnl_krw = (disp_krw - acq_krw - fee_krw) if disp_krw is not None else None
        fb_n = sum(1 for r in tx9 if "폴백" in str(r.get("ex") or ""))
        recon = bool(tx9) and abs(tpnl - r_usd) <= max(1.0, 0.01 * abs(r_usd))
        rate_by_q = {}
        for r in tx9:
            if r.get("rate"):
                rate_by_q.setdefault(round(float(r.get("qty") or 0), 4), []).append(float(r["rate"]))
        usd_of = lambda o: o["_usd"] if o.get("_usd") is not None else (o["usd"] or 0)
        sq = sum(o["q"] or 0 for o in sells)
        su = sum(usd_of(o) for o in sells)
        uq = sum(rd._unknown_of(o)[0] for o in sells)
        is_pay = lambda o: "스왑 지불" in o["d"] or "대금 지불" in o["d"]
        pays = [o for o in sells if is_pay(o)]
        convs = [o for o in sells if o.get("conv") and not is_pay(o)]
        fl = []
        for o in sells:
            rq = rate_by_q.get(round(float(o["q"] or 0), 4))
            u9 = usd_of(o)
            px9 = o.get("_px") or (u9 / o["q"] if o["q"] and u9 else None)
            f9 = {"ts": o["ts"], "q": rd._r(o["q"]), "usd": rd._r(u9), "px": rd._r(px9) if px9 else None,
                  "v": o["v"], "rate": rq.pop(0) if rq else None, "unk": rd._r(rd._unknown_of(o)[0]) or None}
            if is_pay(o):
                f9["pay"] = True
            elif o.get("conv"):
                f9["conv"] = o["conv"]
            fl.append(f9)
        if len(fl) > self.RECEIPT_FILLS_MAX:
            keep = sorted(range(len(fl)), key=lambda i: -(fl[i]["usd"] or 0))[:self.RECEIPT_FILLS_MAX]
            fl = [fl[i] for i in sorted(keep)]
        bk = {}
        for o in buys:
            bk[o["k"]] = bk.get(o["k"], 0) + 1
        bq = sum(o["q"] or 0 for o in buys)
        bu = sum(o["usd"] or 0 for o in buys)
        nd = [o for o in buys if not o.get("dca")]
        sn = [o for o in sells if not o.get("dca")]
        dep_same = [o for o in deps if sn and o["v"] == sn[0]["v"] and o["ts"] <= sn[0]["ts"]]
        d0 = dep_same[0] if dep_same else (deps[0] if deps else None)
        tts = {}
        if nd and (not sn or nd[0]["ts"] <= sn[-1]["ts"]):
            tts["first_buy"] = nd[0]["ts"]
        if d0:
            tts["deposit"] = d0["ts"]
        if sn:
            tts["first_sell"], tts["last_sell"] = sn[0]["ts"], sn[-1]["ts"]
        out = {"ok": True, "date": iso, "sym": want, "aliases": sorted(raw_syms - {want}), "builtAt": idx["builtAt"],
               "realized": {"usd": round(r_usd, 2), "krw": round(r_krw) if r_krw is not None else None, "cards": len(cards)},
               "sell": {"n": len(sells), "qty": rd._r(sq), "usd": rd._r(su), "vwap": rd._r(su / sq) if sq else None,
                        "pay": {"n": len(pays), "qty": rd._r(sum(o["q"] or 0 for o in pays)), "usd": rd._r(sum(usd_of(o) for o in pays))},
                        "conv": {"n": len(convs), "qty": rd._r(sum(o["q"] or 0 for o in convs)), "usd": rd._r(sum(usd_of(o) for o in convs))},
                        "costKnownPct": round(100.0 * (1 - uq / sq), 1) if sq else None,
                        "venues": sorted({o["v"] for o in sells}), "krwMarket": any(o["v"] in rd.KRW_MARKETS for o in sells)},
               "buy": {"n": len(buys), "qty": rd._r(bq), "usd": rd._r(bu), "vwap": rd._r(bu / bq) if bq else None, "kinds": bk,
                       "venues": sorted({o["v"] for o in buys})},
               "dep": {"n": len(deps), "qty": rd._r(sum(o["q"] or 0 for o in deps)),
                       "first": {"ts": d0["ts"], "q": rd._r(d0["q"]), "v": d0["v"], "carry": "원가 승계" in d0["d"]} if d0 else None},
               "tax": {"n": len(tx9), "fb": fb_n, "disp": round(disp, 2), "dispKrw": round(disp_krw) if disp_krw is not None else None,
                       "recon": recon, "diff": round(tpnl - r_usd, 2),
                       "acqKrw": round(acq_krw) if acq_krw is not None else None, "feeKrw": round(fee_krw) if fee_krw is not None else None,
                       "pnlKrw": round(pnl_krw) if pnl_krw is not None else None,
                       "fxDiffKrw": round(pnl_krw - r_krw) if (pnl_krw is not None and r_krw is not None) else None},
               "path": rd._timeline(ev), "pathTs": tts, "fills": fl, "fillsTotal": len(sells)}
        if not buys and cards:
            cr = rd._carry({"positions": pos}, raw_syms, iso, None, rd._carry_src_keys(raw, raw_syms))
            if cr:
                out["carry"] = cr
        return out

    @staticmethod
    def _dex_later(out, iso, sym, side, why, listed=True):
        if why:
            out["dexLater"] = str(why)
            out["autoEval"] = False
        if not listed:
            return
        try:
            sellchart.dex_later_mark(iso, sym, side, why)
        except Exception as _cg9:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_detail:DetailApiMixin._dex_later", _cg9)
            pass

    def _chart_cache_put(self, cache: dict, ck, out):
        while len(cache) >= self.CHART_CACHE_MAX:
            cache.pop(next(iter(cache)))
        cache[ck] = (time.time(), out)

    def _sell_rows(self, iso, raw_syms):
        idx = getattr(self, "_day_idx", None) or {}
        out = []
        for ts, kind, e, meta in ((idx.get("ix") or {}).get(iso) or ()):
            if kind != "pos" or meta is None or meta[1] not in raw_syms:
                continue
            k9, d9 = str(e.get("k") or ""), str(e.get("d") or "")
            if "매도" not in k9 or "스왑 지불" in d9 or "대금 지불" in d9 or not e.get("_pid"):
                continue
            try:
                q9 = float(str(e.get("q") or "0").replace(",", ""))
            except ValueError:
                continue
            un9 = sellchart._f(e.get("un"))
            u9 = sellchart._f(str(e.get("a") or "").replace("$", ""))
            if q9 <= 0:
                continue
            out.append((int(ts), q9, (un9 * q9) if un9 else (u9 or 0.0), un9 or ((u9 / q9) if u9 else None), int(e["_pid"])))
        return out

    def _sell_specs(self, pids):
        out, gtok = {}, {}
        if not pids:
            return out, gtok
        conn = dbm.open_db(paths.DB_PATH, readonly=True)
        try:
            rows = []
            pl = sorted(set(pids))
            for i in range(0, len(pl), 400):
                ch9 = pl[i:i + 400]
                rows += conn.execute(
                    "SELECT p.posting_id, p.source_ns, p.source_id, a.chain, a.address, a.symbol, a.group_id FROM postings p"
                    " JOIN assets a ON a.asset_id = p.asset_id WHERE p.posting_id IN (%s)" % ",".join("?" * len(ch9)), ch9).fetchall()
            groups = set()
            for r in rows:
                ns = str(r["source_ns"] or "")
                payload = snap = None
                if ":" in ns:
                    ex9, kd9 = ns.split(":", 1)
                    x9 = conn.execute("SELECT payload FROM raw_ex WHERE exchange=? AND kind=? AND uuid=? ORDER BY revision DESC LIMIT 1",
                                      (ex9, kd9, r["source_id"])).fetchone()
                    if x9:
                        try:
                            payload = json.loads(x9["payload"])
                        except ValueError:
                            payload = None
                elif r["address"]:
                    x9 = conn.execute("SELECT snapshot FROM raw_txs WHERE chain=? AND txhash=?", (ns, r["source_id"])).fetchone()
                    snap = x9["snapshot"] if x9 else None
                sp, px, cur = sellchart.spec_of(ns, payload, r["chain"], r["address"], r["symbol"], snap)
                out[int(r["posting_id"])] = (sp, px, cur, r["group_id"])
                if r["group_id"] is not None:
                    groups.add(int(r["group_id"]))
            for g9 in groups:
                toks = [(x["chain"], x["address"]) for x in conn.execute(
                    "SELECT chain, address FROM assets WHERE group_id=? AND address IS NOT NULL AND address != '' AND hidden=0", (g9,)).fetchall()
                    if x["chain"] in candles.GT_NETWORK]
                pref = {c: i for i, c in enumerate(self._DEX_CHAIN_PREF)}
                gtok[g9] = sorted(toks, key=lambda t: pref.get(t[0], 99))[:2]
        finally:
            conn.close()
        return out, gtok

    def chart_request(self, iso, sym, iv="5m", after="1h", venue=None, wait=None, side="sell", bvenue=None, bg=False):
        if getattr(self, "_day_idx", None) is None:
            return None, "ok"
        buy = side == "buy"
        bg = bool(bg) and side in ("sell", "buy")
        fn = (lambda **k9: self.receipt_chart_buy(iso, sym, iv, venue, bvenue, **k9)) if buy else \
            (lambda **k9: self.receipt_chart(iso, sym, iv, after, venue, **k9))
        if side == "fut":
            fn = lambda **k9: self.fut_chart(iso, sym, iv, venue, **k9)   # noqa: E731
        key = (iso, sym, iv, "-" if buy else after, venue or "") + (("buy", bvenue or "") if buy else ()) + (("fut",) if side == "fut" else ()) \
            + (("bg",) if bg else ())
        J, L = type(self)._CHART_JOBS, type(self)._CHART_JLOCK
        with L:
            pend9 = bg and key in J
        if not pend9:
            with candles.chart_mode("bg" if bg else "fg"):
                hit = fn(cache_only=True)
            if hit is not None:
                return (dict(hit, calls=0) if bg and isinstance(hit, dict) else hit), "ok"
        now = time.time()
        with L:
            for k9 in [k9 for k9, j9 in J.items() if j9["done"] and now - j9["t"] > 120]:
                J.pop(k9, None)
            job = J.get(key)
            if job is not None and job["done"]:
                J.pop(key, None)
                return job["res"], "ok"
            if job is None:
                if (any(not j9["done"] for j9 in J.values()) if bg else
                        sum(1 for j9 in J.values() if not j9["done"] and not j9.get("bg")) >= self.CHART_WORKERS):
                    return None, "busy"
                job = J[key] = {"ev": threading.Event(), "done": False, "res": None, "t": now, "bg": bg}

                def work(job=job):
                    try:
                        with candles.hard_deadline(time.time() + (self.CHART_BG_HARD_S if bg else self.CHART_HARD_S)), \
                                candles.chart_mode("bg" if bg else "fg"), candles.count_calls() as nc9:
                            job["res"] = fn()
                        if bg and isinstance(job["res"], dict):
                            job["res"] = dict(job["res"], calls=nc9[0])
                    except Exception as e9:   # noqa: BLE001 [boundary]
                        calcguard.swallowed("view_detail:DetailApiMixin.chart_request.work", e9)
                        log.warning("%s 차트 수집 실패(%s %s): %s", "매수" if buy else "매도", iso, sym, e9)
                        job["res"] = {"ok": False, "error": "차트를 만들지 못했어요"}
                    finally:
                        job["done"], job["t"] = True, time.time()
                        job["ev"].set()
                threading.Thread(target=work, name=f"{'buychart' if buy else 'sellchart'} {iso} {sym}", daemon=True).start()
        job["ev"].wait(self.CHART_WAIT_S if wait is None else wait)
        if job["done"]:
            with L:
                if J.get(key) is job:
                    J.pop(key, None)
            return job["res"], "ok"
        return None, "preparing"

    def receipt_chart(self, iso, sym, iv="5m", after="1h", venue=None, fetch=True, cache_only=False):
        base = self.receipt(iso, sym)
        if base is None:
            return None
        if base.get("empty"):
            return {"ok": True, "empty": True, "date": iso, "sym": sym}
        want = base["sym"]
        raw_syms = set(base.get("aliases") or ()) | {want, sym}
        ck = (base.get("builtAt"), iso, want, iv, after, venue or "", bool(fetch))
        cache = self.__dict__.setdefault("_chart_cache", {})
        hit = cache.get(ck)
        if hit and time.time() - hit[0] < self.CHART_TTL_S and not (hit[1].get("dexLater") and candles.chart_mode_now() == "bg"):
            return self._with_eval(hit[1])
        if cache_only:
            return None
        rows = self._sell_rows(iso, raw_syms)
        specs, gtok = self._sell_specs([r[4] for r in rows])
        groups = {}
        for ts9, q9, usd9, un9, pid9 in rows:
            sp9, px9, cur9, gid9 = specs.get(pid9) or (None, None, "USD", None)
            if sp9 is None:
                continue
            key9 = candles.spec_key(sp9)
            g = groups.get(key9)
            if g is None:
                g = groups[key9] = {"spec": sp9, "cur": cur9, "gid": gid9, "fills": [], "usd": 0.0}
            if sp9.get("venue") == "dex" and sp9.get("tx_addrs"):
                g["spec"] = dict(g["spec"], tx_addrs=sorted(set(g["spec"].get("tx_addrs") or ()) | set(sp9["tx_addrs"])))
            px = px9 if px9 else (un9 if cur9 == "USD" else None)
            if not px:
                continue
            g["fills"].append({"ts": ts9, "px": px, "q": q9, "amt": px * q9})
            g["usd"] += usd9 or 0.0
        venues = []
        tot_usd = sum(g["usd"] for g in groups.values()) or 0.0
        for k9, g in sorted(groups.items(), key=lambda kv: -kv[1]["usd"]):
            if not g["fills"]:
                continue
            sp9 = g["spec"]
            venues.append({"key": k9, "label": candles.spec_label(sp9) + (" (네이티브 — 바이낸스 시세)" if sp9.get("native") else ""),
                           "venue": sp9.get("venue"), "cur": g["cur"], "curSym": sellchart.CUR_SYM.get(g["cur"], ""), "n": len(g["fills"]),
                           "qty": sellchart._r(sum(f["q"] for f in g["fills"])),
                           "amt": sellchart._r(sum(f["amt"] for f in g["fills"])), "usd": round(g["usd"], 2),
                           "sharePct": round(100.0 * g["usd"] / tot_usd, 1) if tot_usd else None})
        out = {"ok": True, "date": iso, "sym": want, "iv": iv, "after": after, "builtAt": base.get("builtAt"), "buySide": True, "autoEval": True,
               "venues": venues, "venue": None, "chart": None, "fills": [], "summary": None, "receipt": {
                   "realized": base.get("realized"), "sellUsd": (base.get("sell") or {}).get("usd"), "krwMarket": (base.get("sell") or {}).get("krwMarket"),
                   "pathTs": base.get("pathTs")}}
        if not venues:
            out["why"] = "차트로 그릴 매도 체결이 없어요(스테이블·지불 레그만이거나 원장 행을 못 찾음)"
            self._chart_cache_put(cache, ck, out)
            return self._with_eval(out)
        sel = next((v for v in venues if v["key"] == venue), None) or venues[0]
        g = groups[sel["key"]]
        fills = sorted(g["fills"], key=lambda f: f["ts"])
        cur = g["cur"]
        iv_s = candles.IV_SEC[iv]
        w0, w1, t_first, t_last = sellchart.window(fills, after)
        out["venue"] = sel["key"]
        out["cur"], out["curSym"] = cur, sellchart.CUR_SYM.get(cur, "")
        out["fills"] = [{"ts": f["ts"], "px": sellchart._r(f["px"]), "q": sellchart._r(f["q"]), "amt": sellchart._r(f["amt"])} for f in fills]
        out["window"] = {"from": w0, "to": w1, "sellFrom": t_first, "sellTo": t_last}
        dep9 = (base.get("pathTs") or {}).get("deposit")
        cs9 = None
        if fetch:
            primary = {k9: v9 for k9, v9 in g["spec"].items() if k9 != "native"}
            dex_specs = []
            if primary.get("venue") != "dex":
                for ch9, ca9 in gtok.get(g["gid"]) or ():
                    dex_specs.append({"venue": "dex", "chain": ch9, "token": ca9})
            base_sym = primary.get("base") or want.split("#", 1)[0].upper()
            plan = candles.plan_chain(primary, base_sym, cur, dex_specs)
            res = candles.best_chart(plan, iv, w0, w1 + iv_s, cur, fx_rows_fn=lambda iv9, a9, b9: candles.fx_rows(iv9, a9, b9),
                                     budget_s=self.CHART_BUDGET_S, ref_px=candles.median_px(fills))
            cs9 = res["candles"]
            if res["ok"] and res.get("spec"):
                sp_c9 = self.__dict__.setdefault("_chart_src_spec", {})
                if len(sp_c9) >= self.CHART_CACHE_MAX * 2:
                    sp_c9.pop(next(iter(sp_c9)))
                sp_c9[ck] = (res["spec"], res.get("res"))
            out["chart"] = {"ok": res["ok"], "src": res["src"], "tried": res["tried"], "candles": cs9 or [], "complete": bool(res.get("complete", True)),
                            "volUnit": ("usd" if (res["src"] or {}).get("venue") == "dex" else "coin") if res["ok"] else None,
                            "why": None if res["ok"] else "봉을 받지 못했어요 — " + " · ".join(
                                f"{t['label']}: {t.get('note') or t.get('why')}" for t in res["tried"][:4])}
            self._dex_later(out, iso, want, "sell", res.get("dexLater"), listed=(iv == "5m" and after == "1h" and not venue))
        iv_eff = candles.IV_SEC.get(((out.get("chart") or {}).get("src") or {}).get("iv") or iv, iv_s)
        out["summary"] = sellchart.summarize(cs9 or [], fills, iv_eff, req_end=w1 + iv_s, deposit_ts=dep9, cur=cur)
        if cs9:
            inp = sellchart.eval_input(iso, want, sel["label"], (out["chart"] or {}).get("src"), out["summary"], fills, cs9)
            inp = self._memo_inp(inp, iso, [want, sym] + sorted(str(x) for x in (base.get("aliases") or ())))
            out["evalFp"] = sellchart.eval_fp(inp)
            self._eval_inputs = getattr(self, "_eval_inputs", {})
            self._eval_inputs[(iso, want, out["evalFp"])] = inp
            while len(self._eval_inputs) > self.EVAL_INPUTS_MAX:
                self._eval_inputs.pop(next(iter(self._eval_inputs)))
        if len(cache) >= self.CHART_CACHE_MAX:
            cache.pop(next(iter(cache)))
        if (out.get("chart") or {}).get("ok") or not fetch:
            cache[ck] = (time.time(), out)
        return self._with_eval(out)

    def _fut_px(self):
        px, keys = {}, []
        for ex in fut_rcpt.PX_EX:
            k9, d9 = fut_rcpt.load_cached_k(ex)
            px[ex] = d9
            keys.append(k9)
        return px, tuple(keys)

    def fut_receipt(self, iso):
        idx = getattr(self, "_day_idx", None)
        if fut_rcpt is None or not idx or idx.get("futEv") is None:
            return None
        px, pk = self._fut_px()
        ck = (idx["builtAt"], iso)
        C = self.__dict__.setdefault("_fut_rc", {})
        hit = C.get(ck)
        if hit and hit[0] == pk and hit[1] is idx["futEv"]:
            return hit[2]
        body = fut_rcpt.assemble(iso, idx["futEv"], px, dict(self.FUT_EXN, **PERP_NAMES), _fut_by_date_ex, int(time.time() * 1000),
                                 stale=idx.get("futStale") or (), accts=idx.get("futAccts") or {})
        body["builtAt"] = idx["builtAt"]
        if len(C) >= self.FUT_RC_MAX:
            C.pop(next(iter(C)))
        C[ck] = (pk, idx["futEv"], body)
        return body

    def _att_fut_pack(self, fut_ev, det):
        if not det or not fut_ev:
            return {}
        exn = dict(self.FUT_EXN, **PERP_NAMES)
        acc = {}
        for ev9 in fut_ev:
            try:
                dk9, _t9, amt9, krw9, r9 = ev9[:5]
            except (TypeError, ValueError):
                continue
            if dk9 not in det or not isinstance(r9, dict):
                continue
            k9 = (dk9, str(r9.get("ex") or ""), str(r9.get("symbol") or "—"))
            a9 = acc.setdefault(k9, [0.0, 0.0, 0, 0.0])
            a9[0] += float(amt9 or 0)
            a9[1] += float(krw9 or 0)
            if r9.get("kind") == "REALIZED":
                a9[2] += 1
            else:
                a9[3] += float(amt9 or 0)
        out = {}
        for (dk9, ex9, sym9), a9 in sorted(acc.items(), key=lambda kv: (-abs(kv[1][0]), -abs(kv[1][1]), kv[0])):
            if abs(a9[0]) >= 0.005 or abs(a9[1]) >= 0.5:
                out.setdefault(dk9, {"rows": []})["rows"].append([ex9, exn.get(ex9, ex9), sym9, round(a9[0], 2), round(a9[1]), a9[2], round(a9[3], 2)])
        for v9 in out.values():
            more9 = {}
            rows9 = v9["rows"]
            v9["rows"] = self._att_cap(rows9, self.ATT_DET_CAP, "fut", more9, vi=3)
            if more9:
                v9["more"] = more9["fut"] + [round(sum(float(x[4]) for x in rows9[self.ATT_DET_CAP:]))]
        return out

    def att_detail(self, d_from, d_to, lite=False):
        idx = getattr(self, "_day_idx", None)
        det = idx.get("attDet") if isinstance(idx, dict) and "attDet" in idx else self.__dict__.get("_att_det")
        if not idx or det is None:
            return None
        days = {}
        d9 = datetime.strptime(d_from, "%Y-%m-%d")
        end9 = datetime.strptime(d_to, "%Y-%m-%d")
        n9 = 0
        while d9 <= end9 and len(days) <= self.ATT_DET_SPAN and n9 <= self.ATT_DET_SPAN:
            k9 = d9.strftime("%Y-%m-%d")
            if isinstance(det.get(k9), dict):
                days[k9] = dict(det[k9])
                if lite:
                    days[k9]["mk"] = [x[:3] for x in days[k9].get("mk") or ()]
            n9 += 1
            if d9 >= end9:
                break
            d9 += timedelta(days=1)
        af9 = dict(idx.get("attFut") or {})
        frz = {} if lite else attfreeze.serve(days, af9, d_from, d_to, idx.get("builtAt"))
        for k9, v9 in days.items():
            f9 = af9.get(k9)
            if f9:
                v9["fut"] = [list(x) for x in f9.get("rows") or ()]
                if f9.get("more"):
                    v9["more"] = dict(v9.get("more") or {}, fut=list(f9["more"]))
        return dict({"ok": True, "builtAt": idx.get("builtAt"), "days": days}, **({"frz": frz} if frz else {}))

    def _fut_rkey(self, base):
        C = self.__dict__.get("_fut_rc") or {}
        for v9 in C.values():
            if v9[2] is base:
                return (base.get("builtAt"), base.get("date"), v9[0])
        return None

    @staticmethod
    def _fut_spec(ex, coin, sym):
        q = fut_rcpt.quote_of(sym)
        q = q if q in ("USDT", "USDC") else "USDT"
        if ex == "bybit":
            return {"venue": "bybit_linear", "base": coin, "quote": q}
        return {"venue": "binance_futures", "base": coin, "quote": q}

    def fut_chart(self, iso, sym, iv="5m", venue=None, fetch=True, cache_only=False):
        base = self.fut_receipt(iso)
        if base is None:
            return None
        c = next((x for x in base.get("coins") or () if x.get("coin") == sym), None)
        if base.get("empty") or c is None:
            return {"ok": True, "empty": True, "side": "fut", "date": iso, "sym": sym}
        rk9 = self._fut_rkey(base)
        ck = ("fut", rk9, iso, sym, iv, venue or "", bool(fetch)) if rk9 is not None else None
        cache = self.__dict__.setdefault("_chart_cache", {})
        hit = cache.get(ck) if ck is not None else None
        if hit and time.time() - hit[0] < self.CHART_TTL_S:
            return hit[1]
        if cache_only:
            return None
        trs = c.get("trades") or []
        tot = sum(abs(v["usd"]) for v in c["venues"]) or 0.0
        vby = {}
        for v in c["venues"]:
            x = vby.setdefault(v["exKey"], {"key": v["exKey"], "label": v["ex"] + " " + v["symbol"], "sym": v["symbol"], "n": 0, "usd": 0.0})
            x["n"] += v["n"]
            x["usd"] += v["usd"]
        venues = sorted(vby.values(), key=lambda x: (-abs(x["usd"]), x["key"]))
        for x in venues:
            x["usd"] = round(x["usd"], 2)
            x["sharePct"] = round(100.0 * abs(x["usd"]) / tot, 1) if tot else None
        venues = [x for x in venues if x["n"] > 0] or venues
        sel = next((x for x in venues if x["key"] == venue), None) or venues[0]
        trs = [t for t in trs if t.get("exKey") == sel["key"]] if len(venues) > 1 else trs
        n_all = (c.get("tradesTotalEx") or {}).get(sel["key"], len(trs)) if len(venues) > 1 else c.get("tradesTotal", len(trs))
        cap_note = f"큰 손익 {len(trs)}건만 그림(그날 {n_all}건)" if trs and n_all > len(trs) else None
        if not trs:
            out = {"ok": True, "side": "fut", "date": iso, "sym": sym, "label": c.get("label"), "iv": iv, "builtAt": base.get("builtAt"), "venues": [], "venue": sel["key"],
                   "cur": "USD", "window": None, "marks": [], "spans": [],
                   "chart": {"ok": False, "src": None, "tried": [], "candles": [], "complete": True, "why": "그날 이 종목은 청산이 없어(수수료·펀딩만) 차트를 그리지 않아요"}}
            if ck is not None:
                self._chart_cache_put(cache, ck, out)
            return out
        now = time.time()
        ex_ts = [float(t["exitTs"]) for t in trs]
        en_ts = [float(t["entryTs"]) for t in trs if t.get("entryTs")]
        w1 = min(max(ex_ts) + 3600, now)
        w0 = min(min(ex_ts) - 3600, (min(en_ts) - 1800) if en_ts else float("inf"))
        w0 = max(w0, w1 - self.FUT_SPAN_MAX_S)
        iv_use = "1h" if w1 - w0 > self.FUT_SPAN_LO_S else iv
        iv_s = candles.IV_SEC[iv_use]
        w0, w1 = int(w0) // iv_s * iv_s, int(w1)
        out = {"ok": True, "side": "fut", "date": iso, "sym": sym, "label": c.get("label"), "iv": iv, "ivUse": iv_use, "builtAt": base.get("builtAt"),
               "venues": [{k: v for k, v in x.items() if k != "sym"} for x in venues], "venue": sel["key"], "cur": "USD",
               "window": {"from": w0, "to": w1}, "chart": None, "marks": [], "spans": []}
        if cap_note:
            out["capNote"] = cap_note
        cs9 = None
        if fetch:
            prim = self._fut_spec(sel["key"], sym, sel["sym"])
            if sel["key"] not in ("binance", "bybit"):
                out["srcNote"] = f"{sel['label']} 봉 대신 같은 코인 선물 봉"
            plan = candles.plan_chain(prim, sym, "USD")
            alts = [(sp, None, "alt_cex") for sp in ({"venue": "binance_futures", "base": sym, "quote": "USDT"},
                                                       {"venue": "bybit_linear", "base": sym, "quote": "USDT"})
                    if candles.spec_key(sp) != candles.spec_key(prim)]
            plan = plan[:1] + alts + plan[1:]
            ref = sorted(float(t["exitPx"]) for t in trs if t.get("exitPx"))
            res = candles.best_chart(plan, iv_use, w0, w1 + iv_s, "USD", budget_s=self.CHART_BUDGET_S, ref_px=ref[len(ref) // 2] if ref else None)
            cs9 = res["candles"]
            out["chart"] = {"ok": res["ok"], "src": res["src"], "tried": res["tried"], "candles": cs9 or [], "complete": bool(res.get("complete", True)),
                            "volUnit": "coin" if res["ok"] else None,
                            "why": None if res["ok"] else "봉을 받지 못했어요 — " + " · ".join(
                                f"{t['label']}: {t.get('note') or t.get('why')}" for t in res["tried"][:4])}
        bars = sorted(cs9 or [], key=lambda r9: r9[0])

        def close_at(ts9):
            if not bars:
                return None
            lo9, hi9 = 0, len(bars) - 1
            while lo9 < hi9:
                mid9 = (lo9 + hi9 + 1) // 2
                if bars[mid9][0] <= ts9:
                    lo9 = mid9
                else:
                    hi9 = mid9 - 1
            return bars[lo9][4]
        for t in trs:
            p9 = t.get("exitPx")
            out["marks"].append({"id": t["id"], "ts": t["exitTs"], "px": p9 if p9 else close_at(t["exitTs"]), "kind": "close", "side": t.get("side"),
                                 "exKey": t["exKey"], "q": t.get("qty"), "pnl": t["pnl"], "approx": not p9})
            if p9 and t.get("entryPx"):
                out["spans"].append({"id": t["id"], "from": t.get("entryTs"), "to": t["exitTs"], "entryPx": t["entryPx"], "exitPx": p9,
                                     "side": t.get("side"), "pnl": t["pnl"]})
        for o in c.get("opens") or ():
            if o.get("exKey") != sel["key"] or not (w0 <= float(o["ts"]) <= w1):
                continue
            m9 = {"ts": o["ts"], "px": o["px"], "kind": "open", "side": o["side"], "exKey": o["exKey"], "q": o.get("q"), "approx": False}
            if o.get("fills"):
                m9["fills"] = o["fills"]
            out["marks"].append(m9)
        out["marks"].sort(key=lambda x: x["ts"])
        if len(cache) >= self.CHART_CACHE_MAX:
            cache.pop(next(iter(cache)))
        if ck is not None and ((out.get("chart") or {}).get("ok") or not fetch):
            cache[ck] = (time.time(), out)
        return out

    def purge_memo_charts(self, iso, sym):
        def hit(key9):
            if not isinstance(key9, tuple) or iso not in key9:
                return False
            return any(isinstance(x, str) and day_memo.norm_sym(x) == sym for x in key9)
        cache = self.__dict__.get("_chart_cache") or {}
        for k9 in [k9 for k9 in list(cache) if hit(k9)]:
            cache.pop(k9, None)
        with type(self)._CHART_JLOCK:
            J = type(self)._CHART_JOBS
            for k9 in [k9 for k9, j9 in list(J.items()) if j9.get("done") and hit(k9)]:
                J.pop(k9, None)

    @staticmethod
    def _memo_inp(inp, iso, syms):
        try:
            mm = DAY_MEMOS.for_date(iso)
        except Exception as _cg9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_detail:DetailApiMixin._memo_inp", _cg9)
            return inp
        if not mm:
            return inp
        for s9 in syms:
            k9 = day_memo.norm_sym(str(s9 or ""))
            if k9 and k9 in mm:
                return dict(inp, memo=mm[k9])
        return inp

    @staticmethod
    def _eval_rec(rec, side="sell"):
        import review_prompt as rp9
        cur9 = rp9.BUY_EVAL_VERSION if side == "buy" else rp9.SELL_EVAL_VERSION
        return dict(rec, old=True) if rec.get("pv") != cur9 else dict(rec)

    @staticmethod
    def _receipt_vk(idx, iso, canon):
        import review_daily as rd
        out = {}
        for _ts, kind, e, meta in ((idx.get("ix") or {}).get(iso) or ()):
            if kind != "pos" or meta is None or not isinstance(e, dict):
                continue
            k9 = str(e.get("k") or "")
            if "매도" not in k9 and "매수" not in k9:
                continue
            v9 = rd._venue(e)
            if v9 in ("LP", "?", ""):
                continue
            t9 = ("gate" if v9 == "게이트" else "cex") if v9 in rd._EX_KO else "dex"
            s9 = canon.get(meta[1], meta[1])
            lst9 = out.setdefault(s9, [])
            if t9 not in lst9:
                lst9.append(t9)
        return {k9: sorted(v9) for k9, v9 in out.items()}

    def receipt_list(self, d_from, d_to):
        idx = getattr(self, "_day_idx", None)
        if not idx or idx.get("pos") is None:
            return None
        import review_daily as rd
        by_day = {}
        for p in idx["pos"]:
            if p.get("kind") in ("gas", "stake") or not p.get("sym"):
                continue
            for k9, v9 in (p.get("realizedByDay") or {}).items():
                if len(str(k9)) != 10 or not (d_from <= k9 <= d_to):
                    continue
                try:
                    v9 = float(v9 or 0)
                except (TypeError, ValueError):
                    continue
                by_day.setdefault(k9, {}).setdefault(p["sym"], 0.0)
                by_day[k9][p["sym"]] += v9
        items = []
        for d9, m9 in by_day.items():
            canon = rd._canon_map(set(m9))
            agg = {}
            for s9, v9 in m9.items():
                c9 = canon.get(s9, s9)
                agg[c9] = agg.get(c9, 0.0) + v9
            vk9 = self._receipt_vk(idx, d9, canon)
            for s9, v9 in agg.items():
                if abs(v9) >= 0.005:
                    items.append({"date": d9, "sym": s9, "usd": round(v9, 2), "vk": vk9.get(s9) or []})
        items.sort(key=lambda x: (x["date"], abs(x["usd"])), reverse=True)
        return {"ok": True, "from": d_from, "to": d_to, "builtAt": idx.get("builtAt"), "n": len(items), "items": items}

    @staticmethod
    def _fetched_span(res, a, b, iv_s):
        if not res or not res.get("ok"):
            return None
        if res.get("complete", True):
            return (a, b)
        cs9 = res.get("candles") or []
        return (int(cs9[0][0]), int(cs9[-1][0]) + int(iv_s)) if cs9 else None

    @staticmethod
    def _xc_resolve(legs, raw_syms):
        fam = {str(x9 or "").split("#", 1)[0].strip().upper() for x9 in raw_syms}
        conn9 = dbm.open_db(paths.DB_PATH, readonly=True)
        try:
            for l9 in legs:
                x9 = l9["xc"]
                ch9, tx9 = str(x9.get("chain") or ""), str(x9.get("tx") or "")
                if not ch9 or not tx9:
                    continue
                txq9 = tx9.lower() if tx9.startswith("0x") else tx9
                hit9 = None
                for r9 in conn9.execute("SELECT p.posting_id, p.event_ts, a.symbol FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
                                        " WHERE p.source_kind = 'chain_tx' AND p.source_ns = ? AND p.source_id = ? AND p.leg_kind = 'acq'",
                                        (ch9, txq9)).fetchall():
                    if str(r9["symbol"] or "").split("#", 1)[0].strip().upper() in fam:
                        hit9 = r9
                        break
                if hit9 is not None:
                    l9["pid"], l9["ts"] = int(hit9["posting_id"]), int(hit9["event_ts"])
                    x9["tsFrom"] = "ledger"
                    continue
                if l9["ts"] or x9.get("block") in (None, ""):
                    continue
                try:
                    blk9 = int(x9["block"])
                except (TypeError, ValueError):
                    continue
                for r9 in conn9.execute("SELECT txhash FROM raw_txs WHERE chain = ? AND block = ? LIMIT 8", (ch9, blk9)).fetchall():
                    p9 = conn9.execute("SELECT event_ts FROM postings WHERE source_kind = 'chain_tx' AND source_ns = ? AND source_id = ? LIMIT 1",
                                       (ch9, r9["txhash"])).fetchone()
                    if p9 is not None and p9["event_ts"]:
                        l9["ts"] = int(p9["event_ts"])
                        x9["tsFrom"] = "block"
                        break
        finally:
            conn9.close()

    def _buy_cards(self, raw_syms):
        idx = self._day_idx
        ck = (idx.get("builtAt"), tuple(sorted(str(x) for x in raw_syms)))
        cc = self.__dict__.setdefault("_buy_cards_cache", {})
        if ck in cc:
            return cc[ck]
        cards = {}
        for _d9, rows in (idx.get("ix") or {}).items():
            for ts, kind, e, meta in rows:
                if kind != "pos" or meta is None or meta[1] not in raw_syms:
                    continue
                c9 = cards.get(meta[0])
                if c9 is None:
                    c9 = cards[meta[0]] = {"sym": meta[1], "chain": meta[2], "ev": []}
                c9["ev"].append((int(ts), e))
        for c9 in cards.values():
            c9["ev"].sort(key=lambda x: x[0])
        while len(cc) >= 8:
            cc.pop(next(iter(cc)))
        cc[ck] = cards
        return cards

    def receipt_chart_buy(self, iso, sym, iv="5m", venue=None, bvenue=None, fetch=True, cache_only=False):
        base = self.receipt(iso, sym)
        if base is None:
            return None
        if base.get("empty"):
            return {"ok": True, "empty": True, "side": "buy", "date": iso, "sym": sym}
        want = base["sym"]
        raw_syms = set(base.get("aliases") or ()) | {want, sym}
        ck = ("buy", base.get("builtAt"), iso, want, iv, venue or "", bvenue or "", bool(fetch))
        cache = self.__dict__.setdefault("_chart_cache", {})
        hit = cache.get(ck)
        if hit and time.time() - hit[0] < self.CHART_TTL_S and not (hit[1].get("dexLater") and candles.chart_mode_now() == "bg"):
            return self._with_eval(hit[1])
        if cache_only:
            return None
        sell = self.receipt_chart(iso, sym, iv, "1h", venue, fetch=fetch) or {}
        bs9, tx9 = base.get("sell") or {}, base.get("tax") or {}
        cur = sell.get("cur") or ("KRW" if bs9.get("krwMarket") else "USD")
        ssm = sell.get("summary") or {}
        sw = sell.get("window") or {}
        sq9 = float(bs9.get("qty") or 0)
        cost9 = None
        if tx9.get("recon") and sq9 > 0:
            rz9 = base.get("realized") or {}
            if cur == "KRW" and tx9.get("dispKrw") is not None and rz9.get("krw") is not None:
                cost9 = (float(tx9["dispKrw"]) - float(rz9["krw"])) / sq9
            elif cur == "USD":
                cost9 = (float(tx9.get("disp") or 0) - float(rz9.get("usd") or 0)) / sq9
        sell_ctx = {"avgPx": ssm.get("avgPx") if (ssm.get("cur") or cur) == cur else None,
                    "firstTs": sw.get("sellFrom") or (base.get("pathTs") or {}).get("first_sell"), "lastTs": sw.get("sellTo"),
                    "openTs": ssm.get("openTs"), "costPx": cost9 if cost9 and cost9 > 0 else None}
        idx = self._day_idx
        cards = self._buy_cards(raw_syms)
        real = buychart.sell_cards(cards, iso)
        ex = buychart.extract_legs(cards, real, iso)
        legs = list(ex["legs"])
        inflows = [dict(x9) for x9 in (ex.get("inflows") or ())]
        if any(l9.get("xc") for l9 in legs):
            self._xc_resolve([l9 for l9 in legs if l9.get("xc")], raw_syms)
            legs, inflows = buychart.xc_settle(legs, inflows)
        specs, gtok = self._sell_specs([l9["pid"] for l9 in legs if l9.get("pid")])
        ko2code = {v9: k9 for k9, v9 in candles.CHAIN_KO.items()}
        card_gid = lambda pk9: (int(m9.group(1)) if (m9 := re.match(r"g(\d+)", str(pk9 or ""))) else None)
        lp_odd = sorted({l9["pid"] for l9 in legs if l9.get("pid") and l9["k"] == "LP 전환 매수" and specs.get(l9["pid"])
                         and specs[l9["pid"]][3] is not None and card_gid(l9["pkey"]) is not None and int(specs[l9["pid"]][3]) != card_gid(l9["pkey"])})
        row_sym = {}
        if lp_odd:
            conn9 = dbm.open_db(paths.DB_PATH, readonly=True)
            try:
                for i9 in range(0, len(lp_odd), 400):
                    ch9 = lp_odd[i9:i9 + 400]
                    for x9 in conn9.execute("SELECT p.posting_id, a.symbol FROM postings p JOIN assets a ON a.asset_id = p.asset_id WHERE p.posting_id IN (%s)"
                                            % ",".join("?" * len(ch9)), ch9).fetchall():
                        row_sym[int(x9["posting_id"])] = x9["symbol"]
            finally:
                conn9.close()
        spec_of_leg = {}
        for l9 in legs:
            r9 = specs.get(l9.get("pid"))
            spec_of_leg[id(l9)] = r9 if (r9 and buychart.keep_leg_row(l9["k"], card_gid(l9["pkey"]), r9[3], row_sym.get(l9.get("pid")), raw_syms)) else None
        gid_of = {}
        for l9 in legs:
            cg9 = card_gid(l9["pkey"])
            g9 = cg9 if cg9 is not None else (spec_of_leg[id(l9)] or (None, None, None, None))[3]
            if g9 is not None:
                gid_of.setdefault(l9["pkey"], g9)
        any_gid = next(iter(gid_of.values()), None)
        fills, need_fx, groups = [], [], {}
        for l9 in legs:
            sp9, px9, cur9, gid9 = spec_of_leg[id(l9)] or (None, None, "USD", None)
            if sp9 is None:
                ch9 = ko2code.get(str(l9.get("chain") or ""), str(l9.get("chain") or "").lower())
                tok9 = next((ca for c9, ca in (gtok.get(gid_of.get(l9["pkey"], any_gid)) or ()) if c9 == ch9), None)
                if tok9 is None and gid_of.get(l9["pkey"], any_gid) is not None:
                    conn9 = dbm.open_db(paths.DB_PATH, readonly=True)
                    try:
                        r9 = conn9.execute("SELECT address FROM assets WHERE group_id=? AND chain=? AND address IS NOT NULL AND address != '' AND hidden=0 LIMIT 1",
                                           (gid_of.get(l9["pkey"], any_gid), ch9)).fetchone()
                        tok9 = r9["address"] if r9 else None
                    finally:
                        conn9.close()
                if l9.get("xc") and l9["xc"].get("chain"):
                    ch9, tok9 = str(l9["xc"]["chain"]), l9["xc"].get("token")
                sp9 = {"venue": "dex", "chain": ch9, "token": tok9} if (tok9 and ch9 in candles.GT_NETWORK) else None
                gid9 = gid_of.get(l9["pkey"], any_gid)
            q9 = float(l9["q"])
            if cur == "KRW":
                px = (l9["krw"] / q9) if l9.get("krw") else (px9 if (cur9 == "KRW" and px9) else None)
            else:
                px = l9.get("un") or (px9 if (cur9 == "USD" and px9) else None)
            vlab = candles.spec_label(sp9) if sp9 else str(l9.get("chain") or "?")
            f9 = {"ts": l9["ts"], "px": px, "q": q9, "amt": (px * q9) if px else None, "kind": buychart.KIND_SHORT.get(l9["k"], l9["k"]),
                  "venue": sellchart.clean_label(vlab) or "?", "usd": l9.get("usd"), "un": l9.get("un"),
                  "vkey": candles.spec_key(sp9) if sp9 else None}
            if l9.get("from"):
                f9["from"] = l9["from"]
            if l9.get("xc"):
                f9["via"] = "경유 역추적" + (" · 시각 = 같은 블록" if l9["xc"].get("tsFrom") == "block" else "")
            if px is None and cur == "KRW" and l9.get("un"):
                need_fx.append(f9)
            fills.append(f9)
            if sp9 is not None:
                k9 = candles.spec_key(sp9)
                g = groups.get(k9)
                if g is None:
                    g = groups[k9] = {"spec": {k: v for k, v in sp9.items() if k != "native"}, "gid": gid9, "usd": 0.0, "n": 0}
                if sp9.get("venue") == "dex" and sp9.get("tx_addrs"):
                    g["spec"] = dict(g["spec"], tx_addrs=sorted(set(g["spec"].get("tx_addrs") or ()) | set(sp9["tx_addrs"])))
                g["usd"] += float(l9.get("usd") or 0)
                g["n"] += 1
        inf_out = []
        for x9 in inflows:
            u9 = x9.get("un")
            f9 = {"ts": x9["ts"], "q": float(x9["q"]), "un": u9, "usd": x9.get("usd"), "px": (u9 if cur != "KRW" else None),
                  "kind": "입금", "d": x9.get("d"), "rule": x9.get("rule"), "chain": x9.get("chain")}
            f9["amt"] = (f9["px"] * f9["q"]) if f9["px"] else None
            if f9["px"] is None and u9:
                need_fx.append(f9)
            inf_out.append(f9)
        if need_fx and fetch:
            t9 = [f["ts"] for f in need_fx]
            iv_fx = iv if max(t9) - min(t9) <= 86400 else "1h"
            r9 = candles.fx_rows(iv_fx, min(t9) - 3600, max(t9) + candles.IV_SEC[iv_fx])
            fr9 = sorted((c[0], c[4]) for c in (r9.candles or ()) if c[4] > 0) if r9 is not None and r9.ok else []
            for f in need_fx:
                k9 = next((c for t, c in reversed(fr9) if t <= f["ts"]), fr9[0][1] if fr9 else None)
                if k9:
                    f["px"], f["amt"] = f["un"] * k9, f["un"] * k9 * f["q"]
        fills = sorted([f for f in fills if f["px"]], key=lambda f: f["ts"])
        tot_usd = sum(g["usd"] for g in groups.values()) or 0.0
        venues = [{"key": k9, "label": candles.spec_label(g["spec"]), "venue": g["spec"].get("venue"), "n": g["n"], "usd": round(g["usd"], 2),
                   "sharePct": round(100.0 * g["usd"] / tot_usd, 1) if tot_usd else None}
                  for k9, g in sorted(groups.items(), key=lambda kv: -kv[1]["usd"])]
        lg9 = {"cards": ex["cards"], "srcCards": ex["srcCards"], "unmatched": ex["unmatched"], "fallback": ex.get("fallback", 0),
               "source": ex.get("source"), "simSells": ex.get("simSells", 0), "other": ex.get("other"), "unknownQty": ex.get("unknownQty"),
               "trimmed": ex["trimmed"], "lpFee": ex["lpFee"],
               "n": len(legs), "priced": len(fills), "inflows": len(inf_out),
               "inflowQty": sellchart._r(sum(f9["q"] for f9 in inf_out)), "inflowUsd": round(sum(float(f9.get("usd") or 0) for f9 in inf_out), 2)}
        out = {"ok": True, "side": "buy", "date": iso, "sym": want, "iv": iv, "builtAt": base.get("builtAt"), "cur": cur, "autoEval": True,
               "curSym": sellchart.CUR_SYM.get(cur, ""), "sellVenue": sell.get("venue"), "venues": venues, "venue": None,
               "fills": [], "segs": [], "chart": None, "summary": None, "legs": lg9,
               "inflows": [{"ts": f9["ts"], "px": sellchart._r(f9["px"]) if f9["px"] else None, "q": sellchart._r(f9["q"]),
                            "amt": sellchart._r(f9["amt"]) if f9["amt"] else None, "kind": "입금", "d": f9.get("d"), "rule": f9.get("rule"),
                            "chain": f9.get("chain")} for f9 in sorted(inf_out, key=lambda f9: f9["ts"])],
               "sell": {k: v for k, v in sell_ctx.items() if v is not None}}
        if not fills:
            out["why"] = (("이 매도의 원가는 매수 기록이 아니라 입금으로 잡혔어요 — " + str(max(inf_out, key=lambda f9: f9["q"]).get("rule") or "규칙 표시 없음"))
                          if inf_out else
                          "이 매도의 원가가 된 매수 기록을 찾지 못했어요(이전 보유분 · 원가 미상 · 이관 짝 없음)" if not legs
                          else "매수 체결가를 표시 통화로 바꾸지 못했어요")
            self._chart_cache_put(cache, ck, out)
            return self._with_eval(out)
        sel = next((v for v in venues if v["key"] == bvenue), None) or (venues[0] if venues else None)
        out["venue"] = sel["key"] if sel else None
        segs, outside = buychart.segments(fills, sell_from=sw.get("from"))
        out["outside"] = {"n": len(outside), "amt": sellchart._r(sum(float(fills[i]["amt"] or 0) for i in outside))} if outside else None
        iv_s = candles.IV_SEC[iv]
        cs_all, srcs, bridge = [], [], None
        later9 = sell.get("dexLater")
        fetched9 = []
        seg_out = []
        gseg9, gap_job = [], None
        if fetch and sel:
            g = groups[sel["key"]]
            primary = g["spec"]
            dex_specs = []
            if primary.get("venue") != "dex":
                for ch9, ca9 in gtok.get(g["gid"]) or ():
                    dex_specs.append({"venue": "dex", "chain": ch9, "token": ca9})
            base_sym = primary.get("base") or want.split("#", 1)[0].upper()
            plan = candles.plan_chain(primary, base_sym, cur, dex_specs)
            s_ch = sell.get("chart") or {}
            s_cs = sorted((list(c[:6]) for c in (s_ch.get("candles") or ()) if isinstance(c, (list, tuple)) and len(c) >= 6), key=lambda c: c[0]) \
                if (s_ch.get("ok") and sell.get("cur") == cur) else []
            s_first = s_cs[0][0] if s_cs else None
            rk9 = (float(tx9["dispKrw"]) / float(tx9["disp"])) if (tx9.get("dispKrw") and tx9.get("disp")) else None

            def val9(c, unit, fxk):
                if unit == "usd":
                    return c[5] * (fxk if cur == "KRW" else 1.0)
                return c[5] * (c[2] + c[3] + c[4]) / 3.0
            s_unit = s_ch.get("volUnit") or "coin"
            s_iv9 = candles.IV_SEC.get((s_ch.get("src") or {}).get("iv") or iv, iv_s)
            s_fx = (((s_ch.get("src") or {}).get("fx") or {}).get("avg")) or rk9 or 1.0
            for s9 in segs:
                res = candles.best_chart(plan, iv, s9["from"], s9["to"] + iv_s, cur, fx_rows_fn=lambda iv9, a9, b9: candles.fx_rows(iv9, a9, b9),
                                         budget_s=self.CHART_BUDGET_S / max(1, len(segs)),
                                         ref_px=candles.median_px([f9 for f9 in fills if s9["from"] <= f9["ts"] <= s9["to"]] or fills))
                later9 = later9 or res.get("dexLater")
                src9 = res["src"]
                unit9 = "usd" if (src9 or {}).get("venue") == "dex" else "coin"
                fx9 = ((src9 or {}).get("fx") or {}).get("avg") or rk9 or 1.0
                own = [c for c in (res["candles"] or []) if s_first is None or c[0] < s_first]
                raw_n9 = len(own)
                end9 = min(s9["to"] + iv_s, s_first) if s_first else s9["to"] + iv_s
                g_iv9 = candles.IV_SEC.get((src9 or {}).get("iv") or iv, iv_s)
                cs9 = [c[:5] + [val9(c, unit9, fx9), (c[6] if len(c) > 6 else 0), g_iv9] for c in buychart.ffill(own, g_iv9, s9["from"], end9)]
                joined = [c[:5] + [val9(c, s_unit, s_fx), 2, s_iv9] for c in s_cs if s9["from"] - s_iv9 < c[0] < s9["to"] + iv_s] if s_first is not None else []
                seg_out.append(dict(s9, ok=res["ok"] or bool(joined), src=src9, tried=res["tried"], candles=cs9 + joined, filled=len(cs9) - raw_n9,
                                    joinAt=joined[0][0] if joined else None, joinSrc=(s_ch.get("src") if joined else None),
                                    volUnit="val",
                                    why=None if (res["ok"] or joined) else "봉을 받지 못했어요 — " + " · ".join(
                                        f"{t['label']}: {t.get('note') or t.get('why')}" for t in res["tried"][:4])))
                cs_all += cs9 + joined
                if res["ok"] and res.get("spec") and cs9:
                    gseg9.append({"from": int(s9["from"]), "end": int(s9["to"]) + g_iv9, "iv": g_iv9, "spec": res["spec"], "res": res.get("res"),
                                  "src": src9, "unit": unit9, "fx": fx9, "last": cs9[-1][4], "lastT": cs9[-1][0]})
                sp9 = self._fetched_span(res, s9["from"], s9["to"] + iv_s, candles.IV_SEC.get((src9 or {}).get("iv") or iv, iv_s))
                if sp9:
                    fetched9.append(sp9)
                if src9:
                    srcs.append(src9)
            if s_first is not None:
                sp9 = self._fetched_span({"ok": True, "complete": s_ch.get("complete", True), "candles": s_cs},
                                         int(sw.get("from") or s_cs[0][0]), int(sw.get("to") or s_cs[-1][0]) + s_iv9, s_iv9)
                if sp9:
                    fetched9.append(sp9)
            fs9 = int(sell_ctx.get("firstTs") or 0)
            if s_first is not None and fs9:
                seen9 = {c[0] for c in cs_all if len(c) > 6 and c[6] == 2}
                cs_all += [c[:5] + [val9(c, s_unit, s_fx), 2, s_iv9] for c in s_cs if c[0] < fs9 and c[0] not in seen9]
            if segs and fs9 and fs9 - segs[-1]["to"] > 0 and fs9 - segs[-1]["to"] <= self.BRIDGE_MAX_S and srcs:
                rb = candles.best_chart([(primary, "hour", "bridge")], iv, segs[-1]["to"], fs9 + 3600, cur,
                                        fx_rows_fn=lambda iv9, a9, b9: candles.fx_rows(iv9, a9, b9), budget_s=20, by_date=False)
                bridge = rb["candles"] if rb["ok"] else None
                later9 = later9 or rb.get("dexLater")
                sp9 = self._fetched_span(rb, segs[-1]["to"], fs9 + 3600, 3600)
                if sp9:
                    fetched9.append(sp9)
            if gseg9 and s_first is not None and self.GAP_BRIDGE_S > 0:
                ls9 = int(sw.get("sellTo") or 0) or fs9
                sv9 = str(sell.get("venue") or "").split(":", 1)[0]
                gap_job = {"segs": sorted(gseg9, key=lambda g9: g9["from"]), "s_first": int(s_first), "w_from": int(sw["from"]) if sw.get("from") else None,
                           "open_ts": ssm.get("openTs"), "s_iv": s_iv9, "short": bool(ls9) and ls9 - int(fills[0]["ts"]) <= buychart.SHORT_SPAN_S,
                           "s_spec": (self.__dict__.get("_chart_src_spec") or {}).get((base.get("builtAt"), iso, want, iv, "1h", venue or "", bool(fetch))),
                           "s_name": self._venue_name(sv9), "cur": cur, "iv": iv, "rk": rk9, "val": val9}
            out["chart"] = {"ok": any(x["ok"] for x in seg_out), "src": srcs[0] if srcs else None,
                            "why": None if any(x["ok"] for x in seg_out) else (seg_out[0]["why"] if seg_out else "봉을 받지 못했어요")}
            self._dex_later(out, iso, want, "buy", later9, listed=(iv == "5m" and not venue and not bvenue))
        else:
            seg_out = [dict(s9, ok=False, src=None, tried=[], candles=[], volUnit=None, why=None) for s9 in segs]
        out["segs"] = seg_out
        cs_all.sort(key=lambda c: c[0])
        iv_eff = candles.IV_SEC.get(((out.get("chart") or {}).get("src") or {}).get("iv") or iv, iv_s)
        fl_sum = [{"ts": f["ts"], "px": f["px"], "q": f["q"], "amt": f["amt"]} for f in fills]
        out["summary"] = buychart.summarize_buy(cs_all, fl_sum, iv_eff, segs, cur=cur, sell=sell_ctx, bridge=bridge, fetched=fetched9 if fetch else None)
        keep9 = fills if len(fills) <= self.BUY_FILLS_MAX else sorted(sorted(fills, key=lambda f: -float(f["amt"] or 0))[:self.BUY_FILLS_MAX], key=lambda f: f["ts"])
        out["fills"] = [{"ts": f["ts"], "px": sellchart._r(f["px"]), "q": sellchart._r(f["q"]), "amt": sellchart._r(f["amt"]), "kind": f["kind"],
                         "venue": f["venue"]} for f in keep9]
        out["fillsTotal"] = len(fills)
        if cs_all:
            inp = buychart.buy_eval_input(iso, want, [v["label"] for v in venues], (out["chart"] or {}).get("src"), out["summary"], fills, cs_all,
                                          extra={"outside": len(outside) or None, "trimmed": ex["trimmed"]["n"] or None,
                                                 "lp_fee_n": ex["lpFee"]["n"] or None})
            inp = self._memo_inp(inp, iso, [want, sym] + sorted(str(x) for x in (base.get("aliases") or ())))
            out["evalFp"] = sellchart.eval_fp(inp)
            self._eval_inputs = getattr(self, "_eval_inputs", {})
            self._eval_inputs[("buy", iso, want, out["evalFp"])] = inp
            while len(self._eval_inputs) > self.EVAL_INPUTS_MAX:
                self._eval_inputs.pop(next(iter(self._eval_inputs)))
        if gap_job is not None and (out.get("chart") or {}).get("ok"):
            try:
                gb9 = self._gap_bridges(gap_job)
            except Exception as e9:   # noqa: BLE001 [fallback]
                calcguard.swallowed("view_detail:DetailApiMixin.receipt_chart_buy", e9)
                log.warning("빈 시간 표시 봉 실패(%s %s): %s", iso, want, e9)
                gb9 = None
            if gb9:
                out["gapBridges"] = gb9
        if len(cache) >= self.CHART_CACHE_MAX:
            cache.pop(next(iter(cache)))
        if (out.get("chart") or {}).get("ok") or not fetch:
            cache[ck] = (time.time(), out)
        return self._with_eval(out)

    @staticmethod
    def _venue_name(v):
        return {"dex": "DEX", "coingecko": "코인게코"}.get(v) or candles.VENUE_KO.get(v, v or "")

    def _gap_bridges(self, job):
        gs = job["segs"]
        plan = buychart.gap_plan([(g["from"], g["end"], g["iv"]) for g in gs], job["s_first"], job["w_from"], job["open_ts"], job["s_iv"],
                                 job["short"], self.GAP_BRIDGE_S)
        cur, iv = job["cur"], job["iv"]
        iv_s = candles.IV_SEC[iv]
        fxf = lambda iv9, a9, b9: candles.fx_rows(iv9, a9, b9)
        out = []
        for gp in plan:
            g, a, b = gs[gp["seg"]], gp["from"], gp["to"]
            got = None
            if gp["kind"] == "wait" and job.get("s_spec") and job["s_spec"][0]:
                r = candles.best_chart([(job["s_spec"][0], job["s_spec"][1], "bridge")], iv, a, b, cur, fx_rows_fn=fxf,
                                       budget_s=self.GAP_BRIDGE_BUDGET_S, by_date=False)
                if r["ok"]:
                    s9 = r["src"] or {}
                    iv9 = candles.IV_SEC.get(s9.get("iv") or iv, iv_s)
                    rows = buychart.bridge_rows(r["candles"], iv9, a, b)
                    if rows:
                        got = ("wait", s9, rows, iv9, "usd" if s9.get("venue") == "dex" else "coin", (s9.get("fx") or {}).get("avg") or job["rk"] or 1.0)
            if got is None:
                r = candles.best_chart([(g["spec"], g["res"], "bridge")], iv, a, b, cur, fx_rows_fn=fxf, budget_s=self.GAP_BRIDGE_BUDGET_S, by_date=False)
                s9 = r["src"] or g["src"] or {}
                iv9 = candles.IV_SEC.get(s9.get("iv") or iv, iv_s) if r["ok"] else g["iv"]
                none9 = not r["ok"] and any(t9.get("why") == "no_data" for t9 in r["tried"])
                rows = buychart.bridge_rows(r["candles"] if r["ok"] else [], iv9, a, b, seed=g["last"]) if (r["ok"] or none9) else []
                if rows:
                    got = ("move" if gp["kind"] == "wait" else gp["kind"], s9, rows, iv9, g["unit"], (s9.get("fx") or {}).get("avg") or g["fx"])
            if got is None:
                continue
            kind, s9, rows, iv9, unit, fx = got
            short, label = buychart.bridge_label(kind, self._venue_name(s9.get("venue")) if kind == "wait" else job["s_name"],
                                                 self._venue_name((g["src"] or {}).get("venue")), opened=job["open_ts"] is not None)
            out.append({"from": a, "to": b, "kind": kind, "short": short, "label": label, "src": s9,
                        "candles": [r9[:5] + [job["val"](r9, unit, fx), r9[6], iv9] for r9 in rows], "volUnit": "val",
                        "filled": sum(1 for r9 in rows if r9[6] == 1)})
        return out
