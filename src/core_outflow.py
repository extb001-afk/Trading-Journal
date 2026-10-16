import chain_registry
import common
import json
import os
import time
import logging
import calcguard

log = logging.getLogger('tj-core')


class OutflowMixin:

    def _out_dests(self, chain: str, snap: dict, mine: set) -> dict:
        def addr(x):
            return ((x.get("hash") if isinstance(x, dict) else x) or "").lower()
        acc = {}
        tx = snap.get("tx") or {}
        native_aid = self.asset_id("native", chain, None, symbol=self.native_sym.get(chain, chain.upper()),
                                   decimals=9 if chain == "sol" else chain_registry.native_decimals(chain, 18))

        def add(w, aid, to9, v):
            if w in mine and to9 and to9 not in mine and v > 0:
                k = (w, aid)
                acc.setdefault(k, {})[to9] = acc.setdefault(k, {}).get(to9, 0) + v
        try:
            add(addr(tx.get("from")), native_aid, addr(tx.get("to")), int(tx.get("value") or 0))
        except (TypeError, ValueError):
            pass
        for it in snap.get("internal") or []:
            if it.get("success") is False or it.get("error"):
                continue
            try:
                add(addr(it.get("from")), native_aid, addr(it.get("to")), int(it.get("value") or 0))
            except (TypeError, ValueError):
                continue
        for tt in snap.get("token_transfers") or []:
            tok = tt.get("token") or {}
            if (tok.get("type") or "ERC-20") != "ERC-20":
                continue
            ca = tok.get("address") or tok.get("address_hash")
            if not ca:
                continue
            try:
                v = int((tt.get("total") or {}).get("value") or 0)
            except (TypeError, ValueError):
                continue
            try:
                dec9 = None if tok.get("decimals") is None else int(tok.get("decimals"))
            except (TypeError, ValueError):
                dec9 = None
            aid = self.asset_id("token", chain, ca, symbol=tok.get("symbol"),
                                decimals=dec9 if dec9 is not None else self._meta_dec(chain, ca))
            add(addr(tt.get("from")), aid, addr(tt.get("to")), v)
        return {f"{w}|{aid}": max(d.items(), key=lambda kv: (kv[1], kv[0]))[0] for (w, aid), d in acc.items()}

    def _out_legs(self, chain: str, perw: dict, dest: dict, loc_of) -> list:
        dmap = dest.get("out") or {}
        cps = [c for c in (dest.get("cps") or []) if c]
        fallback = cps[0] if len(cps) == 1 else ("multi" if cps else "?")
        legs = []
        by_aid = {}
        for (w, aid), v in perw.items():
            by_aid.setdefault(aid, []).append((w, v))
        for aid in sorted(by_aid):
            ws = sorted(by_aid[aid], key=lambda x: x[0] or "")
            pos = [[w, v] for w, v in ws if v > 0]
            for w, v in ws:
                if v >= 0:
                    continue
                legs.append(("move_out", aid, v, loc_of(w)))
                left = -v
                for pw in pos:
                    take = min(left, pw[1])
                    if take > 0:
                        legs.append(("move_in", aid, take, loc_of(pw[0])))
                        pw[1] -= take
                        left -= take
                if left > 0:
                    to9 = dmap.get(f"{w}|{aid}") or fallback
                    legs.append(("move_in", aid, left, f"out:{chain}:{to9}"))
        return legs

    OUTFLOW_PATH = os.path.join(common.STATE_DIR, "outflow_decisions.json")

    def _outflow_decisions(self) -> dict:
        try:
            with open(self.OUTFLOW_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            log.warning("보낸 내역 판정 파일 읽기 실패(건너뜀): %s", e)
            return {}
        dd = (d or {}).get("decisions") if isinstance(d, dict) else None
        return dd if isinstance(dd, dict) else {}

    def _outflow_chains(self, addr: str) -> list:
        return sorted({r["location"].split(":")[1] for r in self.conn.execute(
            "SELECT DISTINCT location FROM postings WHERE location LIKE 'out:%' AND location LIKE ?",
            ("%:" + addr,)).fetchall() if r["location"].split(":", 2)[2] == addr})

    def outflow_sync_exchange_rows(self) -> set:
        dec = self._outflow_decisions()
        want = {}
        for a, v in dec.items():
            if isinstance(v, dict) and v.get("verdict") == "exchange":
                for ch in (v.get("chains") or self._outflow_chains(a)):
                    want[(ch, a)] = str(v.get("exchange") or "unknown")[:32]
        have = {(r["chain"], r["address"]): r["exchange"] for r in self.conn.execute(
            "SELECT exchange, chain, address FROM exchange_addresses WHERE sync_state='outflow'").fetchall()}
        changed = set()
        for (ch, a), ex in want.items():
            if have.get((ch, a)) != ex:
                self.conn.execute("DELETE FROM exchange_addresses WHERE chain=? AND address=? AND sync_state='outflow'",
                                  (ch, a))
                self.conn.execute("INSERT OR IGNORE INTO exchange_addresses (exchange, chain, address, currency, memo,"
                                  " sync_state) VALUES (?,?,?,NULL,'보낸 내역 판정','outflow')", (ex, ch, a))
                changed.add(a)
        for (ch, a) in set(have) - set(want):
            self.conn.execute("DELETE FROM exchange_addresses WHERE chain=? AND address=? AND sync_state='outflow'", (ch, a))
            changed.add(a)
        return changed

    def _rederive_tx(self, chain: str, txhash: str) -> str:
        row = self.conn.execute("SELECT snapshot FROM raw_txs WHERE chain=? AND txhash=?", (chain, txhash)).fetchone()
        if not row:
            return None
        oe = self.conn.execute("SELECT event FROM tx_class WHERE chain=? AND txhash=?", (chain, txhash)).fetchone()
        t_old9 = None
        for p in self._unpost_source("chain_tx", chain, txhash):
            t_old9 = int(p["event_ts"]) if t_old9 is None else min(t_old9, int(p["event_ts"]))
        keep = set()
        for t in self.conn.execute("SELECT transfer_id, state, asset_id FROM transfers WHERE chain_txhash=?", (txhash,)).fetchall():
            if t["state"] == "sent":
                self.conn.execute("DELETE FROM transfers WHERE transfer_id=?", (t["transfer_id"],))
            else:
                keep.add(t["asset_id"])
        snap = json.loads(row["snapshot"])
        if chain == "sol" and snap.get("kind") == "sol_tx":
            ev = self.apply_sol(snap, rederive=((oe["event"] if oe else None), frozenset(keep)))
        else:
            ev = self.apply(chain, txhash, "", snap, rederive=((oe["event"] if oe else None), frozenset(keep)))
        self._hist_late_gone("chain_tx", chain, txhash, t_old9)
        return ev

    def _rederive_tx_anchor_safe(self, chain: str, txhash: str) -> str:
        before = self._tx_wallet_sums(chain, txhash)
        ev = self._rederive_tx(chain, txhash)
        self._anchor_absorb(chain, txhash, before)
        return ev

    def _hist_late_gone(self, kind: str, ns: str, sid: str, t_old):
        if t_old is None:
            return None
        r9 = self.conn.execute("SELECT MIN(event_ts) FROM postings WHERE source_kind=? AND source_ns=? AND source_id=?", (kind, ns, sid)).fetchone()
        if r9 and r9[0] is not None and int(r9[0]) <= int(t_old):
            return None
        if kind == "chain_tx" and self._meta_get(f"ext_prewindow_tx:{ns}:{sid}") is not None:
            return None
        iso = common.hist_late_put(self.conn, int(t_old))
        log.info("지난 원장 행 삭제(%s %s:%s · 다시 기장 없음) — 지난 곡선 다시 계산 표식: %s 부터", kind, ns, str(sid)[:16], iso)
        return iso

    def outflow_pass(self, force: bool = False):
        if not force and time.time() - getattr(self, "_last_outflow", 0) < 60:
            return
        self._last_outflow = time.time()
        dec = self._outflow_decisions()
        changed = self.outflow_sync_exchange_rows()
        addrs = set(dec) | changed | {r["k"][len("outflow_applied:"):] for r in self.conn.execute(
            "SELECT k FROM meta WHERE k LIKE 'outflow_applied:%'").fetchall()}
        n_tx = 0
        for a in sorted(addrs):
            v = dec.get(a) if isinstance(dec.get(a), dict) else {}
            verdict = v.get("verdict") or "clear"
            reg = any(a in ws for ws in self.my_wallets.values()) or a in self.sol_wallets
            sig = f"{verdict}:{int(reg) if verdict == 'own' else ''}:{v.get('exchange') or ''}:{','.join(sorted(v.get('chains') or []))}"
            k = f"outflow_applied:{a}"
            cur = self.conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
            prev9 = cur["v"] if cur else "clear::"
            if prev9 == sig and a not in changed:
                continue
            _bk = lambda s9: "out" if s9.split(":", 1)[0] in ("clear", "external") else s9
            if _bk(prev9) == _bk(sig) and a not in changed:
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k, sig))
                self.conn.commit()
                continue
            if verdict == "own" and not reg:
                if cur is None or not str(cur["v"]).startswith("own:0"):
                    log.info("보낸 내역: %s '내 지갑' 판정 — config 등록 확인됨, tj-core·수집기 재기동 뒤 재분류", a[:12])
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k, sig))
                self.conn.commit()
                continue
            txs = {(r["source_ns"], r["source_id"]) for r in self.conn.execute(
                "SELECT DISTINCT p.source_ns, p.source_id FROM postings p WHERE p.source_kind='chain_tx'"
                " AND p.location LIKE ?", ("out:%:" + a,)).fetchall()}
            for r in self.conn.execute("SELECT chain, txhash, detail FROM tx_class WHERE event IN ('TRANSFER_OUT_EX', 'TRANSFER_SELF')"
                                       " AND detail LIKE ?", ('%' + a + '%',)).fetchall():
                txs.add((r["chain"], r["txhash"]))
            for r in self.conn.execute("SELECT DISTINCT source_ns, source_id FROM postings WHERE source_kind='chain_tx'"
                                       " AND event IN ('TRANSFER_SELF', 'TRANSFER_OUT') AND leg_kind='move_in' AND location LIKE ?",
                                       ("wallet:%:" + a,)).fetchall():
                txs.add((r["source_ns"], r["source_id"]))
            try:
                for ch9, h9 in sorted(txs):
                    self._rederive_tx_anchor_safe(ch9, h9)
                    n_tx += 1
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k, sig))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
            for ch9, h9 in sorted(txs):
                try:
                    self._price_tx(ch9, h9)
                except Exception as e:
                    calcguard.swallowed("core_outflow:OutflowMixin.outflow_pass", e)
                    self.conn.rollback()
                    log.warning("보낸 내역 재기장 가격 %s %s 실패(가격패스가 재시도): %s", ch9, h9[:12], e)
            log.info("★보낸 내역 판정 반영: %s → %s (tx %d건 재분류)★", a[:12], verdict, len(txs))
        if n_tx:
            try:
                os.remove(os.path.join(common.STATE_DIR, "daily_cache.json"))
            except FileNotFoundError:
                pass
