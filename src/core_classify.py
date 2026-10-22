import chain_registry
import chaincatalog, paths, timeutil
import json
import lpdec
import time
from core_common import MissingTs
from core_common import dm
import logging
import calcguard  # noqa: E402

log = logging.getLogger('tj-core')


class ClassifyMixin:

    def is_confirmed(self, aid: int) -> bool:
        r = self.conn.execute("SELECT confirmed FROM assets WHERE asset_id=?", (aid,)).fetchone()
        return bool(r and r["confirmed"])

    @staticmethod
    def op_deposit_mint(tx: dict):
        if tx.get("type") != 126:
            return 0, None
        m = tx.get("op_mint")
        if m is None:
            m = tx.get("value")
        try:
            m = int(m or 0)
        except (TypeError, ValueError):
            m = 0
        frm = tx.get("from")
        if isinstance(frm, dict):
            frm = frm.get("hash")
        return m, (frm or "").lower()

    def deltas(self, chain: str, snap: dict):
        mine = self.my_wallets.get(chain, set())
        tx = snap["tx"]
        perw = {}
        counterparties = set()

        def addr(x):
            if isinstance(x, dict):
                return (x.get("hash") or "").lower()
            return (x or "").lower()

        def add(w, aid, v):
            perw[(w, aid)] = perw.get((w, aid), 0) + v

        failed = (tx.get("status") != "ok")
        frm, to = addr(tx.get("from")), addr(tx.get("to"))
        is_contract_call = bool(tx.get("raw_input") and tx.get("raw_input") != "0x") or \
            bool((tx.get("to") or {}).get("is_contract") if isinstance(tx.get("to"), dict) else False)
        gas = 0
        gas_wallet = None
        if frm in mine:
            fee = tx.get("fee") or {}
            try:
                gas = int(fee.get("value") or 0)
            except (TypeError, ValueError):
                gas = 0
            gas_wallet = frm
        native_aid = self.asset_id("native", chain, None,
                                   symbol=self.native_sym.get(chain, chain.upper()),
                                   decimals=9 if chain == "sol" else chain_registry.native_decimals(chain, 18))
        if not failed:
            try:
                val = int(tx.get("value") or 0)
            except (TypeError, ValueError):
                val = 0
            if val:
                if frm in mine:
                    add(frm, native_aid, -val)
                    counterparties.add(to)
                if to in mine:
                    add(to, native_aid, val)
                    counterparties.add(frm)
            for it in snap.get("internal", []):
                if it.get("success") is False or it.get("error"):
                    continue
                if str(it.get("type") or "").lower() in ("delegatecall", "staticcall", "callcode"):
                    continue
                f2, t2 = addr(it.get("from")), addr(it.get("to"))
                try:
                    v2 = int((it.get("value") or 0))
                except (TypeError, ValueError):
                    v2 = 0
                if not v2:
                    continue
                if f2 in mine:
                    add(f2, native_aid, -v2)
                    counterparties.add(t2)
                if t2 in mine:
                    add(t2, native_aid, v2)
                    counterparties.add(f2)
            for tt in snap.get("token_transfers", []):
                f3, t3 = addr(tt.get("from")), addr(tt.get("to"))
                tok = tt.get("token") or {}
                if (tok.get("type") or "ERC-20") != "ERC-20":
                    continue
                ca = tok.get("address") or tok.get("address_hash")
                if not ca or str(ca).lower() == chaincatalog.NATIVE_ALIAS_TOKEN.get(chain):
                    continue
                total = tt.get("total") or {}
                try:
                    v3 = int(total.get("value") or 0)
                except (TypeError, ValueError):
                    continue
                if not v3 or (f3 not in mine and t3 not in mine):
                    continue
                try:
                    dec = None if tok.get("decimals") is None else int(tok.get("decimals"))
                except (TypeError, ValueError):
                    dec = None
                if dec is None:
                    dec = self._meta_dec(chain, ca)
                aid = self.asset_id("token", chain, ca,
                                    symbol=tok.get("symbol"), decimals=dec)
                if f3 in mine:
                    add(f3, aid, -v3)
                    counterparties.add(t3)
                if t3 in mine:
                    add(t3, aid, v3)
                    counterparties.add(f3)
        mint, mint_to = self.op_deposit_mint(tx)
        if mint and mint_to in mine:
            add(mint_to, native_aid, mint)
        ts = tx.get("timestamp")
        if isinstance(ts, str):
            ts = timeutil.iso_epoch(ts)
        if ts is None or (isinstance(ts, (int, float)) and ts <= 0):
            log.warning("시각 없는 tx 거부: %s %s timestamp=%r", chain, (tx.get("hash") or "?")[:14], tx.get("timestamp"))
            raise MissingTs(f"{chain} tx 시각 없음: {tx.get('timestamp')!r}")
        counterparties.discard("")
        external_cps = counterparties - mine
        only_mine = bool(counterparties) and not external_cps
        return (perw, external_cps, gas, gas_wallet, int(ts), failed, is_contract_call,
                frm, to, only_mine)

    @staticmethod
    def _zk_norm(chain: str, snap: dict) -> dict:
        zk = chaincatalog.ZK_STACK.get(chain)
        if not zk or not isinstance(snap, dict) or snap.get("internal_note") == "zk_base_token" or not snap.get("tx"):
            return snap
        base, boot = zk

        def addr(x):
            return ((x.get("hash") if isinstance(x, dict) else x) or "").lower()

        def ival(v):
            try:
                return int(v or 0)
            except (TypeError, ValueError):
                return 0
        tx = snap["tx"]
        f_tx = addr(tx.get("from"))
        t_top = addr(tx.get("to")) or addr(tx.get("created_contract"))
        v_top = ival(tx.get("value"))
        tts, nat = [], []
        for tt in snap.get("token_transfers") or []:
            tok = tt.get("token") or {}
            ca = str(tok.get("address") or tok.get("address_hash") or "").lower()
            if ca == base and (tok.get("type") or "ERC-20") == "ERC-20":
                nat.append((addr(tt.get("from")), addr(tt.get("to")), ival((tt.get("total") or {}).get("value"))))
            else:
                tts.append(tt)
        fee = None
        legs = []
        if nat:
            paid = back = 0
            seen = False
            for f0, t0, v0 in nat:
                if boot in (f0, t0):
                    seen = True
                    if f0 == f_tx and t0 == boot:
                        paid += v0
                        continue
                    if f0 == boot and t0 == f_tx:
                        back += v0
                        continue
                if v0:
                    legs.append((f0, t0, v0))
            if seen:
                if paid or back:
                    if paid >= back:
                        fee = paid - back
                else:
                    fee = 0
        else:
            traces = snap.get("internal") or []
            prepaid = any(it.get("success") is not False and not it.get("error") and addr(it.get("from")) == f_tx
                          and addr(it.get("to")) == boot and ival(it.get("value")) > 0 for it in traces)
            for it in traces:
                if it.get("success") is False or it.get("error"):
                    continue
                f0, t0, v0 = addr(it.get("from")), addr(it.get("to")), ival(it.get("value"))
                if not v0 or (f0 == f_tx and t0 == boot) or (prepaid and f0 == boot and t0 == f_tx):
                    continue
                legs.append((f0, t0, v0))
        internal = []
        skip = v_top > 0
        for f0, t0, v0 in legs:
            if skip and (f0, t0) == (f_tx, t_top) and v0 == v_top:
                skip = False
                continue
            internal.append({"from": f0, "to": t0, "value": str(v0), "success": True})
        out = dict(snap, token_transfers=tts, internal=internal, internal_note="zk_base_token")
        if fee is not None and fee != ival((tx.get("fee") or {}).get("value")):
            out["tx"] = dict(tx, fee=dict(tx.get("fee") or {}, value=str(fee)))
        return out

    def classify(self, chain: str, txhash: str, snap: dict):
        snap = self._zk_norm(chain, snap)
        (perw, cps, gas, gas_w, ts, failed, is_call,
         frm, to, only_mine) = self.deltas(chain, snap)
        mine = self.my_wallets.get(chain, set())
        perw = {k: v for k, v in perw.items() if v != 0}
        deltas = {}
        for (w, a), v in perw.items():
            deltas[a] = deltas.get(a, 0) + v
        deltas = {a: v for a, v in deltas.items() if v != 0}
        outs = {a: v for a, v in deltas.items() if v < 0}
        ins = {a: v for a, v in deltas.items() if v > 0}
        ex_addrs = self._ex_addr_set(chain)

        def R(event, hint=None):
            return (event, deltas, perw, gas, gas_w, ts, hint,
                    {"to": to, "cps": sorted(cps)[:4] if cps else []})

        if failed:
            if perw:
                return R("PROGRAM_IN")
            return R("FAILED")
        lp9 = self._lp_detect(chain, snap, to, frm, mine)
        if lp9 is not None and lp9.get("lp_token"):
            t_aid = self.asset_id("token", chain, lp9["lp_token"])
            perw = {k: v for k, v in perw.items() if k[1] != t_aid}
            deltas = {}
            for (_w, a), v in perw.items():
                deltas[a] = deltas.get(a, 0) + v
            deltas = {a: v for a, v in deltas.items() if v != 0}
            outs = {a: v for a, v in deltas.items() if v < 0}
            ins = {a: v for a, v in deltas.items() if v > 0}
        if lp9 is not None:
            if outs and ins:
                ev9 = "LP_ADJUST"
            elif outs:
                ev9 = "LP_ADD"
            elif ins or lp9.get("burn") or lp9.get("gone"):
                ev9 = "LP_REMOVE"
            elif perw or lp9.get("stake") or lp9.get("unstake"):
                ev9 = "LP_ADJUST"
            else:
                return R("NOOP")
            return (ev9, deltas, perw, gas, gas_w, ts, None,
                    {"to": to, "cps": sorted(cps)[:4] if cps else [], "lp": lp9})
        if len(outs) == 1 and len(ins) == 1:
            oa = self.conn.execute("SELECT * FROM assets WHERE asset_id=?", (next(iter(outs)),)).fetchone()
            ia = self.conn.execute("SELECT * FROM assets WHERE asset_id=?", (next(iter(ins)),)).fetchone()
            wrapped_ca = self.wrapped.get(chain)
            if wrapped_ca and {oa["kind"], ia["kind"]} == {"native", "token"}:
                tok = oa if oa["kind"] == "token" else ia
                if tok["address"] == wrapped_ca and abs(next(iter(outs.values()))) == next(iter(ins.values())):
                    return R("CONVERT")
        if only_mine or (not deltas and perw):
            return R("TRANSFER_SELF")
        if outs and cps and cps <= ex_addrs:
            return R("TRANSFER_OUT_EX", next(iter(cps)))
        if outs and ((frm in mine and to in self.bridges)
                     or (cps and all(c in self.bridges for c in cps))):
            hint = to if to in self.bridges else next(iter(cps))
            return R("BRIDGE", hint)
        if not cps and outs and ins:
            return R("UNKNOWN")
        if outs and not ins:
            if is_call and to and frm in mine:
                for a in outs:
                    ar = self.conn.execute(
                        "SELECT kind, address FROM assets WHERE asset_id=?", (a,)).fetchone()
                    if ar and ar["kind"] == "token" and ar["address"] == to and self._oft_like(snap, mine, to):
                        return R("BRIDGE", to)
            r9 = R("TRANSFER_OUT")
            r9[7]["out"] = self._out_dests(chain, snap, mine)
            return r9
        if outs and ins:
            if is_call and cps:
                unconfirmed = [a for a in ins if not self.is_confirmed(a)]
                if unconfirmed:
                    for a in unconfirmed:
                        self.conn.execute("UPDATE assets SET confirmed=1 WHERE asset_id=?", (a,))
                    dm("NEW_ASSET", f"[{chain}] 새 자산 자동 기록 tx {txhash} — LP/예치 토큰이면 검토",
                       {"chain": chain, "txhash": txhash,
                        "assets": [int(a) for a in unconfirmed]}, event_ts=ts)
                return R("SWAP")
            return R("UNKNOWN")
        if ins and not outs:
            if is_call:
                return R("PROGRAM_IN")
            return R("TRANSFER_IN")
        if not deltas:
            return R("NOOP")
        return R("UNKNOWN")

    ERC20_PLAIN_SELS = ("0xa9059cbb", "0x23b872dd")

    def _oft_like(self, snap: dict, mine: set, ca: str) -> bool:
        ca = (ca or "").lower()
        dests = set()
        for tt in snap.get("token_transfers") or []:
            tok = tt.get("token") or {}
            if str(tok.get("address") or tok.get("address_hash") or "").lower() != ca:
                continue
            f9, t9 = tt.get("from"), tt.get("to")
            f9 = str((f9.get("hash") if isinstance(f9, dict) else f9) or "").lower()
            t9 = str((t9.get("hash") if isinstance(t9, dict) else t9) or "").lower()
            if f9 in mine:
                dests.add(t9)
        if dests:
            return dests <= {self.ZERO_ADDR, ca}
        tx = snap.get("tx") or {}
        sel = str(tx.get("raw_input") or tx.get("input") or "")[:10].lower()
        return sel not in self.ERC20_PLAIN_SELS

    def _reclass_plain_xfer_once(self):
        if self._meta_get("reclass_q_plainxfer"):
            return 0
        n = 0
        done = []
        try:
            for r in self.conn.execute(
                    "SELECT t.chain, t.txhash, r.snapshot FROM tx_class t JOIN raw_txs r ON r.chain=t.chain AND r.txhash=t.txhash"
                    " WHERE t.event='BRIDGE' AND t.chain != 'sol' ORDER BY t.chain, t.txhash").fetchall():
                snap = json.loads(r["snapshot"])
                f9 = (snap.get("tx") or {}).get("from")
                f9 = str((f9.get("hash") if isinstance(f9, dict) else f9) or "").lower()
                if f9 not in self.my_wallets.get(r["chain"], set()):
                    continue
                if self.classify(r["chain"], r["txhash"], snap)[0] == "BRIDGE":
                    continue
                gas9 = {(p["asset_id"], p["location"], p["qty_base"]): (p["cost_usd"], p["cost_krw"]) for p in self.conn.execute(
                    "SELECT asset_id, location, qty_base, cost_usd, cost_krw FROM postings WHERE source_kind='chain_tx'"
                    " AND source_ns=? AND source_id=? AND leg_kind='gas' AND cost_usd IS NOT NULL", (r["chain"], r["txhash"])).fetchall()}
                ev = self._rederive_tx_anchor_safe(r["chain"], r["txhash"])
                for (aid9, loc9, qb9), (cu9, ck9) in gas9.items():
                    self._leg_sql("_reclass_plain_xfer_once.1", (cu9, ck9, r["chain"], r["txhash"], aid9, loc9, qb9))
                done.append((r["chain"], r["txhash"], ev))
                n += 1
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('reclass_q_plainxfer', ?)", (f"{int(time.time())}:{n}",))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        if n:
            ev_n = {}
            for _c, _h, e in done:
                ev_n[e] = ev_n.get(e, 0) + 1
            log.warning("★평범한 ERC-20 전송 오분류 BRIDGE %d건 재분류 %s★", n, ev_n)
        return n

    def _reclass_added_lp_mgrs_once(self) -> int:
        todo = []
        for ch, mg in (self.lp_mgrs or {}).items():
            if not isinstance(mg, dict):
                continue
            for addr, meta in mg.items():
                if isinstance(meta, dict) and meta.get("added") and meta.get("proto") in lpdec.NFT_PROTOS \
                        and not self._meta_get(f"reclass_lp_mgr:{ch}:{addr}"):
                    todo.append((ch, str(addr).lower()))
        if not todo:
            return 0
        n = 0
        changed = {}
        try:
            for ch, addr in todo:
                rows = self.conn.execute(
                    "SELECT r.txhash, r.ts, r.snapshot, t.event FROM raw_txs r LEFT JOIN tx_class t ON t.chain=r.chain AND t.txhash=r.txhash"
                    " WHERE r.chain=? AND instr(lower(r.snapshot), ?) > 0", (ch, addr)).fetchall()
                items = []
                miss9 = []
                for r in rows:
                    snap = json.loads(r["snapshot"])
                    tx9 = snap.get("tx") or {}
                    to9 = tx9.get("to")
                    to9 = str((to9.get("hash") if isinstance(to9, dict) else to9) or "").lower()
                    if to9 == addr and (self.lp_mgrs.get(ch) or {}).get(addr, {}).get("proto") in ("uni_v3", "slipstream") \
                            and any(a9 in ("MINT", "INCREASE") and l9 is None
                                    for a9, _t9, l9 in lpdec.decode_lp_calls(tx9.get("raw_input") or tx9.get("input"))) \
                            and not snap.get("_lp_liq"):
                        miss9.append(r["txhash"])
                    ts9 = r["ts"]
                    if ts9 is None:
                        try:
                            ts9 = self.deltas(ch, snap)[4]
                        except Exception as _cg9:  # noqa: BLE001 [fallback]
                            calcguard.swallowed("core_classify:ClassifyMixin._reclass_added_lp_mgrs_once", _cg9)
                            ts9 = 0
                    items.append((int(ts9 or 0), r["txhash"], r["event"]))
                if miss9:
                    log.warning("새 LP 관리자 %s:%s — v3 예치 유동성 힌트 없는 tx %d건(%s…) · 재분류 보류(%s)",
                                ch, addr[:10], len(miss9), miss9[0][:12],
                                ((paths.tool_ref("backfill_gap.py", "") + " nft-enrich/import 먼저") if paths.tool_ref("backfill_gap.py", "")
                                 else "보강 도구가 이 설치엔 없음 — 보류 유지(장부는 그대로)"))
                    continue
                for _ts9, h, old_ev in sorted(items):
                    gas9 = {(p["asset_id"], p["location"], p["qty_base"]): (p["cost_usd"], p["cost_krw"]) for p in self.conn.execute(
                        "SELECT asset_id, location, qty_base, cost_usd, cost_krw FROM postings WHERE source_kind='chain_tx'"
                        " AND source_ns=? AND source_id=? AND leg_kind='gas' AND cost_usd IS NOT NULL", (ch, h)).fetchall()}
                    ev = self._rederive_tx_anchor_safe(ch, h)
                    for (aid9, loc9, qb9), (cu9, ck9) in gas9.items():
                        self._leg_sql("_reclass_added_lp_mgrs_once.1", (cu9, ck9, ch, h, aid9, loc9, qb9))
                    if ev != old_ev:
                        changed[f"{old_ev}→{ev}"] = changed.get(f"{old_ev}→{ev}", 0) + 1
                    n += 1
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)",
                                  (f"reclass_lp_mgr:{ch}:{addr}", f"{int(time.time())}:{len(items)}"))
            if changed:
                self._inval_daily()
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        if changed:
            log.warning("★새 LP 관리자 %s — 저장된 tx %d건 재분류 %s★", ", ".join(f"{c}:{a[:10]}" for c, a in todo), n, changed)
        return n
