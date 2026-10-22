import histmark, timeutil
import discopen
import json
import time
import logging

log = logging.getLogger('tj-core')


class LateMixin:

    def _recon_view(self, chain: str):
        cache = self.__dict__.setdefault("_recon_cache", {})
        T = self._meta_get(f"recon_done_{chain}")
        if chain not in cache or cache[chain][2] != T:
            ws = set()
            r = self.conn.execute("SELECT payload FROM raw_observations WHERE obs_id=?", (f"recon:{chain}",)).fetchone()
            try:
                d9 = json.loads(r[0]) if r and r[0] else {}
                ws = {str(w).lower() for w, v in d9.items() if isinstance(v, dict)} if isinstance(d9, dict) else set()
            except (TypeError, ValueError):
                ws = set()
            cache[chain] = (int(float(T)) if T else None, ws, T)
        return cache[chain][:2]

    def _recon_view_drop(self, chain: str) -> None:
        self.__dict__.get("_recon_cache", {}).pop(chain, None)

    def _note_pre_window(self, chain: str, ts_raw, txhash: str = None):
        ts = self._ts_of(ts_raw)
        if ts is None:
            return
        T, ws = self._recon_view(chain)
        wT = self.svc_recon._wrecon_times(chain)
        dT = self.svc_recon._disc_max_t(chain)
        if (not T or ts >= T) and not any(ts < t9 for t3 in wT.values() for t9 in t3[:2] if t9) and not (dT and ts < dT):
            return
        if txhash:
            hit = False
            hits9 = set()
            blk9 = self.svc_recon._tx_block(chain, txhash)
            for r in self.conn.execute("SELECT DISTINCT p.location, a.kind, a.address, p.asset_id FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
                                       " WHERE p.source_kind='chain_tx' AND p.source_ns=? AND p.source_id=? AND p.location LIKE ?",
                                       (chain, txhash, f"wallet:{chain}:%")).fetchall():
                w = r[0].split(":", 2)[2].lower()
                w = w.split(":stake:", 1)[0]
                wt3 = wT.get(w)
                wt9 = (wt3[1] if r[1] == "native" else wt3[0]) if wt3 else None
                sid9 = f"recon:{chain}:{w}" + (":native" if (wt3 and r[1] == "native" and wt3[2]) else "")
                tok9 = r[1] != "native"
                if (T and w in ws and self.svc_recon._absorbed(f"recon:{chain}", ts, T, blk9)
                        and (not tok9 or self.svc_recon._obs_tok_observed(f"recon:{chain}", w, r[2]))) \
                        or (wt9 and self.svc_recon._absorbed(sid9, ts, wt9, blk9) and (not tok9 or self.svc_recon._obs_tok_observed(sid9, w, r[2]))) \
                        or (dT and ts < dT and r[0].count(":") == 2
                            and discopen.absorbed_by(self.conn, chain, r[0], r[3], blk9, ts)[0] is not None):
                    hit = True
                    hits9.add((r[0], r[3]))
            if not hit:
                return
            if self._late_absorb(chain, txhash, ts, hits9):
                return
        elif not T or ts >= T:
            return
        k = f"ext_prewindow:{chain}"
        n = int(self._meta_get(k) or 0) + 1
        self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k, str(n)))
        if txhash:
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (f"ext_prewindow_tx:{chain}:{txhash}", str(ts)))

    def _hist_late_scan(self, now: float = None):
        if self.conn.in_transaction:
            return None
        now = time.time() if now is None else float(now)
        top = int(self.conn.execute("SELECT MAX(posting_id) FROM postings").fetchone()[0] or 0)
        cur = self._meta_get(histmark.HIST_LATE_PID_K)
        try:
            cur = int(cur) if cur is not None else None
        except (TypeError, ValueError):
            cur = None
        if cur is not None and top <= cur:
            return None
        t9 = None
        if cur is not None:
            r = self.conn.execute(
                "SELECT MIN(p.event_ts) FROM postings p WHERE p.posting_id > ? AND p.posting_id <= ? AND p.event_ts < ? AND " + histmark.HIST_LATE_EXCL_SQL,
                (cur, top, timeutil.kst_day0(now + histmark.HIST_LATE_CLOSE_S))).fetchone()
            t9 = r[0] if r else None
        self.conn.execute("BEGIN")
        try:
            iso = histmark.hist_late_put(self.conn, int(t9), now) if t9 is not None else None
            self.conn.execute("INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (histmark.HIST_LATE_PID_K, str(top)))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        if iso:
            if int(t9) >= timeutil.kst_day0(now):
                log.info("마감 직전 원장 행(posting %d~%d) — 오늘(%s) 마감 스냅숏 지문 표식", (cur or 0) + 1, top, iso)
            else:
                log.info("늦은 원장 행(posting %d~%d) — 지난 곡선 다시 계산 표식: %s 부터", (cur or 0) + 1, top, iso)
        return iso

    HL_FENCE_TRIES = 5

    HL_FENCE_SLEEP = 2.0

    def _hist_late_fence(self) -> str:
        if self.conn.in_transaction:
            self.conn.rollback()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            cur = self._meta_get(histmark.HIST_LATE_PID_K)
            try:
                ok9 = cur is not None and int(cur) >= 0
            except (TypeError, ValueError):
                ok9 = False
            if ok9:
                self.conn.rollback()
                return "keep"
            top = int(self.conn.execute("SELECT MAX(posting_id) FROM postings").fetchone()[0] or 0)
            self.conn.execute("INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (histmark.HIST_LATE_PID_K, str(top)))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        log.info("늦은 원장 행 커서 울타리 초기화: posting %d (이 뒤 기장분부터 지난 곡선 표식 대상 — 그 전 행은 소급 안 함)", top)
        return "init"
