"""EVM wallet watcher (RPC and explorer based)."""
import hashlib
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
import re
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config, envfile, logs, paths, runtime, statefile
if __name__ == "__main__":
    runtime.cpu_reserve_apply()
import lpdec
import bf_engine
import tsfix
import addr_tier
from inbox import SegmentWriter

from evm_base import (  # noqa: F401
    _dm,
    _ES_DAILY,
    _ES_DAILY_LOCK,
    _ES_Q,
    _ES_WMEM,
    _is_http_5xx,
    _revoke_stamp_disk,
    _ScanLog,
    BisectBudget,
    BsDetailCap,
    ChainDisabled,
    DISCOVERY_PAGES_MAX,
    es_daily_left,
    ES_DAILY_MARGIN,
    ES_DAILY_PROBE,
    es_daily_trip,
    es_is_daily_limit,
    EtherscanDailyLimit,
    EtherscanKeyError,
    EtherscanPaced,
    EXPLORER_FROZEN_SEC,
    HoldError,
    http_json,
    HTTP_RETRIES,
    leaf_overflow_read,
    RETENTION_CONFIRM_SEC,
    retention_summary,
    rpc_handback,
    StateUnavailable,
    TRACE_DEPTH_MAX,
    trace_fail_index,
    trace_path_failed,
    TraceDeferred,
)


log = logs.setup_logging("tj-evm")


ES_FALLBACK_STREAK = 3


def es_fallback_watcher(cfg: dict, wt, writer, daily: bool = False, why: str = None):
    why9 = "day" if daily else (why or "es_fail")
    dead9 = ("rpc_first" if evm_route(cfg, wt.chain, decide=False) == "rpc_first" else None) or rpcfb_bs_dead(cfg, wt.chain)
    if dead9:
        nw9 = rpcfb_enter(cfg, wt.chain, wt.wallets, writer, "etherscan", why9, err=f"이더스캔 {RPCFB_WHY.get(why9, why9)}", bs=dead9)
        if nw9 is not None:
            return nw9
    elif not daily:
        rpcfb_note_es_bad(wt.chain, why9)
    if not cfg["chains"].get(wt.chain, {}).get("blockscout"):
        if daily:
            return wt
        import chaincatalog
        if chaincatalog.es_only(cfg["chains"].get(wt.chain)):
            log.warning("%s: etherscan 경로 실패 — 이더스캔 전용 체인이라 다른 경로 없이 기다림(다음 주기 재시도)", wt.chain)
            return wt
        log.error("%s: etherscan 경로 실패 — blockscout 미구성이라 폴백 불가", wt.chain)
        _dm("ES_FALLBACK_NONE", f"[{wt.chain}] Etherscan 경로 실패인데 blockscout 미구성 — 키/설정 확인 필요")
        return wt
    nw = ChainWatcher(cfg, wt.chain, wt.wallets, writer)
    if daily:
        log.warning("%s: ★이더스캔 하루 한도 → blockscout 임시 폴백★ (%s 뒤 자동 복귀 시도)", wt.chain,
                    time.strftime("%m-%d %H:%M", time.localtime(_ES_DAILY["until"])))
        return nw
    log.error("%s: ★etherscan 경로 → blockscout 런타임 폴백★ (재시작 전까지 유지)", wt.chain)
    _dm("ES_FALLBACK", f"[{wt.chain}] Etherscan 실패(키 거부/연속 실패) → blockscout 폴백으로 전환. TJ_ETHERSCAN_KEY 확인 후 tj-evm 재시작하면 복귀")
    return nw


def es_on_cycle_error(cfg: dict, wt, e: BaseException, es_fail: int, writer):
    if not isinstance(wt, EtherscanWatcher):
        return wt, es_fail, False
    daily = isinstance(e, EtherscanDailyLimit)
    es_fail = ES_FALLBACK_STREAK if isinstance(e, EtherscanKeyError) else es_fail + 1
    if es_fail < ES_FALLBACK_STREAK:
        return wt, es_fail, False
    nw = es_fallback_watcher(cfg, wt, writer, daily=daily, why="key" if isinstance(e, EtherscanKeyError) else "es_fail")
    return nw, 0, daily and nw is not wt


def _es_bs_unfinished(cur) -> bool:
    if not isinstance(cur, dict):
        return False
    return (isinstance(cur.get("_bfjob"), dict) or isinstance(cur.get("_ext_internal_pending"), dict)
            or any(str(k).startswith("_bf:") and isinstance(v, dict) for k, v in cur.items()))


def es_bs_busy(chain: str, wt=None) -> bool:
    if wt is not None and (getattr(wt, "enrich", None) or getattr(wt, "pending_detail", None)
                           or _es_bs_unfinished(getattr(wt, "cursor", None))):
        return True
    if _es_bs_unfinished(statefile.read_json(paths.state(f"cursor_evm_{chain}.json"), {})):
        return True
    return any(statefile.read_json(paths.state(n9), {})
               for n9 in (f"enrich_{chain}.json", f"pending_detail_{chain}.json"))


def es_daily_return(cfg: dict, wt, make):
    if isinstance(wt, EtherscanWatcher):
        return wt, False
    if es_daily_left() > 0:
        return wt, True
    if es_bs_busy(wt.chain, wt):
        if not getattr(wt, "_es_ret_wait_logged", False):
            wt._es_ret_wait_logged = True
            log.info("%s: 이더스캔 하루 한도 창 끝 — blockscout 큐·백필·internal 재수집 잔존, 끝나면 복귀", wt.chain)
        return wt, True
    try:
        nw = make(cfg, wt.chain, wt.wallets)
    except (Exception, SystemExit) as e9:   # noqa: BLE001 [fallback]
        log.warning("%s: 이더스캔 복귀 워처 생성 실패(blockscout 유지·다음 사이클 재시도): %s", wt.chain, e9)
        return wt, True
    if not isinstance(nw, EtherscanWatcher):
        return wt, True
    log.warning("★%s: 이더스캔 하루 한도 창 종료 — etherscan 경로 복귀★", wt.chain)
    return nw, False


def es_daily_restore(until: float):
    with _ES_DAILY_LOCK:
        if float(until) > _ES_DAILY["until"]:
            _ES_DAILY["until"] = float(until)
            _ES_DAILY["dm_at"] = max(float(_ES_DAILY.get("dm_at") or 0.0), time.time())


RPCFB_FILE = "rpc_fallback.json"
RPCFB_MIN_STAY = 1800
RPCFB_STAY_MAX = 6 * 3600
RPCFB_FLAP_WIN = 6 * 3600
RPCFB_PROBE_SEC = 900
RPCFB_ES_PROBE_SEC = 3600
RPCFB_BS_403_N = 2
RPCFB_BS_FAIL_N = 5
RPCFB_BS_DEAD_TTL = 24 * 3600
RPCFB_PACE_SEC = 1200
RPCFB_PACE_ROOM = 0.02
RPCFB_DM_GAP = 12 * 3600
RPCFB_WHY = {"day": "하루 한도 쉼", "pace": "하루 예산 페이싱으로 새 거래 확인이 막힘", "key": "이더스캔 키 거부", "es_fail": "이더스캔 연속 실패",
             "queue": "블록스카웃 미완 큐를 RPC 가 이어받음", "bs403": "블록스카웃 403(Cloudflare)", "bs_fail": "블록스카웃 연속 실패",
             "bs_frozen": "블록스카웃 색인 정지", "bs_none": "블록스카웃 미구성", "rpc_first": "블록스카웃 건너뜀(RPC 우선)"}
_RPCFB_LOCK = threading.RLock()
_RPCFB_MEM = {}
_RPCFB_RESUMED = set()
_RPCFB_RETURNING = set()
RPCFB_ON = {}
CUR_WATCHER = {}


def _rpcfb_path() -> str:
    return paths.state(RPCFB_FILE)


def _rpcfb_all() -> dict:
    d = statefile.read_json(_rpcfb_path(), {})
    return d if isinstance(d, dict) else {}


def rpcfb_get(chain: str) -> dict:
    r = _rpcfb_all().get(chain)
    return dict(r) if isinstance(r, dict) else {}


def _rpcfb_put(chain: str, rec):
    with _RPCFB_LOCK:
        d = _rpcfb_all()
        if rec:
            d[chain] = rec
        else:
            d.pop(chain, None)
        statefile.atomic_write_json(_rpcfb_path(), d)


def _rpcfb_text(rec: dict) -> str:
    prim = "이더스캔" if rec.get("src") == "etherscan" else "블록스카웃"
    why = str(rec.get("why") or "")
    t9 = RPCFB_WHY.get(why, why)
    if why == "day" and rec.get("until"):
        t9 += f" — {time.strftime('%H:%M', time.localtime(float(rec['until'])))} 저절로 복귀"
    elif why == "pace":
        t9 += " — 몫이 차면 복귀"
    elif why in ("key", "es_fail"):
        t9 += f" — {RPCFB_ES_PROBE_SEC // 60}분마다 다시 시험"
    elif prim == "블록스카웃" and why != "bs_none":
        t9 += f" — {RPCFB_PROBE_SEC // 60}분마다 다시 시험"
    bs9 = rec.get("bs")
    if bs9 and bs9 != why and rec.get("src") == "etherscan":
        t9 += " · " + RPCFB_WHY.get(bs9, bs9)
    if rec.get("nokey"):
        t9 += " · 이더스캔 키 없음"
    out = f"{prim} 대신 RPC 로 확인 중({t9})"
    if rec.get("limited"):
        out += f" · 제한된 백업({rec['limited']})"
    return out


def _rpcfb_info(rec: dict) -> dict:
    return {k: rec.get(k) for k in ("src", "why", "bs", "since", "until", "limited", "text", "nokey")}


def _rpcfb_swap(chain: str):
    try:
        bf_engine.health("evm").reset_facts(chain)
    except Exception:   # noqa: BLE001 [optional]
        pass


def rpcfb_bs_dead(cfg: dict, chain: str):
    cc = (cfg.get("chains") or {}).get(chain) or {}
    if not cc.get("blockscout"):
        return "bs_none"
    bd = rpcfb_get(chain).get("bs_dead")
    if isinstance(bd, dict) and time.time() - float(bd.get("at") or 0) < RPCFB_BS_DEAD_TTL:
        return str(bd.get("why") or "bs_fail")
    return None


def rpcfb_note_es_bad(chain: str, why: str):
    with _RPCFB_LOCK:
        rec = rpcfb_get(chain)
        rec["es_bad"] = {"at": int(time.time()), "why": why}
        _rpcfb_put(chain, rec)


def rpcfb_allowed(cfg: dict, chain: str) -> bool:
    if (cfg or {}).get("rpc_fallback") is False:
        return False
    return (((cfg or {}).get("chains") or {}).get(chain) or {}).get("rpc_fallback") is not False


def rpcfb_enter(cfg: dict, chain: str, wallets: list, writer, src: str, why: str, err: str = None, bs: str = None,
                bs_seen: bool = False, nokey: bool = False):
    if (_RPCFB_MEM.get(chain) or {}).get("broken") or not rpcfb_allowed(cfg, chain):
        return None
    try:
        nw = RpcChainWatcher(cfg, chain, wallets, writer)
    except (Exception, SystemExit) as e:   # noqa: BLE001 [fallback]
        log.error("%s RPC 대체 수집기 생성 실패(종전 경로 유지): %s", chain, logs.redact_urls(logs.safe_err(e))[:160])
        return None
    now = time.time()
    with _RPCFB_LOCK:
        rec = rpcfb_get(chain)
        stay = RPCFB_MIN_STAY
        if rec.get("exit_at") and now - float(rec["exit_at"]) < RPCFB_FLAP_WIN:
            stay = min(RPCFB_STAY_MAX, max(RPCFB_MIN_STAY, int(rec.get("stay") or RPCFB_MIN_STAY)) * 2)
        ent9 = [t for t in (rec.get("entries") or []) if isinstance(t, (int, float)) and now - t < 86400][-9:] + [int(now)]
        dm9 = why != "day" and now - float(rec.get("dm_at") or 0) > RPCFB_DM_GAP
        rec.update(active=True, src=src, why=why, bs=bs, nokey=bool(nokey) or None,
                   err=logs.redact_urls(logs.redact_secret_text(logs.redact_urls(str(err or "")), generic=False))[:160] or None,
                   since=int(now), stay=int(stay), next_probe=int(now + stay), entries=ent9,
                   until=int(_ES_DAILY["until"]) if why == "day" and _ES_DAILY["until"] > now else None,
                   limited=getattr(nw, "nodes_limited", None))
        if bs and bs_seen:
            rec["bs_dead"] = {"at": int(now), "why": bs}
        if why in ("key", "es_fail"):
            rec["es_bad"] = {"at": int(now), "why": why}
        if dm9:
            rec["dm_at"] = int(now)
        rec["text"] = _rpcfb_text(rec)
        _rpcfb_put(chain, rec)
    nw.fb_info = _rpcfb_info(rec)
    RPCFB_ON[chain] = nw.fb_info
    _rpcfb_swap(chain)
    log.warning("★%s %s — 같은 커서 파일을 RPC 전용 수집기가 이어받음(최소 %d분 · 살아나면 자동 복귀)★ %s", chain, rec["text"], stay // 60,
                rec.get("err") or "")
    if dm9:
        _dm("RPC_FALLBACK", f"[{chain}] {rec['text']} — 새 거래는 공개 RPC 로 계속 받아요(살아나면 자동 복귀 · 재시작 불필요)")
    return nw


def rpcfb_resume(cfg: dict, chain: str, wallets: list, writer, es_key: str):
    rec = rpcfb_get(chain)
    if not rec.get("active") or (_RPCFB_MEM.get(chain) or {}).get("broken"):
        return None
    cc = cfg["chains"].get(chain) or {}
    now = time.time()
    if not rpcfb_allowed(cfg, chain):
        with _RPCFB_LOCK:
            rec.update(active=False, exit_at=int(now))
            _rpcfb_put(chain, rec)
        log.warning("%s RPC 대체 해제 — 설정 rpc_fallback:false", chain)
        return None
    if chain not in _RPCFB_RESUMED:
        _RPCFB_RESUMED.add(chain)
        if rec.get("nokey") and es_key and cc.get("etherscan_chainid"):
            with _RPCFB_LOCK:
                rec.update(active=False, exit_at=int(now))
                _rpcfb_put(chain, rec)
            log.warning("%s RPC 대체 해제 — 이더스캔 키가 생김(이더스캔 경로로)", chain)
            return None
        if rec.get("why") == "day" and float(rec.get("until") or 0) > now:
            es_daily_restore(float(rec["until"]))
        if rec.get("why") in ("key", "es_fail") or rec.get("src") == "blockscout":
            with _RPCFB_LOCK:
                rec["next_probe"] = int(min(float(rec.get("next_probe") or now), now))
                _rpcfb_put(chain, rec)
    try:
        nw = RpcChainWatcher(cfg, chain, wallets, writer)
    except (Exception, SystemExit) as e:   # noqa: BLE001 [fallback]
        log.error("%s RPC 대체 수집기 재생성 실패(주 경로로): %s", chain, logs.redact_urls(logs.safe_err(e))[:160])
        with _RPCFB_LOCK:
            rec.update(active=False, exit_at=int(now))
            _rpcfb_put(chain, rec)
        return None
    rec["limited"] = getattr(nw, "nodes_limited", None)
    rec["text"] = _rpcfb_text(rec)
    nw.fb_info = _rpcfb_info(rec)
    RPCFB_ON[chain] = nw.fb_info
    log.info("%s %s(대체 이어감 — %s 부터)", chain, rec["text"], time.strftime("%m-%d %H:%M", time.localtime(float(rec.get("since") or now))))
    return nw


def _bs_err_kind(e) -> str:
    s = str(e)
    low = s.lower()
    if getattr(e, "code", None) in (401, 403) or "http error 403" in low or "cloudflare" in low or "just a moment" in low:
        return "bs403"
    if getattr(e, "kind", None) == "stale_head" and "색인 정지" in s:
        return "bs_frozen"
    return "bs_fail"


def rpcfb_bs_error(cfg: dict, wt, e, writer, es_key: str):
    if not isinstance(wt, ChainWatcher):
        return wt
    chain = wt.chain
    k9 = _bs_err_kind(e)
    m = _RPCFB_MEM.setdefault(chain, {})
    m["bs_n"] = int(m.get("bs_n") or 0) + 1
    m["bs_403"] = (int(m.get("bs_403") or 0) + 1) if k9 == "bs403" else 0
    if not (k9 == "bs_frozen" or (k9 == "bs403" and m["bs_403"] >= RPCFB_BS_403_N) or m["bs_n"] >= RPCFB_BS_FAIL_N):
        return wt
    if getattr(wt, "lr_info", None):
        try:
            nw = RpcChainWatcher(cfg, chain, wt.wallets, writer)
        except (Exception, SystemExit) as e9:   # noqa: BLE001 [fallback]
            log.warning("%s RPC 본선 재생성 실패(블록스카웃 최후 경로 유지): %s", chain, logs.safe_err(e9)[:120])
            return wt
        _lr_restore_fb(nw, wt.lr_info)
        m["bs_n"] = m["bs_403"] = 0
        m["rpc_fail_since"], m["rpc_fail_n"] = time.time(), 0
        _rpcfb_swap(chain)
        log.warning("★%s 최후 경로 블록스카웃도 실패(%s) — RPC 우선 본선으로 돌아가 재시도★", chain, RPCFB_WHY.get(k9, k9))
        return nw
    cc = cfg["chains"].get(chain) or {}
    if cc.get("etherscan_chainid") and es_key:
        eb9 = rpcfb_get(chain).get("es_bad")
        why9 = "day" if es_daily_left() > 0 else (str(eb9.get("why")) if isinstance(eb9, dict) and eb9.get("why") else "queue")
        nw = rpcfb_enter(cfg, chain, wt.wallets, writer, "etherscan", why9, err=logs.safe_err(e), bs=k9, bs_seen=True)
    else:
        nw = rpcfb_enter(cfg, chain, wt.wallets, writer, "blockscout", k9, err=logs.safe_err(e), bs=k9, bs_seen=True,
                         nokey=bool(cc.get("etherscan_chainid")))
    if nw is None:
        return wt
    m["bs_n"] = m["bs_403"] = 0
    return nw


def rpcfb_paced(cfg: dict, wt, writer, err=None):
    if not isinstance(wt, EtherscanWatcher):
        return wt
    m = _RPCFB_MEM.setdefault(wt.chain, {})
    now = time.time()
    ps = m.get("paced_since") or now
    m["paced_since"] = ps
    if now - ps < RPCFB_PACE_SEC:
        return wt
    nw = rpcfb_enter(cfg, wt.chain, wt.wallets, writer, "etherscan", "pace", err=logs.safe_err(err) if err else None)
    if nw is None:
        return wt
    m["paced_since"] = None
    return nw


def rpcfb_ok(wt):
    m = _RPCFB_MEM.setdefault(wt.chain, {})
    m["bs_n"] = m["bs_403"] = 0
    if isinstance(wt, RpcChainWatcher):
        m.pop("rpc_fail_since", None)
        m["rpc_fail_n"] = 0
    if isinstance(wt, EtherscanWatcher):
        m["paced_since"] = None
    key9 = "bs_dead" if isinstance(wt, ChainWatcher) else ("es_bad" if isinstance(wt, EtherscanWatcher) else None)
    if key9 and getattr(wt, "_max_head", 0):
        with _RPCFB_LOCK:
            rec = rpcfb_get(wt.chain)
            if rec.get(key9) and not rec.get("active"):
                rec.pop(key9, None)
                _rpcfb_put(wt.chain, rec)


def _es_probe(chain: str, cid: int, key: str):
    p = object.__new__(EtherscanWatcher)
    p.chain, p.cid, p.key, p.conf_depth, p._es_kind = chain, int(cid), key, 12, "head"
    try:
        p.head_block()
        return True, None
    except Exception as e:   # noqa: BLE001 [fallback]
        return False, e


def _bs_probe(cfg: dict, chain: str, wallet: str = None):
    base = str(((cfg.get("chains") or {}).get(chain) or {}).get("blockscout") or "").rstrip("/")
    if not base:
        return False, "블록스카웃 미구성"
    try:
        d = http_json(f"{base}/api/v2/blocks?type=block", retries=1)
    except Exception as e:   # noqa: BLE001 [fallback]
        return False, logs.redact_urls(logs.safe_err(e))[:120]
    items = d.get("items") if isinstance(d, dict) else None
    if not items or not isinstance(items[0], dict) or items[0].get("height") is None:
        return False, "blocks 응답 비어있음"
    ts9 = items[0].get("timestamp")
    if isinstance(ts9, str):
        try:
            import datetime as _dt
            t9 = _dt.datetime.fromisoformat(ts9.replace("Z", "+00:00")).timestamp()
            if time.time() - t9 > EXPLORER_FROZEN_SEC:
                return False, f"색인 정지(최신 블록 {(time.time() - t9) / 3600:.0f}시간 전)"
        except ValueError:
            pass
    if wallet:
        try:
            d2 = http_json(f"{base}/api/v2/addresses/{wallet}/transactions", retries=1)
        except Exception as e:   # noqa: BLE001 [fallback]
            return False, "주소 목록 " + logs.redact_urls(logs.safe_err(e))[:110]
        if not isinstance(d2, dict) or not isinstance(d2.get("items"), list):
            return False, "주소 목록 응답 형식 오류"
    return True, None


EVM_ROUTE_FILE = "evm_route.json"
_EVM_ROUTE_LOCK = threading.RLock()
_EXPLORER_KEYS = ("_bf:", "_bfjob", "_bfes:", "_cov:", "_es_int", "_ext_", "_idx_", "_disc:", "_int_lag", "_synced_tok_at")


def _explorer_era_cursor(cur) -> bool:
    if not isinstance(cur, dict) or not cur:
        return False
    if any(str(k).startswith(_EXPLORER_KEYS) for k in cur):
        return True
    if cur.get("_rpc_v") is None:
        return any(not str(k).startswith("_") and type(v) is int for k, v in cur.items())
    ho = cur.get("_handover")
    return isinstance(ho, dict) and ho.get("from") in ("explorer", "rescan")


def evm_route(cfg: dict, chain: str, decide: bool = True) -> str:
    cc = ((cfg or {}).get("chains") or {}).get(chain) or {}
    if config.chain_discovery(chain, cc) == "rpc":
        return "rpc"
    if str(cc.get("discovery") or "").lower() == "explorer" or (cfg or {}).get("rpc_first") is False or cc.get("rpc_first") is False:
        return "legacy"
    p9 = paths.state(EVM_ROUTE_FILE)
    with _EVM_ROUTE_LOCK:
        d9 = statefile.read_json(p9, {})
        d9 = d9 if isinstance(d9, dict) else {}
        r9 = d9.get(chain)
        if isinstance(r9, dict) and r9.get("route") in ("rpc_first", "legacy"):
            return r9["route"]
        try:
            nd9 = rpc_nodes(cfg, chain)
            rpc_ok = bool(nd9.get("detail")) and bool(nd9.get("logs")) and bool((RPC_NODES.get(chain) or {}).get("logs") or cc.get("rpc_logs"))
        except Exception:   # noqa: BLE001 [fallback]
            rpc_ok = False
        cur9 = statefile.read_json(paths.state(f"cursor_evm_{chain}.json"), {})
        if not rpc_ok:
            route, why = "legacy", "RPC 노드 표 없음"
        elif _explorer_era_cursor(cur9) or rpcfb_get(chain):
            route, why = "legacy", "탐색기 시절 커서·대체 기록 있음(기존 설치본 유지)"
        else:
            route, why = "rpc_first", "새 체인(커서 없음)"
        if decide:
            d9[chain] = {"route": route, "at": int(time.time()), "why": why}
            statefile.atomic_write_json(p9, d9)
            log.info("%s 수집 경로 순서 = %s(%s) — state/%s 에 고정", chain, route, why, EVM_ROUTE_FILE)
        return route


def _primary_kind(cfg: dict, chain: str, es_key: str) -> str:
    cc = cfg["chains"].get(chain) or {}
    if config.chain_discovery(chain, cc) == "rpc":
        return "rpc"
    if cc.get("etherscan_chainid") and es_key and not es_bs_busy(chain) and es_daily_left() <= 0:
        return "etherscan"
    if evm_route(cfg, chain, decide=False) == "rpc_first":
        return "rpc"
    return "blockscout"


RPC_LR_SEC = 1800
RPC_LR_MIN_N = 3


def rpc_first_note_fail(cfg: dict, wt):
    if not isinstance(wt, RpcChainWatcher) or evm_route(cfg, wt.chain, decide=False) != "rpc_first":
        return
    m = _RPCFB_MEM.setdefault(wt.chain, {})
    if not m.get("rpc_fail_since"):
        m["rpc_fail_since"] = time.time()
    m["rpc_fail_n"] = int(m.get("rpc_fail_n") or 0) + 1


def rpc_first_last_resort(cfg: dict, wt, writer):
    if not isinstance(wt, RpcChainWatcher):
        return wt
    cc = (cfg.get("chains") or {}).get(wt.chain) or {}
    if not cc.get("blockscout") or evm_route(cfg, wt.chain, decide=False) != "rpc_first":
        return wt
    m = _RPCFB_MEM.setdefault(wt.chain, {})
    now = time.time()
    since9, n9 = m.get("rpc_fail_since"), int(m.get("rpc_fail_n") or 0)
    if not since9 or now - float(since9) < RPC_LR_SEC or n9 < RPC_LR_MIN_N or now < float(m.get("lr_probe_next") or 0):
        return wt
    m["lr_probe_next"] = now + RPCFB_PROBE_SEC
    ok9, why9 = _bs_probe(cfg, wt.chain, (wt.wallets or [None])[0])
    if not ok9:
        log.info("%s RPC 연속 실패 %d회 — 블록스카웃도 안 됨(%s) · RPC 계속 재시도", wt.chain, n9, why9)
        return wt
    try:
        nw = ChainWatcher(cfg, wt.chain, wt.wallets, writer)
    except (Exception, SystemExit) as e9:   # noqa: BLE001 [fallback]
        log.warning("%s 블록스카웃 최후 경로 생성 실패(RPC 유지): %s", wt.chain, logs.safe_err(e9)[:120])
        return wt
    nw.lr_info = {"since": int(now), "fails": n9, "fb_info": dict(getattr(wt, "fb_info", None) or {})}
    RPCFB_ON.pop(wt.chain, None)
    m.pop("rpc_fail_since", None)
    m["rpc_fail_n"] = 0
    _rpcfb_swap(wt.chain)
    log.warning("★%s RPC 우선 본선이 %d분 넘게 실패(%d회) — 살아 있는 블록스카웃을 최후 경로로(RPC 회복되면 복귀)★", wt.chain, int((now - float(since9)) // 60), n9)
    _dm("RPC_LAST_RESORT", f"[{wt.chain}] 공개 RPC 가 {int((now - float(since9)) // 60)}분 넘게 실패 — 블록스카웃으로 임시 수집(RPC 회복되면 자동 복귀)")
    return nw


def _lr_restore_fb(nw, lr9) -> None:
    fb9 = (lr9 or {}).get("fb_info")
    if fb9:
        nw.fb_info = dict(fb9)
        RPCFB_ON[nw.chain] = nw.fb_info


def _rpc_probe(cfg: dict, chain: str, wallet: str = None):
    nd = rpc_nodes(cfg, chain)
    try:
        h9 = int(bf_engine.rpc_call(nd["detail"][0], "eth_blockNumber", [], timeout=15, retries=0), 16)
        if wallet and nd["logs"]:
            b9 = hex(max(0, h9 - 2))
            bf_engine.rpc_call(nd["logs"][0], "eth_getLogs", [{"fromBlock": b9, "toBlock": b9,
                                                               "topics": [RpcSynthMixin.TRANSFER_TOPIC, "0x" + wallet[2:].rjust(64, "0")]}],
                               timeout=20, retries=0)
    except Exception as e:   # noqa: BLE001 [fallback]
        return False, logs.redact_urls(logs.safe_err(e))[:120]
    return True, None


def rpc_first_try_back(cfg: dict, wt, writer):
    lr9 = getattr(wt, "lr_info", None)
    if not lr9:
        return wt
    m = _RPCFB_MEM.setdefault(wt.chain, {})
    now = time.time()
    since9 = lr9.get("since")
    if now - float(since9 if isinstance(since9, (int, float)) else now) < RPCFB_MIN_STAY or now < float(m.get("lr_back_next") or 0):
        return wt
    m["lr_back_next"] = now + RPCFB_PROBE_SEC
    ok9, why9 = _rpc_probe(cfg, wt.chain, (wt.wallets or [None])[0])
    if not ok9:
        log.info("%s 최후 경로(블록스카웃) 유지 — RPC 시험 실패: %s", wt.chain, why9)
        return wt
    try:
        nw = RpcChainWatcher(cfg, wt.chain, wt.wallets, writer)
    except (Exception, SystemExit) as e9:   # noqa: BLE001 [fallback]
        log.warning("%s RPC 본선 재생성 실패(블록스카웃 유지): %s", wt.chain, logs.safe_err(e9)[:120])
        return wt
    _lr_restore_fb(nw, lr9)
    _rpcfb_swap(wt.chain)
    log.warning("★%s RPC 회복 — 최후 경로(블록스카웃) 끝, RPC 우선 본선 복귀(같은 커서 파일 인계)★", wt.chain)
    return nw


def rpcfb_try_return(cfg: dict, wt, make, es_key: str):
    if not getattr(wt, "fb_info", None):
        return wt
    chain = wt.chain
    now = time.time()
    rec = rpcfb_get(chain)
    cc = cfg["chains"].get(chain) or {}
    if rec.get("active") and rpcfb_allowed(cfg, chain):
        st9 = rec.get("stay")
        if now < float(rec.get("since") or 0) + float(st9 if isinstance(st9, (int, float)) and not isinstance(st9, bool) else RPCFB_MIN_STAY):
            return wt
        if rec.get("src") == "etherscan" and cc.get("etherscan_chainid") and es_key:
            target = "etherscan"
            if es_daily_left() > 0:
                return wt
            if rec.get("why") == "pace" and bf_engine.es_pace_room("head") < RPCFB_PACE_ROOM * bf_engine.ES_DAILY_BUDGET:
                return wt
            if _primary_kind(cfg, chain, es_key) != "etherscan":
                return wt
            if rec.get("es_bad"):
                if now < float(rec.get("next_probe") or 0):
                    return wt
                ok9, e9 = _es_probe(chain, int(cc["etherscan_chainid"]), es_key)
                if not ok9:
                    with _RPCFB_LOCK:
                        rec["next_probe"] = int(now + RPCFB_ES_PROBE_SEC)
                        rec["probe_err"] = logs.redact_urls(logs.redact_secret_text(logs.redact_urls(str(e9)), generic=False))[:120]
                        _rpcfb_put(chain, rec)
                    log.info("%s 이더스캔 복귀 시험 실패 — RPC 대체 유지(%d분 뒤 다시): %s", chain, RPCFB_ES_PROBE_SEC // 60, rec["probe_err"])
                    return wt
        else:
            target = "blockscout"
            if not cc.get("blockscout") or now < float(rec.get("next_probe") or 0):
                return wt
            if _primary_kind(cfg, chain, es_key) != "blockscout":
                return wt
            ok9, why9 = _bs_probe(cfg, chain, (wt.wallets or [None])[0])
            if not ok9:
                with _RPCFB_LOCK:
                    rec["next_probe"] = int(now + RPCFB_PROBE_SEC)
                    rec["probe_err"] = why9
                    _rpcfb_put(chain, rec)
                log.info("%s 블록스카웃 복귀 시험 실패 — RPC 대체 유지(%d분 뒤 다시): %s", chain, RPCFB_PROBE_SEC // 60, why9)
                return wt
    else:
        target = "manual"
    with _RPCFB_LOCK:
        rec0 = dict(rec)
        rec.update(active=False, exit_at=int(now))
        if target == "blockscout":
            rec.pop("bs_dead", None)
        elif target == "etherscan":
            rec.pop("es_bad", None)
        _rpcfb_put(chain, rec)
    _RPCFB_RETURNING.add(chain)
    try:
        nw = make(cfg, chain, wt.wallets)
    except (Exception, SystemExit) as e:   # noqa: BLE001 [fallback]
        nw = None
        log.warning("%s 주 경로 워처 생성 실패(RPC 대체 유지 · 다음 시험): %s", chain, logs.safe_err(e)[:120])
    finally:
        _RPCFB_RETURNING.discard(chain)
    if nw is None:
        with _RPCFB_LOCK:
            if rec0.get("active"):
                rec0["next_probe"] = int(now + RPCFB_PROBE_SEC)
                _rpcfb_put(chain, rec0)
        return wt
    if isinstance(nw, RpcChainWatcher):
        RPCFB_ON.pop(chain, None)
        return nw
    if not wt._bk_jobs():
        wt.progress.finish(f"{chain}:rpc", note="탐색기 경로 복귀")
    RPCFB_ON.pop(chain, None)
    _RPCFB_MEM.setdefault(chain, {}).update(bs_n=0, bs_403=0, paced_since=None)
    _rpcfb_swap(chain)
    log.warning("★%s RPC 대체 끝 — %s 경로 복귀(대체 %.0f분 · 같은 커서 파일 되돌림)★", chain,
                "이더스캔" if isinstance(nw, EtherscanWatcher) else "블록스카웃", (now - float(rec0.get("since") or now)) / 60)
    return nw


def build_watcher(cfg: dict, chain: str, addrs: list, shared_writer, es_key: str):
    if chain not in cfg["chains"]:
        raise SystemExit(f"config.chains 에 없는 체인: {chain}")
    if config.chain_discovery(chain, cfg["chains"][chain]) == "rpc":
        log.info("%s: RPC 전용 발견 경로 사용 (getLogs + nonce·잔고 정합)", chain)
        RPCFB_ON.pop(chain, None)
        if rpcfb_get(chain).get("active"):
            with _RPCFB_LOCK:
                r9 = rpcfb_get(chain)
                r9.update(active=False, exit_at=int(time.time()))
                _rpcfb_put(chain, r9)
        return RpcChainWatcher(cfg, chain, addrs, shared_writer)
    returning9 = chain in _RPCFB_RETURNING
    if not returning9:
        nw9 = rpcfb_resume(cfg, chain, addrs, shared_writer, es_key)
        if nw9 is not None:
            return nw9
    import chaincatalog
    if chaincatalog.es_only(cfg["chains"][chain]):
        log.info("%s: 이더스캔 전용 경로(chainid %s · 블록스카웃·RPC 대체 없음)%s", chain, cfg["chains"][chain]["etherscan_chainid"],
                 "" if es_key else " — 이더스캔 키 없음: 이 체인은 멈춤")
        return EtherscanWatcher(cfg, chain, addrs, shared_writer, int(cfg["chains"][chain]["etherscan_chainid"]), es_key or "")
    if evm_route(cfg, chain) == "rpc_first":
        es9 = cfg["chains"][chain].get("etherscan_chainid")
        if es9 and es_key:
            why9 = "day" if es_daily_left() > 0 else ("queue" if es_bs_busy(chain) else None)
            if why9 is None:
                log.info("%s: etherscan 고속 경로 사용 (chainid %s · RPC 우선 순서)", chain, es9)
                return EtherscanWatcher(cfg, chain, addrs, shared_writer, int(es9), es_key)
            nw9 = rpcfb_enter(cfg, chain, addrs, shared_writer, "etherscan", why9, err=f"이더스캔 {RPCFB_WHY.get(why9, why9)}", bs="rpc_first")
            if nw9 is not None:
                return nw9
        log.info("%s: RPC 우선 경로(새 설치본 순서 — 블록스카웃은 첫 경로로 안 씀 · getLogs + nonce·잔고 정합 · 차선 모드)", chain)
        return RpcChainWatcher(cfg, chain, addrs, shared_writer)
    es_cid = cfg["chains"][chain].get("etherscan_chainid")
    why9 = None
    if es_cid and es_key and es_bs_busy(chain):
        log.warning("%s: 미완 blockscout 큐·백필·internal 재수집 잔존 — 회수 위해 blockscout 경로 유지(끝나면 etherscan 복귀)",
                    chain)
        es_cid, why9 = None, "queue"
    if es_cid and es_key and es_daily_left() > 0:
        log.info("%s: 이더스캔 하루 한도 쉼 창(%.0f분 남음) — blockscout 경로", chain, es_daily_left() / 60)
        es_cid, why9 = None, "day"
    if es_cid and es_key:
        log.info("%s: etherscan 고속 경로 사용 (chainid %s)", chain, es_cid)
        return EtherscanWatcher(cfg, chain, addrs, shared_writer, int(es_cid), es_key)
    dead9 = None if returning9 else rpcfb_bs_dead(cfg, chain)
    if dead9:
        es9 = bool(cfg["chains"][chain].get("etherscan_chainid"))
        nw9 = rpcfb_enter(cfg, chain, addrs, shared_writer, "etherscan" if (es9 and es_key) else "blockscout",
                          why9 if (es9 and es_key and why9) else dead9, err=f"블록스카웃 {RPCFB_WHY.get(dead9, dead9)}", bs=dead9,
                          nokey=bool(es9 and not es_key))
        if nw9 is not None:
            return nw9
    return ChainWatcher(cfg, chain, addrs, shared_writer)


class ChainLoop:

    def __init__(self, cfg: dict, wt, make, es_key: str, writer):
        self.cfg, self.wt, self.make, self.es_key, self.writer = cfg, wt, make, es_key, writer
        self.es_fail = 0
        self.es_daily_fb = bool(es_key and es_daily_left() > 0 and not isinstance(wt, EtherscanWatcher) and not getattr(wt, "fb_info", None)
                                and (cfg["chains"].get(wt.chain) or {}).get("etherscan_chainid"))
        CUR_WATCHER[wt.chain] = wt

    @staticmethod
    def _ho_deterministic(wt, e) -> bool:
        m = re.search(r"블록 (\d+)·(\d+)", str(e))
        if not m or not getattr(wt, "wallets", None):
            return False
        det = False
        memo9 = getattr(wt, "_st_memo", None)
        for b9 in dict.fromkeys((int(m.group(1)), int(m.group(2)))):
            if isinstance(memo9, dict):
                memo9.pop((wt.wallets[0], b9), None)
            try:
                wt._states([(wt.wallets[0], b9)], strict=True)
            except StateUnavailable:
                det = True
            except Exception:   # noqa: BLE001 [fallback]
                return False
        return det

    @staticmethod
    def _disc_fail(wt, e) -> bool:
        if _bs_err_kind(e) == "bs403":
            return True
        tb9 = getattr(wt, "_tier", None)
        seen9 = [w for w in wt.wallets if isinstance(wt.cursor.get(w), int) and not (tb9 is not None and tb9.is_resting(w))]
        bad9 = {w for w, n in (getattr(wt, "fail_streak", None) or {}).items() if n}
        return bool(seen9) and set(seen9) <= bad9

    def step(self) -> bool:
        cfg, make = self.cfg, self.make
        wt = self.wt
        nw9 = take_rebuild(wt, make)
        if nw9 is not wt and isinstance(wt, EtherscanWatcher) and not isinstance(nw9, EtherscanWatcher) \
                and es_daily_left() > 0 and not getattr(nw9, "fb_info", None):
            self.es_daily_fb = True
        wt = nw9
        if getattr(wt, "fb_info", None):
            nw9 = rpcfb_try_return(cfg, wt, make, self.es_key)
            if nw9 is not wt:
                wt, self.es_fail = nw9, 0
                self.es_daily_fb = bool(self.es_key and isinstance(nw9, ChainWatcher) and es_daily_left() > 0
                                        and (cfg["chains"].get(nw9.chain) or {}).get("etherscan_chainid"))
        elif self.es_daily_fb:
            wt, self.es_daily_fb = es_daily_return(cfg, wt, make)
        elif getattr(wt, "lr_info", None):
            wt = rpc_first_try_back(cfg, wt, self.writer)
        self.wt = wt
        CUR_WATCHER[wt.chain] = wt
        if isinstance(wt, ChainWatcher):
            wt._rpcfb_disc_error = None
        import inflow_probe
        inflow_probe.tick(cfg, wt)
        try:
            wt.cycle()
            self.es_fail = 0
            e9 = getattr(wt, "_rpcfb_disc_error", None) if isinstance(wt, ChainWatcher) else None
            if e9 is not None:
                if self._disc_fail(wt, e9):
                    nw9 = rpcfb_bs_error(cfg, wt, e9, self.writer, self.es_key)
                    if nw9 is not wt:
                        self.wt, self.es_fail, self.es_daily_fb = nw9, 0, False
                        wt = nw9
            elif isinstance(wt, RpcChainWatcher) and getattr(wt, "_rpc_cycle_failed", False):
                rpc_first_note_fail(cfg, wt)
                nw9 = rpc_first_last_resort(cfg, wt, self.writer)
                if nw9 is not wt:
                    self.wt, self.es_fail, self.es_daily_fb = nw9, 0, False
                    wt = nw9
            else:
                rpcfb_ok(wt)
            tsfix.repair(wt.chain, lambda b, wt=wt: tsfix.block_ts(wt, b), self.writer)
        except EtherscanPaced as e:
            bf_engine.health("evm").facts(wt.chain, paced_at=int(time.time()))
            bf_engine.health("evm").flush()
            if time.time() - getattr(wt, "_paced_log", 0) >= 600:
                wt._paced_log = time.time()
                log.info("%s 이더스캔 하루 예산 페이싱 — 이번 주기 쉼(기록은 그대로, 다음 주기에 이어 받음): %s", wt.chain, e)
            nw9 = rpcfb_paced(cfg, wt, self.writer, e)
            if nw9 is not wt:
                self.wt, self.es_fail = nw9, 0
                wt = nw9
        except ChainDisabled as e:
            if getattr(wt, "fb_info", None):
                _RPCFB_MEM.setdefault(wt.chain, {})["broken"] = True
                with _RPCFB_LOCK:
                    rec9 = rpcfb_get(wt.chain)
                    rec9.update(active=False, exit_at=int(time.time()), broken=logs.redact_urls(str(e))[:120])
                    _rpcfb_put(wt.chain, rec9)
                RPCFB_ON.pop(wt.chain, None)
                log.error("★%s RPC 대체 수집기 설정 오류 — 대체 끄고 주 경로로: %s★", wt.chain, logs.redact_urls(str(e)))
                _RPCFB_RETURNING.add(wt.chain)
                try:
                    self.wt = make(cfg, wt.chain, wt.wallets)
                except (Exception, SystemExit) as e9:   # noqa: BLE001 [optional]
                    log.error("%s 주 경로 워처 생성 실패(다음 주기 재시도): %s", wt.chain, e9)
                finally:
                    _RPCFB_RETURNING.discard(wt.chain)
                return True
            bf_engine.health("evm").fail(wt.chain, e, "rpc")
            bf_engine.health("evm").flush()
            log.error("★%s 체인 추적 중지(설정 오류): %s — 다른 체인은 계속, 고친 뒤 pm2 restart tj-evm★", wt.chain, logs.redact_urls(str(e)))
            DISABLED_CHAINS.add(wt.chain)
            return False
        except Exception as e:  # noqa: BLE001 [fallback]
            if getattr(e, "_tj_health_counted", False):
                n9 = int((bf_engine.health("evm")._s(wt.chain).get("consecutive_failures")) or 1)
            else:
                n9 = bf_engine.health("evm").fail(wt.chain, e, "etherscan" if isinstance(wt, EtherscanWatcher)
                                                  else "rpc" if isinstance(wt, RpcChainWatcher) else "blockscout")
            bf_engine.health("evm").flush()
            lv = bf_engine.LogDebounce.level(n9)
            if lv:
                getattr(log, lv)("%s cycle 실패 %d회 연속(다음 주기 재시도): %s", wt.chain, n9, logs.redact_urls(str(e)))
            if (getattr(wt, "fb_info", None) or (isinstance(wt, RpcChainWatcher) and evm_route(cfg, wt.chain, decide=False) == "rpc_first")) \
                    and isinstance(e, StateUnavailable) and "인계 기준점" in str(e):
                m9 = _RPCFB_MEM.setdefault(wt.chain, {})
                m9["ho_fail"] = (int(m9.get("ho_fail") or 0) + 1) if self._ho_deterministic(wt, e) else 0
                if m9["ho_fail"] >= 2 and getattr(wt, "handover", None) != "rescan":
                    wt.handover = "rescan"
                    log.warning("★%s RPC 대체 노드 비아카이브(인계 기준점 없음 %d회) — 창 처음부터 다시 훑기(rescan)로 · 로그 없는 이동은 최근 구간만 정합★",
                                wt.chain, m9["ho_fail"])
            wt0 = wt
            wt, self.es_fail, d9 = es_on_cycle_error(cfg, wt, e, self.es_fail, self.writer)
            self.es_daily_fb = self.es_daily_fb or d9
            if wt is wt0:
                wt = rpcfb_bs_error(cfg, wt, e, self.writer, self.es_key)
            if wt is wt0 and isinstance(wt, RpcChainWatcher):
                rpc_first_note_fail(cfg, wt)
                wt = rpc_first_last_resort(cfg, wt, self.writer)
            if wt is not wt0 and getattr(wt, "fb_info", None):
                self.es_daily_fb = False
            self.wt = wt
            try:
                cur9 = statefile.read_json(wt.cursor_path, {})
                a9 = cur9.pop("_synced_at", None) is not None
                b9 = cur9.pop("_synced_tok_at", None) is not None
                if a9 or b9:
                    statefile.atomic_write_json(wt.cursor_path, cur9)
                wt.cursor = cur9
            except Exception:  # noqa: BLE001 [optional]
                pass
        wt = self.wt
        CUR_WATCHER[wt.chain] = wt
        try:
            fb9 = getattr(wt, "fb_info", None)
            bf_engine.health("evm").facts(
                wt.chain, es_daily_until=int(_ES_DAILY["until"]) if self.es_daily_fb and es_daily_left() > 0 else None,
                rpc_fb=dict(fb9) if fb9 else None,
                rpc_limited=getattr(wt, "nodes_limited", None) if (isinstance(wt, RpcChainWatcher) and not fb9) else None)
        except Exception:   # noqa: BLE001 [optional]
            pass
        return True


from evm_synth import (  # noqa: F401
    RpcSynthMixin,
)


from evm_bscout import (  # noqa: F401
    ChainWatcher,
)


from evm_es import (  # noqa: F401
    EtherscanWatcher,
)


from evm_logdisc import (  # noqa: F401
    RpcLogDiscovery,
)


DISABLED_CHAINS = set()


REBUILD = {}
GATE_RELOAD_SEC = 600
REBUILD_FAILS = {}


def take_rebuild(wt, make):
    nw9 = REBUILD.pop(wt.chain, None)
    if nw9 is None:
        return wt
    try:
        new = make(nw9[0], wt.chain, nw9[1])
    except (Exception, SystemExit) as e:   # noqa: BLE001 [fallback]
        REBUILD.setdefault(wt.chain, nw9)
        n9 = REBUILD_FAILS[wt.chain] = REBUILD_FAILS.get(wt.chain, 0) + 1
        lv = "warning" if n9 == 1 else bf_engine.LogDebounce.level(n9)
        if lv:
            getattr(log, lv)("%s 워처 재구성 실패 %d회(종전 워처 유지·다음 사이클 재시도): %s", wt.chain, n9, e)
        return wt
    REBUILD_FAILS.pop(wt.chain, None)
    log.warning("★%s 활동 게이트 지갑 합류 — 워처 재구성(지갑 %d)★", wt.chain, len(nw9[1]))
    return new


from evm_rpcw import (  # noqa: F401
    RPC_NODES,
    rpc_nodes,
    RpcChainWatcher,
)


def main():
    paths.ensure_dirs()
    cfg = config.load_config()
    bf_engine.configure(cfg)
    bf_engine.es_budget_install_sigterm()
    addr_tier.ACTIVE_PROC = True
    poll = int(cfg.get("evm_poll_sec", 45))
    watchers = []
    by_chain = {}
    for w in cfg["wallets"]:
        if w.get("type", "evm") == "evm":
            by_chain.setdefault(w["chain"], []).append(w["address"])
    shared_writer = SegmentWriter(os.path.join(paths.INBOX_DIR, "evm"))
    es_key = envfile.read_env_file().get("TJ_ETHERSCAN_KEY", "")
    chain_poll_cfg = {}

    def make_watcher(cfg, chain, addrs):
        if chain in cfg["chains"]:
            chain_poll_cfg[chain] = (cfg["chains"][chain] or {}).get("poll_sec")
        return build_watcher(cfg, chain, addrs, shared_writer, es_key)

    for chain, addrs in by_chain.items():
        watchers.append(make_watcher(cfg, chain, addrs))
    if not watchers:
        raise SystemExit("추적할 EVM 지갑이 없음 — config.wallets 확인")
    rpclogs = []
    for wt in watchers:
        flag = cfg["chains"][wt.chain].get("rpc_log_discovery")
        if not flag:
            continue
        if not isinstance(wt, ChainWatcher):
            (log.info if isinstance(wt, RpcChainWatcher) else log.warning)(
                "%s: rpc_log_discovery 는 blockscout(ChainWatcher) 체인 전용 — 무시(RPC 전용 경로가 getLogs 를 직접)", wt.chain)
            continue
        rd = RpcLogDiscovery(cfg, wt.chain, wt.wallets, shared_writer, wt)
        rpclogs.append(rd)
        log.info("★%s: RPC getLogs 이중화 트랙 가동 (mode=%s, 로그풀 %d)★",
                 wt.chain, rd.mode, len(rd.logs_rpcs))
    log.info("가동: %d체인 %d지갑, %d초 주기 (체인별 병렬)",
             len(watchers), sum(len(x.wallets) for x in watchers), poll)

    def chain_poll(chain: str) -> float:
        try:
            v = float(chain_poll_cfg.get(chain) or (cfg["chains"].get(chain) or {}).get("poll_sec") or poll)
        except (TypeError, ValueError):
            v = float(poll)
        return min(max(v, 5.0), 300.0)

    wlock = threading.Lock()
    orig_append = shared_writer.append

    def locked_append(rec):
        with wlock:
            orig_append(rec)
    shared_writer.append = locked_append

    def chain_loop(wt):
        lp = ChainLoop(cfg, wt, make_watcher, es_key, shared_writer)
        while True:
            t0 = time.time()
            if not lp.step():
                return
            time.sleep(max(5.0, chain_poll(lp.wt.chain) - (time.time() - t0)))

    def rpclog_loop(rd):
        while True:
            t0 = time.time()
            cw9 = CUR_WATCHER.get(rd.chain)
            if RPCFB_ON.get(rd.chain) or (cw9 is not None and not isinstance(cw9, ChainWatcher)):
                time.sleep(max(5.0, poll))
                continue
            if isinstance(cw9, ChainWatcher) and cw9 is not rd.bs:
                rd.bs = cw9
            try:
                rd.cycle()
            except Exception as e:  # noqa: BLE001 [fallback]
                n9 = bf_engine.health("evm").fail(f"{rd.chain}:rpclog", e, "rpclog")
                bf_engine.health("evm").flush()
                lv = bf_engine.LogDebounce.level(n9)
                if lv:
                    getattr(log, lv)("%s rpclog cycle 실패 %d회 연속(다음 주기 재시도): %s", rd.chain, n9, logs.redact_urls(str(e)))
                try:
                    st9 = statefile.read_json(rd.state_path, {})
                    if st9.pop("rpc_synced_at", None) is not None:
                        statefile.atomic_write_json(rd.state_path, st9)
                    rd.st = st9
                except Exception:  # noqa: BLE001 [optional]
                    pass
            time.sleep(max(5.0, poll - (time.time() - t0)))

    threads = [threading.Thread(target=chain_loop, args=(wt,), daemon=True, name=wt.chain)
               for wt in watchers]
    threads += [threading.Thread(target=rpclog_loop, args=(rd,), daemon=True,
                                 name=f"{rd.chain}-rpclog") for rd in rpclogs]
    for t in threads:
        t.start()
    cur_pairs = {c: sorted(a.lower() for a in ws) for c, ws in by_chain.items()}
    last_reload = time.time()
    while True:
        time.sleep(60)
        dead = [t.name for t in threads if not t.is_alive() and t.name not in DISABLED_CHAINS]
        if dead:
            raise SystemExit(f"체인 스레드 사망: {dead} — pm2 재시작으로 복구")
        if time.time() - last_reload < GATE_RELOAD_SEC:
            continue
        last_reload = time.time()
        try:
            cfg2 = config.load_config()
        except (Exception, SystemExit) as e:   # noqa: BLE001 [boundary]
            log.warning("활동 게이트 반영용 설정 재적재 실패(다음 주기): %s", e)
            continue
        try:
            for b9 in list(addr_tier.BOOKS.values()):
                b9.reload_cfg(cfg2)
            addr_tier.plan_stretch(list(addr_tier.BOOKS.values()), cfg2)
        except Exception as e:   # noqa: BLE001 [boundary]
            log.warning("계단식 주기 설정·예산 반영 실패(다음 주기): %s", e)
        by2 = {}
        for w in cfg2["wallets"]:
            if w.get("type", "evm") == "evm":
                by2.setdefault(w["chain"], []).append(w["address"])
        for c, ws in by2.items():
            ws9 = sorted({a.lower() for a in ws})
            if c in cur_pairs:
                if set(ws9) - set(cur_pairs[c]):
                    REBUILD[c] = (cfg2, sorted(set(ws9) | set(cur_pairs[c])))
                    cur_pairs[c] = sorted(set(ws9) | set(cur_pairs[c]))
                continue
            try:
                wt = make_watcher(cfg2, c, ws9)
            except (Exception, SystemExit) as e:   # noqa: BLE001 [isolate]
                log.error("★%s 새 체인 워처 생성 실패(다음 주기 재시도): %s★", c, e)
                continue
            cur_pairs[c] = ws9
            t = threading.Thread(target=chain_loop, args=(wt,), daemon=True, name=c)
            threads.append(t)
            t.start()
            log.warning("★활동 게이트: 새 체인 %s 추적 시작 (지갑 %d)★", c, len(ws9))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("정지 신호(SIGINT) — 종료")
