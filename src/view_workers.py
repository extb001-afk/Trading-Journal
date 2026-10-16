from __future__ import annotations
import common
import db as dbm
import depaddr
import flow_trace
import json
import lpchain
import lpdec
import lpsol
import netpace
import os
import pricing
import rabby
import sale_match
import time
import urllib.request
import xchain_match
from view_common import LP_CLOSED_SEC
from view_common import LP_NEW_POLL_SEC
from view_common import LP_OPEN_SEC
from view_common import LP_POS_PATH
from view_common import RABBY_PATH
from view_common import SALE_PATH
from view_common import SALE_SEC
from view_common import STABLE_GROUPS
import logging
import calcguard

log = logging.getLogger('tj-web')


class WorkersMixin:

    def _rabby_worker(self):
        s = rabby.settings(self.cfg)
        time.sleep(s["first_delay_sec"])
        while True:
            try:
                s = rabby.settings(self.cfg)
                res = rabby.refresh_once(self.cfg, RABBY_PATH, log=log.info, bot_usd=self.__dict__.get("_bot_wallet_usd"))
                if res == "ok":
                    self.soft_invalidate()
            except (Exception, SystemExit) as e:
                calcguard.swallowed("view_workers:WorkersMixin._rabby_worker", e)
                log.warning("rabby-worker 실패(다음 주기): %s", e)
            time.sleep(max(60.0, s["tick_sec"]))

    def _lp_worker(self):
        time.sleep(20)
        while True:
            try:
                self._lp_refresh_once()
            except (Exception, SystemExit) as e:
                calcguard.swallowed("view_workers:WorkersMixin._lp_worker", e)
                log.warning("lp-worker 실패(다음 주기): %s", e)
            end9 = time.time() + LP_OPEN_SEC
            while True:
                left9 = end9 - time.time()
                if left9 <= 0:
                    break
                time.sleep(min(LP_NEW_POLL_SEC, left9))
                try:
                    self._lp_refresh_new()
                except (Exception, SystemExit) as e:
                    calcguard.swallowed("view_workers:WorkersMixin._lp_worker", e)
                    log.warning("lp-worker 새 포지션 확인 실패(다음 확인): %s", e)

    def _lp_refresh_once(self, force: bool = False):
        prev = common.read_json(LP_POS_PATH, {}) or {}
        pos = dict(prev.get("positions") or {})
        nft_prev = dict(prev.get("wallet_nfts") or {})
        off9 = set(self.cfg.get("_disabled_chains") or ())
        off9.update(c for c, cc in (self.cfg.get("chains") or {}).items() if isinstance(cc, dict) and not common.chain_enabled(c, cc))
        with self._lp_lock:
            ledger_open = [t for t in self._lp_targets if t[0] not in off9]
        targets = {t9[3]: (t9[0], t9[1], t9[2]) for t9 in ledger_open}
        extra = {t9[3]: (t9[4] if len(t9) > 4 else {}) for t9 in ledger_open}
        mgrs_all = lpdec.lp_managers(common.BASE_DIR)
        nfts = {k: v for k, v in nft_prev.items() if str(k).split(":", 1)[0] in off9}
        for w in self.cfg.get("wallets") or []:
            if not isinstance(w, dict) or w.get("type", "evm") == "sol":
                continue
            ch = w.get("chain"); wa = str(w.get("address") or "").lower()
            if ch in off9 or ch not in mgrs_all or not wa:
                continue
            lst = lpchain.list_wallet_positions(self.cfg, ch, wa)
            key9 = f"{ch}:{wa}"
            if lst is None:
                lst = [tuple(x) for x in (nft_prev.get(key9) or [])]
            nfts[key9] = [list(x) for x in lst]
            for mgr, tid in lst:
                targets.setdefault(f"lp:{ch}:{mgr}:{tid}", (ch, mgr, tid))
            time.sleep(0.3)
        now9 = int(time.time())
        ledger_locs = {t9[3] for t9 in ledger_open}
        n_ok = n_try = 0
        for loc, (ch, mgr, tid) in sorted(targets.items()):
            old = pos.get(loc) or {}
            closed_known = old and int(old.get("liquidity") or 0) <= 0 and loc not in ledger_locs
            if not force and closed_known and now9 - int(old.get("t") or 0) < LP_CLOSED_SEC:
                continue
            n_try += 1
            ex9 = extra.get(loc) or {}
            d9 = self._lp_read_one(ch, mgr, tid, ex9)
            if d9:
                if not d9.get("feesOk", True) and old:
                    d9["fees0"], d9["fees1"] = old.get("fees0"), old.get("fees1")
                    d9["feesStale"] = True
                d9["t"] = now9
                d9.setdefault("chain", ch)
                if isinstance(tid, int):
                    d9["owner"] = lpchain.owner_of(self.cfg, ch, mgr, tid)
                if ex9.get("stake") and d9.get("rewardAmount") is None and old.get("rewardAmount") is not None:
                    d9["rewardAmount"], d9["rewardToken"], d9["rewardSym"] = (old.get("rewardAmount"), old.get("rewardToken"),
                                                                              old.get("rewardSym"))
                pos[loc] = d9
                n_ok += 1
            time.sleep(0.2)
        for loc in list(pos):
            ch9 = str((pos[loc] or {}).get("chain") or (loc.split(":")[1] if ":" in loc else ""))
            if ch9 in off9:
                continue
            if loc not in targets and now9 - int(pos[loc].get("t") or 0) > 7 * 86400:
                pos.pop(loc, None)
        common.atomic_write_json(LP_POS_PATH, {"updated": now9, "positions": pos, "wallet_nfts": nfts,
                                               "targets": sorted(targets)})
        self.soft_invalidate(kick=False)
        self._lp_known = set(pos)
        log.info("lp-worker: %d/%d 포지션 온체인 갱신 (대상 %d)", n_ok, n_try, len(targets))
        return n_ok, n_try

    def _lp_refresh_new(self):
        off9 = set(self.cfg.get("_disabled_chains") or ())
        off9.update(c for c, cc in (self.cfg.get("chains") or {}).items() if isinstance(cc, dict) and not common.chain_enabled(c, cc))
        with self._lp_lock:
            ledger_open = [t for t in self._lp_targets if t[0] not in off9]
        tried9 = self.__dict__.setdefault("_lp_new_tried", set())
        known9 = self.__dict__.get("_lp_known")
        cand = [t9 for t9 in ledger_open if t9[3] not in tried9 and (known9 is None or t9[3] not in known9)]
        if not cand:
            return 0, 0
        prev = common.read_json(LP_POS_PATH, {}) or {}
        pos = dict(prev.get("positions") or {})
        cand = [t9 for t9 in cand if t9[3] not in pos]
        if not cand:
            self._lp_known = set(pos)
            return 0, 0
        now9 = int(time.time())
        n_ok = 0
        for t9 in cand:
            ch, mgr, tid, loc = t9[0], t9[1], t9[2], t9[3]
            tried9.add(loc)
            d9 = self._lp_read_one(ch, mgr, tid, (t9[4] if len(t9) > 4 else {}) or {})
            if d9:
                d9["t"] = now9
                d9.setdefault("chain", ch)
                if isinstance(tid, int):
                    d9["owner"] = lpchain.owner_of(self.cfg, ch, mgr, tid)
                pos[loc] = d9
                n_ok += 1
            time.sleep(0.2)
        if n_ok:
            out9 = dict(prev)
            out9["positions"] = pos
            common.atomic_write_json(LP_POS_PATH, out9)
            self.soft_invalidate(kick=False)
        self._lp_known = set(pos)
        log.info("lp-worker: 새 포지션 %d/%d 바로 평가", n_ok, len(cand))
        return n_ok, len(cand)

    def _lp_read_one(self, ch: str, mgr: str, tid, ex9: dict) -> dict:
        proto = (ex9 or {}).get("proto")
        if ch == "sol":
            sol9 = self.cfg.get("sol") or {}
            urls = [u for u in [sol9.get("rpc_fallback")] + list(sol9.get("rpc_fallbacks") or []) if u]
            meta = dict(getattr(self, "_lp_solmeta", {}) or {})
            meta.setdefault(lpsol.WSOL, {"symbol": "SOL", "decimals": 9})
            return lpsol.read_dlmm_position(urls, str(tid), meta.get)
        if proto == "v2":
            return lpchain.read_v2(self.cfg, ch, mgr, int(ex9.get("units") or 0), ex9.get("wallet"), ex9.get("stake"))
        if not isinstance(tid, int):
            return {}
        d9 = lpchain.read_position(self.cfg, ch, mgr, tid)
        if d9 and ex9.get("stake"):
            d9.update(lpchain.read_stake_reward(self.cfg, ch, ex9["stake"], tid, ex9.get("wallet")))
        return d9

    def _xchain_worker(self):
        xc = self.cfg.get("xchain") or {}
        if xc.get("trace") is False:
            return
        time.sleep(90)
        px = None
        per = max(1, int(xc.get("per_cycle") or 3))
        cap = max(1, int(xc.get("cycle_calls") or 60))
        while True:
            try:
                used, hit = 0, False
                for _i in range(per):
                    with self._xc_lock:
                        todo = list(self._xc_pending[:1])
                    if not todo:
                        break
                    if px is None:
                        px = pricing.PxCache(os.path.join(common.STATE_DIR, "xchain_px_cache.json"))
                    res = xchain_match.run_once(self.cfg, common.STATE_DIR, common.DB_PATH, common.BASE_DIR, todo, limit=1,
                                                budget=int(xc.get("budget") or 300), log=log.info, px=px,
                                                skip_gids=getattr(self, "_risk_quarantined", None))
                    px.flush()
                    with self._xc_lock:
                        self._xc_pending = [c for c in self._xc_pending if c["key"] != todo[0]["key"]]
                    log.info("xchain-worker: %s", res)
                    hit = hit or any(st in ("ok", "link") for _k, st, _c in res)
                    used += sum(int(c9 or 0) for _k, _st, c9 in res)
                    if used >= cap or any(st == "paused" for _k, st, _c in res):
                        break
                if hit:
                    self.soft_invalidate()
            except (Exception, SystemExit) as e:
                calcguard.swallowed("view_workers:WorkersMixin._xchain_worker", e)
                log.warning("xchain-worker 실패(다음 주기): %s", e)
            time.sleep(float(xc.get("interval_sec") or 60))

    def _flow_worker(self):
        ft = self.cfg.get("flow_trace") or {}
        if ft.get("trace") is False:
            return
        time.sleep(120)
        px = None
        cap = max(1, int(ft.get("cycle_calls") or 40))
        while True:
            try:
                with self._flow_lock:
                    todo = list(self._flow_pending[:1])
                if todo:
                    if px is None:
                        px = pricing.PxCache(os.path.join(common.STATE_DIR, "flow_px_cache.json"))
                    sym_of = self._flow_sym_of()
                    res = flow_trace.run_once(self.cfg, common.STATE_DIR, todo, budget=cap, log=log.info, px=px, sym_of=sym_of)
                    px.flush()
                    with self._flow_lock:
                        self._flow_pending = [c for c in self._flow_pending if c["dest"] != todo[0]["dest"]]
                    log.info("flow-worker: %s", res)
                    if any(st in ("ok", "partial") for _a, st, _c in res):
                        self.soft_invalidate()
            except (Exception, SystemExit) as e:
                calcguard.swallowed("view_workers:WorkersMixin._flow_worker", e)
                log.warning("flow-worker 실패(다음 주기): %s", e)
            time.sleep(float(ft.get("interval_sec") or 60))

    def _flow_sym_of(self):
        try:
            conn = dbm.open_db(common.DB_PATH, readonly=True)
        except Exception as _cg9:
            calcguard.swallowed("view_workers:WorkersMixin._flow_sym_of", _cg9)
            return lambda ch, tok: None
        try:
            m = {}
            for r in conn.execute("SELECT a.chain, a.address, a.symbol, g.name AS gname FROM assets a LEFT JOIN asset_groups g"
                                  " ON g.group_id=a.group_id WHERE a.address IS NOT NULL").fetchall():
                m[(r["chain"], xchain_match.norm(r["address"]))] = self._gsym(r)
        except Exception as _cg9:
            calcguard.swallowed("view_workers:WorkersMixin._flow_sym_of", _cg9)
            m = {}
        finally:
            conn.close()
        return lambda ch, tok: m.get((ch, xchain_match.norm(tok)))

    def _origin_net_hints(self, txs) -> dict:
        out = {}
        want = {str(t).lower() for t in txs}
        if not want:
            return out
        try:
            conn = dbm.open_db(common.DB_PATH, readonly=True)
        except Exception as _cg9:
            calcguard.swallowed("view_workers:WorkersMixin._origin_net_hints", _cg9)
            return out
        try:
            for r9 in conn.execute("SELECT payload FROM raw_ex WHERE kind='deposit'"):
                try:
                    p9 = json.loads(r9["payload"])
                except (json.JSONDecodeError, TypeError):
                    continue
                t9 = str(p9.get("txid") or "").lower()
                if t9 not in want:
                    continue
                net9 = str(p9.get("net_type") or p9.get("network") or "").strip()
                if net9:
                    out[t9] = (net9, depaddr.chain_of(net9, p9.get("currency")))
        finally:
            conn.close()
        return out

    def _origin_chains(self) -> list:
        return [(n, str(c.get("blockscout")).rstrip("/")) for n, c in (self.cfg.get("chains") or {}).items()
                if isinstance(c, dict) and c.get("blockscout") and common.chain_discovery(n, c) != "rpc"]

    def _origin_chain_names(self) -> list:
        return [n for n, _b in self._origin_chains()]

    def _origin_worker(self):
        path = os.path.join(common.STATE_DIR, "tx_origin_cache.json")
        chains = self._origin_chains()
        while True:
            time.sleep(60)
            try:
                with self._origin_lock:
                    pending9 = sorted(self._origin_pending)
                off9 = set(self.cfg.get("_disabled_chains") or ())
                hints9 = self._origin_net_hints(pending9) if (off9 and pending9) else {}
                todo = [tx for tx in pending9 if hints9.get(str(tx).lower(), (None, None))[1] not in off9][:5] if off9 else pending9[:5]
                if not todo:
                    continue
                cache = common.read_json(path, {})
                now9 = int(time.time())
                hints9 = self._origin_net_hints(todo) if not off9 else hints9
                for tx in todo:
                    ent = cache.get(tx)
                    net9, ch9 = hints9.get(tx, (None, None))
                    names9 = [n for n, _b in chains]
                    if ent and (ent.get("from") or ent.get("na")):
                        continue
                    if net9 and ch9 not in names9:
                        cache[tx] = {"chain": None, "from": None, "to": None, "t": now9, "na": net9}
                        continue
                    if ent and now9 - int(ent.get("t") or 0) < 86400:
                        continue
                    found = None
                    for name, base in ([(n, b) for n, b in chains if n == ch9] if ch9 else chains):
                        url = f"{base}/api/v2/transactions/{tx}"
                        try:
                            req = urllib.request.Request(url, headers={"User-Agent": common.ua_for(url, "tj-bot/0.1 (personal trade journal)"),
                                                                       "Accept": "application/json"})
                            netpace.wait(url)
                            try:
                                with urllib.request.urlopen(req, timeout=8) as r9:
                                    d9 = json.loads(common.read_capped(r9).decode())
                            except urllib.error.HTTPError as he9:
                                netpace.note_error(url, he9)
                                raise
                            if isinstance(d9, dict) and d9.get("hash"):
                                f9 = d9.get("from") or {}; t9 = d9.get("to") or {}
                                found = {"chain": name, "from": str(f9.get("hash") or "").lower() or None,
                                         "to": str(t9.get("hash") or "").lower() or None, "t": now9}
                                break
                        except Exception as _cg9:
                            calcguard.swallowed("view_workers:WorkersMixin._origin_worker", _cg9)
                            continue
                    if found:
                        cache[tx] = found
                    else:
                        n9 = int((ent or {}).get("n") or (2 if ent and "n" not in ent else 0)) + (0 if (off9 and not ch9) else 1)
                        cache[tx] = {"chain": None, "from": None, "to": None, "t": now9, "n": n9}
                        if n9 >= 3:
                            cache[tx]["na"] = "notfound"
                common.atomic_write_json(path, cache)
                with self._origin_lock:
                    self._origin_pending -= set(todo)
                self.soft_invalidate()
            except (Exception, SystemExit) as e:
                calcguard.swallowed("view_workers:WorkersMixin._origin_worker", e)
                log.warning("origin-worker 실패(다음 주기): %s", e)

    def _sale_worker(self):
        time.sleep(120)
        while True:
            try:
                self._sale_refresh_once()
            except (Exception, SystemExit) as e:
                calcguard.swallowed("view_workers:WorkersMixin._sale_worker", e)
                log.warning("sale-worker 실패(다음 주기): %s", e)
            time.sleep(SALE_SEC)

    def _sale_refresh_once(self, budget: int = 4, get=None, now=None, gap: float = 3.0):
        seed = sale_match.load_seed()
        bases = {n: str(c.get("blockscout")).rstrip("/") for n, c in (self.cfg.get("chains") or {}).items()
                 if isinstance(c, dict) and c.get("blockscout") and common.chain_discovery(n, c) != "rpc" and n in seed["chains"]}
        if not bases:
            return 0
        now = int(now or time.time())
        cache = common.read_json(SALE_PATH, {}) or {}
        owners = cache.setdefault("owners", {})
        if not self._sale_queue or now - self._sale_queue_t > 6 * 3600:
            wallets = {}
            for w in self.cfg.get("wallets") or []:
                if isinstance(w, dict) and w.get("type", "evm") != "sol" and w.get("chain") in bases:
                    a9 = str(w.get("address") or "").lower()
                    if a9:
                        wallets.setdefault(w["chain"], set()).add(a9)
            oc9 = common.read_json(os.path.join(common.STATE_DIR, "tx_origin_cache.json"), {}) or {}
            conn = dbm.open_db(common.DB_PATH, readonly=True)
            try:
                self._sale_queue = sale_match.owner_queue(conn, sorted(bases), wallets, oc9, prio_syms=set(self._sale_prio))
                cache["heuristic"] = sale_match.heuristic_scan(conn, set(STABLE_GROUPS) | {"USDC", "USDT", "DAI"})[:50]
            finally:
                conn.close()
            self._sale_queue_t = now
        base_get = get or sale_match.http_get_json

        def slow_get(u):
            time.sleep(gap)
            return base_get(u)
        mine9 = {str(w.get("address") or "").lower() for w in (self.cfg.get("wallets") or []) if isinstance(w, dict)}
        blk9 = self.__dict__.setdefault("_sale_blocked", {})
        todo = [(c9, a9) for c9, a9 in self._sale_queue if c9 in bases and blk9.get(c9, 0) <= now
                and sale_match.needs_refresh(owners.get(f"{c9}:{a9}"), now, hot=a9 in mine9)][:budget]
        changed = False
        for c9, a9 in todo:
            if blk9.get(c9, 0) > now:
                continue
            try:
                rec = sale_match.fetch_owner(slow_get, bases[c9], c9, a9, seed, now)
            except urllib.error.HTTPError as e:
                if e.code != 403:
                    log.info("sale-worker: %s %s 조회 보류(%s) — 다음 주기", c9, a9[:10], str(e)[:80])
                    break
                blk9[c9] = now + 6 * 3600
                log.info("sale-worker: %s 블록스카웃 접속 차단(403) — 6시간 동안 이 체인 건너뜀", c9)
                continue
            except OSError as e:
                log.info("sale-worker: %s %s 조회 보류(%s) — 다음 주기", c9, a9[:10], str(e)[:80])
                break
            except Exception as e:
                calcguard.swallowed("view_workers:WorkersMixin._sale_refresh_once", e)
                rec = {"t": now, "chain": c9, "owner": a9, "err": common.safe_err(e)[:160], "bids": [], "auctions": {}}
            prev = owners.get(f"{c9}:{a9}") or {}
            if rec.get("err") and prev.get("bids"):
                prev["t"], prev["err_last"] = now, rec["err"]
                continue
            changed = changed or bool(rec.get("bids")) or bool(prev.get("bids"))
            owners[f"{c9}:{a9}"] = rec
        cache["updated"] = now
        common.atomic_write_json(SALE_PATH, cache)
        if changed:
            self.soft_invalidate()
        return len(todo)
