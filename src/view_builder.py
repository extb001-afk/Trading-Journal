from __future__ import annotations
import hashlib
import json
import os
import re
import threading
import time
import config, logs, paths, statefile
import db as dbm
import fsio
import pricing
import websnap
import health
import cgca
import nft
import buychart
import netpace
import buildproc
import rawtx_cache
import rabby
import salelink
import day_memo
import addr_ai
from view_review import review_fill_req_view
from view_review import review_len_eff
from view_review import review_pause_eff
from view_review import review_progress
from view_common import BUILD_EX_N
from view_common import BUILD_HIST_N
from view_common import DAILY_V
from view_snapfile import _snapfile_drop
from view_snapfile import _snapfile_load
from view_snapfile import _snapfile_save
from view_snapfile import _snapfile_sig
from view_hero import _publish_snap
from view_evals import BUY_EVALS
from view_evals import DAY_MEMOS
from view_evals import SELL_EVALS
from view_spot import Spot
from view_misc import _BuildObsolete
from view_misc import _cfg_file_sig
from view_detail import DetailApiMixin
from view_workers import WorkersMixin
from view_prov import ProvMixin
from view_load import LoadMixin
from view_outflows import OutflowsMixin
from view_backfill import BackfillMixin
from view_krw import KrwMixin
from view_daily import DailyMixin
from view_index import IndexMixin
from view_reviews import ReviewsMixin
from view_b_replay import ReplayMixin
from view_b_cards import CardsMixin
from view_b_pendings import PendingsMixin
from view_b_outflows import OutflowsBuildMixin
from view_b_daily import DailyBuildMixin
from view_b_futidx import FutIdxMixin
from view_b_tail import TailMixin
DAY_MEMO_REEVAL = None
import logging
import calcguard  # noqa: E402
import accounting_books  # noqa: E402
import accounting_ctx  # noqa: E402

log = logging.getLogger('tj-web')


class StateBuilder(TailMixin, FutIdxMixin, DailyBuildMixin, OutflowsBuildMixin, PendingsMixin, CardsMixin, ReplayMixin, ReviewsMixin, IndexMixin, DailyMixin, KrwMixin, BackfillMixin, OutflowsMixin, LoadMixin, ProvMixin, WorkersMixin, DetailApiMixin):
    LEDGER_GEN = 2
    skip_gen_check = False
    SNAP_TTL = 5
    SNAP_STALE_MAX = 6 * 3600
    BUILD_DUTY = 2.0
    REFRESH_SEC = 15
    ACTIVE_SEC = 90
    INPUT_MAX_AGE = 60
    KEEP_DIAG = os.environ.get("TJ_REPLAY_DEBUG") == "1" or os.environ.get("TJ_KEEP_DIAG") == "1"
    UB_KRW_KEEP_SEC = 86400
    _SIG_SKIP = frozenset(("web_diag.json", "daily_cache.json", "daily_px.json", "px_cache_web.json", "backfill_status.json",
                           "upbit_orders_state.json", "ledger.db-shm", "pending_dm.jsonl.1",
                           "alert_watch.json",
                           "curve_hist.json", "curve_hist_px.json",
                           "search.db", "search.db-wal", "search.db-shm",
                           rawtx_cache.FILE,
                           "web_snap_last.bin", "web_snap_last.bin.tmp",
                           "day_memos.json",
                           "addr_tier_req.json")
                          + nft.STATE_FILES)
    _SIG_SKIP_RX = re.compile(r"^(cursor_|emitted_|enrich_|pending_detail_|health_|alerts_|runner_)|(token_meta|mint_meta)[\w.-]*\.json$"
                              r"|\.(lock|tmp|pending|log)$|\.bak|\.absent|^" + re.escape(fsio.TMP_PREFIX))

    _SIG_CONTENT = ("outflow_decisions.json", "ui_prefs.json")
    PREFS_NOBUILD = frozenset(("alert_prefs", "alert_prefs_v1",
                               "chain_auto_off",
                               "review_len", "review_pause", "review_fill",
                               "first_seen_note",
                               "plans"))

    def _sig_content(self, name, st9):
        key9 = (st9.st_mtime_ns, st9.st_size, st9.st_ino)
        memo9 = self.__dict__.setdefault("_sigc_memo", {})
        hit9 = memo9.get(name)
        prov9 = frozenset(((self.__dict__.get("_of_auto") or {}).get("proven") or {})) if name == "outflow_decisions.json" else None
        if hit9 is not None and hit9[0] == key9 and hit9[1] == prov9:
            return hit9[2]
        try:
            with open(paths.state(name), "rb") as f9:
                d9 = json.loads(f9.read().decode("utf-8"))
            if not isinstance(d9, dict):
                raise ValueError("not dict")
            if name == "outflow_decisions.json":
                v9 = self._dec_build_view(d9, prov9)
            else:
                v9 = self._prefs_build_view(d9)
            h9 = ("c", hashlib.sha1(json.dumps(v9, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest())
        except (OSError, ValueError, TypeError):
            h9 = ("s",) + key9
        memo9[name] = (key9, prov9, h9)
        return h9

    @staticmethod
    def _dec_build_view(d9, proven=None):
        dd9 = d9.get("decisions") if isinstance(d9.get("decisions"), dict) else {}
        out9 = {}
        for a9, v9 in dd9.items():
            if not isinstance(v9, dict):
                out9[a9] = v9
                continue
            w9 = {k9: x9 for k9, x9 in v9.items() if k9 not in ("memo", "ts")}
            nm9 = salelink.dest_name(a9, v9)
            if nm9 != salelink.dest_name(a9, {}):
                w9["_nm"] = nm9
            if w9 or proven is None or a9 in proven:
                out9[a9] = w9
        return {"v": d9.get("version"), "d": out9, "x": sorted(k9 for k9 in d9 if k9 not in ("decisions", "version", "updated"))}

    @classmethod
    def _prefs_build_view(cls, d9):
        return {k9: v9 for k9, v9 in d9.items() if k9 not in cls.PREFS_NOBUILD}

    def _rtxc(self):
        r9 = self.__dict__.get("_rtx")
        if r9 is None:
            r9 = self._rtx = rawtx_cache.RawTxCache(paths.STATE_DIR, paths.DB_PATH)
        return r9

    def _input_sig(self):
        try:
            sig = []
            for p9 in (paths.CONFIG_PATH,):
                st9 = os.stat(p9) if os.path.exists(p9) else None
                sig.append((p9, st9.st_mtime_ns, st9.st_size) if st9 else (p9, 0, 0))
            with os.scandir(paths.STATE_DIR) as it9:
                for e9 in it9:
                    n9 = e9.name
                    if n9 in self._SIG_SKIP or self._SIG_SKIP_RX.search(n9) or not e9.is_file(follow_symlinks=False):
                        continue
                    st9 = e9.stat(follow_symlinks=False)
                    if n9 in self._SIG_CONTENT:
                        sig.append((n9,) + self._sig_content(n9, st9))
                    else:
                        sig.append((n9, st9.st_mtime_ns, st9.st_size))
            return tuple(sorted(sig))
        except OSError:
            return None

    def _min_gap(self) -> float:
        return max(float(self.SNAP_TTL), float(getattr(self, "build_ms", 0) or 0) / 1000.0 * self.BUILD_DUTY)

    def inputs_changed(self, snap=None, now=None) -> bool:
        now = time.time() if now is None else now
        if snap is None or now - snap.at >= self.INPUT_MAX_AGE or self._built_sig is None:
            return True
        return self._input_sig() != self._built_sig

    @property
    def cache(self):
        return self.__dict__.get("_cache")

    @cache.setter
    def cache(self, v):
        if v is None:
            self.__dict__["_inval"] = self.__dict__.get("_inval", 0) + 1
            if self.__dict__.get("_snapfile_on"):
                _snapfile_drop()
        self.__dict__["_cache"] = v

    def __init__(self):
        self._cfg_hot_sig = _cfg_file_sig()
        self.cfg = config.load_config()
        self.addr_label = self._label_map(self.cfg)
        self.spot = Spot()
        self._spot_off()
        try:
            self.spot.min_reserve_usd = float((self.cfg.get("price_guard") or {}).get(
                "min_reserve_usd", Spot.MIN_RESERVE_USD))
        except (TypeError, ValueError):
            self.spot.min_reserve_usd = Spot.MIN_RESERVE_USD
        try:
            self.spot.dex_max_age = max(float(Spot.DEX_FRESH_SEC), float((self.cfg.get("price_guard") or {}).get(
                "dex_max_age_sec", Spot.DEX_MAX_AGE_SEC)))
        except (TypeError, ValueError):
            self.spot.dex_max_age = Spot.DEX_MAX_AGE_SEC
        self.px = pricing.PxCache(paths.state("px_cache_web.json"))
        self._pxq = pricing.PxFetchQueue(self.px)
        self.daily = statefile.read_json(paths.state("daily_cache.json"), {}) if os.path.exists(paths.state("daily_cache.json")) else {}
        if self.daily.get("_v") != DAILY_V:
            if any(not str(k).startswith("_") for k in self.daily):
                log.info("일별 캐시 v%s → v%s: 마감값 정의 통일로 지난날 1회 재계산", self.daily.get("_v"), DAILY_V)
            live9 = self.daily.get("_live") if self.daily.get("_v") == 3 and isinstance(self.daily.get("_live"), dict) else None
            self.daily = {"_v": DAILY_V}
            if live9:
                self.daily["_live"] = live9
        dpx9 = statefile.read_json(paths.state("daily_px.json"), {}) if os.path.exists(paths.state("daily_px.json")) else {}
        self.daily_px = dpx9 if isinstance(dpx9, dict) and dpx9.get("_v") == 1 else {"_v": 1}
        seed9 = statefile.read_json(paths.state("daily_px_seed.json"), {}) if os.path.exists(paths.state("daily_px_seed.json")) else {}
        self._daily_seed = {k9: v9 for k9, v9 in (seed9 or {}).items()
                            if not str(k9).startswith("_") and isinstance(v9, dict) and v9.get("src") == "live"
                            and isinstance(v9.get("g"), dict)}
        self._upbit_krw_tl = None
        self._bt_krw_tl = None
        self._rtx = rawtx_cache.RawTxCache(paths.STATE_DIR, paths.DB_PATH)
        self.cache = None
        self.cache_at = 0.0
        self.lock = threading.Lock()
        self.snaps = websnap.SnapStore()
        self._build_err = None
        self._refreshing = False
        self._last_client = 0.0
        self._built_sig = None
        try:
            wd0 = (statefile.read_json(paths.state("web_diag.json"), {}) or {}) if os.path.exists(paths.state("web_diag.json")) else {}
            bh0 = wd0.get("build_hist") if isinstance(wd0, dict) else None
            if isinstance(bh0, list):
                self._build_hist = [int(x) for x in bh0 if isinstance(x, (int, float)) and not isinstance(x, bool)][-BUILD_HIST_N:]
            bx0 = wd0.get("build_ex") if isinstance(wd0, dict) else None
            if isinstance(bx0, list):
                self._build_ex = [{"ms": int(x["ms"]), "at": int(x["at"]), "why": str(x.get("why") or "")[:20]} for x in bx0
                                  if isinstance(x, dict) and isinstance(x.get("ms"), (int, float)) and isinstance(x.get("at"), (int, float))][-BUILD_EX_N:]
        except (Exception, SystemExit) as _cg9:  # noqa: BLE001 [optional]
            calcguard.swallowed("view_builder:StateBuilder.__init__", _cg9)
            pass
        self.build_lock = threading.Lock()
        self._origin_pending = set()
        self._origin_lock = threading.Lock()
        threading.Thread(target=self._origin_worker, daemon=True, name="origin-worker").start()
        netpace.configure(self.cfg)
        self._sale_queue, self._sale_queue_t, self._sale_prio = [], 0, set()
        threading.Thread(target=self._sale_worker, daemon=True, name="sale-worker").start()
        self._xc_pending = []
        self._xc_lock = threading.Lock()
        threading.Thread(target=self._xchain_worker, daemon=True, name="xchain-worker").start()
        self._flow_pending = []
        self._flow_lock = threading.Lock()
        threading.Thread(target=self._flow_worker, daemon=True, name="flow-worker").start()
        self._bot_wallet_usd = rabby.load_bot_usd(paths.state(rabby.BOTUSD_NAME))
        self._lp_targets = []
        self._lp_lock = threading.Lock()
        threading.Thread(target=self._lp_worker, daemon=True, name="lp-worker").start()
        threading.Thread(target=self._rabby_worker, daemon=True, name="rabby-worker").start()
        self._addr_ai_targets = []
        self._addr_ai_paused = lambda: review_pause_eff(self.prefs()).get("on")
        self._addr_ai_busy = lambda: bool(SELL_EVALS.running or BUY_EVALS.running)
        threading.Thread(target=addr_ai.worker_loop, args=(self,), daemon=True, name="addr-ai-worker").start()

    def _hist_wallets(self) -> list:
        return config.history_wallets(self.cfg)

    @staticmethod
    def _chain_disp_wallets(cfg) -> list:
        try:
            import chain_registry as _cr9
            rows9 = _cr9.wallets(cfg)
        except Exception as _cg9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_builder:StateBuilder._chain_disp_wallets", _cg9)
            return []
        return [{"chain": r9["chain"], "network": r9["network"], "key": r9["key"], "label": r9["label"],
                 "disp": "" if r9["mode"] == "descriptor" else str(r9["display"] or ""), "name": _cr9.display_name(r9["chain"])}
                for r9 in rows9 if r9.get("key")]


    def _spot_off(self):
        off = set(self.cfg.get("_disabled_chains") or ())
        self.spot.off_chains = off
        if not off:
            return
        try:
            raw9 = statefile.read_json(paths.CONFIG_PATH, {}) or {}
        except (Exception, SystemExit) as _cg9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_builder:StateBuilder._spot_off", _cg9)
            raw9 = {}
        now9 = time.time()
        for ch9 in off:
            cc9 = (raw9.get("chains") or {}).get(ch9) if isinstance(raw9.get("chains"), dict) else None
            mk9 = cc9.get("_chainoff") if isinstance(cc9, dict) else None
            at9 = mk9.get("at") if isinstance(mk9, dict) else None
            if not (isinstance(at9, (int, float)) and not isinstance(at9, bool) and 0 < at9 <= now9):
                ts9 = [float(v) for k, v in (self.spot.dex_ts or {}).items() if str(k).startswith(ch9 + ":") and isinstance(v, (int, float))]
                at9 = max(ts9) if ts9 else now9
            self.spot.off_at[ch9] = float(at9)


    CANCEL_PH = frozenset(("prep", "load·replay", "outflow_dest·match", "rt_same", "xfer_links·positions", "signer·cards", "cex_proof·prices", "pendings"))

    def _ph(self, name):
        cur = self.__dict__.get("_ph_cur")
        if cur is None:
            return
        t = time.time()
        cur.append((name, int((t - self.__dict__.get("_ph_t", t)) * 1000)))
        self._ph_t = t
        g0 = self.__dict__.get("_ph_gen0")
        if g0 is not None and name in self.CANCEL_PH and self._inval_now() != g0:
            raise _BuildObsolete(name)

    def _rb_mark(self):
        try:
            d9 = statefile.read_json(paths.state("ext_rebuild_status.json"), {}) if os.path.exists(paths.state("ext_rebuild_status.json")) else {}
        except (Exception, SystemExit) as _cg9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_builder:StateBuilder._rb_mark", _cg9)
            return False, None
        if not isinstance(d9, dict):
            return False, None
        try:
            lim9 = float(((getattr(self, "cfg", None) or {}).get("backfill") or {}).get("rebuild_timeout_sec") or 5400) + 600
        except (TypeError, ValueError, AttributeError):
            lim9 = 6000.0
        try:
            st9 = float(d9.get("started_at") or 0)
            run9 = bool(d9.get("running")) and st9 > 0 and time.time() - st9 < lim9
        except (TypeError, ValueError):
            run9 = False
        ra9 = d9.get("rebuilt_at")
        return run9, (int(ra9) if isinstance(ra9, (int, float)) and not isinstance(ra9, bool) else None)

    def _build_sample_ex(self, rb0, rb1):
        prev = self.__dict__.get("_rb_gen")
        self._rb_gen = rb1[1]
        if rb0[0] or rb1[0]:
            return "rebuild"
        if prev is not None and rb1[1] is not None and rb1[1] != prev:
            return "swap"
        return None

    def _ph_note(self, total_ms, ex=None):
        ph = [[n9, ms9] for n9, ms9 in (self.__dict__.get("_ph_cur") or [])]
        rec = {"ms": int(total_ms), "at": int(time.time()), "ph": ph, "warm": bool(self.__dict__.get("_build_warm"))}
        if ex:
            rec["ex"] = ex
        hist = self.__dict__.setdefault("_ph_hist", [])
        hist.append(rec)
        del hist[:-BUILD_HIST_N]
        self._ph_last = rec
        if total_ms >= 20000:
            top9 = sorted(ph, key=lambda x9: -x9[1])[:3]
            log.info("빌드 단계(느림 %.1f초): %s", total_ms / 1000, " · ".join(f"{n9} {ms9 / 1000:.1f}초" for n9, ms9 in top9))

    def _ph_view(self):
        hist = ([r9 for r9 in (self.__dict__.get("_ph_hist") or []) if r9.get("warm") and not r9.get("ex")]
                or list(self.__dict__.get("_ph_hist") or []))
        slow = max(hist, key=lambda r9: r9["ms"]) if hist else None
        return {"last": self.__dict__.get("_ph_last"), "slow": slow}

    def build(self) -> dict:
        with self.lock:
            if self.cache and time.time() - self.cache_at < 5:
                return self.cache
        with self.build_lock:
            with self.lock:
                if self.cache and time.time() - self.cache_at < 5:
                    return self.cache
                building = {}
                self.cache = building
                gen0 = self.__dict__.get("_inval", 0)
            obsolete9 = None
            mp0 = self.__dict__.get("_mp_n", 0)
            sig9 = self._input_sig()
            try:
                self._cfg_hot_refresh()
            except Exception as e9:   # noqa: BLE001 [optional]
                calcguard.swallowed("view_builder:StateBuilder.build", e9)
                log.warning("설정 다시 읽기 실패(종전 값으로 빌드): %s", type(e9).__name__)
            conn = None
            rb0_9 = self._rb_mark()
            try:
                t0_9 = time.time()
                self._ph_cur, self._ph_t = [], t0_9
                self._ph_gen0 = gen0
                out = self._build_child()
                if out is None:
                    buildproc.note_inproc()
                    conn = dbm.open_db(paths.DB_PATH, readonly=True)
                    conn.execute("BEGIN")
                    nb9 = getattr(self.px, "nb_begin", None)
                    if nb9:
                        nb9()
                    try:
                        with buildproc.nogc():
                            out = self._build(conn)
                    finally:
                        if nb9:
                            self._pxq.add(self.px.nb_end())
                self._ph("reviews·tail")
                self._prefid_persist()
                self.build_ms = int((time.time() - t0_9) * 1000)
                ex9 = self._build_sample_ex(rb0_9, self._rb_mark())
                self._ph_note(self.build_ms, ex9)
                bh9 = self.__dict__.setdefault("_build_hist", [])
                if not self.__dict__.get("_build_warm"):
                    self._build_warm = True
                    self._build_cold_ms = self.build_ms
                elif ex9:
                    bx9 = self.__dict__.setdefault("_build_ex", [])
                    bx9.append({"ms": self.build_ms, "at": int(time.time()), "why": ex9})
                    del bx9[:-BUILD_EX_N]
                else:
                    bh9.append(self.build_ms)
                    del bh9[:-BUILD_HIST_N]
                if self.build_ms >= 20000:
                    log.info("빌드 %.1f초 (느림 — %s)", self.build_ms / 1000,
                             {"rebuild": "원장 재구축과 겹침 · p95 표본 제외", "swap": "원장 교체 직후 첫 빌드 · p95 표본 제외"}.get(ex9 or "", "보유·기록 규모 또는 원장 잠금 확인"))
            except _BuildObsolete as e:
                obsolete9 = str(e)
            except BaseException as e:
                self._build_err = f"{type(e).__name__}: {logs.safe_err(e)}"
                raise
            finally:
                self._ph_gen0 = None
                if conn is not None:
                    conn.close()
            if obsolete9 is not None:
                log.info("빌드 도중 사용자 변경(%s 단계 뒤 %.1f초) — 이 빌드는 그만두고 곧바로 새로 빌드", obsolete9, time.time() - t0_9)
                published = False
            else:
                published, out = self._publish_built(out, gen0, mp0, sig9, building)
        if obsolete9 is not None:
            return self.build()
        if published and self.snaps.wanted:
            threading.Thread(target=self.snaps.precompute, daemon=True, name="snap-delta").start()
        return out

    def _build_child(self):
        if not buildproc.usable():
            return None
        q9 = buildproc.qsnap_of(self)
        res = buildproc.run(self)
        if res is None:
            return None
        if res[0] == "obsolete":
            raise _BuildObsolete(res[1])
        _k9, out, pay = res
        self._ph_cur = list(pay.get("ph") or [])
        if pay.get("ph_t"):
            self._ph_t = float(pay["ph_t"])
        buildproc.apply(self, pay, q9)
        cw9 = self.__dict__.get("_cgca_want")
        if isinstance(cw9, tuple) and len(cw9) == 2:
            cgca.want(*cw9)
        return out

    @staticmethod
    def _label_map(cfg) -> dict:
        out = {}
        for w in config.history_wallets(cfg):
            a = w["address"] if w.get("type") == "sol" else w["address"].lower()
            if w.get("label"):
                out[a] = w["label"]
        for cw in StateBuilder._chain_disp_wallets(cfg):
            if cw["label"]:
                out.setdefault(cw["key"], cw["label"])
        return out

    def _cfg_hot_refresh(self) -> bool:
        sig9 = _cfg_file_sig()
        if sig9 is None or sig9 == self.__dict__.get("_cfg_hot_sig"):
            return False
        try:
            with open(paths.CONFIG_PATH, "r", encoding="utf-8") as f9:
                raw9 = json.load(f9)
        except (OSError, ValueError):
            return False
        if not isinstance(raw9, dict):
            return False
        self.__dict__["_cfg_hot_sig"] = sig9
        cfg9 = self.cfg if isinstance(self.cfg, dict) else None
        if cfg9 is None:
            return False

        def akey(w):
            a9 = str(w.get("address") or "")
            return a9 if w.get("type") == "sol" else a9.lower()
        by_row, by_addr = {}, {}
        for w in raw9.get("wallets") or []:
            if not isinstance(w, dict) or not w.get("address"):
                continue
            lab0 = w.get("label") if isinstance(w.get("label"), str) else ""
            by_row.setdefault((w.get("type", "evm"), w.get("chain"), akey(w)), lab0)
            if w.get("type", "evm") in ("evm", "bsc_rpc"):
                by_addr.setdefault(akey(w), lab0)
        n9 = 0
        for k9 in ("wallets", "_disabled_wallets"):
            for w in cfg9.get(k9) or []:
                if not isinstance(w, dict) or not w.get("address"):
                    continue
                key9 = akey(w) if w.get("_auto") else (w.get("type", "evm"), w.get("chain"), akey(w))
                src9 = by_addr if w.get("_auto") else by_row
                if key9 not in src9:
                    continue
                lab9 = src9[key9]
                if lab9 != (w.get("label") or ""):
                    if lab9 or w.get("_auto"):
                        w["label"] = lab9
                    else:
                        w.pop("label", None)
                    n9 += 1
        pw9 = raw9.get("perp_wallets")
        if pw9 != cfg9.get("perp_wallets"):
            if pw9 is None:
                cfg9.pop("perp_wallets", None)
            else:
                cfg9["perp_wallets"] = json.loads(json.dumps(pw9))
            n9 += 1
        if n9:
            self.addr_label = self._label_map(cfg9)
            log.info("설정 다시 읽음(재시작 없이): 지갑 별명·퍼프 주소 %d칸", n9)
        return bool(n9)

    def _thread_names(self):
        if self.__dict__.get("_bp_shm") is not None and isinstance(self.__dict__.get("_bp_threads"), list):
            return list(self.__dict__["_bp_threads"])
        return [t9.name for t9 in threading.enumerate()]

    def _inval_now(self):
        shm = self.__dict__.get("_bp_shm")
        return buildproc.shm_get(shm) if shm is not None else self.__dict__.get("_inval", 0)

    def _publish_built(self, out, gen0, mp0, sig9, building):
        if True:
            with self._publock():
                if self.__dict__.get("_mp_n", 0) != mp0:
                    try:
                        out = self._mp_apply(out, self.__dict__.get("_mp_kinds") or frozenset())
                    except Exception as e:   # noqa: BLE001 [optional]
                        calcguard.swallowed("view_builder:StateBuilder._publish_built[nogc]", e)
                        log.warning("칸 고치기(빌드 뒤) 실패(무시): %s", type(e).__name__)
                with self.lock:
                    published = self.cache is building
                    if published:
                        self.cache = out
                        self.cache_at = time.time()
                        self._last_out, self._last_out_at, self._last_out_gen = out, self.cache_at, gen0
                        self._built_sig = sig9
                if published:
                    self._publish(out, gen0)
            try:
                self._rtxc().maybe_save()
            except Exception as e:   # noqa: BLE001 [optional]
                calcguard.swallowed("view_builder:StateBuilder._publish_built[t0_9]", e)
                log.warning("raw_txs 캐시 저장 실패(무시): %s", e)
        return published, out

    def soft_invalidate(self, kick: bool = True):
        with self.lock:
            c9 = self.__dict__.get("_cache")
            if isinstance(c9, dict) and not c9:
                if kick:
                    self._soft_dirty = True
            else:
                self.__dict__["_cache"] = None
        if kick:
            self.kick_refresh()

    def _publock(self):
        l9 = self.__dict__.get("_pub_lock")
        if l9 is None:
            with self.lock:
                l9 = self.__dict__.get("_pub_lock")
                if l9 is None:
                    l9 = self._pub_lock = threading.Lock()
        return l9

    MP_KINDS = frozenset(("of_memo", "day_memo", "plan", "review", "fsnote"))

    def mpatch(self, kinds) -> bool:
        kinds = frozenset(kinds) & self.MP_KINDS
        if not kinds:
            return False
        try:
            with self.lock:
                self._mp_n = self.__dict__.get("_mp_n", 0) + 1
                self._mp_kinds = frozenset(self.__dict__.get("_mp_kinds") or frozenset()) | kinds
            with self._publock():
                with self.lock:
                    base, gen = self.__dict__.get("_last_out"), self.__dict__.get("_last_out_gen")
                    cur9 = self.snaps.cur
                    ok = (base is not None and gen == self.__dict__.get("_inval", 0) and cur9 is not None and cur9.gen == gen
                          and self._build_err is None)
                if not ok:
                    return False
                new = self._mp_apply(base, kinds)
                with self.lock:
                    if self.__dict__.get("_last_out") is not base or self.__dict__.get("_inval", 0) != gen:
                        return False
                    self._last_out = new
                    if self.__dict__.get("_cache") is base:
                        self.__dict__["_cache"] = new
                if self.__dict__.get("_snapfile_on"):
                    _snapfile_drop()
                self._publish(new, gen, at=cur9.at)
                return self._build_err is None
        except Exception as e:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_builder:StateBuilder.mpatch", e)
            log.warning("칸 고치기 실패(종전 무효화로): %s", type(e).__name__)
            return False

    def _mp_apply(self, out, kinds):
        f = out.get("fields") if isinstance(out, dict) else None
        if not isinstance(f, dict):
            raise ValueError("fields 없음")
        g = dict(f)
        if "of_memo" in kinds:
            dec = self.outflow_decisions()
            old_m = {}
            rows = []
            for r9 in f.get("outflows") or []:
                if isinstance(r9, dict) and "address" in r9:
                    d9 = dec.get(r9["address"]) if isinstance(dec.get(r9["address"]), dict) else {}
                    old_m[r9["address"]] = r9.get("memo")
                    if r9.get("memo") != d9.get("memo") or r9.get("decidedTs") != d9.get("ts"):
                        r9 = dict(r9, memo=d9.get("memo"), decidedTs=d9.get("ts"))
                rows.append(r9)
            g["outflows"] = rows
            dep = []
            for r9 in f.get("depositRows") or []:
                a9 = r9.get("addr") if isinstance(r9, dict) else None
                v9 = dec.get(a9) if isinstance(a9, str) and isinstance(dec.get(a9), dict) else None
                if v9 is not None and v9.get("verdict") == "exchange" and a9 in old_m:
                    om9 = old_m[a9]
                    if r9.get("memo") == "보낸 내역 판정" + (f" · {om9}" if om9 else "") and r9.get("ex") == (v9.get("exchange") or "?"):
                        nm9 = "보낸 내역 판정" + (f" · {v9['memo']}" if v9.get("memo") else "")
                        if nm9 != r9.get("memo"):
                            r9 = dict(r9, memo=nm9)
                dep.append(r9)
            g["depositRows"] = dep
        if "day_memo" in kinds:
            mm9, err9 = DAY_MEMOS.read()
            if err9 or "dayMemosErr" in f or "dayMemos" not in f:
                raise ValueError("근거 메모 파일 이상")
            g["dayMemos"] = mm9
        if "plan" in kinds:
            if "plans" not in f or "planMemos" not in f:
                raise ValueError("계획 칸 없음")
            g["plans"], g["planMemos"] = self._plans_view(self._prefid_eff(self.prefs()))
        if "review" in kinds:
            pr9 = self.prefs()
            for k9, v9 in (("reviewLen", review_len_eff(pr9)), ("reviewPause", review_pause_eff(pr9)),
                           ("reviewFill", review_progress.fill_eff(pr9.get("review_fill")) if review_progress is not None else None)):
                if k9 not in f:
                    raise ValueError("리뷰 칸 없음")
                g[k9] = v9
            if isinstance(f.get("reviewProgress"), dict):
                g["reviewProgress"] = dict(f["reviewProgress"], fillReq=review_fill_req_view())
        if "fsnote" in kinds:
            fs9 = f.get("firstSeen")
            if not isinstance(fs9, dict):
                raise ValueError("firstSeen 칸 없음")
            g["firstSeen"] = dict(fs9, note=bool(self.prefs().get("first_seen_note")))
        return dict(out, fields=g)

    @staticmethod
    def _plans_view(prefs):
        plans_out = {}
        plan_memos = {}
        for k, p in (prefs.get("plans") or {}).items():
            if isinstance(p, dict) and isinstance(p.get("memo"), str) and p.get("memo").strip():
                plan_memos[k] = p["memo"]
            try:
                t = float(p.get("target") or 0)
                s = float(p.get("stop") or 0)
            except (TypeError, ValueError):
                t = s = 0
            if 0 < s < t < float("inf"):
                plans_out[k] = {"target": t, "stop": s, "src": p.get("src") or "CEX",
                                "venue": p.get("venue") or "감시 중",
                                "tags": p.get("tags") or [],
                                "memo": p.get("memo") or ""}
        return plans_out, plan_memos

    def _publish(self, out, gen, at=None):
        try:
            try:
                pub = dict(out, health=health.compact(health.web_view()))
            except Exception as e:  # noqa: BLE001 [fallback]
                calcguard.swallowed("view_builder:StateBuilder._publish[pub]", e)
                log.warning("health 요약 실패(무시): %s", e)
                pub = out
            snap9 = _publish_snap(pub, gen, out)
            if at is not None:
                snap9.at = float(at)
            self.snaps.publish(snap9)
            self._build_err = None
            if self.__dict__.get("_snapfile_on") and gen == self.__dict__.get("_inval", 0):
                _snapfile_save(snap9, still_ok=lambda: self.__dict__.get("_inval", 0) == gen)
        except Exception as e:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_builder:StateBuilder._publish[blk]", e)
            self._build_err = f"publish {type(e).__name__}: {logs.safe_err(e)}"
            log.warning("스냅샷 게시 실패: %s", e)

    def restore_snapfile(self) -> bool:
        ok = False
        try:
            _snapfile_sig()
        except Exception as e:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_builder:StateBuilder.restore_snapfile[_snapfile_sig]", e)
            (log.warning if os.path.exists(paths.DB_PATH) else log.debug)("스냅샷 저장본 서명 실패(저장본 끔): %s", type(e).__name__)
            return False
        try:
            with self.lock:
                gen9 = self.__dict__.get("_inval", 0)
            snap = _snapfile_load(gen9, self.SNAP_STALE_MAX)
            if snap is not None:
                with self.lock:
                    if self.snaps.cur is None and self.__dict__.get("_inval", 0) == gen9:
                        self.snaps.publish(snap)
                        ok = True
                if ok:
                    self._restored = True
                    log.info("스냅샷 저장본으로 시작(%d초 전 · 버전 %s) — 배경 빌드로 새로", int(time.time() - snap.at), snap.ver[:8])
                    self.kick_refresh()
        except Exception as e:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_builder:StateBuilder.restore_snapfile[self]", e)
            log.warning("스냅샷 저장본 복원 실패(무시): %s", type(e).__name__)
        self.__dict__["_snapfile_on"] = True
        return ok

    MATS_FREE = frozenset(("/api/state", "/api/v2/state", "/api/v2/part", "/api/health", "/api/wallet_reload",
                           "/api/health/ack", "/api/health/restore"))

    def mats_wait(self, path) -> bool:
        if not self.__dict__.get("_restored") or self.__dict__.get("_last_out") is not None:
            return True
        if not str(path).startswith("/api/") or path in self.MATS_FREE or path == "/api/ops" or str(path).startswith("/api/ops/"):
            return True
        try:
            self.build()
        except Exception as e:   # noqa: BLE001 [optional]
            calcguard.swallowed("view_builder:StateBuilder.mats_wait", e)
            log.warning("첫 빌드 대기 실패(%s): %s", str(path)[:40], type(e).__name__)
        return self.__dict__.get("_last_out") is not None

    def snapshot(self, max_age=None) -> "websnap.Snap":
        now = time.time()
        with self.lock:
            self._last_client = now
            snap = self.snaps.cur
            ok = (snap is not None and snap.gen == self.__dict__.get("_inval", 0)
                  and self._build_err is None and now - snap.at <= self.SNAP_STALE_MAX)
        if ok and max_age is not None and now - snap.at > float(max_age) and self.inputs_changed(snap, now):
            ok = False
        if ok:
            if now - snap.at >= self._min_gap() and self.inputs_changed(snap, now):
                self.kick_refresh()
            return snap
        out = None
        for _ in range(3):
            out = self.build()
            with self.lock:
                snap = self.snaps.cur
                if snap is not None and snap.gen == self.__dict__.get("_inval", 0) and self._build_err is None:
                    return snap
        return websnap.Snap(out, -1)

    def kick_refresh(self):
        with self.lock:
            if self._refreshing:
                return
            self._refreshing = True

        def run():
            try:
                while True:
                    self.build()
                    with self.lock:
                        again = bool(self.__dict__.get("_soft_dirty"))
                        self._soft_dirty = False
                    if not again:
                        break
                    time.sleep(self._min_gap())
            except (Exception, SystemExit) as e:  # noqa: BLE001 [boundary]
                calcguard.swallowed("view_builder:StateBuilder.kick_refresh.run", e)
                log.warning("백그라운드 빌드 실패(다음 요청은 동기 빌드): %s", e)
            finally:
                with self.lock:
                    self._refreshing = False
        threading.Thread(target=run, daemon=True, name="snap-kick").start()

    def latest(self, max_age: float) -> dict:
        with self.lock:
            out, at = self.__dict__.get("_last_out"), float(self.__dict__.get("_last_out_at") or 0)
            ok = out is not None and time.time() - at <= float(max_age) and self.__dict__.get("_last_out_gen") == self.__dict__.get("_inval", 0)
        return out if ok else self.build()

    def _build(self, conn) -> dict:
        inval = dbm.daily_inval_state(conn)
        calcguard.rows_reset()
        rr = self._build_replay(conn)
        _bs9 = rr.screen_scope(inval)
        seal = accounting_books.books_seal(rr.books) if calcguard.strict() else None
        for stage in (self._build_cards, self._build_pendings, self._build_outflows, self._build_daily, self._build_futidx, self._build_tail):
            out = stage(_bs9)
            if calcguard.strict():
                seal = accounting_books.screen_check(seal, rr, _bs9, stage.__name__, accounting_ctx.check_ctx)
        return out


    BF_REQ_PATH = paths.StatePath("backfill_request.json")


    OUTFLOW_SALE_CAT = "세일 참가금"
    OUTFLOW_CATEGORIES = ("송금·결제/선물", OUTFLOW_SALE_CAT, "분실·해킹", "기타")
    OUTFLOW_PATH = paths.StatePath("outflow_decisions.json")


    OF_LINK_KINDS = ("refund", "tokens")
    OF_LINK_MAX = 40
    OF_IN_EVENTS = ("TRANSFER_IN", "PROGRAM_IN", "EX_DEPOSIT", "EXF_DEPOSIT")


    OF_CAND_WINDOW = 60 * 86400
    SALE_CAND_PATH = paths.StatePath("sale_cand_alerts.json")


    _ADDR_RX = re.compile(r"0x[0-9a-fA-F]{40}(?![0-9a-fA-F])")


    OF_LIST_CAP = 200


    KRW_FLOW_EX = (("upbit", "업비트"), ("bithumb", "빗썸"))


    FLOW_SKIP_EV = frozenset(("SWAP", "CONVERT", "EXF_BUY", "EXF_SELL", "EX_BUY", "EX_SELL", "LP_ADD", "LP_REMOVE", "LP_ADJUST",
                              "NOOP", "FAILED", "OPENING", "UNKNOWN"))
    FLOW_KO = {"TRANSFER_OUT": "외부 전송", "TRANSFER_IN": "외부 유입", "PROGRAM_IN": "프로그램 수령", "EXF_ADJUST": "거래소 대사 정정",
               "STAKE_REWARD": "스테이킹 보상",
               "EX_ADJUST": "거래소 대사 정정", "EXF_DEPOSIT": "거래소 입금", "EX_DEPOSIT": "거래소 입금", "EXF_WITHDRAW": "거래소 출금",
               "EX_WITHDRAW": "거래소 출금", "TRANSFER_OUT_EX": "거래소 입금 전송", "TRANSFER_SELF": "내 지갑 이동", "BRIDGE": "브릿지"}

    FLOW_INT_EV = frozenset(("EXF_DEPOSIT", "EX_DEPOSIT", "EXF_WITHDRAW", "EX_WITHDRAW", "TRANSFER_OUT_EX", "TRANSFER_SELF", "BRIDGE"))
    FLOW_OFFC_KO = ("내 다른 계정으로 이동", "내 다른 계정에서 돌아옴")
    FLOW_DEBT_KO = "마진 부채 반영(차입)"
    FLOW_ARR_KO = "거래소 출금 도착"
    FLOW_DEBT_FIRST_KO = "기존 부채 첫 반영(차입 — 이날 첫 관측)"
    LATE_OFFSET_KO = "늦게 찾은 과거 체결 상쇄(같은 돈 두 번 안 잡히게)"
    FLOW_LATE_KO = "늦게 찾은 체결 상쇄"


    ATT_TOP = 5
    ATT_TRADE_EV = frozenset(("SWAP", "CONVERT", "EXF_BUY", "EXF_SELL", "EX_BUY", "EX_SELL", "NOOP", "FAILED", "UNKNOWN"))
    ATT_LP_EV = frozenset(("LP_ADD", "LP_REMOVE", "LP_ADJUST"))
    ATT_V = 2
    ATT_BAND = 1.2
    ATT_NOPX_BAND = (0.5, 2.0)


    ATT_DET_MK = 400
    ATT_DET_CAP = 100
    ATT_DET_FL = 200
    ATT_DET_BYTES = 6_000_000


    ATT_SPIKE = 3.0
    ATT_TOPX_GS = 6


    CEX_PX_ORDER = ("binance", "bybit", "okx", "gate", "kucoin", "upbit", "bithumb")
    PRE_DIVERGE = 2.0
    _CEX_FAIL_STATES = {"CANCELLED", "CANCELED", "FAILED", "FAIL", "REJECTED", "REJECT", "REFUNDED"}


    DM_KINDS = {"NEW_ASSET": "새 자산 검토", "UNKNOWN": "분류 보류",
                "TRANSFER_OUT": "외부 전송 확인", "POISON": "처리 실패",
                "PROGRAM_IN": "프로그램 수령 검토", "RECON": "기초잔고 대사"}


    DAY_EV_LIMIT_MAX = 20000
    DAY_EV_LIMIT_DEFAULT = 5000


    TAX_ROWS_MAX = 2000


    RECEIPT_FILLS_MAX = 400


    CHART_CACHE_MAX = 32


    CHART_TTL_S = 600
    CHART_BUDGET_S = 75.0
    _DEX_CHAIN_PREF = ("eth", "bsc", "base", "sol", "arbitrum", "polygon", "optimism")


    CHART_WORKERS = 2
    CHART_WAIT_S = 8.0
    CHART_HARD_S = 75.0
    CHART_BG_HARD_S = 300.0
    _CHART_JOBS = {}
    _CHART_JLOCK = threading.Lock()


    FUT_RC_MAX = 16
    FUT_SPAN_LO_S = 30 * 3600
    FUT_SPAN_MAX_S = 7 * 86400
    FUT_EXN = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX"}


    ATT_DET_SPAN = 40


    @staticmethod
    def _with_eval(out):
        if not out.get("ok") or out.get("empty"):
            return out
        side = "buy" if out.get("side") == "buy" else "sell"
        st9 = BUY_EVALS if side == "buy" else SELL_EVALS
        o = dict(out)
        ev9 = st9.get(out["date"], out["sym"])
        if ev9:
            o["eval"] = dict(StateBuilder._eval_rec(ev9[0], side), stale=bool(out.get("evalFp") and ev9[0].get("fp") != out.get("evalFp")))
        k9 = f"{out['date']}|{out['sym']}"
        if k9 in st9.running or DAY_MEMO_REEVAL.pending(out["date"], day_memo.norm_sym(str(out["sym"])) or out["sym"]):
            o["evalStatus"] = "running"
        return o


    BUY_FILLS_MAX = 400
    EVAL_INPUTS_MAX = 256
    BRIDGE_MAX_S = 30 * 86400
    GAP_BRIDGE_S = buychart.GAP_BRIDGE_S
    GAP_BRIDGE_BUDGET_S = 15.0
