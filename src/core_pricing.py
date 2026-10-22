import acct_norm
import json
import pricing, token_tables
import random
import spamguard
import sqlite3
import time
from core_common import KRW_FILL_CALLS
from core_common import KRW_FILL_SEC
from core_common import PRICE_BACKOFF_MAX
from core_common import PRICE_BACKOFF_MIN
from core_common import PRICE_BATCH
from core_common import PRICE_BULK_BATCH
from core_common import PRICE_BULK_BUDGET
from core_common import PRICE_IDLE_SEC
from core_common import PRICE_PREFETCH_CALLS
from decimal import Decimal
from decimal import InvalidOperation
from decimal import localcontext
import logging
import calcguard  # noqa: E402

log = logging.getLogger('tj-core')


class PricingMixin:

    def _leg_px(self, aid: int, ts: int):
        r = self.conn.execute("SELECT kind, chain, address, symbol FROM assets WHERE asset_id=?",
                              (aid,)).fetchone()
        if not r:
            return None
        kind, chain, ca, sym = r["kind"], r["chain"], r["address"], (r["symbol"] or "").upper()
        if kind == "native":
            sym = sym or self.native_sym.get(chain, "")
            if sym in pricing.DOLLAR_NATIVES:
                return 1.0
            return self.px.candle_usd(sym, ts * 1000) if sym else None
        if kind == "token" and ca:
            st = token_tables.STABLE_CAS.get(chain, {}).get(ca)
            if chain == "sol" and not st:
                st = token_tables.STABLE_MINTS.get(ca)
            if st:
                return 1.0
            jst = token_tables.JPY_STABLE_CAS.get(chain, {}).get(ca)
            if jst:
                return self.px.jpy_stable_usd(jst, ts * 1000)
            if ca == self.wrapped.get(chain):
                return self.px.candle_usd(self.native_sym.get(chain, "ETH"), ts * 1000)
            if sym in ("USDT", "USDC", "DAI", "USDG", "USDE", "CUSD", "USD1", "NUSD"):
                return None
            sym = acct_norm.norm_ticker(sym)
            if sym in ("USDT", "USDC", "DAI", "USDG", "USDE", "CUSD", "USD1", "NUSD"):
                return None
            cex9 = self.px.candle_usd(sym, ts * 1000) if sym and sym not in pricing.NATIVE_EX_TICKER else None
            vd9 = self._sym_px_verdict(aid, cex9, sym, ts * 1000) if cex9 else "unknown"
            if vd9 == "ok":
                return cex9
            cand9 = None if vd9 == "diff" else cex9
            chk9 = getattr(self.px, "token_usd_checked", None)
            return chk9(sym, ts * 1000, chain, ca, cand9) if chk9 else cand9
        return None

    def _is_stable_aid(self, aid: int) -> bool:
        r = self.conn.execute("SELECT kind, chain, address, symbol FROM assets WHERE asset_id=?",
                              (aid,)).fetchone()
        if r and r["kind"] == "native":
            return (r["symbol"] or "").upper() in pricing.DOLLAR_NATIVES
        if not r or r["kind"] != "token" or not r["address"]:
            return False
        if token_tables.STABLE_CAS.get(r["chain"], {}).get(r["address"]):
            return True
        return r["chain"] == "sol" and r["address"] in token_tables.STABLE_MINTS

    OUT_PX_BAND = (Decimal("0.2"), Decimal("5"))

    def _sym_px_token(self, aid: int) -> bool:
        r = self.conn.execute("SELECT kind, chain, address FROM assets WHERE asset_id=?", (aid,)).fetchone()
        if not r or r["kind"] != "token" or not r["address"]:
            return False
        ch, ca = r["chain"], r["address"]
        if token_tables.STABLE_CAS.get(ch, {}).get(ca) or (ch == "sol" and ca in token_tables.STABLE_MINTS) \
                or token_tables.JPY_STABLE_CAS.get(ch, {}).get(ca) or ca == self.wrapped.get(ch):
            return False
        return not spamguard.is_genuine(ch, ca)

    SYM_PX_BAND = (Decimal("0.5"), Decimal("2"))

    def _sym_px_proven(self, aid: int, px, sym: str = None, ts_ms: int = None) -> bool:
        return self._sym_px_verdict(aid, px, sym, ts_ms) == "ok"

    def _sym_px_verdict(self, aid: int, px, sym: str = None, ts_ms: int = None) -> str:
        try:
            if not self._sym_px_token(aid):
                return "ok"
            ven9 = None
            if sym and ts_ms is not None and hasattr(self.px, "candle_venue"):
                try:
                    ven9 = self.px.candle_venue(sym, ts_ms)
                except Exception as _cg9:   # noqa: BLE001 [fallback]
                    calcguard.swallowed("core_pricing:PricingMixin._sym_px_verdict", _cg9)
                    ven9 = None
            vex9 = {"upbit_krw": "upbit"}.get(ven9, ven9)
            proof9 = self._ex_proven_venues(aid)
            coin9 = self._cg_coin_ids(sym, proof9)

            def venue_same(v9):
                if not coin9 or not v9:
                    return None
                ids9 = self._cg_venue_ids(v9, sym)
                if not ids9:
                    return None
                return bool(ids9 & coin9)
            known9 = vex9 not in (None, "coingecko", "legacy")
            same9 = venue_same(vex9) if known9 else None
            if same9 is False:
                return "diff"
            if proof9 and known9 and vex9 in proof9:
                return "ok"
            if same9 is True:
                return "ok"
            if vex9 == "legacy":
                if any(venue_same(v9) is False for v9 in ("binance", "bybit")):
                    return "diff"
                if proof9:
                    return "ok"
            elif proof9:
                return "unknown"
            if vex9 == "coingecko":
                return "unknown"
            u = self._own_unit_cost(aid)
            lo, hi = self.SYM_PX_BAND
            return "ok" if (bool(u) and lo <= Decimal(str(px)) / u <= hi) else "unknown"
        except (sqlite3.Error, InvalidOperation, ZeroDivisionError):
            return "unknown"

    @staticmethod
    def _cg_venue_ids(ex, sym):
        try:
            import candles as _cd
            return _cd.cg_ids(ex, sym, fetch=False) or set()
        except Exception as _cg9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("core_pricing:PricingMixin._cg_venue_ids", _cg9)
            return set()

    def _cg_coin_ids(self, sym, proof):
        out9 = set()
        for ex9 in proof or ():
            out9 |= self._cg_venue_ids(ex9, sym)
        return out9

    def _ex_proven_venues(self, aid: int) -> set:
        cache = self.__dict__.setdefault("_ex_proven_v_cache", {})
        if aid in cache:
            return cache[aid]
        r = self.conn.execute("SELECT symbol FROM assets WHERE asset_id=?", (aid,)).fetchone()
        sym = str((r["symbol"] if r else "") or "").strip().upper()
        out = set()
        if self.conn.execute("SELECT 1 FROM transfers WHERE asset_id=? AND ex_uuid IS NOT NULL LIMIT 1", (aid,)).fetchone():
            out.add("upbit")
        if sym:
            tx9 = self._ex_txid_venues()
            for p in self.conn.execute("SELECT DISTINCT source_id FROM postings WHERE asset_id=? AND source_kind='chain_tx'", (aid,)).fetchall():
                h = str(p["source_id"] or "")
                for ex9, cur9 in tx9.get(h.lower() if h.startswith("0x") else h, ()):
                    if cur9 == sym:
                        out.add(ex9)
        cache[aid] = out
        return out

    def _ex_txid_venues(self) -> dict:
        try:
            sig = tuple(self.conn.execute("SELECT COUNT(*), MAX(rowid) FROM raw_ex WHERE kind IN ('deposit','withdraw')").fetchone())
        except sqlite3.Error:
            return {}
        c9 = self.__dict__.get("_ex_txid_v_cache")
        if c9 and c9[0] == sig:
            return c9[1]
        m = {}
        for r in self.conn.execute("SELECT exchange, payload FROM raw_ex WHERE kind IN ('deposit','withdraw')"):
            try:
                p9 = json.loads(r["payload"])
            except (json.JSONDecodeError, TypeError):
                continue
            t9 = str((p9 or {}).get("txid") or "").strip() if isinstance(p9, dict) else ""
            if t9:
                m.setdefault(t9.lower() if t9.startswith("0x") else t9, set()).add((str(r["exchange"] or "").lower(),
                                                                                  str(p9.get("currency") or "").upper()))
        self._ex_txid_v_cache = (sig, m)
        return m

    def _own_unit_cost(self, aid: int):
        tq, tc = Decimal(0), Decimal(0)
        with localcontext() as ctx:
            ctx.prec = 60
            for r in self.conn.execute(
                    "SELECT qty_base, cost_usd FROM postings WHERE asset_id=? AND leg_kind='acq' AND cost_usd IS NOT NULL"
                    " AND qty_base NOT LIKE '-%' AND qty_base != '0'", (aid,)).fetchall():
                try:
                    tq += Decimal(self._norm(aid, int(r["qty_base"])))
                    tc += Decimal(str(r["cost_usd"]))
                except (InvalidOperation, ValueError, TypeError):
                    continue
            return (tc / tq) if tq > 0 and tc > 0 else None

    def _ex_txids(self) -> dict:
        try:
            sig = tuple(self.conn.execute("SELECT COUNT(*), MAX(rowid) FROM raw_ex WHERE kind IN ('deposit','withdraw')").fetchone())
        except sqlite3.Error:
            return {}
        c9 = self.__dict__.get("_ex_txid_cache")
        if c9 and c9[0] == sig:
            return c9[1]
        m = {}
        for r in self.conn.execute("SELECT payload FROM raw_ex WHERE kind IN ('deposit','withdraw')"):
            try:
                p9 = json.loads(r["payload"])
            except (json.JSONDecodeError, TypeError):
                continue
            t9 = str((p9 or {}).get("txid") or "").strip() if isinstance(p9, dict) else ""
            if not t9:
                continue
            m.setdefault(t9.lower() if t9.startswith("0x") else t9, set()).add(str(p9.get("currency") or "").upper())
        self._ex_txid_cache = (sig, m)
        return m

    def _ex_proven(self, aid: int) -> bool:
        cache = self.__dict__.setdefault("_ex_proven_cache", {})
        if aid in cache:
            return cache[aid]
        r = self.conn.execute("SELECT symbol FROM assets WHERE asset_id=?", (aid,)).fetchone()
        sym = str((r["symbol"] if r else "") or "").strip().upper()
        ok = bool(self.conn.execute("SELECT 1 FROM transfers WHERE asset_id=? AND ex_uuid IS NOT NULL LIMIT 1", (aid,)).fetchone())
        if not ok and sym:
            tx9 = self._ex_txids()
            for p in self.conn.execute("SELECT DISTINCT source_id FROM postings WHERE asset_id=? AND source_kind='chain_tx'",
                                       (aid,)).fetchall():
                h = str(p["source_id"] or "")
                if sym in tx9.get(h.lower() if h.startswith("0x") else h, ()):
                    ok = True
                    break
        cache[aid] = ok
        return ok

    def _out_px(self, aid: int, px):
        if px and self._sym_px_token(aid) and not self._ex_proven(aid):
            u = self._own_unit_cost(aid)
            lo, hi = self.OUT_PX_BAND
            if not u or not (lo <= Decimal(str(px)) / u <= hi):
                return None
        return px

    def _out_px_band_fix_once(self) -> list:
        if self._meta_get("px_out_band_r"):
            return []
        lo, hi = self.OUT_PX_BAND
        changed = []
        try:
            for r in self.conn.execute(
                    "SELECT posting_id, asset_id, qty_base, cost_usd, source_ns, source_id FROM postings WHERE source_kind='chain_tx'"
                    " AND leg_kind='move_in' AND location LIKE 'out:%' AND cost_usd IS NOT NULL").fetchall():
                aid = r["asset_id"]
                if not self._sym_px_token(aid) or self._ex_proven(aid):
                    continue
                q9 = abs(Decimal(self._norm(aid, int(r["qty_base"]))))
                if q9 <= 0:
                    continue
                u = self._own_unit_cost(aid)
                if u and lo <= Decimal(str(r["cost_usd"])) / q9 / u <= hi:
                    continue
                self._leg_sql("_out_px_band_fix_once.1", (r["posting_id"],))
                changed.append((int(r["posting_id"]), r["source_ns"], r["source_id"], int(aid), str(r["cost_usd"])))
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('px_out_band_r', ?)", (f"{int(time.time())}:{len(changed)}",))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        for pid, ns, sid, aid, usd in changed:
            log.warning("보낸 내역 시가 되돌림 posting %d %s %s asset %d $%s → NULL(새 규칙으로 재산정)", pid, ns, sid[:12], aid, usd)
        return changed

    def _price_tx(self, chain: str, txhash: str) -> int:
        legs = self.conn.execute(
            "SELECT posting_id, asset_id, qty_base, leg_kind, event, event_ts, cost_usd, location FROM postings"
            " WHERE source_kind='chain_tx' AND source_ns=? AND source_id=?",
            (chain, txhash)).fetchall()
        if not legs:
            return 0
        ts = legs[0]["event_ts"]
        updates = {}
        with localcontext() as ctx:
            ctx.prec = 60

            def norm_abs(leg):
                return abs(Decimal(self._norm(leg["asset_id"], int(leg["qty_base"]))))

            for leg in legs:
                if leg["cost_usd"] is not None:
                    continue
                out9 = leg["leg_kind"] == "move_in" and str(leg["location"] or "").startswith("out:")
                if leg["leg_kind"] == "gas" or (str(leg["event"] or "").startswith("LP_")
                                                 and leg["leg_kind"] in ("disp", "acq")) or out9 \
                        or (leg["event"] == "STAKE_REWARD" and leg["leg_kind"] == "acq"):
                    px = self._leg_px(leg["asset_id"], ts)
                    if out9:
                        px = self._out_px(leg["asset_id"], px)
                    if px:
                        updates[leg["posting_id"]] = float(norm_abs(leg) * Decimal(str(px)))
            swap = [l for l in legs if l["event"] == "SWAP" and l["leg_kind"] in ("disp", "acq")]
            if swap and any(l["cost_usd"] is None for l in swap):
                outs = [l for l in swap if l["leg_kind"] == "disp"]
                ins = [l for l in swap if l["leg_kind"] == "acq"]

                def side_val(side):
                    vals = []
                    for l in side:
                        px = self._leg_px(l["asset_id"], ts)
                        vals.append(None if px is None else norm_abs(l) * Decimal(str(px)))
                    total = sum((v for v in vals if v is not None), Decimal(0))
                    return vals, total, all(v is not None for v in vals)

                out_vals, out_total, out_ok = side_val(outs)
                in_vals, in_total, in_ok = side_val(ins)
                stable_out = sum((v for l, v in zip(outs, out_vals)
                                  if v is not None and self._is_stable_aid(l["asset_id"])), Decimal(0))
                stable_in = sum((v for l, v in zip(ins, in_vals)
                                 if v is not None and self._is_stable_aid(l["asset_id"])), Decimal(0))
                if stable_out > 0 and all(self._is_stable_aid(l["asset_id"]) for l in outs):
                    V = stable_out
                elif stable_in > 0 and all(self._is_stable_aid(l["asset_id"]) for l in ins):
                    V = stable_in
                elif out_ok and out_total > 0:
                    V = out_total
                elif in_ok and in_total > 0:
                    V = in_total
                else:
                    V = None
                if V is not None:
                    def assign(side, vals, total, ok):
                        got = self._swap_split(V, vals, total, ok, [self._is_stable_aid(l["asset_id"]) for l in side])
                        if got is not None:
                            for l, v in zip(side, got):
                                updates[l["posting_id"]] = float(v)
                    assign(outs, out_vals, out_total, out_ok)
                    assign(ins, in_vals, in_total, in_ok)
                    if any(l["cost_usd"] is not None and l["posting_id"] not in updates for l in swap):
                        for l in swap:
                            updates.pop(l["posting_id"], None)
        if not updates:
            return 0
        fx = self.px.fx_at(ts * 1000)
        n9 = 0
        old9 = {l["posting_id"]: l["cost_usd"] for l in legs}
        for pid, usd in updates.items():
            try:
                if old9.get(pid) is not None and abs(float(old9[pid]) - usd) <= 1e-9 * max(1.0, abs(usd)):
                    continue
            except (TypeError, ValueError):
                pass
            cur9 = self._leg_sql(
                "_price_tx.1",
                (repr(usd), repr(usd * fx) if fx else None, pid))
            n9 += max(0, cur9.rowcount or 0)
        self.conn.commit()
        return n9

    @staticmethod
    def _swap_split(V, vals, total, ok, stable):
        n = len(vals)
        if n == 1:
            return [V]
        if ok and total > 0:
            return [V * v / total for v in vals]
        miss = [i for i, v in enumerate(vals) if v is None]
        if len(miss) == 1:
            known = sum((v for v in vals if v is not None), Decimal(0))
            if V - known > 0:
                return [(V - known) if i == miss[0] else vals[i] for i in range(n)]
        return None

    def _px_skip_json(self) -> str:
        try:
            sig = tuple(self.conn.execute("SELECT COUNT(*), MAX(asset_id) FROM assets").fetchone()) + (spamguard.user_sig(),)
        except sqlite3.Error:
            return self._px_skip[1]
        if sig != self._px_skip[0]:
            ids = []
            for r in self.conn.execute("SELECT asset_id, chain, address, symbol FROM assets WHERE kind='token' AND symbol IS NOT NULL"):
                s9 = r["symbol"] or ""
                if spamguard.impostor_of(s9) or spamguard.fake_major(s9, [(r["chain"], r["address"])]):
                    ids.append(int(r["asset_id"]))
            self._px_skip = (sig, json.dumps(ids))
        return self._px_skip[1]

    def _px_bulk_on(self) -> bool:
        return (self.cfg.get("backfill") or {}).get("px_prefetch") is not False

    def _leg_px_sym(self, aid: int):
        r = self.conn.execute("SELECT kind, chain, address, symbol FROM assets WHERE asset_id=?", (aid,)).fetchone()
        if not r:
            return None
        kind, chain, ca, sym = r["kind"], r["chain"], r["address"], (r["symbol"] or "").upper()
        if kind == "native":
            sym = sym or self.native_sym.get(chain, "")
            return None if sym in pricing.DOLLAR_NATIVES else (sym or None)
        if kind == "token" and ca:
            if token_tables.STABLE_CAS.get(chain, {}).get(ca) or (chain == "sol" and token_tables.STABLE_MINTS.get(ca)) \
                    or token_tables.JPY_STABLE_CAS.get(chain, {}).get(ca):
                return None
            if ca == self.wrapped.get(chain):
                return self.native_sym.get(chain, "ETH")
            if sym in ("USDT", "USDC", "DAI", "USDG", "USDE", "CUSD", "USD1", "NUSD"):
                return None
            sym = acct_norm.norm_ticker(sym)
            if sym in pricing.NATIVE_EX_TICKER:
                return None
            return None if sym in ("USDT", "USDC", "DAI", "USDG", "USDE", "CUSD", "USD1", "NUSD") else (sym or None)
        return None

    def _px_prefetch(self, rows, deadline: float):
        pairs, tss = [], []
        sym_of = {}
        for r in rows:
            for lg in self.conn.execute("SELECT asset_id, event_ts FROM postings WHERE source_kind='chain_tx'"
                                        " AND source_ns=? AND source_id=?", (r["chain"], r["txhash"])).fetchall():
                aid9 = int(lg["asset_id"])
                if aid9 not in sym_of:
                    sym_of[aid9] = self._leg_px_sym(aid9)
                ms9 = int(lg["event_ts"]) * 1000
                if sym_of[aid9]:
                    pairs.append((sym_of[aid9], ms9))
                tss.append(ms9)
        c9 = self.px.prefetch_candles(pairs, max_calls=PRICE_PREFETCH_CALLS, deadline=deadline) if pairs else {"calls": 0, "filled": 0}
        f9 = self.px.prefetch_fx(tss, max_calls=PRICE_PREFETCH_CALLS, deadline=deadline) if tss else {"calls": 0, "filled": 0}
        if c9["calls"] or f9["calls"]:
            log.info("가격 선조회: tx %d · 1분봉 %d콜 %d분 · 환율 %d콜 %d분", len(rows), c9["calls"], c9["filled"], f9["calls"], f9["filled"])

    def krw_fill_pass(self):
        if time.time() - getattr(self, "_last_krw_fill", 0) < KRW_FILL_SEC or not self._px_bulk_on():
            return
        self._last_krw_fill = time.time()
        fail = self.__dict__.setdefault("_krw_fill_fail", {})
        now9 = time.time()
        mins = [int(r[0]) for r in self.conn.execute(
            "SELECT DISTINCT (event_ts / 60) * 60 FROM postings WHERE cost_usd IS NOT NULL AND cost_krw IS NULL"
            " ORDER BY 1").fetchall() if now9 - fail.get(int(r[0]), 0) >= 3600]
        if not mins:
            return
        want = []
        for m9 in mins:
            if len(want) >= 4000:
                break
            want.append(m9)
        with self.px.lock:
            have0 = {m9 for m9 in want if str(m9 * 1000) in self.px.d["fx"]}
        st9 = self.px.prefetch_fx([m9 * 1000 for m9 in want if m9 not in have0], max_calls=KRW_FILL_CALLS,
                                  deadline=time.time() + 30) if len(have0) < len(want) else {"calls": 0, "filled": 0, "done": True}
        n9 = 0
        want9 = set(want)
        by_min = {}
        for r in self.conn.execute("SELECT posting_id, cost_usd, event_ts FROM postings WHERE cost_usd IS NOT NULL AND cost_krw IS NULL").fetchall():
            m9 = (int(r["event_ts"]) // 60) * 60
            if m9 in want9:
                by_min.setdefault(m9, []).append(r)
        for m9 in want:
            with self.px.lock:
                fx = self.px.d["fx"].get(str(m9 * 1000))
            if not fx:
                if st9.get("done"):
                    fail[m9] = now9
                continue
            for r in by_min.get(m9, ()):
                try:
                    krw9 = repr(float(r["cost_usd"]) * fx)
                except (TypeError, ValueError):
                    continue
                self._leg_sql("krw_fill_pass.1", (krw9, r["posting_id"], r["cost_usd"]))
                n9 += 1
        self.conn.commit()
        if n9 or st9["calls"]:
            log.info("원화 원가 채움: %d레그 (환율 %d콜 · 남은 분 %d)", n9, st9["calls"], max(0, len(mins) - len(want)))


    def price_pass(self):
        if time.time() - self._last_price_pass < PRICE_IDLE_SEC:
            return
        self._last_price_pass = time.time()
        self._ex_proven_cache = {}
        self._ex_proven_v_cache = {}
        now9 = time.time()
        boff = self.__dict__.setdefault("_px_backoff", {})
        cand = [r for r in self.conn.execute(
            "SELECT source_ns AS chain, source_id AS txhash, MIN(event_ts) AS ts FROM postings"
            " WHERE source_kind='chain_tx' AND cost_usd IS NULL"
            " AND (leg_kind='gas' OR (event='SWAP' AND leg_kind IN ('disp','acq'))"
            "      OR (event LIKE 'LP\\_%' ESCAPE '\\' AND leg_kind IN ('disp','acq'))"
            "      OR (event='STAKE_REWARD' AND leg_kind='acq')"
            "      OR (leg_kind='move_in' AND location LIKE 'out:%'"
            "          AND asset_id NOT IN (SELECT value FROM json_each(?))))"
            " GROUP BY source_ns, source_id",
            (self._px_skip_json(),)).fetchall()
            if boff.get((r["chain"], r["txhash"]), (0, 0))[0] <= now9]
        bulk = len(cand) > PRICE_BATCH * 3 and self._px_bulk_on()
        if bulk:
            cand.sort(key=lambda r9: (int(r9["ts"] or 0), r9["chain"], r9["txhash"]))
            i9 = random.randrange(len(cand))
            rows = (cand[i9:] + cand[:i9])[:PRICE_BULK_BATCH]
            try:
                self._px_prefetch(rows, time.time() + PRICE_BULK_BUDGET)
            except Exception as e:   # noqa: BLE001 [optional]
                calcguard.swallowed("core_pricing:PricingMixin.price_pass[_px_prefetch]", e)
                log.warning("가격 선조회 실패(단건 조회로 계속): %s", e)
        else:
            rows = random.sample(cand, PRICE_BATCH) if len(cand) > PRICE_BATCH else cand
        t_end9 = time.time() + PRICE_BULK_BUDGET
        done = 0
        filled = 0
        for i9, r in enumerate(rows):
            if bulk and i9 >= PRICE_BATCH and time.time() > t_end9:
                break
            k9 = (r["chain"], r["txhash"])
            try:
                if self._price_tx(r["chain"], r["txhash"]):
                    filled += 1
                    boff.pop(k9, None)
                else:
                    d9 = min(PRICE_BACKOFF_MAX, max(PRICE_BACKOFF_MIN, boff.get(k9, (0, 0))[1] * 2))
                    boff[k9] = (time.time() + d9, d9)
                done += 1
            except Exception as e:  # noqa: BLE001 [isolate]
                calcguard.swallowed("core_pricing:PricingMixin.price_pass[_price_tx]", e)
                self.conn.rollback()
                log.warning("가격패스 %s %s 실패(다음 주기 재시도): %s", r["chain"], r["txhash"][:12], e)
        if len(boff) > 50000:
            for k9 in [k for k, v in boff.items() if v[0] <= now9][:25000]:
                boff.pop(k9, None)
        ex_rows = self.conn.execute(
            "SELECT posting_id, event_ts, cost_krw FROM postings"
            " WHERE source_kind='exchange' AND cost_usd IS NULL AND cost_krw IS NOT NULL"
            " ORDER BY RANDOM() LIMIT ?", (PRICE_BATCH,)).fetchall()
        ex_done = 0
        for r in ex_rows:
            fx = self.px.fx_at(r["event_ts"] * 1000)
            time.sleep(0.2)
            if fx is None:
                break
            if fx:
                try:
                    usd = float(r["cost_krw"]) / fx
                except (TypeError, ValueError):
                    continue
                self._leg_sql("price_pass.1", (repr(usd), r["posting_id"]))
                ex_done += 1
        exf_rows = self.conn.execute(
            "SELECT DISTINCT source_ns, source_id, event_ts FROM postings"
            " WHERE source_kind='exchange' AND source_ns LIKE '%:trade'"
            " AND cost_usd IS NULL AND leg_seq=0"
            " ORDER BY RANDOM() LIMIT ?", (PRICE_BATCH,)).fetchall()
        exf_done = 0
        for r in exf_rows:
            ex9 = r["source_ns"].rsplit(":", 1)[0]
            raw9 = self.conn.execute(
                "SELECT payload FROM raw_ex WHERE exchange=? AND kind='trade' AND uuid=?"
                " ORDER BY revision DESC LIMIT 1", (ex9, r["source_id"])).fetchone()
            if not raw9:
                continue
            try:
                f9 = json.loads(raw9["payload"])
                qty9 = Decimal(str(f9.get("qty") or "0"))
                px99 = Decimal(str(f9.get("price") or "0"))
            except (json.JSONDecodeError, ArithmeticError):
                continue
            qu9 = self.svc_exf._quote_usd(str(f9.get("quote") or ""), int(r["event_ts"]))
            time.sleep(0.1)
            if qu9 is None or qty9 <= 0 or px99 <= 0:
                continue
            usd9 = float(qty9 * px99 * qu9)
            fx99 = self.px.fx_at(int(r["event_ts"]) * 1000)
            self._leg_sql(
                "price_pass.2",
                (repr(usd9), repr(usd9 * fx99) if fx99 else None,
                 r["source_ns"], r["source_id"]))
            exf_done += 1
        self._price_upbit_quote_fills(PRICE_BATCH)
        self.conn.commit()
        if ex_rows:
            log.info("가격패스(거래소): %d/%d 환산", ex_done, len(ex_rows))
        if exf_rows:
            log.info("가격패스(해외체결): %d/%d 환산", exf_done, len(exf_rows))
        if filled:
            log.info("가격패스: %d tx 원가 채움 (시도 %d)", filled, done)
        self.px.flush()

    def _price_upbit_quote_fills(self, limit: int) -> int:
        n9 = 0
        ubq_rows = self.conn.execute(
            "SELECT DISTINCT source_id FROM postings WHERE source_ns='upbit:order' AND leg_seq=0"
            " AND cost_usd IS NULL AND cost_krw IS NULL ORDER BY RANDOM() LIMIT ?", (limit,)).fetchall()
        for r in ubq_rows:
            raw9 = self.conn.execute(
                "SELECT payload FROM raw_ex WHERE exchange='upbit' AND kind='order' AND uuid=?"
                " ORDER BY revision DESC LIMIT 1", (r["source_id"],)).fetchone()
            try:
                o9 = json.loads(raw9["payload"]) if raw9 else None
            except json.JSONDecodeError:
                o9 = None
            p9 = self.svc_exf._upbit_quote_fill_legs(o9) if isinstance(o9, dict) else None
            if p9 is None:
                continue
            qu9 = self.svc_exf._quote_usd(p9[1], p9[4])
            time.sleep(0.1)
            if qu9 is None:
                continue
            usd9 = float(Decimal(abs(p9[3])) / (Decimal(10) ** 8) * qu9)
            fx99 = self.px.fx_at(p9[4] * 1000)
            self._leg_sql(
                "_price_upbit_quote_fills.1",
                (repr(usd9), repr(usd9 * fx99) if fx99 else None, r["source_id"]))
            n9 += 1
        return n9
