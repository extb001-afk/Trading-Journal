import json
import lpdec


class LpMixin:

    ZERO_ADDR = "0x0000000000000000000000000000000000000000"

    def _lp_detect(self, chain: str, snap: dict, to, frm, mine: set):
        mgrs_all = self.lp_mgrs.get(chain) or {}
        stakers = {a9: m9 for a9, m9 in mgrs_all.items() if m9.get("proto") == "stake"}
        mgrs = {a9: m9 for a9, m9 in mgrs_all.items() if m9.get("proto") in lpdec.NFT_PROTOS}
        to_l = str(to or "").lower()
        tx = snap.get("tx") or {}
        sel9 = str(tx.get("raw_input") or tx.get("input") or "")[2:10].lower()
        dyn = self._lp_gauges(chain) if (to_l and to_l not in mgrs_all and str(frm or "").lower() in mine) else {}
        stk = stakers.get(to_l) or (dyn.get(to_l) if (dyn.get(to_l) or {}).get("npm") else None)
        if not mgrs:
            return self._lp_v2_detect(chain, snap, to_l, frm, mine, sel9, dyn) if mine else None
        mgr = to_l if to_l in mgrs else (str(stk.get("npm") or "").lower() or None if stk else None)
        moves = sorted({m for m in lpdec.nft_moves(snap, mgrs) if (m[2] in mine or m[3] in mine)})
        if mgr is None and moves:
            mgr = moves[0][0]
        if mgr is None:
            return self._lp_v2_detect(chain, snap, to_l, frm, mine, sel9, dyn)
        if str(frm or "").lower() not in mine and not moves:
            return None
        calls = lpdec.decode_lp_calls(tx.get("raw_input") or tx.get("input")) if (to_l == mgr or stk) else []
        mv = [m for m in moves if m[0] == mgr]
        mint = sorted({tid for _a, tid, f, t in mv if f == self.ZERO_ADDR and t in mine})
        burn = sorted({tid for _a, tid, f, t in mv if t == self.ZERO_ADDR and f in mine}
                      | {tid for act, tid, _ in calls if act == "BURN" and tid is not None})
        stake = {}
        for _a, tid, f, t in mv:
            if f in mine and t not in mine and t != self.ZERO_ADDR and (
                    t in stakers or (t == to_l and to_l not in mgrs_all and sel9 == lpdec.SEL_DEPOSIT_U256)):
                stake[str(tid)] = t
        unstake = {str(tid): f for _a, tid, f, t in mv if t in mine and f not in mine and f != self.ZERO_ADDR
                   and (f in stakers or f in dyn or f == to_l)}
        gone = sorted({tid for _a, tid, f, t in mv if f in mine and t not in mine and t != self.ZERO_ADDR
                       and str(tid) not in stake})
        hint = {}
        for h9 in snap.get("_lp_liq") or []:
            try:
                hint[int(h9[0])] = str(int(h9[1]))
            except (TypeError, ValueError, IndexError):
                continue
        if not mint and hint and any(a == "MINT" for a, _t, _l in calls):
            inc_ids = {t for a, t, _l in calls if a == "INCREASE" and t is not None}
            mint = sorted(set(hint) - inc_ids)
        liq = []
        for act, tid, l in calls:
            if act == "MINT" and tid is None and len(mint) == 1:
                tid = mint[0]
            if act in ("MINT", "INCREASE") and l is None and tid is not None and tid in hint:
                l = hint[tid]
            if act in ("MINT", "INCREASE", "DECREASE", "BURN"):
                liq.append([act, tid, (str(l) if l is not None else None)])
        dep_ids = sorted({tid for act, tid, _ in liq if act in ("MINT", "INCREASE") and tid is not None} | set(mint))
        wd_ids = sorted({tid for act, tid, _ in calls if act in ("DECREASE", "COLLECT", "BURN") and tid is not None}
                        | set(burn) | set(gone))
        ids = sorted(set(dep_ids) | set(wd_ids) | {tid for _a, tid, _f, _t in mv})
        mint_unk = any(act == "MINT" and tid is None for act, tid, _ in liq)
        who = str(frm or "").lower() if str(frm or "").lower() in mine else \
            next((t if t in mine else f for _a, _i, f, t in mv), "")
        unk_loc = f"lp:{chain}:{mgr}:?{who}"
        if len(dep_ids) == 1 and not mint_unk:
            dep_loc = lpdec.lp_location(chain, mgr, dep_ids)
        elif not dep_ids and not mint_unk and len(wd_ids) == 1:
            dep_loc = lpdec.lp_location(chain, mgr, wd_ids)
        elif not dep_ids:
            dep_loc = unk_loc
        else:
            dep_loc = f"lp:{chain}:{mgr}:multi"
        if stk and not ids:
            return None
        out9 = {"mgr": mgr, "proto": mgrs[mgr].get("proto"), "name": mgrs[mgr].get("name"),
                "ids": ids, "mint": mint, "burn": burn, "gone": gone,
                "dep_ids": dep_ids, "wd_ids": wd_ids,
                "actions": sorted({a for a, _, _ in calls}), "liq": liq, "who": who,
                "loc": lpdec.lp_location(chain, mgr, ids), "dep_loc": dep_loc, "unk_loc": unk_loc}
        if stake:
            out9["stake"] = stake
        if unstake:
            out9["unstake"] = unstake
        if stk:
            out9["via"] = to_l
        return out9

    def _lp_gauges(self, chain: str) -> dict:
        cache = self.__dict__.setdefault("_lp_learn_cache", {})
        if ("g", chain) in cache:
            return cache[("g", chain)]
        out = cache[("g", chain)] = {}
        for r in self.conn.execute("SELECT detail FROM tx_class WHERE chain=? AND event LIKE 'LP_%' AND detail LIKE '%stake%'",
                                   (chain,)).fetchall():
            try:
                lp = (json.loads(r["detail"] or "{}") or {}).get("lp") or {}
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue
            for _tid, g in (lp.get("stake") or {}).items():
                g = str(g or "").lower()
                if not g:
                    continue
                if lp.get("proto") == "v2":
                    out.setdefault(g, {"pair": lp.get("mgr")})
                else:
                    out.setdefault(g, {"npm": lp.get("mgr")})
        return out

    def _lp_v2_detect(self, chain: str, snap: dict, to_l: str, frm, mine: set, sel9: str, dyn: dict):
        who = str(frm or "").lower()
        if who not in mine:
            return None
        tts = []
        for tt in (snap.get("token_transfers") or []):
            tok = tt.get("token") or {}
            if (tok.get("type") or "ERC-20") != "ERC-20":
                continue
            ca = str(tok.get("address") or tok.get("address_hash") or "").lower()
            f3, t3 = tt.get("from"), tt.get("to")
            f3 = str((f3.get("hash") if isinstance(f3, dict) else f3) or "").lower()
            t3 = str((t3.get("hash") if isinstance(t3, dict) else t3) or "").lower()
            try:
                v3 = int((tt.get("total") or {}).get("value") or 0)
            except (TypeError, ValueError):
                continue
            if ca and v3 > 0:
                tts.append((ca, f3, t3, v3, tok.get("symbol") or ""))
        if not tts:
            return None
        Z = self.ZERO_ADDR
        known = self._lp_v2_tokens(chain)
        names = (self.lp_mgrs.get(chain) or {})
        parties = set(mine)
        rt9 = names.get(to_l) or {}
        if rt9.get("proto") == "v2_router" and rt9.get("verified"):
            parties.add(to_l)
        for T in sorted({c for c, f, t, v, _s in tts if f == Z and t in mine}):
            und = {c for c, f, t, v, _s in tts if t == T and c != T and f in parties}
            if len(und) >= 2:
                minted = sum(v for c, f, t, v, _s in tts if c == T and f == Z and t in mine)
                return self._lp_v2_dict(chain, T, who, "add", minted, tts, to_l, names)
        for T in sorted({c for c, f, t, v, _s in tts if t == Z and f == c}):
            mine_out = sum(v for c, f, t, v, _s in tts if c == T and f in mine and t == T)
            und = {c for c, f, t, v, _s in tts if f == T and c != T and t in parties}
            if mine_out > 0 and len(und) >= 2:
                return self._lp_v2_dict(chain, T, who, "remove", mine_out, tts, to_l, names)
        for c, f, t, v, _s in tts:
            if c in known and f in mine and t == to_l and t not in mine and sel9 == lpdec.SEL_DEPOSIT_U256:
                d9 = self._lp_v2_dict(chain, c, f, "stake", 0, tts, to_l, names)
                d9["stake"] = {f: t}
                return d9
            if c in known and t in mine and f == to_l and f in dyn:
                d9 = self._lp_v2_dict(chain, c, t, "unstake", 0, tts, to_l, names)
                d9["unstake"] = {t: f}
                return d9
        g9 = dyn.get(to_l) or {}
        if g9.get("pair") and any(t in mine and f == to_l for c, f, t, v, _s in tts):
            d9 = self._lp_v2_dict(chain, str(g9["pair"]).lower(), who, "claim", 0, tts, to_l, names)
            d9["via"] = to_l
            return d9
        return None

    def _lp_v2_tokens(self, chain: str) -> dict:
        cache = self.__dict__.setdefault("_lp_learn_cache", {})
        if ("t", chain) in cache:
            return cache[("t", chain)]
        out = cache[("t", chain)] = {}
        for r in self.conn.execute("SELECT detail FROM tx_class WHERE chain=? AND event LIKE 'LP_%' AND detail LIKE '%\"v2\"%'",
                                   (chain,)).fetchall():
            try:
                lp = (json.loads(r["detail"] or "{}") or {}).get("lp") or {}
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue
            if lp.get("proto") == "v2" and lp.get("mgr"):
                out[str(lp["mgr"]).lower()] = lp.get("name")
        return out

    @staticmethod
    def _lp_v2_name(sym: str, router_meta: dict) -> str:
        if router_meta.get("name"):
            return str(router_meta["name"])
        s9 = str(sym or "")
        if s9.startswith(("vAMM-", "sAMM-")):
            return "Aerodrome/Velodrome v2"
        if s9 == "Cake-LP":
            return "PancakeSwap v2"
        if s9 == "UNI-V2":
            return "Uniswap v2"
        if s9 == "SLP":
            return "SushiSwap v2"
        return "v2 LP"

    def _lp_v2_dict(self, chain, T, who, kind, amount, tts, to_l, names) -> dict:
        sym = next((s9 for c, f, t, v, s9 in tts if c == T and s9), "")
        rt = names.get(to_l) or {}
        name = self._lp_v2_name(sym, rt if rt.get("proto") == "v2_router" else {})
        liq = []
        if kind == "add":
            liq = [["MINT", who, str(int(amount))]]
        elif kind == "remove":
            liq = [["DECREASE", who, str(int(amount))]]
        loc = f"lp:{chain}:{T}:{who}"
        acts = {"add": ["MINT"], "remove": ["DECREASE"], "claim": ["COLLECT"], "stake": [], "unstake": []}[kind]
        return {"mgr": T, "proto": "v2", "name": name, "lpSym": sym, "lp_token": T, "ids": [who], "mint": [], "burn": [],
                "gone": [], "dep_ids": [who] if kind == "add" else [], "wd_ids": [who] if kind in ("remove", "claim") else [],
                "actions": acts, "liq": liq, "who": who, "loc": loc, "dep_loc": loc, "unk_loc": f"lp:{chain}:{T}:?{who}",
                "v2kind": kind}

    def _lp_held(self, loc_lp: str, before_ts=None) -> dict:
        held = {}
        q = "SELECT asset_id, qty_base FROM postings WHERE location=?" + (" AND event_ts <= ?" if before_ts is not None else "")
        args = (loc_lp, before_ts) if before_ts is not None else (loc_lp,)
        for r in self.conn.execute(q, args).fetchall():
            try:
                held[r["asset_id"]] = held.get(r["asset_id"], 0) + int(r["qty_base"])
            except (TypeError, ValueError):
                continue
        return {a: v for a, v in held.items() if v > 0}

    def _lp_liq_before(self, chain: str, mgr: str, tid, ts: int, txhash: str):
        tot = 0
        seen = False
        for r in self.conn.execute(
                "SELECT t.txhash, t.detail, (SELECT min(p.event_ts) FROM postings p WHERE p.source_kind='chain_tx'"
                "  AND p.source_ns=t.chain AND p.source_id=t.txhash) AS ets"
                " FROM tx_class t WHERE t.chain=? AND t.event LIKE 'LP_%' AND t.txhash != ?",
                (chain, txhash)).fetchall():
            if r["ets"] is None or int(r["ets"]) > ts:
                continue
            try:
                lp = (json.loads(r["detail"] or "{}") or {}).get("lp") or {}
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue
            if str(lp.get("mgr") or "") != mgr:
                continue
            for act, t9, l9 in lp.get("liq") or []:
                if t9 is None or lpdec.lp_tid(t9) != tid or act not in ("MINT", "INCREASE", "DECREASE"):
                    continue
                if l9 is None:
                    return None
                seen = True
                tot += int(l9) if act != "DECREASE" else -int(l9)
        return tot if seen else None

    def _lp_legs(self, chain: str, txhash: str, perw: dict, lp: dict, loc_of, ts: int) -> list:
        mgr = lp.get("mgr") or ""
        prefix = f"lp:{chain}:{mgr}"
        loc_unk = lp.get("unk_loc") or f"{prefix}:?{lp.get('who') or ''}"
        dep_loc = lp.get("dep_loc") or lp.get("loc") or loc_unk
        items = sorted(perw.items(), key=lambda kv: (kv[1] > 0, kv[0][1], kv[0][0] or ""))
        legs = []
        held = {}

        def H(b):
            if b not in held:
                held[b] = self._lp_held(b, before_ts=ts)
            return held[b]
        for (w, aid), v in items:
            if v < 0:
                legs.append(("move_out", aid, v, loc_of(w)))
                legs.append(("move_in", aid, -v, dep_loc))
                H(dep_loc)[aid] = H(dep_loc).get(aid, 0) + (-v)
        srcs = [f"{prefix}:{t}" for t in (lpdec.lp_tid(i) for i in (lp.get("wd_ids") or [])) if t is not None]
        if loc_unk not in srcs:
            srcs.append(loc_unk)
        dec_by_id = {}
        dec_unknown = set()
        for act, t9, l9 in lp.get("liq") or []:
            if act == "DECREASE" and lpdec.lp_tid(t9) is not None:
                if l9 is None:
                    dec_unknown.add(lpdec.lp_tid(t9))
                else:
                    dec_by_id[lpdec.lp_tid(t9)] = dec_by_id.get(lpdec.lp_tid(t9), 0) + int(l9)
        burn_ids = {t for t in map(lpdec.lp_tid, lp.get("burn") or []) if t is not None}
        exit_ids = burn_ids | {t for t in map(lpdec.lp_tid, lp.get("gone") or []) if t is not None}
        frac_hint = {str(k): v for k, v in (lp.get("frac") or {}).items()
                     if isinstance(v, (list, tuple)) and len(v) == 2 and int(v[1]) > 0}
        frac = {}
        for b in srcs:
            tid = lpdec.lp_tid(b.rsplit(":", 1)[1])
            if tid is None:
                frac[b] = None
                continue
            if tid in burn_ids:
                frac[b] = (1, 1)
            elif str(tid) in frac_hint:
                n9, d9 = (int(x) for x in frac_hint[str(tid)])
                frac[b] = (max(0, min(n9, d9)), d9)
            elif tid in dec_unknown:
                frac[b] = None
            elif tid in dec_by_id:
                d9 = dec_by_id[tid]
                lb = self._lp_liq_before(chain, mgr, tid, ts, txhash) if d9 > 0 else None
                if d9 == 0:
                    frac[b] = (0, 1)
                elif lb is None or lb <= 0:
                    frac[b] = None
                else:
                    frac[b] = (min(d9, lb), lb)
            elif tid in exit_ids or "COLLECT" in (lp.get("actions") or []):
                frac[b] = (0, 1)
            else:
                frac[b] = None
        release = {}
        rent9 = {int(a) for a in (lp.get("rent_aids") or [])}
        for b in srcs:
            fb = frac.get(b)
            hb = H(b)
            if fb is None:
                release[b] = dict(hb)
            else:
                n9, d9 = fb
                release[b] = {a: ((q * n9) // d9 if (a not in rent9 or n9 >= d9) else 0) for a, q in hb.items()}
        backed = {b: {} for b in srcs}
        for (w, aid), v in items:
            if v <= 0:
                continue
            rem = v
            for b in srcs:
                cap = release[b].get(aid, 0) - backed[b].get(aid, 0)
                back = min(rem, cap)
                if back > 0:
                    legs.append(("move_out", aid, -back, b))
                    legs.append(("move_in", aid, back, loc_of(w)))
                    backed[b][aid] = backed[b].get(aid, 0) + back
                    rem -= back
                if rem <= 0:
                    break
            if rem > 0:
                legs.append(("acq", aid, rem, loc_of(w)))
        gone_q = {}
        for b in srcs:
            if frac.get(b) is None:
                continue
            for aid in sorted(release[b]):
                conv = release[b][aid] - backed[b].get(aid, 0)
                if conv > 0:
                    legs.append(("disp", aid, -conv, b))
                    gone_q[(b, aid)] = gone_q.get((b, aid), 0) + conv
        for tid in sorted(exit_ids):
            b = f"{prefix}:{tid}"
            hb = H(b)
            for aid in sorted(hb):
                left = hb[aid] - backed.get(b, {}).get(aid, 0) - gone_q.get((b, aid), 0)
                if left > 0:
                    legs.append(("disp", aid, -left, b))
        return legs

    @staticmethod
    def _unknown_legs(perw: dict, loc_of) -> list:
        by = {}
        for (w, aid), v in perw.items():
            if v:
                by.setdefault(aid, []).append((w or "", v))
        legs = []
        for aid in sorted(by):
            ws = sorted(by[aid])
            mo = mi = min(-sum(v for _w, v in ws if v < 0), sum(v for _w, v in ws if v > 0))
            for w, v in ws:
                if v < 0:
                    m = min(-v, mo)
                    mo -= m
                    if m:
                        legs.append(("move_out", aid, -m, loc_of(w)))
                    if -v > m:
                        legs.append(("disp", aid, v + m, loc_of(w)))
                else:
                    m = min(v, mi)
                    mi -= m
                    if m:
                        legs.append(("move_in", aid, m, loc_of(w)))
                    if v > m:
                        legs.append(("acq", aid, v - m, loc_of(w)))
        return legs
