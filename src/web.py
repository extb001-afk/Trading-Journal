"""tj-web: dashboard HTTP server and state builder."""
from __future__ import annotations
import copy
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from decimal import Decimal, getcontext  # noqa: F401
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config, net_http, paths, runtime, statefile, timeutil
import logs
if __name__ == "__main__":
    runtime.cpu_reserve_apply()
    _SQLITE_MEMSTAT_OFF = runtime.sqlite_memstatus_off()
import web_ctx  # noqa: E402
import db as dbm
import pricing, prefs_ident
import balcheck
import chainsweep
import websnap
import health
import cgca
import depaddr   # noqa: F401
import onboarding
import login_auth
import reqclass
import bf_engine
import xfer_match   # noqa: F401
import search_index
import other_assets
import nft
import histcurve
import sellchart
import coverage_limits
import buildproc
import day_memo
import alert_prefs
import alert_watch
from view_review import (  # noqa: F401
    review_fill_req_view,
    review_len_eff,
    REVIEW_LEN_KEYS,
    review_manual_busy,
    review_pause_eff,
    review_progress,
    REVIEW_PV,
)


from view_fut import (  # noqa: F401
    _fut_by_date_ex,
    _fut_fxb,
    _fut_notional,
    _fut_notional_sum,
    _PERP_BAD_WARNED,
    FUT_CEX,
    fut_ev_usd,
    fut_px_at,
    fut_sym,
    perp_active,
    perp_filter,
    PERP_KEYS,
    PERP_NAMES,
)
try:
    import fut_rcpt
except Exception:   # noqa: BLE001 [optional]
    fut_rcpt = None


def futures_api_payload():
    out9 = {}
    b9 = BUILDER if "BUILDER" in globals() else None
    sp9 = getattr(b9, "spot", None)
    pxf9 = None
    try:
        on9 = perp_active() or {}
    except Exception:   # noqa: BLE001 [fallback]
        on9 = {}
    for ex9 in FUT_CEX + tuple(k9 for k9 in PERP_KEYS if k9 in on9):
        fp9 = paths.state(f"futures_{ex9}.json")
        if not os.path.exists(fp9):
            continue
        try:
            d9 = statefile.read_json(fp9, {})
        except SystemExit:
            continue
        if ex9 not in on9 and isinstance(d9, dict) and isinstance(d9.get("events"), list) and any(isinstance(r9, dict) and r9.get("asset") for r9 in d9["events"]):
            if pxf9 is None:
                pxf9 = fut_px_at(_fut_fxb(getattr(b9, "px", None), sp9), sp9.price if sp9 is not None else None)
            evs9 = [fut_ev_usd(r9, lambda a9, r9=r9: pxf9(a9, r9.get("t"))) if isinstance(r9, dict) else r9 for r9 in d9["events"]]
            d9 = dict(d9, events=[r9 for r9 in evs9 if r9 is not None])
        out9[ex9] = perp_filter(d9, on9[ex9], None, ex9) if ex9 in on9 else d9
    return out9


def leverage_api_payload(now=None):
    import leverage
    import lev_view
    now9 = time.time() if now is None else float(now)
    lev9 = leverage.read_state(now9)
    futs9 = {}
    try:
        on9 = perp_active() or {}
    except Exception:   # noqa: BLE001 [fallback]
        on9 = {}
    for ex9 in FUT_CEX + tuple(k9 for k9 in PERP_KEYS if k9 in on9):
        fp9 = paths.state(f"futures_{ex9}.json")
        if not os.path.exists(fp9):
            continue
        try:
            d9 = statefile.read_json(fp9, {})
        except SystemExit:
            continue
        if isinstance(d9, dict):
            futs9[ex9] = perp_filter(d9, on9[ex9], now9, ex9) if ex9 in on9 else d9
    try:
        th9 = float(((alert_prefs.load(BUILDER.prefs()) or {}).get("th") or {}).get("liq_pct") or 10)
    except Exception:   # noqa: BLE001 [fallback]
        th9 = 10.0
    lm9, lp9 = None, paths.state("liq_watch.json")
    if os.path.exists(lp9):
        try:
            lm9 = statefile.read_json(lp9, None)
        except SystemExit:
            lm9 = None
    syms9 = set()
    for it9 in lev9.get("items") or []:
        if isinstance(it9, dict):
            syms9 |= {str(x.get("ccy") or "").upper() for x in (it9.get("debt") or []) + (it9.get("collateral") or []) if isinstance(x, dict)}
            syms9.add(str((it9.get("position") or {}).get("settle") or "").upper())
    syms9 = {"BTC" if s9 == "XBT" else s9 for s9 in syms9}
    syms9 = {s9 for s9 in syms9 if s9 and s9 not in STABLE_GROUPS and not _ex_stable_sym(s9)}
    sp9 = getattr(BUILDER, "spot", None) if "BUILDER" in globals() else None
    if sp9 is not None and syms9:
        sp9.want(syms9)

    def price9(s9):
        s9 = str(s9 or "").upper()
        s9 = "BTC" if s9 == "XBT" else s9
        if s9 in STABLE_GROUPS or _ex_stable_sym(s9):
            return 1.0
        return sp9.price(s9) if sp9 is not None else None
    return lev_view.build(lev9, futs9, price9, th9, lm9, now9)


log = logs.setup_logging("tj-web")
getcontext().prec = 60

from timeutil import KST
from view_common import (  # noqa: F401
    _ex_stable_sym,
    _px_tables,
    BUILD_HIST_N,
    CHAIN_NAME,
    DAILY_LIVE_WIN,
    DAILY_LQ_V,
    DAILY_PX_KEEP,
    DAILY_V,
    DAYCLOSE_ON,
    DC_LATE_S,
    DC_RETRY_S,
    DC_SMALL_USD,
    DISC_OPEN_KO,
    EPS,
    EX_CANDLE_SYMS,
    EX_STABLE_SYMS,
    GOPLUS_STATUS,
    HL_MAXWAIT_S,
    LP_OPEN_SEC,
    STABLE_GROUPS,
)
from http_assets import (  # noqa: F401
    _asset,
    _ASSETS,
    _ASSETS_LOCK,
    _ui_route,
    _V2_FILES,
    _V2_FONT_RE,
    _V2_JS_RE,
    _V2_VER_JS,
    UI_DEFAULT,
    V2_DIR,
    V2_FONT_DIR,
    WEB_DIR,
)


from view_text import (  # noqa: F401
    _GP_KO,
    _human_dm,
    _INVISIBLE,
    _SCAM_DOMAIN,
    _SCAM_FREE,
    _SCAM_NAME,
    _scam_name,
    _SCAM_SOFT,
    _short_addr,
    _usd_txt,
)
from view_pending import (  # noqa: F401
    _classify_pendings,
    _of_linked_txs,
    dust_usd_eff,
    unpriced_ent,
    unpriced_facts,
)


from view_snapfile import (  # noqa: F401
    _aged_last_scan,
    _code_sig,
    _LASTSCAN_KEY,
    _LASTSCAN_RX,
    _SIG0,
    _SNAPFILE,
    _snapfile_drop,
    _snapfile_load,
    _SNAPFILE_MAGIC,
    _snapfile_save,
    _snapfile_sig,
    SNAPFILE_EVERY,
    SNAPFILE_MAX_AGE,
)


from view_hero import (  # noqa: F401
    _ago_ko,
    _HERO_HTML,
    _HERO_HTML_LOCK,
    _hero_ok,
    _hero_summary,
    _publish_snap,
)


def _wallet_reload_view() -> dict:
    try:
        import wallet_register as _wr9
        alive9 = _wr9.auto_reload_alive()
        return {"ok": True, "auto": bool(_wr9.apply_info().get("runner")), "addrs": sorted(_wr9.pending_addrs()) if alive9 else []}
    except Exception:   # noqa: BLE001 [fallback]
        return {"ok": True, "auto": False, "addrs": []}


def _bcall(name, *a):
    f9 = getattr(BUILDER, name, None)
    return f9(*a) if callable(f9) else None


def _mats_ready(path) -> bool:
    r9 = _bcall("mats_wait", path)
    return True if r9 is None else bool(r9)


from view_regroup import (  # noqa: F401
    _daily_krw,
    _daily_reset,
    _relabel_daily_gids,
    _stable_regroup_aliases,
)


from view_tax import (  # noqa: F401
    _tax_add,
    _tax_fee_key,
    _tax_fee_merge,
    _tax_stable_fx,
    _tax_summary,
    FEE_TAX_EX,
)


def chain_auto_off_save(prefs: dict, body: dict):
    on9 = (body or {}).get("on")
    if not isinstance(on9, bool):
        return 400, {"ok": False, "error": "on 은 true/false"}
    prefs["chain_auto_off"] = {"on": on9, "at": int(time.time())}
    statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
    return 200, {"ok": True, "on": on9}


def snapshot_refresher():
    last9 = None
    while True:
        time.sleep(3)
        try:
            b = BUILDER
            if b is None:
                continue
            now = time.time()
            snap = b.snaps.cur
            if now - b._last_client <= b.ACTIVE_SEC and (snap is None or now - snap.at >= max(b.REFRESH_SEC, b._min_gap())) \
                    and b.inputs_changed(snap, now):
                b.kick_refresh()
            last9 = None
        except (Exception, SystemExit) as e:   # noqa: BLE001 [boundary]
            if str(e) != last9:
                log.warning("스냅샷 갱신기 오류(계속): %s", e)
                last9 = str(e)


PREFS_LOCK = threading.Lock()
prefs_ident.WRITE_LOCK_FN = lambda: PREFS_LOCK
from http_state import (  # noqa: F401
    _ALERT_TEST_T,
    MemoHourly,
)


from view_evals import (  # noqa: F401
    BUY_EVALS,
    DAY_MEMOS,
    SELL_EVALS,
)
from view_spot import (  # noqa: F401
    _alt_src_of,
    _alt_src_stale,
    _cg_key_set,
    _px1004_spot_filter,
    PX1004_ALT_OK,
    Spot,
)
from view_misc import (  # noqa: F401
    _BuildObsolete,
    _cfg_file_sig,
    _dec_or0,
    _fx_candle_near,
    _hist_kit_rows,
    _px_recent,
    _px_took,
    _rate_state,
    _recon_q,
    _sol_stake_accounts,
    _venue_flows30,
    build_stats,
    HIST_NF,
    STAKE_STATE_KO,
)


from view_fspin import (  # noqa: F401
    _fs_pin_load,
    _fs_pin_save,
    FS_CAP_X,
    FS_EX,
    FS_HOLD_KO,
)


from view_pxfix import (  # noqa: F401
    _bind_px_blocks,
    _capture_px_blocks,
    _migrate_px_blocks,
    _pin_frozen_x,
    _px1004_backup,
    _px1004_reset,
    _pxfix_backup,
    _reprice_now_days,
    PXB_KEYS,
)


from view_xv import (  # noqa: F401
    _ufc_ku,
    _x_end,
    _x_sync_entry,
    _xq_sets,
    _xv_checked,
    _xv_disk,
    _xv_ob,
    _xv_obs_parts,
    _xv_parts,
    _xv_sum,
    XQ_X_KEYS,
    XV_V,
)


GOPLUS_CHAIN_ID = {"eth": "1", "bsc": "56", "base": "8453", "optimism": "10",
                   "arbitrum": "42161", "polygon": "137", "gnosis": "100",
                   "scroll": "534352", "zksync": "324", "robinhood": "4663"}
GOPLUS_TTL = 7 * 86400
GOPLUS_FAIL_RETRY = 3600
GOPLUS_LIMIT_SEC = 300
GOPLUS_LOG_EVERY = 600
GOPLUS_PERM_N = 3


from view_txkey import (  # noqa: F401
    _B64URL_32_TX,
    _HEX64_TX,
    _ton_hash_uids,
    _txk,
    _wd_txk,
)


from view_order import (  # noqa: F401
    _ord_auth_before,
    _ord_cash,
    _ord_feasible,
    _ord_flow,
    _ORD_HOLD,
    _ord_pair_moves,
    _ord_splice,
    _ord_tie,
    NOPX_LEGS_MAX,
    ORD_DFS_MAX,
    ORD_DFS_NODES,
    ORD_GAP_SEC,
    ORD_RUN_MAX,
)


from view_plans import (  # noqa: F401
    _bridge_plan,
    _loan_plan,
    _loan_windows,
    BR_QTY_HI,
    BR_QTY_LO,
    BR_SPLIT_MAX,
    BR_UNIQ_LO,
    BR_WIN,
    LOAN_MIN_S,
    LOAN_SKIP_EX,
)


from view_offc import (  # noqa: F401
    _offc_answered,
    _offc_excl,
    _offc_on,
    _offc_tx,
    OFFC_EXCHANGES,
    OFFC_TX_PREFIX,
)


import view_builder  # noqa: E402
from view_builder import (  # noqa: F401
    StateBuilder,
)


def _chain_usd_now():
    b9 = BUILDER
    last9 = b9.__dict__.get("_last_out") if b9 is not None else None
    f9 = last9.get("fields") if isinstance(last9, dict) and isinstance(last9.get("fields"), dict) else last9
    if not isinstance(f9, dict):
        return None
    rev9 = {v: k for k, v in CHAIN_NAME.items()}
    out = {}
    for row in list(f9.get("coins") or []) + list(f9.get("stables") or []):
        if not isinstance(row, dict):
            continue
        try:
            px9 = float(row.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if px9 <= 0:
            continue
        for l9 in row.get("locs") or []:
            k9 = rev9.get(l9.get("ch")) if isinstance(l9, dict) else None
            if not k9:
                continue
            try:
                out[k9] = out.get(k9, 0.0) + max(0.0, float(l9.get("qty") or 0)) * px9
            except (TypeError, ValueError):
                continue
    return out


AUTO_OFF_PX_DAYS = 7


def _recent_px_gids(b9, now=None) -> set:
    out = set()
    try:
        now = time.time() if now is None else now
        lo9 = timeutil.kst_day(now, AUTO_OFF_PX_DAYS)
        srcs9 = [v9 for k9, v9 in (getattr(b9, "daily_px", None) or {}).items() if isinstance(k9, str) and k9[:1].isdigit() and k9 >= lo9]
        lv9 = (getattr(b9, "daily", None) or {}).get("_live")
        if isinstance(lv9, dict):
            srcs9.append(lv9)
        for e9 in srcs9:
            p9 = e9.get("p") if isinstance(e9, dict) else None
            if not isinstance(p9, dict):
                continue
            for g9, v9 in p9.items():
                try:
                    if float(v9) > 0:
                        out.add(str(g9))
                except (TypeError, ValueError):
                    continue
    except Exception:   # noqa: BLE001 [fallback]
        return set()
    return out


def _chain_auto_off_info():
    b9 = BUILDER
    if b9 is None:
        return None
    try:
        last9 = b9.latest(0) if b9.__dict__.get("_built_sig") != b9._input_sig() else b9.__dict__.get("_last_out")
    except (Exception, SystemExit):   # noqa: BLE001 [fallback]
        return None
    f9 = last9.get("fields") if isinstance(last9, dict) and isinstance(last9.get("fields"), dict) else last9
    if not isinstance(f9, dict):
        return None
    rev9 = {v: k for k, v in CHAIN_NAME.items()}
    out = {}
    recent9 = _recent_px_gids(b9)

    def add9(k9, v9):
        try:
            v9 = float(v9 or 0)
        except (TypeError, ValueError):
            return
        if math.isfinite(v9) and v9 > 0:
            e9 = out.setdefault(k9, {"usd": 0.0})
            e9["usd"] += v9
    for row in list(f9.get("coins") or []) + list(f9.get("stables") or []):
        if not isinstance(row, dict):
            continue
        try:
            px9 = float(row.get("price") or 0)
        except (TypeError, ValueError):
            px9 = float("nan")
        if not math.isfinite(px9) or px9 <= 0:
            if str(row.get("key") or "")[1:] in recent9:
                for l9 in row.get("locs") or []:
                    k9 = rev9.get(l9.get("ch")) if isinstance(l9, dict) else None
                    try:
                        q9 = float(l9.get("qty") or 0) if k9 else 0.0
                    except (TypeError, ValueError):
                        q9 = 0.0
                    if k9 and q9 > 0:
                        out.setdefault(k9, {"usd": 0.0})["unk"] = True
            continue
        for l9 in row.get("locs") or []:
            k9 = rev9.get(l9.get("ch")) if isinstance(l9, dict) else None
            if k9:
                try:
                    add9(k9, float(l9.get("qty") or 0) * px9)
                except (TypeError, ValueError):
                    continue
    for lp9 in f9.get("lps") or []:
        if not isinstance(lp9, dict) or lp9.get("closed"):
            continue
        k9 = lp9.get("chainKey") or rev9.get(lp9.get("chain"))
        if k9:
            for a9 in ("value", "fees", "rewards"):
                add9(k9, lp9.get(a9))
    try:
        for it9 in (_nft_tracker().view() or {}).get("tracked") or []:
            if isinstance(it9, dict) and it9.get("chain") and not it9.get("hidden"):
                add9(str(it9["chain"]), (it9.get("value") or {}).get("usd") if isinstance(it9.get("value"), dict) else None)
    except Exception:   # noqa: BLE001 [fallback]
        return None
    try:
        lim9 = min(100.0, dust_usd_eff(b9.prefs()))
    except Exception:   # noqa: BLE001 [fallback]
        lim9 = 50.0
    return {"lim": lim9, "chains": out}


class _SearchPool:
    N = 2
    TIMEOUT = 20.0

    def __init__(self):
        self.lock = threading.Lock()
        self.idle = []
        self.sem = threading.BoundedSemaphore(self.N)
        self.off_until = 0.0

    def _spawn(self):
        return subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "search_worker.py")],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None, bufsize=0,
                                cwd=paths.BASE_DIR, env=dict(os.environ))

    @staticmethod
    def _kill(p):
        try:
            p.kill()
            p.wait(timeout=5)
        except Exception:   # noqa: BLE001 [optional]
            pass

    def run(self, req: dict):
        if time.time() < self.off_until or not self.sem.acquire(timeout=5):
            return None
        p = None
        try:
            with self.lock:
                while self.idle:
                    p = self.idle.pop()
                    if p.poll() is None:
                        break
                    p = None
            if p is None:
                p = self._spawn()
            import select
            end9 = time.monotonic() + self.TIMEOUT
            fd_in9, fd_out9 = p.stdin.fileno(), p.stdout.fileno()
            os.set_blocking(fd_in9, False)
            os.set_blocking(fd_out9, False)
            msg9 = json.dumps(req).encode("ascii") + b"\n"
            while msg9:
                left9 = end9 - time.monotonic()
                if left9 <= 0 or not select.select([], [fd_in9], [], left9)[1]:
                    raise TimeoutError("검색 일꾼 입력 대기 초과")
                try:
                    n9 = os.write(fd_in9, msg9)
                except BlockingIOError:
                    continue
                msg9 = msg9[n9:]
            line9 = bytearray()
            while not line9.endswith(b"\n"):
                left9 = end9 - time.monotonic()
                if left9 <= 0 or not select.select([fd_out9], [], [], left9)[0]:
                    raise TimeoutError("검색 일꾼 응답 없음")
                try:
                    chunk9 = os.read(fd_out9, 65536)
                except BlockingIOError:
                    continue
                if not chunk9:
                    raise EOFError("검색 일꾼 응답 닫힘")
                line9.extend(chunk9)
            if line9.count(b"\n") != 1:
                raise ValueError("검색 일꾼 응답 줄 수 이상")
            out9 = json.loads(line9)
            with self.lock:
                self.idle.append(p)
            p = None
            return out9.get("body") if isinstance(out9, dict) and out9.get("ok") else None
        except Exception as e:   # noqa: BLE001 [fallback]
            log.warning("검색 일꾼 실패(직접 검색으로): %s", type(e).__name__)
            self.off_until = time.time() + 60
            return None
        finally:
            if p is not None:
                self._kill(p)
            self.sem.release()


SEARCH_POOL = _SearchPool()
BUILDER: StateBuilder = None
web_ctx.register(builder=lambda: BUILDER, bcall=_bcall)
web_ctx.register(day_memo=lambda: DAY_MEMO_REEVAL, search_pool=lambda: SEARCH_POOL,
                 nft_tracker=lambda *a, **k: _nft_tracker(*a, **k), oa_quoter=lambda *a, **k: _oa_quoter(*a, **k),
                 oa_rate=lambda *a, **k: _oa_rate(*a, **k), memo_driven=lambda *a, **k: memo_driven(*a, **k))
web_ctx.register(alert_view=lambda *a, **k: _alert_view(*a, **k), tg_connected=lambda *a, **k: _tg_connected(*a, **k))
web_ctx.register(
    mats_ready=lambda *a, **k: _mats_ready(*a, **k), wallet_reload_view=lambda *a, **k: _wallet_reload_view(*a, **k),
    registered_wallet_keys=lambda *a, **k: _registered_wallet_keys(*a, **k), bench_series=lambda *a, **k: bench_series(*a, **k),
    chain_auto_off_save=lambda *a, **k: chain_auto_off_save(*a, **k), coverage_refresh=lambda *a, **k: coverage_refresh(*a, **k),
    futures_api_payload=lambda *a, **k: futures_api_payload(*a, **k), leverage_api_payload=lambda *a, **k: leverage_api_payload(*a, **k),
    prefs_lock=lambda: PREFS_LOCK, coverage_path=lambda: paths.state(coverage_limits.OUT_NAME), alias_max=lambda: ALIAS_MAX, ignored_max=lambda: IGNORED_MAX,
    plans_max=lambda: PLANS_MAX, src_wl_max=lambda: SRC_WL_MAX, alias_addr_re=lambda: _ALIAS_ADDR_RE)
OA_Q: "other_assets.Quoter | None" = None


def _oa_rate() -> float:
    try:
        return float(getattr(getattr(BUILDER, "spot", None), "rate", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _oa_paxg():
    sp = getattr(BUILDER, "spot", None)
    if sp is None:
        return None
    sp.want(["PAXG"])
    return sp.price("PAXG")


def _oa_quoter():
    global OA_Q
    if OA_Q is None:
        OA_Q = other_assets.Quoter(rate_fn=_oa_rate, paxg_fn=_oa_paxg, cfg_fn=lambda: getattr(BUILDER, "cfg", None) or {})
    return OA_Q


NFT_T: "nft.Tracker | None" = None


def _nft_px(sym):
    sp = getattr(BUILDER, "spot", None)
    if sp is None or not sym:
        return None
    s9 = "ETH" if sym == "WETH" else str(sym).upper()
    sp.want([s9])
    return sp.price(s9)


def _nft_alert(line) -> bool:
    if not isinstance(line, dict) or not _tg_connected():
        return False
    now9 = time.time()
    doc9 = alert_prefs.load(BUILDER.prefs() if BUILDER is not None else None)
    if not alert_prefs.effective(doc9, alert_prefs.cat_of(line.get("kind"), line.get("cat")), now9, alert_prefs.connect_ts()):
        return False
    _append_alert(line)
    log.info("새 알림 1건 적재: %s", line.get("kind"))
    return True


def _nft_tracker():
    global NFT_T
    if NFT_T is None:
        NFT_T = nft.Tracker(cfg_fn=lambda: getattr(BUILDER, "cfg", None) or {}, px_fn=_nft_px, rate_fn=_oa_rate, alert_fn=_nft_alert)
    return NFT_T


class DayMemoReeval:
    DEBOUNCE_S = 5.0
    KEY_GAP_S = 60.0
    PER_SAVE_MAX = 20
    HOURLY_MAX = 30
    QUEUE_MAX = 50
    CHART_TRIES = 40
    CHART_SLEEP_S = 3.0
    LOCK_TRIES = 60
    LOCK_SLEEP_S = 5.0
    HOURLY_MSG = "근거 메모로 다시 만드는 AI 평가는 시간당 {n}회까지예요 — 잠시 뒤 다시"

    def __init__(self):
        self.mu = threading.Lock()
        self.q = {}
        self.last = {}
        self.manual = {}
        self.force = {}
        self.cur = None
        self.hour = []
        self.th = None
        self.log = []
        self.sleep = time.sleep
        self.now = time.time

    def schedule(self, date, sym, reset=True, force=False, side=None, manual=False) -> bool:
        k = f"{date}|{sym}"
        with self.mu:
            if force:
                self.force.setdefault(k, set()).update((side,) if side in ("sell", "buy") else ("sell", "buy"))
            if manual:
                self.manual.setdefault(k, set()).update((side,) if side in ("sell", "buy") else ("sell", "buy"))
            if not reset and k in self.q:
                return True
            if k not in self.q and len(self.q) >= self.QUEUE_MAX:
                return False
            due = self.now() + self.DEBOUNCE_S
            if k in self.last:
                due = max(due, self.last[k] + self.KEY_GAP_S)
            self.q[k] = due
            if self.th is None or not self.th.is_alive():
                self.th = threading.Thread(target=self._loop, name="daymemo-reeval", daemon=True)
                self.th.start()
        return True

    def pending(self, date, sym) -> bool:
        k = f"{date}|{sym}"
        with self.mu:
            return k in self.q or self.cur == k

    def tracked(self, date, sym) -> bool:
        k = f"{date}|{sym}"
        with self.mu:
            return k in self.q or k in self.last or self.cur == k

    def hour_left(self) -> int:
        with self.mu:
            t9 = self.now()
            self.hour = [x for x in self.hour if t9 - x < 3600]
            return max(0, self.HOURLY_MAX - len(self.hour))

    def runner(self, label):
        def run(b9, p9, body9):
            with self.mu:
                t9 = self.now()
                self.hour = [x for x in self.hour if t9 - x < 3600]
                if len(self.hour) >= self.HOURLY_MAX:
                    raise MemoHourly(label)
                self.hour.append(t9)
            import review_daily as rd9
            return rd9._run_cli(b9, p9, None, label, body=body9)
        return run

    def _loop(self):
        while True:
            with self.mu:
                if not self.q:
                    self.th = None
                    return
                k, due = min(self.q.items(), key=lambda kv: kv[1])
                w = due - self.now()
                if w <= 0:
                    self.q.pop(k, None)
                    self.last[k] = self.now()
                    self.cur = k
                    force = self.force.pop(k, set())
            if w > 0:
                self.sleep(min(w, 1.0))
                continue
            try:
                self.run_key(k, force=force)
            except Exception as e:   # noqa: BLE001 [boundary]
                log.warning("근거 메모 뒤 AI 평가 다시 실패(%s): %s", k, e)
            finally:
                with self.mu:
                    self.cur = None
                    self.manual.pop(k, None)

    def _note(self, k, side, res):
        self.log.append((k, side, res))
        del self.log[:-100]
        return res

    def run_key(self, k, force=()):
        fs = {"sell", "buy"} if force is True else set(force or ())
        date, sym = k.split("|", 1)
        if BUILDER is None:
            return
        BUILDER.snapshot()
        lst = BUILDER.receipt_list(date, date) or {}
        items = [(str(x["date"]), str(x["sym"])) for x in (lst.get("items") or []) if day_memo.norm_sym(str(x.get("sym") or "")) == sym]
        n = 0
        for d9, s9 in items:
            for side in ("sell", "buy"):
                if n >= self.PER_SAVE_MAX:
                    return
                n += 1
                self._one(k, d9, s9, side, force=side in fs)

    def _one(self, k, date, sym, side, force=False):
        ST = BUY_EVALS if side == "buy" else SELL_EVALS
        with self.mu:
            man9 = side in (self.manual.get(k) or set())
        if not man9 and review_pause_eff(BUILDER.prefs() if BUILDER is not None else {}).get("on"):
            return self._note(k, side, "paused")
        ch = None
        for _ in range(self.CHART_TRIES):
            ch, st9 = BUILDER.chart_request(date, sym, "5m", "1h", None, side=side)
            if st9 == "ok":
                break
            self.sleep(self.CHART_SLEEP_S)
        else:
            return self._note(k, side, "nochart")
        if not ch or not ch.get("ok") or ch.get("empty") or (side == "buy" and ch.get("side") != "buy"):
            return self._note(k, side, "nochart")
        fp = ch.get("evalFp")
        sym9 = str(ch.get("sym") or sym)
        inp = (getattr(BUILDER, "_eval_inputs", None) or {}).get((("buy",) if side == "buy" else ()) + (date, sym9, fp)) if fp else None
        if not inp:
            return self._note(k, side, "nochart")
        import review_prompt as rp9
        old = ST.find(date, sym9, fp)
        if not force and old and old.get("pv") == (rp9.BUY_EVAL_VERSION if side == "buy" else rp9.SELL_EVAL_VERSION):
            return self._note(k, side, "fresh")
        rk9 = f"{date}|{sym9}"
        if self.hour_left() <= 0:
            log.info("근거 메모 뒤 AI 평가: 시간당 상한(%d) — %s %s 건너뜀", self.HOURLY_MAX, k, side)
            ST.errors[rk9] = {"at": int(time.time()), "error": self.HOURLY_MSG.format(n=self.HOURLY_MAX)}
            return self._note(k, side, "hourly")
        for _ in range(self.LOCK_TRIES):
            with ST.mu:
                if not ST.running:
                    ST.running[rk9] = {"since": int(self.now()), "fp": fp, "by": "memo"}
                    ST.errors.pop(rk9, None)
                    break
            self.sleep(self.LOCK_SLEEP_S)
        else:
            return self._note(k, side, "busy")
        try:
            rec, e9 = sellchart.run_eval(ST, BUILDER.cfg, date, sym9, fp, inp, skip_if_fresh=not force,
                                         runner=self.runner(f"{'매수' if side == 'buy' else '매도'}평가(근거) {rk9}"))
            if e9:
                ST.errors[rk9] = {"at": int(time.time()), "error": e9}
                return self._note(k, side, "fail")
            return self._note(k, side, "made" if rec else "fail")
        except MemoHourly:
            ST.errors[rk9] = {"at": int(time.time()), "error": self.HOURLY_MSG.format(n=self.HOURLY_MAX)}
            return self._note(k, side, "hourly")
        finally:
            with ST.mu:
                ST.running.pop(rk9, None)


DAY_MEMO_REEVAL = DayMemoReeval()
view_builder.DAY_MEMO_REEVAL = DAY_MEMO_REEVAL


def memo_driven(date, sym, inp, side):
    sy = day_memo.norm_sym(str(sym or ""))
    if not sy or not isinstance(inp, dict):
        return None
    if inp.get("memo"):
        return sy
    if DAY_MEMO_REEVAL.tracked(date, sy):
        return sy
    st9 = BUY_EVALS if side == "buy" else SELL_EVALS
    try:
        return sy if any(r9.get("memoUsed") for r9 in st9.get(date, sym)) else None
    except Exception:   # noqa: BLE001 [fallback]
        return None


ALIAS_MAX = 2000
PLANS_MAX = 5000
IGNORED_MAX = 20000
SRC_WL_MAX = 2000
_ALIAS_ADDR_RE = re.compile(r"0x[0-9a-f]{40}|[1-9A-HJ-NP-Za-km-z]{32,44}")


def _registered_wallet_keys(cfg) -> set:
    out = set()
    for k9 in ("wallets", "perp_wallets"):
        for w in ((cfg or {}).get(k9) or ()):
            a = str((w or {}).get("address") or "").strip() if isinstance(w, dict) else ""
            if a:
                out.add(a.lower() if a.startswith("0x") else a)
    return out


BASE_SEC_HEADERS = (("X-Frame-Options", "DENY"), ("Content-Security-Policy", "frame-ancestors 'none'"),
                    ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"))
PROXY_SEC_HEADERS = (("Cloudflare-CDN-Cache-Control", "no-store"), ("Vary", "Cookie"),
                     ("Cross-Origin-Opener-Policy", "same-origin"), ("Cross-Origin-Resource-Policy", "same-origin"),
                     ("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()"))
HSTS = ("Strict-Transport-Security", "max-age=31536000")
_BENCH = {"sig": None, "at": 0.0, "body": None}
_BENCH_LOCK = threading.Lock()


def _bench_btc_ids() -> set:
    try:
        c9 = dbm.connect(paths.sqlite_ro_uri(paths.DB_PATH), uri=True, timeout=5)
        try:
            return {str(r[0]) for r in c9.execute("SELECT DISTINCT group_id FROM assets WHERE upper(symbol)='BTC' AND group_id IS NOT NULL "
                                                    "AND COALESCE(hidden, 0) = 0")}
        finally:
            c9.close()
    except Exception:   # noqa: BLE001 [fallback]
        return set()


def bench_series() -> dict:
    hp = paths.state("curve_hist_px.json")
    sig = []
    for p9 in (hp, paths.state("daily_px.json")):
        try:
            st9 = os.stat(p9)
            sig.append((p9, st9.st_mtime_ns, st9.st_size))
        except OSError:
            sig.append((p9, None, None))
    now9 = time.time()
    with _BENCH_LOCK:
        if _BENCH["body"] is not None and _BENCH["sig"] == sig and now9 - _BENCH["at"] < 600:
            body = dict(_BENCH["body"])
            body["now"] = _bench_now()
            return body
    px, n_hist, n_day = {}, 0, 0
    try:
        h9 = statefile.read_json(hp, {}) if os.path.exists(hp) else {}
        sp9 = ((h9.get("specs") or {}).get("sym:BTC") or {}).get("p") or {}
        for d9, v9 in sp9.items():
            try:
                f9 = float(v9)
            except (TypeError, ValueError):
                continue
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d9)) and math.isfinite(f9) and f9 > 0:
                px[d9] = f9
                n_hist += 1
    except (SystemExit, Exception):   # noqa: BLE001 [optional]
        pass
    ids = _bench_btc_ids()
    if ids:
        try:
            dp9 = statefile.read_json(paths.state("daily_px.json"), {}) if os.path.exists(paths.state("daily_px.json")) else {}
            for d9, row9 in dp9.items():
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d9)) or not isinstance(row9, dict):
                    continue
                vs = sorted(float(v) for k, v in (row9.get("p") or {}).items()
                            if str(k) in ids and isinstance(v, (int, float)) and math.isfinite(v) and v > 1000)
                if vs:
                    px[d9] = vs[len(vs) // 2]
                    n_day += 1
        except (SystemExit, Exception):   # noqa: BLE001 [optional]
            pass
    body = {"ok": True, "sym": "BTC", "px": dict(sorted(px.items())), "src": {"hist": n_hist, "daily": n_day}}
    with _BENCH_LOCK:
        _BENCH.update(sig=sig, at=now9, body=body)
    out = dict(body)
    out["now"] = _bench_now()
    return out


def _bench_now():
    try:
        sp9 = BUILDER.spot if BUILDER is not None else None
        ex9 = getattr(sp9, "ex_usd", None) or {}
        for k9 in ("binance:BTC", "bybit:BTC", "upbit:BTC"):
            v9 = ex9.get(k9)
            if isinstance(v9, (int, float)) and math.isfinite(v9) and v9 > 1000:
                return float(v9)
    except Exception:   # noqa: BLE001 [optional]
        pass
    return None


def _etag_match(inm, etag) -> bool:
    if not inm or not etag:
        return False

    def op(t):
        t = t.strip()
        return t[2:] if t.startswith("W/") else t
    want = op(str(etag))
    for x in str(inm).split(","):
        x = x.strip()
        if x == "*" or (x and op(x) == want):
            return True
    return False


def _private_cache(cache: str, proxied: bool, ctype: str = "") -> str:
    c = (cache or "no-store").strip()
    if "public" in c:
        c = c.replace("public", "private")
    elif "private" not in c:
        c = "private, " + c
    if proxied:
        t = (ctype or "").lower()
        asset = "max-age" in c and "no-store" not in c and not ("text/html" in t or "json" in t)
        if not asset:
            c = "private, no-store"
    return c


REQ_SWITCH_SEC = 0.001
_SW_BASE = sys.getswitchinterval()
_SW_LOCK = threading.Lock()
_SW_N = [0]


def _sw_enter():
    with _SW_LOCK:
        _SW_N[0] += 1
        if _SW_N[0] == 1:
            sys.setswitchinterval(min(REQ_SWITCH_SEC, _SW_BASE))


def _sw_exit():
    with _SW_LOCK:
        _SW_N[0] = max(0, _SW_N[0] - 1)
        if _SW_N[0] == 0:
            sys.setswitchinterval(_SW_BASE)


import io as _io  # noqa: E402
import socket as _socket  # noqa: E402

HDR_DEADLINE_SEC = 10


class _HdrClockReader(_io.RawIOBase):

    def __init__(self, h):
        super().__init__()
        self._h = h

    def readable(self):
        return True

    def readinto(self, b):
        h = self._h
        dl = h._tj_hdr_dl
        if dl is not None:
            rem = dl - time.monotonic()
            if rem <= 0:
                raise _socket.timeout("요청 헤더 마감")
            h.connection.settimeout(min(rem, h.timeout) if h.timeout else rem)
        return h.connection.recv_into(b)


from http_outflow import OutflowMixin  # noqa: E402


from http_get import GetMixin  # noqa: E402


from http_post import PostMixin  # noqa: E402


from http_route import RouteMixin  # noqa: E402


class Handler(RouteMixin, PostMixin, GetMixin, OutflowMixin, BaseHTTPRequestHandler):
    server_version = "tj-web/0.1"
    protocol_version = "HTTP/1.1"
    timeout = 120

    def log_message(self, fmt, *args):
        pass

    def setup(self):
        super().setup()
        self._tj_hdr_dl = time.monotonic() + HDR_DEADLINE_SEC
        self.rfile.close()
        self.rfile = _io.BufferedReader(_HdrClockReader(self))

    def parse_request(self):
        ok = super().parse_request()
        if getattr(self, "_tj_hdr_dl", None) is not None:
            self._tj_hdr_dl = None
            try:
                self.connection.settimeout(self.timeout)
            except OSError:
                pass
        if ok and not getattr(self, "_tj_sw", False):
            self._tj_sw = True
            _sw_enter()
        return ok

    def tj_read_within(self, n, sec):
        prev = self.connection.gettimeout()
        self._tj_hdr_dl = time.monotonic() + sec
        try:
            return self.rfile.read(n)
        finally:
            self._tj_hdr_dl = None
            try:
                self.connection.settimeout(prev)
            except OSError:
                pass

    def _tj_next_request(self) -> bool:
        try:
            self.connection.settimeout(self.timeout)
            if not self.rfile.peek(1):
                return False
        except OSError:
            return False
        self._tj_hdr_dl = time.monotonic() + HDR_DEADLINE_SEC
        return True

    def handle_one_request(self):
        try:
            if "_tj_hdr_dl" in self.__dict__ and self._tj_hdr_dl is None and not self._tj_next_request():
                self.close_connection = True
                return
            super().handle_one_request()
        finally:
            if getattr(self, "_tj_sw", False):
                self._tj_sw = False
                _sw_exit()

    def version_string(self):
        return "tj-web"

    def send_error(self, code, message=None, explain=None):
        try:
            short = self.responses.get(code, ("error",))[0]
        except Exception:  # noqa: BLE001 [fallback]
            short = "error"
        body = json.dumps({"error": short}).encode()
        self.close_connection = True
        if getattr(self, "request_version", "HTTP/0.9") == "HTTP/0.9":
            self.request_version = "HTTP/1.0"
        try:
            self.send_response(code, short)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "private, no-store")
            self.send_header("Cloudflare-CDN-Cache-Control", "no-store")
            self.send_header("Vary", "Cookie")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            if code == 405 or code == 501:
                self.send_header("Allow", "GET, POST")
            self.send_header("Connection", "close")
            body_ok = code >= 200 and code not in (204, 304) and getattr(self, "command", "") != "HEAD"
            self.send_header("Content-Length", str(len(body) if body_ok else 0))
            self.end_headers()
            if body_ok:
                self.wfile.write(body)
        except (OSError, AttributeError):
            pass

    def _gzip_ok(self) -> bool:
        for part in (self.headers.get("Accept-Encoding") or "").lower().split(","):
            tok, _, q = part.strip().partition(";")
            if tok.strip() in ("gzip", "*"):
                return q.replace(" ", "") not in ("q=0", "q=0.0", "q=0.00", "q=0.000")
        return False

    def _proxy_headers(self):
        try:
            px = reqclass.proxied(self)
        except Exception:   # noqa: BLE001 [fallback]
            px = True
        if not px:
            return False, ()
        return True, PROXY_SEC_HEADERS + ((HSTS,) if reqclass.proxied_https(self) else ())

    def _send_bytes(self, code, raw, gzb=None, ctype="application/json; charset=utf-8", etag=None,
                    cache="no-store", extra=()):
        px, pxh = self._proxy_headers()
        cache = _private_cache(cache, px, ctype)
        out = []
        have = set()
        for k, v in tuple(extra) + pxh + BASE_SEC_HEADERS:
            kl = k.lower()
            if kl in have and kl != "set-cookie":
                continue
            have.add(kl)
            out.append((k, v))
        extra = tuple(out)
        if etag and code == 200:
            inm = self.headers.get("If-None-Match")
            if _etag_match(inm, etag):
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", cache)
                self.send_header("Vary", "Accept-Encoding")
                self.send_header("Content-Length", "0")
                for k, v in extra:
                    self.send_header(k, v)
                self.end_headers()
                return
        use_gz = gzb is not None and self._gzip_ok()
        data = gzb if use_gz else raw
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        if gzb is not None:
            self.send_header("Vary", "Accept-Encoding")
        if use_gz:
            self.send_header("Content-Encoding", "gzip")
        if etag:
            self.send_header("ETag", etag)
        for k, v in extra:
            self.send_header(k, v)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        gzb = websnap.gz(data) if len(data) >= 2048 and self._gzip_ok() else None
        self._send_bytes(code, data, gzb, ctype)


    def _body_on_bodyless(self) -> bool:
        cl = (self.headers.get("Content-Length") or "").strip()
        if self.headers.get("Transfer-Encoding") is None and cl in ("", "0"):
            return False
        self.close_connection = True
        self._send(400, {"error": "GET 요청에 본문을 실을 수 없습니다"})
        return True

    def _method_not_allowed(self):
        reqclass.mark_conn(self)
        self.close_connection = True
        self._send_bytes(405, b'{"error": "method not allowed"}', extra=(("Allow", "GET, POST"),))

    do_HEAD = do_OPTIONS = do_PUT = do_DELETE = do_PATCH = _method_not_allowed


TAILSCALE_BINS = ("tailscale", "/usr/local/bin/tailscale", "/opt/homebrew/bin/tailscale",
                  "/Applications/Tailscale.app/Contents/MacOS/Tailscale")


def tailnet_ip():
    for binpath in TAILSCALE_BINS:
        try:
            out = subprocess.run([binpath, "ip", "-4"],
                                 capture_output=True, text=True, timeout=10)
            ip = out.stdout.strip().splitlines()[0].strip() if out.stdout.strip() else ""
            if ip.startswith("100."):
                return ip
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def extra_host(cfg):
    web = cfg.get("web") or {}
    mode = web.get("bind", "loopback")
    if isinstance(mode, str) and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", mode):
        parts = [int(x) for x in mode.split(".")]
        private = (parts[0] == 10
                   or (parts[0] == 172 and 16 <= parts[1] <= 31)
                   or (parts[0] == 192 and parts[1] == 168)
                   or (parts[0] == 100 and 64 <= parts[1] <= 127))
        if parts[0] == 127:
            return None, "루프백 지정"
        if private and mode != "0.0.0.0":
            return mode, "명시 사설 IP"
        return None, f"★공인/전체 IP 바인딩 거부({mode}) — 루프백만★"
    if mode == "tailscale":
        ip = tailnet_ip()
        return (ip, "테일넷") if ip else (None, "테일넷 IP 미확보(테일스케일 정지?) — 루프백만")
    return None, "루프백만"


def bind_host(cfg) -> str:
    h, _why = extra_host(cfg)
    return h or "127.0.0.1"


from view_alerts import (  # noqa: F401
    _append_alert,
)


ALERT_WATCH_EVERY = 60
ALERT_WATCH_SAVE = 300


def _tg_connected() -> bool:
    try:
        import settings_store
        return bool(settings_store.env_value(settings_store.TG_TOKEN) and settings_store.env_value(settings_store.TG_CHAT))
    except Exception:   # noqa: BLE001 [fallback]
        return False


def _alert_view(prefs) -> dict:
    b9 = BUILDER.__dict__ if BUILDER is not None else {}
    f9 = ((b9.get("_last_out") or {}).get("fields")) or {}
    fu9 = f9.get("futures") if isinstance(f9.get("futures"), dict) else {}
    extra = {"futuresN": int(fu9.get("posCount") or 0), "lpOpen": sum(1 for x in (f9.get("lps") or []) if isinstance(x, dict) and not x.get("closed")),
             "built": bool(f9)}
    try:
        with other_assets.STORE_LOCK:
            d9 = other_assets.load_store()
        extra["oaAuto"] = sum(1 for x in (d9.get("items") or []) if isinstance(x, dict) and x.get("auto") in ("stock", "gold"))
        bc9 = (getattr(BUILDER, "cfg", None) or {}).get("brokers")
        extra["oaBrokers"] = sum(1 for v9 in (bc9 or {}).values() if isinstance(v9, dict) and v9.get("enabled") is True) if isinstance(bc9, dict) else 0
    except Exception:   # noqa: BLE001 [fallback]
        extra["oaAuto"] = extra["oaBrokers"] = 0
    return alert_prefs.view(prefs, tg_connected=_tg_connected(), extra=extra)


_PUBLIC_URL_RE = re.compile(r"https://(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(?::\d{1,5})?")


def public_url(cfg) -> str:
    try:
        u = str(((cfg or {}).get("web") or {}).get("public_url") or "").strip().rstrip("/")
    except AttributeError:
        return ""
    return u if u and len(u) <= 300 and _PUBLIC_URL_RE.fullmatch(u) else ""


def _alert_link_daily() -> str:
    try:
        u9 = public_url(getattr(BUILDER, "cfg", None))
        if u9:
            return f"보기: {u9}/v2/#daily"
    except Exception:   # noqa: BLE001 [optional]
        pass
    return "보기: 일별 기록 탭"


def _alert_watch_inputs(doc, conn, now):
    b9 = BUILDER
    out9 = b9.__dict__.get("_last_out")
    sp = getattr(b9, "spot", None)
    spot9 = {"usd": getattr(sp, "usd", None) or {}, "usd_ts": getattr(sp, "usd_ts", None) or {},
             "ex_usd": getattr(sp, "ex_usd", None) or {}, "ex_ts": getattr(sp, "ex_ts", None) or {},
             "dex_usd": getattr(sp, "dex_usd", None) or {}, "dex_ts": getattr(sp, "dex_ts", None) or {}} if sp is not None else None
    fut9 = oa9 = None
    if True:
        try:
            with other_assets.STORE_LOCK:
                d9 = other_assets.load_store()
            if any(isinstance(x, dict) and x.get("auto") in ("stock", "gold") for x in (d9.get("items") or [])) \
                    or any(isinstance(v9, dict) and v9.get("enabled") is True for v9 in ((getattr(b9, "cfg", None) or {}).get("brokers") or {}).values()):
                bc9 = (getattr(b9, "cfg", None) or {}).get("brokers")
                oa9 = other_assets.view(d9, _oa_quoter(), _oa_rate(), bc9 if isinstance(bc9, dict) else {})
        except Exception:   # noqa: BLE001 [fallback]
            oa9 = None
    try:
        import settings_store
        cur9 = "USD" if (settings_store.read_settings() or {}).get("currency") == "USD" else "KRW"
    except Exception:   # noqa: BLE001 [fallback]
        cur9 = "KRW"
    try:
        pub9 = public_url(getattr(b9, "cfg", None))
    except Exception:   # noqa: BLE001 [fallback]
        pub9 = ""
    return {"out": out9, "spot": spot9, "futures": fut9, "oa": oa9, "cur": cur9, "link_daily": _alert_link_daily(), "pub": pub9,
            "flows": b9.__dict__.get("_flow_ev")}


ALERT_FLOW_FRESH = 300


def _flow_rearm(st, now):
    st["flow2"] = {"boff": 1, "aoff": 1}
    st.pop("flow2_rearm_at", None)
    st["flow2_paused"] = 1


def _flow_fresh_kick(now):
    try:
        b9 = BUILDER
        snap9 = b9.snaps.cur
        if snap9 is None or now - float(snap9.at) >= ALERT_FLOW_FRESH:
            if snap9 is None or getattr(b9, "_built_sig", None) is None or b9._input_sig() != b9._built_sig:
                b9.kick_refresh()
    except Exception as e9:   # noqa: BLE001 [optional]
        log.warning("큰 출금 재료 재빌드 요청 실패(다음 판): %s", e9)


def alert_watch_once(st: dict, now: float = None) -> list:
    now = time.time() if now is None else now
    if not _tg_connected():
        _flow_rearm(st, now)
        return []
    prefs = BUILDER.prefs()
    doc = alert_prefs.load(prefs)
    conn = alert_prefs.connect_ts()
    if not any(alert_prefs.effective(doc, k, now, conn) for k in getattr(alert_watch, "WATCH_CATS", [k9 for k9, _fn in alert_watch.PRODUCERS])):
        _flow_rearm(st, now)
        return []
    if alert_prefs.effective(doc, "bigflow", now, conn) or alert_prefs.effective(doc, "arrive", now, conn):
        _flow_fresh_kick(now)
    snap9 = copy.deepcopy(st)
    inp9 = _alert_watch_inputs(doc, conn, now)
    if st.pop("flow2_paused", None):
        st["flow2_rearm_at"] = int(now)
    if "flow2_rearm_at" in st:
        fl9 = inp9.get("flows")
        try:
            fresh9 = isinstance(fl9, dict) and float(fl9.get("builtAt") or 0) >= float(st["flow2_rearm_at"])
        except (TypeError, ValueError):
            fresh9 = True
        if fresh9:
            st.pop("flow2_rearm_at", None)
        else:
            inp9 = dict(inp9, flows=None)
    alerts = alert_watch.step(inp9, doc, st, now, conn, log)
    try:
        for a9 in alerts:
            _append_alert(a9)
    except Exception:
        st.clear()
        st.update(snap9)
        raise
    if alerts:
        log.info("새 알림 %d건 적재: %s", len(alerts), ", ".join(sorted({a9["kind"] for a9 in alerts})))
    return alerts


def alert_watch_loop():
    time.sleep(150)
    st = alert_watch.load_state()
    last_save = time.time()
    while True:
        try:
            got = alert_watch_once(st)
            if got or time.time() - last_save >= ALERT_WATCH_SAVE:
                alert_watch.save_state(st)
                last_save = time.time()
        except (Exception, SystemExit) as e:   # noqa: BLE001 [boundary]
            log.warning("새 알림 생산자 실패(다음 판): %s", e)
        time.sleep(ALERT_WATCH_EVERY)


COVERAGE_EVERY = 24 * 3600
_COV_LOCK = threading.Lock()


def coverage_refresh():
    if not _COV_LOCK.acquire(blocking=False):
        return False
    try:
        d = coverage_limits.write()
        log.info("수집 한계 갱신: 소스 %d · 한계 %d", len(d.get("sources") or []), len(d.get("unavailable") or []))
        return True
    except (Exception, SystemExit) as e:  # noqa: BLE001 [fallback]
        log.warning("수집 한계 생성 실패(다음 주기): %s", e)
        return False
    finally:
        _COV_LOCK.release()


def coverage_loop():
    time.sleep(300)
    while True:
        try:
            age = time.time() - os.path.getmtime(paths.state(coverage_limits.OUT_NAME)) if os.path.exists(paths.state(coverage_limits.OUT_NAME)) else None
        except OSError:
            age = None
        if age is None or age >= COVERAGE_EVERY - 60:
            coverage_refresh()
        time.sleep(3600)


def _balcheck_defer_keys(state: dict) -> set:
    try:
        now9 = time.time()
        srcs = health.collect_sources(BUILDER.cfg, {}, now9)
        items = [m for m in (state.get("mismatches") or []) if m.get("confirmed")]
        _now9, late9 = health.balcheck_split({"items": items}, srcs)
        out9 = set()
        rest9 = health.tier_rest_map()
        for m in late9:
            try:
                lim9 = health.REST_LATE_MAX if health.rest_late(m, rest9, now9) else 86400
                if m.get("key") and 0 <= now9 - float(m.get("firstSeen") or 0) < lim9:
                    out9.add(m["key"])
            except (TypeError, ValueError):
                pass
        return out9
    except (Exception, SystemExit) as e:   # noqa: BLE001 [fallback]
        log.warning("잔고 대조 지연 대기 판정 실패(DM 은 종전대로): %s", e)
        return set()


def _hist_flows(fk, days, dpx, fx_day, fx_tx=None, att=None) -> dict:
    sh9 = StateBuilder.__new__(StateBuilder)
    sh9.daily = fk.get("wdt") or {}
    sh9.daily_px = {}
    sh9._flow_px_delta, sh9._att_fx_at, sh9._att_bf = {}, fx_tx, att
    today9 = datetime.strptime(fk.get("today") or datetime.now(KST).strftime("%Y-%m-%d"), "%Y-%m-%d").replace(tzinfo=KST)
    conn9 = dbm.open_db(paths.DB_PATH, readonly=True)
    try:
        return StateBuilder._daily_flows(sh9, conn9, None, fk.get("G") or {}, today9, {}, fk.get("skip") or frozenset(), fk.get("rate"),
                                         transit=fk.get("transit") or [], offc_ids=fk.get("offc") or frozenset(),
                                         days=list(days), dpx=dpx, fx_day=fx_day)
    finally:
        conn9.close()


histcurve.HIST.flow_fn = _hist_flows


def balcheck_loop():
    time.sleep(180)
    while True:
        st9 = balcheck.settings(BUILDER.cfg)
        if st9.get("enabled"):
            try:
                (BUILDER.latest(600) if hasattr(BUILDER, "latest") else BUILDER.build())
                prev = statefile.read_json(paths.state("onchain_check.json"), {}) \
                    if os.path.exists(paths.state("onchain_check.json")) else {}
                conn = dbm.open_db(paths.DB_PATH, readonly=True)
                try:
                    state = balcheck.run_once(BUILDER.cfg, conn,
                                              dict(getattr(BUILDER, "_live_px", {}) or {}),
                                              set(getattr(BUILDER, "_risk_quarantined", set()) or set()), prev)
                finally:
                    conn.close()
                new_alerts = balcheck.finalize(state, _balcheck_defer_keys(state))
                if new_alerts:
                    statefile.atomic_write_json(paths.state("onchain_check.json"), state)
                    _append_alert({"ts": int(time.time()), "kind": "BALANCE_MISMATCH",
                                   "text": balcheck.alert_text(new_alerts),
                                   "keys": sorted({str(m.get("key")) for m in new_alerts if m.get("key")})})
                    log.warning("온체인 잔고 불일치 알림 적재: %d건", len(new_alerts))
                else:
                    statefile.atomic_write_json(paths.state("onchain_check.json"), state)
                log.info("온체인 잔고 대조: %d항목·%d콜·불일치 %d(확정 %d)%s%s", state["checked"], state["calls"],
                         len(state["mismatches"]), sum(1 for m in state["mismatches"] if m.get("confirmed")),
                         " · 호출 상한 도달(부분)" if state["capped"] else "",
                         f" · 오류 {len(state['errors'])}" if state["errors"] else "")
                BUILDER.soft_invalidate()
            except (Exception, SystemExit) as e:  # noqa: BLE001 [boundary]
                log.warning("온체인 잔고 대조 실패(다음 주기): %s", e)
        try:
            iv = max(600, int(st9.get("interval_sec") or 3600))
        except (TypeError, ValueError):
            iv = 3600
        time.sleep(iv)


def chainsweep_more_wallets(prev: dict, cfg: dict, now: float = None) -> bool:
    try:
        n9 = len(chainsweep.wallets(cfg or {})[0])
        at9 = float((prev or {}).get("checkedAt") or 0)
        return bool(prev) and n9 > int((prev or {}).get("wallets") or 0) and (time.time() if now is None else now) - at9 >= 600
    except Exception:   # noqa: BLE001 [fallback]
        return False


def chainsweep_loop():
    time.sleep(240)
    _chain_auto_off()
    sp_once = False
    while True:
        st9 = chainsweep.settings(BUILDER.cfg)
        try:
            iv = max(3600, int(st9.get("interval_sec") or 86400))
        except (TypeError, ValueError):
            iv = 86400
        prev = chainsweep.view() or {}
        wait = iv - (time.time() - float(prev.get("checkedAt") or 0))
        if wait > 0 and chainsweep_more_wallets(prev, BUILDER.cfg):
            wait = 0
        if wait > 0:
            if not sp_once and st9.get("enabled"):
                sp_once = True
                try:
                    cfg9 = config.load_config()
                    gate9 = statefile.read_json(paths.ACTIVITY_GATE_PATH, {}) or {}
                    if chainsweep.missing_speed(cfg9, gate9):
                        chainsweep.speed_tick(cfg9, gate9)
                except (Exception, SystemExit) as e:   # noqa: BLE001 [boundary]
                    log.warning("체인 백필 속도 실측(빠진 체인) 실패(다음 점검 때): %s", e)
            time.sleep(min(wait, iv))
            continue
        if st9.get("enabled"):
            try:
                cfg9 = config.load_config()
                try:
                    bn9 = pricing.binance_spot_usdt()
                except Exception:   # noqa: BLE001 [fallback]
                    bn9 = {}
                spot9 = dict(getattr(BUILDER.spot, "usd", {}) or {})
                led9 = set()
                conn = dbm.open_db(paths.DB_PATH, readonly=True)
                try:
                    for r9 in conn.execute("SELECT DISTINCT location FROM postings WHERE location LIKE 'wallet:%'"):
                        p9 = str(r9[0] or "").split(":")
                        if len(p9) >= 3 and p9[2].startswith("0x"):
                            led9.add((p9[1], p9[2].lower()))
                finally:
                    conn.close()
                gate9 = statefile.read_json(paths.ACTIVITY_GATE_PATH, {}) or {}
                res = chainsweep.run_once(cfg9, price_fn=lambda sym: bn9.get(sym) or spot9.get(sym), gate=gate9, ledger_pairs=led9)
                statefile.atomic_write_json(paths.ACTIVITY_GATE_PATH, gate9)
                prev_auto = {(f["chain"], f["wallet"]) for f in (prev.get("autoEnabled") or [])}
                statefile.atomic_write_json(paths.state("chain_sweep.json"), logs.scrub_secrets(res)[0])
                log.info("미추적 체인 점검: 체인 %d·지갑 %d·JSON-RPC %d(HTTP %d)·오류 %d · 자동 켬 %d · 경고 %d%s", len(res["chains"]), res["wallets"],
                         res["calls"], res["http"], len(res["errors"]), len(res["autoEnabled"]), len(res["findings"]),
                         (" — " + " / ".join(chainsweep.finding_text(f) for f in res["findings"][:5])) if res["findings"] else "")
                new_auto = [f for f in res["autoEnabled"] if (f["chain"], f["wallet"]) not in prev_auto]
                if new_auto:
                    _append_alert({"ts": int(time.time()), "kind": "CHAIN_AUTO",
                                   "text": "[체인 자동 추적] 활동이 확인된 지갑을 추적에 넣었어요 (10분 안에 수집 시작):\n"
                                           + "\n".join("· " + chainsweep.finding_text(f) for f in new_auto[:10])})
                try:
                    chainsweep.speed_tick(cfg9, gate9)
                except (Exception, SystemExit) as e:   # noqa: BLE001 [boundary]
                    log.warning("체인 백필 속도 실측 실패(다음 판): %s", e)
                _chain_auto_off()
            except (Exception, SystemExit) as e:  # noqa: BLE001 [boundary]
                log.warning("미추적 체인 점검 실패(1시간 뒤 재시도): %s", e)
                time.sleep(3600)
                continue
        time.sleep(iv)


def _chain_auto_off():
    try:
        import chainoff
        off9 = chainoff.auto_off()
    except (Exception, SystemExit) as e:   # noqa: BLE001 [fallback]
        log.warning("체인 자동 끄기 실패(다음 점검 때): %s", logs.safe_err(e)[:160])
        return []
    if off9:
        log.info("체인 자동 끔(활동 없음 — 추천 조건): %s", ", ".join(off9))
        _append_alert({"ts": int(time.time()), "kind": "CHAIN_AUTO",
                       "text": "[체인 자동 끔] 지갑마다 보낸 거래가 거의 없고 최근 30일 활동이 없어 조회를 꺼 뒀어요: " + ", ".join(off9)
                               + "\n켜려면 설정 › 지갑 › 체인별 조회에서 스위치를 켜세요(다시 켠 체인은 자동으로 끄지 않아요)."})
    return off9


GOPLUS_BODY_MAX = 4 << 20


def _goplus_fetch(cid, ca_l):
    req = net_http.request(
        f"https://api.gopluslabs.io/api/v1/token_security/{cid}?contract_addresses={ca_l}",
        headers={"User-Agent": "tj-bot/0.1", "Accept": "application/json"})
    with net_http.urlopen(req, timeout=15) as r:
        return json.loads(net_http.read_capped(r, GOPLUS_BODY_MAX).decode())


def goplus_round(state: dict, now: float = None, fetch=None, sleep=None) -> int:
    now = time.time() if now is None else now
    fetch = fetch or _goplus_fetch
    sleep = sleep or time.sleep
    fail_until = state.setdefault("fail_until", {})
    lg = state.setdefault("log", {})
    same = state.setdefault("same", {})
    changed = False

    def perm_fail(key, sig, label):
        nonlocal changed
        ent9 = same.get(key)
        n9 = ent9[1] + 1 if ent9 and ent9[0] == sig else 1
        same[key] = [sig, n9]
        if n9 < GOPLUS_PERM_N:
            return False
        cache[key] = {"ts": int(now), "risk": {"strong": False, "label": label}, "perm": sig}
        same.pop(key, None)
        fail_until.pop(key, None)
        changed = True
        log.info("고플러스 %s: 같은 실패 응답 %d회(%s) — 무정보로 %d일 캐시", key, n9, sig, GOPLUS_TTL // 86400)
        return True

    def note(kind, detail):
        GOPLUS_STATUS.update({"lastErr": int(now), "err": f"{kind}: {detail}"[:160]})
        ent = lg.get(kind)
        if ent is None or now - ent[0] >= GOPLUS_LOG_EVERY:
            log.warning("고플러스 확증 조회 실패: %s — %s (최근 %d분 %d회)", kind, str(detail)[:120],
                        max(1, int((now - ent[0]) / 60)) if ent else 1, (ent[1] if ent else 0) + 1)
            lg[kind] = [now, 0]
        else:
            ent[1] += 1

    if now < GOPLUS_STATUS.get("limitedUntil", 0):
        return 0
    want = list(getattr(BUILDER, "_goplus_want", None) or [])
    off9 = set((getattr(BUILDER, "cfg", None) or {}).get("_disabled_chains") or [])
    want = [p for p in want if p and p[0] not in off9]
    if not want:
        return 0
    cache = statefile.read_json(paths.state("goplus_cache.json"), {}) if os.path.exists(paths.state("goplus_cache.json")) else {}
    new9, exp9, deferred = [], [], 0
    seen9 = set()
    for ch, ca in want:
        cid = GOPLUS_CHAIN_ID.get(ch)
        ca_l = (ca or "").lower()
        key = f"{ch}:{ca_l}"
        if not cid or not ca_l or key in seen9:
            continue
        seen9.add(key)
        ent = cache.get(key)
        if ent and now - (ent.get("ts") or 0) < GOPLUS_TTL:
            continue
        if fail_until.get(key, 0) > now:
            deferred += 1
            continue
        (exp9 if ent else new9).append((ch, ca_l, cid, key))
    exp9.sort(key=lambda x9: (cache.get(x9[3]) or {}).get("ts") or 0)
    GOPLUS_STATUS.update({"pendingNew": len(new9), "pendingExpired": len(exp9), "deferred": deferred})
    done = 0
    for ch, ca_l, cid, key in new9 + exp9:
        if done >= 9:
            break
        done += 1
        try:
            d = fetch(cid, ca_l)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                GOPLUS_STATUS["limitedUntil"] = int(now + GOPLUS_LIMIT_SEC)
                note("한도", f"HTTP 429 · {GOPLUS_LIMIT_SEC}초 쉼")
                break
            if 400 <= e.code < 500 and perm_fail(key, f"HTTP {e.code}", f"조회 불가(고플러스 HTTP {e.code})"):
                sleep(6.7)
                continue
            fail_until[key] = now + GOPLUS_FAIL_RETRY
            note(f"HTTP {e.code}", f"{key} — 이 CA 만 1시간 뒤 재시도")
            sleep(6.7)
            continue
        except net_http.ResponseTooLarge as e:
            fail_until[key] = now + GOPLUS_FAIL_RETRY
            note("응답 큼", f"{logs.safe_err(e)[:60]} ({key}) — 이 CA 만 1시간 뒤 재시도")
            sleep(6.7)
            continue
        except Exception as e:   # noqa: BLE001 [isolate]
            fail_until[key] = now + GOPLUS_FAIL_RETRY
            state["net_fail"] = state.get("net_fail", 0) + 1
            note("연결", f"{type(e).__name__}: {logs.safe_err(e)[:60]} ({key})")
            if state["net_fail"] >= 3:
                state["net_fail"] = 0
                break
            sleep(6.7)
            continue
        state["net_fail"] = 0
        code = d.get("code") if isinstance(d, dict) else None
        if code == 4029:
            GOPLUS_STATUS["limitedUntil"] = int(now + GOPLUS_LIMIT_SEC)
            note("한도", f"code 4029 · {GOPLUS_LIMIT_SEC}초 쉼")
            break
        if code == 3 and isinstance(d, dict) and isinstance(d.get("result"), dict) and d["result"].get(ca_l):
            code = 1
        if code not in (1, 2):
            msg9 = (d.get("message") if isinstance(d, dict) else "") or "응답 형식 이상"
            if perm_fail(key, f"code {code}: {str(msg9)[:40]}", f"조회 불가(고플러스 code {code})"):
                sleep(6.7)
                continue
            fail_until[key] = now + GOPLUS_FAIL_RETRY
            note(f"code {code}", f"{key} {str(msg9)[:60]} — 이 CA 만 1시간 뒤 재시도")
            sleep(6.7)
            continue
        res = ((d.get("result") or {}).get(ca_l)) or {}
        if res:
            strong = [k for k in ("is_airdrop_scam", "is_honeypot", "cannot_sell_all", "is_fake_token")
                      if str(res.get(k) or "") == "1"]
            weak = [k for k in ("is_mintable", "is_proxy", "is_blacklisted", "transfer_pausable")
                    if str(res.get(k) or "") == "1"]
            label = ("스캠 확증 " + "·".join(strong)) if strong else \
                (("주의 " + "·".join(weak)) if weak else "특이신호 없음")
        else:
            strong, label = [], "미등재(무정보)"
        cache[key] = {"ts": int(now), "risk": {"strong": bool(strong), "label": label}}
        fail_until.pop(key, None)
        same.pop(key, None)
        GOPLUS_STATUS["lastOk"] = int(now)
        changed = True
        sleep(6.7)
    if changed:
        statefile.atomic_write_json(paths.state("goplus_cache.json"), cache)
        BUILDER.soft_invalidate()
    for k9 in [k9 for k9, t9 in fail_until.items() if t9 <= now - GOPLUS_FAIL_RETRY]:
        fail_until.pop(k9, None)
    return done


def goplus_state_load(path=None) -> dict:
    try:
        d = statefile.read_json(path or paths.state("goplus_status.json"), {}) if os.path.exists(path or paths.state("goplus_status.json")) else {}
    except (Exception, SystemExit):   # noqa: BLE001 [fallback]
        d = {}
    st = {}
    if isinstance(d, dict):
        same = d.get("same")
        if isinstance(same, dict):
            st["same"] = {k: [str(v[0]), int(v[1])] for k, v in same.items()
                          if isinstance(v, list) and len(v) == 2 and isinstance(v[1], (int, float))}
        fu = d.get("failUntil")
        if isinstance(fu, dict):
            st["fail_until"] = {k: float(v) for k, v in fu.items() if isinstance(v, (int, float))}
    return st


def goplus_status_doc(state: dict) -> dict:
    doc = dict(GOPLUS_STATUS)
    if state.get("same"):
        doc["same"] = dict(list(state["same"].items())[-500:])
    if state.get("fail_until"):
        doc["failUntil"] = {k: int(v) for k, v in state["fail_until"].items()}
    return doc


def goplus_loop():
    state = goplus_state_load()
    last_st = None
    while True:
        try:
            goplus_round(state)
            doc9 = goplus_status_doc(state)
            st9 = json.dumps(doc9, sort_keys=True)
            if st9 != last_st:
                statefile.atomic_write_json(paths.state("goplus_status.json"), doc9)
                last_st = st9
        except (Exception, SystemExit) as e:  # noqa: BLE001 [boundary]
            log.warning("goplus loop 오류(다음 주기): %s", e)
        time.sleep(60)


PLAN_PX_MAX_AGE = 600
PLAN_PX_BLIND_AGE = 1800


def _plan_px_stale(c: dict, built_at, now: float):
    if c.get("pxFrozen"):
        return None, "멈춘 값(끈 체인의 마지막 값)"
    a9 = c.get("pxAge")
    if a9 is None:
        return None
    try:
        age = float(a9) + max(0.0, float(now) - float(built_at or now))
    except (TypeError, ValueError):
        return None
    if age <= PLAN_PX_MAX_AGE:
        return None
    return age, (f"약 {int(age // 3600)}시간" if age >= 3600 else f"약 {max(1, int(age // 60))}분") + " 전 값"


def plan_monitor_loop():
    while True:
        time.sleep(60)
        try:
            if not any(isinstance(p9, dict) and p9.get("target") not in (None, "") and p9.get("stop") not in (None, "")
                       for p9 in (BUILDER.prefs().get("plans") or {}).values()):
                continue
            st = BUILDER.latest(90) if hasattr(BUILDER, "latest") else BUILDER.build()
            coins = {c["key"]: c for c in st["fields"]["coins"]}
            plans = st["fields"]["plans"]
            sent = statefile.read_json(paths.state("alerts_sent_web.json"), {}) if os.path.exists(paths.state("alerts_sent_web.json")) else {}
            today = datetime.now(KST).strftime("%Y-%m-%d")
            changed = False
            for key, pl in plans.items():
                c = coins.get(key)
                if not c or not c.get("price"):
                    continue
                px = c["price"]
                hits = []
                lk9 = alert_watch._link({"pub": public_url(getattr(BUILDER, "cfg", None))}, "journal")
                why9 = _plan_px_stale(c, st.get("builtAt"), time.time())
                if why9 and (why9[0] is None or why9[0] > PLAN_PX_BLIND_AGE):
                    hits.append(("PLAN_BLIND", f"🔴 {c['sym']} 목표가·손절 감시를 못 하고 있어요\n가격이 {why9[1]}이라 지금 닿았는지 알 수 없어요 — 거래소(앱·웹)에서 직접 확인하세요.\n"
                                               f"마지막 가격 {alert_watch.px_txt(px)} · 목표 {alert_watch.px_txt(pl['target'])} · 손절 {alert_watch.px_txt(pl['stop'])}" + lk9))
                elif not why9 and px >= pl["target"]:
                    hits.append(("TARGET_HIT", f"🔴 {c['sym']} 목표가에 닿았어요\n팔 계획이었다면 지금이에요.\n"
                                               f"지금 {alert_watch.px_txt(px)} · 목표 {alert_watch.px_txt(pl['target'])}" + lk9))
                if not why9 and px <= pl["stop"]:
                    hits.append(("STOP_HIT", f"🔴 {c['sym']} 손절선 아래로 내려왔어요\n계획대로라면 지금 정리할 때예요.\n"
                                             f"지금 {alert_watch.px_txt(px)} · 손절 {alert_watch.px_txt(pl['stop'])}" + lk9))
                for kind, text in hits:
                    dk = f"{key}:{kind}"
                    if sent.get(dk) == today:
                        continue
                    _append_alert({
                        "ts": int(time.time()), "kind": kind, "sym": c["sym"], "text": text})
                    sent[dk] = today
                    changed = True
                    log.info("가격알림 적재: %s", text)
            if changed:
                statefile.atomic_write_json(paths.state("alerts_sent_web.json"), sent)
        except (Exception, SystemExit) as e:  # noqa: BLE001 [boundary]
            log.warning("plan monitor 실패(다음 주기): %s", e)


def ext_bind_step(cfg, port: int, ext: dict):
    try:
        want, why = extra_host(cfg)
        if why != ext["why"]:
            (log.error if "거부" in why else log.info)("추가 바인딩 상태: %s%s", why,
                                                      f" ({want})" if want else "")
            ext["why"] = why
        if ext["srv"] is not None and (want != ext["host"] or not ext["thread"].is_alive()):
            log.info("추가 바인딩 해제: %s", ext["host"])
            try:
                ext["srv"].shutdown()
                ext["srv"].server_close()
            except Exception:  # noqa: BLE001 [optional]
                pass
            ext.update(srv=None, host=None, thread=None)
        if want and ext["srv"] is None:
            try:
                srv2 = QuietHTTPServer((want, port), Handler)
            except OSError as e:
                if ext.get("bind_err") != logs.safe_err(e):
                    log.warning("추가 바인딩 실패(%s:%d, 60초 뒤 재시도): %s", want, port, e)
                    ext["bind_err"] = logs.safe_err(e)
            else:
                t2 = threading.Thread(target=srv2.serve_forever, daemon=True, name="http-ext")
                t2.start()
                ext.update(srv=srv2, host=want, thread=t2, bind_err=None)
                log.info("가동: http://%s:%d (%s)", want, port, why)
    except Exception as e:  # noqa: BLE001 [optional]
        log.warning("바인딩 감시 오류(다음 주기): %s", e)


class QuietHTTPServer(ThreadingHTTPServer):
    MAX_CONN = 256
    PER_IP = 32
    request_queue_size = 128

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._conn_sem = threading.BoundedSemaphore(max(8, int(self.MAX_CONN)))
        self._ip_lock = threading.Lock()
        self._ip_n = {}

    @staticmethod
    def _loopback(ip) -> bool:
        s = str(ip or "")
        return s.startswith(("127.", "::ffff:127.")) or s == "::1"

    def _ip_take(self, client_address) -> bool:
        ip = client_address[0] if isinstance(client_address, tuple) and client_address else ""
        if self._loopback(ip):
            return True
        with self._ip_lock:
            n = self._ip_n.get(ip, 0)
            if n >= max(1, int(self.PER_IP)):
                return False
            self._ip_n[ip] = n + 1
        return True

    def _ip_give(self, client_address):
        ip = client_address[0] if isinstance(client_address, tuple) and client_address else ""
        if self._loopback(ip):
            return
        with self._ip_lock:
            n = self._ip_n.get(ip, 0) - 1
            if n > 0:
                self._ip_n[ip] = n
            else:
                self._ip_n.pop(ip, None)

    def process_request(self, request, client_address):
        if not self._ip_take(client_address):
            return self._refuse(request)
        if not self._conn_sem.acquire(blocking=False):
            self._ip_give(client_address)
            return self._refuse(request)
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._conn_sem.release()
            self._ip_give(client_address)
            raise

    def _refuse(self, request):
        try:
            request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        except OSError:
            pass
        self.shutdown_request(request)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._conn_sem.release()
            self._ip_give(client_address)

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return
        logs.print_request_error(client_address)


def _login_startup_warnings(cfg):
    try:
        web9 = (cfg or {}).get("web") or {}
        mode9 = web9.get("bind", "loopback")
        ext9, _why = extra_host(cfg)
        tail9 = isinstance(ext9, str) and ext9.startswith("100.") and 64 <= int(ext9.split(".")[1]) <= 127
        if not login_auth.S.enabled:
            if ext9 or mode9 == "tailscale":
                log.error("★웹 로그인이 꺼져 있어요(allow_lan_without_password) — %s(%s)에 닿는 누구나 대시보드를 보고 바꿀 수 있어요★ config.json web.login.enabled 를 "
                          "true 로(또는 키 삭제) 바꾸고 tj-web 을 다시 시작하세요", ext9 or "테일넷 IP", "테일넷" if tail9 or not ext9 else "사설망")
            else:
                log.error("웹 로그인이 꺼져 있어요(web.login.enabled=false) — 이 컴퓨터의 다른 프로그램·사용자도 대시보드를 열 수 있어요. "
                          "리버스 프록시·터널 요청은 거부합니다(403). 켜려면 enabled 를 true 로(또는 키 삭제)")
        elif ext9 and not tail9 and not ((web9.get("login") or {}).get("secure_cookie") is True if isinstance(web9.get("login"), dict) else False):
            log.warning("웹 로그인 켜짐 · 사설 IP(%s) 바인딩은 HTTP 라 비밀번호·로그인 쿠키가 같은 네트워크에 암호화 없이 오가요 — "
                        "테일넷(bind \"tailscale\")이나 HTTPS 리버스 프록시를 쓰세요(bind=%s)", ext9, mode9)
    except Exception as e:   # noqa: BLE001 [optional]
        log.warning("로그인 상태 안내 실패: %s", type(e).__name__)


def port_busy_exit(port: int, e: OSError, demo: bool = False):
    import errno
    if getattr(e, "errno", None) not in (errno.EADDRINUSE, 10048):
        raise e
    if demo:
        msg = f"포트 {port} 을(를) 다른 프로그램이 쓰고 있어요 — 데모는 TJ_PORT=다른번호 로 다시 실행하세요(예: TJ_PORT=8024 bash tools/setup.sh --demo)"
    else:
        msg = (f"포트 {port} 을(를) 다른 프로그램이 쓰고 있어요 — config.json 의 web.port 를 바꾸고 tj-web 을 다시 시작하세요"
               f"(TJ_PORT 환경변수는 데모 전용이라 일반 실행에선 쓰지 않아요)")
    log.error(msg)
    raise SystemExit(2)


def main():
    global BUILDER
    if onboarding.demo_main(sys.modules[__name__]):
        return
    paths.ensure_dirs()
    ms9 = globals().get("_SQLITE_MEMSTAT_OFF")
    if ms9 is not None:
        log.info("SQLite 메모리 통계 %s — %s(빌드 자식 교착 방지 — fork 순간 다른 스레드가 쥔 전역 뮤텍스)",
                 "끔" if ms9 is True else ("끄기 시도함 · 적용 확인 불가" if ms9 == "unverified" else "못 끔(종전 — 교착이면 다시 fork)"),
                 runtime.SQLITE_MEMSTAT_WHY[0] or "-")
    try:
        buildproc.sweep_tmp()
    except Exception as e9:   # noqa: BLE001 [boundary]
        log.warning("임시 파일 정리 실패: %s", type(e9).__name__)
    if paths.tighten_config_mode():
        log.info("config.json 권한을 본인만 읽게(0600) 좁혔어요 — 증권사 비밀값이 들어갈 수 있는 파일이에요")
    cfg = config.load_config()
    bf_engine.configure(cfg)
    try:
        tp9, cp9 = str(os.environ.get("TJ_PORT") or "").strip(), int((cfg.get("web") or {}).get("port", 8023))
        if tp9 and tp9 != str(cp9):
            log.warning("TJ_PORT=%s 는 데모(TJ_DEMO=1) 전용이라 무시해요 — 일반 실행 포트는 config.json 의 web.port(지금 %d)", tp9[:8], cp9)
    except (TypeError, ValueError):
        pass
    try:
        n9 = (logs.scrub_secret_file(paths.state(coverage_limits.OUT_NAME)) + bf_engine.scrub_status_file()
              + logs.scrub_secret_file(paths.state("chain_sweep.json")))
        if n9:
            log.info("수정 전 상태 문구 %d칸 비밀값 가림(수집 한계·백필 진행)", n9)
    except Exception as e9:   # noqa: BLE001 [boundary]
        log.warning("상태 문구 비밀값 정리 실패(서빙 때 가림): %s", type(e9).__name__)
    try:
        histcurve.migrate_px1004()
    except Exception as e9:   # noqa: BLE001 [boundary]
        log.warning("px1004 이관 실패(다음 기동에 다시): %s", logs.safe_err(e9)[:160])
    login_auth.init(cfg, lan=extra_host(cfg)[0])
    BUILDER = StateBuilder()
    import chainoff
    chainoff.BAL_FN = _chain_usd_now
    chainoff.AUTO_INFO_FN = _chain_auto_off_info
    BUILDER.restore_snapfile()
    threading.Thread(target=BUILDER.spot.loop, daemon=True).start()
    threading.Thread(target=plan_monitor_loop, daemon=True).start()
    threading.Thread(target=goplus_loop, daemon=True).start()
    threading.Thread(target=balcheck_loop, daemon=True, name="balcheck").start()
    threading.Thread(target=coverage_loop, daemon=True, name="coverage").start()
    threading.Thread(target=chainsweep_loop, daemon=True, name="chainsweep").start()
    threading.Thread(target=cgca.loop, daemon=True, name="cgca").start()
    threading.Thread(target=snapshot_refresher, daemon=True, name="snap-refresh").start()
    threading.Thread(target=histcurve.HIST.worker, daemon=True, name="curve-hist").start()
    threading.Thread(target=histcurve.DAYCLOSE.worker, daemon=True, name="day-close").start()
    threading.Thread(target=_oa_quoter().loop, daemon=True, name="other-assets").start()
    threading.Thread(target=_nft_tracker().loop, daemon=True, name="nft").start()
    search_index.start(lambda: (getattr(BUILDER, "_last_out", None), getattr(BUILDER, "_day_idx", None)),
                       nft_fn=lambda: _nft_tracker().view(), chain_names=CHAIN_NAME)
    threading.Thread(target=alert_watch_loop, daemon=True, name="alert-watch").start()
    port = int((cfg.get("web") or {}).get("port", 8023))
    try:
        mc9 = (cfg.get("web") or {}).get("max_conn")
        if isinstance(mc9, int) and not isinstance(mc9, bool) and 8 <= mc9 <= 4096:
            QuietHTTPServer.MAX_CONN = mc9
        pi9 = (cfg.get("web") or {}).get("max_conn_per_ip")
        if isinstance(pi9, int) and not isinstance(pi9, bool) and 1 <= pi9 <= 4096:
            QuietHTTPServer.PER_IP = pi9
        import resource
        so9, hd9 = resource.getrlimit(resource.RLIMIT_NOFILE)
        want9 = 4096 if hd9 == resource.RLIM_INFINITY else min(hd9, 4096)
        if so9 != resource.RLIM_INFINITY and so9 < want9:
            resource.setrlimit(resource.RLIMIT_NOFILE, (want9, hd9))
    except (ImportError, ValueError, OSError) as e9:
        log.info("파일 한도 올리기 건너뜀: %s", e9)
    try:
        lo = QuietHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e9:
        port_busy_exit(port, e9)
    lo_t = threading.Thread(target=lo.serve_forever, daemon=True, name="http-lo")
    lo_t.start()
    log.info("가동: http://127.0.0.1:%d (루프백)", port)
    _login_startup_warnings(cfg)
    ext = {"srv": None, "host": None, "thread": None, "why": None, "bind_err": None}
    while True:
        if not lo_t.is_alive():
            raise SystemExit("루프백 서버 스레드 사망 — pm2 재시작으로 복구")
        ext_bind_step(cfg, port, ext)
        time.sleep(60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("정지 신호(SIGINT) — 종료")
