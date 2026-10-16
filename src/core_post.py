import chain_event
import chain_registry
import common
import json
import lpdec
import lpsol
import os
import time
from core_common import CLASSIFIER_VER
from core_common import MissingTs
from core_common import dm
from decimal import Decimal
from decimal import localcontext
import logging

log = logging.getLogger('tj-core')


class PostMixin:

    LEG_BY_EVENT = {
        "SWAP": ("disp", "acq"), "CONVERT": ("move_out", "move_in"),
        "TRANSFER_SELF": ("move_out", "move_in"), "TRANSFER_OUT_EX": ("move_out", "move_in"),
        "BRIDGE": ("move_out", "move_in"), "TRANSFER_IN": (None, "acq"),
        "PROGRAM_IN": (None, "acq"),
        "STAKE_REWARD": (None, "acq"),
    }

    def apply(self, chain: str, txhash: str, wallets_json: str, snap: dict, rederive=None):
        if isinstance(snap, dict) and snap.get("kind") == chain_event.KIND:
            return self.apply_chain_delta(snap, rederive=rederive)
        event, deltas, perw, gas, gas_w, ts, ex_hint, dest = self.classify(chain, txhash, snap)
        return self._post_event(chain, txhash, event, deltas, perw, gas, gas_w, ts, ex_hint,
                                dest=dest, rederive=rederive)

    def _post_event(self, chain: str, txhash: str, event: str, deltas: dict, perw: dict,
                    gas: int, gas_w, ts: int, ex_hint, dest=None, rederive=None, extra_legs=None):
        quiet = rederive is not None
        keep_aids = rederive[1] if rederive else frozenset()
        self.conn.execute(
            "INSERT OR REPLACE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES (?,?,?,?,?)",
            (chain, txhash, event,
             json.dumps({"ex": ex_hint, "lp": (dest or {}).get("lp")} if (dest or {}).get("lp")
                        else ({"ex": ex_hint, "out": (dest or {}).get("out") or {}, "cps": (dest or {}).get("cps") or []}
                              if event == "TRANSFER_OUT" else {"ex": ex_hint})),
             CLASSIFIER_VER))

        def loc_of(w):
            return f"wallet:{chain}:{w}" if w else f"wallet:{chain}"

        legs = []
        if event in ("FAILED", "NOOP"):
            pass
        elif event.startswith("LP_"):
            lp9 = (dest or {}).get("lp") or {}
            self.__dict__.pop("_lp_learn_cache", None)
            legs = self._lp_legs(chain, txhash, perw, lp9, loc_of, ts)
            if not quiet:
                dm(event, f"[{chain}] {lp9.get('name') or 'LP'} {event} tx {txhash} · 포지션 {lp9.get('loc')}",
                   {"chain": chain, "txhash": txhash, "lp": lp9}, event_ts=ts)
        elif event == "TRANSFER_OUT":
            legs = self._out_legs(chain, perw, (dest or {}), loc_of)
            if not quiet:
                dm(event, f"[{chain}] {event} — 외부 전송(보낸 내역) tx {txhash}",
                   {"chain": chain, "txhash": txhash,
                    "to": (dest or {}).get("to"),
                    "counterparties": (dest or {}).get("cps") or [],
                    "deltas": {str(k): str(v) for k, v in deltas.items()}}, event_ts=ts)
        elif event in ("UNKNOWN", "NEW_ASSET"):
            if event == "UNKNOWN":
                legs = self._unknown_legs(perw, loc_of)
            if not quiet:
                dm(event, f"[{chain}] {event} — 검토 필요 tx {txhash}",
                   {"chain": chain, "txhash": txhash,
                    "to": (dest or {}).get("to"),
                    "counterparties": (dest or {}).get("cps") or [],
                    "deltas": {str(k): str(v) for k, v in deltas.items()}}, event_ts=ts)
        else:
            out_kind, in_kind = self.LEG_BY_EVENT.get(event, (None, None))
            self_in = {}
            if event in ("TRANSFER_IN", "PROGRAM_IN"):
                for (_w, aid), v in perw.items():
                    if v < 0:
                        self_in[aid] = self_in.get(aid, 0) - v
            for (w, aid), v in sorted(perw.items(), key=lambda kv: (kv[0][1], kv[0][0] or "")):
                if aid in self_in:
                    if v < 0:
                        legs.append(("move_out", aid, v, loc_of(w)))
                        continue
                    moved = min(v, self_in[aid])
                    if moved:
                        legs.append(("move_in", aid, moved, loc_of(w)))
                        self_in[aid] -= moved
                        v -= moved
                    if not v:
                        continue
                lk = out_kind if v < 0 else in_kind
                if lk is None:
                    continue
                legs.append((lk, aid, v, loc_of(w)))
            if event == "TRANSFER_OUT_EX":
                for (w, aid), v in perw.items():
                    if v < 0 and aid not in keep_aids:
                        self.conn.execute(
                            "INSERT INTO transfers (state, asset_id, qty_base, src, dst, chain_txhash, updated_at)"
                            " VALUES ('sent', ?, ?, ?, ?, ?, ?)",
                            (aid, str(-v), loc_of(w), f"exchange:{ex_hint}", txhash, int(time.time())))
                if not quiet:
                    dm("TRANSFER_OUT_EX", f"[{chain}] 거래소 전송 감지 tx {txhash}", None, event_ts=ts)
            elif event == "SWAP":
                if not quiet:
                    dm("SWAP", f"[{chain}] 스왑 감지 tx {txhash}", {"chain": chain, "txhash": txhash},
                       event_ts=ts)
            elif event == "PROGRAM_IN":
                if not quiet:
                    dm("PROGRAM_IN", f"[{chain}] 프로그램 경유 수령 tx {txhash} — 체결/에어드랍 검토",
                       {"chain": chain, "txhash": txhash}, event_ts=ts)
        if extra_legs:
            legs.extend(extra_legs)
        if gas:
            native_aid = self.asset_id("native", chain, None,
                                       symbol=self.native_sym.get(chain, chain.upper()),
                                       decimals=9 if chain == "sol" else chain_registry.native_decimals(chain, 18))
            legs.append(("gas", native_aid, -gas, loc_of(gas_w)))
        self._post_legs_strict([("chain_tx", chain, txhash, seq, ts, aid, l, v, None, None, lk, event)
                                for seq, (lk, aid, v, l) in enumerate(legs)])
        if event.startswith("LP_") and not getattr(self, "_lp_reflowing", False):
            self._lp_reflow(chain, txhash, (dest or {}).get("lp") or {}, ts)
        return event

    @staticmethod
    def _lp_locs_of(chain: str, lp: dict) -> set:
        pre = f"lp:{chain}:{lp.get('mgr') or ''}"
        out = {f"{pre}:{t}" for t in (lpdec.lp_tid(i) for i in (lp.get("ids") or [])) if t is not None}
        for k in ("dep_loc", "unk_loc"):
            if lp.get(k):
                out.add(lp[k])
        return out

    def _lp_reflow(self, chain: str, txhash: str, lp: dict, ts: int) -> None:
        mgr = lp.get("mgr") or ""
        if not mgr:
            return
        cands = []
        for r in self.conn.execute(
                "SELECT t.txhash, t.event, t.detail, (SELECT min(p.event_ts) FROM postings p WHERE p.source_kind='chain_tx'"
                "  AND p.source_ns=t.chain AND p.source_id=t.txhash) AS ets"
                " FROM tx_class t WHERE t.chain=? AND t.event LIKE 'LP_%' AND t.txhash != ?", (chain, txhash)).fetchall():
            if r["ets"] is None or (int(r["ets"]), r["txhash"]) <= (int(ts), txhash):
                continue
            try:
                lp2 = (json.loads(r["detail"] or "{}") or {}).get("lp") or {}
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue
            if (lp2.get("mgr") or "") != mgr:
                continue
            cands.append((int(r["ets"]), r["txhash"], r["event"], self._lp_locs_of(chain, lp2)))
        if not cands:
            return
        cands.sort(key=lambda x: (x[0], x[1]))
        locs = self._lp_locs_of(chain, lp)
        later = []
        for ets, h, ev, l2 in cands:
            if l2 & locs:
                later.append((ets, h, ev))
                locs |= l2
        if not later:
            return
        self._lp_reflowing = True
        try:
            for _e, h, _ev in later:
                self._unpost_source("chain_tx", chain, h)
            for _e, h, ev in later:
                row = self.conn.execute("SELECT snapshot FROM raw_txs WHERE chain=? AND txhash=?", (chain, h)).fetchone()
                if not row:
                    continue
                snap9 = json.loads(row["snapshot"])
                if chain == "sol" and snap9.get("kind") == "sol_tx":
                    self.apply_sol(snap9, rederive=(ev, frozenset()))
                    continue
                self.apply(chain, h, "", snap9, rederive=(ev, frozenset()))
        finally:
            self._lp_reflowing = False
        log.info("LP 재정렬: [%s] %s 도착으로 뒤 LP tx %d건 재기장", chain, txhash[:14], len(later))

    def _post_leg(self, kind: str, ns: str, sid, seq: int, ts: int, aid: int, loc: str, qb: int,
                  cost_usd, cost_krw, leg_kind: str, event: str) -> bool:
        c9 = self.conn.execute(
            "INSERT OR IGNORE INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base,"
            " cost_usd, cost_krw, leg_kind, event, classifier_ver) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (kind, ns, sid, seq, ts, aid, loc, str(qb), cost_usd, cost_krw, leg_kind, event, CLASSIFIER_VER))
        if not c9.rowcount:
            return False
        self._bump_position(aid, qb, loc)
        return True

    def _post_leg_strict(self, kind: str, ns: str, sid, seq: int, ts: int, aid: int, loc: str, qb: int,
                         cost_usd, cost_krw, leg_kind: str, event: str, ver: int = None) -> None:
        self._post_legs_strict([(kind, ns, sid, seq, ts, aid, loc, qb, cost_usd, cost_krw, leg_kind, event)], ver=ver)

    def _post_legs_strict(self, rows, ver: int = None) -> None:
        v9 = CLASSIFIER_VER if ver is None else ver
        for kind, ns, sid, seq, ts, aid, loc, qb, cost_usd, cost_krw, leg_kind, event in rows:
            self.conn.execute(
                "INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base,"
                " cost_usd, cost_krw, leg_kind, event, classifier_ver) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kind, ns, sid, seq, ts, aid, loc, str(qb), cost_usd, cost_krw, leg_kind, event, v9))
        for r9 in rows:
            self._bump_position(r9[5], r9[7], r9[6])

    def _amend_leg(self, pid: int, aid: int, loc: str, d_qb: int, qb_new=None, ts: int = None) -> None:
        if qb_new is None:
            self.conn.execute("DELETE FROM postings WHERE posting_id=?", (pid,))
        elif ts is None:
            self.conn.execute("UPDATE postings SET qty_base=? WHERE posting_id=?", (str(qb_new), pid))
        else:
            self.conn.execute("UPDATE postings SET event_ts=?, qty_base=? WHERE posting_id=?", (ts, str(qb_new), pid))
        self._bump_position(aid, d_qb, loc)

    def _unpost_source(self, kind: str, ns: str, sid) -> list:
        rows = self.conn.execute(
            "SELECT asset_id, location, qty_base, event_ts FROM postings WHERE source_kind=? AND source_ns=? AND source_id=?",
            (kind, ns, sid)).fetchall()
        for p in rows:
            self._bump_position(p["asset_id"], -int(p["qty_base"]), p["location"])
        self.conn.execute("DELETE FROM postings WHERE source_kind=? AND source_ns=? AND source_id=?", (kind, ns, sid))
        return rows

    def _bump_position(self, aid: int, v: int, loc: str) -> None:
        grp = self._group_of(aid)
        norm = self._norm(aid, v)
        row = self.conn.execute(
            "SELECT qty_norm FROM positions WHERE group_id=? AND location=?",
            (grp, loc)).fetchone()
        with localcontext() as ctx:
            ctx.prec = 100
            qty = Decimal(norm) + (Decimal(row["qty_norm"]) if row else Decimal(0))
            new_qty = format(qty, "f")
        if row:
            self.conn.execute("UPDATE positions SET qty_norm=? WHERE group_id=? AND location=?",
                              (new_qty, grp, loc))
        else:
            self.conn.execute("INSERT INTO positions (group_id, location, qty_norm) VALUES (?,?,?)",
                              (grp, loc, new_qty))

    def apply_sol(self, rec: dict, rederive=None):
        txhash = rec["txhash"]
        try:
            ts = int(rec.get("ts") or 0)
        except (TypeError, ValueError):
            ts = 0
        if ts <= 0:
            log.warning("시각 없는 sol tx 거부: %s ts=%r", str(rec.get("txhash") or "?")[:14], rec.get("ts"))
            raise MissingTs(f"sol tx 시각 없음: {rec.get('ts')!r}")
        if rec.get("stake_open"):
            return self._post_stake_open(rec, ts)
        perw = {}
        deltas = {}
        for d in rec.get("deltas", []):
            if d["asset"] == "native":
                aid = self.asset_id("native", "sol", None, symbol="SOL", decimals=9)
            else:
                aid = self.asset_id("token", "sol", d["asset"], symbol=d.get("symbol"),
                                    decimals=d.get("decimals"))
            v = int(d["delta"])
            if v:
                owner = d.get("owner")
                perw[(owner, aid)] = perw.get((owner, aid), 0) + v
                deltas[aid] = deltas.get(aid, 0) + v
        gas = int(rec.get("fee_lamports") or 0) if rec.get("fee_payer_mine") else 0
        gas_w = rec.get("fee_payer") if rec.get("fee_payer_mine") else None
        cps = set(rec.get("counterparties") or []) - self.sol_wallets
        only_mine = bool(rec.get("counterparties")) and not cps
        ex_rows = self.conn.execute(
            "SELECT address FROM exchange_addresses WHERE chain='sol'").fetchall()
        ex_addrs = {r["address"] for r in ex_rows}
        deltas = {a: v for a, v in deltas.items() if v != 0}
        outs = {a: v for a, v in deltas.items() if v < 0}
        ins = {a: v for a, v in deltas.items() if v > 0}
        self_move = (not deltas) and any(v for v in perw.values())
        lp9 = None if rec.get("err") else lpsol.lp_detect(rec, self.sol_wallets)
        if lp9 is not None and not any(lpsol.WSOL in (m or []) for m in (lp9.get("mints") or {}).values()):
            lp9["rent_aids"] = [self.asset_id("native", "sol", None, symbol="SOL", decimals=9)]
        if lp9 is not None:
            if outs and ins:
                ev9 = "LP_ADJUST"
            elif outs:
                ev9 = "LP_ADD"
            elif ins or lp9.get("burn"):
                ev9 = "LP_REMOVE"
            elif any(v for v in perw.values()):
                ev9 = "LP_ADJUST"
            else:
                ev9 = "NOOP"
            if ev9 != "NOOP":
                return self._post_event("sol", txhash, ev9, deltas, perw, gas, gas_w, ts, None,
                                        dest={"to": None, "cps": sorted(cps)[:4], "lp": lp9}, rederive=rederive)
        if rec.get("err"):
            event, ex_hint = "FAILED", None
        elif only_mine or self_move:
            event, ex_hint = "TRANSFER_SELF", None
        elif outs and cps and cps <= ex_addrs:
            event, ex_hint = "TRANSFER_OUT_EX", "upbit"
        elif outs and ins:
            if rec.get("has_program"):
                unconfirmed = [a for a in ins if not self.is_confirmed(a)]
                if unconfirmed:
                    for a in unconfirmed:
                        self.conn.execute("UPDATE assets SET confirmed=1 WHERE asset_id=?", (a,))
                    dm("NEW_ASSET", f"[sol] 새 자산 자동 기록 tx {txhash} — LP/예치 토큰이면 검토",
                       {"chain": "sol", "txhash": txhash,
                        "assets": [int(a) for a in unconfirmed]}, event_ts=ts)
                event, ex_hint = "SWAP", None
            else:
                event, ex_hint = "UNKNOWN", None
        elif outs:
            event, ex_hint = "TRANSFER_OUT", None
        elif ins and rec.get("stake_reward") and all(":stake:" in (w or "") for (w, _a), v in perw.items() if v):
            event, ex_hint = "STAKE_REWARD", None
        elif ins:
            event = "PROGRAM_IN" if rec.get("has_program") else "TRANSFER_IN"
            ex_hint = None
        else:
            event, ex_hint = "NOOP", None
        if event == "STAKE_REWARD" and ts < time.time() - 86400:
            self._drop_daily_cache()
        return self._post_event("sol", txhash, event, deltas, perw, gas, gas_w, ts, ex_hint,
                                dest={"to": None, "cps": sorted(cps)[:4]}, rederive=rederive)

    def apply_chain_delta(self, rec: dict, rederive=None):
        c = chain_event.to_core(rec)
        chain, uid, ts = c["chain"], c["uid"], c["ts"]
        sp = chain_registry.spec(chain)
        mine = set(self.chain_owners.get(chain) or ()) | set(c["owners"])
        aids = {}

        def aid_of(ak):
            if ak not in aids:
                if ak[0] == "native":
                    aids[ak] = self.asset_id("native", chain, None, symbol=sp.native_symbol, decimals=sp.native_decimals)
                else:
                    m9 = c["meta"].get(ak) or {}
                    if m9.get("decimals") is None:
                        r9 = self.conn.execute("SELECT decimals FROM assets WHERE kind='token' AND chain=? AND address IS ?",
                                               (chain, ak[1].lower() if ak[1] else None)).fetchone()
                        if r9 is None or r9["decimals"] is None:
                            raise chain_event.ContractError(f"[{chain}] 자릿수 미확인 토큰 {str(ak[1])[:24]} — 보류(18 로 짐작해 기장하지 않음)")
                    aids[ak] = self.asset_id("token", chain, ak[1], symbol=m9.get("symbol"), decimals=m9.get("decimals"))
            return aids[ak]
        perw, deltas = {}, {}
        for (o, ak), v in sorted(c["econ"].items(), key=lambda kv: (kv[0][0], kv[0][1][0], kv[0][1][1] or "")):
            a9 = aid_of(ak)
            perw[(o, a9)] = perw.get((o, a9), 0) + v
            deltas[a9] = deltas.get(a9, 0) + v
        deltas = {a: v for a, v in deltas.items() if v}
        outs = {a for a, v in deltas.items() if v < 0}
        ins = {a for a, v in deltas.items() if v > 0}
        moved = any(v for v in perw.values())
        cps = set(c["cps"]) - mine
        ex_rows = {r["address"]: r["exchange"] for r in self.conn.execute(
            "SELECT address, exchange FROM exchange_addresses WHERE chain=?", (chain,)).fetchall()}
        hint = c["hint"]
        if c["failed"]:
            event, ex_hint = ("UNKNOWN" if moved else "FAILED"), None
        elif not moved:
            event, ex_hint = "NOOP", None
        elif not deltas:
            event, ex_hint = "TRANSFER_SELF", None
        elif outs and not ins and cps and cps <= set(ex_rows):
            event, ex_hint = "TRANSFER_OUT_EX", sorted({ex_rows[a] for a in cps})[0]
        elif outs and ins:
            event, ex_hint = ("SWAP" if (hint == "swap" and c["trusted"] and c["trace_complete"]) else "UNKNOWN"), None
            if event == "SWAP":
                unconfirmed = [a for a in sorted(ins) if not self.is_confirmed(a)]
                for a in unconfirmed:
                    self.conn.execute("UPDATE assets SET confirmed=1 WHERE asset_id=?", (a,))
                if unconfirmed and rederive is None:
                    dm("NEW_ASSET", f"[{chain}] 새 자산 자동 기록 tx {rec.get('txhash')} — 검토",
                       {"chain": chain, "txhash": uid, "assets": [int(a) for a in unconfirmed]}, event_ts=ts)
        elif outs:
            event, ex_hint = "TRANSFER_OUT", None
        else:
            event = "PROGRAM_IN" if (hint in ("program_in", "stake", "swap", "unknown") or not c["trace_complete"]) else "TRANSFER_IN"
            ex_hint = None
        out9 = {}
        for (o, ak), to9 in c["dest"].items():
            out9[f"{o}|{aid_of(ak)}"] = to9
        extra = []
        for o, f in sorted(c["fee"].items()):
            loc9 = chain_registry.make_location(chain, o)
            extra.append(("gas", aid_of(("native", None)), -f, loc9) if f > 0 else ("acq", aid_of(("native", None)), -f, loc9))
        return self._post_event(chain, uid, event, deltas, perw, 0, None, ts, ex_hint,
                                dest={"to": None, "cps": sorted(cps)[:4], "out": out9}, rederive=rederive, extra_legs=extra)

    def _consume_chain_delta(self, rec: dict):
        chain_event.validate(rec)
        chain, uid = rec["chain"], rec["tx_uid"]
        sp = chain_registry.spec(chain)
        od = rec.get("order") or {}
        blk = od.get("height") if sp.order_kind == "height" else (od.get("checkpoint") if sp.order_kind == "checkpoint" else None)
        try:
            blk = int(blk) if blk is not None else None
        except (TypeError, ValueError):
            blk = None
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO raw_txs (chain, txhash, block, blockhash, ts, snapshot, wallets, ingested_at) VALUES (?,?,?,?,?,?,?,?)",
            (chain, uid, blk, (rec.get("finality") or {}).get("blockhash"), rec["ts"], json.dumps(rec, ensure_ascii=False),
             json.dumps(sorted(rec.get("owners") or [])), int(time.time())))
        if cur.rowcount:
            ev = self.apply_chain_delta(rec)
            log.info("[%s] %s → %s", chain, uid[:14], ev)
            self._note_pre_window(chain, rec["ts"], uid)
            return ev
        row = self.conn.execute("SELECT snapshot FROM raw_txs WHERE chain=? AND txhash=?", (chain, uid)).fetchone()
        try:
            old = json.loads(row["snapshot"])
        except (TypeError, ValueError):
            raise RuntimeError(f"[{chain}] 저장본 해석 불가 — 재방출 격리 유지(replay_poison 으로 재시도)")
        verdict = chain_event.merge_ok(old, rec)
        if verdict == "same":
            return None
        if verdict == "conflict":
            raise RuntimeError(f"[{chain}] 같은 tx 재방출이 저장본과 모순(레그 엇갈림·실패 여부 다름) — 격리 유지(replay_poison 으로 재시도)")
        t_before = self._tx_hist_ts(chain, uid)
        before = self._tx_wallet_sums(chain, uid)
        oe = self.conn.execute("SELECT event FROM tx_class WHERE chain=? AND txhash=?", (chain, uid)).fetchone()
        old_ev = oe["event"] if oe else None
        self._unpost_source("chain_tx", chain, uid)
        keep = set()
        for t in self.conn.execute("SELECT transfer_id, state, asset_id FROM transfers WHERE chain_txhash=?", (uid,)).fetchall():
            if t["state"] == "sent":
                self.conn.execute("DELETE FROM transfers WHERE transfer_id=?", (t["transfer_id"],))
            else:
                keep.add(t["asset_id"])
        self.conn.execute("UPDATE raw_txs SET snapshot=?, wallets=?, ingested_at=? WHERE chain=? AND txhash=?",
                          (json.dumps(rec, ensure_ascii=False), json.dumps(sorted(rec.get("owners") or [])), int(time.time()), chain, uid))
        ev = self.apply_chain_delta(rec, rederive=(old_ev, frozenset(keep)))
        self._anchor_absorb(chain, uid, before)
        self._hist_late_gone("chain_tx", chain, uid, t_before)
        self._drop_daily_cache()
        log.info("★[%s] %s 재파생(새 관점): %s→%s★", chain, uid[:14], old_ev, ev)
        if ev != old_ev:
            dm("REDERIVE", f"[{chain}] 새 관점으로 분류 변경 {old_ev}→{ev} tx {rec.get('txhash')}", {"chain": chain, "txhash": uid})
        return ev

    @staticmethod
    def _drop_daily_cache():
        try:
            os.remove(os.path.join(common.STATE_DIR, "daily_cache.json"))
        except FileNotFoundError:
            pass

    def _post_stake_open(self, rec: dict, ts: int) -> str:
        so = rec.get("stake_open") or {}
        acct = so.get("acct")
        sid = f"recon:sol:stake:{acct}"
        if not acct:
            return "NOOP"
        t_old9 = None
        if so.get("reopen"):
            for r9 in self.conn.execute("SELECT posting_id, asset_id, location, qty_base, event_ts FROM postings WHERE source_kind='opening'"
                                        " AND source_id=?", (sid,)).fetchall():
                self._amend_leg(r9["posting_id"], r9["asset_id"], r9["location"], -int(r9["qty_base"]))
                t_old9 = int(r9["event_ts"]) if t_old9 is None else min(t_old9, int(r9["event_ts"]))
            self.conn.execute(
                "INSERT OR REPLACE INTO raw_observations (obs_id, kind, venue, payload, observed_at) VALUES (?,?,?,?,?)",
                (sid + ":reopen", "opening_balance", "sol", json.dumps(so, ensure_ascii=False), int(time.time())))
        elif self.conn.execute("SELECT 1 FROM postings WHERE source_kind='opening' AND source_id=? LIMIT 1", (sid,)).fetchone() \
                or self.conn.execute("SELECT 1 FROM raw_observations WHERE obs_id=?", (sid + ":reopen",)).fetchone():
            return "NOOP"
        aid = self.asset_id("native", "sol", None, symbol="SOL", decimals=9)
        seq = 0
        for d in rec.get("deltas") or []:
            v = int(d.get("delta") or 0)
            if d.get("asset") != "native" or not v or ":stake:" not in (d.get("owner") or ""):
                continue
            loc = f"wallet:sol:{d['owner']}"
            self._post_leg_strict('opening', 'sol', sid, seq, ts, aid, loc, v, None, None, 'opening', 'OPENING')
            seq += 1
        self.conn.execute(
            "INSERT OR REPLACE INTO raw_observations (obs_id, kind, venue, payload, observed_at) VALUES (?,?,?,?,?)",
            (sid, "opening_balance", "sol", json.dumps(so, ensure_ascii=False), int(time.time())))
        self._hist_late_gone("opening", "sol", sid, t_old9)
        self._drop_daily_cache()
        if seq:
            dm("RECON", f"[sol] 스테이크 계정 기초잔고 {int(so.get('lamports') or 0) / 1e9:,.4f} SOL — {acct[:6]}…{acct[-4:]}"
                        f" (지갑 {str(so.get('wallet') or '')[:6]}…, 창 시작 기준)")
        return "OPENING"
