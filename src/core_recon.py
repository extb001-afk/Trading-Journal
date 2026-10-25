import bf_engine
import chain_event
import chain_registry
import chain_state
import chaincatalog, config, envfile, evm_reorg, logs, paths, statefile
import discopen
import fsio
import json
import os
import token_tables
import recon
import recon_adj
import spamguard
import threading
import time
import token_discovery
from core_common import CLASSIFIER_VER
from core_common import dm
import logging
import calcguard  # noqa: E402

log = logging.getLogger('tj-core')


class ReconMixin:

    def _sol_rpc_url(self):
        key = os.environ.get("TJ_HELIUS_KEY", "")
        if not key:
            key = envfile.read_env_file().get("TJ_HELIUS_KEY", "")
        sol = self.cfg.get("sol", {})
        if sol.get("rpc") == "helius" and key:
            return f"https://mainnet.helius-rpc.com/?api-key={key}"
        return sol.get("rpc") or sol.get("rpc_fallback")

    @staticmethod
    def _synced(cur: dict, max_age: float = 600, key: str = "_synced_at") -> bool:
        try:
            return time.time() - float(cur.get(key) or 0) < max_age
        except (TypeError, ValueError):
            return False

    def _scope_ready(self, scope: str) -> bool:
        sd = paths.STATE_DIR
        if chain_registry.is_nonevm(scope):
            return chain_state.ChainState(scope, sd).ready(self.chain_owners.get(scope, set()))
        if scope == "sol":
            cur = statefile.read_json(os.path.join(sd, "cursor_sol.json"), {})
            return self._synced(cur) and all(o in cur for o in self.sol_wallets)
        if scope == "bsc":
            cur = statefile.read_json(os.path.join(sd, "cursor_bsc.json"), {})
            head, frm = int(cur.get("head") or 0), int(cur.get("from_block") or 0)
            return self._synced(cur) and head > 0 and frm > 0 and head - frm < 3000
        cur = statefile.read_json(os.path.join(sd, f"cursor_evm_{scope}.json"), {})
        pend = statefile.read_json(os.path.join(sd, f"pending_detail_{scope}.json"), {})
        enr = statefile.read_json(os.path.join(sd, f"enrich_{scope}.json"), {})
        return self._synced(cur) and not pend and not enr and not evm_reorg.held(cur) \
            and all(w in cur for w in self.my_wallets.get(scope, set()))

    def _scope_ready_tok(self, scope: str) -> bool:
        if scope in ("sol", "bsc"):
            return False
        if self._scope_ready(scope):
            return True
        sd = paths.STATE_DIR
        cur = statefile.read_json(os.path.join(sd, f"cursor_evm_{scope}.json"), {})
        if evm_reorg.held(cur) or not (isinstance(cur.get("_ext_internal_pending"), dict) or isinstance(cur.get("_ext_internal_lag"), dict)):
            return False
        pend = statefile.read_json(os.path.join(sd, f"pending_detail_{scope}.json"), {})
        return self._synced(cur, key="_synced_tok_at") and not pend \
            and all(w in cur for w in self.my_wallets.get(scope, set()))

    NATX_STALL_HOURS = 24.0

    def _scope_ready_natx(self, scope: str) -> bool:
        if scope in ("sol", "bsc"):
            return False
        cc = (self.cfg.get("chains") or {}).get(scope) or {}
        if config.chain_discovery(scope, cc) == "rpc":
            return False
        try:
            hrs = float(self.cfg.get("recon_native_stall_hours", self.NATX_STALL_HOURS))
        except (TypeError, ValueError):
            hrs = self.NATX_STALL_HOURS
        if hrs <= 0 or self._scope_ready(scope) or not self._scope_ready_tok(scope):
            return False
        cur = statefile.read_json(paths.state(f"cursor_evm_{scope}.json"), {})
        since = cur.get("_int_lag_since")
        if not isinstance(cur.get("_ext_internal_lag"), dict) or not isinstance(since, int) or isinstance(since, bool):
            return False
        return time.time() - since >= hrs * 3600

    def _wrecon_times(self, chain: str) -> dict:
        out = {}
        done = {}
        for k, v in self.conn.execute("SELECT k, v FROM meta WHERE k LIKE ?", (f"wrecon_done:{chain}:%",)).fetchall():
            try:
                done[k.split(":", 2)[2].lower()] = int(float(v))
            except (TypeError, ValueError, IndexError):
                continue
        for w, t in done.items():
            out[w] = (t, t, False)
        for k, v in self.conn.execute("SELECT k, v FROM meta WHERE k LIKE ?", (f"wrecon_tok:{chain}:%",)).fetchall():
            if not k.startswith(f"wrecon_tok:{chain}:"):
                continue
            try:
                w = k.split(":", 2)[2].lower()
                out[w] = (int(float(v)), done.get(w), True)
            except (TypeError, ValueError, IndexError):
                continue
        return out

    def _posted_sums(self, chain: str) -> dict:
        out = {}
        for r in self.conn.execute(
                "SELECT p.asset_id, p.qty_base, p.location FROM postings p JOIN assets a"
                " ON a.asset_id = p.asset_id WHERE a.chain=?"
                " AND p.location LIKE 'wallet:%'", (chain,)).fetchall():
            parts = (r["location"] or "").split(":")
            if len(parts) > 3:
                continue
            w = parts[2] if len(parts) >= 3 and parts[2] else None
            key = (w, r["asset_id"])
            out[key] = out.get(key, 0) + int(r["qty_base"])
        return out

    def _rpc_recon_reset(self):
        for c, cc in (self.cfg.get("chains") or {}).items():
            if config.chain_discovery(c, cc) != "rpc" or not self._meta_get(f"recon_done_{c}") \
                    or self._meta_get(f"recon_reset_rpc_{c}"):
                continue
            cur = statefile.read_json(paths.state(f"cursor_evm_{c}.json"), {})
            if not cur.get("_rpc_v") or not self._scope_ready(c):
                continue
            n_open = self.conn.execute("SELECT count(*) FROM postings WHERE source_kind='opening' AND source_id=?",
                                       (f"recon:{c}",)).fetchone()[0]
            if n_open:
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (f"recon_reset_rpc_{c}", "skipped_existing_opening"))
                self.conn.commit()
                log.warning("%s RPC 재대사 건너뜀 — 기존 opening %d건(수동 확인)", c, n_open)
                continue
            self.conn.execute("DELETE FROM meta WHERE k=?", (f"recon_done_{c}",))
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (f"recon_reset_rpc_{c}", str(int(time.time()))))
            self.conn.commit()
            self._recon_view_drop(c)
            log.warning("★%s RPC 백필 완료 → 탐색기 시절 대사 도장 해제, 온체인 잔고로 재대사★", c)

    def _nonevm_adapter(self, chain: str):
        cache = self.__dict__.setdefault("_nonevm_adapters", {})
        if chain not in cache:
            ad = None
            if chain_registry.available(chain):
                try:
                    import importlib
                    mk = getattr(importlib.import_module(chain_registry.spec(chain).module), "make_adapter", None)
                    ad = mk(self.cfg) if callable(mk) else None
                except Exception as e:   # noqa: BLE001 [fallback]
                    calcguard.swallowed("core_recon:ReconMixin._nonevm_adapter", e)
                    log.warning("[%s] 수집기 어댑터 만들기 실패(대사 없음): %s", chain, logs.safe_err(e)[:160])
                    ad = None
            cache[chain] = ad
        return cache[chain]

    SUI_GAP_CHECK_MAX = 8

    def _sui_recon_guard(self, chain: str):
        st9 = chain_state.ChainState(chain, paths.STATE_DIR)
        pend = sorted(str(s9) for s9 in st9.d["pending"])
        gaps = st9.unresolved_gaps()
        fp = json.dumps([pend, sorted([s9, str(r9.get("owner")), sorted(o9)] for s9, r9, o9 in gaps)])
        return pend, gaps, fp

    def _nonevm_fetch_plan(self, chain: str, wallets: list, mode: str = None, latest: bool = False):
        ad = self._nonevm_adapter(chain)
        if ad is None:
            raise RuntimeError(f"[{chain}] 수집기 어댑터 없음")
        toks = {}
        for r in self.conn.execute("SELECT DISTINCT p.location, a.address FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
                                   " WHERE a.chain=? AND a.kind='token' AND p.location LIKE ?", (chain, f"wallet:{chain}:%")).fetchall():
            w9 = chain_registry.parse_location(r["location"])[2]
            if w9 in wallets and r["address"]:
                toks.setdefault(w9, set()).add(r["address"])
        toks = {w: sorted(v) for w, v in toks.items()}
        ldec = {str(r["address"]).lower(): r["decimals"] for r in self.conn.execute(
            "SELECT address, decimals FROM assets WHERE chain=? AND kind='token' AND address IS NOT NULL", (chain,)).fetchall()}
        owners = set(wallets)
        sp = chain_registry.spec(chain)
        guard9 = self._sui_recon_guard(chain) if chain == "sui" and mode == "new" else None
        first9 = {w9 for w9 in owners if not self._meta_get(f"wrecon_done:{chain}:{w9}")} if chain == "sui" else set()

        def run():
            q_owners, held = set(owners), {}
            if guard9 is not None:
                if guard9[0]:
                    raise RuntimeError(f"[{chain}] 상세 대기 {len(guard9[0])}건 남음 — 지갑별 대사 보류")
                todo9 = [(sid9, ref9, w9) for sid9, ref9, eo9 in guard9[1] for w9 in sorted(owners) if w9 not in eo9]
                if len(todo9) > self.SUI_GAP_CHECK_MAX:
                    raise RuntimeError(f"[{chain}] 미해소 gap 확인 {len(todo9)}건(상한 넘음) — 지갑별 대사 보류")
                for sid9, ref9, w9 in todo9:
                    if w9 in held:
                        continue
                    try:
                        rec9 = ad.fetch_and_normalize(dict(ref9, stable_id=sid9, owner=w9, lane="history"), {w9})
                        if rec9 is None:
                            raise RuntimeError("gap 거래 상세 없음")
                        v9 = chain_event.validate(rec9)
                        hit9 = any(o9 == w9 and d9 for o9, _k9, d9, _m9 in v9["deltas"]) or any(p9 == w9 and f9 for p9, f9 in v9["fees"])
                    except Exception as _cg9:   # noqa: BLE001 [fallback]
                        calcguard.swallowed("core_recon:ReconMixin._nonevm_fetch_plan.run", _cg9)
                        hit9 = True
                    if hit9:
                        held[w9] = [sid9]
                q_owners -= set(held)
                if not q_owners:
                    raise RuntimeError(f"[{chain}] 미해소 gap 이 조회 지갑에 영향(또는 모름) — 지갑별 대사 보류")
            bal = ad.fetch_balances(set(q_owners), None, tokens=toks, **({"latest": True} if latest and chain == "btc" else {}))
            if (latest and chain == "ton" and isinstance(bal, dict) and bal.get("_complete") is False and bal.get("_why")
                    and set(bal["_why"]) <= {"wallet_lt_ahead", "jetton_lt_ahead", "pending_details"}):
                bal = dict(bal, _complete=True, _why=[])
            sm9 = {w9: sorted(map(str, ks9)) for w9, ks9 in ((bal.get("_sum_mismatch") if isinstance(bal, dict) else None) or {}).items()
                   if w9 in first9 and ks9} if first9 else {}
            if sm9:
                h9 = {w9: set(map(str, v9 or ())) for w9, v9 in (bal.get("_dec_unknown") or {}).items()}
                why9 = list(bal.get("_why") or [])
                bal = dict(bal, _complete=False, _why=why9 + ([chain_event.WHY_SUM_MISMATCH] if chain_event.WHY_SUM_MISMATCH not in why9 else []),
                           _dec_unknown={w9: sorted(h9.get(w9, set()) | set(sm9.get(w9, ()))) for w9 in set(h9) | set(sm9)})
            du9 = bal.get("_dec_unknown") if guard9 is not None and isinstance(bal, dict) and isinstance(bal.get("_dec_unknown"), dict) else {}
            if du9 and bal.get("_complete") is False and all(w9 in (chain_event.WHY_DEC_UNKNOWN, chain_event.WHY_SUM_MISMATCH) for w9 in bal.get("_why") or ()):
                for w9, ks9 in du9.items():
                    if w9 in q_owners:
                        held[w9] = sorted(map(str, ks9 or ()))
                q_owners -= set(du9)
                if not q_owners:
                    raise RuntimeError(f"[{chain}] 자릿수 미확인·합계 불일치 새 코인 — 지갑별 대사 보류")
                bal = dict(bal, _complete=True, _why=[], per_wallet={w9: v9 for w9, v9 in (bal.get("per_wallet") or {}).items() if w9 in q_owners})
            chk9 = chain_event.validate_balances(bal, chain, q_owners)
            if not chk9["ok"]:
                raise RuntimeError(f"[{chain}] 대사 결과 보류: " + " · ".join(chk9["why"][:3]))
            per = chk9["usable"]
            hint9 = bal.get("_meta") or {}
            bad9 = set()
            for w9 in list(per):
                wb9 = {}
                for k9, x9 in per[w9].items():
                    if k9[0] == "token":
                        a9 = str(k9[1]).lower()
                        h9 = hint9.get(k9[1])
                        if not (chain_event.valid_decimals(ldec.get(a9))
                                or chain_event.valid_decimals(h9[1] if isinstance(h9, (list, tuple)) and len(h9) >= 2 else None)):
                            if a9 not in ldec and not x9:
                                continue
                            bad9.add(str(k9[1]))
                            continue
                    wb9[k9] = x9
                per[w9] = wb9
            if bad9:
                raise RuntimeError(f"[{chain}] 자릿수 미확인 토큰 {len(bad9)}개 — 기초 잔고 대사 보류(18 로 짐작하지 않음)")
            out = {"per_wallet": per, "_meta": dict(bal.get("_meta") or {}), "_source": "rpc",
                   "_queried": {w: sorted(k[1] for k in wb if k[0] == "token") for w, wb in per.items()},
                   "_unobs": {w: sorted(map(str, v)) for w, v in (bal.get("_unobserved") or {}).items() if v}}
            if chain == "ton" and isinstance(bal.get("_jw_fp"), dict):
                out["_jw_fp"] = bal["_jw_fp"]
            if guard9 is not None:
                out["_sui_fp"] = guard9[2]
                if held:
                    out["_hold"] = held
            b9 = bal.get("_boundary") or {}
            if b9.get("kind") in ("height", "checkpoint") and sp.order_kind == b9.get("kind"):
                try:
                    out["_block"] = int(b9.get("value"))
                    if isinstance(b9.get("ts"), int) and not isinstance(b9.get("ts"), bool):
                        out["_block_ts"] = int(b9["ts"])
                except (TypeError, ValueError):
                    pass
            elif b9.get("kind") == "account_lt" == sp.order_kind and isinstance(b9.get("ts"), int) and not isinstance(b9.get("ts"), bool):
                out["_ts_cut"] = int(b9["ts"]) + 1
            return out
        return run

    def _recon_fetch(self, chain: str, kind: str, wallets: list) -> dict:
        return self._recon_fetch_plan(chain, kind, wallets)()

    def _recon_fetch_plan(self, chain: str, kind: str, wallets: list, mode: str = None, latest: bool = False):
        wallets = list(wallets)
        if kind == "nonevm":
            return self._nonevm_fetch_plan(chain, wallets, mode, latest=latest)
        if kind == "sol":
            url9 = self._sol_rpc_url()
            if latest:
                ln9, nat9 = self._prov_sol_lanes(url9)
                return lambda: self._prov_sol_fetch(ln9, wallets, native_url=nat9)
            return lambda: recon.fetch_sol_balances(url9, wallets)
        if kind == "bsc":
            cas = {}
            for r in self.conn.execute(
                    "SELECT address, symbol, decimals FROM assets"
                    " WHERE chain='bsc' AND kind='token'").fetchall():
                if r["address"]:
                    cas[r["address"]] = (r["symbol"], r["decimals"] if r["decimals"] is not None else self._meta_dec("bsc", r["address"]))
            rpcs8 = list(self.cfg["bsc"]["detail_rpcs"])
            if latest:
                own8 = self._disc_own_cas("bsc", wallets)
                sw8 = {str(k).lower(): str(v) for tab9 in (token_tables.STABLE_CAS, token_tables.JPY_STABLE_CAS) for k, v in (tab9.get("bsc") or {}).items()}
                st8 = self._recon_strict_fn("bsc")
                cas8 = {str(k).lower(): v for k, v in cas.items()}
                px8 = self._disc_prep("bsc", "bsc", wallets, st8) if mode != "fast" else None
                return lambda: self._prov_fastx("bsc", px8, lambda **x9: self._prov_fast_fetch(
                    "bsc", rpcs8, wallets, cas8, discover_url=None, multicall=token_tables.MULTICALL3, wallet_cas=own8, block=None, strict=st8, sweep=sw8, **x9),
                    full=mode != "fastx")
            prep8 = self._disc_prep("bsc", "bsc", wallets, self._recon_strict_fn("bsc"))
            own8 = self._disc_own_cas("bsc", wallets)
            if prep8 is None:
                st8 = self._recon_strict_fn("bsc")
                wc8 = {str(w).lower(): {str(ca).lower() for ca in cas if str(ca).lower() in own8.get(str(w).lower(), set()) or st8(ca)}
                       for w in wallets}
                return lambda: recon.fetch_bsc_balances(rpcs8, wallets, cas, wallet_cas=wc8)
            return lambda: token_discovery.bsc_fetch(rpcs8, wallets, cas, own8, prep8)
        cc9 = self.cfg["chains"][chain]
        rpc_only9 = config.chain_discovery(chain, cc9) == "rpc"
        bsoff9 = config.bs_blocked(chain, cc9)
        fast9 = bool(latest and mode in ("fast", "fastx"))
        base9 = None if (rpc_only9 or bsoff9 or fast9 or not cc9.get("blockscout")) else str(cc9["blockscout"]).rstrip("/")
        from evm_watch import RpcSynthMixin as _RS
        rpcs9 = list(cc9.get("rpcs") or _RS.RPC_DEFAULT.get(chain) or [])
        if not rpcs9:
            log.error("recon %s 보류 — RPC 없음(chains.%s.rpcs 필요): 블록스카웃 잔고는 대사 정본으로 쓰지 않는다", chain, chain)

            def _no_rpc(chain=chain):
                raise RuntimeError(f"recon {chain} RPC 없음 — 대사 보류")
            return _no_rpc
        cas = {}
        for r in self.conn.execute("SELECT address, symbol, decimals FROM assets WHERE chain=? AND kind='token'", (chain,)).fetchall():
            if r["address"]:
                cas[str(r["address"]).lower()] = (r["symbol"], r["decimals"] if r["decimals"] is not None else self._meta_dec(chain, r["address"]))
        rt9 = set()
        for ca9, meta9 in ((cc9.get("recon_tokens") or {}).items()):
            ca9 = str(ca9).lower()
            if ca9 and isinstance(meta9, (list, tuple)) and len(meta9) == 2:
                try:
                    m9 = (str(meta9[0]), int(meta9[1]))
                except (TypeError, ValueError):
                    continue
                rt9.add(ca9)
                cas.setdefault(ca9, m9)
        must = {str(w).lower(): set(rt9) for w in wallets}
        strict9 = self._recon_strict_fn(chain)
        cur9 = statefile.read_json(paths.state(f"cursor_evm_{chain}.json"), {})
        try:
            blk9 = min(int(cur9.get(w, cur9.get(str(w).lower()))) for w in wallets)
        except (TypeError, ValueError):
            blk9 = None
        if latest:
            blk9 = None
        elif not blk9 or blk9 <= 0:
            def _no_cur(chain=chain):
                raise RuntimeError(f"recon {chain} 수집기 커서 블록 없음 — 대사 보류")
            return _no_cur
        wcas = {str(w).lower(): set(rt9) for w in wallets}
        for r in self.conn.execute("SELECT DISTINCT p.location, a.address FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
                                   " WHERE a.chain=? AND a.kind='token' AND p.location LIKE ?", (chain, f"wallet:{chain}:%")).fetchall():
            parts = str(r[0] or "").split(":")
            if len(parts) == 3 and parts[2].lower() in wcas and r[1]:
                wcas[parts[2].lower()].add(str(r[1]).lower())
        excl = chaincatalog.not_token_cas(chain)
        mc9 = token_tables.MULTICALL3_BY_CHAIN.get(chain, token_tables.MULTICALL3)
        nat9 = mode in ("nat", "natx")
        sweep9 = None
        if (bsoff9 or fast9) and not nat9:
            sweep9 = {str(k).lower(): str(v) for tab9 in (token_tables.STABLE_CAS, token_tables.JPY_STABLE_CAS) for k, v in (tab9.get(chain) or {}).items()}
        prep9 = None if (nat9 or fast9) else self._disc_prep(chain, "evm", wallets, strict9)

        if fast9:
            px9 = self._disc_prep(chain, "evm", wallets, strict9) if mode == "fastx" else None
            return lambda: self._prov_fastx(chain, px9, lambda **x9: self._prov_fast_fetch(
                chain, rpcs9, wallets, cas, discover_url=None, must=must, exclude=excl, multicall=mc9, wallet_cas=wcas, block=None,
                strict=strict9, sweep=sweep9, **x9))

        def _go9(prep9=prep9):
            ext9 = token_discovery.recon_extra_safe(prep9, upto=blk9)
            bal9 = recon.fetch_evm_rpc_balances(rpcs9, wallets, cas, discover_url=None if nat9 else base9, must=must,
                                                exclude=excl, want_native=mode != "tok", want_tokens=not nat9,
                                                multicall=mc9, wallet_cas=wcas, block=blk9, strict=strict9, sweep=sweep9,
                                                **({"wallet_extra": ext9["extra"]} if ext9.get("extra") else {}))
            return token_discovery.filter_result(bal9, prep9, ext9, keep_pending=bool(latest))
        return _go9

    @staticmethod
    def _prov_fastx(chain: str, prep, fetch, full: bool = False) -> dict:
        if not prep:
            return fetch()
        ext = token_discovery.recon_extra_safe(prep) if full else token_discovery.fast_extra(prep)
        bal = fetch(**({"wallet_extra": ext["extra"]} if ext.get("extra") else {}))
        return token_discovery.filter_result(bal, prep, ext, keep_pending=True)

    def _prov_sol_lanes(self, url: str):
        sol = self.cfg.get("sol") or {}
        h9 = bf_engine._host_norm(url)
        if not (h9 == "helius-rpc.com" or h9.endswith(".helius-rpc.com")):
            return [url], None

        def _u(k, d):
            v = sol.get(k, d)
            return str(v).strip() if isinstance(v, str) and v.strip().startswith("http") else None
        head, arch = _u("head_rpc", "https://solana-rpc.publicnode.com"), _u("archive_rpc", "https://api.mainnet-beta.solana.com")
        return [url] + ([arch] if arch else []), head

    @staticmethod
    def _prov_sol_fetch(url, wallets: list, stake_path: str = None, now: float = None, native_url: str = None) -> dict:
        try:
            sd = statefile.read_json(stake_path or paths.state("sol_stake.json"), {}) or {}
        except (Exception, SystemExit) as _cg9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("core_recon:ReconMixin._prov_sol_fetch", _cg9)
            sd = {}
        try:
            fresh = (time.time() if now is None else now) - float(sd.get("ts") or 0) <= 3 * 3600
        except (TypeError, ValueError):
            fresh = False
        accts = sd.get("accounts") if fresh and isinstance(sd.get("accounts"), dict) else {}
        ws = set(wallets)
        mine = sorted(pk for pk, a in accts.items() if pk and isinstance(a, dict) and a.get("w") in ws)
        live = ReconMixin._prov_sol_stake_live(url, mine, native_url) if mine else {}
        if live is None:
            raise RuntimeError(f"SOL 스테이크 계정 {len(mine)}개 지금 잔고 조회 실패 — 이 바퀴 SOL 임시 잔고 보류(다음 바퀴 재시도)")
        r = recon.fetch_sol_balances_fast(url if isinstance(url, list) else [url], wallets, native_url=native_url)
        try:
            r["_stake_ts"] = int(float(sd.get("ts") or 0)) if fresh and isinstance(sd.get("accounts"), dict) else 0
        except (TypeError, ValueError):
            r["_stake_ts"] = 0
        per = r.setdefault("per_wallet", {})
        if mine:
            r["_stake_live"] = 1
        for pk in mine:
            a = accts[pk]
            if a["w"] in ((r.get("_hold") or {})):
                continue
            try:
                lam = int(live[pk])
            except (TypeError, ValueError, KeyError):
                continue
            if lam >= 0:
                per[f"{a['w']}:stake:{pk}"] = {("native", None): lam}
        return r

    @staticmethod
    def _prov_sol_stake_live(url, pks: list, native_url: str = None):
        lanes = [u for u in ([native_url] if native_url else []) + ([url[0]] if isinstance(url, list) and url else [url] if isinstance(url, str) else []) if u]
        out = {}
        for i in range(0, len(pks), 100):
            chunk = pks[i:i + 100]
            got = None
            for u in lanes:
                try:
                    res = recon._rpc(u, "getMultipleAccounts", [chunk, {"encoding": "base64", "dataSlice": {"offset": 0, "length": 0}}])
                    vals = res.get("value") if isinstance(res, dict) else None
                    if not isinstance(vals, list) or len(vals) != len(chunk):
                        raise RuntimeError("getMultipleAccounts value 형식 오류")
                    got = [0 if v is None else int(v["lamports"]) for v in vals]
                    break
                except Exception as e:   # noqa: BLE001 [isolate]
                    calcguard.swallowed("core_recon:ReconMixin._prov_sol_stake_live", e)
                    log.info("SOL 스테이크 지금 잔고 조회 실패(계정 %d개 · 다음 차선 → 끝내 실패면 이 바퀴 SOL 임시 잔고 실패): %s", len(chunk), logs.safe_err(e)[:80])
            if got is None:
                return None
            out.update(zip(chunk, got))
        return out

    @staticmethod
    def _prov_fast_fetch(chain: str, urls: list, wallets: list, cas: dict, **kw) -> dict:
        r = recon.fetch_evm_rpc_balances(urls, wallets, cas, want_native=False, **kw)
        per = r.get("per_wallet") or {}
        hold = r.setdefault("_hold", {})
        todo = [w for w in wallets if w in per]
        if not todo:
            return r
        blk = hex(int(r["_block"]))
        mc = kw.get("multicall") if r.get("_multicall") else None
        if mc and chain not in chaincatalog.ZK_STACK and chain not in chaincatalog.NATIVE_MIRROR:
            items = [(("nat", w), mc, "4d2301cc" + str(w).lower().replace("0x", "").rjust(64, "0")) for w in todo]
            got = recon._mc_call(urls, blk, items, mc)
            for w in todo:
                rd = got.get(("nat", w))
                if rd is not None and len(rd) == 32:
                    per[w][("native", None)] = int.from_bytes(rd, "big")
                else:
                    hold.setdefault(w, []).append("native")
        else:
            for w in todo:
                per[w][("native", None)] = recon._rpc_any(urls, "eth_getBalance", [str(w).lower(), blk], check=recon._hex_int)
        for w in hold:
            per.pop(w, None)
        return r

    def _disc_prep(self, chain: str, kind: str, wallets: list, strict):
        if (self.cfg.get("token_discovery") or {}).get("enabled") is False:
            return None
        try:
            return token_discovery.recon_prep(self.conn, self.cfg, chain, list(wallets), strict, kind=kind)
        except Exception as e:   # noqa: BLE001 [fallback]
            calcguard.swallowed("core_recon:ReconMixin._disc_prep", e)
            log.warning("recon %s 토큰 발견 재료 실패(종전 목록으로): %s", chain, logs.safe_err(e)[:120])
            return None

    def _disc_own_cas(self, chain: str, wallets: list) -> dict:
        own = {str(w).lower(): set() for w in wallets}
        for r in self.conn.execute("SELECT DISTINCT p.location, a.address FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
                                   " WHERE a.chain=? AND a.kind='token' AND p.location LIKE ?", (chain, f"wallet:{chain}:%")).fetchall():
            parts = str(r[0] or "").split(":")
            if len(parts) == 3 and parts[2].lower() in own and r[1]:
                own[parts[2].lower()].add(str(r[1]).lower())
        return own

    @staticmethod
    def _recon_src(bal: dict, wallets=None) -> dict:
        if isinstance(bal, dict) and bal.get("_source") == "rpc" and isinstance(bal.get("_block"), int):
            out = {"_source": "rpc", "_block": int(bal["_block"])}
            if wallets is None:
                wallets = list((bal.get("_unobs") or {}).keys())
            un = sorted(f"{str(w).lower()}:{str(ca).lower()}" for w in wallets for ca in ((bal.get("_unobs") or {}).get(w) or ()))
            if un:
                out["_unobs"] = un
            qd = bal.get("_queried")
            if isinstance(qd, dict):
                out["_q"] = sorted(f"{str(w).lower()}:{str(ca).lower()}" for w in wallets for ca in (qd.get(w) or qd.get(str(w).lower()) or ()))
            return out
        tc = bal.get("_ts_cut") if isinstance(bal, dict) else None
        if isinstance(tc, int) and not isinstance(tc, bool):
            return {"_ts_cut": int(tc)}
        return {}

    def _recon_strict_fn(self, chain: str):
        spamguard.is_genuine(chain, "0x0")
        st9 = {str(k).lower() for k in (token_tables.STABLE_CAS.get(chain) or {})}
        jp9 = {str(k).lower() for k in (token_tables.JPY_STABLE_CAS.get(chain) or {})}
        wr9 = str(self.wrapped.get(chain) or "").lower()

        def strict(ca, chain=chain):
            ca = str(ca).lower()
            return ca in st9 or ca in jp9 or (wr9 and ca == wr9) or spamguard.is_genuine(chain, ca)
        return strict

    def _posted_sums_at(self, chain: str, blk: int):
        out, unknown = {}, set()
        for r in self.conn.execute(
                "SELECT p.asset_id, p.qty_base, p.location, p.source_kind, r.block FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
                " LEFT JOIN raw_txs r ON p.source_kind = 'chain_tx' AND r.chain = p.source_ns AND r.txhash = p.source_id"
                " WHERE a.chain=? AND p.location LIKE 'wallet:%'", (chain,)).fetchall():
            parts = (r["location"] or "").split(":")
            if len(parts) > 3:
                continue
            w = parts[2] if len(parts) >= 3 and parts[2] else None
            if r["source_kind"] == "chain_tx":
                try:
                    b9 = int(r["block"])
                except (TypeError, ValueError):
                    unknown.add(w)
                    continue
                if b9 > blk:
                    continue
            key = (w, r["asset_id"])
            out[key] = out.get(key, 0) + int(r["qty_base"])
        return out, unknown

    def _recon_at(self, chain: str, bal: dict):
        if isinstance(bal, dict) and bal.get("_source") == "rpc" and isinstance(bal.get("_block"), int) \
                and isinstance(bal.get("_block_ts"), int):
            sums, unk = self._posted_sums_at(chain, int(bal["_block"]))
            return sums, unk, int(bal["_block_ts"]) + 1
        return self._posted_sums(chain), set(), int(time.time())

    def _obs_block(self, sid: str):
        return self._obs_bound(sid)[0]

    def _obs_bound(self, sid: str):
        cache = self.__dict__.setdefault("_obs_block_cache", {})
        r = self.conn.execute("SELECT payload, observed_at FROM raw_observations WHERE obs_id=?", (sid,)).fetchone()
        key = (sid, r[1] if r else None)
        if key not in cache:
            try:
                d = json.loads(r[0]) if r and r[0] else {}
            except (TypeError, ValueError):
                d = {}
            b = d.get("_block") if isinstance(d, dict) else None
            c = d.get("_ts_cut") if isinstance(d, dict) else None
            cache[key] = (int(b) if isinstance(b, int) and not isinstance(b, bool) else None,
                          int(c) if isinstance(c, int) and not isinstance(c, bool) else None)
        return cache[key]

    def _absorbed(self, sid: str, ts: int, T: int, blk) -> bool:
        B, cut = self._obs_bound(sid)
        if B is not None and blk is not None:
            try:
                return int(blk) <= B
            except (TypeError, ValueError):
                pass
        return ts < (cut if cut is not None else T)

    def _tx_block(self, chain: str, txhash: str):
        r = self.conn.execute("SELECT block FROM raw_txs WHERE chain=? AND txhash=?", (chain, txhash)).fetchone() if txhash else None
        try:
            return int(r[0]) if r and r[0] is not None else None
        except (TypeError, ValueError):
            return None

    def _recon_q_aids(self, chain: str, bal: dict):
        qd = (bal or {}).get("_queried") if isinstance(bal, dict) and bal.get("_source") == "rpc" else None
        if not isinstance(qd, dict):
            return None
        out = {}
        for w, cas in qd.items():
            s9 = out.setdefault(w, set())
            for ca in cas or ():
                r = self.conn.execute("SELECT asset_id FROM assets WHERE chain=? AND kind='token' AND lower(address)=?",
                                      (chain, str(ca).lower())).fetchone()
                if r:
                    s9.add(r[0])
        return out

    def _recon_unobs_aids(self, chain: str, bal: dict) -> dict:
        out = {}
        for w, cas in ((bal or {}).get("_unobs") or {}).items():
            for ca in cas or ():
                r = self.conn.execute("SELECT asset_id FROM assets WHERE chain=? AND kind='token' AND lower(address)=?",
                                      (chain, str(ca).lower())).fetchone()
                if r:
                    out.setdefault(w, set()).add(r[0])
        return out

    def _obs_cov(self, sid: str):
        cache = self.__dict__.setdefault("_obs_cov_cache", {})
        r = self.conn.execute("SELECT payload, observed_at FROM raw_observations WHERE obs_id=?", (sid,)).fetchone()
        key = (sid, r[1] if r else None)
        if key not in cache:
            try:
                d = json.loads(r[0]) if r and r[0] else {}
            except (TypeError, ValueError):
                d = {}
            u = d.get("_unobs") if isinstance(d, dict) else None
            q = d.get("_q") if isinstance(d, dict) else None
            cache[key] = ({str(x).lower() for x in u} if isinstance(u, list) else set(),
                          {str(x).lower() for x in q} if isinstance(q, list) else None)
        return cache[key]

    @staticmethod
    def _obs_wallet_pay(wb: dict, zeros=None, keep=None) -> dict:
        out = {f"{k[0]}:{k[1]}": v for k, v in (wb or {}).items() if keep is None or keep(k)}
        for ca in zeros or ():
            if ca and (keep is None or keep(("token", ca))):
                out.setdefault(f"token:{ca}", 0)
        return out

    def _obs_tok_observed(self, sid: str, w: str, ca: str) -> bool:
        un, q = self._obs_cov(sid)
        k9 = f"{str(w).lower()}:{str(ca or '').lower()}"
        if q is None and (sid == "recon:bsc" or str(sid).startswith("recon:bsc:")) and k9 not in un:
            ck9 = self.__dict__.setdefault("_obs_bsc_keys_cache", {})
            r9 = self.conn.execute("SELECT payload, observed_at FROM raw_observations WHERE obs_id=?", (sid,)).fetchone()
            key9 = (sid, r9[1] if r9 else None)
            if key9 not in ck9:
                try:
                    d9 = json.loads(r9[0]) if r9 and r9[0] else {}
                except (TypeError, ValueError):
                    d9 = {}
                ck9[key9] = {str(x).lower(): {str(y).lower() for y in v} for x, v in d9.items() if isinstance(v, dict)} \
                    if isinstance(d9, dict) else {}
            return f"token:{str(ca or '').lower()}" in ck9[key9].get(str(w).lower(), set())
        return k9 not in un and (q is None or k9 in q)

    def _recon_onchain(self, chain: str, bal: dict) -> dict:
        onchain = {}
        meta_hint = bal.get("_meta") or {}
        for w, wb in (bal.get("per_wallet") or {}).items():
            for (k2, addr), amount in wb.items():
                if k2 == "native":
                    aid = self.asset_id("native", chain, None,
                                        symbol=self.native_sym.get(chain, chain_registry.native_symbol(chain, chain.upper())),
                                        decimals=9 if chain == "sol" else chain_registry.native_decimals(chain, 18))
                else:
                    hint = meta_hint.get(addr, (None, None))
                    aid = self.asset_id("token", chain, addr, symbol=hint[0], decimals=hint[1])
                onchain[(w, aid)] = amount
        return onchain

    RECON_WAIT_SEC = 8.0

    RECON_MAX_JOBS = 4

    RECON_PENDING_SCAN = 2000

    RECON_DEFER_MAX_SEC = 900

    def _recon_pending_chains(self):
        out = set()
        for stream, reader in (("evm", self.reader), ("sol", self.sol_reader), ("bsc", self.bsc_reader)) + tuple(getattr(self, "chain_readers", None) or ()):
            row = self.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream=?", (stream,)).fetchone()
            seg, off = (row["seg"], row["off"]) if row else (1, 0)
            batch, _, _ = reader.read_batch(seg, off, max_records=self.RECON_PENDING_SCAN)
            if len(batch) >= self.RECON_PENDING_SCAN:
                return None
            for rec, _s, _o in batch:
                if not isinstance(rec, dict) or rec.get("chain") is None:
                    return None
                out.add(str(rec["chain"]).lower())
        return out

    def _recon_pending(self, chain: str) -> bool:
        pend = self._recon_pending_chains()
        return pend is None or str(chain).lower() in pend

    def _recon_quiet(self, chain: str, stream: str, drained: set) -> bool:
        if stream in drained:
            return True
        cache = self.__dict__.get("_recon_pend_pass")
        if cache is None or cache[0] is not True:
            cache = (True, self._recon_pending_chains())
            if "_recon_pend_pass" in self.__dict__:
                self._recon_pend_pass = cache
        pend = cache[1]
        return pend is not None and str(chain).lower() not in pend

    def _recon_fp(self, chain: str, wallets=None):
        n, mx, sums = 0, 0, {}
        wset = None if wallets is None else set(wallets)
        for r in self.conn.execute(
                "SELECT p.posting_id, p.asset_id, p.qty_base, p.location FROM postings p JOIN assets a"
                " ON a.asset_id = p.asset_id WHERE a.chain=? AND p.location LIKE 'wallet:%'", (chain,)).fetchall():
            parts = (r["location"] or "").split(":")
            if len(parts) > 3:
                continue
            w = parts[2] if len(parts) >= 3 and parts[2] else None
            if wset is not None and w not in wset:
                continue
            n += 1
            mx = max(mx, int(r["posting_id"]))
            key = (w, r["asset_id"])
            sums[key] = sums.get(key, 0) + int(r["qty_base"])
        return (n, mx, sums)

    def _recon_bal(self, chain: str, kind: str, mode: str, wallets: list):
        jobs = self.__dict__.setdefault("_recon_jobs", {})
        key = (chain, mode)
        wl = sorted(wallets)
        job = jobs.get(key)
        if job is None:
            if sum(1 for j in jobs.values() if not j["ev"].is_set()) >= self.RECON_MAX_JOBS:
                return None
            stub = self.__dict__.get("_recon_fetch")
            fn = (lambda: stub(chain, kind, list(wl))) if stub is not None \
                else self._recon_fetch_plan(chain, kind, wl, mode)
            job = {"wallets": wl, "t0": time.time(), "t1": None, "bal": None, "err": None,
                   "fp": self._recon_fp(chain, None if mode == "chain" else wl), "ev": threading.Event()}

            def _run(job=job, fn=fn):
                try:
                    job["bal"] = fn()
                except BaseException as e:   # noqa: BLE001 [fallback]
                    job["err"] = e
                    calcguard.swallowed("core_recon:ReconMixin._recon_bal._run", e)
                finally:
                    job["t1"] = time.time()
                    job["ev"].set()
            jobs[key] = job
            if stub is not None:
                _run()
            else:
                try:
                    threading.Thread(target=_run, name=f"tj-recon-{chain}-{mode}", daemon=True).start()
                except Exception:
                    jobs.pop(key, None)
                    raise
                dl = self.__dict__.get("_recon_deadline")
                job["ev"].wait(self.RECON_WAIT_SEC if dl is None else max(0.0, dl - time.time()))
        if not job["ev"].is_set():
            return None
        label = f"recon {chain}" + {"new": " 새 지갑", "tok": " 새 지갑(토큰만)", "nat": " 새 지갑(네이티브)",
                                    "natx": " 새 지갑(네이티브 — 색인 정체 임시)"}.get(mode, "")
        if job["err"] is not None:
            jobs.pop(key, None)
            e = job["err"]
            raise e if isinstance(e, Exception) else RuntimeError(repr(e))
        if time.time() - job["t1"] > self.RECON_DEFER_MAX_SEC:
            jobs.pop(key, None)
            log.info("%s 보류 — 조회 결과가 %d초 넘게 반영 못 됨(폐기·재조회)", label, self.RECON_DEFER_MAX_SEC)
            return None
        if self._recon_pending(chain):
            return None
        jobs.pop(key, None)
        if job["wallets"] != wl:
            log.info("%s 보류 — 조회 중 지갑 목록 변경", label)
            return None
        sui9 = kind == "nonevm" and chain == "sui" and mode == "new"
        if not (self._scope_ready_tok(chain) if mode == "tok" else
                self._scope_ready_natx(chain) if mode == "natx" else
                chain_state.ChainState(chain, paths.STATE_DIR).ready(set(wl)) if sui9 else self._scope_ready(chain)):
            log.info("%s 보류 — 조회 중 수집기 준비 상태 해제(동기 도장·상세 큐)", label)
            return None
        if sui9 and (job["bal"] if isinstance(job["bal"], dict) else {}).get("_sui_fp") != self._sui_recon_guard(chain)[2]:
            log.info("%s 보류 — 조회 중 수집기 상세 대기·gap 상태 변경(또는 지문 없음)", label)
            return None
        if self._recon_fp(chain, None if mode == "chain" else wl) != job["fp"]:
            log.info("%s 보류 — 조회 중 신규 레코드 유입(이 체인 원장 변경)", label)
            return None
        jf9 = (job["bal"] if isinstance(job["bal"], dict) else {}).get("_jw_fp") if kind == "nonevm" and chain == "ton" else None
        if jf9 is not None:
            import ton_watch
            if ton_watch.jw_fingerprint(wl) != jf9:
                log.info("%s 보류 — 조회 중 검증 제톤 지갑 집합 변경(폐기·재조회)", label)
                return None
        if job["t1"] - job["t0"] > 30:
            log.info("%s 잔고조회 %.0f초 — 백그라운드 완료(소비 루프 비차단) · 반영", label, job["t1"] - job["t0"])
        b9 = job["bal"] if isinstance(job["bal"], dict) else {}
        if b9.get("_source") == "rpc":
            nd = len(b9.get("_bs_diff") or [])
            nu = sum(len(v) for v in (b9.get("_unobs") or {}).values())
            log.info("%s 잔고 = RPC 블록 %s (블록스카웃과 다른 칸 %d · 관측 불가로 뺀 칸 %d)", label, b9.get("_block"), nd, nu)
            for w9, ca9, bv9, rv9 in (b9.get("_bs_diff") or [])[:20]:
                log.info("  %s %s 블록스카웃 %s → RPC %s", str(w9)[:10], str(ca9)[:10], bv9, rv9)
        if isinstance(b9.get("_disc"), dict):
            nk = sum(len(v) for v in (b9.get("_disc_keep") or {}).values())
            ns = sum(len(v) for v in (b9.get("_disc_skip") or {}).values())
            nf = len((b9["_disc"].get("fail") or {}))
            if nk or ns or nf:
                log.info("%s 토큰 발견: 원장 밖 보유 %d칸(기초 잔고로) · 스팸 의심 제외 %d칸 · 발견 일부 실패 %d지갑", label, nk, ns, nf)
        return job["bal"]

    def _wallet_backfilled(self, chain: str, kind: str, w: str) -> bool:
        sd = paths.STATE_DIR
        if kind == "nonevm":
            return chain_state.ChainState(chain, sd).owner_done(w)
        if kind == "bsc":
            cur = statefile.read_json(os.path.join(sd, "cursor_bsc.json"), {})
            return w in {str(x).lower() for x in (cur.get("_wallets") or [])} and not cur.get("_neww")
        if kind == "sol":
            return w in statefile.read_json(os.path.join(sd, "cursor_sol.json"), {})
        return w in statefile.read_json(os.path.join(sd, f"cursor_evm_{chain}.json"), {})

    def _recon_new_wallets(self, chain: str, kind: str, stream: str, drained: set, cutoff_ts: int, start: bool = True):
        T, ws = self._recon_view(chain)
        pool = sorted(self.sol_wallets) if kind == "sol" else (sorted(self.chain_owners.get(chain, set())) if kind == "nonevm"
                                                               else sorted(self.my_wallets.get(chain, set())))

        def cands():
            return [w for w in pool if w.lower() not in ws and not self._meta_get(f"wrecon_done:{chain}:{w}")]
        if not cands():
            return 0
        jobs = self.__dict__.get("_recon_jobs", {})
        full_ok = self._scope_ready(chain)
        if kind == "nonevm" and chain == "sui" and not full_ok:
            st9 = chain_state.ChainState(chain, paths.STATE_DIR)
            full_ok = st9.ready({w for w in cands() if st9.owner_done(w)})
        done = 0
        for mode in ("new", "nat"):
            if not full_ok and (chain, mode) not in jobs:
                continue
            sel = [w for w in cands() if bool(self._meta_get(f"wrecon_tok:{chain}:{w}")) == (mode == "nat")]
            if sel:
                done += self._wrecon_run(chain, kind, stream, drained, cutoff_ts, start, mode, sel)
        if kind == "evm" and ((not full_ok and self._scope_ready_tok(chain)) or (chain, "tok") in jobs):
            sel = [w for w in cands() if not self._meta_get(f"wrecon_tok:{chain}:{w}")]
            if sel:
                done += self._wrecon_run(chain, kind, stream, drained, cutoff_ts, start, "tok", sel)
        if kind == "evm" and ((not full_ok and self._scope_ready_natx(chain)) or (chain, "natx") in jobs):
            sel = [w for w in cands() if self._meta_get(f"wrecon_tok:{chain}:{w}")]
            if sel:
                done += self._wrecon_run(chain, kind, stream, drained, cutoff_ts, start, "natx", sel)
        return done

    def _wrecon_run(self, chain: str, kind: str, stream: str, drained: set, cutoff_ts: int, start: bool, mode: str, wallets: list):
        new = [w for w in wallets if self._wallet_backfilled(chain, kind, w)]
        if not new:
            return 0
        if (chain, mode) not in self.__dict__.get("_recon_jobs", {}) \
                and (not start or not self._recon_quiet(chain, stream, drained)):
            return 0
        bal = self._recon_bal(chain, kind, mode, new)
        if bal is None:
            return 0
        per = bal.get("per_wallet") or {}
        onchain = self._recon_onchain(chain, bal)
        posted, unk9, t_obs = self._recon_at(chain, bal)
        nat_aids = {r[0] for r in self.conn.execute("SELECT asset_id FROM assets WHERE chain=? AND kind='native'", (chain,)).fetchall()}

        natm = mode in ("nat", "natx")

        def in_scope(aid):
            return mode == "new" or ((aid in nat_aids) == natm)
        scope9 = {"tok": "token", "nat": "native", "natx": "native"}.get(mode)
        now9 = t_obs
        done = 0
        nlegs = 0
        try:
            hold9 = bal.get("_hold") or {}
            unobs_aids = self._recon_unobs_aids(chain, bal)
            q_aids = self._recon_q_aids(chain, bal)
            for w in new:
                if w in unk9 or str(w).lower() in unk9:
                    log.warning("recon %s 새 지갑 %s 보류 — 블록 모르는 체인 거래 기장", chain, w[:10])
                    continue
                if w in hold9:
                    log.warning("recon %s 새 지갑 %s 보류 — 관측 불가 토큰 %s", chain, w[:10], ",".join(str(x)[:10] for x in hold9[w][:5]))
                    continue
                if w not in per:
                    log.warning("recon %s 새 지갑 %s 잔고 응답 없음 — 다음 주기", chain, w[:10])
                    continue
                legs = []
                for key in {k for k in onchain if k[0] == w} | {k for k in posted if k[0] == w}:
                    if not in_scope(key[1]) or key[1] in unobs_aids.get(w, ()):
                        continue
                    if q_aids is not None and key[1] not in nat_aids and key[1] not in q_aids.get(w, ()):
                        continue
                    diff = onchain.get(key, 0) - posted.get(key, 0)
                    if diff:
                        legs.append((key[1], diff))
                loc = f"wallet:{chain}:{w}"
                if mode == "new":
                    f9 = self.conn.execute("SELECT min(event_ts) FROM postings WHERE location=?", (loc,)).fetchone()[0]
                else:
                    f9 = self.conn.execute("SELECT min(event_ts) FROM postings WHERE location=? AND source_kind='chain_tx'",
                                           (loc,)).fetchone()[0]
                pos_ts = min(int(cutoff_ts), int(f9) - 1) if f9 is not None else int(cutoff_ts)
                sid = f"recon:{chain}:{w}" + (":native" if natm else "")
                obs9 = self._obs_wallet_pay(per[w], (bal.get("_zero") or {}).get(w),
                                            keep=lambda k, natm=natm: mode == "new" or ((k[0] == "native") == natm))
                pay9 = {w: obs9}
                if scope9:
                    pay9["_scope"] = scope9
                if mode == "natx":
                    pay9["_basis"] = "internal_index_stalled"
                pay9.update(self._recon_src(bal, [w]))
                self.conn.execute(
                    "INSERT OR REPLACE INTO raw_observations (obs_id, kind, venue, payload, observed_at) VALUES (?,?,?,?,?)",
                    (sid, "opening_balance", chain, json.dumps(pay9, ensure_ascii=False), now9))
                for seq, (aid, diff) in enumerate(sorted(legs)):
                    self._post_leg_strict('opening', chain, sid, seq, pos_ts if diff > 0 else now9, aid, loc, diff, None, None, 'opening', 'OPENING')
                    recon_adj.note(self.conn, "K2", ('opening', chain, sid, seq), "pre_window" if diff > 0 else "untracked_out", mode=mode)
                mk9 = f"wrecon_tok:{chain}:{w}" if mode == "tok" else f"wrecon_done:{chain}:{w}"
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (mk9, str(now9)))
                if mode == "natx":
                    self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (f"wrecon_natx:{chain}:{w}", str(now9)))
                done += 1
                nlegs += len(legs)
                log.info("★recon %s 새 지갑 %s 기초잔고%s %d개 자산 보정★", chain, w[:10],
                         {"tok": "(토큰만 — 네이티브는 내부 이동 색인 뒤)", "nat": "(네이티브)",
                          "natx": "(네이티브 — 탐색기 내부 이동 색인 장기 정체: RPC 블록 잔고로 임시 대사, 색인 완료 뒤 자동 보정)"}.get(mode, ""),
                         len(legs))
            if nlegs:
                self._inval_daily()
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        if done:
            self._recon_view_drop(chain)
        if nlegs:
            dm("RECON", f"[{chain}] 새 지갑 기초잔고 대사 완료" + {"tok": "(토큰만 — 네이티브는 내부 이동 색인 완료 뒤)",
                                                              "nat": "(네이티브)",
                                                              "natx": "(네이티브 — 탐색기 내부 이동 색인 장기 정체라 RPC 잔고로 임시 맞춤, "
                                                                      "색인 완료 뒤 늦게 오는 내부 이동은 자동 보정)"}.get(mode, "")
               + f" — {done}개 지갑 · 보정 {nlegs}건")
        return done

    GATE_RELOAD_SEC = 600

    def _gate_reload(self):
        now9 = time.time()
        sig9 = []
        for p9 in (paths.ACTIVITY_GATE_PATH, paths.BACKFILL_SPEED_PATH):
            try:
                st9 = os.stat(p9)
                sig9.append((st9.st_mtime_ns, st9.st_size))
            except OSError:
                sig9.append(None)
        if now9 - getattr(self, "_gate_at", 0) < self.GATE_RELOAD_SEC and sig9 == getattr(self, "_gate_sig", sig9):
            return 0
        self._gate_at = now9
        self._gate_sig = sig9
        if not os.path.exists(paths.ACTIVITY_GATE_PATH):
            return 0
        cfg2 = config.load_config()
        added = []
        for w in cfg2.get("wallets") or []:
            if w.get("type", "evm") != "evm":
                continue
            c, a = w["chain"], str(w["address"]).lower()
            if a in self.my_wallets.get(c, set()):
                continue
            if c not in self.cfg["chains"]:
                self.cfg["chains"][c] = (cfg2.get("chains") or {}).get(c)
                if not self.cfg["chains"][c]:
                    self.cfg["chains"].pop(c, None)
                    continue
            ns9 = (cfg2.get("native_symbol") or {}).get(c)
            if ns9:
                self.native_sym.setdefault(c, ns9)
            wr9 = (cfg2.get("wrapped_native") or {}).get(c)
            if wr9:
                self.wrapped.setdefault(c.lower(), str(wr9).lower())
            self.my_wallets.setdefault(c, set()).add(a)
            self.cfg["wallets"].append(dict(w))
            self.conn.execute("INSERT OR IGNORE INTO wallets (chain, address, label, added_at) VALUES (?,?,?,?)",
                              (c, a, w.get("label"), int(now9)))
            added.append(f"{c}:{a[:10]}")
        if added:
            self.conn.commit()
            log.warning("★활동 게이트 합류 %d쌍: %s★", len(added), ", ".join(added[:12]))
        return len(added)

    def _negabs_on(self) -> bool:
        return self.cfg.get("negabs_enabled", True) is not False and os.environ.get("TJ_NEGABS") != "0"

    def _negabs_runner(self):
        r = self.__dict__.get("_negabs")
        if r is None:
            r = self._negabs = discopen.Runner(self, log)
        return r

    def _negabs_note(self, chain: str, txhash: str) -> int:
        if not self._negabs_on():
            return 0
        try:
            return self._negabs_runner().note(chain, txhash)
        except Exception as e:   # noqa: BLE001 [fallback]
            calcguard.swallowed("core_recon:ReconMixin._negabs_note", e)
            log.warning("발견 시점 기초 잔고 후보 기록 실패(무시 — 도구로 다시 찾음) %s: %s", txhash[:14], logs.safe_err(str(e))[:160])
            return 0

    def negabs_pass(self, drained=frozenset()) -> int:
        if not self._negabs_on():
            return 0
        return self._negabs_runner().run(drained)

    def _disc_max_t(self, chain: str) -> int:
        cache = self.__dict__.setdefault("_disc_t_cache", {})
        if chain not in cache:
            cache[chain] = discopen.max_t(self.conn, chain)
        return cache[chain]

    def recon_pass(self, drained: set):
        jobs = self.__dict__.setdefault("_recon_jobs", {})
        start = time.time() - self._last_recon >= 300
        if self.recon_months <= 0 or (not start and not jobs):
            return
        if start:
            self._last_recon = time.time()
            try:
                self._rpc_recon_reset()
            except Exception as e:  # noqa: BLE001 [fallback]
                calcguard.swallowed("core_recon:ReconMixin.recon_pass", e)
                self.conn.rollback()
                log.warning("RPC 재대사 점검 실패(다음 주기): %s", e)
        self._recon_deadline = time.time() + self.RECON_WAIT_SEC
        self._recon_pend_pass = (False, None)
        try:
            self._recon_pass_scopes(drained, start, jobs)
        finally:
            self._recon_deadline = None
            self.__dict__.pop("_recon_pend_pass", None)

    RECON_HOLD_FILE = "recon_hold.json"

    RECON_HOLD_GAP = 7200

    def _recon_hold_set(self, chain: str, why) -> None:
        try:
            p9 = paths.state(self.RECON_HOLD_FILE)
            try:
                with open(p9, "r", encoding="utf-8") as f:
                    cur = json.load(f)
            except FileNotFoundError:
                cur = {}
            except (OSError, ValueError):
                cur = {}
            cur = cur if isinstance(cur, dict) else {}
            if why is None:
                if chain not in cur:
                    return
                cur.pop(chain, None)
            else:
                now9 = int(time.time())
                o9 = cur.get(chain) if isinstance(cur.get(chain), dict) else {}
                try:
                    keep9 = now9 - int(o9.get("at") or 0) <= self.RECON_HOLD_GAP
                    since9 = int(o9.get("since") or now9) if keep9 else now9
                except (TypeError, ValueError):
                    since9 = now9
                cur[chain] = {"why": logs.safe_err(why)[:240], "since": since9, "at": now9}
            statefile.atomic_write_json(p9, cur)
        except Exception as e:   # noqa: BLE001 [optional]
            calcguard.swallowed("core_recon:ReconMixin._recon_hold_set", e)
            log.warning("[%s] 대사 보류 기록 실패(무시): %s", chain, logs.safe_err(e)[:160])

    def _recon_pass_scopes(self, drained: set, start: bool, jobs: dict):
        scopes = []
        for chain in self.cfg.get("chains", {}):
            if self.my_wallets.get(chain):
                scopes.append((chain, "evm"))
        if self.sol_wallets:
            scopes.append(("sol", "sol"))
        if any(w.get("type") == "bsc_rpc" for w in self.cfg["wallets"]):
            scopes.append(("bsc", "bsc"))
        for c9 in sorted(self.chain_owners):
            if self.chain_owners[c9] and self._nonevm_adapter(c9) is not None:
                scopes.append((c9, "nonevm"))
        if start and scopes:
            off9 = self.__dict__.get("_recon_scope_cursor", 0) % len(scopes)
            scopes = scopes[off9:] + scopes[:off9]
            self._recon_scope_cursor = (off9 + 1) % len(scopes)
        live = set()
        for c, _k in scopes:
            if self._meta_get(f"recon_done_{c}"):
                live |= {(c, "new"), (c, "tok"), (c, "nat"), (c, "natx")}
            else:
                live.add((c, "chain"))
                if c == "sui" and _k == "nonevm":
                    live.add((c, "new"))
        now9 = time.time()
        for k9 in [k for k, j in jobs.items() if j["ev"].is_set()
                   and (k not in live or now9 - (j["t1"] or now9) > self.RECON_DEFER_MAX_SEC)]:
            jobs.pop(k9, None)
        for chain, kind in scopes:
            cutoff_ts = self._win_t0(None, chain)
            stream = {"evm": "evm", "sol": "sol", "bsc": "bsc"}.get(kind, chain)
            if self._meta_get(f"recon_done_{chain}"):
                if start and kind == "nonevm":
                    self._recon_hold_set(chain, None)
                if not start and not any((chain, m9) in jobs for m9 in ("new", "tok", "nat", "natx")):
                    continue
                try:
                    self._recon_new_wallets(chain, kind, stream, drained, cutoff_ts, start=start)
                except Exception as e:  # noqa: BLE001 [isolate]
                    calcguard.swallowed("core_recon:ReconMixin._recon_pass_scopes[_recon_new_wallets#1]", e)
                    self.conn.rollback()
                    log.warning("recon %s 새 지갑 대사 실패(다음 주기): %s", chain, e)
                continue
            if chain == "sui" and kind == "nonevm" and (chain, "chain") not in jobs \
                    and ((chain, "new") in jobs or (start and not self._scope_ready(chain))):
                try:
                    self._recon_new_wallets(chain, kind, stream, drained, cutoff_ts, start=start)
                except Exception as e:  # noqa: BLE001 [isolate]
                    calcguard.swallowed("core_recon:ReconMixin._recon_pass_scopes[_recon_new_wallets#2]", e)
                    self.conn.rollback()
                    log.warning("recon %s 지갑별 대사 보류·실패(다음 주기): %s", chain, logs.safe_err(e)[:200])
                    self._recon_hold_set(chain, e)
                continue
            if (chain, "chain") not in jobs:
                if not start or not self._scope_ready(chain) or not self._recon_quiet(chain, stream, drained):
                    continue
            try:
                bal = self._recon_bal(chain, kind, "chain", sorted(self.chain_owners.get(chain, set())) if kind == "nonevm"
                                      else sorted(self.my_wallets.get(chain, set())) if kind != "sol"
                                      else sorted(self.sol_wallets))
            except Exception as e:  # noqa: BLE001 [isolate]
                calcguard.swallowed("core_recon:ReconMixin._recon_pass_scopes[bal]", e)
                log.warning("recon %s 잔고조회 실패(다음 주기 재시도): %s", chain, e)
                if kind == "nonevm":
                    self._recon_hold_set(chain, e)
                continue
            if bal is None:
                continue
            if bal.get("_hold"):
                log.warning("recon %s 보류 — 관측 불가 토큰 있는 지갑 %s", chain, ",".join(str(w)[:10] for w in bal["_hold"]))
                continue
            per = bal.get("per_wallet") or {}
            meta_hint = bal.get("_meta") or {}
            posted, unk9, t_obs = self._recon_at(chain, bal)
            if unk9:
                log.error("recon %s 보류 — 블록 모르는 체인 거래 기장(지갑 %s)", chain, ",".join(str(w)[:10] for w in unk9))
                continue
            if any(w is None for (w, _a) in posted):
                log.error("recon %s 보류 — 지갑 미상 레거시 posting 존재(재파생 필요)", chain)
                continue
            legs = []
            onchain = {}
            for w, wb in per.items():
                for (k2, addr), amount in wb.items():
                    if k2 == "native":
                        aid = self.asset_id("native", chain, None,
                                            symbol=self.native_sym.get(chain, chain_registry.native_symbol(chain, chain.upper())),
                                            decimals=9 if chain == "sol" else chain_registry.native_decimals(chain, 18))
                    else:
                        hint = meta_hint.get(addr, (None, None))
                        aid = self.asset_id("token", chain, addr, symbol=hint[0], decimals=hint[1])
                    onchain[(w, aid)] = amount
            unobs_aids = self._recon_unobs_aids(chain, bal)
            q_aids = self._recon_q_aids(chain, bal)
            nat9 = {r[0] for r in self.conn.execute("SELECT asset_id FROM assets WHERE chain=? AND kind='native'", (chain,)).fetchall()}
            for key in set(onchain) | set(posted):
                if key[1] in unobs_aids.get(key[0], ()):
                    continue
                if q_aids is not None and key[1] not in nat9 and key[1] not in q_aids.get(key[0], ()):
                    continue
                diff = onchain.get(key, 0) - posted.get(key, 0)
                if diff == 0:
                    continue
                legs.append((key[0], key[1], diff))
            try:
                self.conn.execute(
                    "INSERT OR REPLACE INTO raw_observations (obs_id, kind, venue, payload, observed_at)"
                    " VALUES (?,?,?,?,?)",
                    (f"recon:{chain}", "opening_balance", chain,
                     json.dumps(dict({w: self._obs_wallet_pay(wb, (bal.get("_zero") or {}).get(w))
                                      for w, wb in per.items()}, **self._recon_src(bal, list(per))), ensure_ascii=False),
                     t_obs))
                for seq, (w, aid, diff) in enumerate(sorted(legs, key=lambda x: (x[1], x[0] or ""))):
                    ev_ts = cutoff_ts if diff > 0 else t_obs
                    loc = f"wallet:{chain}:{w}" if w else f"wallet:{chain}"
                    self._post_leg_strict('opening', chain, f'recon:{chain}', seq, ev_ts, aid, loc, diff, None, None, 'opening', 'OPENING')
                    recon_adj.note(self.conn, "K1", ('opening', chain, f'recon:{chain}', seq), "pre_window" if diff > 0 else "untracked_out")
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)",
                                  (f"recon_done_{chain}", str(t_obs)))
                self.conn.commit()
                if kind == "nonevm":
                    self._recon_hold_set(chain, None)
                log.info("★recon %s 완료: 기초잔고 %d개 자산 보정★", chain, len(legs))
                dm("RECON", f"[{chain}] 기초잔고 대사 완료 — {len(legs)}개 자산 보정")
            except Exception:
                self.conn.rollback()
                raise
        marker = paths.state("backfill_done")
        if not os.path.exists(marker):
            all_done = all(self._meta_get(f"recon_done_{c}") for c, _ in scopes)
            if not self._meta_get("recon_done_upbit") and self._upbit_keys():
                all_done = False
            exf9 = self._exf_connected() if all_done else []
            if all_done and any(not self._meta_get(f"recon_done_exf_{ex9}") for ex9 in exf9):
                all_done = False
            if all_done and (scopes or (self._upbit_keys() or exf9)):
                fsio.atomic_write_text(marker, repr(time.time()), mode=None, fsync=False, dir_fsync=False, makedirs=False)
                log.info("★백필 완료 마커 생성 — 일별 스냅샷 동결 시작★")
                dm("BACKFILL_DONE", "전 체인 백필+기초잔고 대사 완료 — 일별 스냅샷 동결 시작")
