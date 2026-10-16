import chain_event
import common
import discopen
import json
import os
import time
from core_common import CLASSIFIER_VER
from core_common import dm
import logging

log = logging.getLogger('tj-core')


class SnapMixin:

    @staticmethod
    def _snap_quality(snap: dict) -> str:
        syn = (snap.get("tx") or {}).get("synth")
        if syn == "rpc":
            return "rpc_basic"
        if syn == "bs_list" or snap.get("src") == "bs_list":
            return "bs_list"
        return "blockscout_full"

    _ES_TT_KEYS = frozenset(("from", "to", "token", "total", "via"))

    _ES_IT_KEYS = frozenset(("from", "to", "value", "success", "error", "attr", "via"))

    @classmethod
    def _es_shape(cls, snap: dict) -> bool:
        tx = snap.get("tx") or {}
        if not tx or tx.get("synth") or snap.get("src"):
            return False
        return all(isinstance(r, dict) and (set(r) <= cls._ES_TT_KEYS or (not isinstance(r.get("from"), dict) and set(r) - {"log_index"} <= cls._ES_TT_KEYS))
                   for r in snap.get("token_transfers") or []) \
            and all(isinstance(r, dict) and set(r) <= cls._ES_IT_KEYS for r in snap.get("internal") or [])

    @classmethod
    def _es_list(cls, snap: dict) -> bool:
        return cls._es_shape(snap) and not isinstance((snap.get("tx") or {}).get("from"), dict)

    @staticmethod
    def _leg_row_key(kind: str, r) -> str:
        if not isinstance(r, dict):
            return "raw:" + json.dumps(r, sort_keys=True, default=str)

        def a9(x):
            return str((x.get("hash") if isinstance(x, dict) else x) or "").lower()

        def n9(v):
            try:
                return str(int(str(v)))
            except (TypeError, ValueError):
                return "" if v is None else str(v)
        if kind == "internal":
            ok9 = not (r.get("success") is False or r.get("error"))
            return json.dumps(["it", a9(r.get("from")), a9(r.get("to")), n9(r.get("value")), ok9])
        tok = r.get("token") if isinstance(r.get("token"), dict) else {}
        tot = r.get("total") if isinstance(r.get("total"), dict) else {}
        typ = str(tok.get("type") or r.get("token_type") or "ERC-20").upper()
        ca = str(tok.get("address") or tok.get("address_hash") or "").lower()
        if typ == "ERC-721":
            q9 = ["id", n9(tot.get("token_id"))]
        elif typ == "ERC-20":
            q9 = ["v", n9(tot.get("value"))]
        else:
            q9 = ["v", n9(tot.get("value")), "id", n9(tot.get("token_id"))]
        return json.dumps(["tt", a9(r.get("from")), a9(r.get("to")), ca, typ] + q9)

    BD_ATTR = "balance_delta"

    VIA_RPC = "rpc"

    @classmethod
    def _via_mark(cls, snap: dict, keys=None) -> dict:
        out = dict(snap)
        for key in ("token_transfers", "internal"):
            rows = snap.get(key)
            if isinstance(rows, list):
                out[key] = [dict(r, via=cls.VIA_RPC) if (isinstance(r, dict) and r.get("via") != cls.VIA_RPC
                                                         and (keys is None or cls._leg_row_key(key, r) in keys)) else r for r in rows]
        return out

    RPC_SEEN = "_rpc_seen"

    @classmethod
    def _rpc_hist(cls, snap: dict) -> bool:
        if snap.get(cls.RPC_SEEN) or (snap.get("tx") or {}).get("synth") == "rpc" or cls._bd_rows(snap):
            return True
        return any(isinstance(r, dict) and r.get("via") == cls.VIA_RPC for key in ("token_transfers", "internal") for r in snap.get(key) or [])

    @classmethod
    def _bd_rows(cls, snap: dict) -> list:
        rows = [r for r in snap.get("internal") or [] if isinstance(r, dict)]
        if any(r.get("attr") == cls.BD_ATTR for r in rows):
            return [r for r in rows if r.get("attr") == cls.BD_ATTR]
        return rows if snap.get("internal_note") == cls.BD_ATTR else []

    @classmethod
    def _bd_mark(cls, snap: dict) -> dict:
        bd = cls._bd_rows(snap)
        if not bd or all(r.get("attr") == cls.BD_ATTR for r in bd):
            return snap
        ids = {id(r) for r in bd}
        return dict(snap, internal=[dict(r, attr=cls.BD_ATTR) if (isinstance(r, dict) and id(r) in ids) else r
                                    for r in snap.get("internal") or []])

    @classmethod
    def _bd_union(cls, base: dict, other: dict) -> list:
        def a9(x):
            return str((x.get("hash") if isinstance(x, dict) else x) or "").lower()

        def ok9(r):
            return isinstance(r, dict) and r.get("success") is not False and not r.get("error")
        base, other = cls._bd_mark(base), cls._bd_mark(other)
        tot, proto = {}, {}
        for snap in (base, other):
            bdw = {a9(r.get("to")) for r in cls._bd_rows(snap)}
            t9 = {}
            for r in snap.get("internal") or []:
                if ok9(r) and a9(r.get("to")) in bdw:
                    try:
                        t9[a9(r.get("to"))] = t9.get(a9(r.get("to")), 0) + int(str(r.get("value") or "0"))
                    except ValueError:
                        continue
            for w9, v9 in t9.items():
                tot[w9] = max(tot.get(w9, 0), v9)
            for r in cls._bd_rows(snap):
                proto.setdefault(a9(r.get("to")), r)
        bdids = {id(r) for r in cls._bd_rows(base)} | {id(r) for r in cls._bd_rows(other)}
        real = cls._merge_list_snaps({"internal": [r for r in base.get("internal") or [] if id(r) not in bdids]},
                                     {"internal": [r for r in other.get("internal") or [] if id(r) not in bdids]})["internal"]
        out = list(real)
        for w9, t9 in tot.items():
            r9 = 0
            for r in real:
                if ok9(r) and a9(r.get("to")) == w9:
                    try:
                        r9 += int(str(r.get("value") or "0"))
                    except ValueError:
                        pass
            if t9 > r9:
                out.append(dict(json.loads(json.dumps(proto[w9])), value=str(t9 - r9), success=True, attr=cls.BD_ATTR))
        return out

    @classmethod
    def _snap_merge(cls, old: dict, new: dict) -> dict:
        out = cls._merge_list_snaps(old, new)
        if cls._bd_rows(old) or cls._bd_rows(new):
            out["internal"] = cls._bd_union(old, new)
        cls._bd_note_fix(out)
        return out

    @classmethod
    def _bd_note_fix(cls, out: dict):
        if out.get("internal_note") == cls.BD_ATTR and not any(isinstance(r, dict) and r.get("attr") == cls.BD_ATTR
                                                               for r in out.get("internal") or []):
            out.pop("internal_note", None)

    @staticmethod
    def _merge_list_snaps(old: dict, new: dict) -> dict:
        out = json.loads(json.dumps(old))
        for key in ("token_transfers", "internal"):
            co, cn, rows = {}, {}, {}
            for r in old.get(key) or []:
                k = SnapMixin._leg_row_key(key, r)
                co[k] = co.get(k, 0) + 1
            for r in new.get(key) or []:
                k = SnapMixin._leg_row_key(key, r)
                cn[k] = cn.get(k, 0) + 1
                rows.setdefault(k, r)
            lst = out.setdefault(key, [])
            for k, n in cn.items():
                lst.extend(json.loads(json.dumps(rows[k])) for _ in range(max(0, n - co.get(k, 0))))
        ot, nt = old.get("tx") or {}, new.get("tx") or {}
        if (ot.get("raw_input") == "0x01" and str((ot.get("fee") or {}).get("value") or "0") == "0"
                and nt and nt.get("raw_input") != "0x01"):
            out["tx"] = json.loads(json.dumps(nt))
        elif isinstance(out.get("tx"), dict) and nt.get("type") == 126 and out["tx"].get("type") is None:
            out["tx"]["type"] = 126
            if nt.get("op_mint") is not None and out["tx"].get("op_mint") is None:
                out["tx"]["op_mint"] = nt.get("op_mint")
        return out

    @classmethod
    def _promote_keep(cls, old: dict, new: dict) -> dict:
        out = json.loads(json.dumps(new))
        if (old.get("tx") or {}).get("synth") == "rpc":
            old = cls._via_mark(old)
        cn = {}
        for r in new.get("token_transfers") or []:
            k = cls._leg_row_key("token_transfers", r)
            cn[k] = cn.get(k, 0) + 1
        seen = {}
        for r in old.get("token_transfers") or []:
            k = cls._leg_row_key("token_transfers", r)
            seen[k] = seen.get(k, 0) + 1
            if seen[k] > cn.get(k, 0):
                out.setdefault("token_transfers", []).append(json.loads(json.dumps(r)))
        if old.get("internal") or cls._bd_rows(new):
            out["internal"] = cls._bd_union(new, old)
            cls._bd_note_fix(out)
        via9 = {cls._leg_row_key(k9, r) for k9 in ("token_transfers", "internal") for r in old.get(k9) or []
                if isinstance(r, dict) and r.get("via") == cls.VIA_RPC}
        if via9:
            out = cls._via_mark(out, via9)
        return out

    @staticmethod
    def _legs_grow(old: dict, new: dict) -> bool:
        for key in ("token_transfers", "internal"):
            co, cn = {}, {}
            for r in old.get(key) or []:
                k = SnapMixin._leg_row_key(key, r)
                co[k] = co.get(k, 0) + 1
            for r in new.get(key) or []:
                k = SnapMixin._leg_row_key(key, r)
                cn[k] = cn.get(k, 0) + 1
            if any(n > co.get(k, 0) for k, n in cn.items()):
                return True
        return False

    @staticmethod
    def _internal_grows(old: dict, new: dict) -> bool:
        co, cn = {}, {}
        for r in old.get("internal") or []:
            k = SnapMixin._leg_row_key("internal", r)
            co[k] = co.get(k, 0) + 1
        for r in new.get("internal") or []:
            k = SnapMixin._leg_row_key("internal", r)
            cn[k] = cn.get(k, 0) + 1
        return any(n > co.get(k, 0) for k, n in cn.items())

    @staticmethod
    def _legs_cover(big: dict, small: dict) -> bool:
        for key in ("token_transfers", "internal"):
            cb = {}
            for r in big.get(key) or []:
                k = SnapMixin._leg_row_key(key, r)
                cb[k] = cb.get(k, 0) + 1
            for r in small.get(key) or []:
                k = SnapMixin._leg_row_key(key, r)
                if cb.get(k, 0) <= 0:
                    return False
                cb[k] -= 1
        return True

    def _tsfix_plan(self, old_snap: dict, new_u: dict) -> str:
        def is_list(s):
            return self._es_list(s) or self._snap_quality(s) in ("rpc_basic", "bs_list")
        old_l, new_l = is_list(old_snap), is_list(new_u)
        if old_l and new_l:
            act, out = "union", self._snap_merge(old_snap, new_u)
        elif old_l and self._legs_cover(new_u, old_snap):
            act, out = "promote", new_u
        elif not old_l and self._legs_cover(old_snap, new_u):
            act, out = "keep", old_snap
        elif not old_l and not new_l and self._legs_cover(new_u, old_snap):
            act, out = "promote", new_u
        elif not old_l and self._legs_cover(old_snap, dict(new_u, internal=[])):
            act, out = "union", self._snap_merge(old_snap, new_u)
        else:
            act, out = None, None
        if act == "keep" and not self._tx_legs(old_snap) >= self._tx_legs(new_u):
            act, out = "union", self._snap_merge(old_snap, new_u)
        if act is None or not (self._legs_cover(out, old_snap) and self._legs_cover(out, new_u)
                               and self._tx_legs(out) >= self._tx_legs(old_snap) | self._tx_legs(new_u)):
            raise RuntimeError("시각 보강본 레그 유실 위험 — 저장본(%s)·보강본(%s) 레그(가스·tx 값·실패 여부 포함)가 서로 모순이라 격리 유지(replay_poison 으로 재시도)"
                               % ("목록" if old_l else "완전 상세", "목록" if new_l else "완전 상세"))
        return act

    @staticmethod
    def _tx_legs(snap: dict) -> set:
        tx = snap.get("tx") if isinstance(snap.get("tx"), dict) else {}

        def a9(x):
            return str((x.get("hash") if isinstance(x, dict) else x) or "").lower()

        def i9(v):
            return 0 if v is None or v == "" else int(str(v))
        fee = i9((tx.get("fee") or {}).get("value") if isinstance(tx.get("fee"), dict) else None)
        mint9 = set()
        if tx.get("type") == 126:
            m9 = i9(tx.get("op_mint") if tx.get("op_mint") is not None else tx.get("value"))
            if m9:
                mint9.add(("mint", a9(tx.get("from")), m9))
        if not tx or (tx.get("raw_input") == "0x01" and not fee):
            return ({("st", "ok")} if (snap.get("token_transfers") or snap.get("internal")) else set()) | mint9
        out = {("st", "ok" if tx.get("status") == "ok" else "fail")} | mint9
        if fee > 0:
            out.add(("fee", a9(tx.get("from"))))
        val = i9(tx.get("value"))
        if val:
            out.add(("val", a9(tx.get("from")), a9(tx.get("to")), val))
        return out

    def _tx_wallet_sums(self, chain: str, txhash: str) -> dict:
        out = {}
        for p in self.conn.execute("SELECT asset_id, location, qty_base FROM postings WHERE source_kind='chain_tx'"
                                   " AND source_ns=? AND source_id=? AND location LIKE ?",
                                   (chain, txhash, f"wallet:{chain}:%")).fetchall():
            if p["location"].count(":") != 2:
                continue
            k = (p["asset_id"], p["location"])
            out[k] = out.get(k, 0) + int(p["qty_base"])
        return out

    def _rederive_anchor_safe(self, chain: str, txhash: str, rec: dict):
        t_before = self._tx_hist_ts(chain, txhash)
        before = self._tx_wallet_sums(chain, txhash)
        ev = self._maybe_rederive(chain, txhash, rec)
        self._anchor_absorb(chain, txhash, before)
        if ev is not None:
            self._hist_late_gone("chain_tx", chain, txhash, t_before)
        return ev

    def _tx_hist_ts(self, chain: str, txhash: str):
        r = self.conn.execute("SELECT MIN(event_ts) FROM postings WHERE source_kind='chain_tx' AND source_ns=? AND source_id=?",
                              (chain, txhash)).fetchone()
        if r and r[0] is not None:
            return int(r[0])
        row = self.conn.execute("SELECT snapshot FROM raw_txs WHERE chain=? AND txhash=?", (chain, txhash)).fetchone()
        try:
            snap9 = json.loads(row["snapshot"]) if row else {}
            return self._ts_of(snap9.get("ts") if (chain == "sol" or snap9.get("kind") == chain_event.KIND)
                               else (snap9.get("tx") or {}).get("timestamp")) if isinstance(snap9, dict) else None
        except (TypeError, ValueError, AttributeError):
            return None

    def _anchor_absorb(self, chain: str, txhash: str, before: dict, plan: list = None):
        outer9 = self.__dict__.get("_anchor_touch")
        touch9 = []
        self._anchor_touch = touch9
        try:
            n9, ts9 = self._anchor_absorb_run(chain, txhash, before, plan)
        finally:
            self._anchor_touch = outer9
        if isinstance(outer9, list):
            outer9.extend(touch9)
        if touch9 and plan is None:
            self._hist_anchor_mark(chain, txhash, touch9 + [ts9])
        return n9

    def _hist_anchor_mark(self, chain: str, txhash: str, tss):
        t9 = [int(t) for t in (tss or ()) if t is not None]
        if not t9:
            return None
        lo9 = min(t9)
        if lo9 >= common.kst_day0(time.time() + common.HIST_LATE_CLOSE_S):
            return None
        iso = common.hist_late_put(self.conn, lo9)
        log.info("대사 앵커 보정(%s %s) — 지난 곡선 다시 계산 표식: %s 부터", chain, str(txhash)[:14], iso)
        return iso

    def _anchor_absorb_run(self, chain: str, txhash: str, before: dict, plan: list = None):
        after = self._tx_wallet_sums(chain, txhash)
        if after == before or self._meta_get(f"ext_prewindow_tx:{chain}:{txhash}"):
            return 0, None
        n9 = 0
        row = self.conn.execute("SELECT snapshot FROM raw_txs WHERE chain=? AND txhash=?", (chain, txhash)).fetchone()
        try:
            snap9 = json.loads(row["snapshot"]) if row else {}
            ts = self._ts_of(snap9.get("ts") if (chain == "sol" or snap9.get("kind") == chain_event.KIND)
                             else (snap9.get("tx") or {}).get("timestamp")) if isinstance(snap9, dict) else None
        except (TypeError, ValueError, AttributeError):
            ts = None
        if ts is None:
            return 0, None
        blk9 = self._tx_block(chain, txhash)
        T, ws = self._recon_view(chain)
        pay = None
        wtimes = None
        for (aid, loc) in sorted(set(before) | set(after)):
            d = after.get((aid, loc), 0) - before.get((aid, loc), 0)
            if not d:
                continue
            w = loc.split(":", 2)[2].lower()
            sid = t9 = None
            if T and w in ws and self._absorbed(f"recon:{chain}", ts, T, blk9):
                if chain == "bsc":
                    if pay is None:
                        r9 = self.conn.execute("SELECT payload FROM raw_observations WHERE obs_id=?", (f"recon:{chain}",)).fetchone()
                        try:
                            pay = {str(k).lower(): {str(x).lower() for x in (v or {})}
                                   for k, v in (json.loads(r9[0]) if r9 and r9[0] else {}).items() if isinstance(v, dict)}
                        except (TypeError, ValueError):
                            pay = {}
                    a9 = self.conn.execute("SELECT kind, address FROM assets WHERE asset_id=?", (aid,)).fetchone()
                    k9 = "native:none" if (a9 and a9[0] == "native") else f"token:{str((a9 or [None, ''])[1] or '').lower()}"
                    if k9 not in pay.get(w, set()):
                        k9 = None
                if chain != "bsc" or k9 is not None:
                    sid, t9 = f"recon:{chain}", int(T)
            else:
                if wtimes is None:
                    wtimes = self._wrecon_times(chain)
                wt3 = wtimes.get(w)
                if wt3:
                    is_nat = bool(self.conn.execute("SELECT 1 FROM assets WHERE asset_id=? AND kind='native'", (aid,)).fetchone())
                    wt = wt3[1] if is_nat else wt3[0]
                    w_sid = loc.split(":", 2)[2] if chain == "sol" else w
                    sid9 = f"recon:{chain}:{w_sid}" + (":native" if (is_nat and wt3[2]) else "")
                    if wt and self._absorbed(sid9, ts, wt, blk9):
                        sid, t9 = sid9, wt
            if sid:
                a9 = self.conn.execute("SELECT kind, address FROM assets WHERE asset_id=?", (aid,)).fetchone()
                if a9 and a9[0] == "token" and not self._obs_tok_observed(sid, w, a9[1]):
                    sid = None
            if not sid and loc.count(":") == 2:
                sid, t9 = discopen.absorbed_by(self.conn, chain, loc, aid, blk9, ts)
            if sid:
                if plan is not None:
                    plan.append((sid, t9, aid, loc, -d))
                else:
                    self._anchor_adjust(chain, sid, t9, aid, loc, -d, txhash)
                n9 += 1
        return n9, ts

    def _anchor_pos_ts(self, chain: str, sid: str, T: int, loc: str) -> int:
        f9 = self.conn.execute("SELECT min(event_ts) FROM postings WHERE location=? AND source_kind='chain_tx'", (loc,)).fetchone()[0]
        pos_ts = self._win_t0(T, chain)
        if sid != f"recon:{chain}" and f9 is not None:
            pos_ts = min(pos_ts, int(f9) - 1)
        if discopen.is_disc(sid):
            pos_ts = discopen.anchor_at(self.conn, sid) or pos_ts
        return int(pos_ts)

    def _ext_unmoved(self, chain: str) -> bool:
        for r in self.conn.execute("SELECT p.source_id, p.qty_base, p.event_ts, o.observed_at FROM postings p"
                                   " JOIN raw_observations o ON o.obs_id = p.source_id"
                                   " WHERE p.source_kind='opening' AND p.source_ns=? AND p.source_id >= 'recon:' AND p.source_id < 'recon;'",
                                   (chain,)).fetchall():
            try:
                if int(r["qty_base"]) > 0 and not discopen.is_disc(r["source_id"]) \
                        and int(r["event_ts"]) > self._win_t0(int(r["observed_at"]), chain) + 86400:
                    return True
            except (TypeError, ValueError):
                return True
        return False

    def _late_absorb(self, chain: str, txhash: str, ts: int, hits) -> bool:
        if chain == "sol":
            return False
        plan = []
        self._anchor_absorb(chain, txhash, {}, plan=plan)
        net9 = self._tx_wallet_sums(chain, txhash)
        need9 = {(loc9, aid9) for (loc9, aid9) in hits if net9.get((aid9, loc9), 0) != 0}
        if not plan or not need9 <= {(loc9, aid9) for (_s9, _t9, aid9, loc9, _c9) in plan}:
            return False
        if self._ext_unmoved(chain):
            return False
        for sid, t9, aid, loc, comp in plan:
            if discopen.is_disc(sid):
                return False
            r = self.conn.execute("SELECT qty_base, event_ts FROM postings WHERE source_kind='opening' AND source_ns=? AND source_id=?"
                                  " AND asset_id=? AND location=? ORDER BY leg_seq LIMIT 1", (chain, sid, aid, loc)).fetchone()
            q0 = int(r["qty_base"]) if r else 0
            if r and q0 > 0 and int(r["event_ts"]) > int(ts):
                return False
            if q0 + comp > 0 and q0 <= 0 and self._anchor_pos_ts(chain, sid, t9, loc) > int(ts):
                return False
        outer9 = self.__dict__.get("_anchor_touch")
        touch9 = []
        self._anchor_touch = touch9
        try:
            for sid, t9, aid, loc, comp in plan:
                self._anchor_adjust(chain, sid, t9, aid, loc, comp, txhash)
        finally:
            self._anchor_touch = outer9
        self._hist_anchor_mark(chain, txhash, touch9 + [ts])
        log.info("★[%s] %s 대사 뒤 처음 온 창 안 옛 거래 — 기초 잔고 %d칸을 그만큼 즉시 고침(재구축 없이 · 이중 계상 방지)★", chain, txhash[:14], len(plan))
        return True

    def _anchor_adjust(self, chain: str, sid: str, T: int, aid: int, loc: str, comp: int, txhash: str):
        r = self.conn.execute("SELECT posting_id, qty_base, event_ts FROM postings WHERE source_kind='opening' AND source_ns=? AND source_id=?"
                              " AND asset_id=? AND location=? ORDER BY leg_seq LIMIT 1", (chain, sid, aid, loc)).fetchone()
        pos_ts = self._anchor_pos_ts(chain, sid, T, loc)
        touch9 = getattr(self, "_anchor_touch", None)
        if r:
            q0 = int(r["qty_base"])
            nq = q0 + comp
            if isinstance(touch9, list):
                touch9.append(int(r["event_ts"]))
            if nq == 0:
                self._amend_leg(r["posting_id"], aid, loc, comp)
            else:
                ets = int(r["event_ts"]) if (nq > 0) == (q0 > 0) else (pos_ts if nq > 0 else int(T))
                self._amend_leg(r["posting_id"], aid, loc, comp, qb_new=nq, ts=ets)
                if isinstance(touch9, list):
                    touch9.append(int(ets))
        else:
            q0, nq = 0, comp
            if isinstance(touch9, list):
                touch9.append(int(pos_ts if comp > 0 else int(T)))
            seq = self.conn.execute("SELECT coalesce(max(leg_seq), -1) FROM postings WHERE source_kind='opening' AND source_ns=?"
                                    " AND source_id=?", (chain, sid)).fetchone()[0] + 1
            self._post_leg_strict("opening", chain, sid, seq, pos_ts if comp > 0 else int(T), aid, loc, comp,
                                  None, None, "opening", "OPENING")
        if isinstance(touch9, list):
            disc9 = discopen.is_disc(sid)
            if (not disc9 and (q0 < 0 or nq < 0)) or (disc9 and (q0 > 0 or nq > 0)):
                touch9.append(int(self._win_t0(None, chain)))
        log.info("★[%s] %s 재기장 — 대사 앵커(%s) %s 칸 보정 %d → %d (앵커가 흡수한 T 이전 흐름과 이중 계상 방지)★",
                 chain, txhash[:14], sid, loc.split(":", 2)[2][:10], q0, nq)

    def own_overlap_repair(self, apply: bool = False, chain: str = None) -> list:
        applied = sorted(r["k"][len("outflow_applied:"):] for r in self.conn.execute(
            "SELECT k, v FROM meta WHERE k >= 'outflow_applied:' AND k < 'outflow_applied;'").fetchall() if str(r["v"]).startswith("own:1"))
        out = []
        if not applied:
            return out
        try:
            for ch in sorted(self.my_wallets):
                if ch == "sol" or (chain and ch != chain):
                    continue
                mine = self.my_wallets.get(ch) or set()
                T_full, ws_full = self._recon_view(ch)
                wtimes = self._wrecon_times(ch)
                pre9 = {r[0].split(":", 2)[2] for r in self.conn.execute(
                    "SELECT k FROM meta WHERE k >= ? AND k < ?", (f"ext_prewindow_tx:{ch}:", f"ext_prewindow_tx:{ch};")).fetchall()}
                for a in applied:
                    if a not in mine:
                        continue
                    loc = f"wallet:{ch}:{a}"
                    sids = []
                    if T_full and a in ws_full:
                        sids.append((f"recon:{ch}", int(T_full), None))
                    wt3 = wtimes.get(a)
                    if wt3 and wt3[0]:
                        sids.append((f"recon:{ch}:{a}", int(wt3[0]), "token" if wt3[2] else None))
                    if wt3 and wt3[2] and wt3[1]:
                        sids.append((f"recon:{ch}:{a}:native", int(wt3[1]), "native"))
                    if not sids:
                        continue
                    rx = self.conn.execute(
                        "SELECT p.source_id, p.event_ts, p.asset_id, p.qty_base, r.ingested_at, r.block, r.wallets FROM postings p"
                        " JOIN raw_txs r ON r.chain=p.source_ns AND r.txhash=p.source_id WHERE p.location=? AND p.source_kind='chain_tx'"
                        " AND p.source_ns=? AND p.leg_kind='move_in' AND p.event='TRANSFER_SELF'", (loc, ch)).fetchall()
                    for sid, T, scope in sids:
                        R, R_all, t_rx = {}, {}, {}
                        for p in rx:
                            if p["source_id"] in pre9 or not self._absorbed(sid, int(p["event_ts"]), T, p["block"]):
                                continue
                            R_all[p["asset_id"]] = R_all.get(p["asset_id"], 0) + int(p["qty_base"])
                            t_rx[p["asset_id"]] = min(t_rx.get(p["asset_id"], int(p["event_ts"])), int(p["event_ts"]))
                            try:
                                persp = {str(x).lower() for x in (json.loads(p["wallets"] or "[]") or [])}
                            except (TypeError, ValueError):
                                continue
                            if a in persp or p["ingested_at"] is None or int(p["ingested_at"]) >= T:
                                continue
                            R[p["asset_id"]] = R.get(p["asset_id"], 0) + int(p["qty_base"])
                        if not any(R_all.values()):
                            continue
                        r9 = self.conn.execute("SELECT payload FROM raw_observations WHERE obs_id=?", (sid,)).fetchone()
                        try:
                            d9 = json.loads(r9[0]) if r9 and r9[0] else {}
                        except (TypeError, ValueError):
                            d9 = {}
                        wp = {}
                        for k9, v9 in (d9.items() if isinstance(d9, dict) else ()):
                            if isinstance(v9, dict) and str(k9).lower() == a:
                                wp = {str(x).lower(): y for x, y in v9.items()}
                        for aid in sorted(R_all):
                            if not R_all[aid]:
                                continue
                            a9 = self.conn.execute("SELECT kind, address, symbol FROM assets WHERE asset_id=?", (aid,)).fetchone()
                            is_nat = bool(a9 and a9["kind"] == "native")
                            if (scope == "token" and is_nat) or (scope == "native" and not is_nat):
                                continue
                            key = "native:none" if is_nat else f"token:{str((a9['address'] if a9 else '') or '').lower()}"
                            if key not in wp or (not is_nat and not self._obs_tok_observed(sid, a, a9["address"])):
                                continue
                            v9 = wp[key]
                            try:
                                bobs = None if isinstance(v9, (bool, float)) else int(v9)
                            except (TypeError, ValueError):
                                bobs = None
                            anc = F = 0
                            other9 = False
                            for q in self.conn.execute(
                                    "SELECT p.source_kind, p.source_ns, p.source_id, p.qty_base, p.event_ts, r.block FROM postings p"
                                    " LEFT JOIN raw_txs r ON p.source_kind='chain_tx' AND r.chain=p.source_ns AND r.txhash=p.source_id"
                                    " WHERE p.location=? AND p.asset_id=?", (loc, aid)).fetchall():
                                qb = int(q["qty_base"])
                                if q["source_kind"] == "opening" and q["source_ns"] == ch and q["source_id"] == sid:
                                    anc += qb
                                    continue
                                if q["source_kind"] == "opening" and qb:
                                    other9 = True
                                if q["source_kind"] == "chain_tx":
                                    if q["source_id"] not in pre9 and self._absorbed(sid, int(q["event_ts"]), T, q["block"]):
                                        F += qb
                                elif int(q["event_ts"]) < T:
                                    F += qb
                            D = None if bobs is None else anc - (bobs - F)
                            fixq = None
                            if D is not None and D != 0 and not other9:
                                fixq = R.get(aid) if (R.get(aid) and D == R.get(aid)) else (R_all[aid] if D == R_all[aid] else None)
                            act = "skip" if D is None else ("ok" if D == 0 else ("fix" if fixq else "skip"))
                            out.append({"chain": ch, "wallet": a, "sid": sid, "asset_id": aid, "symbol": (a9["symbol"] if a9 else None),
                                        "observed": None if bobs is None else str(bobs), "anchor": str(anc),
                                        "expected": None if bobs is None else str(bobs - F), "extra": None if D is None else str(D),
                                        "recv": str(fixq if fixq else R_all[aid]), "other_anchor": other9, "action": act})
                            if act == "fix" and apply:
                                outer9 = self.__dict__.get("_anchor_touch")
                                touch9 = []
                                self._anchor_touch = touch9
                                try:
                                    self._anchor_adjust(ch, sid, T, aid, loc, -fixq, "own_overlap")
                                finally:
                                    self._anchor_touch = outer9
                                self._hist_anchor_mark(ch, "own_overlap", touch9 + [t_rx.get(aid)])
                                log.warning("★own 중복 복구 [%s] %s %s — 기초 잔고 %d → %d(받은 레그와 겹친 양 %d)★",
                                            ch, a[:10], (a9["symbol"] if a9 else aid), anc, anc - fixq, fixq)
            if apply:
                self.conn.commit()
        except Exception:
            if apply:
                self.conn.rollback()
            raise
        return out

    def _rpc_touch(self, chain: str, txhash: str, old_snap: dict, new_u: dict, q_new: str, rpc_old: bool):
        if q_new != "rpc_basic" or rpc_old or common.ZK_STACK.get(chain):
            return
        keys = {self._leg_row_key(k9, r) for k9 in ("token_transfers", "internal") for r in new_u.get(k9) or [] if isinstance(r, dict)}
        marked = dict(self._via_mark(old_snap, keys) if keys else old_snap, **{self.RPC_SEEN: True})
        if marked != old_snap:
            self.conn.execute("UPDATE raw_txs SET snapshot=? WHERE chain=? AND txhash=?",
                              (json.dumps(marked, ensure_ascii=False), chain, txhash))

    def _maybe_rederive(self, chain: str, txhash: str, rec: dict):
        new_snap = rec.get("snapshot") or {}
        row = self.conn.execute("SELECT snapshot, wallets FROM raw_txs WHERE chain=? AND txhash=?",
                                (chain, txhash)).fetchone()
        if not row:
            return None
        try:
            old_snap = json.loads(row["snapshot"])
        except json.JSONDecodeError:
            old_snap = {}
        try:
            old_w = {str(w).lower() for w in (json.loads(row["wallets"] or "[]") or [])}
        except (json.JSONDecodeError, TypeError):
            old_w = set()
        new_w = {str(w).lower() for w in (rec.get("wallets") or [])}
        add_w = (new_w - old_w) & self.my_wallets.get(chain, set())
        q_old, q_new = self._snap_quality(old_snap), self._snap_quality(new_snap)
        es_list_new = self._es_list(new_snap)
        new_u = new_snap
        if common.ZK_STACK.get(chain) and old_snap.get("internal_note") == "zk_base_token" \
                and new_snap.get("internal_note") != "zk_base_token" and new_snap.get("tx"):
            ctx9 = (old_snap.get("tx") or new_snap.get("tx")) if es_list_new else new_snap.get("tx")
            new_u = dict(self._zk_norm(chain, dict(new_snap, tx=ctx9)), tx=new_snap.get("tx"))
        old_snap = self._bd_mark(old_snap)
        new_u = self._bd_mark(new_u)
        bd_any = bool(self._bd_rows(old_snap) or self._bd_rows(new_u))
        if q_new == "rpc_basic":
            new_u = self._via_mark(new_u)
        rpc_old = self._rpc_hist(old_snap)
        rpc9 = q_old == "rpc_basic" or q_new == "rpc_basic" or bd_any or rpc_old
        rpc_es_union = (q_old == "rpc_basic" and es_list_new)
        promote = (q_new == "blockscout_full" and q_old == "rpc_basic" and not rpc_es_union)
        merge_list = False
        tsf9 = isinstance(rec.get("ts_fix"), dict)
        if tsf9:
            act9 = self._tsfix_plan(old_snap, new_u)
            if common.ZK_STACK.get(chain):
                cand9 = new_snap if act9 == "promote" else (self._snap_merge(old_snap, new_u) if act9 == "union" else old_snap)
                zo9, zn9, zc9 = self._zk_norm(chain, old_snap), self._zk_norm(chain, new_u), self._zk_norm(chain, cand9)
                if not (self._legs_cover(zc9, zo9) and self._legs_cover(zc9, zn9) and self._tx_legs(zc9) >= self._tx_legs(zo9) | self._tx_legs(zn9)):
                    raise RuntimeError("시각 보강본 레그 유실 위험 — ZK 기장 정규화 뒤 결과가 저장본·보강본 레그를 다 담지 못해 격리 유지(replay_poison 으로 재시도)")
            promote, merge_list = act9 == "promote", act9 == "union"
            if merge_list and not add_w and self._snap_merge(old_snap, new_u) == old_snap:
                self._rpc_touch(chain, txhash, old_snap, new_u, q_new, rpc_old)
                return None
        elif add_w and not promote and q_new == "blockscout_full" and not self._es_shape(new_snap) \
                and (q_old == "bs_list" or self._es_shape(old_snap)):
            promote = True
        elif add_w and ((self._es_shape(old_snap) and self._es_shape(new_snap)) or (q_old == q_new == "bs_list")
                        or (q_old == q_new == "rpc_basic") or (q_old == "bs_list" and es_list_new)
                        or (q_new == "rpc_basic" and (q_old == "bs_list" or self._es_list(old_snap)))):
            merge_list = True
        elif (rec.get("repair") == "leg_union" or rpc_es_union) and not promote and ((self._es_shape(old_snap) and self._es_shape(new_snap))
                                                                                    or (q_old == q_new == "rpc_basic") or rpc_es_union
                                                                                    or (q_old == "bs_list" and es_list_new)):
            if not add_w and self._snap_merge(old_snap, new_u) == old_snap:
                return None
            merge_list = True
        if (not tsf9 and not promote and not merge_list and q_new == "blockscout_full" and q_old != "rpc_basic"
                and (old_snap.get("internal") or []) and self._internal_grows(old_snap, new_u)):
            merge_list = True
        if (not tsf9 and rec.get("repair") == "int_fill" and not promote and not merge_list and q_new == "blockscout_full"
                and not (old_snap.get("internal") or []) and (new_snap.get("internal") or [])):
            if es_list_new:
                merge_list = True
            else:
                promote = True
        if (not tsf9 and rec.get("repair") == "int_fill" and not promote and not merge_list and q_new == "rpc_basic"
                and new_snap.get("internal_note") in ("trace", "balance_delta") and (new_u.get("internal") or [])
                and self._internal_grows(old_snap, new_u)):
            merge_list = True
        if (not tsf9 and not promote and not merge_list and rpc9 and not common.ZK_STACK.get(chain)) and self._legs_grow(old_snap, new_u):
            merge_list = True
        if rpc9 and merge_list and not promote and not add_w and not tsf9 and self._snap_merge(old_snap, new_u) == old_snap:
            self._rpc_touch(chain, txhash, old_snap, new_u, q_new, rpc_old)
            return None
        if not promote and not add_w and not merge_list:
            self._rpc_touch(chain, txhash, old_snap, new_u, q_new, rpc_old)
            return None
        oe = self.conn.execute("SELECT event FROM tx_class WHERE chain=? AND txhash=?",
                               (chain, txhash)).fetchone()
        old_ev = oe["event"] if oe else None
        n_old = len(self._unpost_source("chain_tx", chain, txhash))
        keep = set()
        for t in self.conn.execute("SELECT transfer_id, state, asset_id FROM transfers"
                                   " WHERE chain_txhash=?", (txhash,)).fetchall():
            if t["state"] == "sent":
                self.conn.execute("DELETE FROM transfers WHERE transfer_id=?",
                                  (t["transfer_id"],))
            else:
                keep.add(t["asset_id"])
        merged_w = json.dumps(sorted(old_w | (new_w & self.my_wallets.get(chain, set()))))
        if promote:
            if "_lp_liq" in old_snap and "_lp_liq" not in new_snap:
                new_snap = dict(new_snap, _lp_liq=old_snap["_lp_liq"])
            if not tsf9 and not common.ZK_STACK.get(chain) and (q_old == "rpc_basic" or bd_any or rpc_old):
                new_snap = self._promote_keep(old_snap, new_snap)
            if rpc9:
                new_snap = dict(new_snap, **{self.RPC_SEEN: True})
            ntx = new_snap.get("tx") or {}
            self.conn.execute(
                "UPDATE raw_txs SET snapshot=?, block=?, blockhash=?, wallets=?, ingested_at=?"
                " WHERE chain=? AND txhash=?",
                (json.dumps(new_snap, ensure_ascii=False),
                 ntx.get("block_number") or ntx.get("block"), ntx.get("block_hash"),
                 merged_w, int(time.time()), chain, txhash))
            snap_use = new_snap
        elif merge_list:
            snap_use = self._snap_merge(old_snap, new_u)
            if q_new == "rpc_basic":
                snap_use = self._via_mark(snap_use, {self._leg_row_key(k9, r) for k9 in ("token_transfers", "internal")
                                                     for r in new_u.get(k9) or [] if isinstance(r, dict)})
            if rpc9:
                snap_use[self.RPC_SEEN] = True
            self.conn.execute("UPDATE raw_txs SET snapshot=?, wallets=?, ingested_at=? WHERE chain=? AND txhash=?",
                              (json.dumps(snap_use, ensure_ascii=False), merged_w, int(time.time()), chain, txhash))
        else:
            self.conn.execute("UPDATE raw_txs SET wallets=?, ingested_at=? WHERE chain=? AND txhash=?",
                              (merged_w, int(time.time()), chain, txhash))
            snap_use = old_snap
            self._rpc_touch(chain, txhash, old_snap, new_u, q_new, rpc_old)
        ev = self.apply(chain, txhash, "", snap_use, rederive=(old_ev, keep))
        try:
            os.remove(os.path.join(common.STATE_DIR, "daily_cache.json"))
        except FileNotFoundError:
            pass
        why = ("상세 승격" if promote else ("새 관점 " + ",".join(a[:10] for a in sorted(add_w))) if add_w
               else "누락 leg 복구") + (" · leg 합집합" if merge_list else "")
        log.info("★[%s] %s 재파생(%s): %s→%s (기존 legs %d 역적용)★",
                 chain, txhash[:14], why, old_ev, ev, n_old)
        if ev != old_ev:
            dm("PROMOTE" if promote else "REDERIVE",
               f"[{chain}] {why}으로 분류 변경 {old_ev}→{ev} tx {txhash}",
               {"chain": chain, "txhash": txhash})
        return ev

    @staticmethod
    def _sol_legs(snap: dict) -> set:
        legs = {(str(d.get("owner")), str(d.get("asset")), str(d.get("delta"))) for d in (snap.get("deltas") or [])}
        gas = int(snap.get("fee_lamports") or 0) if snap.get("fee_payer_mine") else 0
        if gas:
            legs.add((str(snap.get("fee_payer")), "__gas__", str(-gas)))
        return legs

    def _rederive_sol_anchor_safe(self, rec: dict):
        t_before = self._tx_hist_ts("sol", rec["txhash"])
        before = self._tx_wallet_sums("sol", rec["txhash"])
        ev = self._maybe_rederive_sol(rec)
        self._anchor_absorb("sol", rec["txhash"], before)
        if ev is not None:
            self._hist_late_gone("chain_tx", "sol", rec["txhash"], t_before)
        return ev

    def _maybe_rederive_sol(self, rec: dict):
        txhash = rec["txhash"]
        row = self.conn.execute("SELECT snapshot FROM raw_txs WHERE chain='sol' AND txhash=?", (txhash,)).fetchone()
        if not row:
            return None
        try:
            old = json.loads(row["snapshot"])
        except json.JSONDecodeError:
            return None
        lo, ln = self._sol_legs(old), self._sol_legs(rec)
        if ln == lo or not lo <= ln or bool(old.get("err")) != bool(rec.get("err")):
            return None
        oe = self.conn.execute("SELECT event FROM tx_class WHERE chain='sol' AND txhash=?", (txhash,)).fetchone()
        old_ev = oe["event"] if oe else None
        n_old = len(self._unpost_source("chain_tx", "sol", txhash))
        keep = set()
        for t in self.conn.execute("SELECT transfer_id, state, asset_id FROM transfers WHERE chain_txhash=?", (txhash,)).fetchall():
            if t["state"] == "sent":
                self.conn.execute("DELETE FROM transfers WHERE transfer_id=?", (t["transfer_id"],))
            else:
                keep.add(t["asset_id"])
        rec2 = dict(rec)
        rec2.pop("repersp", None)
        self.conn.execute("UPDATE raw_txs SET snapshot=?, wallets=?, ingested_at=? WHERE chain='sol' AND txhash=?",
                          (json.dumps(rec2, ensure_ascii=False), json.dumps(rec2.get("wallets", [])), int(time.time()), txhash))
        ev = self.apply_sol(rec2, rederive=(old_ev, frozenset(keep)))
        self._drop_daily_cache()
        new_o = sorted({o for o, _a, _d in ln - lo})
        log.info("★[sol] %s 재파생(새 관점 %s): %s→%s (기존 legs %d 역적용)★", txhash[:14],
                 ",".join(o[:10] for o in new_o), old_ev, ev, n_old)
        if ev != old_ev:
            dm("REDERIVE", f"[sol] 새 관점 {','.join(o[:10] for o in new_o)}으로 분류 변경 {old_ev}→{ev} tx {txhash}",
               {"chain": "sol", "txhash": txhash})
        return ev

    def _tsfix_sol(self, rec: dict):
        row = self.conn.execute("SELECT snapshot FROM raw_txs WHERE chain='sol' AND txhash=?", (rec["txhash"],)).fetchone()
        if not row:
            return None
        try:
            old = json.loads(row["snapshot"])
        except (json.JSONDecodeError, TypeError):
            old = None
        if not isinstance(old, dict):
            raise RuntimeError("솔라나 시각 보강본 — 저장본 해석 불가라 격리 유지(replay_poison 으로 재시도)")
        lo, ln = self._sol_legs(old), self._sol_legs(rec)
        if bool(old.get("err")) != bool(rec.get("err")) or not (ln <= lo or lo <= ln):
            raise RuntimeError("솔라나 시각 보강본 레그 유실 위험 — 저장본·보강본 델타(또는 실패 여부)가 서로 모순이라 격리 유지(replay_poison 으로 재시도)")
        if ln <= lo:
            return None
        return self._rederive_sol_anchor_safe(rec)
