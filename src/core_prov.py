import envfile, logs, paths, statefile
import os
import threading
import time
import token_discovery
import logging
import calcguard  # noqa: E402

log = logging.getLogger('tj-core')


class ProvMixin:

    @staticmethod
    def _upbit_keys() -> bool:
        e9 = envfile.read_env_file()
        return bool(e9.get("UPBIT_ACCESS") and e9.get("UPBIT_SECRET"))

    def _exf_connected(self) -> list:
        import settings_store
        e9 = envfile.read_env_file()
        out = [ex9 for ex9, sp9 in settings_store.EXCHANGES.items()
               if ex9 != "upbit" and all(e9.get(k9) for k9, _l9 in sp9.get("fields") or ())]
        try:
            import hl_spot
            if hl_spot.addresses(self.cfg):
                out.append("hyperliquid")
        except Exception as _cg9:   # noqa: BLE001 [optional]
            calcguard.swallowed("core_prov:ProvMixin._exf_connected", _cg9)
            pass
        return out

    PROV_FILE = "prov_bal.json"

    PROV_EVERY = 3600

    PROV_TICK = 120

    PROV_PAR = 6

    PROV_ORDER = ("eth", "base", "arbitrum", "sol", "bsc", "polygon", "optimism")

    PROV_FAST_UPGRADE = 600

    def _prov_alch_ok(self, chain: str) -> bool:
        if (self.cfg.get("token_discovery") or {}).get("enabled") is False:
            return False
        try:
            return bool(token_discovery.alchemy_net(chain) and token_discovery.alchemy_url(chain))
        except Exception as _cg9:   # noqa: BLE001 [probe]
            calcguard.swallowed("core_prov:ProvMixin._prov_alch_ok", _cg9)
            return False

    def _prov_targets(self) -> list:
        scopes = [(c, "evm") for c in self.cfg.get("chains", {}) if self.my_wallets.get(c)]
        if self.sol_wallets:
            scopes.append(("sol", "sol"))
        if any(w.get("type") == "bsc_rpc" for w in self.cfg["wallets"]):
            scopes.append(("bsc", "bsc"))
        for c9 in sorted(getattr(self, "chain_owners", None) or {}):
            if self.chain_owners[c9] and self._nonevm_adapter(c9) is not None:
                scopes.append((c9, "nonevm"))
        out = []
        for chain, kind in scopes:
            ws = (sorted(self.sol_wallets) if kind == "sol" else sorted(self.chain_owners.get(chain) or ()) if kind == "nonevm"
                  else sorted(self.my_wallets.get(chain, set())))
            if ws and not self._meta_get(f"recon_done_{chain}"):
                out.append((chain, kind, "chain", ws))
        return out

    @staticmethod
    def _prov_pack(bal: dict, mode: str, t0: float, req=None, t1: float = None, kind: str = None) -> dict:
        bal = bal or {}
        per = bal.get("per_wallet") or {}
        meta = bal.get("_meta") or {}
        hold = set(bal.get("_hold") or ())
        qd = bal.get("_queried") if bal.get("_source") == "rpc" and isinstance(bal.get("_queried"), dict) else None
        un = bal.get("_unobs") if isinstance(bal.get("_unobs"), dict) else {}
        zeros = bal.get("_zero") if isinstance(bal.get("_zero"), dict) else {}
        rpc9 = bal.get("_source") == "rpc"
        blk9, bts9 = bal.get("_block"), bal.get("_block_ts")
        out = {"mode": mode, "at": int(t0), "t1": int(t1 if t1 is not None else t0), "wallets": {}}
        if rpc9 and isinstance(blk9, int) and not isinstance(blk9, bool) and isinstance(bts9, int) and not isinstance(bts9, bool):
            out["block"], out["bts"] = blk9, bts9
        if req is not None:
            out["req"] = sorted(str(w) for w in req)
        for w, wb in per.items():
            if w in hold or not isinstance(wb, dict):
                continue
            d = {"tok": {}}
            for key, amt in wb.items():
                try:
                    k2, addr = key
                    a9 = int(amt)
                except (TypeError, ValueError):
                    continue
                if a9 < 0:
                    continue
                if k2 == "native":
                    d["native"] = str(a9)
                else:
                    sym, dec = (meta.get(addr) or (None, None))[:2]
                    d["tok"][str(addr)] = [str(a9), sym, dec]
            for ca in zeros.get(w) or ():
                if ca:
                    d["tok"].setdefault(str(ca), ["0", None, None])
            if qd is not None:
                d["q"] = sorted({str(x).lower() for x in (qd.get(w) or ())})
            elif kind != "sol":
                d["q"] = sorted({str(x).lower() for x in d["tok"]})
            if un.get(w):
                d["unobs"] = sorted({str(x).lower() for x in un[w]})
            out["wallets"][str(w)] = d
        return out

    def prov_pass(self):
        now = time.time()
        jobs = self.__dict__.setdefault("_prov_jobs", {})
        done9 = any(j["ev"].is_set() for j in jobs.values())
        if now - float(self.__dict__.get("_prov_last") or 0) < self.PROV_TICK and not done9:
            return
        self._prov_last = now
        p = paths.state(self.PROV_FILE)
        if self.recon_months <= 0:
            if os.path.exists(p):
                os.remove(p)
            return
        try:
            st = statefile.read_json(p, {})
        except (Exception, SystemExit) as _cg9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("core_prov:ProvMixin.prov_pass[st#1]", _cg9)
            st = {}
        st = st if isinstance(st, dict) else {}
        tg = {c: (k, m, ws) for c, k, m, ws in self._prov_targets()}
        changed = False
        for c in [c for c in st if c not in tg]:
            st.pop(c, None)
            changed = True
        for c in [c for c, j in jobs.items() if j["ev"].is_set()]:
            job = jobs.pop(c)
            kind, mode, ws = tg.get(c) or (None, None, None)
            if kind is None:
                continue
            if job["bal"] is not None and job["mode"] == mode and job["wallets"] == ws:
                st[c] = self._prov_pack(job["bal"], mode, job["t0"], req=ws, t1=job.get("t1"), kind=kind)
                if job.get("fast"):
                    st[c]["fast"] = int(job["fast"])
                if kind == "sol":
                    st[c]["stake_ts"] = int((job["bal"] or {}).get("_stake_ts") or 0)
                    st[c]["stake_live"] = int((job["bal"] or {}).get("_stake_live") or 0)
                if any(s9 == "pending" for s9 in (((job["bal"] or {}).get("_disc") or {}).get("status") or {}).values()):
                    st[c]["fast"] = 3
                changed = True
            elif job["err"] is not None:
                calcguard.swallowed("core_prov:ProvMixin.prov_pass[st#2]", job["err"])
                log.info("임시 잔고 %s 조회 실패(다음 바퀴): %s", c, logs.safe_err(job["err"])[:120])
        def _fresh(c, ws):
            ent = st.get(c)
            return isinstance(ent, dict) and ent.get("mode") == tg[c][1] \
                and (ent.get("req") or sorted((ent.get("wallets") or {}).keys())) == sorted(str(w) for w in ws)
        have_all = all(_fresh(c, ws) for c, (_k, _m, ws) in tg.items())
        rj9 = self.__dict__.get("_recon_jobs") or {}
        sst9 = 0
        if any(k9 == "sol" for k9, _m9, _w9 in tg.values()):
            try:
                sd9 = statefile.read_json(paths.state("sol_stake.json"), {}) or {}
                t9 = int(float(sd9.get("ts") or 0)) if isinstance(sd9.get("accounts"), dict) else 0
                sst9 = t9 if now - t9 <= 3 * 3600 else 0
            except (Exception, SystemExit) as _cg9:   # noqa: BLE001 [fallback]
                calcguard.swallowed("core_prov:ProvMixin.prov_pass[sd9]", _cg9)
                sst9 = 0
        def _rank(c, ws):
            return (self.PROV_ORDER.index(c) if c in self.PROV_ORDER else len(self.PROV_ORDER), -len(ws), c)
        for c, (kind, mode, ws) in sorted(tg.items(), key=lambda kv: (_fresh(kv[0], kv[1][2]),) + _rank(kv[0], kv[1][2])):
            if c in jobs:
                continue
            ent = st.get(c)
            alch9 = False
            stake9 = False
            if _fresh(c, ws):
                age9 = now - float(ent.get("at") or 0)
                f9 = int(ent.get("fast") or 0)
                alch9 = f9 == 1 and kind in ("evm", "bsc") and self._prov_alch_ok(c)
                stake9 = kind == "sol" and sst9 > int(ent.get("stake_ts") or 0)
                due9 = alch9 or stake9 or (f9 == 1 and kind in ("evm", "bsc")) or f9 == 3 or (f9 and have_all and age9 >= self.PROV_FAST_UPGRADE)
                if not due9 and age9 < self.PROV_EVERY:
                    continue
            first9 = not _fresh(c, ws)
            fast9 = (1 if first9 and kind in ("evm", "bsc") else 2 if alch9 else 0)
            lane9 = "par" if (first9 or stake9) else "alch" if alch9 else "disc"
            if first9 or stake9:
                if sum(1 for j in jobs.values() if j.get("par")) >= self.PROV_PAR:
                    continue
            elif any(j.get("lane") == lane9 for j in jobs.values()):
                continue
            if kind == "nonevm" and any(k9[0] == c and not j9["ev"].is_set() for k9, j9 in rj9.items()):
                continue
            try:
                fn = self._recon_fetch_plan(c, kind, ws, {1: "fast", 2: "fastx"}.get(fast9), latest=True)
            except Exception as e:   # noqa: BLE001 [isolate]
                calcguard.swallowed("core_prov:ProvMixin.prov_pass[fn]", e)
                log.info("임시 잔고 %s 조회 준비 실패(다음 바퀴): %s", c, logs.safe_err(e)[:120])
                continue
            job = {"wallets": ws, "mode": mode, "t0": now, "bal": None, "err": None, "ev": threading.Event(), "fast": fast9, "par": first9 or stake9, "lane": lane9}

            def _run(job=job, fn=fn):
                try:
                    job["bal"] = fn()
                except BaseException as e:   # noqa: BLE001 [fallback]
                    job["err"] = e
                    calcguard.swallowed("core_prov:ProvMixin.prov_pass._run", e)
                finally:
                    job["t1"] = time.time()
                    job["ev"].set()
            jobs[c] = job
            threading.Thread(target=_run, name=f"tj-prov-{c}", daemon=True).start()
        if changed:
            statefile.atomic_write_json(p, st)

    def _streams_have_data(self) -> bool:
        for stream, reader in (("evm", self.reader), ("sol", self.sol_reader),
                               ("bsc", self.bsc_reader)) + tuple(getattr(self, "chain_readers", None) or ()):
            row = self.conn.execute(
                "SELECT seg, off FROM inbox_offsets WHERE stream=?", (stream,)).fetchone()
            seg, off = (row["seg"], row["off"]) if row else (1, 0)
            batch, _, _ = reader.read_batch(seg, off, max_records=1)
            if batch:
                return True
        return False
