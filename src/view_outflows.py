from __future__ import annotations
import acct_norm
import bf_engine
import common
import db as dbm
import depaddr
import flow_trace
import json
import lpdec
import ops_requests
import os
import outflow_match
import rawtx_cache
import salelink
import spamguard
import time
import xchain_match
import xfer_match
from datetime import datetime
from decimal import Decimal
from decimal import InvalidOperation
from view_alerts import _append_alert
from view_common import CHAIN_NAME
from view_common import EPS
from view_common import KST
from view_common import OF_BASIS_KO
from view_common import STABLE_GROUPS
from view_common import TRANSIT_COVER_MARGIN_S
from view_common import TRANSIT_COVER_MAX_H
from view_common import TRANSIT_DEFAULT_H
from view_common import TRANSIT_NET_H
from view_common import TRANSIT_OWN_H
from view_common import _ex_stable_sym
from view_common import _f
from view_hero import _ago_ko
from view_offc import _offc_excl
from view_offc import _offc_on
from view_offc import _offc_tx
from view_txkey import _txk
from view_txkey import _wd_txk
import logging
import calcguard

log = logging.getLogger('tj-web')


class OutflowsMixin:

    def _backfill_since_view(self, conn=None):
        try:
            req = common.read_json(self.BF_REQ_PATH, {}) if os.path.exists(self.BF_REQ_PATH) else {}
        except BaseException as _cg9:
            calcguard.swallowed("view_outflows:OutflowsMixin._backfill_since_view", _cg9)
            req = {}
        months = float(self.cfg.get("backfill_months") or 5)
        base_t0 = int(time.time() - months * 30 * 86400)
        secs = sorted(k for k, v in (self.cfg.get("chains") or {}).items() if isinstance(v, dict))
        secs += [x for x in ("bsc", "sol") if isinstance(self.cfg.get(x), dict)] + ["upbit"]
        per = {}
        for sec in secs:
            t9 = bf_engine.SINCE.target(sec)
            if t9:
                per[sec] = datetime.fromtimestamp(t9, KST).strftime("%Y-%m-%d")
        jobs = []
        for unit, items in bf_engine.read_status().items():
            if not isinstance(items, dict) or unit.startswith("_"):
                continue
            for key, it in items.items():
                if isinstance(it, dict) and (key.endswith(":extend") or it.get("phase") == "extend"):
                    jobs.append({"key": key, "unit": unit, "phase": it.get("phase"), "done": it.get("done"),
                                 "total": it.get("total"), "eta": it.get("eta_sec"), "note": it.get("note"),
                                 "updated": it.get("updated")})
        meta = {}
        try:
            c9 = conn if conn is not None else dbm.open_db(common.DB_PATH, readonly=True)
            try:
                for r9 in c9.execute("SELECT k, v FROM meta WHERE k IN ('ext_rebuilt_at', 'ext_rebuild_fail_at', 'ext_rebuild_fails',"
                                     " 'ext_rebuild_last_error', 'ext_rebuild_started_at', 'rebuild_not_before', 'ext_rebuild_fail_code',"
                                     " 'ext_rebuild_fail_stage', 'ext_rebuild_fail_code_at')"
                                     " OR k LIKE 'ext_prewindow:%'").fetchall():
                    meta[r9["k"]] = r9["v"]
            finally:
                if c9 is not conn:
                    c9.close()
        except Exception as _cg9:
            calcguard.swallowed("view_outflows:OutflowsMixin._backfill_since_view", _cg9)
            pass
        g9 = bf_engine.SINCE.target(None)
        fc9 = meta.get("ext_rebuild_fail_code") if meta.get("ext_rebuild_fails") and meta.get("ext_rebuild_fail_at") \
            and meta.get("ext_rebuild_fail_code_at") == meta.get("ext_rebuild_fail_at") else None
        return {"windowStart": datetime.fromtimestamp(min(base_t0, g9) if g9 else base_t0, KST).strftime("%Y-%m-%d"),
                "defaultStart": datetime.fromtimestamp(base_t0, KST).strftime("%Y-%m-%d"), "months": months,
                "request": req if isinstance(req, dict) else {}, "per": per, "sections": secs, "jobs": jobs,
                "pendingRebuild": {k[len("ext_prewindow:"):]: v for k, v in meta.items() if k.startswith("ext_prewindow:")},
                "rebuiltAt": int(float(meta["ext_rebuilt_at"])) if meta.get("ext_rebuilt_at") else None,
                "rebuildFailAt": int(float(meta["ext_rebuild_fail_at"])) if meta.get("ext_rebuild_fail_at") else None,
                "rebuildFails": int(meta.get("ext_rebuild_fails") or 0),
                "rebuildLastError": (meta.get("ext_rebuild_last_error") or None),
                "rebuildFailCode": fc9 or None,
                "rebuildFailLabel": ops_requests.REBUILD_FAIL_LABEL.get(fc9) if fc9 else None,
                "rebuildDiskRetry": fc9 == "resource_disk" and meta.get("ext_rebuild_fail_stage") == "precheck",
                "rebuildRunning": bool(meta.get("ext_rebuild_started_at")) and (self.cfg.get("backfill") or {}).get("auto_rebuild") is not False
                and time.time() - float(meta.get("ext_rebuild_started_at") or 0)
                < float((self.cfg.get("backfill") or {}).get("rebuild_timeout_sec") or 5400) + 600,
                "rebuildNotBefore": int(float(meta["rebuild_not_before"])) if meta.get("rebuild_not_before") and
                float(meta["rebuild_not_before"]) > time.time() else None}

    @staticmethod
    def _dec_core(e):
        return {k9: v9 for k9, v9 in e.items() if k9 not in ("memo", "ts")} if isinstance(e, dict) else None

    def of_memo_only(self, a, old, new) -> bool:
        co, cn = self._dec_core(old), self._dec_core(new)
        if co is not None and co == cn:
            return True
        if co in (None, {}) and cn in (None, {}):
            return a not in ((self.__dict__.get("_of_auto") or {}).get("proven") or {})
        return False

    def of_row_patch(self, a, new, old) -> dict:
        e9 = new if isinstance(new, dict) else {}
        o9 = old if isinstance(old, dict) else {}
        v9 = e9.get("verdict")
        st0 = (self.__dict__.get("_outflow_status") or {}).get(a)
        still = a in (self.__dict__.get("_outflow_still") or ())
        st = None
        if v9 == "external":
            st = "external"
        elif v9 == "exchange":
            st = "exchange_applying" if still else "exchange"
        elif v9 == "own":
            st = "own_restart_needed" if still else "own"
        elif self._dec_core(old) == self._dec_core(new) or (self._dec_core(old) in (None, {}) and self._dec_core(new) in (None, {})):
            st = st0
        elif v9 == "clear" and e9.get("ret") is True and o9.get("ret") is not True and not e9.get("noAuto") and not o9.get("noAuto") \
                and o9.get("verdict") in (None, "clear") and st0 in ("pending", "bridge_untracked"):
            st = "returned"
        out = {"status": st, "verdict": v9 or None, "category": e9.get("category"), "memo": e9.get("memo"), "alias": e9.get("alias"),
               "noAuto": bool(e9.get("noAuto")), "decidedTs": e9.get("ts"),
               "excludeLegs": [str(k0.get("key") if isinstance(k0, dict) else k0) for k0 in (e9.get("excludeLegs") or []) if isinstance(k0, (str, dict))][:200]}
        if st is not None:
            out["retOk"] = bool(e9.get("ret") is True and st == "returned")
        if st == "own_restart_needed":
            try:
                import wallet_register as _wr9
                out["applyWait"] = bool(_wr9.auto_reload_alive() and a in _wr9.pending_addrs())
            except Exception as _cg9:
                calcguard.swallowed("view_outflows:OutflowsMixin.of_row_patch", _cg9)
                out["applyWait"] = False
        if e9.get("exchange"):
            out["exchange"] = e9["exchange"]
        return out

    def outflow_decisions(self) -> dict:
        d = common.read_json(self.OUTFLOW_PATH, {}) if os.path.exists(self.OUTFLOW_PATH) else {}
        dd = d.get("decisions") if isinstance(d, dict) else None
        return dd if isinstance(dd, dict) else {}

    @staticmethod
    def _of_key(r) -> str:
        try:
            sk = r["source_kind"]
        except (IndexError, KeyError):
            sk = "exchange" if str(r["location"] or "").startswith("exchange:") else "chain_tx"
        return f"{sk}|{r['source_ns']}|{r['source_id']}|{int(r['leg_seq'])}"

    @staticmethod
    def _of_asset(r) -> str:
        return f"{r['kind']}:{r['chain'] or ''}:{str(r['address'] or r['symbol'] or '').lower()}"

    @staticmethod
    def _of_stable_row(r) -> bool:
        return bool((r["gname"] or "") in STABLE_GROUPS
                    or (r["kind"] == "exchange_currency" and _ex_stable_sym(r["symbol"])))

    def _of_where(self, w: str) -> str:
        w = str(w or "")
        if w.startswith("ex:"):
            return self.EX_NAME_KO.get(w[3:], w[3:]) if isinstance(getattr(self, "EX_NAME_KO", None), dict) else w[3:]
        if w.startswith("w:"):
            ad9 = w[2:]
            k9 = ad9.lower() if ad9.startswith("0x") else ad9
            for w9 in self._hist_wallets():
                if isinstance(w9, dict) and w9.get("address"):
                    a9 = str(w9["address"])
                    if (a9.lower() if a9.startswith("0x") else a9) == k9 and w9.get("label"):
                        return str(w9["label"])
            return ad9[:6] + "…" + ad9[-4:] if len(ad9) > 12 else ad9
        return w

    def _of_sale_cands(self, a, first_ts, stable_syms, px_of=None, skip=()) -> list:
        cl9 = getattr(self, "_of_claims", None) or {}
        rr9 = getattr(self, "_risk_reasons", None) or {}
        taken9 = {str(l9.get("key")) for v9 in self.outflow_decisions().values() if isinstance(v9, dict) for l9 in (v9.get("links") or [])
                  if isinstance(l9, dict)}
        out = []
        for c9 in (getattr(self, "_of_cands", None) or {}).values():
            if not (first_ts <= int(c9["ts"]) <= first_ts + self.OF_CAND_WINDOW) or c9["key"] in cl9 or c9["key"] in taken9 or c9.get("sale"):
                continue
            if c9["key"] in skip:
                continue
            if c9.get("gid") in rr9:
                continue
            q9 = float(c9.get("qty") or 0)
            if c9.get("stable"):
                if str(c9.get("sym") or "").upper() not in stable_syms or q9 < 1:
                    continue
            else:
                p9 = float(px_of(c9.get("gid")) or 0) if px_of else 0.0
                if q9 <= 0 or (p9 > 0 and q9 * p9 < 1):
                    continue
            out.append(c9["key"])
        return sorted(out)

    def _sale_cand_notify(self, cands: dict):
        if self.prefs().get("sale_cand_alert") is False:
            return
        first9 = not os.path.exists(self.SALE_CAND_PATH)
        seen = {} if first9 else (common.read_json(self.SALE_CAND_PATH, {}) or {})
        if not isinstance(seen, dict):
            seen = {}
        d9 = seen.setdefault("dests", {})
        changed = first9
        out9 = []
        for a, keys in sorted(cands.items()):
            old9 = set(d9.get(a) or [])
            new9 = [k9 for k9 in keys if k9 not in old9]
            if not new9:
                continue
            if not first9:
                out9.append({"ts": int(time.time()), "kind": "SALE_CAND", "sym": "",
                             "text": f"🔗 세일 참가금 {salelink.name_addr(a, self.outflow_decisions().get(a))} 에 연결할 후보가 생겼어요 — 새 {len(new9)}건"
                                     f"(모두 {len(keys)}건) · 보낸 내역 › 정리된 내역에서 '받은 것과 연결'"})
            d9[a] = sorted(old9 | set(keys))
            changed = True
        if changed:
            seen["v"] = 1
            common.atomic_write_json(self.SALE_CAND_PATH, seen)
        for x9 in out9:
            _append_alert(x9)
            log.info("세일 참가금 후보 알림 적재: %s", x9["text"][:40])

    def _of_manual_resolve(self, rows) -> dict:
        dec = self.outflow_decisions()
        want = {a: [l for l in (v.get("links") or []) if isinstance(l, dict)] for a, v in dec.items()
                if isinstance(v, dict) and v.get("verdict") == "external" and isinstance(v.get("links"), list) and v.get("links")}
        out = {"dests": {}, "pids": set(), "dup": set(), "claims": {}}
        self._of_claims = out["claims"]
        if not want:
            return out
        by_key, by_src = {}, {}
        for r in rows:
            if r["leg_kind"] not in ("acq", "move_in") or r["event"] not in self.OF_IN_EVENTS:
                continue
            k9 = self._of_key(r)
            by_key[k9] = r
            by_src.setdefault((k9.rsplit("|", 1)[0], self._of_asset(r), str(r["qty_base"])), []).append(r)
        def same(l9, r9):
            return (self._of_asset(r9) == str(l9.get("asset") or "") and str(r9["qty_base"]) == str(l9.get("qb") or "")
                    and self._of_where_raw(r9) == str(l9.get("where") or ""))
        order9 = sorted(((int(l9.get("lts") or 0), a, i9, l9) for a, links in want.items() for i9, l9 in enumerate(links[:self.OF_LINK_MAX])),
                        key=lambda x9: x9[:3])
        res9 = {}
        for _lt, a, i9, l9 in order9:
            k9 = str(l9.get("key") or "")
            r9 = by_key.get(k9)
            if r9 is not None and not same(l9, r9):
                r9 = None
            if r9 is None and k9.count("|") >= 3:
                c9 = [r0 for r0 in by_src.get((k9.rsplit("|", 1)[0], str(l9.get("asset") or ""), str(l9.get("qb") or "")), []) if same(l9, r0)]
                r9 = c9[0] if len(c9) == 1 else None
            if r9 is not None:
                ck9 = self._of_key(r9)
                if ck9 in out["claims"]:
                    out["dup"].add((a, k9))
                    r9 = None
                else:
                    out["claims"][ck9] = (a, k9, l9.get("kind"))
            res9[(a, i9)] = r9
        for a, links in want.items():
            lst = []
            for i9, l9 in enumerate(links[:self.OF_LINK_MAX]):
                r9 = res9.get((a, i9))
                lst.append((l9, r9))
                if r9 is not None and l9.get("kind") == "tokens":
                    out["pids"].add(r9["posting_id"])
            out["dests"][a] = lst
        return out

    def _of_key_cur(self, a, l9) -> str:
        k9 = str((l9 or {}).get("key") or "")
        for ck9, own9 in (getattr(self, "_of_claims", None) or {}).items():
            if own9[0] == a and own9[1] == k9:
                return ck9
        return k9

    @staticmethod
    def _of_where_raw(r) -> str:
        loc9 = str(r["location"] or "")
        if loc9.startswith("wallet:"):
            p9 = loc9.split(":")
            return f"w:{p9[2]}" if len(p9) >= 3 and p9[2] else "w:?"
        if loc9.startswith("exchange:"):
            return "ex:" + loc9.split(":")[1]
        return ""

    def _of_manual_lots(self, conn, of_man: dict, krw_of, own_dep9, rt_pair) -> tuple:
        lots, links, state = {}, {}, {}
        for a, lst in (of_man.get("dests") or {}).items():
            refund = refund_krw = Decimal(0)
            rgids9 = set()
            st9 = {"paidUsd": None, "refundUsd": Decimal(0), "costUsd": None, "links": {}}
            toks = []
            for l9, r9 in lst:
                k9 = str(l9.get("key") or "")
                if r9 is None:
                    st9["links"][k9] = {"st": "dup" if (a, k9) in (of_man.get("dup") or ()) else "missing"}
                    continue
                q9 = self._norm(r9)
                stab9 = self._of_stable_row(r9)
                if l9.get("kind") == "refund":
                    if not stab9 or q9 <= 0:
                        st9["links"][k9] = {"st": "invalid"}
                        continue
                    refund += q9
                    refund_krw += krw_of(q9, int(r9["event_ts"]))
                    rgids9.add(("st", self._gsym(r9).upper()))
                    st9["links"][k9] = {"st": "ok", "usd": q9}
                    continue
                if stab9 or q9 <= 0:
                    st9["links"][k9] = {"st": "invalid"}
                    continue
                exd9 = str(r9["location"] or "").startswith("exchange:")
                if (exd9 and r9["source_id"] in own_dep9) or (not exd9 and (r9["source_ns"], r9["source_id"]) in rt_pair):
                    st9["links"][k9] = {"st": "other_path"}
                    continue
                toks.append((k9, r9, q9))
            st9["refundUsd"] = refund
            if toks:
                gids9 = {(r9["group_id"] or -r9["asset_id"]) for _k, r9, _q in toks}
                w9 = [q9 for _k, _r, q9 in toks]
                if len(gids9) > 1:
                    px9 = []
                    for _k, r9, q9 in toks:
                        try:
                            p9 = float(self.px.candle_usd(str(r9["symbol"] or ""), int(r9["event_ts"]) * 1000) or 0)
                        except Exception as _cg9:
                            calcguard.swallowed("view_outflows:OutflowsMixin._of_manual_lots", _cg9)
                            p9 = 0.0
                        px9.append(p9)
                    if all(p9 > 0 for p9 in px9):
                        w9 = [q9 * Decimal(str(p9)) for (_k, _r, q9), p9 in zip(toks, px9)]
                tw9 = sum(w9, Decimal(0))
                lid = "of:" + a
                lots[lid] = {"id": lid, "ratio": Decimal(1), "sym": "", "manual": a, "refund": refund, "refund_krw": refund_krw,
                             "excl": [x0 for x0 in (((self.outflow_decisions().get(a) or {}).get("excludeLegs")) or []) if isinstance(x0, (dict, str))],
                             "t_first": min(int(r9["event_ts"]) for _k, r9, _q in toks), "n": len(toks), "fin": None,
                             "refund_assets": rgids9, "tsym": "/".join(sorted({str(r9["symbol"] or "?").upper() for _k, r9, _q in toks}))}
                for (k9, r9, q9), wi in zip(toks, w9):
                    exd9 = str(r9["location"] or "").startswith("exchange:")
                    links[r9["posting_id"]] = {"lot": lid, "take": q9, "qty": q9, "unit": None, "unit_krw": None, "cost": None,
                                               "wsh": (wi / tw9) if tw9 > 0 else Decimal(1) / len(toks),
                                               "ts": int(r9["event_ts"]), "ref": str(r9["source_id"]), "kind": "ex" if exd9 else "chain",
                                               "sender": "", "manual": a}
                    st9["links"][k9] = {"st": "pending", "pid": r9["posting_id"]}
            state[a] = st9
        self._of_man_state = state
        return lots, links

    def _known_addrs(self):
        k = {}

        def put(a, kind, name):
            if a:
                a9 = a.lower() if str(a).startswith("0x") else a
                l9 = k.setdefault(a9, [])
                if (kind, name) not in l9:
                    l9.append((kind, name))
        for w in self._hist_wallets():
            put(w.get("address"), "my_wallet", w.get("label") or "내 지갑")
        fx_name = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "kucoin": "쿠코인", "gate": "게이트",
                   "bithumb": "빗썸", "upbit": "업비트", "hyperliquid": "Hyperliquid"}
        for e in self.cfg.get("exchange_addresses") or []:
            put(e.get("address"), "exchange_deposit", fx_name.get(e.get("exchange"), e.get("exchange")) + " 입금주소(내 계정)")
        try:
            for a9, labs in depaddr.hint_index().items():
                for _ex9, lab9 in labs:
                    put(a9, "exchange_deposit", lab9)
        except Exception as _cg9:
            calcguard.swallowed("view_outflows:OutflowsMixin._known_addrs", _cg9)
            pass
        for a9 in common.seed_json("bridge_contracts.json", [], base_dir=common.BASE_DIR, strict=True) or []:
            put(a9, "bridge", "브릿지 컨트랙트")
        for ch9, mg9 in lpdec.lp_managers(common.BASE_DIR).items():
            for a9, m9 in mg9.items():
                if not str(a9).startswith("0x"):
                    continue
                put(a9, "lp", f"{m9.get('name') or 'LP'} " + {"stake": "스테이킹(팜)", "v2_router": "라우터"}.get(m9.get("proto"), "포지션 관리자"))
                if m9.get("pool_manager"):
                    put(m9["pool_manager"], "lp", f"{m9.get('name') or 'LP'} PoolManager")
        return k

    def _bridge_labels(self) -> dict:
        out = {}
        try:
            for a9 in common.seed_json("bridge_contracts.json", [], base_dir=common.BASE_DIR, strict=True) or []:
                if isinstance(a9, str):
                    out[a9.lower()] = {"name": "브릿지 컨트랙트", "chain": None}
            d9 = common.seed_json("bridge_labels.json", {}, base_dir=common.BASE_DIR, strict=True) or {}
            for a9, v9 in d9.items():
                if isinstance(v9, dict) and v9.get("name") and not a9.startswith("_"):
                    out[a9.lower() if a9.startswith("0x") else a9] = {"name": str(v9["name"])[:80], "chain": v9.get("chain")}
        except BaseException as _cg9:
            calcguard.swallowed("view_outflows:OutflowsMixin._bridge_labels", _cg9)
            pass
        return out

    def _xfer_links(self, conn, onchain_txids, linked_dep_uuids, prefs, origin_cache=None, origin_pending=None) -> dict:
        wds, deps = [], []
        offc9, offx9 = _offc_on(prefs), _offc_excl(prefs)
        for rf in conn.execute("SELECT exchange, kind, uuid, payload FROM raw_ex WHERE kind IN ('withdraw','deposit')"
                               " GROUP BY exchange, kind, uuid HAVING revision = MAX(revision)").fetchall():
            try:
                pw = json.loads(rf["payload"])
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(pw, dict):
                continue
            if (rf["exchange"] in offc9 and _offc_tx(pw.get("txid"))
                    and not (rf["kind"] == "withdraw" and pw.get("address")
                             and xfer_match.norm_addr(pw.get("address")) in offx9.get(rf["exchange"], ()))):
                continue
            if str(pw.get("currency") or "").upper() == "KRW":
                continue
            st = str(pw.get("state") or "").upper()
            row = dict(pw, exchange=rf["exchange"], uuid=rf["uuid"])
            if rf["kind"] == "withdraw" and st == "DONE":
                wds.append(row)
            elif rf["kind"] == "deposit" and st == "ACCEPTED":
                deps.append(row)
        own = {xfer_match.norm_addr(w9.get("address")) for w9 in self._hist_wallets() if w9.get("address")}
        own_ch = {}
        for w9 in (self.cfg.get("wallets") or []):
            if w9.get("address"):
                own_ch.setdefault(xfer_match.norm_addr(w9["address"]), set()).add(str(w9.get("chain") or "").lower())

        def own_tracked(w):
            a9 = xfer_match.norm_addr(w.get("address"))
            if a9 not in own_ch:
                return False
            ch9 = depaddr.chain_of(w.get("network") or w.get("net_type"), w.get("currency"), a9)
            return bool(ch9) and ch9 in own_ch[a9]
        store_ok = os.path.exists(depaddr.store_path())
        dest_memo = {}

        def dest_of(w):
            if not store_ok:
                return None
            a = str(w.get("address") or "")
            k9 = (a, w.get("tag") or "", w.get("network") or w.get("net_type") or "", w.get("currency") or "")
            if k9 not in dest_memo:
                ch = depaddr.chain_of(w.get("network") or w.get("net_type"), w.get("currency"), a)
                hit = depaddr.lookup(ch, a, w.get("tag") or w.get("memo") or None, w.get("currency"))
                dest_memo[k9] = hit.get("exchange") if (hit and not hit.get("ambiguous") and not hit.get("tag_required")
                                                        and hit.get("match") in ("exact", "family", "address")) else None
            return dest_memo[k9]
        oc = origin_cache or {}

        def origin_of(d):
            t9 = outflow_match.norm_txid(d.get("txid")) if d.get("txid") else ""
            f9 = (oc.get(t9) or {}).get("from") if t9 else None
            return xfer_match.norm_addr(f9) if f9 else None
        if origin_pending is not None:
            for t9 in xfer_match.hop_candidates(wds, deps, dest_of, own_tracked):
                if t9.startswith("0x") and len(t9) == 66 and t9 not in oc:
                    origin_pending.add(t9)
        off = {str(x) for x in (prefs.get("xfer_link_off") or [])}
        args9 = (wds, deps, frozenset(onchain_txids), frozenset(linked_dep_uuids))
        links = xfer_match.match(*args9, frozenset(off), dest_of, origin_of, own_tracked)
        self._xfer_links_all = xfer_match.match(*args9, frozenset(), dest_of, origin_of, own_tracked) if off else links
        self._xfer_links_last = links
        rows9 = []
        for w in wds:
            a = w.get("address")
            if not a:
                continue
            na = xfer_match.norm_addr(a)
            cls9 = ("wallet" if own_tracked(w) else "wallet_untracked") if na in own else ("exchange" if dest_of(w) else "unknown")
            rows9.append({"uuid": w["uuid"], "ex": w["exchange"], "addr": na, "cls": cls9, "sym": str(w.get("currency") or "").upper(),
                          "qty": w.get("amount"), "network": w.get("network") or "", "txid": outflow_match.norm_txid(w.get("txid")) if w.get("txid") else "",
                          "ts": xfer_match._ts(w.get("created_at")) or 0, "dest_ex": dest_of(w) if cls9 == "exchange" else None})
        self._wd_dest_rows = rows9

        def cls_of(w):
            a = w.get("address")
            if not a:
                return None, None
            if xfer_match.norm_addr(a) in own:
                return ("wallet" if own_tracked(w) else "wallet_untracked"), None
            d9 = dest_of(w)
            return ("exchange", d9) if d9 else ("unknown", None)
        self._wd_cls_fn = cls_of
        return links

    @staticmethod
    def _transit_loc(e, now) -> dict:
        age = _ago_ko(max(0, float(now) - float(e["ts"])))
        w = f"{e['src']} → {e['dst']} 전송 중" if e.get("dst") else f"{e['src']} 출금 → 도착 확인 대기"
        cover = e.get("why") == "cover"
        sub = [f"출금 {age}째"]
        if cover:
            sub.append("받는 쪽 기록 확인 중")
        if e.get("net"):
            sub.append(f"{e['net']} 네트워크")
        sub.append("내 계정으로 이동 중" if e.get("own") else ("받는 주소 " + xfer_match.short(e["addr"]) if e.get("addr") else "받는 주소 미상"))
        return {"w": w, "sub": " · ".join(sub), "qty": float(e["qty"]),
                "tr": {"from": e["src"], "to": e.get("dst"), "since": int(e["ts"]), "until": int(e["until"]), "net": e.get("net") or "",
                       "own": bool(e.get("own")), "txid": e.get("txid_raw") or "", "addr": e.get("addr") or "", "uuid": str(e["uuid"]),
                       "cover": cover}}

    @staticmethod
    def _wd_key(ex, uuid) -> str:
        return f"wd:{ex}:{uuid}"

    def _transit_hours(self, net, cur=None):
        tc = self.cfg.get("transit") if isinstance(self.cfg.get("transit"), dict) else {}
        n = str(net or "").strip().upper()
        hm = {str(k).upper(): v for k, v in (tc.get("hours") or {}).items()} if isinstance(tc.get("hours"), dict) else {}
        for k in (n, n.split("-")[-1].strip() if "-" in n else None):
            if k and k in hm:
                return float(hm[k])
            if k and k in TRANSIT_NET_H:
                return float(TRANSIT_NET_H[k])
        ch = depaddr.chain_of(n, cur) if n else None
        if ch:
            return 3.0 if ch == "eth" else 2.0
        return float(tc.get("default_hours", TRANSIT_DEFAULT_H))

    def _wd_transit_resolve(self, wd_tr, rows, wd_raw, fx_transit, xf_links, up_dep_uid_tx, exf_dep_tx, G, skip_tx=frozenset(), now=None,
                           skip_deps=frozenset(), ton_h2u=None):
        now = time.time() if now is None else float(now)
        tc = self.cfg.get("transit") if isinstance(self.cfg.get("transit"), dict) else {}
        own_h = float(tc.get("own_hours", TRANSIT_OWN_H))
        try:
            dec = self.outflow_decisions() or {}
        except Exception as _cg9:
            calcguard.swallowed("view_outflows:OutflowsMixin._wd_transit_resolve", _cg9)
            dec = {}
        cls_fn = getattr(self, "_wd_cls_fn", None)
        fx_name = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "kucoin": "쿠코인", "gate": "게이트", "bithumb": "빗썸", "upbit": "업비트", "hyperliquid": "Hyperliquid"}
        wl9 = {}
        for w9 in self._hist_wallets():
            if isinstance(w9, dict) and w9.get("address"):
                wl9[xfer_match.norm_addr(w9["address"])] = str(w9.get("label") or "")
        arr_tx, dep_ts, cands = {}, {}, []
        for r0 in rows:
            ev0 = r0["event"]
            if r0["leg_kind"] not in ("move_in", "acq"):
                continue
            if ev0 in ("EX_DEPOSIT", "EXF_DEPOSIT"):
                u0 = r0["source_id"]
                ex0 = (r0["location"] or "").split(":")[-1]
                dep_ts.setdefault(u0, int(r0["event_ts"]))
                t0 = up_dep_uid_tx.get(u0) if ex0 == "upbit" else exf_dep_tx.get((ex0, u0))
            elif ev0 in ("TRANSFER_IN", "PROGRAM_IN"):
                t0 = r0["source_id"]
            else:
                continue
            k0 = _txk(t0) if t0 else ""
            if k0:
                arr_tx.setdefault(k0, int(r0["event_ts"]))
            if (ev0 in ("EX_DEPOSIT", "EXF_DEPOSIT") and not (k0 and k0 in skip_tx)
                    and u0 not in skip_deps and u0 not in (xf_links or {})):
                gid0 = r0["group_id"] or -r0["asset_id"]
                try:
                    q0 = self._norm(r0)
                except (TypeError, ValueError, InvalidOperation):
                    continue
                cands.append({"ts": int(r0["event_ts"]), "sym": str((G.get(gid0) or {}).get("sym") or r0["symbol"] or "").upper(),
                              "qty": q0, "used": False})
        link_wd = {}
        for du9, xl9 in (xf_links or {}).items():
            if du9 in dep_ts and xl9.get("wd_uuid"):
                link_wd.setdefault(xl9["wd_uuid"], dep_ts[du9])
        for i9 in (getattr(self, "_hl_bridge_free", None) or ()):
            cands.append({"ts": int(i9["ts"]), "sym": "USDC", "qty": Decimal(str(i9["qty"])), "used": False, "ex": "hyperliquid"})
        cands.sort(key=lambda c9: c9["ts"])
        tx_owners = {}
        for w9 in wd_tr:
            p9 = wd_raw.get((w9["ex"], w9["uuid"])) or {}
            if str(p9.get("state") or "").upper() in ("CANCELED", "CANCELLED", "REJECTED", "FAILED"):
                continue
            t9 = _wd_txk(str(p9.get("txid") or w9.get("txid") or "").strip(), p9.get("network") or p9.get("net_type"), ton_h2u)
            if t9 and not t9.startswith("amt:"):
                tx_owners.setdefault(t9, []).append(w9)
        out = []
        cover_memo = {}
        for e in sorted(wd_tr, key=lambda x9: (x9["ts"], str(x9["uuid"]))):
            p = wd_raw.get((e["ex"], e["uuid"])) or {}
            st = str(p.get("state") or "").upper()
            addr = str(p.get("address") or "").strip()
            na = xfer_match.norm_addr(addr) if addr else ""
            net = str(p.get("network") or p.get("net_type") or "").strip()
            txr = str(p.get("txid") or "").strip()
            done = xfer_match._ts(p.get("done_at")) or 0
            start = max(int(e["ts"]), int(done or 0))
            cls, dest_ex = (cls_fn(dict(p, exchange=e["ex"])) if (cls_fn and addr) else (None, None))
            key = na if na else self._wd_key(e["ex"], e["uuid"])
            d9 = dec.get(key) if isinstance(dec.get(key), dict) else {}
            vd = d9.get("verdict")
            own = cls in ("wallet", "exchange") or vd in ("own", "exchange")
            win = own_h if own else self._transit_hours(net, p.get("currency"))
            dst = None
            if cls == "exchange" and dest_ex:
                dst = fx_name.get(dest_ex, dest_ex)
            elif cls in ("wallet", "wallet_untracked"):
                dst = (wl9.get(na) or "내 지갑") if str(wl9.get(na) or "").rstrip().endswith("지갑") else f"{wl9.get(na) or '내'} 지갑"
            elif vd == "exchange":
                dst = fx_name.get(d9.get("exchange"), d9.get("exchange") or "거래소")
            elif vd == "own":
                dst = str(d9.get("alias") or "내 지갑")
            dex9 = dest_ex if (cls == "exchange" and dest_ex) else (d9.get("exchange") if vd == "exchange" else None)
            e.update({"addr": addr, "net": net, "txid_raw": txr, "start": start, "until": int(start + win * 3600), "own": own, "dex": dex9,
                      "cls": cls, "dst": dst, "key": key, "verdict": vd, "arr_ts": None, "state": None, "why": None,
                      "src": fx_name.get(e["ex"], e["ex"]), "fee": p.get("fee")})
            if st in ("CANCELED", "CANCELLED", "REJECTED", "FAILED"):
                e["state"] = "cancel"
                out.append(e)
                continue
            tk = _wd_txk(txr or (e["txid"] if e.get("txid") and not str(e["txid"]).startswith("amt:") else ""), net, ton_h2u) or ""
            owners9 = tx_owners.get(tk, ())
            f9 = fx_transit.get(e.get("txid"))
            if len(owners9) > 1 and (
                    tk in arr_tx or any(w9["uuid"] in link_wd for w9 in owners9)
                    or (f9 and f9.get("qty") and f9["qty"] > 0
                        and f9["left"] < f9["qty"] * Decimal("0.999999"))):
                e["state"], e["why"] = "out", "txid_ambiguous"
                out.append(e)
                continue
            at = arr_tx.get(tk) if tk else None
            if at is None:
                at = link_wd.get(e["uuid"])
            if at is None and e.get("txid"):
                f4 = fx_transit.get(e["txid"])
                if f4 and f4.get("qty") and f4["qty"] > 0 and f4["left"] < f4["qty"] * Decimal("0.999999"):
                    at = int(e["ts"])
            if at is not None:
                e["state"], e["arr_ts"] = "arrived", int(at)
            elif vd == "external":
                e["state"], e["why"] = "out", "external"
            elif now < e["until"]:
                e["state"] = "pending"
            elif self._wd_cover_wait(e, now, cover_memo, tc):
                e["state"], e["why"] = "pending", "cover"
            else:
                e["state"], e["why"] = "out", "expired"
            out.append(e)
        fits, claims = {}, {}
        for i9, e9 in enumerate(out):
            if e9["state"] != "pending" and not (e9["state"] == "out" and e9["why"] == "expired"):
                continue
            hits9 = [j9 for j9, c9 in enumerate(cands)
                     if not c9["used"] and c9["sym"] == str(e9["sym"] or "").upper() and c9.get("ex", e9["ex"]) == e9["ex"]
                     and int(e9["ts"]) - 60 <= c9["ts"] <= e9["until"]
                     and e9["qty"] * Decimal("0.98") <= c9["qty"] <= e9["qty"]]
            fits[i9] = hits9
            for j9 in hits9:
                claims[j9] = claims.get(j9, 0) + 1
        for i9, hits9 in fits.items():
            if not hits9:
                continue
            if len(hits9) != 1 or claims[hits9[0]] != 1:
                out[i9].update({"state": "out", "why": "amount_ambiguous"})
                continue
            c9 = cands[hits9[0]]
            c9["used"] = True
            out[i9].update({"state": "arrived", "arr_ts": c9["ts"], "why": "amount"})
        return out

    def _wd_cover_wait(self, e, now, memo, tc) -> bool:
        if e.get("cls") != "wallet":
            return False
        try:
            cap_h = float(tc.get("cover_max_hours", TRANSIT_COVER_MAX_H))
        except (TypeError, ValueError):
            cap_h = float(TRANSIT_COVER_MAX_H)
        if now - float(e["start"]) > cap_h * 3600:
            return False
        na9 = xfer_match.norm_addr(e.get("addr") or "")
        ch9 = depaddr.chain_of(e.get("net"), e.get("sym"), na9)
        if not ch9 or not na9:
            return False
        return not self._recv_covered(ch9, na9, float(e["start"]), float(e["start"]) + TRANSIT_COVER_MARGIN_S, memo, now)

    @staticmethod
    def _recv_covered(chain, addr, t_from, t_need, memo, now) -> bool:
        sd = common.STATE_DIR

        def rd(key, path):
            if key not in memo:
                try:
                    v9 = common.read_json(path, {})
                except SystemExit:
                    v9 = {}
                memo[key] = v9 if isinstance(v9, dict) else {}
            return memo[key]

        def num(x9):
            return isinstance(x9, (int, float)) and not isinstance(x9, bool)
        try:
            cf9 = rd(("cur", chain), os.path.join(sd, "cursor_bsc.json" if chain == "bsc" else f"cursor_evm_{chain}.json")) if chain != "sol" else {}
            bk9 = cf9.get("_bk:" + addr) if chain not in ("bsc", "sol") else None
            bk_open = isinstance(bk9, dict) and not (num(bk9.get("done")) and num(bk9.get("to")) and bk9["done"] >= bk9["to"])
            tb9 = rd(("tb", chain), os.path.join(sd, f"addr_tier_{chain}.json"))
            p9 = (tb9.get("pairs") or {}).get(addr) if isinstance(tb9.get("pairs"), dict) else None
            if (isinstance(p9, dict) and num(p9.get("full")) and p9["full"] > 0 and not bk_open
                    and now - float(tb9.get("updatedAt") or 0) <= 1800):
                return float(p9["full"]) - 600.0 >= t_need
            if chain == "sol":
                return False
            hb9 = rd(("hb", chain), os.path.join(sd, "health", ("bsc" if chain == "bsc" else "evm") + ".json"))
            s9 = (hb9.get("sources") or {}).get(chain) if isinstance(hb9.get("sources"), dict) else None
            s9 = s9 if isinstance(s9, dict) else {}
            hd9, bs9, at9 = s9.get("head"), s9.get("block_sec_est"), s9.get("last_success_ts")
            if not (num(hd9) and num(bs9) and num(at9) and bs9 > 0):
                return False

            def bt(b9):
                return float(at9) - max(0.0, float(hd9) - float(b9)) * float(bs9)
            if chain == "bsc":
                nj9 = cf9.get("_neww")
                if addr not in (cf9.get("_wallets") or []) or (isinstance(nj9, dict) and addr in (nj9.get("wallets") or [])):
                    return False
                cur9 = s9.get("cursor")
            else:
                cur9 = cf9.get(addr)
            if not num(cur9):
                return False
            if bk_open:
                if not (num(bk9.get("done")) and num(bk9.get("to"))):
                    return False
                t_to = bt(bk9["to"])
                if t_from < t_to:
                    return t_need <= t_to and bt(bk9["done"]) >= t_need
            return bt(cur9) >= t_need
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            return False

    def _wd_transit_wake(self, wdt) -> list:
        try:
            own9 = None
            items = []
            for e in wdt or ():
                if not isinstance(e, dict) or e.get("state") != "pending" or not e.get("own"):
                    continue
                a9 = str(e.get("addr") or "").strip()
                if not a9:
                    continue
                na9 = xfer_match.norm_addr(a9)
                if e.get("cls") != "wallet":
                    if e.get("cls") not in (None, "unknown") or e.get("verdict") != "own":
                        continue
                    if own9 is None:
                        own9 = {xfer_match.norm_addr(w9.get("address")) for w9 in self._hist_wallets() if isinstance(w9, dict) and w9.get("address")}
                    if na9 not in own9:
                        continue
                ch9 = depaddr.chain_of(e.get("net"), e.get("sym"), na9)
                items.append((ch9 or "*", na9))
            if not items:
                return []
            import addr_tier
            return addr_tier.request_wake(items).get("added") or []
        except Exception as e9:
            calcguard.swallowed("view_outflows:OutflowsMixin._wd_transit_wake", e9)
            log.debug("전송 중 출금 받는 주소 깨움 실패: %s", e9)
            return []

    @staticmethod
    def _hl_neg_mark(G, neg_gids) -> bool:
        p9 = os.path.join(common.STATE_DIR, "hl_neg_mark.json")
        try:
            prev9 = set(int(x) for x in ((common.read_json(p9, {}) or {}).get("gids") or []))
        except (SystemExit, TypeError, ValueError):
            prev9 = set()
        new9 = set(neg_gids or ()) - prev9
        if not new9:
            return False
        ts9 = [int(t9) for g9 in new9 for t9, _dq in ((G.get(g9) or {}).get("qty_timeline") or ())]
        if ts9:
            common.mark_hist_dirty(min(ts9))
        common.atomic_write_json(p9, {"v": 1, "gids": sorted(prev9 | new9), "at": int(time.time())})
        return True

    def _hl_bridge_links(self, conn, wd_raw) -> dict:
        import hl_spot
        self._hl_bridge_free = []
        wds = []
        for (ex9, u9), p9 in (wd_raw or {}).items():
            if ex9 != "hyperliquid" or not isinstance(p9, dict) or str(p9.get("state") or "").upper() != "DONE":
                continue
            if str(p9.get("txid") or "").strip() or str(p9.get("currency") or "").upper() != "USDC" or p9.get("hl_type") != "withdraw":
                continue
            try:
                ts9 = int(datetime.fromisoformat(str(p9.get("created_at")).replace("Z", "+00:00")).timestamp())
                wds.append({"uuid": u9, "ts": ts9, "amount": Decimal(str(p9.get("amount"))), "fee": Decimal(str(p9.get("fee") or "0"))})
            except (TypeError, ValueError, ArithmeticError):
                continue
        if not wds:
            return {}
        lo9 = min(w["ts"] for w in wds) - hl_spot.BRIDGE_EARLY
        hi9 = max(w["ts"] for w in wds) + hl_spot.BRIDGE_WINDOW
        inflows = []
        for r9 in conn.execute(
                "SELECT p.source_id, p.event_ts, p.qty_base, p.location, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                " WHERE p.source_kind='chain_tx' AND p.source_ns='arbitrum' AND p.event='TRANSFER_IN' AND p.leg_kind='acq'"
                " AND a.kind='token' AND a.chain='arbitrum' AND a.address=? AND p.event_ts BETWEEN ? AND ?",
                (hl_spot.USDC_ARB, lo9, hi9)).fetchall():
            loc9 = str(r9["location"] or "")
            if not loc9.startswith("wallet:arbitrum:"):
                continue
            me9 = loc9.split(":")[2].lower()
            row9 = conn.execute("SELECT snapshot FROM raw_txs WHERE chain='arbitrum' AND txhash=?", (r9["source_id"],)).fetchone()
            try:
                snap9 = json.loads(row9["snapshot"]) if row9 else {}
            except (TypeError, ValueError):
                snap9 = {}
            dec9 = 6 if r9["decimals"] is None else int(r9["decimals"])
            got9 = Decimal(0)
            for tt9 in snap9.get("token_transfers") or []:
                tok9 = tt9.get("token") or {}
                if str(tok9.get("address") or tok9.get("address_hash") or "").lower() != hl_spot.USDC_ARB:
                    continue
                f9, t9 = tt9.get("from"), tt9.get("to")
                f9 = str((f9.get("hash") if isinstance(f9, dict) else f9) or "").lower()
                t9 = str((t9.get("hash") if isinstance(t9, dict) else t9) or "").lower()
                if f9 == hl_spot.BRIDGE2 and t9 == me9:
                    try:
                        got9 += Decimal(int((tt9.get("total") or {}).get("value") or 0)) / (Decimal(10) ** dec9)
                    except (TypeError, ValueError, ArithmeticError):
                        pass
            if got9 <= 0:
                continue
            qn9 = Decimal(int(r9["qty_base"])) / (Decimal(10) ** dec9)
            if abs(qn9 - got9) > Decimal("0.000001"):
                continue
            inflows.append({"tx": r9["source_id"], "loc": loc9, "ts": int(r9["event_ts"]), "qty": qn9})
        links = hl_spot.match_bridge_withdrawals(wds, inflows)
        used9 = set(links.values())
        self._hl_bridge_free = [i9 for i9 in inflows if i9["tx"] not in used9]
        return links

    def _deposit_exchange_index(self) -> dict:
        idx = {}

        def put(a, ex):
            if a and ex:
                a = a.lower() if str(a).startswith("0x") else a
                idx.setdefault(a, set()).add(str(ex))
        for e in self.cfg.get("exchange_addresses") or []:
            put(e.get("address"), e.get("exchange"))
        try:
            names = os.listdir(common.STATE_DIR)
        except OSError:
            names = []
        for f9 in names:
            if f9.startswith("exf_addrs_") and f9.endswith(".json"):
                try:
                    d9 = common.read_json(os.path.join(common.STATE_DIR, f9), {})
                except SystemExit:
                    continue
                for a9 in (d9.get("addrs") or []) if isinstance(d9, dict) else []:
                    if isinstance(a9, dict) and not a9.get("tag"):
                        put(a9.get("address"), f9[len("exf_addrs_"):-5])
        return {a: next(iter(v)) for a, v in idx.items() if len(v) == 1}

    def _deposit_exchange(self, chain, addr):
        a = (addr or "").lower() if str(addr or "").startswith("0x") else (addr or "")
        try:
            if os.path.exists(depaddr.store_path()):
                r = depaddr.lookup(chain, a)
                if r and r.get("match") in ("exact", "family") and not r.get("tag_required") and not r.get("ambiguous"):
                    return r.get("exchange")
                return None
        except Exception as _cg9:
            calcguard.swallowed("view_outflows:OutflowsMixin._deposit_exchange", _cg9)
            pass
        return (getattr(self, "_depx_idx", None) or {}).get(a)

    def _raw_from_counts(self, conn) -> dict:
        self._rtxc().sync(conn)
        return self._rtxc().from_counts(conn)

    def _inflow_senders(self, conn, dests) -> dict:
        try:
            mine = rawtx_cache.mine_wallets(common.read_json(common.CONFIG_PATH, {}) or {})
        except BaseException as _cg9:
            calcguard.swallowed("view_outflows:OutflowsMixin._inflow_senders", _cg9)
            mine = set()
        self._rtxc().sync(conn)
        return self._rtxc().inflow_senders(conn, dests, mine)

    def _outflow_returns(self, conn, groups: dict, live_px: dict, G: dict) -> dict:
        idx = self._inflow_senders(conn, [a for a, o9 in groups.items()
                                          if a not in ("multi", "?") and not o9.get("phantom") and not flow_trace.is_burn(a)])
        br_arr9 = {a9.get("key") for a9 in ((getattr(self, "_of_auto", None) or {}).get("bridge") or {}).values() if isinstance(a9, dict)}
        tok_pid9 = {l9.get("pid") for s9 in (getattr(self, "_of_man_state", None) or {}).values()
                    for l9 in (s9.get("links") or {}).values() if l9.get("st") == "applied" and l9.get("pid") is not None}
        own_ref9 = {l9["key"]: a9 for a9, ls9 in (getattr(self, "_of_claim_legs", None) or {}).items()
                    for l9 in ls9 if l9.get("kind") == "refund" and l9.get("st") == "ok" and l9.get("key")}
        want = {}
        for a, o9 in groups.items():
            if a in ("multi", "?") or not idx.get(a):
                continue
            for key in idx[a]:
                if key[1] not in o9["txs"]:
                    want.setdefault(key, set()).add(a)
        out = {}
        keys = list(want)
        for i in range(0, len(keys), 400):
            ch = keys[i:i + 400]
            q = ("SELECT p.posting_id, p.source_kind, p.source_ns, p.source_id, p.leg_seq, p.event_ts, p.location, p.qty_base, p.cost_usd, a.symbol,"
                 " a.decimals, a.group_id, a.asset_id FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_kind='chain_tx'"
                 " AND p.source_id IN (" + ",".join("?" * len(ch)) + ") AND p.location LIKE 'wallet:%'"
                 " AND p.leg_kind IN ('acq', 'move_in')")
            for r in conn.execute(q, [k[1] for k in ch]).fetchall():
                key = (r["source_ns"], r["source_id"])
                if key not in want or int(r["qty_base"]) <= 0 or r["posting_id"] in br_arr9 or r["posting_id"] in tok_pid9:
                    continue
                qn = Decimal(int(r["qty_base"])) / (Decimal(10) ** int(r["decimals"] if r["decimals"] is not None else 18))
                gid = r["group_id"] or -r["asset_id"]
                if gid in (getattr(self, "_risk_quarantined", None) or ()):
                    continue
                g9 = G.get(gid) or {}
                if r["cost_usd"] is not None:
                    usd = float(r["cost_usd"])
                elif g9.get("is_stable"):
                    usd = float(qn)
                else:
                    u9 = self._ledger_unit_px(conn, gid, int(r["event_ts"]))
                    if u9 is None:
                        for a in want[key]:
                            for t9 in (groups[a].get("tokens") or {}).values():
                                if t9.get("gid") == gid and t9.get("usd_send_known") and t9.get("qty") and t9.get("usd_send"):
                                    u9 = float(t9["usd_send"]) / float(t9["qty"])
                                    break
                            if u9 is not None:
                                break
                    usd = float(qn) * (u9 if u9 is not None else float(live_px.get(gid) or 0))
                if usd < 1:
                    continue
                ow9 = own_ref9.get(self._of_key(r)) if own_ref9 else None
                for a in want[key]:
                    if ow9 is not None and ow9 != a:
                        continue
                    first = groups[a]["first"]
                    out.setdefault(a, {"after": [], "before": []})["after" if r["event_ts"] >= first else "before"].append({
                        "key": self._of_key(r),
                        "ts": int(r["event_ts"]), "t": datetime.fromtimestamp(r["event_ts"], KST).strftime("%Y-%m-%d %H:%M"),
                        "chain": r["source_ns"], "tx": r["source_id"], "sym": g9.get("sym") or (r["symbol"] or "?"),
                        "qty": float(qn), "usd": _f(usd, 2),
                        "wallet": str(r["location"] or "").split(":")[-1]})
        return out

    def _ledger_unit_px(self, conn, gid, ts, win=7 * 86400):
        c9 = getattr(self, "_lpx_cache", None)
        if c9 is None or c9.get("_db") is not conn:
            c9 = self._lpx_cache = {"_db": conn}
        lst = c9.get(gid)
        if lst is None:
            lst = []
            try:
                cond9 = "a.group_id=?" if gid is not None and gid > 0 else "a.asset_id=?"
                for r9 in conn.execute("SELECT p.event_ts, p.qty_base, p.cost_usd, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                                       " WHERE " + cond9 + " AND p.cost_usd IS NOT NULL AND p.leg_kind IN ('acq', 'disp')",
                                       (gid if gid is not None and gid > 0 else -gid,)).fetchall():
                    q9 = abs(Decimal(int(r9["qty_base"]))) / (Decimal(10) ** int(r9["decimals"] if r9["decimals"] is not None else 18))
                    if q9 > 0:
                        lst.append((int(r9["event_ts"]), float(Decimal(r9["cost_usd"]) / q9)))
            except Exception as _cg9:
                calcguard.swallowed("view_outflows:OutflowsMixin._ledger_unit_px", _cg9)
                lst = []
            lst.sort()
            c9[gid] = lst
        best = None
        for t9, u9 in lst:
            d9 = abs(t9 - ts)
            if d9 <= win and u9 > 0 and (best is None or d9 < best[0]):
                best = (d9, u9)
        return best[1] if best else None

    @staticmethod
    def _lookalike(a: str, pool: dict):
        if not (a or "").startswith("0x") or len(a) != 42:
            return None
        for b, desc in pool.items():
            if b != a and len(b) == 42 and b.startswith("0x") and b[2:6] == a[2:6] and b[-4:] == a[-4:]:
                return {"similarTo": b, "label": desc}
        return None

    @staticmethod
    def _rt_parties(snap: dict, side: str, mine: set) -> set:
        if not isinstance(snap, dict):
            return set()
        if snap.get("kind") == "sol_tx":
            return {str(x) for x in (snap.get("counterparties") or []) if x}

        def _a(x):
            return str((x.get("hash") if isinstance(x, dict) else x) or "").lower()
        out = set()
        tx = snap.get("tx") or {}
        legs = [(tx.get("from"), tx.get("to"), tx.get("value"))]
        legs += [(it.get("from"), it.get("to"), it.get("value")) for it in (snap.get("internal") or [])
                 if not (it.get("success") is False or it.get("error"))]
        legs += [(tt.get("from"), tt.get("to"), (tt.get("total") or {}).get("value")) for tt in (snap.get("token_transfers") or [])]
        for f9, t9, v9 in legs:
            try:
                if not int(v9 or 0):
                    continue
            except (TypeError, ValueError):
                continue
            f9, t9 = _a(f9), _a(t9)
            if side == "in" and t9 in mine and f9 and f9 not in mine:
                out.add(f9)
            elif side == "out" and f9 in mine and t9 and t9 not in mine:
                out.add(t9)
        return out

    def _rt_same_dest(self, conn, rt_pair: dict) -> set:
        ok = set()
        if not rt_pair:
            return ok
        cfg_mine = {str(w.get("address") or "").lower() for w in self._hist_wallets() if isinstance(w, dict)}
        for ki, ko in rt_pair.items():
            try:
                ri = conn.execute("SELECT snapshot, wallets FROM raw_txs WHERE chain=? AND txhash=?", ki).fetchone()
                ro = conn.execute("SELECT snapshot, wallets FROM raw_txs WHERE chain=? AND txhash=?", ko).fetchone()
                if not ri or not ro:
                    continue
                mine9 = set(cfg_mine)
                for r9 in (ri, ro):
                    try:
                        mine9 |= {str(w).lower() for w in (json.loads(r9[1] or "[]") or []) if w}
                    except ValueError:
                        pass
                if self._rt_parties(json.loads(ri[0]), "in", mine9) & self._rt_parties(json.loads(ro[0]), "out", mine9):
                    ok.add(ko)
            except Exception as e:
                calcguard.swallowed("view_outflows:OutflowsMixin._rt_same_dest", e)
                log.debug("왕복 상대 대조 실패 %s: %s", ko, e)
                continue
        return ok

    def _untracked_net_deps(self, conn) -> list:
        trk9 = {str(k).upper() for k in (self.cfg.get("chains") or {})} | {"SOL", "BSC"}
        out = []
        try:
            for rf in conn.execute("SELECT exchange, payload FROM raw_ex WHERE kind='deposit'"
                                   " GROUP BY exchange, uuid HAVING revision = MAX(revision)").fetchall():
                try:
                    pw = json.loads(rf["payload"])
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(pw, dict) or str(pw.get("state") or "").upper() != "ACCEPTED":
                    continue
                net9 = str(pw.get("net_type") or pw.get("network") or "").strip()
                cur9 = str(pw.get("currency") or "").strip().upper()
                selfnet9 = net9.upper() == cur9
                if not net9 or not cur9 or depaddr.chain_of(net9, cur9):
                    continue
                if any(k9 in net9.upper() for k9 in trk9 if k9 != "ETH"):
                    continue
                try:
                    ts9 = datetime.fromisoformat(str(pw.get("done_at") or pw.get("created_at"))).timestamp()
                    q9 = float(pw.get("amount") or 0)
                except (ValueError, TypeError):
                    continue
                if q9 > 0:
                    out.append({"ts": ts9, "ex": rf["exchange"], "cur": acct_norm.canon(cur9, rf["exchange"]), "qty": q9, "net": net9,
                                "selfnet": selfnet9})
        except Exception as e9:
            calcguard.swallowed("view_outflows:OutflowsMixin._untracked_net_deps", e9)
            log.warning("미추적 체인 입금 읽기 실패(제안 없음): %s", e9)
            return []
        return out

    @classmethod
    def _of_list_add(cls, o9: dict, item: dict) -> dict:
        lst = o9["list"]
        lst.append(item)
        o9["listN"] = int(o9.get("listN") or 0) + 1
        if len(lst) >= 2 * cls.OF_LIST_CAP:
            lst.sort(key=lambda x9: x9["ts"])
            del lst[:-cls.OF_LIST_CAP]
        return item

    @classmethod
    def _of_list_cut(cls, o9: dict) -> int:
        lst = sorted(o9.get("list") or (), key=lambda x9: x9["ts"])
        o9["list"] = lst[-cls.OF_LIST_CAP:]
        return max(0, int(o9.get("listN") or len(lst)) - len(o9["list"]))

    def _outflows(self, conn, ob: dict, live_px: dict, G: dict, scam_gids=frozenset(), dust_usd: float = 0.0, exwd=None):
        dec = self.outflow_decisions()
        known = self._known_addrs()
        try:
            reg_now = {((w.get("address") or "").lower() if str(w.get("address") or "").startswith("0x") else (w.get("address") or ""))
                       for w in (common.read_json(common.CONFIG_PATH, {}) or {}).get("wallets") or []}
        except BaseException as _cg9:
            calcguard.swallowed("view_outflows:OutflowsMixin._outflows", _cg9)
            reg_now = set()
        try:
            import wallet_register as _wr9
            alive9 = _wr9.auto_reload_alive()
            reload_addrs9 = _wr9.pending_addrs() if alive9 else set()
            auto9 = bool(_wr9.apply_info().get("runner"))
        except Exception as _cg9:
            calcguard.swallowed("view_outflows:OutflowsMixin._outflows", _cg9)
            reload_addrs9, auto9 = set(), False
        self._of_auto_reload = auto9
        fx_name = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "kucoin": "쿠코인", "gate": "게이트",
                   "bithumb": "빗썸", "upbit": "업비트", "hyperliquid": "Hyperliquid"}
        groups = {a: dict(v, resolved_rows=False, list=list(v.get("list") or ())) for a, v in ob.items()}
        try:
            gid_ca9 = {r9[0] for r9 in conn.execute("SELECT DISTINCT COALESCE(group_id, -asset_id) FROM assets"
                                                    " WHERE kind='token' AND address IS NOT NULL").fetchall()} - \
                      {r9[0] for r9 in conn.execute("SELECT DISTINCT COALESCE(group_id, -asset_id) FROM assets WHERE kind != 'token'").fetchall()}
            gid_ca9 -= {r9[0] for r9 in conn.execute("SELECT COALESCE(group_id, -asset_id), chain, address FROM assets"
                                                     " WHERE kind='token' AND address IS NOT NULL").fetchall()
                        if spamguard.is_genuine(r9[1], r9[2])}
        except Exception as _cg9:
            calcguard.swallowed("view_outflows:OutflowsMixin._outflows", _cg9)
            gid_ca9 = set()
        for a, v in dec.items():
            if not isinstance(v, dict) or v.get("verdict") not in ("exchange", "own"):
                continue
            if v["verdict"] == "exchange":
                q = ("SELECT p.source_ns, p.source_id, p.event_ts, p.qty_base, p.cost_usd, a.symbol, a.decimals, a.group_id, a.asset_id"
                     " FROM postings p JOIN assets a ON a.asset_id=p.asset_id JOIN tx_class t ON t.chain=p.source_ns"
                     " AND t.txhash=p.source_id WHERE p.source_kind='chain_tx' AND t.event='TRANSFER_OUT_EX'"
                     " AND p.leg_kind='move_out' AND t.detail LIKE ?")
                args = ('%"' + a + '"%',)
            else:
                q = ("SELECT p.source_ns, p.source_id, p.event_ts, p.qty_base, p.cost_usd, a.symbol, a.decimals, a.group_id, a.asset_id"
                     " FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_kind='chain_tx'"
                     " AND p.event IN ('TRANSFER_SELF', 'TRANSFER_OUT') AND p.leg_kind='move_in' AND p.location LIKE ?")
                args = ("wallet:%:" + a,)
            for r in conn.execute(q, args).fetchall():
                qn = abs(Decimal(int(r["qty_base"])) / (Decimal(10) ** int(r["decimals"] if r["decimals"] is not None else 18)))
                o9 = groups.setdefault(a, {"chains": set(), "first": r["event_ts"], "last": r["event_ts"], "txs": set(),
                                           "tokens": {}, "list": [], "auto": None, "resolved_rows": True})
                o9["chains"].add(r["source_ns"])
                o9["first"] = min(o9["first"], r["event_ts"]); o9["last"] = max(o9["last"], r["event_ts"])
                o9["txs"].add(r["source_id"])
                gid9r = r["group_id"] or -r["asset_id"]
                sym9 = (G.get(gid9r) or {}).get("sym") or (r["symbol"] or "?")
                tk9 = o9["tokens"].setdefault(sym9, {"qty": Decimal(0), "cost": None, "usd_send": Decimal(0),
                                                     "usd_send_known": False, "gid": gid9r, "unknown": Decimal(0)})
                tk9["qty"] += qn
                o9.setdefault("hsyms", {}).setdefault(r["source_id"], set()).add(sym9)
                self._of_list_add(o9, {"ts": int(r["event_ts"]), "t": datetime.fromtimestamp(r["event_ts"], KST).strftime("%Y-%m-%d %H:%M"),
                                       "chain": r["source_ns"], "tx": r["source_id"], "sym": sym9, "qty": float(qn),
                                       "usdAtSend": None, "costUsd": None})
        for e9 in (exwd or ()):
            a9 = e9["key"]
            o9 = groups.get(a9)
            if o9 is None:
                o9 = groups[a9] = {"chains": set(), "first": e9["ts"], "last": e9["ts"], "txs": set(), "tokens": {}, "list": [],
                                   "auto": None, "resolved_rows": False}
            ch9 = depaddr.chain_of(e9.get("net"), e9.get("sym")) if e9.get("net") else None
            if ch9:
                o9["chains"].add(ch9)
            o9["first"] = min(o9["first"], e9["ts"])
            o9["last"] = max(o9["last"], e9["ts"])
            o9["txs"].add(e9.get("txid_raw") or f"{e9['ex']}:{e9['uuid']}")
            g9 = G.get(e9["gid"]) or {}
            q9 = Decimal(e9["qty"])
            tk9 = o9["tokens"].setdefault(e9["sym"], {"qty": Decimal(0), "cost": Decimal(0), "usd_send": Decimal(0),
                                                      "usd_send_known": True, "gid": e9["gid"], "unknown": Decimal(0)})
            tk9["qty"] += q9
            tk9["cost"] = (tk9["cost"] or Decimal(0)) + Decimal(e9.get("cost") or 0)
            tk9["unknown"] += max(Decimal(0), q9 - Decimal(e9.get("known") or 0))
            if g9.get("is_stable"):
                tk9["usd_send"] += q9
            else:
                tk9["usd_send_known"] = False
            o9.setdefault("hsyms", {}).setdefault(e9.get("txid_raw") or f"{e9['ex']}:{e9['uuid']}", set()).add(e9["sym"])
            self._of_list_add(o9, {"ts": int(e9["ts"]), "t": datetime.fromtimestamp(e9["ts"], KST).strftime("%Y-%m-%d %H:%M"),
                                   "chain": ch9 or (e9.get("net") or ""), "tx": e9.get("txid_raw") or "", "sym": e9["sym"], "qty": float(q9),
                                   "usdAtSend": float(q9) if g9.get("is_stable") else None, "costUsd": float(e9.get("cost") or 0),
                                   "ex": e9["src"], "signed": True,
                                   "key": self._wd_key(e9["ex"], e9["uuid"])})
            o9.setdefault("exwd", []).append(e9)
        for o9 in groups.values():
            o9["listCut"] = self._of_list_cut(o9)
        pool = {a: f"{kk[0][1]}" for a, kk in known.items() if kk and kk[0][0] in ("my_wallet", "exchange_deposit")}
        for a, v in dec.items():
            if isinstance(v, dict) and v.get("verdict") in ("own", "exchange"):
                pool.setdefault(a, "판정된 " + ("내 지갑" if v["verdict"] == "own" else "거래소 입금주소"))
        out, n_pend = [], 0
        tot = {}
        vals = {}

        def _ph9(t9):
            return bool((("held" in t9) and t9["held"] <= EPS) or t9.get("gid") in scam_gids)
        ad_gids9 = getattr(self, "_risk_airdrop_only", None) or frozenset()

        def _ad9(t9):
            return bool(t9.get("gid") in ad_gids9 and t9.get("gid") in scam_gids and not (("held" in t9) and t9["held"] <= EPS))
        for a, o9 in groups.items():
            now9 = send9 = cost9 = 0.0
            toks = []
            phantom_all = bool(o9["tokens"]) and all(_ph9(t9) for t9 in o9["tokens"].values())
            o9["phantom"] = phantom_all
            for sym9, t9 in sorted(o9["tokens"].items()):
                g9x = G.get(t9["gid"]) or {}
                px9 = 1.0 if g9x.get("is_stable") else float(live_px.get(t9["gid"]) or 0)
                if _ph9(t9):
                    px9 = 0.0
                elif not px9 and t9["usd_send_known"] and t9["qty"] > 0 and t9["usd_send"] > 0:
                    sp9 = float(self.spot.price(acct_norm.canon(g9x.get("sym") or sym9)) or 0)
                    u9 = float(t9["usd_send"]) / float(t9["qty"])
                    if sp9 > 0 and 0.1 <= sp9 / u9 <= 10.0 and not g9x.get("is_fiat"):
                        px9 = sp9
                un9 = float(t9["qty"]) * px9
                ph9 = _ph9(t9)
                toks.append({"sym": sym9, "qty": float(t9["qty"]), "costUsd": (_f(float(t9["cost"]), 2) if t9["cost"] is not None else None),
                             "phantom": ph9, **({"quar": "airdrop"} if ph9 and _ad9(t9) else {}),
                             "usdAtSend": (_f(float(t9["usd_send"]), 2) if t9["usd_send_known"] and not ph9 else None),
                             "usdNow": _f(un9, 2) or 0, "unknownCostQty": _f(float(t9["unknown"]), 6) or 0})
                now9 += un9
                send9 += float(t9["usd_send"]) if t9["usd_send_known"] and not ph9 else 0.0
                cost9 += float(t9["cost"] or 0)
            vals[a] = send9 or now9
            out.append((a, o9, toks, now9, send9, cost9))
        for a, v in sorted(vals.items(), key=lambda kv: -kv[1]):
            pool.setdefault(a, f"다른 보낸 주소({a[:6]}…{a[-4:]})") if v >= 1000 and a not in ("multi", "?") else None
        rets = self._outflow_returns(conn, groups, live_px, G)
        blabels = self._bridge_labels()
        auto9 = getattr(self, "_of_auto", None) or {}
        up_from = {}
        for t9, oc9 in (common.read_json(os.path.join(common.STATE_DIR, "tx_origin_cache.json"), {}) or {}).items():
            f9 = (oc9 or {}).get("from") if isinstance(oc9, dict) else None
            if f9:
                up_from.setdefault(f9.lower() if f9.startswith("0x") else f9, []).append(t9)
        rows = []
        sale_cands9 = {}
        sug_pid9 = {}
        self._of_sug_pid = sug_pid9
        utd9 = None if not any(blabels.get(a0) for a0, *_r in out) else self._untracked_net_deps(conn)
        utd_hint = {}
        self._of_untracked_hint = utd_hint
        for a, o9, toks, now9, send9, cost9 in out:
            d9 = dec.get(a) if isinstance(dec.get(a), dict) else {}
            verdict = d9.get("verdict")
            still_out = a in ob
            if verdict == "external":
                status = "external"
            elif verdict == "exchange":
                status = "exchange_applying" if still_out else "exchange"
            elif verdict == "own":
                status = "own_restart_needed" if still_out else "own"
            elif a in reg_now and still_out:
                status = "own_restart_needed"
            elif (o9.get("mtx") and not (set(o9.get("rtx") or ()) - set(o9.get("mtx") or ()))
                  and set(o9.get("basis") or ()) == {"roundtrip"}):
                status = "returned"
            elif o9.get("mtx") and not (set(o9.get("rtx") or ()) - set(o9.get("mtx") or ())):
                status = "exchange_matched" if o9.get("auto") else "bridge_matched"
            elif o9.get("phantom"):
                status = "spam"
            elif a == "0x0000000000000000000000000000000000008001" and o9["chains"] <= {"zksync"}:
                status = "system"
            else:
                status = "pending"
            rt9 = rets.get(a) or {"after": [], "before": []}
            ms9 = (getattr(self, "_of_man_state", None) or {}).get(a) or {}
            if verdict == "external" and ms9:
                aft9 = [dict(x9) for x9 in rt9["after"]]
                cur9 = {own9[1]: ck9 for ck9, own9 in (getattr(self, "_of_claims", None) or {}).items() if own9[0] == a}
                for l9 in (d9.get("links") if isinstance(d9.get("links"), list) else []):
                    if not isinstance(l9, dict) or l9.get("kind") != "refund" \
                            or ((ms9.get("links") or {}).get(str(l9.get("key") or "")) or {}).get("st") != "ok":
                        continue
                    tx9, sy9 = str(l9.get("tx") or "").lower(), str(l9.get("sym") or "")
                    ck9 = cur9.get(str(l9.get("key") or ""), str(l9.get("key") or ""))
                    hit9 = next((x9 for x9 in aft9 if x9.get("key") == ck9), None)
                    if hit9 is not None:
                        hit9["linked"] = True
                        continue
                    ts9l = int(l9.get("ts") or 0)
                    aft9.append({"ts": ts9l, "t": datetime.fromtimestamp(ts9l, KST).strftime("%Y-%m-%d %H:%M"),
                                 "chain": str(l9.get("key") or "").split("|")[1] if str(l9.get("key") or "").count("|") >= 3 else "",
                                 "tx": l9.get("tx") or "", "sym": sy9, "qty": float(l9.get("qty") or 0),
                                 "usd": _f(float((ms9["links"][str(l9["key"])]).get("usd") or 0), 2),
                                 "wallet": str(l9.get("where") or "")[2:] if str(l9.get("where") or "").startswith("w:") else "",
                                 "linked": True, "where": self._of_where(l9.get("where")), "key": ck9})
                rt9 = {"after": aft9, "before": rt9["before"]}
            ret_usd = sum(x["usd"] or 0 for x in rt9["after"])
            m_usd = float(o9.get("musd") or 0.0) if status == "pending" else 0.0
            sent_v = max(0.0, (send9 or now9) - m_usd)
            rkind = outflow_match.return_kind(sent_v, ret_usd) if a not in ("multi", "?") else None
            if status == "pending" and rkind == "full" and not (verdict == "clear" and d9.get("noAuto")):
                status = "returned"
            if status == "pending" and verdict in (None, "clear") and d9.get("ret") is True:
                status = "returned"
            blab9 = blabels.get(a)
            if status == "pending" and blab9 and not (verdict == "clear" and d9.get("noAuto")):
                status = "bridge_untracked"
            xw9 = o9.get("exwd") or []
            if status == "pending" and xw9 and not ob.get(a) and all(x9.get("cls") == "wallet_untracked" for x9 in xw9):
                status = "own"
            look = self._lookalike(a, pool)
            fake_look9 = False
            if status == "pending" and look and not xw9 and o9["tokens"] and all(
                    (lambda g9f: bool(g9f) and not g9f.get("is_stable") and not g9f.get("is_fiat") and not g9f.get("px_seen")
                     and not g9f.get("ex_seen") and not g9f.get("mv_seen") and not float(live_px.get(t9["gid"]) or 0)
                     and not t9["usd_send_known"] and t9["gid"] in gid_ca9)(G.get(t9["gid"]))
                    for t9 in o9["tokens"].values()):
                status = "spam"
                fake_look9 = True
            if status == "pending":
                n_pend += 1
            hints = [{"kind": k9, "label": n9} for k9, n9 in (known.get(a) or [])]
            if flow_trace.is_burn(a) and not hints:
                hints.append({"kind": "burn", "label": "발행·소각·시스템 주소 — 누구의 지갑도 아님"})
            if blab9 and not any(h9["kind"] == "bridge" for h9 in hints):
                hints.append({"kind": "bridge", "label": f"브릿지 · {blab9['name']}"})
            bas9 = sorted(o9.get("basis") or ())
            if o9.get("auto") and o9["auto"][0] == "sale":
                hints.append({"kind": "sale_bid", "label": "토큰 세일 입찰 — 체결분은 수령 토큰(세일 로트)이 입찰액을 원가로 이어받음 · "
                                                            f"{len(o9.get('mtx') or ())}/{len(o9.get('rtx') or o9['txs'])}건"})
            elif o9.get("auto"):
                nm9 = f"{len(o9.get('mtx') or ())}/{len(o9.get('rtx') or o9['txs'])}"
                hints.append({"kind": "exchange_txid" if bas9 == ["txid"] else "exchange_auto",
                              "chip": f"{o9['auto'][1]} 입금 자동 매칭 · {nm9}건",
                              "label": f"{o9['auto'][1]} 입금으로 자동 매칭(근거: " + " / ".join(OF_BASIS_KO.get(b9, b9) for b9 in bas9 or ["txid"])
                              + f") · {nm9}건 · "
                              + ("창 이전 입금 · 원가 이관 없음" if o9.get("prewin") and o9["prewin"] >= len(o9.get("mtx") or ())
                                 else (f"원가 이관됨(창 이전 입금 {o9['prewin']}건 제외)" if o9.get("prewin") else "원가 이관됨"))})
            if "roundtrip" in bas9:
                hints.append({"kind": "roundtrip", "label": "프로그램 예치 왕복 — 보낸 자산이 6시간 안에 같은 지갑으로 전액 복귀(원가 복원) · "
                                                            f"{len({x['tx'] for x in o9['list'] if (x.get('match') or {}).get('basis') == 'roundtrip'})}건"})
            sugg = []
            if status == "bridge_untracked":
                sugg.append({"kind": "bridge_untracked", "exchange": None, "label": "브릿지 → 미추적 체인",
                             "evidence": f"{blab9['name']} 로 보냈는데 추적 중인 내 지갑에 60분 안에 같은 수량 도착이 없어요 — "
                                         "받은 체인·지갑을 추가(설정 › 연결)하면 자동으로 이어져요"})
                snd9 = [x9 for x9 in o9["list"] if x9.get("ts")]
                hit9 = {}
                for dp9 in (utd9 if utd9 is not None else []):
                    for x9 in snd9:
                        if dp9.get("selfnet") and acct_norm.canon(x9.get("sym")) != dp9["cur"]:
                            continue
                        if x9["ts"] <= dp9["ts"] <= x9["ts"] + 86400 and \
                                datetime.fromtimestamp(x9["ts"], KST).date() == datetime.fromtimestamp(dp9["ts"], KST).date():
                            h9 = hit9.setdefault((dp9["ex"], dp9["cur"], dp9["net"]), {"qty": 0.0, "n": 0, "t0": dp9["ts"], "t1": dp9["ts"],
                                                                                       "day": datetime.fromtimestamp(dp9["ts"], KST).strftime("%Y-%m-%d")})
                            h9["qty"] += dp9["qty"]; h9["n"] += 1
                            h9["t0"] = min(h9["t0"], dp9["ts"]); h9["t1"] = max(h9["t1"], dp9["ts"])
                            break
                for (ex9, cur9, net9), h9 in sorted(hit9.items(), key=lambda kv: kv[1]["t0"]):
                    bu9 = sum(float(x9.get("usdAtSend") or 0) for x9 in snd9
                              if datetime.fromtimestamp(x9["ts"], KST).strftime("%Y-%m-%d") == h9["day"])
                    sugg.append({"kind": "untracked_chain_deposit", "exchange": ex9, "label": "미추적 체인 → 거래소 입금으로 보임 — 확인",
                                 "evidence": f"{h9['day'][5:]} {datetime.fromtimestamp(h9['t0'], KST).strftime('%H:%M')}"
                                             + (f"~{datetime.fromtimestamp(h9['t1'], KST).strftime('%H:%M')}" if h9["n"] > 1 else "")
                                             + f" {fx_name.get(ex9, ex9)} {cur9} {h9['qty']:,.6g} 입금({net9} 네트워크 · {h9['n']}건) — "
                                             f"이 브릿지로 보낸 ${bu9:,.0f} 가 추적 밖 체인에서 {cur9} 로 바뀌어 들어온 것일 수 있어요. "
                                             f"맞으면 {cur9} 원가를 지정해 주세요(자동 연결 안 함)",
                                 "sym": cur9, "day": h9["day"], "qty": _f(h9["qty"], 6), "net": net9, "bridgeUsd": _f(bu9, 2)})
                    u9h = utd_hint.setdefault(cur9, {"day": h9["day"], "ex": ex9, "net": net9, "qty": h9["qty"], "usd": 0.0, "names": []})
                    if u9h["day"] == h9["day"]:
                        u9h["usd"] += bu9
                        if blab9["name"] not in u9h["names"]:
                            u9h["names"].append(blab9["name"])
            if status in ("pending", "bridge_untracked"):
                pv9 = (auto9.get("proven") or {}).get(a)
                for c9 in (auto9.get("sugg") or {}).get(a) or []:
                    sugg.append({"kind": "exchange", "exchange": c9["ex"], "label": "거래소 입금으로 보임 — 확인",
                                 "evidence": c9["evidence"], "uuid": c9["uuid"]})
                if pv9 and pv9[1] == "conflict":
                    sugg.append({"kind": "exchange", "exchange": None, "label": "거래소 입금주소로 보임 — 거래소가 엇갈려 확인 필요",
                                 "evidence": "txid 일치·입금주소 목록이 서로 다른 거래소를 가리킴"})
                br9 = [(pid9, v9) for pid9, v9 in (auto9.get("bridge_amb") or {}).items()
                       if ((auto9.get("sends") or {}).get(pid9) or {}).get("dest") == a]
                if br9:
                    s0, b0 = auto9["sends"][br9[0][0]], br9[0][1][0]
                    sugg.append({"kind": "bridge", "exchange": None, "label": "브릿지로 보임 — 확인",
                                 "evidence": f"{len(br9)}건 · 예: {s0['sym']} {outflow_match.fmt_q(s0['qty'])} "
                                             f"{CHAIN_NAME.get(s0['chain'], s0['chain'])} → {CHAIN_NAME.get(b0['chain'], b0['chain'])} "
                                             f"{max(0, int((b0['ts'] - s0['ts']) // 60))}분 뒤 도착 후보 {len(br9[0][1])}건 — 유일하지 않아 자동 안 함"})
                if a == "0x0000000000000000000000000000000000008001" and o9["chains"] <= {"zksync"}:
                    sugg.append({"kind": "system", "exchange": None, "label": "zkSync 시스템 주소(부트로더) — 가스 성격",
                                 "evidence": "0x…8001 = zkSync Era 부트로더(수수료 수취)"})
            if status in ("pending", "returned", "bridge_untracked") and a not in ("multi", "?") and not blab9:
                ev9 = []
                if rt9["after"]:
                    ev9.append(f"보낸 뒤 이 주소에서 내 지갑으로 {len(rt9['after'])}건 ${ret_usd:,.0f} 받음")
                if rt9["before"]:
                    ev9.append(f"보내기 전 이 주소에서 {len(rt9['before'])}건 ${sum(x['usd'] or 0 for x in rt9['before']):,.0f} 받음(자금 출처)")
                if up_from.get(a):
                    ev9.append(f"이 주소가 내 업비트 계정에 {len(up_from[a])}건 입금(업비트 입금 발신지)")
                if ev9:
                    strong9 = bool(up_from.get(a) or rt9["before"] or rkind == "full")
                    ws9 = {x.get("wallet") for x in rt9["after"] if x.get("wallet")}
                    likely9 = (not strong9) and ((sent_v > 0 and ret_usd >= 0.5 * sent_v) or (len(rt9["after"]) >= 3 and len(ws9) >= 2))
                    if likely9 and len(ws9) >= 2:
                        ev9.append(f"내 지갑 {len(ws9)}곳과 주고받음")
                    sugg.append({"kind": "own" if (strong9 or likely9) else "roundtrip", "exchange": None,
                                 "label": "내 지갑 같음" if strong9 else ("내 지갑 가능성 높음" if likely9 else "일부 되돌려 받음"),
                                 "action": "register_own" if (strong9 or likely9) else None,
                                 "evidence": " · ".join(ev9)})
            if xw9 and status == "pending":
                x0 = xw9[-1]
                why9 = ("받는 주소를 '외부'로 판정해 둔 주소예요" if x0.get("why") == "external"
                        else "같은 txid의 출금이 여러 건이에요 — 건별 도착 확인 전 중복 가산을 보류했어요" if x0.get("why") == "txid_ambiguous"
                        else "같은 수량의 입출금 후보가 여러 건이에요 — 중복 가산을 보류했으니 도착지를 확인해 주세요" if x0.get("why") == "amount_ambiguous"
                        else f"{max(1, int(round((x0['until'] - x0['start']) / 3600)))}시간 안에 내 지갑·거래소 도착 기록이 없어요")
                ev9 = (f"{x0['src']} {x0['sym']} {outflow_match.fmt_q(x0['qty'])} 출금"
                       + (f"({x0['net']})" if x0.get("net") else "") + f" — {why9}"
                       + (f" · 내 {x0['dst']} 입금주소인데 입금 기록이 아직 없어요" if x0.get("cls") == "exchange" and x0.get("dst") else ""))
                sugg.insert(0, {"kind": "exwd", "exchange": None, "label": "이 출금은 어디로 갔나요?" if a.startswith("wd:") else "이 주소가 어떤 주소인가요?",
                                "evidence": ev9})
            flags = []
            if look:
                flags.append(dict(look, kind="lookalike",
                                  note=("주소 오염(사칭) 의심 — 앞뒤 자리가 같은 다른 주소"
                                        + (" · 소액(더스트)" if (send9 or now9) < 1 else ""))))
            if o9.get("phantom"):
                flags.append({"kind": "spoof_token", "note": "보유한 적 없는 토큰의 전송 로그(사칭 토큰 · 주소 오염 공격) — 실제 유출 아님"})
            elif fake_look9:
                flags.append({"kind": "spoof_token", "note": "닮은 주소로 간 시세·체결 없는 토큰의 전송 로그(가짜 토큰 · 주소 오염 공격) — 실제 유출 아님"})
            if a in ("multi", "?"):
                flags.append({"kind": "unknown_dest", "note": "수령 주소를 특정하지 못함(여러 상대/정보 없음)"})
            if xw9 and a.startswith("wd:"):
                flags.append({"kind": "exwd_noaddr", "note": "받는 주소 미상 — 거래소 출금 기록에 주소가 없어요"})
            lv9 = []
            for l9 in (d9.get("links") if isinstance(d9.get("links"), list) else []):
                if not isinstance(l9, dict):
                    continue
                s9 = (ms9.get("links") or {}).get(str(l9.get("key") or "")) or {}
                st9 = s9.get("st") or ("off" if verdict != "external" else "missing")
                lv9.append({"kind": l9.get("kind"), "key": l9.get("key"), "sym": l9.get("sym"), "qty": l9.get("qty"), "ts": l9.get("ts"),
                            "where": self._of_where(l9.get("where")), "tx": l9.get("tx"), "st": st9,
                            "usd": _f(float(s9["usd"]), 2) if s9.get("usd") is not None else None,
                            "costUsd": _f(float(s9["cost"]), 2) if st9 == "applied" and s9.get("cost") is not None else None})
            lref9 = float(ms9.get("refundUsd") or 0) if verdict == "external" else 0.0
            cand9 = None
            cand_top9 = None
            if verdict == "external" and d9.get("category") == self.OUTFLOW_SALE_CAT:
                ss9 = {sy9.upper() for sy9, t9 in o9["tokens"].items() if (G.get(t9.get("gid")) or {}).get("is_stable") and not _ph9(t9)}
                dis9 = {str(x9) for x9 in (d9.get("dismiss") or []) if isinstance(x9, str)}
                cand9 = self._of_sale_cands(a, int(o9["first"]), ss9, px_of=lambda g9: live_px.get(g9), skip=dis9)
                sale_cands9[a] = cand9
                sent_q9 = {sy9.upper(): float(t9["qty"]) for sy9, t9 in o9["tokens"].items() if sy9.upper() in ss9}
                fw9 = o9.get("from_w") or set()
                cx9 = [(getattr(self, "_of_cands", None) or {}).get(k9) for k9 in cand9]
                cx9 = [c9 for c9 in cx9 if c9]
                def _rk9(c9):
                    same9 = bool(c9.get("stable")) and abs(float(c9.get("qty") or 0) - sent_q9.get(str(c9.get("sym") or "").upper(), -1e18)) <= \
                        0.01 * max(1.0, sent_q9.get(str(c9.get("sym") or "").upper(), 0))
                    return (str(c9.get("where") or "") not in fw9, not same9, abs(int(c9["ts"]) - int(o9["first"])))
                cand_top9 = [{"key": c9["key"], "sym": c9["sym"], "qty": c9["qty"], "ts": int(c9["ts"]), "stable": bool(c9.get("stable")),
                              "where": self._of_where(c9.get("where") or ""), "fromSender": str(c9.get("where") or "") in fw9,
                              "kind": "refund" if c9.get("stable") else "tokens"} for c9 in sorted(cx9, key=_rk9)[:3]]
                for c9 in cx9:
                    sug_pid9.setdefault(c9["pid"], {"a": a, "nm": salelink.dest_name(a, d9), "key": c9["key"],
                                                    "kind": "refund" if c9.get("stable") else "tokens", "fromSender": str(c9.get("where") or "") in fw9})
            ltok9 = sum(float(x9["costUsd"] or 0) for x9 in lv9 if x9["kind"] == "tokens" and x9["st"] == "applied")
            ad_syms9 = {sy9 for sy9, t9 in o9["tokens"].items() if _ph9(t9) and _ad9(t9)}
            ph_syms9 = {sy9 for sy9, t9 in o9["tokens"].items() if _ph9(t9)} - ad_syms9
            ph_txn9 = 0
            if ph_syms9:
                tsy9 = {tx9: set(sy9) for tx9, sy9 in (o9.get("txsyms") or {}).items()}
                for tx9, sy9 in (o9.get("hsyms") or {}).items():
                    if tx9 not in (o9.get("txsyms") or {}):
                        tsy9.setdefault(tx9, set()).update(sy9)
                ph_txn9 = sum(1 for tx9 in o9["txs"] if tsy9.get(tx9) and tsy9[tx9] <= ph_syms9)
            wait9 = None
            if verdict == "external" and d9.get("category") == self.OUTFLOW_SALE_CAT \
                    and not any(x9["kind"] == "tokens" and x9["st"] == "applied" for x9 in lv9):
                w9 = (send9 or now9) - ret_usd - ltok9
                wait9 = round(w9, 2) if w9 >= 0.005 else None
            rows.append({
                "address": a, "chains": sorted(o9["chains"]), "chainNames": [CHAIN_NAME.get(c, c) for c in sorted(o9["chains"])],
                "firstTs": int(o9["first"]), "lastTs": int(o9["last"]),
                "first": datetime.fromtimestamp(o9["first"], KST).strftime("%Y-%m-%d"),
                "last": datetime.fromtimestamp(o9["last"], KST).strftime("%Y-%m-%d"),
                "count": len(o9["txs"]), "tokens": toks,
                "usdAtSend": _f(send9, 2) or 0, "usdNow": _f(now9, 2) or 0, "costUsd": _f(cost9, 2) or 0,
                "usdAtSendKnown": all(t9["usd_send_known"] for t9 in o9["tokens"].values() if not _ph9(t9)),
                "dust": bool(status == "pending" and dust_usd > 0 and a not in ("multi", "?")
                             and all(t9["usd_send_known"] for t9 in o9["tokens"].values() if not _ph9(t9))
                             and max(send9, now9) < dust_usd),
                "status": status, "verdict": verdict or None, "retOk": bool(d9.get("ret") is True and status == "returned"),
                "applyWait": bool(status == "own_restart_needed" and a in reload_addrs9),
                "category": d9.get("category"), "memo": d9.get("memo"), "alias": d9.get("alias"),
                "links": lv9, "linkRefundUsd": _f(lref9, 2) or 0, "linkTokenUsd": _f(ltok9, 2) or 0, "saleWait": wait9,
                "excludeLegs": [str(k0.get("key") if isinstance(k0, dict) else k0) for k0 in (d9.get("excludeLegs") or [])
                                if isinstance(k0, (str, dict))][:200],
                "candN": len(cand9) if cand9 is not None else None,
                "candTop": cand_top9,
                "linkPaidUsd": _f(float(ms9["paidUsd"]), 2) if verdict == "external" and ms9.get("paidUsd") is not None else None,
                "exchange": d9.get("exchange") or (o9["auto"][1] if o9.get("auto") else None),
                "decidedTs": d9.get("ts"), "hints": hints, "flags": flags,
                "autoMatch": ({"basis": bas9 or ["txid"], "matched": len(o9.get("mtx") or ()),
                               "of": len(o9.get("rtx") or o9["txs"]),
                               "exchange": o9["auto"][1] if o9.get("auto") else (
                                   "프로그램 예치 왕복" if set(bas9) == {"roundtrip"} else "브릿지 → 내 지갑")}
                              if (o9.get("auto") or o9.get("mtx")) else None),
                "noAuto": bool(d9.get("noAuto")),
                "bridge": ({"name": blab9["name"], "chain": blab9.get("chain")} if blab9 else None),
                "arrivals": sorted(o9.get("arrivals") or [], key=lambda x: -x["ts"])[:50], "arrivalsN": len(o9.get("arrivals") or []),
                "suggest": sugg[0] if sugg else None, "suggestions": sugg,
                "returned": sorted(rt9["after"], key=lambda x: -x["ts"])[:50], "returnedN": len(rt9["after"]),
                "returnedUsd": _f(ret_usd, 2) or 0, "returnKind": rkind,
                "netUsd": _f(sent_v - ret_usd - ltok9, 2) or 0, "matchedUsd": _f(m_usd, 2) or 0,
                "priorIn": {"n": len(rt9["before"]), "usd": _f(sum(x["usd"] or 0 for x in rt9["before"]), 2) or 0},
                "txs": [dict(x9, phantom=True) if x9.get("sym") in ph_syms9 else dict(x9, quar="airdrop") if x9.get("sym") in ad_syms9 else x9
                        for x9 in sorted(o9["list"], key=lambda x: -x["ts"])[:self.OF_LIST_CAP]],
                "txsCut": int(o9.get("listCut") or 0),
                "phantomTxN": ph_txn9})
            if o9.get("listCut"):
                rows[-1]["walletUsdAtSend"] = float(o9.get("wusd") or 0.0)
                rows[-1]["walletDays"] = dict(o9.get("wdays") or {})
            if xw9:
                rows[-1]["exwd"] = [{"ex": x9["ex"], "exName": x9["src"], "sym": x9["sym"], "qty": float(x9["qty"]), "net": x9.get("net") or "",
                                     "txid": x9.get("txid_raw") or "", "uuid": str(x9["uuid"]), "ts": int(x9["ts"]), "addr": x9.get("addr") or "",
                                     "cls": x9.get("cls"), "dst": x9.get("dst"), "why": x9.get("why"),
                                     "offc": _offc_tx(x9.get("txid_raw"))} for x9 in xw9[-20:]]
                rows[-1]["exwdN"] = len(xw9)
                oc9 = [x9 for x9 in xw9 if _offc_tx(x9.get("txid_raw"))]
                if oc9:
                    rows[-1]["exwdOffc"] = {"n": len(oc9), "ex": sorted({x9["ex"] for x9 in oc9})}
                if not ob.get(a):
                    rows[-1]["exwdOnly"] = True
            b9 = tot.setdefault(status, {"n": 0, "usdAtSend": 0.0, "usdNow": 0.0})
            fr9 = (sent_v / (send9 or now9)) if m_usd and (send9 or now9) else 1.0
            b9["n"] += 1; b9["usdAtSend"] += max(0.0, send9 - m_usd) if m_usd else send9; b9["usdNow"] += now9 * fr9
            if d9.get("category"):
                c9 = tot.setdefault("category:" + d9["category"], {"n": 0, "usdAtSend": 0.0, "usdNow": 0.0})
                c9["n"] += 1; c9["usdAtSend"] += send9; c9["usdNow"] += now9
            if ltok9 > 0:
                t9t = tot.setdefault("link_tokens", {"n": 0, "usdAtSend": 0.0, "usdNow": 0.0})
                t9t["n"] += 1; t9t["usdAtSend"] += ltok9; t9t["usdNow"] += ltok9
            if wait9:
                w9t = tot.setdefault("sale_wait", {"n": 0, "usdAtSend": 0.0, "usdNow": 0.0})
                w9t["n"] += 1; w9t["usdAtSend"] += wait9; w9t["usdNow"] += wait9
        rows.sort(key=lambda r9: (r9["status"] != "pending", -r9["lastTs"]))
        self._outflow_dests = {r9["address"]: r9["chains"] for r9 in rows}
        self._outflow_status = {r9["address"]: r9["status"] for r9 in rows}
        self._outflow_still = frozenset(a9 for a9 in self._outflow_status if a9 in ob)
        self._outflow_autorows = {r9["address"] for r9 in rows if r9.get("autoMatch")}
        self._outflow_exwd = {r9["address"] for r9 in rows if r9.get("exwdOnly")}
        self._outflow_first = {r9["address"]: r9["firstTs"] for r9 in rows}
        self._outflow_from_w = {a9: set(o9.get("from_w") or ()) for a9, o9 in groups.items() if o9.get("from_w")}
        self._sale_send_tx = {str(t9).lower() for a9, o9 in groups.items()
                              if isinstance(dec.get(a9), dict) and dec[a9].get("verdict") == "external" and dec[a9].get("category") == self.OUTFLOW_SALE_CAT
                              for t9 in (o9.get("txs") or ()) if t9}
        self._outflow_legkeys = {r9["address"]: {str(t9.get("key")) for t9 in (groups.get(r9["address"]) or {}).get("list") or [] if t9.get("key")}
                                 for r9 in rows}
        self._outflow_legmeta = {a9: {x0[6]: (x0[7], x0[8]) for x0 in (o9.get("sends") or ()) if x0[6]} for a9, o9 in ob.items()}
        try:
            self._sale_cand_notify(sale_cands9)
        except Exception as e9:
            calcguard.swallowed("view_outflows:OutflowsMixin._outflows", e9)
            log.warning("세일 참가금 후보 알림 실패(다음 빌드): %s", e9)
        self._outflow_rettx = {r9["address"]: {str(x9.get("tx") or "").lower() for x9 in r9.get("returned") or []} for r9 in rows if r9.get("returned")}
        return rows, n_pend, {k: {"n": v["n"], "usdAtSend": round(v["usdAtSend"], 2), "usdNow": round(v["usdNow"], 2)}
                              for k, v in tot.items()}

    def _flow_cache_load(self) -> dict:
        p9 = os.path.join(common.STATE_DIR, flow_trace.CACHE_NAME)
        try:
            st9 = os.stat(p9)
            sig9 = (st9.st_ino, st9.st_mtime_ns, st9.st_size)
        except OSError:
            sig9 = None
        hit9 = self.__dict__.get("_flow_cache_hit")
        if sig9 is not None and hit9 is not None and hit9[0] == sig9:
            return hit9[1]
        c9 = flow_trace.load_cache(common.STATE_DIR)
        self._flow_cache_hit = (sig9, c9) if sig9 is not None else None
        return c9

    def _attach_flows(self, conn, rows: list, live_px: dict, G: dict):
        cache = self._flow_cache_load()
        rows = [r9 for r9 in rows if not r9.get("exwdOnly")]
        cands = flow_trace.candidates(rows, cache, min_usd=float((self.cfg.get("flow_trace") or {}).get("min_usd") or flow_trace.MIN_USD))
        off9 = set(self.cfg.get("_disabled_chains") or ())
        if off9:
            cands = [c9 for c9 in cands if not off9.intersection(c9.get("chains") or ())]
        lk9 = getattr(self, "_flow_lock", None)
        if lk9 is not None:
            with lk9:
                self._flow_pending = cands
        try:
            mine = {xchain_match.norm(w.get("address")) for w in (common.read_json(common.CONFIG_PATH, {}) or {}).get("wallets") or []
                    if w.get("address")}
            alias = {xchain_match.norm(w.get("address")): (w.get("label") or "") for w in (common.read_json(common.CONFIG_PATH, {}) or {}).get("wallets") or []
                     if w.get("address")}
        except BaseException as _cg9:
            calcguard.swallowed("view_outflows:OutflowsMixin._attach_flows", _cg9)
            mine, alias = set(), {}
        by_addr = {r9["address"]: r9 for r9 in rows}
        dec = self.outflow_decisions()
        exch = {}
        for a9, kk in self._known_addrs().items():
            for k9, n9 in kk:
                if k9 == "exchange_deposit":
                    exch.setdefault(a9, n9)
        for r9 in rows:
            if r9["status"] in ("exchange", "exchange_matched", "exchange_applying") and r9["address"] not in ("multi", "?"):
                exch.setdefault(r9["address"], "거래소 입금주소" + (f" ({r9['exchange']})" if r9.get("exchange") else ""))
        for a9, v9 in dec.items():
            if isinstance(v9, dict) and v9.get("verdict") == "own":
                mine.add(xchain_match.norm(a9))
        bridges = {a9: (v9.get("name") or "브릿지") for a9, v9 in self._bridge_labels().items()}
        ents = {r9["address"]: (cache.get("dest") or {}).get(r9["address"]) for r9 in rows}
        recips = set()
        for a9, e9 in ents.items():
            for ev9 in flow_trace.all_events(e9 or {}):
                if ev9.get("kind") == "out" and ev9.get("cp") and ev9["cp"] != "?":
                    recips.add(ev9["cp"])
        targets = {a9 for a9 in recips if a9 not in mine} | {r9["address"] for r9 in rows if r9["address"] not in ("multi", "?")}
        pseudo = {a9: {"first": 0, "txs": set(), "phantom": False} for a9 in targets}
        back = {a9: v9.get("after") or [] for a9, v9 in self._outflow_returns(conn, pseudo, live_px, G).items()}
        from_mine = {}
        want_tx = {}
        for a9, r9 in by_addr.items():
            if a9 in ("multi", "?") or r9["status"] == "spam":
                continue
            from_mine[a9] = {"n": r9["count"], "usd": float(r9.get("usdAtSend") or r9.get("usdNow") or 0), "wallets": set()}
            for t9 in r9.get("txs") or []:
                want_tx[t9["tx"]] = a9
        ks = list(want_tx)
        for i in range(0, len(ks), 400):
            ch = ks[i:i + 400]
            for rr in conn.execute("SELECT DISTINCT source_id, location FROM postings WHERE source_kind='chain_tx' AND leg_kind='move_out'"
                                   " AND location LIKE 'wallet:%' AND source_id IN (" + ",".join("?" * len(ch)) + ")", ch).fetchall():
                a9 = want_tx.get(rr["source_id"])
                if a9 in from_mine:
                    from_mine[a9]["wallets"].add(str(rr["location"]).split(":")[-1])
        sym_px = {}
        for gid9, g9 in G.items():
            if g9.get("sym") and live_px.get(gid9):
                sym_px.setdefault(str(g9["sym"]).upper(), float(live_px[gid9]))
        exch_in = {}
        for a9, ds9 in (getattr(self, "_of_deps_origin", None) or {}).items():
            for d9 in ds9:
                cur9 = outflow_match.canon_sym(d9.get("cur"), d9.get("ex"))
                amt9 = float(d9.get("amt") or 0)
                usd9 = amt9 if cur9 in outflow_match.STABLES else (amt9 * sym_px[cur9] if cur9 in sym_px else None)
                exch_in.setdefault(a9, []).append({"ts": int(d9.get("ts") or 0), "usd": _f(usd9, 2) if usd9 is not None else None,
                                                   "ex": d9.get("ex"), "txn": d9.get("txn"), "sym": cur9, "qty": amt9})
        wd_in = {a9: {"n": int(u9.get("n") or 0), "exchanges": [self.EX_NAME_KO.get(x9, x9) for x9 in u9.get("exchanges") or []]}
                 for a9, u9 in (getattr(self, "_wd_dest_unknown", None) or {}).items()}
        rinfo = {a9: {"status": r9["status"], "returnKind": r9.get("returnKind"), "priorUsd": (r9.get("priorIn") or {}).get("usd") or 0}
                 for a9, r9 in by_addr.items()}
        ap = getattr(self, "_flow_asset_px", None)
        n_as = conn.execute("SELECT COUNT(*) AS n FROM assets").fetchone()["n"]
        if not ap or ap[0] != n_as:
            amap = {}
            for rr in conn.execute("SELECT chain, address, group_id, asset_id FROM assets WHERE address IS NOT NULL").fetchall():
                amap[(rr["chain"], xchain_match.norm(rr["address"]))] = rr["group_id"] or -rr["asset_id"]
            ap = self._flow_asset_px = (n_as, amap)
        nat_gid = {}
        for gid9, g9 in G.items():
            if g9.get("sym") in ("SOL", "ETH", "BNB", "POL") and live_px.get(gid9):
                nat_gid.setdefault(g9["sym"], gid9)

        q_flow9 = set(getattr(self, "_risk_quarantined", None) or ()) - set(getattr(self, "_risk_airdrop_only", None) or ())

        def px_now(chain, token, sym):
            if token == "native":
                g9 = nat_gid.get(flow_trace.NATIVE.get(chain, "SOL") if chain != "sol" else "SOL")
                return float(live_px.get(g9) or 0) or None
            if flow_trace.stable_sym(chain, token):
                return 1.0
            g9 = ap[1].get((chain, xchain_match.norm(token)))
            if g9 is None:
                return None
            if (G.get(g9) or {}).get("is_stable"):
                return 1.0
            if g9 in q_flow9:
                return None
            return float(live_px.get(g9) or 0) or None

        def lookalike(x9):
            if x9 in mine or len(x9) < 12:
                return False
            return any(m9 != x9 and len(m9) == len(x9) and m9[:4] == x9[:4] and m9[-4:] == x9[-4:] for m9 in mine)
        grp9 = {}
        try:
            for ra9 in conn.execute("SELECT chain, address, group_id, asset_id FROM assets WHERE kind='token' AND address IS NOT NULL").fetchall():
                gs9 = (G.get(ra9["group_id"] or -ra9["asset_id"]) or {}).get("sym")
                if gs9:
                    grp9[(ra9["chain"], xchain_match.norm(ra9["address"]))] = gs9
        except Exception as _cg9:
            calcguard.swallowed("view_outflows:OutflowsMixin._attach_flows", _cg9)
            grp9 = {}
        spam_tok9 = self._flow_spam_tokens(ap[1], q_flow9)
        ctx = {"mine": mine, "alias": alias, "exch": exch, "bridges": bridges, "lookalike": lookalike, "back": back,
               "from_mine": from_mine, "exch_in": exch_in, "wd_in": wd_in, "rows": rinfo, "grp": grp9, "spam_tok": spam_tok9}
        reg9 = {}
        for r9 in rows:
            if r9["status"] not in flow_trace.ELIGIBLE or r9["address"] in ("multi", "?") or r9.get("dust") or flow_trace.is_burn(r9["address"]):
                continue
            if max(float(r9.get("usdAtSend") or 0), float(r9.get("usdNow") or 0)) < flow_trace.MIN_USD:
                continue
            e9 = ents.get(r9["address"])
            cl9 = getattr(self, "_of_claim_legs", None) or {}
            if cl9:
                r9f = dict(r9, links=cl9.get(r9["address"]) or [], linkedAway=[l9 for a9, ls9 in cl9.items() if a9 != r9["address"] for l9 in ls9])
            else:
                r9f = r9
            f9 = flow_trace.account(r9f, e9, ctx, px_now=px_now)
            if not e9:
                f9["status"] = "queued"
            elif e9.get("status") in ("budget", "paused", "running", "error") and not e9.get("t"):
                f9["status"] = "scanning" if e9.get("status") != "error" else "error"
                now9f = time.time()
                t0f, rtf = float(e9.get("t0") or 0), float(e9.get("rt") or 0)
                if f9["status"] == "scanning" and ((t0f and now9f - t0f > flow_trace.SCAN_TIMEOUT_SEC)
                                                   or (rtf and now9f - rtf > flow_trace.SCAN_IDLE_SEC)):
                    f9["status"] = "timeout"
                f9["scanSince"] = int(t0f) or None
                f9["lastTry"] = int(rtf) or None
                f9["scanWhy"] = str(e9.get("status") or "")
            r9["flow"] = f9
            if r9["status"] == "pending" and f9.get("status") in ("ok", "partial") and float(f9.get("sent") or 0) > 0 \
                    and float(f9.get("net") or 0) <= 0.5:
                sg9 = {"kind": "returned", "exchange": None, "label": "전액 이상 되돌려 받음", "action": "mark_returned",
                       "evidence": "흐름 추적 기준 · 직접·경유·거래소·브릿지로 돌려받은 돈이 보낸 돈 이상이에요"}
                r9["suggestions"] = [sg9] + [x9 for x9 in (r9.get("suggestions") or []) if x9.get("kind") != "roundtrip"]
                r9["suggest"] = sg9
                r9["retSugg"] = True
            for x9 in f9["recips"]:
                if x9["base"] == "eoa":
                    g9 = reg9.setdefault(x9["addr"], {"chains": set(), "dests": set(), "level": x9["score"]["level"]})
                    g9["chains"].update(x9["chains"]); g9["dests"].add(r9["address"])
        self._flow_recips = reg9

    @staticmethod
    def _flow_spam_tokens(amap: dict, quarantined) -> frozenset:
        q9 = set(quarantined or ())
        return frozenset(k9 for k9, g9 in (amap or {}).items() if g9 in q9) if q9 else frozenset()
