from __future__ import annotations
import os
import threading
import time
import common
import pricing
import candles
import logging
import calcguard

log = logging.getLogger('tj-web')

SPOT_PATH = os.path.join(common.STATE_DIR, "spot.json")


PX1004_ALT_OK = ("binance", "bybit", "coingecko")


def _alt_src_of(why) -> str:
    p9 = str(why or "").split(" ")
    return f"coingecko:{p9[1]}" if p9[0] == "coingecko" and len(p9) > 1 and p9[1] else p9[0]


def _alt_src_stale(holder, sym, src, cid=None, now=None) -> bool:
    v9, _, id9 = str(src or "").partition(":")
    if v9 in ("binance", "bybit"):
        return candles.same_coin(holder, v9, sym, now=now, fetch=False)[0] is False
    if v9 == "coingecko" and id9:
        cur9 = cid if cid is not None else candles.holder_cg_id(holder, sym, now=now, fetch=False)
        return bool(cur9) and cur9 != id9
    return False


def _px1004_spot_filter(ex_usd, ex_ts, d) -> dict:
    krw9 = set(d.get("upbit_krw") or ()) if isinstance(d, dict) else set()
    src0 = d.get("ex_alt_src") if isinstance(d, dict) and isinstance(d.get("ex_alt_src"), dict) else {}
    keep9, drop9 = {}, []
    for k9 in [k9 for k9 in list(ex_usd or {}) if str(k9).startswith("upbit:")]:
        s9 = str(k9).split(":", 1)[1]
        if krw9 and s9 in krw9:
            continue
        sv9 = str(src0.get(s9) or "")
        if sv9.split(":", 1)[0] in PX1004_ALT_OK and not _alt_src_stale("upbit", s9, sv9):
            keep9[s9] = sv9
            continue
        ex_usd.pop(k9, None)
        (ex_ts or {}).pop(k9, None)
        drop9.append(s9)
    if drop9:
        log.info("px1004: 되살린 업비트 시세 중 출처 모르는 비원화 값 %d개 버림(다음 조회로 다시): %s", len(drop9), sorted(drop9)[:12])
    return keep9


def _cg_key_set() -> bool:
    try:
        import cgkey
        return bool(cgkey.key())
    except Exception as _cg9:
        calcguard.swallowed("view_spot:_cg_key_set", _cg9)
        return False


class Spot:

    STALE_SEC = 3600
    MIN_RESERVE_USD = 10_000.0
    RESERVE_STALE_SEC = 6 * 3600
    UNV_AGREE = 0.10
    RATE_STALE_SEC = 3600
    GT_BATCH = 30
    GT_PENDING_MAX_TRIES = 10
    DEX_FRESH_SEC = 1800
    DEX_MAX_AGE_SEC = 6 * 3600
    GT_BACKOFF_MIN = 60
    GT_BACKOFF_MAX = 300
    GT_GAP_START = 11.0
    GT_GAP_MIN = 10.0
    GT_GAP_MAX = 30.0
    GT_TICK_BUDGET = 22.0
    GT_REPOLL_SEC = 90
    GT_QUAR_EVERY = 5 * 3600
    GT_PROOF_EVERY = 3600
    GT_GUARD_EVERY = 3 * 3600
    GT_FLOOR_SEC = 1800
    GT_FLOOR_X = 1.25
    PROOF_DIVERGE = 0.20
    GT_TIER2_DELAY = 1200
    GT_LOG_EVERY = 600
    DS_EVERY = 90
    DS_AFTER_SEC = 900
    DS_RETRY_SEC = 600
    DS_MAX_BATCHES = 6
    DS_BACKOFF_SEC = 180

    def __init__(self):
        d = common.read_json(SPOT_PATH, {}) if os.path.exists(SPOT_PATH) else {}
        self.usd = d.get("usd", {})
        self.usd_ts = d.get("usd_ts", {})
        self.dex_usd = d.get("dex_usd", {})
        self.dex_ts = d.get("dex_ts", {})
        self.dex_res = d.get("dex_res", {})
        self.dex_res_ts = d.get("dex_res_ts", {})
        self.min_reserve_usd = self.MIN_RESERVE_USD
        self.guarded = {k: v for k, v in (d.get("guarded") or {}).items() if isinstance(v, str)}
        self._guard_seen = {k: time.time() for k in self.guarded}
        self._guard_logged = {k: v.split(" ", 1)[0] for k, v in self.guarded.items()}
        self.ex_usd = d.get("ex_usd", {})
        self.ex_ts = d.get("ex_ts", {})
        self.ex_alt_src = _px1004_spot_filter(self.ex_usd, self.ex_ts, d)
        self.ex_want = set()
        self._ex_at = {}
        self.token_pairs = set()
        self.off_chains = set()
        self.off_at = {}
        self._tp_slots = {}
        self.token_slow = set()
        self.meta_want = set()
        self.token_meta = {k: v for k, v in (d.get("meta") or {}).items()
                           if isinstance(v, list) and len(v) == 2}
        self._meta_polled = {}
        self._res_gecko_ts = {k: v for k, v in self.dex_res_ts.items()
                              if (d.get("dex_src") or {}).get(k, "gecko") == "gecko"}
        self.proof_div = []
        self.ex_dead = {}
        self.ex_dead_syms = {}
        self._gt_floor = 0.0
        self._gt_429_at = 0.0
        self._gt_gap = self.GT_GAP_START
        self._gt_next_at = 0.0
        self._gt_ok_since = 0
        self.okx_pairs = set()
        self._gt_at = 0
        self._gt_done = set()
        self._gt_tries = {}
        self._ex_done = set()
        self._gt_polled = {k: float(v) for k, v in self.dex_ts.items() if isinstance(v, (int, float))}
        self.token_prio = {}
        self.token_skip = set()
        self.dex_src = {k: v for k, v in (d.get("dex_src") or {}).items() if isinstance(v, str)}
        self._ds_at = 0
        self._ds_polled = {}
        self._ds_backoff_until = 0
        self.ds_stat = {}
        self._gt_backoff_until = 0
        self._gt_backoff_sec = 0
        self._gt_err_log = {}
        self._gt_err_since = 0
        self.gt_stat = {}
        self.dex_max_age = self.DEX_MAX_AGE_SEC
        self._okx_at = 0
        self._okx_fullscan_done = False
        self._okx_fullscan_tries = 0
        self.rate = d.get("rate") or 0
        self.rate_ts = float(d.get("rate_ts") or d.get("updated") or 0) if self.rate else 0.0
        self.fx_basis = d.get("fx_basis") or 0
        self.fx_basis_ts = float(d.get("fx_basis_ts") or d.get("updated") or 0) if self.fx_basis else 0.0
        self.dex_alt = {}
        self.upbit_krw = set(d.get("upbit_krw") or [])
        self.upbit_alt = {k: set(v) for k, v in (d.get("upbit_alt") or {}).items()}
        self.upbit_alt_why = {}
        self.updated = d.get("updated") or 0
        self.syms = set()
        self._fx_at = 0
        self._mk_at = 0
        self.lock = threading.Lock()

    def want(self, syms):
        with self.lock:
            self.syms |= {s for s in syms if s}

    def want_tokens(self, pairs, slot="main"):
        with self.lock:
            off = self.off_chains
            self._tp_slots[slot] = {p for p in pairs if p[0] and p[1] and p[0] not in off}
            self.token_pairs = set().union(*self._tp_slots.values())

    def set_token_prio(self, prio, skip=None, slow=None, meta_want=None):
        with self.lock:
            off = self.off_chains
            self.token_prio = {p: float(v or 0) for p, v in (prio or {}).items() if p and p[0] and p[1] and p[0] not in off}
            self.token_skip = set(skip or ())
            self.token_slow = set(slow or ())
            self.meta_want = {p for p in (meta_want or ()) if p and p[0] not in off}

    def ex_age(self, ex, sym):
        ts = self.ex_ts.get(f"{ex}:{sym}")
        return (time.time() - ts) if ts else None

    def want_okx(self, pairs):
        with self.lock:
            off = self.off_chains
            self.okx_pairs = {p for p in pairs if p[0] and p[1] and p[0] not in off}

    def want_ex(self, exs):
        with self.lock:
            self.ex_want |= {e for e in exs if e}

    def ex_price(self, ex, sym):
        k = f"{ex}:{sym}"
        if time.time() - self.ex_ts.get(k, 0) > self.STALE_SEC:
            return None
        return self.ex_usd.get(k)

    @staticmethod
    def _okx_creds():
        e9 = common.read_env_file()
        creds = {k: e9.get(n, "") for k, n in (("key", "TJ_OKX_KEY"), ("secret", "TJ_OKX_SECRET"), ("passphrase", "TJ_OKX_PASSPHRASE"))}
        return creds if all(creds.get(k) for k in ("key", "secret", "passphrase")) else None

    def dex_reserve(self, chain, ca):
        key = f"{chain}:{ca}"
        if self.off_at.get(chain, time.time()) - self.dex_res_ts.get(key, 0) > self.RESERVE_STALE_SEC:
            return None
        return self.dex_res.get(key)

    def _guard_note(self, key, why, quiet=False):
        self._guard_seen[key] = time.time()
        prev = self.guarded.get(key)
        kind_prev = prev.split(" ", 1)[0] if prev else None
        kind_new = why.split(" ", 1)[0] if why else None
        if kind_prev != kind_new:
            if why:
                if self._guard_logged.get(key) != kind_new:
                    log.warning("DEX 가격 가드: %s — %s → 평가불가(0)", key, why)
                self._guard_logged[key] = kind_new
            elif not quiet:
                log.info("DEX 가격 가드 해제: %s", key)
                self._guard_logged.pop(key, None)
        if why:
            self.guarded[key] = why
        else:
            self.guarded.pop(key, None)

    def _liq_guarded(self, pair, now):
        k = f"{pair[0]}:{pair[1]}"
        rt = self._res_gecko_ts.get(k, 0)
        if not rt or now - rt > self.RESERVE_STALE_SEC:
            return False
        rv = self.dex_res.get(k)
        return rv is not None and rv < self.min_reserve_usd

    def dex_age(self, chain, ca):
        ts = self.dex_ts.get(f"{chain}:{ca}")
        return (time.time() - ts) if ts else None

    def dex_price(self, chain, ca):
        key = f"{chain}:{ca}"
        ts = self.dex_ts.get(key, 0)
        if self.off_at.get(chain, time.time()) - ts > self.dex_max_age:
            return None
        px = self.dex_usd.get(key)
        res = self.dex_reserve(chain, ca)
        if px and res is not None and res < self.min_reserve_usd:
            self._guard_note(key, f"풀 유동성 ${res:,.2f} < ${self.min_reserve_usd:,.0f} (가격 ${px:,.6g})")
            return 0.0
        if px and res is None:
            last9 = self.dex_res.get(key)
            if isinstance(last9, (int, float)) and last9 < self.min_reserve_usd:
                self._guard_note(key, f"풀 유동성 ${last9:,.2f} < ${self.min_reserve_usd:,.0f} (마지막 값 · 가격 ${px:,.6g})")
                return 0.0
            if not self._dex_agree(chain, key, px):
                self._guard_note(key, f"유동성 미상 — 다른 출처 확인 없음(미검증 · 가격 ${px:,.6g})")
                return 0.0
        if px and key in self.guarded and self.guarded[key].startswith(("풀 유동성", "유동성 미상")):
            self._guard_note(key, None)
        return px

    def _dex_agree(self, chain, key, px):
        alt = self.dex_alt.get(key) or {}
        t0 = self.off_at.get(chain, time.time())
        fr = {s: p for s, (p, t) in alt.items() if p and p > 0 and t0 - t <= self.dex_max_age}
        po = fr.get("okx")
        if not (po and px and px > 0) or max(po, px) / min(po, px) > 1 + self.UNV_AGREE:
            return False
        if self.dex_src.get(key) != "okx":
            return True
        return any(s != "okx" and max(po, p) / min(po, p) <= 1 + self.UNV_AGREE for s, p in fr.items())

    def _alt_note(self, key, src, px, ts):
        if px and px > 0:
            self.dex_alt.setdefault(key, {})[src] = (float(px), float(ts))

    def rate_state(self, now=None):
        if not self.rate:
            return "none"
        now = time.time() if now is None else float(now)
        return "live" if self.rate_ts and now - self.rate_ts <= self.RATE_STALE_SEC else "stale"

    def dex_pending(self, chain, ca):
        with self.lock:
            return (chain, ca) in self.token_pairs and (chain, ca) not in self._gt_done

    def ex_pending(self, ex):
        with self.lock:
            return ex in self.ex_want and ex not in self._ex_done

    def price(self, sym):
        ts = self.usd_ts.get(sym, 0)
        if time.time() - ts > self.STALE_SEC:
            return None
        return self.usd.get(sym)

    def loop(self):
        while True:
            t0 = time.time()
            try:
                self.tick()
            except (Exception, SystemExit) as e:
                calcguard.swallowed("view_spot:Spot.loop", e)
                log.warning("spot tick 실패: %s", e)
            time.sleep(max(5.0, 30.0 - (time.time() - t0)))

    SLOW_TICK_SEC = 120

    def _lap(self, name):
        t9 = time.time()
        self._laps.append((name, t9 - self._lap_at))
        self._lap_at = t9

    def _gt_plan(self, pairs, prio, now):
        by_chain = {}
        for ch, ca in pairs:
            k = f"{ch}:{ca}"
            key = (self._gt_polled.get(k, 0) + (0 if (ch, ca) in prio else self.GT_TIER2_DELAY),
                   -prio.get((ch, ca), 0.0), ca)
            by_chain.setdefault(ch, []).append((key, ca))
        batches = []
        for ch, lst in by_chain.items():
            lst.sort()
            for i in range(0, len(lst), self.GT_BATCH):
                part = lst[i:i + self.GT_BATCH]
                batches.append((part[0][0], ch, [ca for _, ca in part]))
        batches.sort(key=lambda b: (b[0], b[1]))
        return [(ch, cas) for _, ch, cas in batches]

    def _gt_note_err(self, err, now, extra=""):
        kind, code, why = err
        k = (kind, code)
        nf9 = (kind[3:] if kind.startswith("ds-") else kind) == "http" and str(code) == "404"
        ent = self._gt_err_log.get(k)
        if ent is None or now - ent[0] >= self.GT_LOG_EVERY:
            n9 = (ent[1] if ent else 0) + 1
            src = "덱스스크리너" if kind.startswith("ds-") else "게코"
            base = kind[3:] if kind.startswith("ds-") else kind
            label = {"rate": "요청 한도(HTTP 429)", "http": f"HTTP {code}", "net": "연결 실패"}.get(base, base)
            if base == "rate" and code == "gate":
                label = "요청 한도 쉼(같은 IP 차트·다른 조회의 429 쉼·간격 — 안 보냄)"
            (log.debug if nf9 else log.warning)(
                "%s DEX 가격 조회 실패: %s%s — 최근 %d분 %d회%s", src, label, f" ({why})" if why and base != "rate" else "",
                max(1, int((now - ent[0]) / 60)) if ent else 1, n9, extra)
            self._gt_err_log[k] = [now, 0]
        else:
            ent[1] += 1
        if not self._gt_err_since and not nf9:
            self._gt_err_since = now

    def _ds_round(self, now):
        with self.lock:
            prio = dict(self.token_prio)
            skip = set(self.token_skip)
        cand = []
        for (ch, ca), v in prio.items():
            if (ch, ca) in skip or not pricing.DS_CHAIN.get(ch):
                continue
            k = f"{ch}:{ca}"
            if now - self.dex_ts.get(k, 0) <= self.DS_AFTER_SEC or now - self._ds_polled.get(k, 0) < self.DS_RETRY_SEC:
                continue
            if self._liq_guarded((ch, ca), now):
                continue
            cand.append((-v, ch, ca))
        cand.sort()
        by_chain = {}
        for _v, ch, ca in cand:
            by_chain.setdefault(ch, []).append(ca)
        batches = []
        for ch, cas in by_chain.items():
            for i in range(0, len(cas), self.GT_BATCH):
                batches.append((ch, cas[i:i + self.GT_BATCH]))
        rank = {(ch, ca): i for i, (_v, ch, ca) in enumerate(cand)}
        batches.sort(key=lambda b: rank[(b[0], b[1][0])])
        calls = got_n = 0
        limited = False
        pricing.ds_take_error()
        for ch, batch in batches[:self.DS_MAX_BATCHES]:
            calls += 1
            got, res = pricing.ds_token_prices(ch, batch)
            err = pricing.ds_take_error()
            if err and err[0] == "rate" and not (got or res):
                self._ds_backoff_until = now + self.DS_BACKOFF_SEC
                limited = True
                self._gt_note_err(("ds-" + err[0], err[1], err[2]), now, f" · 덱스스크리너 {self.DS_BACKOFF_SEC}초 쉼")
                break
            if err:
                self._gt_note_err(("ds-" + err[0], err[1], err[2]), now)
            for ca in batch:
                self._ds_polled[f"{ch}:{ca}"] = now
            self._ds_take_meta(ch, now)
            for ca, px in got.items():
                k = f"{ch}:{ca}"
                if now - self.dex_ts.get(k, 0) <= self.DS_AFTER_SEC:
                    continue
                self.dex_usd[k] = px
                self.dex_ts[k] = int(now)
                self.dex_src[k] = "dexscreener"
                self._alt_note(k, "dexscreener", px, now)
                got_n += 1
                if ca in res and now - self._res_gecko_ts.get(k, 0) > self.RESERVE_STALE_SEC:
                    self.dex_res[k] = res[ca]
                    self.dex_res_ts[k] = int(now)
        meta_calls = 0
        if not limited and calls < self.DS_MAX_BATCHES:
            with self.lock:
                mw = sorted(self.meta_want)
            mcand = {}
            for ch, ca in mw:
                k = f"{ch}:{ca}"
                if k in self.token_meta or not pricing.DS_CHAIN.get(ch) or now - self._meta_polled.get(k, 0) < 6 * 3600:
                    continue
                mcand.setdefault(ch, []).append(ca)
            for ch, cas9 in sorted(mcand.items()):
                batch = cas9[:self.GT_BATCH]
                for ca in batch:
                    self._meta_polled[f"{ch}:{ca}"] = now
                meta_calls += 1
                pricing.ds_token_prices(ch, batch)
                err = pricing.ds_take_error()
                self._ds_take_meta(ch, now)
                if err and err[0] == "rate":
                    self._ds_backoff_until = now + self.DS_BACKOFF_SEC
                    break
                break
        if calls or cand or meta_calls:
            self.ds_stat = {"at": int(now), "cand": len(cand), "calls": calls, "priced": got_n, "limited": limited,
                            "meta_calls": meta_calls, "meta": len(self.token_meta)}

    def _ds_take_meta(self, ch, now):
        m = pricing.ds_take_meta() if hasattr(pricing, "ds_take_meta") else {}
        with self.lock:
            mw = set(self.meta_want)
        for ca, (sym9, name9) in (m or {}).items():
            if (ch, ca) in mw and (sym9 or name9):
                self.token_meta[f"{ch}:{ca}"] = [sym9, name9]

    def _gt_round(self, now):
        with self.lock:
            tp = set(self.token_pairs)
            skip = set(self.token_skip)
            slow = set(self.token_slow)
            prio = dict(self.token_prio)
        pairs = []
        for p in sorted(tp):
            last = self._gt_polled.get(f"{p[0]}:{p[1]}", 0)
            if now - last < self.GT_REPOLL_SEC:
                continue
            if p in skip and now - last < self.GT_PROOF_EVERY:
                continue
            if p in slow and now - last < self.GT_QUAR_EVERY:
                continue
            if now - last < self.GT_GUARD_EVERY and p in self._gt_done and self._liq_guarded(p, now):
                continue
            pairs.append(p)
        n_guard9 = sum(1 for p in tp if self._liq_guarded(p, now))
        plan = self._gt_plan(pairs, prio, now)
        calls = ok = fail = 0
        rate_err = None
        pricing.gt_take_error()
        pricing.gt_take_unresolved()
        t_start = time.time()
        for ch, batch in plan:
            sched = max(time.time(), self._gt_next_at)
            if sched - t_start > self.GT_TICK_BUDGET:
                break
            wait = sched - time.time()
            if wait > 0:
                time.sleep(wait)
            self._gt_next_at = sched + self._gt_gap
            calls += 1
            got, res = pricing.gt_token_prices_ex(ch, batch, keyed=any((ch, ca9) not in skip for ca9 in batch))
            err = pricing.gt_take_error()
            unres9 = pricing.gt_take_unresolved()
            t_got = int(now)
            for ca, px in got.items():
                self.dex_usd[f"{ch}:{ca}"] = px
                self.dex_ts[f"{ch}:{ca}"] = t_got
                self.dex_src[f"{ch}:{ca}"] = "gecko"
                self._alt_note(f"{ch}:{ca}", "gecko", px, t_got)
            for ca, rv in res.items():
                self.dex_res[f"{ch}:{ca}"] = rv
                self.dex_res_ts[f"{ch}:{ca}"] = t_got
                self._res_gecko_ts[f"{ch}:{ca}"] = t_got
            if err is None or got or res:
                ok += 1
            else:
                fail += 1
            if not (err and err[0] == "rate" and not (got or res)):
                for ca in batch:
                    self._gt_polled[f"{ch}:{ca}"] = now
            with self.lock:
                if got or res or not pricing.GT_NETWORK.get(ch):
                    self._gt_done |= {(ch, ca) for ca in batch if ca not in unres9}
                    for ca in unres9:
                        if ca in batch:
                            k = (ch, ca)
                            self._gt_tries[k] = self._gt_tries.get(k, 0) + 1
                            if self._gt_tries[k] >= self.GT_PENDING_MAX_TRIES:
                                self._gt_done.add(k)
                else:
                    for ca in batch:
                        k = (ch, ca)
                        self._gt_tries[k] = self._gt_tries.get(k, 0) + 1
                        if self._gt_tries[k] >= self.GT_PENDING_MAX_TRIES:
                            self._gt_done.add(k)
            if err and err[0] == "rate":
                rate_err = err
                break
            if err is None or got or res:
                self._gt_ok_since += 1
                floor9 = self._gt_floor if now - self._gt_429_at < self.GT_FLOOR_SEC else 0.0
                self._gt_gap = max(self.GT_GAP_MIN, floor9, self._gt_gap - 0.5)
            if err:
                self._gt_note_err(err, now)
        if rate_err:
            try:
                ra9 = float(rate_err[2]) if rate_err[2] else 0.0
            except (TypeError, ValueError):
                ra9 = 0.0
            b9 = self._gt_backoff_sec
            if not b9:
                nb9 = self.GT_BACKOFF_MIN
            elif self._gt_ok_since > 0:
                nb9 = b9 / 2
            else:
                nb9 = b9 * 2
            self._gt_backoff_sec = min(self.GT_BACKOFF_MAX, max(self.GT_BACKOFF_MIN, nb9, ra9))
            self._gt_backoff_until = time.time() + self._gt_backoff_sec
            prev_floor9 = self._gt_floor if now - self._gt_429_at < self.GT_FLOOR_SEC else 0.0
            self._gt_floor = min(self.GT_GAP_MAX, max(prev_floor9, self._gt_gap * self.GT_FLOOR_X))
            self._gt_429_at = now
            self._gt_gap = min(self.GT_GAP_MAX, self._gt_gap * 1.5)
            self._gt_ok_since = 0
            self._gt_note_err(rate_err, now, f" · {calls}/{len(plan)}묶음째 한도, {self._gt_backoff_sec:.0f}초 쉼 · 호출 간격 {self._gt_gap:.0f}초")
        elif self._gt_ok_since >= max(1, len(plan)) and (self._gt_err_since or self._gt_backoff_sec):
            if self._gt_err_since:
                log.info("게코 DEX 가격 조회 회복 — 한도 뒤 %d묶음 연속 응답 (실패 시작 %d분 전, 호출 간격 %.0f초)", self._gt_ok_since,
                         int((now - self._gt_err_since) / 60), self._gt_gap)
            self._gt_backoff_sec = 0
            self._gt_err_since = 0
            self._gt_err_log.clear()
        if plan or calls:
            self.gt_stat = {"at": int(now), "plan": len(plan), "calls": calls, "ok": ok, "fail": fail,
                            "limited": bool(rate_err), "backoff": int(self._gt_backoff_sec), "gap": round(self._gt_gap, 1),
                            "okSince": self._gt_ok_since,
                            "floor": round(self._gt_floor, 1) if now - self._gt_429_at < self.GT_FLOOR_SEC else 0,
                            "guardSlow": n_guard9}

    def _upbit_alt_global(self, syms, bn, now, fresh_s=120, reuse_s=300):
        cache9 = self.__dict__.setdefault("_alt_books", {})
        fail9 = self.__dict__.setdefault("_alt_fail", {})
        books9 = {"binance": bn or {}}
        failed9 = set()

        def book(ex):
            if ex in books9:
                return books9[ex]
            c9 = cache9.get(ex)
            d9 = c9[1] if (c9 and now - c9[0] < fresh_s) else None
            if d9 is None and ex in self.ex_want:
                d9 = {k9.split(":", 1)[1]: v9 for k9, v9 in self.ex_usd.items()
                      if k9.startswith(ex + ":") and now - float(self.ex_ts.get(k9) or 0) < reuse_s} or None
            if d9 is None and now - fail9.get(ex, 0) >= fresh_s:
                try:
                    d9 = pricing.ex_spot_usd(ex, self.rate) or {}
                    cache9[ex] = (now, d9)
                except Exception as e9:
                    calcguard.swallowed("view_spot:Spot._upbit_alt_global.book", e9)
                    log.warning("업비트 비원화 코인 달러 시세: %s 벌크 조회 실패(다음): %s", ex, common.safe_err(e9)[:120])
                    fail9[ex] = now
                    d9 = None
            if d9 is None:
                failed9.add(ex)
                d9 = {}
            books9[ex] = d9
            return d9
        ids9 = {s9: candles.holder_cg_id("upbit", s9, now=now, fetch=False) for s9 in syms}
        cgp9 = {}

        def cg_px():
            if "_done" not in cgp9:
                cgp9["_done"] = True
                cf9 = []
                cgp9.update(candles.cg_simple_usd([i9 for i9 in ids9.values() if i9], now=now, fail=cf9))
                if cf9:
                    failed9.add("coingecko")
            return cgp9

        def ident(s9, ex):
            return candles.same_coin("upbit", ex, s9, now=now, fetch=False)

        vok9 = self.__dict__.setdefault("_alt_vok", {})

        def ref(s9):
            cid9 = ids9.get(s9)
            if cid9 and cg_px().get(cid9):
                return cgp9[cid9], f"코인게코 {cid9}"
            pv9 = self.ex_usd.get(f"upbit:{s9}")
            return (float(pv9), "직전 값") if pv9 and vok9.get(s9) else None
        notes9 = {}
        out9 = pricing.pick_global_usd(syms, book, ident=ident, ref=ref, notes=notes9,
                                       failed=lambda ex: ex in failed9 or (ex == "binance" and not bn))
        miss9 = [x for x in syms if x not in out9 and ids9.get(x)]
        if miss9 and "_done" not in cgp9:
            cgp9["_done"] = True
            cf9 = []
            cgp9.update(candles.cg_simple_usd([i9 for i9 in ids9.values() if i9], now=now, fail=cf9, keyed=True))
            if cf9:
                failed9.add("coingecko")
        elif miss9 and "coingecko" in failed9 and _cg_key_set():
            need9 = sorted({ids9[s9] for s9 in miss9 if not cgp9.get(ids9[s9])})
            if need9:
                cgp9.update(candles.cg_simple_usd(need9, now=now, keyed=True, key_only=True))
        for s9 in miss9:
            v9 = cg_px().get(ids9[s9])
            if v9:
                out9[s9] = (float(v9), f"coingecko {ids9[s9]}")
        for s9 in out9:
            ex9 = out9[s9][1].split(" ", 1)[0]
            vok9[s9] = ex9 == "coingecko" or (ex9 in ("binance", "bybit") and ident(s9, ex9)[0] is True)
        src9 = self.__dict__.setdefault("upbit_alt_src", {})
        nm9 = {"binance": "바이낸스", "bybit": "바이빗", "coingecko": "코인게코"}
        for s9, (v9, why9) in out9.items():
            lab9 = nm9.get(why9.split(" ", 1)[0], why9.split(" ", 1)[0]) + " · 업비트 비원화"
            src9[s9] = lab9 + (f" (제외: {'; '.join(notes9[s9])[:120]})" if notes9.get(s9) else "")
        alt9 = self.__dict__.setdefault("ex_alt_src", {})
        for s9 in [x for x in syms if x not in out9 and alt9.get(x)]:
            if _alt_src_stale("upbit", s9, alt9[s9], cid=ids9.get(s9), now=now):
                self.upbit_alt_why[s9] = f"직전 값 출처({alt9[s9]}) = 지금 매핑으로 다른 코인 — 지움"
                src9.pop(s9, None)
                self.ex_usd.pop(f"upbit:{s9}", None)
                self.ex_ts.pop(f"upbit:{s9}", None)
                alt9.pop(s9, None)
                vok9.pop(s9, None)
        self.upbit_alt_miss = {s9 for s9 in syms if s9 not in out9} if not failed9 and bn else set()
        for s9 in self.upbit_alt_miss:
            self.upbit_alt_why[s9] = "바이낸스·바이빗·코인게코 시세 없음" + (f" (제외: {'; '.join(notes9[s9])[:120]})" if notes9.get(s9) else "")
            src9.pop(s9, None)
            self.ex_usd.pop(f"upbit:{s9}", None)
            self.ex_ts.pop(f"upbit:{s9}", None)
            self.__dict__.setdefault("ex_alt_src", {}).pop(s9, None)
            vok9.pop(s9, None)
        return out9

    def _hl_px(self, now):
        import hl_spot
        hl9 = hl_spot.fetch_book(now)
        cache9 = self.__dict__.setdefault("_alt_books", {})

        def book(ex):
            if ex == "binance":
                b9 = getattr(self, "_bn_book", None)
                if b9 and now - b9[0] < 300 and b9[1]:
                    return b9[1]
            c9 = cache9.get(ex)
            if c9 and now - c9[0] < 120:
                return c9[1]
            if ex in self.ex_want and ex != "hyperliquid":
                d9 = {k9.split(":", 1)[1]: v9 for k9, v9 in self.ex_usd.items()
                      if k9.startswith(ex + ":") and now - float(self.ex_ts.get(k9) or 0) < 300}
                if d9:
                    return d9
            try:
                d9 = (pricing.binance_spot_usdt() if ex == "binance" else pricing.ex_spot_usd(ex, self.rate)) or {}
            except Exception as e9:
                calcguard.swallowed("view_spot:Spot._hl_px.book", e9)
                log.warning("Hyperliquid 같은 코인 시세: %s 벌크 조회 실패(다음): %s", ex, common.safe_err(e9)[:120])
                d9 = {}
            cache9[ex] = (now, d9)
            return d9
        cg9 = {}

        def cg(_ids):
            if "_d" not in cg9:
                cg9["_d"] = candles.cg_simple_usd([m9[1] for m9 in hl_spot.SAME_COIN.values() if m9[1]], now=now, keyed=True)
            return cg9["_d"]
        notes9 = {}
        out9 = hl_spot.venue_prices(hl9, book, cg, notes9)
        nm9 = {"face": "액면", "binance": "바이낸스", "bybit": "바이빗", "coingecko": "코인게코"}
        self.hl_src = {n9: ((nm9.get(src9, src9) + " · Hyperliquid 보유") if src9 != "hyperliquid" else "Hyperliquid 현물 중간가")
                       + (f" (제외: {'; '.join(notes9[n9])[:120]})" if notes9.get(n9) else "")
                       for n9, (_v9, src9) in out9.items()}
        return {n9: v9 for n9, (v9, _s9) in out9.items()}

    def tick(self):
        now = time.time()
        self._laps, self._lap_at = [], now
        try:
            rate = pricing.usdt_krw_ask()
        except Exception as e:
            calcguard.swallowed("view_spot:Spot.tick", e)
            log.warning("업비트 환율 조회 실패(마지막 값 유지): %s", e)
            rate = None
        if rate:
            self.rate = rate
            self.rate_ts = now
        if now - self._fx_at > 3600:
            fx = pricing.fx_basis_krw_per_usd()
            if fx:
                self.fx_basis = fx
                self.fx_basis_ts = now
                self._fx_at = now
        if now - self._mk_at > 3600:
            try:
                mk9 = pricing.upbit_markets()
                self.upbit_krw = mk9.get("KRW", set())
                alt9 = {}
                for q9 in ("BTC", "USDT"):
                    for b9 in mk9.get(q9, set()):
                        if b9 not in self.upbit_krw:
                            alt9.setdefault(b9, set()).add(q9)
                self.upbit_alt = alt9
                self._mk_at = now
            except Exception as _cg9:
                calcguard.swallowed("view_spot:Spot.tick", _cg9)
                pass
        self._lap("환율·마켓")
        with self.lock:
            syms = sorted(self.syms)
        if syms:
            usd = {}
            try:
                bn = pricing.binance_spot_usdt()
            except Exception as _cg9:
                calcguard.swallowed("view_spot:Spot.tick", _cg9)
                bn = {}
            if bn:
                self._bn_book = (now, bn)
            for s in syms:
                if s in ("USDT", "USDC", "DAI", "BUSD"):
                    usd[s] = 1.0
                elif pricing.NATIVE_EX_TICKER.get(s, s) in bn:
                    usd[s] = bn[pricing.NATIVE_EX_TICKER.get(s, s)]
            up_syms = [s for s in syms if s in self.upbit_krw]
            if up_syms and self.rate:
                krw = pricing.upbit_spot_krw(up_syms)
                for s, v in krw.items():
                    if s not in usd and s not in pricing.NATIVE_EX_TICKER:
                        usd[s] = v / self.rate
                    self.ex_usd[f"upbit:{s}"] = v / self.rate
                    self.ex_ts[f"upbit:{s}"] = int(now)
                    self.ex_alt_src.pop(s, None)
            alt_syms = [s for s in syms if s in self.upbit_alt and s not in self.upbit_krw]
            if alt_syms:
                for s, (v, why) in self._upbit_alt_global(alt_syms, bn, now).items():
                    self.ex_usd[f"upbit:{s}"] = v
                    self.ex_ts[f"upbit:{s}"] = int(now)
                    self.upbit_alt_why[s] = why
                    self.ex_alt_src[s] = _alt_src_of(why)
            self.usd.update(usd)
            for s in usd:
                self.usd_ts[s] = int(now)
        self._lap("글로벌·업비트")
        if self.upbit_krw:
            with self.lock:
                self._ex_done.add("upbit")
        with self.lock:
            exs = sorted(self.ex_want)
        for ex1 in exs:
            if ex1 == "upbit":
                continue
            if now - self._ex_at.get(ex1, 0) < 120:
                continue
            self._ex_at[ex1] = now
            try:
                got1 = self._hl_px(now) if ex1 == "hyperliquid" else pricing.ex_spot_usd(ex1, self.rate)
            except Exception as e1:
                calcguard.swallowed("view_spot:Spot.tick", e1)
                log.warning("%s 거래소 시세 조회 실패: %s", ex1, e1)
                continue
            for s1, v1 in got1.items():
                self.ex_usd[f"{ex1}:{s1}"] = v1
                self.ex_ts[f"{ex1}:{s1}"] = int(now)
            self.ex_dead[ex1] = int(pricing.EX_DEAD.get(ex1) or 0)
            self.ex_dead_syms[ex1] = set(pricing.EX_DEAD_SYMS.get(ex1) or ())
            old1 = [k1 for k1 in self.ex_usd if k1.startswith(ex1 + ":") and k1[len(ex1) + 1:] not in got1]
            if got1 and len(got1) * 2 >= len(got1) + len(old1):
                for k1 in old1:
                    self.ex_usd.pop(k1, None)
                    self.ex_ts.pop(k1, None)
            if got1:
                with self.lock:
                    self._ex_done.add(ex1)
        self._lap("거래소별")
        if now >= self._gt_backoff_until:
            self._gt_at = now
            self._gt_round(now)
        if now - self._ds_at > self.DS_EVERY and now >= self._ds_backoff_until:
            self._ds_at = now
            self._ds_round(now)
        self._lap("DEX(게코)")
        creds = self._okx_creds()
        if creds and now - self._okx_at > 60:
            self._okx_at = now
            with self.lock:
                targets = set(self.okx_pairs)
                if not self._okx_fullscan_done:
                    targets |= set(self.token_pairs)
            if targets:
                got2 = pricing.okx_dex_prices(creds, sorted(targets))
                for (ch, ca), px in got2.items():
                    self.dex_usd[f"{ch}:{ca}"] = px
                    self.dex_ts[f"{ch}:{ca}"] = int(now)
                    self.dex_src[f"{ch}:{ca}"] = "okx"
                    self._alt_note(f"{ch}:{ca}", "okx", px, now)
                if not self._okx_fullscan_done:
                    self._okx_fullscan_tries += 1
                    if got2 or self._okx_fullscan_tries >= 3:
                        self._okx_fullscan_done = True
        self._lap("OKX DEX")
        tick_sec = time.time() - now
        if tick_sec > self.SLOW_TICK_SEC:
            log.warning("시세 갱신 한 바퀴 %.0f초(>%d초) — 단계별: %s", tick_sec, self.SLOW_TICK_SEC,
                        " · ".join(f"{n9} {d9:.0f}초" for n9, d9 in self._laps))
        self.updated = int(now)
        for k9 in [k9 for k9 in list(self.guarded) if now - self._guard_seen.get(k9, 0) > 6 * 3600]:
            self.guarded.pop(k9, None)
            self._guard_logged.pop(k9, None)
        common.atomic_write_json(SPOT_PATH, {
            "guarded": dict(self.guarded),
            "gt": dict(self.gt_stat),
            "ds": dict(self.ds_stat),
            "dex_src": self.dex_src,
            "meta": dict(self.token_meta),
            "proof_div": list(self.proof_div),
            "ex_dead": dict(self.ex_dead),
            "tick": {"sec": round(tick_sec, 1), "slowest": max(self._laps, key=lambda x9: x9[1])[0] if self._laps else None},
            "usd": self.usd, "usd_ts": self.usd_ts, "rate": self.rate,
            "rate_ts": int(self.rate_ts) if self.rate else None,
            "dex_usd": self.dex_usd, "dex_ts": self.dex_ts,
            "dex_res": self.dex_res, "dex_res_ts": self.dex_res_ts,
            "ex_usd": self.ex_usd, "ex_ts": self.ex_ts,
            "ex_alt_src": dict(self.ex_alt_src),
            "fx_basis": self.fx_basis, "fx_basis_ts": int(self.fx_basis_ts) if self.fx_basis else None,
            "upbit_krw": sorted(self.upbit_krw),
            "upbit_alt": {k: sorted(v) for k, v in self.upbit_alt.items()}, "updated": self.updated,
            "want": {"ex": sorted(self.ex_want), "dex": len(self.token_pairs)}})
