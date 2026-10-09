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
import common
if __name__ == "__main__":
    common.cpu_reserve_apply()
import lpdec
import bf_engine
import tsfix
import addr_tier
from inbox import SegmentWriter

_HTTP5XX_RE = re.compile(r"HTTP(?: Error)? ?5\d\d\b")


def _is_http_5xx(e) -> bool:
    cur, hops = e, 0
    while cur is not None and hops < 4:
        code = getattr(cur, "code", None)
        if isinstance(cur, urllib.error.HTTPError) and isinstance(code, int) and 500 <= code < 600:
            return True
        if _HTTP5XX_RE.search(str(cur) or ""):
            return True
        cur = cur.__cause__ or cur.__context__
        hops += 1
    return False

log = common.setup_logging("tj-evm")


class _ScanLog:
    WIN = 600

    def __init__(self, base):
        self.base = base
        self.seen = {}

    def info(self, msg, *args, **kw):
        if isinstance(msg, str) and msg.endswith("— 재배치") and len(args) >= 5:
            err = str(args[4])
            kind = "429" if ("429" in err or "Too Many" in err) else err[:40]
            key = (str(args[0]), str(args[1]), kind)
            now = time.time()
            ent = self.seen.get(key)
            if ent and now - ent[0] < self.WIN:
                ent[1] += 1
                return
            n = ent[1] if ent else 0
            self.seen[key] = [now, 0]
            if n:
                msg = msg + " (지난 %d분 같은 줄 %d회 더)"
                args = tuple(args) + (max(1, int((now - ent[0]) / 60)), n)
        return self.base.info(msg, *args, **kw)

    def __getattr__(self, name):
        return getattr(self.base, name)


_SCAN_LOG = _ScanLog(log)

UA = "tj-bot/0.1 (personal trade journal)"
HTTP_TIMEOUT = 40
HTTP_RETRIES = 2
DISCOVERY_PAGES_MAX = 40
BACKFILL_PAGES_MAX = 400


def _dm(kind: str, text: str):
    try:
        fd = os.open(os.path.join(common.STATE_DIR, "pending_dm.jsonl"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": int(time.time()), "kind": kind, "text": text, "payload": None},
                               ensure_ascii=False) + "\n")
    except Exception as e:
        log.warning("DM 큐 기록 실패: %s", e)


ES_FALLBACK_STREAK = 3


def es_fallback_watcher(cfg: dict, wt, writer, daily: bool = False, why: str = None):
    why9 = "day" if daily else (why or "es_fail")
    dead9 = rpcfb_bs_dead(cfg, wt.chain)
    if dead9:
        nw9 = rpcfb_enter(cfg, wt.chain, wt.wallets, writer, "etherscan", why9, err=f"이더스캔 {RPCFB_WHY.get(why9, why9)}", bs=dead9)
        if nw9 is not None:
            return nw9
    elif not daily:
        rpcfb_note_es_bad(wt.chain, why9)
    if not cfg["chains"].get(wt.chain, {}).get("blockscout"):
        if daily:
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


ES_DAILY_MARGIN = 300
ES_DAILY_FAR = 20 * 3600
ES_DAILY_PROBE = 3600
ES_DAILY_DM_GAP = 12 * 3600
_ES_DAILY = {"until": 0.0, "dm_at": 0.0}
_ES_DAILY_LOCK = threading.Lock()


def es_is_daily_limit(text) -> bool:
    low = str(text or "").lower()
    return "day/limit" in low or ("daily" in low and "limit" in low)


def es_daily_left(now: float = None) -> float:
    now = time.time() if now is None else now
    with _ES_DAILY_LOCK:
        return max(0.0, _ES_DAILY["until"] - now)


def es_daily_trip(text: str, now: float = None) -> float:
    now = time.time() if now is None else now
    nxt = (int(now) // 86400 + 1) * 86400 + ES_DAILY_MARGIN
    until = float(nxt) if nxt - now <= ES_DAILY_FAR else now + ES_DAILY_PROBE
    with _ES_DAILY_LOCK:
        if _ES_DAILY["until"] > now:
            return _ES_DAILY["until"]
        _ES_DAILY["until"] = until
        send_dm = now - _ES_DAILY.get("dm_at", 0.0) > ES_DAILY_DM_GAP
        if send_dm:
            _ES_DAILY["dm_at"] = now
    kst = time.strftime("%m-%d %H:%M", time.localtime(until))
    log.error("★이더스캔 하루 한도 소진 — %s 까지 이더스캔 0콜(해당 체인 blockscout 임시 폴백 · 블록스카웃이 막힌 체인은 RPC 전용), 그 뒤 자동 재시도★ (%s)",
              kst, str(text)[:100])
    if send_dm:
        _dm("ES_DAILY_LIMIT", f"이더스캔 무료 키 하루 한도 소진 — {kst} 까지 blockscout(막힌 체인은 공개 RPC)로 수집, 그 뒤 자동 복귀(재시작 불필요)")
    return until


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
    if _es_bs_unfinished(common.read_json(os.path.join(common.STATE_DIR, f"cursor_evm_{chain}.json"), {})):
        return True
    return any(common.read_json(os.path.join(common.STATE_DIR, n9), {})
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
    except (Exception, SystemExit) as e9:
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
             "bs_frozen": "블록스카웃 색인 정지", "bs_none": "블록스카웃 미구성"}
_RPCFB_LOCK = threading.RLock()
_RPCFB_MEM = {}
_RPCFB_RESUMED = set()
_RPCFB_RETURNING = set()
RPCFB_ON = {}
CUR_WATCHER = {}


def _rpcfb_path() -> str:
    return os.path.join(common.STATE_DIR, RPCFB_FILE)


def _rpcfb_all() -> dict:
    d = common.read_json(_rpcfb_path(), {})
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
        common.atomic_write_json(_rpcfb_path(), d)


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
    except Exception:
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
    except (Exception, SystemExit) as e:
        log.error("%s RPC 대체 수집기 생성 실패(종전 경로 유지): %s", chain, common.redact_urls(common.safe_err(e))[:160])
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
                   err=common.redact_urls(common.redact_secret_text(str(err or ""), generic=False))[:160] or None,
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
    except (Exception, SystemExit) as e:
        log.error("%s RPC 대체 수집기 재생성 실패(주 경로로): %s", chain, common.redact_urls(common.safe_err(e))[:160])
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
    cc = cfg["chains"].get(chain) or {}
    if cc.get("etherscan_chainid") and es_key:
        eb9 = rpcfb_get(chain).get("es_bad")
        why9 = "day" if es_daily_left() > 0 else (str(eb9.get("why")) if isinstance(eb9, dict) and eb9.get("why") else "queue")
        nw = rpcfb_enter(cfg, chain, wt.wallets, writer, "etherscan", why9, err=common.safe_err(e), bs=k9, bs_seen=True)
    else:
        nw = rpcfb_enter(cfg, chain, wt.wallets, writer, "blockscout", k9, err=common.safe_err(e), bs=k9, bs_seen=True,
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
    nw = rpcfb_enter(cfg, wt.chain, wt.wallets, writer, "etherscan", "pace", err=common.safe_err(err) if err else None)
    if nw is None:
        return wt
    m["paced_since"] = None
    return nw


def rpcfb_ok(wt):
    m = _RPCFB_MEM.setdefault(wt.chain, {})
    m["bs_n"] = m["bs_403"] = 0
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
    except Exception as e:
        return False, e


def _bs_probe(cfg: dict, chain: str, wallet: str = None):
    base = str(((cfg.get("chains") or {}).get(chain) or {}).get("blockscout") or "").rstrip("/")
    if not base:
        return False, "블록스카웃 미구성"
    try:
        d = http_json(f"{base}/api/v2/blocks?type=block", retries=1)
    except Exception as e:
        return False, common.redact_urls(common.safe_err(e))[:120]
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
        except Exception as e:
            return False, "주소 목록 " + common.redact_urls(common.safe_err(e))[:110]
        if not isinstance(d2, dict) or not isinstance(d2.get("items"), list):
            return False, "주소 목록 응답 형식 오류"
    return True, None


def _primary_kind(cfg: dict, chain: str, es_key: str) -> str:
    cc = cfg["chains"].get(chain) or {}
    if common.chain_discovery(chain, cc) == "rpc":
        return "rpc"
    if cc.get("etherscan_chainid") and es_key and not es_bs_busy(chain) and es_daily_left() <= 0:
        return "etherscan"
    return "blockscout"


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
                        rec["probe_err"] = common.redact_urls(common.redact_secret_text(str(e9), generic=False))[:120]
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
    except (Exception, SystemExit) as e:
        nw = None
        log.warning("%s 주 경로 워처 생성 실패(RPC 대체 유지 · 다음 시험): %s", chain, common.safe_err(e)[:120])
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
    if common.chain_discovery(chain, cfg["chains"][chain]) == "rpc":
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
            except Exception:
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
        self.wt = wt
        CUR_WATCHER[wt.chain] = wt
        if isinstance(wt, ChainWatcher):
            wt._rpcfb_disc_error = None
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
                    rec9.update(active=False, exit_at=int(time.time()), broken=common.redact_urls(str(e))[:120])
                    _rpcfb_put(wt.chain, rec9)
                RPCFB_ON.pop(wt.chain, None)
                log.error("★%s RPC 대체 수집기 설정 오류 — 대체 끄고 주 경로로: %s★", wt.chain, common.redact_urls(str(e)))
                _RPCFB_RETURNING.add(wt.chain)
                try:
                    self.wt = make(cfg, wt.chain, wt.wallets)
                except (Exception, SystemExit) as e9:
                    log.error("%s 주 경로 워처 생성 실패(다음 주기 재시도): %s", wt.chain, e9)
                finally:
                    _RPCFB_RETURNING.discard(wt.chain)
                return True
            bf_engine.health("evm").fail(wt.chain, e, "rpc")
            bf_engine.health("evm").flush()
            log.error("★%s 체인 추적 중지(설정 오류): %s — 다른 체인은 계속, 고친 뒤 pm2 restart tj-evm★", wt.chain, common.redact_urls(str(e)))
            DISABLED_CHAINS.add(wt.chain)
            return False
        except Exception as e:
            n9 = bf_engine.health("evm").fail(wt.chain, e, "etherscan" if isinstance(wt, EtherscanWatcher)
                                              else "rpc" if isinstance(wt, RpcChainWatcher) else "blockscout")
            bf_engine.health("evm").flush()
            lv = bf_engine.LogDebounce.level(n9)
            if lv:
                getattr(log, lv)("%s cycle 실패 %d회 연속(다음 주기 재시도): %s", wt.chain, n9, common.redact_urls(str(e)))
            if getattr(wt, "fb_info", None) and isinstance(e, StateUnavailable) and "인계 기준점" in str(e):
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
            if wt is not wt0 and getattr(wt, "fb_info", None):
                self.es_daily_fb = False
            self.wt = wt
            try:
                cur9 = common.read_json(wt.cursor_path, {})
                a9 = cur9.pop("_synced_at", None) is not None
                b9 = cur9.pop("_synced_tok_at", None) is not None
                if a9 or b9:
                    common.atomic_write_json(wt.cursor_path, cur9)
                wt.cursor = cur9
            except Exception:
                pass
        wt = self.wt
        CUR_WATCHER[wt.chain] = wt
        try:
            fb9 = getattr(wt, "fb_info", None)
            bf_engine.health("evm").facts(
                wt.chain, es_daily_until=int(_ES_DAILY["until"]) if self.es_daily_fb and es_daily_left() > 0 else None,
                rpc_fb=dict(fb9) if fb9 else None,
                rpc_limited=getattr(wt, "nodes_limited", None) if (isinstance(wt, RpcChainWatcher) and not fb9) else None)
        except Exception:
            pass
        return True


def _revoke_stamp_disk(cursor_path: str, tok: bool = True):
    try:
        cur9 = common.read_json(cursor_path, {})
        a9 = cur9.pop("_synced_at", None) is not None
        b9 = tok and cur9.pop("_synced_tok_at", None) is not None
        if a9 or b9:
            common.atomic_write_json(cursor_path, cur9)
    except Exception as e:
        log.warning("도장 철회 실패(무시): %s", e)


def http_json(url: str, prio: str = "fg", deadline: float = None, retries: int = None, breaker_5xx: bool = True):
    return bf_engine.http_json(url, timeout=HTTP_TIMEOUT, retries=HTTP_RETRIES if retries is None else retries,
                               prio=prio, deadline=deadline, ua=UA, breaker_5xx=breaker_5xx)


class RpcSynthMixin:

    TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    WETH_DEPOSIT = "0xe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc9109c"
    WETH_WITHDRAWAL = "0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65"
    ZERO_ADDR = "0x0000000000000000000000000000000000000000"
    RPC_DEFAULT = {
        "base": ["https://mainnet.base.org", "https://base.drpc.org", "https://gateway.tenderly.co/public/base"],
        "optimism": ["https://mainnet.optimism.io", "https://optimism.drpc.org"],
        "eth": ["https://eth.drpc.org", "https://ethereum-rpc.publicnode.com"],
        "arbitrum": ["https://arb1.arbitrum.io/rpc"],
        "polygon": ["https://polygon.drpc.org", "https://polygon-bor-rpc.publicnode.com", "https://gateway.tenderly.co/public/polygon"],
        "gnosis": ["https://rpc.gnosischain.com"],
        "scroll": ["https://rpc.scroll.io"],
        "zksync": ["https://mainnet.era.zksync.io"],
        "robinhood": ["https://rpc.mainnet.chain.robinhood.com"],
        "arc": ["https://rpc.mainnet.arc.io", "https://rpc.quicknode.mainnet.arc.io"],
    }

    NATIVE_EMITTER = {"arc": "0xfffffffffffffffffffffffffffffffffffffffe",
                      **{c9: z9[0] for c9, z9 in common.ZK_STACK.items()}}
    NATIVE_FEE_SINK = {c9: z9[1] for c9, z9 in common.ZK_STACK.items()}
    NATIVE_MIRROR = {c9: frozenset({m9[0]}) for c9, m9 in common.NATIVE_MIRROR.items()}
    NATIVE_MIRROR_SRC = {k9: v9 for k9, v9 in common.NATIVE_MIRROR.items() if k9 != "arc"}

    SYNTH_TRIP_BASE = 15.0
    SYNTH_TRIP_RATE = 60.0
    SYNTH_TRIP_MAX = 900.0

    def _synth_ep(self, url: str) -> dict:
        eps = getattr(self, "_synth_eps", None)
        if eps is None:
            eps = self._synth_eps = {}
        return eps.setdefault(url, {"fail_until": 0.0, "streak": 0})

    @staticmethod
    def rpc_deferred(e) -> bool:
        seen = set()
        while isinstance(e, BaseException) and id(e) not in seen:
            seen.add(id(e))
            if isinstance(e, bf_engine.NetError) and getattr(e, "kind", None) in ("quota", "budget", "circuit"):
                return True
            e = e.__cause__
        return False

    def synth_fail_count(self, counts: dict, h: str, err):
        if self.rpc_deferred(err):
            return None
        counts[h] = int(counts.get(h, 0)) + 1
        return counts[h]

    def _synth_trip(self, url: str, e: Exception):
        st = self._synth_ep(url)
        st["deferred"] = e if self.rpc_deferred(e) else None
        msg = str(e)
        ratelike = ("429" in msg or "Too Many" in msg or "rate limit" in msg.lower()
                    or "-32016" in msg or "403" in msg)
        base = self.SYNTH_TRIP_RATE if ratelike else self.SYNTH_TRIP_BASE
        wait = min(base * (2 ** min(st["streak"], 5)), self.SYNTH_TRIP_MAX) * (1.0 + random.random() * 0.5)
        st["fail_until"] = time.time() + wait
        st["streak"] += 1
        log.warning("%s rpc 엔드포인트 쿨다운 %.0fs (%d연속): %s — %s", self.chain, wait, st["streak"],
                    common.redact_urls(url), common.redact_urls(msg)[:80])

    def _rpc_call(self, method: str, params: list):
        rpcs = self.cfg_rpcs or self.RPC_DEFAULT.get(self.chain) or []
        now = time.time()
        ready = [u for u in rpcs if self._synth_ep(u)["fail_until"] <= now]
        order = ready if ready else list(rpcs)
        last = None
        for url in order:
            try:
                d = bf_engine.http_json(
                    url, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                    headers={"User-Agent": common.ua_for(url, UA)}, timeout=15, retries=1, rpc_methods=(method,))
                if not isinstance(d, dict):
                    raise RuntimeError(f"rpc {method}: 응답 형식 오류 ({type(d).__name__})")
                if d.get("error"):
                    raise RuntimeError(f"rpc {method}: {common.redact_secret_text(str(d['error']))[:160]}")
                self._synth_ep(url)["streak"] = 0
                self._synth_ep(url)["deferred"] = None
                if d.get("result") is not None:
                    return d["result"]
                last = RuntimeError("result null")
            except Exception as e:
                last = e
                self._synth_trip(url, e)
        for url in rpcs:
            d9 = self._synth_ep(url).get("deferred")
            if d9 is not None:
                raise bf_engine.NetError(f"보류(게이트·장부): {common.redact_urls(str(d9))[:160]}", getattr(d9, "kind", None) or "circuit",
                                         host=getattr(d9, "host", None))
        raise last if last else RuntimeError("rpc 미구성")

    def _ref_head(self):
        try:
            return int(self._rpc_call("eth_blockNumber", []), 16)
        except Exception:
            return None

    def _block_sec_est(self, head: int) -> float:
        now = time.time()
        prev = getattr(self, "_hb_prev", None)
        est = getattr(self, "_hb_bsec", None)
        if prev and head > prev[0] and now > prev[1]:
            v = (now - prev[1]) / float(head - prev[0])
            est = v if est is None else 0.7 * est + 0.3 * v
            self._hb_bsec = est
        if not prev or head != prev[0]:
            self._hb_prev = (head, now)
            self._hb_head_changed = now
        return est

    def _health_cycle(self, kind: str, head: int, safe: int, ok: bool, err=None, **extra):
        hb = bf_engine.health("evm")
        tb9 = getattr(self, "_tier", None)
        curs = [v for k, v in self.cursor.items() if not k.startswith("_") and isinstance(v, int)
                and not (tb9 is not None and tb9.is_resting(k))]
        cmin = min(curs) if curs else None
        bsec = self._block_sec_est(head) if head else None
        ref = None if extra.get("tier_idle") else self._ref_head()
        facts = dict(head=head, head_ts=getattr(self, "_head_ts", None), ref_head=ref,
                     ref_gap_blocks=(ref - head) if (ref is not None and head) else None,
                     head_unchanged_sec=int(time.time() - getattr(self, "_hb_head_changed", time.time())),
                     cursor=cmin, lag_blocks=(safe - cmin) if (cmin is not None and safe) else None,
                     block_sec_est=round(bsec, 3) if bsec else None,
                     lag_sec=int((safe - cmin) * bsec) if (cmin is not None and safe and bsec) else None,
                     synced_at=self.cursor.get("_synced_at"), wallets=len(self.wallets),
                     wallets_backfilling=sum(1 for w in self.wallets if not isinstance(self.cursor.get(w), int)),
                     backfilling_ids=[w[:6] for w in self.wallets if not isinstance(self.cursor.get(w), int)][:3],
                     wallets_resting=sum(1 for w in self.wallets if tb9 is not None and tb9.is_resting(w)),
                     **extra)
        if ok:
            hb.ok(self.chain, kind, **facts)
        else:
            hb.fail(self.chain, err or RuntimeError("부분 실패"), kind, **facts)
        hb.flush()

    def _block_ts(self, blk: int) -> int:
        b = self._rpc_call("eth_getBlockByNumber", [hex(int(blk)), False]) or {}
        if not b.get("timestamp"):
            raise RuntimeError(f"블록 {blk} 시각 미확보")
        return int(b["timestamp"], 16)

    def window_start_block(self, safe_now: int, months: float, bpd: int) -> int:
        target = int(time.time() - months * 30 * 86400)
        try:
            b = bf_engine.block_at_ts(self._block_ts, target, 0, int(safe_now))
            log.info("%s 백필 창 시작 = 블록 %d (타임스탬프 탐색, bpd 가정치 %d 대비 %+d블록)", self.chain, b,
                     max(0, safe_now - int(months * 30 * bpd)), b - max(0, safe_now - int(months * 30 * bpd)))
            return b
        except Exception as e:
            b = max(0, safe_now - int(months * 30 * bpd))
            log.warning("%s 창 시작 타임스탬프 탐색 실패 → blocks_per_day 환산 %d 로 폴백: %s", self.chain, b, e)
            return b

    def _nodec_reg(self):
        return bf_engine.nodec_registry(self.chain, log)

    def _rpc_token_dec(self, ca: str) -> int:
        m = self.rpc_meta.get(ca)
        if m is not None:
            return int(m)
        reg = self._nodec_reg()
        if reg.perm(ca):
            raise bf_engine.TokenNoDecimals(f"token decimals 영구 불능 {ca[:10]}")
        try:
            r = self._rpc_call("eth_call", [{"to": ca, "data": "0x313ce567"}, "latest"])
        except Exception as e:
            if bf_engine.revert_like(e) and reg.bad(ca, "revert: " + common.safe_err(e)[:80]):
                raise bf_engine.TokenNoDecimals(f"token decimals 영구 불능 {ca[:10]}: {common.safe_err(e)[:80]}") from e
            raise RuntimeError(f"token decimals 조회 실패 {ca[:10]}: {e}") from e
        dec, why = bf_engine.decimals_from_result(r)
        if dec is None:
            if reg.bad(ca, why):
                raise bf_engine.TokenNoDecimals(f"token decimals 영구 불능 {ca[:10]}: {why}")
            raise RuntimeError(f"token decimals 조회 실패 {ca[:10]}: decimals() {why}")
        reg.ok(ca)
        self.rpc_meta[ca] = dec
        common.atomic_write_json(self.rpc_meta_path, self.rpc_meta)
        return dec

    @staticmethod
    def opstack_normalize(tx: dict, rc: dict):
        fee = int(rc["gasUsed"], 16) * int(rc.get("effectiveGasPrice") or
                                           tx.get("gasPrice") or "0x0", 16)
        fee += int(rc.get("l1Fee") or "0x0", 16)
        typ_raw = tx.get("type")
        try:
            typ = int(typ_raw, 16) if isinstance(typ_raw, str) else (
                int(typ_raw) if typ_raw is not None else None)
        except (TypeError, ValueError):
            typ = None
        if typ == 3:
            if rc.get("blobGasUsed") is None or rc.get("blobGasPrice") is None:
                raise ValueError("blob tx(type 3) 영수증에 blobGasUsed·blobGasPrice 없음 — 수수료 추정 안 함(결정적 상세 실패 규약)")
            fee += int(rc["blobGasUsed"], 16) * int(rc["blobGasPrice"], 16)
        if rc.get("operatorFee") is not None:
            fee += int(rc["operatorFee"], 16)
        elif rc.get("operatorFeeScalar") is not None or rc.get("operatorFeeConstant") is not None:
            g9 = int(rc["gasUsed"], 16) * int(rc.get("operatorFeeScalar") or "0x0", 16)
            fee += (g9 * 100 if rc.get("daFootprintGasScalar") is not None else g9 // 1_000_000) + int(rc.get("operatorFeeConstant") or "0x0", 16)
        mint = None
        if typ == 126:
            try:
                m = int(tx.get("mint") or "0x0", 16)
            except (TypeError, ValueError):
                m = 0
            if m > 0:
                mint = str(m)
        return fee, typ, mint

    def _wrap_legs(self, logs: list, tts: list, myset: set) -> list:
        wr = str(getattr(self, "wrapped_ca", None) or "").lower()
        if not wr:
            return []
        cover = {}
        for t in tts:
            if str(((t.get("token") or {}).get("address")) or "").lower() == wr and (t.get("token") or {}).get("type", "ERC-20") == "ERC-20":
                k = (str(t.get("from") or "").lower(), str(t.get("to") or "").lower(), str((t.get("total") or {}).get("value")))
                cover[k] = cover.get(k, 0) + 1
        out = []
        for lg in logs:
            tps = lg.get("topics") or []
            if len(tps) != 2 or (lg.get("address") or "").lower() != wr:
                continue
            t0 = (tps[0] or "").lower()
            if t0 not in (self.WETH_DEPOSIT, self.WETH_WITHDRAWAL):
                continue
            who = ("0x" + str(tps[1])[-40:]).lower()
            if who not in myset:
                continue
            try:
                v = int(lg.get("data") or "0x", 16)
            except ValueError:
                continue
            if not v:
                continue
            fr, to = (self.ZERO_ADDR, who) if t0 == self.WETH_DEPOSIT else (who, self.ZERO_ADDR)
            k = (fr, to, str(v))
            if cover.get(k):
                cover[k] -= 1
                continue
            out.append({"from": fr, "to": to,
                        "token": {"address": wr, "symbol": None, "type": "ERC-20", "decimals": self._rpc_token_dec(wr)},
                        "total": {"value": str(v)}})
        return out

    SELL_HINTS = False

    def _sell_wd_hint(self, tx: dict, rc: dict, tts: list, myset: set):
        wr = str(getattr(self, "wrapped_ca", None) or "").lower()
        f = str(tx.get("from") or "").lower()
        if not wr or f not in myset or rc.get("status") != "0x1":
            return None
        try:
            if int(tx.get("value") or "0x0", 16):
                return None
        except (TypeError, ValueError):
            return None
        if any(str(t.get("to") or "").lower() in myset for t in tts) or not any(str(t.get("from") or "").lower() == f for t in tts):
            return None
        wd = dep = 0
        src = None
        for lg in rc.get("logs") or []:
            tps = lg.get("topics") or []
            if len(tps) != 2 or (lg.get("address") or "").lower() != wr:
                continue
            t0 = (tps[0] or "").lower()
            who = ("0x" + str(tps[1])[-40:]).lower()
            if who in myset or t0 not in (self.WETH_DEPOSIT, self.WETH_WITHDRAWAL):
                continue
            try:
                v = int(lg.get("data") or "0x", 16)
            except ValueError:
                continue
            if t0 == self.WETH_WITHDRAWAL:
                wd += v
                src = src or who
            else:
                dep += v
        return (f, src, wd - dep) if src and wd - dep > 0 else None

    def _rpc_synth_detail(self, h: str) -> dict:
        tx = self._rpc_call("eth_getTransactionByHash", [h])
        rc = self._rpc_call("eth_getTransactionReceipt", [h])
        if not tx or not rc or rc.get("blockNumber") is None:
            raise RuntimeError("rpc 미확정 tx")
        blk = int(rc["blockNumber"], 16)
        blkinfo = self._rpc_call("eth_getBlockByNumber", [rc["blockNumber"], False]) or {}
        if not blkinfo.get("timestamp"):
            raise RuntimeError("블록 시각 미확보")
        ts9 = int(blkinfo["timestamp"], 16)
        if rc.get("gasUsed") is None:
            raise RuntimeError("영수증 gasUsed 미확보")
        fee, typ, mint = self.opstack_normalize(tx, rc)
        myset = set(self.wallets)
        tts = []
        emitter = self.NATIVE_EMITTER.get(self.chain)
        mirror = self.NATIVE_MIRROR.get(self.chain) or frozenset()
        msrc = None if emitter else self.NATIVE_MIRROR_SRC.get(self.chain)
        sink = self.NATIVE_FEE_SINK.get(self.chain) if emitter else None
        f_tx = (tx.get("from") or "").lower()
        fee_paid = fee_back = 0
        fee_seen = False
        nat_logs = []
        for lg in rc.get("logs") or []:
            tps = lg.get("topics") or []
            if len(tps) == 4 and (tps[0] or "").lower() == self.TRANSFER_TOPIC:
                fr7, to7 = ("0x" + tps[1][-40:]).lower(), ("0x" + tps[2][-40:]).lower()
                if fr7 in myset or to7 in myset:
                    try:
                        tid7 = int(tps[3], 16)
                    except (TypeError, ValueError):
                        continue
                    tts.append({"from": fr7, "to": to7, "token": {"address": (lg.get("address") or "").lower(), "symbol": None,
                                                                   "type": "ERC-721", "decimals": None},
                                "total": {"token_id": str(tid7), "decimals": None, "value": None}})
                continue
            if len(tps) != 3 or (tps[0] or "").lower() != self.TRANSFER_TOPIC:
                continue
            ca0 = (lg.get("address") or "").lower()
            if ca0 in mirror:
                if msrc and ca0 == msrc[0]:
                    try:
                        v0 = int(lg.get("data") or "0x", 16)
                    except ValueError:
                        continue
                    if v0:
                        nat_logs.append((("0x" + tps[1][-40:]).lower(), ("0x" + tps[2][-40:]).lower(), v0 * int(msrc[1])))
                continue
            if emitter and ca0 == emitter:
                try:
                    v0 = int(lg.get("data") or "0x", 16)
                except ValueError:
                    continue
                f0, t0 = ("0x" + tps[1][-40:]).lower(), ("0x" + tps[2][-40:]).lower()
                if sink and sink in (f0, t0):
                    fee_seen = True
                    if f0 == f_tx and t0 == sink:
                        fee_paid += v0
                        continue
                    if f0 == sink and t0 == f_tx:
                        fee_back += v0
                        continue
                if v0:
                    nat_logs.append((f0, t0, v0))
                continue
            data = lg.get("data") or "0x"
            try:
                v = int(data, 16)
            except ValueError:
                continue
            if not v:
                continue
            fr = ("0x" + tps[1][-40:]).lower()
            to = ("0x" + tps[2][-40:]).lower()
            if fr not in myset and to not in myset:
                continue
            ca = (lg.get("address") or "").lower()
            try:
                dec9 = self._rpc_token_dec(ca)
            except bf_engine.TokenNoDecimals:
                self._nodec_reg().skip(h, ca, fr, to, v)
                continue
            tts.append({"from": fr, "to": to,
                        "token": {"address": ca, "symbol": None, "type": "ERC-20",
                                  "decimals": dec9},
                        "total": {"value": str(v)}})
        tts.extend(self._wrap_legs(rc.get("logs") or [], tts, myset))
        if getattr(self, "SELL_HINTS", False) and not emitter and not msrc:
            hint9 = self._sell_wd_hint(tx, rc, tts, myset)
            hd9 = self.__dict__.setdefault("_sell_wd", {})
            if hint9:
                if len(hd9) > 20000:
                    hd9.clear()
                hd9[h.lower()] = hint9
            else:
                hd9.pop(h.lower(), None)
        internal = []
        if emitter or msrc:
            v_top = int(tx.get("value", "0x0"), 16)
            f_top = (tx.get("from") or "").lower()
            t_top = (tx.get("to") or rc.get("contractAddress") or "").lower()
            skip = v_top > 0
            sc9 = int(msrc[1]) if msrc else 1
            for f0, t0, v0 in nat_logs:
                if skip and (f0, t0) == (f_top, t_top) and (v0 == v_top or (msrc and v0 == (v_top // sc9) * sc9)):
                    skip = False
                    continue
                if f0 in myset or t0 in myset:
                    internal.append({"from": f0, "to": t0, "value": str(v0), "success": True})
        if sink and fee_seen:
            if fee_paid or fee_back:
                if fee_paid >= fee_back:
                    fee = fee_paid - fee_back
            else:
                fee = 0
        snap_tx = {"hash": h, "from": tx.get("from"), "to": tx.get("to"),
                   "value": str(int(tx.get("value", "0x0"), 16)),
                   "fee": {"value": str(fee)},
                   "status": "ok" if rc.get("status") == "0x1" else "error",
                   "raw_input": tx.get("input") or "0x",
                   "timestamp": ts9, "block_number": blk,
                   "block_hash": rc.get("blockHash"), "synth": "rpc"}
        if typ is not None:
            snap_tx["type"] = typ
        if typ == 126:
            snap_tx["op_mint"] = mint or "0"
        if emitter:
            return {"tx": snap_tx, "token_transfers": tts, "internal": internal, "internal_note": "zk_base_token" if sink else "eip7708"}
        if msrc:
            return {"tx": snap_tx, "token_transfers": tts, "internal": internal, "internal_note": "native_mirror"}
        return {"tx": snap_tx, "token_transfers": tts, "internal": []}


def rpc_handback(wt, target: str):
    cur = wt.cursor
    ts9 = time.strftime("%Y%m%d_%H%M%S")
    common.atomic_write_json(wt.cursor_path + f".rpc_handback_{ts9}", cur)
    jobs = {k[4:]: v for k, v in cur.items() if k.startswith("_bk:") and isinstance(v, dict)}
    new = {k: v for k, v in cur.items() if k.startswith("_cov:") or (not k.startswith("_") and isinstance(v, int)
                                                                    and not isinstance(v, bool))}
    rs, drop = [], []
    for w, j in jobs.items():
        try:
            d9, t9 = int(j.get("done") or 0), int(j.get("to") or 0)
        except (TypeError, ValueError):
            continue
        if d9 >= t9:
            continue
        if j.get("why") == "new" or (target == "etherscan" and j.get("why") == "internal"):
            new.pop(w, None)
            drop.append(w)
        elif j.get("why") == "extend":
            new["_cov:" + w] = t9
        else:
            rs.append({"wallet": w, "from_block": d9, "to_block": t9, "kind": "readd", "since": None, "job": None,
                       "npp": None, "done": False, "pages": 0})
    ll9 = {k: v for k, v in (cur.get("_leaf_later") or {}).items()
           if isinstance(v, dict) and isinstance(v.get("w"), str) and type(v.get("blk")) is int and v["blk"] > 0}
    for e9 in ll9.values():
        w9, y9 = e9["w"].lower(), int(e9["blk"])
        if target == "etherscan":
            new.pop(w9, None)
            if w9 not in drop:
                drop.append(w9)
        else:
            rs.append({"wallet": w9, "from_block": y9 - 1, "to_block": y9, "kind": "leaf", "since": None, "job": None,
                       "npp": None, "done": False, "pages": 0})
    if ll9:
        new["_leaf_later_left"] = ll9
    if rs:
        new["_ext_internal_pending"] = {"v": 1, "ranges": rs, "hashes": [], "emit_i": 0, "created": int(time.time())}
    qd = cur.get("_quarantine") if isinstance(cur.get("_quarantine"), dict) else {}
    if qd and target == "etherscan":
        new["_quarantine_left"] = qd
    elif qd:
        pp = os.path.join(common.STATE_DIR, f"pending_detail_{wt.chain}.json")
        pend9 = common.read_json(pp, {}) or {}
        for h in qd:
            pend9.setdefault(str(h).lower(), 0)
        common.atomic_write_json(pp, pend9)
    hq = cur.get("_hq") if isinstance(cur.get("_hq"), dict) else {}
    if hq and target == "etherscan":
        hp = os.path.join(common.STATE_DIR, f"hq_left_{wt.chain}.json")
        old9 = common.read_json(hp, {}) or {}
        for h in hq:
            old9.setdefault(str(h).lower(), 0)
        common.atomic_write_json(hp, old9)
    elif hq:
        ep = os.path.join(common.STATE_DIR, f"enrich_{wt.chain}.json")
        enr = common.read_json(ep, {}) or {}
        for h in hq:
            enr.setdefault(str(h).lower(), 0)
        common.atomic_write_json(ep, enr)
    new["_handback"] = {"at": int(time.time()), "from": "rpc", "first_backfill": len(drop), "internal_ranges": len(rs), "enrich": len(hq),
                        "leaf_later": len(ll9),
                        "backup": os.path.basename(wt.cursor_path + f".rpc_handback_{ts9}")}
    wt.cursor = new
    common.atomic_write_json(wt.cursor_path, new)
    log.warning("★%s RPC 전용 → " + ("이더스캔" if target == "etherscan" else "블록스카웃") + " 되돌림: 지갑 커서 %d개 이어받음 · 첫 백필로 되돌린 지갑 %d · internal 재훑기 구간 %d · enrich %d건 (원본 .rpc_handback_%s)★",
                wt.chain, sum(1 for k in new if not k.startswith("_")), len(drop), len(rs), len(hq), ts9)


class ChainWatcher(RpcSynthMixin):
    def __init__(self, cfg: dict, chain: str, wallets: list, writer: SegmentWriter):
        self.chain = chain
        self.wrapped_ca = str((cfg.get("wrapped_native") or {}).get(chain) or "").lower() or None
        self.base = cfg["chains"][chain]["blockscout"].rstrip("/")
        self.conf_depth = int(cfg["chains"][chain].get("conf_depth", 12))
        self.backfill = bool(cfg.get("backfill_full_history"))
        self.backfill_months = float(cfg.get("backfill_months") or 0)
        self.bpd = int(cfg["chains"][chain].get("blocks_per_day", 43200))
        self.wallets = [w.lower() for w in wallets]
        self.wallet_since = bf_engine.wallet_since_map(cfg, chain)
        self.writer = writer
        self.cursor_path = os.path.join(common.STATE_DIR, f"cursor_evm_{chain}.json")
        self.cursor = common.read_json(self.cursor_path, {})
        if self.cursor.get("_rpc_v") is not None:
            self._rpc_handback()
        self.pending_detail = common.read_json(
            os.path.join(common.STATE_DIR, f"pending_detail_{chain}.json"), {})
        self.fail_streak = {}
        self.cfg_rpcs = cfg["chains"][chain].get("rpcs")
        self.rpc_meta_path = os.path.join(common.STATE_DIR, f"rpc_token_meta_{chain}.json")
        self.rpc_meta = common.read_json(self.rpc_meta_path, {})
        self.emitted_path = os.path.join(common.STATE_DIR, f"emitted_evm_{chain}.json")
        self.emitted = set(common.read_json(self.emitted_path, []))
        _prev_w = {k for k in self.cursor if not k.startswith("_")}
        if _prev_w and not set(self.wallets).issubset(_prev_w) and self.emitted:
            log.warning("%s 새 관점 지갑 감지 — emitted %d건 초기화(재방출 허용)", chain, len(self.emitted))
            self.emitted.clear()
        self.rescan_overlap = int(cfg["chains"][chain].get("rescan_overlap_blocks", 0))
        self.idx_guard = bool(cfg["chains"][chain].get("indexing_status_guard"))
        self.idx_guard_scope = str(cfg["chains"][chain].get("indexing_guard_scope") or "head")
        self.enrich_path = os.path.join(common.STATE_DIR, f"enrich_{chain}.json")
        self.enrich = common.read_json(self.enrich_path, {})
        self._enrich_5xx = {}
        bfc = cfg.get("backfill") or {}
        self.bf_mode = str(bfc.get("engine") or "v2")
        self.bf2_budget = float(bfc.get("evm_cycle_budget_sec") or self.BF2_TIME_BUDGET)
        self.progress = bf_engine.progress("evm")
        self._prev_emitted = set(common.read_json(self.emitted_path, []))
        self._tier = addr_tier.evm_book(self, cfg, "blockscout")

    def _rpc_handback(self):
        rpc_handback(self, "blockscout")

    def _idx_note(self, idx_ok: bool, state: str = None, head_ok: bool = None):
        now9 = time.time()
        prev9 = getattr(self, "_idx_prev", True)
        kind9 = "ok" if idx_ok else ("partial" if head_ok else "hold")
        if not idx_ok:
            if prev9 is True:
                self._idx_bad_since = now9
            if prev9 is True or prev9 != kind9 or now9 - getattr(self, "_idx_warn_at", 0) >= 3600:
                unk9 = getattr(self, "_idx_unknown", None)
                if kind9 == "partial":
                    log.warning("%s blockscout indexing-status internal 색인만 미완(%s%s) — tx·토큰 목록으로 발견 진행(커서 전진), 내부 이동은 "
                                "'나중에 채우기' 표식(색인 완료 뒤 자동 재훑기) · 동기화 도장 보류(%.0f분째 — 다음 안내는 1시간 뒤/복구 시)",
                                self.chain, getattr(self, "_idx_ratio", None), f", 조회 실패 — 마지막 관측 유지: {unk9}" if unk9 else "",
                                (now9 - getattr(self, "_idx_bad_since", now9)) / 60)
                else:
                    log.warning("%s blockscout indexing-status 미완(%s%s) — discovery 보류(커서 유지, %.0f분째 — 다음 경고는 1시간 뒤/복구 시)",
                                self.chain, state, f", 조회 실패 — 마지막 관측 유지: {unk9}" if unk9 else "",
                                (now9 - getattr(self, "_idx_bad_since", now9)) / 60)
                self._idx_warn_at = now9
        elif prev9 is not True:
            log.info("%s blockscout indexing-status 복구 — discovery 재개(전면 · %.0f분 만에)",
                     self.chain, (now9 - getattr(self, "_idx_bad_since", now9)) / 60)
        self._idx_prev = True if idx_ok else kind9

    def _indexing_ok(self) -> bool:
        return self._indexing_state() == "ok"

    def _indexing_state(self) -> str:
        self._idx_ratio = None
        try:
            d = http_json(f"{self.base}/api/v2/main-page/indexing-status")
        except Exception as e:
            return self._idx_sticky(e)
        if not isinstance(d, dict):
            return self._idx_sticky(RuntimeError("indexing-status 응답 형식 오류"))
        fb, fi = d.get("finished_indexing_blocks"), d.get("finished_indexing")
        if fb is False:
            st = "blocks"
        elif fi is True:
            st = "ok"
        elif fi is False:
            st = "internal" if fb is True else "blocks"
        else:
            return self._idx_sticky(RuntimeError("indexing-status 응답에 finished_indexing 없음"))
        self._idx_ratio = d.get("indexed_internal_transactions_ratio")
        self._idx_unknown = None
        self._idx_seen = (st, time.time(), self._idx_ratio)
        self._idx_streak_note(st, self._idx_ratio)
        return st

    IDX_BLOCKS_STICKY_SEC = 3600
    IDX_OK_FRESH_SEC = 1800
    IDX_STABLE_SEC = int(os.environ.get("TJ_INT_RESCAN_STABLE_SEC") or 3600)
    IDX_STREAK_GAP_SEC = 900
    IDX_RECHECK_SEC = 30
    IDX_RATIO_FULL = 0.99

    @classmethod
    def _ratio_full(cls, ratio) -> bool:
        if ratio is None:
            return True
        try:
            return float(str(ratio)) >= cls.IDX_RATIO_FULL
        except (TypeError, ValueError):
            return True

    def _idx_streak_note(self, st: str, ratio):
        now = int(time.time())
        if st == "ok" and self._ratio_full(ratio):
            s = self.cursor.get("_idx_ok_streak")
            if isinstance(s, dict) and now - int(s.get("last") or 0) <= self.IDX_STREAK_GAP_SEC:
                s["last"] = now
            else:
                self.cursor["_idx_ok_streak"] = {"since": now, "last": now}
            return
        self.cursor.pop("_idx_ok_streak", None)
        prev_bad = int(self.cursor.get("_idx_bad_at") or 0)
        self._int_reopen(prev_bad, st, ratio)
        self.cursor["_idx_bad_at"] = now

    def _int_reopen(self, prev_bad: int, st: str, ratio) -> int:
        m = self.cursor.get("_ext_internal_pending")
        if not isinstance(m, dict):
            return 0
        n = 0
        for r in m.get("ranges") or []:
            if not isinstance(r, dict):
                continue
            if r.get("done"):
                hit = r.get("done_at") is not None and int(r["done_at"]) >= int(prev_bad)
            else:
                prog = int(r.get("pages") or 0) > 0 or r.get("npp") is not None
                hit = prog and (r.get("read_at") is None or int(r["read_at"]) >= int(prev_bad))
            if hit:
                r["done"], r["npp"], r["pages"] = False, None, 0
                r.pop("done_at", None)
                r.pop("read_at", None)
                n += 1
        if n:
            m.pop("started", None)
            m["reopened"] = int(m.get("reopened") or 0) + n
            m["emit_i"] = 0
            log.warning("★%s 탐색기 색인 회귀(%s · 비율 %s) — 그 전 '완료' 관측 뒤 끝내거나 읽던 internal 재훑기 구간 %d개를 처음부터 다시(1시간 연속 완료 뒤 재개)★",
                        self.chain, st, ratio, n)
        return n

    def _int_lag_track(self, idx_state: str):
        if idx_state in ("internal", "blocks") and not isinstance(self.cursor.get("_int_lag_since"), int):
            m9 = self.cursor.get("_ext_internal_pending")
            c9 = int(m9.get("created") or 0) if isinstance(m9, dict) else 0
            self.cursor["_int_lag_since"] = min(int(time.time()), c9) if c9 > 0 else int(time.time())
        elif idx_state == "ok" and not isinstance(self.cursor.get("_ext_internal_pending"), dict):
            self.cursor.pop("_int_lag_since", None)

    def _idx_stable(self) -> bool:
        if not self.idx_guard:
            return True
        s = self.cursor.get("_idx_ok_streak")
        if not isinstance(s, dict) or getattr(self, "_idx_unknown", None):
            return False
        now = time.time()
        return now - int(s.get("since") or now) >= self.IDX_STABLE_SEC and now - int(s.get("last") or 0) <= self.IDX_STREAK_GAP_SEC

    def _idx_recheck(self) -> bool:
        if not self.idx_guard:
            return True
        seen = getattr(self, "_idx_seen", None)
        if not (seen and seen[0] == "ok" and self._ratio_full(seen[2]) and time.time() - seen[1] < self.IDX_RECHECK_SEC
                and not getattr(self, "_idx_unknown", None)):
            if self._indexing_state() != "ok" or getattr(self, "_idx_unknown", None):
                return False
        return self._idx_stable()

    def _idx_sticky(self, err) -> str:
        self._idx_unknown = common.safe_err(err)[:120]
        seen = getattr(self, "_idx_seen", None)
        now9 = time.time()
        if seen and seen[0] == "blocks" and now9 - seen[1] < self.IDX_BLOCKS_STICKY_SEC:
            return "blocks"
        lag = self.cursor.get("_ext_internal_lag")
        pend = isinstance(self.cursor.get("_ext_internal_pending"), dict)
        job = self.cursor.get("_bfjob")
        if isinstance(job, dict) and job.get("int_lag"):
            pend = True
        if seen and seen[0] == "ok":
            if not pend and now9 - seen[1] < self.IDX_OK_FRESH_SEC:
                return "ok"
            self._idx_ratio = seen[2]
            return "internal"
        if seen or isinstance(lag, dict):
            self._idx_ratio = (seen[2] if seen else None) or (lag.get("ratio") if isinstance(lag, dict) else None)
            return "internal"
        return "internal" if pend else "ok"

    def head_block(self):
        d = http_json(f"{self.base}/api/v2/blocks?type=block")
        items = d.get("items") or []
        if not items:
            raise RuntimeError("blocks 응답 비어있음")
        head = int(items[0]["height"])
        ts9 = items[0].get("timestamp")
        if isinstance(ts9, str):
            try:
                import datetime as _dt
                self._head_ts = int(_dt.datetime.fromisoformat(ts9.replace("Z", "+00:00")).timestamp())
            except ValueError:
                pass
        mx = getattr(self, "_max_head", 0)
        if mx and head < mx - max(64, self.conf_depth):
            raise bf_engine.NetError(f"blockscout 헤드 역행 {head} < 관측 최대 {mx} (뒤처진 복제본)", "stale_head")
        self._max_head = max(mx, head)
        self._explorer_frozen_check(head)
        return head

    def _explorer_frozen_check(self, head: int):
        hts = getattr(self, "_head_ts", None)
        if not isinstance(hts, int) or time.time() - hts <= EXPLORER_FROZEN_SEC:
            return
        ref = self._ref_head()
        if ref is None or ref - int(head) <= max(EXPLORER_FROZEN_GAP, 10 * int(self.conf_depth)):
            return
        hrs = (time.time() - hts) / 3600.0
        raise bf_engine.NetError(
            f"blockscout 색인 정지 — 최신 블록 {int(head)} 이 {hrs:.0f}시간째 그대로(노드 헤드 {ref} · {ref - int(head)}블록 뒤) — "
            "그 뒤 새 거래를 받지 못함", "stale_head")

    def _page_json(self, url: str, tries: int = 5):
        for i in range(tries):
            try:
                return http_json(url)
            except bf_engine.NetError as e:
                if i == tries - 1 or e.kind in ("circuit", "quota", "budget"):
                    raise
                time.sleep(1.0 + 1.5 * i)
            except Exception:
                if i == tries - 1:
                    raise
                time.sleep(1.0 + 1.5 * i)

    def discover(self, wallet: str, since_block: int, safe_block: int, first_sync: bool = False, skip_internal: bool = False):
        hashes = {}
        ck = None if first_sync else self.cursor.get("_disc:" + wallet)
        if not (isinstance(ck, dict) and isinstance(ck.get("safe"), int) and ck.get("since") == since_block
                and isinstance(ck.get("ep"), int) and 0 <= ck["ep"] < 3 and ck["safe"] > since_block):
            ck = None
        if ck:
            safe_block = int(ck["safe"])
        self._disc_safe = safe_block
        self._disc_ck_next = None
        eps9 = (("transactions", "hash"),
                ("token-transfers", "transaction_hash"),
                ("internal-transactions", "transaction_hash"))
        for ep_i, (ep, hash_key) in enumerate(eps9[:2] if skip_internal else eps9):
            if ck and ep_i < int(ck["ep"]):
                continue
            url = f"{self.base}/api/v2/addresses/{wallet}/{ep}"
            if ck and ep_i == int(ck["ep"]) and isinstance(ck.get("npp"), dict):
                url += "?" + urllib.parse.urlencode(ck["npp"])
            pages = 0
            pages_max = BACKFILL_PAGES_MAX if first_sync else DISCOVERY_PAGES_MAX
            while url and pages < pages_max:
                try:
                    d = self._page_json(url)
                except Exception as e:
                    self._disc_err = f"{ep}: {common.safe_err(e)[:160]}"
                    self._rpcfb_disc_error = e
                    return None
                if not isinstance(d, dict) or not isinstance(d.get("items"), list):
                    log.warning("%s %s 응답 형식 오류 — 커서 유지", wallet[:10], ep)
                    return None
                oldest = None
                for it in d["items"]:
                    if not isinstance(it, dict):
                        continue
                    h = it.get(hash_key)
                    if not isinstance(h, str) or not h:
                        continue
                    raw_blk = it.get("block_number")
                    if raw_blk is None:
                        raw_blk = it.get("block")
                    if raw_blk is None:
                        hashes.setdefault(h, None)
                        continue
                    try:
                        blk = int(raw_blk)
                    except (TypeError, ValueError):
                        hashes.setdefault(h, None)
                        continue
                    oldest = blk if oldest is None else min(oldest, blk)
                    if since_block < blk <= safe_block:
                        hashes[h] = blk
                npp = d.get("next_page_params")
                if oldest is None and isinstance(npp, dict) and npp.get("block_number") is not None:
                    try:
                        oldest = int(npp["block_number"])
                    except (TypeError, ValueError):
                        pass
                if oldest is not None and oldest <= since_block:
                    break
                if not npp:
                    break
                if not isinstance(npp, dict):
                    log.warning("%s %s next_page_params 형식 오류 — 커서 유지", wallet[:10], ep)
                    return None
                url = f"{self.base}/api/v2/addresses/{wallet}/{ep}?" + urllib.parse.urlencode(npp)
                pages += 1
                time.sleep(0.3)
            else:
                if pages >= pages_max:
                    if first_sync:
                        log.warning("%s %s 페이지 상한 도달 — 놓친 구간은 커서 유지로 다음 사이클 재시도",
                                    wallet[:10], ep)
                        return None
                    self._disc_ck_next = {"since": since_block, "safe": safe_block, "ep": ep_i, "npp": npp}
                    log.warning("%s %s 증분 페이지 상한(%d) — 체크포인트 저장, 다음 사이클 이어받기(창 %d~%d)",
                                wallet[:10], ep, pages_max, since_block, safe_block)
                    return hashes
        return hashes

    BF_PAGE_BUDGET = 150
    BF_TIME_BUDGET = 600
    BF_FLUSH_EVERY = 10

    def _first_sync_walk(self, w: str, head: int, safe_now: int) -> bool:
        ck = self.cursor.get("_bf:" + w)
        if not isinstance(ck, dict) or "safe" not in ck:
            since0 = 0 if self.backfill else self.window_start_block(safe_now, self.backfill_months, self.bpd)
            ws9 = (getattr(self, "wallet_since", None) or {}).get(w)
            if ws9 and since0 > 0:
                since0 = min(since0, self.window_start_block_ts(ws9))
            ck = {"since": since0, "safe": safe_now, "ep": 0, "npp": None, "pages": 0}
            self.cursor["_bf:" + w] = ck
            common.atomic_write_json(self.enrich_path, self.enrich)
            common.atomic_write_json(
                os.path.join(common.STATE_DIR, f"pending_detail_{self.chain}.json"),
                self.pending_detail)
            common.atomic_write_json(self.emitted_path, sorted(self.emitted))
            common.atomic_write_json(self.cursor_path, self.cursor)
            log.info("%s 재개형 백필 시작 (%d → %d)", w[:10], since0, safe_now)
        since0, safe0 = int(ck["since"]), int(ck["safe"])
        eps = (("transactions", "hash"),
               ("token-transfers", "transaction_hash"),
               ("internal-transactions", "transaction_hash"))
        budget = self.BF_PAGE_BUDGET
        deadline = time.time() + self.BF_TIME_BUDGET
        try:
            while int(ck["ep"]) < len(eps) and budget > 0 and time.time() < deadline:
                ep, hash_key = eps[int(ck["ep"])]
                url = f"{self.base}/api/v2/addresses/{w}/{ep}"
                if isinstance(ck.get("npp"), dict):
                    url += "?" + urllib.parse.urlencode(ck["npp"])
                try:
                    d = self._page_json(url)
                except Exception as e:
                    log.warning("%s %s 백필 페이지 실패 — 체크포인트 유지(p%d): %s",
                                w[:10], ep, int(ck.get("pages", 0)), e)
                    return False
                if not isinstance(d, dict) or not isinstance(d.get("items"), list):
                    log.warning("%s %s 백필 응답 형식 오류 — 체크포인트 유지", w[:10], ep)
                    return False
                oldest = None
                cands = []
                seen_pg = set()
                for it in d["items"]:
                    if not isinstance(it, dict):
                        continue
                    h = it.get(hash_key)
                    if not isinstance(h, str) or not h:
                        continue
                    raw_blk = it.get("block_number")
                    if raw_blk is None:
                        raw_blk = it.get("block")
                    blk = None
                    if raw_blk is not None:
                        try:
                            blk = int(raw_blk)
                        except (TypeError, ValueError):
                            blk = None
                    if blk is not None:
                        oldest = blk if oldest is None else min(oldest, blk)
                        if not (since0 < blk <= safe0):
                            continue
                    addr_tier.tier_mark_if_live(self, h, [w])
                    if h.lower() in self.emitted or h.lower() in seen_pg:
                        continue
                    seen_pg.add(h.lower())
                    cands.append((h, blk))
                results = {}
                if cands:
                    ex9 = ThreadPoolExecutor(max_workers=5)
                    try:
                        futs = {ex9.submit(self.fetch_detail, h): h for h, _ in cands}
                        page_deadline = time.time() + 300
                        for fu in futs:
                            remain9 = max(0.05, page_deadline - time.time())
                            try:
                                results[futs[fu]] = fu.result(timeout=remain9)
                            except FutTimeout:
                                results[futs[fu]] = RuntimeError("페이지 상세 예산 초과")
                            except Exception as e9:
                                results[futs[fu]] = e9
                    finally:
                        ex9.shutdown(wait=False, cancel_futures=True)
                for h, blk in cands:
                    snap = results.get(h)
                    if isinstance(snap, Exception) or snap is None:
                        if blk is None:
                            log.warning("%s 백필 detail %s 블록 확인 실패 — 체크포인트 유지: %s",
                                        w[:10], h[:12], snap)
                            return False
                        log.warning("%s 백필 detail %s 실패 → pending 큐: %s", w[:10], h[:12], snap)
                        addr_tier.tier_mark(self, h, [w])
                        self.pending_detail[h] = 0
                        continue
                    try:
                        detail_blk = int(snap["tx"]["block_number"])
                    except (KeyError, TypeError, ValueError):
                        if blk is None:
                            return False
                        addr_tier.tier_mark(self, h, [w])
                        self.pending_detail[h] = 0
                        continue
                    if not (since0 < detail_blk <= safe0):
                        continue
                    try:
                        self.emit(h, snap, head)
                    except Exception as e:
                        log.error("inbox append 실패 — 체크포인트 유지: %s", e)
                        return False
                    self.emitted.add(h.lower())
                npp = d.get("next_page_params")
                if oldest is None and isinstance(npp, dict) and npp.get("block_number") is not None:
                    try:
                        oldest = int(npp["block_number"])
                    except (TypeError, ValueError):
                        pass
                ck["pages"] = int(ck.get("pages", 0)) + 1
                budget -= 1
                if (oldest is not None and oldest <= since0) or not npp:
                    ck["ep"] = int(ck["ep"]) + 1
                    ck["npp"] = None
                elif not isinstance(npp, dict):
                    log.warning("%s %s next_page_params 형식 오류 — 체크포인트 유지", w[:10], ep)
                    return False
                else:
                    ck["npp"] = npp
                if int(ck["pages"]) % self.BF_FLUSH_EVERY == 0:
                    common.atomic_write_json(self.enrich_path, self.enrich)
                    common.atomic_write_json(
                        os.path.join(common.STATE_DIR, f"pending_detail_{self.chain}.json"),
                        self.pending_detail)
                    common.atomic_write_json(self.emitted_path, sorted(self.emitted))
                    common.atomic_write_json(self.cursor_path, self.cursor)
                if int(ck["pages"]) % 50 == 0:
                    log.info("%s 백필 진행: %d페이지 누적, endpoint %d/3",
                             w[:10], int(ck["pages"]), int(ck["ep"]))
                time.sleep(0.3)
            if int(ck["ep"]) >= len(eps):
                self.cursor[w] = safe0
                self.cursor.pop("_bf:" + w, None)
                log.info("★%s 백필 완주 (%d페이지) — 커서 %d★", w[:10], int(ck.get("pages", 0)), safe0)
                return True
            why = "시간" if time.time() >= deadline else "페이지"
            log.info("%s 백필 %s예산 소진 (%d페이지 누적, endpoint %d/3) — 다음 사이클 계속",
                     w[:10], why, int(ck.get("pages", 0)), int(ck["ep"]))
            return False
        finally:
            common.atomic_write_json(self.enrich_path, self.enrich)
            common.atomic_write_json(
                os.path.join(common.STATE_DIR, f"pending_detail_{self.chain}.json"),
                self.pending_detail)
            common.atomic_write_json(self.emitted_path, sorted(self.emitted))
            common.atomic_write_json(self.cursor_path, self.cursor)

    BF2_TIME_BUDGET = 240
    BF2_EPS = (("transactions", "hash"), ("token-transfers", "transaction_hash"),
               ("internal-transactions", "transaction_hash"))
    BF2_FLUSH_EMITS = 50

    def _bf2_spool_path(self, job: dict) -> str:
        return os.path.join(common.STATE_DIR, f"bfspool_{self.chain}_{int(job['id'])}.jsonl")

    def _bf2_persist(self):
        common.atomic_write_json(self.enrich_path, self.enrich)
        common.atomic_write_json(os.path.join(common.STATE_DIR, f"pending_detail_{self.chain}.json"),
                                 self.pending_detail)
        common.atomic_write_json(self.emitted_path, sorted(self.emitted))
        common.atomic_write_json(self.cursor_path, self.cursor)

    def _bf2_new_job(self, first_ws: list, safe_now: int):
        groups = {}
        wsm = getattr(self, "wallet_since", None) or {}
        for w in first_ws:
            ck = self.cursor.get("_bf:" + w)
            if isinstance(ck, dict) and "safe" in ck and "since" in ck:
                key = (int(ck["since"]), int(ck["safe"]))
            else:
                key = ("new", wsm.get(w))
            groups.setdefault(key, []).append(w)
        key = next((k for k in groups if not isinstance(k[0], str)), None)
        if key is None:
            nk = sorted(groups, key=lambda k9: (k9[1] is None, k9[1] or 0))[0]
            since0 = 0 if self.backfill else self.window_start_block(safe_now, self.backfill_months, self.bpd)
            if nk[1] and since0 > 0:
                since0 = min(since0, self.window_start_block_ts(nk[1]))
            key = (since0, safe_now)
            wallets = sorted(groups[nk])
        else:
            wallets = sorted(groups[key])
        job = {"v": 2, "id": int(time.time() * 1000), "wallets": wallets, "since": int(key[0]),
               "safe": int(key[1]), "phase": "collect", "spool_off": 0, "rows": 0, "emit_i": 0,
               "t0": int(time.time()), "streams": {}}
        for w in wallets:
            for ep, _hk in self.BF2_EPS:
                job["streams"][f"{w}|{ep}"] = {"npp": None, "done": False, "pages": 0, "oldest": None}
            self.cursor["_bf:" + w] = {"since": job["since"], "safe": job["safe"], "ep": 0, "npp": None,
                                       "pages": 0, "v2": True}
        self.cursor["_bfjob"] = job
        self._bf2_persist()
        log.info("★%s 백필 v2 잡 시작: 지갑 %d (%s) 창 %d → %d★", self.chain, len(wallets),
                 ",".join(w[:10] for w in wallets), job["since"], job["safe"])
        return job

    def _cov_block(self, w: str, target_blk: int):
        v = self.cursor.get("_cov:" + w)
        if isinstance(v, int):
            return v
        hint = bf_engine.SINCE.covered_hint(self.chain)
        if hint:
            hb = getattr(self, "_hint_blk", None)
            if not hb or hb[0] != hint:
                hb = self._hint_blk = (hint, self.window_start_block_ts(hint))
            return min(hb[1], int(self.cursor.get(w, 0) or 0))
        return int(self.cursor.get(w, 0) or 0)

    def window_start_block_ts(self, ts: int) -> int:
        safe = getattr(self, "_max_head", 0) or self.head_block()
        return bf_engine.block_at_ts(self._block_ts, int(ts), 0, int(safe))

    def _bs_has_rows(self, w: str, blk: int):
        if self.idx_guard:
            seen9 = getattr(self, "_idx_seen", None)
            if not seen9 or seen9[0] not in ("ok", "internal") or getattr(self, "_idx_unknown", None):
                return None
        d = http_json(f"{self.base}/api/v2/addresses/{w}/token-transfers", prio="bg", retries=1)
        if not isinstance(d, dict) or not isinstance(d.get("items"), list):
            return None
        return bool(d["items"])

    def _ext_maybe_needed(self) -> bool:
        if str(getattr(self, "bf_mode", "v2")) == "legacy" or not bf_engine.SINCE.target(self.chain):
            return False
        return any(isinstance(self.cursor.get(w), int) and addr_tier._evm_ext_need(self, "blockscout", w) for w in self.wallets)

    def _maybe_extend(self, head: int, safe: int):
        target = bf_engine.SINCE.target(self.chain)
        if not target:
            return None
        if isinstance(self.cursor.get("_bfjob"), dict):
            return None
        tb = getattr(self, "_ext_tb", None)
        if not tb or tb[0] != target:
            try:
                tb = self._ext_tb = (target, self.window_start_block_ts(target))
            except Exception as e:
                log.info("%s 확장 목표 블록 탐색 실패(다음 사이클): %s", self.chain, e)
                return None
        tblk = tb[1]
        need = {w: self._cov_block(w, tblk) for w in self.wallets if isinstance(self.cursor.get(w), int)}
        need = {w: c for w, c in need.items() if c > tblk + 1}
        if not need:
            return None
        job = {"v": 2, "kind": "extend", "id": int(time.time() * 1000), "wallets": sorted(need), "since": int(tblk),
               "safe": int(max(need.values())), "phase": "collect", "spool_off": 0, "rows": 0, "emit_i": 0,
               "t0": int(time.time()), "streams": {}, "target_ts": int(target)}
        for w, c in need.items():
            for ep, _hk in self.BF2_EPS:
                job["streams"][f"{w}|{ep}"] = {"npp": None, "done": False, "pages": 0, "oldest": None, "seek": int(c)}
        self.cursor["_bfjob"] = job
        self._bf2_persist()
        log.info("★%s 과거 창 확장 잡: 지갑 %d, 블록 %d → 지갑별 커버 하한(최대 %d) — 목표 %s★", self.chain, len(need),
                 tblk, job["safe"], time.strftime("%Y-%m-%d", time.gmtime(target)))
        return job

    @staticmethod
    def _bf2_int_deferred(job: dict, key: str) -> bool:
        return bool(job.get("int_lag")) and job.get("kind") != "extend" and key.endswith("|internal-transactions")

    def _bf2_frac(self, job: dict) -> float:
        tot = 0.0
        for key9, st in job["streams"].items():
            top = int(st.get("seek") if st.get("seek") is not None else job["safe"])
            span = max(1, top - job["since"])
            if st.get("done") or self._bf2_int_deferred(job, key9):
                tot += 1.0
            elif st.get("oldest") is not None:
                tot += min(1.0, max(0.0, (top - int(st["oldest"])) / span))
        return tot / max(1, len(job["streams"]))

    def _bf2_collect(self, job: dict, deadline: float) -> bool:
        path = self._bf2_spool_path(job)
        if os.path.exists(path) and os.path.getsize(path) > int(job["spool_off"]):
            with open(path, "r+b") as f:
                f.truncate(int(job["spool_off"]))
        errs = {}
        while time.time() < deadline:
            todo = [k for k, st in job["streams"].items() if not st.get("done") and not self._bf2_int_deferred(job, k)]
            if not todo:
                return True
            progressed = False
            for key in todo:
                if time.time() >= deadline:
                    break
                st = job["streams"][key]
                w, ep = key.split("|", 1)
                hk = dict(self.BF2_EPS)[ep]
                url = f"{self.base}/api/v2/addresses/{w}/{ep}"
                npp0 = st.get("npp")
                if not isinstance(npp0, dict) and st.get("seek") is not None and int(st.get("pages", 0)) == 0:
                    npp0 = {"block_number": int(st["seek"]) + 1, "index": 0}
                    if ep == "internal-transactions":
                        npp0["transaction_index"] = 0
                if isinstance(npp0, dict):
                    url += "?" + urllib.parse.urlencode(npp0)
                try:
                    d = http_json(url, prio="bg", deadline=deadline)
                except bf_engine.NetError as e:
                    errs[e.kind] = errs.get(e.kind, 0) + 1
                    st["errs"] = int(st.get("errs", 0)) + 1
                    if e.kind in ("circuit", "budget", "quota"):
                        log.info("%s v2 수집 보류(%s) — 다음 사이클 같은 페이지부터", self.chain, str(e)[:100])
                        self.progress.update(f"{self.chain}:job", errors=errs, note=str(e)[:120])
                        return False
                    log.warning("%s v2 %s %s 페이지 실패(p%d, 누계 %d) — 체크포인트 유지: %s", self.chain, w[:10],
                                ep, int(st["pages"]), int(st["errs"]), str(e)[:120])
                    continue
                if not isinstance(d, dict) or not isinstance(d.get("items"), list):
                    errs["payload"] = errs.get("payload", 0) + 1
                    log.warning("%s v2 %s %s 응답 형식 오류 — 체크포인트 유지", self.chain, w[:10], ep)
                    continue
                rows, oldest = [], None
                for it in d["items"]:
                    if not isinstance(it, dict):
                        continue
                    h = it.get(hk)
                    if not isinstance(h, str) or not h:
                        continue
                    raw_blk = it.get("block_number")
                    if raw_blk is None:
                        raw_blk = it.get("block")
                    blk = None
                    if raw_blk is not None:
                        try:
                            blk = int(raw_blk)
                        except (TypeError, ValueError):
                            blk = None
                    if blk is not None:
                        oldest = blk if oldest is None else min(oldest, blk)
                        if not (job["since"] < blk <= job["safe"]):
                            continue
                    rows.append({"k": key, "h": h.lower(), "b": blk, "it": it})
                npp = d.get("next_page_params")
                if oldest is None and isinstance(npp, dict) and npp.get("block_number") is not None:
                    try:
                        oldest = int(npp["block_number"])
                    except (TypeError, ValueError):
                        pass
                if npp is not None and not isinstance(npp, dict):
                    log.warning("%s v2 %s %s next_page_params 형식 오류 — 체크포인트 유지", self.chain, w[:10], ep)
                    continue
                if rows:
                    with open(path, "ab") as f:
                        f.write(b"".join((json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
                                         .encode("utf-8") for r in rows))
                        f.flush()
                        os.fsync(f.fileno())
                        job["spool_off"] = f.tell()
                    job["rows"] = int(job["rows"]) + len(rows)
                st["pages"] = int(st["pages"]) + 1
                if oldest is not None:
                    st["oldest"] = oldest
                if (oldest is not None and oldest <= job["since"]) or not npp:
                    st["done"], st["npp"] = True, None
                else:
                    st["npp"] = npp
                mir = self.cursor.get("_bf:" + w)
                if isinstance(mir, dict):
                    mir["pages"] = int(mir.get("pages", 0)) + 1
                common.atomic_write_json(self.cursor_path, self.cursor)
                progressed = True
                self.progress.update(f"{self.chain}:job", phase="collect" if job.get("kind") != "extend" else "extend",
                                     unit="frac", since_block=job["since"], safe_block=job["safe"],
                                     done=round(self._bf2_frac(job), 4), total=1.0,
                                     pages=sum(int(s["pages"]) for s in job["streams"].values()),
                                     rows=int(job["rows"]), wallets=len(job["wallets"]), errors=errs or None)
                errs = {}
            if not progressed:
                time.sleep(2.0)
        return not [k for k, st in job["streams"].items() if not st.get("done") and not self._bf2_int_deferred(job, k)]

    @staticmethod
    def _bf2_tx_ok(tx: dict) -> bool:
        try:
            int(tx["block_number"])
            int(tx["value"] or 0)
            fee = tx["fee"]
            if not isinstance(fee, dict) or fee.get("value") is None:
                return False
            int(fee["value"])
        except (KeyError, TypeError, ValueError):
            return False
        return tx.get("status") in ("ok", "error") and tx.get("is_pending_update") is not True \
            and tsfix.ts_valid(tx.get("timestamp"))

    def _bf2_groups(self, job: dict):
        groups = {}
        path = self._bf2_spool_path(job)
        if not os.path.exists(path):
            return groups
        with open(path, "rb") as f:
            data = f.read(int(job["spool_off"]))
        for line in data.splitlines():
            if not line.strip():
                continue
            r = json.loads(line.decode("utf-8"))
            h, it, ep = r["h"], r["it"], r["k"].split("|", 1)[1]
            g = groups.setdefault(h, {"tx": None, "tt": {}, "it": {}, "b": None, "nob": False})
            g.setdefault("ws", set()).add(str(r["k"]).split("|", 1)[0].lower())
            if r.get("b") is None:
                g["nob"] = True
            elif g["b"] is None:
                g["b"] = int(r["b"])
            if ep == "transactions":
                if g["tx"] is None:
                    g["tx"] = it
            elif ep == "token-transfers":
                k = (it.get("log_index"), it.get("block_hash") or it.get("block_number"))
                if k[0] is None:
                    k = json.dumps(it, sort_keys=True)
                g["tt"].setdefault(json.dumps(k, sort_keys=True, default=str), it)
            else:
                def _a(x):
                    return (x.get("hash") if isinstance(x, dict) else x) or ""
                k = (it.get("index"), it.get("block_number"), _a(it.get("from")).lower(), _a(it.get("to")).lower(),
                     str(it.get("value")))
                g["it"].setdefault(json.dumps(k, default=str), it)
        return groups

    def _bf2_snapshot(self, h: str, g: dict):
        tts = list(g["tt"].values())
        its = list(g["it"].values())
        if g["tx"] is not None:
            tx = dict(g["tx"])
            if not self._bf2_tx_ok(tx):
                return None
        else:
            if its:
                return None
            if not tts:
                return None
            src = tts[0]
            if not tsfix.ts_valid(src.get("timestamp")):
                return None
            tx = {"hash": src.get("transaction_hash") or h, "from": src.get("from"), "to": src.get("to"),
                  "value": "0", "fee": {"value": "0"}, "status": "ok",
                  "raw_input": "0x01",
                  "timestamp": src.get("timestamp"), "block_number": int(src.get("block_number")),
                  "block_hash": src.get("block_hash"), "synth": "bs_list"}
        return {"tx": tx, "token_transfers": tts, "internal": its, "src": "bs_list"}

    def _bf2_emit(self, job: dict, head: int, deadline: float) -> bool:
        groups = self._bf2_groups(job)
        order = sorted(groups, key=lambda x: (groups[x]["b"] if groups[x]["b"] is not None else -1, x))
        n = len(order)
        i = int(job.get("emit_i", 0))
        since0, safe0 = int(job["since"]), int(job["safe"])
        n_detail = n_list = 0
        since_flush = 0
        other_pending = any(w not in job["wallets"] and not isinstance(self.cursor.get(w), int) for w in self.wallets)
        try:
            while i < n:
                if time.time() >= deadline:
                    return False
                h = order[i]
                g = groups[h]
                ws9 = sorted(g.get("ws") or ()) or list(job["wallets"])
                addr_tier.tier_mark_if_live(self, h, ws9)
                if h in self.emitted or h in self.pending_detail:
                    i += 1
                    continue
                snap = None
                b9 = g["b"] if g["b"] is not None else int(job.get("safe") or 0)
                behind_pending = any(w not in job["wallets"] and isinstance(self.cursor.get(w), int) and int(self.cursor[w]) < b9
                                     for w in self.wallets)
                need_detail = g["nob"] or (h in self._prev_emitted) or other_pending or behind_pending
                if not need_detail:
                    snap = self._bf2_snapshot(h, g)
                    need_detail = snap is None
                if need_detail:
                    try:
                        snap = self.fetch_detail(h)
                        n_detail += 1
                    except Exception as e:
                        if g["b"] is None:
                            nf = job.setdefault("nob_fail", {})
                            nf[h] = int(nf.get(h, 0)) + 1
                            if nf[h] < 3:
                                log.warning("%s v2 %s 블록 미상·상세 실패(%d) — 잡 보류(다음 사이클): %s", self.chain,
                                            h[:12], nf[h], str(e)[:100])
                                return False
                            log.warning("%s v2 %s 블록 미상 항목 3회 상세 실패 — 건너뜀(미채굴 추정)", self.chain, h[:12])
                            i += 1
                            job["emit_i"] = i
                            continue
                        log.warning("%s v2 detail %s 실패 → pending 큐: %s", self.chain, h[:12], str(e)[:100])
                        addr_tier.tier_mark(self, h, ws9)
                        self.pending_detail[h] = 0
                        i += 1
                        job["emit_i"] = i
                        continue
                else:
                    n_list += 1
                try:
                    blk = int(snap["tx"]["block_number"])
                except (KeyError, TypeError, ValueError):
                    addr_tier.tier_mark(self, h, ws9)
                    self.pending_detail[h] = 0
                    i += 1
                    continue
                part_int = (not need_detail and job.get("kind") != "extend")
                if job.get("int_lag") and (not (snap.get("internal") or []) or part_int) and not (h in self._prev_emitted or other_pending or behind_pending):
                    snap = self._int_mark(snap)
                if since0 < blk <= safe0:
                    self.emit(h, snap, head)
                    self.emitted.add(h)
                    since_flush += 1
                i += 1
                job["emit_i"] = i
                if since_flush >= self.BF2_FLUSH_EMITS:
                    since_flush = 0
                    self._bf2_persist()
                    self.progress.update(f"{self.chain}:job", phase="emit", unit="tx", done=i, total=n)
        finally:
            job["emit_i"] = i
            self._bf2_persist()
            self.progress.update(f"{self.chain}:job", phase="emit", unit="tx", done=i, total=n)
            if n_detail or n_list:
                log.info("%s v2 방출 %d/%d (리스트 합성 %d · 상세 %d)", self.chain, i, n, n_list, n_detail)
        return True

    def _bf2_step(self, first_ws: list, head: int, safe_now: int) -> bool:
        deadline = time.time() + self.bf2_budget
        self._bf2_persist()
        job = self.cursor.get("_bfjob")
        if not isinstance(job, dict) or job.get("v") != 2:
            job = self._bf2_new_job(first_ws, safe_now)
        if getattr(self, "_int_lag_now", False) and not job.get("int_lag"):
            job["int_lag"] = True
            self._bf2_persist()
        if job["phase"] == "collect":
            if not self._bf2_collect(job, deadline):
                self._bf2_persist()
                fr = self._bf2_frac(job)
                log.info("%s v2 수집 %.0f%% (페이지 %d, 행 %d) — 다음 사이클 계속", self.chain, fr * 100,
                         sum(int(s["pages"]) for s in job["streams"].values()), int(job["rows"]))
                return False
            job["phase"] = "emit"
            self._bf2_persist()
            log.info("%s v2 수집 완주 (페이지 %d, 행 %d, %.0f초) — 방출 단계", self.chain,
                     sum(int(s["pages"]) for s in job["streams"].values()), int(job["rows"]),
                     time.time() - int(job["t0"]))
        if not self._bf2_emit(job, head, deadline):
            return False
        if job.get("int_lag"):
            self._int_pending_add(job)
        for w in job["wallets"]:
            if job.get("kind") == "extend":
                self.cursor["_cov:" + w] = int(job["since"])
                continue
            self.cursor[w] = max(int(self.cursor.get(w, 0) or 0), int(job["safe"]))
            self.cursor["_cov:" + w] = int(job["since"])
            self.cursor.pop("_bf:" + w, None)
        self.cursor.pop("_bfjob", None)
        self._bf2_persist()
        try:
            os.remove(self._bf2_spool_path(job))
        except OSError:
            pass
        took = time.time() - int(job["t0"])
        log.info("★%s 백필 v2 완주: 지갑 %d, 커서 %d, %.1f분★", self.chain, len(job["wallets"]), job["safe"],
                 took / 60)
        self.progress.finish(f"{self.chain}:job", note=f"완주 {len(job['wallets'])}지갑 {took / 60:.1f}분")
        return True

    INT_EMPTY_RETRY = 5

    @staticmethod
    def _int_mark(snap: dict) -> dict:
        s = dict(snap)
        tx = dict(s.get("tx") or {})
        if tx.get("synth") != "rpc":
            tx["synth_was"] = tx.get("synth")
        tx["synth"] = "rpc"
        s["tx"] = tx
        s["int_pending"] = True
        return s

    def _int_pending_add(self, job: dict):
        m = self.cursor.get("_ext_internal_pending")
        if not isinstance(m, dict):
            m = {"v": 1, "ranges": [], "hashes": [], "emit_i": 0, "created": int(time.time())}
        lo = int(job["since"])
        hi_max = lo
        for w in job["wallets"]:
            st = job["streams"].get(f"{w}|transactions") or {}
            hi = int(st.get("seek") if st.get("seek") is not None else job["safe"])
            if hi <= lo:
                continue
            hi_max = max(hi_max, hi)
            m["ranges"].append({"wallet": w, "from_block": lo, "to_block": hi, "since": job.get("target_ts"),
                                "job": job.get("id"), "npp": None, "done": False, "pages": 0})
        if job.get("target_ts"):
            m["from_ts"] = min(int(m.get("from_ts") or job["target_ts"]), int(job["target_ts"]))
        else:
            f9 = self._int_est_ts(lo)
            if f9:
                m["from_ts"] = min(int(m.get("from_ts") or f9), f9)
        try:
            hts = self._block_ts(hi_max)
            m["to_ts"] = max(int(m.get("to_ts") or 0), int(hts))
        except Exception as e:
            log.info("%s internal 대기 구간 끝 시각 미확보(표시만 영향): %s", self.chain, e)
        m["ratio"] = getattr(self, "_idx_ratio", None)
        self.cursor["_ext_internal_pending"] = m
        log.warning("★%s %s 완료(tx·토큰) — internal(내부 ETH 이동)은 탐색기 색인 미완(%s)이라 블록 %d → %d 를 "
                    "'나중에 채우기'로 표시(색인 완료 시 자동 재훑기)★", self.chain,
                    "과거 창 확장" if job.get("kind") == "extend" else "새 지갑 첫 백필", m.get("ratio"), lo, hi_max)

    def _int_est_ts(self, blk: int):
        hts, hb = getattr(self, "_head_ts", None), getattr(self, "_max_head", 0)
        if not hts or not hb:
            return None
        bsec = getattr(self, "_hb_bsec", None) or (86400.0 / max(1, self.bpd))
        return int(hts - max(0, hb - int(blk)) * bsec)

    def _int_head_pending(self, w: str, lo: int, hi: int):
        if hi <= lo:
            return
        m = self.cursor.get("_ext_internal_pending")
        if not isinstance(m, dict):
            m = {"v": 1, "ranges": [], "hashes": [], "emit_i": 0, "created": int(time.time())}
            self.cursor["_ext_internal_pending"] = m
        rs = m.setdefault("ranges", [])
        for r in reversed(rs):
            if (isinstance(r, dict) and r.get("wallet") == w and r.get("kind") == "head" and not r.get("done")
                    and r.get("npp") is None and not int(r.get("pages", 0) or 0)
                    and int(r["from_block"]) <= lo <= int(r["to_block"])):
                r["to_block"] = max(int(r["to_block"]), int(hi))
                break
        else:
            rs.append({"wallet": w, "from_block": int(lo), "to_block": int(hi), "kind": "head", "since": None, "job": None,
                       "npp": None, "done": False, "pages": 0})
            log.info("%s %s 증분 발견(tx·토큰) 블록 %d → %d — internal 은 '나중에 채우기' 표식(색인 %s)", self.chain, w[:10], lo, hi,
                     getattr(self, "_idx_ratio", None))
        f9, t9 = self._int_est_ts(lo), self._int_est_ts(hi)
        if f9:
            m["from_ts"] = min(int(m.get("from_ts") or f9), f9)
        if t9:
            m["to_ts"] = max(int(m.get("to_ts") or 0), t9)
        m["ratio"] = getattr(self, "_idx_ratio", None)
        m.pop("started", None)

    def _int_rescan_step(self, head: int, deadline: float) -> bool:
        m = self.cursor.get("_ext_internal_pending")
        if not isinstance(m, dict):
            return True
        self._bf2_persist()
        ranges = [r for r in (m.get("ranges") or []) if isinstance(r, dict)]
        hashes = m.setdefault("hashes", [])
        seen = set(hashes)
        if not m.get("started"):
            m["started"] = int(time.time())
            log.info("★%s 탐색기 internal 색인 완료 — internal 늦은 채움 재훑기 시작(구간 %d: 과거 창·첫 백필·증분)★", self.chain, len(ranges))
        wl = set(self.wallets)
        for r in ranges:
            while not r.get("done"):
                if r.get("wallet") not in wl:
                    r["done"], r["npp"] = True, None
                    break
                if time.time() >= deadline:
                    common.atomic_write_json(self.cursor_path, self.cursor)
                    return False
                w, lo, hi = r["wallet"], int(r["from_block"]), int(r["to_block"])
                npp = r.get("npp") if isinstance(r.get("npp"), dict) else \
                    {"block_number": hi + 1, "index": 0, "transaction_index": 0}
                url = f"{self.base}/api/v2/addresses/{w}/internal-transactions?" + urllib.parse.urlencode(npp)
                try:
                    d = http_json(url, prio="bg", deadline=deadline)
                except bf_engine.NetError as e:
                    log.info("%s internal 재훑기 %s 보류(다음 사이클 같은 페이지부터): %s", self.chain, w[:10], str(e)[:120])
                    common.atomic_write_json(self.cursor_path, self.cursor)
                    return False
                if not isinstance(d, dict) or not isinstance(d.get("items"), list) or \
                        (d.get("next_page_params") is not None and not isinstance(d.get("next_page_params"), dict)):
                    log.warning("%s internal 재훑기 %s 응답 형식 오류 — 체크포인트 유지", self.chain, w[:10])
                    common.atomic_write_json(self.cursor_path, self.cursor)
                    return False
                oldest = None
                for it in d["items"]:
                    if not isinstance(it, dict) or not isinstance(it.get("transaction_hash"), str):
                        continue
                    blk = it.get("block_number", it.get("block"))
                    try:
                        blk = int(blk) if blk is not None else None
                    except (TypeError, ValueError):
                        blk = None
                    if blk is not None:
                        oldest = blk if oldest is None else min(oldest, blk)
                        if not (lo < blk <= hi):
                            continue
                    h = it["transaction_hash"].lower()
                    if h not in seen:
                        seen.add(h)
                        hashes.append(h)
                    fa, ta = it.get("from"), it.get("to")
                    k9 = json.dumps((it.get("index"), it.get("block_number"),
                                     str((fa.get("hash") if isinstance(fa, dict) else fa) or "").lower(),
                                     str((ta.get("hash") if isinstance(ta, dict) else ta) or "").lower(), str(it.get("value"))), default=str)
                    m.setdefault("items", {}).setdefault(h, {}).setdefault(k9, it)
                nxt = d.get("next_page_params")
                if oldest is None and isinstance(nxt, dict) and nxt.get("block_number") is not None:
                    try:
                        oldest = int(nxt["block_number"])
                    except (TypeError, ValueError):
                        pass
                r["pages"] = int(r.get("pages", 0)) + 1
                r["read_at"] = int(time.time())
                if (oldest is not None and oldest <= lo) or not nxt:
                    if not self._idx_recheck():
                        log.info("%s internal 재훑기 %s 완료 표시 보류 — 색인 재확인 실패(다음 사이클 같은 페이지부터)", self.chain, w[:10])
                        common.atomic_write_json(self.cursor_path, self.cursor)
                        return False
                    r["done"], r["npp"] = True, None
                    r["done_at"] = int(time.time())
                else:
                    r["npp"] = nxt
                common.atomic_write_json(self.cursor_path, self.cursor)
        i = int(m.get("emit_i", 0))
        n_full = n_retry = 0
        span = [(int(r["from_block"]), int(r["to_block"])) for r in ranges]
        try:
            while i < len(hashes):
                if time.time() >= deadline:
                    return False
                r9 = self._int_emit_one(hashes[i], m, span, head)
                if r9 == "wait":
                    return False
                if r9 == "fail":
                    if hashes[i] not in m.setdefault("retry", []):
                        m["retry"].append(hashes[i])
                    n_retry += 1
                elif r9 == "ok":
                    n_full += 1
                    if n_full % self.BF2_FLUSH_EMITS == 0:
                        m["emit_i"] = i + 1
                        self._bf2_persist()
                    time.sleep(0.12)
                i += 1
                m["emit_i"] = i
            left = []
            for h in list(m.get("retry") or []):
                if time.time() >= deadline:
                    left.append(h)
                    continue
                r9 = self._int_emit_one(h, m, span, head)
                if r9 in ("fail", "wait"):
                    left.append(h)
                elif r9 == "ok":
                    n_full += 1
            m["retry"] = left
            if left:
                return False
        finally:
            m["emit_i"] = i
            self._bf2_persist()
            if n_full or n_retry:
                log.info("%s internal 재훑기 방출 %d/%d (완전 상세 %d · 상세 실패 재시도 대기 %d)", self.chain, i, len(hashes), n_full,
                         len(m.get("retry") or []))
        if not self._idx_recheck():
            log.info("%s internal 늦은 채움 마무리 보류 — 색인 재확인 실패(다음 사이클)", self.chain)
            self._bf2_persist()
            return False
        self.cursor.pop("_ext_internal_pending", None)
        self.cursor.pop("_int_lag_since", None)
        self._bf2_persist()
        log.info("★%s internal 늦은 채움 완료 — tx %d건 재확인, 표식 제거★", self.chain, len(hashes))
        return True

    def _pending_fail(self, h: str, err, snap=None) -> bool:
        snap = err if snap is None else snap
        n9 = self.synth_fail_count(self.pending_detail, h, err)
        if n9 is None:
            log.debug("pending %s 보류(게이트·장부 거절 — 횟수 안 셈): %s", h[:12], str(err)[:120])
            return False
        if n9 > 200:
            common.append_durable_jsonl(
                os.path.join(common.STATE_DIR, "pending_poison.jsonl"),
                {"ts": int(time.time()), "chain": self.chain,
                 "txhash": h, "err": str(snap)[:200]})
            del self.pending_detail[h]
            log.error("★pending %s %d회 초과 — 포이즌 격리(pending_poison.jsonl)★",
                      h[:12], 200)
            return True
        log.warning("pending detail %s 재시도 실패(%d회): %s",
                    h[:12], n9, snap)
        return False

    def _int_emit_one(self, h: str, m: dict, span: list, head: int) -> str:
        rows9 = list(((m.get("items") or {}).get(h) or {}).values())

        def poison(src, err=None, n=None):
            common.append_durable_jsonl(os.path.join(common.STATE_DIR, "pending_poison.jsonl"),
                                        {"ts": int(time.time()), "chain": self.chain, "txhash": h, "src": src, "n": n,
                                         "err": (common.safe_err(err)[:200] if err else None), "internal": rows9})
        try:
            snap = self.fetch_detail(h)
            blk = int(snap["tx"]["block_number"])
        except Exception as e:
            rt = m.setdefault("detail_retry", {})
            rt[h] = int(rt.get(h, 0)) + 1
            if rt[h] > self.ENRICH_FAIL_MAX:
                log.error("★%s internal 재훑기 상세 %s %d회 실패 — 격리(pending_poison.jsonl, 목록 행 보존)★", self.chain, h[:12], rt[h])
                poison("int_rescan_detail", e, rt[h])
                return "skip"
            log.warning("%s internal 재훑기 상세 %s 실패(%d회) — 표식에 남겨 다음 사이클 재시도: %s", self.chain, h[:12], rt[h], str(e)[:100])
            return "fail"
        if not any(a < blk <= b for a, b in span):
            return "skip"
        if not (snap.get("internal") or []):
            rt = m.setdefault("empty_retry", {})
            rt[h] = int(rt.get(h, 0)) + 1
            if rt[h] < self.INT_EMPTY_RETRY:
                log.info("%s internal 재훑기 %s — 목록엔 있는데 상세 internal 이 비어 있음(%d회) — 다음 사이클 재시도",
                         self.chain, h[:12], rt[h])
                return "wait"
            if not rows9:
                log.error("★%s internal 재훑기 %s — 상세 internal 이 %d회 비었고 목록 행도 없음: 방출 보류·격리(pending_poison.jsonl)★",
                          self.chain, h[:12], rt[h])
                poison("int_rescan_empty", n=rt[h])
                return "skip"
            log.warning("%s internal 재훑기 %s — 상세 internal 이 %d회 비어 있음 → 주소 목록 internal %d행으로 방출",
                        self.chain, h[:12], rt[h], len(rows9))
            snap = dict(snap, internal=rows9, internal_note="bs_addr_list")
        self.emit(h, snap, head, repair="int_fill")
        self.emitted.add(h)
        for k9 in ("empty_retry", "detail_retry", "items"):
            (m.get(k9) or {}).pop(h, None)
        self.enrich.pop(h, None)
        self.pending_detail.pop(h, None)
        return "ok"

    def _fetch_all_items(self, path: str):
        base_url = f"{self.base}{path}"
        url = base_url
        out = []
        seen = set()
        while True:
            d = http_json(url, breaker_5xx=False)
            if not isinstance(d, dict) or not isinstance(d.get("items"), list):
                raise RuntimeError(f"상세 목록 응답 형식 오류: {path}")
            out.extend(x for x in d["items"] if isinstance(x, dict))
            npp = d.get("next_page_params")
            if not npp:
                return out
            if not isinstance(npp, dict):
                raise RuntimeError(f"상세 페이지 커서 형식 오류: {path}")
            marker = json.dumps(npp, sort_keys=True, separators=(",", ":"))
            if marker in seen:
                raise RuntimeError(f"상세 페이지 커서 반복: {path}")
            seen.add(marker)
            url = base_url + "?" + urllib.parse.urlencode(npp)

    def fetch_detail(self, txhash: str, accept_pending: bool = False):
        tx = http_json(f"{self.base}/api/v2/transactions/{txhash}", breaker_5xx=False)
        if not isinstance(tx, dict) or str(tx.get("hash") or "").lower() != txhash.lower():
            raise RuntimeError(f"tx 상세 응답 불일치: {txhash}")
        try:
            int(tx["block_number"])
            int(tx["value"] or 0)
            fee = tx["fee"]
            if not isinstance(fee, dict) or fee.get("value") is None:
                raise ValueError("fee 형식/누락")
            int(fee["value"])
        except (KeyError, TypeError, ValueError) as e:
            raise RuntimeError(f"tx 상세 필수 수치 오류: {txhash}") from e
        if tx.get("status") not in ("ok", "error"):
            raise RuntimeError(f"tx status 미확정: {txhash}")
        if tx.get("is_pending_update") is True and not accept_pending:
            raise RuntimeError(f"tx 상세가 아직 갱신 중: {txhash}")
        if not tsfix.ts_valid(tx.get("timestamp")):
            try:
                tx["timestamp"] = tsfix.block_ts(self, int(tx["block_number"]))
            except Exception as e:
                raise RuntimeError(f"tx 상세 시각 없음 · 블록 시각 조회 실패: {txhash}") from e
        tt = self._fetch_all_items(f"/api/v2/transactions/{txhash}/token-transfers")
        it = self._fetch_all_items(f"/api/v2/transactions/{txhash}/internal-transactions")
        return {"tx": tx, "token_transfers": tt, "internal": it}

    def emit(self, txhash: str, snapshot: dict, head: int, repair: str = None):
        rec = {
            "v": 1, "kind": "evm_tx", "chain": self.chain, "txhash": txhash,
            "snapshot": snapshot,
            "wallets": self.wallets,
            "observed_head": head, "ts": int(time.time()),
        }
        if repair:
            rec["repair"] = repair
        self.writer.append(rec)
        tb9 = getattr(self, "_tier", None)
        if tb9 is not None and not repair:
            tb9.note_sent(addr_tier.sent_from(snapshot), addr_tier.snap_ts(snapshot))

    def _detail_probe_ok(self) -> bool:
        cand = [h for h in self.emitted if h not in self.enrich]
        if not cand:
            return False
        h9 = max(cand)
        try:
            snap = self.fetch_detail(h9, accept_pending=True)
            return isinstance(snap, dict) and bool(snap.get("tx"))
        except Exception as e:
            log.info("enrich 5xx 판정용 상세 프로브 실패 → 포기 보류: %s", str(e)[:120])
            return False

    ENRICH_BATCH = 5
    ENRICH_FAIL_MAX = 200
    ENRICH_5XX_MAX = 5

    def _int_window_hold(self, snap: dict) -> bool:
        m = self.cursor.get("_ext_internal_pending")
        if not isinstance(m, dict) or (snap.get("internal") or []):
            return False
        try:
            blk = int((snap.get("tx") or {}).get("block_number"))
        except (TypeError, ValueError):
            return True
        return any(int(r["from_block"]) < blk <= int(r["to_block"]) for r in (m.get("ranges") or []) if isinstance(r, dict))

    def _enrich_pass(self, head: int, healthy: bool = False):
        probe = None
        for h in list(self.enrich)[:self.ENRICH_BATCH]:
            try:
                snap = self.fetch_detail(h)
            except Exception as e:
                self.enrich[h] = int(self.enrich.get(h, 0)) + 1
                giveup, src9 = self.enrich[h] > self.ENRICH_FAIL_MAX, "enrich_giveup"
                if _is_http_5xx(e):
                    if healthy:
                        if probe is None:
                            probe = self._detail_probe_ok()
                        if probe:
                            self._enrich_5xx[h] = self._enrich_5xx.get(h, 0) + 1
                            if self._enrich_5xx[h] >= self.ENRICH_5XX_MAX:
                                giveup, src9 = True, "enrich_giveup_5xx"
                else:
                    self._enrich_5xx.pop(h, None)
                if giveup:
                    n9, n5xx9 = self.enrich[h], self._enrich_5xx.get(h, 0)
                    common.append_durable_jsonl(
                        os.path.join(common.STATE_DIR, "pending_poison.jsonl"),
                        {"ts": int(time.time()), "chain": self.chain, "txhash": h,
                         "src": src9, "n": n9, "n5xx": n5xx9, "err": common.safe_err(e)[:200]})
                    del self.enrich[h]
                    self._enrich_5xx.pop(h, None)
                    log.error("★enrich %s 포기(%s, 실패 누계 %d회·연속 5xx %d회) — rpc_basic 영구 확정"
                              "(잔차는 대사 흡수)★", h[:12], src9, n9, n5xx9)
                continue
            self._enrich_5xx.pop(h, None)
            if self._int_window_hold(snap):
                continue
            try:
                self.emit(h, snap, head)
                del self.enrich[h]
                log.info("★enrich %s 완전 상세 재방출 — core 승격 대상★", h[:12])
            except Exception as e:
                log.warning("enrich %s emit 실패(카운트 유지, 재시도): %s", h[:12], e)

    def cycle(self):
        tb = getattr(self, "_tier", None)
        rest_set = set()
        if tb is not None:
            addr_tier.tier_prune(self)
            addr_tier.evm_activity(self, tb)
            due9, rest9 = tb.due_list(self.wallets)
            rest_set = set(rest9)
            if not due9 and not self.pending_detail and not self.enrich and not isinstance(self.cursor.get("_bfjob"), dict) \
                    and not isinstance(self.cursor.get("_ext_internal_pending"), dict) and not self._ext_maybe_needed():
                addr_tier.idle_cycle(self, tb, "blockscout", urllib.parse.urlsplit(self.base).hostname)
                return
        head = self.head_block()
        safe = head - self.conf_depth
        all_ok = True
        tok_ok = True
        pend_deadline = time.time() + (300 if len(self.pending_detail) > 200 else 120)
        p_items = list(self.pending_detail.items())
        p_idx = 0
        while p_idx < len(p_items) and time.time() < pend_deadline:
            batch = p_items[p_idx:p_idx + 10]
            p_idx += len(batch)
            accepts = {h: cnt > 120 for h, cnt in batch}
            res_p = {}
            ex8 = ThreadPoolExecutor(max_workers=5)
            try:
                futs8 = {}
                direct8 = set()
                for h, cnt in batch:
                    if not accepts[h]:
                        futs8[ex8.submit(self._rpc_synth_detail, h)] = h
                        direct8.add(h)
                    else:
                        futs8[ex8.submit(self.fetch_detail, h, accepts[h])] = h
                for fu8 in futs8:
                    remain8 = max(0.05, pend_deadline - time.time())
                    try:
                        res_p[futs8[fu8]] = fu8.result(timeout=remain8)
                    except FutTimeout:
                        res_p[futs8[fu8]] = RuntimeError("pending 시간예산 초과 — 다음 사이클")
                    except Exception as e8:
                        res_p[futs8[fu8]] = e8
            finally:
                ex8.shutdown(wait=False, cancel_futures=True)
            for h, _ in batch:
                snap = res_p.get(h)
                if isinstance(snap, Exception) or snap is None:
                    fail9 = snap
                    if h not in direct8:
                        emitted_ok = False
                        try:
                            snap2 = self._rpc_synth_detail(h)
                            self.emit(h, snap2, head)
                            emitted_ok = True
                            self.emitted.add(h.lower())
                            del self.pending_detail[h]
                            self.enrich[h.lower()] = 0
                            log.info("pending %s RPC 합성 확정 (블록스카웃 상세 불능 대체)", h[:12])
                            continue
                        except Exception as e9r:
                            if emitted_ok:
                                log.warning("pending %s 합성 emit 후 정리 실패(카운트 유지): %s",
                                            h[:12], e9r)
                                continue
                            log.debug("rpc 합성 실패 %s: %s", h[:12], e9r)
                            fail9 = e9r
                    self._pending_fail(h, fail9, snap)
                    continue
                if accepts[h]:
                    log.warning("pending %s 120회 초과 — is_pending_update 수용 확정", h[:12])
                try:
                    self.emit(h, snap, head)
                    self.emitted.add(h.lower())
                    del self.pending_detail[h]
                    if not accepts[h]:
                        self.enrich[h.lower()] = 0
                except Exception as e:
                    log.warning("pending %s emit 실패(카운트 유지 %d): %s",
                                h[:12], self.pending_detail.get(h, 0), e)
        idx_state = self._indexing_state() if self.idx_guard else "ok"
        idx_known9 = idx_state
        if self.idx_guard and getattr(self, "_idx_unknown", None):
            idx_known9 = None
            idx_state = "blocks"
        idx_ok = idx_state == "ok"
        ext_idx_ok = idx_ok or (idx_state == "internal" and self.idx_guard_scope != "all")
        head_idx_ok = ext_idx_ok
        int_lag_now = self._int_lag_now = (not idx_ok) or not self._idx_stable()
        self._idx_note(idx_ok, idx_state, head_idx_ok)
        if idx_known9 == "internal":
            self.cursor["_ext_internal_lag"] = {"ts": int(time.time()), "ratio": getattr(self, "_idx_ratio", None)}
        elif idx_ok:
            self.cursor.pop("_ext_internal_lag", None)
        self._int_lag_track(idx_known9)
        ipm = self.cursor.get("_ext_internal_pending")
        if isinstance(ipm, dict):
            ipm["ratio"] = getattr(self, "_idx_ratio", None) if idx_state != "ok" else None
        if not idx_ok:
            all_ok = False
        if not idx_ok or isinstance(self.cursor.get("_ext_internal_pending"), dict):
            self.cursor.pop("_synced_at", None)
            _revoke_stamp_disk(self.cursor_path, tok=False)
        if getattr(self, "_idx_unknown", None) or not head_idx_ok:
            self.cursor.pop("_synced_tok_at", None)
            _revoke_stamp_disk(self.cursor_path, tok=True)
        first_ws = []
        for w in (self.wallets if head_idx_ok else []):
            first = w not in self.cursor
            since = int(self.cursor.get(w, 0))
            eff_since = max(0, since - self.rescan_overlap) if (self.rescan_overlap and
                                                                not first) else since
            if first:
                if not self.backfill and self.backfill_months <= 0:
                    self.cursor[w] = safe
                    log.info("%s 첫 가동 — 커서를 %d 로 초기화(등록 시점부터 추적)", w[:10], safe)
                    continue
                all_ok = tok_ok = False
                if self.bf_mode == "legacy":
                    if idx_ok and self._idx_stable():
                        self._first_sync_walk(w, head, safe)
                else:
                    first_ws.append(w)
                continue
            if w in rest_set:
                continue
            found = self.discover(w, eff_since, safe, skip_internal=int_lag_now)
            if found and tb is not None:
                tb.clear_empty(w, "rows")
            if found is None:
                all_ok = tok_ok = False
                _revoke_stamp_disk(self.cursor_path)
                self.fail_streak[w] = self.fail_streak.get(w, 0) + 1
                n9 = self.fail_streak[w]
                lv = bf_engine.LogDebounce.level(n9)
                if n9 in (20, 100):
                    log.error("★%s discovery %d회 연속 실패 — 이 지갑 추적이 멈춰 있음(커서 %d): %s",
                              w[:10], n9, since, getattr(self, "_disc_err", ""))
                elif lv:
                    getattr(log, lv)("%s discovery 실패 %d회 연속(커서 유지, 다음 사이클 재시도): %s", w[:10], n9,
                                     getattr(self, "_disc_err", ""))
                continue
            self.fail_streak[w] = 0
            ok = True
            safe_w = int(getattr(self, "_disc_safe", safe))
            ck_next = getattr(self, "_disc_ck_next", None)
            if ck_next:
                _revoke_stamp_disk(self.cursor_path)
            for h in sorted(found):
                addr_tier.tier_mark_if_live(self, h, [w])
                if h.lower() in self.emitted:
                    continue
                hinted_blk = found[h]
                try:
                    snap = self.fetch_detail(h)
                    detail_blk = int(snap["tx"]["block_number"])
                except Exception as e:
                    if hinted_blk is None:
                        log.warning("detail %s 블록 확인 실패 — 커서 유지: %s", h[:12], e)
                        ok = False
                        _revoke_stamp_disk(self.cursor_path)
                        break
                    log.warning("detail %s 실패 → pending 큐: %s", h[:12], e)
                    _revoke_stamp_disk(self.cursor_path)
                    addr_tier.tier_mark(self, h, [w])
                    self.pending_detail[h] = 0
                    continue
                if not (eff_since < detail_blk <= safe_w):
                    continue
                try:
                    self.emit(h, snap, head)
                    self.emitted.add(h.lower())
                except Exception as e:
                    log.error("inbox append 실패 — 커서 미전진: %s", e)
                    ok = False
                    _revoke_stamp_disk(self.cursor_path)
                    break
                time.sleep(0.12)
            if ok and ck_next:
                self.cursor["_disc:" + w] = ck_next
                all_ok = tok_ok = False
            elif ok:
                if int_lag_now:
                    self._int_head_pending(w, since, safe_w)
                self.cursor[w] = max(int(self.cursor.get(w, 0)), safe_w)
                self.cursor.pop("_disc:" + w, None)
                if tb is not None:
                    addr_tier.tier_partial(self, w, int(self.cursor[w]) < safe)
                    if (int(self.cursor[w]) >= safe and not getattr(self, "_idx_unknown", None)
                            and not addr_tier.tier_pending(self, w, enrich=False)):
                        tb.note_full(w, int(self.cursor[w]))
                if safe_w < safe:
                    all_ok = tok_ok = False
                    _revoke_stamp_disk(self.cursor_path)
            else:
                all_ok = tok_ok = False
                if tb is not None:
                    addr_tier.tier_partial(self, w, True)
        if not all_ok or self.pending_detail or self.enrich:
            self.cursor.pop("_synced_at", None)
        if not tok_ok or self.pending_detail:
            self.cursor.pop("_synced_tok_at", None)
        ext_job = isinstance(self.cursor.get("_bfjob"), dict) and self.cursor["_bfjob"].get("kind") == "extend"
        ext_job = ext_job and ext_idx_ok
        if first_ws or ext_job or (ext_idx_ok and self.bf_mode != "legacy" and self._maybe_extend(head, safe)):
            try:
                self._bf2_step(first_ws, head, safe)
            except Exception as e:
                log.error("%s v2 백필 스텝 예외(다음 사이클 재개): %s", self.chain, e)
                self._bf2_persist()
        if idx_ok and isinstance(self.cursor.get("_ext_internal_pending"), dict) and not self._idx_stable():
            s9 = self.cursor.get("_idx_ok_streak") if isinstance(self.cursor.get("_idx_ok_streak"), dict) else {}
            if time.time() - getattr(self, "_idx_wait_log", 0) >= 1800:
                self._idx_wait_log = time.time()
                log.info("%s 탐색기 색인 완료 관측 — internal 재훑기는 %d분 연속 완료 확인 뒤 시작(지금 %.0f분째)", self.chain,
                         self.IDX_STABLE_SEC // 60, (time.time() - int(s9.get("since") or time.time())) / 60)
        elif idx_ok and isinstance(self.cursor.get("_ext_internal_pending"), dict):
            try:
                self._int_rescan_step(head, time.time() + max(30.0, self.bf2_budget / 2))
            except Exception as e:
                log.error("%s internal 재훑기 예외(다음 사이클 재개): %s", self.chain, e)
                self._bf2_persist()
        if idx_ok and self._idx_stable():
            self._enrich_pass(head, healthy=all_ok)
        common.atomic_write_json(self.enrich_path, self.enrich)
        common.atomic_write_json(
            os.path.join(common.STATE_DIR, f"pending_detail_{self.chain}.json"), self.pending_detail)
        common.atomic_write_json(self.emitted_path, sorted(self.emitted))
        if all_ok and not self.pending_detail and not self.enrich and "_ext_internal_pending" not in self.cursor:
            self.cursor["_synced_at"] = int(time.time())
        else:
            self.cursor.pop("_synced_at", None)
        int_wait9 = idx_state == "internal" or isinstance(self.cursor.get("_ext_internal_pending"), dict)
        if tok_ok and head_idx_ok and int_wait9 and not self.pending_detail and not getattr(self, "_idx_unknown", None):
            self.cursor["_synced_tok_at"] = int(time.time())
        else:
            self.cursor.pop("_synced_tok_at", None)
        common.atomic_write_json(self.cursor_path, self.cursor)
        if tb is not None:
            addr_tier.evm_baselines(self, tb, [w for w in self.wallets if w not in rest_set])
            if head_idx_ok and not getattr(self, "_idx_unknown", None):
                addr_tier.evm_empty_probe(self, tb, self._bs_has_rows)
            tb.save()
        failed_ws = [w[:10] for w, n9 in self.fail_streak.items() if n9]
        job = self.cursor.get("_bfjob")
        ipm9 = self.cursor.get("_ext_internal_pending") if isinstance(self.cursor.get("_ext_internal_pending"), dict) else None
        int_fill9 = None
        if ipm9 and ipm9.get("ranges"):
            int_fill9 = {"state": "filling" if idx_ok else "waiting", "ratio": getattr(self, "_idx_ratio", None) if not idx_ok else None,
                         "ranges": len(ipm9["ranges"]), "from_ts": ipm9.get("from_ts"), "to_ts": ipm9.get("to_ts"),
                         "wallets": sorted({str(r.get("wallet")) for r in ipm9["ranges"] if isinstance(r, dict) and r.get("wallet")})}
        self._health_cycle("blockscout", head, safe, ok=head_idx_ok and not failed_ws,
                           err=RuntimeError("indexing-status 조회 실패(색인 상태 모름 — 발견 보류 · 커서 유지)" if getattr(self, "_idx_unknown", None)
                                            else "indexing-status 미완(발견 보류)") if not head_idx_ok else
                           RuntimeError(f"discovery 실패 지갑 {failed_ws}: {getattr(self, '_disc_err', '')}"),
                           current_source=urllib.parse.urlsplit(self.base).hostname, indexing_ok=idx_ok,
                           indexing_state=idx_state, internal_ratio=getattr(self, "_idx_ratio", None),
                           indexing_unknown=getattr(self, "_idx_unknown", None), int_fill=int_fill9,
                           wallets_failing=failed_ws, pending_detail=len(self.pending_detail), enrich=len(self.enrich),
                           backfill=({"phase": job.get("phase"), "wallets": len(job.get("wallets") or []),
                                      "rows": job.get("rows"), "emit_i": job.get("emit_i")}
                                     if isinstance(job, dict) else None))


class EtherscanKeyError(RuntimeError):
    pass


class EtherscanPaced(RuntimeError):
    pass


class EtherscanDailyLimit(EtherscanKeyError):
    pass


_ES_Q = {}
_ES_Q_LOCK = threading.Lock()
ES_Q_TTL = 900
_ES_WMEM = {}
ES_FAIL_ISOLATE_SEC = 1800


class EtherscanWatcher(RpcSynthMixin):

    ES_API = "https://api.etherscan.io/v2/api"
    PAGE = 1000
    ES_ROW_FLOOR = 1000

    def __init__(self, cfg: dict, chain: str, wallets: list, writer, chainid: int, key: str):
        self.chain = chain
        self.cid = chainid
        self.key = key
        self.wrapped_ca = str((cfg.get("wrapped_native") or {}).get(chain) or "").lower() or None
        self.cfg_rpcs = cfg["chains"][chain].get("rpcs")
        self.rpc_meta_path = os.path.join(common.STATE_DIR, f"rpc_token_meta_{chain}.json")
        self.rpc_meta = common.read_json(self.rpc_meta_path, {})
        self.conf_depth = int(cfg["chains"][chain].get("conf_depth", 12))
        self.backfill = bool(cfg.get("backfill_full_history"))
        self.backfill_months = float(cfg.get("backfill_months") or 0)
        self.bpd = int(cfg["chains"][chain].get("blocks_per_day", 7200))
        try:
            self.page = max(100, int(((cfg.get("etherscan") or {}).get("page_rows")) or self.PAGE))
        except (TypeError, ValueError):
            self.page = self.PAGE
        try:
            self.INT_LAG_SEC = max(60, int(((cfg.get("etherscan") or {}).get("int_lag_sec")) or EtherscanWatcher.INT_LAG_SEC))
        except (TypeError, ValueError):
            pass
        self.wallets = [w.lower() for w in wallets]
        self.wallet_since = bf_engine.wallet_since_map(cfg, chain)
        self.writer = writer
        self.cursor_path = os.path.join(common.STATE_DIR, f"cursor_evm_{chain}.json")
        self.cursor = common.read_json(self.cursor_path, {})
        if self.cursor.get("_rpc_v") is not None:
            rpc_handback(self, "etherscan")
        self.emitted_path = os.path.join(common.STATE_DIR, f"emitted_evm_{chain}.json")
        self.emitted = set(common.read_json(self.emitted_path, []))
        _prev_w = {k for k in self.cursor if not k.startswith("_")}
        if _prev_w and not set(self.wallets).issubset(_prev_w) and self.emitted:
            log.warning("%s 새 관점 지갑 감지 — emitted %d건 초기화(재방출 허용)", chain, len(self.emitted))
            self.emitted.clear()
        self.pending_detail = {}
        self.progress = bf_engine.progress("evm")
        self._tier = addr_tier.evm_book(self, cfg, "etherscan")

    ES_RETRY = 4
    INT_LAG_SEC = 21600

    def _es_get(self, params: dict):
        left = es_daily_left()
        if left > 0:
            raise EtherscanDailyLimit(f"etherscan 하루 한도 쉼 창 — {left / 60:.0f}분 뒤 재시도")
        k9 = getattr(self, "_es_kind", "head")
        if not bf_engine.es_budget_take("evm", kind=k9):
            if bf_engine.es_budget_why() == "pace":
                raise EtherscanPaced(f"이더스캔 하루 예산 페이싱({getattr(self, '_es_kind', 'head')}) — 잠시 쉬고 다음 주기에 이어 받음")
            used9, cap9 = bf_engine.es_budget_used()
            msg9 = f"로컬 하루 예산 도달 {used9}/{cap9} (공표 한도 80% 규칙) — day/limit"
            es_daily_trip(msg9)
            raise EtherscanDailyLimit(f"etherscan {msg9}")
        if k9 == "head":
            self._es_hspent = getattr(self, "_es_hspent", 0) + 1
        try:
            d = http_json(self.ES_API + "?" + urllib.parse.urlencode(params), retries=1)
        except bf_engine.NetError as e:
            if es_is_daily_limit(e):
                es_daily_trip(str(e))
                raise EtherscanDailyLimit(f"etherscan 하루 한도: {str(e)[:120]}") from e
            raise
        if isinstance(d, dict):
            res9 = d.get("result")
            if (isinstance(res9, str) and es_is_daily_limit(res9)) or \
                    (d.get("status") == "0" and es_is_daily_limit(d.get("message"))):
                es_daily_trip(res9 if isinstance(res9, str) else d.get("message"))
                raise EtherscanDailyLimit(f"etherscan 하루 한도: {str(res9)[:120]}")
        return d

    ES_NET_RETRY = 2

    def _es_get_retry(self, params: dict):
        for i in range(self.ES_NET_RETRY):
            try:
                return self._es_get(params)
            except bf_engine.NetError as e:
                if isinstance(e, bf_engine.CircuitOpen) or e.kind not in bf_engine.RETRYABLE or e.kind == "quota" \
                        or i + 1 >= self.ES_NET_RETRY:
                    raise
                wait = e.retry_after if (e.kind == "http429" and e.retry_after is not None) else bf_engine._backoff(i)
                time.sleep(min(float(wait), 20.0))

    def _es(self, params: dict):
        params = dict(params, chainid=self.cid, apikey=self.key)
        last = None
        for i in range(self.ES_RETRY):
            d = self._es_get_retry(params)
            if not isinstance(d, dict):
                raise RuntimeError("etherscan 응답 형식 오류")
            if str(d.get("status")) not in ("0", "1"):
                raise RuntimeError("etherscan 응답 상태 오류")
            if d.get("status") == "0" and d.get("message") not in ("No transactions found",
                                                                  "No records found"):
                res = d.get("result")
                if "api key" in str(res).lower():
                    raise EtherscanKeyError(f"etherscan 키 거부: {res}")
                low = str(res).lower()
                if res is None or "rate limit" in low or "max calls" in low or "timeout" in low \
                        or "busy" in low or "try again" in low:
                    last = RuntimeError(f"etherscan 오류: {res}")
                    bf_engine._stat("api.etherscan.io", "es_retry")
                    time.sleep(bf_engine._backoff(i, base=1.5, cap=12.0) + 0.5)
                    continue
                raise RuntimeError(f"etherscan 오류: {res}")
            if str(d.get("status")) == "0":
                return []
            return d.get("result")
        raise last if last else RuntimeError("etherscan 재시도 소진")

    def head_block(self) -> int:
        d = self._es_get_retry({"chainid": self.cid, "module": "proxy", "action": "eth_blockNumber",
                                "apikey": self.key})
        if not isinstance(d, dict) or not isinstance(d.get("result"), str) or not d["result"].startswith("0x"):
            res9 = (d or {}).get("result") if isinstance(d, dict) else d
            if "api key" in str(res9).lower():
                raise EtherscanKeyError(f"etherscan 키 거부: {res9}")
            raise RuntimeError(f"etherscan head 응답 오류: {str(res9)[:80]}")
        head = int(d["result"], 16)
        mx = getattr(self, "_max_head", 0)
        if mx and head < mx - max(64, self.conf_depth):
            raise bf_engine.NetError(f"etherscan 헤드 역행 {head} < 관측 최대 {mx}", "stale_head")
        self._max_head = max(mx, head)
        return head

    def window_start_block(self, safe_now: int, months: float, bpd: int) -> int:
        target = int(time.time() - months * 30 * 86400)
        try:
            r = self._es({"module": "block", "action": "getblocknobytime", "timestamp": target,
                          "closest": "before"})
            b = int(r)
            if 0 <= b <= safe_now:
                log.info("%s 백필 창 시작 = 블록 %d (이더스캔 getblocknobytime, bpd 가정치 대비 %+d블록)", self.chain,
                         b, b - max(0, safe_now - int(months * 30 * bpd)))
                return b
        except (EtherscanKeyError, EtherscanPaced):
            raise
        except Exception as e:
            log.warning("%s getblocknobytime 실패 → RPC 탐색: %s", self.chain, str(e)[:100])
        return RpcSynthMixin.window_start_block(self, safe_now, months, bpd)

    def _block_by_ts(self, ts: int) -> int:
        try:
            b = int(self._es({"module": "block", "action": "getblocknobytime", "timestamp": int(ts), "closest": "before"}))
            if b >= 0:
                return b
        except (EtherscanKeyError, EtherscanPaced):
            raise
        except Exception:
            pass
        return bf_engine.block_at_ts(self._block_ts, int(ts), 0, int(getattr(self, "_max_head", 0) or self.head_block()))

    def _ext_block_at(self, ts: int, head: int) -> int:
        try:
            return self._block_by_ts(ts)
        except EtherscanPaced as e:
            try:
                return bf_engine.block_at_ts(self._block_ts, int(ts), 0, int(head))
            except Exception as e9:
                bf_engine.es_pace_room("fill")
                raise EtherscanPaced(f"확장 목표 블록 — 이더스캔 몫 막힘 · RPC 탐색 실패({str(e9)[:80]}) — 옛 기록 수요만 등록") from e

    ES_EXT_SLICES = 4
    ES_EXT_WORKERS = 3

    def _es_extend(self, head: int):
        target = bf_engine.SINCE.target(self.chain)
        if not target:
            return
        self._es_kind = "aux"
        tb = getattr(self, "_ext_tb", None)
        if not tb or tb[0] != target:
            b9 = addr_tier._ext_tb_of(self, "etherscan", target)
            tb = self._ext_tb = (target, b9 if b9 is not None else self._ext_block_at(target, head))
        tblk = tb[1]
        need = {}
        hint = bf_engine.SINCE.covered_hint(self.chain)
        hb9 = getattr(self, "_ext_hint", None)
        if hint and (not hb9 or hb9[0] != hint):
            hb9 = self._ext_hint = (hint, self._ext_block_at(hint, head))
        hint_blk = hb9[1] if hint else None
        for w in self.wallets:
            if not isinstance(self.cursor.get(w), int):
                continue
            c = self.cursor.get("_cov:" + w)
            if not isinstance(c, int):
                c = min(hint_blk, int(self.cursor[w])) if hint_blk else int(self.cursor[w])
            if c > tblk + 1:
                need[w] = c
        if not need:
            return
        t0 = time.time()
        tasks = []
        _mg9 = lpdec.lp_managers(common.BASE_DIR).get(self.chain) or {}
        acts9 = ("txlist", "tokentx", "txlistinternal") + (("tokennfttx",) if _mg9 else ())
        for w, c in need.items():
            lo, hi = tblk + 1, c
            step = max(1, (hi - lo + 1) // self.ES_EXT_SLICES + 1)
            for a in range(lo, hi + 1, step):
                for act in acts9:
                    tasks.append((w, act, a, min(hi, a + step - 1)))
        room9 = bf_engine.es_pace_room("fill")
        if room9 < len(tasks) * 2:
            if time.time() - getattr(self, "_ext_room_log", 0) >= 1800:
                self._ext_room_log = time.time()
                log.info("%s 과거 창 확장 대기 — 하루 예산 페이싱(채우기 몫 %d < 필요 %d) · 몫이 차면 이어서", self.chain, max(0, room9), len(tasks) * 2)
            self.progress.update(f"{self.chain}:extend", phase="extend", unit="tasks", done=0, total=len(tasks),
                                 target=time.strftime("%Y-%m-%d", time.gmtime(target)), since_block=tblk, wallets=len(need), paced=True,
                                 paced_at=int(time.time()))
            return
        self._es_kind = "fill"
        res = {}
        self.progress.update(f"{self.chain}:extend", phase="extend", unit="tasks", done=0, total=len(tasks),
                             target=time.strftime("%Y-%m-%d", time.gmtime(target)), since_block=tblk, wallets=len(need), flush=True)
        from concurrent.futures import ThreadPoolExecutor as _TPE
        with _TPE(max_workers=self.ES_EXT_WORKERS) as ex9:
            futs = {ex9.submit(self._list_all, act, w, a, b): (w, act, a) for (w, act, a, b) in tasks}
            for fu, key in futs.items():
                try:
                    res[key] = fu.result()
                except EtherscanKeyError:
                    raise
                except EtherscanPaced as e:
                    res[key] = e
                except Exception as e:
                    res[key] = e
        errs = [k for k, v in res.items() if isinstance(v, Exception)]
        self.progress.update(f"{self.chain}:extend", phase="extend", unit="tasks", done=len(tasks) - len(errs),
                             total=len(tasks), target=time.strftime("%Y-%m-%d", time.gmtime(target)),
                             since_block=tblk, wallets=len(need), errors={"task_fail": len(errs)} if errs else None)
        if errs:
            log.info("%s 확장 조회 %d/%d 조각 실패 — 다음 사이클 재시도: %s", self.chain, len(errs), len(tasks),
                     str(res[errs[0]])[:120])
            return
        per_wallet = {}
        for w in need:
            parts = {act: [] for act in acts9}
            for (w2, act, a), rows in sorted(res.items(), key=lambda kv: kv[0][2]):
                if w2 == w:
                    parts[act].extend(rows)
            nft9 = [r9 for r9 in parts.get("tokennfttx", []) if str(r9.get("contractAddress") or "").lower() in _mg9]
            per_wallet[w] = (parts["txlist"], parts["tokentx"] + nft9, parts["txlistinternal"])
        merged = self.merge_wallet_rows(per_wallet)
        n_emit = 0
        for h in sorted(merged, key=lambda x: (self._ent_block(merged[x]) or 0, x)):
            ent = merged[h]
            snap = self._snapshot(ent)
            if snap is None or not self._ent_block(ent):
                log.warning("%s 확장 %s 파싱 불능 — 커버 하한 보류", self.chain, h[:12])
                common.atomic_write_json(self.emitted_path, sorted(self.emitted))
                return
            rec9 = {"v": 1, "kind": "evm_tx", "chain": self.chain, "txhash": h, "snapshot": snap,
                    "wallets": self.wallets, "observed_head": head, "ts": int(time.time())}
            if h in self.emitted:
                rec9["repair"] = "leg_union"
            self.writer.append(rec9)
            self.emitted.add(h)
            n_emit += 1
        common.atomic_write_json(self.emitted_path, sorted(self.emitted))
        for w in need:
            self.cursor["_cov:" + w] = int(tblk)
        common.atomic_write_json(self.cursor_path, self.cursor)
        self.progress.finish(f"{self.chain}:extend", note=f"확장 {len(need)}지갑 {n_emit}tx {time.time() - t0:.0f}초")
        log.info("★%s 과거 창 확장 완료 [etherscan]: 지갑 %d, 방출 %d, 조각 %d, %.0f초 → 하한 블록 %d★", self.chain,
                 len(need), n_emit, len(tasks), time.time() - t0, tblk)

    def _list_all(self, action: str, wallet: str, frm: int, to: int) -> list:
        out = []
        seen = {}
        start = frm
        while True:
            page9 = int(getattr(self, "page", self.PAGE) or self.PAGE)
            rows = self._es({"module": "account", "action": action, "address": wallet,
                             "startblock": start, "endblock": to, "page": 1,
                             "offset": page9, "sort": "asc"})
            if not isinstance(rows, list):
                raise RuntimeError(f"{action} 형식 오류")
            page_counts = {}
            for row in rows:
                key = self._row_key(row)
                page_counts[key] = page_counts.get(key, 0) + 1
                if page_counts[key] <= seen.get(key, 0):
                    continue
                seen[key] = page_counts[key]
                out.append(row)
            if len(rows) < min(page9, self.ES_ROW_FLOOR):
                return out
            last_blk = int(rows[-1].get("blockNumber") or 0)
            if last_blk <= start:
                raise RuntimeError(f"{action} 페이지 전진 불가 (단일 블록 {len(rows)}건 이상)")
            start = last_blk

    @staticmethod
    def _ent_block(ent: dict):
        for src in ([ent["tx"]] if ent.get("tx") else []) + list(ent.get("tt") or []) + list(ent.get("it") or []):
            try:
                return int(src.get("blockNumber") or 0) or None
            except (TypeError, ValueError, AttributeError):
                continue
        return None

    @staticmethod
    def _row_key(row) -> str:
        return json.dumps({k: v for k, v in row.items() if k != "confirmations"} if isinstance(row, dict) else row,
                          sort_keys=True, separators=(",", ":"))

    @classmethod
    def merge_wallet_rows(cls, per_wallet: dict) -> dict:
        out = {}
        for w, (txs, tts, its) in per_wallet.items():
            for row in txs:
                h = (row.get("hash") or "").lower()
                if h:
                    e = out.setdefault(h, {"tx": None, "tt": {}, "it": {}, "ws": set()})
                    e["ws"].add(w)
                    if e["tx"] is None:
                        e["tx"] = row
            for kind, rows in (("tt", tts), ("it", its)):
                cnt = {}
                for row in rows:
                    h = (row.get("hash") or "").lower()
                    if not h:
                        continue
                    k = cls._row_key(row)
                    cnt.setdefault(h, {}).setdefault(k, [0, row])[0] += 1
                for h, per in cnt.items():
                    e = out.setdefault(h, {"tx": None, "tt": {}, "it": {}, "ws": set()})
                    e["ws"].add(w)
                    for k, (n, row) in per.items():
                        cur = e[kind].get(k)
                        if cur is None or cur[0] < n:
                            e[kind][k] = [n, row]
        for e in out.values():
            for kind in ("tt", "it"):
                e[kind] = [row for n, row in e[kind].values() for _ in range(n)]
        return out

    @classmethod
    def _leg_marks(cls, ent: dict) -> dict:
        out = {}
        if ent.get("tx"):
            out["tx"] = 1
        for kind in ("tt", "it"):
            for row in ent.get(kind) or []:
                k = kind + ":" + hashlib.sha1(cls._row_key(row).encode()).hexdigest()[:16]
                out[k] = out.get(k, 0) + 1
        return out

    @staticmethod
    def _marks_new(prev, cur: dict) -> bool:
        if not isinstance(prev, dict):
            return bool(cur)
        return any(n > int(prev.get(k, 0) or 0) for k, n in cur.items())

    @staticmethod
    def _marks_merge(prev, cur: dict) -> dict:
        out = dict(prev) if isinstance(prev, dict) else {}
        for k, n in cur.items():
            out[k] = max(int(out.get(k, 0) or 0), n)
        return out

    def _lag_blocks(self) -> int:
        bpd9 = int(getattr(self, "bpd", 0) or 7200)
        return max(int(getattr(self, "conf_depth", 12) or 12), -(-bpd9 * self.INT_LAG_SEC // 86400))

    def _lag_from(self, w: str, since: int) -> int:
        floor9 = self.cursor.get("_cov:" + w)
        if not isinstance(floor9, int):
            floor9 = ((self.cursor.get("_es_int") or {}).get("floor") or {}).get(w)
        floor9 = int(floor9) if isinstance(floor9, int) else 0
        return max(floor9 + 1, since + 1 - self._lag_blocks(), 1)

    def _es_mem(self) -> dict:
        return _ES_WMEM.setdefault(self.chain, {"cost": {}, "next": None})

    def _es_wneed(self, w) -> int:
        n9 = int(addr_tier.per_check_calls("etherscan", bool(lpdec.lp_managers(common.BASE_DIR).get(self.chain))))
        return max(n9, int(self._es_mem()["cost"].get(w, 0)))

    def _es_q_room(self, own: int, start: bool) -> bool:
        if bf_engine.ES_PACE_BURST_FRAC >= 1.0 or es_daily_left() > 0:
            return True
        used9, cap9 = bf_engine.es_budget_used()
        if used9 >= cap9:
            return True
        now = time.time()
        keep9 = max(1, int(cap9 * max(bf_engine.ES_FILL_KEEP_FRAC, bf_engine.ES_FILL_KEEP_MIN)))
        with _ES_Q_LOCK:
            me = _ES_Q.setdefault(self.chain, {"went": 0.0})
            if start:
                me.update(need=int(own), seen=now)
            k0 = (float(me.get("went") or 0), self.chain)
            ahead = 0
            for c9, v9 in _ES_Q.items():
                if c9 == self.chain or not (v9.get("busy") or now - float(v9.get("seen") or 0) <= ES_Q_TTL):
                    continue
                if not start or v9.get("busy") or (float(v9.get("went") or 0), c9) < k0:
                    ahead += int(v9.get("need") or 0)
            ok9 = bf_engine.es_pace_room("head", now) >= min(ahead + int(own), keep9)
            if ok9 and start:
                me["busy"] = True
                self._es_q_go = True
        return ok9

    def _es_q_done(self):
        if getattr(self, "_es_q_go", False):
            self._es_q_go = False
            with _ES_Q_LOCK:
                me = _ES_Q.get(self.chain)
                if me is not None:
                    me.update(went=time.time(), busy=False)

    def _legacy_pending(self, pend9: dict, safe: int, tb=None):
        for h9 in list(pend9.keys())[:30]:
            try:
                if h9 not in self.emitted and h9.lower() not in self.emitted:
                    snap9 = self._rpc_synth_detail(h9)
                    rec9 = {"v": 1, "kind": "evm_tx", "chain": self.chain, "txhash": h9,
                            "snapshot": snap9, "wallets": self.wallets,
                            "observed_head": safe + self.conf_depth,
                            "ts": int(time.time())}
                    self.writer.append(rec9)
                    self.emitted.add(h9.lower())
                    if tb is not None:
                        tb.note_sent(addr_tier.sent_from(snap9), addr_tier.snap_ts(snap9))
                del pend9[h9]
                log.info("%s 구 pending %s RPC 합성 해소", self.chain, h9[:12])
            except Exception as e9:
                failures9 = self.synth_fail_count(pend9, h9, e9)
                if failures9 is None:
                    log.debug("%s 구 pending %s 보류(게이트·장부 거절 — 횟수 안 셈): %s", self.chain, h9[:12], str(e9)[:120])
                    continue
                if failures9 > 200:
                    common.append_durable_jsonl(
                        os.path.join(common.STATE_DIR, "pending_poison.jsonl"),
                        {"ts": int(time.time()), "chain": self.chain,
                         "txhash": h9, "err": common.safe_err(e9)[:200]})
                    del pend9[h9]
                    log.error("★%s 구 pending %s 200회 초과 — 포이즌 격리★",
                              self.chain, h9[:12])
                else:
                    log.warning("%s 구 pending %s 합성 실패(%d회): %s",
                                self.chain, h9[:12], failures9, e9)

    def cycle(self):
        try:
            self._es_cycle()
        finally:
            self._es_q_done()

    def _es_cycle(self):
        self._es_kind = "head"
        tb = getattr(self, "_tier", None)
        rest_set = set()
        if tb is not None:
            lp9 = common.read_json(os.path.join(common.STATE_DIR, f"pending_detail_{self.chain}.json"), {})
            self._tier_legacy_pend = lp9 if isinstance(lp9, dict) else {}
            addr_tier.tier_prune(self)
            addr_tier.evm_activity(self, tb)
            due9, rest9 = tb.due_list(self.wallets)
            rest_set = set(rest9)
            if not due9 and not self._tier_legacy_pend:
                if self._ext_maybe_needed():
                    try:
                        hd9 = int(getattr(self, "_max_head", 0) or 0) or self.head_block()
                    except EtherscanPaced:
                        hd9 = 0
                    if hd9:
                        self._es_extend_safe(hd9)
                addr_tier.evm_empty_probe(self, tb, self._es_has_rows)
                addr_tier.idle_cycle(self, tb, "etherscan", "api.etherscan.io")
                return
        mem9 = self._es_mem()
        order9 = list(self.wallets)
        nx9 = mem9.get("next")
        if nx9 in order9:
            i9 = order9.index(nx9)
            order9 = order9[i9:] + order9[:i9]
        w09 = next((w for w in order9 if w in self.cursor and w not in rest_set), None)
        own9 = 1 + (self._es_wneed(w09) if w09 else 0)
        if not self._es_q_room(own9, True):
            raise EtherscanPaced(f"이더스캔 지갑 목록 묶음({own9}콜)이 실시간 몫에 쌓일 때까지 대기 — 다음 주기에 이어 받음")
        head = self.head_block()
        safe = head - self.conf_depth
        cycle_ok = True
        failed_w = 0
        tried_w = 0
        per_wallet = {}
        since_of = {}
        from_of = {}
        int_rec = self.cursor.get("_es_int") if isinstance(self.cursor.get("_es_int"), dict) else {}
        int_seen = int_rec.get("seen") if isinstance(int_rec.get("seen"), dict) else {}
        fail_since = {}
        paced_w = 0
        self._es_paced_next = mem9["next"] = None
        hw9 = 0
        wcost9 = mem9["cost"]
        for w9 in [w9 for w9 in wcost9 if w9 not in self.wallets]:
            wcost9.pop(w9, None)
        ft9 = mem9.setdefault("fail_t0", {})
        for w9 in [w9 for w9 in ft9 if w9 not in self.wallets]:
            ft9.pop(w9, None)
        for w in order9:
            first = w not in self.cursor
            since = int(self.cursor.get(w, 0))
            self._es_kind = "fill" if first else "head"
            if first:
                if self.backfill:
                    since = 0
                elif self.backfill_months > 0:
                    ck = self.cursor.get("_bfes:" + w)
                    if isinstance(ck, dict) and "since" in ck:
                        since = int(ck["since"])
                    else:
                        try:
                            since = self.window_start_block(safe, self.backfill_months, self.bpd)
                            ws9 = self.wallet_since.get(w)
                            if ws9:
                                since = min(since, self._block_by_ts(ws9))
                        except EtherscanPaced:
                            paced_w += 1
                            continue
                        self.cursor["_bfes:" + w] = {"since": since, "t0": int(time.time())}
                        common.atomic_write_json(self.cursor_path, self.cursor)
                    log.info("%s %d개월 한도 백필 시작 [etherscan] (%d → %d)",
                             w[:10], int(self.backfill_months), since, safe)
                else:
                    self.cursor[w] = safe
                    int_rec.setdefault("floor", {})[w] = safe
                    self.cursor["_es_int"] = int_rec
                    continue
            if w in rest_set:
                continue
            if since >= safe:
                if tb is not None:
                    addr_tier.tier_partial(self, w, False)
                if tb is not None and not addr_tier.tier_pending(self, w, enrich=False):
                    tb.note_full(w, since)
                continue
            if self._es_kind == "head":
                if hw9 and not self._es_q_room(self._es_wneed(w), False):
                    paced_w += 1
                    self._es_paced_next = mem9["next"] = w
                    break
                hw9 += 1
            hs9 = getattr(self, "_es_hspent", 0)
            tried_w += 1
            frm = since + 1 if first else self._lag_from(w, since)
            try:
                txs = self._list_all("txlist", w, frm, safe)
                tts = self._list_all("tokentx", w, frm, safe)
                its = self._list_all("txlistinternal", w, frm, safe)
                _mg9 = lpdec.lp_managers(common.BASE_DIR).get(self.chain) or {}
                if _mg9:
                    tts = tts + [r9 for r9 in self._list_all("tokennfttx", w, frm, safe)
                                 if str(r9.get("contractAddress") or "").lower() in _mg9]
            except EtherscanPaced:
                tried_w -= 1
                paced_w += 1
                if self._es_kind == "head":
                    self._es_paced_next = mem9["next"] = w
                    sp9 = getattr(self, "_es_hspent", 0) - hs9
                    wcost9[w] = max(int(wcost9.get(w, 0)), sp9 + 1, 2 * sp9)
                    break
                continue
            except EtherscanKeyError:
                raise
            except Exception as e:
                log.warning("%s etherscan 수집 실패(다음 사이클): %s", w[:10], e)
                cycle_ok = False
                failed_w += 1
                fail_since[w] = since
                t9, f9 = time.time(), ft9.get(w)
                if isinstance(f9, list) and len(f9) == 2 and t9 - float(f9[1]) <= ES_FAIL_ISOLATE_SEC:
                    f9[1] = t9
                else:
                    ft9[w] = [t9, t9]
                _revoke_stamp_disk(self.cursor_path)
                continue
            ft9.pop(w, None)
            per_wallet[w] = (txs, tts, its)
            since_of[w] = since
            from_of[w] = frm
            if self._es_kind == "head":
                wcost9[w] = getattr(self, "_es_hspent", 0) - hs9
            if tb is not None and (txs or tts or its):
                tb.clear_empty(w, "rows")
        self._es_kind = "head"
        merged = self.merge_wallet_rows(per_wallet)
        now9 = time.time()
        iso9 = {w for w in fail_since if now9 - float((ft9.get(w) or [now9])[0]) >= ES_FAIL_ISOLATE_SEC}
        note9 = mem9.setdefault("iso_note", set())
        note9.intersection_update(ft9)
        if iso9 - note9:
            log.warning("%s etherscan 목록 조회 %d분 넘게 실패한 지갑 %s — 그 지갑만 보류(커서 유지), 다른 지갑은 진행(겹친 tx 는 회복 때 레그 합집합)",
                        self.chain, ES_FAIL_ISOLATE_SEC // 60, [w9[:10] for w9 in sorted(iso9 - note9)])
        note9.update(iso9)
        eff_safe = min([safe] + [int(v) for w, v in fail_since.items() if w not in iso9])
        bad_w = set()
        n_emit = 0
        relist = []
        for h in sorted(merged, key=lambda x: (self._ent_block(merged[x]) or 0, x)):
            ent = merged[h]
            if h in self.emitted:
                blk9 = self._ent_block(ent)
                if blk9 and (ent["tx"] or ent["it"] or ent["tt"]) and any(from_of[w] <= blk9 <= eff_safe for w in ent["ws"]):
                    prev9 = int_seen.get(h)
                    if self._marks_new(prev9[1] if isinstance(prev9, list) and len(prev9) == 2 else None, self._leg_marks(ent)):
                        relist.append(h)
                continue
            blk = self._ent_block(ent)
            if not blk:
                log.warning("etherscan %s 블록 번호 파싱 불능 — 관련 지갑 커서 유지", h[:12])
                bad_w |= ent["ws"]
                continue
            if not any(from_of[w] <= blk <= eff_safe for w in ent["ws"]):
                continue
            snap = self._snapshot(ent)
            if snap is None:
                log.warning("etherscan %s 상세 수치 파싱 불능 — 관련 지갑 커서 유지", h[:12])
                bad_w |= ent["ws"]
                continue
            rec = {"v": 1, "kind": "evm_tx", "chain": self.chain, "txhash": h,
                   "snapshot": snap, "wallets": self.wallets,
                   "observed_head": head, "ts": int(time.time())}
            try:
                self.writer.append(rec)
                self.emitted.add(h)
                n_emit += 1
                int_seen[h] = [blk, self._leg_marks(ent)]
                if tb is not None and ent["tx"]:
                    tb.note_sent(str(ent["tx"].get("from") or "").lower(), snap["tx"].get("timestamp"))
            except Exception as e:
                log.error("inbox append 실패 — 커서 미전진: %s", e)
                bad_w |= set(per_wallet)
                cycle_ok = False
                _revoke_stamp_disk(self.cursor_path)
                break
        for h in relist:
            ent = merged[h]
            blk = self._ent_block(ent)
            if not any(w not in bad_w and from_of[w] <= blk <= eff_safe for w in ent["ws"]):
                continue
            snap = self._snapshot(ent)
            if snap is None:
                log.warning("etherscan %s internal 늦은 색인 재방출 — 상세 수치 파싱 불능, 관련 지갑 커서 유지", h[:12])
                bad_w |= ent["ws"]
                continue
            try:
                self.writer.append({"v": 1, "kind": "evm_tx", "chain": self.chain, "txhash": h, "snapshot": snap, "wallets": self.wallets,
                                    "observed_head": head, "ts": int(time.time()), "repair": "leg_union"})
                if tb is not None and ent["tx"]:
                    tb.note_sent(str(ent["tx"].get("from") or "").lower(), snap["tx"].get("timestamp"))
            except Exception as e:
                log.error("inbox append 실패(internal 늦은 색인 재방출) — 커서 미전진: %s", e)
                bad_w |= set(per_wallet)
                cycle_ok = False
                _revoke_stamp_disk(self.cursor_path)
                break
            prev9 = int_seen.get(h)
            int_seen[h] = [blk, self._marks_merge(prev9[1] if isinstance(prev9, list) and len(prev9) == 2 else None, self._leg_marks(ent))]
            log.info("%s %s 늦은 색인 레그 — leg 합집합 재방출(토큰 %d · internal %d행)", self.chain, h[:12], len(ent["tt"]), len(ent["it"]))
        if int_seen or int_rec.get("floor"):
            lo_all9 = list(from_of.values()) + [self._lag_from(w, int(self.cursor[w])) for w in rest_set if isinstance(self.cursor.get(w), int)]
            lo9 = min(lo_all9) if lo_all9 else None
            if lo9 is not None:
                int_seen = {h9: v9 for h9, v9 in int_seen.items() if isinstance(v9, list) and len(v9) == 2 and int(v9[0]) >= lo9}
            int_rec["seen"] = int_seen
            self.cursor["_es_int"] = int_rec
        if bad_w:
            cycle_ok = False
            failed_w += len(bad_w & set(per_wallet))
            _revoke_stamp_disk(self.cursor_path)
        for w in per_wallet:
            if w not in bad_w:
                if w not in self.cursor:
                    ck = self.cursor.pop("_bfes:" + w, None)
                    if isinstance(ck, dict) and "since" in ck:
                        self.cursor["_cov:" + w] = int(ck["since"])
                    if isinstance(ck, dict):
                        log.info("★%s 백필 완주 [etherscan] %d tx 방출, %.0f초★", w[:10], n_emit,
                                 time.time() - float(ck.get("t0") or time.time()))
                self.cursor[w] = max(int(self.cursor.get(w, 0)), eff_safe)
                if tb is not None:
                    addr_tier.tier_partial(self, w, int(self.cursor[w]) < safe)
                    if int(self.cursor[w]) >= safe and not addr_tier.tier_pending(self, w, enrich=False):
                        tb.note_full(w, int(self.cursor[w]))
        if tb is not None:
            self._tier_fail = (getattr(self, "_tier_fail", set()) - (set(per_wallet) - bad_w)) | set(fail_since) | (bad_w & set(per_wallet))
        common.atomic_write_json(self.emitted_path, sorted(self.emitted))
        pp9 = os.path.join(common.STATE_DIR, f"pending_detail_{self.chain}.json")
        pend9 = common.read_json(pp9, {})
        if pend9:
            self._legacy_pending(pend9, safe, tb)
            common.atomic_write_json(pp9, pend9)
            if tb is not None:
                self._tier_legacy_pend = dict(pend9)
        if tried_w and failed_w == tried_w:
            raise RuntimeError(f"etherscan 수집 전 지갑 실패 ({failed_w}/{tried_w})")
        if cycle_ok and not pend9 and \
                all(int(self.cursor.get(w, 0)) >= safe for w in self.wallets if w not in rest_set):
            self.cursor["_synced_at"] = int(time.time())
        else:
            self.cursor.pop("_synced_at", None)
        common.atomic_write_json(self.cursor_path, self.cursor)
        if tb is not None:
            addr_tier.evm_baselines(self, tb, list(per_wallet))
            if cycle_ok:
                addr_tier.evm_empty_probe(self, tb, self._es_has_rows)
            tb.save()
        if cycle_ok:
            self._es_extend_safe(head)
        if self._es_paced_next is not None and not per_wallet:
            raise EtherscanPaced("이더스캔 지갑 조회 페이싱 — 이번 주기 목록 조회를 끝낸 지갑 없음")
        self._health_cycle("etherscan", head, safe, ok=cycle_ok,
                           err=RuntimeError(f"지갑 실패 {failed_w}/{tried_w}"), current_source="api.etherscan.io",
                           wallets_failing=failed_w, pending_detail=len(pend9), wallets_paced=paced_w)

    def _es_has_rows(self, w: str, blk: int):
        self._es_kind = "aux"
        try:
            acts = ["tokentx"] + (["tokennfttx"] if lpdec.lp_managers(common.BASE_DIR).get(self.chain) else [])
            for act in acts:
                rows = self._es({"module": "account", "action": act, "address": w, "startblock": 0, "endblock": int(blk),
                                 "page": 1, "offset": 1, "sort": "asc"})
                if not isinstance(rows, list):
                    return None
                if rows:
                    return True
            return False
        finally:
            self._es_kind = "head"

    def _es_extend_safe(self, head: int):
        try:
            self._es_extend(head)
        except EtherscanKeyError:
            raise
        except EtherscanPaced as e:
            log.debug("%s 과거 창 확장 — 페이싱으로 다음 주기: %s", self.chain, e)
        except Exception as e:
            log.info("%s 과거 창 확장 예외(다음 사이클): %s", self.chain, e)
        finally:
            self._es_kind = "head"

    def _ext_maybe_needed(self) -> bool:
        if not bf_engine.SINCE.target(self.chain):
            return False
        return any(isinstance(self.cursor.get(w), int) and addr_tier._evm_ext_need(self, "etherscan", w) for w in self.wallets)

    def _ent_ts(self, ent: dict):
        for r in ([ent["tx"]] if ent.get("tx") else []) + list(ent.get("tt") or []) + list(ent.get("it") or []):
            try:
                v = int(r.get("timeStamp") or 0)
            except (TypeError, ValueError, AttributeError):
                continue
            if v > 0:
                return v
        if self is None:
            return None
        src9 = ent.get("tx") or next(iter(list(ent.get("tt") or []) + list(ent.get("it") or [])), None) or {}
        h9 = str(src9.get("hash") or "")
        hold = getattr(self, "_ts_hold", None)
        if hold is None:
            hold = self._ts_hold = tsfix.TsHold()
        try:
            v = tsfix.block_ts(self, self._ent_block(ent) or 0)
            hold.clear(h9)
            return v
        except Exception as e:
            if hold.hold(h9):
                log.warning("etherscan %s 시각 없음 · 블록 시각 조회 실패 — 보류(커서 유지 · 다음 사이클): %s", h9[:12], str(e)[:100])
                return None
            log.error("★etherscan %s 시각 없음 %d회 연속 — 내보냄(core 격리 → 블록 시각 구하는 대로 자동 재방출 · 상태 패널 '격리된 거래 기록')★",
                      h9[:12], hold.limit)
            return 0

    ES_WRAP_DEPOSIT_SEL = "0xd0e30db0"
    ES_WRAP_WITHDRAW_SEL = "0x2e1a7d4d"
    ES_NONVALUE_INTERNAL = frozenset(("delegatecall", "staticcall", "callcode"))

    def _es_wrap_legs(self, t: dict, status: str, ent: dict, tts: list):
        wr = str(getattr(self, "wrapped_ca", None) or "").lower()
        if not wr or not t or status != "ok" or str(t.get("to") or "").lower() != wr:
            return []
        fr = str(t.get("from") or "").lower()
        ws9 = getattr(self, "wallets", None)
        if not fr or (ws9 is not None and fr not in ws9):
            return []
        inp = str(t.get("input") or "").lower()
        mid = str(t.get("methodId") or "").lower()
        sel = inp[:10] if inp.startswith("0x") and len(inp) >= 10 else (mid[:10] if len(mid) >= 10 else "")
        empty9 = inp == "0x" or (inp == "" and mid == "0x")
        z9 = RpcSynthMixin.ZERO_ADDR
        try:
            if sel == EtherscanWatcher.ES_WRAP_DEPOSIT_SEL or empty9:
                v, a, b = int(t.get("value") or 0), z9, fr
            elif sel == EtherscanWatcher.ES_WRAP_WITHDRAW_SEL:
                a, b = fr, z9
                if len(inp) >= 74 and re.fullmatch(r"[0-9a-f]{64}", inp[10:74]):
                    v = int(inp[10:74], 16)
                else:
                    v = sum(int(r.get("value") or 0) for r in ent.get("it") or []
                            if str(r.get("from") or "").lower() == wr and str(r.get("to") or "").lower() == fr
                            and str(r.get("isError") or "0") == "0"
                            and str(r.get("type") or "").lower() not in EtherscanWatcher.ES_NONVALUE_INTERNAL)
            else:
                return []
        except (TypeError, ValueError):
            return []
        if v <= 0:
            return []
        for r in tts:
            tok9 = r.get("token") or {}
            if str(tok9.get("address") or "").lower() == wr and str(r.get("from") or "").lower() == a \
                    and str(r.get("to") or "").lower() == b and str((r.get("total") or {}).get("value")) == str(v):
                return []
        dec9 = sym9 = None
        for r in ent.get("tt") or []:
            if str(r.get("contractAddress") or "").lower() == wr and r.get("tokenDecimal") not in (None, ""):
                dec9, sym9 = int(r.get("tokenDecimal")), r.get("tokenSymbol")
                break
        if dec9 is None:
            try:
                dec9 = self._rpc_token_dec(wr)
            except bf_engine.TokenNoDecimals:
                return []
            except Exception as e9:
                log.warning("etherscan %s 랩드 네이티브 %s 자릿수 조회 실패 — 보류: %s", str(t.get("hash"))[:12], wr[:10], str(e9)[:100])
                return None
        return [{"from": a, "to": b, "token": {"address": wr, "symbol": sym9, "decimals": dec9, "type": "ERC-20"},
                 "total": {"value": str(v)}}]

    def _snapshot(self, ent: dict):
        t = ent["tx"]
        ts9 = EtherscanWatcher._ent_ts(self, ent)
        if ts9 is None:
            return None
        if t:
            try:
                fee = int(t.get("gasUsed") or 0) * int(t.get("gasPrice") or 0)
                status = "ok" if str(t.get("txreceipt_status") or "1") == "1" else "error"
                tx = {"hash": t["hash"], "from": t.get("from"), "to": t.get("to"),
                      "value": str(int(t.get("value") or 0)),
                      "fee": {"value": str(fee)}, "status": status,
                      "raw_input": t.get("input") or "0x",
                      "timestamp": ts9,
                      "block_number": int(t.get("blockNumber") or 0),
                      "block_hash": t.get("blockHash")}
            except (TypeError, ValueError, KeyError):
                return None
        else:
            src = (ent["tt"] or ent["it"])[0]
            try:
                tx = {"hash": src["hash"], "from": src.get("from"), "to": src.get("to"),
                      "value": "0", "fee": {"value": "0"}, "status": "ok",
                      "raw_input": "0x01",
                      "timestamp": ts9,
                      "block_number": int(src.get("blockNumber") or 0),
                      "block_hash": src.get("blockHash")}
            except (TypeError, ValueError, KeyError):
                return None
        tts = []
        for r in ent["tt"]:
            try:
                if r.get("tokenID") is not None and r.get("tokenDecimal") in (None, "", "0") and r.get("value") is None:
                    tts.append({"from": r.get("from"), "to": r.get("to"),
                                "token": {"address": (r.get("contractAddress") or "").lower(),
                                          "symbol": r.get("tokenSymbol"), "name": r.get("tokenName"),
                                          "type": "ERC-721"},
                                "total": {"token_id": str(int(r.get("tokenID")))}})
                    continue
                ca9 = (r.get("contractAddress") or "").lower()
                v9 = int(r.get("value") or 0)
                td9 = r.get("tokenDecimal")
                if td9 not in (None, ""):
                    dec9 = int(td9)
                elif not v9:
                    dec9 = None
                else:
                    try:
                        dec9 = self._rpc_token_dec(ca9)
                    except bf_engine.TokenNoDecimals:
                        self._nodec_reg().skip(tx["hash"], ca9, r.get("from"), r.get("to"), v9)
                        continue
                    except Exception as e9:
                        log.warning("etherscan %s 토큰 %s 자릿수 미상(빈 tokenDecimal) · RPC 조회 실패 — 보류: %s", str(tx.get("hash"))[:12],
                                    ca9[:10], str(e9)[:100])
                        return None
                tts.append({"from": r.get("from"), "to": r.get("to"),
                            "token": {"address": ca9,
                                      "symbol": r.get("tokenSymbol"),
                                      "decimals": dec9,
                                      "type": "ERC-20"},
                            "total": {"value": str(v9)}})
            except (TypeError, ValueError):
                return None
        wl9 = EtherscanWatcher._es_wrap_legs(self, t, tx["status"], ent, []) if t else []
        if wl9 is None:
            return None
        for r9 in wl9:
            if not any(str(t9.get("from") or "").lower() == r9["from"] and str(t9.get("to") or "").lower() == r9["to"]
                       and str((t9.get("token") or {}).get("address") or "").lower() == r9["token"]["address"]
                       and str((t9.get("total") or {}).get("value")) == r9["total"]["value"] for t9 in tts):
                tts.append(r9)
        its = []
        for r in ent["it"]:
            if str(r.get("type") or "").lower() in EtherscanWatcher.ES_NONVALUE_INTERNAL:
                continue
            try:
                its.append({"from": r.get("from"), "to": r.get("to"),
                            "value": str(int(r.get("value") or 0)),
                            "success": str(r.get("isError") or "0") == "0",
                            "error": None if str(r.get("isError") or "0") == "0" else "err"})
            except (TypeError, ValueError):
                return None
        for r9 in wl9:
            a9, b9 = str(r9.get("from") or "").lower(), str(r9.get("to") or "").lower()
            wr9 = str((r9.get("token") or {}).get("address") or "").lower()
            if b9 != RpcSynthMixin.ZERO_ADDR or not a9 or a9 != str((t or {}).get("from") or "").lower():
                continue
            if not any(str(i.get("from") or "").lower() == wr9 and str(i.get("to") or "").lower() == a9 and i.get("success") for i in its):
                its.append({"from": wr9, "to": a9, "value": str((r9.get("total") or {}).get("value")), "success": True, "error": None})
        return {"tx": tx, "token_transfers": tts, "internal": its}


class RpcLogDiscovery(RpcSynthMixin):

    DEGRADE_AFTER = 600
    SPAN_INIT = 2000
    SPAN_MIN = 250
    SPAN_MAX = 5000
    HEAD_TTL = 20
    EMIT_FAIL_MAX = 200
    NW_BUDGET = 45

    def __init__(self, cfg: dict, chain: str, wallets: list, writer, bs_watcher):
        cc = cfg["chains"][chain]
        self.chain = chain
        self.wrapped_ca = str((cfg.get("wrapped_native") or {}).get(chain) or "").lower() or None
        self.mode = str(cc.get("rpc_log_discovery") or "shadow")
        self.chain_id = int(cc["chain_id"])
        self.conf_depth = int(cc.get("conf_depth", 12))
        self.bpd = int(cc.get("blocks_per_day", 43200))
        self.backfill_months = float(cfg.get("backfill_months") or 0)
        self.logs_rpcs = list(cc.get("rpc_logs") or [])
        if not self.logs_rpcs:
            raise SystemExit(f"{chain}: rpc_log_discovery 켰는데 rpc_logs 미구성")
        self.span_caps = dict(cc.get("rpc_log_span_caps") or {})
        self.logs_sleep = float(cc.get("rpc_logs_sleep_sec", 1.0))
        self.wallets = [w.lower() for w in wallets]
        self.pads = ["0x" + w[2:].rjust(64, "0") for w in self.wallets]
        self.writer = writer
        self.bs = bs_watcher
        self.cfg_rpcs = cc.get("rpcs")
        self.rpc_meta_path = os.path.join(common.STATE_DIR, f"rpc_token_meta_{chain}.json")
        self.rpc_meta = common.read_json(self.rpc_meta_path, {})
        self.state_path = os.path.join(common.STATE_DIR, f"cursor_rpc_{chain}.json")
        self.st = common.read_json(self.state_path, {})
        self.emitted_path = os.path.join(common.STATE_DIR, f"emitted_rpc_{chain}.json")
        self.emitted = set(common.read_json(self.emitted_path, []))
        self.span = min(max(int(self.st.get("span") or self.SPAN_INIT), self.SPAN_MIN),
                        self.SPAN_MAX)
        self.ep = {}
        self.emit_fail = {}

    def _ep_state(self, url):
        return self.ep.setdefault(url, {"ok": False, "head": 0, "head_ts": 0.0,
                                        "fail_until": 0.0, "streak": 0})

    def _one(self, url: str, method: str, params: list, timeout: int = 25):
        d = bf_engine.http_json(
            url, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
            headers={"User-Agent": common.ua_for(url, UA)}, timeout=timeout, retries=1, rpc_methods=(method,))
        if not isinstance(d, dict):
            raise RuntimeError(f"rpc-error None: 응답 형식 오류 ({type(d).__name__})")
        if "error" in d:
            err = d["error"] if isinstance(d["error"], dict) else {}
            raise RuntimeError(f"rpc-error {err.get('code')}: {str(err.get('message'))[:120]}")
        return d.get("result")

    def _trip(self, url: str, e: Exception):
        s = self._ep_state(url)
        msg = str(e)
        ratelike = ("429" in msg or "Too Many" in msg
                    or "rate limit" in msg.lower() or "-32016" in msg)
        base_wait = 30.0 if ratelike else 10.0
        s["fail_until"] = time.time() + base_wait * (1.0 + random.random())
        cap9 = re.search(r"up to a (\d+) block range", msg)
        if cap9 and int(cap9.group(1)) < self.SPAN_MIN:
            s["fail_until"] = time.time() + 6 * 3600
            if not s.get("capped"):
                s["capped"] = int(cap9.group(1))
                log.warning("%s rpclog 엔드포인트 %s: getLogs 범위 한도 %s블록 < 최소 %d — 6시간 제외(다른 엔드포인트 사용)", self.chain,
                            urllib.parse.urlsplit(url).hostname, cap9.group(1), self.SPAN_MIN)
            self._last_failed_log_ep = url
            return
        s["streak"] = 0
        self._last_failed_log_ep = url
        m = self.st.setdefault("metrics", {})
        key = "err_429" if base_wait == 30.0 else "err_ep"
        m[key] = m.get(key, 0) + 1
        log.warning("%s rpclog 엔드포인트 보류(%s): %s", self.chain,
                    urllib.parse.urlsplit(url).hostname, msg[:160])

    def _ready_ep(self, need_to: int):
        now = time.time()
        order = list(self.logs_rpcs)
        last = getattr(self, "_last_failed_log_ep", None)
        if last in order:
            start = order.index(last) + 1
            order = order[start:] + order[:start]
        for url in order:
            s = self._ep_state(url)
            if now < s["fail_until"]:
                continue
            try:
                if not s["ok"]:
                    cid = int(self._one(url, "eth_chainId", [], timeout=10), 16)
                    if cid != self.chain_id:
                        log.error("★%s rpclog %s chainId 불일치(%d≠%d) — 영구 제외★",
                                  self.chain, common.redact_urls(url), cid, self.chain_id)
                        s["fail_until"] = now + 86400 * 365
                        continue
                    s["ok"] = True
                if now - s["head_ts"] > self.HEAD_TTL or s["head"] < need_to:
                    s["head"] = int(self._one(url, "eth_blockNumber", [], timeout=10), 16)
                    s["head_ts"] = time.time()
            except Exception as e:
                self._trip(url, e)
                continue
            if s["head"] >= need_to:
                return url
        return None

    def _chunk_logs(self, url: str, frm: int, to: int, pads: list) -> dict:
        found = {}
        for pos in (1, 2):
            topics = [self.TRANSFER_TOPIC, None, None]
            topics[pos] = pads
            rows = self._one(url, "eth_getLogs",
                             [{"fromBlock": hex(frm), "toBlock": hex(to),
                               "topics": topics}])
            if not isinstance(rows, list):
                raise RuntimeError(f"getLogs 비정상 result: {type(rows).__name__} (빈 배열 아님) — 무응답")
            for lg in rows:
                h = (lg.get("transactionHash") or "").lower()
                if not h:
                    continue
                try:
                    blk = int(lg.get("blockNumber"), 16)
                except (TypeError, ValueError):
                    blk = to
                found[h] = blk
            time.sleep(self.logs_sleep)
        return found

    def _on_logs_err(self, url: str, e: Exception):
        msg = str(e)
        if "rate limit" in msg.lower() or "-32016" in msg:
            self._trip(url, e)
            m = self.st.setdefault("metrics", {})
            m["err_logs"] = m.get("err_logs", 0) + 1
            return
        range_err = any(k in msg for k in ("-32005", "408", "timed out", "timeout",
                                           "too large", "range", "limit", "-32602"))
        if range_err and self.span > self.SPAN_MIN:
            self.span = max(self.SPAN_MIN, self.span // 2)
            log.info("%s rpclog span 반감 → %d (%s)", self.chain, self.span, msg[:80])
        else:
            self._trip(url, e)
        m = self.st.setdefault("metrics", {})
        m["err_logs"] = m.get("err_logs", 0) + 1

    def _bs_degraded(self) -> bool:
        ts = self.bs.cursor.get("_synced_at")
        try:
            if ts:
                self.st["bs_last_ok"] = max(float(self.st.get("bs_last_ok") or 0), float(ts))
        except (TypeError, ValueError):
            pass
        return time.time() - float(self.st.get("bs_last_ok") or 0) > self.DEGRADE_AFTER

    def _bs_min_cursor(self):
        vals = []
        for w in self.wallets:
            v = self.bs.cursor.get(w)
            if not isinstance(v, int):
                return None
            vals.append(v)
        return min(vals) if vals else None

    def _wallet_set_check(self):
        cur_set = sorted(self.wallets)
        prev = self.st.get("wallet_set")
        if prev is None or self.st.get("from_block") is None:
            self.st["wallet_set"] = cur_set
            return
        if prev == cur_set:
            return
        for w in cur_set:
            if w not in prev and ("_nw:" + w) not in self.st:
                fb = int(self.st["from_block"])
                start = max(0, fb - int(self.backfill_months * 30 * self.bpd))
                ws9 = (getattr(getattr(self, "bs", None), "wallet_since", None) or {}).get(w)
                if ws9:
                    start = min(start, max(0, fb - int((time.time() - ws9) / 86400.0 * self.bpd)))
                self.st["_nw:" + w] = {"from": start, "to": fb, "done": start - 1}
                log.info("★%s rpclog 신규 지갑 %s — 과거 구간 %d→%d 별도 백필 개시★",
                         self.chain, w[:10], start, fb)
        self.st["wallet_set"] = cur_set

    def _nw_progress(self):
        keys = [k for k in self.st if k.startswith("_nw:") and isinstance(self.st[k], dict)]
        if not keys:
            self.__dict__.pop("_nw_seen", None)
            return None
        tot = left = 0
        for k in keys:
            ck = self.st[k]
            try:
                frm, to, done = int(ck["from"]), int(ck["to"]), int(ck["done"])
            except (KeyError, TypeError, ValueError):
                continue
            tot += max(0, to - frm + 1)
            left += max(0, to - done)
        now = time.time()
        seen = self.__dict__.setdefault("_nw_seen", (now, left))
        eta = None
        if left < seen[1] and now > seen[0]:
            rate = (seen[1] - left) / (now - seen[0])
            eta = int(left / rate) if rate > 0 else None
        return {"n": len(keys), "done": tot - left, "to": tot, "pct": round((tot - left) * 100.0 / tot, 1) if tot else 100.0,
                "eta": eta}

    def _nw_walk(self):
        keys = [k for k in self.st if k.startswith("_nw:")]
        if not keys:
            return
        deadline = time.time() + self.NW_BUDGET
        for k in keys:
            w = k[4:]
            ck = self.st[k]
            pads = ["0x" + w[2:].rjust(64, "0")]
            while int(ck["done"]) < int(ck["to"]) and time.time() < deadline:
                frm = int(ck["done"]) + 1
                to = min(frm + self.span - 1, int(ck["to"]))
                url = self._ready_ep(to)
                if url is None:
                    return
                cap = int(self.span_caps.get(url) or self.SPAN_INIT)
                to = min(frm + min(self.span, cap) - 1, int(ck["to"]))
                try:
                    found = self._chunk_logs(url, frm, to, pads)
                except Exception as e:
                    self._on_logs_err(url, e)
                    continue
                self._ep_state(url)["streak"] += 1
                self._absorb(found)
                ck["done"] = to
            if int(ck["done"]) >= int(ck["to"]):
                del self.st[k]
                log.info("★%s rpclog 신규 지갑 %s 백필 완주 — 체인 커서 합류★", self.chain, w[:10])

    def _absorb(self, found: dict):
        m = self.st.setdefault("metrics", {})
        buf = self.st.setdefault("pending_emit", {})
        for h, blk in found.items():
            m["found"] = m.get("found", 0) + 1
            if h in self.emitted or h in buf:
                continue
            if h in self.bs.emitted:
                m["bs_covered"] = m.get("bs_covered", 0) + 1
                continue
            buf[h] = blk

    def _drain_buffer(self, head: int):
        m = self.st.setdefault("metrics", {})
        buf = self.st.get("pending_emit") or {}
        if not buf:
            return
        degraded = self._bs_degraded()
        bs_min = self._bs_min_cursor()
        for h in sorted(buf):
            if h in self.emitted:
                del buf[h]
                continue
            if h in self.bs.emitted:
                del buf[h]
                m["bs_covered"] = m.get("bs_covered", 0) + 1
                continue
            if h in self.bs.pending_detail and not (self.mode == "active" and degraded):
                continue
            blk = int(buf[h])
            silent = (bs_min is not None and blk <= bs_min
                      and h not in self.bs.pending_detail)
            if silent:
                m["silent_gap"] = m.get("silent_gap", 0) + 1
                log.error("★%s rpclog silent-200 실증 — blockscout 커서(%s)가 지났는데"
                          " 미방출: %s @%d★", self.chain, bs_min, h[:12], blk)
            if self.mode != "active":
                if silent:
                    lst = self.st.setdefault("rpc_only", [])
                    lst.append({"h": h, "blk": blk, "ts": int(time.time())})
                    del self.st["rpc_only"][:-200]
                    del buf[h]
                continue
            if not (degraded or silent):
                continue
            try:
                snap = self._rpc_synth_detail(h)
            except Exception as e:
                if self.synth_fail_count(self.emit_fail, h, e) is None:
                    log.debug("%s rpclog %s 합성 보류(게이트·장부 거절): %s", self.chain, h[:12], str(e)[:120])
                    continue
                if self.emit_fail[h] > self.EMIT_FAIL_MAX:
                    common.append_durable_jsonl(
                        os.path.join(common.STATE_DIR, "pending_poison.jsonl"),
                        {"ts": int(time.time()), "chain": self.chain, "txhash": h,
                         "src": "rpc_log", "err": common.safe_err(e)[:200]})
                    del buf[h]
                    self.emit_fail.pop(h, None)
                    log.error("★%s rpclog %s 합성 %d회 초과 — 포이즌 격리★",
                              self.chain, h[:12], self.EMIT_FAIL_MAX)
                else:
                    log.warning("%s rpclog %s 합성 실패(%d회): %s",
                                self.chain, h[:12], self.emit_fail[h], e)
                continue
            rec = {"v": 1, "kind": "evm_tx", "chain": self.chain, "txhash": h,
                   "snapshot": snap, "wallets": self.wallets,
                   "observed_head": head, "ts": int(time.time())}
            try:
                self.writer.append(rec)
            except Exception as e:
                log.error("%s rpclog inbox append 실패(버퍼 유지): %s", self.chain, e)
                break
            self.emitted.add(h)
            self.emit_fail.pop(h, None)
            del buf[h]
            m["emitted"] = m.get("emitted", 0) + 1
            log.info("★%s rpclog 저하 방출 %s @%d (silent=%s)★", self.chain, h[:12], blk, silent)

    def cycle(self):
        url0 = self._ready_ep(1)
        if url0 is None:
            self.st.pop("rpc_synced_at", None)
            common.atomic_write_json(self.state_path, self.st)
            n9 = bf_engine.health("evm").fail(f"{self.chain}:rpclog", RuntimeError("가용 엔드포인트 없음"), "rpclog",
                                              cursor=self.st.get("from_block"))
            lv = bf_engine.LogDebounce.level(n9)
            if lv:
                getattr(log, lv)("%s rpclog 가용 엔드포인트 없음 %d회 연속 — 다음 주기", self.chain, n9)
            return
        head = self._ep_state(url0)["head"]
        safe = head - self.conf_depth
        self._wallet_set_check()
        if self.st.get("from_block") is None:
            bs_curs = [int(self.bs.cursor[w]) for w in self.wallets
                       if isinstance(self.bs.cursor.get(w), int)]
            if bs_curs and len(bs_curs) == len(self.wallets):
                self.st["from_block"] = min(bs_curs)
            else:
                self.st["from_block"] = max(0, safe - int(self.backfill_months * 30 * self.bpd))
            log.info("★%s rpclog 커서 초기화 → %d (safe %d)★",
                     self.chain, self.st["from_block"], safe)
            common.atomic_write_json(self.state_path, self.st)
        self._nw_walk()
        cur = int(self.st["from_block"])
        complete = True
        if cur < safe:
            budget = 40 if (safe - cur) <= 3 * self.span else 120
            deadline = time.time() + budget
            while cur < safe:
                if time.time() >= deadline:
                    complete = False
                    break
                url = self._ready_ep(min(cur + self.SPAN_MIN, safe))
                if url is None:
                    complete = False
                    break
                cap = int(self.span_caps.get(url) or self.SPAN_INIT)
                eff_head = self._ep_state(url)["head"]
                to = min(cur + min(self.span, cap), safe, eff_head)
                if to <= cur:
                    complete = False
                    break
                try:
                    found = self._chunk_logs(url, cur + 1, to, self.pads)
                except Exception as e:
                    self._on_logs_err(url, e)
                    continue
                s = self._ep_state(url)
                s["streak"] += 1
                if s["streak"] % 5 == 0:
                    self.span = min(self.SPAN_MAX, int(self.span * 1.25))
                self._absorb(found)
                cur = to
                self.st["from_block"] = cur
        self._drain_buffer(head)
        m = self.st.setdefault("metrics", {})
        m["cycles"] = m.get("cycles", 0) + 1
        cursor_ok = complete
        nw9 = self._nw_progress()
        if any(k.startswith("_nw:") for k in self.st):
            complete = False
        if complete:
            self.st["rpc_synced_at"] = int(time.time())
        else:
            self.st.pop("rpc_synced_at", None)
        self.st["mode"] = self.mode
        self.st["span"] = self.span
        bs_min = self._bs_min_cursor()
        common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        common.atomic_write_json(self.state_path, self.st)
        eps9 = {urllib.parse.urlsplit(u).hostname: {"head": st9.get("head"), "open": st9.get("fail_until", 0) > time.time()}
                for u, st9 in self.ep.items()}
        (bf_engine.health("evm").ok if cursor_ok else bf_engine.health("evm").fail)(
            f"{self.chain}:rpclog", *(() if cursor_ok else (RuntimeError("부분 진행(예산·노드)"),)), kind="rpclog",
            head=head, cursor=cur, lag_blocks=safe - cur, buf=len(self.st.get("pending_emit") or {}),
            mode=self.mode, degraded=self._bs_degraded(), span=self.span,
            current_source=urllib.parse.urlsplit(url0).hostname, endpoints=eps9,
            silent_gap=m.get("silent_gap", 0), err_429=m.get("err_429", 0), nw=nw9)
        sig9 = (self.mode, bool(self._bs_degraded()), bool(nw9), cursor_ok)
        if m.get("found", 0) != getattr(self, "_log_found", None) or m["cycles"] % 10 == 0 \
                or sig9 != getattr(self, "_log_sig", None):
            self._log_found, self._log_sig = m.get("found", 0), sig9
            log.info("%s rpclog cycle: cursor→%d lag=%d buf=%d bs_lag=%s mode=%s degraded=%s "
                     "span=%d found=%d emitted=%d bs_covered=%d silent=%d err429=%d%s",
                     self.chain, cur, safe - cur, len(self.st.get("pending_emit") or {}),
                     (safe - bs_min) if bs_min is not None else "?", self.mode,
                     self._bs_degraded(), self.span, m.get("found", 0), m.get("emitted", 0),
                     m.get("bs_covered", 0), m.get("silent_gap", 0), m.get("err_429", 0),
                     f" nw={nw9['pct']}%" if nw9 else "")


class StateUnavailable(RuntimeError):
    pass


class ChainDisabled(Exception):
    pass


DISABLED_CHAINS = set()
RETENTION_CONFIRM_N = 3
RETENTION_CONFIRM_SEC = 1800
RETENTION_MIN_AGE_SEC = 2 * 86400
EXPLORER_FROZEN_SEC = 3 * 3600
EXPLORER_FROZEN_GAP = 2000


def retention_summary(cur: dict):
    g = [x for x in ((cur or {}).get("_retention_gaps") or []) if isinstance(x, dict)]
    if not g:
        return None
    a = min(g, key=lambda x: int(x.get("from") or 0))
    b = max(g, key=lambda x: int(x.get("to") or 0))
    return {"from": int(a.get("from") or 0), "to": int(b.get("to") or 0), "from_ts": a.get("from_ts"), "floor_ts": b.get("floor_ts"),
            "n": len(g)}
REBUILD = {}
GATE_RELOAD_SEC = 600
REBUILD_FAILS = {}


def take_rebuild(wt, make):
    nw9 = REBUILD.pop(wt.chain, None)
    if nw9 is None:
        return wt
    try:
        new = make(nw9[0], wt.chain, nw9[1])
    except (Exception, SystemExit) as e:
        REBUILD.setdefault(wt.chain, nw9)
        n9 = REBUILD_FAILS[wt.chain] = REBUILD_FAILS.get(wt.chain, 0) + 1
        lv = "warning" if n9 == 1 else bf_engine.LogDebounce.level(n9)
        if lv:
            getattr(log, lv)("%s 워처 재구성 실패 %d회(종전 워처 유지·다음 사이클 재시도): %s", wt.chain, n9, e)
        return wt
    REBUILD_FAILS.pop(wt.chain, None)
    log.warning("★%s 활동 게이트 지갑 합류 — 워처 재구성(지갑 %d)★", wt.chain, len(nw9[1]))
    return new


_TDLY = "https://gateway.tenderly.co/public/"
RPC_NODES = {
    "eth": {"logs": ["https://rpc.mevblocker.io", _TDLY + "mainnet", "https://eth.drpc.org"],
            "state": ["https://eth.drpc.org", "https://rpc.mevblocker.io", _TDLY + "mainnet"],
            "trace": ["https://eth.drpc.org"], "detail": ["https://ethereum-rpc.publicnode.com", "https://eth.drpc.org"],
            "caps": {"https://rpc.mevblocker.io": 10_000, "https://eth.drpc.org": 100}},
    "arbitrum": {"logs": ["https://arb1.arbitrum.io/rpc", _TDLY + "arbitrum", "https://arbitrum.drpc.org"],
                 "state": ["https://arb1.arbitrum.io/rpc", _TDLY + "arbitrum"],
                 "trace": ["https://arbitrum.drpc.org"], "caps": {"https://arb1.arbitrum.io/rpc": 30_000, "https://arbitrum.drpc.org": 100},
                 "mc_l1_block": True},
    "polygon": {"logs": [_TDLY + "polygon", "https://polygon.drpc.org"],
                "state": ["https://polygon.drpc.org", _TDLY + "polygon"], "trace": ["https://polygon.drpc.org"],
                "detail": ["https://polygon-bor-rpc.publicnode.com", "https://polygon.drpc.org"], "caps": {"https://polygon.drpc.org": 100}},
    "optimism": {"logs": ["https://mainnet.optimism.io", _TDLY + "optimism", "https://optimism.drpc.org"],
                 "state": ["https://mainnet.optimism.io", "https://optimism.drpc.org", _TDLY + "optimism"], "trace": ["https://optimism.drpc.org"],
                 "caps": {"https://mainnet.optimism.io": 10_000, "https://optimism.drpc.org": 100}},
    "scroll": {"logs": ["https://rpc.scroll.io", "https://scroll.drpc.org"],
               "state": ["https://rpc.scroll.io", "https://scroll-rpc.publicnode.com", "https://scroll.drpc.org"], "trace": [],
               "detail": ["https://rpc.scroll.io", "https://scroll-rpc.publicnode.com"], "caps": {"https://scroll.drpc.org": 100}},
    "zksync": {"logs": ["https://mainnet.era.zksync.io", "https://zksync.drpc.org"],
               "state": ["https://mainnet.era.zksync.io"], "trace": [],
               "caps": {"https://mainnet.era.zksync.io": 100_000, "https://zksync.drpc.org": 100},
               "multicall3": "0xf9cda624fbc7e059355ce98a31693d299facd963"},
    "gnosis": {"logs": ["https://rpc.gnosischain.com", "https://rpc.gnosis.gateway.fm", "https://gnosis.drpc.org"],
               "state": ["https://rpc.gnosischain.com", "https://rpc.gnosis.gateway.fm"],
               "trace": ["https://rpc.gnosischain.com", "https://rpc.gnosis.gateway.fm", "https://gnosis.drpc.org"], "caps": {"https://gnosis.drpc.org": 100}},
    "megaeth": {"logs": ["https://mainnet.megaeth.com/rpc", "https://megaeth.drpc.org"],
                "state": ["https://mainnet.megaeth.com/rpc", "https://megaeth.drpc.org"],
                "trace": ["https://mainnet.megaeth.com/rpc", "https://megaeth.drpc.org"], "caps": {"https://megaeth.drpc.org": 100}},
    "story": {"logs": ["https://mainnet.storyrpc.io"], "state": ["https://mainnet.storyrpc.io"], "trace": [],
              "caps": {"https://mainnet.storyrpc.io": 100_000}, "limited": "노드 1개·비아카이브 — 로그 없는 이동 정합은 최근 구간만",
              "handover": "rescan"},
    "base": {"logs": ["https://mainnet.base.org", _TDLY + "base", "https://base.drpc.org"],
             "state": ["https://mainnet.base.org", "https://base.drpc.org", _TDLY + "base"],
             "caps": {"https://mainnet.base.org": 500, _TDLY + "base": 1000, "https://base.drpc.org": 10}},
    "robinhood": {"logs": ["https://rpc.mainnet.chain.robinhood.com", "https://robinhood.drpc.org"],
                  "caps": {"https://rpc.mainnet.chain.robinhood.com": 30_000, "https://robinhood.drpc.org": 100},
                  "mc_l1_block": True},
    "arc": {"logs": ["https://rpc.mainnet.arc.io", "https://rpc.quicknode.mainnet.arc.io", "https://arc.drpc.org"],
            "state": ["https://rpc.mainnet.arc.io", "https://rpc.quicknode.mainnet.arc.io", "https://arc.drpc.org"], "caps": {"https://arc.drpc.org": 100}},
    "monad": {"logs": ["https://rpc1.monad.xyz", "https://rpc2.monad.xyz", "https://rpc.monad.xyz"], "state": ["https://rpc2.monad.xyz", "https://rpc1.monad.xyz"],
              "caps": {"https://rpc2.monad.xyz": 10_000, "https://rpc.monad.xyz": 100}, "fallback": {"https://rpc2.monad.xyz": 10_000}},
    "xlayer": {"logs": ["https://xlayerrpc.okx.com", "https://rpc.xlayer.tech", "https://xlayer.drpc.org"],
               "state": ["https://xlayerrpc.okx.com", "https://rpc.xlayer.tech", "https://xlayer.drpc.org"], "caps": {"https://xlayer.drpc.org": 100}},
    "kaia": {"logs": ["https://public-en.node.kaia.io", "https://kaia.drpc.org"], "state": ["https://public-en.node.kaia.io", "https://kaia.drpc.org"],
             "caps": {"https://public-en.node.kaia.io": 1_000_000, "https://kaia.drpc.org": 100}},
    "fraxtal": {"logs": ["https://rpc.frax.com", "https://fraxtal.drpc.org"], "state": ["https://rpc.frax.com", "https://fraxtal.drpc.org"], "caps": {"https://fraxtal.drpc.org": 100}},
    "bob": {"logs": ["https://rpc.gobob.xyz", "https://bob.drpc.org"], "state": ["https://rpc.gobob.xyz", "https://bob.drpc.org"], "caps": {"https://bob.drpc.org": 100}},
    "avalanche": {"logs": ["https://api.avax.network/ext/bc/C/rpc", "https://avalanche.drpc.org"],
                  "caps": {"https://api.avax.network/ext/bc/C/rpc": 100_000, "https://avalanche.drpc.org": 100}},
    "blast": {"logs": ["https://rpc.blast.io", "https://blast.drpc.org"], "caps": {"https://rpc.blast.io": 10_000, "https://blast.drpc.org": 100}},
    "linea": {"logs": ["https://rpc.linea.build", "https://linea.drpc.org"], "state": ["https://rpc.linea.build", "https://linea.drpc.org"],
              "caps": {"https://rpc.linea.build": 10_000, "https://linea.drpc.org": 100}},
    "berachain": {"logs": ["https://rpc.berachain.com", "https://berachain.drpc.org"], "state": ["https://rpc.berachain.com", "https://berachain.drpc.org"],
                  "caps": {"https://rpc.berachain.com": 10_000, "https://berachain.drpc.org": 100}},
    "zerog": {"logs": ["https://evmrpc.0g.ai", "https://0g.drpc.org"], "state": ["https://evmrpc.0g.ai", "https://0g.drpc.org"],
              "caps": {"https://evmrpc.0g.ai": 10_000, "https://0g.drpc.org": 100}, "addr_max": 32},
    "plasma": {"limited": "노드 1개(무키 백업 없음)"},
    "stable": {"limited": "노드 1개·비아카이브 — 로그 없는 이동 정합은 최근 구간만"},
    "abstract": {"limited": "노드 1개(무키 백업 없음)"},
}


def _cap_num(x):
    return int(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and int(x) > 0 else None


def logs_cap_host(url: str):
    sp = urllib.parse.urlsplit(str(url))
    h9 = (sp.hostname or "").lower()
    p9 = h9 + (sp.path or "").rstrip("/")
    tbl = RpcChainWatcher.LOGS_CAP_HOSTS
    return _cap_num(tbl.get(p9)) if p9 in tbl else _cap_num(tbl.get(h9))


def rpc_nodes(cfg: dict, chain: str) -> dict:
    cc = ((cfg or {}).get("chains") or {}).get(chain) or {}
    t = (RPC_NODES.get(chain) or {}) if cc.get("rpc_node_table", True) is not False else {}
    R = RpcChainWatcher
    cfgcaps = cc.get("rpc_log_span_caps") if isinstance(cc.get("rpc_log_span_caps"), dict) else {}
    tcaps = t.get("caps") or {}

    def cap_of(u):
        c9 = [x for x in (_cap_num(cfgcaps.get(u)), _cap_num(tcaps.get(u)), logs_cap_host(u)) if x]
        return min(c9) if c9 else None
    detail = list(cc.get("rpcs") or t.get("detail") or R.RPC_DEFAULT.get(chain) or [])
    if common.chain_discovery(chain, cc) == "rpc":
        logs = list(cc.get("rpc_logs") or detail)
        state = list(dict.fromkeys(list(cc.get("archive_rpcs") or []) + detail))
    else:
        logs = list(dict.fromkeys(list(cc.get("rpc_logs") or []) + list(t.get("logs") or []))) or list(detail)
        state = list(dict.fromkeys(list(cc.get("archive_rpcs") or []) + list(t.get("state") or []) + detail))
    if "trace_rpcs" in cc:
        trace = list(cc.get("trace_rpcs") or [])
    else:
        trace = list(t["trace"] if "trace" in t else (R.TRACE_DEFAULT.get(chain) or []))
    caps = {}
    for u in logs:
        c9 = cap_of(u)
        if c9:
            caps[u] = c9
    fb9 = cc.get("rpc_logs_fallback")
    if isinstance(fb9, dict):
        fallback = {u: int(c) for u, c in fb9.items() if _cap_num(c)}
    else:
        fallback = {u: c for u, c in caps.items() if c <= R.LOGS_FALLBACK_MAX_CAP}
        for u, c in (t.get("fallback") or {}).items():
            if u in logs and _cap_num(c):
                fallback.setdefault(u, int(caps.get(u) or c))
        if len(fallback) >= len(logs):
            fallback = {}
    mc9 = cc["multicall3"] if "multicall3" in cc else (t.get("multicall3") or R.MULTICALL3)
    try:
        amax = max(0, int(cc.get("getlogs_max_addrs") or t.get("addr_max") or 0))
    except (TypeError, ValueError):
        amax = 0
    hosts9 = {(urllib.parse.urlsplit(u).hostname or "").lower() for u in detail + logs + state}
    return {"detail": detail, "logs": logs, "state": state, "trace": trace, "caps": caps, "fallback": fallback, "addr_max": amax,
            "multicall3": mc9, "limited": t.get("limited") if len(hosts9) <= 1 else None, "handover": t.get("handover"),
            "mc_l1_block": bool(cc["multicall3_l1_block"] if "multicall3_l1_block" in cc else t.get("mc_l1_block"))}


class RpcChainWatcher(RpcSynthMixin):

    TRANSFER = RpcSynthMixin.TRANSFER_TOPIC
    APPROVAL = "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"
    WETH_DEPOSIT = RpcSynthMixin.WETH_DEPOSIT
    WETH_WITHDRAWAL = RpcSynthMixin.WETH_WITHDRAWAL
    VERSION = 1
    NATIVE_LOG_MAX = 50
    TRACE_DEFAULT = {"robinhood": ["https://robinhood.drpc.org"], "base": ["https://base.drpc.org"]}
    HANDOVER_DEFAULT = {"robinhood": "rescan", "arc": "rescan"}
    LOGS_CAP_HOSTS = {"mainnet.base.org": 500, "gateway.tenderly.co/public/base": 1000, "base.drpc.org": 10}
    LOGS_FALLBACK_MAX_CAP = 100
    MULTICALL3 = "0xca11bde05977b3631167028862be2a173976ca11"
    TRACE_SKIP_SELECTORS = ("0xa9059cbb", "0x095ea7b3", "0x23b872dd", "0x39509351", "0xa457c2d7", "0xd505accf")
    SELL_HINTS = True
    handover = "rescan"
    lanes_cfg = None
    addr_max = 0
    multicall = None
    bk_budget = None
    poll_sec = 45.0
    trace_mode = None
    bk_span = 200_000
    block_trace = True

    @classmethod
    def day_calls(cls, cfg: dict, chain: str, n_wallets: int, tx_per_day: float = 0, backfill_blocks: int = 0,
                  backfill_txs: int = 0, logless: int = 0, own_calls: int = 0) -> dict:
        cc = (cfg.get("chains") or {}).get(chain) or {}
        import math

        def host(u):
            return (urllib.parse.urlsplit(u).hostname or "?").lower()
        nd = rpc_nodes(cfg, chain)
        rpcs, logs, state = nd["detail"], nd["logs"], nd["state"]
        trace = [] if cls.NATIVE_EMITTER.get(chain) else nd["trace"]
        caps = {u: int(nd["caps"].get(u) or cc.get("getlogs_span", 5_000_000)) for u in logs}
        prim = [u for u in logs if u not in nd["fallback"]] or logs
        try:
            poll = min(max(float(cc.get("poll_sec") or cfg.get("evm_poll_sec") or 45), 5.0), 300.0)
        except (TypeError, ValueError):
            poll = 45.0
        cyc = 86400.0 / poll
        bpd = float(cc.get("blocks_per_day") or 43200)
        mx = nd["addr_max"] or max(1, n_wallets)
        bundles = max(1, math.ceil(max(1, n_wallets) / mx))
        mc = nd["multicall3"]
        st, bk = {}, {}

        def add(d, h, n):
            d[h] = d.get(h, 0) + n
        h0 = host(rpcs[0]) if rpcs else "?"
        hs = host(state[0]) if state else h0
        add(st, h0, 2 * cyc)
        nw9 = max(1, n_wallets)
        st_cost = (nw9 + math.ceil(nw9 / 150)) if mc else 2 * nw9
        add(st, hs, st_cost * cyc)
        per_cyc_blocks = bpd * poll / 86400.0
        for u in prim:
            add(st, host(u), 2 * bundles * math.ceil(per_cyc_blocks / max(1, caps[u])) * cyc / len(prim))
        add(st, hs, 3 * tx_per_day)
        if trace:
            add(st, host(trace[0]), 0.5 * tx_per_day)
        if backfill_blocks:
            avg = sum(caps[u] for u in prim) / len(prim)
            for u in prim:
                add(bk, host(u), 2 * bundles * backfill_blocks / avg / len(prim))
            add(bk, hs, 2.7 * backfill_txs + logless * (2 * math.log2(max(2, backfill_blocks / 60)) + 1)
                + (backfill_blocks / 200_000.0) * st_cost)
            if trace:
                add(bk, host(trace[0]), own_calls + logless * 0.2)
        return {"steady": {h: int(round(v)) for h, v in st.items()}, "backfill": {h: int(round(v)) for h, v in bk.items()}}

    def __init__(self, cfg: dict, chain: str, wallets: list, writer):
        cc = cfg["chains"][chain]
        self.chain = chain
        self.cfg = cfg
        self.wrapped_ca = str((cfg.get("wrapped_native") or {}).get(chain) or "").lower() or None
        self.chain_id = int(cc["chain_id"]) if cc.get("chain_id") else None
        self.conf_depth = int(cc.get("conf_depth", 12))
        self.backfill_months = float(cfg.get("backfill_months") or 0)
        self.backfill_full = bool(cfg.get("backfill_full_history"))
        self.bpd = int(cc.get("blocks_per_day", 43200))
        self.wallets = [w.lower() for w in wallets]
        self.writer = writer
        nd9 = rpc_nodes(cfg, chain)
        self.cfg_rpcs = nd9["detail"]
        if not self.cfg_rpcs:
            raise SystemExit(f"{chain}: discovery=rpc 인데 rpcs 미구성")
        self.logs_rpcs = nd9["logs"]
        self.state_rpcs = nd9["state"]
        self.nodes_limited = nd9.get("limited")
        self.span = int(cc.get("getlogs_span", 5_000_000))
        self.min_span = int(cc.get("getlogs_min_span", 1))
        self.cycle_budget = float(cc.get("cycle_budget_sec", 240))
        self.detail_batch = max(1, int(cc.get("detail_batch", 10)))
        self.block_batch = max(1, int(cc.get("block_scan_batch", 50)))
        self.gap_scan_max = int(cc.get("gap_scan_max_blocks", 10_000))
        self.trace_rpcs = nd9["trace"]
        if self.NATIVE_EMITTER.get(chain) and self.trace_rpcs:
            log.warning("%s: 네이티브 시스템 이벤트 체인 — trace_rpcs 무시", chain)
            self.trace_rpcs = []
        self.start_block = int(cc.get("start_block") or 0)
        if cc.get("rps"):
            for u9 in dict.fromkeys(self.cfg_rpcs + self.logs_rpcs + self.state_rpcs):
                bf_engine.set_call_rate(u9, cc.get("rps"))
        self._trace_fail = {}
        self.gap_budget = float(cc.get("gap_scan_budget_sec", 1800))
        self.handover = str(cc.get("rpc_handover") or self.HANDOVER_DEFAULT.get(chain) or nd9.get("handover") or "adopt").lower()
        self.lanes_cfg = cc.get("rpc_lanes")
        caps9 = dict(nd9["caps"])
        self.logs_fallback = dict(nd9["fallback"])
        self.logs_primary = [u for u in self.logs_rpcs if u not in self.logs_fallback]
        self._log_caps = dict(caps9)
        self.addr_max = nd9["addr_max"]
        mc9 = nd9["multicall3"]
        self.mc_l1_block = bool(nd9.get("mc_l1_block"))
        self.multicall = str(mc9).lower() if (mc9 and str(mc9).lower().startswith("0x") and len(str(mc9)) == 42) else None
        bb9 = cc.get("rpc_backfill_budget_sec")
        self.bk_budget = float(bb9) if isinstance(bb9, (int, float)) and not isinstance(bb9, bool) else None
        try:
            self.poll_sec = min(max(float(cc.get("poll_sec") or cfg.get("evm_poll_sec") or 45), 5.0), 300.0)
        except (TypeError, ValueError):
            self.poll_sec = 45.0
        self.trace_mode = str(cc.get("rpc_trace") or "").lower() or None
        self.bk_span = max(1000, int(cc.get("rpc_backfill_span", 200_000)))
        self.block_trace = bool(cc.get("rpc_block_trace", True))
        self.cursor_path = os.path.join(common.STATE_DIR, f"cursor_evm_{chain}.json")
        self.cursor = common.read_json(self.cursor_path, {})
        self.emitted_path = os.path.join(common.STATE_DIR, f"emitted_evm_{chain}.json")
        self.emitted = set(common.read_json(self.emitted_path, []))
        _prev_w = {k for k in self.cursor if not k.startswith("_")}
        if _prev_w and not set(self.wallets).issubset(_prev_w) and self.emitted:
            log.warning("%s 새 관점 지갑 감지 — emitted %d건 초기화(재방출 허용)", chain, len(self.emitted))
            self.emitted.clear()
            common.atomic_write_json(self.emitted_path, [])
        self.since = {}
        for w9 in cfg.get("wallets") or []:
            a9 = str(w9.get("address") or "").lower()
            if w9.get("chain") == chain and a9 in self.wallets and w9.get("since_block") is not None:
                try:
                    st9 = w9.get("since_state") or [0, "0"]
                    self.since[a9] = (int(w9["since_block"]), int(st9[0]), str(int(st9[1])))
                except (TypeError, ValueError, IndexError):
                    continue
        self.pending_detail = {}
        self.rpc_meta_path = os.path.join(common.STATE_DIR, f"rpc_token_meta_{chain}.json")
        self.rpc_meta = common.read_json(self.rpc_meta_path, {})
        self.sym_path = os.path.join(common.STATE_DIR, f"rpc_token_sym_{chain}.json")
        self.sym = common.read_json(self.sym_path, {})
        self.progress = bf_engine.progress("evm")
        try:
            jobs9 = self._bk_jobs()
            if jobs9 or self.cursor.get("_hq"):
                self.progress.update(f"{chain}:rpc", phase="extend", unit="blocks",
                                     done=sum(max(0, int(j["done"]) - int(j["from"])) for j in jobs9.values()),
                                     total=max(1, sum(max(0, int(j["to"]) - int(j["from"])) for j in jobs9.values())),
                                     note="재기동 — 뒤 차선 이어서")
        except (TypeError, ValueError, KeyError) as e9:
            log.warning("%s 뒤 차선 진행률 기동 표시 실패(첫 사이클 뒤 표시): %s", chain, type(e9).__name__)
        self._pref = None
        self._txmeta = {}
        self._st_memo = {}
        self._bal_memo = {}
        self._snap_memo = {}
        self.last_scan_metrics = {}

    def _order(self, urls):
        ok = [u for u in urls if not bf_engine.gate(u).is_open()]
        ready = [u for u in ok if not bf_engine.gate(u).resting()]
        return (ready + [u for u in ok if u not in ready]) if ok else list(urls)

    def _rpc_call(self, method: str, params: list):
        if self._pref is not None:
            k = (method, json.dumps(params, sort_keys=True))
            if k in self._pref:
                return self._pref[k]
        last = None
        for url in self._order(self.cfg_rpcs):
            try:
                r = bf_engine.rpc_call(url, method, params, timeout=25, retries=1, allow_null=True)
            except Exception as e:
                last = e
                continue
            if r is not None:
                return r
            last = RuntimeError(f"rpc {method}: result null")
        raise last if last else RuntimeError("rpc 미구성")

    def _batch(self, calls: list, urls: list = None) -> list:
        last, all_bad = None, None
        for url in self._order(urls or self.cfg_rpcs):
            try:
                out = []
                cap = bf_engine.gate(url).batch_cap(40)
                for i in range(0, len(calls), cap):
                    out += bf_engine.rpc_batch(url, calls[i:i + cap], timeout=30, retries=1)
                if out and all(isinstance(r, Exception) for r in out):
                    all_bad = out
                    continue
                return out
            except Exception as e:
                last = e
        if all_bad is not None:
            return all_bad
        raise last if last else RuntimeError("rpc 미구성")

    def _head(self) -> int:
        h = int(self._rpc_call("eth_blockNumber", []), 16)
        self._log_head = h
        if self.chain_id is not None and not getattr(self, "_cid_ok", False):
            cid = int(self._rpc_call("eth_chainId", []), 16)
            if cid != self.chain_id:
                raise ChainDisabled(f"{self.chain}: RPC chainId 불일치 {cid} ≠ {self.chain_id} — 설정 확인")
            self._cid_ok = True
        return h

    def _states(self, pairs, strict: bool = False) -> dict:
        need = [p for p in dict.fromkeys(pairs) if p not in self._st_memo]
        if need:
            calls = []
            for w, b in need:
                calls += [("eth_getTransactionCount", [w, hex(b)]), ("eth_getBalance", [w, hex(b)])]
            got = {}
            last = None
            order9 = self._order(self.state_rpcs)
            transient9 = {}
            for url in order9:
                todo = [p for p in need if p not in got]
                if not todo:
                    break
                cl = []
                for w, b in todo:
                    cl += [("eth_getTransactionCount", [w, hex(b)]), ("eth_getBalance", [w, hex(b)])]
                try:
                    res = []
                    cap = bf_engine.gate(url).batch_cap(40)
                    for i in range(0, len(cl), cap):
                        res += bf_engine.rpc_batch(url, cl[i:i + cap], timeout=30, retries=1)
                except Exception as e:
                    last = e
                    if strict and getattr(e, "kind", None) != "pruned":
                        for p in todo:
                            transient9.setdefault(p, e)
                    continue
                for j, p in enumerate(todo):
                    n9, b9 = res[2 * j], res[2 * j + 1]
                    if isinstance(n9, Exception) or isinstance(b9, Exception):
                        last = n9 if isinstance(n9, Exception) else b9
                        if strict:
                            for err9 in (n9, b9):
                                if isinstance(err9, Exception) and getattr(err9, "kind", None) != "pruned":
                                    transient9.setdefault(p, err9)
                                    break
                        continue
                    got[p] = (int(n9, 16), int(b9, 16))
            if strict:
                unchecked9 = [u for u in self.state_rpcs if u not in order9]
                for p in need:
                    if p not in got and p in transient9:
                        raise transient9[p]
                    if p not in got and unchecked9:
                        raise bf_engine.NetError(f"{self.chain} 블록 {p[1]} 상태 — 노드 {len(unchecked9)}곳 서킷으로 미확인(다음 사이클)", "circuit")
            for p in need:
                if p not in got:
                    kind = getattr(last, "kind", None)
                    if kind == "pruned" or last is None:
                        e9 = StateUnavailable(f"{self.chain} 블록 {p[1]} 상태 없음(비아카이브): {str(last)[:120]}")
                        e9.blk = int(p[1])
                        raise e9
                    raise last
            self._st_memo.update(got)
            if len(self._st_memo) > 20000:
                self._st_memo.clear()
                self._st_memo.update(got)
        return {p: self._st_memo[p] for p in pairs}

    @property
    def bk_mode(self) -> bool:
        return isinstance(self.cursor.get("_handover"), dict) and self.lanes_cfg is not False

    def _trace_want(self, h: str, snap: dict) -> bool:
        mode9 = self.trace_mode or ("own" if self.bk_mode else "all")
        if mode9 != "own":
            return True
        if h in (self.cursor.get("_hq") or {}):
            return True
        tx = snap.get("tx") or {}
        if tx.get("status") != "ok" or (tx.get("from") or "").lower() not in set(self.wallets):
            return False
        inp = str(tx.get("raw_input") or "0x").lower()
        return len(inp) >= 10 and inp[:10] not in self.TRACE_SKIP_SELECTORS

    def _details(self, hashes, deadline: float = None, trace: bool = True) -> dict:
        out = {}
        hs = [h for h in dict.fromkeys(hashes) if h]
        myset = set(self.wallets)
        for i in range(0, len(hs), self.detail_batch):
            chunk = hs[i:i + self.detail_batch]
            if deadline is not None and time.time() > deadline:
                for h in hs[i:]:
                    out[h] = RuntimeError("상세 예산 소진 — 다음 사이클")
                break
            pref = {}

            def put(m, p, r):
                if r is not None and not isinstance(r, Exception):
                    pref[(m, json.dumps(p, sort_keys=True))] = r
            try:
                calls = []
                for h in chunk:
                    calls += [("eth_getTransactionByHash", [h]), ("eth_getTransactionReceipt", [h])]
                res = self._batch(calls)
                for (m, p), r in zip(calls, res):
                    put(m, p, r)
                rcs = [r for (m, _p), r in zip(calls, res) if m == "eth_getTransactionReceipt" and isinstance(r, dict)]
                blks = sorted({r["blockNumber"] for r in rcs if r.get("blockNumber")})
                if blks:
                    bc = [("eth_getBlockByNumber", [b9, False]) for b9 in blks]
                    for (m, p), r in zip(bc, self._batch(bc)):
                        put(m, p, r)
                cas = set()
                skip9 = set(self.NATIVE_MIRROR.get(self.chain) or ()) | {self.NATIVE_EMITTER.get(self.chain)}
                for rc in rcs:
                    for lg in rc.get("logs") or []:
                        tps = lg.get("topics") or []
                        if len(tps) == 3 and (tps[0] or "").lower() == self.TRANSFER and (
                                ("0x" + tps[1][-40:]).lower() in myset or ("0x" + tps[2][-40:]).lower() in myset):
                            cas.add((lg.get("address") or "").lower())
                cas -= skip9
                nd9 = self._nodec_reg()
                dc = [("eth_call", [{"to": ca, "data": "0x313ce567"}, "latest"]) for ca in sorted(cas)
                      if ca and ca not in self.rpc_meta and not nd9.perm(ca)]
                if dc:
                    for (m, p), r in zip(dc, self._batch(dc)):
                        put(m, p, r)
            except Exception as e:
                log.info("%s 상세 배치 실패 → 단건 경로: %s", self.chain, str(e)[:100])
            self._pref = pref
            try:
                for h in chunk:
                    try:
                        snap = self._rpc_synth_detail(h)
                        tx = self._rpc_call("eth_getTransactionByHash", [h]) or {}
                        self._txmeta[h] = {"nonce": int(tx.get("nonce") or "0x0", 16),
                                           "from": (tx.get("from") or "").lower(), "to": (tx.get("to") or "").lower(),
                                           "block": snap["tx"]["block_number"]}
                        out[h] = snap
                    except Exception as e:
                        out[h] = e
            finally:
                self._pref = None
        if self.trace_rpcs and trace:
            for h, snap in list(out.items()):
                if isinstance(snap, dict) and self._trace_want(h, snap):
                    try:
                        self._trace_internal(h, snap)
                    except Exception as e:
                        n9 = self._trace_fail[h] = self._trace_fail.get(h, 0) + 1
                        if n9 < self.TRACE_RETRY:
                            out[h] = RuntimeError(f"trace 실패 {n9}회(재시도): {common.safe_err(e)[:100]}")
                        else:
                            log.warning("%s trace %d회 실패 — internal 없이 확정 %s: %s", self.chain, n9, h[:12], str(e)[:80])
        self._fill_symbols([s for s in out.values() if isinstance(s, dict)])
        return out

    def _prestate(self, h: str, w: str) -> tuple:
        last = None
        for url in self._order(self.trace_rpcs):
            try:
                r = bf_engine.rpc_call(url, "debug_traceTransaction", [h, {"tracer": "prestateTracer"}], timeout=30, retries=1)
                e = {k.lower(): v for k, v in (r or {}).items()}.get(w) or {}
                return int(e.get("nonce") or 0), int(e.get("balance") or "0x0", 16)
            except Exception as e9:
                last = e9
        raise last if last else RuntimeError("trace 미구성")

    TRACE_RETRY = 3
    _VALUE_OPS = ("CALL", "CREATE", "CREATE2", "SELFDESTRUCT")

    def _trace_internal(self, h: str, snap: dict):
        last = None
        tr = None
        for url in self._order(self.trace_rpcs):
            try:
                tr = bf_engine.rpc_call(url, "debug_traceTransaction", [h, {"tracer": "callTracer"}], timeout=30, retries=1)
                break
            except Exception as e:
                last = e
        if not isinstance(tr, dict) or not tr.get("type"):
            rows9 = self._trace_parity(h)
            if rows9 is None:
                raise last if last else RuntimeError("trace 응답 형식 오류")
            snap["internal"] = rows9
            snap["internal_note"] = "trace"
            self._trace_fail.pop(h, None)
            return
        myset = set(self.wallets)
        out = []

        def walk(fr, failed):
            for ch in fr.get("calls") or []:
                bad = failed or bool(ch.get("error"))
                try:
                    v = int(ch.get("value") or "0x0", 16)
                except (TypeError, ValueError):
                    v = 0
                f9, t9 = (ch.get("from") or "").lower(), (ch.get("to") or "").lower()
                if v and str(ch.get("type") or "").upper() in self._VALUE_OPS and (f9 in myset or t9 in myset):
                    out.append({"from": f9, "to": t9, "value": str(v), "success": not bad})
                walk(ch, bad)
        walk(tr, bool(tr.get("error")))
        snap["internal"] = out
        snap["internal_note"] = "trace"
        self._trace_fail.pop(h, None)

    def _trace_parity(self, h: str):
        res = None
        for url in self._order(self.trace_rpcs):
            try:
                res = bf_engine.rpc_call(url, "trace_transaction", [h], timeout=30, retries=1)
                break
            except Exception:
                continue
        if not isinstance(res, list):
            return None
        myset = set(self.wallets)
        bad = [tuple(t.get("traceAddress") or []) for t in res if isinstance(t, dict) and t.get("error")]
        out = []
        for t in res:
            if not isinstance(t, dict):
                return None
            ta = tuple(t.get("traceAddress") or [])
            if not ta:
                continue
            ac = t.get("action") or {}
            typ = str(t.get("type") or "").lower()
            if typ == "call":
                if str(ac.get("callType") or "call").lower() != "call":
                    continue
                f9, t9, v9 = ac.get("from"), ac.get("to"), ac.get("value")
            elif typ == "create":
                f9, t9, v9 = ac.get("from"), (t.get("result") or {}).get("address"), ac.get("value")
            elif typ in ("suicide", "selfdestruct"):
                f9, t9, v9 = ac.get("address"), ac.get("refundAddress"), ac.get("balance")
            else:
                continue
            try:
                v = int(v9 or "0x0", 16)
            except (TypeError, ValueError):
                return None
            f9, t9 = str(f9 or "").lower(), str(t9 or "").lower()
            if v and (f9 in myset or t9 in myset):
                failed = any(ta[:len(b9)] == b9 for b9 in bad)
                out.append({"from": f9, "to": t9, "value": str(v), "success": not failed})
        return out

    @staticmethod
    def _dec_symbol(r):
        try:
            b = bytes.fromhex((r or "0x")[2:])
            if len(b) == 32:
                return b.rstrip(b"\x00").decode("utf-8", "ignore").strip() or None
            if len(b) >= 64:
                ln = int.from_bytes(b[32:64], "big")
                return b[64:64 + ln].decode("utf-8", "ignore").strip() or None
        except (ValueError, TypeError):
            pass
        return None

    def _fill_symbols(self, snaps):
        need = sorted({(tt.get("token") or {}).get("address") for s in snaps for tt in s.get("token_transfers") or []}
                      - set(self.sym) - {None, ""})
        if need:
            try:
                calls = [("eth_call", [{"to": ca, "data": "0x95d89b41"}, "latest"]) for ca in need]
                for ca, r in zip(need, self._batch(calls)):
                    if not isinstance(r, Exception):
                        self.sym[ca] = (self._dec_symbol(r) or "")[:16]
                common.atomic_write_json(self.sym_path, self.sym)
            except Exception as e:
                log.info("%s 토큰 심볼 조회 실패(무시): %s", self.chain, str(e)[:80])
        for s in snaps:
            for tt in s.get("token_transfers") or []:
                tok = tt.get("token") or {}
                if not tok.get("symbol") and self.sym.get(tok.get("address")):
                    tok["symbol"] = self.sym[tok["address"]]

    @staticmethod
    def _implied(snaps, w: str):
        own, nat = 0, 0
        for s in snaps:
            tx = s.get("tx") or {}
            fr, to = (tx.get("from") or "").lower(), (tx.get("to") or "").lower()
            if fr == w:
                own += 1
                nat -= int((tx.get("fee") or {}).get("value") or 0)
                if tx.get("type") == 126:
                    try:
                        nat += int(tx.get("op_mint") if tx.get("op_mint") is not None else (tx.get("value") or 0))
                    except (TypeError, ValueError):
                        pass
            if tx.get("status") != "ok":
                continue
            v = int(tx.get("value") or 0)
            if fr == w:
                nat -= v
            if to == w:
                nat += v
            for it in s.get("internal") or []:
                if it.get("success") is False or it.get("error"):
                    continue
                v2 = int(it.get("value") or 0)
                if (it.get("from") or "").lower() == w:
                    nat -= v2
                if (it.get("to") or "").lower() == w:
                    nat += v2
        return own, nat

    @staticmethod
    def _touches(s, w: str) -> bool:
        tx = s.get("tx") or {}
        if w in ((tx.get("from") or "").lower(), (tx.get("to") or "").lower()):
            return True
        return any(w in ((r.get("from") or "").lower(), (r.get("to") or "").lower())
                   for r in (s.get("token_transfers") or []) + (s.get("internal") or []))

    def _scan_blocks(self, lo: int, hi: int, w: str, deadline: float, reverse: bool = False, stop_nonces=None) -> tuple:
        found = {}
        want = stop_nonces
        b, top = (lo, hi)
        while b <= top:
            if want is not None and not want:
                return found, True
            if time.time() > deadline:
                return found, False
            if reverse:
                e, b0 = top, max(b, top - self.block_batch + 1)
                rng = (b0, e)
            else:
                rng = (b, min(top, b + self.block_batch - 1))
            calls = [("eth_getBlockByNumber", [hex(x), True]) for x in range(rng[0], rng[1] + 1)]
            for k9 in range(6):
                try:
                    res = self._batch(calls)
                    break
                except Exception as e9:
                    if k9 == 5 or time.time() + 20 > deadline:
                        raise
                    log.info("%s 블록 스캔 %d-%d 일시 실패(%s) — 20초 뒤 재시도", self.chain, rng[0], rng[1], str(e9)[:60])
                    time.sleep(20)
            for x, blk in zip(range(rng[0], rng[1] + 1), res):
                if isinstance(blk, Exception) or not isinstance(blk, dict):
                    raise RuntimeError(f"블록 {x} 조회 실패: {str(blk)[:80]}")
                for t in blk.get("transactions") or []:
                    if isinstance(t, dict) and w in ((t.get("from") or "").lower(), (t.get("to") or "").lower()):
                        found[(t.get("hash") or "").lower()] = x
                        if want is not None and (t.get("from") or "").lower() == w:
                            want.discard(int(t.get("nonce") or "0x0", 16))
            if want is not None and not want:
                return found, True
            if reverse:
                top = rng[0] - 1
            else:
                b = rng[1] + 1
        return found, True

    def _note(self, key: str, rec: dict):
        lst = self.cursor.setdefault(key, [])
        lst.append(dict(rec, ts=int(time.time())))
        del lst[:-self.NATIVE_LOG_MAX]

    def _bisect(self, w, a, b, sa, sb, pool, deadline):
        by_blk = {}
        for s in pool:
            by_blk.setdefault(s["tx"]["block_number"], []).append(s)

        def imp(x, y):
            return self._implied([s for k, v in by_blk.items() if x < k <= y for s in v], w)
        leaves, level = [], [(a, b, sa, sb)]
        while level:
            if time.time() > deadline:
                raise RuntimeError("이분 탐색 예산 소진")
            bad = []
            for (x, y, s1, s2) in level:
                o9, n9 = imp(x, y)
                if (s2[0] - s1[0], s2[1] - s1[1]) != (o9, n9):
                    bad.append((x, y, s1, s2))
            nxt = []
            mids = [((x + y) // 2) for (x, y, _s1, _s2) in bad if y - x > 1]
            st = self._states([(w, m) for m in mids]) if mids else {}
            for (x, y, s1, s2) in bad:
                if y - x <= 1:
                    leaves.append((x, y, s1, s2))
                    continue
                m = (x + y) // 2
                sm = st[(w, m)]
                nxt += [(x, m, s1, sm), (m, y, sm, s2)]
            level = nxt
        return leaves

    def _state_call(self, method: str, params: list):
        last = None
        for url in self._order(self.state_rpcs):
            try:
                return bf_engine.rpc_call(url, method, params, timeout=30, retries=1)
            except Exception as e:
                last = e
        raise last if last else RuntimeError("rpc 미구성")

    @staticmethod
    def _mc_encode(ws, target: str = None) -> str:
        tgt = int(target or RpcChainWatcher.MULTICALL3, 16)
        n = len(ws)
        out = ["252dba42", "%064x" % 32, "%064x" % n]
        out += ["%064x" % (32 * n + 160 * k) for k in range(n)]
        for w in ws:
            out += ["%064x" % tgt, "%064x" % 64, "%064x" % 36,
                    ("4d2301cc" + w[2:].lower().rjust(64, "0")).ljust(128, "0")]
        return "0x" + "".join(out)

    @staticmethod
    def _mc_decode(r: str, n: int, blk: int) -> list:
        b = bytes.fromhex(str(r or "0x")[2:])

        def word(o):
            if o + 32 > len(b):
                raise ValueError("multicall 응답 길이 부족")
            return int.from_bytes(b[o:o + 32], "big")
        if blk is not None and word(0) != int(blk):
            raise ValueError(f"multicall 블록 {word(0)} ≠ 요청 {blk}")
        arr = word(32)
        if word(arr) != n:
            raise ValueError("multicall 개수 불일치")
        base, out = arr + 32, []
        for k in range(n):
            o = base + word(base + 32 * k)
            if word(o) != 32:
                raise ValueError("multicall 항목 길이 ≠ 32")
            out.append(word(o + 32))
        return out

    @staticmethod
    def _rate_err(e) -> bool:
        return isinstance(e, bf_engine.NetError) and getattr(e, "kind", None) in ("http429", "quota", "budget", "circuit")

    def _mc_balances(self, ws, blk: int) -> int:
        bm9 = self.__dict__.setdefault("_bal_memo", {})
        sm9 = self.__dict__.setdefault("_st_memo", {})
        ws = [w for w in dict.fromkeys(ws) if (w, blk) not in sm9]
        if not self.multicall or not ws:
            return 0
        n9 = 0
        for i in range(0, len(ws), 150):
            part = ws[i:i + 150]
            try:
                r = self._state_call("eth_call", [{"to": self.multicall, "data": self._mc_encode(part, self.multicall)}, hex(int(blk))])
                bals = self._mc_decode(r, len(part), None if getattr(self, "mc_l1_block", False) else blk)
            except Exception as e:
                if (isinstance(e, ValueError) and "multicall 블록" not in str(e)) or bf_engine.revert_like(e):
                    log.warning("%s Multicall3 묶음 안 됨(%s) — 지갑별 nonce·잔고 조회로(config chains.%s.multicall3 로 주소 지정 가능)", self.chain,
                                common.safe_err(e)[:80], self.chain)
                    self.multicall = None
                elif self._rate_err(e):
                    self._mc_rate = e
                    log.info("%s Multicall3 잔고 묶음 한도 거절(다음 사이클): %s", self.chain, common.safe_err(e)[:100])
                else:
                    log.info("%s Multicall3 잔고 묶음 일시 실패(지갑별 조회로): %s", self.chain, common.safe_err(e)[:100])
                return n9
            try:
                nres = self._batch([("eth_getTransactionCount", [w, hex(int(blk))]) for w in part], self.state_rpcs)
            except Exception as e:
                nres = [e] * len(part)
            rl9 = next((x for x in nres if self._rate_err(x)), None)
            if rl9 is not None:
                self._mc_rate = rl9
            for w, v, nn in zip(part, bals, nres):
                bm9[(w, int(blk))] = int(v)
                if isinstance(nn, str):
                    try:
                        sm9[(w, int(blk))] = (int(nn, 16), int(v))
                        n9 += 1
                    except ValueError:
                        pass
        if len(bm9) > 50000:
            bm9.clear()
        return n9

    def _trace_block(self, blk: int) -> tuple:
        last = None
        res = None
        for url in self._order(self.trace_rpcs):
            try:
                res = bf_engine.rpc_call(url, "debug_traceBlockByNumber", [hex(int(blk)), {"tracer": "callTracer"}], timeout=60, retries=1)
                break
            except Exception as e:
                last = e
        if not isinstance(res, list):
            raise last if last else RuntimeError("블록 trace 응답 형식 오류")
        myset = set(self.wallets)
        out, unres, nfb9 = {}, [], 0
        hs9 = None
        if not res or any(not (isinstance(it, dict) and it.get("txHash")) for it in res):
            try:
                hs9 = [str(x if isinstance(x, str) else (x or {}).get("hash") or "").lower()
                       for x in (self._rpc_call("eth_getBlockByNumber", [hex(int(blk)), False]) or {}).get("transactions") or []]
            except Exception as e:
                raise RuntimeError(f"블록 trace 항목 txHash 없음 — 블록 tx 목록 실패: {common.safe_err(e)[:80]}")
            if len(hs9) != len(res) or not all(hs9):
                raise RuntimeError(f"블록 trace 항목 txHash 없음 — 개수 불일치 {len(res)} ≠ {len(hs9)}")
        for k9, it in enumerate(res):
            h9 = str((it.get("txHash") if isinstance(it, dict) else None) or (hs9[k9] if hs9 else "")).lower()
            r9 = it.get("result") if isinstance(it, dict) else None
            if (isinstance(it, dict) and it.get("error")) or not isinstance(r9, dict) or not r9.get("type"):
                tmp9 = {}
                if nfb9 >= self.BTRACE_ITEM_FALLBACK:
                    unres.append(h9)
                    continue
                nfb9 += 1
                try:
                    self._trace_internal(h9, tmp9)
                    if tmp9.get("internal"):
                        out[h9] = tmp9["internal"]
                except Exception as e:
                    unres.append(h9)
                    log.info("%s 블록 %d trace 항목 %s 실패(단건도 실패 — 재시도): %s", self.chain, blk, h9[:12], common.safe_err(e)[:80])
                continue
            rows = []

            def walk(fr, failed):
                for ch in fr.get("calls") or []:
                    bad = failed or bool(ch.get("error"))
                    try:
                        v = int(ch.get("value") or "0x0", 16)
                    except (TypeError, ValueError):
                        v = 0
                    f9, t9 = (ch.get("from") or "").lower(), (ch.get("to") or "").lower()
                    if v and str(ch.get("type") or "").upper() in self._VALUE_OPS and (f9 in myset or t9 in myset):
                        rows.append({"from": f9, "to": t9, "value": str(v), "success": not bad})
                    walk(ch, bad)
            walk(r9, bool(r9.get("error")))
            if rows:
                out[h9] = rows
        return out, unres

    BTRACE_ITEM_FALLBACK = 5
    LEAF_RETRY_N = 10
    LEAF_RETRY_SEC = 1800

    def _leaf_trace(self, w: str, y: int, pool: list, got) -> tuple:
        n_tr, added, failed = 0, [], False
        fail_h = set()
        for s9 in [s for s in pool if s["tx"]["block_number"] == y]:
            if s9["tx"].get("status") == "ok" and s9.get("internal_note") not in ("trace", "balance_delta"):
                try:
                    self._trace_internal(s9["tx"]["hash"].lower(), s9)
                    n_tr += 1
                    if s9["tx"]["hash"].lower() in self.emitted and s9.get("internal"):
                        self.__dict__.setdefault("_reemit", set()).add(s9["tx"]["hash"].lower())
                except Exception as e:
                    if not self._unsupported(e):
                        fail_h.add(s9["tx"]["hash"].lower())
                    log.info("%s 잎 블록 %d trace 실패: %s", self.chain, y, common.safe_err(e)[:80])
        if self.block_trace:
            unres9 = []
            try:
                frames, unres9 = self._trace_block(y)
                if unres9:
                    failed = True
                for s9 in [s for s in pool if s["tx"]["block_number"] == y and s["tx"]["hash"].lower() in fail_h]:
                    h9 = s9["tx"]["hash"].lower()
                    if h9 in unres9:
                        continue
                    s9["internal"] = list(frames.get(h9) or [])
                    s9["internal_note"] = "trace"
                    fail_h.discard(h9)
                    n_tr += 1
                    if h9 in self.emitted and s9["internal"]:
                        self.__dict__.setdefault("_reemit", set()).add(h9)
            except Exception as e:
                frames = {}
                failed = failed or not self._unsupported(e)
                log.info("%s 잎 블록 %d 블록 trace 실패: %s", self.chain, y, common.safe_err(e)[:80])
            pool_h = {s["tx"]["hash"].lower() for s in pool}
            q9 = bf_engine.quarantine_map(self.cursor)
            cand = [h for h, rows in frames.items() if h not in pool_h and h not in q9 and h not in got
                    and any((r.get("to") or "").lower() == w and r.get("success") is not False for r in rows)]
            if cand:
                dets = self._details(cand, trace=False)
                bad9 = [h for h in cand if not isinstance(dets.get(h), dict)]
                self._detail_fail_clear([h for h in cand if isinstance(dets.get(h), dict)])
                if bad9 and self._detail_fail_note(bad9, dets, blocks={h: y for h in bad9}):
                    failed = True
                for h in cand:
                    s9 = dets.get(h)
                    if isinstance(s9, dict) and int(s9["tx"]["block_number"]) == int(y):
                        s9["internal"] = frames[h]
                        s9["internal_note"] = "trace"
                        pool.append(s9)
                        added.append(h)
                        if h in self.emitted:
                            self.__dict__.setdefault("_reemit", set()).add(h)
        failed = failed or bool(fail_h)
        rec = {"kind": "internal_traced", "w": w[:10], "blk": y, "traced": n_tr, "added": [h[:14] for h in added]} if (n_tr or added) else None
        return rec, failed

    @staticmethod
    def _unsupported(e) -> bool:
        m = str(e).lower()
        return "-32601" in m or "does not exist" in m or "method not found" in m or "not supported" in m \
            or ("not available" in m and "method" in m)

    def _leaf_retry(self, w: str, y: int, ok: bool):
        lf = self.cursor.setdefault("_leaf_fail", {})
        k = f"{w[:12]}:{int(y)}"
        if ok:
            lf.pop(k, None)
            return False
        now = int(time.time())
        for k9 in [k9 for k9, v9 in lf.items() if now - int((v9 or [0, 0])[1]) > 86400]:
            lf.pop(k9, None)
        n9, t9 = (lf.get(k) or [0, now])[:2]
        n9 += 1
        lf[k] = [n9, t9]
        if n9 < self.LEAF_RETRY_N or now - int(t9) < self.LEAF_RETRY_SEC:
            common.atomic_write_json(self.cursor_path, self.cursor)
            raise RuntimeError(f"잎 블록 {y} trace·상세 일시 실패 {n9}회 — 커서 유지(다음 사이클)")
        lf.pop(k, None)
        self._note("_native_notes", {"kind": "leaf_giveup", "w": w[:10], "blk": int(y), "n": n9})
        ll = self.cursor.setdefault("_leaf_later", {})
        ll[k] = {"w": w, "blk": int(y), "at": now, "n": 0, "next": now + self.LEAF_LATER_SEC}
        for k9 in sorted(ll, key=lambda x: ll[x].get("at") or 0)[:-self.LEAF_LATER_MAX]:
            ll.pop(k9, None)
        return False

    LEAF_LATER_SEC = 600
    LEAF_LATER_MAX = 500
    LEAF_LATER_PER_CYCLE = 3

    def _leaf_later_step(self, head: int) -> int:
        ll = self.cursor.get("_leaf_later")
        if not isinstance(ll, dict) or not ll or not self.trace_rpcs:
            return 0
        now = int(time.time())
        n_emit, done = 0, 0
        for k in sorted(ll, key=lambda x: ll[x].get("next") or 0):
            e = ll.get(k) or {}
            if done >= self.LEAF_LATER_PER_CYCLE or int(e.get("next") or 0) > now:
                break
            done += 1
            w, y = str(e.get("w") or "").lower(), int(e.get("blk") or 0)
            try:
                frames, unres9 = self._trace_block(y)
                cand = [h for h, rows in frames.items() if any((r.get("to") or "").lower() == w and r.get("success") is not False for r in rows)]
                q9 = bf_engine.quarantine_map(self.cursor)
                cand = [h for h in cand if h not in q9]
                dets = self._details(cand, trace=False) if cand else {}
                bad = [h for h in cand if not isinstance(dets.get(h), dict)]
                if bad:
                    raise RuntimeError(f"상세 실패 {bad[0][:12]}: {common.safe_err(dets.get(bad[0]))[:80]}")
            except Exception as ex:
                if self._unsupported(ex):
                    ll.pop(k, None)
                    self._note("_native_notes", {"kind": "leaf_later_unsupported", "w": w[:10], "blk": y})
                else:
                    e["n"] = int(e.get("n") or 0) + 1
                    e["next"] = now + min(7200, self.LEAF_LATER_SEC * (2 ** min(e["n"], 4)))
                    e["err"] = common.safe_err(ex)[:80]
                continue
            for h in cand:
                s9 = dets[h]
                s9["internal"] = frames[h]
                s9["internal_note"] = "trace"
                if any(self._touches(s9, w9) for w9 in self.wallets):
                    self._emit(h, s9, head)
                    n_emit += 1
            if unres9:
                e["n"] = int(e.get("n") or 0) + 1
                e["next"] = now + min(7200, self.LEAF_LATER_SEC * (2 ** min(e["n"], 4)))
                e["err"] = f"블록 trace 항목 {len(unres9)}개 미해결"
                continue
            ll.pop(k, None)
            self._note("_native_notes", {"kind": "leaf_later_done", "w": w[:10], "blk": y, "found": len(cand)})
        if done:
            common.atomic_write_json(self.emitted_path, sorted(self.emitted))
            common.atomic_write_json(self.cursor_path, self.cursor)
        if n_emit:
            log.info("%s 나중에 다시 잎 블록 — internal 입금 tx %d건 방출", self.chain, n_emit)
        return n_emit

    STATE_LAG_NEAR = 10
    STATE_LAG_N = 10
    STATE_LAG_SEC = 1800
    STATE_LAG_OFF_SEC = 21600

    @staticmethod
    def _st_lag_map(v) -> dict:
        return dict(v) if isinstance(v, dict) and all(isinstance(x, dict) for x in v.values()) else {}

    def _state_lag_hold(self, nk: str, blk: int, head, last: int = None, c: int = None) -> None:
        sl = self._st_lag_map(self.cursor.get("_st_lag"))
        now = int(time.time())
        if int((sl.get("*") or {}).get("off") or 0) > now:
            return
        k9 = str(c)
        g = sl.get(k9) or {}
        held9 = bool(g)
        if nk != "_ns" or head is None or (not held9 and int(head) - int(blk) > max(64, self.STATE_LAG_NEAR * max(1, int(self.conf_depth or 0)))):
            return
        n9, t9 = int(g.get("n") or 0) + 1, int(g.get("t") or now)
        if n9 < self.STATE_LAG_N or now - t9 < self.STATE_LAG_SEC:
            sl[k9] = {"n": n9, "t": t9, "blk": int(blk), "to": None if last is None else int(last)}
            self.cursor["_st_lag"] = sl
            cur9 = common.read_json(self.cursor_path, {})
            cur9["_st_lag"] = dict(self._st_lag_map(cur9.get("_st_lag")), **{k9: sl[k9]})
            common.atomic_write_json(self.cursor_path, cur9)
            raise RuntimeError(f"블록 {blk} 상태 없음 — 헤드 {head} 근처라 노드 뒤처짐으로 봄({n9}회) · 커서 유지(다음 사이클 재시도)")
        sl.pop(k9, None)
        sl["*"] = {"off": now + self.STATE_LAG_OFF_SEC, "n": n9}
        self.cursor["_st_lag"] = sl
        self._note("_native_notes", {"kind": "state_lag_giveup", "blk": int(blk), "n": n9})
        log.warning("%s 라이브 꼬리 상태 없음 %d회·%d분 — 종전 누적으로 넘김(%d시간 쉼 · 남는 차이는 _native_gaps → 대사 흡수)", self.chain, n9,
                    (now - t9) // 60, self.STATE_LAG_OFF_SEC // 3600)

    def _explorer_era(self, w: str, blk: int, nk: str) -> bool:
        ho = self.cursor.get("_handover")
        if isinstance(ho, dict) and ho.get("from") == "explorer":
            if nk == "_bkns":
                return True
            cs = ho.get("curs")
            cv = cs.get(w) if isinstance(cs, dict) else ho.get("src_max")
        else:
            cs = self.cursor.get("_xcurs")
            cv = cs.get(w) if isinstance(cs, dict) else None
        return isinstance(cv, int) and int(blk) <= cv

    def _sell_pick(self, cands: list, w: str, rb: int) -> tuple:
        def no_back(s):
            tx = s.get("tx") or {}
            inp = str(tx.get("raw_input") or "0x").lower()
            return (tx.get("from") or "").lower() == w and (tx.get("to") or "").lower() != w and (inp == "0x" or inp[:10] in self.TRACE_SKIP_SELECTORS)
        c2 = [s for s in cands if not no_back(s)]
        if len(c2) == 1:
            return c2, None
        hd9 = self.__dict__.get("_sell_wd") or {}
        hit = []
        for s in c2 or cands:
            hn = hd9.get(str((s.get("tx") or {}).get("hash") or "").lower())
            if hn and hn[0] == w and int(hn[2]) == int(rb):
                hit.append((s, hn[1]))
        if len(hit) == 1:
            return [hit[0][0]], hit[0][1]
        return cands, None

    def _sell_fill(self, pool: list, w: str, diff: int, nk: str) -> int:
        hd9 = self.__dict__.get("_sell_wd") or {}
        got = []
        for s in pool:
            tx = s.get("tx") or {}
            h9 = str(tx.get("hash") or "").lower()
            hn = hd9.get(h9)
            if not hn or hn[0] != w or tx.get("status") != "ok":
                continue
            if any((it.get("to") or "").lower() == w for it in s.get("internal") or []):
                continue
            if self._explorer_era(w, int(tx.get("block_number") or 0), nk):
                continue
            got.append((s, hn))
        if not got or sum(int(hn[2]) for _s, hn in got) != int(diff):
            return 0
        for s9, hn in got:
            s9.setdefault("internal", []).append({"from": hn[1], "to": w, "value": str(int(hn[2])), "success": True, "attr": "balance_delta"})
            s9["internal_note"] = "balance_delta"
            if s9["tx"]["hash"].lower() in self.emitted:
                self.__dict__.setdefault("_reemit", set()).add(s9["tx"]["hash"].lower())
        return len(got)

    def _native(self, w: str, c: int, last: int, pool: list, deadline: float, nk: str = "_ns", head: int = None) -> dict:
        ns = (self.cursor.get(nk) or {}).get(w)
        own_i, nat_i = self._implied([s for s in pool if self._touches(s, w)], w)
        try:
            sl = self._states([(w, last)])[(w, last)]
        except StateUnavailable as e:
            if ns is None:
                return {"ns": None}
            self._state_lag_hold(nk, getattr(e, "blk", last), head, last, c)
            return {"ns": [ns[0], ns[1], ns[2], int(ns[3]) + own_i, str(int(ns[4]) + nat_i)]}
        if ns is None:
            self._note("_native_notes", {"w": w[:10], "kind": "baseline", "blk": last})
            return {"ns": [last, sl[0], str(sl[1]), 0, "0"]}
        n0, b0 = int(ns[1]), int(ns[2])
        dn, db = sl[0] - n0, sl[1] - b0
        eo, en = int(ns[3]) + own_i, int(ns[4]) + nat_i
        if (dn, db) == (eo, en):
            return {"ns": [last, sl[0], str(sl[1]), 0, "0"]}
        recs = []
        if int(ns[0]) == c:
            try:
                leaves = self._bisect(w, c, last, (n0, b0), sl, pool, deadline)
            except StateUnavailable as e:
                self._state_lag_hold(nk, getattr(e, "blk", last), head, last, c)
                leaves = None
            if leaves is not None:
                for (x, y, s1, s2) in leaves:
                    got, done9 = self._scan_blocks(y, y, w, max(deadline, time.time() + 60))
                    if not done9:
                        raise RuntimeError(f"잎 블록 {y} 스캔 미완 — 다음 사이클 재시도")
                    q9 = bf_engine.quarantine_map(self.cursor)
                    new = [h for h in got if h not in {s["tx"]["hash"].lower() for s in pool} and h not in q9]
                    if new:
                        dets = self._details(new)
                        bad = [h for h in new if not isinstance(dets.get(h), dict) and not (h in self.emitted and dets.get(h) is None)]
                        self._detail_fail_clear([h for h in new if isinstance(dets.get(h), dict)])
                        left9 = self._detail_fail_note(bad, dets, blocks={h: y for h in bad}) if bad else []
                        if left9:
                            raise RuntimeError(f"잎 블록 {y} tx 상세 실패 {left9[0][:12]}: {dets.get(left9[0])}")
                        pool.extend(dets[h] for h in new if isinstance(dets.get(h), dict))
                        for h9 in new:
                            s8 = dets.get(h9)
                            if h9 in self.emitted and isinstance(s8, dict) and s8.get("internal_note") == "trace" and s8.get("internal"):
                                self.__dict__.setdefault("_reemit", set()).add(h9)
                    here = [s for s in pool if s["tx"]["block_number"] == y and self._touches(s, w)]
                    o9, n9 = self._implied(here, w)
                    rn, rb = (s2[0] - s1[0]) - o9, (s2[1] - s1[1]) - n9
                    if rn == 0 and rb > 0 and self.trace_rpcs:
                        rec9, fail9 = self._leaf_trace(w, y, pool, got)
                        if rec9:
                            recs.append(rec9)
                        here = [s for s in pool if s["tx"]["block_number"] == y and self._touches(s, w)]
                        o9, n9 = self._implied(here, w)
                        rn, rb = (s2[0] - s1[0]) - o9, (s2[1] - s1[1]) - n9
                        if rn == 0 and rb == 0:
                            self._leaf_retry(w, y, True)
                            continue
                        if fail9:
                            self._leaf_retry(w, y, False)
                            recs.append({"kind": "leaf_deferred", "w": w[:10], "blk": y, "native": str(rb)})
                            continue
                    held9 = self._held_block(y, {s["tx"]["hash"].lower() for s in pool}, got) if (rn == 0 and rb > 0) else []
                    if held9:
                        recs.append({"kind": "held", "w": w[:10], "blk": y, "native": str(rb), "txs": [h[:14] for h in held9[:5]]})
                        continue
                    if rn == 0 and rb > 0 and not self._explorer_era(w, y, nk):
                        cands = [s for s in here if s["tx"].get("status") == "ok"]
                        src9 = None
                        if len(cands) > 1:
                            cands, src9 = self._sell_pick(cands, w, rb)
                        if len(cands) == 1:
                            s9 = cands[0]
                            s9.setdefault("internal", []).append(
                                {"from": src9 or (s9["tx"].get("to") or s9["tx"].get("from") or "").lower(), "to": w,
                                 "value": str(rb), "success": True, "attr": "balance_delta"})
                            s9["internal_note"] = "balance_delta"
                            if s9["tx"]["hash"].lower() in self.emitted:
                                self.__dict__.setdefault("_reemit", set()).add(s9["tx"]["hash"].lower())
                            recs.append({"kind": "internal_attributed", "w": w[:10], "blk": y, "value": str(rb),
                                         "tx": s9["tx"]["hash"][:14]})
                            continue
                    if rn or rb:
                        recs.append(dict({"kind": "unexplained", "w": w[:10], "blk": y, "nonce": rn, "native": str(rb)},
                                         **({"era": "explorer"} if rn == 0 and rb > 0 and self._explorer_era(w, y, nk) else {})))
                for r in recs:
                    self._note("_native_notes", r)
                    getattr(log, "warning" if r["kind"] in ("unexplained", "held") else "info")(
                        "%s 네이티브 %s: %s", self.chain, r["kind"], r)
                return {"ns": [last, sl[0], str(sl[1]), 0, "0"]}
        pool_own = sorted((self._txmeta[s["tx"]["hash"].lower()]["nonce"], s["tx"]["block_number"])
                          for s in pool if (s["tx"].get("from") or "").lower() == w
                          and s["tx"]["hash"].lower() in self._txmeta)
        known = {int(n): int(bk) for n, bk in ((self.cursor.get("_nonces") or {}).get(w) or {}).items()}
        known.update(pool_own)
        ranges = {}
        start = int(ns[0])
        for j in range(n0, sl[0]):
            if j in known:
                continue
            lower = [bk for n, bk in known.items() if n < j]
            upper = [bk for n, bk in known.items() if n > j]
            lo = max(lower) if lower else start + 1
            hi = min(upper) if upper else last
            ranges.setdefault((lo, hi, bool(lower), bool(upper)), []).append(j)
        added = 0
        gdl = max(deadline, time.time() + self.gap_budget)
        for (lo, hi, has_lo, has_hi), js in sorted(ranges.items()):
            wins = [(lo, hi, False)]
            stop = None
            if hi - lo + 1 > self.gap_scan_max:
                M = self.gap_scan_max
                stop = set(js)
                if has_hi and not has_lo:
                    wins = [(hi - M + 1, hi, True)]
                elif has_lo and not has_hi:
                    wins = [(lo, lo + M - 1, False)]
                elif has_lo and has_hi:
                    wins = [(lo, lo + M // 2 - 1, False), (hi - M // 2 + 1, hi, True)]
                else:
                    wins = []
                recs.append({"kind": "gap_window", "w": w[:10], "from": lo, "to": hi, "nonces": js[:10],
                             "windows": wins})
            got, done = {}, True
            for (a9, b9, rev9) in wins:
                g9, d9 = self._scan_blocks(a9, b9, w, gdl, reverse=rev9, stop_nonces=stop)
                got.update(g9)
                done = done and d9
            q9 = bf_engine.quarantine_map(self.cursor)
            new = [h for h in got if h not in {s["tx"]["hash"].lower() for s in pool} and h not in self.emitted and h not in q9]
            if new:
                dets = self._details(new)
                ok9 = [dets[h] for h in new if isinstance(dets.get(h), dict)]
                bad9 = [h for h in new if not isinstance(dets.get(h), dict)]
                self._detail_fail_clear([h for h in new if isinstance(dets.get(h), dict)])
                if bad9 and self._detail_fail_note(bad9, dets, blocks=got):
                    raise RuntimeError("nonce 틈 tx 상세 실패 — 다음 사이클 재시도")
                pool.extend(ok9)
                added += len(ok9)
            if not done:
                raise RuntimeError("nonce 틈 스캔 예산 소진 — 다음 사이클 재시도")
        own2, nat2 = self._implied([s for s in pool if self._touches(s, w)], w)
        eo2, en2 = int(ns[3]) + own2, int(ns[4]) + nat2
        if (dn, db) != (eo2, en2) and dn == eo2 and db > en2:
            n9 = self._sell_fill(pool, w, db - en2, nk)
            if n9:
                own2, nat2 = self._implied([s for s in pool if self._touches(s, w)], w)
                eo2, en2 = int(ns[3]) + own2, int(ns[4]) + nat2
                recs.append({"kind": "sell_filled", "w": w[:10], "from": int(ns[0]), "to": last, "txs": n9})
        if (dn, db) != (eo2, en2):
            rec = {"kind": "gap", "w": w[:10], "from": int(ns[0]), "to": last, "nonce_missing": dn - eo2,
                   "native_diff": str(db - en2), "added": added}
            cands = [(s["tx"]["block_number"], s["tx"]["hash"]) for s in pool if (s["tx"].get("from") or "").lower() == w]
            fo = (self.cursor.get("_first_own") or {}).get(w)
            if fo:
                cands.append((int(fo[0]), fo[1]))
            first = min(cands) if cands else None
            if first is not None and self.trace_rpcs:
                try:
                    pre = self._prestate(first[1], w)
                    rec["pre_first_own"] = {"blk": first[0], "nonce": pre[0], "balance": str(pre[1])}
                except Exception as e:
                    rec["pre_first_own"] = {"err": common.safe_err(e)[:80]}
            recs.append(rec)
        elif added:
            recs.append({"kind": "gap_resolved", "w": w[:10], "from": int(ns[0]), "to": last, "added": added})
        for r in recs:
            self._note("_native_gaps" if r["kind"] == "gap" else "_native_notes", r)
            getattr(log, "warning" if r["kind"] == "gap" else "info")(
                "%s 네이티브 %s: %s", self.chain, r["kind"], r)
        return {"ns": [last, sl[0], str(sl[1]), 0, "0"]}

    def _window_start(self, safe: int) -> int:
        lo = min(max(0, self.start_block), int(safe))
        if self.backfill_full:
            return lo
        tgt = [time.time() - self.backfill_months * 30 * 86400] if self.backfill_months > 0 else []
        s9 = bf_engine.SINCE.target(self.chain)
        if s9:
            tgt.append(s9)
        if not tgt:
            return safe
        if lo and self._block_ts(lo) >= int(min(tgt)):
            return lo
        return max(lo, bf_engine.block_at_ts(self._block_ts, int(min(tgt)), 0, int(safe)))

    def _since_reinit(self, safe: int):
        if self.cursor.get("_rpc_v") != self.VERSION or self.backfill_full or isinstance(self.cursor.get("_since_ext"), dict):
            return
        s9 = bf_engine.SINCE.target(self.chain)
        if not s9 or self.cursor.get("_since_seen") == int(s9):
            return
        if self.bk_mode:
            self._since_reinit_bk(safe, int(s9))
            return
        old = int(self.cursor.get("_start") or 0)
        new = self._window_start(safe) if old > max(0, self.start_block) else old
        ws = [w for w in self.wallets if isinstance(self.cursor.get(w), int)]
        if new >= old or not ws:
            self.cursor["_since_seen"] = int(s9)
            common.atomic_write_json(self.cursor_path, self.cursor)
            return
        sk9 = self.cursor.get("_since_skip")
        if isinstance(sk9, dict) and sk9.get("target") == int(s9) and time.time() - float(sk9.get("at") or 0) < 6 * 3600:
            return
        try:
            st0 = self._states([(w, new) for w in ws])
        except StateUnavailable as e:
            st0, err9 = {}, common.safe_err(e)[:120]
        else:
            err9 = None if all((w, new) in st0 for w in ws) else "일부 지갑 상태 누락"
        if err9:
            self.cursor["_since_skip"] = {"target": int(s9), "at": int(time.time()), "err": err9}
            common.atomic_write_json(self.cursor_path, self.cursor)
            log.warning("%s 과거 창 확장 보류(시작 블록 %d 상태 조회 불가 — 아카이브 노드 필요, 6시간 뒤 재시도): %s", self.chain, new, err9)
            return
        self.cursor.pop("_since_skip", None)
        ts9 = time.strftime("%Y%m%d_%H%M%S")
        common.atomic_write_json(self.cursor_path + f".pre_since_{ts9}", self.cursor)
        ns = self.cursor.setdefault("_ns", {})
        self.cursor["_since_ext"] = {"from": int(new), "to": old, "at": int(time.time()),
                                     "live": {w: int(self.cursor[w]) for w in ws}, "ns": {w: ns.get(w) for w in ws}}
        for w in ws:
            self.cursor[w] = int(new)
            if (w, new) in st0:
                n9, b9 = st0[(w, new)]
                ns[w] = [int(new), n9, str(b9), 0, "0"]
            else:
                ns.pop(w, None)
        self.cursor.pop("_scan", None)
        self.cursor["_start"] = int(new)
        self.cursor["_since_seen"] = int(s9)
        common.atomic_write_json(self.cursor_path, self.cursor)
        log.warning("★%s 과거 창 확장(backfill_since %s): 앞 구간 블록 %d → %d 만 훑음(지갑 %d · 보존본 .pre_since_%s)★",
                    self.chain, time.strftime("%Y-%m-%d", time.gmtime(s9)), new, old, len(ws), ts9)

    def _since_reinit_bk(self, safe: int, s9: int):
        if self._bk_jobs():
            return
        old = int(self.cursor.get("_start") or 0)
        new = self._window_start(safe) if old > max(0, self.start_block) else old
        ws = [w for w in self.wallets if isinstance(self.cursor.get(w), int)]
        if new >= old or not ws:
            self.cursor["_since_seen"] = int(s9)
            common.atomic_write_json(self.cursor_path, self.cursor)
            return
        sk9 = self.cursor.get("_since_skip")
        if isinstance(sk9, dict) and sk9.get("target") == int(s9) and time.time() - float(sk9.get("at") or 0) < 6 * 3600:
            return
        try:
            b0 = self._baselines(ws, new)
            err9 = None if all(w in b0 for w in ws) else "일부 지갑 상태 누락"
        except StateUnavailable as e:
            b0, err9 = {}, common.safe_err(e)[:120]
        if err9:
            self.cursor["_since_skip"] = {"target": int(s9), "at": int(time.time()), "err": err9}
            common.atomic_write_json(self.cursor_path, self.cursor)
            log.warning("%s 과거 창 확장 보류(시작 블록 %d 상태 조회 불가, 6시간 뒤 재시도): %s", self.chain, new, err9)
            return
        self.cursor.pop("_since_skip", None)
        bkns = self.cursor.setdefault("_bkns", {})
        for w in ws:
            self.cursor["_bk:" + w] = {"from": int(new), "to": int(old), "done": int(new), "why": "extend"}
            bkns[w] = b0[w]
        self.cursor["_start"] = int(new)
        self.cursor["_since_seen"] = int(s9)
        common.atomic_write_json(self.cursor_path, self.cursor)
        log.warning("★%s 과거 창 확장(backfill_since %s): 앞 구간 블록 %d → %d 를 뒤 차선으로(지갑 %d · 라이브 꼬리는 계속)★",
                    self.chain, time.strftime("%Y-%m-%d", time.gmtime(s9)), new, old, len(ws))

    def _since_ext_done(self):
        ext9 = self.cursor.get("_since_ext")
        ns = self.cursor.setdefault("_ns", {})
        for w, v in (ext9.get("live") or {}).items():
            self.cursor[w] = int(v)
            b9 = (ext9.get("ns") or {}).get(w)
            if b9 is None:
                ns.pop(w, None)
            else:
                ns[w] = b9
        self.cursor.pop("_since_ext", None)
        self.cursor.pop("_scan", None)
        common.atomic_write_json(self.cursor_path, self.cursor)
        log.info("%s 과거 창 확장(앞 구간 %d → %d) 완주 — 지갑 커서 복원", self.chain, int(ext9.get("from") or 0), int(ext9.get("to") or 0))

    def _baselines(self, ws, blk: int) -> dict:
        out = {}
        if int(blk) == 0:
            return {w: [0, 0, "0", 0, "0"] for w in ws}
        for i in range(0, len(ws), 20):
            part = ws[i:i + 20]
            try:
                st = self._states([(w, int(blk)) for w in part])
            except StateUnavailable:
                st = {}
                for w in part:
                    try:
                        st.update(self._states([(w, int(blk))]))
                    except StateUnavailable:
                        pass
            for w in part:
                if (w, int(blk)) in st:
                    n9, b9 = st[(w, int(blk))]
                    out[w] = [int(blk), n9, str(b9), 0, "0"]
        return out

    def _es_late_overlap(self, cc: dict) -> int:
        if not cc.get("etherscan_chainid"):
            return 0
        try:
            sec = max(60, int(((self.cfg.get("etherscan") or {}).get("int_lag_sec")) or EtherscanWatcher.INT_LAG_SEC))
        except (TypeError, ValueError):
            sec = EtherscanWatcher.INT_LAG_SEC
        return max(int(self.conf_depth or 12), -(-int(self.bpd or 7200) * sec // 86400))

    def _adopt_explorer(self, safe: int):
        old = dict(self.cursor)
        cc = self.cfg["chains"][self.chain]
        start = self._window_start(safe)
        ov = max(0, min(int(cc.get("rescan_overlap_blocks") or 0), 5000))
        ov = max(ov, self._es_late_overlap(cc))
        curs = {w: int(old[w]) for w in self.wallets if isinstance(old.get(w), int) and not isinstance(old.get(w), bool)}
        live = max(int(start), min(min(curs.values()) - ov, int(safe))) if curs else int(safe)
        ipm = old.get("_ext_internal_pending") if isinstance(old.get("_ext_internal_pending"), dict) else {}
        rr0 = [r for r in (ipm.get("ranges") or []) if isinstance(r, dict) and not r.get("done")]
        leaf9 = [r for r in rr0 if r.get("kind") == "leaf" and isinstance(r.get("wallet"), str) and type(r.get("to_block")) is int]
        rr = [r for r in rr0 if r.get("kind") != "leaf"]
        any_w = any(not isinstance(r.get("wallet"), str) or not r.get("wallet") for r in rr)
        int_ws = {w for w in curs if any_w or any(str(r.get("wallet") or "").lower() == w for r in rr)}
        fr9 = [int(r["from_block"]) for r in rr if isinstance(r.get("from_block"), int)]
        bk_from = min([int(start)] + fr9)
        if bk_from >= live:
            int_ws = set()
        jobs = {}
        for w in self.wallets:
            bj9 = old.get("_bfjob") if isinstance(old.get("_bfjob"), dict) else {}
            first9 = (w not in curs or ("_bfes:" + w) in old or ("_bf:" + w) in old
                      or (bj9.get("kind") != "extend" and w in [str(x).lower() for x in (bj9.get("wallets") or [])]))
            why = "new" if first9 else ("internal" if w in int_ws else None)
            to9 = live
            if why is None:
                cv9 = old.get("_cov:" + w)
                if isinstance(cv9, int) and not isinstance(cv9, bool) and cv9 > bk_from + 1:
                    why, to9 = "extend", min(int(cv9), live)
            if why and bk_from < to9:
                jobs[w] = {"from": bk_from, "to": int(to9), "done": bk_from, "why": why}
        hq = {}
        hqp9 = os.path.join(common.STATE_DIR, f"hq_left_{self.chain}.json")
        for k9 in list((common.read_json(hqp9, {}) or {}).keys()) \
                + list((common.read_json(os.path.join(common.STATE_DIR, f"enrich_{self.chain}.json"), {}) or {}).keys()) \
                + list((common.read_json(os.path.join(common.STATE_DIR, f"pending_detail_{self.chain}.json"), {}) or {}).keys()) \
                + [h for h in (ipm.get("hashes") or []) if isinstance(h, str)] + list((ipm.get("items") or {}).keys()):
            if isinstance(k9, str) and k9.startswith("0x"):
                hq[k9.lower()] = 0
        ns = self._baselines(list(self.wallets), live)
        bkns = self._baselines(sorted(jobs), bk_from) if jobs else {}
        if set(ns) != set(self.wallets) or set(bkns) != set(jobs):
            miss9 = len(set(self.wallets) - set(ns)) + len(set(jobs) - set(bkns))
            raise StateUnavailable(f"{self.chain} 인계 기준점 {miss9}건 없음(블록 {live}·{bk_from} 상태) — 탐색기 커서 유지, 아카이브 상태 노드 필요")
        bp = self.cursor_path + ".explorer_legacy"
        if os.path.exists(bp):
            bp += time.strftime("_%Y%m%d_%H%M%S")
        common.atomic_write_json(bp, old)
        if self.emitted:
            self.emitted.clear()
            common.atomic_write_json(self.emitted_path, [])
        cur = {"_rpc_v": self.VERSION, "_start": int(start), "_ns": ns, "_bkns": bkns,
               "_handover": {"from": "explorer" if curs else "fresh", "at": int(time.time()), "live": int(live), "start": int(start),
                             "bk_from": int(bk_from), "overlap": ov, "adopted": len(curs), "new": sum(1 for j in jobs.values() if j["why"] == "new"),
                             "internal": sum(1 for j in jobs.values() if j["why"] == "internal"),
                             "extend": sum(1 for j in jobs.values() if j["why"] == "extend"), "hq": len(hq),
                             "src_min": min(curs.values()) if curs else None, "src_max": max(curs.values()) if curs else None,
                             "curs": dict(curs),
                             "backup": os.path.basename(bp)}}
        for k9, v9 in old.items():
            if str(k9).startswith("_cov:") or k9 in ("_quarantine", "_detail_fail", "_q_released"):
                cur[k9] = v9
        if isinstance(old.get("_quarantine_left"), dict):
            q9 = cur["_quarantine"] if isinstance(cur.get("_quarantine"), dict) else cur.setdefault("_quarantine", {})
            for h9, v9 in old["_quarantine_left"].items():
                q9.setdefault(h9, v9)
        for w in self.wallets:
            cur[w] = int(live)
        for w, j in jobs.items():
            cur["_bk:" + w] = j
        if hq:
            cur["_hq"] = hq
        lln9 = {}
        for k9, v9 in (old.get("_leaf_later_left") or {}).items():
            if isinstance(v9, dict) and isinstance(v9.get("w"), str) and type(v9.get("blk")) is int and v9["w"].lower() in self.wallets:
                lln9[k9] = dict(v9, next=0)
        for r9 in leaf9:
            w9 = r9["wallet"].lower()
            if w9 in self.wallets:
                lln9.setdefault(f"{w9[:12]}:{int(r9['to_block'])}", {"w": w9, "blk": int(r9["to_block"]), "at": int(time.time()), "n": 0, "next": 0})
        if lln9:
            cur["_leaf_later"] = lln9
        if bf_engine.SINCE.target(self.chain):
            cur["_since_seen"] = int(bf_engine.SINCE.target(self.chain))
        self.cursor = cur
        common.atomic_write_json(self.cursor_path, self.cursor)
        if hq:
            common.atomic_write_json(os.path.join(common.STATE_DIR, f"enrich_{self.chain}.json"), {})
            if os.path.exists(hqp9):
                common.atomic_write_json(hqp9, {})
        log.warning("★%s 탐색기 → RPC 전용 인계: 지갑 커서 %d개 이어받음(%s~%s → 라이브 %d, 겹침 %d) · 새 지갑 첫 백필 %d · internal 재훑기 %d"
                    "(블록 %d → %d, 뒤 차선) · 인계 큐 %d건 · 원본 %s★", self.chain, len(curs), cur["_handover"]["src_min"],
                    cur["_handover"]["src_max"], live, ov, cur["_handover"]["new"], cur["_handover"]["internal"], bk_from, live, len(hq),
                    os.path.basename(bp))

    def _init(self, safe: int):
        self._since_reinit(safe)
        if self.cursor.get("_rpc_v") != self.VERSION:
            has9 = any(not str(k).startswith("_") and isinstance(v, int) and not isinstance(v, bool) for k, v in self.cursor.items())
            back9 = isinstance(self.cursor.get("_handback"), dict) and self.cursor["_handback"].get("from") == "rpc"
            if (self.handover == "adopt" and (has9 or back9) and self.lanes_cfg is not False) or (not has9 and self.lanes_cfg is True):
                self._adopt_explorer(safe)
            else:
                old = {k: v for k, v in self.cursor.items()}
                if old:
                    common.atomic_write_json(self.cursor_path + ".explorer_legacy", old)
                start = self._window_start(safe)
                self.cursor = {"_rpc_v": self.VERSION, "_start": int(start)}
                xc9 = {k: v for k, v in old.items() if not str(k).startswith("_") and isinstance(v, int) and not isinstance(v, bool)}
                self.cursor["_xcurs"] = xc9
                if bf_engine.SINCE.target(self.chain):
                    self.cursor["_since_seen"] = int(bf_engine.SINCE.target(self.chain))
                common.atomic_write_json(self.cursor_path, self.cursor)
                log.info("★%s RPC 전용 추적 초기화 — 창 시작 블록 %d (safe %d, 종전 커서는 .explorer_legacy)★",
                         self.chain, start, safe)
        if "_xcurs" not in self.cursor and not isinstance(self.cursor.get("_handover"), dict):
            lg9 = common.read_json(self.cursor_path + ".explorer_legacy", {})
            self.cursor["_xcurs"] = {k: v for k, v in (lg9.items() if isinstance(lg9, dict) else ())
                                     if not str(k).startswith("_") and isinstance(v, int) and not isinstance(v, bool)}
        start = int(self.cursor["_start"])
        ns = self.cursor.setdefault("_ns", {})
        new_ws = []
        for w in self.wallets:
            if not isinstance(self.cursor.get(w), int):
                sb = self.since.get(w)
                if sb is not None and sb[0] > start and sb[0] < int(safe):
                    self.cursor[w] = sb[0]
                    ns[w] = [sb[0], sb[1], sb[2], 0, "0"]
                    continue
                new_ws.append(w)
        if new_ws and self.bk_mode:
            lv = [int(self.cursor[w]) for w in self.wallets if isinstance(self.cursor.get(w), int)]
            live = min(lv) if lv else int(safe)
            b0 = self._baselines(new_ws, live)
            bb = self._baselines(new_ws, start) if start < live else {}
            if set(b0) != set(new_ws) or (start < live and set(bb) != set(new_ws)):
                raise StateUnavailable(f"{self.chain} 새 지갑 기준점 없음 — 합류 보류(커서 유지 · 다음 사이클), 아카이브 상태 노드 필요")
            bkns = self.cursor.setdefault("_bkns", {})
            for w in new_ws:
                self.cursor[w] = live
                if w in b0:
                    ns[w] = b0[w]
                if start < live:
                    self.cursor["_bk:" + w] = {"from": start, "to": live, "done": start, "why": "new"}
                    if w in bb:
                        bkns[w] = bb[w]
            common.atomic_write_json(self.cursor_path, self.cursor)
            log.warning("★%s 새 지갑 %d개 합류 — 라이브 %d 부터 · 옛 구간 %d → %d 는 뒤 차선★", self.chain, len(new_ws), live, start, live)
            new_ws = []
        st0 = {}
        if new_ws and start > 0:
            for w9 in new_ws:
                try:
                    st0.update(self._states([(w9, start)]))
                except StateUnavailable:
                    pass
        for w in new_ws:
            self.cursor[w] = start
            if start == 0:
                ns[w] = [0, 0, "0", 0, "0"]
            elif (w, start) in st0:
                n9, b9 = st0[(w, start)]
                ns[w] = [start, n9, str(b9), 0, "0"]
        self._legacy_queues()

    def _legacy_queues(self):
        pp = os.path.join(common.STATE_DIR, f"pending_detail_{self.chain}.json")
        ep = os.path.join(common.STATE_DIR, f"enrich_{self.chain}.json")
        pend = common.read_json(pp, {})
        if pend:
            dets = self._details(sorted(h.lower() for h in pend))
            for h in sorted(dets):
                if isinstance(dets[h], dict) and h not in self.emitted:
                    self._emit(h, dets[h], 0)
            left = {h: v for h, v in pend.items() if not isinstance(dets.get(h.lower()), dict)}
            common.atomic_write_json(self.emitted_path, sorted(self.emitted))
            if self.bk_mode:
                common.atomic_write_json(self.cursor_path, self.cursor)
            common.atomic_write_json(pp, left)
        enr = common.read_json(ep, {})
        if enr:
            if self.bk_mode:
                hq = self.cursor.setdefault("_hq", {})
                for h in enr:
                    if isinstance(h, str) and h.startswith("0x"):
                        hq.setdefault(h.lower(), 0)
                common.atomic_write_json(self.cursor_path, self.cursor)
                log.warning("%s 탐색기 enrich 큐 %d건 → 인계 큐(_hq — RPC trace 로 internal 채움)로 옮기고 비움", self.chain, len(enr))
            else:
                log.warning("%s 탐색기 enrich 큐 잔존 — RPC 경로는 네이티브 정합으로 대체, 큐 비움", self.chain)
            common.atomic_write_json(ep, {})


    def _detail_fail_note(self, bad: list, dets: dict, blocks: dict = None) -> list:
        return bf_engine.detail_fail_note(self.cursor, bad, dets, self.chain, "rpc_detail", log, self.__dict__.setdefault("_df_seen", set()),
                                          blocks=blocks)

    def _held_block(self, blk: int, pool_hashes: set, got=()) -> list:
        out = [h for h, v in bf_engine.quarantine_map(self.cursor).items()
               if isinstance(v, dict) and v.get("blk") is not None and int(v["blk"]) == int(blk)]
        out += [h for h, b in (self.cursor.get("_q_released") or {}).items() if int(b) == int(blk) and h not in pool_hashes]
        out += [h for h in got if h not in pool_hashes]
        return sorted(set(out))

    def _detail_fail_clear(self, ok_hashes):
        bf_engine.detail_fail_clear(self.cursor, ok_hashes)

    def _quarantine_retry(self, head: int):
        due = bf_engine.quarantine_due(self.cursor)
        if not due:
            return 0
        try:
            dets = self._details(due)
        except Exception as e:
            dets = {h: e for h in due}
        n = 0
        for h in due:
            snap = dets.get(h)
            if isinstance(snap, dict):
                if h not in self.emitted and any(self._touches(snap, w) for w in self.wallets):
                    self._emit(h, snap, head)
                    n += 1
                bf_engine.quarantine_result(self.cursor, h, True, self.chain, "rpc_detail", log)
            else:
                bf_engine.quarantine_result(self.cursor, h, False, self.chain, "rpc_detail", log, err=snap)
        common.atomic_write_json(self.emitted_path, sorted(self.emitted))
        common.atomic_write_json(self.cursor_path, self.cursor)
        return n

    def _retention_check(self, ws: list, c: int, target: int, f9: int) -> int:
        now = time.time()
        cands = self.cursor.get("_retention_cand") if isinstance(self.cursor.get("_retention_cand"), dict) else {}
        cands = {k: v for k, v in cands.items() if isinstance(v, dict) and now - float(v.get("last") or 0) < 86400}
        k = str(int(c) + 1)
        cd = cands.get(k) if isinstance(cands.get(k), dict) else {"n": 0, "first": int(now)}
        cd["floor"] = min(int(cd.get("floor") or f9), int(f9))
        cd["n"] = int(cd.get("n") or 0) + 1
        cd["last"] = int(now)
        cands[k] = cd
        self.cursor["_retention_cand"] = cands
        why = None
        ts9 = None
        if cd["n"] < RETENTION_CONFIRM_N or now - float(cd.get("first") or now) < RETENTION_CONFIRM_SEC:
            why = f"확인 중 {cd['n']}/{RETENTION_CONFIRM_N}회"
        else:
            try:
                ts9 = int(self._block_ts(int(cd["floor"])))
            except Exception as e:
                why = f"보관 시작 블록 시각 조회 실패({common.safe_err(e)[:60]}) — 다음 사이클"
            if ts9 is not None and now - ts9 < RETENTION_MIN_AGE_SEC:
                why = (f"보관 시작이 {time.strftime('%Y-%m-%d %H:%M', time.localtime(ts9))}로 너무 최근 — 노드 이상일 수 있어 자동으로 "
                       "건너뛰지 않음(사람 확인)")
        if why:
            common.atomic_write_json(self.cursor_path, self.cursor)
            msg9 = f"노드 보관 범위 밖(블록 {int(c) + 1}~{int(cd['floor']) - 1}, 첫 보관 블록 {cd['floor']}) — {why}"
            if isinstance(self.last_scan_metrics, dict):
                self.last_scan_metrics["stop"] = msg9
            log.warning("%s %s", self.chain, msg9)
            return c
        to9 = min(int(cd["floor"]) - 1, int(target))
        return self._retention_skip(ws, c, to9, ts9 if to9 == int(cd["floor"]) - 1 else None, int(cd["n"]), cand_key=k)

    def _retention_skip(self, ws: list, c: int, to: int, floor_ts=None, n_obs: int = 0, cand_key=None) -> int:
        def _ts(b):
            try:
                return int(self._block_ts(int(b)))
            except Exception:
                return None
        if floor_ts is None:
            floor_ts = _ts(to + 1)
        from_ts = _ts(c + 1)
        st0 = {}
        for w in ws:
            try:
                st0.update(self._states([(w, int(to))], strict=True))
            except StateUnavailable:
                pass
        if cand_key is not None:
            cands9 = self.cursor.get("_retention_cand") if isinstance(self.cursor.get("_retention_cand"), dict) else {}
            cands9.pop(str(cand_key), None)
            if not cands9:
                self.cursor.pop("_retention_cand", None)
        gaps = self.cursor.setdefault("_retention_gaps", [])
        gaps.append({"kind": "node_retention", "from": int(c) + 1, "to": int(to), "from_ts": from_ts, "floor_ts": floor_ts,
                     "ws": [w[:10] for w in ws], "at": int(time.time()), "n_obs": int(n_obs),
                     "host": urllib.parse.urlsplit(self.logs_rpcs[0]).hostname if self.logs_rpcs else None})
        del gaps[:-20]
        ns = self.cursor.setdefault("_ns", {})
        nb = 0
        for w in ws:
            self.cursor[w] = int(to)
            if (w, int(to)) in st0:
                n9, b9 = st0[(w, int(to))]
                ns[w] = [int(to), n9, str(b9), 0, "0"]
                nb += 1
            else:
                ns.pop(w, None)
        self.cursor.pop("_scan", None)
        common.atomic_write_json(self.cursor_path, self.cursor)
        log.warning("★%s 로그 노드 보관 밖 옛 구간 = 미수집 범위로 기록하고 넘어감: 블록 %d~%d%s · 지갑 %d(네이티브 새 기준점 %d) — "
                    "그 앞 보유는 잔고 대조(기초 잔고)로 맞춤★", self.chain, c + 1, to,
                    f"(~{time.strftime('%Y-%m-%d', time.localtime(floor_ts))} 이전)" if floor_ts else "", len(ws), nb)
        return int(to)

    def _scan_logs(self, ws: list, c: int, target: int, deadline: float) -> tuple:
        mx = self.addr_max or max(1, len(ws))
        found, last, floor9, stop9, mets = {}, int(target), None, None, {}
        caps0 = self.__dict__.setdefault("_log_caps", {})
        fb0 = getattr(self, "logs_fallback", None) or {}
        prim0 = getattr(self, "logs_primary", None) or self.logs_rpcs
        head9 = self.__dict__.get("_log_head")
        if isinstance(head9, int) and c >= head9 - bf_engine.RPC_NEAR_HEAD:
            try:
                import nodekeys
                key9 = [u for u in prim0 if nodekeys.is_key_node(u)]
            except Exception:
                key9 = []
            if key9 and len(key9) < len(prim0):
                prim0 = [u for u in prim0 if u not in key9]
                fb0 = dict(fb0)
                for u9 in key9:
                    fb0.setdefault(u9, int(caps0.get(u9) or self.span))
        for i in range(0, len(ws), mx):
            pads = ["0x" + w[2:].rjust(64, "0") for w in ws[i:i + mx]]
            scanner = bf_engine.LogScanner(
                prim0, self.TRANSFER, pads, span=self.span, min_span=self.min_span, timeout=25, log=_SCAN_LOG,
                caps=dict(caps0), fallback={u: int(caps0.get(u) or cap9) for u, cap9 in fb0.items()},
                name=f"{self.chain} getLogs",
                positions={1: [self.TRANSFER, self.APPROVAL, self.WETH_DEPOSIT, self.WETH_WITHDRAWAL], 2: self.TRANSFER},
                head_guard=(self.cfg["chains"][self.chain].get("logs_head_guard") is not False),
                soft=self.__dict__.setdefault("_log_soft", {}))
            f9, l9 = scanner.scan(c + 1, last, deadline=deadline)
            for u9, cap9 in (getattr(scanner, "caps", None) or {}).items():
                if isinstance(cap9, int) and cap9 > 0:
                    caps0[u9] = min(int(caps0.get(u9) or cap9), cap9)
            for k9, v9 in (getattr(scanner, "metrics", None) or {}).items():
                if isinstance(v9, (int, float)):
                    mets[k9] = mets.get(k9, 0) + v9
            stop9 = getattr(scanner, "last_stop", None) or stop9
            found.update(f9)
            if l9 < last:
                last = l9
            if l9 <= c:
                fl9 = getattr(scanner, "retention_floor", None)
                floor9 = fl9 if (isinstance(fl9, int) and not isinstance(fl9, bool)) else None
                break
        self.last_scan_metrics = dict(mets, stop=stop9)
        return {h: b for h, b in found.items() if b <= last}, last, floor9

    def _emit(self, h: str, snap: dict, head: int):
        rec = {"v": 1, "kind": "evm_tx", "chain": self.chain, "txhash": h, "snapshot": snap,
               "wallets": self.wallets, "observed_head": head, "ts": int(time.time())}
        if self.bk_mode:
            rec["wallets"] = [w for w in self.wallets if self._touches(snap, w)] or self.wallets
            if snap.get("internal_note") in ("trace", "balance_delta") and snap.get("internal"):
                rec["repair"] = "int_fill"
        self.writer.append(rec)
        self.emitted.add(h)
        hq = self.cursor.get("_hq")
        if isinstance(hq, dict) and snap.get("internal_note") == "trace":
            hq.pop(h, None)

    def _advance(self, ws: list, c: int, target: int, head: int, deadline: float, bk: bool = False) -> int:
        sk, nk = ("_bkscan", "_bkns") if bk else ("_scan", "_ns")
        self._reemit = set()
        sc = self.cursor.get(sk)
        if isinstance(sc, dict) and sc.get("frm") == c + 1 and sorted(sc.get("ws") or []) == sorted(ws) \
                and int(sc.get("to") or 0) > c:
            found, last = dict(sc.get("found") or {}), int(sc["to"])
        else:
            found, last, f9 = self._scan_logs(ws, c, target, deadline)
            if last <= c:
                if not bk and isinstance(f9, int) and f9 > c + 1:
                    return self._retention_check(ws, c, target, f9)
                return c
            self.cursor[sk] = {"frm": c + 1, "to": last, "ws": sorted(ws),
                               "found": {h: b for h, b in found.items() if h not in self.emitted}}
            common.atomic_write_json(self.cursor_path, self.cursor)
        qset = bf_engine.quarantine_map(self.cursor)
        todo = [h for h in found if h not in self.emitted and h not in qset]
        memo9 = self.__dict__.setdefault("_snap_memo", {})
        need = [h for h in todo if h not in memo9]
        dets = self._details(need, deadline=deadline + 120) if need else {}
        for h in need:
            if isinstance(dets.get(h), dict):
                memo9[h] = json.loads(json.dumps(dets[h]))
        for h in todo:
            if h not in dets and h in memo9:
                dets[h] = json.loads(json.dumps(memo9[h]))
        if len(memo9) > 20000:
            memo9.clear()
        bad = [h for h in todo if not isinstance(dets.get(h), dict)]
        self._detail_fail_clear([h for h in todo if isinstance(dets.get(h), dict)])
        if bad:
            left = self._detail_fail_note(bad, dets, blocks=found)
            if left:
                log.warning("%s 상세 %d건 실패 — 커서 유지(스캔 체크포인트로 재시도): %s", self.chain, len(left),
                            str(dets.get(left[0]))[:120])
                return c
            todo = [h for h in todo if isinstance(dets.get(h), dict)]
        pool = [dets[h] for h in todo]
        self._mc_rate = None
        n_mc = self._mc_balances(ws, last) if self.multicall else 0
        if n_mc < len(ws) and self._mc_rate is not None:
            raise self._mc_rate
        if n_mc < len(ws):
            try:
                self._states([(w, last) for w in ws if (w, last) not in self.__dict__.setdefault("_st_memo", {})])
            except StateUnavailable:
                pass
        new_ns = {}
        for w in ws:
            new_ns[w] = (self._native(w, c, last, pool, deadline + 120, nk) if bk else self._native(w, c, last, pool, deadline + 120, head=head))["ns"]
        if not bk and all(isinstance(new_ns.get(w), list) and int(new_ns[w][0]) == int(last) for w in ws):
            sl9 = self._st_lag_map(self.cursor.get("_st_lag"))
            sl9.pop(str(c), None)
            sl9.pop("*", None)
            if sl9:
                self.cursor["_st_lag"] = sl9
            else:
                self.cursor.pop("_st_lag", None)
        n_emit = 0
        for s in sorted(pool, key=lambda s: (s["tx"]["block_number"], s["tx"]["hash"])):
            h = s["tx"]["hash"].lower()
            re9 = self.__dict__.get("_reemit") or set()
            if (h in self.emitted and h not in re9) or not any(self._touches(s, w) for w in self.wallets):
                continue
            self._emit(h, s, head)
            re9.discard(h)
            n_emit += 1
        common.atomic_write_json(self.emitted_path, sorted(self.emitted))
        nm = self.cursor.setdefault("_nonces", {})
        for s in pool:
            m9 = self._txmeta.get(s["tx"]["hash"].lower())
            if m9 and m9["from"] in ws:
                nm.setdefault(m9["from"], {})[str(m9["nonce"])] = m9["block"]
                fo = self.cursor.setdefault("_first_own", {}).get(m9["from"])
                if not fo or m9["block"] < int(fo[0]):
                    self.cursor["_first_own"][m9["from"]] = [m9["block"], s["tx"]["hash"]]
        ns = self.cursor.setdefault(nk, {})
        fin = []
        for w in ws:
            if bk:
                job = self.cursor.get("_bk:" + w)
                if isinstance(job, dict):
                    job["done"] = int(last)
                    if int(last) >= int(job.get("to") or 0):
                        fin.append(w)
            else:
                self.cursor[w] = last
            if new_ns.get(w) is not None:
                ns[w] = new_ns[w]
        for w in fin:
            j9 = self.cursor.pop("_bk:" + w, None) or {}
            ns.pop(w, None)
            log.info("★%s 뒤 차선 완주 %s(%s) — 블록 %s → %s★", self.chain, w[:10], j9.get("why"), j9.get("from"), j9.get("to"))
        self.cursor.pop(sk, None)
        for h in todo:
            memo9.pop(h, None)
        common.atomic_write_json(self.cursor_path, self.cursor)
        if n_emit:
            log.info("%s rpc 발견 %d tx 방출 (%s블록 %d→%d, 지갑 %d)", self.chain, n_emit, "옛 구간 " if bk else "", c, last, len(ws))
        return last

    def _bk_jobs(self) -> dict:
        return {w: self.cursor["_bk:" + w] for w in self.wallets if isinstance(self.cursor.get("_bk:" + w), dict)}

    def _bk_step(self, head: int, deadline: float) -> tuple:
        adv, stalled = 0, False
        bud9 = max(1.0, deadline - time.time())
        span = max(2000, min(self.bk_span, int(self.cursor.get("_bkspan") or self.bk_span)))
        while time.time() < deadline:
            jobs = self._bk_jobs()
            if not jobs:
                break
            groups = {}
            for w, j in jobs.items():
                groups.setdefault(int(j.get("done") or 0), []).append(w)
            d = min(groups)
            ws = groups[d]
            to = min(int(jobs[w].get("to") or 0) for w in ws)
            tgt = min(to, d + span)
            if tgt <= d:
                break
            t0 = time.time()
            try:
                got = self._advance(ws, d, tgt, head, deadline, bk=True)
            except StateUnavailable as e:
                got = d
                log.info("%s 뒤 차선 상태 조회 불가(다음 사이클): %s", self.chain, e)
            el = time.time() - t0
            if got <= d:
                stalled = True
                span = max(2000, span // 2)
                self.cursor["_bkspan"] = int(span)
                break
            adv += got - d
            if got >= tgt and el < bud9 / 3:
                span = min(self.bk_span, span * 2)
            self.cursor["_bkspan"] = int(span)
        if not self._bk_jobs() and self.cursor.get("_hq") and time.time() < deadline:
            self._hq_step(head, deadline)
        return adv, stalled

    HQ_BATCH = 20
    HQ_FAIL_MAX = 5

    def _hq_step(self, head: int, deadline: float) -> int:
        hq = self.cursor.get("_hq")
        if not isinstance(hq, dict) or not hq:
            return 0
        n = 0
        keys = sorted(hq)
        for i in range(0, len(keys), self.HQ_BATCH):
            if time.time() >= deadline:
                break
            part = [h for h in keys[i:i + self.HQ_BATCH] if h in hq]
            if not part:
                continue
            dets = self._details(part, deadline=deadline + 60, trace=False)
            for h in part:
                s9 = dets.get(h)
                err9 = None
                if isinstance(s9, dict):
                    try:
                        self._trace_internal(h, s9)
                    except Exception as e:
                        err9 = e
                        if self._unsupported(e):
                            hq.pop(h, None)
                            self._note("_native_notes", {"kind": "hq_untraced", "tx": h[:14]})
                            continue
                    if err9 is None:
                        if s9.get("internal") and any(self._touches(s9, w) for w in self.wallets):
                            self._emit(h, s9, head)
                            n += 1
                        else:
                            hq.pop(h, None)
                        continue
                else:
                    err9 = s9
                if "예산 소진" in str(err9) or not bf_engine.detail_err_deterministic(err9):
                    continue
                hq[h] = int(hq.get(h) or 0) + 1
                if hq[h] >= self.HQ_FAIL_MAX:
                    hq.pop(h, None)
                    self._note("_native_notes", {"kind": "hq_fail", "tx": h[:14], "err": common.safe_err(err9)[:80]})
                    log.warning("%s 인계 큐 %s 결정적 실패 %d회 — 뺌(internal 미확인 · 대사 흡수): %s", self.chain, h[:12], self.HQ_FAIL_MAX,
                                common.safe_err(err9)[:100])
            common.atomic_write_json(self.emitted_path, sorted(self.emitted))
            common.atomic_write_json(self.cursor_path, self.cursor)
        if n:
            log.info("%s 인계 큐 internal 채움 %d건 방출(남은 %d)", self.chain, n, len(hq))
        return n

    def cycle(self):
        tc0 = time.time()
        if self.cursor.pop("_synced_at", None) is not None:
            common.atomic_write_json(self.cursor_path, self.cursor)
        self._st_memo = {}
        self._bal_memo = {}
        self._df_seen = set()
        head = self._head()
        safe = head - self.conf_depth
        self._init(safe)
        try:
            self._quarantine_retry(head)
        except Exception as e:
            log.info("%s 격리 tx 재시도 실패(다음 사이클): %s", self.chain, str(e)[:120])
        t0 = time.time()
        deadline = t0 + self.cycle_budget
        complete = True
        groups = {}
        for w in self.wallets:
            groups.setdefault(int(self.cursor[w]), []).append(w)
        advanced, stalled = 0, False
        ext9 = self.cursor.get("_since_ext") if isinstance(self.cursor.get("_since_ext"), dict) else None
        tgt = min(safe, int(ext9["to"])) if ext9 else safe
        for c in sorted(groups, reverse=self.bk_mode):
            if c >= tgt:
                continue
            if time.time() >= deadline:
                complete = False
                break
            try:
                got = self._advance(groups[c], c, tgt, head, deadline)
            except StateUnavailable as e:
                got = c
                log.info("%s 상태 조회 불가(다음 사이클): %s", self.chain, e)
            if got > c:
                advanced += got - c
            else:
                stalled = True
            if got < tgt:
                complete = False
        if ext9:
            complete = False
            if tgt == int(ext9["to"]) and all(int(self.cursor[w]) >= tgt for w in self.wallets if isinstance(self.cursor.get(w), int)):
                self._since_ext_done()
        if self.cursor.get("_leaf_later"):
            try:
                self._leaf_later_step(head)
            except Exception as e:
                log.info("%s 나중에 다시 잎 블록 재시도 실패(다음 사이클): %s", self.chain, common.safe_err(e)[:120])
        bk9 = None
        if self.bk_mode and (self._bk_jobs() or self.cursor.get("_hq")):
            bud9 = self.bk_budget if self.bk_budget is not None else max(10.0, self.poll_sec - (time.time() - tc0) - 5.0)
            bk_dl = min(deadline, time.time() + bud9)
            bk_adv, bk_stall = 0, False
            if time.time() < bk_dl:
                try:
                    bk_adv, bk_stall = self._bk_step(head, bk_dl)
                except Exception as e:
                    bk_stall = True
                    log.warning("%s 뒤 차선 실패(다음 사이클 이어서): %s", self.chain, common.redact_urls(common.safe_err(e))[:160])
                    try:
                        cur9 = common.read_json(self.cursor_path, {})
                        for k9 in [k for k in self.cursor if k.startswith("_bk:") or k in ("_bkns", "_bkscan", "_hq", "_bkspan")]:
                            if k9 in cur9:
                                self.cursor[k9] = cur9[k9]
                            else:
                                self.cursor.pop(k9, None)
                    except Exception:
                        pass
            jobs9 = self._bk_jobs()
            if jobs9 or self.cursor.get("_hq"):
                tot9 = sum(max(0, int(j["to"]) - int(j["from"])) for j in jobs9.values())
                left9 = sum(max(0, int(j["to"]) - int(j["done"])) for j in jobs9.values())
                bk9 = {"wallets": len(jobs9), "new": sum(1 for j in jobs9.values() if j.get("why") == "new"),
                       "internal": sum(1 for j in jobs9.values() if j.get("why") == "internal"),
                       "extend": sum(1 for j in jobs9.values() if j.get("why") == "extend"),
                       "done_min": min((int(j["done"]) for j in jobs9.values()), default=None),
                       "to": max((int(j["to"]) for j in jobs9.values()), default=None),
                       "pct": round(100.0 * (tot9 - left9) / tot9, 1) if tot9 else 100.0, "advanced": bk_adv, "stalled": bk_stall,
                       "hq": len(self.cursor.get("_hq") or {}),
                       "ids": sorted(w[:6] for w, j in jobs9.items() if j.get("why") == "new")[:3]}
        start = int(self.cursor.get("_start") or 0)
        cmin = min(int(self.cursor[w]) for w in self.wallets) if self.wallets else safe
        new_left = bool(bk9 and bk9["new"])
        if complete and cmin >= safe and not new_left:
            self.cursor["_synced_at"] = int(time.time())
        if len(self._txmeta) > 50000:
            self._txmeta.clear()
        common.atomic_write_json(self.cursor_path, self.cursor)
        common.atomic_write_json(self.rpc_meta_path, self.rpc_meta)
        if bk9 is not None:
            self.progress.update(f"{self.chain}:rpc", phase="extend", unit="blocks",
                                 done=sum(max(0, int(j["done"]) - int(j["from"])) for j in self._bk_jobs().values()),
                                 total=max(1, sum(max(0, int(j["to"]) - int(j["from"])) for j in self._bk_jobs().values())),
                                 note=(self.last_scan_metrics or {}).get("stop"))
        else:
            self.progress.update(f"{self.chain}:rpc", phase="live" if complete else ("extend" if self.cursor.get("_since_ext") else "scan"),
                                 unit="blocks",
                                 done=max(0, cmin - start), total=max(1, safe - start),
                                 note=(self.last_scan_metrics or {}).get("stop"))
        gaps = self.cursor.get("_native_gaps") or []
        progressing = (not complete) and advanced > 0 and not stalled
        self._health_cycle("rpc", head, safe, ok=complete or progressing,
                           err=None if (complete or progressing) else RuntimeError("부분 진행(예산·노드)"),
                           rpc_backfill=({"from": start, "cursor": cmin, "safe": safe, "advanced": advanced,
                                          "pct": round(100.0 * max(0, cmin - start) / max(1, safe - start), 1)}
                                         if progressing else None),
                           current_source=urllib.parse.urlsplit(self.cfg_rpcs[0]).hostname,
                           emitted=len(self.emitted), scan=self.last_scan_metrics or None,
                           native_verified=sorted(w[:10] for w, v in (self.cursor.get("_ns") or {}).items()
                                                  if v and int(v[0]) >= cmin),
                           native_gaps=gaps[-5:] or None,
                           retention=retention_summary(self.cursor),
                           native_unexplained=[r for r in (self.cursor.get("_native_notes") or [])
                                               if r.get("kind") == "unexplained"][-5:] or None,
                           rpc_bk=bk9)
        if not complete:
            log.info("%s rpc 사이클 부분 진행: 커서 %d / safe %d (%.0fs)", self.chain, cmin, safe, time.time() - t0)


def main():
    common.ensure_dirs()
    cfg = common.load_config()
    bf_engine.configure(cfg)
    bf_engine.es_budget_install_sigterm()
    addr_tier.ACTIVE_PROC = True
    poll = int(cfg.get("evm_poll_sec", 45))
    watchers = []
    by_chain = {}
    for w in cfg["wallets"]:
        if w.get("type", "evm") == "evm":
            by_chain.setdefault(w["chain"], []).append(w["address"])
    shared_writer = SegmentWriter(os.path.join(common.INBOX_DIR, "evm"))
    es_key = common.read_env_file().get("TJ_ETHERSCAN_KEY", "")
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
            except Exception as e:
                n9 = bf_engine.health("evm").fail(f"{rd.chain}:rpclog", e, "rpclog")
                bf_engine.health("evm").flush()
                lv = bf_engine.LogDebounce.level(n9)
                if lv:
                    getattr(log, lv)("%s rpclog cycle 실패 %d회 연속(다음 주기 재시도): %s", rd.chain, n9, common.redact_urls(str(e)))
                try:
                    st9 = common.read_json(rd.state_path, {})
                    if st9.pop("rpc_synced_at", None) is not None:
                        common.atomic_write_json(rd.state_path, st9)
                    rd.st = st9
                except Exception:
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
            cfg2 = common.load_config()
        except (Exception, SystemExit) as e:
            log.warning("활동 게이트 반영용 설정 재적재 실패(다음 주기): %s", e)
            continue
        try:
            for b9 in list(addr_tier.BOOKS.values()):
                b9.reload_cfg(cfg2)
            addr_tier.plan_stretch(list(addr_tier.BOOKS.values()), cfg2)
        except Exception as e:
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
            except (Exception, SystemExit) as e:
                log.error("★%s 새 체인 워처 생성 실패(다음 주기 재시도): %s★", c, e)
                continue
            cur_pairs[c] = ws9
            t = threading.Thread(target=chain_loop, args=(wt,), daemon=True, name=c)
            threads.append(t)
            t.start()
            log.warning("★활동 게이트: 새 체인 %s 추적 시작 (지갑 %d)★", c, len(ws9))


if __name__ == "__main__":
    main()
