"""tj-web: dashboard HTTP server and state builder."""
from __future__ import annotations

import base64
import gzip
import hashlib
import bisect
import copy
import hmac
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
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, getcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
if __name__ == "__main__":
    common.cpu_reserve_apply()
    _SQLITE_MEMSTAT_OFF = common.sqlite_memstatus_off()
import db as dbm
import pricing
import balcheck
import chainsweep
import websnap
import health
import spamguard
import depaddr
import onboarding
import demo_data
import login_auth
import lpdec
import lpchain
import lpsol
import bf_engine
import outflow_match
import xfer_match
import sale_match
import flow_trace
import xchain_match
import search_index
import wow
import wow2
import ops_requests
import other_assets
import nft
import candles
import histcurve
import sellchart
import buychart
import netpace
import coverage_limits
import buildproc
import rawtx_cache
import acct_norm
import rabby
import salelink
import day_memo
import alert_prefs
import alert_watch
import flowev
import addr_ai
try:
    from review_prompt import PROMPT_VERSION as REVIEW_PV
except Exception:
    REVIEW_PV = None
try:
    from review_prompt import WEEKLY_PROMPT_VERSION as REVIEW_WPV
except Exception:
    REVIEW_WPV = REVIEW_PV
try:
    from review_prompt import LEN_KEYS as REVIEW_LEN_KEYS, len_key as review_len_key
except Exception:
    REVIEW_LEN_KEYS, review_len_key = (), None


try:
    import review_progress
except Exception:
    review_progress = None
REVIEW_PROGRESS_PATH = os.path.join(common.STATE_DIR, "review_progress.json")
try:
    import perp_dex
    PERP_NAMES = dict(perp_dex.NAMES)
except Exception:
    perp_dex, PERP_NAMES = None, {}
FUT_CEX = ("binance", "bybit", "okx")
PERP_KEYS = tuple(PERP_NAMES)
try:
    import fut_rcpt
except Exception:
    fut_rcpt = None
FUT_FEE_SYM = "선물 수수료·펀딩"
_FUT_SYM_RE = re.compile(r"[-_/]?(USDT|USDC|USD)([-_]?(SWAP|PERP|M))?$", re.I)


def fut_sym(s) -> str:
    s = str(s or "")
    b = _FUT_SYM_RE.sub("", s, count=1)
    return (b or s) + " 무기한"


FUT_T_MIN_MS = 1420070400000


def _fin(v):
    try:
        x = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return x if math.isfinite(x) else None


def perp_active():
    if perp_dex is None:
        return {}
    cfg9 = perp_dex._read_cfg()
    if cfg9 is None:
        return None
    return {k9: {a9["address"] for a9 in v9} for k9, v9 in perp_dex.configured(cfg9).items()}


PERP_AMT_MAX, PERP_NUM_MAX = 1e13, 1e15
_PERP_BAD_WARNED = set()


def _pnum(v, cap=PERP_NUM_MAX):
    x = _fin(v if v is not None else 0)
    return x if x is not None and abs(x) <= cap else None


def perp_filter(d9, on9, now9=None, ex9="?"):
    ac9 = d9.get("accts") or {}
    t_hi9 = (time.time() + 86400) * 1000
    bad9 = 0
    out = {k9: v9 for k9, v9 in d9.items() if k9 not in ("events", "positions", "accts", "cursor", "wallet")}
    evs9 = []
    for r9 in d9.get("events") or []:
        if not isinstance(r9, dict) or r9.get("acct") not in on9:
            continue
        a9, t9 = _pnum(r9.get("amount"), PERP_AMT_MAX), _fin(r9.get("t"))
        if a9 is None or t9 is None or not (FUT_T_MIN_MS <= t9 <= t_hi9):
            bad9 += 1
            continue
        evs9.append(r9)
    out["events"] = evs9
    pos9 = []
    for p9 in d9.get("positions") or []:
        if not isinstance(p9, dict) or p9.get("acct") not in on9:
            continue
        if now9 is not None and now9 - int(_fin((ac9.get(p9.get("acct")) or {}).get("ts")) or 0) > 1800:
            continue
        if any(_pnum(p9.get(k9)) is None for k9 in ("qty", "entry", "mark", "upnl", "liq")):
            bad9 += 1
            continue
        pos9.append(p9)
    out["positions"] = pos9
    w9 = {}
    for k9, v9 in (d9.get("wallet") or {}).items():
        if k9 in ("balance", "equity", "maint_margin", "margin_balance"):
            if v9 is None:
                w9[k9] = None
            elif _pnum(v9) is not None:
                w9[k9] = v9
            else:
                bad9 += 1
        elif k9 == "note" and isinstance(v9, str):
            w9[k9] = v9
    out["wallet"] = w9
    out["accts"] = {a9: m9 for a9, m9 in ac9.items() if a9 in on9}
    if bad9 and ex9 not in _PERP_BAD_WARNED:
        _PERP_BAD_WARNED.add(ex9)
        log.warning("퍼프 스냅숏 %s: 범위 밖 숫자·시각 %d건 건너뜀(표시·합류 제외)", ex9, bad9)
    return out


def futures_api_payload():
    out9 = {}
    try:
        on9 = perp_active() or {}
    except Exception:
        on9 = {}
    for ex9 in FUT_CEX + tuple(k9 for k9 in PERP_KEYS if k9 in on9):
        fp9 = os.path.join(common.STATE_DIR, f"futures_{ex9}.json")
        if not os.path.exists(fp9):
            continue
        try:
            d9 = common.read_json(fp9, {})
        except SystemExit:
            continue
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
    except Exception:
        on9 = {}
    for ex9 in FUT_CEX + tuple(k9 for k9 in PERP_KEYS if k9 in on9):
        fp9 = os.path.join(common.STATE_DIR, f"futures_{ex9}.json")
        if not os.path.exists(fp9):
            continue
        try:
            d9 = common.read_json(fp9, {})
        except SystemExit:
            continue
        if isinstance(d9, dict):
            futs9[ex9] = perp_filter(d9, on9[ex9], now9, ex9) if ex9 in on9 else d9
    try:
        th9 = float(((alert_prefs.load(BUILDER.prefs()) or {}).get("th") or {}).get("liq_pct") or 10)
    except Exception:
        th9 = 10.0
    lm9, lp9 = None, os.path.join(common.STATE_DIR, "liq_watch.json")
    if os.path.exists(lp9):
        try:
            lm9 = common.read_json(lp9, None)
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


def review_pause_eff(prefs) -> dict:
    v = (prefs or {}).get("review_pause")
    return {"on": bool(isinstance(v, dict) and v.get("on") is True), "at": (v or {}).get("at") if isinstance(v, dict) else None}


def review_len_eff(prefs) -> dict:
    if not review_len_key:
        return {}
    rl = (prefs or {}).get("review_len")
    rl = rl if isinstance(rl, dict) else {}
    return {k: review_len_key(k, rl.get(k) if isinstance(rl.get(k), str) else None) for k in ("daily", "weekly")}

log = common.setup_logging("tj-web")
getcontext().prec = 60

KST = timezone(timedelta(hours=9))
_GSYM_MEMO = {}
WEB_DIR = os.path.join(common.BASE_DIR, "web")
UI_DEFAULT = "v2"
V2_DIR = os.path.join(WEB_DIR, "v2")
_V2_FILES = {"index.html": "text/html; charset=utf-8",
             "app.js": "application/javascript; charset=utf-8",
             "health.js": "application/javascript; charset=utf-8",
             "search.js": "application/javascript; charset=utf-8",
             "salelink.js": "application/javascript; charset=utf-8",
             "wow.js": "application/javascript; charset=utf-8"}


V2_FONT_DIR = os.path.join(V2_DIR, "fonts")
_V2_FONT_RE = re.compile(r"[a-z]{1,16}-[0-9]{3}-[0-9a-f]{12}\.woff2")


def _ui_route(path: str):
    if path in ("/v2", "/v2/", "/v2/index.html") or (UI_DEFAULT == "v2" and path in ("/", "/index.html")):
        return os.path.join(V2_DIR, "index.html"), _V2_FILES["index.html"]
    if path.startswith("/v2/") and path[4:] in _V2_FILES:
        return os.path.join(V2_DIR, path[4:]), _V2_FILES[path[4:]]
    if path.startswith("/v2/fonts/"):
        n9 = path[len("/v2/fonts/"):]
        ct9 = "text/css; charset=utf-8" if n9 == "plex.css" else "font/woff2" if _V2_FONT_RE.fullmatch(n9) else None
        f9 = os.path.join(V2_FONT_DIR, n9) if ct9 else None
        return (f9, ct9) if f9 and os.path.isfile(f9) else None
    if path == "/classic" and os.path.isfile(os.path.join(WEB_DIR, "index.html")):
        return os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8"
    return None


_ASSETS = {}
_ASSETS_LOCK = threading.Lock()
_V2_JS_RE = re.compile(rb'<script src="/v2/app\.js"></script>')
_V2_VER_JS = ("health.js", "search.js", "wow.js", "setup.js")


def _asset(fpath: str) -> dict:
    deps = [fpath]
    v2_index = os.path.normpath(fpath) == os.path.normpath(os.path.join(V2_DIR, "index.html"))
    font_css = os.path.join(V2_FONT_DIR, "plex.css")
    if v2_index:
        deps.append(os.path.join(V2_DIR, "app.js"))
        deps += [os.path.join(V2_DIR, n) for n in _V2_VER_JS]
        if os.path.isfile(font_css):
            deps.append(font_css)
    key = tuple((os.stat(d).st_mtime_ns, os.stat(d).st_size) for d in deps)
    with _ASSETS_LOCK:
        ent = _ASSETS.get(fpath)
        if ent and ent[0] == key:
            return ent[1]
    with open(fpath, "rb") as f:
        raw = f.read()
    if v2_index:
        js = _asset(deps[1])
        raw = _V2_JS_RE.sub(b'<script src="/v2/app.js?v=' + js["hash"].encode() + b'"></script>', raw)
        for n9 in _V2_VER_JS:
            a9 = _asset(os.path.join(V2_DIR, n9))
            raw = raw.replace(b'<script src="/v2/' + n9.encode() + b'"></script>', b'<script src="/v2/' + n9.encode() + b'?v=' + a9["hash"].encode() + b'"></script>', 1)
        if deps[-1] == font_css:
            fv9 = _asset(font_css)["hash"].encode()
            raw = re.sub(rb"(['\"])/v2/fonts/plex\.css\1", lambda m9: m9.group(1) + b"/v2/fonts/plex.css?v=" + fv9 + m9.group(1), raw, count=1)
    h = hashlib.sha1(raw).hexdigest()[:16]
    a = {"raw": raw, "gz": websnap.gz(raw) if len(raw) >= 1024 else None, "etag": f'W/"{h}"', "hash": h}
    with _ASSETS_LOCK:
        _ASSETS[fpath] = (key, a)
    return a


_GP_KO = {"is_airdrop_scam": "에어드랍 스캠 확증", "is_honeypot": "팔 수 없는 토큰(허니팟)", "cannot_sell_all": "전량 매도 불가",
          "is_fake_token": "가짜 토큰", "is_mintable": "민트 가능 토큰", "is_proxy": "변경 가능 컨트랙트",
          "is_blacklisted": "블랙리스트 기능", "transfer_pausable": "전송 정지 기능"}
_SCAM_NAME = re.compile(r"(https?:|www\.|\.(com|io|org|net|xyz|top|mom|site|app|live|pro|claim|gift|click|vip)\b|t\.me|"
                        r"visit|claim|reward|airdrop|voucher|✅|🎁|\$\s?\d|"
                        r"@\w{3,}bot\b|telegram)", re.I)
_SCAM_DOMAIN = re.compile(r"(?<![\w.])[a-z0-9][a-z0-9-]{1,62}\.(?:" + spamguard.LURE_TLD + r")(?![\w-])", re.I)
_SCAM_SOFT = re.compile(r"zero[\s_-]?fees?|返佣|空投|免费", re.I)
_SCAM_FREE = re.compile(r"(?<![a-z])free(?![a-z])", re.I)
_INVISIBLE = re.compile("[\u200b-\u200f\u2060-\u206f\ufeff\u00ad]")
NEG_DIAG_MIN_USD = 0.5
_PEND_GAP = {"TRANSFER_OUT": "미등록 외부 주소로 전송", "PROGRAM_IN": "컨트랙트 경유 수령"}


def _short_addr(a):
    a = str(a or "")
    return (a[:6] + "…" + a[-4:]) if len(a) > 14 else (a or "—")


def _human_dm(t):
    t = re.sub(r"^\[[\w-]+\]\s*[A-Z_]+\s*[—-]\s*", "", str(t or ""))
    t = re.sub(r"\s*·?\s*검토 후 /confirm 처리 예정", "", t)
    return t.strip()


def _usd_txt(v):
    v = float(v or 0)
    return f"${v:,.2f}" if v < 100 else f"${v:,.0f}"


def _scam_name(sym):
    s = str(sym or "")
    if _INVISIBLE.search(s):
        return "사칭 문자(보이지 않는 글자)"
    if _SCAM_NAME.search(s) or _SCAM_DOMAIN.search(s):
        return "링크·보상 유도 이름"
    if _SCAM_SOFT.search(s) or (re.search(r"\s", s.strip()) and _SCAM_FREE.search(s)):
        return "보상 유도 문구"
    if spamguard.impostor_of(s) or spamguard.odd_symbol(s):
        return "사칭 문자(유사 글자)"
    return None


SNAPFILE_PATH = os.path.join(common.STATE_DIR, "web_snap_last.bin")
SNAPFILE_EVERY = 300
SNAPFILE_MAX_AGE = 1800
_SNAPFILE = {"at": 0.0, "ver": None, "lock": threading.Lock()}
_SNAPFILE_MAGIC = b"TJSNAP1\n"
_LASTSCAN_KEY = b'"lastScan": '
_LASTSCAN_RX = re.compile(r"(\d+)(초|분) 전 스캔")


def _code_sig() -> str:
    h = hashlib.sha1()
    d9 = os.path.dirname(os.path.abspath(__file__))
    for n9 in sorted(os.listdir(d9)):
        if n9.endswith(".py"):
            with open(os.path.join(d9, n9), "rb") as f9:
                h.update(n9.encode() + b"\0" + f9.read())
    seen9 = set()
    for sd in (os.path.join(os.path.dirname(d9), "seed"), os.path.join(common.BASE_DIR, "seed")):
        rp = os.path.realpath(sd)
        if rp in seen9 or not os.path.isdir(rp):
            continue
        seen9.add(rp)
        for root9, dirs9, files9 in os.walk(rp):
            dirs9.sort()
            for n9 in sorted(files9):
                fp9 = os.path.join(root9, n9)
                with open(fp9, "rb") as f9:
                    h.update(b"seed:" + os.path.relpath(fp9, rp).encode() + b"\0" + f9.read())
    return h.hexdigest()[:16]


_SIG0 = {}


def _snapfile_sig() -> dict:
    if not _SIG0:
        with open(common.CONFIG_PATH, "rb") as f9:
            cfg9 = hashlib.sha1(f9.read()).hexdigest()[:16]
        try:
            st9 = os.stat(common.ENV_PATH)
            env9 = [st9.st_mtime_ns, st9.st_size]
        except OSError:
            env9 = None
        _SIG0.update(code=_code_sig(), cfg=cfg9, env=env9)
    out = dict(_SIG0)
    c9 = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        out["led"] = [list(r) for r in c9.execute("SELECT k, v FROM meta WHERE k IN ('schema_version', 'ext_rebuilt_at') ORDER BY k")]
    finally:
        c9.close()
    return out


def _snapfile_save(snap, force=False, still_ok=None):
    now = time.time()
    with _SNAPFILE["lock"]:
        if not force and (_SNAPFILE["ver"] == snap.ver or now - _SNAPFILE["at"] < SNAPFILE_EVERY):
            return False
        _SNAPFILE["at"], _SNAPFILE["ver"] = now, snap.ver
    try:
        parts = snap.parts_gz or {}
        blobs = [snap.gz, snap.slim_gz or b""] + [parts[n] for n in websnap.PARTS if n in parts]
        head = {"ver": snap.ver, "at": snap.at, "built_at": snap.built_at, "hero": snap.hero, "sig": _snapfile_sig(),
                "slim": snap.slim_gz is not None, "parts": [n for n in websnap.PARTS if n in parts], "lens": [len(b) for b in blobs],
                "h": hashlib.sha1(b"".join(blobs)).hexdigest()}
        hj = json.dumps(head, ensure_ascii=False).encode()
        tmp = SNAPFILE_PATH + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as f9:
            f9.write(_SNAPFILE_MAGIC + str(len(hj)).encode() + b"\n" + hj)
            for b9 in blobs:
                f9.write(b9)
            f9.flush()
            os.fsync(f9.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, SNAPFILE_PATH)
        if still_ok is not None and not still_ok():
            _snapfile_drop()
            return False
        return True
    except Exception as e:
        log.warning("스냅샷 저장본 쓰기 실패(무시): %s", type(e).__name__)
        with _SNAPFILE["lock"]:
            _SNAPFILE["ver"] = None
        return False


def _snapfile_drop():
    try:
        os.unlink(SNAPFILE_PATH)
    except OSError:
        pass
    with _SNAPFILE["lock"]:
        _SNAPFILE["at"], _SNAPFILE["ver"] = 0.0, None


def _aged_last_scan(raw: bytes, elapsed: float):
    if raw.count(_LASTSCAN_KEY) != 1:
        return None
    i = raw.index(_LASTSCAN_KEY) + len(_LASTSCAN_KEY)
    if raw[i:i + 1] != b'"':
        return None
    end = raw.find(b'"', i + 1, i + 202)
    if end < 0 or b"\\" in raw[i + 1:end]:
        return None
    m9 = _LASTSCAN_RX.fullmatch(raw[i + 1:end].decode("utf-8", "replace"))
    if not m9:
        return raw
    ago = int(m9.group(1)) * (1 if m9.group(2) == "초" else 60) + int(max(0.0, elapsed))
    new = f"{ago}초 전 스캔" if ago < 90 else f"{ago // 60}분 전 스캔"
    return raw[:i] + json.dumps(new, ensure_ascii=False).encode() + raw[end + 1:]


def _snapfile_load(gen: int, stale_max: float):
    if not os.path.exists(SNAPFILE_PATH):
        return None
    why = ""
    try:
        with open(SNAPFILE_PATH, "rb") as f9:
            data = f9.read()
        if not data.startswith(_SNAPFILE_MAGIC):
            raise ValueError("magic")
        rest = data[len(_SNAPFILE_MAGIC):]
        n9, _, rest = rest.partition(b"\n")
        head = json.loads(rest[:int(n9)])
        body = rest[int(n9):]
        lens = [int(x) for x in head["lens"]]
        if sum(lens) != len(body) or hashlib.sha1(body).hexdigest() != head.get("h"):
            raise ValueError("length/hash")
        blobs, o9 = [], 0
        for L9 in lens:
            blobs.append(body[o9:o9 + L9])
            o9 += L9
        at = float(head["at"])
        hero = head.get("hero") if isinstance(head.get("hero"), dict) else None
        age9 = time.time() - at
        if age9 > min(stale_max, SNAPFILE_MAX_AGE) or age9 < -60:
            why = "너무 오래됨(%d분)" % int(age9 // 60) if age9 > 0 else "시각이 미래"
        elif not hero or hero.get("todayKey") != datetime.now(KST).strftime("%m-%d"):
            why = "날짜 바뀜"
        else:
            sig0, sig1 = head.get("sig") or {}, _snapfile_sig()
            if sig0 != sig1:
                why = "바뀜: " + ",".join(k for k in ("code", "cfg", "env", "led") if sig0.get(k) != sig1.get(k))
        if why:
            log.info("스냅샷 저장본 안 씀(%s) — 첫 빌드를 기다림", why)
            return None
        raw = gzip.decompress(blobs[0])
        if hashlib.sha1(raw).hexdigest()[:16] != head["ver"]:
            raise ValueError("ver")
        names = head.get("parts") or []
        slim_ok = head.get("slim") and len(names) == len(websnap.PARTS) and len(blobs) == 2 + len(names)
        el9 = max(0.0, age9)
        raw2 = _aged_last_scan(raw, el9)
        slim2 = _aged_last_scan(gzip.decompress(blobs[1]), el9) if slim_ok else None
        if raw2 is None or (slim_ok and slim2 is None):
            log.info("스냅샷 저장본 안 씀(수집 시각 칸 없음) — 첫 빌드를 기다림")
            return None
        snap = websnap.Snap.__new__(websnap.Snap)
        snap.raw, snap.at, snap.gen = raw2, at, gen
        snap.gz = blobs[0] if raw2 == raw else websnap.gz(raw2)
        snap.ver = head["ver"] if raw2 == raw else hashlib.sha1(raw2).hexdigest()[:16]
        snap.built_at, snap.hero = head.get("built_at"), hero
        if slim_ok:
            snap.slim_gz = blobs[1] if slim2 == gzip.decompress(blobs[1]) else websnap.gz(slim2)
            snap.parts_gz = dict(zip(names, blobs[2:]))
        else:
            snap.slim_gz = snap.parts_gz = None
        return snap
    except Exception as e:
        log.warning("스냅샷 저장본 읽기 실패(지움): %s", type(e).__name__)
        _snapfile_drop()
        return None


_HERO_HTML = {}
_HERO_HTML_LOCK = threading.Lock()


def _hero_ok(b, snap) -> bool:
    try:
        if b is None or snap is None:
            return False
        lim = float(getattr(b, "SNAP_STALE_MAX", 120))
        if time.time() - float(snap.at) > lim:
            return False
        if snap.gen != b.__dict__.get("_inval", 0) or b.__dict__.get("_build_err") is not None:
            return False
        tk = (getattr(snap, "hero", None) or {}).get("todayKey")
        return tk == datetime.now(KST).strftime("%m-%d")
    except Exception:
        return False


def _wallet_reload_view() -> dict:
    try:
        import wallet_register as _wr9
        alive9 = _wr9.auto_reload_alive()
        return {"ok": True, "auto": bool(_wr9.apply_info().get("runner")), "addrs": sorted(_wr9.pending_addrs()) if alive9 else []}
    except Exception:
        return {"ok": True, "auto": False, "addrs": []}


def _bcall(name, *a):
    f9 = getattr(BUILDER, name, None)
    return f9(*a) if callable(f9) else None


def _mats_ready(path) -> bool:
    r9 = _bcall("mats_wait", path)
    return True if r9 is None else bool(r9)


def _publish_snap(pub, gen, out=None):
    snap9 = websnap.Snap(pub, gen)
    try:
        snap9.hero = _hero_summary(out if out is not None else pub)
    except Exception as e:
        log.warning("hero 요약 실패(무시): %s", e)
    try:
        websnap.attach_slim(snap9, pub)
    except Exception as e:
        snap9.slim_gz = snap9.parts_gz = None
        log.warning("가벼운 상태 만들기 실패(무시): %s", e)
    return snap9


def _hero_summary(out):
    f = out.get("fields") or {}
    n = lambda v: float(v) if isinstance(v, (int, float)) and v == v else 0.0
    rate = n(f.get("rate")) or 1384.0
    total = sum(n(x.get("qty")) * n(x.get("price")) for x in (f.get("stables") or []))
    total += sum(n(x.get("qty")) * n(x.get("price")) for x in (f.get("coins") or []))
    total += sum(n(x.get("krw")) / rate for x in (f.get("fiats") or []))
    for lp in f.get("lps") or []:
        if isinstance(lp, dict) and not lp.get("closed"):
            total += n(lp.get("value")) + n(lp.get("fees")) + n(lp.get("rewards"))
    total += sum(n(x.get("usd")) for x in (f.get("rabbyDebts") or []) if isinstance(x, dict))
    tk = str(out.get("todayKey") or "")
    daily = [d for d in (f.get("dailySeries") or []) if isinstance(d, dict)]
    prev = daily[-2] if len(daily) > 1 and daily[-1].get("date") == tk else (daily[-1] if daily else None)
    mm = tk[:3]
    ym = str(out.get("todayIso") or "")[:8]
    inm = lambda k: str(k).startswith(ym) if (ym and len(str(k)) == 10) else str(k).startswith(mm)
    fut = (f.get("futures") or {}).get("realizedByDate") or {}
    month = sum(n(v) for k, v in (f.get("realizedByDate") or {}).items() if inm(k))
    month += sum(n(v) for k, v in fut.items() if inm(k))
    rk = f.get("realizedKrwByDate")
    month_krw, month_ap = None, False
    if isinstance(rk, dict):
        fk = (f.get("futures") or {}).get("realizedKrwByDate") or {}
        mk = 0.0
        for su, sk in (((f.get("realizedByDate") or {}), rk), (fut, fk)):
            for k, v in su.items():
                if not inm(k):
                    continue
                if isinstance(sk, dict) and sk.get(k) is not None:
                    mk += n(sk.get(k))
                else:
                    mk += n(v) * rate
                    month_ap = month_ap or abs(n(v)) >= 0.005
        month_krw = round(mk)
    tiso = str(out.get("todayIso") or "")[:10]
    ist = lambda k: (str(k) == tiso) if len(str(k)) == 10 else (str(k) == tk)
    today_r = sum(n(v) for k, v in (f.get("realizedByDate") or {}).items() if ist(k)) + sum(n(v) for k, v in fut.items() if ist(k))
    today_krw = None
    if isinstance(rk, dict):
        fk = (f.get("futures") or {}).get("realizedKrwByDate") or {}
        tkw = 0.0
        for su, sk in (((f.get("realizedByDate") or {}), rk), (fut, fk)):
            for k, v in su.items():
                if ist(k):
                    tkw += n(sk.get(k)) if isinstance(sk, dict) and sk.get(k) is not None else n(v) * rate
        today_krw = round(tkw)
    series = []
    for d in daily[-30:]:
        v9 = n(d.get("val"))
        ap9 = 1 if (d.get("date") != tk and n(d.get("est")) + n(d.get("xc")) >= max(50.0, 0.005 * abs(v9))) else 0
        series.append([d.get("date"), round(v9, 2), d.get("valKrw") if isinstance(d.get("valKrw"), (int, float)) else None, ap9])
    if series and series[-1][0] == tk:
        series[-1][1] = round(total, 2)
        series[-1][2] = None
        series[-1][3] = 0
    last = daily[-1] if daily and daily[-1].get("date") == tk else None
    return {"total": round(total, 2), "prev": round(n(prev.get("val")), 2) if prev else None,
            "prevKrw": prev.get("valKrw") if prev and isinstance(prev.get("valKrw"), (int, float)) else None,
            "flow": n(last.get("flow")) if last and last.get("flow") is not None else None,
            "month": round(month, 2), "monthKrw": month_krw, "monthAp": month_ap,
            "tr": round(today_r, 2), "trKrw": today_krw,
            "rate": rate, "todayKey": tk, "series": series}


def _ago_ko(sec) -> str:
    s9 = max(0, int(sec))
    if s9 < 7200:
        return f"{max(1, s9 // 60)}분"
    if s9 < 172800:
        return f"{s9 // 3600}시간"
    return f"{s9 // 86400}일"


def _daily_krw(daily, today_key):
    for row9 in daily or ():
        u9 = row9.get("usdt")
        if row9.get("date") != today_key and isinstance(u9, (int, float)) and not isinstance(u9, bool) and u9 > 0 \
                and isinstance(row9.get("val"), (int, float)):
            row9["valKrw"] = round(float(row9["val"]) * float(u9))
    return daily


def _tax_summary(rows, today):
    acc = {}
    for r in rows:
        ym = acct_norm.month_of(r.get("sold"), today)
        if not ym:
            continue
        key = (ym, r.get("sym") or "?", r.get("ex") or "")
        a = acc.setdefault(key, [0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0])
        a[0] += 1
        acq9, disp9, fee9 = (float(r.get("_" + k9, r.get(k9)) or 0) for k9 in ("acq", "disp", "fee"))
        a[1] += float(r.get("qty") or 0); a[2] += acq9
        a[3] += disp9; a[4] += fee9
        rt = float(r.get("rate") or 0)
        ak9 = r.get("_akr", r.get("akr"))
        if r.get("_akm") and ak9 is not None:
            a[5] += disp9 * rt - float(ak9) - fee9 * rt
            a[6] += float(ak9)
        else:
            a[5] += (disp9 - acq9 - fee9) * rt
            a[6] += acq9 * rt
        a[7] += disp9 * rt
        a[8] += int(r.get("tx") or 0)
        if ak9 is None:
            ak9 = acq9 * rt
            a[11] += 1 if acq9 else 0
        a[9] += float(ak9)
        a[10] += disp9 * rt - float(ak9) - fee9 * rt
    return [[k[0], k[1], k[2], v[0], round(v[1], 6), round(v[2], 4), round(v[3], 4), round(v[4], 4), round(v[5], 2), round(v[6], 2), round(v[7], 2), v[8],
             round(v[9], 2), round(v[10], 2), v[11]]
            for k, v in sorted(acc.items())]


def chain_auto_off_save(prefs: dict, body: dict):
    on9 = (body or {}).get("on")
    if not isinstance(on9, bool):
        return 400, {"ok": False, "error": "on 은 true/false"}
    prefs["chain_auto_off"] = {"on": on9, "at": int(time.time())}
    common.atomic_write_json(PREFS_PATH, prefs)
    return 200, {"ok": True, "on": on9}


def dust_usd_eff(prefs) -> float:
    d9 = (prefs or {}).get("dust_usd")
    try:
        return 50.0 if d9 is None else max(0.0, float(d9 or 0))
    except (TypeError, ValueError):
        return 50.0


def _tx_norm(tx) -> str:
    tx = str(tx or "")
    return tx.lower() if tx.startswith("0x") else tx


def _of_linked_txs(of_dec) -> dict:
    out = {}
    for ent in (of_dec or {}).values():
        if not isinstance(ent, dict):
            continue
        for l in (ent.get("links") or ()):
            if not isinstance(l, dict):
                continue
            kp = str(l.get("key") or "").split("|")
            if len(kp) < 3 or kp[0] != "chain_tx" or not kp[1] or not kp[2]:
                continue
            out[(kp[1], _tx_norm(kp[2]))] = "세일 토큰" if l.get("kind") == "tokens" else "환불"
    return out


def _classify_pendings(pendings, prefs):
    dust = dust_usd_eff(prefs)
    for p in pendings:
        key = str(p.get("key") or "")
        usd = p.get("usd")
        hide = why = None
        if key == "risk:summary":
            hide, why = "dust", f"저평가 격리분 {p.get('n') or ''}종 일괄".replace("  ", " ")
        elif key.startswith("risk:"):
            rr = str(p.get("risk") or "")
            m9 = re.search(r"고플러스 (스캠 확증|주의) ([\w·]+)", rr)
            flags9 = [_GP_KO.get(x, x) for x in (m9.group(2).split("·") if m9 else [])]
            name9 = _scam_name(p.get("sym"))
            if "유저 확정" in rr:
                hide, why = "scam", "직접 스팸으로 지정함"
            elif rr.startswith(("가짜 ", "사칭 ")):
                hide, why = "scam", rr
            elif "재정렬" in rr:
                hide, why = "info", "잔고 대사 잔여분(실측 잔고로 소거됨)"
            elif m9 and m9.group(1) == "스캠 확증":
                hide, why = "scam", "에어드랍 스캠 · " + " · ".join(flags9)
            elif name9:
                hide, why = "scam", "에어드랍 스캠 · " + name9
            elif usd is not None and float(usd) < dust:
                hide, why = "dust", "소액 " + _usd_txt(usd)
        elif p.get("scamWhy"):
            hide, why = "scam", p["scamWhy"]
        elif p.get("autoDone"):
            hide, why = "info", str(p["autoDone"])
        elif p.get("riskOf"):
            hide, why = "info", "코인 검토 행에서 판정 · " + str(p["riskOf"])[:120]
        elif p.get("usdIn") is not None and float(p["usdIn"]) < dust:
            hide, why = "dust", "소액 수령 " + _usd_txt(p["usdIn"])
        elif usd is not None and float(usd) < dust and not key.startswith(("unv:", "unvlost:")):
            hide, why = "dust", "소액 " + _usd_txt(usd)
        elif key.startswith("unvlost:"):
            hide, why = "info", "백필 창 이전 보유분 정리 · 표시용 보정(할 일 없음)"
        p["hide"], p["hideReason"] = hide, why


def _daily_reset(daily: dict, today_kst) -> dict:
    out = dict({"_v": DAILY_V}, **{k9: daily[k9] for k9 in ("_risk_rev", "_live", "_live_ok") if k9 in daily})
    y9 = (today_kst - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        ra9 = float(daily.get("_reset_at") or 0)
    except (TypeError, ValueError):
        ra9 = 0.0
    if ra9 and y9 not in daily and ra9 >= today_kst.replace(hour=0, minute=0, second=0, microsecond=0).timestamp():
        out["_reset_at"] = daily["_reset_at"]
    return out


def snapshot_refresher():
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
        except Exception as e:
            log.warning("스냅샷 갱신기 오류(계속): %s", e)


PREFS_PATH = os.path.join(common.STATE_DIR, "ui_prefs.json")
PREFS_LOCK = threading.Lock()
_OPS_RL = __import__("collections").deque()
_OPS_RL_LOCK = threading.Lock()
SELL_EVALS = sellchart.EvalStore()
BUY_EVALS = sellchart.EvalStore(kind="buy")
DAY_MEMOS = day_memo.Store()
SPOT_PATH = os.path.join(common.STATE_DIR, "spot.json")
WEB_DIAG_PATH = os.path.join(common.STATE_DIR, "web_diag.json")
DAILY_PATH = os.path.join(common.STATE_DIR, "daily_cache.json")
SOL_STAKE_PATH = os.path.join(common.STATE_DIR, "sol_stake.json")
STAKE_STATE_KO = {"activating": "스테이킹 활성화 대기", "active": "스테이킹 중", "deactivating": "스테이킹 해제 중",
                  "inactive": "스테이킹 해제됨 · 인출 가능", "undelegated": "위임 안 됨", "closed": "닫힘"}


def _sol_stake_accounts() -> dict:
    try:
        d = common.read_json(SOL_STAKE_PATH, {}) or {}
        acc = d.get("accounts") or {}
        return acc if isinstance(acc, dict) else {}
    except (Exception, SystemExit):
        return {}
DAILY_V = 4
DAILY_LIVE_WIN = 900
DAILY_PX_PATH = os.path.join(common.STATE_DIR, "daily_px.json")
DAILY_PX_SEED = os.path.join(common.STATE_DIR, "daily_px_seed.json")
DAILY_PX_KEEP = 45
EX_CANDLE_SYMS = frozenset(("OKB",))
DAYCLOSE_ON = os.environ.get("TJ_DAYCLOSE", "1") != "0"
DC_LATE_S = 2 * 86400
DC_RETRY_S = 86400
DC_SMALL_USD = 1.0


def _pxfix_backup(ts) -> list:
    import shutil
    out = []
    for src9 in (DAILY_PX_PATH, DAILY_PATH):
        if os.path.exists(src9):
            dst9 = f"{src9}.bak_pxfix_{int(ts)}"
            shutil.copy2(src9, dst9)
            out.append(dst9)
    return out


PXB_KEYS = ("p", "k", "fp", "lp", "dcn", "dcw", "rdo")


def _bind_px_blocks(daily, dpx, lo=None):
    n, legacy = 0, []
    for ck, c in (daily or {}).items():
        if str(ck).startswith("_") or not isinstance(c, dict) or "val" not in c or (lo and str(ck) < lo):
            continue
        b = c.get("px")
        if not isinstance(b, dict):
            legacy.append(ck)
            continue
        e = dpx.get(ck)
        if not isinstance(e, dict):
            e = dpx[ck] = {}
        hit = False
        for key in PXB_KEYS:
            if key in b:
                if e.get(key) is not b[key]:
                    hit = hit or e.get(key) != b[key]
                    e[key] = b[key]
            elif key in e:
                e.pop(key)
                hit = True
        if hit:
            n += 1
            log.info("일별 %s: daily_px 를 동결 항목 가격 블록으로 맞춤(저장 사이 중단·저장 실패 복구)", ck)
    return n, legacy


def _migrate_px_blocks(daily, dpx, days) -> int:
    n = 0
    for ck in days:
        c = daily[ck]
        e = dpx.get(ck)
        if not isinstance(e, dict):
            e = dpx[ck] = {"p": {}, "k": {}}
        for key, kind in (("dcp", "d"), ("native_c", "c")):
            m = c.get(key)
            if not isinstance(m, dict):
                continue
            for sid, v in m.items():
                k = e.setdefault("k", {})
                if k.get(sid) or not v:
                    continue
                p = e.setdefault("p", {})
                if kind == "d" and p.get(sid):
                    e.setdefault("fp", {}).setdefault(sid, float(p[sid]))
                p[sid] = float(v)
                k[sid] = kind
                log.info("일별 %s: 교정 표식(%s) 복구 — g%s 고정가 %s · 종류 %s(옛 저장 사이 중단)", ck, key, sid, v, kind)
        e.setdefault("p", {})
        e.setdefault("k", {})
        dcp0 = c.get("dcp") if isinstance(c.get("dcp"), dict) else {}
        for sid, fpv in list((e.get("fp") or {}).items()):
            if e["k"].get(sid) == "d" and sid not in dcp0 and fpv:
                e["p"][sid] = float(fpv)
                e["k"].pop(sid, None)
                e["fp"].pop(sid, None)
                log.warning("일별 %s: g%s 옛 형식 동결 항목 + daily_px 교정 흔적 — 교정 전 가격으로 되돌려 다시 교정", ck, sid)
        c["px"] = {key: e[key] for key in PXB_KEYS if key in e}
        n += 1
    return n


def _capture_px_blocks(daily, dpx, lo=None) -> int:
    n = 0
    for ck, c in (daily or {}).items():
        if str(ck).startswith("_") or not isinstance(c, dict) or "val" not in c or (lo and str(ck) < lo):
            continue
        e = dpx.get(ck)
        if not isinstance(e, dict):
            continue
        b = {key: e[key] for key in PXB_KEYS if key in e}
        old = c.get("px")
        if not isinstance(old, dict) or set(old) != set(b) or any(old[k] is not b[k] for k in b):
            c["px"] = b
            n += 1
    return n


def _reprice_now_days(daily, dpx, G, today_iso, now_ts, day_close, skip_gids=None, backup=_pxfix_backup) -> dict:
    out = {"rep": 0, "fin": 0, "pend": 0, "dv": 0.0, "days": {}, "changed": False, "px_changed": False, "bak": None}
    if day_close is None or not isinstance(dpx, dict):
        return out
    skip9 = set(skip_gids or ())
    lo9 = (datetime.strptime(today_iso, "%Y-%m-%d") - timedelta(days=29)).strftime("%Y-%m-%d")
    plan9, fin9, pend9 = [], {}, {}
    for ck9 in sorted(k9 for k9 in dpx if not str(k9).startswith("_")):
        if not (lo9 <= ck9 < today_iso):
            continue
        e9, c9 = dpx.get(ck9), (daily or {}).get(ck9)
        if not isinstance(e9, dict) or not isinstance(c9, dict) or not isinstance(c9.get("g"), dict):
            continue
        p9, k9, dn9 = e9.get("p") or {}, e9.get("k") or {}, set(e9.get("dcn") or ())
        done9 = c9.get("dcp") if isinstance(c9.get("dcp"), dict) else {}
        for sid9, op9 in p9.items():
            if sid9 in k9 or sid9 in dn9 or not op9:
                continue
            if done9.get(sid9) is not None:
                plan9.append((ck9, sid9, float(op9), float(done9[sid9]), True))
                continue
            try:
                gv9 = float(c9["g"].get(sid9) or 0)
                gid9 = int(sid9)
            except (TypeError, ValueError):
                continue
            if gv9 < DC_SMALL_USD or gid9 not in G:
                continue
            np9, st9 = day_close(gid9, ck9, gv9)
            if np9:
                plan9.append((ck9, sid9, float(op9), float(np9), False))
            elif st9 == "none":
                fin9.setdefault(ck9, []).append(sid9)
            else:
                pend9.setdefault(ck9, []).append(sid9)
    stamp9 = {}
    for ck9 in pend9:
        if not dpx[ck9].get("dcw"):
            stamp9[ck9] = int(now_ts)
    for ck9, e9 in dpx.items():
        if isinstance(e9, dict) and e9.get("dcw") and ck9 not in pend9:
            stamp9.setdefault(ck9, None)
    out["pend"] = sum(len(v9) for v9 in pend9.values())
    if not plan9 and not fin9 and not stamp9:
        return out
    if not isinstance(dpx.get("_pxfix"), dict):
        ts9 = int(now_ts)
        try:
            out["bak"] = backup(ts9) if backup else []
        except Exception as e9:
            log.warning("pxfix: 이관 전 백업 실패 — 이번 빌드는 재평가 안 함: %s", e9)
            return out
        dpx["_pxfix"] = {"v": 1, "bak": ts9, "at": ts9}
        log.info("pxfix: 근사(now) 고정가 → 그날 마감가 1회 이관 시작 — 백업 %s", out["bak"])
    out["px_changed"] = True
    for ck9, w9 in stamp9.items():
        if w9:
            dpx[ck9]["dcw"] = w9
        else:
            dpx[ck9].pop("dcw", None)
    for ck9, sids9 in fin9.items():
        e9 = dpx[ck9]
        e9["dcn"] = sorted(set(e9.get("dcn") or ()) | set(sids9), key=lambda x9: (len(x9), x9))
        out["fin"] += len(sids9)
    for ck9, sid9, op9, np9, rec9 in plan9:
        e9, c9 = dpx[ck9], daily[ck9]
        d9 = out["days"].setdefault(ck9, [0, 0.0, float(c9.get("est") or 0), None])
        if not rec9:
            ov9 = Decimal(str(c9["g"][sid9]))
            nv9 = ov9 * Decimal(str(np9)) / Decimal(str(op9))
            c9["g"][sid9] = round(float(nv9), 4)
            if int(sid9) not in skip9:
                c9["val"] = _f(Decimal(str(c9["val"])) + nv9 - ov9, 2) or 0
                if c9.get("est"):
                    e9s = float(c9["est"]) - float(ov9)
                    if e9s >= 1:
                        c9["est"] = round(e9s, 2)
                    else:
                        c9.pop("est", None)
                d9[1] += float(nv9 - ov9)
                out["dv"] += float(nv9 - ov9)
            c9.setdefault("dcp", {})[sid9] = float(np9)
            c9["src9"] = "dayclose"
            out["changed"] = True
        e9.setdefault("fp", {}).setdefault(sid9, float(op9))
        e9.setdefault("p", {})[sid9] = float(np9)
        e9.setdefault("k", {})[sid9] = "d"
        rd9 = e9.get("rdo") if isinstance(e9.get("rdo"), dict) else {}
        rd9[sid9] = max(int(rd9.get(sid9) or 0), int(now_ts))
        e9["rdo"] = rd9
        d9[0] += 1
        d9[3] = float(c9.get("est") or 0)
        out["rep"] += 1
    for ck9, (n9, dv9, est0, est1) in sorted(out["days"].items()):
        log.info("일별 %s: 근사(now) %d그룹 → 그날 마감가 재평가 %+.2f (근사분 %.2f → %.2f)", ck9, n9, dv9, est0, est1 or 0)
    return out


def _px1004_backup(ts) -> list:
    import shutil
    out = []
    for src9 in (DAILY_PX_PATH, DAILY_PATH):
        if os.path.exists(src9):
            dst9 = f"{src9}.bak_px1004_{int(ts)}"
            shutil.copy2(src9, dst9)
            out.append(dst9)
    return out


def _px1004_reset(daily, dpx, G, today_iso, day_close, live_px=None, skip_gids=None, now_ts=None, backup=_px1004_backup) -> dict:
    out = {"n": 0, "days": {}, "dv": 0.0, "changed": False, "px_changed": False, "bak": None}
    chg_of, spec9 = getattr(day_close, "chg", None), getattr(day_close, "spec", None)
    if chg_of is None or spec9 is None or not isinstance(dpx, dict):
        return out
    skip9 = set(skip_gids or ())
    lo9 = (datetime.strptime(today_iso, "%Y-%m-%d") - timedelta(days=29)).strftime("%Y-%m-%d")
    plan9 = []
    for ck9 in sorted(k9 for k9 in dpx if not str(k9).startswith("_")):
        if not (lo9 <= ck9 < today_iso):
            continue
        e9, c9 = dpx.get(ck9), (daily or {}).get(ck9)
        if not isinstance(e9, dict):
            continue
        frozen9 = isinstance(c9, dict) and isinstance(c9.get("g"), dict)
        k9, p9 = e9.get("k") or {}, e9.get("p") or {}
        rdo9 = e9.get("rdo") if isinstance(e9.get("rdo"), dict) else {}
        hit9 = []
        for sid9, kd9 in k9.items():
            if kd9 != "d" or not p9.get(sid9):
                continue
            try:
                gid9 = int(sid9)
            except (TypeError, ValueError):
                continue
            if gid9 not in G:
                continue
            c9g = chg_of(spec9(gid9))
            if not c9g:
                continue
            t9 = int(c9g.get(ck9) or 0)
            st9 = int(c9g.get("*") or 0)
            if st9 and histcurve.settle_ts(ck9) <= st9:
                t9 = max(t9, st9)
            if t9 and t9 > int(rdo9.get(sid9) or 0):
                hit9.append((sid9, gid9, t9))
        if hit9:
            plan9.append((ck9, e9, c9, frozen9, k9, p9, hit9))
    if not plan9:
        return out
    if not isinstance(dpx.get("_px1004"), dict):
        ts9 = int(time.time() if now_ts is None else now_ts)
        try:
            out["bak"] = backup(ts9) if backup else []
        except Exception as e9:
            log.warning("px1004: 되돌리기 전 백업 실패 — 이번 빌드는 안 바꿈: %s", e9)
            return out
        dpx["_px1004"] = {"v": 1, "bak": ts9, "at": ts9}
        log.info("px1004: 업비트·빗썸 USDT·BTC 마켓 그날 마감가 되돌리기 시작 — 백업 %s", out["bak"])
    for ck9, e9, c9, frozen9, k9, p9, hit9 in plan9:
        d9 = out["days"].setdefault(ck9, [0, 0.0])
        for sid9, gid9, t9 in hit9:
            pb9 = float(p9[sid9])
            fp9 = (e9.get("fp") or {}).get(sid9)
            prov9 = float(fp9) if fp9 else (float((live_px or {}).get(gid9) or 0) or pb9)
            if frozen9 and sid9 in c9["g"]:
                ov9 = Decimal(str(c9["g"][sid9]))
                nv9 = ov9 * Decimal(str(prov9)) / Decimal(str(pb9))
                c9["g"][sid9] = round(float(nv9), 4)
                if gid9 not in skip9:
                    c9["val"] = _f(Decimal(str(c9["val"])) + nv9 - ov9, 2) or 0
                    c9["est"] = round(float(c9.get("est") or 0) + float(nv9), 2)
                    d9[1] += float(nv9 - ov9)
                    out["dv"] += float(nv9 - ov9)
                if isinstance(c9.get("dcp"), dict):
                    c9["dcp"].pop(sid9, None)
            p9[sid9] = prov9
            k9.pop(sid9, None)
            if isinstance(e9.get("dcn"), list) and sid9 in e9["dcn"]:
                e9["dcn"].remove(sid9)
            d9[0] += 1
            out["n"] += 1
        e9.pop("dcw", None)
        rd9 = e9.get("rdo") if isinstance(e9.get("rdo"), dict) else {}
        rd9.update({sid9: t9 for sid9, _g9, t9 in hit9})
        e9["rdo"] = rd9
        out["changed"] = out["changed"] or frozen9
        out["px_changed"] = True
        log.warning("일별 %s: px1004 업비트·빗썸 USDT·BTC 마켓 그날 마감가 %d그룹 근사로 되돌림(다시 받기) %+.2f", ck9, d9[0], d9[1])
    return out


def _pin_frozen_x(daily, dpx, lo=None) -> int:
    n = 0
    for ck, c in list((daily or {}).items()):
        if str(ck).startswith("_") or not isinstance(c, dict) or c.get("x") is None or (lo and str(ck) < lo):
            continue
        e = dpx.setdefault(ck, {"p": {}, "k": {}})
        if not isinstance(e, dict) or e.get("x") is not None:
            continue
        try:
            e["x"] = round(float(c["x0"] if c.get("x0") is not None else c["x"]), 2)
        except (TypeError, ValueError):
            continue
        e["xk"] = "live" if c.get("src") in ("live", "partial") else "calc"
        if c.get("xc"):
            e["xc"] = c["xc"]
        xu9 = c.get("xu0") if c.get("x0") is not None else c.get("xu")
        if isinstance(xu9, dict) and xu9:
            e["xu"] = xu9
        n += 1
    return n


def _stable_regroup_aliases(conn) -> dict:
    try:
        cur9 = {int(r[0]): int(r[1]) for r in conn.execute(
            "SELECT a.asset_id, a.group_id FROM assets a JOIN asset_groups g ON g.group_id=a.group_id"
            " WHERE a.kind='token' AND g.name IN (%s)" % ",".join("?" * len(STABLE_GROUPS)), sorted(STABLE_GROUPS))}
        if not cur9:
            return {}
        out = {}
        for gid9, name9 in conn.execute(
                "SELECT group_id, name FROM asset_groups WHERE name LIKE '%#%'"
                " AND group_id NOT IN (SELECT group_id FROM assets WHERE group_id IS NOT NULL)"):
            _h9, sep9, aid9 = str(name9).rpartition("#")
            if sep9 and aid9.isdigit() and int(aid9) in cur9 and cur9[int(aid9)] != int(gid9):
                out[str(gid9)] = str(cur9[int(aid9)])
        return out
    except Exception as e:
        log.warning("스테이블 재그룹 별칭 조회 실패: %s", e)
        return {}


def _relabel_daily_gids(daily, dpx, aliases) -> int:
    if not aliases:
        return 0
    snaps = [c for c in (daily or {}).values() if isinstance(c, dict)]
    snaps += [e.get("partial") for e in (dpx or {}).values() if isinstance(e, dict) and isinstance(e.get("partial"), dict)]
    n = 0
    for c in snaps:
        if isinstance(c.get("z"), list):
            z9 = sorted({str(aliases.get(str(k), str(k))) for k in c["z"]})
            if z9 != sorted(str(k) for k in c["z"]):
                c["z"] = z9
                n += 1
        g = c.get("g")
        if not isinstance(g, dict):
            continue
        for old, new in aliases.items():
            if old not in g:
                continue
            v = Decimal(str(g.pop(old)))
            g[new] = float(Decimal(str(g.get(new) or 0)) + v)
            n += 1
    return n


DM_PATH = os.path.join(common.STATE_DIR, "pending_dm.jsonl")
GOPLUS_PATH = os.path.join(common.STATE_DIR, "goplus_cache.json")
GOPLUS_CHAIN_ID = {"eth": "1", "bsc": "56", "base": "8453", "optimism": "10",
                   "arbitrum": "42161", "polygon": "137", "gnosis": "100",
                   "scroll": "534352", "zksync": "324", "robinhood": "4663"}
GOPLUS_TTL = 7 * 86400
GOPLUS_STATUS_PATH = os.path.join(common.STATE_DIR, "goplus_status.json")
GOPLUS_STATUS = {"lastOk": 0, "lastErr": 0, "err": "", "limitedUntil": 0, "pendingNew": 0, "pendingExpired": 0, "deferred": 0}
GOPLUS_T0 = time.time()
GOPLUS_FAIL_RETRY = 3600
GOPLUS_LIMIT_SEC = 300
GOPLUS_LOG_EVERY = 600
BUILD_HIST_N = 60
BUILD_EX_N = 10
EXT_RB_STATUS_PATH = os.path.join(common.STATE_DIR, "ext_rebuild_status.json")
GOPLUS_PERM_N = 3

CHAIN_NAME = {"eth": "Ethereum", "base": "Base", "arbitrum": "Arbitrum", "optimism": "Optimism",
              "polygon": "Polygon", "scroll": "Scroll", "zksync": "zkSync", "gnosis": "Gnosis", "robinhood": "Robinhood",
              "arc": "Arc", "bsc": "BSC", "sol": "Solana"}
common.fill_chain_table(CHAIN_NAME)
STABLE_GROUPS = {"USDT", "USDC", "DAI", "BUSD", "USDG", "USDE", "CUSD", "USD1", "NUSD", "USDM"}
EX_STABLE_SYMS = frozenset(("USDT", "USDC", "FDUSD", "BUSD", "DAI", "TUSD", "USD", "USDG", "USDE", "USD1",
                            "RLUSD", "PYUSD", "USDP", "USDS"))


def _hl_cash_syms() -> frozenset:
    out = {"USDC"}
    try:
        d9 = common.read_json(os.path.join(common.STATE_DIR, "hl_cash_syms.json"), {}) or {}
        out |= {str(x).upper() for x in (d9.get("syms") or []) if isinstance(x, str)}
    except (Exception, SystemExit):
        pass
    return frozenset(out)


def _ex_stable_sym(sym) -> bool:
    s9 = str(sym or "").upper()
    return "@" not in s9 and s9 in EX_STABLE_SYMS
OF_BASIS_KO = {"txid": "txid 일치", "amount_time": "수량·시간 일치", "address": "입금주소 일치", "bridge": "브릿지 도착", "sale": "토큰 세일 입찰",
               "hop_split": "경유 주소 분할 입금", "roundtrip": "프로그램 예치 왕복"}
EPS = Decimal("0.000000001")
LP_CONV_MIN_USD = Decimal(1)
TRANSIT_NET_H = {"TRX": 2, "TRC20": 2, "TRON": 2, "SOL": 2, "SPL": 2, "BSC": 2, "BEP20": 2, "BNB": 2, "ARBITRUM": 2, "ARB": 2,
                 "OPTIMISM": 2, "OP": 2, "BASE": 2, "POLYGON": 2, "MATIC": 2, "POL": 2, "ZKSYNC": 2, "SCROLL": 2, "LINEA": 2,
                 "AVAXC": 2, "AVAX": 2, "KAIA": 2, "KLAY": 2, "APT": 2, "SUI": 2, "TON": 2, "XRP": 2, "XLM": 2, "ATOM": 2,
                 "ETH": 3, "ERC20": 3, "BTC": 6, "LTC": 6, "BCH": 6, "DOGE": 6}
TRANSIT_DEFAULT_H = 6
TRANSIT_OWN_H = 48
OF_NATIVE_SYMS = frozenset(("ETH", "SOL", "BNB", "POL", "MATIC", "AVAX", "XDAI"))
TRANSIT_ASK_DAYS = 30
LP_POS_PATH = os.path.join(common.STATE_DIR, "lp_positions.json")
RABBY_PATH = os.path.join(common.STATE_DIR, rabby.STATE_NAME)
RABBY_DAILY_PATH = os.path.join(common.STATE_DIR, rabby.DAILY_NAME)
LP_OPEN_SEC = 300
SALE_PATH = os.path.join(common.STATE_DIR, sale_match.CACHE_NAME)
SALE_SEC = 300
LP_CLOSED_SEC = 6 * 3600


_HEX64_TX = re.compile(r"[0-9a-fA-F]{64}")


def _txk(t) -> str:
    t = str(t or "")
    return t.lower() if (t.startswith("0x") or _HEX64_TX.fullmatch(t)) else t


OFFC_EXCHANGES = ("binance", "bybit", "okx", "kucoin", "gate", "bithumb")
OFFC_TX_PREFIX = "off-chain transfer"


def _offc_tx(t) -> bool:
    return str(t or "").strip().lower().startswith(OFFC_TX_PREFIX)


def _offc_on(prefs) -> frozenset:
    v = prefs.get("offchain_self") if isinstance(prefs, dict) else None
    if not isinstance(v, dict):
        return frozenset()
    return frozenset(k for k, on in v.items() if k in OFFC_EXCHANGES and on is True)


def _offc_answered(prefs) -> dict:
    v = prefs.get("offchain_self") if isinstance(prefs, dict) else None
    return {k: on for k, on in v.items() if k in OFFC_EXCHANGES and isinstance(on, bool)} if isinstance(v, dict) else {}


def _offc_excl(prefs) -> dict:
    v = prefs.get("offchain_self_excl") if isinstance(prefs, dict) else None
    if not isinstance(v, dict):
        return {}
    return {k: frozenset(xfer_match.norm_addr(a) for a in lst if isinstance(a, str) and a.strip())
            for k, lst in v.items() if k in OFFC_EXCHANGES and isinstance(lst, list)}


def _f(x: Decimal | float | None, nd=6):
    if x is None:
        return None
    return round(float(x), nd)


def _recon_q(q) -> str:
    try:
        d = Decimal(str(q))
    except (InvalidOperation, ValueError, TypeError):
        return str(q)
    if not d.is_finite() or d == 0:
        return "0"
    a = abs(d)
    nd = 4 if a >= 1 else min(12, max(4, 3 - a.adjusted()))
    t = f"{a:,.{nd}f}"
    t = t.rstrip("0").rstrip(".") if "." in t else t
    return "0" if t in ("0", "") else ("-" if d < 0 else "") + t


def _tax_add(t, k, v):
    t["_" + k] = float(t.get("_" + k, t.get(k) or 0)) + float(v)
    t[k] = _f(t["_" + k], 2)


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
    except Exception:
        return False


class Spot:

    STALE_SEC = 3600
    MIN_RESERVE_USD = 10_000.0
    RESERVE_STALE_SEC = 6 * 3600
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
        self.fx_basis = d.get("fx_basis") or 0
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
        creds = {}
        try:
            with open(common.ENV_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("TJ_OKX_KEY="):
                        creds["key"] = line.split("=", 1)[1]
                    elif line.startswith("TJ_OKX_SECRET="):
                        creds["secret"] = line.split("=", 1)[1]
                    elif line.startswith("TJ_OKX_PASSPHRASE="):
                        creds["passphrase"] = line.split("=", 1)[1]
        except OSError:
            pass
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
        if px and key in self.guarded and self.guarded[key].startswith("풀 유동성"):
            self._guard_note(key, None, quiet=res is None)
        return px

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
            except Exception as e:
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
            log.warning("업비트 환율 조회 실패(마지막 값 유지): %s", e)
            rate = None
        if rate:
            self.rate = rate
        if now - self._fx_at > 3600:
            fx = pricing.fx_basis_krw_per_usd()
            if fx:
                self.fx_basis = fx
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
            except Exception:
                pass
        self._lap("환율·마켓")
        with self.lock:
            syms = sorted(self.syms)
        if syms:
            usd = {}
            try:
                bn = pricing.binance_spot_usdt()
            except Exception:
                bn = {}
            if bn:
                self._bn_book = (now, bn)
            for s in syms:
                if s in ("USDT", "USDC", "DAI", "BUSD"):
                    usd[s] = 1.0
                elif s in bn:
                    usd[s] = bn[s]
            up_syms = [s for s in syms if s in self.upbit_krw]
            if up_syms and self.rate:
                krw = pricing.upbit_spot_krw(up_syms)
                for s, v in krw.items():
                    if s not in usd:
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
            "dex_usd": self.dex_usd, "dex_ts": self.dex_ts,
            "dex_res": self.dex_res, "dex_res_ts": self.dex_res_ts,
            "ex_usd": self.ex_usd, "ex_ts": self.ex_ts,
            "ex_alt_src": dict(self.ex_alt_src),
            "fx_basis": self.fx_basis,
            "upbit_krw": sorted(self.upbit_krw),
            "upbit_alt": {k: sorted(v) for k, v in self.upbit_alt.items()}, "updated": self.updated,
            "want": {"ex": sorted(self.ex_want), "dex": len(self.token_pairs)}})


def _px_took(px) -> bool:
    f9 = getattr(px, "took_pending", None)
    return bool(f9()) if f9 else False


HIST_NF = "nf"


def _hist_kit_rows(daily, today_iso, cache, flow_nf=(), val_nf=()):
    rows = list(daily or ())
    n = len(rows)
    t0 = datetime.strptime(today_iso, "%Y-%m-%d")
    fnf = set(flow_nf or ())
    vnf = set(val_nf or ())
    out, nf, past, fin = [], set(), 0, 0
    for i, r in enumerate(rows):
        iso = (t0 - timedelta(days=n - 1 - i)).strftime("%Y-%m-%d")
        r2 = dict(r)
        if iso < today_iso:
            past += 1
            c = (cache or {}).get(iso)
            if iso in vnf or not (isinstance(c, dict) and c.get("val") is not None):
                r2[HIST_NF] = ("val", "flow")
                r2["val"] = None
                r2["flow"] = None
                nf.add(iso)
            else:
                fin += 1
                if iso in fnf:
                    r2[HIST_NF] = ("flow",)
                    r2["flow"] = None
                    nf.add(iso)
        out.append(r2)
    return out, nf, (past == 0 or fin > 0)


def _px_tables(px):
    d9 = getattr(px, "d", None)
    if not isinstance(d9, dict):
        return {}, None
    lk9 = getattr(px, "lock", None)
    if lk9 is None:
        return dict(d9.get("fx") or {}), (dict(d9["candle"]) if d9.get("candle") is not None else None)
    with lk9:
        return dict(d9.get("fx") or {}), (dict(d9["candle"]) if d9.get("candle") is not None else None)


def _px_recent(px, sym, ms):
    f9 = getattr(px, "candle_recent", None)
    return f9(sym, ms) if f9 else px.candle_usd(sym, ms)


def _dec_or0(x) -> Decimal:
    try:
        d9 = Decimal(str(x))
        return d9 if d9.is_finite() else Decimal(0)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)


class _BuildObsolete(Exception):
    pass


class StateBuilder:
    LEDGER_GEN = 2
    skip_gen_check = False
    SNAP_TTL = 5
    SNAP_STALE_MAX = 6 * 3600
    BUILD_DUTY = 2.0
    REFRESH_SEC = 15
    ACTIVE_SEC = 90
    INPUT_MAX_AGE = 60
    KEEP_DIAG = os.environ.get("TJ_REPLAY_DEBUG") == "1" or os.environ.get("TJ_KEEP_DIAG") == "1"
    _SIG_SKIP = frozenset(("web_diag.json", "daily_cache.json", "daily_px.json", "px_cache_web.json", "backfill_status.json",
                           "upbit_orders_state.json", "ledger.db-shm", "pending_dm.jsonl.1",
                           "alert_watch.json",
                           "curve_hist.json", "curve_hist_px.json",
                           "search.db", "search.db-wal", "search.db-shm",
                           rawtx_cache.FILE,
                           "web_snap_last.bin", "web_snap_last.bin.tmp",
                           "day_memos.json")
                          + nft.STATE_FILES)
    _SIG_SKIP_RX = re.compile(r"^(cursor_|emitted_|enrich_|pending_detail_|health_|alerts_|runner_)|(token_meta|mint_meta)[\w.-]*\.json$"
                              r"|\.(lock|tmp|pending|log)$|\.bak|\.absent")

    _SIG_CONTENT = ("outflow_decisions.json", "ui_prefs.json")
    PREFS_NOBUILD = frozenset(("alert_prefs", "alert_prefs_v1",
                               "chain_auto_off",
                               "review_len", "review_pause", "review_fill",
                               "plans"))

    def _sig_content(self, name, st9):
        key9 = (st9.st_mtime_ns, st9.st_size, st9.st_ino)
        memo9 = self.__dict__.setdefault("_sigc_memo", {})
        hit9 = memo9.get(name)
        prov9 = frozenset(((self.__dict__.get("_of_auto") or {}).get("proven") or {})) if name == "outflow_decisions.json" else None
        if hit9 is not None and hit9[0] == key9 and hit9[1] == prov9:
            return hit9[2]
        try:
            with open(os.path.join(common.STATE_DIR, name), "rb") as f9:
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
            r9 = self._rtx = rawtx_cache.RawTxCache(common.STATE_DIR, common.DB_PATH)
        return r9

    def _input_sig(self):
        try:
            sig = []
            for p9 in (common.CONFIG_PATH,):
                st9 = os.stat(p9) if os.path.exists(p9) else None
                sig.append((p9, st9.st_mtime_ns, st9.st_size) if st9 else (p9, 0, 0))
            with os.scandir(common.STATE_DIR) as it9:
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
        self.cfg = common.load_config()
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
        self.px = pricing.PxCache(os.path.join(common.STATE_DIR, "px_cache_web.json"))
        self._pxq = pricing.PxFetchQueue(self.px)
        self.daily = common.read_json(DAILY_PATH, {}) if os.path.exists(DAILY_PATH) else {}
        if self.daily.get("_v") != DAILY_V:
            if any(not str(k).startswith("_") for k in self.daily):
                log.info("일별 캐시 v%s → v%s: 마감값 정의 통일로 지난날 1회 재계산", self.daily.get("_v"), DAILY_V)
            live9 = self.daily.get("_live") if self.daily.get("_v") == 3 and isinstance(self.daily.get("_live"), dict) else None
            self.daily = {"_v": DAILY_V}
            if live9:
                self.daily["_live"] = live9
        dpx9 = common.read_json(DAILY_PX_PATH, {}) if os.path.exists(DAILY_PX_PATH) else {}
        self.daily_px = dpx9 if isinstance(dpx9, dict) and dpx9.get("_v") == 1 else {"_v": 1}
        seed9 = common.read_json(DAILY_PX_SEED, {}) if os.path.exists(DAILY_PX_SEED) else {}
        self._daily_seed = {k9: v9 for k9, v9 in (seed9 or {}).items()
                            if not str(k9).startswith("_") and isinstance(v9, dict) and v9.get("src") == "live"
                            and isinstance(v9.get("g"), dict)}
        self._upbit_krw_tl = None
        self._rtx = rawtx_cache.RawTxCache(common.STATE_DIR, common.DB_PATH)
        self.cache = None
        self.cache_at = 0.0
        self.lock = threading.Lock()
        self.snaps = websnap.SnapStore()
        self._build_err = None
        self._refreshing = False
        self._last_client = 0.0
        self._built_sig = None
        try:
            wd0 = (common.read_json(WEB_DIAG_PATH, {}) or {}) if os.path.exists(WEB_DIAG_PATH) else {}
            bh0 = wd0.get("build_hist") if isinstance(wd0, dict) else None
            if isinstance(bh0, list):
                self._build_hist = [int(x) for x in bh0 if isinstance(x, (int, float)) and not isinstance(x, bool)][-BUILD_HIST_N:]
            bx0 = wd0.get("build_ex") if isinstance(wd0, dict) else None
            if isinstance(bx0, list):
                self._build_ex = [{"ms": int(x["ms"]), "at": int(x["at"]), "why": str(x.get("why") or "")[:20]} for x in bx0
                                  if isinstance(x, dict) and isinstance(x.get("ms"), (int, float)) and isinstance(x.get("at"), (int, float))][-BUILD_EX_N:]
        except (Exception, SystemExit):
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
        self._bot_wallet_usd = rabby.load_bot_usd(os.path.join(common.STATE_DIR, rabby.BOTUSD_NAME))
        self._lp_targets = []
        self._lp_lock = threading.Lock()
        threading.Thread(target=self._lp_worker, daemon=True, name="lp-worker").start()
        threading.Thread(target=self._rabby_worker, daemon=True, name="rabby-worker").start()
        self._addr_ai_targets = []
        self._addr_ai_paused = lambda: review_pause_eff(self.prefs()).get("on")
        self._addr_ai_busy = lambda: bool(SELL_EVALS.running or BUY_EVALS.running)
        threading.Thread(target=addr_ai.worker_loop, args=(self,), daemon=True, name="addr-ai-worker").start()

    def _hist_wallets(self) -> list:
        return common.history_wallets(self.cfg)

    def _spot_off(self):
        off = set(self.cfg.get("_disabled_chains") or ())
        self.spot.off_chains = off
        if not off:
            return
        try:
            raw9 = common.read_json(common.CONFIG_PATH, {}) or {}
        except (Exception, SystemExit):
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
                log.warning("rabby-worker 실패(다음 주기): %s", e)
            time.sleep(max(60.0, s["tick_sec"]))

    def _lp_worker(self):
        time.sleep(20)
        while True:
            try:
                self._lp_refresh_once()
            except (Exception, SystemExit) as e:
                log.warning("lp-worker 실패(다음 주기): %s", e)
            time.sleep(LP_OPEN_SEC)

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
        log.info("lp-worker: %d/%d 포지션 온체인 갱신 (대상 %d)", n_ok, n_try, len(targets))
        return n_ok, n_try

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
                log.warning("flow-worker 실패(다음 주기): %s", e)
            time.sleep(float(ft.get("interval_sec") or 60))

    def _flow_sym_of(self):
        try:
            conn = dbm.open_db(common.DB_PATH, readonly=True)
        except Exception:
            return lambda ch, tok: None
        try:
            m = {}
            for r in conn.execute("SELECT a.chain, a.address, a.symbol, g.name AS gname FROM assets a LEFT JOIN asset_groups g"
                                  " ON g.group_id=a.group_id WHERE a.address IS NOT NULL").fetchall():
                m[(r["chain"], xchain_match.norm(r["address"]))] = self._gsym(r)
        except Exception:
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
        except Exception:
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
                                    d9 = json.loads(r9.read().decode())
                            except urllib.error.HTTPError as he9:
                                netpace.note_error(url, he9)
                                raise
                            if isinstance(d9, dict) and d9.get("hash"):
                                f9 = d9.get("from") or {}; t9 = d9.get("to") or {}
                                found = {"chain": name, "from": str(f9.get("hash") or "").lower() or None,
                                         "to": str(t9.get("hash") or "").lower() or None, "t": now9}
                                break
                        except Exception:
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
                log.warning("origin-worker 실패(다음 주기): %s", e)

    def _sale_worker(self):
        time.sleep(120)
        while True:
            try:
                self._sale_refresh_once()
            except (Exception, SystemExit) as e:
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

    def prefs(self):
        return common.read_json(PREFS_PATH, {"plans": {}, "ignored": []}) \
            if os.path.exists(PREFS_PATH) else {"plans": {}, "ignored": []}

    def _load(self, conn):
        rows = conn.execute(
            "SELECT p.posting_id, p.source_ns, p.source_id, p.leg_seq, p.event_ts, p.asset_id,"
            " p.location, p.qty_base, p.cost_usd, p.cost_krw, p.leg_kind, p.event,"
            " a.symbol, a.kind, a.chain, a.address, a.decimals, a.group_id, g.name AS gname"
            " FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
            " LEFT JOIN asset_groups g ON g.group_id = a.group_id"
            " ORDER BY p.event_ts, p.source_ns, p.source_id,"
            " CASE p.leg_kind WHEN 'disp' THEN 0 WHEN 'acq' THEN 1 ELSE 2 END, p.leg_seq").fetchall()
        return rows

    def _drop_cancelled_openings(self, rows):
        pos, neg, by_loc = {}, {}, {}
        for r in rows:
            k = (r["asset_id"], r["location"] or "")
            by_loc.setdefault(k, []).append(r)
            if r["leg_kind"] != "opening" or r["event"] != "OPENING":
                continue
            q = int(r["qty_base"])
            sid = str(r["source_id"] or "")
            if q > 0 and sid.startswith("recon:"):
                pos.setdefault(k, []).append(r)
            elif q < 0 and sid.startswith("rebal"):
                neg.setdefault(k, []).append(r)
        drop = set()
        for k, ps in pos.items():
            ns = neg.get(k) or []
            pairs = [(p, n) for p in ps for n in ns if n["event_ts"] >= p["event_ts"]
                     and abs(int(p["qty_base"]) + int(n["qty_base"])) <= max(1, int(p["qty_base"]) // 10 ** 6)]
            if len(pairs) != 1:
                continue
            p, n = pairs[0]
            if (p["gname"] or "") in STABLE_GROUPS:
                continue
            pid = {p["posting_id"], n["posting_id"]}
            mid = [r for r in by_loc[k] if r["posting_id"] not in pid and p["event_ts"] <= r["event_ts"] <= n["event_ts"]]
            if not mid:
                continue
            run, lo = 0, 0
            for r in by_loc[k]:
                if r["event_ts"] > n["event_ts"]:
                    break
                if r["posting_id"] in pid:
                    continue
                run += int(r["qty_base"])
                lo = min(lo, run)
            if lo < -max(1, int(p["qty_base"]) // 10 ** 6):
                continue
            drop |= pid
        self._open_cancel_n = len(drop) // 2
        return [r for r in rows if r["posting_id"] not in drop] if drop else rows

    def _norm(self, row) -> Decimal:
        dec = row["decimals"] if row["decimals"] is not None else 18
        return Decimal(int(row["qty_base"])) / (Decimal(10) ** int(dec))

    @staticmethod
    def _flow_chain(fl) -> str:
        chl = fl.get("chl") or {}
        if not chl:
            return CHAIN_NAME.get(fl["chain"], fl["chain"])
        labs = [k for k, _ in sorted(chl.items(), key=lambda kv: (-kv[1], kv[0]))]
        return " · ".join(labs) if len(labs) <= 2 else " · ".join(labs[:2]) + f" 외 {len(labs) - 2}"

    PREWIN_MAX = 20000

    @staticmethod
    def _prewin_pairs(conn, cap: int = None) -> set:
        cap = StateBuilder.PREWIN_MAX if cap is None else cap
        out = set()
        try:
            ks = conn.execute("SELECT k FROM meta WHERE k >= 'ext_prewindow_tx:' AND k < 'ext_prewindow_tx;' LIMIT ?", (int(cap),)).fetchall()
            for (k9,) in ks:
                parts = str(k9).split(":", 2)
                if len(parts) != 3:
                    continue
                for g9, loc9 in conn.execute(
                        "SELECT DISTINCT a.group_id, p.location FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
                        " WHERE p.source_kind='chain_tx' AND p.source_ns=? AND p.source_id=?", (parts[1], parts[2])).fetchall():
                    if g9 is not None:
                        out.add((int(g9), loc9))
        except Exception as e9:
            log.warning("재계산 대기 표식 읽기 실패(원장 음수 보유 문구 구분 없이): %s", type(e9).__name__)
            return set()
        return out

    @staticmethod
    def _gsym(row) -> str:
        k9 = (row["gname"], row["symbol"])
        v9 = _GSYM_MEMO.get(k9)
        if v9 is not None:
            return v9
        v9 = StateBuilder._gsym_calc(row)
        if len(_GSYM_MEMO) < 200000:
            _GSYM_MEMO[k9] = v9
        return v9

    @staticmethod
    def _gsym_calc(row) -> str:
        name = row["gname"] or (row["symbol"] or "?")
        if row["symbol"] and re.fullmatch(r"TOKEN#\d+", name or ""):
            return str(row["symbol"]).strip() or "TOKEN"
        return re.sub(r"#\d+$", "", name)

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
            d9 = common.read_json(EXT_RB_STATUS_PATH, {}) if os.path.exists(EXT_RB_STATUS_PATH) else {}
        except (Exception, SystemExit):
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
            except Exception as e9:
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
                    conn = dbm.open_db(common.DB_PATH, readonly=True)
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
                self._build_err = f"{type(e).__name__}: {common.safe_err(e)}"
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
        return out

    @staticmethod
    def _label_map(cfg) -> dict:
        out = {}
        for w in common.history_wallets(cfg):
            a = w["address"] if w.get("type") == "sol" else w["address"].lower()
            if w.get("label"):
                out[a] = w["label"]
        return out

    def _cfg_hot_refresh(self) -> bool:
        sig9 = _cfg_file_sig()
        if sig9 is None or sig9 == self.__dict__.get("_cfg_hot_sig"):
            return False
        try:
            with open(common.CONFIG_PATH, "r", encoding="utf-8") as f9:
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
                    except Exception as e:
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
            except Exception as e:
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

    MP_KINDS = frozenset(("of_memo", "day_memo", "plan", "review"))

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
        except Exception as e:
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
            g["plans"], g["planMemos"] = self._plans_view(self.prefs())
        if "review" in kinds:
            pr9 = self.prefs()
            for k9, v9 in (("reviewLen", review_len_eff(pr9)), ("reviewPause", review_pause_eff(pr9)),
                           ("reviewFill", review_progress.fill_eff(pr9.get("review_fill")) if review_progress is not None else None)):
                if k9 not in f:
                    raise ValueError("리뷰 칸 없음")
                g[k9] = v9
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
            except Exception as e:
                log.warning("health 요약 실패(무시): %s", e)
                pub = out
            snap9 = _publish_snap(pub, gen, out)
            if at is not None:
                snap9.at = float(at)
            self.snaps.publish(snap9)
            self._build_err = None
            if self.__dict__.get("_snapfile_on") and gen == self.__dict__.get("_inval", 0):
                _snapfile_save(snap9, still_ok=lambda: self.__dict__.get("_inval", 0) == gen)
        except Exception as e:
            self._build_err = f"publish {type(e).__name__}: {common.safe_err(e)}"
            log.warning("스냅샷 게시 실패: %s", e)

    def restore_snapfile(self) -> bool:
        ok = False
        try:
            _snapfile_sig()
        except Exception as e:
            log.warning("스냅샷 저장본 서명 실패(저장본 끔): %s", type(e).__name__)
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
        except Exception as e:
            log.warning("스냅샷 저장본 복원 실패(무시): %s", type(e).__name__)
        self.__dict__["_snapfile_on"] = True
        return ok

    MATS_FREE = frozenset(("/api/state", "/api/v2/state", "/api/v2/part", "/api/health", "/api/wallet_reload"))

    def mats_wait(self, path) -> bool:
        if not self.__dict__.get("_restored") or self.__dict__.get("_last_out") is not None:
            return True
        if not str(path).startswith("/api/") or path in self.MATS_FREE or path == "/api/ops" or str(path).startswith("/api/ops/"):
            return True
        try:
            self.build()
        except Exception as e:
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
            except (Exception, SystemExit) as e:
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
        if not self.skip_gen_check:
            v9 = conn.execute("SELECT v FROM meta WHERE k='schema_version'").fetchone()
            if v9 is None or int(v9["v"] if hasattr(v9, "keys") else v9[0]) != self.LEDGER_GEN:
                raise RuntimeError(f"원장 세대 불일치: DB={v9[0] if v9 else None} web={self.LEDGER_GEN} — 마이그레이션 상태 확인")
        self._ph("prep")
        rows = self._drop_cancelled_openings(self._load(conn))
        prefs = self.prefs()
        fb_on = bool(prefs.get("fallback_avg"))
        offc_on = _offc_on(prefs)
        offc_ans = _offc_answered(prefs)
        offc_excl = _offc_excl(prefs)
        gas_on = prefs.get("gas_in_cost")
        if gas_on is None:
            gas_on = self.cfg.get("gas_in_cost", True)
        gas_on = bool(gas_on)
        gas_applied = {"buy": Decimal(0), "sell": Decimal(0), "n": 0}
        gas_expense = {}
        ex_fee = {}
        ex_fee_m = {}
        up_fee = {}
        up_mkt = {}
        krw_mkt = {(r0["source_ns"], r0["source_id"]) for r0 in rows
                   if r0["leg_seq"] == 1 and str(r0["source_ns"] or "").endswith(":trade") and str(r0["symbol"] or "").upper() == "KRW"}
        try:
            for uid9, pl9 in conn.execute(
                    "SELECT uuid, payload FROM raw_ex WHERE exchange='upbit' AND kind='order'"
                    " GROUP BY uuid HAVING revision = MAX(revision)").fetchall():
                o9 = json.loads(pl9)
                mk9 = str(o9.get("market") or "").upper()
                if mk9.startswith("KRW-"):
                    krw_mkt.add(("upbit:order", uid9))
                if "-" in mk9:
                    up_mkt[uid9] = mk9.split("-", 1)[0]
                    f9, e9 = Decimal(str(o9.get("executed_funds") or "0")), Decimal(str(o9.get("paid_fee") or "0"))
                    if f9 > 0 and e9 > 0:
                        up_fee[uid9] = (f9, e9)
        except (ValueError, TypeError, InvalidOperation) as e9:
            log.warning("업비트 수수료 원본 읽기 실패(수수료 열 0 유지): %s", e9)

        kst_fm = {}

        def kst_fmt(ts9, fmt9):
            t9 = type(ts9)
            k9 = ("m", fmt9, ts9 // 60) if t9 is int else ("f", fmt9, ts9) if t9 is float else None
            if k9 is None:
                return datetime.fromtimestamp(ts9, KST).strftime(fmt9)
            v9 = kst_fm.get(k9)
            if v9 is None:
                v9 = kst_fm[k9] = datetime.fromtimestamp(ts9, KST).strftime(fmt9)
            return v9

        def ex_fee_add(ex9, usd9, ts9):
            if usd9 <= 0:
                return
            a9 = ex_fee.setdefault(ex9, {"usd": Decimal(0), "tx": 0})
            a9["usd"] += usd9
            a9["tx"] += 1
            m9 = ex_fee_m.setdefault(kst_fmt(ts9, "%Y-%m"), {}).setdefault(ex9, {"usd": Decimal(0), "tx": 0})
            m9["usd"] += usd9
            m9["tx"] += 1
        cost_ov = prefs.get("cost_overrides") or {}
        cost_be = prefs.get("cost_breakeven") if isinstance(prefs.get("cost_breakeven"), dict) else {}

        def be_until(gid9):
            v9 = cost_be.get(f"g{gid9}")
            try:
                t9 = float(v9.get("until")) if isinstance(v9, dict) and v9.get("until") is not None else None
            except (TypeError, ValueError, OverflowError):
                return None
            return t9 if t9 is not None and 0 < t9 < 1e11 else None

        def be_cap_of(v9):
            if not isinstance(v9, dict) or "qty" not in v9:
                return None
            try:
                q9 = Decimal(str(v9.get("qty"))) if v9.get("qty") is not None else Decimal(0)
            except (InvalidOperation, TypeError, ValueError):
                return Decimal(0)
            return q9 if (q9.is_finite() and q9 >= 0) else Decimal(0)
        cost_be = {k9: dict({"until": be_until(k9[1:])},
                            **({"qty": str(be_cap_of(cost_be[k9]))} if be_cap_of(cost_be[k9]) is not None else {}))
                   for k9 in cost_be
                   if isinstance(k9, str) and re.fullmatch(r"g[0-9]+", k9)
                   and be_until(k9[1:]) is not None}
        be_cap = {k9[1:]: be_cap_of(v9) for k9, v9 in cost_be.items()}
        be_used = {}

        def be_take(gid9, ts9, q9):
            u9 = be_until(gid9)
            if u9 is None or ts9 > u9:
                return False
            cap9 = be_cap.get(str(gid9))
            used9 = be_used.get(str(gid9), Decimal(0))
            if cap9 is not None and (cap9 <= 0 or used9 + q9 > cap9 * (1 + Decimal("1e-12")) + EPS):
                return False
            be_used[str(gid9)] = used9 + q9
            return True
        be_done = {}
        be_tax = []
        now = time.time()
        today_kst = datetime.now(KST)
        backfill_t0 = now - float(self.cfg.get("backfill_months") or 5) * 30 * 86400
        _bf_since = bf_engine.SINCE.target(None)
        if _bf_since and not self.cfg.get("backfill_full_history"):
            backfill_t0 = min(backfill_t0, float(_bf_since))
        exf_first = {}
        for r9 in rows:
            if r9["event"] == "EXF_ADJUST":
                try:
                    b9 = int(str(r9["source_id"]).rsplit(":", 1)[1])
                except (IndexError, ValueError):
                    continue
                exf_first[r9["source_ns"]] = min(exf_first.get(r9["source_ns"], b9), b9)
        exf_open_span = float(self.cfg.get("backfill_months") or 5) * 30 * 86400
        ex_debt9 = {}
        ex_loan9 = {}
        for ex9 in ("binance", "bybit", "okx", "kucoin", "gate", "bithumb"):
            bp9 = os.path.join(common.STATE_DIR, f"exf_balances_{ex9}.json")
            if not os.path.exists(bp9):
                continue
            bd9 = common.read_json(bp9, {}) or {}
            for ln9 in (bd9.get("loans") if isinstance(bd9.get("loans"), list) else ()):
                if isinstance(ln9, dict) and isinstance(ln9.get("debt"), dict):
                    for s9 in ln9["debt"]:
                        ex_loan9.setdefault(f"{ex9}:recon", {})[str(s9).upper()] = str(ln9.get("label") or "담보대출")
            dd9 = bd9.get("debts")
            for s9, v9 in (dd9.items() if isinstance(dd9, dict) else ()):
                try:
                    fv9 = float(v9)
                except (TypeError, ValueError):
                    continue
                if fv9 < 0:
                    ex_debt9.setdefault(f"{ex9}:recon", {})[str(s9).upper()] = Decimal(str(fv9))

        def exf_kind(r9):
            if r9["event"] != "EXF_ADJUST":
                return None
            try:
                b9 = int(str(r9["source_id"]).rsplit(":", 1)[1])
            except (IndexError, ValueError):
                return None
            if int(r9["event_ts"]) <= b9 - exf_open_span + 86400:
                return "open"
            return "init" if b9 <= exf_first.get(r9["source_ns"], b9) + 72 * 3600 else "fix"

        G = {}
        gas_by_chain = {}
        gas_by_month = {}
        tax_rows = []
        realized_by_date = {}
        realized_by_loc = {}
        extra_events = []
        stake_rwd = {}
        stake_inc = {}
        ub_wd_shown = set()
        swap_dep = {}
        unverified = {}
        noproc = {}
        unv_fb9 = {}
        bridge_outs = []
        fx_wd = {}
        fx_uid_tx = {}
        fx_name = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX",
                   "kucoin": "쿠코인", "gate": "게이트", "bithumb": "빗썸", "upbit": "업비트", "hyperliquid": "Hyperliquid"}
        wd_raw9 = {}
        offc_wd, offc_dep = set(), set()
        offc_wd_addr = {}
        offc_pool = {}
        offc_st = {}

        def offc_s(ex9):
            return offc_st.setdefault(ex9, {"wdN": 0, "wdCost": Decimal(0), "wdUnkQty": Decimal(0), "depN": 0, "inhN": 0,
                                            "inhCost": Decimal(0), "inhQty": Decimal(0), "inhUnkQty": Decimal(0),
                                            "excessQty": Decimal(0), "excessN": 0, "syms": set(),
                                            "wdCostStable": Decimal(0), "inhCostStable": Decimal(0), "bySym": {}, "byAddr": {},
                                            "exclN": 0, "exclCost": Decimal(0)})

        def offc_self_wd(ex9, uid9):
            return (ex9 in offc_on and (ex9, uid9) in offc_wd
                    and not (offc_wd_addr.get((ex9, uid9)) and offc_wd_addr[(ex9, uid9)] in offc_excl.get(ex9, ())))

        def offc_addr_add(ex9, uid9, cost9):
            a9 = offc_wd_addr.get((ex9, uid9)) or ""
            b9 = offc_s(ex9)["byAddr"].setdefault(a9, [0, Decimal(0)])
            b9[0] += 1
            b9[1] += cost9
            if a9 and a9 in offc_excl.get(ex9, ()) and ex9 in offc_on:
                offc_s(ex9)["exclN"] += 1
                offc_s(ex9)["exclCost"] += cost9

        def offc_add(ex9, sym9, stable9, wd=None, dep=False, inh=None):
            s9 = offc_s(ex9)
            b9 = s9["bySym"].setdefault(sym9, {"wdN": 0, "wdCost": Decimal(0), "depN": 0, "inhN": 0, "inhCost": Decimal(0), "stable": bool(stable9)})
            if wd is not None:
                b9["wdN"] += 1
                b9["wdCost"] += wd
                if stable9:
                    s9["wdCostStable"] += wd
            if dep:
                b9["depN"] += 1
            if inh is not None:
                b9["inhN"] += 1
                b9["inhCost"] += inh
                if stable9:
                    s9["inhCostStable"] += inh

        def offc_summary():
            out9 = {}
            for ex9 in sorted(set(offc_st) | set(offc_on) | set(offc_ans)):
                s9 = offc_s(ex9)
                left9 = {}
                for (e9, _k9), ls9 in offc_pool.items():
                    if e9 != ex9:
                        continue
                    for l9 in ls9:
                        if l9["left"] > EPS and l9["qty"] > 0:
                            a9 = left9.setdefault(l9["sym"], [Decimal(0), Decimal(0), 0])
                            a9[0] += l9["left"]
                            a9[1] += l9["cost"] * l9["left"] / l9["qty"]
                            a9[2] += 1
                out9[ex9] = {"on": ex9 in offc_on, "name": fx_name.get(ex9, ex9),
                             "answered": ex9 in offc_ans,
                             "excl": sorted(offc_excl.get(ex9, ())), "exclN": s9["exclN"], "exclCost": _f(s9["exclCost"], 2) or 0,
                             "byAddr": [{"addr": a0, "n": v9[0], "cost": _f(v9[1], 2) or 0, "excl": bool(a0 and a0 in offc_excl.get(ex9, ()))}
                                        for a0, v9 in sorted(s9["byAddr"].items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))[:40]],
                             "assumedSold": {"n": offc_sold[0], "realized": _f(offc_sold[1], 2) or 0} if ex9 in offc_on else None,
                             "wdN": s9["wdN"], "wdCost": _f(s9["wdCost"], 2) or 0, "depN": s9["depN"], "syms": len(s9["syms"]),
                             "inhN": s9["inhN"], "inhCost": _f(s9["inhCost"], 2) or 0,
                             "excessN": s9["excessN"],
                             "poolLeftN": sum(v9[2] for v9 in left9.values()),
                             "poolLeftCost": _f(sum((v9[1] for v9 in left9.values()), Decimal(0)), 2) or 0,
                             "poolLeft": [[s0, _f(v9[0], 6) or 0, _f(v9[1], 2) or 0]
                                          for s0, v9 in sorted(left9.items(), key=lambda kv: -kv[1][1])[:12]],
                             "wdCostStable": _f(s9["wdCostStable"], 2) or 0, "inhCostStable": _f(s9["inhCostStable"], 2) or 0,
                             "bySym": [{"sym": s0, "wdN": b9["wdN"], "wdCost": _f(b9["wdCost"], 2) or 0, "depN": b9["depN"], "inhN": b9["inhN"],
                                        "inhCost": _f(b9["inhCost"], 2) or 0, "stable": b9["stable"],
                                        "leftCost": _f(left9.get(s0, [0, Decimal(0)])[1], 2) or 0}
                                       for s0, b9 in sorted(s9["bySym"].items(), key=lambda kv: (kv[1]["stable"], -kv[1]["wdCost"], kv[0]))[:30]]}
            return out9
        for rf in conn.execute(
                "SELECT exchange, uuid, payload FROM raw_ex WHERE kind='withdraw'"
                " GROUP BY exchange, uuid HAVING revision = MAX(revision)").fetchall():
            try:
                pw = json.loads(rf["payload"])
            except json.JSONDecodeError:
                continue
            if isinstance(pw, dict):
                wd_raw9[(rf["exchange"], rf["uuid"])] = pw
            if isinstance(pw, dict) and _offc_tx(pw.get("txid")):
                offc_wd.add((rf["exchange"], rf["uuid"]))
                offc_wd_addr[(rf["exchange"], rf["uuid"])] = xfer_match.norm_addr(pw.get("address")) if pw.get("address") else ""
            t9 = str(pw.get("txid") or "")
            if t9 and str(pw.get("state") or "").upper() == "DONE":
                t9n = _txk(t9)
                fx_wd[t9n] = fx_name.get(rf["exchange"], rf["exchange"])
                fx_uid_tx[rf["uuid"]] = t9n
        try:
            for u9h, t9h in self._hl_bridge_links(conn, wd_raw9).items():
                fx_uid_tx[u9h] = _txk(t9h)
                fx_wd[_txk(t9h)] = fx_name.get("hyperliquid", "Hyperliquid")
        except Exception as e9h:
            log.warning("Hyperliquid 출금 ↔ 지갑 도착 연결 실패(이번 빌드 생략): %s", common.safe_err(e9h)[:160])
        fx_transit = {}
        wd_tr = []
        fx_dep_tx = {}
        fx_dep_uid_tx = {}
        dep_net9 = {}
        for rf in conn.execute(
                "SELECT exchange, uuid, payload FROM raw_ex WHERE kind='deposit'"
                " AND exchange != 'upbit'"
                " GROUP BY exchange, uuid HAVING revision = MAX(revision)").fetchall():
            try:
                pw = json.loads(rf["payload"])
            except json.JSONDecodeError:
                continue
            t9 = str(pw.get("txid") or "")
            if _offc_tx(t9):
                offc_dep.add((rf["exchange"], rf["uuid"]))
            if t9 and str(pw.get("network") or pw.get("net_type") or "").strip():
                dep_net9[t9.lower()] = (str(pw.get("network") or pw.get("net_type")).strip(), pw.get("currency"))
            if t9 and str(pw.get("state") or "").upper() == "ACCEPTED":
                t9n = _txk(t9)
                fx_dep_tx[t9n] = rf["exchange"]
                fx_dep_uid_tx[rf["uuid"]] = t9n
        diag = {"ex_out_cost": Decimal(0), "ex_out_n": 0, "ex_dep_inh_cost": Decimal(0), "ex_dep_inh_n": 0,
                "ex_dep_unlinked_n": 0, "ex_transit_unused_cost": Decimal(0),
                "ex_dep_fee_resid_cost": Decimal(0),
                "exf_dep_inh_cost": Decimal(0), "exf_dep_inh_n": 0,
                "of_bridge_inh_cost": Decimal(0), "of_bridge_inh_n": 0,
                "xc_inh_cost": Decimal(0), "xc_inh_n": 0, "xc_link_n": 0, "xc_sale_drop_n": 0, "xc_hop_drop_n": 0}
        up_dep_uid_tx = {}
        up_dep_uid_ts = {}
        wallet_label = {}
        for w9 in self._hist_wallets():
            wallet_label[str(w9.get("address") or "").lower()] = str(w9.get("label") or w9.get("chain") or "내 지갑")
        exf_dep_tx = {}
        for rf9 in conn.execute("SELECT exchange, uuid, payload FROM raw_ex WHERE kind='deposit' AND exchange!='upbit'"
                                " GROUP BY exchange, uuid HAVING revision = MAX(revision)"):
            try:
                t9x = str(json.loads(rf9["payload"]).get("txid") or "")
            except (json.JSONDecodeError, TypeError):
                continue
            if t9x:
                exf_dep_tx[(rf9["exchange"], rf9["uuid"])] = t9x
        origin_cache = common.read_json(os.path.join(common.STATE_DIR, "tx_origin_cache.json"), {})
        origin_pending = set()
        now_oc = int(time.time())

        def oc_fresh(k9):
            oc9 = origin_cache.get(k9)
            return isinstance(oc9, dict) and bool(oc9.get("from") or oc9.get("na") or now_oc - int(oc9.get("t") or 0) < 86400)

        snap_cache = {}
        raw_chains9 = [r9[0] for r9 in conn.execute("SELECT DISTINCT chain FROM raw_txs").fetchall()]
        fx_tab, web_candle9 = _px_tables(self.px)

        fxb = acct_norm.FxBook(fx_tab, os.path.join(common.STATE_DIR, "px_cache_core.json"), self.spot.rate or None,
                               web_candle=web_candle9)
        realized_krw_by_date = {}
        fee_disp, fee_acq = {}, {}
        fee_diag = {"n": 0, "usd_cost": Decimal(0), "usd_realized": Decimal(0), "usd_unv": Decimal(0), "no_px": 0}

        def krw_of(usd, ts9, row9=None):
            try:
                usd = Decimal(usd)
            except Exception:
                return Decimal(0)
            if row9 is not None and row9["cost_krw"] is not None and row9["cost_usd"] is not None:
                try:
                    cu9 = Decimal(row9["cost_usd"])
                    if cu9 > 0:
                        return usd * Decimal(row9["cost_krw"]) / cu9
                except Exception:
                    pass
            return usd * Decimal(str(fxb.rate_at(ts9)))

        _AK_TRADE = frozenset(("EX_BUY", "EX_SELL", "EXF_BUY", "EXF_SELL", "SWAP"))
        _AK_RE = re.compile(r"^\$([\d,]+(?:\.\d+)?)$")

        def _ak(a9, ts9, row9=None):
            m9 = _AK_RE.match(str(a9 or ""))
            if not m9:
                return None
            try:
                u9 = float(m9.group(1).replace(",", ""))
                r9 = None
                if row9 is not None and row9["event"] in _AK_TRADE and int(row9["event_ts"] or 0) == int(ts9 or 0):
                    r9 = row9
                return int(round(u9 * float(fxb.rate_at(ts9, r9))))
            except (KeyError, IndexError, TypeError, ValueError):
                return None

        def apply_ov(fl9, pend9):
            ts9, take, unit_d, txt9, ref9, badd9 = pend9
            fl9["cost"] += take * unit_d
            fl9["cost_krw"] += krw_of(take * unit_d, ts9)
            fl9["bought"] += badd9
            ev(fl9, ts9, "원가 지정", txt9, f"{float(take):,.4f}".rstrip("0").rstrip("."), f"${float(take * unit_d):,.2f}", ref9,
               un=_un(take, take * unit_d))

        def note_unk(g9, ts9, kind9, qty9, ref9, ex9=None, chain9=None, up_gid=None, unc9=None, via9=None):
            try:
                q9 = float(qty9)
            except (TypeError, ValueError):
                return
            if q9 <= 1e-9:
                return
            lst9 = g9.setdefault("unk_src", [])
            ref = str(ref9 or "")
            ov9 = cost_ov.get(f"g{g9.get('gid')}") if isinstance(cost_ov, dict) else None
            applied9 = None
            if isinstance(ov9, dict) and ov9.get("mode") in ("unit", "market"):
                unit9 = 0.0
                if ov9.get("mode") == "market":
                    try:
                        unit9 = float(self.px.candle_usd(g9.get("sym") or "", int(ts9) * 1000) or 0)
                    except Exception:
                        unit9 = 0.0
                else:
                    try:
                        unit9 = float(ov9.get("unit") or 0)
                    except (TypeError, ValueError):
                        unit9 = 0.0
                if unit9 > 0:
                    dq = Decimal(str(qty9))
                    take = min(dq, g9["qty_unknown"])
                    if take > 0:
                        g9["qty_unknown"] -= take
                        g9["qty_known"] += take
                        g9["cost"] += take * Decimal(str(unit9))
                        unc_d = dq if unc9 is None else max(Decimal(0), min(dq, Decimal(str(unc9))))
                        pend9 = (ts9, take, Decimal(str(unit9)), ("개당 지정 단가" if ov9.get("mode") != "market" else "유입 당시 시세") + f" ${unit9:,.6g} 적용",
                                 ref if ref.startswith("0x") else "", take * unc_d / dq)
                        if g9.get("cur") is not None:
                            apply_ov(g9["cur"], pend9)
                        else:
                            g9.setdefault("_ov_pend", []).append(pend9)
                        applied9 = {"mode": ov9.get("mode"), "unit": unit9, "qty": float(take)}
            if applied9 is not None:
                ovs9 = g9.setdefault("ov_applied", [Decimal(0), Decimal(0)])
                ovs9[0] += Decimal(str(applied9["qty"])); ovs9[1] += Decimal(str(applied9["qty"])) * Decimal(str(applied9["unit"]))
            ent9 = {"ts": int(ts9), "kind": kind9, "qty": q9, "ref": ref, "ex": ex9,
                    "chain": chain9, "from": None, "to": None, "up_gid": up_gid, "ov": applied9, "via": via9}
            if not ref:
                for y9 in lst9:
                    if not y9["ref"] and y9["kind"] == kind9:
                        y9["qty"] += q9; y9["ts"] = min(y9["ts"], int(ts9))
                        if applied9 is not None:
                            y9["ov"] = y9["ov"] or {"mode": applied9["mode"], "unit": applied9["unit"], "qty": 0.0}
                            y9["ov"]["qty"] += applied9["qty"]
                        break
                else:
                    lst9.append(ent9)
            elif len(lst9) < 60:
                lst9.append(ent9)
            else:
                i_min = min(range(len(lst9)), key=lambda i9: lst9[i9]["qty"])
                if lst9[i_min]["qty"] < q9:
                    lst9[i_min] = ent9

        oc_names9 = set(self._origin_chain_names())

        def _net_na(k9):
            h9 = dep_net9.get(k9)
            if not h9:
                return ""
            return h9[0] if depaddr.chain_of(h9[0], h9[1]) not in oc_names9 else ""

        def resolve_origin(x):
            ref = str(x.get("ref") or "")
            if x.get("from") is not None or not (ref.startswith("0x") and len(ref) == 66):
                return x
            key9 = ref.lower()
            if key9 in snap_cache:
                row9 = snap_cache[key9]
            else:
                sel9 = ("SELECT chain, json_extract(snapshot,'$.tx.from') AS f, json_extract(snapshot,'$.tx.to') AS t,"
                        " json_extract(snapshot,'$.tx.from.hash') AS fh, json_extract(snapshot,'$.tx.to.hash') AS th FROM raw_txs WHERE ")
                ch9 = x.get("chain")
                if ch9:
                    row9 = conn.execute(sel9 + "chain=? AND txhash IN (?, ?) LIMIT 1", (ch9, key9, ref)).fetchone()
                elif raw_chains9:
                    row9 = conn.execute(sel9 + "chain IN (" + ",".join("?" * len(raw_chains9)) + ") AND txhash IN (?, ?)"
                                        " ORDER BY rowid LIMIT 1", (*raw_chains9, key9, ref)).fetchone()
                else:
                    row9 = None
                snap_cache[key9] = row9
            if row9:
                frm = str(row9["fh"] or row9["f"] or "").lower() or None
                to = str(row9["th"] or row9["t"] or "").lower() or None
                if frm and frm.startswith("{"):
                    frm = None
                x["from"], x["to"], x["chain"] = frm, to, (row9["chain"] or x.get("chain"))
            elif key9 in origin_cache:
                oc = origin_cache[key9]
                x["from"], x["to"], x["chain"] = (oc.get("from") or None), (oc.get("to") or None), (oc.get("chain") or x.get("chain"))
                if oc.get("na"):
                    x["oc_na"] = str(oc["na"])
                elif not x["from"] and _net_na(key9):
                    x["oc_na"] = _net_na(key9)
                if not oc_fresh(key9):
                    origin_pending.add(key9)
                elif not x["from"] and not x.get("oc_na"):
                    x["oc_fail"] = int(oc.get("t") or 0) + 86400
            else:
                if _net_na(key9):
                    x["oc_na"] = _net_na(key9)
                origin_pending.add(key9)
            return x

        for rf in conn.execute(
                "SELECT uuid, payload FROM raw_ex WHERE kind='deposit' AND exchange='upbit'"
                " GROUP BY uuid HAVING revision = MAX(revision)").fetchall():
            try:
                pw = json.loads(rf["payload"])
            except json.JSONDecodeError:
                continue
            t9 = str(pw.get("txid") or "")
            if t9 and str(pw.get("net_type") or pw.get("network") or "").strip():
                dep_net9[t9.lower()] = (str(pw.get("net_type") or pw.get("network")).strip(), pw.get("currency"))
            if t9 and str(pw.get("state") or "").upper() == "ACCEPTED":
                up_dep_uid_tx[rf["uuid"]] = _txk(t9)
                try:
                    up_dep_uid_ts[rf["uuid"]] = datetime.fromisoformat(str(pw.get("done_at") or pw.get("created_at"))).timestamp()
                except (ValueError, TypeError):
                    pass
        fxdep_transit = {}
        ub_wd_tx = set()
        for rf in conn.execute(
                "SELECT uuid, payload FROM raw_ex WHERE kind='withdraw'"
                " AND exchange='upbit'"
                " GROUP BY uuid HAVING revision = MAX(revision)").fetchall():
            try:
                pw = json.loads(rf["payload"])
            except json.JSONDecodeError:
                continue
            t9 = str(pw.get("txid") or "")
            if t9:
                ub_wd_tx.add(_txk(t9))
        xc_cache = xchain_match.load_cache(common.STATE_DIR)
        xc_ext = frozenset(xchain_match.norm(a9) for a9, v9 in self.outflow_decisions().items()
                           if isinstance(v9, dict) and v9.get("verdict") == "external")
        xc_off = frozenset(xchain_match.norm(t9) for t9 in (prefs.get("xchain_off") or []))
        xc_transit = xchain_match.transit_for(rows, xc_cache, xc_off, xc_ext)
        xc_stable = frozenset(r0["group_id"] for r0 in rows if (r0["gname"] or "") in STABLE_GROUPS and r0["group_id"] is not None)
        xc_cands = xchain_match.send_candidates(rows, xc_cache, xchain_match.load_seed(common.BASE_DIR)) + \
            xchain_match.candidates(rows, xc_cache, frozenset(set(fx_wd) | ub_wd_tx), xc_stable)
        xc_off9 = set(self.cfg.get("_disabled_chains") or ())
        if xc_off9:
            xc_cands = [c9 for c9 in xc_cands if c9.get("chain") not in xc_off9]
        if hasattr(self, "_xc_lock"):
            with self._xc_lock:
                self._xc_pending = xc_cands[:50]
        xc_used = {}
        self._ph("load·replay")
        to_dest9 = self._transfer_out_dest(conn)
        ex_transit = {}
        uuid2txh = {}
        for r9 in conn.execute(
                "SELECT ex_uuid, chain_txhash FROM transfers WHERE ex_uuid IS NOT NULL").fetchall():
            if r9["ex_uuid"] and r9["chain_txhash"]:
                uuid2txh[r9["ex_uuid"]] = r9["chain_txhash"]

        def _un(qn, usd):
            try:
                qd = qn if type(qn) is Decimal else Decimal(str(qn))
                ud = usd if type(usd) is Decimal else Decimal(str(usd))
            except (InvalidOperation, ValueError, TypeError):
                return None
            if not qd.is_finite() or not ud.is_finite() or qd == 0 or ud == 0:
                return None
            return float(f"{abs(ud / qd):.10g}")

        def extra_ev(ts, sym, k, d, q, a, tx, un=None, vq=None):
            gid_e = None
            if isinstance(sym, dict):
                gid_e, sym = sym.get("gid"), sym.get("sym")
            e0 = {
                "t": kst_fmt(ts, "%m-%d %H:%M"),
                "sym": sym, "k": k, "d": d, "q": q, "a": a, "_gid": gid_e,
                "tx": (tx[:6] + "…" + tx[-4:]) if tx else "—", "src": cur_src[0],
                "_ts": int(ts or 0),
                "_pid": cur_row[0]["posting_id"] if cur_row[0] is not None else None}
            if un is not None:
                e0["un"] = un
            ak9 = _ak(a, ts, cur_row[0])
            if ak9 is not None:
                e0["aK"] = ak9
            if vq is not None:
                e0["_vq"] = vq
            extra_events.append(e0)

        def gstate(row):
            gid = row["group_id"] or -row["asset_id"]
            if gid not in G:
                G[gid] = {
                    "gid": gid, "sym": self._gsym(row), "chains": set(),
                    "is_stable": ((row["gname"] or "") in STABLE_GROUPS
                                  or (row["kind"] == "exchange_currency"
                                      and _ex_stable_sym(row["symbol"]))),
                    "is_fiat": (row["kind"] == "exchange_currency"
                                and (row["symbol"] or "").upper() in ("KRW",)),
                    "qty_known": Decimal(0), "cost": Decimal(0), "qty_unknown": Decimal(0),
                    "realized": Decimal(0), "flows": [], "cur": None, "transit": Decimal(0),
                    "qty_timeline": [],
                }
            return G[gid]

        def consume_krw(g, cost):
            flow = g.get("cur")
            if flow is None or cost <= 0:
                return None
            used = flow.get("_cost_used", Decimal(0))
            left = flow["cost"] - used
            if left <= EPS or abs(left - g["cost"]) > EPS:
                return None
            used_krw = flow.get("_cost_krw_used", Decimal(0))
            taken = (flow["cost_krw"] - used_krw) * cost / left
            flow["_cost_used"] = used + cost
            flow["_cost_krw_used"] = used_krw + taken
            return taken

        def tax_krw_acq(tax9, g, flow, cc9, cck9, rate_s, dkey, venue_loc=None):
            fck9, fcu9 = float(flow.get("cost_krw") or 0), float(flow.get("cost") or 0)
            if not g["is_stable"] and fck9 > 0 and fcu9 > 0 and 0.5 <= (fck9 / fcu9) / max(rate_s, 1.0) <= 2.0:
                tax9["_akr"] = float(cc9) * fck9 / fcu9
                if cck9 is not None and cc9 > 0 and \
                        0.5 <= (float(cck9) / float(cc9)) / max(rate_s, 1.0) <= 2.0:
                    tax9["_akr"] = float(cck9)
                tax9["akr"] = round(tax9["_akr"])
                if float(flow.get("kmc") or 0) >= 0.99 * fcu9:
                    if cck9 is not None:
                        tax9["_akr"] = float(cck9)
                        tax9["akr"] = round(tax9["_akr"])
                    adj9 = float(cc9) * rate_s - tax9["_akr"]
                    flow["rbdk"][dkey] = flow["rbdk"].get(dkey, 0.0) + adj9
                    realized_krw_by_date[dkey] = realized_krw_by_date.get(dkey, 0) + adj9
                    if venue_loc is not None:
                        realized_by_loc.setdefault((venue_loc, dkey), [0.0, 0.0])[1] += adj9
                    tax9["_akm"] = 1

        offc_sold = [0, Decimal(0)]
        krw_last = [None]
        oa_last = [Decimal(0)]

        def oa_take(g9, take9):
            a9 = g9.get("oa") or Decimal(0)
            if a9 <= 0 or take9 <= 0:
                return Decimal(0)
            k9 = g9["qty_known"]
            p9 = a9 if take9 >= k9 else a9 * take9 / k9
            g9["oa"] = a9 - p9
            return p9

        CP_EMIT_MAX = 64
        cp_last = [None]
        cp_ev = {}

        def cp_pool(g):
            if g.get("is_stable"):
                return None
            p9 = g.get("_cp")
            if p9 is None:
                p9 = g["_cp"] = buychart.CpPool()
            return p9

        def cp_add(g, key, q9, c9):
            p9 = cp_pool(g)
            if p9 is not None:
                p9.add(key, q9, c9)

        def cp_add_map(g, mp9, s9):
            p9 = cp_pool(g) if mp9 else None
            if p9 is not None:
                p9.add_map(mp9, s9)

        def cp_sync(g, key=None):
            p9 = cp_pool(g)
            if p9 is not None:
                p9.sync(g["qty_known"], g["cost"], key if key is not None else ("u", g["gid"]))

        def cp_take(g, take9, cost9, want=True):
            p9 = cp_pool(g)
            if p9 is None or float(take9) <= 0:
                return None
            cp_sync(g)
            return p9.take(g["qty_known"], take9, cost9, ("m", g["gid"]), CP_EMIT_MAX, want=want)

        def cp_emit(mp9, unk9, q9, c9):
            if mp9 is None and not unk9:
                return None
            return {"o": [(cp_ev.get(k9), k9, v9[0], v9[1]) for k9, v9 in (mp9 or {}).items()], "unk": float(unk9 or 0), "q": float(q9), "c": float(c9)}

        def cp_merge(dst9, mp9, s9=1.0):
            if not mp9:
                return dst9
            for k9, (q9, c9) in mp9.items():
                a9 = dst9.setdefault(k9, [0.0, 0.0])
                a9[0] += q9 * s9
                a9[1] += c9 * s9
            return dst9

        xc_tok9 = {}
        for v9 in (xc_cache.get("ws") or {}).values():
            for w9 in (v9 if isinstance(v9, list) else ()):
                if isinstance(w9, dict) and w9.get("src_tx") and w9.get("token"):
                    xc_tok9.setdefault(str(w9["src_tx"]).lower(), (str(w9.get("token_chain") or w9.get("src_chain") or ""), str(w9["token"])))
        xc_stx9 = xc_cache.get("stx") if isinstance(xc_cache.get("stx"), dict) else {}
        xc_blk9 = xc_cache.get("blk") if isinstance(xc_cache.get("blk"), dict) else {}
        cp_xrec = {}

        def cp_xc(g, r9, xc9, cov9, inh9, ch9, ts9):
            p9 = cp_pool(g)
            if p9 is None or cov9 <= 0:
                return
            lv9 = buychart.xc_leaves(xc9.get("lots"))
            kq9, kc9 = sum(x9["known"] for x9 in lv9), sum(x9["cost"] for x9 in lv9)
            if not lv9 or kq9 <= 0:
                return
            fq9 = float(cov9) / kq9
            for i9, x9 in enumerate(lv9):
                q9 = x9["known"] * fq9
                c9 = (x9["cost"] * float(inh9) / kc9) if kc9 > 0 else float(inh9) * x9["known"] / kq9
                cc9 = str(x9.get("chain") or ch9 or "")
                tk9 = r9["address"] if cc9 == ch9 else None
                if tk9 is None and x9.get("btx"):
                    bt9 = xc_tok9.get(str(x9["btx"]).lower())
                    tk9 = bt9[1] if bt9 and bt9[0] == cc9 else None
                tsx9 = buychart.xc_lot_ts(xc_stx9, xc_blk9, cc9, x9["tx"], x9.get("block"))
                buy9 = x9["kind"] == "swap"
                info9 = {"chain": cc9, "chainKo": CHAIN_NAME.get(cc9, cc9), "tx": x9["tx"], "block": x9.get("block"), "token": tk9,
                         "arrPid": r9["posting_id"], "arrTs": int(ts9), "via": xc9.get("via") or "", "lot": x9.get("lot"), "depth": x9.get("depth"),
                         "cut": x9.get("cut")}
                if not buy9:
                    info9["rule"] = buychart.in_rule("경유") if x9.get("lot") == "hop" else "경유 역추적 원가 · 더 앞 원천을 못 찾음(그 로트 원가 그대로)"
                rec9 = {"t": datetime.fromtimestamp(tsx9 or ts9, KST).strftime("%m-%d %H:%M"),
                        "k": "온체인 매수" if buy9 else "전송",
                        "d": (f"{CHAIN_NAME.get(cc9, cc9)} · 스왑 매수 · {xc9.get('label') or '경유 역추적'} (원장 밖 · 경유 역추적)" if buy9
                              else f"{xc9.get('label') or '경유 역추적'} · 원가 이관"),
                        "q": f"{q9:.10f}", "a": f"${c9:,.2f}", "tx": "—", "src": None, "_ts": tsx9 if buy9 else int(ts9), "_pid": None,
                        "_xc": info9}
                if buy9 and x9.get("un"):
                    rec9["un"] = x9["un"]
                if buy9:
                    rec9 = cp_xrec.setdefault((cc9, str(x9["tx"]).lower(), r9["posting_id"]), rec9)
                key9 = ("xc", r9["posting_id"], i9)
                cp_add(g, key9, q9, c9)
                cp_ev[key9] = rec9

        def cv_label(mp9, sym9):
            out9, own9 = [], False
            for k9, (q9, _c9) in (mp9 or {}).items():
                e9 = cp_ev.get(k9)
                if q9 > 0 and e9 is not None and e9.get("_cv"):
                    l9 = f"{e9['_cv']['from']} → {sym9}"
                    if l9 not in out9:
                        out9.append(l9)
                elif q9 > 0:
                    own9 = True
            return " · ".join(out9 + ([sym9] if (own9 or not out9) else []))

        def consume(g, qty, cp=True):
            oa_last[0] = Decimal(0)
            krw_last[0] = None
            cost_taken = Decimal(0)
            from_unknown = min(qty, g["qty_unknown"])
            g["qty_unknown"] -= from_unknown
            rem = qty - from_unknown
            take = Decimal(0)
            cp_last[0] = None
            if rem > 0 and g["qty_known"] > EPS:
                wac = g["cost"] / g["qty_known"]
                take = min(rem, g["qty_known"])
                oa_last[0] = oa_take(g, take)
                cp_last[0] = cp_take(g, take, wac * take, cp)
                g["qty_known"] -= take
                cost_taken = wac * take
                krw_last[0] = consume_krw(g, cost_taken)
                g["cost"] -= cost_taken
            return cost_taken, take, from_unknown

        def krw_took(mc9, ts9):
            return krw_last[0] if krw_last[0] is not None else krw_of(mc9, ts9)

        def krw_inh(e9, part9, ts9):
            k9, c9 = e9.get("krw"), e9.get("cost")
            if k9 is not None and c9 is not None and c9 > 0:
                return k9 * part9 / c9
            return krw_of(part9, ts9)

        def flow_of(g, ts, chain):
            if g["cur"] is None:
                g["cur"] = {"opened": ts, "chain": chain, "bought": Decimal(0),
                            "cost": Decimal(0), "realized": Decimal(0), "fee": Decimal(0),
                            "proceeds": Decimal(0),
                            "cost_krw": Decimal(0), "proceeds_krw": Decimal(0),
                            "events": [], "sold_dates": [],
                            "moved_qty": Decimal(0), "moved_cost": Decimal(0),
                            "sold": Decimal(0),
                            "rbd": {}, "ubd": {}, "rbdk": {},
                            "chl": ({cur_lab[0]: 1} if cur_lab[0] else {}), "rch": {}}
                g["cur"]["_gid"] = g["gid"]
                g["flows"].append(g["cur"])
                for pend9 in g.pop("_ov_pend", []):
                    apply_ov(g["cur"], pend9)
            return g["cur"]

        cur_src = [None]
        cur_row = [None]
        cur_lab = [None]

        def _qfmt(v):
            v = float(v)
            return f"{v:,.4f}".rstrip("0").rstrip(".") if abs(v) >= 1 else f"{v:.6g}"

        def unk_tag(fk, fu, proceeds, qty, stable, be=False):
            if fu <= 0 or stable:
                return ""
            pu = proceeds * fu / qty if qty > 0 else Decimal(0)
            if pu < 1:
                return ""
            if be:
                return (f" · 매수가 = 매도가로 처리 ${float(pu):,.2f} (직접 정함 · 손익 없음)" if fk <= 0
                        else f" · 일부 {_qfmt(fu)}개 매수가 = 매도가로 처리 ${float(pu):,.2f} (직접 정함 · 손익 없음)")
            if fk <= 0:
                return f" · 원가미상 ${float(pu):,.2f} (미확인 분류)"
            return f" · 일부 원가미상 {_qfmt(fu)}개 ${float(pu):,.2f} (미확인 분류)"

        def ev(flow, ts, k, d, q, a, tx, un=None):
            e0 = {
                "t": kst_fmt(ts, "%m-%d %H:%M"),
                "k": k, "d": d, "q": q, "a": a,
                "tx": (tx[:6] + "…" + tx[-4:]) if tx else "—", "src": cur_src[0],
                "_ts": int(ts or 0),
                "_pid": cur_row[0]["posting_id"] if cur_row[0] is not None else None}
            if un is not None:
                e0["un"] = un
            ak9 = _ak(a, ts, cur_row[0])
            if ak9 is not None:
                e0["aK"] = ak9
            flow["events"].append(e0)
            if cur_row[0] is not None and flow.get("_gid") is not None and (("매수" in k and "매도" not in k) or k == "LP 수수료 수령"):
                g9b = G.get(flow["_gid"])
                if g9b is not None and not g9b.get("is_stable"):
                    key9 = (cur_row[0]["posting_id"], flow["_gid"])
                    cp_sync(g9b, key9)
                    cp_ev.setdefault(key9, e0)
            elif (cur_row[0] is not None and flow.get("_gid") is not None and k in ("전송", "입금 확인")
                  and cur_row[0]["leg_kind"] in ("acq", "move_in") and (cur_row[0]["group_id"] or -cur_row[0]["asset_id"]) == flow["_gid"]):
                g9b = G.get(flow["_gid"])
                if g9b is not None and not g9b.get("is_stable"):
                    key9 = ("in", cur_row[0]["posting_id"], flow["_gid"])
                    cp_sync(g9b, key9)
                    cp_ev.setdefault(key9, e0)
            if "매수" in k and "매도" not in k:
                flow["nb"] = flow.get("nb", 0) + 1

        def mv_note(fl, label, q, own=True):
            if fl is None or not label or q <= 0:
                return
            a = fl.setdefault("mv_to", {}).setdefault(label, [Decimal(0), own])
            a[0] += q

        def in_note(fl, label, q, cost, ts, story=None, cost_krw=None):
            if fl is None:
                return
            if label and q > 0:
                a = fl.setdefault("in_from", {}).setdefault(label, [Decimal(0), Decimal(0), 0.0])
                a[0] += q
                a[1] += cost
                a[2] += float(krw_of(cost, ts) if cost_krw is None else cost_krw)
            if story:
                fl["story_n"] = fl.get("story_n", 0) + len(story)

        credited_txh = set()
        credited_gid = {}
        for r0 in conn.execute(
                "SELECT t.chain_txhash, t.qty_base, a.group_id, a.decimals FROM transfers t"
                " JOIN assets a ON a.asset_id = t.asset_id WHERE t.state='credited'").fetchall():
            if r0["chain_txhash"]:
                credited_txh.add(r0["chain_txhash"])
            gid0 = r0["group_id"]
            if gid0 is not None:
                qn0 = Decimal(int(r0["qty_base"])) / (Decimal(10) ** int(18 if r0["decimals"] is None else r0["decimals"]))
                credited_gid[gid0] = credited_gid.get(gid0, Decimal(0)) + qn0

        bridge_dep_ts = {}
        for r in rows:
            if r["event"] == "BRIDGE" and r["leg_kind"] == "move_out":
                bridge_dep_ts.setdefault(self._gsym(r), []).append(r["event_ts"])

        _PAY_NAT = {"ETH", "WETH", "SOL", "WSOL", "BNB", "WBNB"}

        def _qk(r9):
            s9 = (r9["symbol"] or "").upper()
            if (r9["gname"] or "") in STABLE_GROUPS or (r9["kind"] == "exchange_currency" and _ex_stable_sym(s9)):
                return "st"
            if r9["kind"] == "exchange_currency" and s9 == "KRW":
                return "fiat"
            return "nat" if self._gsym(r9).upper() in _PAY_NAT else "tok"
        pay_tx = {}
        conv_cp = {}
        for r in rows:
            if r["leg_kind"] in ("acq", "disp") and r["event"] in ("SWAP", "EXF_BUY", "EXF_SELL", "EX_BUY", "EX_SELL"):
                qk9 = _qk(r)
                pay_tx.setdefault((r["source_ns"], r["source_id"]), []).append((r["posting_id"], r["leg_kind"], qk9))
                if r["leg_kind"] == "acq" and qk9 in ("st", "fiat"):
                    cp9 = conv_cp.setdefault((r["source_ns"], r["source_id"]), [])
                    s9 = "원화" if qk9 == "fiat" else self._gsym(r)
                    if s9 not in cp9:
                        cp9.append(s9)
        pay_pid = set()
        for legs9 in pay_tx.values():
            acq9 = {c9 for _p9, lk9, c9 in legs9 if lk9 == "acq"}
            tokd9 = any(lk9 == "disp" and c9 == "tok" for _p9, lk9, c9 in legs9)
            for p9, lk9, c9 in legs9:
                if lk9 == "disp" and ((c9 == "st" and acq9 & {"tok", "nat"}) or (c9 == "nat" and ("tok" in acq9 or tokd9))):
                    pay_pid.add(p9)
        pay_tx = None
        tx_group = {}
        swap_gas = {}
        swap_recv = {}
        swap_pay = {}
        swap_wd_pre = {}
        for r in rows:
            if r["event"] == "EX_WITHDRAW" and r["leg_kind"] == "move_out":
                t9w = fx_uid_tx.get(r["source_id"]) or ""
                if t9w.startswith("swap_"):
                    swap_wd_pre[t9w] = {"sym": self._gsym(r), "gid": r["group_id"] or -r["asset_id"]}
            if r["leg_kind"] == "disp" and r["event"] == "SWAP":
                swap_pay.setdefault((r["source_ns"], r["source_id"]), []).append((self._gsym(r), -self._norm(r)))
            if r["leg_kind"] in ("acq", "disp") and r["event"] == "SWAP":
                key = (r["source_ns"], r["source_id"])
                gid_r = r["group_id"] or -r["asset_id"]
                st_r = (r["gname"] or "") in STABLE_GROUPS
                prev = tx_group.get(key)
                pl_r = st_r or r["posting_id"] in pay_pid
                if prev is None or (prev[1] and not pl_r):
                    tx_group[key] = (gid_r, pl_r)
                sg9 = swap_gas.setdefault(key, {"usd": Decimal(0), "sell": None, "buy": None, "done": False})
                if not st_r and r["kind"] != "exchange_currency":
                    if r["leg_kind"] == "disp" and sg9["sell"] is None and r["posting_id"] not in pay_pid:
                        sg9["sell"] = gid_r
                    elif r["leg_kind"] == "acq" and sg9["buy"] is None:
                        sg9["buy"] = gid_r
                if r["leg_kind"] == "acq":
                    swap_recv.setdefault(key, []).append((gid_r, r["kind"], r["chain"], r["address"], st_r))
            if r["leg_kind"] == "gas" and r["event"] == "SWAP" and r["cost_usd"] is not None:
                sg9 = swap_gas.setdefault((r["source_ns"], r["source_id"]), {"usd": Decimal(0), "sell": None, "buy": None, "done": False})
                sg9["usd"] += Decimal(r["cost_usd"])
        arr_groups = {}
        arr_tx_chain = {}
        for r in rows:
            if r["leg_kind"] == "acq" and r["event"] in ("TRANSFER_IN", "PROGRAM_IN"):
                arr_groups.setdefault((r["source_ns"], r["source_id"]), set()).add(r["group_id"] or -r["asset_id"])
                arr_tx_chain.setdefault(r["source_id"], r["chain"] or r["source_ns"])

        lp_mgrs = lpdec.lp_managers(common.BASE_DIR)
        lp_by_tx = {}
        for r9 in conn.execute("SELECT chain, txhash, detail FROM tx_class WHERE event LIKE 'LP\\_%' ESCAPE '\\'").fetchall():
            try:
                d9 = (json.loads(r9["detail"] or "{}") or {}).get("lp") or {}
            except (json.JSONDecodeError, TypeError, AttributeError):
                d9 = {}
            if d9:
                lp_by_tx[(r9["chain"], r9["txhash"])] = d9
        lp_meta_by = {}
        for (ch9, _h9), d9 in lp_by_tx.items():
            if d9.get("mgr"):
                m9 = lp_meta_by.setdefault((ch9, str(d9["mgr"])), {"proto": d9.get("proto"), "name": d9.get("name")})
                if d9.get("lpSym") and not m9.get("lpSym"):
                    m9["lpSym"] = d9["lpSym"]
                for t9, g9 in (d9.get("stake") or {}).items():
                    m9.setdefault("stake", {})[str(t9)] = g9
                    if d9.get("who"):
                        m9.setdefault("who", {})[str(t9)] = d9["who"]
                for t9, mm9 in (d9.get("mints") or {}).items():
                    m9.setdefault("mints", {})[str(t9)] = mm9
                for t9 in (d9.get("unstake") or {}):
                    (m9.get("stake") or {}).pop(str(t9), None)
        lp_tx_rows = {}
        for r0 in rows:
            if str(r0["event"] or "").startswith("LP_") and r0["leg_kind"] in ("disp", "acq"):
                lp_tx_rows.setdefault((r0["source_ns"], r0["source_id"]), []).append(r0)
        lp_done = set()
        lpb = {}
        lp_events = []
        lp_dep_seen = set()

        def lp_bucket(loc9, chain9, ts9):
            b9 = lpb.get(loc9)
            if b9 is None:
                parts9 = loc9.split(":")
                mgr9 = parts9[2] if len(parts9) > 2 else ""
                meta9 = (lp_mgrs.get(chain9) or {}).get(mgr9) or lp_meta_by.get((chain9, mgr9)) or {}
                b9 = lpb[loc9] = {"loc": loc9, "chain": chain9, "mgr": mgr9, "id": parts9[3] if len(parts9) > 3 else "?",
                                  "proto": meta9.get("proto"), "name": meta9.get("name") or "LP",
                                  "units": {}, "ucost": {}, "gids": {}, "deposited": Decimal(0),
                                  "opened": ts9, "last": ts9, "realized": Decimal(0), "income": Decimal(0),
                                  "returned": {}, "converted": {}, "acq": {}, "rbd": {}, "rbdk": {}}
            b9["last"] = max(b9["last"], ts9)
            return b9

        def lp_label(b9):
            t9 = lpdec.lp_tid(b9["id"])
            if isinstance(t9, int):
                return f"{b9['name']} #{b9['id']}"
            if t9 is not None:
                return f"{b9['name']} #{lpsol.short(str(t9)) if not str(t9).startswith('0x') else str(t9)[:6] + '…' + str(t9)[-4:]}"
            return f"{b9['name']} (포지션 번호 미상)"

        def lp_event(b9, ts9, k9, d9, q9, a9, tx9):
            lp_events.append({"t": datetime.fromtimestamp(ts9, KST).strftime("%m-%d %H:%M"), "_ts": int(ts9), "lp": b9["loc"],
                              "sym": b9.get("pool") or lp_label(b9), "k": k9, "d": d9, "q": q9, "a": a9,
                              "tx": (tx9[:6] + "…" + tx9[-4:]) if tx9 else "—", "src": cur_src[0]})
            ak9 = _ak(a9, ts9)
            if ak9 is not None:
                lp_events[-1]["aK"] = ak9

        def lp_move(r9, g9, q9, ts9, lk9, chain9, txh9):
            loc9 = r9["location"] or ""
            if not loc9.startswith("lp:"):
                return
            b9 = lp_bucket(loc9, chain9, ts9)
            sym9 = g9["sym"]
            b9["gids"][sym9] = g9["gid"]
            qs9 = f"{abs(q9):,.4f}".rstrip("0").rstrip(".")
            if lk9 == "move_in":
                wac9 = (g9["cost"] / g9["qty_known"]) if g9["qty_known"] > EPS else (Decimal(1) if g9["is_stable"] else Decimal(0))
                b9["units"][sym9] = b9["units"].get(sym9, Decimal(0)) + q9
                b9["ucost"][sym9] = b9["ucost"].get(sym9, Decimal(0)) + wac9 * q9
                b9["deposited"] += wac9 * q9
                lp_dep_seen.add(loc9)
                lp_event(b9, ts9, "유동성 예치", f"{CHAIN_NAME.get(chain9, chain9)} · {lp_label(b9)}", f"{qs9} {sym9}",
                         f"${float(wac9 * q9):,.2f}", txh9)
            else:
                qa = -q9
                u0 = b9["units"].get(sym9, Decimal(0))
                c_back = (b9["ucost"].get(sym9, Decimal(0)) * min(qa, u0) / u0) if u0 > EPS else Decimal(0)
                b9["units"][sym9] = max(Decimal(0), u0 - qa)
                b9["ucost"][sym9] = max(Decimal(0), b9["ucost"].get(sym9, Decimal(0)) - c_back)
                b9["returned"][sym9] = b9["returned"].get(sym9, Decimal(0)) + qa
                lp_event(b9, ts9, "유동성 회수", f"{CHAIN_NAME.get(chain9, chain9)} · {lp_label(b9)} · 원금 복귀", f"{qs9} {sym9}",
                         f"${float(c_back):,.2f}", txh9)

        def lp_tx(r9):
            chain9, txh9, ts9 = r9["chain"] or "?", r9["source_id"], r9["event_ts"]
            dkey9 = acct_norm.iso_day(ts9)
            legs9 = lp_tx_rows.get((r9["source_ns"], txh9)) or [r9]
            lpi9 = lp_by_tx.get((r9["source_ns"], txh9)) or {}
            pre9 = f"lp:{chain9}:{lpi9.get('mgr') or ''}"
            cand_locs = [f"{pre9}:{t}" for t in (lpdec.lp_tid(i) for i in (lpi9.get("wd_ids") or [])) if t is not None] \
                + [x for x in (lpi9.get("unk_loc"), lpi9.get("dep_loc"), lpi9.get("loc")) if x]
            disp9 = [x for x in legs9 if x["leg_kind"] == "disp"]
            acq9 = [x for x in legs9 if x["leg_kind"] == "acq"]
            home = next((x["location"] for x in disp9 if (x["location"] or "").startswith("lp:")), None) \
                or next((l for l in cand_locs if l in lpb), None) or (cand_locs[0] if cand_locs else f"{pre9}:?")
            b9 = lp_bucket(home, chain9, ts9)
            rent9 = {int(a) for a in (lpi9.get("rent_aids") or []) if str(a).lstrip("-").isdigit()}

            def lp_small(x):
                if int(x["asset_id"]) in rent9:
                    return True
                if x["cost_usd"] is not None:
                    return abs(Decimal(x["cost_usd"])) < LP_CONV_MIN_USD
                gx = gstate(x)
                wac = (gx["cost"] / gx["qty_known"]) if gx["qty_known"] > EPS else None
                return wac is not None and wac * (-self._norm(x)) < LP_CONV_MIN_USD
            conv9 = [x for x in disp9 if not lp_small(x)]
            rent_only = bool(disp9) and not conv9
            B = Decimal(0); w_all = Decimal(0); w_known = Decimal(0); conv_txt = []
            dinfo = []
            for x in disp9:
                gx = gstate(x)
                qx = -self._norm(x)
                if qx <= 0:
                    continue
                fk = min(qx, gx["qty_known"]); fu = qx - fk
                wac = (gx["cost"] / gx["qty_known"]) if gx["qty_known"] > EPS else Decimal(0)
                bk = wac * fk
                krw9 = consume_krw(gx, bk)
                cp9x = cp_take(gx, fk, bk)
                gx["qty_known"] -= fk; gx["cost"] -= bk
                gx["qty_unknown"] = max(Decimal(0), gx["qty_unknown"] - fu)
                gx["qty_timeline"].append((ts9, -qx))
                mv = Decimal(x["cost_usd"]) if x["cost_usd"] is not None else None
                wt = mv if (mv is not None and mv > 0) else (bk if bk > 0 else qx)
                B += bk; w_all += wt; w_known += wt * (fk / qx)
                bx = lp_bucket(x["location"], chain9, ts9) if (x["location"] or "").startswith("lp:") else b9
                u0 = bx["units"].get(gx["sym"], Decimal(0))
                c_cv = (bx["ucost"].get(gx["sym"], Decimal(0)) * min(qx, u0) / u0) if u0 > EPS else Decimal(0)
                bx["units"][gx["sym"]] = max(Decimal(0), u0 - qx)
                bx["ucost"][gx["sym"]] = max(Decimal(0), bx["ucost"].get(gx["sym"], Decimal(0)) - c_cv)
                if rent_only:
                    if gx["qty_known"] + gx["qty_unknown"] <= Decimal("0.000001"):
                        gx["cur"] = None
                    continue
                bx["converted"][gx["sym"]] = bx["converted"].get(gx["sym"], Decimal(0)) + qx
                conv_txt.append(f"{float(qx):,.4f}".rstrip("0").rstrip(".") + f" {gx['sym']}")
                dinfo.append({"g": gx, "qx": qx, "fk": fk, "bk": bk, "wk": wt * (fk / qx), "krw": krw9, "bx": bx, "_cp": cp9x,
                              "fl": None if gx["is_stable"] else (gx["cur"] or flow_of(gx, ts9, chain9))})
            k9 = (w_known / w_all) if w_all > 0 else Decimal(1)
            B_rent = Decimal(0)
            if rent_only:
                B_rent, B = B, Decimal(0)
                disp9 = []
            priced = [(x, Decimal(x["cost_usd"])) for x in acq9 if x["cost_usd"] is not None]
            unpriced = [x for x in acq9 if x["cost_usd"] is None]
            M = sum((m for _x, m in priced), Decimal(0))
            no_dep = (not disp9) and not any(l in lp_dep_seen for l in cand_locs)
            cost_of = {}
            realized9 = Decimal(0)
            income9 = Decimal(0)
            if disp9:
                kB = B
                if priced and M > 0 and (not unpriced or M >= kB):
                    for x, m in priced:
                        cost_of[x["posting_id"]] = kB * m / M
                    for x in unpriced:
                        cost_of[x["posting_id"]] = Decimal(0)
                elif priced:
                    for x, m in priced:
                        cost_of[x["posting_id"]] = m
                    for x in unpriced:
                        cost_of[x["posting_id"]] = (kB - M) / len(unpriced)
                elif acq9:
                    for x in acq9:
                        cost_of[x["posting_id"]] = kB / len(acq9)
                realized9 = Decimal(0)
            elif not no_dep:
                for x, m in priced:
                    if int(x["asset_id"]) in rent9:
                        cost_of[x["posting_id"]] = Decimal(0)
                        continue
                    cost_of[x["posting_id"]] = m
                    income9 += m
                for x in unpriced:
                    cost_of[x["posting_id"]] = Decimal(0)
            sale9 = {}
            if disp9 and dinfo and B > 0 and k9 > 0:
                st_acq = [x for x in acq9 if gstate(x)["is_stable"] and self._norm(x) > 0 and x["posting_id"] in cost_of]
                ns_ix = [i for i, d in enumerate(dinfo) if d["fl"] is not None and d["fk"] > 0]
                wk_all = sum((d["wk"] for d in dinfo), Decimal(0))
                wk_ns = sum((dinfo[i]["wk"] for i in ns_ix), Decimal(0))
                c_st = sum((cost_of[x["posting_id"]] for x in st_acq), Decimal(0))
                if st_acq and ns_ix and wk_all > 0 and wk_ns > 0 and c_st > 0:
                    ns9 = wk_ns / wk_all
                    fs9 = min(Decimal(1), c_st / B)
                    C_R = fs9 * sum((dinfo[i]["bk"] for i in ns_ix), Decimal(0))
                    faces = {x["posting_id"]: (Decimal(x["cost_usd"]) if x["cost_usd"] is not None else self._norm(x)) * k9 for x in st_acq}
                    P_R = ns9 * sum(faces.values(), Decimal(0))
                    for x in st_acq:
                        c = cost_of[x["posting_id"]]
                        cost_of[x["posting_id"]] = c - C_R * c / c_st + ns9 * faces[x["posting_id"]]
                    for i in ns_ix:
                        d = dinfo[i]
                        sale9[i] = (d["fk"] * fs9, d["bk"] * fs9, P_R * d["wk"] / wk_ns, (d["krw"] * fs9) if d["krw"] is not None else None)
            st_real9 = Decimal(0)
            for i, d in enumerate(dinfo):
                gx, fl9, qx, bk = d["g"], d["fl"], d["qx"], d["bk"]
                if fl9 is None:
                    continue
                qi, ci, pi, ki = sale9.get(i, (Decimal(0), Decimal(0), Decimal(0), None))
                if qi > 0:
                    pnl9 = pi - ci
                    st_real9 += pnl9
                    rate9, rsrc9 = fxb.rate_src(ts9)
                    gx["realized"] += pnl9
                    fl9["realized"] += pnl9
                    fl9["rbd"][dkey9] = fl9["rbd"].get(dkey9, Decimal(0)) + pnl9
                    fl9["rbdk"][dkey9] = fl9["rbdk"].get(dkey9, 0.0) + float(pnl9) * rate9
                    fl9.setdefault("rch", {}).setdefault(dkey9, set()).add(cur_lab[0] or "?")
                    realized_by_date[dkey9] = realized_by_date.get(dkey9, 0) + float(pnl9)
                    realized_krw_by_date[dkey9] = realized_krw_by_date.get(dkey9, 0) + float(pnl9) * rate9
                    tax9 = {"sold": dkey9, "sym": gx["sym"], "ticker": gx["sym"], "ex": "유동성(DEX LP) · 스테이블 전환",
                            "qty": _f(qi, 4), "acq": _f(ci, 2), "disp": _f(pi, 2), "fee": 0, "rate": round(rate9, 4), "rateSrc": rsrc9,
                            "_acq": float(ci), "_disp": float(pi)}
                    tax_krw_acq(tax9, gx, fl9, ci, ki, rate9, dkey9)
                    tax_rows.append(tax9)
                    fl9["sold"] += qi
                    fl9["sold_dates"].append(dkey9)
                    fl9["proceeds"] = fl9.get("proceeds", Decimal(0)) + pi
                    fl9["proceeds_krw"] = fl9.get("proceeds_krw", Decimal(0)) + krw_of(pi, ts9)
                    ev(fl9, ts9, "LP 전환 매도", f"{lp_label(d['bx'])} · 풀 안에서 스테이블로 전환된 원금(= 매도 · 실현 "
                       + f"{'+' if pnl9 >= 0 else '−'}${abs(float(pnl9)):,.2f})",
                       f"{float(qi):,.4f}".rstrip("0").rstrip("."), f"${float(pi):,.2f}", txh9, un=_un(qi, pi))
                    fl9["events"][-1]["_tax"] = tax9
                    if d.get("_cp") and d["fk"] > 0:
                        fs9x = float(qi / d["fk"])
                        cmx = {k9: [v9[0] * fs9x, v9[1] * fs9x] for k9, v9 in d["_cp"].items()}
                        tcx = sum(v9[1] for v9 in cmx.values())
                        for v9 in cmx.values():
                            v9[1] = v9[1] * float(ci) / tcx if tcx > 0 else 0.0
                        fl9["events"][-1]["_cmp"] = cp_emit(cmx, 0, qi, ci)
                qr = qx - qi
                if qr > Decimal("0.000001") or qi <= 0:
                    fl9["lpconv"] = fl9.get("lpconv", Decimal(0)) + qr
                    ev(fl9, ts9, "LP 전환", f"{lp_label(d['bx'])} · 풀 안에서 다른 자산으로 전환된 원금",
                       f"{float(qr):,.4f}".rstrip("0").rstrip("."), f"${float(bk - ci):,.2f}", txh9, un=_un(qr, bk - ci))
                if gx["qty_known"] + gx["qty_unknown"] <= Decimal("0.000001"):
                    gx["cur"] = None
            realized9 -= B_rent
            for x in acq9:
                gx = gstate(x)
                qx = self._norm(x)
                if qx <= 0:
                    continue
                cp_sync(gx)
                gx["qty_timeline"].append((ts9, qx))
                gx["risk_allow"] = True
                flow = flow_of(gx, ts9, chain9)
                qsx = f"{float(qx):,.4f}".rstrip("0").rstrip(".")
                b9["acq"][gx["sym"]] = b9["acq"].get(gx["sym"], Decimal(0)) + qx
                if no_dep:
                    if gx["is_stable"]:
                        gx["qty_known"] += qx; gx["cost"] += qx
                    else:
                        gx["qty_unknown"] += qx
                        note_unk(gx, ts9, f"LP 회수 · 예치 기록 없음(수집 창 이전 예치) · {lp_label(b9)}", qx, txh9, chain9=chain9)
                    flow["bought"] += qx
                    ev(flow, ts9, "LP 회수", f"{lp_label(b9)} · 예치 기록 없음(원가 미상)", qsx, "—", txh9)
                    lp_event(b9, ts9, "유동성 회수", f"{CHAIN_NAME.get(chain9, chain9)} · {lp_label(b9)} · 예치 기록 없음",
                             f"{qsx} {gx['sym']}", "—", txh9)
                    continue
                c = cost_of.get(x["posting_id"], Decimal(0))
                kq = qx * k9 if disp9 else qx
                uq = qx - kq
                gx["qty_known"] += kq; gx["cost"] += c
                if uq > EPS:
                    gx["qty_unknown"] += uq
                    note_unk(gx, ts9, f"LP 전환 취득 · 원가미상 원금분 · {lp_label(b9)}", uq, txh9, chain9=chain9)
                flow["bought"] += qx; flow["cost"] += c
                flow["cost_krw"] += krw_of(c, ts9, x)
                rw9 = bool(lpi9.get("via")) and not disp9
                rn9 = (not disp9) and int(x["asset_id"]) in rent9
                how = ("스테이블 수령 · 액면 원가(스테이블로 바뀐 전환 원금 = 매도 실현)" if (disp9 and sale9 and gx["is_stable"]) else
                       "풀 전환가 · 전환 원금 원가 승계" if disp9 else
                       "계정 임대료 환급(수익 아님 · 원가 0)" if rn9 else
                       (("스테이킹 리워드(시가)" if rw9 else "수수료 수익(시가)") if x["cost_usd"] is not None
                        else ("스테이킹 리워드(시세 없음 · 원가 0)" if rw9 else "수수료(시세 없음 · 원가 0)")))
                kname = "LP 전환 매수" if disp9 else ("LP 임대료 환급" if rn9 else ("LP 리워드 수령" if rw9 else "LP 수수료 수령"))
                unit9 = f" · 개당 ${float(c / qx):,.6g}" if qx > 0 and c > 0 else ""
                ev(flow, ts9, kname, f"{lp_label(b9)} · {how}{unit9}", qsx, f"${float(c):,.2f}", txh9, un=_un(qx, c))
                lp_event(b9, ts9, kname, f"{CHAIN_NAME.get(chain9, chain9)} · {lp_label(b9)} · {how}",
                         f"{qsx} {gx['sym']}", f"${float(c):,.2f}", txh9)
            gain9 = realized9 + income9
            if abs(gain9) >= Decimal("0.005"):
                realized_by_date[dkey9] = realized_by_date.get(dkey9, 0) + float(gain9)
                b9["rbd"][dkey9] = b9["rbd"].get(dkey9, Decimal(0)) + gain9
                rt9x, rsrc9x = fxb.rate_src(ts9)
                realized_krw_by_date[dkey9] = realized_krw_by_date.get(dkey9, 0) + float(gain9) * rt9x
                b9["rbdk"][dkey9] = b9["rbdk"].get(dkey9, 0.0) + float(gain9) * rt9x
                b9["realized"] += realized9
                b9["income"] += income9
                tax_rows.append({"sold": dkey9, "sym": b9.get("pool") or lp_label(b9), "ticker": "LP",
                                 "ex": "유동성(DEX LP)" if disp9 else ("유동성 리워드" if lpi9.get("via") else "유동성 수수료"),
                                 "qty": _f(float(sum((-self._norm(x) for x in disp9), Decimal(0))), 4) if disp9 else 0,
                                 "acq": _f(float(B), 2) if disp9 else _f(float(B_rent), 2),
                                 "disp": _f(float(k9 * M if disp9 else income9), 2), "fee": 0, "rate": round(rt9x, 4), "rateSrc": rsrc9x,
                                 "_acq": float(B) if disp9 else float(B_rent), "_disp": float(k9 * M if disp9 else income9)})
            if disp9 and B >= Decimal("0.005"):
                lp_event(b9, ts9, "LP 전환", f"{CHAIN_NAME.get(chain9, chain9)} · {lp_label(b9)} · 원금 전환 "
                         + " + ".join(conv_txt) + (f" · 손익 {'+' if realized9 >= 0 else ''}${float(realized9):,.2f}" if abs(realized9) > EPS else "")
                         + (f" · 스테이블 전환 실현 {'+' if st_real9 >= 0 else '−'}${abs(float(st_real9)):,.2f}(코인 카드)" if sale9 else ""),
                         "—", f"${float(B):,.2f}", txh9)

        ob = {}
        up_dep_by_tx = {t9: u9 for u9, t9 in up_dep_uid_tx.items()}
        up_win_t0 = min((r0["event_ts"] for r0 in rows if r0["event"] == "EX_DEPOSIT"
                         and str(r0["source_ns"] or "").startswith("upbit")), default=None)
        ever_in = {r0["group_id"] or -r0["asset_id"] for r0 in rows
                   if int(r0["qty_base"]) > 0 and r0["event"] != "TRANSFER_OUT"
                   and str(r0["location"] or "").startswith(("wallet:", "exchange:"))}
        of_noauto = {a for a, v in self.outflow_decisions().items() if isinstance(v, dict) and v.get("noAuto")}
        of_dec9 = self.outflow_decisions()
        rt_pair = {}
        rt_transit = {}
        _ro, _ri = {}, {}
        for r0 in rows:
            loc0 = r0["location"] or ""
            if r0["event"] == "TRANSFER_OUT" and r0["leg_kind"] == "move_out" and loc0.startswith("wallet:"):
                o0 = _ro.setdefault((r0["source_ns"], r0["source_id"]), {"ts": int(r0["event_ts"]), "loc": set(), "a": {}})
                o0["loc"].add(loc0); o0["a"][r0["asset_id"]] = o0["a"].get(r0["asset_id"], Decimal(0)) - self._norm(r0)
            elif r0["event"] == "PROGRAM_IN" and r0["leg_kind"] == "acq":
                i0 = _ri.setdefault((r0["source_ns"], r0["source_id"]), {"ts": int(r0["event_ts"]), "loc": set(), "a": {}, "priced": False})
                i0["loc"].add(loc0); i0["a"][r0["asset_id"]] = i0["a"].get(r0["asset_id"], Decimal(0)) + self._norm(r0)
                i0["priced"] = i0["priced"] or r0["cost_usd"] is not None
        _rc_o, _rc_i = {}, {}
        _ri_l = sorted(_ri.items(), key=lambda kv: kv[1]["ts"])
        _ri_ts = [kv[1]["ts"] for kv in _ri_l]
        for ko, o0 in _ro.items():
            if len(o0["loc"]) != 1:
                continue
            for j0 in range(bisect.bisect_left(_ri_ts, o0["ts"]), bisect.bisect_right(_ri_ts, o0["ts"] + 6 * 3600)):
                ki, i0 = _ri_l[j0]
                if ki[0] != ko[0]:
                    continue
                if i0["priced"] or i0["loc"] != o0["loc"] or not i0["a"] or set(i0["a"]) - set(o0["a"]):
                    continue
                if all(o0["a"][a0] > 0 and o0["a"][a0] * Decimal("0.995") <= q0 <= o0["a"][a0] * Decimal("1.005") for a0, q0 in i0["a"].items()):
                    _rc_o.setdefault(ko, []).append(ki); _rc_i.setdefault(ki, []).append(ko)
        rt_back = {}
        for ko, kis in _rc_o.items():
            if len(kis) == 1 and len(_rc_i.get(kis[0], ())) == 1:
                rt_pair[kis[0]] = ko
                rt_back[ko] = (set(_ri[kis[0]]["a"]), set(_ri[kis[0]]["a"]) == set(_ro[ko]["a"]))
        rt_out = set(rt_pair.values())
        self._ph("outflow_dest·match")
        rt_same = self._rt_same_dest(conn, rt_pair)
        of_sends, of_arr, of_comp = [], [], []
        for r0 in rows:
            loc0 = r0["location"] or ""
            if loc0.startswith("out:") and r0["leg_kind"] == "move_in":
                gid0, gn0, sym0 = r0["group_id"] or -r0["asset_id"], r0["gname"] or "", self._gsym(r0)
                of_sends.append({"pid": r0["posting_id"], "txn": outflow_match.norm_txid(r0["source_id"]), "txh": r0["source_id"],
                                 "chain": r0["source_ns"], "dest": loc0.split(":", 2)[2] if loc0.count(":") >= 2 else "?",
                                 "sym": sym0, "qty": self._norm(r0), "ts": int(r0["event_ts"]),
                                 "ok": gid0 in ever_in and not (sym0.upper() in STABLE_GROUPS and gn0 not in STABLE_GROUPS),
                                 "stable": gn0 in STABLE_GROUPS,
                                 "ca": str(r0["address"] or "").lower()})
            elif loc0.startswith("wallet:") and r0["leg_kind"] == "acq" and \
                    r0["event"] in ("TRANSFER_IN", "PROGRAM_IN") and int(r0["qty_base"]) > 0:
                t0 = r0["source_id"] or ""
                if t0 in fx_wd or t0.lower() in fx_wd or t0 in ub_wd_tx or t0.lower() in ub_wd_tx:
                    continue
                of_arr.append({"key": r0["posting_id"], "chain": r0["source_ns"], "ts": int(r0["event_ts"]),
                               "sym": self._gsym(r0), "qty": self._norm(r0), "tx": t0, "gid": r0["group_id"] or -r0["asset_id"],
                               "gname": r0["gname"] or "", "native": r0["address"] in (None, "", "native"),
                               "stable": (r0["gname"] or "") in STABLE_GROUPS,
                               "ca": f"{r0['source_ns']}:{(r0['address'] or '').lower()}",
                               "wallet": loc0.split(":", 2)[2] if loc0.count(":") >= 2 else ""})
            elif r0["event"] == "BRIDGE" and r0["leg_kind"] == "move_out" and loc0.startswith("wallet:"):
                of_comp.append({"pid": r0["posting_id"], "chain": r0["source_ns"], "dest": "", "sym": self._gsym(r0),
                                "qty": -self._norm(r0), "ts": int(r0["event_ts"]), "ok": True,
                                "txn": outflow_match.norm_txid(r0["source_id"])})
        for s0 in of_sends:
            if not flow_trace.is_burn(s0["dest"]) or s0["chain"] == "sol":
                continue
            try:
                x0 = conn.execute("SELECT json_extract(snapshot, '$.tx.raw_input'), COALESCE(json_extract(snapshot, '$.tx.to.hash'),"
                                  " json_extract(snapshot, '$.tx.to')), json_extract(snapshot, '$.tx.fee.value') FROM raw_txs"
                                  " WHERE chain=? AND txhash=? AND json_valid(snapshot)", (s0["chain"], s0["txh"])).fetchone()
            except Exception:
                x0 = None
            if x0 and str(x0[0] or "")[:10].lower() == outflow_match.OFT_SEND_SEL and not spamguard.snapshot_synth(x0[2], x0[0]) \
                    and str(x0[1] or "").lower() not in ("", s0.get("ca") or ""):
                s0["oft"] = True
        of_deps = []
        for rf in conn.execute("SELECT exchange, uuid, payload FROM raw_ex WHERE kind='deposit'"
                               " GROUP BY exchange, uuid HAVING revision = MAX(revision)").fetchall():
            if rf["exchange"] in offc_on and (rf["exchange"], rf["uuid"]) in offc_dep:
                continue
            try:
                pw = json.loads(rf["payload"])
                if str(pw.get("state") or "").upper() != "ACCEPTED":
                    continue
                ts0 = None
                for k0 in ("created_at", "done_at"):
                    if pw.get(k0):
                        ts0 = int(datetime.fromisoformat(str(pw[k0]).replace("Z", "+00:00")).timestamp())
                        break
                amt0 = Decimal(str(pw.get("amount") or 0))
            except (ValueError, TypeError, InvalidOperation):
                continue
            t0 = str(pw.get("txid") or "")
            oc0 = origin_cache.get(t0) or origin_cache.get(t0.lower()) or {}
            of0 = oc0.get("from") if isinstance(oc0, dict) else None
            of0 = (of0.lower() if str(of0).startswith("0x") else of0) if of0 else None
            of_deps.append({"ex": rf["exchange"], "uuid": rf["uuid"], "cur": pw.get("currency") or "", "amt": amt0, "ts": ts0,
                            "txn": outflow_match.norm_txid(t0), "origin_from": of0,
                            "origin_mine": bool(of0) and of0.lower() in wallet_label})
        self._of_deps_origin = {}
        for d0 in of_deps:
            if d0.get("origin_from") and not d0.get("origin_mine"):
                self._of_deps_origin.setdefault(d0["origin_from"], []).append(d0)
        dep_txn9 = {d0["txn"] for d0 in of_deps if d0.get("txn")}
        of_comp_n0 = len(of_comp)
        of_comp = [c0 for c0 in of_comp if c0.get("txn") not in dep_txn9]
        self._of_comp_exdep_drop = of_comp_n0 - len(of_comp)
        of_mine = {outflow_match.norm_txid(r0["txhash"]) for r0 in conn.execute("SELECT txhash FROM raw_txs").fetchall()}
        of_chain = frozenset(of_mine)
        for rf in conn.execute("SELECT payload FROM raw_ex WHERE kind='withdraw'").fetchall():
            try:
                tw9 = outflow_match.norm_txid(json.loads(rf["payload"]).get("txid"))
            except (ValueError, TypeError, AttributeError):
                continue
            if tw9:
                of_mine.add(tw9)
        self._depx_idx = self._deposit_exchange_index()
        of_match, of_sugg, of_proven = outflow_match.match(of_sends, of_deps, of_mine, self._deposit_exchange, of_noauto)
        priced_gid = {r0["group_id"] or -r0["asset_id"] for r0 in rows
                      if r0["cost_usd"] is not None or (r0["event"] == "TRANSFER_OUT_EX" and r0["leg_kind"] == "move_out")}
        priced_gid |= {r0["group_id"] or -r0["asset_id"] for r0 in conn.execute(
            "SELECT asset_id, group_id FROM assets WHERE confirmed=1").fetchall()}
        try:
            gp9 = common.read_json(GOPLUS_PATH, {}) if os.path.exists(GOPLUS_PATH) else {}
        except BaseException:
            gp9 = {}
        for a0 in of_arr:
            strong9 = bool(((gp9.get(a0["ca"]) or {}).get("risk") or {}).get("strong")) if isinstance(gp9, dict) else False
            stable_name9 = outflow_match.canon_sym(a0["sym"]) in STABLE_GROUPS
            a0["ok"] = not strong9 and (a0["gname"] in STABLE_GROUPS if stable_name9 else (a0["native"] or a0["gid"] in priced_gid))
        of_bridge, of_bridge_amb = outflow_match.bridge_match(of_sends, of_arr, of_comp, skip=set(of_match), no_auto=of_noauto)
        xc_links, xc_barr = xchain_match.links_for(xc_cache), xchain_match.bridge_arrivals(xc_cache)
        if xc_links or xc_barr:
            used9 = {a9["key"]: p9 for p9, a9 in of_bridge.items()}
            sends9 = [s9 for s9 in of_sends if s9["dest"] not in of_noauto]
            for p9, (a9, bs9) in xchain_match.match_pairs(sends9, of_arr, xc_links, xc_barr, outflow_match.family,
                                                           frozenset(outflow_match.STABLES), skip=set(of_match)).items():
                if bs9 == "window" and (p9 in of_bridge or a9["key"] in used9):
                    continue
                if bs9 == "id" and used9.get(a9["key"]) not in (None, p9):
                    of_bridge.pop(used9[a9["key"]], None)
                of_bridge[p9] = a9
                used9[a9["key"]] = p9
                of_bridge_amb.pop(p9, None)
                diag["xc_link_n"] += 1
        br_transit = {}

        def _of_uids(m0):
            return [m0["uuid"]] if m0.get("uuid") else list(m0.get("uuids") or [])
        for s0 in of_sends:
            m0 = of_match.get(s0["pid"])
            if not m0:
                continue
            for u0 in _of_uids(m0):
                if m0["ex"] == "upbit":
                    uuid2txh.setdefault(u0, s0["txh"])
                else:
                    fx_dep_uid_tx[u0] = s0["txn"]
        self._of_auto = {"sugg": of_sugg, "proven": of_proven, "bridge": of_bridge, "bridge_amb": of_bridge_amb,
                         "sends": {s0["pid"]: s0 for s0 in of_sends}}
        self._ph("rt_same")
        xf_links = self._xfer_links(conn, of_chain, set(uuid2txh) | {u0 for m0 in of_match.values() for u0 in _of_uids(m0)}, prefs,
                                    origin_cache, origin_pending)
        for xl9 in xf_links.values():
            if xl9["key"].startswith("amt:"):
                fx_uid_tx[xl9["wd_uuid"]] = xl9["key"]
        xf_wd9 = {xl9["wd_uuid"] for xl9 in xf_links.values()}
        def _sale_px(sym9, ts9):
            try:
                return float(self.px.candle_usd(sym9, int(ts9) * 1000) or 0) or None
            except Exception:
                return None
        sale_lots = []
        sale_links = {}
        own_dep9 = set()
        try:
            of_man = self._of_manual_resolve(rows)
        except Exception as e:
            log.warning("보낸 내역 수동 연결 풀이 실패(이번 빌드 미적용): %s", e)
            of_man = {"dests": {}, "pids": set(), "dup": set(), "claims": {}}
            self._of_claims = {}
        try:
            sale_lots = sale_match.build_lots(common.read_json(SALE_PATH, {}) or {}, _sale_px, prefs.get("sale_link_off") or ())
            my9 = {str(w9.get("address") or "").lower() for w9 in self._hist_wallets() if isinstance(w9, dict)}
            sale_in, sale_need = sale_match.collect_inflows(conn, sale_lots, origin_cache, my9)
            own_dep9 = set(uuid2txh) | set(xf_links) | {u0 for m0 in of_match.values() for u0 in _of_uids(m0)}
            sale_in = [x9 for x9 in sale_in
                       if not (x9["kind"] == "ex" and x9.get("src") in own_dep9)
                       and not (x9["kind"] == "chain" and (x9["chain"], x9["ref"]) in rt_pair)
                       and x9["pid"] not in of_man["pids"]]
            sale_links = sale_match.match(sale_lots, sale_in)
            origin_pending |= {t9 for t9 in sale_need if not oc_fresh(t9)}
        except Exception as e:
            log.warning("토큰 세일 연결 계산 실패(이번 빌드 미적용): %s", e)
            sale_lots, sale_links = [], {}
        sale_lot_by = {l9["id"]: l9 for l9 in sale_lots}
        try:
            of_lots9, of_links9 = self._of_manual_lots(conn, of_man, krw_of, own_dep9, rt_pair)
        except Exception as e:
            log.warning("보낸 내역 수동 연결 원가 계산 실패(이번 빌드 미적용): %s", e)
            of_lots9, of_links9 = {}, {}
            self._of_man_state = {}
        sale_lot_by.update(of_lots9)
        sale_links.update(of_links9)
        redeem_tx = {}
        try:
            rpairs9 = sale_match.redeem_pairs(sale_lots)
            if rpairs9:
                sw9 = {}
                for r0 in rows:
                    if r0["event"] == "SWAP" and r0["leg_kind"] in ("acq", "disp"):
                        sw9.setdefault((r0["source_ns"], r0["source_id"]), []).append(r0)
                for k0, legs0 in sw9.items():
                    d0 = [x0 for x0 in legs0 if x0["leg_kind"] == "disp"]
                    a0 = [x0 for x0 in legs0 if x0["leg_kind"] == "acq"]
                    if len(d0) != 1 or len(a0) != 1 or d0[0]["location"] != a0[0]["location"] or d0[0]["chain"] != a0[0]["chain"]:
                        continue
                    pr0 = rpairs9.get((d0[0]["chain"], str(d0[0]["address"] or "").lower()))
                    if not pr0 or str(a0[0]["address"] or "").lower() != pr0["to"]:
                        continue
                    qd0, qa0 = -self._norm(d0[0]), self._norm(a0[0])
                    exp0 = qd0 * pr0["ratio"]
                    if qd0 <= 0 or qa0 <= 0 or abs(qa0 - exp0) > max(qa0, exp0) * Decimal("0.000001"):
                        continue
                    redeem_tx[k0] = {"disp": d0[0]["posting_id"], "acq": a0[0]["posting_id"], "ratio": pr0["ratio"], "carry": None}
        except Exception as e:
            log.warning("세일 영수증 교환 판정 실패(이번 빌드 미적용): %s", e)
            redeem_tx = {}
        diag["sale_redeem_n"] = len(redeem_tx)
        sale_bid9 = {}
        for l9 in sale_lots:
            if not l9["off"]:
                for t9 in l9["bid_tx"]:
                    sale_bid9[(l9["chain"], str(t9).lower(), l9["auction"])] = l9
        for p9, a9 in list(of_bridge.items()):
            if a9["key"] in sale_links:
                of_bridge.pop(p9, None)
                diag["xc_sale_drop_n"] += 1
        br_arr9 = {a9["key"] for a9 in of_bridge.values()}
        xc_pids9 = set(xc_transit)
        xc_exp9 = set()
        if xc_pids9 or sale_links or br_arr9:
            for r0 in rows:
                pid0 = r0["posting_id"]
                done0 = pid0 in sale_links or pid0 in br_arr9
                if done0:
                    xc_exp9.add((r0["source_ns"], xchain_match.norm(r0["source_id"])))
                if pid0 in xc_pids9 and (done0 or (r0["source_ns"], r0["source_id"]) in rt_pair):
                    xc_transit.pop(pid0, None)
                    diag["xc_hop_drop_n"] += 1
        if xc_exp9 and hasattr(self, "_xc_lock"):
            with self._xc_lock:
                self._xc_pending = [c9 for c9 in self._xc_pending
                                    if c9.get("kind") == "send" or (c9.get("chain"), xchain_match.norm(c9.get("tx"))) not in xc_exp9]
        sale_used = {}
        of_applied = {}
        of_cands = {}

        def of_cand(r9, g9, q9, ts9, ref9, own9=False):
            try:
                if q9 <= 0 or g9.get("is_fiat") or own9:
                    return False
                k9 = self._of_key(r9)
                sl9 = sale_links.get(r9["posting_id"])
                of_cands[k9] = {"key": k9, "pid": r9["posting_id"], "sym": g9["sym"], "qty": float(q9), "ts": int(ts9),
                                "stable": bool(g9["is_stable"]), "where": cur_src[0] or "", "chain": r9["chain"] or "",
                                "ref": str(ref9 or ""), "ev": r9["event"], "gid": g9["gid"],
                                "sale": bool(sl9 and not sl9.get("manual")), "asset": self._of_asset(r9), "qb": str(r9["qty_base"])}
            except Exception:
                pass
            return False

        def of_finalize(lot9):
            if lot9.get("fin") is not None:
                return lot9["fin"]
            by9 = {}
            snd9 = list((ob.get(lot9["manual"]) or {}).get("sends") or ())
            for w0 in wd_tr:
                if w0["ts"] > lot9["t_first"]:
                    continue
                p0 = wd_raw9.get((w0["ex"], w0["uuid"])) or {}
                a0 = xfer_match.norm_addr(str(p0.get("address") or "").strip()) if str(p0.get("address") or "").strip() else ""
                if (a0 or self._wd_key(w0["ex"], w0["uuid"])) != lot9["manual"]:
                    continue
                n0 = str(w0["sym"] or "").upper() in OF_NATIVE_SYMS
                if w0["stable"]:
                    u0 = Decimal(w0["qty"])
                else:
                    try:
                        px0 = float(self.px.candle_usd(str(w0["sym"] or ""), int(w0["ts"]) * 1000) or 0) if n0 else 0.0
                    except Exception:
                        px0 = 0.0
                    u0 = Decimal(w0["qty"]) * Decimal(str(px0)) if px0 > 0 else None
                t0 = str(w0.get("txid") or "")
                sw0 = bool(t0 and (t0 in arr_tx_chain or t0.lower() in arr_tx_chain or t0 in up_dep_by_tx
                                   or t0 in fx_dep_tx)) or w0["uuid"] in xf_wd9
                snd9.append((int(w0["ts"]), w0["gid"], u0, w0.get("held") or Decimal(0), bool(w0["stable"] or n0), None,
                             self._wd_key(w0["ex"], w0["uuid"]), None, None, sw0))
            by_key9 = {x0[6]: x0 for x0 in snd9 if x0[6]}

            def fits9(x0, xe):
                return not isinstance(xe, dict) or (x0[7] == xe.get("asset") and x0[8] == (None if xe.get("qb") is None else str(xe.get("qb"))))
            excl9, miss9 = set(), False
            for xe in lot9.get("excl", ()):
                ke = str(xe.get("key") if isinstance(xe, dict) else xe)
                if ke in by_key9 and fits9(by_key9[ke], xe):
                    excl9.add(ke)
                    continue
                c0 = [x0 for x0 in snd9 if isinstance(xe, dict) and x0[6] and ke.count("|") >= 3 and x0[6].rsplit("|", 1)[0] == ke.rsplit("|", 1)[0]
                      and fits9(x0, xe)]
                if len(c0) == 1:
                    excl9.add(c0[0][6])
                else:
                    miss9 = True
            selfov9 = False
            for ts0, gid0, usd0, held0, ok0, krw0, key0, _as0, _qb0, sw0 in snd9:
                if ts0 > lot9["t_first"] or key0 in excl9:
                    continue
                if sw0:
                    selfov9 = True
                b9 = by9.setdefault(gid0, {"held": Decimal(0), "usd": Decimal(0), "krw": Decimal(0), "known": True, "ok": ok0})
                b9["held"] += held0
                if usd0 is None:
                    b9["known"] = False
                else:
                    b9["usd"] += usd0
                    b9["krw"] += krw0 if krw0 is not None else krw_of(usd0, ts0)
            inc9 = [b9 for b9 in by9.values() if b9["held"] > EPS]
            paid9 = sum((b9["usd"] for b9 in inc9), Decimal(0))
            if miss9:
                fin9 = ("excl_missing", paid9)
            elif selfov9:
                fin9 = ("self_overlap", paid9)
            elif not inc9:
                fin9 = ("no_cost", paid9)
            elif not all(b9["ok"] for b9 in inc9):
                fin9 = ("mixed", paid9)
            elif not all(b9["known"] for b9 in inc9) or paid9 - lot9["refund"] < 0:
                fin9 = ("no_cost", paid9)
            else:
                cost9 = paid9 - lot9["refund"]
                kt9 = max(Decimal(0), sum((b9["krw"] for b9 in inc9), Decimal(0)) - lot9["refund_krw"]) if cost9 > 0 else Decimal(0)
                fin9 = ("ok", paid9, cost9, kt9)
                lot9["desc"] = (f"토큰 세일 매수 · 보낸 내역 참가금 연결 · 참가 ${float(paid9):,.2f}"
                                + (f" · 환불 ${float(lot9['refund']):,.2f}" if lot9["refund"] > 0 else "")
                                + f" · 원가 ${float(cost9):,.2f}" + (f" (수령 {lot9['n']}건에 나눔)" if lot9["n"] > 1 else ""))
            lot9["fin"] = fin9
            return fin9

        def sale_book(g9, r9, q9, ts9, chain9, ref9):
            sl9 = sale_links.get(r9["posting_id"])
            lot9 = sale_lot_by.get(sl9["lot"]) if sl9 else None
            if not lot9 or g9["is_stable"] or q9 <= 0:
                return None
            if sl9.get("manual"):
                fin9 = of_finalize(lot9)
                if fin9[0] != "ok":
                    return None
                sl9["cost"] = fin9[2] * sl9["wsh"]
                sl9["unit"] = sl9["cost"] / sl9["qty"] if sl9["qty"] > 0 else Decimal(0)
                sl9["unit_krw"] = fin9[3] * sl9["wsh"] / sl9["qty"] if sl9["qty"] > 0 else Decimal(0)
            take9 = min(q9, sl9["take"])
            c9 = take9 * sl9["unit"]
            g9["qty_known"] += take9
            g9["cost"] += c9
            g9["qty_unknown"] += q9 - take9
            note_unk(g9, ts9, "토큰 세일 · 로트 잔량 초과분(원가 없음)", q9 - take9, ref9, chain9=chain9)
            g9["risk_allow"] = True
            fl9 = flow_of(g9, ts9, chain9)
            fl9["bought"] += take9
            fl9["cost"] += c9
            fl9["cost_krw"] += take9 * sl9["unit_krw"] if sl9.get("unit_krw") is not None else krw_of(c9, ts9)
            ev(fl9, ts9, "세일 매수", lot9.get("desc") or sale_match.desc(lot9), f"{take9:,.4f}".rstrip("0").rstrip("."), f"${float(c9):,.2f}", ref9,
               un=_un(take9, c9))
            if sl9.get("manual"):
                of_applied[r9["posting_id"]] = (take9, c9)
            u9 = sale_used.setdefault(lot9["id"], {"qty": Decimal(0), "cost": Decimal(0), "n": 0, "rows": []})
            u9["qty"] += take9 * (lot9.get("ratio") or 1) if sl9.get("rcpt") else take9
            u9["cost"] += c9
            u9["n"] += 1
            if len(u9["rows"]) < 20:
                u9["rows"].append({"t": datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d %H:%M"), "q": _f(take9, 4),
                                   "ref": str(ref9 or ""), "where": cur_src[0]})
            return take9, c9

        def out_move(r9, g9, q9, ts9, chain9, txh9):
            sale9 = False
            loc9 = r9["location"] or ""
            dest9 = loc9.split(":", 2)[2] if loc9.count(":") >= 2 else "?"
            t9n = (txh9 or "").lower() if (txh9 or "").startswith("0x") else txh9
            o9 = ob.setdefault(dest9, {"chains": set(), "first": ts9, "last": ts9, "txs": set(), "tokens": {}, "list": [],
                                       "auto": None})
            o9["chains"].add(chain9)
            o9["first"] = min(o9["first"], ts9)
            o9["last"] = max(o9["last"], ts9)
            o9["txs"].add(txh9)
            for l0 in ((_ro.get((r9["source_ns"], r9["source_id"])) or {}).get("loc") or ()):
                p0 = str(l0).split(":")
                if len(p0) >= 3 and p0[2]:
                    o9.setdefault("from_w", set()).add("w:" + p0[2])
            o9.setdefault("txsyms", {}).setdefault(txh9, set()).add(g9["sym"])
            usd_send = Decimal(r9["cost_usd"]) if r9["cost_usd"] is not None else None
            mc9, mk9, mu9 = consume(g9, q9)
            cp_o9 = cp_last[0]
            kr9 = krw_took(mc9, ts9)
            o9.setdefault("sends", []).append((int(ts9), g9["gid"], usd_send, (mk9 + mu9) if g9["gid"] in ever_in else Decimal(0),
                                               bool(r9["kind"] == "native" or g9["is_stable"]),
                                               Decimal(str(r9["cost_krw"])) if r9["cost_krw"] is not None else None, self._of_key(r9),
                                               self._of_asset(r9), str(r9["qty_base"]), False))
            g9["qty_timeline"].append((ts9, -q9))
            tk9 = o9["tokens"].setdefault(g9["sym"], {"qty": Decimal(0), "cost": Decimal(0), "usd_send": Decimal(0),
                                                       "usd_send_known": True, "gid": g9["gid"], "unknown": Decimal(0),
                                                       "held": Decimal(0), "stable": bool(g9["is_stable"])})
            tk9["qty"] += q9
            tk9["held"] += (mk9 + mu9) if g9["gid"] in ever_in else Decimal(0)
            tk9["cost"] += mc9
            tk9["unknown"] += mu9 + max(Decimal(0), q9 - (mk9 + mu9))
            if usd_send is None:
                tk9["usd_send_known"] = False
            else:
                tk9["usd_send"] += usd_send
                o9["wusd"] = o9.get("wusd", 0.0) + float(usd_send)
                dk9 = datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d")
                wd9 = o9.setdefault("wdays", {})
                wd9[dk9] = wd9.get(dk9, 0.0) + float(usd_send)
            s9o = signer9.get((r9["source_ns"], r9["source_id"]))
            sg9o = (None if not s9o or spamguard.snapshot_synth(s9o[1], s9o[2]) or not s9o[0]
                    else spamguard.signer_mine(*s9o, my_all9))
            li9 = self._of_list_add(o9, {"ts": int(ts9), "t": datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d %H:%M"),
                                         "chain": chain9, "tx": txh9, "sym": g9["sym"], "qty": float(q9),
                                         "usdAtSend": float(usd_send) if usd_send is not None else None, "costUsd": float(mc9),
                                         "signed": sg9o, "key": self._of_key(r9)})
            qs9 = f"{q9:,.4f}".rstrip("0").rstrip(".")
            ex_fx = fx_dep_tx.get(t9n) or fx_dep_tx.get(txh9)
            u_up = up_dep_by_tx.get(t9n) or up_dep_by_tx.get(txh9)
            am9 = of_match.get(r9["posting_id"])
            if dest9 in of_noauto:
                ex_fx = u_up = am9 = None
            elif am9 and not (ex_fx or u_up):
                if am9["ex"] == "upbit":
                    u_up = am9.get("uuid") or "addr"
                else:
                    ex_fx = am9["ex"]
            basis9 = (am9 or {}).get("basis") or "txid"
            bm9 = None if (ex_fx or u_up or dest9 in of_noauto) else of_bridge.get(r9["posting_id"])
            if g9["gid"] in ever_in:
                o9.setdefault("rtx", set()).add(txh9)
            if bm9:
                o9.setdefault("mtx", set()).add(txh9)
                o9.setdefault("basis", set()).add("bridge")
                o9["musd"] = o9.get("musd", 0.0) + (float(usd_send) if usd_send is not None and g9["gid"] in ever_in else 0.0)
                arr9 = {"basis": "bridge", "chain": bm9["chain"], "tx": bm9["tx"], "wallet": bm9.get("wallet") or "",
                        "sym": bm9["sym"], "qty": float(bm9["qty"]), "dt": int(bm9["ts"] - ts9)}
                o9.setdefault("arrivals", []).append(dict(arr9, ts=int(bm9["ts"]), sentSym=g9["sym"], sentQty=float(q9)))
                if li9 is not None:
                    li9["match"] = arr9
            elif ex_fx or u_up:
                if basis9 in ("txid", "amount_time", "hop_split"):
                    g9["risk_allow"] = True
                o9.setdefault("mtx", set()).add(txh9)
                o9.setdefault("basis", set()).add(basis9)
                o9["musd"] = o9.get("musd", 0.0) + (float(usd_send) if usd_send is not None and g9["gid"] in ever_in else 0.0)
                if li9 is not None:
                    li9["match"] = {"basis": basis9, "exchange": fx_name.get(ex_fx, ex_fx) if ex_fx else "업비트"}
            if ex_fx:
                e5 = fxdep_transit.setdefault((t9n, g9["sym"]), {"qty": Decimal(0), "cost": Decimal(0), "known": Decimal(0),
                                                                  "unknown": Decimal(0), "left": Decimal(0), "gid": g9["gid"],
                                                                  "sym": g9["sym"], "ex": ex_fx})
                e5["qty"] += q9; e5["cost"] += mc9; e5["known"] += mk9
                e5["krw"] = e5.get("krw", Decimal(0)) + kr9
                e5.setdefault("_src", []).append((r9["posting_id"], 1.0))
                e5["_cmp"] = cp_merge(e5.get("_cmp") or {}, cp_o9)
                e5.setdefault("cycs", []).append((g9["cur"], q9, mc9))
                e5["unknown"] += mu9 + max(Decimal(0), q9 - (mk9 + mu9))
                if not (basis9 == "address" and not (am9 or {}).get("uuid") and now - float(ts9) > outflow_match.WIN_AFTER):
                    e5["left"] += q9
                o9["auto"] = ("exchange", fx_name.get(ex_fx, ex_fx), ex_fx)
                d9 = (f"{CHAIN_NAME.get(chain9, chain9)} → {dest9[:6]}…{dest9[-4:]} → {fx_name.get(ex_fx, ex_fx)} 입금 {len(am9.get('uuids') or [])}건"
                      if basis9 == "hop_split" else f"{CHAIN_NAME.get(chain9, chain9)} → {fx_name.get(ex_fx, ex_fx)} 입금") \
                    + f" ({OF_BASIS_KO.get(basis9, basis9)} 자동 매칭 · 원가 이관)"
            elif u_up and basis9 == "hop_split" and am9.get("amts"):
                amts9 = [Decimal(str(a)) for a in am9["amts"]]
                tot9 = sum(amts9, Decimal(0))
                unk9h = mu9 + max(Decimal(0), q9 - (mk9 + mu9))
                for a9h in amts9:
                    f9h = a9h / tot9 if tot9 > 0 else Decimal(0)
                    ex_transit.setdefault(txh9, []).append(
                        {"gid": g9["gid"], "sym": g9["sym"], "qty": q9 * f9h, "cost": mc9 * f9h, "krw": kr9 * f9h, "known": mk9 * f9h,
                         "unknown": unk9h * f9h, "raw_sym": (r9["symbol"] or "").upper(), "credited": True, "used": False, "split": True,
                         "_src": [(r9["posting_id"], float(f9h))], "_cmp": cp_merge({}, cp_o9, float(f9h))})
                diag["ex_out_cost"] += mc9
                diag["ex_out_n"] += 1
                o9["auto"] = ("exchange", "업비트", "upbit")
                d9 = (f"{CHAIN_NAME.get(chain9, chain9)} → {dest9[:6]}…{dest9[-4:]} → 업비트 입금 {len(amts9)}건 "
                      f"({OF_BASIS_KO.get(basis9, basis9)} 자동 매칭 · 원가 이관)")
            elif u_up:
                ex_transit.setdefault(txh9, []).append(
                    {"gid": g9["gid"], "sym": g9["sym"], "qty": q9, "cost": mc9, "krw": kr9, "known": mk9,
                     "unknown": mu9 + max(Decimal(0), q9 - (mk9 + mu9)), "raw_sym": (r9["symbol"] or "").upper(),
                     "credited": not (u_up == "addr" and now - float(ts9) <= outflow_match.WIN_AFTER), "used": False,
                     "cyc": g9["cur"], "_src": [(r9["posting_id"], 1.0)], "_cmp": cp_merge({}, cp_o9)})
                diag["ex_out_cost"] += mc9
                diag["ex_out_n"] += 1
                o9["auto"] = ("exchange", "업비트", "upbit")
                ut9 = up_dep_uid_ts.get(u_up) if isinstance(u_up, str) else None
                if ut9 is not None and up_win_t0 is not None and ut9 < up_win_t0 - 60:
                    o9["prewin"] = o9.get("prewin", 0) + 1
                    d9 = f"{CHAIN_NAME.get(chain9, chain9)} → 업비트 입금 ({OF_BASIS_KO.get(basis9, basis9)} 자동 매칭 · 창 이전 입금 · 원가 이관 없음)"
                else:
                    d9 = f"{CHAIN_NAME.get(chain9, chain9)} → 업비트 입금 ({OF_BASIS_KO.get(basis9, basis9)} 자동 매칭 · 원가 이관)"
            elif bm9:
                bt_q, bt_k, bt_u = q9, mk9, mu9 + max(Decimal(0), q9 - (mk9 + mu9))
                aq9 = Decimal(str(bm9.get("qty") or 0))
                if aq9 > 0 and q9 > 0 and outflow_match.family(bm9.get("sym")) != outflow_match.family(g9["sym"]):
                    r9x = aq9 / q9
                    bt_q, bt_k, bt_u = aq9, mk9 * r9x, bt_u * r9x
                br_transit[bm9["key"]] = {"sym": g9["sym"], "qty": bt_q, "ts": ts9, "cost": mc9, "known": bt_k,
                                          "unknown": bt_u, "left": bt_q, "gid": g9["gid"], "_src": [(r9["posting_id"], 1.0)], "_cmp": cp_merge({}, cp_o9)}
                if bt_q is aq9:
                    br_transit[bm9["key"]]["_cv"] = {"from": cv_label(cp_o9, g9["sym"]), "ratio": float(r9x)}
                d9 = (f"{CHAIN_NAME.get(chain9, chain9)} → 브릿지 → 내 {CHAIN_NAME.get(bm9['chain'], bm9['chain'])} 지갑 "
                      f"(자동 매칭 · {max(0, int(bm9['ts'] - ts9)) // 60}분 뒤 도착 · 원가 이관)")
            elif (chain9, str(txh9 or "").lower(), dest9) in sale_bid9 and dest9 not in of_noauto:
                sale9 = True
                lb9 = sale_bid9[(chain9, str(txh9 or "").lower(), dest9)]
                o9.setdefault("mtx", set()).add(txh9)
                o9.setdefault("basis", set()).add("sale")
                o9["musd"] = o9.get("musd", 0.0) + (float(usd_send) if usd_send is not None and g9["gid"] in ever_in else 0.0)
                o9["auto"] = ("sale", "토큰 세일 입찰", None)
                if li9 is not None:
                    li9["match"] = {"basis": "sale", "exchange": "토큰 세일 입찰", "lot": lb9["id"]}
                d9 = f"{CHAIN_NAME.get(chain9, chain9)} → 토큰 세일 입찰 ({lb9['label']} · 원가는 수령 토큰으로 이어짐)"
            else:
                unk9 = mu9 + max(Decimal(0), q9 - (mk9 + mu9))
                if unk9 <= EPS:
                    c9t = f"원가 ${float(mc9):,.2f}"
                elif mc9 > 0:
                    c9t = f"원가 ${float(mc9):,.2f} + 원가 미확인분"
                else:
                    c9t = "원가 미확인"
                dl9 = {"multi": "여러 수령처", "?": "수령처 미상"}.get(dest9) or f"외부 {dest9[:8]}…{dest9[-4:]}"
                d9 = f"{CHAIN_NAME.get(chain9, chain9)} → {dl9} (보낸 내역 · {c9t} 유출)"
            if (r9["source_ns"], txh9) in rt_out and not g9["is_stable"] and not (ex_fx or u_up or bm9):
                rt9 = rt_transit.setdefault((r9["source_ns"], txh9, g9["gid"]), {"qty": Decimal(0), "cost": Decimal(0), "known": Decimal(0),
                                                                                  "unknown": Decimal(0), "left": Decimal(0)})
                rt9["qty"] += q9; rt9["left"] += q9; rt9["cost"] += mc9; rt9["known"] += mk9
                rt9.setdefault("_src", []).append((r9["posting_id"], 1.0))
                rt9["_cmp"] = cp_merge(rt9.get("_cmp") or {}, cp_o9)
                rt9["krw"] = rt9.get("krw", Decimal(0)) + kr9
                rt9["unknown"] += mu9 + max(Decimal(0), q9 - (mk9 + mu9))
                d9 += " · 프로그램 예치(왕복 — 복귀 시 원가 복원)"
            rb9 = rt_back.get((r9["source_ns"], txh9)) if (dest9 in ("multi", "?") and (r9["source_ns"], txh9) in rt_same
                                                           and not (ex_fx or u_up or bm9 or sale9) and dest9 not in of_noauto) else None
            if rb9 and r9["asset_id"] in rb9[0]:
                if rb9[1]:
                    o9.setdefault("mtx", set()).add(txh9)
                o9.setdefault("basis", set()).add("roundtrip")
                o9["musd"] = o9.get("musd", 0.0) + (float(usd_send) if usd_send is not None and g9["gid"] in ever_in else 0.0)
                if li9 is not None:
                    li9["match"] = {"basis": "roundtrip", "exchange": "프로그램 예치 왕복"}
                if g9["is_stable"]:
                    d9 += " · 프로그램 예치(왕복 — 같은 지갑으로 전액 복귀)"
            if (li9.get("match") or {}).get("basis") in ("sale", "roundtrip") and ts9 >= now - flowev.WINDOW:
                o9.setdefault("flow_matches", []).append(li9)
            g9["last_out"] = {"ex": None, "tx": txh9}
            a9 = f"${float(usd_send):,.2f}" if usd_send is not None and g9["gid"] in ever_in else f"${float(mc9):,.2f}"
            un9 = _un(q9, usd_send if usd_send is not None and g9["gid"] in ever_in else mc9)
            if g9["cur"] is not None:
                g9["cur"]["moved_qty"] += q9
                g9["cur"]["moved_cost"] += mc9
                lab9 = (fx_name.get(ex_fx, ex_fx) if ex_fx else "업비트" if u_up
                        else f"{CHAIN_NAME.get(bm9['chain'], bm9['chain'])} 지갑" if bm9 else "토큰 세일 입찰" if sale9
                        else "프로그램 예치 (같은 지갑 복귀)" if (rb9 and r9["asset_id"] in rb9[0]) else None)
                mv_note(g9["cur"], lab9 or "외부 주소", q9, own=bool(lab9))
                if g9["is_stable"]:
                    extra_ev(ts9, g9, "외부 전송", d9, qs9, a9, txh9, un=un9)
                    of_ev9 = extra_events[-1]
                else:
                    ev(g9["cur"], ts9, "외부 전송", d9, qs9, a9, txh9, un=un9)
                    of_ev9 = g9["cur"]["events"][-1]
                if g9["qty_known"] + g9["qty_unknown"] <= Decimal("0.000001"):
                    g9["cur"] = None
            else:
                extra_ev(ts9, g9, "외부 전송", d9, qs9, a9 if usd_send is not None and g9["gid"] in ever_in else "—", txh9,
                         un=un9 if usd_send is not None and g9["gid"] in ever_in else None)
                of_ev9 = extra_events[-1]
            if not (ex_fx or u_up or bm9):
                try:
                    if sale9:
                        of9 = {"c": "sale_auto", "nm": "토큰 세일 입찰", "lab": d9}
                    else:
                        of9 = salelink.label(CHAIN_NAME.get(chain9, chain9), dest9, of_dec9.get(dest9), c9t,
                                             system=(dest9 == "0x0000000000000000000000000000000000008001" and chain9 == "zksync"),
                                             roundtrip=bool(rb9 and r9["asset_id"] in rb9[0]))
                    lw9 = sorted(str(l0).split(":", 2)[2] for l0 in ((_ro.get((r9["source_ns"], r9["source_id"])) or {}).get("loc") or ())
                                 if str(l0).count(":") >= 2)
                    of_ev9["of"] = dict(of9, a=dest9, ch=chain9, tx=str(txh9 or ""), w=lw9[0] if lw9 else "", **({} if sale9 else {"cost": c9t}))
                except Exception as e9:
                    log.debug("외부 전송 분류 표식 실패: %s", e9)

        win_cut = {}
        qn_all9 = []
        for r in rows:
            q_w = self._norm(r)
            qn_all9.append((r, q_w))
            if r["leg_kind"] == "opening" and q_w < 0:
                continue
            if r["event"] == "TRANSFER_OUT":
                continue
            st_w = win_cut.get(r["group_id"] or -r["asset_id"])
            if st_w is None:
                st_w = win_cut[r["group_id"] or -r["asset_id"]] = [Decimal(0), Decimal(0), None]
            st_w[0] += q_w
            if st_w[0] < st_w[1]:
                st_w[1] = st_w[0]
                st_w[2] = r["event_ts"]
        win_cut_d = {}
        for r in rows:
            gid_w = r["group_id"] or -r["asset_id"]
            if gid_w in win_cut_d:
                continue
            st_w = win_cut.get(gid_w)
            if st_w is None or st_w[1] >= -EPS:
                win_cut_d[gid_w] = None
                continue
            g_w = gstate(r)
            if g_w["is_stable"] or g_w.get("is_fiat"):
                win_cut_d[gid_w] = None
                continue
            d_w = -st_w[1]
            win_cut_d[gid_w] = (d_w, st_w[2])
            g_w["qty_unknown"] += d_w
            note_unk(g_w, backfill_t0, "창 이전 보유분 · 창 절단 추정(원가 없음)", d_w, "", chain9=r["chain"] or "?")

        my_evm9 = {str(w9.get("address") or "").lower() for w9 in self._hist_wallets() if w9.get("type") != "sol"}
        my_all9 = my_evm9 | {str(w9.get("address") or "") for w9 in self._hist_wallets() if w9.get("type") == "sol"}
        spoof_keys = set()
        wbal9 = {}
        self._ph("xfer_links·positions")
        signer9 = self._signer_map(conn, rows)
        pid_row = {}
        sell_wm = {}

        def sell_pre(fl9, evs9):
            w9 = sell_wm.get(id(fl9))
            if w9 is None or w9[0] is not fl9 or w9[1] is not evs9:
                return 0, 0
            f9, l9, n9 = w9[2], w9[3], w9[4]
            for k9 in range(len(evs9) - n9 + 1):
                if evs9[k9] is f9:
                    return (k9, n9) if evs9[k9 + n9 - 1] is l9 else (0, 0)
            return 0, 0

        def sell_mark(fl9):
            evs9 = fl9["events"]
            if evs9:
                sell_wm[id(fl9)] = (fl9, evs9, evs9[0], evs9[-1], len(evs9))
            else:
                sell_wm.pop(id(fl9), None)

        g0_9, n9i = self.__dict__.get("_ph_gen0"), 0
        for r in rows:
            n9i += 1
            if not (n9i & 4095) and g0_9 is not None and self._inval_now() != g0_9:
                raise _BuildObsolete("replay")
            g = gstate(r)
            chain = r["chain"] or "?"
            g["chains"].add(chain)
            qn9 = qn_all9[n9i - 1] if n9i <= len(qn_all9) else None
            q = qn9[1] if qn9 is not None and qn9[0] is r else self._norm(r)
            ts = r["event_ts"]
            lk, evk = r["leg_kind"], r["event"]
            cur_row[0] = r
            cp_sync(g)
            pid_row[r["posting_id"]] = r
            if lk in ("acq", "disp") and r["cost_usd"] is not None:
                g["px_seen"] = True
            if evk in ("EX_DEPOSIT", "EXF_DEPOSIT", "EX_SELL", "EXF_SELL", "EX_BUY", "EXF_BUY", "EX_WITHDRAW", "EXF_WITHDRAW"):
                g["ex_seen"] = True
            elif evk in ("TRANSFER_OUT_EX", "BRIDGE", "TRANSFER_SELF") and lk in ("move_out", "move_in"):
                g["mv_seen"] = True
            if (r["location"] or "").startswith("wallet:"):
                wk9 = (r["asset_id"], r["location"])
                held9 = wbal9.get(wk9, Decimal(0))
                if lk == "move_out" and q < 0:
                    g["sent_n"] = g.get("sent_n", 0) + 1
                if lk == "move_out" and q < 0 and chain != "sol" and r["kind"] == "token" \
                        and evk in ("TRANSFER_OUT", "BRIDGE", "TRANSFER_SELF", "TRANSFER_OUT_EX") \
                        and -q > max(held9, Decimal(0)) * Decimal("1.000001") + EPS \
                        and not spamguard.is_genuine(chain, r["address"]) \
                        and (r["source_ns"], r["source_id"]) in signer9 \
                        and spamguard.signer_known_other(*signer9[(r["source_ns"], r["source_id"])], my_evm9):
                    spoof_keys.add((r["source_ns"], r["source_id"], r["asset_id"]))
                    g["spoof_n"] = g.get("spoof_n", 0) + 1
                elif lk == "move_out" and q < 0 and chain != "sol" and r["kind"] == "token" \
                        and evk in ("TRANSFER_OUT", "BRIDGE", "TRANSFER_SELF", "TRANSFER_OUT_EX") \
                        and not spamguard.is_genuine(chain, r["address"]) and (r["source_ns"], r["source_id"]) in signer9 \
                        and spamguard.signer_known_other(*signer9[(r["source_ns"], r["source_id"])], my_evm9):
                    g["spoof_soft"] = g.get("spoof_soft", 0) + 1
                wbal9[wk9] = held9 + q
            loc9 = r["location"] or ""
            if loc9.startswith("wallet:"):
                p9 = loc9.split(":")
                cur_src[0] = f"w:{p9[2]}" if len(p9) >= 3 and p9[2] else "w:?"
            elif loc9.startswith("exchange:"):
                cur_src[0] = "ex:" + loc9.split(":")[1]
            else:
                cur_src[0] = None
            cur_lab[0] = (CHAIN_NAME.get(chain, chain) if chain != "?"
                          else fx_name.get(loc9.split(":")[1], loc9.split(":")[1]) if loc9.startswith("exchange:") else None)
            if g["cur"] is not None and cur_lab[0] and lk != "gas":
                chl9 = g["cur"].setdefault("chl", {})
                chl9[cur_lab[0]] = chl9.get(cur_lab[0], 0) + 1
            cost = Decimal(r["cost_usd"]) if r["cost_usd"] is not None else None
            dkey = acct_norm.iso_day(ts)
            txh = r["source_id"]

            if r["kind"] in ("native", "exchange_currency"):
                g["risk_allow"] = True
            if lk == "disp" and evk == "SWAP" and r["cost_usd"] is not None and q < 0:
                for cp9 in swap_recv.get((r["source_ns"], txh)) or ():
                    if cp9[0] != g["gid"]:
                        g.setdefault("risk_disp_cp", set()).add(cp9)
            if evk in ("EX_BUY", "EXF_BUY", "TRANSFER_SELF", "CONVERT", "BRIDGE",
                       "EX_DEPOSIT", "EX_SELL") or \
                    (lk == "acq" and evk == "SWAP"):
                g["risk_allow"] = True
            elif lk == "acq" and evk in ("TRANSFER_IN", "PROGRAM_IN") and q > 0:
                if r["cost_usd"] is not None:
                    g["risk_allow"] = True
                elif len(g.setdefault("risk_srcs", [])) < 50 and r["address"] \
                        and (chain, txh, r["address"]) not in g.setdefault("risk_srcs_seen", set()):
                    g["risk_srcs_seen"].add((chain, txh, r["address"]))
                    g["risk_srcs"].append((chain, txh, r["address"]))
            elif lk == "opening" and evk == "OPENING":
                if q > 0:
                    g["risk_open_unk"] = True
                elif q < 0 and str(txh).startswith("rebal"):
                    g["risk_rebal_neg"] = True

            if str(evk or "").startswith("LP_") and lk in ("disp", "acq"):
                if (r["source_ns"], txh) not in lp_done:
                    lp_done.add((r["source_ns"], txh))
                    lp_tx(r)
                continue

            if lk == "gas" and evk == "EXF_WD_FEE":
                fq9w = -q
                unit9w = Decimal(1) if g["is_stable"] else None
                if unit9w is None and not g.get("is_fiat"):
                    cp9w = fxb.candle(g["sym"], ts)
                    if cp9w:
                        unit9w = Decimal(str(cp9w))
                if unit9w is None and g["qty_known"] > EPS:
                    unit9w = g["cost"] / g["qty_known"]
                if unit9w is None and (g["sym"] or "").upper() in pricing.MAJOR_CANDLE_SYMS:
                    sp9w = self.spot.price(g["sym"])
                    if sp9w:
                        unit9w = Decimal(str(sp9w))
                usd9w = fq9w * unit9w if (unit9w is not None and fq9w > 0) else Decimal(0)
                if gas_on and usd9w > 0:
                    rt9w = fxb.rate_at(ts)
                    realized_by_date[dkey] = realized_by_date.get(dkey, 0) - float(usd9w)
                    realized_krw_by_date[dkey] = realized_krw_by_date.get(dkey, 0) - float(usd9w) * rt9w
                    ge9w = gas_expense.setdefault(dkey, [Decimal(0), 0, 0.0, {}])
                    ge9w[0] += usd9w
                    ge9w[1] += 1
                    ge9w[2] += float(usd9w) * rt9w
                    kd9w = ge9w[3].setdefault("EXF_WD_FEE", [Decimal(0), 0, Decimal(0), 0, ""])
                    kd9w[0] += usd9w
                    kd9w[1] += 1
                    if usd9w > kd9w[2]:
                        kd9w[2], kd9w[3], kd9w[4] = usd9w, int(ts or 0), (r["location"] or "").split(":")[-1]
                consume(g, -q, cp=False)
                g["qty_timeline"].append((ts, q))
                continue
            if lk == "gas" and evk == "EXF_FEE":
                fq9 = -q
                k9f = (r["source_ns"], txh)
                a9f, d9f = fee_acq.get(k9f), fee_disp.get(k9f)
                unit9 = None
                for c9f in (a9f, d9f):
                    if unit9 is None and c9f and c9f["gid"] == g["gid"] and c9f["qty"] > 0 and c9f["usd"] is not None:
                        unit9 = c9f["usd"] / c9f["qty"]
                if unit9 is None and g["is_stable"]:
                    unit9 = Decimal(1)
                if unit9 is None and not g.get("is_fiat"):
                    cp9 = fxb.candle(g["sym"], ts)
                    if cp9:
                        unit9 = Decimal(str(cp9))
                if unit9 is None and g["qty_known"] > EPS:
                    unit9 = g["cost"] / g["qty_known"]
                if unit9 is None and (g["sym"] or "").upper() in pricing.MAJOR_CANDLE_SYMS:
                    sp9 = self.spot.price(g["sym"])
                    if sp9:
                        unit9 = Decimal(str(sp9))
                F9 = fq9 * unit9 if (unit9 is not None and fq9 > 0) else Decimal(0)
                if unit9 is None and fq9 > 0:
                    fee_diag["no_px"] += 1
                if F9 > 0 and (a9f or d9f):
                    fee_diag["n"] += 1
                    if a9f and not a9f["g"]["is_stable"] and not a9f["g"].get("is_fiat"):
                        ga9 = a9f["g"]
                        ga9["cost"] += F9
                        a9f["flow"]["cost"] += F9
                        a9f["flow"]["cost_krw"] += krw_of(F9, ts, a9f["row"])
                        if k9f in krw_mkt:
                            a9f["flow"]["kmc"] = a9f["flow"].get("kmc", Decimal(0)) + F9
                        fee_diag["usd_cost"] += F9
                    elif a9f and a9f["g"]["is_stable"] and d9f and d9f.get("fiat"):
                        ga9 = a9f["g"]
                        ga9["cost"] += F9
                        a9f["flow"]["cost"] += F9
                        a9f["flow"]["cost_krw"] += krw_of(F9, ts, a9f["row"])
                        fee_diag["usd_cost"] += F9
                    elif d9f and not d9f.get("fiat"):
                        rt9f = d9f["rate"]
                        sh9 = (d9f["fk"] / d9f["qty"]) if d9f["qty"] > 0 else Decimal(1)
                        Fk9, Fu9 = F9 * sh9, F9 - F9 * sh9
                        fl9f, dk9f = d9f["flow"], d9f["dkey"]
                        if Fk9 > 0:
                            d9f["g"]["realized"] -= Fk9
                            fl9f["realized"] -= Fk9
                            fl9f["rbd"][dk9f] = fl9f["rbd"].get(dk9f, Decimal(0)) - Fk9
                            fl9f["rbdk"][dk9f] = fl9f["rbdk"].get(dk9f, 0.0) - float(Fk9) * rt9f
                            realized_by_date[dk9f] = realized_by_date.get(dk9f, 0) - float(Fk9)
                            realized_krw_by_date[dk9f] = realized_krw_by_date.get(dk9f, 0) - float(Fk9) * rt9f
                            if d9f.get("loc") is not None:
                                _rl9 = realized_by_loc.setdefault((d9f["loc"], dk9f), [0.0, 0.0]); _rl9[0] -= float(Fk9); _rl9[1] -= float(Fk9) * rt9f
                            if d9f["tax"] is not None:
                                _tax_add(d9f["tax"], "fee", Fk9)
                            fee_diag["usd_realized"] += Fk9
                        if Fu9 > 0 and d9f["u"] is not None:
                            d9f["u"]["proceeds"] -= Fu9
                            d9f["ud"]["proceeds"] -= Fu9
                            d9f["fu9"][1] -= Fu9
                            fee_diag["usd_unv"] += Fu9
                        fl9f["proceeds"] = fl9f.get("proceeds", Decimal(0)) - F9
                        fl9f["proceeds_krw"] = fl9f.get("proceeds_krw", Decimal(0)) - F9 * Decimal(str(rt9f))
            if lk == "gas" and evk == "EXF_FEE":
                ex_fee_add((r["location"] or "").split(":")[-1], F9, ts)
                consume(g, -q, cp=False)
                g["qty_timeline"].append((ts, q))
                continue
            if lk == "gas":
                usd = cost or Decimal(0)
                if gas_on and usd > 0 and not (evk == "SWAP" and (swap_gas.get((r["source_ns"], txh)) or {}).get("done")):
                    rt9g = fxb.rate_at(ts)
                    realized_by_date[dkey] = realized_by_date.get(dkey, 0) - float(usd)
                    realized_krw_by_date[dkey] = realized_krw_by_date.get(dkey, 0) - float(usd) * rt9g
                    ge9 = gas_expense.setdefault(dkey, [Decimal(0), 0, 0.0, {}])
                    ge9[0] += usd
                    ge9[1] += 1
                    ge9[2] += float(usd) * rt9g
                    kd9 = ge9[3].setdefault(evk or "?", [Decimal(0), 0, Decimal(0), 0, ""])
                    kd9[0] += usd
                    kd9[1] += 1
                    if usd > kd9[2]:
                        kd9[2], kd9[3], kd9[4] = usd, int(ts or 0), chain
                cinfo = gas_by_chain.setdefault(chain, {"usd": Decimal(0), "tx": 0})
                cinfo["usd"] += usd
                cinfo["tx"] += 1
                mk9 = kst_fmt(ts, "%Y-%m")
                mi9 = gas_by_month.setdefault(mk9, {}).setdefault(
                    chain, {"usd": Decimal(0), "tx": 0})
                mi9["usd"] += usd
                mi9["tx"] += 1
                ent2 = tx_group.get((r["source_ns"], txh))
                if ent2 is not None and ent2[0] in G:
                    g2 = G[ent2[0]]
                    tgt = g2["cur"] or (g2["flows"][-1] if g2["flows"] else None)
                    if tgt:
                        tgt["fee"] += usd
                consume(g, -q, cp=False)
                g["qty_timeline"].append((ts, q))
                continue

            if lk == "move_in" and evk == "EX_DEPOSIT":
                g.setdefault("ex_dep", set()).add("upbit")
                g["qty_timeline"].append((ts, q))
                txh2 = uuid2txh.get(r["source_id"])
                all5 = ex_transit.get(txh2, []) if txh2 else []
                syms5 = {acct_norm.canon(e2.get("raw_sym", "")) for e2 in all5}
                cur5 = acct_norm.canon(g["sym"], "upbit")
                cands5 = [e2 for e2 in all5
                          if not e2["used"] and e2["qty"] > 0 and (len(syms5) <= 1 or acct_norm.canon(e2.get("raw_sym", "")) == cur5)]
                ents = []
                tot5 = sum((e2["qty"] for e2 in cands5), Decimal(0))
                sp5 = any(e2.get("split") for e2 in cands5)
                if cands5 and not sp5 and abs(q - tot5) <= tot5 * Decimal("0.01"):
                    ents = cands5
                else:
                    for e2 in (sorted(cands5, key=lambda e9: abs(q - e9["qty"])) if sp5 else cands5):
                        if abs(q - e2["qty"]) <= e2["qty"] * Decimal("0.01"):
                            ents = [e2]
                            break
                ent = ents[0] if ents else None
                qs5 = f"{q:,.4f}".rstrip("0").rstrip(".")
                lnk5 = None
                e7u = xl7 = None
                if not ent:
                    t7u = up_dep_uid_tx.get(r["source_id"])
                    if t7u:
                        e7u = fx_transit.get(t7u) or fx_transit.get(t7u.lower())
                        if e7u and (e7u.get("ambiguous") or e7u.get("ex") == "upbit" or e7u["left"] <= 0
                                    or q > e7u["left"] * Decimal("1.02")
                                    or not (acct_norm.same_asset(e7u.get("sym"), e7u.get("ex"), g["sym"], "upbit")
                                            or acct_norm.qty_close(q, e7u["left"]))):
                            e7u = None
                    if not e7u and r["source_id"] in xf_links:
                        xl7 = xf_links[r["source_id"]]
                        e7u = fx_transit.get(xl7["key"])
                        if e7u and (e7u.get("ambiguous") or not acct_norm.same_asset(e7u.get("sym"), e7u.get("ex"), g["sym"], "upbit")
                                    or e7u.get("ex") == "upbit" or e7u["left"] <= 0
                                    or q > e7u["left"] * Decimal("1.02")):
                            e7u = None
                if ent:
                    tot_e = sum((e2["qty"] for e2 in ents), Decimal(0))
                    ratio5 = min(q / tot_e, Decimal(1)) if tot_e > 0 else Decimal(1)
                    inh5 = Decimal(0)
                    ikr5 = Decimal(0)
                    for e2 in ents:
                        e2["used"] = True
                        if e2.get("gid") in G:
                            G[e2["gid"]]["risk_allow"] = True
                        g["qty_known"] += e2["known"] * ratio5
                        cp_add_map(g, e2.get("_cmp"), ratio5)
                        g["qty_unknown"] += e2["unknown"] * ratio5
                        note_unk(g, ts, "업비트 입금 · 내 지갑 출금 승계(원가 없음)", e2["unknown"] * ratio5, txh2, ex9="upbit", up_gid=e2.get("gid"), unc9=Decimal(0))
                        inh5 += e2["cost"] * ratio5
                        ikr5 += krw_inh(e2, e2["cost"] * ratio5, ts)
                        diag["ex_dep_fee_resid_cost"] += e2["cost"] * (Decimal(1) - ratio5)
                    g["qty_unknown"] += max(Decimal(0), q - tot_e)
                    note_unk(g, ts, "업비트 입금 초과분(원가 없음)", max(Decimal(0), q - tot_e), txh2 or r["source_id"], ex9="upbit", unc9=Decimal(0))
                    g["cost"] += inh5
                    diag["ex_dep_inh_cost"] += inh5
                    diag["ex_dep_inh_n"] += 1
                    flow5 = flow_of(g, ts, chain)
                    flow5["bought"] += q
                    flow5["cost"] += inh5
                    flow5["cost_krw"] += ikr5
                    in_note(flow5, "내 지갑", q, inh5, ts, cost_krw=ikr5)
                    known5 = sum((e2["known"] for e2 in ents), Decimal(0)) * ratio5
                    lnk5 = [(sp9, float(ratio5) * w9) for e2 in ents for sp9, w9 in e2.get("_src", ())]
                    d5 = (f"업비트 입금 완료 · 원장 이관 (원가 승계 ${float(inh5):,.2f})" if known5 > EPS
                          else "업비트 입금 완료 · 원장 이관 (원가 미상 승계)")
                elif e7u:
                    take7 = min(q, e7u["left"])
                    e7u["left"] -= take7
                    sc7 = take7 / e7u["qty"] if e7u["qty"] > 0 else Decimal(1)
                    inh7 = e7u["cost"] * sc7
                    lnk5 = [(sp9, float(sc7) * w9) for sp9, w9 in e7u.get("_src", ())]
                    if e7u.get("oa"):
                        g["oa"] = (g.get("oa") or Decimal(0)) + e7u["oa"] * sc7
                    g["qty_known"] += e7u["known"] * sc7
                    cp_add_map(g, e7u.get("_cmp"), sc7)
                    g["qty_unknown"] += e7u["unknown"] * sc7 + (q - take7)
                    note_unk(g, ts, "업비트 입금 · 해외거래소 출금 승계 잔여(원가 없음)", e7u["unknown"] * sc7 + (q - take7), up_dep_uid_tx.get(r["source_id"]) or r["source_id"], ex9="upbit", unc9=q - take7,
                             up_gid=e7u.get("gid"), via9=f"{fx_name.get(e7u.get('ex'), e7u.get('ex'))} 출금 승계 (그 거래소 {e7u.get('sym')} 의 원가 미상분)")
                    g["cost"] += inh7
                    flow5 = flow_of(g, ts, chain)
                    flow5["bought"] += take7
                    flow5["cost"] += inh7
                    ikr7 = krw_inh(e7u, inh7, ts)
                    flow5["cost_krw"] += ikr7
                    st7 = e7u.pop("story", None)
                    if st7:
                        flow5["events"][:0] = st7
                    in_note(flow5, fx_name.get(e7u["ex"], e7u["ex"]), take7, inh7, ts, st7, cost_krw=ikr7)
                    d5 = (f"업비트 입금 완료 · {fx_name.get(e7u['ex'], e7u['ex'])}"
                          + (f" 출금 원가 승계 (${float(inh7):,.2f})" if e7u["known"] * sc7 > EPS
                             else " 출금 이관 (원가 미상 승계)")
                          + (f" · {xl7['label']}" if xl7 else ""))
                elif of_cand(r, g, q, ts, up_dep_uid_tx.get(r["source_id"]) or r["source_id"]):
                    pass
                elif (not g["is_stable"] and r["posting_id"] in sale_links
                      and sale_book(g, r, q, ts, chain, up_dep_uid_tx.get(r["source_id"]) or r["source_id"])):
                    d5 = "업비트 입금 완료 · 토큰 세일 원가 (입찰 지갑에서 직접 입금)"
                elif g["is_stable"]:
                    g["qty_known"] += q
                    g["cost"] += q
                    d5 = "업비트 입금 완료 (스테이블 액면)"
                elif (up_dep_uid_tx.get(r["source_id"]) or "").startswith("swap_") and \
                        up_dep_uid_tx[r["source_id"]] in swap_wd_pre and up_dep_uid_tx[r["source_id"]] not in swap_dep:
                    t9s = up_dep_uid_tx[r["source_id"]]
                    old9 = swap_wd_pre[t9s]
                    e9s = fx_transit.get(t9s)
                    if e9s and e9s.get("ex") == "upbit" and not e9s.get("ambiguous") and e9s["left"] > 0 and e9s["qty"] > 0:
                        sc9s = e9s["left"] / e9s["qty"]
                        e9s["left"] = Decimal(0)
                        kq9s = q * min(Decimal(1), e9s["known"] / e9s["qty"])
                        c9s = e9s["cost"] * sc9s
                        g["qty_known"] += kq9s
                        g["qty_unknown"] += q - kq9s
                        g["cost"] += c9s
                        fl9s = flow_of(g, ts, chain)
                        fl9s["bought"] += q
                        fl9s["cost"] += c9s
                        fl9s["cost_krw"] += krw_inh(e9s, c9s, ts)
                        note_unk(g, ts, f"업비트 토큰 전환 입금 · {old9['sym']} → {g['sym']} (구 토큰 원가 없음)", q - kq9s, t9s, ex9="upbit",
                                 up_gid=old9["gid"], unc9=Decimal(0), via9=f"업비트 토큰 전환 ({old9['sym']} 출금)")
                    else:
                        g["qty_unknown"] += q
                        note_unk(g, ts, f"업비트 토큰 전환 입금 · {old9['sym']} → {g['sym']} (구 토큰 원가 없음)", q, t9s, ex9="upbit",
                                 up_gid=old9["gid"], via9=f"업비트 토큰 전환 ({old9['sym']} 출금)")
                        lst9s = g.get("unk_src") or []
                        swap_dep[t9s] = {"g": g, "q": q, "ent": lst9s[-1] if lst9s and lst9s[-1].get("ref") == t9s else None}
                    d5 = f"업비트 토큰 전환 입금 ({old9['sym']} → {g['sym']} · 구 토큰 원가 승계)"
                else:
                    g["qty_unknown"] += q
                    note_unk(g, ts, "업비트 입금(원가 없음 · 링크 없음)", q, up_dep_uid_tx.get(r["source_id"]) or r["source_id"], ex9="upbit")
                    diag["ex_dep_unlinked_n"] += 1
                    d5 = "업비트 입금 완료 (원가 미상)"
                if g["is_stable"] or not g["cur"]:
                    extra_ev(ts, g, "입금 확인", d5, qs5, "—", txh2 or "—")
                else:
                    ev(g["cur"], ts, "입금 확인", d5, qs5, "—", txh2 or "—")
                    if lnk5:
                        g["cur"]["events"][-1]["_lnk"] = lnk5
                continue

            if lk == "move_in" and evk == "EXF_DEPOSIT":
                g["qty_timeline"].append((ts, q))
                ex6 = (r["location"] or "").split(":")[-1]
                g.setdefault("ex_dep", set()).add(ex6)
                offc_pk9, offc_av9 = None, Decimal(0)
                if (ex6, r["source_id"]) in offc_dep:
                    offc_s(ex6)["depN"] += 1
                    offc_add(ex6, g["sym"], g["is_stable"], dep=True)
                    if ex6 in offc_on:
                        offc_pk9 = (ex6, acct_norm.canon(g["sym"], ex6))
                        offc_av9 = sum((l9["left"] for l9 in offc_pool.get(offc_pk9, ()) if l9["left"] > EPS and l9["ts"] <= ts), Decimal(0))
                t6 = fx_dep_uid_tx.get(r["source_id"])
                e6 = fxdep_transit.get((t6, g["sym"])) if t6 else None
                if t6 and e6 is None:
                    c6 = [e9 for (t9, _s9), e9 in fxdep_transit.items() if t9 == t6 and e9["left"] > 0]
                    s6 = [e9 for e9 in c6 if acct_norm.same_asset(e9.get("sym"), None, g["sym"], ex6)]
                    if len(s6) == 1:
                        e6 = s6[0]
                    elif len(c6) == 1 and acct_norm.qty_close(q, c6[0]["left"]):
                        e6 = c6[0]
                qs6 = f"{q:,.4f}".rstrip("0").rstrip(".")
                e7 = None
                if t6 and not (e6 and e6["left"] > 0):
                    e7 = fx_transit.get(t6) or fx_transit.get(t6.lower())
                    if e7 and (e7.get("ambiguous") or e7.get("ex") == ex6
                               or not (acct_norm.same_asset(e7.get("sym"), e7.get("ex"), g["sym"], ex6)
                                       or acct_norm.qty_close(q, e7["left"]))):
                        e7 = None
                xl6 = None
                if not e7 and not (e6 and e6["left"] > 0) and r["source_id"] in xf_links:
                    xl6 = xf_links[r["source_id"]]
                    e7 = fx_transit.get(xl6["key"])
                    if e7 and (e7.get("ambiguous") or not acct_norm.same_asset(e7.get("sym"), e7.get("ex"), g["sym"], ex6)
                               or e7.get("ex") == ex6):
                        e7 = None
                lnk6 = None
                if e6 and e6["left"] > 0 and q <= e6["left"] * Decimal("1.02"):
                    take6 = min(q, e6["left"])
                    e6["left"] -= take6
                    sc6 = take6 / e6["qty"] if e6["qty"] > 0 else Decimal(1)
                    lnk6 = [(sp9, float(sc6) * w9) for sp9, w9 in e6.get("_src", ())]
                    inh6 = e6["cost"] * sc6
                    g["qty_known"] += e6["known"] * sc6
                    cp_add_map(g, e6.get("_cmp"), sc6)
                    g["qty_unknown"] += e6["unknown"] * sc6 + (q - take6)
                    unc6 = None
                    if not g["is_stable"]:
                        flow6 = flow_of(g, ts, chain)
                        flow6["bought"] += take6
                        flow6["cost"] += inh6
                        ikr6 = krw_inh(e6, inh6, ts)
                        flow6["cost_krw"] += ikr6
                        in_note(flow6, "내 지갑", take6, inh6, ts, cost_krw=ikr6)
                        unc6 = q - take6
                    note_unk(g, ts, f"{fx_name.get(ex6, ex6)} 입금 · 내 지갑 출금 승계(원가 없음)", e6["unknown"] * sc6 + (q - take6), t6, ex9=ex6, up_gid=e6.get("gid"), unc9=unc6)
                    g["cost"] += inh6
                    d6 = f"{fx_name.get(ex6, ex6)} 입금 완료 · 원가 승계 (${float(inh6):,.2f})"
                    diag["exf_dep_inh_cost"] += inh6
                    diag["exf_dep_inh_n"] += 1
                elif e7 and e7["left"] > 0 and q <= e7["left"] * Decimal("1.02"):
                    take7 = min(q, e7["left"])
                    e7["left"] -= take7
                    sc7 = take7 / e7["qty"] if e7["qty"] > 0 else Decimal(1)
                    inh7 = e7["cost"] * sc7
                    lnk6 = [(sp9, float(sc7) * w9) for sp9, w9 in e7.get("_src", ())]
                    if e7.get("oa"):
                        g["oa"] = (g.get("oa") or Decimal(0)) + e7["oa"] * sc7
                    g["qty_known"] += e7["known"] * sc7
                    cp_add_map(g, e7.get("_cmp"), sc7)
                    g["qty_unknown"] += e7["unknown"] * sc7 + (q - take7)
                    note_unk(g, ts, f"{fx_name.get(ex6, ex6)} 입금 · 출금 승계 잔여(원가 없음)", e7["unknown"] * sc7 + (q - take7), exf_dep_tx.get((ex6, r["source_id"])) or r["source_id"], ex9=ex6, unc9=q - take7,
                             up_gid=e7.get("gid"), via9=f"{fx_name.get(e7.get('ex'), e7.get('ex'))} 출금 승계 (그 거래소 {e7.get('sym')} 의 원가 미상분)")
                    g["cost"] += inh7
                    flow7 = flow_of(g, ts, chain)
                    flow7["bought"] += take7
                    flow7["cost"] += inh7
                    ikr7 = krw_inh(e7, inh7, ts)
                    flow7["cost_krw"] += ikr7
                    st7 = e7.pop("story", None)
                    if st7:
                        flow7["events"][:0] = st7
                    in_note(flow7, fx_name.get(e7["ex"], e7["ex"]), take7, inh7, ts, st7, cost_krw=ikr7)
                    d6 = (f"{fx_name.get(ex6, ex6)} 입금 완료 · {fx_name.get(e7['ex'], e7['ex'])}"
                          + (f" 출금 원가 승계 (${float(inh7):,.2f})" if e7["known"] * sc7 > EPS
                             else " 출금 이관 (원가 미상 승계)")
                          + (f" · {xl6['label']}" if xl6 else ""))
                elif of_cand(r, g, q, ts, exf_dep_tx.get((ex6, r["source_id"])) or r["source_id"]):
                    pass
                elif (not g["is_stable"] and r["posting_id"] in sale_links
                      and sale_book(g, r, q, ts, chain, exf_dep_tx.get((ex6, r["source_id"])) or r["source_id"])):
                    d6 = f"{fx_name.get(ex6, ex6)} 입금 완료 · 토큰 세일 원가 (입찰 지갑에서 직접 입금)"
                elif offc_pk9 is not None and offc_av9 > EPS:
                    exn6 = fx_name.get(ex6, ex6)
                    ref6 = exf_dep_tx.get((ex6, r["source_id"])) or r["source_id"]
                    need6, ck6, kk6, uu6, ckr6 = q, Decimal(0), Decimal(0), Decimal(0), Decimal(0)
                    for l9 in offc_pool.get(offc_pk9, ()):
                        if need6 <= EPS:
                            break
                        if l9["left"] <= EPS or l9["ts"] > ts:
                            continue
                        tk9 = min(need6, l9["left"])
                        l9["left"] -= tk9
                        need6 -= tk9
                        sc9 = tk9 / l9["qty"] if l9["qty"] > 0 else Decimal(1)
                        ck6 += l9["cost"] * sc9
                        ckr6 += l9["cost_krw"] * sc9
                        kk6 += l9["known"] * sc9
                        uu6 += l9["unknown"] * sc9
                    need6 = max(Decimal(0), need6)
                    take6 = q - need6
                    so9 = offc_s(ex6)
                    so9["inhN"] += 1
                    so9["inhQty"] += take6
                    so9["inhUnkQty"] += uu6
                    if need6 > EPS:
                        so9["excessQty"] += need6
                        so9["excessN"] += 1
                    if g["is_stable"]:
                        g["qty_known"] += q
                        g["cost"] += q
                        so9["inhCost"] += take6
                        offc_add(ex6, g["sym"], True, inh=take6)
                        d6 = f"{exn6} 입금 완료 · 내 다른 {exn6} 계정에서 돌아옴(오프체인 · 내 계정으로 가정 · 스테이블 액면)"
                    else:
                        so9["inhCost"] += ck6
                        offc_add(ex6, g["sym"], False, inh=ck6)
                        g["oa"] = (g.get("oa") or Decimal(0)) + kk6
                        g["qty_known"] += kk6
                        g["qty_unknown"] += uu6 + need6
                        g["cost"] += ck6
                        flow6 = flow_of(g, ts, chain)
                        flow6["bought"] += take6
                        flow6["cost"] += ck6
                        flow6["cost_krw"] += ckr6
                        in_note(flow6, f"내 다른 {exn6} 계정", take6, ck6, ts, cost_krw=ckr6)
                        note_unk(g, ts, f"{exn6} 입금 · 내 다른 {exn6} 계정에서 돌아옴(보낼 때부터 원가 미상)", uu6, ref6, ex9=ex6, unc9=Decimal(0),
                                 via9=f"내 다른 {exn6} 계정 이동분(오프체인) — 보낼 때 이 계정에서도 원가 미상이던 몫")
                        note_unk(g, ts, f"{exn6} 입금(오프체인 · 보낸 것보다 많이 돌아옴 — 초과분 원가 없음)", need6, ref6, ex9=ex6, unc9=need6)
                        d6 = (f"{exn6} 입금 완료 · 내 다른 {exn6} 계정에서 돌아옴(오프체인 · 내 계정으로 가정 · 원가 이어받음 ${float(ck6):,.2f})"
                              + (f" · 초과 {_qfmt(need6)}개 원가 미상" if need6 > EPS else ""))
                elif g["is_stable"]:
                    g["qty_known"] += q
                    g["cost"] += q
                    d6 = f"{fx_name.get(ex6, ex6)} 입금 완료 (스테이블 액면)"
                else:
                    g["qty_unknown"] += q
                    note_unk(g, ts, f"{fx_name.get(ex6, ex6)} 입금(원가 없음 · 링크 없음)", q, exf_dep_tx.get((ex6, r["source_id"])) or r["source_id"], ex9=ex6)
                    d6 = f"{fx_name.get(ex6, ex6)} 입금 완료 (원가 미상)"
                if g["is_stable"] or not g["cur"]:
                    extra_ev(ts, g, "입금 확인", d6, qs6, "—", t6 or "—")
                else:
                    ev(g["cur"], ts, "입금 확인", d6, qs6, "—", t6 or "—")
                    if lnk6:
                        g["cur"]["events"][-1]["_lnk"] = lnk6
                continue

            if evk == "TRANSFER_OUT" and lk in ("move_out", "move_in"):
                if loc9.startswith("out:") and lk == "move_in":
                    out_move(r, g, q, ts, chain, txh)
                continue

            if lk in ("move_out", "move_in") and str(evk or "").startswith("LP_"):
                lp_move(r, g, q, ts, lk, chain, txh)
                continue

            if lk in ("move_out", "move_in"):
                qs = f"{-q:,.4f}".rstrip("0").rstrip(".")
                fl_wd9 = None
                wdt9 = None
                if lk == "move_out":
                    if evk == "TRANSFER_OUT_EX" and not ((txh or "").lower() in fx_dep_tx or txh in fx_dep_tx):
                        k2, d2 = "전송", f"{CHAIN_NAME.get(chain, chain)} 지갑 → 업비트 입금 주소"
                        mc2, mk2, mu2 = consume(g, -q)
                        cp_o2 = cp_last[0]
                        kr2 = krw_took(mc2, ts)
                        g["qty_timeline"].append((ts, q))
                        ex_transit.setdefault(txh, []).append(
                            {"gid": g["gid"], "sym": g["sym"], "qty": -q, "cost": mc2, "krw": kr2,
                             "known": mk2, "unknown": mu2 + max(Decimal(0), (-q) - (mk2 + mu2)),
                             "raw_sym": (r["symbol"] or "").upper(),
                             "credited": txh in credited_txh, "used": False, "cyc": g["cur"],
                             "_src": [(r["posting_id"], 1.0)], "_cmp": cp_merge({}, cp_o2)})
                        diag["ex_out_cost"] += mc2
                        diag["ex_out_n"] += 1
                        if g["cur"] is not None:
                            g["cur"]["moved_qty"] += -q
                            g["cur"]["moved_cost"] += mc2
                            mv_note(g["cur"], "업비트", -q)
                        g["last_out"] = {"ex": "upbit", "tx": txh}
                    elif evk == "EXF_WITHDRAW" and offc_self_wd((r["location"] or "").split(":")[-1], r["source_id"]):
                        ex9o = (r["location"] or "").split(":")[-1]
                        exn9o = fx_name.get(ex9o, ex9o)
                        k2 = "전송"
                        d2 = f"{exn9o} 출금 → 내 다른 {exn9o} 계정으로 이동(오프체인 · 내 계정으로 가정 · 원가 이동)"
                        mco, mko, muo = consume(g, -q)
                        mkrwo = krw_last[0] if krw_last[0] is not None else krw_of(mco, ts)
                        g["qty_timeline"].append((ts, q))
                        fl_wd9 = g["cur"]
                        offc_pool.setdefault((ex9o, acct_norm.canon(g["sym"], ex9o)), []).append(
                            {"ts": int(ts), "qty": -q, "left": -q, "cost": mco, "cost_krw": mkrwo, "known": mko,
                             "unknown": muo + max(Decimal(0), (-q) - (mko + muo)), "gid": g["gid"], "sym": g["sym"]})
                        so9 = offc_s(ex9o)
                        so9["wdN"] += 1
                        so9["wdCost"] += mco
                        so9["wdUnkQty"] += (-q) - mko
                        so9["syms"].add(g["sym"])
                        offc_add(ex9o, g["sym"], g["is_stable"], wd=mco)
                        offc_addr_add(ex9o, r["source_id"], mco)
                        if g["cur"] is not None:
                            g["cur"]["moved_qty"] += -q
                            g["cur"]["moved_cost"] += mco
                            mv_note(g["cur"], f"내 다른 {exn9o} 계정", -q)
                            if g["qty_known"] + g["qty_unknown"] <= Decimal("0.000001"):
                                g["cur"] = None
                    elif evk in ("EXF_WITHDRAW", "EX_WITHDRAW"):
                        ex9w = (r["location"] or "").split(":")[-1]
                        k2 = "전송"
                        t4 = fx_uid_tx.get(r["source_id"])
                        if ex9w == "upbit":
                            ub_wd_shown.add(r["source_id"])
                        sw9 = swap_dep.pop(t4, None) if (ex9w == "upbit" and t4 and t4.startswith("swap_")) else None
                        dst9 = ("업비트 입금" if t4 in up_dep_by_tx and ex9w != "upbit"
                                else f"{fx_name.get(fx_dep_tx[t4], fx_dep_tx[t4])} 입금"
                                if t4 in fx_dep_tx and fx_dep_tx[t4] != ex9w
                                else f"내 지갑 ({CHAIN_NAME.get(arr_tx_chain[t4], arr_tx_chain[t4])})" if t4 in arr_tx_chain
                                else "온체인") if t4 else ""
                        d2 = (f"{fx_name.get(ex9w, ex9w)} 토큰 전환 출금 ({g['sym']} → {sw9['g']['sym']} · 원가 이동)" if sw9
                              else f"{fx_name.get(ex9w, ex9w)} 출금 → {dst9} (원가 이동)" if t4
                              else f"{fx_name.get(ex9w, ex9w)} 출금 (txid 없음 · 원가 소실)")
                        mc4, mk4, mu4 = consume(g, -q)
                        cp_o4 = cp_last[0]
                        kr4 = krw_took(mc4, ts)
                        oa4 = oa_last[0]
                        g["qty_timeline"].append((ts, q))
                        if evk == "EXF_WITHDRAW" and (ex9w, r["source_id"]) in offc_wd:
                            so9 = offc_s(ex9w)
                            so9["wdN"] += 1
                            so9["wdCost"] += mc4
                            so9["wdUnkQty"] += (-q) - mk4
                            so9["syms"].add(g["sym"])
                            offc_add(ex9w, g["sym"], g["is_stable"], wd=mc4)
                            offc_addr_add(ex9w, r["source_id"], mc4)
                        fl_wd9 = g["cur"]
                        if not sw9 and not g.get("is_fiat") and -q > 0:
                            wdt9 = {"gid": g["gid"], "sym": g["sym"], "qty": -q, "ts": int(ts), "ex": ex9w, "uuid": r["source_id"],
                                    "txid": t4, "cost": mc4, "known": mk4, "cyc": g["cur"], "stable": bool(g["is_stable"]), "ev": None,
                                    "held": mk4 + mu4}
                            wd_tr.append(wdt9)
                        if g["cur"] is not None:
                            g["cur"]["moved_qty"] += -q
                            g["cur"]["moved_cost"] += mc4
                            if sw9:
                                mv_note(g["cur"], f"{sw9['g']['sym']} 전환", -q)
                            elif t4 and t4 in arr_tx_chain and dst9.startswith("내 지갑"):
                                mv_note(g["cur"], f"{CHAIN_NAME.get(arr_tx_chain[t4], arr_tx_chain[t4])} 지갑", -q)
                            elif t4 and dst9.endswith(" 입금"):
                                mv_note(g["cur"], dst9[:-3], -q)
                            elif t4:
                                mv_note(g["cur"], "온체인 주소", -q, own=False)
                        if sw9:
                            g2, q2 = sw9["g"], sw9["q"]
                            kf9 = (mk4 / (-q)) if -q > 0 else Decimal(0)
                            want9 = q2 * min(kf9, Decimal(1))
                            mv9 = min(want9, g2["qty_unknown"])
                            c9 = mc4 * (mv9 / want9) if want9 > 0 else Decimal(0)
                            if mv9 > 0:
                                g2["qty_unknown"] -= mv9
                                g2["qty_known"] += mv9
                                g2["cost"] += c9
                                fl9 = flow_of(g2, ts, chain)
                                fl9["bought"] += mv9
                                fl9["cost"] += c9
                                fl9["cost_krw"] += kr4 * c9 / mc4 if mc4 > 0 else krw_of(c9, ts)
                                if sw9.get("ent") is not None:
                                    sw9["ent"]["qty"] = max(0.0, sw9["ent"]["qty"] - float(mv9))
                            t4 = None
                        if t4:
                            e4 = fx_transit.setdefault(
                                t4, {"qty": Decimal(0), "cost": Decimal(0),
                                     "known": Decimal(0), "unknown": Decimal(0),
                                     "left": Decimal(0), "ex": ex9w,
                                     "sym": g["sym"], "gid": g["gid"]})
                            if e4.get("sym") != g["sym"] or e4.get("ex") != ex9w:
                                e4["ambiguous"] = True
                            e4["qty"] += -q
                            e4["left"] += -q
                            e4.setdefault("_src", []).append((r["posting_id"], 1.0))
                            e4["_cmp"] = cp_merge(e4.get("_cmp") or {}, cp_o4)
                            e4["cost"] += mc4
                            e4["krw"] = e4.get("krw", Decimal(0)) + kr4
                            e4["known"] += mk4
                            if oa4 > 0:
                                e4["oa"] = e4.get("oa", Decimal(0)) + oa4
                            e4["unknown"] += mu4 + max(Decimal(0), (-q) - (mk4 + mu4))
                            if g["cur"] is not None:
                                evs4w = g["cur"]["events"]
                                k4w, n4w = sell_pre(g["cur"], evs4w)
                                hd4w, tl4w = evs4w[:k4w], evs4w[k4w + n4w:]
                                mv4 = [e9 for e9 in hd4w if "매도" not in str(e9.get("k") or "")] + [e9 for e9 in tl4w if "매도" not in str(e9.get("k") or "")]
                                if mv4:
                                    for e9 in mv4:
                                        e9.setdefault("_mv", r["posting_id"])
                                    e4.setdefault("story", []).extend(mv4)
                                    e4["story_flow"] = g["cur"]
                                    g["cur"]["events"] = ([e9 for e9 in hd4w if "매도" in str(e9.get("k") or "")] + evs4w[k4w:k4w + n4w]
                                                          + [e9 for e9 in tl4w if "매도" in str(e9.get("k") or "")])
                                sell_mark(g["cur"])
                                if g["qty_known"] + g["qty_unknown"] <= Decimal("0.000001"):
                                    g["cur"] = None
                    elif evk in ("BRIDGE", "TRANSFER_OUT_EX") and \
                            ((txh or "").lower() in fx_dep_tx or txh in fx_dep_tx):
                        ex5 = fx_dep_tx.get((txh or "").lower()) or fx_dep_tx.get(txh)
                        k2 = "전송"
                        d2 = f"{CHAIN_NAME.get(chain, chain)} 지갑 → {fx_name.get(ex5, ex5)} 입금 주소"
                        mc5, mk5, mu5 = consume(g, -q)
                        cp_o5 = cp_last[0]
                        kr5 = krw_took(mc5, ts)
                        g["qty_timeline"].append((ts, q))
                        t5 = (txh or "").lower() if (txh or "").startswith("0x") else txh
                        e5 = fxdep_transit.setdefault(
                            (t5, g["sym"]), {"qty": Decimal(0), "cost": Decimal(0),
                                             "known": Decimal(0), "unknown": Decimal(0),
                                             "left": Decimal(0), "gid": g["gid"], "sym": g["sym"], "ex": ex5})
                        e5["qty"] += -q
                        e5["left"] += -q
                        e5.setdefault("_src", []).append((r["posting_id"], 1.0))
                        e5["_cmp"] = cp_merge(e5.get("_cmp") or {}, cp_o5)
                        e5["cost"] += mc5
                        e5["krw"] = e5.get("krw", Decimal(0)) + kr5
                        e5["known"] += mk5
                        e5["unknown"] += mu5 + max(Decimal(0), (-q) - (mk5 + mu5))
                        g["last_out"] = {"ex": ex5, "tx": txh}
                        if g["cur"] is not None and not g["is_stable"]:
                            e5.setdefault("cycs", []).append((g["cur"], -q, mc5))
                            g["cur"]["moved_qty"] += -q
                            g["cur"]["moved_cost"] += mc5
                            mv_note(g["cur"], fx_name.get(ex5, ex5), -q)
                    elif evk == "BRIDGE":
                        k2, d2 = "전송", f"{CHAIN_NAME.get(chain, chain)} → 브릿지 · 위치 이동(손익 없음)"
                        mc3, mk3, mu3 = consume(g, -q)
                        cp_o3 = cp_last[0]
                        g["qty_timeline"].append((ts, q))
                        bridge_outs.append({"sym": g["sym"], "qty": -q, "ts": ts, "_src": [(r["posting_id"], 1.0)], "_cmp": cp_merge({}, cp_o3),
                                            "cost": mc3, "known": mk3,
                                            "unknown": mu3 + max(Decimal(0), (-q) - (mk3 + mu3)),
                                            "left": -q,
                                            "gid": r["group_id"] or -r["asset_id"], "chain": chain})
                    elif evk == "TRANSFER_SELF":
                        k2, d2 = "전송", f"{CHAIN_NAME.get(chain, chain)} · 내 지갑 간 이동 (±0 · 손익 없음)"
                    elif evk == "CONVERT":
                        k2, d2 = "전송", f"{CHAIN_NAME.get(chain, chain)} · 랩/언랩 전환 (평단 불변)"
                    else:
                        k2, d2 = None, None
                    if k2:
                        fl_ev9 = g["cur"] or fl_wd9
                        if g["is_stable"] or not fl_ev9:
                            extra_ev(ts, g, k2, d2, qs, "—", txh)
                            if wdt9 is not None and extra_events:
                                wdt9["ev"] = extra_events[-1]
                        else:
                            ev(fl_ev9, ts, k2, d2, qs, "—", txh)
                            if wdt9 is not None and fl_ev9["events"]:
                                wdt9["ev"] = fl_ev9["events"][-1]
                continue

            if lk == "opening":
                back_o = q < 0 and (r["source_ns"] or "") != "upbit:recon_comp"
                xk9 = exf_kind(r)
                late9 = evk == "EXF_ADJUST" and str(r["source_id"] or "").startswith("exflate:")
                if xk9 == "fix" or late9:
                    back_o = False
                try:
                    rb9 = int(str(r["source_id"]).rsplit(":", 1)[1])
                except (IndexError, ValueError):
                    rb9 = ts
                at9 = "대사 시각" if ts >= rb9 - 60 else ("원장이 처음 모자란 때로 당김" if q > 0 else "잔고가 남던 구간 시작으로 당김")
                hl9 = xk9 == "fix" and (r["source_ns"] or "") == "hyperliquid:recon" and (r["symbol"] or "").upper() in _hl_cash_syms()
                hl_lab9 = "Hyperliquid 무기한 손익·펀딩 정산 (그 대사 구간 합 — 대사 시각)"
                g["qty_timeline"].append((min(ts, backfill_t0) if back_o else ts, q))
                if q > 0:
                    if g["is_stable"]:
                        g["qty_known"] += q
                        g["cost"] += q
                    else:
                        g["qty_unknown"] += q
                        if late9:
                            note_unk(g, ts, "늦게 찾은 과거 체결 상쇄 유입(원가 없음)", q, "", chain9=chain)
                        elif evk in ("EXF_ADJUST", "EX_ADJUST"):
                            note_unk(g, ts, "거래소 잔고 정정 유입(원가 없음)", q, "", chain9=chain)
                        elif ":stake:" in (r["location"] or ""):
                            note_unk(g, ts, "솔라나 스테이킹 기초 잔고 · 수집 시작 이전 위임분(원가 없음)", q, "", chain9=chain)
                        else:
                            note_unk(g, ts, (f"{CHAIN_NAME.get(chain, chain)} " if chain and chain != "?" else "") + "기초 잔고 · 수집 시작 이전 보유분(원가 없음)", q, "", chain9=chain)
                    if late9:
                        extra_ev(ts, g, "전송", f"{cur_lab[0] or CHAIN_NAME.get(chain, chain)} · {StateBuilder.LATE_OFFSET_KO}",
                                 _recon_q(q), "—", txh, vq=q)
                    elif xk9 == "fix" or (xk9 == "init" and ts > backfill_t0 + 86400):
                        lab9 = ("원화 정산 · 체결 원화 순지출(예수금에서 나감)·코인 모으기·은행 입금 (원화는 원장 밖 — 예수금은 따로 표시)"
                                if g.get("is_fiat") else hl_lab9 if hl9 else
                                f"잔고 정정 · 수집 누락 추정 (원인 모름 — 수집 밖 유입, 예: 이자·내부 이체 · {at9})")
                        extra_ev(ts, g, "전송", f"{cur_lab[0] or CHAIN_NAME.get(chain, chain)} · {lab9}",
                                 _recon_q(q), "—", txh, vq=q)
                    else:
                        extra_ev(ts, g, "전송", f"{cur_lab[0] or CHAIN_NAME.get(chain, chain)} · 기초 잔고 (백필 창 이전 보유분)",
                                 _recon_q(q), "—", txh, vq=q)
                else:
                    consume(g, -q, cp=False)
                    if late9:
                        extra_ev(ts, g, "전송", f"{cur_lab[0] or CHAIN_NAME.get(chain, chain)} · {StateBuilder.LATE_OFFSET_KO}",
                                 _recon_q(q), "—", txh, vq=q)
                    elif xk9 == "fix":
                        db9 = (ex_debt9.get(r["source_ns"]) or {}).get((r["symbol"] or "").upper())
                        ln9 = (ex_loan9.get(r["source_ns"]) or {}).get((r["symbol"] or "").upper())
                        try:
                            rb9 = int(str(r["source_id"]).rsplit(":", 1)[1])
                        except (IndexError, ValueError):
                            rb9 = ts
                        if common.exf_is_debt_int(evk, r["leg_seq"], r["source_ns"], r["source_id"]):
                            lab9 = f"{ln9 + ' 이자' if ln9 else '마진 차입 이자'} · 부채 이자 누적 {_recon_q(-q)} (비용 — 총자산에서 뺌, 대사 시각)"
                        elif db9 is not None and -db9 * Decimal("0.5") <= -q <= -db9 * Decimal("1.01") + EPS:
                            if ts < rb9 - 60:
                                lab9 = f"기존 부채 첫 반영 · {ln9 or '마진 차입'} {_recon_q(-q)} — 이때부터 보유 (총자산에서 뺌)"
                            else:
                                lab9 = f"{ln9 + ' 부채' if ln9 else '마진 부채'} 반영 · 차입 {_recon_q(-q)} 차감 (총자산에서 뺌 — 대사 시각)"
                        elif g.get("is_fiat"):
                            lab9 = "원화 잔고 정정(감소) · 수집 밖 출금·결제 추정 (대사 시각)"
                        elif hl9:
                            lab9 = hl_lab9
                        else:
                            lab9 = f"잔고 정정(감소) · 원인 모름 — 수집 밖 이동 추정 (예: 예치·내부 이체 · {at9})"
                        extra_ev(ts, g, "전송", f"{cur_lab[0] or CHAIN_NAME.get(chain, chain)} · {lab9}",
                                 _recon_q(q), "—", txh, vq=q)
                    elif str(r["location"] or "").startswith("exchange:") and (r["source_ns"] or "") != "upbit:recon_comp":
                        extra_ev(ts, g, "전송", f"{cur_lab[0] or CHAIN_NAME.get(chain, chain)} · 잔고 정정(감소) · 원장에만 있던 수량 제거"
                                 " (수집 밖 유출·예치 추정 — 과거 창 정착)", _recon_q(q), "—", txh, vq=q)
                continue

            if lk == "acq" and evk == "STAKE_REWARD":
                g["qty_timeline"].append((ts, q))
                st9 = stake_rwd.setdefault(r["location"] or "", [Decimal(0), Decimal(0)])
                st9[0] += q
                if cost is not None:
                    g["qty_known"] += q
                    g["cost"] += cost
                    st9[1] += cost
                    dk9s = acct_norm.iso_day(ts)
                    rt9s = fxb.rate_at(ts)
                    realized_by_date[dk9s] = realized_by_date.get(dk9s, 0) + float(cost)
                    realized_krw_by_date[dk9s] = realized_krw_by_date.get(dk9s, 0) + float(cost) * rt9s
                    si9 = stake_inc.setdefault(dk9s, {}).setdefault(g["sym"], [Decimal(0), Decimal(0), 0, 0.0])
                    si9[0] += cost; si9[1] += q; si9[2] += 1; si9[3] += float(cost) * rt9s
                else:
                    g["qty_unknown"] += q
                    note_unk(g, ts, "솔라나 스테이킹 보상 · 시가 대기(원가 없음)", q, txh, chain9=chain)
                mev9 = not (r["source_id"] or "").startswith("stakerwd:")
                ep9 = "" if mev9 else (r["source_id"] or "").rsplit(":", 1)[-1]
                extra_ev(ts, g, "전송", f"{CHAIN_NAME.get(chain, chain)} · 스테이킹 보상"
                         + (f" (에폭 {ep9})" if ep9 else " (MEV 팁)"),
                         f"{q:,.6f}".rstrip("0").rstrip("."), f"${float(cost):,.2f}" if cost is not None else "—",
                         txh if mev9 else "")
                continue

            if lk == "acq":
                flow = flow_of(g, ts, chain)
                g["qty_timeline"].append((ts, q))
                rd9 = redeem_tx.get((r["source_ns"], txh))
                if rd9 and rd9["acq"] == r["posting_id"] and rd9["carry"] is not None:
                    mc9, mk9, mu9 = rd9["carry"]
                    k9 = min(q, mk9 * rd9["ratio"])
                    u9 = q - k9
                    g["qty_known"] += k9
                    g["qty_unknown"] += u9
                    g["cost"] += mc9
                    if u9 > EPS:
                        note_unk(g, ts, "세일 영수증 교환 · 승계(원가 없음)", u9, txh, chain9=chain)
                    g["risk_allow"] = True
                    flow["bought"] += k9
                    flow["cost"] += mc9
                    flow["cost_krw"] += rd9["carry_krw"] if rd9.get("carry_krw") is not None else krw_of(mc9, ts)
                    ev(flow, ts, "전송", f"{CHAIN_NAME.get(chain, chain)} · 세일 영수증 → {g['sym']} 교환 · 원가 승계 (${float(mc9):,.2f})",
                       f"{q:,.4f}".rstrip("0").rstrip("."), "—", txh)
                    continue
                xc9 = xc_transit.get(r["posting_id"]) if cost is None and not g["is_stable"] and evk in ("TRANSFER_IN", "PROGRAM_IN") else None
                if xc9 and xc9["qty"] > 0:
                    sc9 = q / xc9["qty"]
                    cov9 = min(q, xc9["cov"] * sc9)
                    inh9 = xc9["cost"] * sc9
                    g["qty_known"] += cov9
                    g["qty_unknown"] += q - cov9
                    if q - cov9 > 0:
                        note_unk(g, ts, f"{xc9['label']} · 일부 원가 미상", q - cov9, txh, chain9=chain)
                    g["cost"] += inh9
                    g["risk_allow"] = True
                    flow["bought"] += cov9
                    flow["cost"] += inh9
                    flow["cost_krw"] += krw_of(inh9, ts)
                    diag["xc_inh_n"] += 1
                    diag["xc_inh_cost"] += inh9
                    cp_xc(g, r, xc9, cov9, inh9, chain, ts)
                    xc_used[r["posting_id"]] = {"tx": txh, "chain": chain, "sym": g["sym"], "qty": float(q), "cov": float(cov9),
                                                "cost": round(float(inh9), 2), "label": xc9["label"], "via": xc9["via"], "ts": int(ts)}
                    ev(flow, ts, "전송", f"{xc9['label']} · 원가 이관 (${float(inh9):,.2f})",
                       f"{q:,.4f}".rstrip("0").rstrip("."), "—", txh)
                    continue
                if cost is None:
                    linked = None
                    take = Decimal(0)
                    rk9 = rt_pair.get((r["source_ns"], txh)) if (evk == "PROGRAM_IN" and not g["is_stable"]) else None
                    rt9 = rt_transit.get((rk9[0], rk9[1], g["gid"])) if rk9 else None
                    if rt9 and rt9["left"] > 0 and q <= rt9["left"] * Decimal("1.005"):
                        take9 = min(q, rt9["left"])
                        rt9["left"] -= take9
                        sc9 = take9 / rt9["qty"] if rt9["qty"] > 0 else Decimal(1)
                        inh9 = rt9["cost"] * sc9
                        g["qty_known"] += rt9["known"] * sc9
                        cp_add_map(g, rt9.get("_cmp"), sc9)
                        g["qty_unknown"] += rt9["unknown"] * sc9 + (q - take9)
                        note_unk(g, ts, "프로그램 예치 복귀 · 승계(원가 없음)", rt9["unknown"] * sc9 + (q - take9), txh, chain9=chain, unc9=q - take9)
                        g["cost"] += inh9
                        g["risk_allow"] = True
                        flow["bought"] += take9
                        flow["cost"] += inh9
                        flow["cost_krw"] += krw_inh(rt9, inh9, ts)
                        ev(flow, ts, "전송", f"{CHAIN_NAME.get(chain, chain)} 프로그램 예치 복귀 · 원가 복원 (${float(inh9):,.2f})",
                           f"{q:,.4f}".rstrip("0").rstrip("."), "—", txh)
                        flow["events"][-1]["_lnk"] = [(sp9, float(sc9) * w9) for sp9, w9 in rt9.get("_src", ())]
                        continue
                    if not g["is_stable"] and evk in ("TRANSFER_IN", "PROGRAM_IN"):
                        arr_gid = r["group_id"] or -r["asset_id"]
                        bt9 = br_transit.get(r["posting_id"])
                        if bt9 and bt9["left"] > 0:
                            linked, take = bt9, min(q, bt9["left"])
                            diag["of_bridge_inh_n"] += 1
                            diag["of_bridge_inh_cost"] += bt9["cost"] * (take / bt9["qty"] if bt9["qty"] > 0 else Decimal(1))
                        for b in (() if linked else bridge_outs):
                            if (b["sym"] == g["sym"] and b.get("left", Decimal(0)) > 0
                                    and b["ts"] - 600 <= ts <= b["ts"] + 21600
                                    and b.get("chain") != chain
                                    and q <= b["left"] * Decimal("1.02")):
                                linked = b
                                take = min(q, b["left"])
                                break
                    if g["is_stable"] and evk in ("TRANSFER_IN", "PROGRAM_IN"):
                        e4s = fx_transit.get(txh) or fx_transit.get((txh or "").lower())
                        if e4s and (e4s.get("ambiguous") or not (G.get(e4s.get("gid")) or {}).get("is_stable")
                                    or (len(arr_groups.get((r["source_ns"], txh), ())) > 1 and e4s.get("sym") != g["sym"])):
                            e4s = None
                        if e4s and e4s["left"] > 0 and q <= e4s["left"] * Decimal("1.02"):
                            g["risk_allow"] = True
                            take4 = min(q, e4s["left"])
                            e4s["left"] -= take4
                            sc4 = take4 / e4s["qty"] if e4s["qty"] > 0 else Decimal(1)
                            inh_c4 = e4s["cost"] * sc4
                            kq4 = min(take4, e4s["known"] * sc4)
                            if e4s.get("oa"):
                                g["oa"] = (g.get("oa") or Decimal(0)) + e4s["oa"] * sc4
                            g["qty_known"] += q
                            g["cost"] += inh_c4 + (q - kq4)
                            diag["st_wd_inh_n"] = diag.get("st_wd_inh_n", 0) + 1
                            diag["st_wd_inh_gap"] = diag.get("st_wd_inh_gap", Decimal(0)) + (inh_c4 - kq4)
                            extra_ev(ts, g, "전송", f"{fx_name.get(e4s['ex'], e4s['ex'])} 출금 도착 · {CHAIN_NAME.get(chain, chain)} · 원가 승계"
                                     f" (${float(inh_c4 + (q - kq4)):,.2f})", f"{q:,.4f}".rstrip("0").rstrip("."), "—", txh)
                            continue
                    if not g["is_stable"] and evk in ("TRANSFER_IN", "PROGRAM_IN"):
                        e4 = fx_transit.get(txh) or fx_transit.get((txh or "").lower())
                        if e4 and (e4.get("ambiguous")
                                   or (len(arr_groups.get((r["source_ns"], txh), ())) > 1
                                       and e4.get("sym") != g["sym"])):
                            e4 = None
                        if e4 and e4["left"] > 0 and q <= e4["left"] * Decimal("1.02"):
                            g["risk_allow"] = True
                            take4 = min(q, e4["left"])
                            e4["left"] -= take4
                            sc4 = take4 / e4["qty"] if e4["qty"] > 0 else Decimal(1)
                            inh_c4 = e4["cost"] * sc4
                            if e4.get("oa"):
                                g["oa"] = (g.get("oa") or Decimal(0)) + e4["oa"] * sc4
                            g["qty_known"] += e4["known"] * sc4
                            cp_add_map(g, e4.get("_cmp"), sc4)
                            g["qty_unknown"] += e4["unknown"] * sc4 + (q - take4)
                            note_unk(g, ts, "거래소 출금 도착 · 승계(원가 없음)", e4["unknown"] * sc4 + (q - take4), txh, chain9=chain, up_gid=e4.get("gid"), unc9=q - take4)
                            g["cost"] += inh_c4
                            flow = flow_of(g, ts, chain)
                            flow["bought"] += take4
                            flow["cost"] += inh_c4
                            ikr4 = krw_inh(e4, inh_c4, ts)
                            flow["cost_krw"] += ikr4
                            st4 = e4.pop("story", None)
                            if st4:
                                flow["events"][:0] = st4
                            in_note(flow, fx_name.get(e4["ex"], e4["ex"]), take4, inh_c4, ts, st4, cost_krw=ikr4)
                            ev(flow, ts, "전송",
                               f"{fx_name.get(e4['ex'], e4['ex'])} 출금 도착 ·"
                               f" {CHAIN_NAME.get(chain, chain)} · 원가 승계"
                               f" (${float(inh_c4):,.2f})",
                               f"{q:,.4f}".rstrip("0").rstrip("."), "—", txh)
                            flow["events"][-1]["_lnk"] = [(sp9, float(sc4) * w9) for sp9, w9 in e4.get("_src", ())]
                            continue
                    if linked:
                        if linked.get("gid") == arr_gid:
                            g["risk_allow"] = True
                        else:
                            g["risk_allow_bridge"] = True
                        linked["left"] -= take
                        scale = take / linked["qty"] if linked["qty"] > 0 else Decimal(1)
                        inh_cost = linked["cost"] * scale
                        g["qty_known"] += linked.get("known", linked["qty"]) * scale
                        cv9 = linked.get("_cv")
                        if cv9 and linked.get("_cmp"):
                            cvk9 = ("cv", r["posting_id"], g["gid"])
                            cp_add(g, cvk9, sum(v9[0] for v9 in linked["_cmp"].values()) * cv9["ratio"] * float(scale),
                                   sum(v9[1] for v9 in linked["_cmp"].values()) * float(scale))
                        else:
                            cp_add_map(g, linked.get("_cmp"), scale)
                        g["qty_unknown"] += linked.get("unknown", Decimal(0)) * scale + (q - take)
                        note_unk(g, ts, "브릿지 도착 · 승계(원가 없음)", linked.get("unknown", Decimal(0)) * scale + (q - take), txh, chain9=chain, up_gid=linked.get("gid"))
                        g["cost"] += inh_cost
                        flow = flow_of(g, ts, chain)
                        ev(flow, ts, "전송",
                           f"{CHAIN_NAME.get(chain, chain)} 브릿지 도착 · 원가 이관"
                           f" (${float(inh_cost):,.2f})",
                           f"{q:,.4f}".rstrip("0").rstrip("."), "—", txh)
                        flow["events"][-1]["_lnk"] = [(sp9, float(scale) * w9) for sp9, w9 in linked.get("_src", ())]
                        if cv9 and linked.get("_cmp"):
                            flow["events"][-1]["_cv"] = cv9
                            cp_ev[cvk9] = flow["events"][-1]
                        continue
                    if evk in ("TRANSFER_IN", "PROGRAM_IN"):
                        of_cand(r, g, q, ts, txh, own9=bool(fx_wd.get(txh) or fx_wd.get((txh or "").lower())
                                                            or txh in ub_wd_tx or (txh or "").lower() in ub_wd_tx))
                    if (not g["is_stable"] and evk in ("TRANSFER_IN", "PROGRAM_IN") and r["posting_id"] in sale_links
                            and sale_book(g, r, q, ts, chain, txh)):
                        continue
                    if g["is_stable"]:
                        g["qty_known"] += q
                        g["cost"] += q
                    else:
                        g["qty_unknown"] += q
                        note_unk(g, ts, f"{CHAIN_NAME.get(chain, chain)} 브릿지/유입(원가 없음 · 링크 없음)", q, r["source_id"], chain9=chain)
                    if evk in ("TRANSFER_IN", "PROGRAM_IN"):
                        qs2 = f"{q:,.4f}".rstrip("0").rstrip(".")
                        src_ex = fx_wd.get(txh) or fx_wd.get((txh or "").lower())
                        if src_ex:
                            d3 = f"{src_ex} 출금 유입 · {CHAIN_NAME.get(chain, chain)} (원가 연결 대기)"
                            g.setdefault("origin_ex", set()).add(src_ex)
                            g["risk_allow"] = True
                        elif txh in ub_wd_tx or (txh or "").lower() in ub_wd_tx:
                            g["risk_allow"] = True
                            d3 = f"{CHAIN_NAME.get(chain, chain)} 외부 유입 (원가 미상)"
                        else:
                            near_bo = any(t9b - 600 <= ts <= t9b + 21600
                                          for t9b in bridge_dep_ts.get(g["sym"], ()))
                            td9 = to_dest9.get((g["sym"] or "").upper())
                            tls9 = (td9 or {}).get("ts_list") or []
                            near_to = bool(td9) and (
                                bool(td9.get("no_ts")) or not tls9
                                or any(t9c - 600 <= ts <= t9c + 21600 for t9c in tls9))
                            if not (near_bo or near_to):
                                s9a = signer9.get((r["source_ns"], txh))
                                if s9a and spamguard.signer_mine(*s9a, my_all9):
                                    g["risk_airdrop_signed"] = g.get("risk_airdrop_signed", 0) + 1
                                else:
                                    g["risk_airdrop"] = True
                            d3 = (f"{CHAIN_NAME.get(chain, chain)} 프로그램 경유 수령 (체결/에어드랍 검토)"
                                  if evk == "PROGRAM_IN"
                                  else f"{CHAIN_NAME.get(chain, chain)} 외부 유입 (원가 미상)")
                        if g["is_stable"]:
                            extra_ev(ts, g, "전송", d3, qs2, "—", txh)
                        else:
                            ev(flow, ts, "전송", d3, qs2, "—", txh)
                    else:
                        g["qty_known"] += 0
                        ev(flow, ts, "온체인 매수",
                           f"{CHAIN_NAME.get(chain, chain)} · 스왑 (원가 산정 중)",
                           f"{q:,.4f}".rstrip("0").rstrip("."), "—", txh)
                else:
                    g["qty_known"] += q
                    g["cost"] += cost
                    flow["bought"] += q
                    flow["cost"] += cost
                    flow["cost_krw"] += krw_of(cost, ts, r)
                    if (r["source_ns"], r["source_id"]) in krw_mkt:
                        flow["kmc"] = flow.get("kmc", Decimal(0)) + cost
                    sg9 = swap_gas.get((r["source_ns"], txh)) if (gas_on and evk == "SWAP") else None
                    if sg9 and not sg9["done"] and sg9["sell"] is None and sg9["buy"] == g["gid"] and sg9["usd"] > 0:
                        sg9["done"] = True
                        g["cost"] += sg9["usd"]
                        flow["cost"] += sg9["usd"]
                        flow["cost_krw"] += krw_of(sg9["usd"], ts, r)
                        gas_applied["buy"] += sg9["usd"]
                        gas_applied["n"] += 1
                    if evk == "EX_BUY":
                        ex_fee9 = up_fee.get(r["source_id"])
                        if ex_fee9 and r["source_ns"] == "upbit:order" and int(r["leg_seq"] or 0) == 0:
                            ex_fee_add("upbit", cost * ex_fee9[1] / (ex_fee9[0] + ex_fee9[1]), ts)
                        ev(flow, ts, "거래소 매수", f"업비트 · {up_mkt.get(r['source_id'], 'KRW')} 마켓 체결",
                           f"{q:,.4f}".rstrip("0").rstrip("."), f"${float(cost):,.2f}", txh, un=_un(q, cost))
                    elif evk == "EXF_BUY":
                        fee_acq[(r["source_ns"], txh)] = {"g": g, "gid": g["gid"], "flow": flow, "row": r, "qty": q, "usd": cost}
                        ex9 = (r["location"] or "").split(":")[-1]
                        ev(flow, ts, "거래소 매수",
                           f"{fx_name.get(ex9, ex9)} · 현물 체결",
                           f"{q:,.4f}".rstrip("0").rstrip("."), f"${float(cost):,.2f}", txh, un=_un(q, cost))
                    else:
                        pay9 = [p9 for p9 in (swap_pay.get((r["source_ns"], txh)) or []) if p9[1] > 0] if evk == "SWAP" else []
                        ev(flow, ts, "온체인 매수", f"{CHAIN_NAME.get(chain, chain)} · 스왑"
                           + ((" · 지불 " + " + ".join(f"{_qfmt(p9[1])} {p9[0]}" for p9 in pay9[:3]) + (f" 외 {len(pay9) - 3}" if len(pay9) > 3 else ""))
                              if pay9 else ""),
                           f"{q:,.4f}".rstrip("0").rstrip("."), f"${float(cost):,.2f}", txh, un=_un(q, cost))
                continue

            if lk == "disp":
                qty = -q
                g["qty_timeline"].append((ts, q))
                if g.get("is_fiat"):
                    consume(g, qty, cp=False)
                    if evk == "EXF_SELL":
                        fee_disp[(r["source_ns"], txh)] = {"g": g, "gid": g["gid"], "qty": qty, "usd": cost, "fiat": True}
                    continue
                rd9 = redeem_tx.get((r["source_ns"], txh))
                if rd9 and rd9["disp"] == r["posting_id"]:
                    mc9, mk9, mu9 = consume(g, qty)
                    rd9["carry"] = (mc9, mk9, mu9 + max(Decimal(0), qty - (mk9 + mu9)))
                    rd9["carry_krw"] = krw_took(mc9, ts)
                    flow = g["cur"] or flow_of(g, ts, chain)
                    ev(flow, ts, "전송", f"{CHAIN_NAME.get(chain, chain)} · 세일 영수증 교환 → 본 토큰 · 원가 이관 (${float(mc9):,.2f})",
                       f"{qty:,.4f}".rstrip("0").rstrip("."), "—", txh)
                    if g["qty_known"] + g["qty_unknown"] <= Decimal("0.000001"):
                        g["cur"] = None
                    continue
                flow = g["cur"] or flow_of(g, ts, chain)
                is_pay9 = r["posting_id"] in pay_pid
                if is_pay9:
                    flow["paid"] = flow.get("paid", Decimal(0)) + qty
                else:
                    flow["sold"] += qty
                if evk in ("EX_SELL", "EXF_SELL"):
                    short = qty - (g["qty_known"] + g["qty_unknown"])
                    if short > EPS:
                        p9s = (r["location"] or "").split(":")
                        sell_ex9 = p9s[1] if evk == "EXF_SELL" and len(p9s) > 1 else "upbit"
                        donors = [g2 for gid2, g2 in G.items()
                                  if gid2 != g["gid"] and g2["sym"] == g["sym"]
                                  and not g2["is_stable"]
                                  and sell_ex9 in (g2.get("ex_dep") or set())
                                  and g2["qty_known"] + g2["qty_unknown"] > EPS]
                        if len(donors) == 1:
                            dn = donors[0]
                            take9 = min(short, dn["qty_known"] + dn["qty_unknown"])
                            bc, bk, bu = consume(dn, take9)
                            cp_dn9 = cp_last[0]
                            dn["qty_timeline"].append((ts, -take9))
                            if dn["qty_known"] + dn["qty_unknown"] <= Decimal("0.000001"):
                                dn["cur"] = None
                            g["qty_known"] += bk
                            cp_add_map(g, cp_dn9, 1.0)
                            g["qty_unknown"] += bu
                            note_unk(g, ts, "동일 심볼 원장 정정 · 기증자 승계(원가 없음)", bu, txh, chain9=chain, up_gid=dn.get("gid"))
                            g["cost"] += bc
                            ev(flow, ts, "전송",
                               "동일 심볼 원장 정정 · 브릿지 인스턴스에서 원가 이관"
                               f" (${float(bc):,.2f})",
                               f"{take9:,.4f}".rstrip("0").rstrip("."), "—", txh)
                from_known = min(qty, g["qty_known"])
                from_unknown = qty - from_known
                wac = (g["cost"] / g["qty_known"]) if g["qty_known"] > EPS else Decimal(0)
                consumed_cost = wac * from_known
                consumed_cost_krw = consume_krw(g, consumed_cost)
                oa9 = oa_take(g, from_known)
                cmp9s = cp_emit(cp_take(g, from_known, consumed_cost), from_unknown, qty, consumed_cost)
                g["qty_known"] -= from_known
                g["cost"] -= consumed_cost
                g["qty_unknown"] = max(Decimal(0), g["qty_unknown"] - from_unknown)
                if cost is not None:
                    is_ex = evk in ("EX_SELL", "EXF_SELL")
                    ex_label = "업비트"
                    if evk == "EXF_SELL":
                        ex9s = (r["location"] or "").split(":")[-1]
                        ex_label = fx_name.get(ex9s, ex9s)
                    rate_s, rsrc_s = fxb.rate_src(ts, r)
                    tax9 = u = ud = fu9 = None
                    be_sale9 = False
                    if from_known > 0:
                        proceeds_known = cost * from_known / qty if qty > 0 else Decimal(0)
                        pnl = proceeds_known - consumed_cost
                        g["realized"] += pnl
                        flow["realized"] += pnl
                        if is_pay9:
                            flow["pay_real"] = flow.get("pay_real", Decimal(0)) + pnl
                        flow["rbd"][dkey] = flow["rbd"].get(dkey, Decimal(0)) + pnl
                        flow["rbdk"][dkey] = flow["rbdk"].get(dkey, 0.0) + float(pnl) * rate_s
                        flow.setdefault("rch", {}).setdefault(dkey, set()).add(cur_lab[0] or "?")
                        realized_by_date[dkey] = realized_by_date.get(dkey, 0) + float(pnl)
                        realized_krw_by_date[dkey] = realized_krw_by_date.get(dkey, 0) + float(pnl) * rate_s
                        _rl9 = realized_by_loc.setdefault((loc9, dkey), [0.0, 0.0]); _rl9[0] += float(pnl); _rl9[1] += float(pnl) * rate_s
                        tax9 = {"sold": dkey, "sym": g["sym"], "ticker": g["sym"],
                                "ex": ex_label if is_ex else "온체인(DEX)",
                                "qty": _f(from_known, 4),
                                "acq": _f(consumed_cost, 2),
                                "disp": _f(proceeds_known, 2), "fee": 0, "rate": round(rate_s, 4), "rateSrc": rsrc_s,
                                "_acq": float(consumed_cost), "_disp": float(proceeds_known),
                                "_qty": float(from_known)}
                        if oa9 > EPS:
                            tax9["oa"] = _f(oa9, 4)
                            flow["oa_sold"] = flow.get("oa_sold", Decimal(0)) + oa9
                            flow["oa_real"] = flow.get("oa_real", Decimal(0)) + pnl * oa9 / from_known
                            offc_sold[0] += 1
                            offc_sold[1] += pnl * oa9 / from_known
                        tax_krw_acq(tax9, g, flow, consumed_cost, consumed_cost_krw, rate_s, dkey, venue_loc=loc9)
                        tax_rows.append(tax9)
                    if from_unknown > 0 and g["is_stable"]:
                        pass
                    elif from_unknown > 0 and be_take(g["gid"], ts, from_unknown):
                        proceeds_unk = cost * from_unknown / qty if qty > 0 else Decimal(0)
                        be_sale9 = True
                        u = be_done.setdefault(g["gid"], {"sym": g["sym"], "qty": Decimal(0), "proceeds": Decimal(0), "n": 0,
                                                          "first": dkey, "last": dkey, "sales": []})
                        ud = {"qty": from_unknown, "proceeds": proceeds_unk}
                        u["qty"] += from_unknown
                        u["proceeds"] += proceeds_unk
                        u["n"] += 1
                        u["last"] = dkey
                        u["sales"].append(ud)
                        fu9 = [0, Decimal(0)]
                        be_tax.append((ud, {"sold": dkey, "sym": g["sym"], "ticker": g["sym"],
                                            "ex": (ex_label if is_ex else "온체인(DEX)") + " · 매수가=매도가",
                                            "qty": _f(from_unknown, 4), "acq": 0, "disp": 0, "fee": 0, "rate": round(rate_s, 4), "rateSrc": rsrc_s, "be": 1,
                                            "_qty": float(from_unknown)}))
                        tax_rows.append(be_tax[-1][1])
                    elif from_unknown > 0:
                        proceeds_unk = cost * from_unknown / qty if qty > 0 else Decimal(0)
                        u = unverified.setdefault(g["gid"], {"sym": g["sym"],
                                                             "qty": Decimal(0),
                                                             "proceeds": Decimal(0), "n": 0,
                                                             "last": dkey, "by_date": {}})
                        u["qty"] += from_unknown
                        u["proceeds"] += proceeds_unk
                        u["n"] += 1
                        u["last"] = dkey
                        ud = u["by_date"].setdefault(dkey, {"qty": Decimal(0), "proceeds": Decimal(0)})
                        ud["qty"] += from_unknown
                        ud["proceeds"] += proceeds_unk
                        fu9 = flow["ubd"].setdefault(dkey, [0, Decimal(0)])
                        fu9[0] += 1
                        fu9[1] += proceeds_unk
                        ubq9 = flow.setdefault("ubq", {})
                        ubq9[dkey] = ubq9.get(dkey, Decimal(0)) + from_unknown
                    if evk == "EXF_SELL":
                        fee_disp[(r["source_ns"], txh)] = {"g": g, "gid": g["gid"], "flow": flow, "dkey": dkey, "qty": qty, "usd": cost,
                                                           "fk": qty if g["is_stable"] else from_known, "tax": tax9, "u": u, "ud": ud,
                                                           "fu9": fu9, "rate": rate_s, "loc": loc9}
                    if is_pay9:
                        flow.setdefault("pay_dates", []).append(dkey)
                        flow["paid_usd"] = flow.get("paid_usd", Decimal(0)) + cost
                    else:
                        flow["sold_dates"].append(dkey)
                        flow["proceeds"] = flow.get("proceeds", Decimal(0)) + cost
                        flow["proceeds_krw"] = flow.get("proceeds_krw", Decimal(0)) + krw_of(cost, ts, r)
                    if evk == "EX_SELL" and tax9 is not None and r["source_ns"] == "upbit:order" and int(r["leg_seq"] or 0) == 0:
                        ex_fee9 = up_fee.get(r["source_id"])
                        if ex_fee9 and ex_fee9[0] > ex_fee9[1]:
                            fu_all9 = cost * ex_fee9[1] / (ex_fee9[0] - ex_fee9[1])
                            fk9 = fu_all9 * from_known / qty if qty > 0 else Decimal(0)
                            _tax_add(tax9, "disp", fk9)
                            _tax_add(tax9, "fee", fk9)
                            ex_fee_add("upbit", fu_all9, ts)
                    elif evk == "EX_SELL" and r["source_ns"] == "upbit:order" and up_fee.get(r["source_id"]) and int(r["leg_seq"] or 0) == 0:
                        ex_fee9 = up_fee[r["source_id"]]
                        if ex_fee9[0] > ex_fee9[1]:
                            ex_fee_add("upbit", cost * ex_fee9[1] / (ex_fee9[0] - ex_fee9[1]), ts)
                    sg9 = swap_gas.get((r["source_ns"], txh)) if (gas_on and evk == "SWAP") else None
                    if sg9 and not sg9["done"] and sg9["sell"] == g["gid"] and sg9["usd"] > 0 and (tax9 is not None or u is not None):
                        sg9["done"] = True
                        G9 = sg9["usd"]
                        Gk9 = G9 * from_known / qty if (qty > 0 and tax9 is not None) else Decimal(0)
                        Gu9 = G9 - Gk9 if u is not None else Decimal(0)
                        if Gk9 > 0:
                            g["realized"] -= Gk9
                            flow["realized"] -= Gk9
                            flow["rbd"][dkey] = flow["rbd"].get(dkey, Decimal(0)) - Gk9
                            flow["rbdk"][dkey] = flow["rbdk"].get(dkey, 0.0) - float(Gk9) * rate_s
                            realized_by_date[dkey] = realized_by_date.get(dkey, 0) - float(Gk9)
                            realized_krw_by_date[dkey] = realized_krw_by_date.get(dkey, 0) - float(Gk9) * rate_s
                            _rl9 = realized_by_loc.setdefault((loc9, dkey), [0.0, 0.0]); _rl9[0] -= float(Gk9); _rl9[1] -= float(Gk9) * rate_s
                            _tax_add(tax9, "fee", Gk9)
                        if Gu9 > 0:
                            u["proceeds"] -= Gu9
                            ud["proceeds"] -= Gu9
                            fu9[1] -= Gu9
                        gas_applied["sell"] += Gk9 + Gu9
                        gas_applied["n"] += 1
                    cv9 = conv_cp.get((r["source_ns"], txh)) if (g["is_stable"] and not is_pay9) else None
                    cv9 = [s9 for s9 in (cv9 or ()) if s9 != g["sym"]]
                    ev(flow, ts, "거래소 매도" if is_ex else "온체인 매도",
                       (f"{ex_label} · " + (f"{up_mkt.get(r['source_id'], 'KRW')} 마켓 체결" if evk == "EX_SELL" else "현물 체결")
                        if is_ex
                        else f"{CHAIN_NAME.get(chain, chain)} · 스왑 매도")
                       + (" · 매수 대금 지불(스왑 지불 레그)" if is_pay9 else "")
                       + (f" · {g['sym']} → {' · '.join(cv9)} 전환" if cv9 else "")
                       + unk_tag(from_known, from_unknown, cost, qty, g["is_stable"], be_sale9)
                       + (f" · 원가 {'전부' if oa9 >= from_known - EPS else '일부'} 오프체인 이어받음(내 계정으로 가정)" if oa9 > EPS else ""),
                       f"{qty:,.4f}".rstrip("0").rstrip("."), f"${float(cost):,.2f}", txh, un=_un(qty, cost))
                    if cmp9s is not None:
                        flow["events"][-1]["_cmp"] = cmp9s
                    flow["events"][-1]["_tax"] = tax9 if tax9 is not None else (be_tax[-1][1] if be_sale9 and be_tax else None)
                    if is_pay9:
                        flow["events"][-1]["_pay"] = True
                    elif cv9:
                        flow["events"][-1]["_conv"] = "원화 환전" if cv9 == ["원화"] else "스테이블 교환"
                else:
                    ev(flow, ts, "온체인 매도", f"{CHAIN_NAME.get(chain, chain)} · 정산액 산정 중"
                       + (" · 매수 대금 지불(스왑 지불 레그)" if is_pay9 else ""),
                       f"{qty:,.4f}".rstrip("0").rstrip("."), "—", txh)
                    flow["events"][-1]["_tax"] = None
                    np9 = noproc.setdefault(g["gid"], {"sym": g["sym"], "n": 0, "qty": Decimal(0), "cost": Decimal(0), "unk": Decimal(0),
                                                       "first": dkey, "last": dkey, "where": set(), "tx": [], "old": False})
                    np9["old"] = np9["old"] or (time.time() - float(ts or 0) > 3600)
                    np9["n"] += 1
                    np9["qty"] += qty
                    np9["cost"] += consumed_cost
                    np9["unk"] += from_unknown
                    np9["last"] = max(np9["last"], dkey)
                    if evk == "EXF_SELL":
                        exn9 = (r["location"] or "").split(":")[-1]
                        np9["where"].add(fx_name.get(exn9, exn9))
                    elif evk == "EX_SELL":
                        np9["where"].add("업비트")
                    else:
                        np9["where"].add(CHAIN_NAME.get(chain, chain))
                    if len(np9["tx"]) < 5:
                        np9["tx"].append(str(txh or ""))
                    if cmp9s is not None:
                        flow["events"][-1]["_cmp"] = cmp9s
                    if is_pay9:
                        flow["events"][-1]["_pay"] = True
                if g["qty_known"] + g["qty_unknown"] <= Decimal("0.000001"):
                    g["cur"] = None
                continue

        cur_row[0] = None
        for ud9, t9 in be_tax:
            p9 = float(ud9["proceeds"])
            t9.update({"acq": _f(p9, 2), "disp": _f(p9, 2), "_acq": p9, "_disp": p9, "_akr": p9 * float(t9["rate"] or 0)})
            t9["akr"] = float(t9["disp"]) * float(t9["rate"] or 0)
        for gid_w, dw in win_cut_d.items():
            if not dw:
                continue
            g_w = G.get(gid_w)
            if g_w is None:
                continue
            c_lost, k_lost, _u_lost = consume(g_w, dw[0])
            if k_lost > EPS:
                g_w["unv_lost"] = (k_lost, c_lost, dw[1])

        uncred_gid = {}
        uncred_fx = {}
        uncred_known = {}
        uncred_cost = {}
        for lst in ex_transit.values():
            for e2 in lst:
                if not e2["credited"] and not e2["used"]:
                    gk = e2["gid"]
                    uncred_gid[gk] = uncred_gid.get(gk, Decimal(0)) + e2["qty"]
                    cy2 = e2.get("cyc")
                    if cy2 is not None:
                        cy2["moved_qty"] -= e2["qty"]
                        cy2["moved_cost"] -= e2.get("cost", Decimal(0))
                    uncred_known[gk] = uncred_known.get(gk, Decimal(0)) + e2.get("known", Decimal(0))
                    uncred_cost[gk] = uncred_cost.get(gk, Decimal(0)) + e2.get("cost", Decimal(0))
        for e9 in fxdep_transit.values():
            if e9["left"] > EPS and e9["qty"] > 0:
                sc9 = e9["left"] / e9["qty"]
                gk9 = e9.get("gid")
                if gk9 is not None:
                    if e9.get("ex"):
                        uncred_fx[gk9] = e9["ex"]
                    uncred_gid[gk9] = uncred_gid.get(gk9, Decimal(0)) + e9["left"]
                    for cy9, q9c, c9c in e9.get("cycs") or ():
                        if cy9 is not None:
                            cy9["moved_qty"] -= q9c * sc9
                            cy9["moved_cost"] -= c9c * sc9
                    uncred_known[gk9] = uncred_known.get(gk9, Decimal(0)) + e9["known"] * sc9
                    uncred_cost[gk9] = uncred_cost.get(gk9, Decimal(0)) + e9["cost"] * sc9
        try:
            wdt_all = self._wd_transit_resolve(wd_tr, rows, wd_raw9, fx_transit, xf_links, up_dep_uid_tx, exf_dep_tx, G,
                                               skip_tx=frozenset(of_chain) | frozenset(fx_wd), now=now,
                                               skip_deps=frozenset(uuid2txh) | frozenset(
                                                   u9 for m9 in of_match.values() for u9 in _of_uids(m9))
                                               | frozenset(u9 for e9, u9 in offc_dep if e9 in offc_on))
        except Exception as e9:
            log.warning("거래소 출금 전송 중 판정 실패(종전대로 즉시 차감): %s", e9)
            wdt_all = []
        wdt_gid = {}
        for e9 in wdt_all:
            if e9["state"] != "pending":
                continue
            gk9 = e9["gid"]
            uncred_gid[gk9] = uncred_gid.get(gk9, Decimal(0)) + e9["qty"]
            uncred_known[gk9] = uncred_known.get(gk9, Decimal(0)) + e9["known"]
            uncred_cost[gk9] = uncred_cost.get(gk9, Decimal(0)) + e9["cost"]
            wdt_gid.setdefault(gk9, []).append(e9)
            cy9 = e9.get("cyc")
            if cy9 is not None and (G.get(gk9) or {}).get("cur") is cy9:
                cy9["moved_qty"] -= e9["qty"]
                cy9["moved_cost"] -= e9["cost"]
            if isinstance(e9.get("ev"), dict):
                e9["ev"]["d"] = f"{e9['src']} 출금 → " + (f"{e9['dst']} " if e9.get("dst") else "") + "전송 중 (도착 확인 대기)"
        if self.KEEP_DIAG:
            self._wd_transit_last = wdt_all

        pos_rows = []
        by_symloc = {}
        lp_pos_rows = []
        for row in conn.execute("SELECT group_id, location, qty_norm FROM positions").fetchall():
            try:
                qn0 = Decimal(row["qty_norm"])
            except (InvalidOperation, TypeError, ValueError):
                continue
            if (row["location"] or "").startswith("lp:"):
                lp_pos_rows.append((row["group_id"], row["location"], qn0))
                continue
            if (row["location"] or "").startswith("out:"):
                continue
            d0 = {"gid": row["group_id"], "location": row["location"] or "", "qty": qn0}
            pos_rows.append(d0)
            if d0["location"].startswith("exchange:"):
                sym0 = ((G.get(d0["gid"]) or {}).get("sym") or "").upper()
                if sym0:
                    by_symloc.setdefault((sym0, d0["location"]), []).append(d0)
        for rows0 in by_symloc.values():
            neg0 = sum((-r["qty"] for r in rows0 if r["qty"] < 0), Decimal(0))
            if neg0 <= 0:
                continue
            for r in sorted((r for r in rows0 if r["qty"] > 0),
                            key=lambda r: (-r["qty"], r["gid"])):
                take0 = min(r["qty"], neg0)
                r["qty"] -= take0
                neg0 -= take0
                if neg0 <= 0:
                    break
        locs_by_gid = {}
        led_by_gid = {}
        led_upbit_gids = set()
        upbit_transit_gids = {
            e2["gid"] for lst in ex_transit.values() for e2 in lst
            if not e2["credited"] and not e2["used"]}
        hl_neg = {}
        hl_cash_syms9 = _hl_cash_syms()
        for r in pos_rows:
            locs_by_gid.setdefault(r["gid"], []).append(
                {"location": r["location"], "qty_norm": str(r["qty"])})
            if r["qty"] > 0:
                led_by_gid[r["gid"]] = led_by_gid.get(r["gid"], Decimal(0)) + r["qty"]
                if r["location"] == "exchange:upbit":
                    led_upbit_gids.add(r["gid"])
            elif (r["qty"] < -EPS and r["location"] == "exchange:hyperliquid"
                  and str((G.get(r["gid"]) or {}).get("sym") or "").upper() in hl_cash_syms9):
                led_by_gid[r["gid"]] = led_by_gid.get(r["gid"], Decimal(0)) + r["qty"]
                hl_neg[r["gid"]] = led_by_gid[r["gid"]]

        live = {gid: g for gid, g in G.items()
                if not g.get("is_fiat")
                and (led_by_gid.get(gid, Decimal(0)) + uncred_gid.get(gid, Decimal(0)) > EPS or gid in hl_neg)}
        price_groups = dict(live)
        price_t0 = (today_kst - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        for gid, g in G.items():
            if gid in price_groups or g.get("is_fiat"):
                continue
            if (sum((dq for ts, dq in g["qty_timeline"] if ts < price_t0), Decimal(0)) > EPS
                    or any(ts >= price_t0 and dq > 0 for ts, dq in g["qty_timeline"])):
                price_groups[gid] = g
        self.spot.want([g["sym"] for g in G.values()])
        ex_gid = {}
        for r7 in conn.execute("SELECT group_id, address FROM assets"
                               " WHERE kind='exchange_currency' AND group_id IS NOT NULL"):
            ad7 = str(r7["address"] or "")
            if ":" in ad7:
                ex_gid[r7["group_id"]] = ad7.split(":", 1)[0]
        self.spot.want_ex({ex for gid, ex in ex_gid.items() if gid in price_groups})
        tok_pairs9 = {}
        for r2 in conn.execute("SELECT group_id, chain, address FROM assets WHERE kind='token'"
                               " AND address IS NOT NULL AND group_id IS NOT NULL").fetchall():
            tok_pairs9.setdefault(r2["group_id"], []).append((r2["chain"], r2["address"]))
        gid_pairs = {}
        for gid in price_groups:
            pairs = list(tok_pairs9.get(gid) or ())
            if pairs:
                gid_pairs[gid] = pairs
        self.spot.want_tokens([p for gid, ps in gid_pairs.items() if not (G.get(gid) or {}).get("is_stable") for p in ps])
        self._ph("signer·cards")
        cex_proof = self._cex_proof(conn)
        self.spot.want_ex({ex9 for gid9, lst9 in cex_proof.items() if gid9 in gid_pairs for ex9, _c9 in lst9})
        def pre_mkt9(sym9):
            return bool(self.spot.upbit_krw) and sym9 not in self.spot.upbit_krw and sym9 not in self.spot.upbit_alt
        exk9 = {}
        for gid9, ex9 in ex_gid.items():
            s9 = acct_norm.canon((G.get(gid9) or {}).get("sym"), ex9) if ex9 == "upbit" else None
            if s9:
                exk9.setdefault(s9, []).append(gid9)
        pre_og9 = {}
        for og9 in sorted(cex_proof):
            if (G.get(og9) or {}).get("is_stable"):
                continue
            for ex9, cur9 in cex_proof[og9]:
                for xg9 in (exk9.get(acct_norm.canon(cur9, ex9)) or ()) if ex9 == "upbit" else ():
                    if og9 not in pre_og9.setdefault(xg9, []):
                        pre_og9[xg9].append(og9)
        pre_want9 = [xg9 for xg9 in pre_og9 if xg9 in price_groups and pre_mkt9(price_groups[xg9]["sym"])
                     and not self.spot.ex_price("upbit", price_groups[xg9]["sym"])]
        self.spot.want_tokens([p9 for xg9 in pre_want9 for og9 in pre_og9[xg9] for p9 in tok_pairs9.get(og9) or ()], slot="expre")
        self.spot.want_ex({ex9 for xg9 in pre_want9 for og9 in pre_og9[xg9] for ex9, _c9 in cex_proof.get(og9) or ()})

        def cex_px_for(gid9):
            for ex9, cur9 in cex_proof.get(gid9) or ():
                p9 = self.spot.ex_price(ex9, cur9)
                if p9:
                    return float(p9), ex9, cur9
            return 0.0, None, None

        overrides9 = prefs.get("risk_overrides") or {}
        wl9 = {str(a).lower() for a in (prefs.get("src_whitelist") or []) if a}
        gp_cache9 = common.read_json(GOPLUS_PATH, {}) if os.path.exists(GOPLUS_PATH) else {}
        gid_pairs_all = {}
        for r12 in conn.execute("SELECT group_id, chain, address FROM assets"
                                " WHERE kind='token' AND address IS NOT NULL"
                                " AND group_id IS NOT NULL").fetchall():
            gid_pairs_all.setdefault(r12["group_id"], []).append(
                (r12["chain"], r12["address"]))
        native_gids9 = {r12[0] for r12 in conn.execute(
            "SELECT DISTINCT group_id FROM assets WHERE kind != 'token' AND group_id IS NOT NULL").fetchall()}
        native_kind9 = {r12[0] for r12 in conn.execute(
            "SELECT DISTINCT group_id FROM assets WHERE kind = 'native' AND group_id IS NOT NULL").fetchall()}
        proven_ca9 = {}
        for gidp9, lstp9 in cex_proof.items():
            if lstp9:
                for chp9, cap9 in gid_pairs_all.get(gidp9, []):
                    if chp9 != "sol" and cap9:
                        proven_ca9.setdefault(cap9.lower(), set()).add(chp9)

        def gp_info9(gid12):
            worst12 = None
            for ch12, ca12 in gid_pairs_all.get(gid12, []):
                ent12 = (gp_cache9.get(f"{ch12}:{(ca12 or '').lower()}") or {}).get("risk")
                if ent12:
                    if ent12.get("strong"):
                        return ent12
                    worst12 = worst12 or ent12
            return worst12

        quarantined = set()
        airdrop_only = set()
        goplus_want9 = set()
        real_sym9 = {}
        for gid9r, g9r in G.items():
            if g9r.get("px_seen") or g9r.get("ex_seen"):
                sk9r = acct_norm.canon(spamguard.clean(g9r.get("sym") or ""))
                if sk9r:
                    real_sym9.setdefault(sk9r, set()).add(gid9r)

        def fake_ticker9(gid12, g12):
            if gid12 not in gid_pairs_all or gid12 in native_gids9 or g12.get("is_stable") or g12.get("is_fiat") or not g12.get("sent_n"):
                return None
            if any(g12.get(k9) for k9 in ("px_seen", "ex_seen", "mv_seen", "risk_allow", "risk_allow_bridge", "risk_airdrop_signed", "risk_airdrop")):
                return None
            for ch12, ca12 in gid_pairs_all.get(gid12, []):
                if spamguard.is_genuine(ch12, ca12):
                    return None
                k12 = f"{ch12}:{(ca12 or '').lower() if ch12 != 'sol' else ca12}"
                if self.spot.dex_usd.get(k12) or float(self.spot.dex_res.get(k12) or 0) >= 1000:
                    return None
            sym9f = spamguard.clean(g12.get("sym") or "").strip()
            sk9 = acct_norm.canon(sym9f)
            if not sk9 or re.fullmatch(r"TOKEN|NATIVE:.*|\?", sk9) or not (real_sym9.get(sk9, set()) - {gid12}):
                return None
            if cex_px_for(gid12)[0] or any(ch12 != "sol" and (proven_ca9.get((ca12 or "").lower()) or set())
                                           for ch12, ca12 in gid_pairs_all.get(gid12, [])):
                return None
            if any(self.spot.dex_price(ch12, (ca12 or "").lower() if ch12 != "sol" else ca12)
                   for ch12, ca12 in gid_pairs_all.get(gid12, [])):
                return None
            return f"가짜 {sym9f} — 원장의 정품 {sym9f}(체결·거래소 이력)와 다른 컨트랙트 · 시세·체결 없음"
        for gid12, g12 in G.items():
            ov12 = overrides9.get(f"g{gid12}")
            why12 = self._impostor_reason(
                g12, gid12 in gid_pairs_all, gid_pairs_all.get(gid12), gid12 in native_gids9,
                priced=not g12.get("spoof_soft") or bool(cex_px_for(gid12)[0])
                or any(self.spot.dex_price(ch12, (ca12 or "").lower() if ch12 != "sol" else ca12)
                       for ch12, ca12 in gid_pairs_all.get(gid12, []))) \
                if ov12 not in ("visible", "spam") else None
            if not why12 and ov12 not in ("visible", "spam"):
                why12 = fake_ticker9(gid12, g12)
            if why12:
                g12["risk_reason"] = why12
                quarantined.add(gid12)
                continue
            if not any(dq12 > 0 for _, dq12 in g12["qty_timeline"]):
                continue
            if ov12 == "spam":
                g12["risk_reason"] = "유저 확정 스팸"
                quarantined.add(gid12)
                continue
            if g12.get("is_stable") or g12.get("is_fiat") or g12.get("risk_allow"):
                continue
            if any(k12 in ("native", "exchange_currency") or st12 or spamguard.is_genuine(ch12, ca12)
                   or (((G.get(cg12) or {}).get("ex_seen") or (G.get(cg12) or {}).get("mv_seen")) and cg12 not in quarantined)
                   for cg12, k12, ch12, ca12, st12 in g12.get("risk_disp_cp") or ()):
                continue
            if ov12 == "visible":
                continue
            if wl9 and g12.get("risk_srcs") and self._risk_wl_hit(conn, g12, wl9):
                continue
            if g12.get("risk_allow_bridge"):
                goplus_want9.update(gid_pairs_all.get(gid12, []))
                gpb12 = gp_info9(gid12)
                if not (gpb12 and gpb12.get("strong")):
                    continue
                g12["risk_reason"] = f"브릿지 매칭 자산 · 고플러스 {gpb12['label']}"
                quarantined.add(gid12)
                continue
            airdrop12 = bool(g12.get("risk_airdrop"))
            if not airdrop12 and g12.get("risk_airdrop_signed"):
                liq12 = bool(cex_px_for(gid12)[0]) or any(
                    self.spot.dex_price(ch12, (ca12 or "").lower() if ch12 != "sol" else ca12)
                    and (self.spot.dex_reserve(ch12, (ca12 or "").lower() if ch12 != "sol" else ca12) or 0) >= self.spot.min_reserve_usd
                    for ch12, ca12 in gid_pairs_all.get(gid12, []))
                if liq12:
                    goplus_want9.update(gid_pairs_all.get(gid12, []))
                    gps12 = gp_info9(gid12)
                    if gps12 and gps12.get("strong"):
                        g12["risk_reason"] = f"내 서명 수령 · 고플러스 {gps12['label']}"
                        quarantined.add(gid12)
                        continue
                airdrop12 = not liq12
                if liq12:
                    g12["risk_signed_ok"] = True
            open12 = bool(g12.get("risk_open_unk"))
            if not (airdrop12 or open12):
                continue
            if any(ch12 != "sol" and (proven_ca9.get((ca12 or "").lower()) or set()) - {ch12}
                   for ch12, ca12 in gid_pairs_all.get(gid12, [])):
                continue
            gp12 = gp_info9(gid12)
            goplus_want9.update(gid_pairs_all.get(gid12, []))
            if airdrop12:
                g12["risk_reason"] = "실매수 이력 없는 에어드랍 유입" + \
                    (f" · 고플러스 {gp12['label']}" if gp12 else " · 고플러스 조회 중")
                quarantined.add(gid12)
                if not (gp12 and gp12.get("strong")):
                    airdrop_only.add(gid12)
            elif open12 and g12.get("risk_rebal_neg"):
                g12["risk_reason"] = "기초잔고 앵커 → 재정렬 실측 소거 (잔고 대사 잔여분)"
                quarantined.add(gid12)
            elif gp12 and gp12.get("strong"):
                g12["risk_reason"] = f"기초잔고 앵커 + 고플러스 {gp12['label']}"
                quarantined.add(gid12)
        off12 = set(self.cfg.get("_disabled_chains") or ())
        self._goplus_want = sorted(p for p in goplus_want9 if p[0] not in off12)
        self._risk_quarantined = quarantined
        self._risk_airdrop_only = frozenset(g9 for g9 in airdrop_only & quarantined
                                            if str(G[g9].get("risk_reason") or "").startswith("실매수 이력 없는 에어드랍 유입"))
        self._risk_reasons = {gid14: (G[gid14].get("risk_reason") or "")
                              for gid14 in quarantined}
        spam_view = []

        override_px = {}
        for k, v in (self.cfg.get("price_overrides") or {}).items():
            if not isinstance(k, str) or ":" not in k:
                continue
            ch, ca = k.split(":", 1)
            row = conn.execute("SELECT group_id FROM assets WHERE chain=? AND address=?",
                               (ch, ca if ch == "sol" else ca.lower())).fetchone()
            if row and row["group_id"]:
                try:
                    override_px[row["group_id"]] = float(v)
                except (TypeError, ValueError):
                    pass

        aliases = prefs.get("aliases") or {}
        stake_meta = _sol_stake_accounts()

        def locs_for(gid, uncred=Decimal(0), ubq=Decimal(0)):
            outl = []
            for row in locs_by_gid.get(gid, []):
                qn = float(Decimal(row["qty_norm"]))
                if qn <= 1e-9:
                    if gid in hl_neg and row["location"] == "exchange:hyperliquid" and qn < 0:
                        outl.append({"w": fx_name.get("hyperliquid", "Hyperliquid"), "qty": qn,
                                     "sub": "무기한 현금 음수(미실현 이익 인출 — 포지션 청산 때 메워짐 · 총자산에서 차감)"})
                    continue
                parts = (row["location"] or "").split(":")
                if parts[0] == "exchange":
                    exn = fx_name.get(parts[1], parts[1])
                    outl.append({"w": exn, "sub": "거래소 잔고 (입금·체결 원장)", "qty": qn})
                    continue
                ch = parts[1] if len(parts) >= 2 else "?"
                wa = parts[2] if len(parts) >= 3 and parts[2] else None
                if wa and len(parts) >= 5 and parts[3] == "stake":
                    label = aliases.get(wa) or self.addr_label.get(wa) or wa[:8]
                    sa9 = parts[4]
                    sm9 = stake_meta.get(sa9) or {}
                    v9 = sm9.get("voter")
                    rw9 = stake_rwd.get(row["location"] or "")
                    sub9 = (f"{CHAIN_NAME.get(ch, ch)} · SOL ({STAKE_STATE_KO.get(sm9.get('state'), '스테이킹')}"
                            f" · 검증인 {(v9[:4] + '…' + v9[-4:]) if v9 else '미상'}) · 계정 {sa9[:4]}…{sa9[-4:]} · {wa[:6]}…{wa[-4:]}")
                    if rw9 and rw9[0] > 0:
                        sub9 += f" · 누적 보상 {float(rw9[0]):,.4f} SOL"
                    outl.append({"w": (f"{label} · 스테이킹" if str(label).rstrip().endswith("지갑") else f"{label} 지갑 · 스테이킹"),
                                 "ch": CHAIN_NAME.get(ch, ch), "sub": sub9, "qty": qn})
                    continue
                if wa:
                    label = aliases.get(wa) or self.addr_label.get(wa) or wa[:8]
                    short = f"{wa[:6]}…{wa[-4:]}"
                    outl.append({"w": label if str(label).rstrip().endswith("지갑") else f"{label} 지갑", "ch": CHAIN_NAME.get(ch, ch),
                                 "sub": f"{CHAIN_NAME.get(ch, ch)} · {short}", "qty": qn})
                else:
                    outl.append({"w": "SOL 지갑" if ch == "sol" else "EVM 지갑",
                                 "sub": f"{CHAIN_NAME.get(ch, ch)} · 합산(구형 기록)", "qty": qn})
            tr9 = wdt_gid.get(gid) or ()
            uncred_old9 = uncred - sum((e9["qty"] for e9 in tr9), Decimal(0))
            if uncred_old9 > EPS:
                w_u = "업비트" if (gid in upbit_transit_gids or gid not in uncred_fx) else fx_name.get(uncred_fx[gid], uncred_fx[gid])
                outl.append({"w": w_u, "sub": "입금확인 대기 · 대사 전", "qty": float(uncred_old9)})
            for e9 in tr9:
                outl.append(self._transit_loc(e9, now))
            if outl:
                return outl
            g9 = G.get(gid) or {}
            last_out = (g9.get("last_out") or {})
            if last_out.get("ex"):
                return [{"w": fx_name.get(last_out["ex"], last_out["ex"]),
                         "sub": "입금 확인 대기 · 거래소 대사 전", "qty": 0}]
            d9 = self._transfer_out_dest(conn).get((g9.get("sym") or "").upper())
            if d9:
                return [{"w": d9["label"],
                         "sub": f"외부 전송 확인 · {(d9.get('to') or '')[:12]}…", "qty": 0}]
            return [{"w": "확인 필요", "sub": "원장 위치 없음 — 미매칭 탭 참조", "qty": 0}]

        def venue_w(loc):
            parts = str(loc or "").split(":")
            if parts[0] == "exchange" and len(parts) >= 2:
                return fx_name.get(parts[1], parts[1])
            if parts[0] != "wallet":
                return None
            ch = parts[1] if len(parts) >= 2 else "?"
            wa = parts[2] if len(parts) >= 3 and parts[2] else None
            if not wa:
                return "SOL 지갑" if ch == "sol" else "EVM 지갑"
            label = aliases.get(wa) or self.addr_label.get(wa) or wa[:8]
            if len(parts) >= 5 and parts[3] == "stake":
                return f"{label} · 스테이킹" if str(label).rstrip().endswith("지갑") else f"{label} 지갑 · 스테이킹"
            return label if str(label).rstrip().endswith("지갑") else f"{label} 지갑"

        ub_coins = {}
        ub2 = {}
        ub_path2 = os.path.join(common.STATE_DIR, "upbit_balances.json")
        if os.path.exists(ub_path2):
            ub2 = common.read_json(ub_path2, {})
            if time.time() - (ub2.get("ts") or 0) < common.upbit_fresh_sec(self.cfg):
                for acc in ub2.get("accounts") or []:
                    cur3 = str(acc.get("currency") or "")
                    if cur3 in ("", "KRW"):
                        continue
                    try:
                        q3 = float(acc.get("balance") or 0) + float(acc.get("locked") or 0)
                    except (TypeError, ValueError):
                        continue
                    if q3 > 0:
                        ub_coins[cur3.upper()] = ub_coins.get(cur3.upper(), 0) + q3

        stables, coins = [], []
        unpriced = []
        unpriced_w = []
        guard_held9 = set()
        hold_prio = {}
        cex_px_pairs = set()
        live_px = {}
        pending_gids = set()
        px_wait9 = self._px_wait_gids = set()
        proof_div9 = []
        meta_want9 = set()

        def meta_sym9(gid9):
            for ch9, ca9 in gid_pairs.get(gid9) or ():
                m9 = self.spot.token_meta.get(f"{ch9}:{ca9}")
                s9 = spamguard.clean((m9 or ["", ""])[0]).strip()
                if not s9 or len(s9) > 20 or s9.upper() in ("TOKEN", "?") or s9.upper() in STABLE_GROUPS:
                    continue
                if _scam_name(s9) or spamguard.major_of(s9) or spamguard.impostor_of(s9) or spamguard.odd_symbol(s9):
                    continue
                return s9
            return None

        def glob_age9(sym9):
            ts9 = self.spot.usd_ts.get(sym9)
            return (time.time() - float(ts9)) if ts9 else None

        def ref_px9(sym9, own9):
            vals9 = sorted((float(p9), ex9) for ex9 in self.CEX_PX_ORDER if ex9 != own9
                           for p9 in (self.spot.ex_price(ex9, sym9),) if p9)
            if not vals9:
                return None
            n9 = len(vals9)
            med9 = vals9[n9 // 2][0] if n9 % 2 else (vals9[n9 // 2 - 1][0] + vals9[n9 // 2][0]) / 2
            return {"px": med9, "srcs": [fx_name.get(e9, e9) for _v9, e9 in vals9], "note": "다른 거래소 참고가(동일 코인 미확인)"}

        pre_used9 = self._px_pre_gids = {}

        def pre_px9(xg9, sym9, qty9):
            ogs9 = pre_og9.get(xg9) or ()
            for og9 in ogs9:
                for ex9, cur9 in cex_proof.get(og9) or ():
                    p9 = self.spot.ex_price(ex9, cur9) if ex9 != "upbit" else None
                    if p9:
                        return float(p9), f"cex:{fx_name.get(ex9, ex9)}", self.spot.ex_age(ex9, cur9), None, 0
            vs9 = []
            for ex9 in self.CEX_PX_ORDER:
                p9 = self.spot.ex_price(ex9, sym9) if ex9 != "upbit" else None
                if p9 and p9 > 0:
                    vs9.append((ex9, float(p9), self.spot.ex_age(ex9, sym9)))
            gp9 = self.spot.price(sym9)
            if gp9 and gp9 > 0 and not any(e9 == "binance" for e9, _p9, _a9 in vs9):
                vs9.append(("글로벌", float(gp9), glob_age9(sym9)))
            if not ogs9:
                for ex9, p9, a9 in vs9:
                    n9 = sum(1 for _e9, q9, _a9 in vs9 if max(p9, q9) / min(p9, q9) <= self.PRE_DIVERGE)
                    if n9 >= 2:
                        return p9, f"cex:{fx_name.get(ex9, ex9)}", a9, None, n9
                return 0.0, None, None, None, 0
            dref9, dval9 = None, None
            for og9 in ogs9:
                for ch9, ca9 in tok_pairs9.get(og9) or ():
                    dp9 = self.spot.dex_price(ch9, ca9)
                    if not dp9:
                        continue
                    dref9 = dref9 or float(dp9)
                    rv9 = self.spot.dex_reserve(ch9, ca9)
                    if rv9 is not None and qty9 > 0 and dp9 * qty9 > rv9:
                        continue
                    dval9 = (float(dp9), (ch9, ca9))
                    break
                if dval9:
                    break
            for ex9, p9, a9 in vs9:
                if dref9 and max(p9, dref9) / min(p9, dref9) > self.PRE_DIVERGE:
                    continue
                if not dref9:
                    n9 = sum(1 for _e9, q9, _a9 in vs9 if max(p9, q9) / min(p9, q9) <= self.PRE_DIVERGE)
                    if n9 < 2:
                        continue
                    return p9, f"cex:{fx_name.get(ex9, ex9)}", a9, None, n9
                return p9, f"cex:{fx_name.get(ex9, ex9)}", a9, None, 0
            if dval9:
                k9 = dval9[1]
                return dval9[0], "dex:" + self.spot.dex_src.get(f"{k9[0]}:{k9[1]}", "gecko"), self.spot.dex_age(*k9), k9, 0
            return 0.0, None, None, None, 0

        for gid, g in sorted(price_groups.items(), key=lambda kv: kv[1]["sym"]):
            sym = g["sym"]
            uncred = uncred_gid.get(gid, Decimal(0))
            if gid in led_upbit_gids or gid in upbit_transit_gids:
                ub_coins.pop(sym, None)
            qty_dec = led_by_gid.get(gid, Decimal(0)) + uncred
            qty = float(qty_dec)
            k_all = g["qty_known"] + uncred_known.get(gid, Decimal(0))
            c_all = g["cost"] + uncred_cost.get(gid, Decimal(0))
            avg = float(c_all / k_all) if k_all > EPS else 0
            if g["is_stable"]:
                if gid not in live:
                    continue
                if gid in quarantined:
                    spam_view.append((gid, g, qty, 1))
                    continue
                stables.append({"key": f"g{gid}", "sym": sym, "name": sym,
                                "qty": qty, "price": 1, "avg": 1,
                                "locs": locs_for(gid, uncred)})
                continue
            dex_px = 0
            dex_key = None
            cex_px, cex_ex, cex_cur = cex_px_for(gid) if gid not in ex_gid else (0.0, None, None)
            if cex_px:
                cex_px_pairs.update(gid_pairs.get(gid, []))
            for ch2, ca2 in gid_pairs.get(gid, []):
                dp = self.spot.dex_price(ch2, ca2)
                if dp:
                    rv2 = self.spot.dex_reserve(ch2, ca2)
                    if rv2 is not None and qty > 0 and dp * qty > rv2:
                        self.spot._guard_note(f"{ch2}:{ca2}", f"보유 평가 ${dp * qty:,.0f} > 풀 유동성 ${rv2:,.0f}")
                        continue
                    if self.spot.guarded.get(f"{ch2}:{ca2}", "").startswith("보유 평가"):
                        self.spot._guard_note(f"{ch2}:{ca2}", None)
                    dex_px = dp
                    dex_key = (ch2, ca2)
                    break
            has_ca = bool(gid_pairs.get(gid))
            src9, age9 = None, None
            if gid in override_px:
                px = override_px[gid]
            elif gid in ex_gid:
                px = self.spot.ex_price(ex_gid[gid], sym) or 0
                src9 = f"cex:{fx_name.get(ex_gid[gid], ex_gid[gid])}"
                if ex_gid[gid] == "upbit" and sym in (getattr(self.spot, "upbit_alt_src", None) or {}):
                    src9 = "cex:" + self.spot.upbit_alt_src[sym]
                elif ex_gid[gid] == "hyperliquid" and sym in (getattr(self.spot, "hl_src", None) or {}):
                    src9 = "cex:" + self.spot.hl_src[sym]
                age9 = self.spot.ex_age(ex_gid[gid], sym)
                if not px and (self.spot.ex_pending(ex_gid[gid])
                               or (ex_gid[gid] == "upbit" and (sym in self.spot.upbit_krw
                                                               or (sym in self.spot.upbit_alt
                                                                   and sym not in (getattr(self.spot, "upbit_alt_miss", None) or ()))))):
                    pending_gids.add(gid)
                if not px and ex_gid[gid] == "upbit" and gid not in pending_gids and pre_mkt9(sym):
                    pp9, ps9, pa9, pk9, pn9 = pre_px9(gid, sym, qty)
                    if pp9:
                        px, src9, age9 = pp9, ps9, pa9
                        pre_used9[gid] = (ps9, pk9, pp9, pn9)
            elif gid in native_kind9 and has_ca and self.spot.price(sym):
                px = self.spot.price(sym)
                src9, age9 = "cex:글로벌", glob_age9(sym)
            elif cex_px:
                px = cex_px
                src9 = f"cex:{fx_name.get(cex_ex, cex_ex)}"
                age9 = self.spot.ex_age(cex_ex, cex_cur)
            elif dex_px:
                px = dex_px
                src9 = "dex:" + self.spot.dex_src.get(f"{dex_key[0]}:{dex_key[1]}", "gecko")
                age9 = self.spot.dex_age(*dex_key)
            elif has_ca:
                px = 0
                m9p = spamguard.major_of(sym) if gid_pairs.get(gid) and all(
                    spamguard.is_genuine(c9, a9) for c9, a9 in gid_pairs[gid]) else None
                if m9p and m9p not in STABLE_GROUPS:
                    ms9 = {"WETH": "ETH", "WBTC": "BTC", "WBNB": "BNB", "WSOL": "SOL", "WPOL": "POL"}.get(m9p, m9p)
                    px = self.spot.price(ms9) or 0
                    if px:
                        src9, age9 = "cex:글로벌", glob_age9(ms9)
                if not px and any(self.spot.dex_pending(ch2, ca2) for ch2, ca2 in gid_pairs.get(gid, [])):
                    pending_gids.add(gid)
            elif sym in STABLE_GROUPS:
                px = 0
            else:
                px = self.spot.price(sym) or 0
                src9, age9 = "cex:글로벌", glob_age9(sym)
                if not px:
                    px = _px_recent(self.px, sym, int(now * 1000)) or 0
                    if _px_took(self.px):
                        px_wait9.add(gid)
                    age9 = None
            live_px[gid] = px
            if cex_px and px == cex_px and dex_px and dex_key and gid in live and gid not in quarantined:
                rv5 = self.spot.dex_reserve(*dex_key)
                ag5 = self.spot.dex_age(*dex_key)
                if rv5 is not None and rv5 >= self.spot.min_reserve_usd and ag5 is not None and ag5 <= 2 * Spot.GT_PROOF_EVERY \
                        and abs(cex_px - dex_px) / min(cex_px, dex_px) > Spot.PROOF_DIVERGE:
                    proof_div9.append({"gid": gid, "sym": sym, "ex": cex_ex, "cex": cex_px, "dex": dex_px, "res": round(rv5),
                                       "pair": f"{dex_key[0]}:{dex_key[1]}", "diff": round(dex_px / cex_px - 1, 4),
                                       "usd": round(qty * cex_px, 2)})
            if gid in live and gid not in quarantined and gid_pairs.get(gid) and qty > 0:
                for ch2, ca2 in gid_pairs[gid]:
                    lp9 = self.spot.dex_usd.get(f"{ch2}:{ca2}") or px or 0
                    hold_prio[(ch2, ca2)] = max(hold_prio.get((ch2, ca2), 0.0), float(lp9 or 0) * qty)
            if gid in pre_used9 and pre_used9[gid][1] and gid in live and gid not in quarantined and qty > 0:
                hold_prio[pre_used9[gid][1]] = max(hold_prio.get(pre_used9[gid][1], 0.0), float(px or 0) * qty)
            if gid not in live:
                continue
            if gid in quarantined:
                spam_view.append((gid, g, qty, px))
                continue
            dsym9 = None
            if sym == "TOKEN" and gid_pairs.get(gid):
                meta_want9.update(gid_pairs[gid])
                dsym9 = meta_sym9(gid)
            row = {"key": f"g{gid}", "sym": dsym9 or sym,
                   "name": (dsym9 or sym) + (" · " + "/".join(sorted(CHAIN_NAME.get(c, c) for c in g["chains"]))),
                   "qty": qty, "price": px, "avg": avg,
                   "kqty": float(min(qty_dec, k_all)),
                   "fbQty": _f(max(float(qty) - float(k_all), 0.0), 6) or 0,
                   "fbCost": _f(max(float(qty) - float(k_all), 0.0) * avg, 2) if (fb_on and avg > 0) else 0,
                   "locs": locs_for(gid, uncred)}
            if src9 and px:
                row["pxSrc"] = src9
                if src9.startswith("dex:") and dex_key and dex_key[0] in self.spot.off_chains:
                    row["pxFrozen"] = True
                if age9 is not None:
                    row["pxAge"] = int(max(0, age9))
                if gid in pre_used9:
                    row["pxPre"] = 1
                    if pre_used9[gid][3]:
                        row["pxPreN"] = pre_used9[gid][3]
                    pk9 = pre_used9[gid][1]
                    if pk9 and pk9[0] in self.spot.off_chains:
                        row["pxFrozen"] = True
            if gid_pairs.get(gid) and qty * (px or 0) >= 1:
                row["ck"], row["ca"] = gid_pairs[gid][0][0], gid_pairs[gid][0][1]
            if dsym9:
                row["symSrc"] = "dexscreener"
            if not px and qty > 0 and gid in ex_gid:
                rf9 = ref_px9(sym, ex_gid[gid])
                if rf9:
                    row["pxRef"] = rf9
            if not px and qty > 0:
                gk9 = [f"{c9}:{a9}" for c9, a9 in gid_pairs.get(gid) or () if f"{c9}:{a9}" in self.spot.guarded]
                if gk9:
                    row["guard"] = 1
                    guard_held9.update(gk9)
                    if not row.get("ca"):
                        ck9, ca9 = gk9[0].split(":", 1)
                        row["ck"], row["ca"] = ck9, ca9
            coins.append(row)
            if not px and qty > 0:
                unpriced.append(dsym9 or sym)
                unpriced_w.append({"sym": dsym9 or sym, "qty": float(qty), "cost": float(avg) * float(qty) if avg else 0.0,
                                   "ref": float((row.get("pxRef") or {}).get("px") or 0) * float(qty),
                                   "where": fx_name.get(ex_gid.get(gid), ex_gid.get(gid)) if gid in ex_gid else "지갑"})

        self.spot.set_token_prio(hold_prio, skip=cex_px_pairs,
                                 slow={p9 for gid9 in quarantined for p9 in gid_pairs.get(gid9, ())}, meta_want=meta_want9)
        self.spot.proof_div = proof_div9
        new_div9 = {d9["gid"] for d9 in proof_div9} - set(self.__dict__.get("_proof_div_seen") or ())
        for d9 in proof_div9:
            if d9["gid"] in new_div9:
                log.warning("증명 거래소 시세 교차검증 괴리: %s g%s %s $%.6g vs DEX %s $%.6g (%+.0f%%, 풀 유동성 $%s, 보유 $%s)",
                            d9["sym"], d9["gid"], d9["ex"], d9["cex"], d9["pair"], d9["dex"], d9["diff"] * 100,
                            f"{d9['res']:,}", f"{d9['usd']:,.0f}")
        self.__dict__["_proof_div_seen"] = {d9["gid"] for d9 in proof_div9}
        for g9 in sorted(set(pre_used9) - set(self.__dict__.get("_pre_seen") or ())):
            log.info("거래 시작 전 평가: g%s %s — 업비트 마켓 없음 → %s $%.6g (%s)", g9, (G.get(g9) or {}).get("sym"), pre_used9[g9][0], pre_used9[g9][2],
                     ("입출금 증명 g" + ",".join(str(o9) for o9 in pre_og9[g9])) if pre_og9.get(g9) else f"증명 없음 · 거래소 {pre_used9[g9][3]}곳 일치")
        self.__dict__["_pre_seen"] = set(pre_used9)
        self._live_px = dict(live_px)
        okx_thresh = float((self.cfg.get("okx_dex") or {}).get("krw_threshold", 1_000_000))
        rate_now = self.spot.rate or 1400
        big_pairs = []
        for c2 in coins:
            if (c2.get("price") or 0) * c2["qty"] * rate_now >= okx_thresh \
                    and c2["key"].startswith("g") and c2["key"][1:].isdigit():
                big_pairs += gid_pairs.get(int(c2["key"][1:]), [])
        self.spot.want_okx(big_pairs)

        for cur4, q4 in sorted(ub_coins.items()):
            if q4 <= 0:
                continue
            entry = {"key": f"ub:{cur4}", "sym": cur4, "name": f"{cur4} · 업비트",
                     "qty": q4, "avg": 0,
                     "locs": [{"w": "업비트", "sub": "거래소 잔고 (실시간)", "qty": q4}]}
            if cur4 in STABLE_GROUPS:
                entry.update({"price": 1, "avg": 1})
                stables.append(entry)
            else:
                self.spot.want([cur4])
                entry["price"] = self.spot.ex_price("upbit", cur4) or 0
                if entry["price"]:
                    entry["pxSrc"] = f"cex:{fx_name.get('upbit', '업비트')}"
                    ag9 = self.spot.ex_age("upbit", cur4)
                    if ag9 is not None:
                        entry["pxAge"] = int(max(0, ag9))
                if not entry["price"]:
                    rf9 = ref_px9(cur4, "upbit")
                    if rf9:
                        entry["pxRef"] = rf9
                coins.append(entry)
                if not entry["price"]:
                    unpriced.append(cur4)
                    unpriced_w.append({"sym": cur4, "qty": float(q4), "cost": 0.0,
                                       "ref": float((entry.get("pxRef") or {}).get("px") or 0) * float(q4), "where": "업비트"})

        rb_view, rb_debts = None, []
        try:
            rb_st = rabby.load_state(RABBY_PATH)
            if (rb_st.get("wallets") or {}):
                known9 = set()
                for ch9, ad9, kd9 in conn.execute("SELECT chain, address, kind FROM assets"):
                    known9.add((ch9, rabby.ZERO if kd9 == "native" else str(ad9 or "").lower()))
                for ch9, (mca9, _sc9) in common.NATIVE_MIRROR.items():
                    known9.add((ch9, mca9))
                held9 = set()
                priced9 = {}
                row_px9 = {c9["key"]: float(c9.get("price") or 0) for c9 in coins + stables}
                for gid9, lr9 in locs_by_gid.items():
                    px9 = row_px9.get(f"g{gid9}", 0.0)
                    sym9 = str((G.get(gid9) or {}).get("sym") or "").upper()
                    for l9 in lr9:
                        p9 = str(l9["location"] or "").split(":")
                        if p9[0] != "wallet" or len(p9) < 3 or not p9[2]:
                            continue
                        held9.add((p9[1], p9[2].lower()))
                        u9 = float(Decimal(l9["qty_norm"])) * px9
                        if u9 > 0:
                            priced9.setdefault((p9[1], p9[2].lower()), []).append((sym9, u9))
                lp_ids9 = set()
                lpf9 = common.read_json(LP_POS_PATH, {}) or {}
                for loc9 in list((lpf9.get("positions") or {}).keys()) + [l9 for _g9, l9, _q9 in lp_pos_rows]:
                    p9 = str(loc9).split(":")
                    if len(p9) >= 4:
                        lp_ids9.add((p9[1], p9[3]))
                        if p9[3].startswith("0x") and len(p9[3]) == 42 and p9[2].startswith("0x"):
                            known9.add((p9[1], p9[2].lower()))

                def rb_spam9(sym9, bc9, ca9):
                    why9 = _scam_name(sym9)
                    if why9:
                        return why9
                    ca9 = str(ca9 or "").lower()
                    if bc9 and ca9.startswith("0x") and len(ca9) == 42 and spamguard.major_of(sym9) \
                            and not spamguard.is_genuine(bc9, ca9):
                        return "가짜 대표 심볼(정품 CA 아님)"
                    return None
                labels9 = {a9: (aliases.get(a9) or self.addr_label.get(a9) or a9[:8]) for a9 in rabby.evm_wallets(self.cfg, include_disabled=True)}
                watch9 = set(rabby.watch_addrs(rb_st, list(labels9), self.__dict__.get("_bot_wallet_usd"), rabby.settings(self.cfg)["min_wallet_usd"]))
                labels9 = {a9: l9 for a9, l9 in labels9.items() if a9 in watch9}
                try:
                    import hl_spot
                    hl9 = hl_spot.known_addresses(self.cfg)
                except Exception:
                    hl9 = set()
                rb_view = rabby.merge(rb_st, resolve=rabby.chain_resolver(self.cfg, rb_st),
                                      wallet_chains_set=rabby.wallet_chains(self.cfg), known_pairs=known9, held_chains=held9,
                                      lp_ids=lp_ids9, priced_held=priced9, spam_fn=rb_spam9, labels=labels9,
                                      chain_names=CHAIN_NAME, now=now, min_usd=rabby.settings(self.cfg)["min_usd"],
                                      only_addrs=set(labels9),
                                      skip_proto=(lambda a9, p9, n9: "Hyperliquid 현물 원장에 반영" if (str(a9).lower() in hl9
                                                                                                and rabby.hl_proto(p9, n9)) else None))
                coins.extend(rabby.rows_for(rb_view, labels9, now))
                rb_debts = rabby.debt_rows(rb_view, labels9)
                rb_view["labels"] = labels9
                rb_view["state"] = {"backoffUntil": rb_st.get("backoffUntil"), "lastErr": rb_st.get("lastErr"),
                                    "calls": rb_st.get("calls"), "enabled": rabby.settings(self.cfg)["enabled"],
                                    "minUsd": rabby.settings(self.cfg)["min_wallet_usd"]}
        except Exception as e9:
            log.warning("Rabby 보강 실패(봇 숫자만 표시): %s", e9)
            rb_view, rb_debts = None, []
        rb_net = round((rb_view or {}).get("onlyUsd", 0.0) + sum(d9["usd"] for d9 in rb_debts), 2)

        grp4r = {}
        for e4r in fx_transit.values():
            st4r, fl4r = e4r.get("story"), e4r.get("story_flow")
            if st4r and fl4r is not None:
                grp4r.setdefault(id(fl4r), (fl4r, []))[1].append(st4r)
                e4r["story"] = []
        for fl4r, sts4r in grp4r.values():
            cat4r = []
            for st4r in reversed(sts4r):
                cat4r += st4r
            fl4r["events"] = sorted(cat4r + fl4r["events"], key=lambda e9: (e9.get("_ts") or 0, e9["t"]))

        d9j = prefs.get("dust_usd")
        try:
            dust_ev = 1.0 if d9j is None else max(0.0, float(d9j or 0))
        except (TypeError, ValueError):
            dust_ev = 1.0
        xfer_k9 = ("전송", "외부 전송", "입금 확인")
        stab_sym9 = set(STABLE_GROUPS) | {"FDUSD", "TUSD", "USDP", "PYUSD", "USD1", "USDS", "USD", "RLUSD"}

        def ev_usd(r9, g9):
            qn = abs(float(self._norm(r9)))
            if g9.get("is_stable"):
                return qn
            px9 = live_px.get(g9["gid"])
            if not px9 and not g9.get("is_fiat"):
                pairs9 = gid_pairs_all.get(g9["gid"]) or []
                if not pairs9:
                    px9 = self.spot.price(g9["sym"])
                elif all(spamguard.is_genuine(c9, a9) for c9, a9 in pairs9) and spamguard.major_of(g9["sym"]):
                    m9 = spamguard.major_of(g9["sym"])
                    px9 = self.spot.price({"WETH": "ETH", "WBTC": "BTC", "WBNB": "BNB", "WSOL": "SOL", "WPOL": "POL"}.get(m9, m9))
            then9 = float(r9["cost_usd"]) if (r9["cost_usd"] is not None and float(r9["cost_usd"]) > 0) else None
            if px9:
                return max(qn * float(px9), then9 or 0.0)
            return then9

        def ev_hide(e9):
            r9 = pid_row.get(e9.get("_pid"))
            if r9 is not None:
                if (r9["source_ns"], r9["source_id"], r9["asset_id"]) in spoof_keys:
                    return "scam", "가짜 전송 — 내가 서명하지 않은 tx 로 보유한 적 없는 수량을 '보냄'(주소 오염)"
                if int(r9["qty_base"]) == 0:
                    return "scam", "수량 0 전송(주소 오염)"
            if e9.get("k") not in xfer_k9 or dust_ev <= 0:
                return None
            if r9 is not None:
                g9 = G.get(r9["group_id"] or -r9["asset_id"]) or {}
                if not g9:
                    return None
                usd9 = ev_usd(r9, g9)
            else:
                try:
                    qn9 = abs(float(str(e9.get("q") or "").replace(",", "")))
                except ValueError:
                    return None
                s9 = str(e9.get("sym") or "").upper()
                px9 = 1.0 if s9 in stab_sym9 else (self.spot.ex_price("upbit", s9) or self.spot.price(s9))
                usd9 = qn9 * float(px9) if px9 else None
            if usd9 is None or usd9 >= dust_ev:
                return None
            if r9 is not None and r9["leg_kind"] == "acq" and r9["event"] in ("TRANSFER_IN", "PROGRAM_IN") and usd9 < 0.01:
                s9 = signer9.get((r9["source_ns"], r9["source_id"]))
                if not (s9 and spamguard.signer_mine(*s9, my_all9)):
                    return "scam", f"주소 오염 의심 초소액 수령 (${usd9:.4f})"
            return "dust", f"소액 ${usd9:,.2f} (기준 ${dust_ev:g} 미만)"

        pos_hid9 = []

        disp9 = {}
        for gid9, g9 in G.items():
            if g9.get("sym") == "TOKEN" and gid9 not in quarantined and gid_pairs.get(gid9):
                s9 = meta_sym9(gid9)
                if s9:
                    disp9[gid9] = s9
        positions = []
        pos_ev_full = []
        stab_ev = []
        for gid, g in sorted(G.items(), key=lambda kv: -(kv[1]["flows"][-1]["opened"] if kv[1]["flows"] else 0)):
            if g.get("is_fiat"):
                continue
            if g["is_stable"] or gid in quarantined:
                if g["is_stable"] and gid not in quarantined:
                    for fl in g["flows"]:
                        stab_ev.append((f"s{gid}", g["sym"], "스테이블 환전", fl["events"]))
                if gid in quarantined and not g["is_stable"]:
                    for fl in g["flows"]:
                        for e9 in fl["events"]:
                            pos_hid9.append(dict(e9, sym=g["sym"], _gid=gid, hide=g.get("risk_reason") or "격리(스팸) 자산", hideKind="scam"))
                rbd_s, ubd_s, sbd_s, rbdk_s, pbd_s = {}, {}, {}, {}, {}
                for fl in g["flows"]:
                    for k9, v9 in fl["rbd"].items():
                        rbd_s[k9] = rbd_s.get(k9, 0.0) + float(v9)
                    for k9, v9 in fl["rbdk"].items():
                        rbdk_s[k9] = rbdk_s.get(k9, 0.0) + float(v9)
                    for k9, v9 in fl["ubd"].items():
                        u9 = ubd_s.setdefault(k9, [0, 0.0]); u9[0] += v9[0]; u9[1] += float(v9[1])
                    for d9 in fl["sold_dates"]:
                        a9 = sbd_s.setdefault(d9, [0, 0]); a9[1] += 1
                    for d9 in fl.get("pay_dates") or ():
                        pbd_s[d9] = pbd_s.get(d9, 0) + 1
                rbd_s = {k9: round(v9, 2) for k9, v9 in sorted(rbd_s.items()) if abs(v9) >= 0.005}
                if not (rbd_s or ubd_s):
                    continue
                o9 = min(fl["opened"] for fl in g["flows"])
                positions.append({
                    "realizedByDay": rbd_s, "actByDay": sbd_s, "payByDay": dict(sorted(pbd_s.items())),
                    "realizedKrwByDay": {k9: round(v9) for k9, v9 in sorted(rbdk_s.items()) if k9 in rbd_s},
                    "unvByDay": {k9: [v9[0], round(v9[1], 2)] for k9, v9 in sorted(ubd_s.items())},
                    "_gid": gid, "kind": "stable" if g["is_stable"] else "quarantined",
                    "unknownQty": 0, "fbAvg": 0, "fbCost": 0,
                    "unvQty": _f(float((unverified.get(gid) or {}).get("qty") or 0), 6) or 0,
                    "unvProceeds": _f(sum(v9[1] for v9 in ubd_s.values()), 2) or 0, "realizedFb": 0,
                    "soldProceeds": 0, "avgSell": 0, "avgKrw": 0, "avgSellKrw": 0, "costKrw": 0, "soldProceedsKrw": 0,
                    "key": f"s{gid}", "sym": g["sym"], "chain": "스테이블 환전" if g["is_stable"] else "격리 자산",
                    "status": "종료", "held": 0, "bought": 0, "movedQty": 0, "movedCost": 0, "soldQty": 0,
                    "avg": 0, "cost": 0, "realized": _f(sum(rbd_s.values()), 2) or 0, "unreal": 0,
                    "opened": datetime.fromtimestamp(o9, KST).strftime("%m-%d"), "_ots": o9, "fee": "$0.00",
                    "realizedKrw": round(sum(v9 for k9, v9 in rbdk_s.items() if k9 in rbd_s)),
                    "steps": ["스테이블 환전 차익" if g["is_stable"] else "격리 자산 매도"], "events": [],
                })
                continue
            px = live_px.get(gid) or 0
            total_flows = len(g["flows"])
            k_all = g["qty_known"] + uncred_known.get(gid, Decimal(0))
            c_all = g["cost"] + uncred_cost.get(gid, Decimal(0))
            fl_ref9 = g["cur"] if g["cur"] in g["flows"] else (g["flows"][-1] if g["flows"] else None)
            ref_avg9 = 0.0
            if fl_ref9 is not None:
                ref_avg9 = float(c_all / k_all) if (fl_ref9 is g["cur"] and k_all > EPS) \
                    else (float(fl_ref9["cost"] / fl_ref9["bought"]) if fl_ref9["bought"] > 0 else 0.0)
            for i, fl in enumerate(g["flows"]):
                if fl["events"]:
                    vis9 = []
                    for e9 in fl["events"]:
                        h9 = ev_hide(e9)
                        if h9:
                            pos_hid9.append(dict(e9, sym=disp9.get(gid) or g["sym"], _gid=gid, hide=h9[1], hideKind=h9[0]))
                        else:
                            vis9.append(e9)
                    fl["events"] = vis9
                active = (g["cur"] is fl)
                held = float(led_by_gid.get(gid, Decimal(0)) + uncred_gid.get(gid, Decimal(0))) if active else 0
                held_known = min(held, float(k_all))
                bought = float(fl["bought"])
                if bought <= 0 and not fl["events"] and not (fl["rbd"] or fl["ubd"]):
                    continue
                avg = float(c_all / k_all) if (active and k_all > EPS) \
                    else (float(fl["cost"] / fl["bought"]) if fl["bought"] > 0 else 0)
                status = "보유" if active and fl["realized"] - fl.get("pay_real", Decimal(0)) == 0 else \
                         ("부분 매도" if active else "종료")
                if active and not held > 0:
                    status = "종료"
                steps = ["거래소 매수" if any(e["k"] == "거래소 매수" for e in fl["events"])
                         else ("토큰 세일 매수" if any(e["k"] == "세일 매수" for e in fl["events"]) else "온체인 매수")]
                if any(e["k"] == "전송" and "업비트" in e["d"] for e in fl["events"]):
                    steps.append("거래소 입금")
                if fl["realized"] - fl.get("pay_real", Decimal(0)) != 0 or fl["sold_dates"]:
                    steps.append("전량 매도" if not active else "매도 진행")
                unreal = held_known * (px - avg) if (px and active and avg > 0) else 0
                unk_q = max(0.0, held - held_known)
                fb_avg = avg if (fb_on and avg > 0) else 0.0
                fb_cost = unk_q * fb_avg if fb_avg else 0.0
                if fb_avg and px and active and unk_q > 0:
                    unreal += unk_q * (px - fb_avg)
                fl_ub9 = fl["ubd"]
                u_fb = ({"qty": sum((fl.get("ubq") or {}).values(), Decimal(0)),
                         "proceeds": sum((v9[1] for v9 in fl_ub9.values()), Decimal(0)),
                         "by_date": {d9: {"qty": (fl.get("ubq") or {}).get(d9, Decimal(0)), "proceeds": v9[1]} for d9, v9 in fl_ub9.items()}}
                        if fl_ub9 and gid in unverified else None)
                fbr9 = ref_avg9 if (fb_on and ref_avg9 > 0) else 0.0
                unv_q = float(u_fb["qty"]) if u_fb else 0.0
                unv_p = float(u_fb["proceeds"]) if u_fb else 0.0
                realized_fb = (unv_p - unv_q * fbr9) if (u_fb and fbr9) else 0.0
                rbd_c = {k9: float(v9) for k9, v9 in fl["rbd"].items()}
                rbdk_c = {k9: float(v9) for k9, v9 in fl["rbdk"].items()}
                if u_fb and fbr9:
                    for dk_f, ud_f in sorted((u_fb.get("by_date") or {}).items()):
                        pnl_f = float(ud_f["proceeds"]) - float(ud_f["qty"]) * fbr9
                        rt_f, rsrc_f = fxb.rate_src(int(datetime.strptime(dk_f + " 23:59", "%Y-%m-%d %H:%M").replace(tzinfo=KST).timestamp()))
                        realized_by_date[dk_f] = realized_by_date.get(dk_f, 0) + pnl_f
                        realized_krw_by_date[dk_f] = realized_krw_by_date.get(dk_f, 0) + pnl_f * rt_f
                        uf9 = unv_fb9.setdefault(dk_f, {}).setdefault(gid, [Decimal(0), Decimal(0)])
                        uf9[0] += Decimal(ud_f["qty"])
                        uf9[1] += Decimal(ud_f["proceeds"])
                        rbd_c[dk_f] = rbd_c.get(dk_f, 0.0) + pnl_f
                        rbdk_c[dk_f] = rbdk_c.get(dk_f, 0.0) + pnl_f * rt_f
                        tax_rows.append({"sold": dk_f, "sym": g["sym"], "ticker": g["sym"], "ex": "평균가 폴백",
                                         "qty": _f(float(ud_f["qty"]), 4), "acq": _f(float(ud_f["qty"]) * fbr9, 2),
                                         "disp": _f(float(ud_f["proceeds"]), 2), "fee": 0, "rate": round(rt_f, 4), "rateSrc": rsrc_f,
                                         "_acq": float(ud_f["qty"]) * fbr9, "_disp": float(ud_f["proceeds"]), "_qty": float(ud_f["qty"])})
                sold_q = float(fl["sold"]); proceeds_f = float(fl.get("proceeds", Decimal(0)))
                act_c = {}
                src_c = {}
                pay_c = {}
                for e9 in fl["events"]:
                    k9 = e9["k"]
                    j9 = 1 if "매도" in k9 else (0 if "매수" in k9 else -1)
                    if j9 == 1 and e9.get("_pay"):
                        j9 = -1
                        dk9p = acct_norm.iso_day(e9["_ts"]) if e9.get("_ts") else e9["t"][:5]
                        pay_c[dk9p] = pay_c.get(dk9p, 0) + 1
                    dk9 = acct_norm.iso_day(e9["_ts"]) if e9.get("_ts") else e9["t"][:5]
                    if j9 >= 0:
                        a9 = act_c.setdefault(dk9, [0, 0])
                        a9[j9] += 1
                    if k9 != "평단 갱신":
                        c9 = src_c.setdefault(e9.get("src") or "", {}).setdefault(dk9, [0, 0, 0, 0])
                        c9[0] += 1
                        if j9 >= 0:
                            c9[1 + j9] += 1
                        if k9 == "입금 확인":
                            c9[3] += 1
                rbd_o = {k9: round(v9, 2) for k9, v9 in sorted(rbd_c.items())
                         if abs(v9) >= 0.005 or abs(rbdk_c.get(k9, 0.0)) >= 0.5}
                positions.append({
                    "realizedByDay": rbd_o,
                    "realizedKrwByDay": {k9: round(v9) for k9, v9 in sorted(rbdk_c.items()) if k9 in rbd_o},
                    "realizedKrw": round(sum(v9 for k9, v9 in rbdk_c.items() if k9 in rbd_o)),
                    "actByDay": act_c, "srcAct": src_c, "evN": len(fl["events"]),
                    "payByDay": pay_c,
                    "paidQty": _f(fl.get("paid", Decimal(0)), 6) or 0, "paidUsd": _f(fl.get("paid_usd", Decimal(0)), 2) or 0,
                    "payReal": _f(fl.get("pay_real", Decimal(0)), 2) or 0,
                    "unvByDay": {k9: [v9[0], round(float(v9[1]), 2)] for k9, v9 in sorted(fl["ubd"].items())},
                    "_gid": gid, "_act": active,
                    "unknownQty": _f(unk_q, 6) or 0, "fbAvg": _f(fbr9 if (u_fb and fbr9) else fb_avg, 6) or 0, "fbCost": _f(fb_cost, 2) or 0,
                    "unvQty": _f(unv_q, 6) or 0, "unvProceeds": _f(unv_p, 2) or 0, "realizedFb": _f(realized_fb, 2) or 0,
                    "soldProceeds": _f(proceeds_f, 2) or 0,
                    "avgSell": _f(proceeds_f / sold_q, 6) if sold_q > 0 else 0,
                    "avgKrw": _f(float(fl.get("cost_krw", 0)) / bought, 4) if bought > 0 else 0,
                    "avgSellKrw": _f(float(fl.get("proceeds_krw", 0)) / sold_q, 4) if sold_q > 0 else 0,
                    "costKrw": _f(float(fl.get("cost_krw", 0)), 0) or 0,
                    "soldProceedsKrw": _f(float(fl.get("proceeds_krw", 0)), 0) or 0,
                    "key": f"g{gid}" if active else f"g{gid}f{i}",
                    "sym": disp9.get(gid) or g["sym"], "chain": self._flow_chain(fl),
                    **({"symSrc": "dexscreener"} if gid in disp9 else {}),
                    "realizedChainByDay": {d9: " · ".join(sorted(v9)) for d9, v9 in (fl.get("rch") or {}).items()},
                    "status": status, "held": held, "bought": bought,
                    "movedQty": _f(fl["moved_qty"], 6) or 0,
                    "movedCost": _f(fl["moved_cost"], 2) or 0,
                    **({"movedTo": [[k9, _f(v9[0], 6), bool(v9[1])] for k9, v9 in sorted(fl["mv_to"].items(), key=lambda x9: -x9[1][0])]} if fl.get("mv_to") else {}),
                    **({"inFrom": [[k9, _f(v9[0], 6), _f(v9[1], 2), round(v9[2])] for k9, v9 in sorted(fl["in_from"].items(), key=lambda x9: -x9[1][0])]} if fl.get("in_from") else {}),
                    "nBuy": fl.get("nb", 0),
                    "soldQty": _f(fl["sold"], 6) or 0,
                    "lpConvQty": _f(fl.get("lpconv", Decimal(0)), 6) or 0,
                    "avg": _f(avg, 6) or 0, "cost": _f(fl["cost"], 2) or 0,
                    "realized": _f(fl["realized"], 2) or 0,
                    "unreal": _f(unreal, 2) or 0,
                    "opened": datetime.fromtimestamp(fl["opened"], KST).strftime("%m-%d"),
                    "_ots": fl["opened"],
                    "fee": f"${float(fl['fee']):,.2f}",
                    "steps": steps, "events": [{k9: v9 for k9, v9 in e9.items() if not k9.startswith("_")} for e9 in fl["events"][-(60 + min(100, fl.get("story_n", 0))):]],
                    "dust": bool(active and held > 0 and px and held * px < dust_ev),
                })
                if fl.get("oa_sold"):
                    positions[-1]["offcA"] = {"qty": _f(fl["oa_sold"], 6) or 0, "realized": _f(fl.get("oa_real", Decimal(0)), 2) or 0}
                pos_ev_full.append((positions[-1]["key"], positions[-1]["sym"], positions[-1]["chain"], fl["events"]))
        if gas_expense:
            gx_rbd = {k9: round(-float(v9[0]), 2) for k9, v9 in sorted(gas_expense.items())}
            gx_o = min(int(datetime.strptime(k9, "%Y-%m-%d").replace(tzinfo=KST).timestamp()) for k9 in gas_expense)
            positions.append({
                "realizedByDay": gx_rbd, "actByDay": {}, "unvByDay": {},
                "realizedKrwByDay": {k9: round(-v9[2]) for k9, v9 in sorted(gas_expense.items())},
                "_gid": None, "kind": "gas", "unknownQty": 0, "fbAvg": 0, "fbCost": 0, "unvQty": 0, "unvProceeds": 0, "realizedFb": 0,
                "soldProceeds": 0, "avgSell": 0, "avgKrw": 0, "avgSellKrw": 0, "costKrw": 0, "soldProceedsKrw": 0,
                "key": "sgas", "sym": "가스 비용", "chain": "매매 외 가스(실패·승인·전송·브릿지·LP)",
                "status": "종료", "held": 0, "bought": 0, "movedQty": 0, "movedCost": 0, "soldQty": 0,
                "avg": 0, "cost": 0, "realized": round(-float(sum(v9[0] for v9 in gas_expense.values())), 2), "unreal": 0,
                "opened": datetime.fromtimestamp(gx_o, KST).strftime("%m-%d"), "_ots": gx_o,
                "fee": f"${float(sum(v9[0] for v9 in gas_expense.values())):,.2f}",
                "realizedKrw": round(-sum(v9[2] for v9 in gas_expense.values())),
                "steps": ["가스 비용"], "events": []})
            for k9, v9 in sorted(gas_expense.items()):
                tax_rows.append({"sold": k9, "sym": "가스", "ticker": "GAS", "ex": "기타 비용(가스)", "qty": 0, "acq": 0, "disp": 0,
                                 "fee": _f(v9[0], 2), "rate": round(v9[2] / float(v9[0]), 4) if v9[0] > 0 else 0,
                                 "_fee": float(v9[0]), "tx": v9[1]})
        if stake_inc:
            sk_rbd = {k9: round(float(sum(v9[0] for v9 in d9.values())), 2) for k9, d9 in sorted(stake_inc.items())}
            sk_o = min(int(datetime.strptime(k9, "%Y-%m-%d").replace(tzinfo=KST).timestamp()) for k9 in stake_inc)
            sk_syms = sorted({s9 for d9 in stake_inc.values() for s9 in d9})
            positions.append({
                "realizedByDay": sk_rbd, "actByDay": {}, "unvByDay": {},
                "realizedKrwByDay": {k9: round(sum(v9[3] for v9 in d9.values())) for k9, d9 in sorted(stake_inc.items())},
                "rwdByDay": {k9: sum(v9[2] for v9 in d9.values()) for k9, d9 in sorted(stake_inc.items())},
                "_gid": None, "kind": "stake", "unknownQty": 0, "fbAvg": 0, "fbCost": 0, "unvQty": 0, "unvProceeds": 0, "realizedFb": 0,
                "soldProceeds": 0, "avgSell": 0, "avgKrw": 0, "avgSellKrw": 0, "costKrw": 0, "soldProceedsKrw": 0,
                "key": "sstake", "sym": "스테이킹 보상", "chain": " · ".join(sk_syms) + " 스테이킹(에폭 보상·MEV 팁)",
                "status": "종료", "held": 0, "bought": 0, "movedQty": 0, "movedCost": 0, "soldQty": 0,
                "avg": 0, "cost": 0, "realized": round(float(sum(v9[0] for d9 in stake_inc.values() for v9 in d9.values())), 2), "unreal": 0,
                "opened": datetime.fromtimestamp(sk_o, KST).strftime("%m-%d"), "_ots": sk_o, "fee": "$0.00",
                "realizedKrw": round(sum(v9[3] for d9 in stake_inc.values() for v9 in d9.values())),
                "steps": ["스테이킹 보상"], "events": []})
            for k9, d9 in sorted(stake_inc.items()):
                for s9, v9 in sorted(d9.items()):
                    tax_rows.append({"sold": k9, "sym": s9, "ticker": s9, "ex": "스테이킹 보상", "qty": _f(float(v9[1]), 6), "acq": 0,
                                     "disp": _f(float(v9[0]), 2), "fee": 0,
                                     "rate": round(v9[3] / float(v9[0]), 4) if v9[0] > 0 else 0,
                                     "_acq": 0.0, "_disp": float(v9[0]), "tx": v9[2]})
        positions.sort(key=lambda p: (not p.get("_act"), -p["_ots"]))
        _pos_all_dbg = positions if os.environ.get("TJ_REPLAY_DEBUG") == "1" else None
        head9 = positions[:400]
        syms9 = {acct_norm.canon(p9["sym"]) for p9 in head9}
        tail9 = [p9 for p9 in positions[400:]
                 if p9.get("realizedByDay") or p9.get("unvByDay") or (p9.get("soldQty") or 0) > 0 or p9.get("actByDay")]
        syms9 |= {acct_norm.canon(p9["sym"]) for p9 in tail9}
        in9 = {id(p9) for p9 in tail9}
        tail9 += [p9 for p9 in positions[400:] if id(p9) not in in9 and (p9.get("movedQty") or 0) > 0 and acct_norm.canon(p9["sym"]) in syms9]
        pos_cut9 = {"total": len(positions), "kept": len(head9) + len(tail9), "dropped": len(positions) - len(head9) - len(tail9)}
        positions = head9 + sorted(tail9, key=lambda p9: -p9["_ots"])
        for p9 in positions:
            p9.pop("_act", None)
        if _pos_all_dbg is None:
            for p9 in positions:
                p9.pop("_gid", None)

        ca_all = {r10["group_id"] for r10 in conn.execute(
            "SELECT DISTINCT group_id FROM assets WHERE kind='token'"
            " AND address IS NOT NULL AND group_id IS NOT NULL").fetchall()}
        native_c9 = set()
        for gid9 in sorted(native_kind9 & ca_all):
            g9 = G.get(gid9)
            prs9 = gid_pairs_all.get(gid9) or []
            m9 = spamguard.major_of(g9["sym"]) if g9 else None
            if prs9 and m9 and m9 == str(g9["sym"]).upper() and m9 not in STABLE_GROUPS \
                    and all(spamguard.is_genuine(c9, a9) for c9, a9 in prs9):
                native_c9.add(gid9)
        ca_all -= native_c9
        ex_c9 = set()
        for gid9 in sorted(ex_gid):
            g9 = G.get(gid9)
            m9 = spamguard.major_of(g9["sym"]) if g9 else None
            if g9 and str(g9["sym"]).upper() in EX_CANDLE_SYMS and not g9.get("is_stable") and not g9.get("is_fiat"):
                ex_c9.add(gid9)
                continue
            if (m9 and m9 == str(g9["sym"]).upper() and "USD" not in m9 and m9 != "DAI"
                    and not g9.get("is_stable") and not g9.get("is_fiat")):
                ex_c9.add(gid9)

        self._ph("cex_proof·prices")
        pendings = self._pendings(conn, prefs)
        ignored_u = set(prefs.get("ignored", []))
        UNK_HINT = ("내 지갑에서 보낸 거라면 설정 › 연결 · 키에서 그 지갑을 추가해 주세요 — 다음 재구축 때 원가가 자동으로 붙습니다. "
                    "에어드랍·타인 송금·LP 인출이라면 아래에서 개당 원가를 입력하거나 '당시 시세로 추정'을 누르세요.")

        def unk_cands(gid9, sym9, px9):
            srcs9 = list((G.get(gid9) or {}).get("unk_src") or [])
            if not srcs9:
                return []
            srcs9.sort(key=lambda x: -x["qty"])
            tot9 = sum(x["qty"] for x in srcs9) or 1.0
            expanded = []
            for x in srcs9[:6]:
                expanded.append((x, 0))
                ug = G.get(x.get("up_gid")) if x.get("up_gid") is not None else None
                for y in sorted((ug or {}).get("unk_src") or [], key=lambda z: -z["qty"])[:2]:
                    expanded.append((y, 1))
                    ug2 = G.get(y.get("up_gid")) if y.get("up_gid") is not None else None
                    for z in sorted((ug2 or {}).get("unk_src") or [], key=lambda w: -w["qty"])[:1]:
                        expanded.append((z, 2))
            out9 = []
            seen9 = set()
            for x, lvl in expanded:
                x = x if x.get("via") else resolve_origin(x)
                key_x = (lvl > 0, x.get("ref"), x.get("kind"))
                if key_x in seen9:
                    continue
                seen9.add(key_x)
                if len(out9) >= 12:
                    break
                ref = x.get("ref") or ""; frm = x.get("from"); dt9 = datetime.fromtimestamp(x["ts"], KST).strftime("%m-%d %H:%M")
                short = (ref[:8] + "…" + ref[-4:]) if len(ref) > 14 else ref
                if x.get("via"):
                    who = f" ← {x['via']}"; copy = ref; btn = "참조 복사" if ref else "—"
                elif frm and frm in wallet_label:
                    who = f" ← 내 지갑 {wallet_label[frm]} ({frm[:6]}…{frm[-4:]})"; copy = frm; btn = "주소 복사"
                elif frm:
                    who = f" ← 외부 지갑 {frm[:6]}…{frm[-4:]} (미등록 · 내 지갑이면 설정에 등록)"; copy = frm; btn = "주소 복사"
                elif ref.startswith("0x") and len(ref) == 66 and x.get("oc_na"):
                    who = (" ← 발신 조회 불가 (추적 체인에서 찾지 못함 · txid 로 직접 확인)" if x["oc_na"] == "notfound"
                           else f" ← 발신 조회 불가 (네트워크 미지원: {x['oc_na']} · txid 로 직접 확인)")
                    copy = ref; btn = "txid 복사"
                elif ref.startswith("0x") and len(ref) == 66 and x.get("oc_fail"):
                    who = f" ← 발신 조회 실패(재시도 {datetime.fromtimestamp(x['oc_fail'], KST).strftime('%m-%d')})"; copy = ref; btn = "txid 복사"
                elif ref.startswith("0x") and len(ref) == 66:
                    who = " ← 발신 지갑 조회 중"; copy = ref; btn = "txid 복사"
                else:
                    who = ""; copy = ref; btn = "참조 복사" if ref else "—"
                val9 = x["qty"] * float(px9 or 0)
                sym_x = (G.get(x.get("up_gid")) or {}).get("sym") if lvl and x.get("up_gid") is not None else sym9
                ov_txt = ""
                if x.get("ov"):
                    ov_txt = (f" · ★원가 지정 ${x['ov']['unit']:,.6g}/개 적용★" if x["ov"].get("mode") == "unit"
                              else f" · ★당시 시세 ${x['ov']['unit']:,.6g}/개 적용★")
                out9.append({"kind": "src", "label": ("↳ " * lvl) + (f"상류({sym_x or sym9}) " if lvl else "") + f"{dt9} {x['kind']} {x['qty']:,.4f}" + (f" · {short}" if short else "") + who
                             + (f" · 지금 평가 ${val9:,.0f}" if (val9 >= 1 and not lvl) else "") + ov_txt,
                             "score": (x.get("chain") or x.get("ex") or "—"),
                             "pct": (0 if lvl else min(100, int(round(100.0 * x["qty"] / tot9)))),
                             "copy": copy, "btn": btn})
            return out9
        _unk_rows = [c9 for c9 in coins if (c9.get("fbQty") or 0) > 0 and str(c9.get("key", "")).startswith("g")
                     and ((c9.get("fbCost") or 0) >= 50.0 or float(c9["fbQty"]) * float(c9.get("price") or 0) >= 50.0)]
        _unk_rows.sort(key=lambda c9: -(float(c9["fbQty"]) * float(c9.get("price") or 0)))
        for c9 in _unk_rows:
            gid9 = int(c9["key"][1:]) if c9["key"][1:].isdigit() else None
            key9 = f"unkh:{gid9 if gid9 is not None else c9['sym']}"
            if key9 in ignored_u:
                continue
            fb_ok = fb_on and (c9.get("fbCost") or 0) > 0
            pendings.insert(0, {
                "key": key9, "t": datetime.fromtimestamp(now, KST).strftime("%m-%d"),
                "kind": ("원가미상 보유 · 평균가 폴백 적용" if fb_ok else
                         ("원가미상 보유 (평균가 없음)" if fb_on else "원가미상 보유 (폴백 OFF · 손익 제외(평가 포함))")),
                "sym": c9["sym"], "chain": "—",
                "onchain": f"{float(c9['fbQty']):,.4f} {c9['sym']} 원가미상 보유"
                           + (f" · 평균 매수가 ${float(c9['avg']):,.6g} → 원가 ${float(c9['fbCost']):,.2f} 적용" if fb_ok else ""),
                "ex": "—",
                "gap": "실매수 기록 없는 유입분(미등록 지갑·OTC·에어드랍·미수집 체결)",
                "why": ("평가·손익에는 이 종목 평균 매수가로 원가를 잡아 반영했습니다. 실제 취득 경로(지갑 등록·체결 연동)가 확인되면 자동으로 정정됩니다."
                        if fb_ok else ("이 종목은 실매수 기록이 없어 평균가로 대체할 수도 없어요 — 평가·손익에서 빠져 있습니다." if fb_on else
                                       "원가 추적(지갑 등록·체결 연동)이 우선입니다. 설정의 '원가 미확인 → 평균가 대체'를 켜면 이 종목 평균 매수가로 원가를 잡아 평가·손익에 반영합니다.")),
                "fbAvg": _f(float(c9["avg"]), 6) or 0, "fbCost": c9.get("fbCost") or 0,
                "gkey": f"g{gid9}" if gid9 is not None else "", "costOv": cost_ov.get(f"g{gid9}") if gid9 is not None else None,
                "cands": unk_cands(gid9, c9["sym"], c9.get("price") or 0),
                "candsHint": UNK_HINT,
                "qty": _f(float(c9["fbQty"]), 6) or 0, "usd": _f(float(c9["fbQty"]) * float(c9.get("price") or 0), 2) or 0,
            })
        for c9 in sorted((c9 for c9 in coins if str(c9.get("key", "")).startswith("ub:") and not (c9.get("avg") or 0)
                          and float(c9.get("qty") or 0) * float(c9.get("price") or 0) >= 50.0),
                         key=lambda c9: -(float(c9["qty"]) * float(c9.get("price") or 0))):
            key9 = f"unkh:{c9['key']}"
            if key9 in ignored_u:
                continue
            pendings.insert(0, {
                "key": key9, "t": datetime.fromtimestamp(now, KST).strftime("%m-%d"),
                "kind": "원가미상 보유 (업비트 단독 · 손익 제외(평가 포함))",
                "sym": c9["sym"], "chain": "업비트",
                "onchain": f"{float(c9['qty']):,.4f} {c9['sym']} 업비트 잔고 · 원장 매수·입금 기록과 매칭 안 됨",
                "ex": "업비트",
                "gap": "원장에 이 코인의 업비트 유입(매수 체결·입금)이 없음 — 수집 창(백필) 이전부터 보유했거나 체결·입금 미수집",
                "why": "업비트 실잔고로만 보이는 보유분이라 원가를 모릅니다 — 평가손익에서 빠져 있어요. 업비트 체결·입금이 원장에 잡히면 자동으로 원가가 붙습니다.",
                "fbAvg": 0, "fbCost": 0, "gkey": "", "ckey": c9["key"], "costOv": None, "cands": [], "candsHint": "",
                "qty": _f(float(c9["qty"]), 6) or 0, "usd": _f(float(c9["qty"]) * float(c9.get("price") or 0), 2) or 0,
            })
        for gid_n, np9 in sorted(noproc.items(), key=lambda kv: -float(kv[1]["cost"])):
            key_n = f"noproc:{gid_n}"
            if key_n in ignored_u or not np9["old"] or (np9["cost"] < 1 and np9["unk"] <= 0):
                continue
            wh9 = " · ".join(sorted(np9["where"])) or "—"
            pendings.insert(0, {
                "key": key_n, "t": acct_norm.mmdd(np9["last"]),
                "kind": "대금 미상 매도 (정산액 산정 전)",
                "sym": np9["sym"], "chain": "—",
                "onchain": f"{float(np9['qty']):,.4f} {np9['sym']} 매도 {np9['n']}건 · 정산액 없음"
                           + (f" · 소진한 원가 ${float(np9['cost']):,.2f}" if np9["cost"] > 0 else ""),
                "ex": wh9,
                "gap": f"{np9['n']}건 · {np9['first'][5:] if len(np9['first']) >= 10 else np9['first']}"
                       + (f"~{np9['last'][5:] if len(np9['last']) >= 10 else np9['last']}" if np9["last"] != np9["first"] else "")
                       + " · 그 시각 시세(받은 쪽 코인·마켓 쿼트)를 못 받아 정산액이 비어 있음",
                "why": "판 대금을 몰라 이 매도의 원가가 실현손익에도 원가미상 매도에도 들어가지 않았어요. 시세를 받으면(가격 채움·재구축) 자동으로 실현에 들어갑니다.",
                "gkey": f"g{gid_n}", "costOv": None, "cands": [], "candsHint": "", "tx": np9["tx"],
                "qty": _f(float(np9["qty"]), 6) or 0, "usd": _f(float(np9["cost"]), 2) or 0})
        for gid_u, u in sorted(unverified.items(), key=lambda kv: float(kv[1]["proceeds"])):
            key_u = f"unv:{gid_u}"
            if key_u in ignored_u:
                continue
            if float(u["proceeds"]) < 1.0:
                continue
            org = ", ".join(sorted(G.get(gid_u, {}).get("origin_ex") or []))
            fb_avg_u = 0.0
            gu = G.get(gid_u) if fb_on else None
            if gu is not None:
                if gu["qty_known"] > EPS:
                    fb_avg_u = float(gu["cost"] / gu["qty_known"])
                elif gu["flows"] and gu["flows"][-1]["bought"] > 0:
                    fb_avg_u = float(gu["flows"][-1]["cost"] / gu["flows"][-1]["bought"])
            pendings.insert(0, {
                "key": key_u, "t": acct_norm.mmdd(u["last"]),
                "kind": "원가미상 매도 · 평균가 폴백 적용" if fb_avg_u else "원가미상 매도 검토",
                "fbAvg": _f(fb_avg_u, 6) or 0,
                "fbRealized": _f(float(u["proceeds"]) - float(u["qty"]) * fb_avg_u, 2) if fb_avg_u else 0,
                "sym": u["sym"], "chain": "—",
                "onchain": f"{float(u['qty']):,.4f} {u['sym']} 매도 · 정산 ${float(u['proceeds']):,.2f}",
                "ex": org or "—",
                "gap": f"{u['n']}건 · " + (f"★{org} 출금 유입 확인★ (원가 연결 대기)" if org
                                           else "실매수 기록 없는 유입분"),
                "why": (f"{org} 출금과 txid 가 일치하는 유입입니다. 해당 거래소 매수내역 연동(2단계)"
                        " 시 원가가 자동 연결됩니다." if org else
                        "매수 기록이 없는 유입분의 매도라 실현손익에서 제외했습니다. "
                        "원가 지정 또는 이체·에어드랍 확인이 필요합니다."),
                "gkey": f"g{gid_u}", "costOv": cost_ov.get(f"g{gid_u}"),
                **({"costBe": cost_be.get(f"g{gid_u}")} if be_until(gid_u) is not None else {}),
                "qty": _f(float(u["qty"]), 6) or 0, "usd": _f(float(u["proceeds"]), 2) or 0,
                "qtyExact": str(u["qty"]),
                "cands": unk_cands(gid_u, u["sym"], live_px.get(gid_u) or 0), "candsHint": UNK_HINT})
        cost_decided_rows = []
        for gid_b, bd in sorted(be_done.items(), key=lambda kv: -float(kv[1]["proceeds"])):
            g_b = G.get(gid_b) or {}
            ut9 = be_until(gid_b)
            cost_decided_rows.append({
                "key": f"be:{gid_b}", "gkey": f"g{gid_b}", "mode": "breakeven", "sym": disp9.get(gid_b) or bd["sym"],
                "chain": "/".join(sorted(CHAIN_NAME.get(c, c) for c in (g_b.get("chains") or ()))) or "—",
                "qty": _f(float(bd["qty"]), 6) or 0, "usd": _f(float(bd["proceeds"]), 2) or 0, "n": bd["n"],
                "qtyExact": str(bd["qty"]),
                "first": bd["first"], "last": bd["last"],
                "until": int(ut9) if ut9 is not None else None,
                "untilT": datetime.fromtimestamp(ut9, KST).strftime("%m-%d %H:%M") if ut9 is not None else ""})
        for gid_l, g_l in sorted(G.items(), key=lambda kv: float((kv[1].get("unv_lost") or (0, 0, 0))[1])):
            lost = g_l.get("unv_lost")
            if not lost:
                continue
            k_l, c_l, ts_l = lost
            key_l = f"unvlost:{gid_l}"
            if key_l in ignored_u or float(c_l) < 1.0:
                continue
            pendings.insert(0, {
                "key": key_l, "t": datetime.fromtimestamp(ts_l or backfill_t0, KST).strftime("%m-%d"),
                "kind": f"창 밖 처분 · 원가 ${float(c_l):,.2f}",
                "sym": g_l["sym"], "chain": "/".join(sorted(CHAIN_NAME.get(c, c) for c in g_l["chains"])) or "—",
                "onchain": f"{float(k_l):,.4f} {g_l['sym']} 실매수분 · 원가 ${float(c_l):,.2f} 가 손익에 안 잡힘",
                "ex": "—",
                "gap": "백필 창(5개월) 시작 직후 창 이전 보유분을 처분 — 원장 순액이 0 밑으로 파여 리플레이가 그 처분을 버리고, 뒤 매수분 원가가 대응 없이 남음",
                "why": "창 이전 보유분은 원가를 모르고 처분은 창 안에 있어 실현손익으로도 미확인 매도로도 못 잡습니다. "
                       "표시용 보정(원장 무변경)이라 무시해도 되고, 창 이전 매수 이력을 등록하면 원가가 연결됩니다.",
                "gkey": f"g{gid_l}", "costOv": cost_ov.get(f"g{gid_l}"), "cands": [], "candsHint": UNK_HINT,
                "qty": _f(float(k_l), 6) or 0, "usd": _f(float(c_l), 2) or 0})
        spam_all = [x for x in sorted(spam_view, key=lambda x: -(x[2] * (x[3] or 0)))
                    if f"risk:g{x[0]}" not in ignored_u]
        pin_gids13 = {x[0] for x in spam_all
                      if "유저 확정" in (x[1].get("risk_reason") or "")
                      or "재정렬" in (x[1].get("risk_reason") or "")}
        pinned13 = [x for x in spam_all if x[0] in pin_gids13]
        rest13 = [x for x in spam_all if x[0] not in pin_gids13]
        spam_sorted = pinned13 + rest13[:30]
        if len(rest13) > 30 and "risk:summary" not in ignored_u:
            more13 = rest13[30:]
            pendings.insert(0, {
                "key": "risk:summary", "t": today_kst.strftime("%m-%d %H:%M"),
                "kind": "스팸·에어드랍 의심", "sym": f"외 {len(more13)}종", "chain": "—",
                "onchain": "저평가 격리분 일괄 — 메인·일일기록에서 제외됨",
                "ex": "—", "gap": "개별 행 생략(평가액 상위 30건만 표시)",
                "why": "격리는 이 종목들 전부에 적용돼 있습니다(평가액이 작은 순서라 개별 행은 생략). "
                       "특정 종목을 되살리려면 그 종목 행에서 [정상으로 복원]을 누르세요.", "cands": [],
                "n": len(more13), "usd": _f(sum(x[2] * (x[3] or 0) for x in more13), 2) or 0})
        for gid13, g13, qty13, px13 in spam_sorted:
            key13 = f"risk:g{gid13}"
            val13 = qty13 * (px13 or 0)
            ch13 = "/".join(sorted(CHAIN_NAME.get(c, c) for c in g13["chains"])) or "—"
            pendings.insert(0, {
                "key": key13, "t": today_kst.strftime("%m-%d %H:%M"),
                "kind": "스팸·에어드랍 의심", "sym": g13["sym"], "chain": ch13,
                "onchain": f"{qty13:,.4f} {g13['sym']} · 평가 ${val13:,.2f} 표시 제외",
                "ex": "—",
                "gap": g13.get("risk_reason") or "실매수 이력 없는 유입",
                "why": "실매수·스왑·내 지갑 이동 이력이 없는 유입이라 메인 목록과 일별 기록에서 뺐습니다."
                       " 실제 보유가 맞으면 [정상으로 복원]을 누르거나, 보낸 주소를 설정 › 발신 주소 화이트리스트에 추가하세요.",
                "gkey": f"g{gid13}", "risk": g13.get("risk_reason") or "",
                "qty": _f(qty13, 6) or 0, "usd": _f(val13, 2) or 0,
                "cands": []})

        tx_legs9 = {}
        for r9 in rows:
            if r9["leg_kind"] in ("acq", "disp", "move_in", "move_out") and (r9["location"] or "").startswith("wallet:"):
                tx_legs9.setdefault((r9["source_ns"], r9["source_id"]), []).append(r9)

        def leg_scam9(r9):
            return ((r9["group_id"] or -r9["asset_id"]) in quarantined
                    or (r9["source_ns"], r9["source_id"], r9["asset_id"]) in spoof_keys or int(r9["qty_base"]) == 0)

        def grp_weak9(r9):
            gid9 = r9["group_id"] or -r9["asset_id"]
            if gid9 not in quarantined or (r9["source_ns"], r9["source_id"], r9["asset_id"]) in spoof_keys or int(r9["qty_base"]) == 0:
                return None
            rr9 = str((G.get(gid9) or {}).get("risk_reason") or "")
            if rr9.startswith(("가짜 ", "사칭 ")) or "유저 확정" in rr9 or "스캠 확증" in rr9 \
                    or _scam_name((G.get(gid9) or {}).get("sym") or r9["symbol"]):
                return None
            return rr9 or "실매수 이력 없는 유입"
        fold9 = {}
        of_linked9 = _of_linked_txs(of_dec9)
        for p9 in pendings:
            k9 = str(p9.get("key") or "").split(":", 1)[0]
            tx9 = str(p9.get("tx") or "")
            if k9 not in ("PROGRAM_IN", "UNKNOWN", "NEW_ASSET") or not tx9 or not p9.get("chainKey"):
                continue
            ol9 = of_linked9.get((p9["chainKey"], _tx_norm(tx9)))
            if ol9:
                p9["autoDone"] = f"보낸 내역에 연결됨({ol9}) — 받은 것과 연결로 설명됨"
                continue
            if k9 == "PROGRAM_IN" and (tx9 in fx_wd or tx9.lower() in fx_wd or tx9 in ub_wd_tx or tx9.lower() in ub_wd_tx):
                p9["autoDone"] = "거래소 출금 도착(txid 일치) — 출금 기록으로 설명됨"
                continue
            legs9 = tx_legs9.get((p9["chainKey"], tx9.lower() if tx9.startswith("0x") else tx9)) or []
            if not legs9:
                continue
            syms9 = sorted({(G.get(r9["group_id"] or -r9["asset_id"]) or {}).get("sym") or (r9["symbol"] or "?") for r9 in legs9})
            if p9.get("sym") in (None, "", "—"):
                p9["sym"] = "/".join(syms9)[:40]
            if all(leg_scam9(r9) for r9 in legs9):
                wk9 = [w9 for w9 in (grp_weak9(r9) for r9 in legs9) if w9]
                if wk9:
                    p9["riskOf"] = wk9[0]
                else:
                    p9["scamWhy"] = "스캠 토큰(가짜·사칭·주소 오염) " + ("수령" if k9 == "PROGRAM_IN" else "기록")
                if k9 == "PROGRAM_IN":
                    fold9.setdefault((frozenset(r9["group_id"] or -r9["asset_id"] for r9 in legs9), "r" if wk9 else "s"), []).append(p9)
                continue
            if k9 == "NEW_ASSET" and all(r9["event"] == "SWAP" and r9["leg_kind"] in ("acq", "disp") and r9["cost_usd"] is not None
                                         for r9 in legs9) and any(r9["leg_kind"] == "disp" for r9 in legs9):
                s9n = self._tx_signer(conn, legs9[0]["source_ns"], legs9[0]["source_id"])
                if s9n and spamguard.signer_mine(*s9n, my_all9):
                    p9["autoDone"] = "원가 있는 내 스왑 체결 — 새 자산 자동 기록 확인됨"
                    continue
            if any(r9["leg_kind"] in ("disp", "move_out") and not leg_scam9(r9) for r9 in legs9):
                continue
            ins9 = [r9 for r9 in legs9 if not leg_scam9(r9)]
            vals9 = [ev_usd(r9, G.get(r9["group_id"] or -r9["asset_id"]) or {"gid": None, "sym": ""}) for r9 in ins9]
            if ins9 and all(v9 is not None for v9 in vals9):
                p9["usdIn"] = round(sum(vals9), 6)
                s9 = signer9.get((legs9[0]["source_ns"], legs9[0]["source_id"]))
                if p9["usdIn"] < 0.01 and not (s9 and spamguard.signer_mine(*s9, my_all9)):
                    p9["scamWhy"] = f"주소 오염 의심 초소액 수령 (${p9['usdIn']:.4f})"
            if not p9.get("scamWhy") and k9 in ("PROGRAM_IN", "UNKNOWN") and len(legs9) == 1 and legs9[0]["leg_kind"] == "acq" \
                    and legs9[0]["event"] in ("TRANSFER_IN", "PROGRAM_IN") and legs9[0]["kind"] == "token" \
                    and (G.get(legs9[0]["group_id"] or -legs9[0]["asset_id"]) or {}).get("is_stable") \
                    and spamguard.is_genuine(legs9[0]["chain"] or legs9[0]["source_ns"], legs9[0]["address"]):
                p9["kind"] = "외부 유입(액면)"
                p9["gap"] = "정품 스테이블 입금 · 액면 원가"
                p9["why"] = ("정품 스테이블(컨트랙트 확인)이 한 줄로 들어온 입금이라 액면 $1 원가로 기록했어요. 내 다른 지갑·거래소에서 보낸 것이면"
                             " 설정 › 연결에서 그 주소를 등록하고, 남에게 받은 것이면 무시해도 돼요.")
        for (gs9, _k9), lst9 in fold9.items():
            if len(lst9) < 2:
                continue
            keep9 = lst9[0]
            keep9["foldN"] = len(lst9)
            keep9["foldTx"] = [str(x9.get("tx") or "") for x9 in lst9[1:21]]
            keep9["why"] = (keep9.get("why") or "") + f" · 같은 코인 수령 {len(lst9)}건을 한 행으로 묶었어요(나머지 {len(lst9) - 1}건 tx 는 foldTx)"
            for x9 in lst9[1:]:
                x9["_fold"] = True
        if fold9:
            pendings[:] = [p9 for p9 in pendings if not p9.pop("_fold", False)]

        _classify_pendings(pendings, prefs)

        wallets_cfg = self._hist_wallets()
        by_addr = {}
        for w in wallets_cfg:
            k9 = w["address"] if w.get("type") == "sol" else w["address"].lower()
            by_addr.setdefault(k9, []).append(w)
        wallet_rows = []
        last_scan9 = self._last_scan_str() if by_addr else None
        for k9, ws in by_addr.items():
            addr = ws[0]["address"]
            chains = sorted({CHAIN_NAME.get(w["chain"], w["chain"]) for w in ws})
            wallet_rows.append({"alias": (aliases.get(k9) or ws[0].get("label")
                                          or addr[:8]),
                                "addr": addr, "key": k9,
                                "chains": " · ".join(chains),
                                "last": last_scan9})
        deposit_rows = []
        seen_dep = set()
        for e in self.cfg.get("exchange_addresses", []):
            net = "SOL" if e["chain"] == "sol" else "EVM"
            k = (e["exchange"], net, e["address"])
            if k in seen_dep:
                continue
            seen_dep.add(k)
            deposit_rows.append({"ex": "업비트" if e["exchange"] == "upbit" else e["exchange"],
                                 "net": net, "addr": e["address"], "memo": "—", "ok": True})
        try:
            man9 = {depaddr.norm_addr(k9[2]) for k9 in seen_dep}
            for r9 in depaddr.deposit_rows():
                if depaddr.norm_addr(r9["addr"]) not in man9:
                    deposit_rows.append(r9)
        except Exception:
            pass
        dec_dep9 = self.outflow_decisions()
        for a9, v9 in dec_dep9.items():
            if isinstance(v9, dict) and v9.get("verdict") == "exchange":
                deposit_rows.append({"ex": v9.get("exchange") or "?", "net": "SOL" if not a9.startswith("0x") else "EVM",
                                     "addr": a9, "memo": "보낸 내역 판정" + (f" · {v9['memo']}" if v9.get("memo") else ""),
                                     "ok": True})
        for a9, (ex9, how9) in sorted(((getattr(self, "_of_auto", None) or {}).get("proven") or {}).items()):
            if ex9 and how9 == "txid" and a9 not in dec_dep9 and a9 not in ("multi", "?") and \
                    not any(str(d9.get("addr") or "").lower() == a9.lower() for d9 in deposit_rows):
                deposit_rows.append({"ex": ex9, "net": "SOL" if not a9.startswith("0x") else "EVM", "addr": a9,
                                     "memo": "보낸 내역 자동 입증(txid 일치)", "ok": True})
        ch9 = {n: c for n, c in (self.cfg.get("chains") or {}).items() if isinstance(c, dict) and not str(n).startswith("_")}
        n_rpc9 = sum(1 for n, c in ch9.items() if common.chain_discovery(n, c) == "rpc")
        wl9 = [w for w in (self.cfg.get("wallets") or []) if isinstance(w, dict) and w.get("address")]
        n_evm9 = len({str(w["address"]).lower() for w in wl9 if w.get("type", "evm") == "evm"})
        n_sol9 = len({str(w["address"]) for w in wl9 if w.get("type") == "sol"})
        n_bsc9 = len({str(w["address"]).lower() for w in wl9 if w.get("type") == "bsc_rpc"})
        sol_src9 = "Helius" if str((self.cfg.get("sol") or {}).get("rpc") or "") == "helius" else "RPC"
        src_chips = [
            {"label": f"EVM {len(ch9)}체인 · " + (f"blockscout {len(ch9) - n_rpc9} + RPC {n_rpc9}" if n_rpc9 else "blockscout"),
             "short": f"EVM {n_evm9}지갑",
             "addr": f"{self._backfill_pct('evm')} · {self._last_scan_str('evm')}"},
            {"label": f"Solana · {sol_src9}", "short": f"SOL {n_sol9}지갑",
             "addr": f"{self._backfill_pct('sol')} · {self._last_scan_str('sol')}"},
            {"label": "BSC · 공개 RPC", "short": f"BSC {n_bsc9}지갑",
             "addr": f"{self._backfill_pct('bsc')} · {self._last_scan_str('bsc')}"},
        ]

        wd_rows = []
        for r8 in conn.execute(
                "SELECT uuid, payload FROM raw_ex WHERE kind='withdraw' AND exchange='upbit'"
                " GROUP BY uuid HAVING revision = MAX(revision)").fetchall():
            try:
                wd = json.loads(r8["payload"])
            except json.JSONDecodeError:
                continue
            if str(wd.get("state") or "").upper() not in ("DONE", "ACCEPTED"):
                continue
            if r8["uuid"] in ub_wd_shown:
                continue
            try:
                wts = int(datetime.fromisoformat(str(wd.get("done_at")
                                                     or wd.get("created_at"))).timestamp())
            except (ValueError, TypeError):
                continue
            wd_rows.append((wts, wd))
        wd_rows.sort(key=lambda x: -x[0])
        n_ev_before_wd = len(extra_events)
        cur_src[0] = "ex:upbit"
        ctx_ns9 = [r9[0] for r9 in conn.execute(
            "SELECT DISTINCT source_ns FROM postings WHERE source_kind='chain_tx'").fetchall()]
        for wts, wd in wd_rows:
            txid = str(wd.get("txid") or "")
            cand = txid.lower() if txid.startswith("0x") else txid
            dest = "외부/미매칭"
            if txid and ctx_ns9:
                hit = conn.execute(
                    "SELECT p.location FROM postings p WHERE p.source_kind='chain_tx'"
                    " AND p.source_ns IN (" + ",".join("?" * len(ctx_ns9)) + ")"
                    " AND p.source_id IN (?, ?) AND p.leg_kind='acq'"
                    " ORDER BY p.source_ns, p.source_id, p.leg_seq LIMIT 1",
                    (*ctx_ns9, cand, txid)).fetchone()
                if hit:
                    pl = (hit["location"] or "").split(":")
                    wa2 = pl[2] if len(pl) >= 3 else None
                    lbl = (aliases.get(wa2) or self.addr_label.get(wa2)) if wa2 else None
                    dest = f"내 지갑 {lbl or (wa2[:8] if wa2 else '?')}" \
                           + (f" ({CHAIN_NAME.get(pl[1], pl[1])})" if len(pl) >= 2 else "")
            if dest == "외부/미매칭":
                if str(wd.get("currency") or "").upper() == "KRW":
                    dest = "은행 (원화 출금)"
                elif txid.startswith("swap_"):
                    dest = "토큰 전환 (업비트 내부)"
                elif cand in fx_dep_tx:
                    dest = f"{fx_name.get(fx_dep_tx[cand], fx_dep_tx[cand])} 입금 (txid 일치)"
            amt = wd.get("amount") or "?"
            extra_ev(wts, str(wd.get("currency") or "?"), "전송",
                     f"업비트 출금 → {dest}", str(amt), "—", txid or "—")
        cur_src[0] = None

        _k9 = lambda e9: e9.get("_ts", 0)
        ev_main9, ev_wd9, ev_hid9 = [], [], []
        n_wd_hid9 = 0
        tdk9 = today_kst.strftime("%Y-%m-%d")
        for e9 in extra_events:
            vq9 = e9.pop("_vq", None)
            if vq9 is None or e9.get("a") not in (None, "", "—"):
                continue
            g9 = G.get(e9.get("_gid"))
            if not g9:
                continue
            try:
                aq9 = abs(Decimal(str(vq9)))
            except (InvalidOperation, ValueError, TypeError):
                continue
            if aq9 <= 0:
                continue
            if g9.get("is_fiat"):
                e9["a"] = f"₩{float(aq9):,.0f}"
                continue
            d9 = datetime.fromtimestamp(e9.get("_ts") or 0, KST).strftime("%Y-%m-%d")
            if g9.get("is_stable"):
                p9 = 1.0
            elif d9 >= tdk9:
                p9 = float(live_px.get(g9["gid"]) or 0)
            else:
                p9 = float((((self.daily_px or {}).get(d9) or {}).get("p") or {}).get(str(g9["gid"])) or 0)
            if p9 > 0:
                e9["a"] = f"${float(aq9) * p9:,.2f}"
                e9["un"] = float(f"{p9:.10g}")
                ak9 = _ak(e9["a"], e9.get("_ts") or 0)
                if ak9 is not None:
                    e9["aK"] = ak9
        for i9, e9 in enumerate(extra_events):
            why9 = self._event_hide_reason(e9, G, quarantined, gid_pairs_all)
            kind9 = "scam" if why9 else None
            if not why9:
                h9 = ev_hide(e9)
                if h9:
                    kind9, why9 = h9
            if why9:
                ev_hid9.append(dict(e9, hide=why9, hideKind=kind9))
                n_wd_hid9 += i9 >= n_ev_before_wd
            else:
                (ev_main9 if i9 < n_ev_before_wd else ev_wd9).append(e9)
        ev_hid9 += pos_hid9
        for e9 in ev_main9 + ev_wd9 + ev_hid9:
            if e9.get("sym") == "TOKEN" and e9.get("_gid") in disp9:
                e9["sym"] = disp9[e9["_gid"]]
        for p9 in pendings:
            m9 = re.match(r"^g(\d+)$", str(p9.get("gkey") or "")) or re.match(r"^(?:unv|unkh|risk):g?(\d+)$", str(p9.get("key") or ""))
            if m9 and p9.get("sym") == "TOKEN" and int(m9.group(1)) in disp9:
                p9["sym"] = disp9[int(m9.group(1))]
        _nopid9 = lambda e9: {k9: v9 for k9, v9 in e9.items() if k9 not in ("_pid", "_lnk", "_mv", "_src", "_cmp", "_cv", "_tax", "_vq")}
        extra_events_out = [_nopid9(e9) for e9 in sorted(sorted(ev_main9, key=_k9)[-150:] + sorted(ev_wd9, key=_k9)[-150:], key=_k9)]
        extra_events_hidden = [_nopid9(e9) for e9 in sorted(ev_hid9, key=_k9)[-150:]]
        hid_kind_n9 = {"scam": 0, "dust": 0}
        for e9 in ev_hid9:
            hid_kind_n9[e9.get("hideKind") or "scam"] = hid_kind_n9.get(e9.get("hideKind") or "scam", 0) + 1

        realized_month = sum(v for k, v in realized_by_date.items()
                             if k.startswith(today_kst.strftime("%Y-%m-")))

        gas_list = [{"chain": CHAIN_NAME.get(c, c), "spot": _f(v["usd"], 2) or 0,
                     "lp": 0, "tx": v["tx"]}
                    for c, v in sorted(gas_by_chain.items(), key=lambda kv: -kv[1]["usd"])]
        exfee_lab = lambda e9: f"{fx_name.get(e9, e9)} 체결 수수료"
        gas_list += [{"chain": exfee_lab(e9), "spot": _f(v9["usd"], 2) or 0, "lp": 0, "tx": v9["tx"], "kind": "exfee"}
                     for e9, v9 in sorted(ex_fee.items(), key=lambda kv: -kv[1]["usd"])]
        gas_chain_usd = sum((v9["usd"] for v9 in gas_by_chain.values()), Decimal(0))
        tax_gas = {"on": gas_on, "total": _f(gas_chain_usd, 2) or 0,
                   "inCost": _f(gas_applied["buy"], 2) or 0, "inRealized": _f(gas_applied["sell"], 2) or 0,
                   "separate": _f(gas_chain_usd - (gas_applied["buy"] + gas_applied["sell"] if gas_on else 0), 2) or 0,
                   "expense": _f(sum((v9[0] for v9 in gas_expense.values()), Decimal(0)), 2) or 0,
                   "swapTx": gas_applied["n"],
                   "exFee": _f(sum((v9["usd"] for v9 in ex_fee.values()), Decimal(0)), 2) or 0}

        day_memos9, day_memos_err9 = DAY_MEMOS.read()
        if day_memos_err9:
            log.warning("그날 매매 근거 메모 파일 이상(%s) — 화면엔 빈 것 · 저장 거부", day_memos_err9)
        plans_out, plan_memos = self._plans_view(prefs)

        fiats = []
        if ub2:
            ub = ub2
            if time.time() - (ub.get("ts") or 0) < 600:
                for acc in ub.get("accounts") or []:
                    if acc.get("currency") == "KRW":
                        try:
                            krw = float(acc.get("balance") or 0) + float(acc.get("locked") or 0)
                        except (TypeError, ValueError):
                            krw = 0
                        if krw > 0:
                            fiats.append({"ex": "업비트", "krw": krw, "note": "거래소 예수금"})
        fx_name9 = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX",
                    "kucoin": "쿠코인", "gate": "게이트", "bithumb": "빗썸"}
        ex_debts = []
        bal_src9 = {}
        for ex9, kn9 in fx_name9.items():
            bp0 = os.path.join(common.STATE_DIR, f"exf_balances_{ex9}.json")
            bp9, bd9 = None, {}
            for c9 in (bp0, bp0 + ".pending", bp0 + ".view"):
                try:
                    d9 = common.read_json(c9, {}) if os.path.exists(c9) else {}
                except (Exception, SystemExit):
                    d9 = {}
                if isinstance(d9, dict) and isinstance(d9.get("balances"), dict):
                    bp9, bd9 = c9, d9
                    break
            if bp9 is None:
                continue
            bal_src9[ex9] = (bp9, float(bd9.get("ts") or 0))
            age9 = time.time() - float(bd9.get("ts") or 0)
            bal9 = bd9.get("balances")
            if not isinstance(bal9, dict):
                continue
            try:
                krw9 = float(bal9.get("KRW") or 0)
            except (TypeError, ValueError):
                continue
            if krw9 > 0:
                f9 = {"ex": kn9, "krw": krw9, "note": "거래소 예수금"}
                if age9 > common.exf_fresh_sec(self.cfg):
                    f9["age"] = int(age9)
                    f9["stale"] = True
                    f9["note"] = f"거래소 예수금 · {kn9} 잔고 {_ago_ko(age9)} 전"
                fiats.append(f9)
            loan_d9, loan_c9 = {}, {}
            for ln9 in (bd9.get("loans") if isinstance(bd9.get("loans"), list) else ()):
                if not isinstance(ln9, dict):
                    continue
                for s9, v9 in ((ln9.get("debt") or {}) if isinstance(ln9.get("debt"), dict) else {}).items():
                    try:
                        su9 = str(s9).upper()
                        loan_d9[su9] = (loan_d9.get(su9, (0.0, ln9.get("label")))[0] + float(v9), str(ln9.get("label") or "담보대출"))
                    except (TypeError, ValueError):
                        continue
                    for c9, cv9 in ((ln9.get("collateral") or {}) if isinstance(ln9.get("collateral"), dict) else {}).items():
                        try:
                            loan_c9.setdefault(su9, []).append(f"{str(c9).upper()} {float(cv9):,.6g}")
                        except (TypeError, ValueError):
                            pass
            for s9, v9 in ((bd9.get("debts") or {}) if isinstance(bd9.get("debts"), dict) else {}).items():
                try:
                    fv9 = float(v9)
                except (TypeError, ValueError):
                    continue
                if fv9 < 0:
                    su9 = str(s9).upper()
                    px9 = 1.0 if su9 in STABLE_GROUPS or _ex_stable_sym(su9) else (
                        self.spot.ex_price(ex9, su9) or self.spot.price(su9))
                    lq9, ll9 = loan_d9.get(su9, (0.0, None))
                    parts9 = []
                    if lq9 > 0:
                        lq9 = min(lq9, -fv9)
                        parts9.append((-lq9, "loan", f"{ll9} 차입(총자산에서 차감 반영 · 담보 {', '.join(loan_c9.get(su9) or []) or '—'} = 내 자산으로 계산)"))
                    if fv9 + lq9 < -1e-12:
                        parts9.append((fv9 + lq9, "margin", "마진 차입(총자산에서 차감 반영)"))
                    for q9, k9, n9 in parts9:
                        d9 = {"ex": kn9, "sym": su9, "qty": q9, "note": n9, "kind": k9}
                        if px9:
                            d9["price"] = float(px9)
                            d9["usd"] = round(q9 * float(px9), 2)
                        ex_debts.append(d9)

        for gid9, q9 in sorted(hl_neg.items()):
            if q9 < -EPS:
                sym9 = str((G.get(gid9) or {}).get("sym") or "USDC").upper()
                px9 = 1.0 if (G.get(gid9) or {}).get("is_stable") else float(live_px.get(gid9) or self.spot.ex_price("hyperliquid", sym9) or 0)
                d9 = {"ex": fx_name.get("hyperliquid", "Hyperliquid"), "sym": sym9, "qty": float(q9), "kind": "margin",
                      "note": "Hyperliquid 무기한 현금 음수(미실현 이익 인출 — 포지션 청산 때 메워짐 · 총자산에서 차감 반영)"}
                if px9:
                    d9.update(price=px9, usd=round(float(q9) * px9, 2))
                ex_debts.append(d9)
        debt_sym9 = {(d9["ex"], d9["sym"]) for d9 in ex_debts}
        neg_hold = []
        for r9 in pos_rows:
            if r9["qty"] >= -EPS or r9["gid"] in quarantined:
                continue
            g9 = G.get(r9["gid"])
            if not g9 or g9.get("is_fiat"):
                continue
            px9 = 1.0 if g9.get("is_stable") else float(live_px.get(r9["gid"]) or 0)
            usd9 = float(r9["qty"]) * px9
            if usd9 > -0.01:
                continue
            loc9 = r9["location"]
            ex9 = fx_name.get(loc9.split(":")[1], loc9.split(":")[1]) if loc9.startswith("exchange:") else None
            neg_hold.append({"key": f"g{r9['gid']}", "sym": g9["sym"], "loc": loc9, "qty": float(r9["qty"]),
                             "usd": round(usd9, 2), "debt": bool(ex9 and (ex9, (g9["sym"] or "").upper()) in debt_sym9)})
        neg_hold.sort(key=lambda d9: d9["usd"])
        if neg_hold:
            pend9 = self._prewin_pairs(conn)
            for n9 in neg_hold:
                if (int(n9["key"][1:]), n9["loc"]) in pend9:
                    n9["pend"] = True

        rate_fx = self.spot.rate or 1384
        hold_qty = {gid9: led_by_gid.get(gid9, Decimal(0)) + uncred_gid.get(gid9, Decimal(0))
                    for gid9 in G if not G[gid9].get("is_fiat")}
        x_ub = sum(c["qty"] * (c.get("price") or 0) for c in coins + stables if str(c.get("key", "")).startswith("ub:"))
        x_ubs = {}
        for c in coins + stables:
            if str(c.get("key", "")).startswith("ub:"):
                a9 = x_ubs.setdefault(str(c["key"])[3:].upper(), [0.0, 0.0])
                a9[0] += float(c["qty"])
                a9[1] += float(c["qty"]) * float(c.get("price") or 0)
        x_fiat = sum(f5["krw"] / rate_fx for f5 in fiats)
        up_fresh9 = bool(ub2) and time.time() - float((ub2 or {}).get("ts") or 0) < common.upbit_fresh_sec(self.cfg)
        x_ok = True
        for p9, lim9 in ([(ub_path2, common.upbit_fresh_sec(self.cfg))] + [(os.path.join(common.STATE_DIR, f"exf_balances_{e9}.json"), common.exf_fresh_sec(self.cfg))
                                               for e9 in fx_name9 if e9 not in bal_src9]):
            if os.path.exists(p9):
                age9 = time.time() - float((common.read_json(p9, {}) or {}).get("ts") or 0)
                if lim9 < age9 < 86400:
                    x_ok = False
        for e9, (p9, ts9) in bal_src9.items():
            age9 = time.time() - ts9
            lim9 = common.exf_fresh_sec(self.cfg) if p9.endswith(".json") else max(21600, common.exf_fresh_sec(self.cfg))
            if lim9 < age9 < 86400:
                x_ok = False
        lp_onchain = (common.read_json(LP_POS_PATH, {}) or {}).get("positions") or {}
        tok_gid = {}
        self._lp_solmeta = {r7["address"]: {"symbol": r7["symbol"], "decimals": r7["decimals"]} for r7 in conn.execute(
            "SELECT address, symbol, decimals FROM assets WHERE chain='sol' AND kind='token' AND address IS NOT NULL"
            " AND decimals IS NOT NULL").fetchall()}
        for r7 in conn.execute("SELECT kind, chain, address, group_id FROM assets"
                               " WHERE group_id IS NOT NULL AND kind IN ('token', 'native')").fetchall():
            a7 = (r7["address"] or "").lower() if r7["kind"] == "token" else lpchain.ZERO
            tok_gid.setdefault((r7["chain"], a7), r7["group_id"])
        _lpa = lambda ch9, a9: (str(a9 or "") if ch9 == "sol" else str(a9 or "").lower())
        lp_want = sorted({(oc9.get("chain") or loc9.split(":")[1], _lpa(oc9.get("chain") or loc9.split(":")[1], oc9.get(k9)))
                          for loc9, oc9 in lp_onchain.items() for k9 in ("token0", "token1", "rewardToken")
                          if str(oc9.get(k9) or "").lower() not in ("", lpchain.ZERO)})
        self.spot.want_tokens([p9 for p9 in lp_want if not pricing.STABLE_CAS.get(p9[0], {}).get(p9[1])
                               and not (p9[0] == "sol" and pricing.STABLE_MINTS.get(p9[1]))], slot="lp")

        def lp_tok_px(ch9, addr9, sym9):
            a9 = _lpa(ch9, addr9)
            if pricing.STABLE_CAS.get(ch9, {}).get(a9) or (ch9 == "sol" and pricing.STABLE_MINTS.get(a9)):
                return 1.0
            if ch9 == "sol" and a9 == lpsol.WSOL:
                a9 = lpchain.ZERO
            gid9 = tok_gid.get((ch9, a9.lower()))
            if gid9 is not None and live_px.get(gid9):
                return float(live_px[gid9])
            if a9 and a9 != lpchain.ZERO:
                dp9 = self.spot.dex_price(ch9, a9)
                return float(dp9) if dp9 else None
            p9 = self.spot.price(sym9 or "") if sym9 else None
            return float(p9) if p9 else None

        def lp_value(oc9, ch9):
            p0 = lp_tok_px(ch9, oc9.get("token0"), oc9.get("sym0"))
            p1 = lp_tok_px(ch9, oc9.get("token1"), oc9.get("sym1"))
            pr9 = float(oc9.get("price") or 0)
            if p0 is None and p1 is not None and pr9:
                p0 = p1 * pr9
            if p1 is None and p0 is not None and pr9:
                p1 = p0 / pr9
            if p0 is None or p1 is None:
                return None
            a0, a1 = float(oc9.get("amount0") or 0), float(oc9.get("amount1") or 0)
            f0, f1 = float(oc9.get("fees0") or 0), float(oc9.get("fees1") or 0)
            rw9 = float(oc9.get("rewardAmount") or 0)
            rp9 = lp_tok_px(ch9, oc9.get("rewardToken"), oc9.get("rewardSym")) if rw9 > 0 else None
            return {"value": a0 * p0 + a1 * p1, "fees": f0 * p0 + f1 * p1, "p0": p0, "p1": p1,
                    "rewards": rw9 * rp9 if rp9 else 0.0}

        def _qfmt(x):
            return f"{float(x):,.4f}".rstrip("0").rstrip(".") if x else "0"

        def _qnow(x):
            if x is None:
                return "구성 미확인"
            return "<0.0001" if 0 < abs(float(x)) < 0.00005 else _qfmt(x)

        lps_out, lps_pending, lps_closed = [], [], []
        lp_targets9 = []
        lp_v2_units = {}
        for (ch9, _h9), d9 in lp_by_tx.items():
            if d9.get("proto") != "v2" or not d9.get("mgr"):
                continue
            for act9, t9, l9 in d9.get("liq") or []:
                if t9 is None or l9 is None:
                    continue
                k9 = f"lp:{ch9}:{d9['mgr']}:{t9}"
                lp_v2_units[k9] = lp_v2_units.get(k9, 0) + (int(l9) if act9 in ("MINT", "INCREASE") else -int(l9))

        def lp_extra(b9, loc9, tid9):
            ex9 = {"proto": b9.get("proto")}
            if b9.get("proto") == "v2":
                ex9["units"] = str(max(0, lp_v2_units.get(loc9, 0)))
                ex9["wallet"] = str(tid9)
            stk9 = ((lp_meta_by.get((b9["chain"], b9["mgr"])) or {}).get("stake") or {}).get(str(b9["id"]))
            if stk9:
                ex9["stake"] = stk9
                ex9.setdefault("wallet", ((lp_meta_by.get((b9["chain"], b9["mgr"])) or {}).get("who") or {}).get(str(b9["id"])))
            return ex9
        seen_lp = set()
        for loc9, b9 in sorted(lpb.items(), key=lambda kv: -kv[1]["last"]):
            seen_lp.add(loc9)
            oc9 = lp_onchain.get(loc9) or {}
            units9 = {k: v for k, v in b9["units"].items() if v > Decimal("0.000001")}
            prin9 = sum((v for k, v in b9["ucost"].items() if k in units9), Decimal(0))
            liq9 = int(oc9.get("liquidity") or 0) if oc9 else None
            is_open = (liq9 > 0) if liq9 is not None else bool(units9)
            tid9 = lpdec.lp_tid(b9["id"])
            if tid9 is not None and (is_open or units9):
                lp_targets9.append((b9["chain"], b9["mgr"], tid9, loc9, lp_extra(b9, loc9, tid9)))
            base9 = {"key": loc9, "id": b9["id"], "chainKey": b9["chain"], "chain": CHAIN_NAME.get(b9["chain"], b9["chain"]),
                     "mgr": b9["mgr"], "proto": b9["proto"], "dex": b9["name"],
                     "opened": datetime.fromtimestamp(b9["opened"], KST).strftime("%m-%d"),
                     "lastTs": int(b9["last"]), "openedTs": int(b9["opened"]),
                     "deposited": _f(float(b9["deposited"]), 2) or 0,
                     "principalUnits": {k: _f(float(v), 6) for k, v in units9.items()},
                     "returned": {k: _f(float(v), 6) for k, v in b9["returned"].items()},
                     "converted": {k: _f(float(v), 6) for k, v in b9["converted"].items()},
                     "acquired": {k: _f(float(v), 6) for k, v in b9["acq"].items()},
                     "realized": _f(float(b9["realized"]), 2) or 0, "income": _f(float(b9["income"]), 2) or 0,
                     "realizedByDay": {d9: round(float(v9), 2) for d9, v9 in sorted(b9["rbd"].items())},
                     "realizedKrwByDay": {d9: round(float(v9)) for d9, v9 in sorted(b9["rbdk"].items())},
                     "liquidity": str(liq9) if liq9 is not None else None}
            if not isinstance(tid9, int) and tid9 is not None:
                base9["idShort"] = (lpsol.short(str(tid9)) if not str(tid9).startswith("0x")
                                    else str(tid9)[:6] + "…" + str(tid9)[-4:])
            stk9 = ((lp_meta_by.get((b9["chain"], b9["mgr"])) or {}).get("stake") or {}).get(str(b9["id"]))
            if stk9:
                base9["staked"] = stk9
            mm9 = ((lp_meta_by.get((b9["chain"], b9["mgr"])) or {}).get("mints") or {}).get(str(b9["id"]))
            if mm9 and b9["chain"] == "sol":
                s9 = [("SOL" if m == lpsol.WSOL else ((self._lp_solmeta.get(m) or {}).get("symbol") or m[:4])) for m in mm9]
                base9["pair"] = s9
                base9["pool"] = f"{s9[0]} / {s9[1]}"
            if oc9.get("sym0") and oc9.get("sym1"):
                base9["pair"] = [oc9.get("sym0"), oc9.get("sym1")]
            if not is_open:
                base9["closed"] = True
                base9["residualUnits"] = base9["principalUnits"]
                lps_closed.append(base9)
                continue
            val9 = lp_value(oc9, b9["chain"]) if oc9 else None
            if val9 is None:
                base9["closed"] = False
                base9["pendingReason"] = ("온체인 평가 대기" if not oc9 else
                                          "지정가 주문 — 온체인 평가 미지원" if oc9.get("limitOrder") else "토큰 시세 없음")
                lps_pending.append(base9)
                continue
            s0, s1 = oc9.get("sym0") or "?", oc9.get("sym1") or "?"
            fee9 = oc9.get("fee")
            if oc9.get("proto") == "meteora_dlmm":
                tier9 = f"bin {oc9.get('binStep')}bp"
            elif oc9.get("proto") == "v2":
                tier9 = "stable" if oc9.get("stable") else ("volatile" if oc9.get("stable") is False else "v2")
            elif oc9.get("proto") == "slipstream" or fee9 is None:
                tier9 = f"틱간격 {oc9.get('tickSpacing')}"
            elif int(fee9) & 0x800000:
                tier9 = "동적 수수료"
            else:
                tier9 = f"{int(fee9) / 10000:.2f}%".replace(".00%", "%")
            hold9 = None
            if all(k in (s0, s1) for k in units9):
                hold9 = sum(float(v) * (val9["p0"] if k == s0 else val9["p1"]) for k, v in units9.items())
            days9 = max(1.0, (now - b9["opened"]) / 86400)
            row9 = dict(base9)
            row9.update({
                "pool": f"{s0} / {s1}", "tier": tier9, "closed": False,
                "status": "범위 내" if oc9.get("inRange") else "범위 이탈",
                "range": (f"전 구간(v2) · 현재 {float(oc9.get('price') or 0):,.6g} ({s1}/{s0})" if oc9.get("proto") == "v2" else
                          f"{float(oc9.get('priceLower') or 0):,.6g} – {float(oc9.get('priceUpper') or 0):,.6g} ({s1}/{s0})"),
                "deposit": round(float(prin9), 2), "value": round(val9["value"], 2), "fees": round(val9["fees"], 2),
                "rewards": round(val9.get("rewards") or 0, 2), "il": round(val9["value"] - hold9, 2) if hold9 is not None else 0,
                "apr": (f"{(val9['fees'] + (val9.get('rewards') or 0)) / float(prin9) * 365 / days9 * 100:.1f}%" if prin9 > 0 else "—"),
                "comp": [{"sym": s0, "then": _qfmt(units9.get(s0)), "now": _qnow(oc9.get("amount0"))},
                         {"sym": s1, "then": _qfmt(units9.get(s1)), "now": _qnow(oc9.get("amount1"))}],
                "feesStale": bool(oc9.get("feesStale"))})
            b9["pool"] = row9["pool"]
            lps_out.append(row9)
        for loc9, oc9 in lp_onchain.items():
            if loc9 in seen_lp or int(oc9.get("liquidity") or 0) <= 0:
                continue
            parts9 = loc9.split(":")
            if len(parts9) < 4:
                continue
            mg9 = (lp_mgrs.get(parts9[1]) or {}).get(parts9[2]) or {}
            val9 = lp_value(oc9, parts9[1])
            s0, s1 = oc9.get("sym0") or "?", oc9.get("sym1") or "?"
            ent9 = {"key": loc9, "id": parts9[3], "chainKey": parts9[1], "chain": CHAIN_NAME.get(parts9[1], parts9[1]),
                    "mgr": parts9[2], "proto": mg9.get("proto"), "dex": mg9.get("name") or "LP", "noLedger": True,
                    "liquidity": str(oc9.get("liquidity")), "closed": False}
            lp_targets9.append((parts9[1], parts9[2], int(parts9[3]), loc9, {})) if parts9[3].isdigit() else None
            if val9 is None:
                ent9["pendingReason"] = "토큰 시세 없음"
                lps_pending.append(ent9)
                continue
            ent9.update({"pool": f"{s0} / {s1}", "tier": "—", "opened": "—",
                         "status": "범위 내" if oc9.get("inRange") else "범위 이탈",
                         "range": f"{float(oc9.get('priceLower') or 0):,.6g} – {float(oc9.get('priceUpper') or 0):,.6g} ({s1}/{s0})",
                         "deposit": 0, "value": round(val9["value"], 2), "fees": round(val9["fees"], 2),
                         "rewards": round(val9.get("rewards") or 0, 2),
                         "il": 0, "apr": "—",
                         "comp": [{"sym": s0, "then": "—", "now": _qnow(oc9.get("amount0"))},
                                  {"sym": s1, "then": "—", "now": _qnow(oc9.get("amount1"))}]})
            lps_out.append(ent9)
        with self._lp_lock:
            self._lp_targets = lp_targets9
        lp_ev_by9 = {}
        for e9 in sorted(lp_events, key=lambda e9: e9["_ts"]):
            lp_ev_by9.setdefault(e9.get("lp"), []).append(e9)
        lp_events_out = sorted((e9 for l9 in lp_ev_by9.values() for e9 in l9[-300:]), key=lambda e9: e9["_ts"])
        lp_total = sum((l9["value"] + l9["fees"] + (l9.get("rewards") or 0)) for l9 in lps_out)
        rb_recon = []
        bot_w9 = {}
        row_px_b9 = {c9["key"]: float(c9.get("price") or 0) for c9 in coins + stables}
        for gid9, lr9 in locs_by_gid.items():
            px9 = row_px_b9.get(f"g{gid9}", 0.0)
            if px9 <= 0:
                continue
            for l9 in lr9:
                p9 = str(l9["location"] or "").split(":")
                if p9[0] != "wallet" or len(p9) < 3 or not p9[2]:
                    continue
                u9 = float(Decimal(l9["qty_norm"])) * px9
                if u9 > 0:
                    bot_w9[p9[2].lower()] = bot_w9.get(p9[2].lower(), 0.0) + u9
        for l9 in lps_out:
            ow9 = str((lp_onchain.get(l9.get("key")) or {}).get("owner") or "").lower()
            if ow9:
                bot_w9[ow9] = bot_w9.get(ow9, 0.0) + float(l9.get("value") or 0) + float(l9.get("fees") or 0) \
                    + float(l9.get("rewards") or 0)
        self._bot_wallet_usd = dict(bot_w9)
        if self.__dict__.get("_bot_usd_saved") != bot_w9:
            try:
                common.atomic_write_json(os.path.join(common.STATE_DIR, rabby.BOTUSD_NAME), {"v": 1, "t": int(now), "w": {a9: round(v9, 2) for a9, v9 in bot_w9.items()}})
                self._bot_usd_saved = dict(bot_w9)
            except OSError as e9:
                log.warning("지갑별 봇 평가 저장 실패(다음 빌드에 다시): %s", e9)
        if rb_view:
            for a9, wv9 in sorted(rb_view["wallets"].items(), key=lambda kv: -kv[1]["rabby"]):
                b9 = round(bot_w9.get(a9, 0.0), 2)
                rb_recon.append({"addr": a9, "label": rb_view["labels"].get(a9) or a9[:8], "bot": b9, "rabby": wv9["rabby"],
                                 "diff": round(wv9["rabby"] - b9, 2), "only": wv9["only"], "onlyDebt": wv9["onlyDebt"],
                                 "rest": round(wv9["rabby"] - b9 - wv9["only"] - wv9["onlyDebt"], 2),
                                 "fetchedAt": wv9["fetchedAt"], "top": wv9["top"],
                                 "skipped": {k9: v9 for k9, v9 in wv9["skipped"].items() if v9 >= 1}, "err": wv9.get("err")})
            try:
                gs9 = rabby.gap_track(os.path.join(common.STATE_DIR, rabby.GAP_NAME), rb_recon, now)
                for r9 in rb_recon:
                    if r9["addr"] in gs9:
                        r9["gapSince"] = gs9[r9["addr"]]
            except Exception as e9:
                log.warning("Rabby 차이 추적 실패: %s", e9)

        tc9 = self.cfg.get("transit") if isinstance(self.cfg.get("transit"), dict) else {}
        ask9 = now - float(tc9.get("ask_days", TRANSIT_ASK_DAYS)) * 86400
        for a9m, st9 in (getattr(self, "_of_man_state", None) or {}).items():
            fin9 = (sale_lot_by.get("of:" + a9m) or {}).get("fin")
            if fin9:
                st9["paidUsd"] = fin9[1]
                if fin9[0] == "ok":
                    st9["costUsd"] = fin9[2]
            for l9 in st9["links"].values():
                if l9.get("st") == "pending":
                    ap9 = of_applied.get(l9.get("pid"))
                    l9["st"] = "applied" if ap9 else (fin9[0] if fin9 and fin9[0] != "ok" else "other_path")
                    if ap9:
                        l9["cost"] = ap9[1]
        self._of_cands = of_cands
        cl_legs9 = {}
        dec_cl9 = self.outflow_decisions()
        for a9c, st9c in (getattr(self, "_of_man_state", None) or {}).items():
            for l9c in ((dec_cl9.get(a9c) or {}).get("links") or []):
                if not isinstance(l9c, dict):
                    continue
                s9c = (st9c.get("links") or {}).get(str(l9c.get("key") or "")) or {}
                cl_legs9.setdefault(a9c, []).append({"kind": l9c.get("kind"), "st": s9c.get("st"), "tx": l9c.get("tx"), "sym": l9c.get("sym"),
                                                     "qty": l9c.get("qty"), "where": l9c.get("where"), "key": self._of_key_cur(a9c, l9c)})
        self._of_claim_legs = cl_legs9
        self._ph("pendings")
        outflows_out, outflows_pending, of_tot = self._outflows(
            conn, ob, live_px, G, frozenset(quarantined), dust_ev,
            exwd=[e9 for e9 in wdt_all if e9["state"] == "out" and e9["ts"] >= ask9])
        try:
            st9 = getattr(self, "_outflow_status", None) or {}
            for e9 in (x9 for _k0, _s0, _c0, evs0 in pos_ev_full for x9 in evs0):
                o9 = e9.get("of")
                if o9 and o9.get("c") == "pending":
                    salelink.relabel(o9, st9.get(o9.get("a")), CHAIN_NAME.get(o9.get("ch"), o9.get("ch")))
            for e9 in extra_events + ev_main9 + ev_wd9 + ev_hid9:
                o9 = e9.get("of")
                if o9 and o9.get("c") == "pending":
                    salelink.relabel(o9, st9.get(o9.get("a")), CHAIN_NAME.get(o9.get("ch"), o9.get("ch")))
            sug9 = getattr(self, "_of_sug_pid", None) or {}
            if sug9:
                for _k0, _s0, _c0, evs0 in pos_ev_full:
                    for e9 in evs0:
                        x9 = sug9.get(e9.get("_pid"))
                        if x9 and "매도" not in str(e9.get("k") or ""):
                            e9["ofc"] = dict(x9)
                for e9 in extra_events + ev_hid9:
                    x9 = sug9.get(e9.get("_pid"))
                    if x9 and "매도" not in str(e9.get("k") or ""):
                        e9["ofc"] = dict(x9)
            def _ofc_cp9(dst9, src9):
                if len(dst9) != len(src9) or any(c9.get("t") != s9.get("t") or c9.get("k") != s9.get("k") or c9.get("tx") != s9.get("tx") for c9, s9 in zip(dst9, src9)):
                    return
                for c9, s9 in zip(dst9, src9):
                    if s9.get("ofc"):
                        c9["ofc"] = dict(s9["ofc"])
                    else:
                        c9.pop("ofc", None)
            src_ev9 = {k0: evs0 for k0, _s0, _c0, evs0 in pos_ev_full}
            for p9 in positions:
                cp9 = p9.get("events")
                if cp9 and p9.get("key") in src_ev9:
                    _ofc_cp9(cp9, src_ev9[p9["key"]][-len(cp9):])
            _ofc_cp9(extra_events_out, sorted(sorted(ev_main9, key=_k9)[-150:] + sorted(ev_wd9, key=_k9)[-150:], key=_k9))
            _ofc_cp9(extra_events_hidden, sorted(ev_hid9, key=_k9)[-150:])
        except Exception as e9:
            log.debug("세일 연결 제안 표식 실패: %s", e9)
        for p9 in pendings:
            h9 = (getattr(self, "_of_untracked_hint", None) or {}).get(acct_norm.canon(p9.get("sym")))
            if h9 and str(p9.get("key") or "").startswith(("unv:", "unkh:")):
                p9["bridgeSugg"] = {"day": h9["day"], "ex": h9["ex"], "net": h9["net"], "qty": _f(h9["qty"], 6),
                                    "bridgeUsd": _f(h9["usd"], 2), "bridges": h9["names"][:3]}
                p9["why"] = (p9.get("why") or "") + (f" · 같은 날({h9['day'][5:]}) 미추적 체인 브릿지({'·'.join(h9['names'][:3])}) 로 ${h9['usd']:,.0f} 를 보낸 뒤 "
                                                     f"{h9['net']} 네트워크로 {p9.get('sym')} {h9['qty']:,.6g} 입금 — 그 돈으로 산 코인이면 원가를 지정해 주세요(자동 연결 안 함)")

        xtra9 = {"ub": x_ub, "fiat": x_fiat, "lp": lp_total,
                 "ubs": x_ubs, "ub_tl": self._upbit_led_timeline(conn),
                 "krw_up": sum(f5["krw"] for f5 in fiats if f5["ex"] == "업비트"),
                 "krw_other": sum(f5["krw"] for f5 in fiats if f5["ex"] != "업비트"),
                 "rate": rate_fx,
                 "krw_up_tl": self._upbit_krw_timeline(conn) if up_fresh9 else None}
        self._ph("outflows")
        hl_cash9 = frozenset(gid9 for gid9, ex9 in ex_gid.items()
                             if ex9 == "hyperliquid" and str((G.get(gid9) or {}).get("sym") or "").upper() in hl_cash_syms9)
        try:
            self._hl_neg_mark(G, hl_cash9)
        except Exception as e9:
            log.warning("Hyperliquid 음수 허용 그룹 장기 곡선 표식 실패(다음 빌드): %s", e9)
        try:
            lg9 = conn.execute("SELECT v FROM meta WHERE k='ext_rebuilt_at'").fetchone()
            led_gen9 = int(float(lg9[0])) if lg9 and lg9[0] else 0
        except Exception:
            led_gen9 = 0
        daily = self._daily_series(G, today_kst, override_px, live_px,
                                   ca_gids=ca_all, ex_gids=set(ex_gid),
                                   skip_gids=quarantined, pending_gids=pending_gids, native_c=native_c9 | ex_c9,
                                   hold_qty=hold_qty, extra=xtra9, extra_ok=x_ok, now_ts=now, led_gen=led_gen9,
                                   neg_ok=hl_cash9,
                                   debt_moves=self._debt_redate_moves(conn),
                                   transit=[e9 for e9 in wdt_all if e9["state"] == "pending"],
                                   stable_aliases=_stable_regroup_aliases(conn),
                                   day_close=(histcurve.DAYCLOSE.resolver(G, ca_all, ex_gid, native_c9 | ex_c9, override_px, gid_pairs_all,
                                                                          STABLE_GROUPS, now) if DAYCLOSE_ON else None))
        if DAYCLOSE_ON:
            histcurve.DAYCLOSE.kick()
        try:
            if rb_view is not None or os.path.exists(RABBY_DAILY_PATH):
                tiso9 = today_kst.strftime("%Y-%m-%d")
                pw9 = {}
                if rb_view is not None:
                    for a9, wv9 in rb_view["wallets"].items():
                        pw9[a9] = round(wv9["only"] + wv9["onlyDebt"], 2)
                rb_note9 = rabby.daily_note(RABBY_DAILY_PATH, tiso9, rb_net, now, per_wallet=pw9) if rb_view is not None \
                    else rabby.load_state(RABBY_DAILY_PATH)
                rabby.daily_overlay(daily, rb_note9, tiso9, rb_net)
        except Exception as e9:
            log.warning("Rabby 일별 보강 실패: %s", e9)
        offc_ids9 = frozenset()
        vflow_loc9 = None
        try:
            offc_ids9 = frozenset({(f"{e9}:withdraw", u9) for e9, u9 in offc_wd if offc_self_wd(e9, u9)}
                                  | {(f"{e9}:deposit", u9) for e9, u9 in offc_dep if e9 in offc_on})
            flows9 = self._daily_flows(conn, daily, G, today_kst, live_px, frozenset(quarantined), rate_fx, transit=wdt_all,
                                       offc_ids=offc_ids9)
            vflow_loc9 = getattr(self, "_venue_flow", None)
            for row9 in daily:
                fl9 = flows9.get(row9.get("date"))
                row9["flow"] = fl9[0] if fl9 else 0
                if fl9 and fl9[1]:
                    row9["flowTop"] = fl9[1]
                if row9.get("rbNew"):
                    row9["flow"] = round(float(row9.get("flow") or 0) + float(row9["rbNew"]), 2)
                    row9["flowTop"] = [["Rabby 기준 첫 반영(봇 미추적 보유)", round(float(row9["rbNew"]), 2)]] + list(row9.get("flowTop") or [])[:2]
        except Exception as e9:
            log.warning("일별 순유입 계산 실패: %s", e9)
        try:
            pid_gid9, spoof_pids9 = {}, set()
            for r9 in rows:
                if r9["event"] not in flowev.EV_ALL:
                    continue
                if (r9["source_ns"], r9["source_id"], r9["asset_id"]) in spoof_keys or int(r9["qty_base"]) == 0:
                    spoof_pids9.add(r9["posting_id"])
                if r9["leg_kind"] == "move_in" and (r9["location"] or "").startswith("out:"):
                    pid_gid9[r9["posting_id"]] = r9["group_id"] or -r9["asset_id"]
            fm9 = {a9: o9["flow_matches"] for a9, o9 in ob.items() if o9.get("flow_matches")}
            of_rows_fe9 = [dict(r9, txs=list(r9.get("txs") or ()) + fm9[r9["address"]]) if r9.get("address") in fm9 else r9 for r9 in outflows_out]
            self._flow_ev = flowev.collect(
                conn, G, live_px, now, transit=wdt_all, of_rows=of_rows_fe9, of_match=of_match, of_bridge=of_bridge, deps=of_deps,
                offc_ids=offc_ids9, debts=StateBuilder._flow_debts(), skip_gids=frozenset(quarantined),
                names={"chain": CHAIN_NAME, "wallet": wallet_label}, fx=lambda t9: self.px.fx_at(int(t9 * 1000)) or rate_fx, xf_links=xf_links,
                proof_sends=[dict(s9, gid=pid_gid9.get(s9["pid"])) for s9 in of_sends], deposit_exchange=self._deposit_exchange,
                skip_pids=frozenset(spoof_pids9))
        except Exception as e9:
            log.warning("큰 출금 재료(flowev) 실패 — 이번 빌드는 판정 재료 없음: %s", e9)
        att_ok9 = False
        try:
            lpf9 = {}
            for b9 in lpb.values():
                for d9, v9 in (b9.get("rbd") or {}).items():
                    lpf9[d9] = lpf9.get(d9, 0.0) + float(v9)
            unv9 = {}
            for gid9, u9 in unverified.items():
                for d9, ud9 in (u9.get("by_date") or {}).items():
                    fb9 = (unv_fb9.get(d9) or {}).get(gid9) or (Decimal(0), Decimal(0))
                    q9, p9 = Decimal(ud9["qty"]) - fb9[0], Decimal(ud9["proceeds"]) - fb9[1]
                    if q9 > EPS or abs(p9) >= Decimal("0.005"):
                        unv9.setdefault(d9, {})[gid9] = (float(max(q9, Decimal(0))), float(p9))
            real9 = {"rbd": realized_by_date, "lpf": lpf9,
                     "stk": {d9: float(sum(v9[0] for v9 in s9.values())) for d9, s9 in stake_inc.items()}, "unv": unv9}
            pxd9 = (ca_all, ex_gid, native_c9 | ex_c9, override_px, gid_pairs_all, STABLE_GROUPS)
            pxs9 = (lambda gid9: histcurve.spec_of(histcurve.group_desc(gid9, G[gid9], *pxd9)) if gid9 in G else None) if DAYCLOSE_ON else None
            att9 = self._daily_attrib(conn, daily, G, today_kst, live_px, frozenset(quarantined), xtra9, real=real9, px_src=pxs9)
            att_ok9 = True
            for row9 in daily:
                if row9.get("date") in att9:
                    row9["att"] = att9[row9["date"]]
        except Exception as e9:
            log.warning("일별 자산 변동 분해 실패: %s", e9)
        if not att_ok9:
            self._att_by_today = {}
        try:
            hold_today9, spark7_9 = self._hold_today(coins, G, live_px, today_kst, self.daily_px, getattr(self, "_att_by_today", None))
        except Exception as e9:
            log.warning("보유표 오늘 변동·7일 추이 재료 실패: %s", e9)
            hold_today9, spark7_9 = {}, {}
        _daily_krw(daily, today_kst.strftime("%m-%d"))
        try:
            td9 = today_kst.strftime("%Y-%m-%d")
            hd9, hnf9, hok9 = _hist_kit_rows(daily, td9, self.daily, self.__dict__.get("_flow_nf") or (),
                                             val_nf=self.__dict__.get("_daily_nf") or ())
            if hnf9:
                log.debug("장기 곡선 재료: 비확정 지난날 %d(%s…) — 값 비워 넘김", len(hnf9), min(hnf9))
            if hok9:
                histcurve.HIST.offer(td9, lambda: histcurve.make_kit(
                    td9, G, hold_qty, quarantined, ca_all, ex_gid, native_c9 | ex_c9, override_px, live_px, gid_pairs_all,
                    [e9 for e9 in wdt_all if e9["state"] == "pending"], xtra9, hd9, self.daily, stable_syms=STABLE_GROUPS,
                    flow_kit=self._hist_flow_kit(G, quarantined, offc_ids9, wdt_all, rate_fx, td9, daily),
                    neg_ok=hl_cash9))
        except Exception as e9:
            log.warning("장기 곡선 재료 실패: %s", e9)
        disp_total = (sum(c["qty"] * (c.get("price") or 0) for c in coins)
                      + sum(s["qty"] * (s.get("price") or 0) for s in stables) + x_fiat + lp_total
                      + sum(d9["usd"] for d9 in rb_debts))
        if daily:
            gap9 = daily[-1]["val"] - disp_total
            diag["daily_today_gap_usd"] = round(gap9, 2)
            if abs(gap9) > 1:
                log.warning("일별 오늘값 ≠ 화면 총자산: %.2f vs %.2f (차 %.2f)", daily[-1]["val"], disp_total, gap9)

        self._ph("daily")
        fut = self._futures_view(fxb)
        lo9 = (today_kst - timedelta(days=40)).strftime("%Y-%m-%d")
        review_realized = {}
        for src9 in (realized_by_date, fut.get("realizedByDate") or {}):
            for day9, pnl9 in src9.items():
                if len(day9) == 10 and day9 < lo9:
                    continue
                k9 = acct_norm.mmdd(day9)
                review_realized[k9] = review_realized.get(k9, 0) + pnl9
        self._ph("futures")
        day_ix, day_acts = self._day_index(pos_ev_full, ev_main9 + ev_wd9, ev_hid9, lp_events)
        stab_ix = self._stab_index(stab_ev, day_acts)
        try:
            krw_ix9 = self._krw_day_index(conn, day_acts)
        except Exception as e9:
            log.warning("그날 기록 원화 입출금 색인 실패(목록에서 빠짐): %s", e9)
            krw_ix9 = {}
        self._day_idx = {"builtAt": int(now), "ix": day_ix, "rbd": realized_by_date, "stab": stab_ix, "krw": krw_ix9,
                         "fut": fut.get("realizedByDate") or {},
                         "tax": tax_rows, "taxToday": today_kst,
                         "futDetail": getattr(self, "_fut_detail", None),
                         "futEv": getattr(self, "_fut_ev", None), "futStale": list(fut.get("staleExchanges") or ()),
                         "futAccts": getattr(self, "_fut_accts", None) or {},
                         "pos": positions}
        acts_md9 = {acct_norm.mmdd(k9): v9 for k9, v9 in day_acts.items() if k9 >= lo9}
        self._ph("day_index")
        reviews = self._auto_reviews(daily, review_realized, acts_md9)
        reviews_weekly = self._merge_llm_reviews(reviews, day_ix, realized_by_date, fut.get("realizedByDate") or {},
                                                 today_kst.strftime("%Y-%m-%d"),
                                                 {k9: round(v9) for k9, v9 in realized_krw_by_date.items() if k9 in realized_by_date},
                                                 fut.get("realizedKrwByDate") or {})
        review_prog = None
        if review_progress is not None:
            try:
                rdays9 = sorted({str(k9) for src9 in (realized_by_date, fut.get("realizedByDate") or {}) for k9, v9 in src9.items()
                                 if len(str(k9)) == 10 and abs(float(v9 or 0)) >= 0.5})
                drv9 = {rv9["iso"]: rv9 for rv9 in reviews.values() if isinstance(rv9, dict) and rv9.get("iso") and isinstance(rv9.get("fp"), dict)}
                review_prog = review_progress.view(REVIEW_PROGRESS_PATH, drv9, reviews_weekly, rdays9, today_kst.strftime("%Y-%m-%d"),
                                                   prefs.get("review_fill"))
            except Exception as e:
                log.warning("AI 리뷰 진행 상황 읽기 실패(표시 생략): %s", e)

        coin_dex = coin_cex = 0.0
        for c9 in coins:
            px9 = c9.get("price") or 0
            for l9 in c9.get("locs") or []:
                q9 = (l9.get("qty") or 0) * px9
                if "지갑" in (l9.get("w") or ""):
                    coin_dex += q9
                else:
                    coin_cex += q9
        for lst9 in ex_transit.values():
            for e9 in lst9:
                if not e9.get("used"):
                    diag["ex_transit_unused_cost"] += e9.get("cost", Decimal(0))
        diag.update({"fee_" + k9: v9 for k9, v9 in fee_diag.items()})
        diag_out = {k: (float(v) if isinstance(v, Decimal) else v) for k, v in diag.items()}
        offc_sum9 = offc_summary()
        self._offc_addrs = {}
        for (e9, u9), a9 in offc_wd_addr.items():
            if a9:
                self._offc_addrs.setdefault(e9, set()).add(a9)

        with self._origin_lock:
            self._origin_pending |= {t for t in origin_pending if not oc_fresh(t)}
        cost_ov_rows = []
        for k9, v9 in (cost_ov.items() if isinstance(cost_ov, dict) else []):
            try:
                gid9 = int(str(k9)[1:])
            except ValueError:
                continue
            g9 = G.get(gid9) or {}
            ovs9 = g9.get("ov_applied") or [Decimal(0), Decimal(0)]
            v9 = v9 if isinstance(v9, dict) else {}
            cost_ov_rows.append({"key": str(k9), "sym": g9.get("sym") or str(k9), "mode": str(v9.get("mode") or "unit"),
                                 "unit": _f(float(v9.get("unit") or 0), 6) or 0,
                                 "qty": _f(float(ovs9[0]), 4) or 0, "cost": _f(float(ovs9[1]), 2) or 0})
        for k9 in sorted(cost_be):
            try:
                gid9 = int(str(k9)[1:])
            except ValueError:
                continue
            if be_until(gid9) is None:
                continue
            bd9 = be_done.get(gid9) or {}
            cost_ov_rows.append({"key": str(k9) + ":be", "gkey": str(k9), "sym": (G.get(gid9) or {}).get("sym") or bd9.get("sym") or str(k9), "mode": "breakeven", "unit": 0,
                                 "qty": _f(float(bd9.get("qty") or 0), 4) or 0, "cost": _f(float(bd9.get("proceeds") or 0), 2) or 0,
                                 "n": bd9.get("n") or 0, "untilT": datetime.fromtimestamp(be_until(gid9), KST).strftime("%m-%d %H:%M")})
        wd_rows9 = getattr(self, "_wd_dest_rows", None) or []
        unk9 = {}
        for w9 in wd_rows9:
            if w9["cls"] != "unknown":
                continue
            e9 = fx_transit.get(w9["txid"]) if w9["txid"] else None
            u9 = unk9.setdefault(w9["addr"], {"address": w9["addr"], "n": 0, "costUsd": 0.0, "costKnown": 0, "syms": set(), "exchanges": set(),
                                              "networks": set(), "first": w9["ts"], "last": w9["ts"], "sentToMine": 0, "walletTx": 0, "hop": 0,
                                              "offcN": 0})
            u9["n"] += 1
            if _offc_tx(w9["txid"]):
                u9["offcN"] += 1
            if e9 and e9.get("qty") and not e9.get("ambiguous"):
                q9 = _dec_or0(w9["qty"])
                u9["costUsd"] += float(e9["cost"] * (q9 / e9["qty"])) if e9["qty"] > 0 else 0.0
                u9["costKnown"] += 1
            u9["syms"].add(w9["sym"]); u9["exchanges"].add(w9["ex"])
            if w9["network"]:
                u9["networks"].add(w9["network"])
            u9["first"] = min(u9["first"], w9["ts"]); u9["last"] = max(u9["last"], w9["ts"])
        if unk9:
            for t9, oc9 in (origin_cache or {}).items():
                f9 = xfer_match.norm_addr((oc9 or {}).get("from"))
                if f9 in unk9:
                    unk9[f9]["sentToMine"] += 1
            for xl9 in (getattr(self, "_xfer_links_last", None) or {}).values():
                if xl9.get("via") in unk9:
                    unk9[xl9["via"]]["hop"] += 1
            for f9, n9 in self._raw_from_counts(conn).items():
                if f9 in unk9:
                    unk9[f9]["walletTx"] += n9
            for gid9, g9 in G.items():
                srcs9 = g9.get("unk_src") or []
                u9 = unverified.get(gid9)
                if not srcs9 or not u9 or float(u9["proceeds"]) < 1.0:
                    continue
                by9 = {}
                for x9 in srcs9:
                    f9 = x9.get("from") or ((origin_cache or {}).get(str(x9.get("ref") or "").lower()) or {}).get("from")
                    f9 = xfer_match.norm_addr(f9) if f9 else None
                    if f9 in unk9 and not x9.get("via"):
                        by9[f9] = by9.get(f9, 0.0) + float(x9["qty"])
                tot9 = sum(float(x9["qty"]) for x9 in srcs9)
                for a9, q9 in by9.items():
                    r9 = unk9[a9].setdefault("_res", {})
                    r9[g9.get("sym") or "?"] = r9.get(g9.get("sym") or "?", 0.0) + float(u9["proceeds"]) * min(1.0, q9 / tot9 if tot9 > 0 else 0.0)
            for u9 in unk9.values():
                r9 = u9.pop("_res", None) or {}
                if r9:
                    u9["resolveUsd"] = round(sum(r9.values()), 2)
                    u9["resolveSyms"] = [[s9, round(v9, 2)] for s9, v9 in sorted(r9.items(), key=lambda kv: -kv[1])[:6]]
        wd_dest_unknown = sorted(({**u9, "syms": sorted(u9["syms"])[:12], "exchanges": sorted(u9["exchanges"]), "networks": sorted(u9["networks"])[:8],
                                   "costUsd": round(u9["costUsd"], 2), "strong": bool(u9["sentToMine"] or u9["walletTx"] or u9["hop"])}
                                  for u9 in unk9.values()), key=lambda u9: (not u9["strong"], -(u9.get("resolveUsd") or 0), -u9["costUsd"], -u9["n"]))
        self._wd_dest_unknown = {u9["address"]: u9 for u9 in wd_dest_unknown}
        try:
            self._attach_flows(conn, outflows_out, live_px, G)
        except Exception as e:
            log.warning("flow 붙이기 실패: %s", e)
        try:
            self._addr_ai_targets = addr_ai.attach(outflows_out, pendings, self.cfg)
        except Exception as e:
            log.warning("AI 주소 의견 붙이기 실패: %s", type(e).__name__)
        cls_n9 = {}
        for w9 in wd_rows9:
            cls_n9[w9["cls"]] = cls_n9.get(w9["cls"], 0) + 1
        xl_all9 = getattr(self, "_xfer_links_all", None) or {}
        xl_on9 = getattr(self, "_xfer_links_last", None) or {}
        xfer_links_out = [{"dep": k9, "wd": v9["wd_uuid"], "sym": v9["sym"], "qty": v9["qty"], "wdEx": v9["wd_ex"], "depEx": v9["dep_ex"],
                           "rule": v9["rule"], "label": v9["label"], "dt": v9["dt"], "via": v9.get("via"), "off": k9 not in xl_on9}
                          for k9, v9 in sorted(xl_all9.items(), key=lambda kv: (kv[1]["sym"], kv[0]))]
        my_w9 = {str(w9.get("address") or "").lower() for w9 in self._hist_wallets() if isinstance(w9, dict)}
        sale_out = []
        for l9 in sale_lots:
            u9 = sale_used.get(l9["id"]) or {}
            sale_out.append({"lot": l9["id"], "sym": l9["sym"], "chain": l9["chain"], "auction": l9["auction"], "bidder": l9["bidder"],
                             "bidderMine": l9["bidder"] in my_w9, "label": l9["label"], "cur": l9["cur"], "bids": l9["bids"],
                             "paid": _f(l9["paid"], 6), "refund": _f(l9["refund"], 6), "paidUsd": _f(l9["paid_usd"], 2),
                             "refundUsd": _f(l9["refund_usd"], 2), "costUsd": _f(l9["cost"], 2), "qty": _f(l9["qty"], 6),
                             "unit": float(l9["unit"]), "receiptSym": l9.get("receipt_sym"), "bidTx": l9["bid_tx"][:5], "claimTx": l9["claim_tx"][:5],
                             "usedQty": _f(u9.get("qty") or 0, 6) or 0, "usedCost": _f(u9.get("cost") or 0, 2) or 0, "usedN": u9.get("n") or 0,
                             "rows": u9.get("rows") or [], "off": bool(l9["off"])})
        self._sale_lot_ids = {l9["id"] for l9 in sale_lots}
        self._sale_prio = {str(u9.get("sym") or "").upper() for u9 in unverified.values() if u9.get("sym")}
        diag_out["open_cancel_pairs"] = getattr(self, "_open_cancel_n", 0)
        diag_out["unv_all"] = {"rows": len(unverified), "proceeds": round(float(sum((u9["proceeds"] for u9 in unverified.values()), Decimal(0))), 2),
                               "by": {str(g9): round(float(u9["proceeds"]), 2) for g9, u9 in unverified.items()}}
        diag_out["sale_lots"] = len(sale_lots)
        diag_out["sale_links"] = len(sale_links)
        diag_out["sale_cost_usd"] = round(float(sum((u9["cost"] for u9 in sale_used.values()), Decimal(0))), 2)
        diag_out["sale_heuristic"] = len((common.read_json(SALE_PATH, {}) or {}).get("heuristic") or [])
        diag_out["workers"] = sorted(n9 for n9 in self._thread_names() if n9.endswith("-worker"))
        diag_out["net_pace"] = netpace.stats()
        diag_out["proof_diverge"] = list(self.spot.proof_div)
        diag_out["goplus"] = dict(GOPLUS_STATUS)
        diag_out["ex_dead"] = dict(self.spot.ex_dead)
        diag_out["pos_cut"] = pos_cut9
        dead_held9 = []
        for c9 in coins:
            k9 = c9.get("key") or ""
            if not (k9.startswith("g") and k9[1:].isdigit()):
                continue
            gid9 = int(k9[1:])
            ex9 = ex_gid.get(gid9)
            sym9 = (G.get(gid9) or {}).get("sym")
            if ex9 and (c9.get("qty") or 0) > 0 and not c9.get("price") and sym9 in (self.spot.ex_dead_syms.get(ex9) or ()):
                dead_held9.append({"ex": ex9, "sym": sym9, "qty": c9["qty"], "ref": (c9.get("pxRef") or {}).get("px")})
        diag_out["ex_dead_held"] = dead_held9
        diag_out["unpriced_held"] = [{"sym": w9["sym"], "where": w9["where"], "qty": w9["qty"], "cost": round(w9["cost"], 2), "ref": round(w9["ref"], 2)}
                                     for w9 in sorted(unpriced_w, key=lambda w9: -max(w9["cost"], w9["ref"]))[:10]
                                     if max(w9["cost"], w9["ref"]) >= 1]
        dex_rows9 = sorted((float(c9.get("pxAge") or 0), c9["qty"] * float(c9.get("price") or 0)) for c9 in coins
                           if str(c9.get("pxSrc") or "").startswith("dex:") and c9.get("pxAge") is not None and not c9.get("pxFrozen")
                           and (c9.get("price") or 0) > 0 and (c9.get("qty") or 0) > 0)
        dex_tot9 = sum(v9 for _a9, v9 in dex_rows9)
        p90w9, acc9 = None, 0.0
        for a9, v9 in dex_rows9:
            acc9 += v9
            if dex_tot9 > 0 and acc9 >= 0.9 * dex_tot9:
                p90w9 = a9
                break
        neg_nd9 = [n9 for n9 in neg_hold if not n9.get("debt") and n9["usd"] <= -NEG_DIAG_MIN_USD]
        neg_pd9 = [n9 for n9 in neg_nd9 if n9.get("pend")]
        wd9 = {"ts": int(now),
               "neg": {"n": len(neg_nd9), "usd": round(sum(n9["usd"] for n9 in neg_nd9), 2),
                       "top": [{k9: n9[k9] for k9 in ("sym", "loc", "usd")} | ({"pend": True} if n9.get("pend") else {}) for n9 in neg_nd9[:3]],
                       "pend": {"n": len(neg_pd9), "usd": round(sum(n9["usd"] for n9 in neg_pd9), 2)}},
               "proof_div": list(self.spot.proof_div), "ex_dead": dict(self.spot.ex_dead), "ex_dead_held": dead_held9,
               "unpriced_held": diag_out["unpriced_held"],
               "gt": dict(self.spot.gt_stat), "ds": dict(self.spot.ds_stat), "goplus": dict(GOPLUS_STATUS, started=int(GOPLUS_T0)),
               "dex_age": {"n": len(dex_rows9), "usd": round(dex_tot9, 2), "p90w": p90w9,
                           "max": dex_rows9[-1][0] if dex_rows9 else None},
               "build": dict(build_stats(self.__dict__.get("_build_hist") or []), cold_ms=self.__dict__.get("_build_cold_ms")),
               "build_hist": list(self.__dict__.get("_build_hist") or []),
               "build_ex": [dict(x9) for x9 in (self.__dict__.get("_build_ex") or [])],
               "phases": self._ph_view(),
               "build_proc": buildproc.status(),
               "rabby": ({"wallets": [{k9: r9[k9] for k9 in ("addr", "label", "bot", "rabby", "diff", "only", "rest", "fetchedAt", "top") if k9 in r9}
                                      | ({"gapSince": r9["gapSince"]} if r9.get("gapSince") else {})
                                      for r9 in rb_recon], "status": rb_view["state"]} if rb_view is not None else None)}
        diag_out["dex_age"] = wd9["dex_age"]
        if time.time() - self.__dict__.get("_wdiag_at", 0) >= 60:
            try:
                common.atomic_write_json(WEB_DIAG_PATH, wd9)
                self._wdiag_at = time.time()
            except OSError as e9:
                log.warning("web_diag.json 쓰기 실패: %s", e9)
        if not self.spot.rate and time.time() - float(self.__dict__.get("_rate_fb_warn") or 0) > 3600:
            self._rate_fb_warn = time.time()
            log.warning("지금 환율(KRW/USDT)을 아직 못 받아 원화 환산에 고정 대체값 1384 를 씀 — 시세 수집이 돌면 저절로 바뀜")
        fields = {
            "costOverrideRows": cost_ov_rows,
            "costDecidedRows": cost_decided_rows,
            "saleLinks": sale_out,
            "xferLinks": xfer_links_out, "wdDestStats": cls_n9, "wdDestUnknown": wd_dest_unknown[:100], "wdDestUnknownTotal": len(wd_dest_unknown),
            "xchainLinks": sorted(xc_used.values(), key=lambda x9: -x9["ts"])[:200], "xchainPending": len(xc_cands),
            "coinDexUsd": round(coin_dex, 2), "coinCexUsd": round(coin_cex, 2),
            "futures": fut,
            "_diag": diag_out,
            "stables": stables, "coins": coins, "fiats": fiats, "exDebts": ex_debts, "negHoldings": neg_hold[:50],
            "rabbyDebts": rb_debts,
            "rabby": ({"wallets": rb_recon, "onlyUsd": rb_view["onlyUsd"], "debtUsd": round(sum(d9["usd"] for d9 in rb_debts), 2),
                       "at": rb_view["at"], "status": rb_view["state"]} if rb_view is not None else None),
            "outflows": outflows_out, "outflowsPending": outflows_pending, "outflowsTotals": of_tot,
            "walletAuto": bool(self.__dict__.get("_of_auto_reload")),
            "saleCandAlert": prefs.get("sale_cand_alert") is not False,
            "krwFlows": self._krw_flows(conn),
            "transits": [dict(self._transit_loc(e9, now)["tr"], sym=e9["sym"], qty=float(e9["qty"]), key=f"g{e9['gid']}")
                         for e9 in wdt_all if e9["state"] == "pending"],
            "lps": lps_out, "lpEvents": lp_events_out,
            "lpsPending": lps_pending, "lpsClosed": lps_closed[:200] + [l9 for l9 in lps_closed[200:] if l9.get("realizedByDay")],
            "lpRealized": _f(float(sum((b9["realized"] + b9["income"]) for b9 in lpb.values())), 2) or 0,
            "stakeRealized": _f(float(sum(v9[0] for d9 in stake_inc.values() for v9 in d9.values())), 2) or 0,
            "positions": positions, "plans": plans_out, "planMemos": plan_memos,
            "dayMemos": day_memos9, "dayMemosOk": True, **({"dayMemosErr": day_memos_err9} if day_memos_err9 else {}),
            "pendings": pendings, "gasByChain": gas_list,
            "taxRows": [{k9: v9 for k9, v9 in r9.items() if not k9.startswith("_")}
                         for r9 in sorted(tax_rows, key=lambda r9: str(r9.get("sold") or ""))[-100:]],
            "extraEvents": extra_events_out, "extraEventsHidden": extra_events_hidden,
            "dayActs": day_acts,
            "extraEventsTotal": {"main": len(ev_main9), "wd": len(ev_wd9), "hidden": len(ev_hid9),
                                 "hiddenScam": hid_kind_n9.get("scam", 0), "hiddenDust": hid_kind_n9.get("dust", 0),
                                 "wdHidden": n_wd_hid9},
            "taxSummary": _tax_summary(tax_rows, today_kst), "taxRowsTotal": len(tax_rows),
            "srcWhitelist": list(prefs.get("src_whitelist") or []),
            "realizedByDate": {k: round(v, 2) for k, v in realized_by_date.items()},
            "dateKeys": "iso",
            "realizedKrwByDate": {k: round(v) for k, v in realized_krw_by_date.items() if k in realized_by_date},
            "reviews": reviews,
            "reviewsWeekly": reviews_weekly,
            "rate": self.spot.rate or 1384,
            "fxRate": self.spot.fx_basis or (self.spot.rate or 1384),
            "rateSrc": "live" if self.spot.rate else "fallback",
            "dailySeries": daily,
            "todayByCoin": hold_today9, "spark7": spark7_9,
            "usdtByDate": {d["date"]: {"usdt": d["usdt"], "kimp": d["kimp"]} for d in daily},
            "lastScan": self._last_scan_str(),
            "upbitConnected": (bool(ub2)
                               and time.time() - (ub2.get("ts") or 0) < 600),
            "srcChips": src_chips, "walletRows": wallet_rows,
            "venueFlows30": _venue_flows30(vflow_loc9, realized_by_loc, venue_w, today_kst),
            "exBalTs": dict({fx_name.get(e9, e9): round(t9) for e9, (_p9, t9) in bal_src9.items() if t9 > 0},
                            **({"업비트": round(float(ub2.get("ts") or 0))} if float(ub2.get("ts") or 0) > 0 else {})),
            "depositRows": deposit_rows, "aliasRows": [],
            "unpricedSyms": [w9["sym"] for w9 in sorted(unpriced_w, key=lambda w9: -max(w9["cost"], w9["ref"]))],
            "unpricedTop": [dict(w9, cost=round(w9["cost"], 2), ref=round(w9["ref"], 2))
                            for w9 in sorted(unpriced_w, key=lambda w9: -max(w9["cost"], w9["ref"]))[:20] if max(w9["cost"], w9["ref"]) >= 1],
            "backfillProgress": self._backfill_progress(conn),
            "backfillSince": self._backfill_since_view(conn),
            "gasByMonth": {m: [{"chain": CHAIN_NAME.get(c, c), "spot": _f(v["usd"], 2) or 0,
                                "tx": v["tx"]}
                               for c, v in sorted(mm.items(), key=lambda kv: -kv[1]["usd"])]
                           + [{"chain": exfee_lab(e9), "spot": _f(v9["usd"], 2) or 0, "tx": v9["tx"], "kind": "exfee"}
                              for e9, v9 in sorted((ex_fee_m.get(m) or {}).items(), key=lambda kv: -kv[1]["usd"])]
                           for m in sorted(set(gas_by_month) | set(ex_fee_m)) for mm in [gas_by_month.get(m) or {}]},
            "taxGas": tax_gas,
            "gasExpenseByDate": {k9: [_f(v9[0], 2), v9[1],
                                      {kk9: {"usd": _f(x9[0], 2), "n": x9[1],
                                             "top": {"usd": _f(x9[2], 2), "ts": x9[3],
                                                     "t": datetime.fromtimestamp(x9[3], KST).strftime("%H:%M") if x9[3] else "",
                                                     "chain": x9[4]}}
                                       for kk9, x9 in sorted(v9[3].items(), key=lambda kv9: -kv9[1][0])}]
                                 for k9, v9 in sorted(gas_expense.items())},
            "walletAlias": {(w["address"] if w.get("type") == "sol"
                             else w["address"].lower()):
                            (prefs.get("aliases", {}).get(
                                w["address"] if w.get("type") == "sol"
                                else w["address"].lower())
                             or w.get("label") or w["address"][:8])
                            for w in self._hist_wallets()},
            "dustUsd": dust_usd_eff(prefs),
            "fallbackOn": fb_on,
            "offchainSelf": offc_sum9,
            "reviewLen": review_len_eff(prefs),
            "reviewProgress": review_prog,
            "reviewFill": review_progress.fill_eff(prefs.get("review_fill")) if review_progress is not None else None,
            "reviewPause": review_pause_eff(prefs),
            "legacyPages": {"classic": os.path.isfile(os.path.join(WEB_DIR, "index.html")), "futures": os.path.isfile(os.path.join(WEB_DIR, "futures.html"))},
            "originPending": len(origin_pending),
            "costOverrides": cost_ov,
            "costBreakeven": cost_be,
            "priceGuard": {k9: v9 for k9, v9 in self.spot.guarded.items() if k9 in guard_held9},
            "balanceCheck": balcheck.view(),
        }
        if os.environ.get("TJ_REPLAY_DEBUG") == "1":
            fields["_taxRowsAll"] = tax_rows
            fields["_positionsAll"] = _pos_all_dbg
            fields["_xferLinks"] = getattr(self, "_xfer_links_last", None)
            fields["_groupsDbg"] = {str(gid9): {"sym": g9["sym"], "stable": bool(g9["is_stable"]), "fiat": bool(g9.get("is_fiat")),
                                                "quar": gid9 in quarantined,
                                                "rbd": {k9: float(v9) for fl9 in g9["flows"] for k9, v9 in fl9["rbd"].items()}}
                                    for gid9, g9 in G.items() if any(fl9["rbd"] for fl9 in g9["flows"])}
            fields["_lpRbd"] = {k9: {d9: float(v9) for d9, v9 in b9["rbd"].items()} for k9, b9 in lpb.items() if b9["rbd"]}
        try:
            spamguard.annotate(fields)
        except Exception as e9:
            log.warning("심볼 정리 실패(무시): %s", e9)
        return {"fields": fields, "todayKey": today_kst.strftime("%m-%d"), "todayIso": today_kst.strftime("%Y-%m-%d"),
                "realizedMonth": round(realized_month, 2), "builtAt": int(now)}

    BF_REQ_PATH = os.path.join(common.STATE_DIR, "backfill_request.json")

    def _backfill_since_view(self, conn=None):
        try:
            req = common.read_json(self.BF_REQ_PATH, {}) if os.path.exists(self.BF_REQ_PATH) else {}
        except BaseException:
            req = {}
        months = float(self.cfg.get("backfill_months") or 5)
        base_t0 = int(time.time() - months * 30 * 86400)
        secs = sorted(k for k, v in (self.cfg.get("chains") or {}).items() if isinstance(v, dict))
        secs += [x for x in ("bsc", "sol") if isinstance(self.cfg.get(x), dict)] + ["upbit"]
        per = {}
        for sec in secs:
            t9 = bf_engine.SINCE.target(sec)
            if t9:
                per[sec] = datetime.fromtimestamp(t9, KST).strftime("%Y-%m-%d")
        jobs = []
        for unit, items in bf_engine.read_status().items():
            if not isinstance(items, dict) or unit.startswith("_"):
                continue
            for key, it in items.items():
                if isinstance(it, dict) and (key.endswith(":extend") or it.get("phase") == "extend"):
                    jobs.append({"key": key, "unit": unit, "phase": it.get("phase"), "done": it.get("done"),
                                 "total": it.get("total"), "eta": it.get("eta_sec"), "note": it.get("note"),
                                 "updated": it.get("updated")})
        meta = {}
        try:
            c9 = conn if conn is not None else dbm.open_db(common.DB_PATH, readonly=True)
            try:
                for r9 in c9.execute("SELECT k, v FROM meta WHERE k IN ('ext_rebuilt_at', 'ext_rebuild_fail_at', 'ext_rebuild_fails',"
                                     " 'ext_rebuild_last_error', 'ext_rebuild_started_at', 'rebuild_not_before')"
                                     " OR k LIKE 'ext_prewindow:%'").fetchall():
                    meta[r9["k"]] = r9["v"]
            finally:
                if c9 is not conn:
                    c9.close()
        except Exception:
            pass
        g9 = bf_engine.SINCE.target(None)
        return {"windowStart": datetime.fromtimestamp(min(base_t0, g9) if g9 else base_t0, KST).strftime("%Y-%m-%d"),
                "defaultStart": datetime.fromtimestamp(base_t0, KST).strftime("%Y-%m-%d"), "months": months,
                "request": req if isinstance(req, dict) else {}, "per": per, "sections": secs, "jobs": jobs,
                "pendingRebuild": {k[len("ext_prewindow:"):]: v for k, v in meta.items() if k.startswith("ext_prewindow:")},
                "rebuiltAt": int(float(meta["ext_rebuilt_at"])) if meta.get("ext_rebuilt_at") else None,
                "rebuildFailAt": int(float(meta["ext_rebuild_fail_at"])) if meta.get("ext_rebuild_fail_at") else None,
                "rebuildFails": int(meta.get("ext_rebuild_fails") or 0),
                "rebuildLastError": (meta.get("ext_rebuild_last_error") or None),
                "rebuildRunning": bool(meta.get("ext_rebuild_started_at")) and (self.cfg.get("backfill") or {}).get("auto_rebuild") is not False
                and time.time() - float(meta.get("ext_rebuild_started_at") or 0)
                < float((self.cfg.get("backfill") or {}).get("rebuild_timeout_sec") or 5400) + 600,
                "rebuildNotBefore": int(float(meta["rebuild_not_before"])) if meta.get("rebuild_not_before") and
                float(meta["rebuild_not_before"]) > time.time() else None}

    OUTFLOW_SALE_CAT = "세일 참가금"
    OUTFLOW_CATEGORIES = ("송금·결제/선물", OUTFLOW_SALE_CAT, "분실·해킹", "기타")
    OUTFLOW_PATH = os.path.join(common.STATE_DIR, "outflow_decisions.json")

    @staticmethod
    def _dec_core(e):
        return {k9: v9 for k9, v9 in e.items() if k9 not in ("memo", "ts")} if isinstance(e, dict) else None

    def of_memo_only(self, a, old, new) -> bool:
        co, cn = self._dec_core(old), self._dec_core(new)
        if co is not None and co == cn:
            return True
        if co in (None, {}) and cn in (None, {}):
            return a not in ((self.__dict__.get("_of_auto") or {}).get("proven") or {})
        return False

    def of_row_patch(self, a, new, old) -> dict:
        e9 = new if isinstance(new, dict) else {}
        o9 = old if isinstance(old, dict) else {}
        v9 = e9.get("verdict")
        st0 = (self.__dict__.get("_outflow_status") or {}).get(a)
        still = a in (self.__dict__.get("_outflow_still") or ())
        st = None
        if v9 == "external":
            st = "external"
        elif v9 == "exchange":
            st = "exchange_applying" if still else "exchange"
        elif v9 == "own":
            st = "own_restart_needed" if still else "own"
        elif self._dec_core(old) == self._dec_core(new) or (self._dec_core(old) in (None, {}) and self._dec_core(new) in (None, {})):
            st = st0
        elif v9 == "clear" and e9.get("ret") is True and o9.get("ret") is not True and not e9.get("noAuto") and not o9.get("noAuto") \
                and o9.get("verdict") in (None, "clear") and st0 in ("pending", "bridge_untracked"):
            st = "returned"
        out = {"status": st, "verdict": v9 or None, "category": e9.get("category"), "memo": e9.get("memo"), "alias": e9.get("alias"),
               "noAuto": bool(e9.get("noAuto")), "decidedTs": e9.get("ts"),
               "excludeLegs": [str(k0.get("key") if isinstance(k0, dict) else k0) for k0 in (e9.get("excludeLegs") or []) if isinstance(k0, (str, dict))][:200]}
        if st is not None:
            out["retOk"] = bool(e9.get("ret") is True and st == "returned")
        if st == "own_restart_needed":
            try:
                import wallet_register as _wr9
                out["applyWait"] = bool(_wr9.auto_reload_alive() and a in _wr9.pending_addrs())
            except Exception:
                out["applyWait"] = False
        if e9.get("exchange"):
            out["exchange"] = e9["exchange"]
        return out

    def outflow_decisions(self) -> dict:
        d = common.read_json(self.OUTFLOW_PATH, {}) if os.path.exists(self.OUTFLOW_PATH) else {}
        dd = d.get("decisions") if isinstance(d, dict) else None
        return dd if isinstance(dd, dict) else {}

    OF_LINK_KINDS = ("refund", "tokens")
    OF_LINK_MAX = 40
    OF_IN_EVENTS = ("TRANSFER_IN", "PROGRAM_IN", "EX_DEPOSIT", "EXF_DEPOSIT")

    @staticmethod
    def _of_key(r) -> str:
        try:
            sk = r["source_kind"]
        except (IndexError, KeyError):
            sk = "exchange" if str(r["location"] or "").startswith("exchange:") else "chain_tx"
        return f"{sk}|{r['source_ns']}|{r['source_id']}|{int(r['leg_seq'])}"

    @staticmethod
    def _of_asset(r) -> str:
        return f"{r['kind']}:{r['chain'] or ''}:{str(r['address'] or r['symbol'] or '').lower()}"

    @staticmethod
    def _of_stable_row(r) -> bool:
        return bool((r["gname"] or "") in STABLE_GROUPS
                    or (r["kind"] == "exchange_currency" and _ex_stable_sym(r["symbol"])))

    def _of_where(self, w: str) -> str:
        w = str(w or "")
        if w.startswith("ex:"):
            return self.EX_NAME_KO.get(w[3:], w[3:]) if isinstance(getattr(self, "EX_NAME_KO", None), dict) else w[3:]
        if w.startswith("w:"):
            ad9 = w[2:]
            k9 = ad9.lower() if ad9.startswith("0x") else ad9
            for w9 in self._hist_wallets():
                if isinstance(w9, dict) and w9.get("address"):
                    a9 = str(w9["address"])
                    if (a9.lower() if a9.startswith("0x") else a9) == k9 and w9.get("label"):
                        return str(w9["label"])
            return ad9[:6] + "…" + ad9[-4:] if len(ad9) > 12 else ad9
        return w

    OF_CAND_WINDOW = 60 * 86400
    SALE_CAND_PATH = os.path.join(common.STATE_DIR, "sale_cand_alerts.json")

    def _of_sale_cands(self, a, first_ts, stable_syms, px_of=None, skip=()) -> list:
        cl9 = getattr(self, "_of_claims", None) or {}
        rr9 = getattr(self, "_risk_reasons", None) or {}
        taken9 = {str(l9.get("key")) for v9 in self.outflow_decisions().values() if isinstance(v9, dict) for l9 in (v9.get("links") or [])
                  if isinstance(l9, dict)}
        out = []
        for c9 in (getattr(self, "_of_cands", None) or {}).values():
            if not (first_ts <= int(c9["ts"]) <= first_ts + self.OF_CAND_WINDOW) or c9["key"] in cl9 or c9["key"] in taken9 or c9.get("sale"):
                continue
            if c9["key"] in skip:
                continue
            if c9.get("gid") in rr9:
                continue
            q9 = float(c9.get("qty") or 0)
            if c9.get("stable"):
                if str(c9.get("sym") or "").upper() not in stable_syms or q9 < 1:
                    continue
            else:
                p9 = float(px_of(c9.get("gid")) or 0) if px_of else 0.0
                if q9 <= 0 or (p9 > 0 and q9 * p9 < 1):
                    continue
            out.append(c9["key"])
        return sorted(out)

    def _sale_cand_notify(self, cands: dict):
        if self.prefs().get("sale_cand_alert") is False:
            return
        first9 = not os.path.exists(self.SALE_CAND_PATH)
        seen = {} if first9 else (common.read_json(self.SALE_CAND_PATH, {}) or {})
        if not isinstance(seen, dict):
            seen = {}
        d9 = seen.setdefault("dests", {})
        changed = first9
        out9 = []
        for a, keys in sorted(cands.items()):
            old9 = set(d9.get(a) or [])
            new9 = [k9 for k9 in keys if k9 not in old9]
            if not new9:
                continue
            if not first9:
                out9.append({"ts": int(time.time()), "kind": "SALE_CAND", "sym": "",
                             "text": f"🔗 세일 참가금 {salelink.name_addr(a, self.outflow_decisions().get(a))} 에 연결할 후보가 생겼어요 — 새 {len(new9)}건"
                                     f"(모두 {len(keys)}건) · 보낸 내역 › 정리된 내역에서 '받은 것과 연결'"})
            d9[a] = sorted(old9 | set(keys))
            changed = True
        if changed:
            seen["v"] = 1
            common.atomic_write_json(self.SALE_CAND_PATH, seen)
        for x9 in out9:
            _append_alert(x9)
            log.info("세일 참가금 후보 알림 적재: %s", x9["text"][:40])

    def _of_manual_resolve(self, rows) -> dict:
        dec = self.outflow_decisions()
        want = {a: [l for l in (v.get("links") or []) if isinstance(l, dict)] for a, v in dec.items()
                if isinstance(v, dict) and v.get("verdict") == "external" and isinstance(v.get("links"), list) and v.get("links")}
        out = {"dests": {}, "pids": set(), "dup": set(), "claims": {}}
        self._of_claims = out["claims"]
        if not want:
            return out
        by_key, by_src = {}, {}
        for r in rows:
            if r["leg_kind"] not in ("acq", "move_in") or r["event"] not in self.OF_IN_EVENTS:
                continue
            k9 = self._of_key(r)
            by_key[k9] = r
            by_src.setdefault((k9.rsplit("|", 1)[0], self._of_asset(r), str(r["qty_base"])), []).append(r)
        def same(l9, r9):
            return (self._of_asset(r9) == str(l9.get("asset") or "") and str(r9["qty_base"]) == str(l9.get("qb") or "")
                    and self._of_where_raw(r9) == str(l9.get("where") or ""))
        order9 = sorted(((int(l9.get("lts") or 0), a, i9, l9) for a, links in want.items() for i9, l9 in enumerate(links[:self.OF_LINK_MAX])),
                        key=lambda x9: x9[:3])
        res9 = {}
        for _lt, a, i9, l9 in order9:
            k9 = str(l9.get("key") or "")
            r9 = by_key.get(k9)
            if r9 is not None and not same(l9, r9):
                r9 = None
            if r9 is None and k9.count("|") >= 3:
                c9 = [r0 for r0 in by_src.get((k9.rsplit("|", 1)[0], str(l9.get("asset") or ""), str(l9.get("qb") or "")), []) if same(l9, r0)]
                r9 = c9[0] if len(c9) == 1 else None
            if r9 is not None:
                ck9 = self._of_key(r9)
                if ck9 in out["claims"]:
                    out["dup"].add((a, k9))
                    r9 = None
                else:
                    out["claims"][ck9] = (a, k9, l9.get("kind"))
            res9[(a, i9)] = r9
        for a, links in want.items():
            lst = []
            for i9, l9 in enumerate(links[:self.OF_LINK_MAX]):
                r9 = res9.get((a, i9))
                lst.append((l9, r9))
                if r9 is not None and l9.get("kind") == "tokens":
                    out["pids"].add(r9["posting_id"])
            out["dests"][a] = lst
        return out

    def _of_key_cur(self, a, l9) -> str:
        k9 = str((l9 or {}).get("key") or "")
        for ck9, own9 in (getattr(self, "_of_claims", None) or {}).items():
            if own9[0] == a and own9[1] == k9:
                return ck9
        return k9

    @staticmethod
    def _of_where_raw(r) -> str:
        loc9 = str(r["location"] or "")
        if loc9.startswith("wallet:"):
            p9 = loc9.split(":")
            return f"w:{p9[2]}" if len(p9) >= 3 and p9[2] else "w:?"
        if loc9.startswith("exchange:"):
            return "ex:" + loc9.split(":")[1]
        return ""

    def _of_manual_lots(self, conn, of_man: dict, krw_of, own_dep9, rt_pair) -> tuple:
        lots, links, state = {}, {}, {}
        for a, lst in (of_man.get("dests") or {}).items():
            refund = refund_krw = Decimal(0)
            st9 = {"paidUsd": None, "refundUsd": Decimal(0), "costUsd": None, "links": {}}
            toks = []
            for l9, r9 in lst:
                k9 = str(l9.get("key") or "")
                if r9 is None:
                    st9["links"][k9] = {"st": "dup" if (a, k9) in (of_man.get("dup") or ()) else "missing"}
                    continue
                q9 = self._norm(r9)
                stab9 = self._of_stable_row(r9)
                if l9.get("kind") == "refund":
                    if not stab9 or q9 <= 0:
                        st9["links"][k9] = {"st": "invalid"}
                        continue
                    refund += q9
                    refund_krw += krw_of(q9, int(r9["event_ts"]))
                    st9["links"][k9] = {"st": "ok", "usd": q9}
                    continue
                if stab9 or q9 <= 0:
                    st9["links"][k9] = {"st": "invalid"}
                    continue
                exd9 = str(r9["location"] or "").startswith("exchange:")
                if (exd9 and r9["source_id"] in own_dep9) or (not exd9 and (r9["source_ns"], r9["source_id"]) in rt_pair):
                    st9["links"][k9] = {"st": "other_path"}
                    continue
                toks.append((k9, r9, q9))
            st9["refundUsd"] = refund
            if toks:
                gids9 = {(r9["group_id"] or -r9["asset_id"]) for _k, r9, _q in toks}
                w9 = [q9 for _k, _r, q9 in toks]
                if len(gids9) > 1:
                    px9 = []
                    for _k, r9, q9 in toks:
                        try:
                            p9 = float(self.px.candle_usd(str(r9["symbol"] or ""), int(r9["event_ts"]) * 1000) or 0)
                        except Exception:
                            p9 = 0.0
                        px9.append(p9)
                    if all(p9 > 0 for p9 in px9):
                        w9 = [q9 * Decimal(str(p9)) for (_k, _r, q9), p9 in zip(toks, px9)]
                tw9 = sum(w9, Decimal(0))
                lid = "of:" + a
                lots[lid] = {"id": lid, "ratio": Decimal(1), "sym": "", "manual": a, "refund": refund, "refund_krw": refund_krw,
                             "excl": [x0 for x0 in (((self.outflow_decisions().get(a) or {}).get("excludeLegs")) or []) if isinstance(x0, (dict, str))],
                             "t_first": min(int(r9["event_ts"]) for _k, r9, _q in toks), "n": len(toks), "fin": None}
                for (k9, r9, q9), wi in zip(toks, w9):
                    exd9 = str(r9["location"] or "").startswith("exchange:")
                    links[r9["posting_id"]] = {"lot": lid, "take": q9, "qty": q9, "unit": None, "unit_krw": None, "cost": None,
                                               "wsh": (wi / tw9) if tw9 > 0 else Decimal(1) / len(toks),
                                               "ts": int(r9["event_ts"]), "ref": str(r9["source_id"]), "kind": "ex" if exd9 else "chain",
                                               "sender": "", "manual": a}
                    st9["links"][k9] = {"st": "pending", "pid": r9["posting_id"]}
            state[a] = st9
        self._of_man_state = state
        return lots, links

    def _known_addrs(self):
        k = {}

        def put(a, kind, name):
            if a:
                a9 = a.lower() if str(a).startswith("0x") else a
                l9 = k.setdefault(a9, [])
                if (kind, name) not in l9:
                    l9.append((kind, name))
        for w in self._hist_wallets():
            put(w.get("address"), "my_wallet", w.get("label") or "내 지갑")
        fx_name = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "kucoin": "쿠코인", "gate": "게이트",
                   "bithumb": "빗썸", "upbit": "업비트", "hyperliquid": "Hyperliquid"}
        for e in self.cfg.get("exchange_addresses") or []:
            put(e.get("address"), "exchange_deposit", fx_name.get(e.get("exchange"), e.get("exchange")) + " 입금주소(내 계정)")
        try:
            for a9, labs in depaddr.hint_index().items():
                for _ex9, lab9 in labs:
                    put(a9, "exchange_deposit", lab9)
        except Exception:
            pass
        for a9 in common.seed_json("bridge_contracts.json", [], base_dir=common.BASE_DIR, strict=True) or []:
            put(a9, "bridge", "브릿지 컨트랙트")
        for ch9, mg9 in lpdec.lp_managers(common.BASE_DIR).items():
            for a9, m9 in mg9.items():
                if not str(a9).startswith("0x"):
                    continue
                put(a9, "lp", f"{m9.get('name') or 'LP'} " + {"stake": "스테이킹(팜)", "v2_router": "라우터"}.get(m9.get("proto"), "포지션 관리자"))
                if m9.get("pool_manager"):
                    put(m9["pool_manager"], "lp", f"{m9.get('name') or 'LP'} PoolManager")
        return k

    def _bridge_labels(self) -> dict:
        out = {}
        try:
            for a9 in common.seed_json("bridge_contracts.json", [], base_dir=common.BASE_DIR, strict=True) or []:
                if isinstance(a9, str):
                    out[a9.lower()] = {"name": "브릿지 컨트랙트", "chain": None}
            d9 = common.seed_json("bridge_labels.json", {}, base_dir=common.BASE_DIR, strict=True) or {}
            for a9, v9 in d9.items():
                if isinstance(v9, dict) and v9.get("name") and not a9.startswith("_"):
                    out[a9.lower() if a9.startswith("0x") else a9] = {"name": str(v9["name"])[:80], "chain": v9.get("chain")}
        except BaseException:
            pass
        return out

    def _xfer_links(self, conn, onchain_txids, linked_dep_uuids, prefs, origin_cache=None, origin_pending=None) -> dict:
        wds, deps = [], []
        offc9, offx9 = _offc_on(prefs), _offc_excl(prefs)
        for rf in conn.execute("SELECT exchange, kind, uuid, payload FROM raw_ex WHERE kind IN ('withdraw','deposit')"
                               " GROUP BY exchange, kind, uuid HAVING revision = MAX(revision)").fetchall():
            try:
                pw = json.loads(rf["payload"])
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(pw, dict):
                continue
            if (rf["exchange"] in offc9 and _offc_tx(pw.get("txid"))
                    and not (rf["kind"] == "withdraw" and pw.get("address")
                             and xfer_match.norm_addr(pw.get("address")) in offx9.get(rf["exchange"], ()))):
                continue
            if str(pw.get("currency") or "").upper() == "KRW":
                continue
            st = str(pw.get("state") or "").upper()
            row = dict(pw, exchange=rf["exchange"], uuid=rf["uuid"])
            if rf["kind"] == "withdraw" and st == "DONE":
                wds.append(row)
            elif rf["kind"] == "deposit" and st == "ACCEPTED":
                deps.append(row)
        own = {xfer_match.norm_addr(w9.get("address")) for w9 in self._hist_wallets() if w9.get("address")}
        own_ch = {}
        for w9 in (self.cfg.get("wallets") or []):
            if w9.get("address"):
                own_ch.setdefault(xfer_match.norm_addr(w9["address"]), set()).add(str(w9.get("chain") or "").lower())

        def own_tracked(w):
            a9 = xfer_match.norm_addr(w.get("address"))
            if a9 not in own_ch:
                return False
            ch9 = depaddr.chain_of(w.get("network") or w.get("net_type"), w.get("currency"), a9)
            return bool(ch9) and ch9 in own_ch[a9]
        store_ok = os.path.exists(depaddr.store_path())
        dest_memo = {}

        def dest_of(w):
            if not store_ok:
                return None
            a = str(w.get("address") or "")
            k9 = (a, w.get("tag") or "", w.get("network") or w.get("net_type") or "", w.get("currency") or "")
            if k9 not in dest_memo:
                ch = depaddr.chain_of(w.get("network") or w.get("net_type"), w.get("currency"), a)
                hit = depaddr.lookup(ch, a, w.get("tag") or w.get("memo") or None, w.get("currency"))
                dest_memo[k9] = hit.get("exchange") if (hit and not hit.get("ambiguous") and not hit.get("tag_required")
                                                        and hit.get("match") in ("exact", "family", "address")) else None
            return dest_memo[k9]
        oc = origin_cache or {}

        def origin_of(d):
            t9 = outflow_match.norm_txid(d.get("txid")) if d.get("txid") else ""
            f9 = (oc.get(t9) or {}).get("from") if t9 else None
            return xfer_match.norm_addr(f9) if f9 else None
        if origin_pending is not None:
            for t9 in xfer_match.hop_candidates(wds, deps, dest_of, own_tracked):
                if t9.startswith("0x") and len(t9) == 66 and t9 not in oc:
                    origin_pending.add(t9)
        off = {str(x) for x in (prefs.get("xfer_link_off") or [])}
        args9 = (wds, deps, frozenset(onchain_txids), frozenset(linked_dep_uuids))
        links = xfer_match.match(*args9, frozenset(off), dest_of, origin_of, own_tracked)
        self._xfer_links_all = xfer_match.match(*args9, frozenset(), dest_of, origin_of, own_tracked) if off else links
        self._xfer_links_last = links
        rows9 = []
        for w in wds:
            a = w.get("address")
            if not a:
                continue
            na = xfer_match.norm_addr(a)
            cls9 = ("wallet" if own_tracked(w) else "wallet_untracked") if na in own else ("exchange" if dest_of(w) else "unknown")
            rows9.append({"uuid": w["uuid"], "ex": w["exchange"], "addr": na, "cls": cls9, "sym": str(w.get("currency") or "").upper(),
                          "qty": w.get("amount"), "network": w.get("network") or "", "txid": outflow_match.norm_txid(w.get("txid")) if w.get("txid") else "",
                          "ts": xfer_match._ts(w.get("created_at")) or 0, "dest_ex": dest_of(w) if cls9 == "exchange" else None})
        self._wd_dest_rows = rows9

        def cls_of(w):
            a = w.get("address")
            if not a:
                return None, None
            if xfer_match.norm_addr(a) in own:
                return ("wallet" if own_tracked(w) else "wallet_untracked"), None
            d9 = dest_of(w)
            return ("exchange", d9) if d9 else ("unknown", None)
        self._wd_cls_fn = cls_of
        return links

    @staticmethod
    def _transit_loc(e, now) -> dict:
        age = _ago_ko(max(0, float(now) - float(e["ts"])))
        w = f"{e['src']} → {e['dst']} 전송 중" if e.get("dst") else f"{e['src']} 출금 → 도착 확인 대기"
        sub = [f"출금 {age}째"]
        if e.get("net"):
            sub.append(f"{e['net']} 네트워크")
        sub.append("내 계정으로 이동 중" if e.get("own") else ("받는 주소 " + xfer_match.short(e["addr"]) if e.get("addr") else "받는 주소 미상"))
        return {"w": w, "sub": " · ".join(sub), "qty": float(e["qty"]),
                "tr": {"from": e["src"], "to": e.get("dst"), "since": int(e["ts"]), "until": int(e["until"]), "net": e.get("net") or "",
                       "own": bool(e.get("own")), "txid": e.get("txid_raw") or "", "addr": e.get("addr") or "", "uuid": str(e["uuid"])}}

    @staticmethod
    def _wd_key(ex, uuid) -> str:
        return f"wd:{ex}:{uuid}"

    def _transit_hours(self, net, cur=None):
        tc = self.cfg.get("transit") if isinstance(self.cfg.get("transit"), dict) else {}
        n = str(net or "").strip().upper()
        hm = {str(k).upper(): v for k, v in (tc.get("hours") or {}).items()} if isinstance(tc.get("hours"), dict) else {}
        for k in (n, n.split("-")[-1].strip() if "-" in n else None):
            if k and k in hm:
                return float(hm[k])
            if k and k in TRANSIT_NET_H:
                return float(TRANSIT_NET_H[k])
        ch = depaddr.chain_of(n, cur) if n else None
        if ch:
            return 3.0 if ch == "eth" else 2.0
        return float(tc.get("default_hours", TRANSIT_DEFAULT_H))

    def _wd_transit_resolve(self, wd_tr, rows, wd_raw, fx_transit, xf_links, up_dep_uid_tx, exf_dep_tx, G, skip_tx=frozenset(), now=None,
                           skip_deps=frozenset()):
        now = time.time() if now is None else float(now)
        tc = self.cfg.get("transit") if isinstance(self.cfg.get("transit"), dict) else {}
        own_h = float(tc.get("own_hours", TRANSIT_OWN_H))
        try:
            dec = self.outflow_decisions() or {}
        except Exception:
            dec = {}
        cls_fn = getattr(self, "_wd_cls_fn", None)
        fx_name = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "kucoin": "쿠코인", "gate": "게이트", "bithumb": "빗썸", "upbit": "업비트", "hyperliquid": "Hyperliquid"}
        wl9 = {}
        for w9 in self._hist_wallets():
            if isinstance(w9, dict) and w9.get("address"):
                wl9[xfer_match.norm_addr(w9["address"])] = str(w9.get("label") or "")
        arr_tx, dep_ts, cands = {}, {}, []
        for r0 in rows:
            ev0 = r0["event"]
            if r0["leg_kind"] not in ("move_in", "acq"):
                continue
            if ev0 in ("EX_DEPOSIT", "EXF_DEPOSIT"):
                u0 = r0["source_id"]
                ex0 = (r0["location"] or "").split(":")[-1]
                dep_ts.setdefault(u0, int(r0["event_ts"]))
                t0 = up_dep_uid_tx.get(u0) if ex0 == "upbit" else exf_dep_tx.get((ex0, u0))
            elif ev0 in ("TRANSFER_IN", "PROGRAM_IN"):
                t0 = r0["source_id"]
            else:
                continue
            k0 = _txk(t0) if t0 else ""
            if k0:
                arr_tx.setdefault(k0, int(r0["event_ts"]))
            if (ev0 in ("EX_DEPOSIT", "EXF_DEPOSIT") and not (k0 and k0 in skip_tx)
                    and u0 not in skip_deps and u0 not in (xf_links or {})):
                gid0 = r0["group_id"] or -r0["asset_id"]
                try:
                    q0 = self._norm(r0)
                except (TypeError, ValueError, InvalidOperation):
                    continue
                cands.append({"ts": int(r0["event_ts"]), "sym": str((G.get(gid0) or {}).get("sym") or r0["symbol"] or "").upper(),
                              "qty": q0, "used": False})
        link_wd = {}
        for du9, xl9 in (xf_links or {}).items():
            if du9 in dep_ts and xl9.get("wd_uuid"):
                link_wd.setdefault(xl9["wd_uuid"], dep_ts[du9])
        for i9 in (getattr(self, "_hl_bridge_free", None) or ()):
            cands.append({"ts": int(i9["ts"]), "sym": "USDC", "qty": Decimal(str(i9["qty"])), "used": False, "ex": "hyperliquid"})
        cands.sort(key=lambda c9: c9["ts"])
        tx_owners = {}
        for w9 in wd_tr:
            p9 = wd_raw.get((w9["ex"], w9["uuid"])) or {}
            if str(p9.get("state") or "").upper() in ("CANCELED", "CANCELLED", "REJECTED", "FAILED"):
                continue
            t9 = _txk(str(p9.get("txid") or w9.get("txid") or "").strip())
            if t9 and not t9.startswith("amt:"):
                tx_owners.setdefault(t9, []).append(w9)
        out = []
        for e in sorted(wd_tr, key=lambda x9: (x9["ts"], str(x9["uuid"]))):
            p = wd_raw.get((e["ex"], e["uuid"])) or {}
            st = str(p.get("state") or "").upper()
            addr = str(p.get("address") or "").strip()
            na = xfer_match.norm_addr(addr) if addr else ""
            net = str(p.get("network") or p.get("net_type") or "").strip()
            txr = str(p.get("txid") or "").strip()
            done = xfer_match._ts(p.get("done_at")) or 0
            start = max(int(e["ts"]), int(done or 0))
            cls, dest_ex = (cls_fn(dict(p, exchange=e["ex"])) if (cls_fn and addr) else (None, None))
            key = na if na else self._wd_key(e["ex"], e["uuid"])
            d9 = dec.get(key) if isinstance(dec.get(key), dict) else {}
            vd = d9.get("verdict")
            own = cls in ("wallet", "exchange") or vd in ("own", "exchange")
            win = own_h if own else self._transit_hours(net, p.get("currency"))
            dst = None
            if cls == "exchange" and dest_ex:
                dst = fx_name.get(dest_ex, dest_ex)
            elif cls in ("wallet", "wallet_untracked"):
                dst = (wl9.get(na) or "내 지갑") if str(wl9.get(na) or "").rstrip().endswith("지갑") else f"{wl9.get(na) or '내'} 지갑"
            elif vd == "exchange":
                dst = fx_name.get(d9.get("exchange"), d9.get("exchange") or "거래소")
            elif vd == "own":
                dst = str(d9.get("alias") or "내 지갑")
            e.update({"addr": addr, "net": net, "txid_raw": txr, "start": start, "until": int(start + win * 3600), "own": own,
                      "cls": cls, "dst": dst, "key": key, "verdict": vd, "arr_ts": None, "state": None, "why": None,
                      "src": fx_name.get(e["ex"], e["ex"]), "fee": p.get("fee")})
            if st in ("CANCELED", "CANCELLED", "REJECTED", "FAILED"):
                e["state"] = "cancel"
                out.append(e)
                continue
            tk = _txk(txr or (e["txid"] if e.get("txid") and not str(e["txid"]).startswith("amt:") else "")) or ""
            owners9 = tx_owners.get(tk, ())
            f9 = fx_transit.get(e.get("txid"))
            if len(owners9) > 1 and (
                    tk in arr_tx or any(w9["uuid"] in link_wd for w9 in owners9)
                    or (f9 and f9.get("qty") and f9["qty"] > 0
                        and f9["left"] < f9["qty"] * Decimal("0.999999"))):
                e["state"], e["why"] = "out", "txid_ambiguous"
                out.append(e)
                continue
            at = arr_tx.get(tk) if tk else None
            if at is None:
                at = link_wd.get(e["uuid"])
            if at is None and e.get("txid"):
                f4 = fx_transit.get(e["txid"])
                if f4 and f4.get("qty") and f4["qty"] > 0 and f4["left"] < f4["qty"] * Decimal("0.999999"):
                    at = int(e["ts"])
            if at is not None:
                e["state"], e["arr_ts"] = "arrived", int(at)
            elif vd == "external":
                e["state"], e["why"] = "out", "external"
            elif now < e["until"]:
                e["state"] = "pending"
            else:
                e["state"], e["why"] = "out", "expired"
            out.append(e)
        fits, claims = {}, {}
        for i9, e9 in enumerate(out):
            if e9["state"] != "pending" and not (e9["state"] == "out" and e9["why"] == "expired"):
                continue
            hits9 = [j9 for j9, c9 in enumerate(cands)
                     if not c9["used"] and c9["sym"] == str(e9["sym"] or "").upper() and c9.get("ex", e9["ex"]) == e9["ex"]
                     and int(e9["ts"]) - 60 <= c9["ts"] <= e9["until"]
                     and e9["qty"] * Decimal("0.98") <= c9["qty"] <= e9["qty"]]
            fits[i9] = hits9
            for j9 in hits9:
                claims[j9] = claims.get(j9, 0) + 1
        for i9, hits9 in fits.items():
            if not hits9:
                continue
            if len(hits9) != 1 or claims[hits9[0]] != 1:
                out[i9].update({"state": "out", "why": "amount_ambiguous"})
                continue
            c9 = cands[hits9[0]]
            c9["used"] = True
            out[i9].update({"state": "arrived", "arr_ts": c9["ts"], "why": "amount"})
        return out

    @staticmethod
    def _hl_neg_mark(G, neg_gids) -> bool:
        p9 = os.path.join(common.STATE_DIR, "hl_neg_mark.json")
        try:
            prev9 = set(int(x) for x in ((common.read_json(p9, {}) or {}).get("gids") or []))
        except (SystemExit, TypeError, ValueError):
            prev9 = set()
        new9 = set(neg_gids or ()) - prev9
        if not new9:
            return False
        ts9 = [int(t9) for g9 in new9 for t9, _dq in ((G.get(g9) or {}).get("qty_timeline") or ())]
        if ts9:
            common.mark_hist_dirty(min(ts9))
        common.atomic_write_json(p9, {"v": 1, "gids": sorted(prev9 | new9), "at": int(time.time())})
        return True

    def _hl_bridge_links(self, conn, wd_raw) -> dict:
        import hl_spot
        self._hl_bridge_free = []
        wds = []
        for (ex9, u9), p9 in (wd_raw or {}).items():
            if ex9 != "hyperliquid" or not isinstance(p9, dict) or str(p9.get("state") or "").upper() != "DONE":
                continue
            if str(p9.get("txid") or "").strip() or str(p9.get("currency") or "").upper() != "USDC" or p9.get("hl_type") != "withdraw":
                continue
            try:
                ts9 = int(datetime.fromisoformat(str(p9.get("created_at")).replace("Z", "+00:00")).timestamp())
                wds.append({"uuid": u9, "ts": ts9, "amount": Decimal(str(p9.get("amount"))), "fee": Decimal(str(p9.get("fee") or "0"))})
            except (TypeError, ValueError, ArithmeticError):
                continue
        if not wds:
            return {}
        lo9 = min(w["ts"] for w in wds) - hl_spot.BRIDGE_EARLY
        hi9 = max(w["ts"] for w in wds) + hl_spot.BRIDGE_WINDOW
        inflows = []
        for r9 in conn.execute(
                "SELECT p.source_id, p.event_ts, p.qty_base, p.location, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                " WHERE p.source_kind='chain_tx' AND p.source_ns='arbitrum' AND p.event='TRANSFER_IN' AND p.leg_kind='acq'"
                " AND a.kind='token' AND a.chain='arbitrum' AND a.address=? AND p.event_ts BETWEEN ? AND ?",
                (hl_spot.USDC_ARB, lo9, hi9)).fetchall():
            loc9 = str(r9["location"] or "")
            if not loc9.startswith("wallet:arbitrum:"):
                continue
            me9 = loc9.split(":")[2].lower()
            row9 = conn.execute("SELECT snapshot FROM raw_txs WHERE chain='arbitrum' AND txhash=?", (r9["source_id"],)).fetchone()
            try:
                snap9 = json.loads(row9["snapshot"]) if row9 else {}
            except (TypeError, ValueError):
                snap9 = {}
            dec9 = 6 if r9["decimals"] is None else int(r9["decimals"])
            got9 = Decimal(0)
            for tt9 in snap9.get("token_transfers") or []:
                tok9 = tt9.get("token") or {}
                if str(tok9.get("address") or tok9.get("address_hash") or "").lower() != hl_spot.USDC_ARB:
                    continue
                f9, t9 = tt9.get("from"), tt9.get("to")
                f9 = str((f9.get("hash") if isinstance(f9, dict) else f9) or "").lower()
                t9 = str((t9.get("hash") if isinstance(t9, dict) else t9) or "").lower()
                if f9 == hl_spot.BRIDGE2 and t9 == me9:
                    try:
                        got9 += Decimal(int((tt9.get("total") or {}).get("value") or 0)) / (Decimal(10) ** dec9)
                    except (TypeError, ValueError, ArithmeticError):
                        pass
            if got9 <= 0:
                continue
            qn9 = Decimal(int(r9["qty_base"])) / (Decimal(10) ** dec9)
            if abs(qn9 - got9) > Decimal("0.000001"):
                continue
            inflows.append({"tx": r9["source_id"], "loc": loc9, "ts": int(r9["event_ts"]), "qty": qn9})
        links = hl_spot.match_bridge_withdrawals(wds, inflows)
        used9 = set(links.values())
        self._hl_bridge_free = [i9 for i9 in inflows if i9["tx"] not in used9]
        return links

    def _deposit_exchange_index(self) -> dict:
        idx = {}

        def put(a, ex):
            if a and ex:
                a = a.lower() if str(a).startswith("0x") else a
                idx.setdefault(a, set()).add(str(ex))
        for e in self.cfg.get("exchange_addresses") or []:
            put(e.get("address"), e.get("exchange"))
        try:
            names = os.listdir(common.STATE_DIR)
        except OSError:
            names = []
        for f9 in names:
            if f9.startswith("exf_addrs_") and f9.endswith(".json"):
                try:
                    d9 = common.read_json(os.path.join(common.STATE_DIR, f9), {})
                except SystemExit:
                    continue
                for a9 in (d9.get("addrs") or []) if isinstance(d9, dict) else []:
                    if isinstance(a9, dict) and not a9.get("tag"):
                        put(a9.get("address"), f9[len("exf_addrs_"):-5])
        return {a: next(iter(v)) for a, v in idx.items() if len(v) == 1}

    def _deposit_exchange(self, chain, addr):
        a = (addr or "").lower() if str(addr or "").startswith("0x") else (addr or "")
        try:
            if os.path.exists(depaddr.store_path()):
                r = depaddr.lookup(chain, a)
                if r and r.get("match") in ("exact", "family") and not r.get("tag_required") and not r.get("ambiguous"):
                    return r.get("exchange")
                return None
        except Exception:
            pass
        return (getattr(self, "_depx_idx", None) or {}).get(a)

    _ADDR_RX = re.compile(r"0x[0-9a-fA-F]{40}(?![0-9a-fA-F])")

    def _raw_from_counts(self, conn) -> dict:
        self._rtxc().sync(conn)
        return self._rtxc().from_counts(conn)

    def _inflow_senders(self, conn, dests) -> dict:
        try:
            mine = rawtx_cache.mine_wallets(common.read_json(common.CONFIG_PATH, {}) or {})
        except BaseException:
            mine = set()
        self._rtxc().sync(conn)
        return self._rtxc().inflow_senders(conn, dests, mine)

    def _outflow_returns(self, conn, groups: dict, live_px: dict, G: dict) -> dict:
        idx = self._inflow_senders(conn, [a for a, o9 in groups.items()
                                          if a not in ("multi", "?") and not o9.get("phantom") and not flow_trace.is_burn(a)])
        br_arr9 = {a9.get("key") for a9 in ((getattr(self, "_of_auto", None) or {}).get("bridge") or {}).values() if isinstance(a9, dict)}
        tok_pid9 = {l9.get("pid") for s9 in (getattr(self, "_of_man_state", None) or {}).values()
                    for l9 in (s9.get("links") or {}).values() if l9.get("st") == "applied" and l9.get("pid") is not None}
        own_ref9 = {l9["key"]: a9 for a9, ls9 in (getattr(self, "_of_claim_legs", None) or {}).items()
                    for l9 in ls9 if l9.get("kind") == "refund" and l9.get("st") == "ok" and l9.get("key")}
        want = {}
        for a, o9 in groups.items():
            if a in ("multi", "?") or not idx.get(a):
                continue
            for key in idx[a]:
                if key[1] not in o9["txs"]:
                    want.setdefault(key, set()).add(a)
        out = {}
        keys = list(want)
        for i in range(0, len(keys), 400):
            ch = keys[i:i + 400]
            q = ("SELECT p.posting_id, p.source_kind, p.source_ns, p.source_id, p.leg_seq, p.event_ts, p.location, p.qty_base, p.cost_usd, a.symbol,"
                 " a.decimals, a.group_id, a.asset_id FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_kind='chain_tx'"
                 " AND p.source_id IN (" + ",".join("?" * len(ch)) + ") AND p.location LIKE 'wallet:%'"
                 " AND p.leg_kind IN ('acq', 'move_in')")
            for r in conn.execute(q, [k[1] for k in ch]).fetchall():
                key = (r["source_ns"], r["source_id"])
                if key not in want or int(r["qty_base"]) <= 0 or r["posting_id"] in br_arr9 or r["posting_id"] in tok_pid9:
                    continue
                qn = Decimal(int(r["qty_base"])) / (Decimal(10) ** int(r["decimals"] if r["decimals"] is not None else 18))
                gid = r["group_id"] or -r["asset_id"]
                if gid in (getattr(self, "_risk_quarantined", None) or ()):
                    continue
                g9 = G.get(gid) or {}
                if r["cost_usd"] is not None:
                    usd = float(r["cost_usd"])
                elif g9.get("is_stable"):
                    usd = float(qn)
                else:
                    u9 = self._ledger_unit_px(conn, gid, int(r["event_ts"]))
                    if u9 is None:
                        for a in want[key]:
                            for t9 in (groups[a].get("tokens") or {}).values():
                                if t9.get("gid") == gid and t9.get("usd_send_known") and t9.get("qty") and t9.get("usd_send"):
                                    u9 = float(t9["usd_send"]) / float(t9["qty"])
                                    break
                            if u9 is not None:
                                break
                    usd = float(qn) * (u9 if u9 is not None else float(live_px.get(gid) or 0))
                if usd < 1:
                    continue
                ow9 = own_ref9.get(self._of_key(r)) if own_ref9 else None
                for a in want[key]:
                    if ow9 is not None and ow9 != a:
                        continue
                    first = groups[a]["first"]
                    out.setdefault(a, {"after": [], "before": []})["after" if r["event_ts"] >= first else "before"].append({
                        "key": self._of_key(r),
                        "ts": int(r["event_ts"]), "t": datetime.fromtimestamp(r["event_ts"], KST).strftime("%Y-%m-%d %H:%M"),
                        "chain": r["source_ns"], "tx": r["source_id"], "sym": g9.get("sym") or (r["symbol"] or "?"),
                        "qty": float(qn), "usd": _f(usd, 2),
                        "wallet": str(r["location"] or "").split(":")[-1]})
        return out

    def _ledger_unit_px(self, conn, gid, ts, win=7 * 86400):
        c9 = getattr(self, "_lpx_cache", None)
        if c9 is None or c9.get("_db") is not conn:
            c9 = self._lpx_cache = {"_db": conn}
        lst = c9.get(gid)
        if lst is None:
            lst = []
            try:
                cond9 = "a.group_id=?" if gid is not None and gid > 0 else "a.asset_id=?"
                for r9 in conn.execute("SELECT p.event_ts, p.qty_base, p.cost_usd, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                                       " WHERE " + cond9 + " AND p.cost_usd IS NOT NULL AND p.leg_kind IN ('acq', 'disp')",
                                       (gid if gid is not None and gid > 0 else -gid,)).fetchall():
                    q9 = abs(Decimal(int(r9["qty_base"]))) / (Decimal(10) ** int(r9["decimals"] if r9["decimals"] is not None else 18))
                    if q9 > 0:
                        lst.append((int(r9["event_ts"]), float(Decimal(r9["cost_usd"]) / q9)))
            except Exception:
                lst = []
            lst.sort()
            c9[gid] = lst
        best = None
        for t9, u9 in lst:
            d9 = abs(t9 - ts)
            if d9 <= win and u9 > 0 and (best is None or d9 < best[0]):
                best = (d9, u9)
        return best[1] if best else None

    @staticmethod
    def _lookalike(a: str, pool: dict):
        if not (a or "").startswith("0x") or len(a) != 42:
            return None
        for b, desc in pool.items():
            if b != a and len(b) == 42 and b.startswith("0x") and b[2:6] == a[2:6] and b[-4:] == a[-4:]:
                return {"similarTo": b, "label": desc}
        return None

    @staticmethod
    def _rt_parties(snap: dict, side: str, mine: set) -> set:
        if not isinstance(snap, dict):
            return set()
        if snap.get("kind") == "sol_tx":
            return {str(x) for x in (snap.get("counterparties") or []) if x}

        def _a(x):
            return str((x.get("hash") if isinstance(x, dict) else x) or "").lower()
        out = set()
        tx = snap.get("tx") or {}
        legs = [(tx.get("from"), tx.get("to"), tx.get("value"))]
        legs += [(it.get("from"), it.get("to"), it.get("value")) for it in (snap.get("internal") or [])
                 if not (it.get("success") is False or it.get("error"))]
        legs += [(tt.get("from"), tt.get("to"), (tt.get("total") or {}).get("value")) for tt in (snap.get("token_transfers") or [])]
        for f9, t9, v9 in legs:
            try:
                if not int(v9 or 0):
                    continue
            except (TypeError, ValueError):
                continue
            f9, t9 = _a(f9), _a(t9)
            if side == "in" and t9 in mine and f9 and f9 not in mine:
                out.add(f9)
            elif side == "out" and f9 in mine and t9 and t9 not in mine:
                out.add(t9)
        return out

    def _rt_same_dest(self, conn, rt_pair: dict) -> set:
        ok = set()
        if not rt_pair:
            return ok
        cfg_mine = {str(w.get("address") or "").lower() for w in self._hist_wallets() if isinstance(w, dict)}
        for ki, ko in rt_pair.items():
            try:
                ri = conn.execute("SELECT snapshot, wallets FROM raw_txs WHERE chain=? AND txhash=?", ki).fetchone()
                ro = conn.execute("SELECT snapshot, wallets FROM raw_txs WHERE chain=? AND txhash=?", ko).fetchone()
                if not ri or not ro:
                    continue
                mine9 = set(cfg_mine)
                for r9 in (ri, ro):
                    try:
                        mine9 |= {str(w).lower() for w in (json.loads(r9[1] or "[]") or []) if w}
                    except ValueError:
                        pass
                if self._rt_parties(json.loads(ri[0]), "in", mine9) & self._rt_parties(json.loads(ro[0]), "out", mine9):
                    ok.add(ko)
            except Exception as e:
                log.debug("왕복 상대 대조 실패 %s: %s", ko, e)
                continue
        return ok

    def _untracked_net_deps(self, conn) -> list:
        trk9 = {str(k).upper() for k in (self.cfg.get("chains") or {})} | {"SOL", "BSC"}
        out = []
        try:
            for rf in conn.execute("SELECT exchange, payload FROM raw_ex WHERE kind='deposit'"
                                   " GROUP BY exchange, uuid HAVING revision = MAX(revision)").fetchall():
                try:
                    pw = json.loads(rf["payload"])
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(pw, dict) or str(pw.get("state") or "").upper() != "ACCEPTED":
                    continue
                net9 = str(pw.get("net_type") or pw.get("network") or "").strip()
                cur9 = str(pw.get("currency") or "").strip().upper()
                selfnet9 = net9.upper() == cur9
                if not net9 or not cur9 or depaddr.chain_of(net9, cur9):
                    continue
                if any(k9 in net9.upper() for k9 in trk9 if k9 != "ETH"):
                    continue
                try:
                    ts9 = datetime.fromisoformat(str(pw.get("done_at") or pw.get("created_at"))).timestamp()
                    q9 = float(pw.get("amount") or 0)
                except (ValueError, TypeError):
                    continue
                if q9 > 0:
                    out.append({"ts": ts9, "ex": rf["exchange"], "cur": acct_norm.canon(cur9, rf["exchange"]), "qty": q9, "net": net9,
                                "selfnet": selfnet9})
        except Exception as e9:
            log.warning("미추적 체인 입금 읽기 실패(제안 없음): %s", e9)
            return []
        return out

    OF_LIST_CAP = 200

    @classmethod
    def _of_list_add(cls, o9: dict, item: dict) -> dict:
        lst = o9["list"]
        lst.append(item)
        o9["listN"] = int(o9.get("listN") or 0) + 1
        if len(lst) >= 2 * cls.OF_LIST_CAP:
            lst.sort(key=lambda x9: x9["ts"])
            del lst[:-cls.OF_LIST_CAP]
        return item

    @classmethod
    def _of_list_cut(cls, o9: dict) -> int:
        lst = sorted(o9.get("list") or (), key=lambda x9: x9["ts"])
        o9["list"] = lst[-cls.OF_LIST_CAP:]
        return max(0, int(o9.get("listN") or len(lst)) - len(o9["list"]))

    def _outflows(self, conn, ob: dict, live_px: dict, G: dict, scam_gids=frozenset(), dust_usd: float = 0.0, exwd=None):
        dec = self.outflow_decisions()
        known = self._known_addrs()
        try:
            reg_now = {((w.get("address") or "").lower() if str(w.get("address") or "").startswith("0x") else (w.get("address") or ""))
                       for w in (common.read_json(common.CONFIG_PATH, {}) or {}).get("wallets") or []}
        except BaseException:
            reg_now = set()
        try:
            import wallet_register as _wr9
            alive9 = _wr9.auto_reload_alive()
            reload_addrs9 = _wr9.pending_addrs() if alive9 else set()
            auto9 = bool(_wr9.apply_info().get("runner"))
        except Exception:
            reload_addrs9, auto9 = set(), False
        self._of_auto_reload = auto9
        fx_name = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "kucoin": "쿠코인", "gate": "게이트",
                   "bithumb": "빗썸", "upbit": "업비트", "hyperliquid": "Hyperliquid"}
        groups = {a: dict(v, resolved_rows=False, list=list(v.get("list") or ())) for a, v in ob.items()}
        try:
            gid_ca9 = {r9[0] for r9 in conn.execute("SELECT DISTINCT COALESCE(group_id, -asset_id) FROM assets"
                                                    " WHERE kind='token' AND address IS NOT NULL").fetchall()} - \
                      {r9[0] for r9 in conn.execute("SELECT DISTINCT COALESCE(group_id, -asset_id) FROM assets WHERE kind != 'token'").fetchall()}
            gid_ca9 -= {r9[0] for r9 in conn.execute("SELECT COALESCE(group_id, -asset_id), chain, address FROM assets"
                                                     " WHERE kind='token' AND address IS NOT NULL").fetchall()
                        if spamguard.is_genuine(r9[1], r9[2])}
        except Exception:
            gid_ca9 = set()
        for a, v in dec.items():
            if not isinstance(v, dict) or v.get("verdict") not in ("exchange", "own"):
                continue
            if v["verdict"] == "exchange":
                q = ("SELECT p.source_ns, p.source_id, p.event_ts, p.qty_base, p.cost_usd, a.symbol, a.decimals, a.group_id, a.asset_id"
                     " FROM postings p JOIN assets a ON a.asset_id=p.asset_id JOIN tx_class t ON t.chain=p.source_ns"
                     " AND t.txhash=p.source_id WHERE p.source_kind='chain_tx' AND t.event='TRANSFER_OUT_EX'"
                     " AND p.leg_kind='move_out' AND t.detail LIKE ?")
                args = ('%"' + a + '"%',)
            else:
                q = ("SELECT p.source_ns, p.source_id, p.event_ts, p.qty_base, p.cost_usd, a.symbol, a.decimals, a.group_id, a.asset_id"
                     " FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_kind='chain_tx'"
                     " AND p.event IN ('TRANSFER_SELF', 'TRANSFER_OUT') AND p.leg_kind='move_in' AND p.location LIKE ?")
                args = ("wallet:%:" + a,)
            for r in conn.execute(q, args).fetchall():
                qn = abs(Decimal(int(r["qty_base"])) / (Decimal(10) ** int(r["decimals"] if r["decimals"] is not None else 18)))
                o9 = groups.setdefault(a, {"chains": set(), "first": r["event_ts"], "last": r["event_ts"], "txs": set(),
                                           "tokens": {}, "list": [], "auto": None, "resolved_rows": True})
                o9["chains"].add(r["source_ns"])
                o9["first"] = min(o9["first"], r["event_ts"]); o9["last"] = max(o9["last"], r["event_ts"])
                o9["txs"].add(r["source_id"])
                gid9r = r["group_id"] or -r["asset_id"]
                sym9 = (G.get(gid9r) or {}).get("sym") or (r["symbol"] or "?")
                tk9 = o9["tokens"].setdefault(sym9, {"qty": Decimal(0), "cost": None, "usd_send": Decimal(0),
                                                     "usd_send_known": False, "gid": gid9r, "unknown": Decimal(0)})
                tk9["qty"] += qn
                o9.setdefault("hsyms", {}).setdefault(r["source_id"], set()).add(sym9)
                self._of_list_add(o9, {"ts": int(r["event_ts"]), "t": datetime.fromtimestamp(r["event_ts"], KST).strftime("%Y-%m-%d %H:%M"),
                                       "chain": r["source_ns"], "tx": r["source_id"], "sym": sym9, "qty": float(qn),
                                       "usdAtSend": None, "costUsd": None})
        for e9 in (exwd or ()):
            a9 = e9["key"]
            o9 = groups.get(a9)
            if o9 is None:
                o9 = groups[a9] = {"chains": set(), "first": e9["ts"], "last": e9["ts"], "txs": set(), "tokens": {}, "list": [],
                                   "auto": None, "resolved_rows": False}
            ch9 = depaddr.chain_of(e9.get("net"), e9.get("sym")) if e9.get("net") else None
            if ch9:
                o9["chains"].add(ch9)
            o9["first"] = min(o9["first"], e9["ts"])
            o9["last"] = max(o9["last"], e9["ts"])
            o9["txs"].add(e9.get("txid_raw") or f"{e9['ex']}:{e9['uuid']}")
            g9 = G.get(e9["gid"]) or {}
            q9 = Decimal(e9["qty"])
            tk9 = o9["tokens"].setdefault(e9["sym"], {"qty": Decimal(0), "cost": Decimal(0), "usd_send": Decimal(0),
                                                      "usd_send_known": True, "gid": e9["gid"], "unknown": Decimal(0)})
            tk9["qty"] += q9
            tk9["cost"] = (tk9["cost"] or Decimal(0)) + Decimal(e9.get("cost") or 0)
            tk9["unknown"] += max(Decimal(0), q9 - Decimal(e9.get("known") or 0))
            if g9.get("is_stable"):
                tk9["usd_send"] += q9
            else:
                tk9["usd_send_known"] = False
            o9.setdefault("hsyms", {}).setdefault(e9.get("txid_raw") or f"{e9['ex']}:{e9['uuid']}", set()).add(e9["sym"])
            self._of_list_add(o9, {"ts": int(e9["ts"]), "t": datetime.fromtimestamp(e9["ts"], KST).strftime("%Y-%m-%d %H:%M"),
                                   "chain": ch9 or (e9.get("net") or ""), "tx": e9.get("txid_raw") or "", "sym": e9["sym"], "qty": float(q9),
                                   "usdAtSend": float(q9) if g9.get("is_stable") else None, "costUsd": float(e9.get("cost") or 0),
                                   "ex": e9["src"], "signed": True,
                                   "key": self._wd_key(e9["ex"], e9["uuid"])})
            o9.setdefault("exwd", []).append(e9)
        for o9 in groups.values():
            o9["listCut"] = self._of_list_cut(o9)
        pool = {a: f"{kk[0][1]}" for a, kk in known.items() if kk and kk[0][0] in ("my_wallet", "exchange_deposit")}
        for a, v in dec.items():
            if isinstance(v, dict) and v.get("verdict") in ("own", "exchange"):
                pool.setdefault(a, "판정된 " + ("내 지갑" if v["verdict"] == "own" else "거래소 입금주소"))
        out, n_pend = [], 0
        tot = {}
        vals = {}

        def _ph9(t9):
            return bool((("held" in t9) and t9["held"] <= EPS) or t9.get("gid") in scam_gids)
        ad_gids9 = getattr(self, "_risk_airdrop_only", None) or frozenset()

        def _ad9(t9):
            return bool(t9.get("gid") in ad_gids9 and t9.get("gid") in scam_gids and not (("held" in t9) and t9["held"] <= EPS))
        for a, o9 in groups.items():
            now9 = send9 = cost9 = 0.0
            toks = []
            phantom_all = bool(o9["tokens"]) and all(_ph9(t9) for t9 in o9["tokens"].values())
            o9["phantom"] = phantom_all
            for sym9, t9 in sorted(o9["tokens"].items()):
                g9x = G.get(t9["gid"]) or {}
                px9 = 1.0 if g9x.get("is_stable") else float(live_px.get(t9["gid"]) or 0)
                if _ph9(t9):
                    px9 = 0.0
                elif not px9 and t9["usd_send_known"] and t9["qty"] > 0 and t9["usd_send"] > 0:
                    sp9 = float(self.spot.price(acct_norm.canon(g9x.get("sym") or sym9)) or 0)
                    u9 = float(t9["usd_send"]) / float(t9["qty"])
                    if sp9 > 0 and 0.1 <= sp9 / u9 <= 10.0 and not g9x.get("is_fiat"):
                        px9 = sp9
                un9 = float(t9["qty"]) * px9
                ph9 = _ph9(t9)
                toks.append({"sym": sym9, "qty": float(t9["qty"]), "costUsd": (_f(float(t9["cost"]), 2) if t9["cost"] is not None else None),
                             "phantom": ph9, **({"quar": "airdrop"} if ph9 and _ad9(t9) else {}),
                             "usdAtSend": (_f(float(t9["usd_send"]), 2) if t9["usd_send_known"] and not ph9 else None),
                             "usdNow": _f(un9, 2) or 0, "unknownCostQty": _f(float(t9["unknown"]), 6) or 0})
                now9 += un9
                send9 += float(t9["usd_send"]) if t9["usd_send_known"] and not ph9 else 0.0
                cost9 += float(t9["cost"] or 0)
            vals[a] = send9 or now9
            out.append((a, o9, toks, now9, send9, cost9))
        for a, v in sorted(vals.items(), key=lambda kv: -kv[1]):
            pool.setdefault(a, f"다른 보낸 주소({a[:6]}…{a[-4:]})") if v >= 1000 and a not in ("multi", "?") else None
        rets = self._outflow_returns(conn, groups, live_px, G)
        blabels = self._bridge_labels()
        auto9 = getattr(self, "_of_auto", None) or {}
        up_from = {}
        for t9, oc9 in (common.read_json(os.path.join(common.STATE_DIR, "tx_origin_cache.json"), {}) or {}).items():
            f9 = (oc9 or {}).get("from") if isinstance(oc9, dict) else None
            if f9:
                up_from.setdefault(f9.lower() if f9.startswith("0x") else f9, []).append(t9)
        rows = []
        sale_cands9 = {}
        sug_pid9 = {}
        self._of_sug_pid = sug_pid9
        utd9 = None if not any(blabels.get(a0) for a0, *_r in out) else self._untracked_net_deps(conn)
        utd_hint = {}
        self._of_untracked_hint = utd_hint
        for a, o9, toks, now9, send9, cost9 in out:
            d9 = dec.get(a) if isinstance(dec.get(a), dict) else {}
            verdict = d9.get("verdict")
            still_out = a in ob
            if verdict == "external":
                status = "external"
            elif verdict == "exchange":
                status = "exchange_applying" if still_out else "exchange"
            elif verdict == "own":
                status = "own_restart_needed" if still_out else "own"
            elif a in reg_now and still_out:
                status = "own_restart_needed"
            elif (o9.get("mtx") and not (set(o9.get("rtx") or ()) - set(o9.get("mtx") or ()))
                  and set(o9.get("basis") or ()) == {"roundtrip"}):
                status = "returned"
            elif o9.get("mtx") and not (set(o9.get("rtx") or ()) - set(o9.get("mtx") or ())):
                status = "exchange_matched" if o9.get("auto") else "bridge_matched"
            elif o9.get("phantom"):
                status = "spam"
            elif a == "0x0000000000000000000000000000000000008001" and o9["chains"] <= {"zksync"}:
                status = "system"
            else:
                status = "pending"
            rt9 = rets.get(a) or {"after": [], "before": []}
            ms9 = (getattr(self, "_of_man_state", None) or {}).get(a) or {}
            if verdict == "external" and ms9:
                aft9 = [dict(x9) for x9 in rt9["after"]]
                cur9 = {own9[1]: ck9 for ck9, own9 in (getattr(self, "_of_claims", None) or {}).items() if own9[0] == a}
                for l9 in (d9.get("links") if isinstance(d9.get("links"), list) else []):
                    if not isinstance(l9, dict) or l9.get("kind") != "refund" \
                            or ((ms9.get("links") or {}).get(str(l9.get("key") or "")) or {}).get("st") != "ok":
                        continue
                    tx9, sy9 = str(l9.get("tx") or "").lower(), str(l9.get("sym") or "")
                    ck9 = cur9.get(str(l9.get("key") or ""), str(l9.get("key") or ""))
                    hit9 = next((x9 for x9 in aft9 if x9.get("key") == ck9), None)
                    if hit9 is not None:
                        hit9["linked"] = True
                        continue
                    ts9l = int(l9.get("ts") or 0)
                    aft9.append({"ts": ts9l, "t": datetime.fromtimestamp(ts9l, KST).strftime("%Y-%m-%d %H:%M"),
                                 "chain": str(l9.get("key") or "").split("|")[1] if str(l9.get("key") or "").count("|") >= 3 else "",
                                 "tx": l9.get("tx") or "", "sym": sy9, "qty": float(l9.get("qty") or 0),
                                 "usd": _f(float((ms9["links"][str(l9["key"])]).get("usd") or 0), 2),
                                 "wallet": str(l9.get("where") or "")[2:] if str(l9.get("where") or "").startswith("w:") else "",
                                 "linked": True, "where": self._of_where(l9.get("where")), "key": ck9})
                rt9 = {"after": aft9, "before": rt9["before"]}
            ret_usd = sum(x["usd"] or 0 for x in rt9["after"])
            m_usd = float(o9.get("musd") or 0.0) if status == "pending" else 0.0
            sent_v = max(0.0, (send9 or now9) - m_usd)
            rkind = outflow_match.return_kind(sent_v, ret_usd) if a not in ("multi", "?") else None
            if status == "pending" and rkind == "full" and not (verdict == "clear" and d9.get("noAuto")):
                status = "returned"
            if status == "pending" and verdict in (None, "clear") and d9.get("ret") is True:
                status = "returned"
            blab9 = blabels.get(a)
            if status == "pending" and blab9 and not (verdict == "clear" and d9.get("noAuto")):
                status = "bridge_untracked"
            xw9 = o9.get("exwd") or []
            if status == "pending" and xw9 and not ob.get(a) and all(x9.get("cls") == "wallet_untracked" for x9 in xw9):
                status = "own"
            look = self._lookalike(a, pool)
            fake_look9 = False
            if status == "pending" and look and not xw9 and o9["tokens"] and all(
                    (lambda g9f: bool(g9f) and not g9f.get("is_stable") and not g9f.get("is_fiat") and not g9f.get("px_seen")
                     and not g9f.get("ex_seen") and not g9f.get("mv_seen") and not float(live_px.get(t9["gid"]) or 0)
                     and not t9["usd_send_known"] and t9["gid"] in gid_ca9)(G.get(t9["gid"]))
                    for t9 in o9["tokens"].values()):
                status = "spam"
                fake_look9 = True
            if status == "pending":
                n_pend += 1
            hints = [{"kind": k9, "label": n9} for k9, n9 in (known.get(a) or [])]
            if flow_trace.is_burn(a) and not hints:
                hints.append({"kind": "burn", "label": "발행·소각·시스템 주소 — 누구의 지갑도 아님"})
            if blab9 and not any(h9["kind"] == "bridge" for h9 in hints):
                hints.append({"kind": "bridge", "label": f"브릿지 · {blab9['name']}"})
            bas9 = sorted(o9.get("basis") or ())
            if o9.get("auto") and o9["auto"][0] == "sale":
                hints.append({"kind": "sale_bid", "label": "토큰 세일 입찰 — 체결분은 수령 토큰(세일 로트)이 입찰액을 원가로 이어받음 · "
                                                            f"{len(o9.get('mtx') or ())}/{len(o9.get('rtx') or o9['txs'])}건"})
            elif o9.get("auto"):
                nm9 = f"{len(o9.get('mtx') or ())}/{len(o9.get('rtx') or o9['txs'])}"
                hints.append({"kind": "exchange_txid" if bas9 == ["txid"] else "exchange_auto",
                              "chip": f"{o9['auto'][1]} 입금 자동 매칭 · {nm9}건",
                              "label": f"{o9['auto'][1]} 입금으로 자동 매칭(근거: " + " / ".join(OF_BASIS_KO.get(b9, b9) for b9 in bas9 or ["txid"])
                              + f") · {nm9}건 · "
                              + ("창 이전 입금 · 원가 이관 없음" if o9.get("prewin") and o9["prewin"] >= len(o9.get("mtx") or ())
                                 else (f"원가 이관됨(창 이전 입금 {o9['prewin']}건 제외)" if o9.get("prewin") else "원가 이관됨"))})
            if "roundtrip" in bas9:
                hints.append({"kind": "roundtrip", "label": "프로그램 예치 왕복 — 보낸 자산이 6시간 안에 같은 지갑으로 전액 복귀(원가 복원) · "
                                                            f"{len({x['tx'] for x in o9['list'] if (x.get('match') or {}).get('basis') == 'roundtrip'})}건"})
            sugg = []
            if status == "bridge_untracked":
                sugg.append({"kind": "bridge_untracked", "exchange": None, "label": "브릿지 → 미추적 체인",
                             "evidence": f"{blab9['name']} 로 보냈는데 추적 중인 내 지갑에 60분 안에 같은 수량 도착이 없어요 — "
                                         "받은 체인·지갑을 추가(설정 › 연결)하면 자동으로 이어져요"})
                snd9 = [x9 for x9 in o9["list"] if x9.get("ts")]
                hit9 = {}
                for dp9 in (utd9 if utd9 is not None else []):
                    for x9 in snd9:
                        if dp9.get("selfnet") and acct_norm.canon(x9.get("sym")) != dp9["cur"]:
                            continue
                        if x9["ts"] <= dp9["ts"] <= x9["ts"] + 86400 and \
                                datetime.fromtimestamp(x9["ts"], KST).date() == datetime.fromtimestamp(dp9["ts"], KST).date():
                            h9 = hit9.setdefault((dp9["ex"], dp9["cur"], dp9["net"]), {"qty": 0.0, "n": 0, "t0": dp9["ts"], "t1": dp9["ts"],
                                                                                       "day": datetime.fromtimestamp(dp9["ts"], KST).strftime("%Y-%m-%d")})
                            h9["qty"] += dp9["qty"]; h9["n"] += 1
                            h9["t0"] = min(h9["t0"], dp9["ts"]); h9["t1"] = max(h9["t1"], dp9["ts"])
                            break
                for (ex9, cur9, net9), h9 in sorted(hit9.items(), key=lambda kv: kv[1]["t0"]):
                    bu9 = sum(float(x9.get("usdAtSend") or 0) for x9 in snd9
                              if datetime.fromtimestamp(x9["ts"], KST).strftime("%Y-%m-%d") == h9["day"])
                    sugg.append({"kind": "untracked_chain_deposit", "exchange": ex9, "label": "미추적 체인 → 거래소 입금으로 보임 — 확인",
                                 "evidence": f"{h9['day'][5:]} {datetime.fromtimestamp(h9['t0'], KST).strftime('%H:%M')}"
                                             + (f"~{datetime.fromtimestamp(h9['t1'], KST).strftime('%H:%M')}" if h9["n"] > 1 else "")
                                             + f" {fx_name.get(ex9, ex9)} {cur9} {h9['qty']:,.6g} 입금({net9} 네트워크 · {h9['n']}건) — "
                                             f"이 브릿지로 보낸 ${bu9:,.0f} 가 추적 밖 체인에서 {cur9} 로 바뀌어 들어온 것일 수 있어요. "
                                             f"맞으면 {cur9} 원가를 지정해 주세요(자동 연결 안 함)",
                                 "sym": cur9, "day": h9["day"], "qty": _f(h9["qty"], 6), "net": net9, "bridgeUsd": _f(bu9, 2)})
                    u9h = utd_hint.setdefault(cur9, {"day": h9["day"], "ex": ex9, "net": net9, "qty": h9["qty"], "usd": 0.0, "names": []})
                    if u9h["day"] == h9["day"]:
                        u9h["usd"] += bu9
                        if blab9["name"] not in u9h["names"]:
                            u9h["names"].append(blab9["name"])
            if status in ("pending", "bridge_untracked"):
                pv9 = (auto9.get("proven") or {}).get(a)
                for c9 in (auto9.get("sugg") or {}).get(a) or []:
                    sugg.append({"kind": "exchange", "exchange": c9["ex"], "label": "거래소 입금으로 보임 — 확인",
                                 "evidence": c9["evidence"], "uuid": c9["uuid"]})
                if pv9 and pv9[1] == "conflict":
                    sugg.append({"kind": "exchange", "exchange": None, "label": "거래소 입금주소로 보임 — 거래소가 엇갈려 확인 필요",
                                 "evidence": "txid 일치·입금주소 목록이 서로 다른 거래소를 가리킴"})
                br9 = [(pid9, v9) for pid9, v9 in (auto9.get("bridge_amb") or {}).items()
                       if ((auto9.get("sends") or {}).get(pid9) or {}).get("dest") == a]
                if br9:
                    s0, b0 = auto9["sends"][br9[0][0]], br9[0][1][0]
                    sugg.append({"kind": "bridge", "exchange": None, "label": "브릿지로 보임 — 확인",
                                 "evidence": f"{len(br9)}건 · 예: {s0['sym']} {outflow_match.fmt_q(s0['qty'])} "
                                             f"{CHAIN_NAME.get(s0['chain'], s0['chain'])} → {CHAIN_NAME.get(b0['chain'], b0['chain'])} "
                                             f"{max(0, int((b0['ts'] - s0['ts']) // 60))}분 뒤 도착 후보 {len(br9[0][1])}건 — 유일하지 않아 자동 안 함"})
                if a == "0x0000000000000000000000000000000000008001" and o9["chains"] <= {"zksync"}:
                    sugg.append({"kind": "system", "exchange": None, "label": "zkSync 시스템 주소(부트로더) — 가스 성격",
                                 "evidence": "0x…8001 = zkSync Era 부트로더(수수료 수취)"})
            if status in ("pending", "returned", "bridge_untracked") and a not in ("multi", "?") and not blab9:
                ev9 = []
                if rt9["after"]:
                    ev9.append(f"보낸 뒤 이 주소에서 내 지갑으로 {len(rt9['after'])}건 ${ret_usd:,.0f} 받음")
                if rt9["before"]:
                    ev9.append(f"보내기 전 이 주소에서 {len(rt9['before'])}건 ${sum(x['usd'] or 0 for x in rt9['before']):,.0f} 받음(자금 출처)")
                if up_from.get(a):
                    ev9.append(f"이 주소가 내 업비트 계정에 {len(up_from[a])}건 입금(업비트 입금 발신지)")
                if ev9:
                    strong9 = bool(up_from.get(a) or rt9["before"] or rkind == "full")
                    ws9 = {x.get("wallet") for x in rt9["after"] if x.get("wallet")}
                    likely9 = (not strong9) and ((sent_v > 0 and ret_usd >= 0.5 * sent_v) or (len(rt9["after"]) >= 3 and len(ws9) >= 2))
                    if likely9 and len(ws9) >= 2:
                        ev9.append(f"내 지갑 {len(ws9)}곳과 주고받음")
                    sugg.append({"kind": "own" if (strong9 or likely9) else "roundtrip", "exchange": None,
                                 "label": "내 지갑 같음" if strong9 else ("내 지갑 가능성 높음" if likely9 else "일부 되돌려 받음"),
                                 "action": "register_own" if (strong9 or likely9) else None,
                                 "evidence": " · ".join(ev9)})
            if xw9 and status == "pending":
                x0 = xw9[-1]
                why9 = ("받는 주소를 '외부'로 판정해 둔 주소예요" if x0.get("why") == "external"
                        else "같은 txid의 출금이 여러 건이에요 — 건별 도착 확인 전 중복 가산을 보류했어요" if x0.get("why") == "txid_ambiguous"
                        else "같은 수량의 입출금 후보가 여러 건이에요 — 중복 가산을 보류했으니 도착지를 확인해 주세요" if x0.get("why") == "amount_ambiguous"
                        else f"{max(1, int(round((x0['until'] - x0['start']) / 3600)))}시간 안에 내 지갑·거래소 도착 기록이 없어요")
                ev9 = (f"{x0['src']} {x0['sym']} {outflow_match.fmt_q(x0['qty'])} 출금"
                       + (f"({x0['net']})" if x0.get("net") else "") + f" — {why9}"
                       + (f" · 내 {x0['dst']} 입금주소인데 입금 기록이 아직 없어요" if x0.get("cls") == "exchange" and x0.get("dst") else ""))
                sugg.insert(0, {"kind": "exwd", "exchange": None, "label": "이 출금은 어디로 갔나요?" if a.startswith("wd:") else "이 주소가 어떤 주소인가요?",
                                "evidence": ev9})
            flags = []
            if look:
                flags.append(dict(look, kind="lookalike",
                                  note=("주소 오염(사칭) 의심 — 앞뒤 자리가 같은 다른 주소"
                                        + (" · 소액(더스트)" if (send9 or now9) < 1 else ""))))
            if o9.get("phantom"):
                flags.append({"kind": "spoof_token", "note": "보유한 적 없는 토큰의 전송 로그(사칭 토큰 · 주소 오염 공격) — 실제 유출 아님"})
            elif fake_look9:
                flags.append({"kind": "spoof_token", "note": "닮은 주소로 간 시세·체결 없는 토큰의 전송 로그(가짜 토큰 · 주소 오염 공격) — 실제 유출 아님"})
            if a in ("multi", "?"):
                flags.append({"kind": "unknown_dest", "note": "수령 주소를 특정하지 못함(여러 상대/정보 없음)"})
            if xw9 and a.startswith("wd:"):
                flags.append({"kind": "exwd_noaddr", "note": "받는 주소 미상 — 거래소 출금 기록에 주소가 없어요"})
            lv9 = []
            for l9 in (d9.get("links") if isinstance(d9.get("links"), list) else []):
                if not isinstance(l9, dict):
                    continue
                s9 = (ms9.get("links") or {}).get(str(l9.get("key") or "")) or {}
                st9 = s9.get("st") or ("off" if verdict != "external" else "missing")
                lv9.append({"kind": l9.get("kind"), "key": l9.get("key"), "sym": l9.get("sym"), "qty": l9.get("qty"), "ts": l9.get("ts"),
                            "where": self._of_where(l9.get("where")), "tx": l9.get("tx"), "st": st9,
                            "usd": _f(float(s9["usd"]), 2) if s9.get("usd") is not None else None,
                            "costUsd": _f(float(s9["cost"]), 2) if st9 == "applied" and s9.get("cost") is not None else None})
            lref9 = float(ms9.get("refundUsd") or 0) if verdict == "external" else 0.0
            cand9 = None
            cand_top9 = None
            if verdict == "external" and d9.get("category") == self.OUTFLOW_SALE_CAT:
                ss9 = {sy9.upper() for sy9, t9 in o9["tokens"].items() if (G.get(t9.get("gid")) or {}).get("is_stable") and not _ph9(t9)}
                dis9 = {str(x9) for x9 in (d9.get("dismiss") or []) if isinstance(x9, str)}
                cand9 = self._of_sale_cands(a, int(o9["first"]), ss9, px_of=lambda g9: live_px.get(g9), skip=dis9)
                sale_cands9[a] = cand9
                sent_q9 = {sy9.upper(): float(t9["qty"]) for sy9, t9 in o9["tokens"].items() if sy9.upper() in ss9}
                fw9 = o9.get("from_w") or set()
                cx9 = [(getattr(self, "_of_cands", None) or {}).get(k9) for k9 in cand9]
                cx9 = [c9 for c9 in cx9 if c9]
                def _rk9(c9):
                    same9 = bool(c9.get("stable")) and abs(float(c9.get("qty") or 0) - sent_q9.get(str(c9.get("sym") or "").upper(), -1e18)) <= \
                        0.01 * max(1.0, sent_q9.get(str(c9.get("sym") or "").upper(), 0))
                    return (str(c9.get("where") or "") not in fw9, not same9, abs(int(c9["ts"]) - int(o9["first"])))
                cand_top9 = [{"key": c9["key"], "sym": c9["sym"], "qty": c9["qty"], "ts": int(c9["ts"]), "stable": bool(c9.get("stable")),
                              "where": self._of_where(c9.get("where") or ""), "fromSender": str(c9.get("where") or "") in fw9,
                              "kind": "refund" if c9.get("stable") else "tokens"} for c9 in sorted(cx9, key=_rk9)[:3]]
                for c9 in cx9:
                    sug_pid9.setdefault(c9["pid"], {"a": a, "nm": salelink.dest_name(a, d9), "key": c9["key"],
                                                    "kind": "refund" if c9.get("stable") else "tokens", "fromSender": str(c9.get("where") or "") in fw9})
            ltok9 = sum(float(x9["costUsd"] or 0) for x9 in lv9 if x9["kind"] == "tokens" and x9["st"] == "applied")
            ad_syms9 = {sy9 for sy9, t9 in o9["tokens"].items() if _ph9(t9) and _ad9(t9)}
            ph_syms9 = {sy9 for sy9, t9 in o9["tokens"].items() if _ph9(t9)} - ad_syms9
            ph_txn9 = 0
            if ph_syms9:
                tsy9 = {tx9: set(sy9) for tx9, sy9 in (o9.get("txsyms") or {}).items()}
                for tx9, sy9 in (o9.get("hsyms") or {}).items():
                    if tx9 not in (o9.get("txsyms") or {}):
                        tsy9.setdefault(tx9, set()).update(sy9)
                ph_txn9 = sum(1 for tx9 in o9["txs"] if tsy9.get(tx9) and tsy9[tx9] <= ph_syms9)
            wait9 = None
            if verdict == "external" and d9.get("category") == self.OUTFLOW_SALE_CAT \
                    and not any(x9["kind"] == "tokens" and x9["st"] == "applied" for x9 in lv9):
                w9 = (send9 or now9) - ret_usd - ltok9
                wait9 = round(w9, 2) if w9 >= 0.005 else None
            rows.append({
                "address": a, "chains": sorted(o9["chains"]), "chainNames": [CHAIN_NAME.get(c, c) for c in sorted(o9["chains"])],
                "firstTs": int(o9["first"]), "lastTs": int(o9["last"]),
                "first": datetime.fromtimestamp(o9["first"], KST).strftime("%Y-%m-%d"),
                "last": datetime.fromtimestamp(o9["last"], KST).strftime("%Y-%m-%d"),
                "count": len(o9["txs"]), "tokens": toks,
                "usdAtSend": _f(send9, 2) or 0, "usdNow": _f(now9, 2) or 0, "costUsd": _f(cost9, 2) or 0,
                "usdAtSendKnown": all(t9["usd_send_known"] for t9 in o9["tokens"].values() if not _ph9(t9)),
                "dust": bool(status == "pending" and dust_usd > 0 and a not in ("multi", "?")
                             and all(t9["usd_send_known"] for t9 in o9["tokens"].values() if not _ph9(t9))
                             and max(send9, now9) < dust_usd),
                "status": status, "verdict": verdict or None, "retOk": bool(d9.get("ret") is True and status == "returned"),
                "applyWait": bool(status == "own_restart_needed" and a in reload_addrs9),
                "category": d9.get("category"), "memo": d9.get("memo"), "alias": d9.get("alias"),
                "links": lv9, "linkRefundUsd": _f(lref9, 2) or 0, "linkTokenUsd": _f(ltok9, 2) or 0, "saleWait": wait9,
                "excludeLegs": [str(k0.get("key") if isinstance(k0, dict) else k0) for k0 in (d9.get("excludeLegs") or [])
                                if isinstance(k0, (str, dict))][:200],
                "candN": len(cand9) if cand9 is not None else None,
                "candTop": cand_top9,
                "linkPaidUsd": _f(float(ms9["paidUsd"]), 2) if verdict == "external" and ms9.get("paidUsd") is not None else None,
                "exchange": d9.get("exchange") or (o9["auto"][1] if o9.get("auto") else None),
                "decidedTs": d9.get("ts"), "hints": hints, "flags": flags,
                "autoMatch": ({"basis": bas9 or ["txid"], "matched": len(o9.get("mtx") or ()),
                               "of": len(o9.get("rtx") or o9["txs"]),
                               "exchange": o9["auto"][1] if o9.get("auto") else (
                                   "프로그램 예치 왕복" if set(bas9) == {"roundtrip"} else "브릿지 → 내 지갑")}
                              if (o9.get("auto") or o9.get("mtx")) else None),
                "noAuto": bool(d9.get("noAuto")),
                "bridge": ({"name": blab9["name"], "chain": blab9.get("chain")} if blab9 else None),
                "arrivals": sorted(o9.get("arrivals") or [], key=lambda x: -x["ts"])[:50], "arrivalsN": len(o9.get("arrivals") or []),
                "suggest": sugg[0] if sugg else None, "suggestions": sugg,
                "returned": sorted(rt9["after"], key=lambda x: -x["ts"])[:50], "returnedN": len(rt9["after"]),
                "returnedUsd": _f(ret_usd, 2) or 0, "returnKind": rkind,
                "netUsd": _f(sent_v - ret_usd - ltok9, 2) or 0, "matchedUsd": _f(m_usd, 2) or 0,
                "priorIn": {"n": len(rt9["before"]), "usd": _f(sum(x["usd"] or 0 for x in rt9["before"]), 2) or 0},
                "txs": [dict(x9, phantom=True) if x9.get("sym") in ph_syms9 else dict(x9, quar="airdrop") if x9.get("sym") in ad_syms9 else x9
                        for x9 in sorted(o9["list"], key=lambda x: -x["ts"])[:self.OF_LIST_CAP]],
                "txsCut": int(o9.get("listCut") or 0),
                "phantomTxN": ph_txn9})
            if o9.get("listCut"):
                rows[-1]["walletUsdAtSend"] = float(o9.get("wusd") or 0.0)
                rows[-1]["walletDays"] = dict(o9.get("wdays") or {})
            if xw9:
                rows[-1]["exwd"] = [{"ex": x9["ex"], "exName": x9["src"], "sym": x9["sym"], "qty": float(x9["qty"]), "net": x9.get("net") or "",
                                     "txid": x9.get("txid_raw") or "", "uuid": str(x9["uuid"]), "ts": int(x9["ts"]), "addr": x9.get("addr") or "",
                                     "cls": x9.get("cls"), "dst": x9.get("dst"), "why": x9.get("why"),
                                     "offc": _offc_tx(x9.get("txid_raw"))} for x9 in xw9[-20:]]
                rows[-1]["exwdN"] = len(xw9)
                oc9 = [x9 for x9 in xw9 if _offc_tx(x9.get("txid_raw"))]
                if oc9:
                    rows[-1]["exwdOffc"] = {"n": len(oc9), "ex": sorted({x9["ex"] for x9 in oc9})}
                if not ob.get(a):
                    rows[-1]["exwdOnly"] = True
            b9 = tot.setdefault(status, {"n": 0, "usdAtSend": 0.0, "usdNow": 0.0})
            fr9 = (sent_v / (send9 or now9)) if m_usd and (send9 or now9) else 1.0
            b9["n"] += 1; b9["usdAtSend"] += max(0.0, send9 - m_usd) if m_usd else send9; b9["usdNow"] += now9 * fr9
            if d9.get("category"):
                c9 = tot.setdefault("category:" + d9["category"], {"n": 0, "usdAtSend": 0.0, "usdNow": 0.0})
                c9["n"] += 1; c9["usdAtSend"] += send9; c9["usdNow"] += now9
            if ltok9 > 0:
                t9t = tot.setdefault("link_tokens", {"n": 0, "usdAtSend": 0.0, "usdNow": 0.0})
                t9t["n"] += 1; t9t["usdAtSend"] += ltok9; t9t["usdNow"] += ltok9
            if wait9:
                w9t = tot.setdefault("sale_wait", {"n": 0, "usdAtSend": 0.0, "usdNow": 0.0})
                w9t["n"] += 1; w9t["usdAtSend"] += wait9; w9t["usdNow"] += wait9
        rows.sort(key=lambda r9: (r9["status"] != "pending", -r9["lastTs"]))
        self._outflow_dests = {r9["address"]: r9["chains"] for r9 in rows}
        self._outflow_status = {r9["address"]: r9["status"] for r9 in rows}
        self._outflow_still = frozenset(a9 for a9 in self._outflow_status if a9 in ob)
        self._outflow_autorows = {r9["address"] for r9 in rows if r9.get("autoMatch")}
        self._outflow_exwd = {r9["address"] for r9 in rows if r9.get("exwdOnly")}
        self._outflow_first = {r9["address"]: r9["firstTs"] for r9 in rows}
        self._outflow_from_w = {a9: set(o9.get("from_w") or ()) for a9, o9 in groups.items() if o9.get("from_w")}
        self._sale_send_tx = {str(t9).lower() for a9, o9 in groups.items()
                              if isinstance(dec.get(a9), dict) and dec[a9].get("verdict") == "external" and dec[a9].get("category") == self.OUTFLOW_SALE_CAT
                              for t9 in (o9.get("txs") or ()) if t9}
        self._outflow_legkeys = {r9["address"]: {str(t9.get("key")) for t9 in (groups.get(r9["address"]) or {}).get("list") or [] if t9.get("key")}
                                 for r9 in rows}
        self._outflow_legmeta = {a9: {x0[6]: (x0[7], x0[8]) for x0 in (o9.get("sends") or ()) if x0[6]} for a9, o9 in ob.items()}
        try:
            self._sale_cand_notify(sale_cands9)
        except Exception as e9:
            log.warning("세일 참가금 후보 알림 실패(다음 빌드): %s", e9)
        self._outflow_rettx = {r9["address"]: {str(x9.get("tx") or "").lower() for x9 in r9.get("returned") or []} for r9 in rows if r9.get("returned")}
        return rows, n_pend, {k: {"n": v["n"], "usdAtSend": round(v["usdAtSend"], 2), "usdNow": round(v["usdNow"], 2)}
                              for k, v in tot.items()}

    def _flow_cache_load(self) -> dict:
        p9 = os.path.join(common.STATE_DIR, flow_trace.CACHE_NAME)
        try:
            st9 = os.stat(p9)
            sig9 = (st9.st_ino, st9.st_mtime_ns, st9.st_size)
        except OSError:
            sig9 = None
        hit9 = self.__dict__.get("_flow_cache_hit")
        if sig9 is not None and hit9 is not None and hit9[0] == sig9:
            return hit9[1]
        c9 = flow_trace.load_cache(common.STATE_DIR)
        self._flow_cache_hit = (sig9, c9) if sig9 is not None else None
        return c9

    def _attach_flows(self, conn, rows: list, live_px: dict, G: dict):
        cache = self._flow_cache_load()
        rows = [r9 for r9 in rows if not r9.get("exwdOnly")]
        cands = flow_trace.candidates(rows, cache, min_usd=float((self.cfg.get("flow_trace") or {}).get("min_usd") or flow_trace.MIN_USD))
        off9 = set(self.cfg.get("_disabled_chains") or ())
        if off9:
            cands = [c9 for c9 in cands if not off9.intersection(c9.get("chains") or ())]
        lk9 = getattr(self, "_flow_lock", None)
        if lk9 is not None:
            with lk9:
                self._flow_pending = cands
        try:
            mine = {xchain_match.norm(w.get("address")) for w in (common.read_json(common.CONFIG_PATH, {}) or {}).get("wallets") or []
                    if w.get("address")}
            alias = {xchain_match.norm(w.get("address")): (w.get("label") or "") for w in (common.read_json(common.CONFIG_PATH, {}) or {}).get("wallets") or []
                     if w.get("address")}
        except BaseException:
            mine, alias = set(), {}
        by_addr = {r9["address"]: r9 for r9 in rows}
        dec = self.outflow_decisions()
        exch = {}
        for a9, kk in self._known_addrs().items():
            for k9, n9 in kk:
                if k9 == "exchange_deposit":
                    exch.setdefault(a9, n9)
        for r9 in rows:
            if r9["status"] in ("exchange", "exchange_matched", "exchange_applying") and r9["address"] not in ("multi", "?"):
                exch.setdefault(r9["address"], "거래소 입금주소" + (f" ({r9['exchange']})" if r9.get("exchange") else ""))
        for a9, v9 in dec.items():
            if isinstance(v9, dict) and v9.get("verdict") == "own":
                mine.add(xchain_match.norm(a9))
        bridges = {a9: (v9.get("name") or "브릿지") for a9, v9 in self._bridge_labels().items()}
        ents = {r9["address"]: (cache.get("dest") or {}).get(r9["address"]) for r9 in rows}
        recips = set()
        for a9, e9 in ents.items():
            for ev9 in flow_trace.all_events(e9 or {}):
                if ev9.get("kind") == "out" and ev9.get("cp") and ev9["cp"] != "?":
                    recips.add(ev9["cp"])
        targets = {a9 for a9 in recips if a9 not in mine} | {r9["address"] for r9 in rows if r9["address"] not in ("multi", "?")}
        pseudo = {a9: {"first": 0, "txs": set(), "phantom": False} for a9 in targets}
        back = {a9: v9.get("after") or [] for a9, v9 in self._outflow_returns(conn, pseudo, live_px, G).items()}
        from_mine = {}
        want_tx = {}
        for a9, r9 in by_addr.items():
            if a9 in ("multi", "?") or r9["status"] == "spam":
                continue
            from_mine[a9] = {"n": r9["count"], "usd": float(r9.get("usdAtSend") or r9.get("usdNow") or 0), "wallets": set()}
            for t9 in r9.get("txs") or []:
                want_tx[t9["tx"]] = a9
        ks = list(want_tx)
        for i in range(0, len(ks), 400):
            ch = ks[i:i + 400]
            for rr in conn.execute("SELECT DISTINCT source_id, location FROM postings WHERE source_kind='chain_tx' AND leg_kind='move_out'"
                                   " AND location LIKE 'wallet:%' AND source_id IN (" + ",".join("?" * len(ch)) + ")", ch).fetchall():
                a9 = want_tx.get(rr["source_id"])
                if a9 in from_mine:
                    from_mine[a9]["wallets"].add(str(rr["location"]).split(":")[-1])
        sym_px = {}
        for gid9, g9 in G.items():
            if g9.get("sym") and live_px.get(gid9):
                sym_px.setdefault(str(g9["sym"]).upper(), float(live_px[gid9]))
        exch_in = {}
        for a9, ds9 in (getattr(self, "_of_deps_origin", None) or {}).items():
            for d9 in ds9:
                cur9 = outflow_match.canon_sym(d9.get("cur"), d9.get("ex"))
                amt9 = float(d9.get("amt") or 0)
                usd9 = amt9 if cur9 in outflow_match.STABLES else (amt9 * sym_px[cur9] if cur9 in sym_px else None)
                exch_in.setdefault(a9, []).append({"ts": int(d9.get("ts") or 0), "usd": _f(usd9, 2) if usd9 is not None else None,
                                                   "ex": d9.get("ex"), "txn": d9.get("txn"), "sym": cur9, "qty": amt9})
        wd_in = {a9: {"n": int(u9.get("n") or 0), "exchanges": [self.EX_NAME_KO.get(x9, x9) for x9 in u9.get("exchanges") or []]}
                 for a9, u9 in (getattr(self, "_wd_dest_unknown", None) or {}).items()}
        rinfo = {a9: {"status": r9["status"], "returnKind": r9.get("returnKind"), "priorUsd": (r9.get("priorIn") or {}).get("usd") or 0}
                 for a9, r9 in by_addr.items()}
        ap = getattr(self, "_flow_asset_px", None)
        n_as = conn.execute("SELECT COUNT(*) AS n FROM assets").fetchone()["n"]
        if not ap or ap[0] != n_as:
            amap = {}
            for rr in conn.execute("SELECT chain, address, group_id, asset_id FROM assets WHERE address IS NOT NULL").fetchall():
                amap[(rr["chain"], xchain_match.norm(rr["address"]))] = rr["group_id"] or -rr["asset_id"]
            ap = self._flow_asset_px = (n_as, amap)
        nat_gid = {}
        for gid9, g9 in G.items():
            if g9.get("sym") in ("SOL", "ETH", "BNB", "POL") and live_px.get(gid9):
                nat_gid.setdefault(g9["sym"], gid9)

        q_flow9 = set(getattr(self, "_risk_quarantined", None) or ()) - set(getattr(self, "_risk_airdrop_only", None) or ())

        def px_now(chain, token, sym):
            if token == "native":
                g9 = nat_gid.get(flow_trace.NATIVE.get(chain, "SOL") if chain != "sol" else "SOL")
                return float(live_px.get(g9) or 0) or None
            if flow_trace.stable_sym(chain, token):
                return 1.0
            g9 = ap[1].get((chain, xchain_match.norm(token)))
            if g9 is None:
                return None
            if (G.get(g9) or {}).get("is_stable"):
                return 1.0
            if g9 in q_flow9:
                return None
            return float(live_px.get(g9) or 0) or None

        def lookalike(x9):
            if x9 in mine or len(x9) < 12:
                return False
            return any(m9 != x9 and len(m9) == len(x9) and m9[:4] == x9[:4] and m9[-4:] == x9[-4:] for m9 in mine)
        grp9 = {}
        try:
            for ra9 in conn.execute("SELECT chain, address, group_id, asset_id FROM assets WHERE kind='token' AND address IS NOT NULL").fetchall():
                gs9 = (G.get(ra9["group_id"] or -ra9["asset_id"]) or {}).get("sym")
                if gs9:
                    grp9[(ra9["chain"], xchain_match.norm(ra9["address"]))] = gs9
        except Exception:
            grp9 = {}
        spam_tok9 = self._flow_spam_tokens(ap[1], q_flow9)
        ctx = {"mine": mine, "alias": alias, "exch": exch, "bridges": bridges, "lookalike": lookalike, "back": back,
               "from_mine": from_mine, "exch_in": exch_in, "wd_in": wd_in, "rows": rinfo, "grp": grp9, "spam_tok": spam_tok9}
        reg9 = {}
        for r9 in rows:
            if r9["status"] not in flow_trace.ELIGIBLE or r9["address"] in ("multi", "?") or r9.get("dust") or flow_trace.is_burn(r9["address"]):
                continue
            if max(float(r9.get("usdAtSend") or 0), float(r9.get("usdNow") or 0)) < flow_trace.MIN_USD:
                continue
            e9 = ents.get(r9["address"])
            cl9 = getattr(self, "_of_claim_legs", None) or {}
            if cl9:
                r9f = dict(r9, links=cl9.get(r9["address"]) or [], linkedAway=[l9 for a9, ls9 in cl9.items() if a9 != r9["address"] for l9 in ls9])
            else:
                r9f = r9
            f9 = flow_trace.account(r9f, e9, ctx, px_now=px_now)
            if not e9:
                f9["status"] = "queued"
            elif e9.get("status") in ("budget", "paused", "running", "error") and not e9.get("t"):
                f9["status"] = "scanning" if e9.get("status") != "error" else "error"
                now9f = time.time()
                t0f, rtf = float(e9.get("t0") or 0), float(e9.get("rt") or 0)
                if f9["status"] == "scanning" and ((t0f and now9f - t0f > flow_trace.SCAN_TIMEOUT_SEC)
                                                   or (rtf and now9f - rtf > flow_trace.SCAN_IDLE_SEC)):
                    f9["status"] = "timeout"
                f9["scanSince"] = int(t0f) or None
                f9["lastTry"] = int(rtf) or None
                f9["scanWhy"] = str(e9.get("status") or "")
            r9["flow"] = f9
            if r9["status"] == "pending" and f9.get("status") in ("ok", "partial") and float(f9.get("sent") or 0) > 0 \
                    and float(f9.get("net") or 0) <= 0.5:
                sg9 = {"kind": "returned", "exchange": None, "label": "전액 이상 되돌려 받음", "action": "mark_returned",
                       "evidence": "흐름 추적 기준 · 직접·경유·거래소·브릿지로 돌려받은 돈이 보낸 돈 이상이에요"}
                r9["suggestions"] = [sg9] + [x9 for x9 in (r9.get("suggestions") or []) if x9.get("kind") != "roundtrip"]
                r9["suggest"] = sg9
                r9["retSugg"] = True
            for x9 in f9["recips"]:
                if x9["base"] == "eoa":
                    g9 = reg9.setdefault(x9["addr"], {"chains": set(), "dests": set(), "level": x9["score"]["level"]})
                    g9["chains"].update(x9["chains"]); g9["dests"].add(r9["address"])
        self._flow_recips = reg9

    @staticmethod
    def _flow_spam_tokens(amap: dict, quarantined) -> frozenset:
        q9 = set(quarantined or ())
        return frozenset(k9 for k9, g9 in (amap or {}).items() if g9 in q9) if q9 else frozenset()

    EX_NAME_KO = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "kucoin": "쿠코인", "gate": "게이트", "bithumb": "빗썸", "upbit": "업비트", "hyperliquid": "Hyperliquid"}

    BF_DONE_FRAC = 0.999
    BF_STALL_SEC = 1800
    BF_UNIT_KO = {"tx": "건", "blocks": "블록", "sigs": "개", "tasks": "개"}

    @staticmethod
    def _bf_jobs():
        out = []
        st = bf_engine.read_status()
        now = time.time()
        for unit, items in st.items():
            if not isinstance(items, dict) or unit.startswith("_"):
                continue
            for key, it in items.items():
                if not isinstance(it, dict) or it.get("phase") in ("done", "live", None):
                    continue
                if now - float(it.get("updated") or 0) > 3 * 3600:
                    continue
                tot, done = it.get("total"), it.get("done")
                frac = None
                try:
                    if tot:
                        frac = max(0.0, min(1.0, float(done or 0) / float(tot)))
                except (TypeError, ValueError):
                    frac = None
                if frac is not None and frac >= StateBuilder.BF_DONE_FRAC:
                    continue
                info = {k9: it.get(k9) for k9 in ("done", "total", "unit", "moved_at", "updated", "note")}
                out.append((key if ":" in key else unit, frac, it.get("eta_sec"),
                            sum(int(v) for v in (it.get("errors") or {}).values()), it.get("phase"), info))
        return out

    @staticmethod
    def _bf_job_text(name, frac, eta, ne, ph, info=None, now=None) -> dict:
        info = info or {}
        now = time.time() if now is None else now
        parts = str(name).split(":")
        ck, kind = parts[0], (parts[1] if len(parts) > 1 else "")
        chain = CHAIN_NAME.get(ck) or StateBuilder.EX_NAME_KO.get(ck) or ck
        sub = ""
        if ck == "sol" and kind and kind not in ("extend",):
            sub = f" 지갑 {kind[:4]}…"
            kind = parts[2] if len(parts) > 2 else "sigs"
        if ck == "bsc" and kind == "newwallet":
            sub, kind = " 새 지갑", "extend"
        note = str(info.get("note") or "")
        mv0 = info.get("moved_at") or info.get("updated")
        try:
            idle9 = now - float(mv0) if mv0 else 0.0
        except (TypeError, ValueError):
            idle9 = 0.0
        if ("circuit" in note or "서킷" in note) and idle9 >= 300:
            what = "외부 탐색기 장애로 대기"
        elif kind == "rpc" or ph == "scan":
            what = "과거 창 넓히는 중" if ph == "extend" else "과거 블록 훑는 중"
        elif kind == "job":
            what = {"collect": "과거 거래 조회 중", "extend": "과거 창 넓히는 중", "emit": "찾은 거래 기록에 반영 중"}.get(ph, "과거 거래 불러오는 중")
        elif kind == "extend" or ph == "extend":
            what = "과거 창 넓히는 중"
        elif ph == "wait":
            what = "옛 기록 차례 대기(오늘 몫을 다 써서 UTC 0시 · 한국 오전 9시에 이어 받음)"
        elif ph == "sigs" or kind == "sigs":
            what = "거래 서명 모으는 중"
        elif ph == "parse":
            what = "거래 내용 읽는 중"
        else:
            what = "과거 거래 불러오는 중"
        prog = None
        u9 = StateBuilder.BF_UNIT_KO.get(str(info.get("unit") or ""))
        try:
            if info.get("total") and u9 and float(info["total"]) < 1e6:
                prog = f"{int(float(info.get('done') or 0)):,}/{int(float(info['total'])):,}{u9}"
            elif frac is not None:
                prog = f"{int(frac * 100)}%"
            elif info.get("done") is not None and u9:
                prog = f"{int(float(info['done'])):,}{u9} 처리"
        except (TypeError, ValueError):
            prog = None
        mv = info.get("moved_at") or info.get("updated")
        try:
            mv = float(mv) if mv else None
        except (TypeError, ValueError):
            mv = None
        last = datetime.fromtimestamp(mv, KST).strftime("%H:%M") if mv else None
        if last and mv and now - mv >= 86400:
            last = datetime.fromtimestamp(mv, KST).strftime("%m-%d %H:%M")
        stalled = bool(mv) and now - mv >= StateBuilder.BF_STALL_SEC and ph != "wait"
        eta_s = None
        if not stalled and eta is not None and float(eta) > 0:
            eta_s = "약 " + StateBuilder._eta_ko(float(eta)) + " 남음"
        tail = []
        if prog:
            tail.append(prog)
        if stalled:
            tail.append(f"멈춤(마지막 진행 {last})")
        elif eta_s:
            tail.append(eta_s)
        if ne and not stalled:
            tail.append(f"재시도 {ne}회")
        text = f"{chain}{sub} · {what}" + (" — " + " · ".join(tail) if tail else "")
        return {"chain": chain + sub, "what": what, "prog": prog, "eta": eta_s, "stalled": stalled, "last": last,
                "pct": int(frac * 100) if frac is not None else None, "errors": int(ne or 0), "text": text}

    @staticmethod
    def _eta_ko(sec: float) -> str:
        sec = int(sec)
        if sec < 90:
            return "1분"
        if sec < 3600:
            return f"{sec // 60}분"
        h9, m9 = divmod(sec // 60, 60)
        if h9 >= 24:
            return f"{h9 // 24}일 {h9 % 24}시간" if h9 % 24 else f"{h9 // 24}일"
        return f"{h9}시간" + (f" {m9}분" if m9 and h9 < 10 else "")

    def _backfill_progress(self, conn):
        sd = common.STATE_DIR
        jobs = []
        try:
            jobs = self._bf_jobs()
        except Exception:
            jobs = []
        eta_txt = None
        now9 = time.time()
        jtx = [StateBuilder._bf_job_text(*j, now=now9) for j in jobs]
        etas = [j[2] for j, t9 in zip(jobs, jtx) if j[2] is not None and not t9["stalled"]]
        if etas:
            eta_txt = bf_engine.fmt_eta(max(etas))
        job_txt = " · ".join(t9["text"] for t9 in jtx[:4]) or None
        jobs_out = [{k9: t9[k9] for k9 in ("chain", "what", "prog", "eta", "stalled", "last", "pct", "errors", "text")} for t9 in jtx[:6]]
        if os.path.exists(os.path.join(sd, "backfill_done")):
            if not jobs:
                return None
            fr = [j[1] for j in jobs if j[1] is not None]
            stl = sum(1 for t9 in jtx if t9["stalled"])
            return {"pct": int(round(100.0 * sum(fr) / len(fr))) if fr else 0,
                    "detail": f"추가로 과거 거래 불러오는 중 {len(jobs)}건" + (f" · 멈춤 {stl}" if stl else ""),
                    "active": job_txt, "remain": None, "eta": eta_txt, "jobs": jobs_out, "stalled": stl}
        try:
            units, total = 0.0, 0
            done_pairs, tot_pairs = 0, 0
            active = []
            curs = {}
            ch_done, ch_tot = {}, {}
            for w in self.cfg.get("wallets", []):
                wtype = w.get("type", "evm")
                if wtype == "evm":
                    total += 1
                    tot_pairs += 1
                    ch = w["chain"]
                    ch_tot[ch] = ch_tot.get(ch, 0) + 1
                    if ch not in curs:
                        curs[ch] = common.read_json(
                            os.path.join(sd, f"cursor_evm_{ch}.json"), {})
                    a = w["address"].lower()
                    bk9 = curs[ch].get("_bk:" + a)
                    if isinstance(bk9, dict) and bk9.get("why") == "new" and type(bk9.get("done")) is int and type(bk9.get("to")) is int \
                            and type(bk9.get("from")) is int and bk9["done"] < bk9["to"]:
                        units += min(1.0, max(0.0, (bk9["done"] - bk9["from"]) / max(1, bk9["to"] - bk9["from"])))
                    elif a in curs[ch]:
                        units += 1.0
                        done_pairs += 1
                        ch_done[ch] = ch_done.get(ch, 0) + 1
                    else:
                        ck = curs[ch].get("_bf:" + a)
                        if isinstance(ck, dict) and ck.get("v2"):
                            jf = next((j[1] for j in jobs if j[0] == f"{ch}:job" and j[1] is not None), 0.0)
                            ph = next((j[4] for j in jobs if j[0] == f"{ch}:job"), "collect")
                            units += min(1.0, 0.5 * jf if ph == "collect" else 0.5 + 0.5 * jf)
                            active.append(f"{ch} {w.get('label') or a[:8]} v2")
                        elif isinstance(ck, dict):
                            units += min(1.0, (int(ck.get("ep") or 0)) / 3.0)
                            active.append(f"{ch} {w.get('label') or a[:8]}"
                                          f" {int(ck.get('pages') or 0)}p")
            sol_cur = common.read_json(os.path.join(sd, "cursor_sol.json"), {})
            for w in self.cfg.get("wallets", []):
                if w.get("type") == "sol":
                    total += 1
                    units += 1.0 if w["address"] in sol_cur else 0.0
            bcur = common.read_json(os.path.join(sd, "cursor_bsc.json"), {})
            head, frm = int(bcur.get("head") or 0), int(bcur.get("from_block") or 0)
            total += 1
            bstat = (bf_engine.read_status().get("bsc") or {}).get("bsc") or {}
            if bstat.get("total") and isinstance(bcur.get("_bf_start"), int):
                units += min(1.0, max(0.0, float(bstat.get("done") or 0) / float(bstat["total"])))
            elif head and frm:
                days = int((self.cfg.get("bsc") or {}).get("backfill_days", 150))
                start = head - days * 28800
                units += min(1.0, max(0.0, (frm - start) / max(1, head - start)))
            rc_have = {r[0].replace("recon_done_", "") for r in conn.execute(
                "SELECT k FROM meta WHERE k LIKE 'recon_done_%'")}
            rc_expect = set(self.cfg.get("chains") or {}) | {"bsc", "sol", "upbit"}
            rc, rc_total = len(rc_have & rc_expect), len(rc_expect)
            pct = int(round(units * 100.0 / total)) if total else 0
            if pct >= 100 and rc < rc_total:
                pct = 99
            remain_c = [f"{c} {ch_done.get(c, 0)}/{t}" for c, t in sorted(ch_tot.items())
                        if ch_done.get(c, 0) < t]
            remain_r = []
            for c in sorted(rc_expect - rc_have):
                np9 = len(common.read_json(
                    os.path.join(sd, f"pending_detail_{c}.json"), {})) \
                    if c not in ("bsc", "sol", "upbit") else 0
                remain_r.append(f"{c} (잔여상세 {np9}건)" if np9 else c)
            remain = []
            if remain_c:
                remain.append("수집 남음: " + " · ".join(remain_c))
            if remain_r:
                remain.append("대사 대기: " + " · ".join(remain_r))
            act = " · ".join(active[:3]) if active else None
            if job_txt:
                act = job_txt if not act else act + " · " + job_txt
            return {"pct": pct,
                    "detail": f"체인쌍 {done_pairs}/{tot_pairs} · 대사 {rc}/{rc_total}",
                    "active": act,
                    "remain": " / ".join(remain) if remain else None,
                    "eta": eta_txt, "jobs": jobs_out, "stalled": sum(1 for t9 in jtx if t9["stalled"])}
        except Exception:
            return None

    def _backfill_pct(self, which: str) -> str:
        sd = common.STATE_DIR
        try:
            if which == "evm":
                total = done = 0
                for w in self.cfg.get("wallets", []):
                    if w.get("type", "evm") != "evm":
                        continue
                    total += 1
                    cur = common.read_json(
                        os.path.join(sd, f"cursor_evm_{w['chain']}.json"), {})
                    bk9 = cur.get("_bk:" + w["address"].lower())
                    if w["address"].lower() in cur and not (isinstance(bk9, dict) and bk9.get("why") == "new"):
                        done += 1
                if total and done >= total:
                    return "증분 감시"
                return f"백필 {done}/{total}쌍"
            if which == "sol":
                owners = [w["address"] for w in self.cfg.get("wallets", [])
                          if w.get("type") == "sol"]
                cur = common.read_json(os.path.join(sd, "cursor_sol.json"), {})
                done = sum(1 for o in owners if o in cur)
                if owners and done >= len(owners):
                    return "증분 감시"
                return f"백필 {done}/{len(owners)}지갑"
            if which == "bsc":
                cur = common.read_json(os.path.join(sd, "cursor_bsc.json"), {})
                head = int(cur.get("head") or 0)
                frm = int(cur.get("from_block") or 0)
                if head and frm:
                    days = int((self.cfg.get("bsc") or {}).get("backfill_days", 150))
                    start = head - days * 28800
                    span = max(1, head - start)
                    pct = min(100, max(0, int((frm - start) * 100 / span)))
                    return "증분 감시" if head - frm < 3000 else f"백필 {pct}%"
                return "백필 시작 대기"
        except Exception:
            pass
        return "상태 미상"

    def _last_scan_str(self, which=None) -> str:
        newest = 0
        pats = {"evm": "cursor_evm_", "sol": "cursor_sol", "bsc": "cursor_bsc"}
        off9 = {f"cursor_evm_{c}.json" for c in (self.cfg.get("_disabled_chains") or [])}
        try:
            for fn in os.listdir(common.STATE_DIR):
                if which and not fn.startswith(pats[which]):
                    continue
                if not which and not fn.startswith("cursor"):
                    continue
                if fn in off9:
                    continue
                newest = max(newest, os.path.getmtime(os.path.join(common.STATE_DIR, fn)))
        except OSError:
            pass
        if not newest:
            return "수집 대기"
        ago = int(time.time() - newest)
        if ago < 90:
            return f"{ago}초 전 스캔"
        return f"{ago // 60}분 전 스캔"

    @staticmethod
    def _upbit_led_timeline(conn):
        out = {}
        try:
            for r in conn.execute("SELECT a.group_id, p.event_ts, p.qty_base, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                                  " WHERE p.location='exchange:upbit' AND a.group_id IS NOT NULL AND a.kind!='fiat'"):
                q9 = Decimal(int(r[2])) / (Decimal(10) ** int(r[3] if r[3] is not None else 18))
                if q9:
                    out.setdefault(int(r[0]), []).append((int(r[1]), q9))
        except Exception as e9:
            log.warning("원장 업비트 위치 이력 조회 실패(지난날 업비트 미매칭 몫 빼기 생략): %s", e9)
            return {}
        for v9 in out.values():
            v9.sort()
        return out

    def _upbit_krw_timeline(self, conn):
        try:
            key9 = tuple(conn.execute("SELECT COUNT(*), MAX(observed_at) FROM raw_ex WHERE exchange='upbit'"
                                      " AND kind IN ('order', 'deposit', 'withdraw')").fetchone())
        except Exception as e9:
            log.warning("업비트 원화 타임라인 조회 실패(과거일 이월 유지): %s", e9)
            return None
        if self._upbit_krw_tl and self._upbit_krw_tl[0] == key9:
            return self._upbit_krw_tl[1]
        latest = {}
        for kind9, uid9, rev9, pl9 in conn.execute(
                "SELECT kind, uuid, revision, payload FROM raw_ex WHERE exchange='upbit' AND kind IN ('order', 'deposit', 'withdraw')"):
            k9 = (kind9, uid9)
            if k9 not in latest or int(rev9) > latest[k9][0]:
                latest[k9] = (int(rev9), pl9)
        tl = []
        tlo = []
        for (kind9, _u9), (_r9, pl9) in latest.items():
            try:
                o = json.loads(pl9)
                if kind9 == "order":
                    if not str(o.get("market") or "").upper().startswith("KRW-"):
                        continue
                    side = str(o.get("side") or "").lower()
                    funds9 = o.get("executed_funds")
                    funds = (Decimal(str(funds9)) if funds9 is not None
                             else Decimal(str(o.get("price") or "0")) * Decimal(str(o.get("executed_volume") or "0")))
                    fee = Decimal(str(o.get("paid_fee") if o.get("paid_fee") not in (None, "") else "0"))
                    if side not in ("bid", "ask") or (funds == 0 and fee == 0):
                        continue
                    d9 = (funds - fee) if side == "ask" else -(funds + fee)
                    ts9 = acct_norm.fill_ts(o) or datetime.fromisoformat(str(o["created_at"])).timestamp()
                elif str(o.get("currency") or "").upper() == "KRW":
                    st9 = str(o.get("state") or "").upper()
                    amt = Decimal(str(o.get("amount") or "0"))
                    if kind9 == "deposit" and st9 == "ACCEPTED":
                        d9 = amt
                    elif kind9 == "withdraw" and st9 == "DONE":
                        d9 = -(amt + Decimal(str(o.get("fee") or "0")))
                    else:
                        continue
                    ts9 = datetime.fromisoformat(str(o.get("done_at") or o["created_at"])).timestamp()
                else:
                    continue
            except (ValueError, TypeError, KeyError, InvalidOperation):
                continue
            tl.append((int(ts9), d9))
            if kind9 == "order":
                tlo.append((int(ts9), d9))
        tl.sort(key=lambda x: x[0])
        self._upbit_krw_tl = (key9, tl, tlo)
        return tl

    KRW_FLOW_EX = (("upbit", "업비트"), ("bithumb", "빗썸"))
    KRW_FAIL_ST = frozenset(("REJECTED", "FAILED", "CANCELLED", "CANCELED", "REFUNDED"))

    @staticmethod
    def _krw_bank_moves(conn, exs):
        exs = tuple(exs)
        if not exs:
            return []
        latest9 = {}
        for ex9, kind9, uid9, rev9, pl9 in conn.execute(
                "SELECT exchange, kind, uuid, revision, payload FROM raw_ex WHERE exchange IN (" + ",".join("?" * len(exs)) + ")"
                " AND kind IN ('deposit', 'withdraw')", exs):
            k9 = (ex9, kind9, uid9)
            if k9 not in latest9 or int(rev9) > latest9[k9][0]:
                latest9[k9] = (int(rev9), pl9)
        out = []
        for (ex9, kind9, _u9), (_r9, pl9) in latest9.items():
            try:
                o9 = json.loads(pl9)
                if str(o9.get("currency") or "").upper() != "KRW":
                    continue
                st9 = str(o9.get("state") or "").upper()
                amt9 = float(o9.get("amount") or 0)
                if kind9 == "deposit" and st9 == "ACCEPTED":
                    k9 = amt9
                elif kind9 == "withdraw" and st9 == "DONE":
                    k9 = -(amt9 + float(o9.get("fee") or 0))
                else:
                    continue
                ts9 = datetime.fromisoformat(str(o9.get("done_at") or o9["created_at"])).timestamp()
                int9 = kind9 == "deposit" and (str(o9.get("transaction_type") or "").lower() == "internal"
                                               or str(o9.get("txid") or "").startswith(("quarterly_payment", "quick_payment")))
            except (ValueError, TypeError, KeyError):
                continue
            out.append((ex9, ts9, k9, int9))
        return out

    @staticmethod
    def _krw_flow_row(ex9, exn9, kind9, uid9, o):
        if str(o.get("currency") or "").upper() != "KRW":
            return None
        st9 = str(o.get("state") or "").upper()
        amt9 = Decimal(str(o.get("amount") or "0"))
        fee9 = Decimal(str(o.get("fee") or "0")) if kind9 == "withdraw" else Decimal(0)
        if not amt9.is_finite() or not fee9.is_finite() or amt9 <= 0:
            return None
        done9 = (st9 == "ACCEPTED") if kind9 == "deposit" else (st9 == "DONE")
        stx9 = "done" if done9 else ("fail" if st9 in StateBuilder.KRW_FAIL_ST else "wait")
        tsr9 = (o.get("done_at") if done9 else None) or o.get("created_at")
        ts9 = int(datetime.fromisoformat(str(tsr9)).timestamp())
        txid9 = str(o.get("txid") or "")
        internal9 = kind9 == "deposit" and (str(o.get("transaction_type") or "").lower() == "internal"
                                           or txid9.startswith(("quarterly_payment", "quick_payment")))
        note9 = ("예치금 이용료(분기 지급)" if txid9.startswith("quarterly_payment") else "거래소 내부 지급") if internal9 else ""
        return {"key": f"{ex9}:{kind9}:{uid9}", "t": ts9, "d": datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d %H:%M"),
                "ex": exn9, "dir": "in" if kind9 == "deposit" else "out", "amt": int(amt9.to_integral_value()),
                "fee": int(fee9.to_integral_value()), "st": stx9, "stRaw": st9, "src": "int" if internal9 else "bank", "note": note9}

    def _krw_flows(self, conn):
        try:
            key9 = tuple(tuple(r9) for r9 in conn.execute(
                "SELECT exchange, COUNT(*), MAX(observed_at) FROM raw_ex WHERE exchange IN ('upbit', 'bithumb')"
                " GROUP BY exchange ORDER BY exchange").fetchall())
        except Exception as e9:
            log.warning("원화 입출금 조회 실패: %s", e9)
            return None
        c9 = self.__dict__.get("_krw_fl_c")
        if c9 and c9[0] == key9:
            return c9[1]
        conn9 = {ex9 for ex9, _n9, _m9 in key9}
        rows, cov = [], {}
        for ex9, exn9 in self.KRW_FLOW_EX:
            latest9 = {}
            for kind9, uid9, rev9, pl9 in conn.execute(
                    "SELECT kind, uuid, revision, payload FROM raw_ex WHERE exchange=? AND kind IN ('deposit', 'withdraw')", (ex9,)):
                if (kind9, uid9) not in latest9 or int(rev9) > latest9[(kind9, uid9)][0]:
                    latest9[(kind9, uid9)] = (int(rev9), pl9)
            n9 = 0
            for (kind9, uid9), (_r9, pl9) in latest9.items():
                try:
                    r9 = self._krw_flow_row(ex9, exn9, kind9, uid9, json.loads(pl9))
                except (ValueError, TypeError, KeyError, InvalidOperation, AttributeError):
                    continue
                if r9:
                    rows.append(r9)
                    n9 += 1
            cov[ex9] = {"name": exn9, "on": ex9 in conn9, "n": n9}
        rows.sort(key=lambda r9: (-r9["t"], r9["key"]))
        mon, tot = {}, {"in": 0, "out": 0, "fee": 0, "net": 0, "intIn": 0, "n": 0, "fail": 0, "wait": 0, "first": None, "last": None}
        for r9 in rows:
            ym9 = r9["d"][:7]
            b9 = mon.setdefault(ym9, {"ym": ym9, "in": 0, "out": 0, "fee": 0, "net": 0, "intIn": 0, "n": 0, "fail": 0, "wait": 0})
            for a9 in (b9, tot):
                if r9["st"] != "done":
                    a9[r9["st"]] += 1
                    continue
                a9["n"] += 1
                if r9["src"] == "int":
                    a9["intIn"] += r9["amt"]
                elif r9["dir"] == "in":
                    a9["in"] += r9["amt"]
                else:
                    a9["out"] += r9["amt"]
                    a9["fee"] += r9["fee"]
                a9["net"] = a9["in"] - a9["out"]
            if r9["st"] == "done":
                d9 = r9["d"][:10]
                tot["first"] = d9 if not tot["first"] or d9 < tot["first"] else tot["first"]
                tot["last"] = d9 if not tot["last"] or d9 > tot["last"] else tot["last"]
        out = {"rows": rows, "byMonth": [mon[k9] for k9 in sorted(mon, reverse=True)], "total": tot, "cov": cov}
        self._krw_fl_c = (key9, out)
        return out

    FLOW_SKIP_EV = frozenset(("SWAP", "CONVERT", "EXF_BUY", "EXF_SELL", "EX_BUY", "EX_SELL", "LP_ADD", "LP_REMOVE", "LP_ADJUST",
                              "NOOP", "FAILED", "OPENING"))
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

    @staticmethod
    def _flow_debts() -> dict:
        out = {}
        for ex9 in ("binance", "bybit", "okx", "kucoin", "gate", "bithumb"):
            bp9 = os.path.join(common.STATE_DIR, f"exf_balances_{ex9}.json")
            if not os.path.exists(bp9):
                continue
            try:
                dd9 = (common.read_json(bp9, {}) or {}).get("debts")
            except (Exception, SystemExit):
                continue
            for s9, v9 in (dd9.items() if isinstance(dd9, dict) else ()):
                try:
                    fv9 = Decimal(str(v9))
                except (InvalidOperation, ValueError, TypeError):
                    continue
                if fv9.is_finite() and fv9 < 0:
                    out.setdefault(f"{ex9}:recon", {})[str(s9).upper()] = fv9
        return out

    def _hist_flow_kit(self, G, skip_gids, offc_ids, transit, rate_now, today_iso, daily) -> dict:
        try:
            return self._hist_flow_kit_x(G, skip_gids, offc_ids, transit, rate_now, today_iso, daily)
        except Exception as e9:
            log.warning("장기 곡선 입출금 재료 실패: %s", e9)
            return None

    def _hist_flow_kit_x(self, G, skip_gids, offc_ids, transit, rate_now, today_iso, daily) -> dict:
        f0 = (datetime.strptime(today_iso, "%Y-%m-%d") - timedelta(days=len(daily) - 1)).strftime("%Y-%m-%d") if daily else None
        dpx9 = self.daily_px or {}
        return {
            "today": today_iso,
            "G": {gid: {"sym": g.get("sym"), "is_fiat": bool(g.get("is_fiat")), "is_stable": bool(g.get("is_stable"))} for gid, g in G.items()},
            "skip": frozenset(skip_gids or ()), "offc": frozenset(offc_ids or ()), "rate": rate_now,
            "transit": [dict(e9) for e9 in (transit or ()) if isinstance(e9, dict)],
            "wdt": {k9: {"wdt": dict(c9["wdt"])} for k9, c9 in (self.daily or {}).items()
                    if isinstance(c9, dict) and isinstance(c9.get("wdt"), dict)},
            "dpx_dc": {k9: {kk: (dict(vv) if isinstance(vv, dict) else vv) for kk, vv in v9.items() if kk in ("p", "fp", "lp")}
                       for k9, v9 in dpx9.items() if isinstance(v9, dict) and len(k9) == 10 and k9[4] == "-"
                       and k9 >= histcurve.FIRST_DAY and (f0 is None or k9 < f0)},
        }

    def _daily_flows(self, conn, daily, G, today_kst, live_px, skip_gids=frozenset(), rate_now=None, transit=None, offc_ids=frozenset(),
                     days=None, dpx=None, fx_day=None) -> dict:
        hist9 = days is not None
        if not hist9:
            self._venue_flow = None
            self._flow_px_delta = {}
            self._flow_nf = set()
        if not daily and not hist9:
            return {}
        keys = {}
        if hist9:
            keys = {str(d9): str(d9) for d9 in days}
            if not keys:
                return {}
        else:
            for i in range(29, -1, -1):
                d9 = today_kst - timedelta(days=i)
                keys[d9.strftime("%Y-%m-%d")] = d9.strftime("%m-%d")
        lo_ts = datetime.strptime(min(keys), "%Y-%m-%d").replace(tzinfo=KST).timestamp()
        vflow9 = {} if not hist9 else None
        dpx = (self.daily_px or {}) if dpx is None else dpx
        today_iso9 = today_kst.strftime("%Y-%m-%d")
        acc = {}
        gpx = {}
        gpxc = {}

        gsrc9 = {}
        held9 = {}
        held_ext9 = set()

        def hold9(ck9, sym9, gid9, lbl9, q9, is_ext9):
            h9 = held9.setdefault((ck9, str(sym9).upper()), {}).setdefault(gid9, {})
            h9[lbl9] = h9.get(lbl9, Decimal(0)) + q9
            if is_ext9:
                held_ext9.add(lbl9)
        nofx9 = {}

        def fpx9(ck9, gid9):
            e9 = dpx.get(ck9) or {}
            sid9 = str(gid9)
            cur9 = float((e9.get("p") or {}).get(sid9) or 0)
            gsrc9[(ck9, gid9)] = e9
            if not cur9 and ck9 < today_iso9:
                pk9 = (datetime.strptime(ck9, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
                cur9 = float(((dpx.get(pk9) or {}).get("p") or {}).get(sid9) or 0)
                if cur9:
                    e9 = dpx.get(pk9) or {}
                    gsrc9[(ck9, gid9)] = e9
            elif not cur9:
                cur9 = float(live_px.get(gid9) or 0)
            b9 = (e9.get("fp") or {}).get(sid9)
            return (float(b9) if b9 else cur9), cur9
        ext9 = set()
        sale_tx9 = getattr(self, "_sale_send_tx", None) or set()
        arr_tx9 = set()
        for w9 in (transit or ()):
            if not isinstance(w9, dict) or w9.get("state") != "arrived":
                continue
            t9 = str(w9.get("txid_raw") or "").strip() or (str(w9.get("txid") or "") if not str(w9.get("txid") or "").startswith("amt:") else "")
            if t9:
                arr_tx9.add(_txk(t9))
        acc_k = {}
        debts9 = StateBuilder._flow_debts()
        for ts9, qb9, dec9, gid9, ev9, lk9, ns9, rsym9, lseq9, sid9, loc9 in conn.execute(
                "SELECT p.event_ts, p.qty_base, a.decimals, COALESCE(a.group_id, -a.asset_id), p.event, p.leg_kind, p.source_ns, a.symbol,"
                " p.leg_seq, p.source_id, p.location"
                " FROM postings p JOIN assets a ON a.asset_id = p.asset_id WHERE p.event_ts >= ?"
                " AND p.location NOT LIKE 'out:%' AND p.location NOT LIKE 'lp:%'", (int(lo_ts),)):
            if ev9 in self.FLOW_SKIP_EV or lk9 in ("fee", "gas") or gid9 in skip_gids:
                continue
            if common.exf_is_debt_int(ev9, lseq9, ns9, sid9):
                continue
            g9 = G.get(gid9)
            if not g9 or g9.get("is_fiat"):
                continue
            ck9 = datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d")
            if ck9 not in keys:
                continue
            if g9.get("is_stable"):
                px9 = pxc9 = 1.0
            else:
                px9, pxc9 = fpx9(ck9, gid9)
            try:
                q9 = Decimal(int(qb9)) / (Decimal(10) ** int(dec9 if dec9 is not None else 18))
            except (TypeError, ValueError, InvalidOperation):
                continue
            sym9 = g9.get("sym") or "?"
            lbl9 = f"{self.FLOW_KO.get(ev9, ev9)} {sym9}"
            if ev9 == "TRANSFER_OUT" and str(sid9 or "").lower() in sale_tx9:
                lbl9 = f"세일 참가금 {sym9}"
            if offc_ids and (ns9, sid9) in offc_ids:
                lbl9 = f"{self.FLOW_OFFC_KO[0 if q9 < 0 else 1]} {sym9}"
            if ev9 == "EXF_ADJUST" and str(sid9 or "").startswith("exflate:"):
                lbl9 = f"{StateBuilder.FLOW_LATE_KO} {sym9}"
            elif ev9 in ("EXF_ADJUST", "EX_ADJUST") and q9 < 0:
                db9 = (debts9.get(ns9) or {}).get(str(rsym9 or "").upper())
                if db9 is not None and -db9 * Decimal("0.5") <= -q9 <= -db9 * Decimal("1.01") + EPS:
                    lbl9 = f"{StateBuilder.FLOW_DEBT_KO} {sym9}"
                    try:
                        if int(ts9) < int(str(sid9).rsplit(":", 1)[1]) - 60:
                            lbl9 = f"{StateBuilder.FLOW_DEBT_FIRST_KO} {sym9}"
                    except (IndexError, ValueError, TypeError):
                        pass
            if ev9 in ("TRANSFER_IN", "PROGRAM_IN") and arr_tx9 and _txk(str(sid9 or "")) in arr_tx9:
                lbl9 = f"{StateBuilder.FLOW_ARR_KO} {sym9}"
                is_ext9 = False
            else:
                is_ext9 = ev9 not in StateBuilder.FLOW_INT_EV
            if not px9:
                if ck9 < today_iso9:
                    hold9(ck9, sym9, gid9, lbl9, q9, is_ext9)
                continue
            if is_ext9:
                ext9.add(lbl9)
            a9 = acc.setdefault(ck9, {}).setdefault(sym9.upper(), {}).setdefault(gid9, {})
            a9[lbl9] = a9.get(lbl9, Decimal(0)) + q9
            gpx[(ck9, gid9)] = px9
            gpxc[(ck9, gid9)] = pxc9
            if vflow9 is not None and q9:
                vf9 = vflow9.setdefault(str(loc9 or ""), [0.0, 0.0])
                vf9[0 if q9 > 0 else 1] += abs(float(q9) * float(px9))
        if transit is not None:
            st9 = {str(e9["uuid"]): e9.get("state") for e9 in transit}
            now9 = {str(e9["uuid"]): [e9["gid"], float(e9["qty"])] for e9 in transit if e9.get("state") == "pending"}
            tiso9 = today_kst.strftime("%Y-%m-%d")

            def wset9(ck9):
                if ck9 == tiso9:
                    return now9
                c9 = (getattr(self, "daily", None) or {}).get(ck9)
                w9 = c9.get("wdt") if isinstance(c9, dict) else None
                return w9 if isinstance(w9, dict) else {}
            for ck9 in sorted(keys):
                pk9 = (datetime.strptime(ck9, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
                cur9, prv9 = wset9(ck9), wset9(pk9)
                for u9, v9, sg9 in [(u9, v9, 1) for u9, v9 in cur9.items() if u9 not in prv9] + \
                                   [(u9, v9, -1) for u9, v9 in prv9.items() if u9 not in cur9]:
                    try:
                        gid9, q9 = int(v9[0]), Decimal(str(v9[1])) * sg9
                    except (TypeError, ValueError, IndexError, InvalidOperation):
                        continue
                    g9 = G.get(gid9)
                    if not g9 or g9.get("is_fiat") or gid9 in skip_gids:
                        continue
                    px9, pxc9 = (1.0, 1.0) if g9.get("is_stable") else fpx9(ck9, gid9)
                    sym9 = g9.get("sym") or "?"
                    if not px9:
                        if ck9 < today_iso9:
                            out9 = sg9 < 0 and st9.get(u9) == "out"
                            hold9(ck9, sym9, gid9, f"{self.FLOW_KO.get('EXF_WITHDRAW', '거래소 출금')} {sym9} · 도착 없음" if out9 else f"전송 중 {sym9}", q9, out9)
                        continue
                    if sg9 < 0 and st9.get(u9) == "out":
                        lbl9 = f"{self.FLOW_KO.get('EXF_WITHDRAW', '거래소 출금')} {sym9} · 도착 없음"
                        ext9.add(lbl9)
                    else:
                        lbl9 = f"전송 중 {sym9}"
                    a9 = acc.setdefault(ck9, {}).setdefault(sym9.upper(), {}).setdefault(gid9, {})
                    a9[lbl9] = a9.get(lbl9, Decimal(0)) + q9
                    gpx.setdefault((ck9, gid9), px9)
                    gpxc.setdefault((ck9, gid9), pxc9)

        for (ck9, su9), gh9 in sorted(held9.items()):
            gm9 = (acc.get(ck9) or {}).get(su9) or {}
            if not gm9:
                continue
            s_h9 = sum((v9 for lv9 in gh9.values() for v9 in lv9.values()), Decimal(0))
            s_p9 = sum((v9 for lv9 in gm9.values() for v9 in lv9.values()), Decimal(0))
            if not s_h9 or not s_p9 or (s_h9 > 0) == (s_p9 > 0):
                continue
            fr9 = min(Decimal(1), abs(s_p9) / abs(s_h9))
            net9 = {g0: sum(lv9.values(), Decimal(0)) for g0, lv9 in gm9.items()}
            ref9g = max((g0 for g0 in gm9 if net9[g0] * s_p9 > 0), key=lambda g0: (abs(net9[g0]), -g0))
            for gid9, lv9 in gh9.items():
                a9 = acc[ck9][su9].setdefault(gid9, {})
                for l9, q9 in lv9.items():
                    a9[l9] = a9.get(l9, Decimal(0)) + q9 * fr9
                    if l9 in held_ext9:
                        ext9.add(l9)
                gpx[(ck9, gid9)] = gpx[(ck9, ref9g)]
                gpxc[(ck9, gid9)] = gpxc[(ck9, ref9g)]
                gsrc9[(ck9, gid9)] = {}

        def add(ck9, grp9, lbl9, usd9):
            if ck9 not in keys:
                return
            a9 = acc_k.setdefault(ck9, {}).setdefault(grp9, {})
            a9[lbl9] = a9.get(lbl9, 0.0) + usd9
        try:
            for ex9, ts9, k9, int9 in StateBuilder._krw_bank_moves(conn, ("upbit",) if hist9 else ("upbit", "bithumb")):
                up9 = ex9 == "upbit"
                if ts9 < lo_ts:
                    continue
                if fx_day is not None:
                    if datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d") not in keys:
                        continue
                    d9 = datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d")
                    fx9 = float(fx_day(d9) or 0)
                    if not fx9 > 0:
                        nofx9[d9] = nofx9.get(d9, 0.0) + k9
                        continue
                else:
                    fxr9 = self.px.fx_at(int(ts9 * 1000))
                    if not fxr9:
                        _px_took(self.px)
                        self._flow_nf.add(datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d"))
                    fx9 = float(fxr9 or rate_now or self.spot.rate or 1384)
                if up9:
                    add(datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d"), "krw:" + ("int" if int9 else "in" if k9 > 0 else "out"),
                        "업비트 원화 지급(예치금 이용료 등·은행 아님)" if int9 else "원화 입금(은행에서)" if k9 > 0 else "원화 출금(은행으로)", k9 / fx9)
                else:
                    add(datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d"), f"krw:{ex9}:" + ("int" if int9 else "in" if k9 > 0 else "out"),
                        "빗썸 원화 지급(거래소 내부·은행 아님)" if int9 else "빗썸 원화 입금(은행에서)" if k9 > 0 else "빗썸 원화 출금(은행으로)", k9 / fx9)
                if vflow9 is not None and k9 and datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d") in keys:
                    vf9 = vflow9.setdefault(f"exchange:{ex9}", [0.0, 0.0])
                    vf9[0 if k9 > 0 else 1] += abs(k9 / fx9)
        except Exception as e9:
            if hist9:
                raise
            vflow9 = None
            log.warning("일별 순유입: 원화 입출금(업비트·빗썸) 조회 실패: %s", e9)
        def bands9(ck9, gm9, bases9):
            par9 = {g0: g0 for g0 in gm9}

            def root9(g0):
                while par9[g0] != g0:
                    par9[g0] = par9[par9[g0]]
                    g0 = par9[g0]
                return g0
            for pm9 in bases9:
                cl9 = []
                for gid9 in sorted((g0 for g0 in gm9 if pm9(g0) > 0), key=lambda g0: (pm9(g0), g0)):
                    if cl9 and pm9(gid9) <= cl9[-1][0] * 1.2:
                        cl9[-1][1].append(gid9)
                    else:
                        cl9.append([pm9(gid9), [gid9]])
                for _p9, gs9 in cl9:
                    for g0 in gs9[1:]:
                        par9[root9(g0)] = root9(gs9[0])
            out9 = {}
            for g0 in sorted(gm9):
                out9.setdefault(root9(g0), []).append(g0)
            return list(out9.values())

        def ref9(gm9, gs9):
            return max(gs9, key=lambda g0: (sum(abs(v) for v in gm9[g0].values()), -g0))
        out = {}
        fpd9 = {}
        if not hist9:
            self._flow_px_delta = fpd9
        for ck9 in sorted(set(acc) | set(acc_k)):
            tot9 = 0.0
            top9 = []
            dlt9 = 0.0
            for sym9, gm9 in (acc.get(ck9) or {}).items():
                e_ck9 = dpx.get(ck9) or {}

                def lp9(g0, ck9=ck9, e_ck9=e_ck9):
                    src9 = gsrc9.get((ck9, g0), e_ck9)
                    lpm9 = src9.get("lp") if isinstance(src9.get("lp"), dict) else {}
                    return float(lpm9.get(str(g0)) or gpx[(ck9, g0)])
                cl_d9 = bands9(ck9, gm9, (lambda g0: gpx[(ck9, g0)],))
                has_int9 = [any(l9 not in ext9 and v9 for g0 in gs9 for l9, v9 in gm9[g0].items()) for gs9 in cl_d9]
                sup9 = list(range(len(cl_d9)))
                if sum(has_int9) >= 2:
                    of9 = {g0: i9 for i9, gs9 in enumerate(cl_d9) for g0 in gs9}

                    def sroot9(i9):
                        while sup9[i9] != i9:
                            sup9[i9] = sup9[sup9[i9]]
                            i9 = sup9[i9]
                        return i9
                    int_gm9 = {g0: gm9[g0] for g0 in gm9 if any(l9 not in ext9 and v9 for l9, v9 in gm9[g0].items())}
                    for gs9 in bands9(ck9, int_gm9, (lambda g0: gpxc[(ck9, g0)], lp9)):
                        ids9 = sorted({of9[g0] for g0 in gs9 if has_int9[of9[g0]]})
                        for i9 in ids9[1:]:
                            sup9[sroot9(i9)] = sroot9(ids9[0])
                    sup9 = [sroot9(i9) for i9 in range(len(cl_d9))]
                cur9 = 0.0
                for gs9 in bands9(ck9, gm9, (lambda g0: gpxc[(ck9, g0)],)):
                    cur9 += float(sum((v for g0 in gs9 for v in gm9[g0].values()), Decimal(0))) * gpxc[(ck9, ref9(gm9, gs9))]
                shown9 = 0.0
                for r9 in sorted(set(sup9)):
                    mem9 = [i9 for i9 in range(len(cl_d9)) if sup9[i9] == r9]
                    allg9 = [g0 for i9 in mem9 for g0 in cl_d9[i9]]
                    pi9 = gpx[(ck9, ref9(gm9, allg9))]
                    lv9 = {}
                    for i9 in mem9:
                        pe9 = gpx[(ck9, ref9(gm9, cl_d9[i9]))]
                        for g0 in cl_d9[i9]:
                            for l9, v9 in gm9[g0].items():
                                px9 = pe9 if (len(mem9) == 1 or l9 in ext9) else pi9
                                lv9[l9] = lv9.get(l9, 0.0) + float(v9) * px9
                    if len(mem9) == 1:
                        gs9 = cl_d9[mem9[0]]
                        n9 = float(sum((v for g0 in gs9 for v in gm9[g0].values()), Decimal(0))) * gpx[(ck9, ref9(gm9, gs9))]
                    else:
                        n9 = sum(lv9.values())
                    tot9 += n9
                    shown9 += n9
                    if abs(n9) >= 1:
                        ex9 = [kv for kv in lv9.items() if kv[0] in ext9 and kv[1] * n9 > 0]
                        pick9 = min(ex9 or lv9.items(), key=lambda kv: (abs(kv[1] - n9), -abs(kv[1]), kv[0]))[0]
                        top9.append((pick9, n9))
                dlt9 += cur9 - shown9
            for g9 in (acc_k.get(ck9) or {}).values():
                n9 = sum(g9.values())
                tot9 += n9
                if abs(n9) >= 1:
                    top9.append((next(iter(g9)), n9))
            top9.sort(key=lambda kv: -abs(kv[1]))
            out[keys[ck9]] = (round(tot9, 2), [[k, round(v, 2)] for k, v in top9[:3]])
            if abs(dlt9) >= 0.005:
                fpd9[keys[ck9]] = round(dlt9, 2)
        if hist9 and nofx9:
            out["_nofx"] = {d9: round(v9, 2) for d9, v9 in nofx9.items()}
        if vflow9 is not None:
            self._venue_flow = vflow9
        return out

    ATT_TOP = 5
    ATT_TRADE_EV = frozenset(("SWAP", "CONVERT", "EXF_BUY", "EXF_SELL", "EX_BUY", "EX_SELL", "NOOP", "FAILED"))
    ATT_LP_EV = frozenset(("LP_ADD", "LP_REMOVE", "LP_ADJUST"))
    ATT_V = 2
    ATT_BAND = 1.2
    ATT_NOPX_BAND = (0.5, 2.0)

    def _daily_attrib(self, conn, daily, G, today_kst, live_px, skip_gids=frozenset(), extra=None, real=None, px_src=None) -> dict:
        src = getattr(self, "_daily_att_src", None) or {}
        by_today = {}
        try:
            self._att_by_today = by_today
        except Exception:
            pass
        if len(daily) < 2 or not src:
            return {}
        extra = extra or {}
        keys = {}
        for i in range(29, -1, -1):
            d9 = today_kst - timedelta(days=i)
            keys[d9.strftime("%m-%d")] = d9.strftime("%Y-%m-%d")
        ck_set = set(keys.values())
        today_ck = today_kst.strftime("%Y-%m-%d")
        skip9s = {str(x) for x in (skip_gids or ())}
        rate_now = float(extra.get("rate") or self.spot.rate or 1384)
        dpx = self.daily_px or {}

        def day_ts(ck9):
            d9 = datetime.strptime(ck9, "%Y-%m-%d").replace(tzinfo=KST)
            return d9.timestamp(), d9.replace(hour=23, minute=59, second=59).timestamp()

        legs = {}
        mv9 = {}
        lo_ts = day_ts(min(ck_set))[0]
        dbi9 = {}
        sql9 = ("SELECT p.event_ts, p.qty_base, a.decimals, COALESCE(a.group_id, -a.asset_id), p.event, p.leg_kind, p.location{}"
                " FROM postings p JOIN assets a ON a.asset_id = p.asset_id WHERE p.event_ts >= ?"
                " AND p.location NOT LIKE 'out:%'")
        try:
            rows9 = conn.execute(sql9.format(", p.leg_seq, p.source_ns, p.source_id"), (int(lo_ts),)).fetchall()
        except Exception as e9:
            if "no such column" not in str(e9):
                raise
            rows9 = [tuple(r9) + (None, None, None) for r9 in conn.execute(sql9.format(""), (int(lo_ts),))]
        krwf9 = {}
        for ts9, qb9, dec9, gid9, ev9, lk9, loc9, lseq9, ns9, sid9 in rows9:
            if gid9 in skip_gids:
                continue
            g9 = G.get(gid9)
            if g9 and g9.get("is_fiat"):
                loc9s = str(loc9 or "")
                if (loc9s.startswith("exchange:") and not loc9s.startswith("exchange:upbit")
                        and (lk9 in ("fee", "gas") or ev9 in self.ATT_TRADE_EV)):
                    ck9 = datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d")
                    if ck9 in ck_set:
                        try:
                            krwf9[ck9] = krwf9.get(ck9, Decimal(0)) + Decimal(int(qb9)) / (Decimal(10) ** int(dec9 if dec9 is not None else 8))
                        except (TypeError, ValueError, InvalidOperation):
                            pass
                continue
            if not g9:
                continue
            is_lp9 = str(loc9 or "").startswith("lp:")
            int9 = common.exf_is_debt_int(ev9, lseq9, ns9, sid9)
            if lk9 in ("fee", "gas") or int9:
                slot9 = 1
            elif ev9 in self.ATT_TRADE_EV:
                slot9 = 0
            elif ev9 in self.ATT_LP_EV:
                slot9 = 2
            else:
                slot9 = None
            if slot9 is None and (is_lp9 or ev9 in StateBuilder.FLOW_SKIP_EV):
                continue
            ck9 = datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d")
            if ck9 not in ck_set:
                continue
            try:
                q9 = Decimal(int(qb9)) / (Decimal(10) ** int(dec9 if dec9 is not None else 18))
            except (TypeError, ValueError, InvalidOperation):
                continue
            if slot9 is None:
                m9 = mv9.setdefault(ck9, {}).setdefault(gid9, {})
                m9[ev9] = m9.get(ev9, Decimal(0)) + q9
                continue
            if is_lp9:
                slot9 = 3
            legs.setdefault(ck9, {}).setdefault(gid9, [Decimal(0), Decimal(0), Decimal(0), Decimal(0)])[slot9] += q9
            if int9:
                d9 = dbi9.setdefault(ck9, {})
                d9[gid9] = d9.get(gid9, Decimal(0)) + q9
        tl9 = extra.get("krw_up_tl")
        if tl9 is None and callable(getattr(self, "_upbit_krw_timeline", None)):
            tl9 = self._upbit_krw_timeline(conn)
        tc9 = getattr(self, "_upbit_krw_tl", None)
        tlo_ok9 = tl9 is not None and isinstance(tc9, tuple) and len(tc9) > 2 and tc9[1] is tl9
        tlo9 = tc9[2] if tlo_ok9 else []
        try:
            krwb9 = [(t9, k9) for _e9, t9, k9, _i9 in StateBuilder._krw_bank_moves(conn, ("bithumb",))]
        except Exception as e9:
            log.debug("자산 변동 분해: 빗썸 원화 입출금 조회 실패(종전대로): %s", e9)
            krwb9 = []
        krw_up_now = float(extra.get("krw_up") or 0)
        krw_other_now = float(extra.get("krw_other") or 0)
        has_krw9 = "krw_up" in extra

        def krw_at(end9):
            if tl9 is None:
                return krw_up_now + krw_other_now
            k9 = Decimal(str(krw_up_now)) - sum((d9 for t9, d9 in tl9 if t9 > end9), Decimal(0))
            return (float(max(k9, Decimal(0))) if k9 >= Decimal(-1000) else krw_up_now) + krw_other_now

        def krw_sum(lst9, ck9):
            a9, b9 = day_ts(ck9)
            return float(sum((d9 for t9, d9 in lst9 if a9 <= t9 <= b9), Decimal(0)))

        def rate_of(row9):
            if keys.get(row9.get("date")) == today_ck:
                return rate_now
            u9 = row9.get("usdt")
            return float(u9) if u9 else None

        def gsum(g9):
            return sum(float(v9) for k9, v9 in (g9 or {}).items() if k9 not in skip9s)

        def xu_px(xu9):
            out9 = {}
            for s9, a9 in (xu9.items() if isinstance(xu9, dict) else ()):
                try:
                    q9, u9 = float(a9[0]), float(a9[1])
                except (TypeError, ValueError, IndexError, KeyError):
                    continue
                if q9 > 0 and u9 >= 0:
                    out9[str(s9).upper()] = (q9, u9 / q9)
            return out9

        def fnum(v9):
            try:
                return float(v9) if v9 is not None else 0.0
            except (TypeError, ValueError):
                return 0.0

        real = real if isinstance(real, dict) else None
        out = {}
        for i9 in range(1, len(daily)):
            rd, rp9 = daily[i9], daily[i9 - 1]
            ckd, ckp = keys.get(rd.get("date")), keys.get(rp9.get("date"))
            sd, sp = src.get(ckd), src.get(ckp)
            if not sd or not sp or not isinstance(sd[0], dict) or not isinstance(sp[0], dict):
                continue
            gd, pdx = sd[0], sd[1] or {}
            gp, ppx = sp[0], sp[1] or {}
            ud, up9 = rate_of(rd), rate_of(rp9)
            is_today9 = ckd == today_ck
            by9, base9 = {}, {}
            det9 = {}

            def moved9(gid9, ck9=ckd):
                return gid9 in (legs.get(ck9) or {}) or gid9 in (mv9.get(ck9) or {})
            unp_n, unp_v = 0, 0.0
            for sid9, vp9 in gp.items():
                if sid9 in skip9s:
                    continue
                try:
                    g9 = G.get(int(sid9))
                except ValueError:
                    g9 = None
                if not g9 or g9.get("is_stable"):
                    continue
                vp9 = float(vp9)
                pa9, pb9 = ppx.get(sid9), pdx.get(sid9)
                if pa9 and pb9 and vp9:
                    sym9 = str(g9.get("sym") or "?").upper()
                    by9[sym9] = by9.get(sym9, 0.0) + vp9 * (float(pb9) / float(pa9) - 1)
                    base9[sym9] = base9.get(sym9, 0.0) + vp9
                    det9.setdefault(sym9, []).append((sid9, vp9, float(pa9), float(pb9)))
                    if is_today9:
                        by_today[sid9] = (vp9 * (float(pb9) / float(pa9) - 1), vp9)
                elif vp9 and sid9 in gd and abs(float(gd[sid9]) - vp9) >= 0.005:
                    unp_n += 1
                    unp_v += float(gd[sid9]) - vp9
                elif vp9 >= 0.005 and pa9 and not pb9 and sid9 not in gd and not moved9(int(sid9)):
                    unp_n += 1
                    unp_v -= vp9
            for sid9, vd9 in gd.items():
                if sid9 in gp or sid9 in skip9s:
                    continue
                try:
                    g9 = G.get(int(sid9))
                except ValueError:
                    continue
                if (g9 and not g9.get("is_stable") and float(vd9) >= 0.005 and pdx.get(sid9) and not ppx.get(sid9)
                        and not moved9(int(sid9))):
                    unp_n += 1
                    unp_v += float(vd9)
            kx = 0.0
            if has_krw9 and ud and up9 and ud != up9:
                kx = krw_at(day_ts(ckp)[1]) * (1 / ud - 1 / up9)
            kx0 = kx
            fxat9 = getattr(getattr(self, "px", None), "fx_at", None)
            if tlo_ok9 and ud and callable(fxat9):
                a9, b9 = day_ts(ckd)
                o9 = {}
                for t9, d9 in tlo9:
                    if a9 <= t9 <= b9:
                        o9[(t9, d9)] = o9.get((t9, d9), 0) + 1
                for t9, d9 in tl9:
                    if not (a9 <= t9 <= b9):
                        continue
                    if o9.get((t9, d9)):
                        o9[(t9, d9)] -= 1
                        continue
                    fx9 = float(fxat9(int(t9 * 1000)) or rate_now or 1384)
                    kx += float(d9) * (1 / ud - 1 / fx9)
            if has_krw9 and krwb9 and ud and callable(fxat9):
                a9, b9 = day_ts(ckd)
                for t9, d9 in krwb9:
                    if a9 <= t9 <= b9:
                        fx9 = float(fxat9(int(t9 * 1000)) or rate_now or 1384)
                        kx += float(d9) * (1 / ud - 1 / fx9)
            mk = sum(by9.values()) + kx
            dfx9 = (dpx.get(ckd) or {}).get("p") or {}
            lg9 = legs.get(ckd) or {}
            mvd9 = mv9.get(ckd) or {}
            own9 = {}
            cand9 = {}
            gids9 = set(lg9)
            for s9 in set(gd) | set(gp):
                try:
                    gids9.add(int(s9))
                except ValueError:
                    continue
            for gid9 in gids9:
                g9 = G.get(gid9) or {}
                sid9 = str(gid9)
                if g9.get("is_stable") or g9.get("is_fiat") or sid9 in skip9s or not g9:
                    continue
                p9 = fnum(pdx.get(sid9)) or fnum(ppx.get(sid9)) or fnum(dfx9.get(sid9))
                if not p9 and is_today9:
                    p9 = fnum(live_px.get(gid9))
                if p9 > 0:
                    own9[gid9] = p9
                elif gid9 in lg9 and fnum(live_px.get(gid9)) > 0:
                    cand9[gid9] = fnum(live_px.get(gid9))

            def wt9(gid9):
                m9 = mvd9.get(gid9) or {}
                l9 = lg9.get(gid9) or ()
                return (float(sum((abs(v9) for v9 in m9.values()), Decimal(0))), float(sum((abs(v9) for v9 in l9), Decimal(0))),
                        abs(fnum(gd.get(str(gid9)))) + abs(fnum(gp.get(str(gid9)))), -gid9)
            by_sym9 = {}
            for gid9, p9 in own9.items():
                by_sym9.setdefault(str((G.get(gid9) or {}).get("sym") or "?").upper(), []).append(gid9)
            leg_px9 = {}
            bands9 = {}
            for sym9, gs9 in by_sym9.items():
                cl9 = []
                for gid9 in sorted(gs9, key=lambda g0: (own9[g0], g0)):
                    if cl9 and own9[gid9] <= cl9[-1][0] * StateBuilder.ATT_BAND:
                        cl9[-1][1].append(gid9)
                    else:
                        cl9.append([own9[gid9], [gid9]])
                for _p9, gs0 in cl9:
                    ref9 = max(gs0, key=wt9)
                    for gid9 in gs0:
                        leg_px9[gid9] = own9[ref9]
                bands9[sym9] = [(own9[max(gs0, key=wt9)], gs0) for _p9, gs0 in cl9]
            lo9, hi9 = StateBuilder.ATT_NOPX_BAND
            for gid9, lv9 in cand9.items():
                sym9 = str((G.get(gid9) or {}).get("sym") or "?").upper()
                fit9 = [bp9 for bp9, _g in bands9.get(sym9) or () if lo9 <= lv9 / bp9 <= hi9]
                if fit9:
                    leg_px9[gid9] = min(fit9, key=lambda bp9: abs(lv9 / bp9 - 1))
            gx = 0.0
            for gid9, p9 in own9.items():
                lp9 = leg_px9.get(gid9)
                if not lp9 or abs(lp9 - p9) <= 1e-15 * max(p9, 1.0):
                    continue
                sid9 = str(gid9)
                gdv9, gpv9 = fnum(gd.get(sid9)), fnum(gp.get(sid9))
                pd9, pp9 = fnum(pdx.get(sid9)), fnum(ppx.get(sid9))
                if gdv9 and gpv9:
                    if not (pd9 and pp9):
                        continue
                    b9, po9 = gdv9 - gpv9 * pd9 / pp9, pd9
                elif gdv9:
                    if not pd9:
                        continue
                    b9, po9 = gdv9, pd9
                elif gpv9:
                    if not pp9:
                        continue
                    b9, po9 = -gpv9, pp9
                else:
                    continue
                gx += b9 * (1 - lp9 / po9)
            tr = fee = lpv = tall = 0.0
            np9 = 0
            for gid9, (qt9, qf9, ql9, qx9) in lg9.items():
                g9 = G.get(gid9) or {}
                px9 = 1.0 if g9.get("is_stable") else leg_px9.get(gid9, 0.0)
                if not px9:
                    if qt9 or qf9 or ql9 or qx9:
                        np9 += 1
                    continue
                tr += float(qt9 + qf9) * px9
                fee += float(qf9) * px9
                lpv += float(ql9) * px9
                tall += float(qt9 + qf9 + ql9 + qx9) * px9
            ord9 = dep9 = 0.0
            if tl9 is not None and ud:
                ord9 = krw_sum(tlo9, ckd) / ud
                dep9 = krw_sum(tl9, ckd) / ud - ord9
            ordb9 = depb9 = 0.0
            if ud:
                ordb9 = float(krwf9.get(ckd) or 0) / ud
                lob9, hib9 = day_ts(ckd)
                depb9 = sum(k9 for t9, k9 in krwb9 if lob9 <= t9 <= hib9) / ud
            tr += ord9 + ordb9
            tall += ord9 + ordb9
            dv = float(rd.get("val") or 0) - float(rp9.get("val") or 0)
            fl = float(rd.get("flow") or 0)
            rs = dv - mk - fl - tr
            dx = (float(rd.get("val") or 0) - gsum(gd)) - (float(rp9.get("val") or 0) - gsum(gp))
            xo = dx - ord9 - dep9 - ordb9 - depb9 - kx0
            mv = sorted(((s9, v9) for s9, v9 in by9.items() if abs(v9) >= 0.005), key=lambda kv: (-abs(kv[1]), kv[0]))
            top = [[s9, round(v9 / base9[s9] * 100, 2) if base9.get(s9) else None, round(v9, 2)] for s9, v9 in mv[:self.ATT_TOP]]
            rest9 = mv[self.ATT_TOP:]
            a9 = {"mk": round(mk, 2), "top": top, "etc": [len(rest9), round(sum(v9 for _s, v9 in rest9), 2)],
                  "kx": round(kx, 2), "tr": round(tr, 2), "fee": round(fee, 2), "lp": round(lpv, 2), "xo": round(xo, 2), "rs": round(rs, 2)}
            if unp_n:
                a9["unp"] = [unp_n, round(unp_v, 2)]
            if top and det9:
                try:
                    tx9 = self._att_topx(top, det9, ckd, ckp, dpx, today_ck, src, px_src)
                except Exception as ex9:
                    log.debug("자산 변동 분해 코인별 재료(topx) 실패 %s: %s", ckd, ex9)
                    tx9 = None
                if tx9:
                    a9["topx"] = tx9
            if real is not None:
                xp9, xd9 = xu_px(sp[2] if len(sp) > 2 else None), xu_px(sd[2] if len(sd) > 2 else None)
                xm = sum(q9 * (xd9[s9][1] - pu9) for s9, (q9, pu9) in xp9.items() if s9 in xd9)
                rbd9 = fnum((real.get("rbd") or {}).get(ckd))
                lpf = fnum((real.get("lpf") or {}).get(ckd))
                stk = fnum((real.get("stk") or {}).get(ckd))
                rz = rbd9 - lpf - stk
                un = 0.0
                for gid9, (uq9, upr9) in ((real.get("unv") or {}).get(ckd) or {}).items():
                    if gid9 in skip_gids:
                        continue
                    g9 = G.get(gid9) or {}
                    un += float(upr9) - float(uq9) * (1.0 if g9.get("is_stable") else leg_px9.get(gid9, 0.0))
                ur = tall + gx - rz - lpf - un
                mkc = mk - kx
                fpx9 = float((getattr(self, "_flow_px_delta", None) or {}).get(rd.get("date")) or 0)
                ev9 = mkc + xm + ur + fpx9
                rest = dv - (ev9 + rz + lpf + fl + kx + un)
                a9.update({"v": StateBuilder.ATT_V, "ev": round(ev9, 2), "xm": round(xm, 2), "ur": round(ur, 2), "rz": round(rz, 2),
                           "lpf": round(lpf, 2), "stk": round(stk, 2), "un": round(un, 2), "gx": round(gx, 2), "rest": round(rest, 2)})
                if fpx9:
                    a9["fpx"] = round(fpx9, 2)
                if np9:
                    a9["np"] = np9
                rbd9, rbp9 = fnum(rd.get("rb")), fnum(rp9.get("rb"))
                rbv9 = (rbd9 - rbp9) - fnum(rd.get("rbNew"))
                xr9 = xo - xm - (rbd9 - rbp9)
                if abs(xr9) >= 0.005:
                    a9["xr"] = round(xr9, 2)
                    if fnum(rd.get("xc")) >= 1 or fnum(rp9.get("xc")) >= 1:
                        a9["xca"] = 1
                if abs(rbv9) >= 0.005:
                    a9["rbv"] = round(rbv9, 2)
                dbv9 = sum(float(q9) * (1.0 if (G.get(gid9) or {}).get("is_stable") else leg_px9.get(gid9, 0.0))
                           for gid9, q9 in (dbi9.get(ckd) or {}).items())
                if abs(dbv9) >= 0.005:
                    a9["dbi"] = round(dbv9, 2)
            out[rd.get("date")] = a9
        return out

    ATT_SPIKE = 3.0
    ATT_TOPX_GS = 6

    def _att_topx(self, top, det, ckd, ckp, dpx, today_ck, src, px_src=None) -> list:
        X = float(self.ATT_SPIKE)

        def px_of(ck9):
            e9 = src.get(ck9)
            p9 = e9[1] if isinstance(e9, (tuple, list)) and len(e9) > 1 else None
            return p9 if isinstance(p9, dict) else {}

        def shift(ck9, n9):
            return (datetime.strptime(ck9, "%Y-%m-%d") + timedelta(days=n9)).strftime("%Y-%m-%d")
        pn9, pq9 = px_of(shift(ckd, 1)), px_of(shift(ckp, -1))

        def kind(ck9, sid9, p9):
            if ck9 == today_ck:
                return "live"
            e9 = dpx.get(ck9) if isinstance(dpx, dict) else None
            if not isinstance(e9, dict):
                return None
            try:
                f9 = float((e9.get("p") or {}).get(sid9) or 0)
            except (TypeError, ValueError):
                return None
            if not f9 or abs(f9 - p9) > 1e-9 * abs(p9):
                return None
            return str((e9.get("k") or {}).get(sid9) or "now")
        memo9 = {}

        def src_of(ck9, sid9, k9):
            if k9 != "d" or px_src is None:
                return None
            if (ck9, sid9) not in memo9:
                try:
                    memo9[(ck9, sid9)] = self._att_dc_src(px_src(int(sid9)), ck9)
                except Exception:
                    memo9[(ck9, sid9)] = None
            return memo9[(ck9, sid9)]

        def off(a9, b9):
            try:
                a9, b9 = float(a9 or 0), float(b9 or 0)
            except (TypeError, ValueError):
                return None
            if a9 <= 0 or b9 <= 0:
                return None
            r9 = a9 / b9
            return r9 if (r9 > X or r9 < 1.0 / X) else None
        out = []
        for s9, pct9, usd9 in top:
            gs9 = det.get(s9) or ()
            rows9 = []
            for sid9, vp9, p0, p1 in gs9:
                q9 = vp9 / p0
                r9 = {"q": q9, "p0": p0, "p1": p1, "usd": vp9 * (p1 / p0 - 1), "vp": vp9, "k": kind(ckd, sid9, p1), "k0": kind(ckp, sid9, p0)}
                r9["src"] = src_of(ckd, sid9, r9["k"])
                s0 = src_of(ckp, sid9, r9["k0"])
                if s0 and s0 != r9["src"]:
                    r9["src0"] = s0
                for fr9, x9 in (("day", off(p1, p0)), ("next", off(p1, pn9.get(sid9))), ("prev", off(p0, pq9.get(sid9)))):
                    if x9:
                        r9.update(flag="spike", fr=fr9, rx=round(x9, 4))
                        break
                rows9.append(r9)
            if not rows9:
                continue
            q_all = sum(r9["q"] for r9 in rows9)
            if not q_all:
                continue
            rows9.sort(key=lambda r0: -abs(r0["usd"]))
            dom9 = rows9[0]
            fl9 = [r9 for r9 in rows9 if r9.get("flag")]
            it9 = {"sym": s9, "q": q_all, "p0": sum(r9["vp"] for r9 in rows9) / q_all, "p1": sum(r9["q"] * r9["p1"] for r9 in rows9) / q_all,
                   "pct": pct9, "usd": usd9,
                   "k": dom9["k"] if all(r9["k"] == dom9["k"] for r9 in rows9) else "mix",
                   "k0": dom9["k0"] if all(r9["k0"] == dom9["k0"] for r9 in rows9) else "mix",
                   "src": dom9["src"]}
            if dom9.get("src0"):
                it9["src0"] = dom9["src0"]
            if fl9:
                it9.update(flag="spike", fr=fl9[0]["fr"], rx=fl9[0]["rx"])
            if len(rows9) > 1:
                it9["gn"] = len(rows9)
                it9["gs"] = [{k9: (round(v9, 6) if k9 == "usd" else v9) for k9, v9 in r9.items() if k9 != "vp" and v9 is not None}
                             for r9 in rows9[:self.ATT_TOPX_GS]]
            out.append(it9)
        return out

    @staticmethod
    def _att_dc_src(spec, iso):
        if not spec or spec in ("stable", "ov"):
            return None
        dc9 = getattr(histcurve, "DAYCLOSE", None)
        if dc9 is None:
            return None
        for e9 in dc9._sources(spec):
            if dc9.covers(e9, iso) and (dc9._ffp(e9).get(iso) or 0) > 0:
                s9 = e9.get("src")
                if isinstance(s9, (list, tuple)):
                    s9 = " · ".join(str(x9) for x9 in s9[:3] if x9)
                return str(s9)[:80] if s9 else None
        return None

    @staticmethod
    def _hold_today(coins, G, live_px, today_kst, dpx, by_today):
        TWIN_X = 1.5
        by_today = by_today if isinstance(by_today, dict) else {}
        rows9 = {}
        for c9 in coins or ():
            if not isinstance(c9, dict) or c9.get("symSrc"):
                continue
            try:
                q9, p9 = float(c9.get("qty") or 0), float(c9.get("price") or 0)
            except (TypeError, ValueError):
                continue
            if not (q9 > 0 and p9 > 0):
                continue
            k9 = str(c9.get("key") or "")
            gid9 = int(k9[1:]) if k9.startswith("g") and k9[1:].isdigit() else None
            if gid9 is not None:
                g9 = (G or {}).get(gid9) or {}
                if not g9 or g9.get("is_stable") or g9.get("is_fiat"):
                    continue
            rows9.setdefault(str(c9.get("sym") or "?").upper(), []).append((q9 * p9, p9, gid9))
        main9, mem9 = {}, {}
        for s9, rs9 in rows9.items():
            rs9.sort(key=lambda r9: -r9[0])
            p0 = rs9[0][1]
            band9 = [r9 for r9 in rs9 if r9[2] is not None and p0 / TWIN_X <= r9[1] <= p0 * TWIN_X]
            if band9:
                main9[s9] = band9[0][2]
                mem9[s9] = {str(r9[2]) for r9 in band9}
        today9 = {}
        for s9, m9 in mem9.items():
            v9 = b9 = 0.0
            hit9 = False
            for sid9, e9 in by_today.items():
                if sid9 in m9 and isinstance(e9, (list, tuple)) and len(e9) >= 2:
                    v9 += float(e9[0])
                    b9 += float(e9[1])
                    hit9 = True
            if hit9:
                today9[s9] = [round(v9 / b9 * 100, 2) if b9 else None, round(v9, 2)]

        def fpos(v9):
            try:
                v9 = float(v9)
            except (TypeError, ValueError):
                return None
            return float(f"{v9:.8g}") if v9 > 0 and v9 == v9 and v9 != float("inf") else None

        days9 = [(today_kst - timedelta(days=i9)).strftime("%Y-%m-%d") for i9 in range(6, 0, -1)]
        spark9 = {}
        for s9, gid9 in main9.items():
            sid9 = str(gid9)
            pts9 = []
            for ck9 in days9:
                e9 = (dpx or {}).get(ck9)
                e9 = e9 if isinstance(e9, dict) else {}
                p9 = (e9.get("p") or {}).get(sid9) if isinstance(e9.get("p"), dict) else None
                if p9 is None:
                    part9 = e9.get("partial")
                    if isinstance(part9, dict) and isinstance(part9.get("p"), dict):
                        p9 = part9["p"].get(sid9)
                pts9.append(fpos(p9))
            pts9.append(fpos((live_px or {}).get(gid9)))
            if sum(1 for p9 in pts9 if p9 is not None) >= 2:
                spark9[s9] = pts9
        return today9, spark9

    @staticmethod
    def _debt_redate_moves(conn):
        try:
            if not conn.execute("SELECT 1 FROM meta WHERE k='exf_debt_redate_t'").fetchone():
                return None
            d9 = common.read_json(os.path.join(common.STATE_DIR, "exf_debt_redate_t.json"), {}) or {}
        except (Exception, SystemExit):
            return None
        out = []
        for m9 in (d9.get("moves") if isinstance(d9, dict) and isinstance(d9.get("moves"), list) else ()):
            try:
                r9 = conn.execute("SELECT COALESCE(group_id, -asset_id), decimals FROM assets WHERE asset_id=?",
                                  (int(m9["asset_id"]),)).fetchone()
                if not r9:
                    continue
                q9 = -Decimal(int(m9["new_qty_base"])) / (Decimal(10) ** (8 if r9[1] is None else int(r9[1])))
                if q9 > 0 and int(m9["new_ts"]) < int(m9["old_ts"]):
                    out.append({"pid": str(int(m9["posting_id"])), "gid": int(r9[0]), "q": q9,
                                "t_new": int(m9["new_ts"]), "t_old": int(m9["old_ts"])})
            except (KeyError, TypeError, ValueError, ArithmeticError):
                continue
        return out

    def _daily_series(self, G, today_kst, override_px=None, live_px=None, ca_gids=None,
                      skip_gids=None,
                      ex_gids=None, pending_gids=None,
                      hold_qty=None, extra=None, extra_ok=True, now_ts=None, native_c=None, debt_moves=None, transit=None,
                      stable_aliases=None, day_close=None, neg_ok=None, led_gen=None) -> list:
        lo_bind9 = (today_kst - timedelta(days=DAILY_PX_KEEP)).strftime("%Y-%m-%d")
        bound9, legacy9 = _bind_px_blocks(self.daily, self.daily_px, lo_bind9)
        if legacy9:
            if not isinstance(self.daily_px.get("_pxfix"), dict):
                ts9 = int(now_ts if now_ts is not None else time.time())
                bak9 = _pxfix_backup(ts9)
                self.daily_px["_pxfix"] = {"v": 1, "bak": ts9, "at": ts9}
                log.info("pxfix: 동결 항목 가격 블록 1회 이관 — 백업 %s", bak9)
            migrated9 = _migrate_px_blocks(self.daily, self.daily_px, legacy9)
            log.info("pxfix: 옛 형식 동결 항목 %d일에 가격 블록 이관", migrated9)
        else:
            migrated9 = 0
        relabeled9 = _relabel_daily_gids(self.daily, self.daily_px, stable_aliases)
        if relabeled9:
            log.info("일별: 스테이블 재그룹 — 동결 그룹 평가액 키 %d개 이관 %s", relabeled9, stable_aliases)
        override_px = override_px or {}
        live_px = live_px or {}
        ca_gids = ca_gids or set()
        ex_gids = ex_gids or set()
        pending_gids = pending_gids or set()
        px_wait9 = self.__dict__.get("_px_wait_gids") or set()
        extra = extra or {}
        x_now = float(extra.get("ub") or 0) + float(extra.get("fiat") or 0) + float(extra.get("lp") or 0)
        x_split = "krw_up" in extra
        krw_up_now = float(extra.get("krw_up") or 0)
        krw_other_now = float(extra.get("krw_other") or 0)
        x_nonkrw = float(extra.get("ub") or 0) + float(extra.get("lp") or 0)
        ubs_now = ({str(k9).upper(): v9 for k9, v9 in extra["ubs"].items()} if isinstance(extra.get("ubs"), dict) else {})
        ub_tl9 = extra.get("ub_tl") if isinstance(extra.get("ub_tl"), dict) else {}
        ub_sym9 = {}
        for gid9 in ub_tl9:
            if gid9 in G:
                ub_sym9.setdefault(str(G[gid9].get("sym") or "").upper(), []).append(gid9)

        def xu_of(v9):
            out9 = {}
            for s9, a9 in (v9.items() if isinstance(v9, dict) else ()):
                try:
                    q9, u9 = float(a9[0]), float(a9[1])
                except (TypeError, ValueError, IndexError, KeyError):
                    continue
                if q9 > 0 and u9 >= 0:
                    out9[str(s9).upper()] = (q9, u9)
            return out9

        def xu_keep(v9):
            return {s9: [round(q9, 12), round(u9, 2)] for s9, (q9, u9) in xu_of(v9).items()}

        def xu_cut(v9, end_ts9, only=None):
            cut9, rest9, px9 = 0.0, {}, {}
            for s9, (q9, u9) in xu_of(v9).items():
                qu9 = Decimal(0)
                for gid9 in ub_sym9.get(s9, ()):
                    if only is not None and gid9 not in only:
                        continue
                    qg9 = Decimal(0)
                    for t9, d9 in ub_tl9[gid9]:
                        if t9 > end_ts9:
                            break
                        qg9 += d9
                    qu9 += max(Decimal(0), min(qg9, qty_at(gid9, int(end_ts9 * 1000))))
                if qu9 > EPS:
                    f9 = min(1.0, float(qu9) / q9)
                    cut9 += u9 * f9
                    if u9 > 0:
                        px9[s9] = u9 / q9
                    if f9 < 1.0:
                        rest9[s9] = [round(q9 * (1 - f9), 12), round(u9 * (1 - f9), 2)]
                else:
                    rest9[s9] = [round(q9, 12), round(u9, 2)]
            return cut9, rest9, px9

        def frozen_ub_cut(c9, end_ts9, added9):
            only9 = {g9 for g9 in added9 if g9 in ub_tl9 and g9 in G}
            if not only9 or not c9.get("xu"):
                return 0.0
            cut9, rest9, _p9 = xu_cut(c9["xu"], end_ts9, only9)
            if cut9 <= 0:
                return 0.0
            c9["val"] = _f(Decimal(str(c9["val"])) - Decimal(str(cut9)), 2) or 0
            c9["x"] = round(float(c9.get("x") or 0) - cut9, 2)
            if c9.get("xc"):
                xc9 = float(c9["xc"]) - cut9
                if xc9 >= 1:
                    c9["xc"] = round(xc9, 2)
                else:
                    c9.pop("xc", None)
            if rest9:
                c9["xu"] = rest9
            else:
                c9.pop("xu", None)
            log.info("일별 동결 항목: 새로 소급한 업비트 원장 그룹 %s — 원장 밖 잔고 x 에서 %.2f 뺌(이중 계상 방지)", sorted(only9), cut9)
            return cut9
        rate_now = float(extra.get("rate") or self.spot.rate or 1384)
        up_tl = extra.get("krw_up_tl")
        now_ts = time.time() if now_ts is None else float(now_ts)
        now_ms = int(now_ts * 1000)
        days = []
        att_src9 = {}
        self._daily_att_src = att_src9
        nf9 = set()
        self._daily_nf = nf9
        frozen_ok = os.path.exists(os.path.join(common.STATE_DIR, "backfill_done"))
        meta_keys = ("_v", "_risk_rev", "_live", "_live_ok", "_reset_at")
        pinned9 = (_pin_frozen_x(self.daily, self.daily_px, (today_kst - timedelta(days=DAILY_PX_KEEP)).strftime("%Y-%m-%d"))
                   if hold_qty is not None and frozen_ok else 0)
        if pinned9:
            log.info("일별: 동결 과거일 %d일의 원장 밖 잔고(x)를 daily_px 에 고정", pinned9)
        if not os.path.exists(DAILY_PATH) and any(k not in meta_keys for k in self.daily):
            self.daily = _daily_reset(self.daily, today_kst)
        if not any(k not in meta_keys for k in self.daily) and not self.daily.get("_reset_at"):
            self.daily["_reset_at"] = int(time.time())
        rev9 = ",".join(str(x) for x in sorted(skip_gids or ()))
        skip9s = {str(x) for x in (skip_gids or ())}
        if self.daily.get("_risk_rev") != rev9:
            kept9 = {"_v": DAILY_V, "_risk_rev": rev9}
            if self.daily.get("_reset_at"):
                kept9["_reset_at"] = self.daily["_reset_at"]
            for lk9 in ("_live", "_live_ok"):
                if isinstance(self.daily.get(lk9), dict):
                    kept9[lk9] = self.daily[lk9]
            n_re, n_drop = 0, 0
            for ck9, c9 in self.daily.items():
                if ck9 in meta_keys or not isinstance(c9, dict):
                    continue
                gv9 = c9.get("g")
                if isinstance(gv9, dict):
                    v9 = sum(float(v) for k, v in gv9.items() if k not in skip9s) + float(c9.get("x") or 0)
                    kept9[ck9] = dict(c9, val=_f(v9, 2) or 0)
                    n_re += 1
                else:
                    n_drop += 1
            self.daily = kept9
            log.info("격리 집합 변경 — 동결 과거일 %d일은 그룹별 마감값으로 재산출, 구형식 %d일은 재계산", n_re, n_drop)
            if frozen_ok:
                common.atomic_write_json(DAILY_PATH, self.daily)
        lg_now9 = int(led_gen or 0)

        def led_old(lg9, ts9):
            if not lg_now9:
                return False
            try:
                return int(float(lg9)) != lg_now9 if lg9 is not None else float(ts9 or 0) < lg_now9
            except (TypeError, ValueError):
                return True

        old9 = set()
        if lg_now9 and hold_qty is not None and frozen_ok:
            lo9, td9 = (today_kst - timedelta(days=29)).strftime("%Y-%m-%d"), today_kst.strftime("%Y-%m-%d")
            old9 = {ck9 for ck9, c9 in self.daily.items()
                    if not str(ck9).startswith("_") and isinstance(c9, dict) and lo9 <= str(ck9) < td9
                    and c9.get("src") == "live" and c9.get("snap") and led_old(c9.get("lg"), c9.get("snap"))}
            if old9 and self.__dict__.get("_led_old_logged") != (lg_now9, tuple(sorted(old9))):
                self._led_old_logged = (lg_now9, tuple(sorted(old9)))
                log.warning("일별: 원장 교체(세대 %s) 전 마감 스냅샷으로 동결된 날 %s — 지금 원장 수량으로 다시 계산(가격·x 는 그날 고정값)",
                            lg_now9, sorted(old9))
        live_snap = self.daily.get("_live") if isinstance(self.daily.get("_live"), dict) else None
        live_ok = self.daily.get("_live_ok") if isinstance(self.daily.get("_live_ok"), dict) else None
        timelines = {}
        for gid, g in G.items():
            tl = sorted(g["qty_timeline"])
            timelines[gid] = tl
        changed = bool(relabeled9 or migrated9 or self.__dict__.get("_daily_dirty"))
        px_changed = bool(pinned9 or relabeled9 or bound9 or migrated9 or self.__dict__.get("_dpx_dirty"))
        dpx = self.daily_px
        stable_gids9 = sorted(gid for gid, g in G.items() if g.get("is_stable") and not g.get("is_fiat"))
        stable_base9 = ",".join(str(x) for x in stable_gids9)
        neg9 = sorted(g9 for g9 in (neg_ok or ()) if g9 in G)
        stable_rev9 = stable_base9 + ("|n:" + ",".join(str(x) for x in neg9) if neg9 else "")

        tr_by9 = {}
        for e9 in (transit or ()):
            tr_by9.setdefault(e9["gid"], []).append((int(e9["ts"]), Decimal(e9["qty"]), str(e9["uuid"])))

        def wdt_at(end_ts9):
            return {u9: [g9, float(q9)] for g9, lst9 in tr_by9.items() for t9, q9, u9 in lst9 if t9 <= end_ts9}

        def qty_at(gid9, end_ms9):
            q9 = hold_qty.get(gid9, Decimal(0))
            if end_ms9 < now_ms:
                for ts9, dq9 in reversed(timelines[gid9]):
                    if ts9 * 1000 <= end_ms9:
                        break
                    q9 -= dq9
                for t9, tq9, _u9 in tr_by9.get(gid9, ()):
                    if end_ms9 < t9 * 1000:
                        q9 -= tq9
            return q9

        for gid9 in sorted(native_c or ()):
            if gid9 not in G:
                continue
            sid9, sym9 = str(gid9), G[gid9]["sym"]
            for ck9 in sorted(k9 for k9 in dpx if not k9.startswith("_")):
                e9 = dpx.get(ck9)
                if not isinstance(e9, dict) or ck9 >= today_kst.strftime("%Y-%m-%d"):
                    continue
                op9 = (e9.get("p") or {}).get(sid9)
                if not op9 or (e9.get("k") or {}).get(sid9):
                    continue
                try:
                    d9 = datetime.strptime(ck9, "%Y-%m-%d").replace(tzinfo=today_kst.tzinfo)
                except ValueError:
                    continue
                c9 = self.daily.get(ck9)
                done9 = (c9.get("native_c") or {}).get(sid9) if isinstance(c9, dict) and isinstance(c9.get("native_c"), dict) else None
                if done9 is not None:
                    e9["p"][sid9] = float(done9)
                    e9.setdefault("k", {})[sid9] = "c"
                    px_changed = True
                    continue
                c9p = self.px.candle_usd(sym9, int(d9.replace(hour=23, minute=59, second=59).timestamp() * 1000))
                if not c9p:
                    continue
                e9["p"][sid9] = float(c9p)
                e9.setdefault("k", {})[sid9] = "c"
                px_changed = True
                c9 = self.daily.get(ck9)
                if isinstance(c9, dict) and isinstance(c9.get("g"), dict) and sid9 in c9["g"]:
                    ov9 = Decimal(str(c9["g"][sid9]))
                    nv9 = ov9 * Decimal(str(c9p)) / Decimal(str(op9))
                    c9["g"][sid9] = round(float(nv9), 4)
                    if not (skip_gids and gid9 in skip_gids):
                        c9["val"] = _f(Decimal(str(c9["val"])) + nv9 - ov9, 2) or 0
                        if c9.get("est"):
                            e9s = float(c9["est"]) - float(ov9)
                            if e9s >= 1:
                                c9["est"] = round(e9s, 2)
                            else:
                                c9.pop("est", None)
                    c9["src9"] = "native_candle"
                    c9.setdefault("native_c", {})[sid9] = float(c9p)
                    changed = True
                    log.info("일별 %s: 네이티브 %s(g%s) 근사가 $%.2f → 1분봉 $%.2f (%+.2f)", ck9, sym9, sid9, float(op9), float(c9p),
                             float(nv9 - ov9))
        if day_close is not None and hold_qty is not None and frozen_ok:
            r10 = _px1004_reset(self.daily, dpx, G, today_kst.strftime("%Y-%m-%d"), day_close, live_px, skip_gids, now_ts)
            if r10["n"]:
                changed = changed or r10["changed"]
                px_changed = True
                log.warning("일별: px1004 업비트·빗썸 USDT·BTC 마켓 그날 마감가 %d개 근사로 되돌림 — 총자산 차 %+.2f · 새 순서로 다시 받는다", r10["n"], r10["dv"])

            def pxfix_key9():
                return (getattr(day_close, "gen", None), today_kst.strftime("%Y-%m-%d"), int(now_ts // 3600),
                        sum(len(e9.get("p") or {}) - len(e9.get("k") or {}) - len(e9.get("dcn") or ())
                            for k9, e9 in dpx.items() if not k9.startswith("_") and isinstance(e9, dict)),
                        sum(len(c9.get("g") or ()) for k9, c9 in self.daily.items() if not k9.startswith("_") and isinstance(c9, dict)))
            if self.__dict__.get("_pxfix_key") != pxfix_key9():
                r9 = _reprice_now_days(self.daily, dpx, G, today_kst.strftime("%Y-%m-%d"), now_ts, day_close, skip_gids)
                self._pxfix_last = r9
                if r9["changed"]:
                    changed = True
                if r9["px_changed"]:
                    px_changed = True
                self._pxfix_key = pxfix_key9()
                if r9["rep"] or r9["fin"]:
                    log.info("일별: 그날 마감가 재평가 %d · 근사 확정 %d · 대기 %d · 총자산 차 %+.2f", r9["rep"], r9["fin"], r9["pend"], r9["dv"])
        drd_all9 = {m9["pid"]: 0 for m9 in (debt_moves or ())}
        for m9 in (debt_moves or ()):
            sid9, gid9 = str(m9["gid"]), m9["gid"]
            g09 = G.get(gid9) or {}
            for ck9, c9 in sorted(self.daily.items()):
                if ck9.startswith("_") or not isinstance(c9, dict) or not isinstance(c9.get("g"), dict) or ck9 >= today_kst.strftime("%Y-%m-%d"):
                    continue
                if m9["pid"] in (c9.get("drd") or {}):
                    continue
                try:
                    end9 = datetime.strptime(ck9, "%Y-%m-%d").replace(tzinfo=today_kst.tzinfo, hour=23, minute=59, second=59).timestamp()
                except ValueError:
                    continue
                if not (m9["t_new"] <= end9 < m9["t_old"]):
                    continue
                ov9 = Decimal(str(c9["g"].get(sid9) or 0))
                if g09.get("is_stable") and not g09.get("is_fiat"):
                    p9 = Decimal(1)
                else:
                    fp9 = ((dpx.get(ck9) or {}).get("p") or {}).get(sid9)
                    p9 = Decimal(str(fp9)) if fp9 else Decimal(0)
                nv9 = ov9
                if p9 > 0:
                    q9 = ov9 / p9 - m9["q"]
                    nv9 = q9 * p9 if q9 > EPS else Decimal(0)
                dv9 = nv9 - ov9
                if nv9 > 0:
                    c9["g"][sid9] = round(float(nv9), 4)
                else:
                    c9["g"].pop(sid9, None)
                if dv9 and not (skip_gids and gid9 in skip_gids):
                    c9["val"] = _f(Decimal(str(c9["val"])) + dv9, 2) or 0
                    if c9.get("est") and not g09.get("is_stable") and not ((dpx.get(ck9) or {}).get("k") or {}).get(sid9):
                        e9s = float(c9["est"]) + float(dv9)
                        if e9s >= 1:
                            c9["est"] = round(e9s, 2)
                        else:
                            c9.pop("est", None)
                c9.setdefault("drd", {})[m9["pid"]] = round(float(dv9), 2)
                c9["src9"] = "debt_redate"
                changed = True
                log.info("일별 %s: 기존 부채 첫 반영 소급(posting %s) %s %s × $%s → %+.2f", ck9, m9["pid"], g09.get("sym"),
                         format(m9["q"], "f"), format(p9, "f"), float(dv9))
        pre9 = self.__dict__.get("_px_pre_gids") or {}
        bf_gids9 = sorted(gid9 for gid9 in (set(ca_gids) | set(ex_gids)) if gid9 in G and gid9 not in override_px and gid9 not in pre9
                          and not G[gid9].get("is_stable") and not G[gid9].get("is_fiat") and (live_px.get(gid9) or 0) > 0)
        bf_rev9 = ",".join(str(x) for x in bf_gids9)
        bf_seen9 = self.__dict__.setdefault("_px_bf_seen", {})

        def live_allow(c9):
            if c9.get("src") != "live":
                return None
            return {str(x9) for x9 in (c9.get("z") or ())}

        def px_backfill(ck9, d9, c9):
            sn9 = bf_seen9.get(ck9)
            if sn9 and sn9[0] == bf_rev9 and sn9[1] is c9:
                return False
            bf_seen9[ck9] = (bf_rev9, c9)
            allow9 = live_allow(c9)
            if allow9 is not None and not allow9:
                return False
            end_ms9 = int(d9.replace(hour=23, minute=59, second=59, microsecond=0).timestamp() * 1000)
            fx9 = dpx.get(ck9) or {}
            fp9, fk9 = fx9.get("p") or {}, fx9.get("k") or {}
            sd9 = (self._daily_seed.get(ck9) or {}).get("g") or {}
            add9, est9, n9 = Decimal(0), Decimal(0), 0
            ubp9 = xu_cut(c9.get("xu"), end_ms9 / 1000)[2] if c9.get("xu") else {}
            added9 = []
            wait9 = False
            for gid9 in bf_gids9:
                sid9 = str(gid9)
                if sid9 in c9["g"] or (allow9 is not None and sid9 not in allow9):
                    continue
                q9 = qty_at(gid9, end_ms9)
                if q9 <= EPS:
                    continue
                c9b = None
                if not (sid9 in fp9 and fp9[sid9]) and native_c and gid9 in native_c:
                    c9b = self.px.candle_usd(G[gid9]["sym"], end_ms9)
                    if c9b is None and _px_took(self.px):
                        wait9 = True
                        continue
                ubs9 = str(G[gid9].get("sym") or "").upper()
                if sid9 in fp9 and fp9[sid9]:
                    p9, k9 = float(fp9[sid9]), fk9.get(sid9) or "now"
                elif gid9 in ub_tl9 and ubs9 in ubp9:
                    p9, k9 = ubp9[ubs9], "ub"
                elif c9b:
                    p9, k9 = float(c9b), "c"
                else:
                    p9, k9 = float(live_px[gid9]), "now"
                    sv9 = sd9.get(sid9)
                    try:
                        sp9 = float(Decimal(str(sv9)) / q9) if sv9 is not None else None
                    except (InvalidOperation, ValueError, ZeroDivisionError):
                        sp9 = None
                    if sp9 and 0.5 <= sp9 / p9 <= 2.0:
                        p9, k9 = sp9, "seed"
                    elif day_close is not None and float(q9) * p9 >= DC_SMALL_USD:
                        dcb9 = day_close(gid9, ck9, float(q9) * p9)[0]
                        if dcb9:
                            p9, k9 = float(dcb9), "d"
                v9 = q9 * Decimal(str(p9))
                if abs(v9) < Decimal("0.00005"):
                    continue
                c9["g"][sid9] = round(float(v9), 4)
                n9 += 1
                added9.append(gid9)
                if sid9 not in fp9:
                    e9 = dpx.setdefault(ck9, {"p": {}, "k": {}})
                    e9.setdefault("p", {})[sid9] = p9
                    if k9 != "now":
                        e9.setdefault("k", {})[sid9] = k9
                    if k9 in ("d", "c") and (live_px.get(gid9) or 0) > 0:
                        e9.setdefault("lp", {}).setdefault(sid9, float(live_px[gid9]))
                if not (skip_gids and gid9 in skip_gids):
                    add9 += v9
                    if k9 == "now":
                        est9 += v9
            if wait9:
                bf_seen9.pop(ck9, None)
            if not n9:
                return False
            if add9:
                c9["val"] = _f(Decimal(str(c9["val"])) + add9, 2) or 0
            if est9 >= 1:
                c9["est"] = round(float(c9.get("est") or 0) + float(est9), 2)
            frozen_ub_cut(c9, end_ms9 / 1000, added9)
            c9["src9"] = "px_backfill"
            log.info("일별 %s: 늦게 가격이 생긴 그룹 %d개 소급 %+.2f (근사 %.2f)", ck9, n9, float(add9), float(est9))
            return True

        for i in range(29, -1, -1):
            d = (today_kst - timedelta(days=i))
            dkey = d.strftime("%m-%d")
            dow = "일월화수목금토"[int(d.strftime("%w"))]
            is_today = (i == 0)
            ck = d.strftime("%Y-%m-%d")
            if not is_today and frozen_ok and ck in self.daily and ck not in old9:
                c = self.daily[ck]
                z_st9 = (c.get("src") == "live" and isinstance(c.get("z"), list) and isinstance(c.get("g"), dict)
                         and any(str(gid9) in c["z"] and str(gid9) not in c["g"] for gid9 in stable_gids9))
                if hold_qty is not None and isinstance(c.get("g"), dict) and (c.get("st") != stable_rev9 or z_st9):
                    end_ms9 = int(d.replace(hour=23, minute=59, second=59, microsecond=0).timestamp() * 1000)
                    add9 = Decimal(0)
                    allow_st9 = live_allow(c)
                    added_st9 = []
                    only_neg9 = c.get("st") != stable_rev9 and str(c.get("st") or "").split("|n:", 1)[0] == stable_base9
                    for gid9 in stable_gids9:
                        neg_g9 = bool(neg_ok and gid9 in neg_ok)
                        if only_neg9 and not neg_g9:
                            continue
                        if str(gid9) in c["g"]:
                            continue
                        out_z9 = allow_st9 is not None and str(gid9) not in allow_st9
                        if out_z9 and not neg_g9:
                            continue
                        q9 = qty_at(gid9, end_ms9)
                        if out_z9 and not q9 < Decimal("-0.00005"):
                            continue
                        if q9 > Decimal("0.00005") or (neg_g9 and q9 < Decimal("-0.00005")):
                            c["g"][str(gid9)] = round(float(q9), 4)
                            added_st9.append(gid9)
                            if not (skip_gids and gid9 in skip_gids):
                                add9 += q9
                    if add9:
                        c["val"] = _f(Decimal(str(c["val"])) + add9, 2) or 0
                        c["src9"] = "stable_backfill"
                    frozen_ub_cut(c, end_ms9 / 1000, added_st9)
                    c["st"] = stable_rev9
                    changed = True
                if hold_qty is not None and isinstance(c.get("g"), dict) and bf_gids9 and px_backfill(ck, d, c):
                    changed = True
                    px_changed = True
                row9 = {"date": dkey, "dow": dow, "val": c["val"], "usdt": c.get("usdt"), "kimp": c.get("kimp")}
                if c.get("est"):
                    row9["est"] = c["est"]
                if c.get("xc"):
                    row9["xc"] = c["xc"]
                days.append(row9)
                att_src9[ck] = (c.get("g"), (dpx.get(ck) or {}).get("p"), c.get("xu"))
                continue
            end = d.replace(hour=23, minute=59, second=59, microsecond=0)
            end_ts = end.timestamp()
            end_ms = now_ms if is_today else int(end_ts * 1000)
            snap1 = None
            part1 = None
            old1 = False
            old_sn1 = None
            if not is_today and hold_qty is not None:
                for sn9 in (live_snap, live_ok, (dpx.get(ck) or {}).get("partial")):
                    if (sn9 and sn9.get("date") == ck and isinstance(sn9.get("g"), dict)
                            and float(sn9.get("ts") or 0) >= end_ts - DAILY_LIVE_WIN):
                        if not sn9.get("defer"):
                            if led_old(sn9.get("lg"), sn9.get("ts")):
                                old1 = True
                                old_sn1 = old_sn1 or sn9
                                continue
                            snap1 = sn9
                            break
                        if part1 is None:
                            part1 = sn9
            if part1 is not None and snap1 is None and frozen_ok and (dpx.get(ck) or {}).get("partial") is not part1:
                dpx.setdefault(ck, {"p": {}, "k": {}})["partial"] = part1
                px_changed = True
            if snap1 is not None:
                gs = snap1["g"]
                xs = float(snap1.get("x") or 0)
                v1 = _f(sum(float(v) for k, v in gs.items() if k not in skip9s) + xs, 2) or 0
                days.append({"date": dkey, "dow": dow, "val": v1,
                             "usdt": snap1.get("usdt"), "kimp": snap1.get("kimp")})
                if frozen_ok:
                    self.daily[ck] = {"val": v1, "usdt": snap1.get("usdt"), "kimp": snap1.get("kimp"),
                                      "g": dict(gs), "x": round(xs, 2), "src": "live", "st": stable_rev9,
                                      "snap": int(float(snap1.get("ts") or 0))}
                    if snap1.get("lg") is not None:
                        self.daily[ck]["lg"] = snap1["lg"]
                    xu9s = xu_keep(snap1.get("xu"))
                    if xu9s:
                        self.daily[ck]["xu"] = xu9s
                    if snap1.get("z"):
                        self.daily[ck]["z"] = list(snap1["z"])
                    if isinstance(snap1.get("wdt"), dict) and snap1["wdt"]:
                        self.daily[ck]["wdt"] = snap1["wdt"]
                    if isinstance(snap1.get("drd"), list):
                        self.daily[ck]["drd"] = {str(k9): 0 for k9 in snap1["drd"]}
                    changed = True
                    lp9 = snap1.get("p")
                    if not isinstance(lp9, dict):
                        lp9 = {}
                        for k9, v9 in gs.items():
                            try:
                                gid9 = int(k9)
                            except ValueError:
                                continue
                            if gid9 in G and not G[gid9].get("is_stable"):
                                q9 = qty_at(gid9, int(end_ts * 1000))
                                if q9 > EPS and float(v9) > 0:
                                    lp9[k9] = float(Decimal(str(v9)) / q9)
                    dpx[ck] = {"p": {k9: v9 for k9, v9 in lp9.items() if v9}, "k": {k9: "live" for k9, v9 in lp9.items() if v9},
                               "x": round(xs, 2), "xk": "live"}
                    if xu9s:
                        dpx[ck]["xu"] = xu9s
                    px_changed = True
                att_src9[ck] = (gs, snap1.get("p") if isinstance(snap1.get("p"), dict) else (dpx.get(ck) or {}).get("p"), snap1.get("xu"))
                continue
            px_live = is_today or end_ms >= now_ms - 120_000
            fixed = (dpx.get(ck) or {}) if not is_today else {}
            fixed_p, fixed_k = fixed.get("p") or {}, fixed.get("k") or {}
            seed = self._daily_seed.get(ck) if not is_today else None
            seed_x = seed if ck not in dpx else None
            new_p, new_k = {}, {}
            new_lp = {}
            pxu9 = {}
            est = Decimal(0)
            total = Decimal(0)
            gvals = {}
            defer = False
            pend9 = []
            z9 = []
            n_est9 = 0
            x_stale9 = False
            part_g9, part_p9, part_pend9 = None, {}, set()
            if hold_qty is None or is_today:
                xu_src9 = None
            elif part1 is not None:
                xu_src9 = part1.get("xu")
            elif live_snap and live_snap.get("date") == ck:
                xu_src9 = live_snap.get("xu")
            elif fixed.get("x") is not None:
                xu_src9 = fixed.get("xu")
            elif seed_x and seed_x.get("x") is not None:
                xu_src9 = None
            else:
                xu_src9 = ubs_now
            xcut9, xrest9, ubpx9 = xu_cut(xu_src9, end_ts) if xu_src9 else (0.0, {}, {})
            if part1 is not None:
                part_g9 = part1["g"]
                part_p9 = part1.get("p") if isinstance(part1.get("p"), dict) else {}
                part_pend9 = {str(x9) for x9 in (part1.get("pend") or ())}
            for gid, g in G.items():
                skip9 = bool(skip_gids and gid in skip_gids)
                if g.get("is_fiat"):
                    continue
                if hold_qty is not None:
                    qty = qty_at(gid, end_ms)
                else:
                    qty = Decimal(0)
                    for ts, dq in timelines[gid]:
                        if ts * 1000 <= end_ms:
                            qty += dq
                if qty <= EPS and not (qty < -EPS and neg_ok and gid in neg_ok):
                    continue
                sym = g["sym"]
                sid = str(gid)
                if g["is_stable"]:
                    gvals[sid] = qty
                    if not skip9:
                        total += qty
                    continue
                if (sym in STABLE_GROUPS and gid not in ca_gids
                        and gid not in ex_gids and gid not in override_px):
                    continue
                ov = override_px.get(gid)
                if ov is not None and not ((ck in old9 or old1) and sid in fixed_p):
                    pxu9[sid] = float(ov)
                    gvals[sid] = qty * Decimal(str(ov))
                    if not skip9:
                        total += gvals[sid]
                    if is_today:
                        new_p[sid] = float(ov)
                    continue
                kind = None
                if sid in fixed_p:
                    px = fixed_p[sid]
                    kind = fixed_k.get(sid) or "now"
                elif part_g9 is not None and sid in part_g9 and sid not in part_pend9 and float(part_g9[sid]) > 0:
                    px = part_p9.get(sid) or float(Decimal(str(part_g9[sid])) / qty)
                    kind = "live"
                elif gid in ub_tl9 and str(sym or "").upper() in ubpx9:
                    px = ubpx9[str(sym or "").upper()]
                    kind = "ub"
                elif gid in ca_gids:
                    px = live_px.get(gid) or 0
                    kind = "live" if px_live else "now"
                    if gid in pending_gids and not skip9:
                        defer = True
                        pend9.append(sid)
                elif gid in ex_gids:
                    c9x = None
                    if not px_live and native_c and gid in native_c:
                        c9x = self.px.candle_usd(sym, end_ms)
                        if c9x is None and _px_took(self.px) and not skip9:
                            defer = True
                            pend9.append(sid)
                    if c9x:
                        px, kind = c9x, "c"
                    else:
                        px = live_px.get(gid) or 0
                        kind = "live" if px_live else "now"
                        if gid in pending_gids and not skip9:
                            defer = True
                            pend9.append(sid)
                elif px_live and (is_today or sid not in part_pend9):
                    _px_took(self.px)
                    px = live_px[gid] if gid in live_px else (
                        self.spot.price(sym) or self.px.candle_usd(sym, end_ms) or 0)
                    kind = "live"
                    if not skip9 and (gid in px_wait9 or (not px and _px_took(self.px))):
                        defer = True
                        pend9.append(sid)
                else:
                    px = self.px.candle_usd(sym, end_ms) or 0
                    kind = "c"
                    if not px and _px_took(self.px) and not skip9:
                        defer = True
                        pend9.append(sid)
                if kind == "now" and seed and px and sid not in fixed_p:
                    sv9 = (seed.get("g") or {}).get(sid)
                    try:
                        sp9 = float(Decimal(str(sv9)) / qty) if sv9 is not None else None
                    except (InvalidOperation, ValueError, ZeroDivisionError):
                        sp9 = None
                    if sp9 and 0.5 <= sp9 / float(px) <= 2.0:
                        px, kind = sp9, "seed"
                if (kind == "now" and day_close is not None and hold_qty is not None and sid not in fixed_p
                        and float(qty) * float(px or 0) >= DC_SMALL_USD):
                    dcp9 = day_close(gid, ck, float(qty) * float(px or 0))[0]
                    if dcp9:
                        px, kind = dcp9, "d"
                if px and sid not in fixed_p:
                    new_p[sid] = float(px)
                    if kind != "now":
                        new_k[sid] = kind
                    if kind in ("d", "c") and not is_today and (live_px.get(gid) or 0) > 0:
                        new_lp[sid] = float(live_px[gid])
                if is_today and not px and not skip9 and (gid in ca_gids or gid in ex_gids):
                    z9.append(sid)
                gvals[sid] = qty * Decimal(str(px))
                if px:
                    pxu9[sid] = float(px)
                if not skip9:
                    total += gvals[sid]
                    if kind == "now" and not is_today:
                        est += gvals[sid]
                        n_est9 += 1
            usdt = None
            kimp = None
            fx = None
            fix9 = ck in old9 or old1
            fx_src9 = ((self.daily.get(ck) if ck in old9 else None) or old_sn1 or {}) if fix9 else {}
            if fix9 and fx_src9.get("usdt"):
                usdt = fx_src9["usdt"]
                kimp = fx_src9.get("kimp")
                fx = float(usdt)
            elif px_live:
                usdt = self.spot.rate or None
                if usdt and self.spot.fx_basis:
                    kimp = round((usdt / self.spot.fx_basis - 1) * 100, 2)
            else:
                fx = self.px.fx_at(end_ms)
                if fx is None and (_px_took(self.px) or fix9):
                    defer = True
                usdt = round(fx) if fx else None
                if usdt and self.spot.fx_basis:
                    kimp = round((usdt / self.spot.fx_basis - 1) * 100, 2)
            x_carry = 0.0
            x_kind = None
            if hold_qty is None:
                x_day = 0.0
            elif is_today:
                x_day = x_now
            elif part1 is not None:
                x_day = float(part1.get("x") or 0)
                x_kind = "live"
            elif live_snap and live_snap.get("date") == ck:
                x_day = float(live_snap.get("x") or 0)
                x_kind = "live"
            elif fixed.get("x") is not None:
                x_day = float(fixed["x"])
                x_kind = fixed.get("xk") or "live"
                if fixed.get("xc"):
                    x_carry = float(fixed["xc"])
            elif seed_x and seed_x.get("x") is not None:
                x_day = float(seed_x["x"])
                x_kind = "seed"
            elif not x_split:
                x_day = x_now
                x_carry = x_now
                if not extra_ok:
                    defer = True
                    x_stale9 = True
            else:
                fx_d = float(fx or rate_now)
                krw_up = None
                if up_tl is not None:
                    later = sum((d9 for t9, d9 in up_tl if t9 > end_ts), Decimal(0))
                    k9 = Decimal(str(krw_up_now)) - later
                    if k9 >= Decimal(-1000):
                        krw_up = float(max(k9, Decimal(0)))
                if krw_up is None:
                    krw_up = krw_up_now
                    x_carry += krw_up_now / fx_d
                x_carry += x_nonkrw + krw_other_now / fx_d
                x_day = x_nonkrw + (krw_up + krw_other_now) / fx_d
                if not extra_ok:
                    defer = True
                    x_stale9 = True
            x_raw9, xc_raw9 = x_day, x_carry
            if xcut9:
                x_day -= xcut9
                x_carry = max(0.0, x_carry - xcut9)
            total += Decimal(str(x_day))
            entry = {"date": dkey, "dow": dow,
                     "val": _f(total, 2) or 0, "usdt": usdt, "kimp": kimp}
            if est >= 1:
                entry["est"] = round(float(est), 2)
            if x_carry >= 1:
                entry["xc"] = round(x_carry, 2)
            days.append(entry)
            if ck in old9 and defer:
                nf9.add(ck)
            g_out = {k: round(float(v), 4) for k, v in gvals.items() if abs(v) >= Decimal("0.00005")}
            att_src9[ck] = (g_out, pxu9, (ubs_now if hold_qty is not None else {}) if is_today else xrest9)
            if is_today and hold_qty is not None:
                self.daily["_live"] = {"date": ck, "ts": round(now_ts, 3), "val": entry["val"], "usdt": usdt,
                                       "kimp": kimp, "g": g_out, "x": round(x_day, 2), "defer": defer,
                                       "p": {k9: round(v9, 12) for k9, v9 in new_p.items()}}
                if lg_now9:
                    self.daily["_live"]["lg"] = lg_now9
                if ubs_now:
                    self.daily["_live"]["xu"] = xu_keep(ubs_now)
                if pend9:
                    self.daily["_live"]["pend"] = sorted(set(pend9))
                if z9:
                    self.daily["_live"]["z"] = sorted(set(z9))
                if x_stale9:
                    self.daily["_live"]["xs"] = 1
                if debt_moves is not None:
                    self.daily["_live"]["drd"] = sorted(drd_all9)
                wdt9 = wdt_at(now_ts)
                if wdt9:
                    self.daily["_live"]["wdt"] = wdt9
                in_win9 = now_ts >= end_ts - DAILY_LIVE_WIN
                if in_win9 and not defer:
                    self.daily["_live_ok"] = self.daily["_live"]
                if in_win9 and now_ts - getattr(self, "_live_saved_at", 0) >= 50:
                    self._live_saved_at = now_ts
                    changed = True
            elif not is_today and frozen_ok and not defer:
                self.daily[ck] = {"val": entry["val"], "usdt": usdt, "kimp": kimp, "g": g_out,
                                  "x": round(x_day, 2), "src": "partial" if part1 is not None else "calc", "st": stable_rev9}
                if xrest9:
                    self.daily[ck]["xu"] = xrest9
                if xcut9:
                    self.daily[ck]["x0"] = round(x_raw9, 2)
                    self.daily[ck]["xu0"] = xu_keep(xu_src9)
                if debt_moves is not None:
                    self.daily[ck]["drd"] = dict(drd_all9)
                wdt9 = wdt_at(end_ts)
                if wdt9:
                    self.daily[ck]["wdt"] = wdt9
                if (dpx.get(ck) or {}).pop("partial", None) is not None:
                    px_changed = True
                if hold_qty is not None:
                    if part1 is not None:
                        self.daily[ck]["snap"] = int(float(part1.get("ts") or 0))
                        self.daily[ck]["pend"] = len(part_pend9) if part1.get("pend") is not None else n_est9
                        if part1.get("xs"):
                            self.daily[ck]["xs"] = 1
                    else:
                        self.daily[ck]["why"] = "led" if old1 else "no_snap"
                if entry.get("est"):
                    self.daily[ck]["est"] = entry["est"]
                if entry.get("xc"):
                    self.daily[ck]["xc"] = entry["xc"]
                changed = True
                if hold_qty is not None:
                    e9 = dpx.setdefault(ck, {"p": {}, "k": {}})
                    e9.setdefault("p", {}).update(new_p)
                    e9.setdefault("k", {}).update(new_k)
                    for k9, v9 in new_lp.items():
                        e9.setdefault("lp", {}).setdefault(k9, v9)
                    if e9.get("x") is None:
                        e9["x"], e9["xk"] = round(x_raw9, 2), (x_kind if x_kind in ("live", "seed") else "calc")
                        if xc_raw9 >= 1:
                            e9["xc"] = round(xc_raw9, 2)
                        xu9p = xu_keep(xu_src9) if xu_src9 else {}
                        if xu9p:
                            e9["xu"] = xu9p
                    px_changed = True
        if _capture_px_blocks(self.daily, dpx, lo_bind9) or px_changed:
            changed = True
        if changed:
            self._daily_dirty = True
        if px_changed and frozen_ok:
            self._dpx_dirty = True
        if changed:
            common.atomic_write_json(DAILY_PATH, self.daily)
            self._daily_dirty = False
        if px_changed and frozen_ok:
            lo9 = (today_kst - timedelta(days=DAILY_PX_KEEP)).strftime("%Y-%m-%d")
            for k9 in [k9 for k9 in dpx if not k9.startswith("_") and k9 < lo9]:
                dpx.pop(k9, None)
            common.atomic_write_json(DAILY_PX_PATH, dpx)
            self._dpx_dirty = False
        self.px.flush()
        return days

    def _futures_view(self, fxb=None):
        poss, ev, margin, ts_max, mm = [], [], 0.0, 0, {}
        snapshot_ts, stale_ex = {}, []
        now9 = time.time()
        perp_on = {}
        try:
            perp_on = perp_active()
            if perp_on is None:
                perp_on = dict(self.__dict__.get("_perp_on_last") or {})
            else:
                self.__dict__["_perp_on_last"] = perp_on
        except Exception as e9:
            perp_on = {}
            log.warning("퍼프 덱스 설정 읽기 실패(합류 생략): %s", e9)
        venues = {}
        for ex9 in FUT_CEX + tuple(k9 for k9 in PERP_KEYS if k9 in perp_on):
            try:
                d9 = common.read_json(
                    os.path.join(common.STATE_DIR, f"futures_{ex9}.json"), {})
            except SystemExit:
                log.warning("선물 스냅숏 손상: %s — 이번 빌드에서 제외", ex9)
                continue
            if not d9:
                continue
            if ex9 in perp_on:
                on9 = perp_on[ex9]
                d9 = perp_filter(d9, on9, now9, ex9)
                ac9 = d9["accts"]
                venues[ex9] = {"dex": True, "accts": len(on9), "err": sum(1 for a9 in on9 if (ac9.get(a9) or {}).get("err")),
                               "equity": _fin((d9.get("wallet") or {}).get("equity")),
                               "liq": sum(1 for r9 in d9["events"] if r9.get("liq") and r9.get("kind") == "REALIZED")}
            ts9 = int(d9.get("ts") or 0)
            snapshot_ts[ex9] = ts9
            fresh9 = ts9 > 0 and now9 - ts9 <= 1800
            if fresh9:
                ts_max = max(ts_max, ts9)
            else:
                stale_ex.append(ex9)
            w9 = (d9.get("wallet") or {}) if fresh9 else {}
            margin += _fin(w9.get("balance")) or 0.0
            mb9 = _fin(w9.get("margin_balance")) or 0.0
            mt9 = _fin(w9.get("maint_margin")) or 0.0
            if mb9 > 0 and mt9 >= 0 and w9.get("maint_margin") is not None:
                mm[ex9] = {"ratio": round(mt9 / mb9 * 100, 2),
                           "maint": round(mt9, 2), "balance": round(mb9, 2)}
            for p9 in ((d9.get("positions") or []) if fresh9 else ()):
                if isinstance(p9, dict) and all(_fin(p9.get(k9) or 0) is not None for k9 in ("qty", "entry", "mark", "upnl", "liq")):
                    poss.append(dict(p9, ex=ex9))
            t_hi9 = (now9 + 86400) * 1000
            for r9 in d9.get("events") or []:
                if not isinstance(r9, dict) or r9.get("kind") not in ("REALIZED", "FUNDING", "FEE"):
                    continue
                a9, tt9 = _fin(r9.get("amount") or 0), _fin(r9.get("t"))
                if a9 is None or (tt9 and not (FUT_T_MIN_MS <= tt9 <= t_hi9)):
                    continue
                ev.append(dict(r9, ex=ex9))
        exn = dict({"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX"}, **PERP_NAMES)
        notional = sum(float(p.get("qty") or 0) * float(p.get("mark") or 0) for p in poss)
        upnl = sum(float(p.get("upnl") or 0) for p in poss)
        long_n = sum(float(p.get("qty") or 0) * float(p.get("mark") or 0)
                     for p in poss if p.get("side") == "LONG")
        short_n = notional - long_n
        by_date, rows = {}, []
        by_date_krw = {}
        by_date_ex = {}
        fev9 = []
        for r9 in ev:
            try:
                t9 = int(r9.get("t") or 0)
                amt9 = float(r9.get("amount") or 0)
            except (TypeError, ValueError):
                continue
            if not t9:
                continue
            dt9 = datetime.fromtimestamp(t9 / 1000, KST)
            dk9 = dt9.strftime("%Y-%m-%d")
            by_date[dk9] = by_date.get(dk9, 0) + amt9
            k9 = amt9 * (fxb.rate_at(t9 // 1000) if fxb else float(self.spot.rate or 1384))
            by_date_krw[dk9] = by_date_krw.get(dk9, 0) + k9
            fev9.append((dk9, t9, amt9, k9, r9))
            x9 = by_date_ex.setdefault((dk9, r9.get("ex")), [0.0, 0.0, 0, 0])
            x9[0] += amt9
            x9[1] += k9
            x9[2] += 1 if r9.get("kind") == "REALIZED" else 0
            x9[3] = max(x9[3], t9)
            if r9.get("kind") == "REALIZED":
                rows.append(dict({"t": dt9.strftime("%m-%d %H:%M"), "_ts": t9,
                                  "sym": r9.get("symbol") or "—",
                                  "ex": exn.get(r9.get("ex"), r9.get("ex")),
                                  "pnl": round(amt9, 4)}, **({"liq": True} if r9.get("liq") else {})))
        rows.sort(key=lambda x: -x["_ts"])
        fee9 = []
        for r9 in ev:
            if r9.get("kind") not in ("FEE", "FUNDING"):
                continue
            try:
                t9, amt9 = int(r9.get("t") or 0), float(r9.get("amount") or 0)
            except (TypeError, ValueError):
                continue
            if t9:
                fee9.append({"_ts": t9, "kind": r9.get("kind"), "sym": r9.get("symbol") or "—",
                             "ex": exn.get(r9.get("ex"), r9.get("ex")), "amt": amt9})
        fee9.sort(key=lambda x: -x["_ts"])
        self._fut_detail = {"rows": rows, "fee": fee9}
        self._fut_ev = fev9
        self._fut_accts = {k9: sorted(v9) for k9, v9 in (perp_on or {}).items()}
        fsum = {}
        for x9 in rows:
            k9 = (datetime.fromtimestamp(x9["_ts"] / 1000, KST).strftime("%Y-%m"), x9["sym"], x9["ex"])
            a9 = fsum.setdefault(k9, [0, 0.0, 0.0])
            a9[0] += 1
            if x9["pnl"] > 0:
                a9[1] += x9["pnl"]
            else:
                a9[2] -= x9["pnl"]
        realized_summary = [[k9[0], k9[1], k9[2], v9[0], round(v9[1], 4), round(v9[2], 4)] for k9, v9 in sorted(fsum.items())]
        brk = {"REALIZED": 0.0, "FUNDING": 0.0, "FEE": 0.0}
        wins = losses = 0
        for r9 in ev:
            try:
                amt9 = float(r9.get("amount") or 0)
            except (TypeError, ValueError):
                continue
            brk[r9.get("kind")] = brk.get(r9.get("kind"), 0.0) + amt9
            if r9.get("kind") == "REALIZED":
                if amt9 > 0:
                    wins += 1
                elif amt9 < 0:
                    losses += 1
        pos_out = []
        for p in poss:
            try:
                liq9 = float(p.get("liq") or 0)
                mark9 = float(p.get("mark") or 0)
            except (TypeError, ValueError):
                liq9 = mark9 = 0.0
            dist9 = (round((liq9 - mark9) / mark9 * 100, 2)
                     if liq9 > 0 and mark9 > 0 else None)
            pos_out.append({"ex": exn.get(p.get("ex"), p.get("ex")),
                            "exKey": p.get("ex"), **({"dex": True} if p.get("ex") in PERP_NAMES else {}),
                            "sym": p.get("symbol") or "—",
                            "side": p.get("side") or "",
                            "qty": float(p.get("qty") or 0),
                            "entry": float(p.get("entry") or 0),
                            "mark": mark9,
                            "upnl": round(float(p.get("upnl") or 0), 2),
                            "lev": str(p.get("leverage") or ""),
                            "liq": liq9, "liqDist": dist9})
        return {
            "margin": round(margin, 2), "notional": round(notional, 2),
            "mmRatio": mm,
            "pnlBreak": {"realized": round(brk["REALIZED"], 2),
                         "funding": round(brk["FUNDING"], 2),
                         "fee": round(brk["FEE"], 2),
                         "net": round(brk["REALIZED"] + brk["FUNDING"] + brk["FEE"], 2),
                         "wins": wins, "losses": losses,
                         "winRate": (round(wins / (wins + losses) * 100, 1)
                                     if (wins + losses) else None)},
            "longNotional": round(long_n, 2), "shortNotional": round(short_n, 2),
            "upnl": round(upnl, 2), "posCount": len(poss), "ts": ts_max,
            "snapshotTs": snapshot_ts, "staleExchanges": stale_ex,
            "venues": venues,
            "positions": pos_out,
            "realizedByDate": {k: round(v, 2) for k, v in by_date.items()},
            "realizedKrwByDate": {k: round(v) for k, v in by_date_krw.items()},
            "realizedByDateEx": _fut_by_date_ex(by_date_ex, exn),
            "realizedRows": rows[:60],
            "realizedRowsTotal": len(rows), "realizedSummary": realized_summary,
            "realizedTotal": round(sum(r9["pnl"] for r9 in rows), 2)}

    @staticmethod
    def _impostor_reason(g, has_ca: bool, pairs=None, native: bool = False, priced: bool = True):
        if not has_ca or g.get("is_stable") or g.get("is_fiat"):
            return None
        if _scam_name(g.get("sym")) == "링크·보상 유도 이름":
            return "링크·보상 유도 이름(에어드랍 스캠)"
        if native or g.get("px_seen") or g.get("ex_seen"):
            return None
        if _scam_name(g.get("sym")) == "보상 유도 문구":
            return "보상 유도 문구(에어드랍 스캠)"
        sym9 = str(g.get("sym") or "")
        imp = None if re.fullmatch(r"TOKEN|native:.*|\?", sym9) else spamguard.impostor_of(sym9)
        if imp:
            return f"사칭 심볼 — {imp} 흉내(보이지 않는 글자·유사 글자)"
        fm = spamguard.fake_major(g.get("sym"), pairs)
        if fm:
            return f"가짜 {fm} — 정품 컨트랙트 아님"
        odd = spamguard.odd_symbol(g.get("sym"))
        if odd:
            return f"사칭 문자 — {odd}"
        if g.get("spoof_n"):
            return "가짜 전송 로그 — 내가 서명하지 않은 tx 로 보유한 적 없는 수량을 '보냄'(주소 오염)"
        if g.get("spoof_soft") and not priced:
            return "가짜 전송 로그 — 내가 서명하지 않은 tx 의 '보냄' · 시세 없는 토큰(주소 오염)"
        return None

    @staticmethod
    def _event_hide_reason(e, G, quarantined, ca_gids):
        gid = e.get("_gid")
        if gid is None:
            return None
        if gid in quarantined:
            return (G.get(gid) or {}).get("risk_reason") or "격리(스팸) 자산"
        g = G.get(gid) or {}
        if gid not in ca_gids or g.get("is_stable") or g.get("is_fiat"):
            return None
        imp = spamguard.impostor_of(e.get("sym"))
        return f"사칭 심볼 — {imp} 흉내" if imp else None

    def _signer_map(self, conn, rows) -> dict:
        self._rtxc().sync(conn)
        cache = self._rtxc().signer
        want = {}
        for r in rows:
            if not (r["location"] or "").startswith("wallet:") or (r["source_ns"], r["source_id"]) in cache:
                continue
            if (r["leg_kind"] == "move_out" and (r["source_ns"] or "") != "sol"
                    and r["event"] in ("TRANSFER_OUT", "BRIDGE", "TRANSFER_SELF", "TRANSFER_OUT_EX")) \
                    or (r["leg_kind"] == "acq" and r["event"] in ("TRANSFER_IN", "PROGRAM_IN")):
                want.setdefault(r["source_ns"], set()).add(r["source_id"])
        return self._rtxc().signer_fill(conn, want)

    @property
    def _signer_cache(self):
        return self._rtxc().signer

    @staticmethod
    def _tx_signer(conn, chain, txh):
        try:
            r9 = conn.execute("SELECT " + rawtx_cache.signer_cols(chain) + " FROM raw_txs WHERE chain=? AND txhash=? AND json_valid(snapshot)",
                              (chain, txh)).fetchone()
            return (r9[0], r9[1], r9[2]) if r9 else None
        except Exception:
            return None

    def _risk_wl_hit(self, conn, g, wl) -> bool:
        my9 = set()
        for w9 in self._hist_wallets():
            my9.add(w9["address"] if w9.get("type") == "sol" else w9["address"].lower())
        for ch9, txh9, ca9 in (g.get("risk_srcs") or [])[:50]:
            row9 = conn.execute("SELECT snapshot FROM raw_txs WHERE chain=? AND txhash=?",
                                (ch9, txh9)).fetchone()
            if not row9:
                continue
            try:
                snap9 = json.loads(row9["snapshot"])
            except json.JSONDecodeError:
                continue
            for tt9 in snap9.get("token_transfers") or []:
                tok9 = tt9.get("token") or {}
                ca_t9 = (tok9.get("address") or tok9.get("address_hash") or "").lower()
                if ca_t9 != (ca9 or "").lower():
                    continue
                to9 = tt9.get("to")
                to9 = ((to9.get("hash") if isinstance(to9, dict) else to9) or "").lower()
                fr9 = tt9.get("from")
                fr9 = ((fr9.get("hash") if isinstance(fr9, dict) else fr9) or "").lower()
                if to9 in my9 and fr9 in wl:
                    return True
        return False

    CEX_PX_ORDER = ("binance", "bybit", "okx", "gate", "kucoin", "upbit", "bithumb")
    PRE_DIVERGE = 2.0
    _CEX_FAIL_STATES = {"CANCELLED", "CANCELED", "FAILED", "FAIL", "REJECTED", "REJECT", "REFUNDED"}

    def _cex_proof(self, conn) -> dict:
        try:
            sig = (tuple(conn.execute("SELECT COUNT(*), MAX(observed_at) FROM raw_ex WHERE kind IN ('deposit','withdraw')").fetchone()),
                   conn.execute("SELECT MAX(posting_id) FROM postings").fetchone()[0])
        except Exception:
            sig = None
        cache = self.__dict__.get("_cex_proof_cache")
        if cache and sig is not None and cache[0] == sig:
            return cache[1]
        by_tx = {}
        last = {}
        for r in conn.execute("SELECT exchange, kind, uuid, revision, payload FROM raw_ex WHERE kind IN ('deposit','withdraw')").fetchall():
            k9 = (r["exchange"], r["kind"], r["uuid"])
            if k9 not in last or r["revision"] > last[k9][0]:
                last[k9] = (r["revision"], r["payload"])
        for (ex0, kind0, _u0), (_rv0, pl0) in last.items():
            try:
                pl = json.loads(pl0)
            except (TypeError, ValueError):
                continue
            tx = str(pl.get("txid") or "").strip()
            cur = str(pl.get("currency") or "").strip().upper()
            if not tx or not cur or str(pl.get("state") or "").upper() in self._CEX_FAIL_STATES:
                continue
            if re.fullmatch(r"(0x)?[0-9a-fA-F]{64}", tx):
                tx = ("0x" + tx[-64:]).lower()
            by_tx.setdefault(tx, []).append((ex0, kind0, cur))
        proof = {}
        candidates = {}
        ids = list(by_tx)
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            for r in conn.execute(
                    "SELECT p.source_id, p.qty_base, a.symbol, a.group_id FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
                    " WHERE p.source_kind = 'chain_tx' AND a.kind = 'token' AND a.group_id IS NOT NULL"
                    " AND p.location LIKE 'wallet:%%' AND p.source_id IN (%s)" % ",".join("?" * len(part)), part).fetchall():
                out9 = str(r["qty_base"] or "").startswith("-")
                for ex, kind, cur in by_tx.get(r["source_id"]) or ():
                    if (kind == "deposit") != out9:
                        continue
                    if not acct_norm.same_asset(r["symbol"], None, cur, ex):
                        continue
                    candidates.setdefault((r["source_id"], ex, kind, cur), set()).add(r["group_id"])
        for (_tx, ex, _kind, cur), gids in candidates.items():
            if len(gids) != 1:
                continue
            proof.setdefault(next(iter(gids)), set()).add((ex, cur))
        order = {e: i for i, e in enumerate(self.CEX_PX_ORDER)}
        out = {gid: sorted(v, key=lambda x: (order.get(x[0], 99), x[0], x[1])) for gid, v in proof.items()}
        self.__dict__["_cex_proof_cache"] = (sig, out)
        return out

    def _transfer_out_dest(self, conn) -> dict:
        if getattr(self, "_todst_at", 0) > time.time() - 60:
            return self._todst
        out = dict(getattr(self, "_todst", {}) or {})
        try:
            with open(DM_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            lines = []
        for ln in lines:
            if '"TRANSFER_OUT"' not in ln:
                continue
            try:
                d = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if d.get("kind") != "TRANSFER_OUT":
                continue
            pl = d.get("payload") or {}
            lbl = self._dest_label(pl)
            for aid_s in (pl.get("deltas") or {}):
                try:
                    row = conn.execute(
                        "SELECT symbol FROM assets WHERE asset_id=?", (int(aid_s),)).fetchone()
                except Exception:
                    row = None
                if row and row["symbol"]:
                    sym9 = row["symbol"].upper()
                    ts9d = d.get("event_ts") or d.get("ts")
                    prev9 = out.get(sym9) or {}
                    tls9d = list(prev9.get("ts_list") or [])
                    if ts9d and ts9d not in tls9d:
                        tls9d = tls9d + [ts9d]
                    nots9 = bool(prev9.get("no_ts")) or not ts9d
                    out[sym9] = {"label": lbl, "to": pl.get("to"),
                                 "ts": ts9d, "ts_list": tls9d, "no_ts": nots9}
        self._todst, self._todst_at = out, time.time()
        return out

    def _dest_label(self, pl: dict) -> str:
        cands = [str(pl.get("to") or "")] + [str(x) for x in (pl.get("counterparties") or [])]
        cands = [c.lower() if c.startswith("0x") else c for c in cands if c]
        if not cands:
            return "미상"
        for c in cands:
            ex9 = self._ex_addr_index().get(c)
            if ex9:
                return {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX",
                        "kucoin": "쿠코인", "gate": "게이트", "bithumb": "빗썸",
                        "upbit": "업비트", "hyperliquid": "Hyperliquid"}.get(ex9, ex9)
            if c in self.addr_label:
                return f"내 지갑({self.addr_label[c]})"
        return "미등록 외부주소"

    def _ex_addr_index(self) -> dict:
        if getattr(self, "_exidx_at", 0) > time.time() - 60:
            return self._exidx
        idx = {}
        for e in self.cfg.get("exchange_addresses", []):
            a = str(e.get("address") or "")
            if a:
                idx[a.lower() if a.startswith("0x") else a] = e.get("exchange") or "?"
        try:
            for a, labs in depaddr.hint_index().items():
                if labs:
                    idx.setdefault(a, labs[0][0])
        except Exception:
            pass
        self._exidx, self._exidx_at = idx, time.time()
        return idx

    DM_KINDS = {"NEW_ASSET": "새 자산 검토", "UNKNOWN": "분류 보류",
                "TRANSFER_OUT": "외부 전송 확인", "POISON": "처리 실패",
                "PROGRAM_IN": "프로그램 수령 검토", "RECON": "기초잔고 대사"}

    def _dm_records(self) -> list:
        try:
            st = os.stat(DM_PATH)
        except OSError:
            self._dm_cache = None
            return []
        c = getattr(self, "_dm_cache", None)
        if not c or c["ino"] != st.st_ino or st.st_size < c["off"]:
            c = {"ino": st.st_ino, "off": 0, "recs": []}
        if st.st_size > c["off"]:
            try:
                with open(DM_PATH, "rb") as f:
                    f.seek(c["off"])
                    buf = f.read(st.st_size - c["off"])
            except OSError:
                return list(c["recs"])
            end = buf.rfind(b"\n") + 1
            for ln in buf[:end].splitlines():
                if b'"kind"' not in ln:
                    continue
                try:
                    d = json.loads(ln.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    continue
                if isinstance(d, dict) and d.get("kind") in self.DM_KINDS and d.get("kind") != "TRANSFER_OUT":
                    c["recs"].append(d)
            c["off"] += end
        self._dm_cache = c
        return list(c["recs"])

    def _pendings(self, conn, prefs) -> list:
        ignored = set(prefs.get("ignored", []))
        out = []
        seen = set()
        kind_map = self.DM_KINDS
        for d in reversed(self._dm_records()):
            k = d.get("kind")
            if k == "RECON":
                continue
            pl = d.get("payload") or {}
            key = f"{k}:{pl.get('txhash') or d.get('ts')}"
            if key in seen or key in ignored:
                continue
            seen.add(key)
            if k in ("TRANSFER_OUT", "PROGRAM_IN", "UNKNOWN") and pl.get("txhash") and pl.get("chain"):
                ev9 = conn.execute("SELECT event FROM tx_class WHERE chain=? AND txhash=?",
                                   (pl.get("chain"), str(pl.get("txhash")).lower())).fetchone()
                if ev9 and str(ev9["event"] or "").startswith("LP_"):
                    continue
            ch = pl.get("chain", "—")
            out.append({
                "key": key,
                "t": datetime.fromtimestamp(d.get("ts", 0), KST).strftime("%m-%d %H:%M"),
                "kind": kind_map[k], "sym": "—", "chain": CHAIN_NAME.get(ch, ch), "chainKey": ch,
                "onchain": (pl.get("txhash") or "—"),
                "ex": self._dest_label(pl) if k == "TRANSFER_OUT" else "—",
                "gap": _PEND_GAP.get(k) or _human_dm(d.get("text", ""))[:60],
                "why": (f"{self._dest_label(pl)}({_short_addr(pl.get('to'))})로 나간 전송입니다. 내 지갑이면 설정 › 연결 · 키에서 추가하고,"
                        " 외부로 보낸 게 맞으면 무시해도 됩니다." if k == "TRANSFER_OUT" else
                        "컨트랙트(프로그램)를 거쳐 들어온 토큰입니다. 스왑 체결인지 에어드랍인지 확인해 주세요." if k == "PROGRAM_IN" else
                        _human_dm(d.get("text", ""))),
                "to": pl.get("to") if k == "TRANSFER_OUT" else None,
                "tx": pl.get("txhash"),
                "cands": [],
            })
        rows = conn.execute(
            "SELECT t.transfer_id, t.qty_base, t.chain_txhash, t.updated_at, a.symbol, a.chain,"
            " a.decimals FROM transfers t JOIN assets a ON a.asset_id = t.asset_id"
            " WHERE t.state='sent' ORDER BY t.updated_at DESC").fetchall()
        for r in rows:
            dec = r["decimals"] if r["decimals"] is not None else 18
            qty = float(Decimal(int(r["qty_base"])) / Decimal(10) ** int(dec))
            key = f"sent:{r['transfer_id']}"
            if key in ignored:
                continue
            out.append({
                "key": key,
                "t": datetime.fromtimestamp(r["updated_at"], KST).strftime("%m-%d %H:%M"),
                "kind": "입금 기록 없음", "sym": r["symbol"] or "?",
                "chain": CHAIN_NAME.get(r["chain"], r["chain"]),
                "onchain": f"추적지갑 → 업비트 입금주소 · {qty:,.4f} {r['symbol'] or ''}",
                "ex": "—", "gap": "거래소 API 미연결 — 입금 확인 대기",
                "why": "업비트 조회 키가 아직 등록되지 않아 입금 확인을 못 합니다. 키 등록 후 자동 매칭됩니다.",
                "cands": [],
            })
        return out

    @staticmethod
    def _day_index(pos_ev_full, extra_vis, extra_hid, lp_events):
        ix, acts = {}, {}

        def add(kind, e, meta):
            try:
                ts = int(e.get("_ts") or 0)
            except (TypeError, ValueError):
                ts = 0
            if ts <= 0:
                return
            d = acct_norm.iso_day(ts)
            ix.setdefault(d, []).append((ts, kind, e, meta))
            a = acts.get(d)
            if a is None:
                a = acts[d] = {"n": 0, "b": 0, "s": 0, "dep": 0, "h": 0, "src": {}}
            if kind == "hidden":
                a["h"] += 1
                return
            k = str(e.get("k") or "")
            if k == "평단 갱신":
                return
            j = 2 if "매도" in k else (1 if "매수" in k else 0)
            c = a["src"].setdefault(e.get("src") or "", [0, 0, 0, 0])
            a["n"] += 1; c[0] += 1
            if j:
                a["b" if j == 1 else "s"] += 1; c[j] += 1
            if k == "입금 확인":
                a["dep"] += 1; c[3] += 1
        for pkey, sym, chain, evs in pos_ev_full:
            meta = (pkey, sym, chain)
            for e in evs:
                add("pos", e, meta)
        for e in extra_vis:
            add("extra", e, None)
        for e in extra_hid:
            add("hidden", e, None)
        for e in lp_events:
            add("lp", e, None)
        for d, rows in ix.items():
            a = acts.get(d)
            if a is None:
                continue
            buys = set()
            for _ts, kind, e, _m in rows:
                if kind != "hidden" and str(e.get("k") or "") == "온체인 매수" and "지불" in str(e.get("d") or "") and e.get("tx"):
                    buys.add((e.get("src") or "", e.get("tx")))
            pay, sp = 0, {}
            if buys:
                for _ts, kind, e, _m in rows:
                    if kind != "hidden" and str(e.get("k") or "") == "온체인 매도" and ((e.get("src") or ""), e.get("tx")) in buys:
                        pay += 1
                        sk = e.get("src") or ""
                        sp[sk] = sp.get(sk, 0) + 1
            a["pay"] = pay
            if sp:
                a["srcPay"] = sp
        return ix, {d: acts[d] for d in sorted(acts)}

    @staticmethod
    def _stab_index(stab_ev, acts):
        ix = {}
        for pkey, sym, chain, evs in stab_ev:
            meta = (pkey, sym, chain)
            for e in evs:
                if "매도" not in str(e.get("k") or ""):
                    continue
                try:
                    ts = int(e.get("_ts") or 0)
                except (TypeError, ValueError):
                    ts = 0
                if ts <= 0:
                    continue
                d = acct_norm.iso_day(ts)
                ix.setdefault(d, []).append((ts, e, meta))
                if e.get("_conv"):
                    a = acts.get(d)
                    if a is None:
                        a = acts[d] = {"n": 0, "b": 0, "s": 0, "dep": 0, "h": 0, "src": {}}
                    a["cv"] = int(a.get("cv") or 0) + 1
                    sk = e.get("src") or ""
                    cs = a.setdefault("cvSrc", {})
                    cs[sk] = int(cs.get(sk) or 0) + 1
        return ix

    @staticmethod
    def _conv_out(e, ts, d, meta):
        o = {k: v for k, v in e.items() if not k.startswith("_")}
        o["k"] = e.get("_conv") or "스테이블 교환"
        o["ts"], o["iso"], o["kind"] = ts, d, "conv"
        o["sym"], o["chain"] = meta[1], meta[2]
        return o

    def _conv_rows(self, idx, d_from, d_to):
        out = []
        for d, lst in (idx.get("stab") or {}).items():
            if d_from <= d <= d_to:
                out.extend(self._conv_out(e, ts, d, meta) for ts, e, meta in lst if e.get("_conv"))
        out.sort(key=lambda o: -o["ts"])
        return out

    def _krw_day_index(self, conn, acts):
        try:
            kf9 = self._krw_flows(conn)
        except Exception as e9:
            log.warning("그날 기록 원화 입출금 색인 실패(목록에서 빠짐): %s", e9)
            kf9 = None
        ix = {}
        for r9 in ((kf9 or {}).get("rows") or ()):
            try:
                key9 = str(r9.get("key") or "")
                if r9.get("st") != "done" or key9.startswith("upbit:withdraw:"):
                    continue
                ex9 = key9.split(":", 1)[0]
                ts9, amt9, fee9 = int(r9["t"]), int(r9["amt"]), int(r9.get("fee") or 0)
                exn9 = str(r9.get("ex") or ex9)
            except (TypeError, ValueError, KeyError):
                continue
            if ts9 <= 0 or amt9 <= 0:
                continue
            if r9.get("src") == "int":
                d9 = f"{exn9} 원화 지급 · {r9.get('note') or '거래소 내부 지급'} (은행 아님)"
            elif r9.get("dir") == "in":
                d9 = f"{exn9} 입금 ← 은행 (원화 입금)"
            else:
                d9 = f"{exn9} 출금 → 은행 (원화 출금" + (f" · 수수료 ₩{fee9:,}" if fee9 else "") + ")"
            e9 = {"t": datetime.fromtimestamp(ts9, KST).strftime("%m-%d %H:%M"), "sym": "KRW", "k": "전송", "d": d9,
                  "q": f"{amt9:,}", "a": f"₩{amt9:,}", "tx": "—", "src": f"ex:{ex9}"}
            d = acct_norm.iso_day(ts9)
            ix.setdefault(d, []).append((ts9, e9))
            a = acts.get(d)
            if a is None:
                a = acts[d] = {"n": 0, "b": 0, "s": 0, "dep": 0, "h": 0, "src": {}}
            a["kw"] = int(a.get("kw") or 0) + 1
            ks9 = a.setdefault("kwSrc", {})
            ks9[e9["src"]] = int(ks9.get(e9["src"]) or 0) + 1
        return ix

    @staticmethod
    def _krw_rows(idx, d_from, d_to):
        out = []
        for d, lst in (idx.get("krw") or {}).items():
            if d_from <= d <= d_to:
                for ts, e in lst:
                    o = dict(e)
                    o["ts"], o["iso"], o["kind"] = ts, d, "krw"
                    out.append(o)
        out.sort(key=lambda o: -o["ts"])
        return out

    DAY_EV_LIMIT_MAX = 20000

    def day_events(self, d_from, d_to, limit=None, offset=0):
        idx = getattr(self, "_day_idx", None)
        if not idx:
            return None
        if limit is not None:
            return self._day_events_page(idx, d_from, d_to, int(limit), int(offset or 0))
        ix = idx["ix"]
        days = sorted(d for d in ix if d_from <= d <= d_to)
        vis, hid, per = [], [], {}
        for d in days:
            a = {"n": 0, "b": 0, "s": 0, "dep": 0, "h": 0}
            for ts, kind, e, meta in ix[d]:
                o = {k: v for k, v in e.items() if not k.startswith("_")}
                o["ts"], o["iso"], o["kind"] = ts, d, kind
                if meta is not None:
                    o["pkey"], o["sym"], o["chain"] = meta
                (hid if kind == "hidden" else vis).append(o)
            per[d] = {"realized": round(float(idx["rbd"].get(d) or 0), 2),
                      "realizedFut": round(float(idx["fut"].get(d) or 0), 2)}
        vis.sort(key=lambda o: -o["ts"])
        hid.sort(key=lambda o: -o["ts"])
        try:
            spamguard.annotate(vis)
            spamguard.annotate(hid)
        except Exception as e9:
            log.warning("심볼 정리 실패(무시): %s", e9)
        counts = {}
        for o in vis:
            counts[o.get("k") or "?"] = counts.get(o.get("k") or "?", 0) + 1
        return {"ok": True, "from": d_from, "to": d_to, "builtAt": idx["builtAt"], "n": len(vis),
                "counts": counts, "days": per, "events": vis, "hidden": hid,
                "conv": self._conv_rows(idx, d_from, d_to),
                "krw": StateBuilder._krw_rows(idx, d_from, d_to)}

    def _day_events_page(self, idx, d_from, d_to, limit, offset):
        ix = idx["ix"]
        limit = max(1, min(self.DAY_EV_LIMIT_MAX, limit))
        offset = max(0, offset)
        days = sorted((d for d in ix if d_from <= d <= d_to), reverse=True)
        per, counts, n_vis, n_hid, hid_kinds = {}, {}, 0, 0, {}
        for d in days:
            for ts, kind, e, meta in ix[d]:
                if kind == "hidden":
                    n_hid += 1
                    hk = str(e.get("hideKind") or "?")
                    hid_kinds[hk] = hid_kinds.get(hk, 0) + 1
                else:
                    n_vis += 1
                    k9 = e.get("k") or "?"
                    counts[k9] = counts.get(k9, 0) + 1
            per[d] = {"realized": round(float(idx["rbd"].get(d) or 0), 2),
                      "realizedFut": round(float(idx["fut"].get(d) or 0), 2)}
        vis, hid = [], []
        need_v, need_h = offset + limit, (limit if offset == 0 else 0)
        for d in days:
            if len(vis) >= need_v and len(hid) >= need_h:
                break
            dv, dh = [], []
            for ts, kind, e, meta in ix[d]:
                if kind == "hidden" and len(hid) >= need_h:
                    continue
                if kind != "hidden" and len(vis) >= need_v:
                    continue
                o = {k: v for k, v in e.items() if not k.startswith("_")}
                o["ts"], o["iso"], o["kind"] = ts, d, kind
                if meta is not None:
                    o["pkey"], o["sym"], o["chain"] = meta
                (dh if kind == "hidden" else dv).append(o)
            dv.sort(key=lambda o: -o["ts"])
            dh.sort(key=lambda o: -o["ts"])
            vis.extend(dv)
            hid.extend(dh)
        vis = vis[offset:offset + limit]
        hid = hid[:need_h]
        try:
            spamguard.annotate(vis)
            spamguard.annotate(hid)
        except Exception as e9:
            log.warning("심볼 정리 실패(무시): %s", e9)
        return {"ok": True, "from": d_from, "to": d_to, "builtAt": idx["builtAt"], "n": n_vis, "counts": counts, "days": per,
                "events": vis, "hidden": hid, "nHidden": n_hid, "hiddenKinds": hid_kinds,
                "offset": offset, "limit": limit, "more": offset + len(vis) < n_vis}

    TAX_ROWS_MAX = 2000

    def tax_rows(self, ym, sym, offset=0):
        idx = getattr(self, "_day_idx", None)
        if not idx or idx.get("tax") is None:
            return None
        today9 = idx.get("taxToday")
        if sym and (sym.endswith(" 무기한") or sym == FUT_FEE_SYM):
            return self._tax_rows_fut(idx, ym, sym, offset)
        rows = [r for r in idx["tax"] if (not sym or (r.get("sym") or "?") == sym) and acct_norm.month_of(r.get("sold"), today9) == ym]
        rows.sort(key=lambda r: str(r.get("sold") or ""), reverse=True)
        off9 = max(0, int(offset or 0))
        yms9 = idx.get("_taxYms")
        if yms9 is None:
            yms9 = idx["_taxYms"] = sorted({m9 for m9 in (acct_norm.month_of(r.get("sold"), today9) for r in idx["tax"] if not r.get("fut")) if m9})
        return {"ok": True, "ym": ym, "sym": sym, "builtAt": idx["builtAt"], "total": len(rows), "offset": off9, "yms": yms9,
                "rows": [self._tax_row_out(r) for r in rows[off9:off9 + self.TAX_ROWS_MAX]]}

    def _tax_rows_fut(self, idx, ym, sym, offset=0):
        fd = idx.get("futDetail") or {}
        out = []
        if sym == FUT_FEE_SYM:
            for x9 in fd.get("fee") or []:
                dt9 = datetime.fromtimestamp(x9["_ts"] / 1000, KST)
                if dt9.strftime("%Y-%m") != ym:
                    continue
                out.append({"sold": dt9.strftime("%Y-%m-%d"), "t": dt9.strftime("%H:%M"), "sym": sym, "ticker": str(x9["sym"]) + " · 선물",
                            "ex": str(x9["ex"] or "선물") + (" 펀딩" if x9["kind"] == "FUNDING" else " 수수료"),
                            "qty": 0, "acq": 0, "disp": 0, "fee": round(-x9["amt"], 4), "fut": True, "futFee": True})
        else:
            for x9 in fd.get("rows") or []:
                dt9 = datetime.fromtimestamp(x9["_ts"] / 1000, KST)
                if dt9.strftime("%Y-%m") != ym or fut_sym(x9.get("sym")) != sym:
                    continue
                p9 = float(x9.get("pnl") or 0)
                out.append({"sold": dt9.strftime("%Y-%m-%d"), "t": dt9.strftime("%H:%M"), "sym": sym, "ticker": str(x9.get("sym")) + " · 선물",
                            "ex": x9.get("ex"), "qty": 0, "acq": -p9 if p9 < 0 else 0, "disp": p9 if p9 > 0 else 0, "fee": 0, "fut": True,
                            **({"liq": True} if x9.get("liq") else {})})
        off9 = max(0, int(offset or 0))
        return {"ok": True, "ym": ym, "sym": sym, "builtAt": idx["builtAt"], "total": len(out), "offset": off9, "fut": True,
                "rows": out[off9:off9 + self.TAX_ROWS_MAX]}

    @staticmethod
    def _tax_row_out(r):
        o = {k: v for k, v in r.items() if not k.startswith("_")}
        for k9, x9 in (("_acq", "xa"), ("_disp", "xd"), ("_fee", "xf")):
            v9 = r.get(k9)
            if isinstance(v9, (int, float)) and v9 == v9 and abs(v9) != float("inf"):
                o[x9] = v9
        return o

    RECEIPT_FILLS_MAX = 400

    def receipt(self, iso, sym):
        idx = getattr(self, "_day_idx", None)
        if not idx or idx.get("pos") is None:
            return None
        import review_daily as rd
        raw = []
        for ts, kind, e, meta in (idx["ix"].get(iso) or ()):
            if kind == "hidden":
                continue
            o = {k: v for k, v in e.items() if not k.startswith("_")}
            o["ts"], o["kind"] = ts, kind
            if meta is not None:
                o["pkey"], o["sym"], o["chain"] = meta
            raw.append(o)
        def _norm_px(raw9):
            n9 = rd._norm_events(raw9, iso)
            for o9, i9 in zip(n9, sorted(range(len(raw9)), key=lambda i: int(raw9[i].get("ts") or 0))):
                try:
                    un9 = float(raw9[i9].get("un")) if raw9[i9].get("un") not in (None, "") else None
                except (TypeError, ValueError):
                    un9 = None
                if un9 and un9 > 0 and o9.get("q"):
                    o9["_px"] = un9
                    inf9 = float(o9["q"]) * un9
                    if o9.get("usd") is not None and abs(inf9 - float(o9["usd"])) <= 0.005 + 1e-9:
                        o9["_usd"] = inf9
            return n9
        norm = _norm_px(raw)
        pos = [p for p in idx["pos"] if p.get("kind") != "gas"]
        syms9 = {o["sym"] for o in norm if not o["lp"]} | {p.get("sym") for p in pos if (p.get("realizedByDay") or {}).get(iso)}
        canon = rd._canon_map(syms9)
        want = canon.get(sym, sym)
        raw_syms = {s for s in (syms9 | {sym}) if s and canon.get(s, s) == want}
        for o in norm:
            if o["sym"] in canon:
                o["sym_raw"], o["sym"] = o["sym"], canon[o["sym"]]
        rd._mark_dca(norm)
        ev = [o for o in norm if not o["lp"] and o["sym"] == want]
        st_raw = []
        for ts, e, meta in ((idx.get("stab") or {}).get(iso) or ()):
            if meta[1] not in raw_syms:
                continue
            o = {k: v for k, v in e.items() if not k.startswith("_")}
            o["ts"], o["kind"] = ts, "stab"
            o["pkey"], o["sym"], o["chain"] = meta
            if e.get("_conv"):
                o["conv"] = str(e["_conv"])
            st_raw.append(o)
        if st_raw:
            st_norm = _norm_px(st_raw)
            for o9, i9 in zip(st_norm, sorted(range(len(st_raw)), key=lambda i: int(st_raw[i].get("ts") or 0))):
                if st_raw[i9].get("conv"):
                    o9["conv"] = st_raw[i9]["conv"]
            for o in st_norm:
                if o["sym"] != want:
                    o["sym_raw"], o["sym"] = o["sym"], want
            rd._mark_dca(st_norm)
            ev = sorted(ev + st_norm, key=lambda o: o["ts"])
        cards = [p for p in pos if p.get("sym") in raw_syms and (p.get("realizedByDay") or {}).get(iso)]
        r_usd = sum(float((p.get("realizedByDay") or {}).get(iso) or 0) for p in cards)
        rk = [(p.get("realizedKrwByDay") or {}).get(iso) for p in cards]
        r_krw = sum(float(x) for x in rk) if cards and all(x is not None for x in rk) else None
        if not ev and not cards:
            return {"ok": True, "empty": True, "date": iso, "sym": sym, "builtAt": idx["builtAt"]}
        sells = [o for o in ev if o["side"] == "sell"]
        buys = [o for o in ev if o["side"] == "buy"]
        deps = [o for o in ev if o["k"] == "입금 확인"]
        tx9 = [r for r in (idx.get("tax") or ()) if r.get("sold") == iso and (r.get("sym") or "?") in raw_syms]
        disp = sum(float(r.get("_disp", r.get("disp")) or 0) for r in tx9)
        disp_krw = sum(float(r.get("_disp", r.get("disp")) or 0) * float(r.get("rate") or 0) for r in tx9) if tx9 and all(r.get("rate") for r in tx9) else None
        tpnl = sum(float(r.get("_disp", r.get("disp")) or 0) - float(r.get("_acq", r.get("acq")) or 0) - float(r.get("fee") or 0) for r in tx9)
        acq_krw = sum(float(r.get("_akr", r.get("akr")) if r.get("_akr", r.get("akr")) is not None
                            else float(r.get("_acq", r.get("acq")) or 0) * float(r.get("rate") or 0)) for r in tx9) if disp_krw is not None else None
        fee_krw = sum(float(r.get("fee") or 0) * float(r.get("rate") or 0) for r in tx9) if disp_krw is not None else None
        pnl_krw = (disp_krw - acq_krw - fee_krw) if disp_krw is not None else None
        fb_n = sum(1 for r in tx9 if "폴백" in str(r.get("ex") or ""))
        recon = bool(tx9) and abs(tpnl - r_usd) <= max(1.0, 0.01 * abs(r_usd))
        rate_by_q = {}
        for r in tx9:
            if r.get("rate"):
                rate_by_q.setdefault(round(float(r.get("qty") or 0), 4), []).append(float(r["rate"]))
        usd_of = lambda o: o["_usd"] if o.get("_usd") is not None else (o["usd"] or 0)
        sq = sum(o["q"] or 0 for o in sells)
        su = sum(usd_of(o) for o in sells)
        uq = sum(rd._unknown_of(o)[0] for o in sells)
        is_pay = lambda o: "스왑 지불" in o["d"] or "대금 지불" in o["d"]
        pays = [o for o in sells if is_pay(o)]
        convs = [o for o in sells if o.get("conv") and not is_pay(o)]
        fl = []
        for o in sells:
            rq = rate_by_q.get(round(float(o["q"] or 0), 4))
            u9 = usd_of(o)
            px9 = o.get("_px") or (u9 / o["q"] if o["q"] and u9 else None)
            f9 = {"ts": o["ts"], "q": rd._r(o["q"]), "usd": rd._r(u9), "px": rd._r(px9) if px9 else None,
                  "v": o["v"], "rate": rq.pop(0) if rq else None, "unk": rd._r(rd._unknown_of(o)[0]) or None}
            if is_pay(o):
                f9["pay"] = True
            elif o.get("conv"):
                f9["conv"] = o["conv"]
            fl.append(f9)
        if len(fl) > self.RECEIPT_FILLS_MAX:
            keep = sorted(range(len(fl)), key=lambda i: -(fl[i]["usd"] or 0))[:self.RECEIPT_FILLS_MAX]
            fl = [fl[i] for i in sorted(keep)]
        bk = {}
        for o in buys:
            bk[o["k"]] = bk.get(o["k"], 0) + 1
        bq = sum(o["q"] or 0 for o in buys)
        bu = sum(o["usd"] or 0 for o in buys)
        nd = [o for o in buys if not o.get("dca")]
        sn = [o for o in sells if not o.get("dca")]
        dep_same = [o for o in deps if sn and o["v"] == sn[0]["v"] and o["ts"] <= sn[0]["ts"]]
        d0 = dep_same[0] if dep_same else (deps[0] if deps else None)
        tts = {}
        if nd and (not sn or nd[0]["ts"] <= sn[-1]["ts"]):
            tts["first_buy"] = nd[0]["ts"]
        if d0:
            tts["deposit"] = d0["ts"]
        if sn:
            tts["first_sell"], tts["last_sell"] = sn[0]["ts"], sn[-1]["ts"]
        out = {"ok": True, "date": iso, "sym": want, "aliases": sorted(raw_syms - {want}), "builtAt": idx["builtAt"],
               "realized": {"usd": round(r_usd, 2), "krw": round(r_krw) if r_krw is not None else None, "cards": len(cards)},
               "sell": {"n": len(sells), "qty": rd._r(sq), "usd": rd._r(su), "vwap": rd._r(su / sq) if sq else None,
                        "pay": {"n": len(pays), "qty": rd._r(sum(o["q"] or 0 for o in pays)), "usd": rd._r(sum(usd_of(o) for o in pays))},
                        "conv": {"n": len(convs), "qty": rd._r(sum(o["q"] or 0 for o in convs)), "usd": rd._r(sum(usd_of(o) for o in convs))},
                        "costKnownPct": round(100.0 * (1 - uq / sq), 1) if sq else None,
                        "venues": sorted({o["v"] for o in sells}), "krwMarket": any(o["v"] in rd.KRW_MARKETS for o in sells)},
               "buy": {"n": len(buys), "qty": rd._r(bq), "usd": rd._r(bu), "vwap": rd._r(bu / bq) if bq else None, "kinds": bk,
                       "venues": sorted({o["v"] for o in buys})},
               "dep": {"n": len(deps), "qty": rd._r(sum(o["q"] or 0 for o in deps)),
                       "first": {"ts": d0["ts"], "q": rd._r(d0["q"]), "v": d0["v"], "carry": "원가 승계" in d0["d"]} if d0 else None},
               "tax": {"n": len(tx9), "fb": fb_n, "disp": round(disp, 2), "dispKrw": round(disp_krw) if disp_krw is not None else None,
                       "recon": recon, "diff": round(tpnl - r_usd, 2),
                       "acqKrw": round(acq_krw) if acq_krw is not None else None, "feeKrw": round(fee_krw) if fee_krw is not None else None,
                       "pnlKrw": round(pnl_krw) if pnl_krw is not None else None,
                       "fxDiffKrw": round(pnl_krw - r_krw) if (pnl_krw is not None and r_krw is not None) else None},
               "path": rd._timeline(ev), "pathTs": tts, "fills": fl, "fillsTotal": len(sells)}
        if not buys and cards:
            cr = rd._carry({"positions": pos}, raw_syms, iso, None, rd._carry_src_keys(raw, raw_syms))
            if cr:
                out["carry"] = cr
        return out

    CHART_CACHE_MAX = 32
    CHART_TTL_S = 600
    CHART_BUDGET_S = 75.0
    _DEX_CHAIN_PREF = ("eth", "bsc", "base", "sol", "arbitrum", "polygon", "optimism")

    def _sell_rows(self, iso, raw_syms):
        idx = getattr(self, "_day_idx", None) or {}
        out = []
        for ts, kind, e, meta in ((idx.get("ix") or {}).get(iso) or ()):
            if kind != "pos" or meta is None or meta[1] not in raw_syms:
                continue
            k9, d9 = str(e.get("k") or ""), str(e.get("d") or "")
            if "매도" not in k9 or "스왑 지불" in d9 or "대금 지불" in d9 or not e.get("_pid"):
                continue
            try:
                q9 = float(str(e.get("q") or "0").replace(",", ""))
            except ValueError:
                continue
            un9 = sellchart._f(e.get("un"))
            u9 = sellchart._f(str(e.get("a") or "").replace("$", ""))
            if q9 <= 0:
                continue
            out.append((int(ts), q9, (un9 * q9) if un9 else (u9 or 0.0), un9 or ((u9 / q9) if u9 else None), int(e["_pid"])))
        return out

    def _sell_specs(self, pids):
        out, gtok = {}, {}
        if not pids:
            return out, gtok
        conn = dbm.open_db(common.DB_PATH, readonly=True)
        try:
            rows = []
            pl = sorted(set(pids))
            for i in range(0, len(pl), 400):
                ch9 = pl[i:i + 400]
                rows += conn.execute(
                    "SELECT p.posting_id, p.source_ns, p.source_id, a.chain, a.address, a.symbol, a.group_id FROM postings p"
                    " JOIN assets a ON a.asset_id = p.asset_id WHERE p.posting_id IN (%s)" % ",".join("?" * len(ch9)), ch9).fetchall()
            groups = set()
            for r in rows:
                ns = str(r["source_ns"] or "")
                payload = snap = None
                if ":" in ns:
                    ex9, kd9 = ns.split(":", 1)
                    x9 = conn.execute("SELECT payload FROM raw_ex WHERE exchange=? AND kind=? AND uuid=? ORDER BY revision DESC LIMIT 1",
                                      (ex9, kd9, r["source_id"])).fetchone()
                    if x9:
                        try:
                            payload = json.loads(x9["payload"])
                        except ValueError:
                            payload = None
                elif r["address"]:
                    x9 = conn.execute("SELECT snapshot FROM raw_txs WHERE chain=? AND txhash=?", (ns, r["source_id"])).fetchone()
                    snap = x9["snapshot"] if x9 else None
                sp, px, cur = sellchart.spec_of(ns, payload, r["chain"], r["address"], r["symbol"], snap)
                out[int(r["posting_id"])] = (sp, px, cur, r["group_id"])
                if r["group_id"] is not None:
                    groups.add(int(r["group_id"]))
            for g9 in groups:
                toks = [(x["chain"], x["address"]) for x in conn.execute(
                    "SELECT chain, address FROM assets WHERE group_id=? AND address IS NOT NULL AND address != '' AND hidden=0", (g9,)).fetchall()
                    if x["chain"] in candles.GT_NETWORK]
                pref = {c: i for i, c in enumerate(self._DEX_CHAIN_PREF)}
                gtok[g9] = sorted(toks, key=lambda t: pref.get(t[0], 99))[:2]
        finally:
            conn.close()
        return out, gtok

    CHART_WORKERS = 2
    CHART_WAIT_S = 8.0
    CHART_HARD_S = 75.0
    _CHART_JOBS = {}
    _CHART_JLOCK = threading.Lock()

    def chart_request(self, iso, sym, iv="5m", after="1h", venue=None, wait=None, side="sell", bvenue=None):
        if getattr(self, "_day_idx", None) is None:
            return None, "ok"
        buy = side == "buy"
        fn = (lambda **k9: self.receipt_chart_buy(iso, sym, iv, venue, bvenue, **k9)) if buy else \
            (lambda **k9: self.receipt_chart(iso, sym, iv, after, venue, **k9))
        if side == "fut":
            fn = lambda **k9: self.fut_chart(iso, sym, iv, venue, **k9)
        hit = fn(cache_only=True)
        if hit is not None:
            return hit, "ok"
        key = (iso, sym, iv, "-" if buy else after, venue or "") + (("buy", bvenue or "") if buy else ()) + (("fut",) if side == "fut" else ())
        now = time.time()
        J, L = StateBuilder._CHART_JOBS, StateBuilder._CHART_JLOCK
        with L:
            for k9 in [k9 for k9, j9 in J.items() if j9["done"] and now - j9["t"] > 120]:
                J.pop(k9, None)
            job = J.get(key)
            if job is not None and job["done"]:
                J.pop(key, None)
                return job["res"], "ok"
            if job is None:
                if sum(1 for j9 in J.values() if not j9["done"]) >= self.CHART_WORKERS:
                    return None, "busy"
                job = J[key] = {"ev": threading.Event(), "done": False, "res": None, "t": now}

                def work(job=job):
                    try:
                        with candles.hard_deadline(time.time() + self.CHART_HARD_S):
                            job["res"] = fn()
                    except Exception as e9:
                        log.warning("%s 차트 수집 실패(%s %s): %s", "매수" if buy else "매도", iso, sym, e9)
                        job["res"] = {"ok": False, "error": "차트를 만들지 못했어요"}
                    finally:
                        job["done"], job["t"] = True, time.time()
                        job["ev"].set()
                threading.Thread(target=work, name=f"{'buychart' if buy else 'sellchart'} {iso} {sym}", daemon=True).start()
        job["ev"].wait(self.CHART_WAIT_S if wait is None else wait)
        if job["done"]:
            with L:
                if J.get(key) is job:
                    J.pop(key, None)
            return job["res"], "ok"
        return None, "preparing"

    def receipt_chart(self, iso, sym, iv="5m", after="1h", venue=None, fetch=True, cache_only=False):
        base = self.receipt(iso, sym)
        if base is None:
            return None
        if base.get("empty"):
            return {"ok": True, "empty": True, "date": iso, "sym": sym}
        want = base["sym"]
        raw_syms = set(base.get("aliases") or ()) | {want, sym}
        ck = (base.get("builtAt"), iso, want, iv, after, venue or "", bool(fetch))
        cache = self.__dict__.setdefault("_chart_cache", {})
        hit = cache.get(ck)
        if hit and time.time() - hit[0] < self.CHART_TTL_S:
            return self._with_eval(hit[1])
        if cache_only:
            return None
        rows = self._sell_rows(iso, raw_syms)
        specs, gtok = self._sell_specs([r[4] for r in rows])
        groups = {}
        for ts9, q9, usd9, un9, pid9 in rows:
            sp9, px9, cur9, gid9 = specs.get(pid9) or (None, None, "USD", None)
            if sp9 is None:
                continue
            key9 = candles.spec_key(sp9)
            g = groups.get(key9)
            if g is None:
                g = groups[key9] = {"spec": sp9, "cur": cur9, "gid": gid9, "fills": [], "usd": 0.0}
            if sp9.get("venue") == "dex" and sp9.get("tx_addrs"):
                g["spec"] = dict(g["spec"], tx_addrs=sorted(set(g["spec"].get("tx_addrs") or ()) | set(sp9["tx_addrs"])))
            px = px9 if px9 else (un9 if cur9 == "USD" else None)
            if not px:
                continue
            g["fills"].append({"ts": ts9, "px": px, "q": q9, "amt": px * q9})
            g["usd"] += usd9 or 0.0
        venues = []
        tot_usd = sum(g["usd"] for g in groups.values()) or 0.0
        for k9, g in sorted(groups.items(), key=lambda kv: -kv[1]["usd"]):
            if not g["fills"]:
                continue
            sp9 = g["spec"]
            venues.append({"key": k9, "label": candles.spec_label(sp9) + (" (네이티브 — 바이낸스 시세)" if sp9.get("native") else ""),
                           "venue": sp9.get("venue"), "cur": g["cur"], "curSym": sellchart.CUR_SYM.get(g["cur"], ""), "n": len(g["fills"]),
                           "qty": sellchart._r(sum(f["q"] for f in g["fills"])),
                           "amt": sellchart._r(sum(f["amt"] for f in g["fills"])), "usd": round(g["usd"], 2),
                           "sharePct": round(100.0 * g["usd"] / tot_usd, 1) if tot_usd else None})
        out = {"ok": True, "date": iso, "sym": want, "iv": iv, "after": after, "builtAt": base.get("builtAt"), "buySide": True, "autoEval": True,
               "venues": venues, "venue": None, "chart": None, "fills": [], "summary": None, "receipt": {
                   "realized": base.get("realized"), "sellUsd": (base.get("sell") or {}).get("usd"), "krwMarket": (base.get("sell") or {}).get("krwMarket"),
                   "pathTs": base.get("pathTs")}}
        if not venues:
            out["why"] = "차트로 그릴 매도 체결이 없어요(스테이블·지불 레그만이거나 원장 행을 못 찾음)"
            cache[ck] = (time.time(), out)
            return self._with_eval(out)
        sel = next((v for v in venues if v["key"] == venue), None) or venues[0]
        g = groups[sel["key"]]
        fills = sorted(g["fills"], key=lambda f: f["ts"])
        cur = g["cur"]
        iv_s = candles.IV_SEC[iv]
        w0, w1, t_first, t_last = sellchart.window(fills, after)
        out["venue"] = sel["key"]
        out["cur"], out["curSym"] = cur, sellchart.CUR_SYM.get(cur, "")
        out["fills"] = [{"ts": f["ts"], "px": sellchart._r(f["px"]), "q": sellchart._r(f["q"]), "amt": sellchart._r(f["amt"])} for f in fills]
        out["window"] = {"from": w0, "to": w1, "sellFrom": t_first, "sellTo": t_last}
        dep9 = (base.get("pathTs") or {}).get("deposit")
        cs9 = None
        if fetch:
            primary = {k9: v9 for k9, v9 in g["spec"].items() if k9 != "native"}
            dex_specs = []
            if primary.get("venue") != "dex":
                for ch9, ca9 in gtok.get(g["gid"]) or ():
                    dex_specs.append({"venue": "dex", "chain": ch9, "token": ca9})
            base_sym = primary.get("base") or want.split("#", 1)[0].upper()
            plan = candles.plan_chain(primary, base_sym, cur, dex_specs)
            res = candles.best_chart(plan, iv, w0, w1 + iv_s, cur, fx_rows_fn=lambda iv9, a9, b9: candles.fx_rows(iv9, a9, b9),
                                     budget_s=self.CHART_BUDGET_S, ref_px=candles.median_px(fills))
            cs9 = res["candles"]
            if res["ok"] and res.get("spec"):
                sp_c9 = self.__dict__.setdefault("_chart_src_spec", {})
                if len(sp_c9) >= self.CHART_CACHE_MAX * 2:
                    sp_c9.pop(next(iter(sp_c9)))
                sp_c9[ck] = (res["spec"], res.get("res"))
            out["chart"] = {"ok": res["ok"], "src": res["src"], "tried": res["tried"], "candles": cs9 or [], "complete": bool(res.get("complete", True)),
                            "volUnit": ("usd" if (res["src"] or {}).get("venue") == "dex" else "coin") if res["ok"] else None,
                            "why": None if res["ok"] else "봉을 받지 못했어요 — " + " · ".join(
                                f"{t['label']}: {t.get('note') or t.get('why')}" for t in res["tried"][:4])}
        iv_eff = candles.IV_SEC.get(((out.get("chart") or {}).get("src") or {}).get("iv") or iv, iv_s)
        out["summary"] = sellchart.summarize(cs9 or [], fills, iv_eff, req_end=w1 + iv_s, deposit_ts=dep9, cur=cur)
        if cs9:
            inp = sellchart.eval_input(iso, want, sel["label"], (out["chart"] or {}).get("src"), out["summary"], fills, cs9)
            inp = self._memo_inp(inp, iso, [want, sym] + sorted(str(x) for x in (base.get("aliases") or ())))
            out["evalFp"] = sellchart.eval_fp(inp)
            self._eval_inputs = getattr(self, "_eval_inputs", {})
            self._eval_inputs[(iso, want, out["evalFp"])] = inp
            while len(self._eval_inputs) > self.EVAL_INPUTS_MAX:
                self._eval_inputs.pop(next(iter(self._eval_inputs)))
        if len(cache) >= self.CHART_CACHE_MAX:
            cache.pop(next(iter(cache)))
        if (out.get("chart") or {}).get("ok") or not fetch:
            cache[ck] = (time.time(), out)
        return self._with_eval(out)

    FUT_RC_MAX = 16
    FUT_SPAN_LO_S = 30 * 3600
    FUT_SPAN_MAX_S = 7 * 86400
    FUT_EXN = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX"}

    def _fut_px(self):
        px, keys = {}, []
        for ex in fut_rcpt.PX_EX:
            k9, d9 = fut_rcpt.load_cached_k(ex)
            px[ex] = d9
            keys.append(k9)
        return px, tuple(keys)

    def fut_receipt(self, iso):
        idx = getattr(self, "_day_idx", None)
        if fut_rcpt is None or not idx or idx.get("futEv") is None:
            return None
        px, pk = self._fut_px()
        ck = (idx["builtAt"], iso)
        C = self.__dict__.setdefault("_fut_rc", {})
        hit = C.get(ck)
        if hit and hit[0] == pk and hit[1] is idx["futEv"]:
            return hit[2]
        body = fut_rcpt.assemble(iso, idx["futEv"], px, dict(self.FUT_EXN, **PERP_NAMES), _fut_by_date_ex, int(time.time() * 1000),
                                 stale=idx.get("futStale") or (), accts=idx.get("futAccts") or {})
        body["builtAt"] = idx["builtAt"]
        if len(C) >= self.FUT_RC_MAX:
            C.pop(next(iter(C)))
        C[ck] = (pk, idx["futEv"], body)
        return body

    def _fut_rkey(self, base):
        C = self.__dict__.get("_fut_rc") or {}
        for v9 in C.values():
            if v9[2] is base:
                return (base.get("builtAt"), base.get("date"), v9[0])
        return None

    @staticmethod
    def _fut_spec(ex, coin, sym):
        q = fut_rcpt.quote_of(sym)
        q = q if q in ("USDT", "USDC") else "USDT"
        if ex == "bybit":
            return {"venue": "bybit_linear", "base": coin, "quote": q}
        return {"venue": "binance_futures", "base": coin, "quote": q}

    def fut_chart(self, iso, sym, iv="5m", venue=None, fetch=True, cache_only=False):
        base = self.fut_receipt(iso)
        if base is None:
            return None
        c = next((x for x in base.get("coins") or () if x.get("coin") == sym), None)
        if base.get("empty") or c is None:
            return {"ok": True, "empty": True, "side": "fut", "date": iso, "sym": sym}
        rk9 = self._fut_rkey(base)
        ck = ("fut", rk9, iso, sym, iv, venue or "", bool(fetch)) if rk9 is not None else None
        cache = self.__dict__.setdefault("_chart_cache", {})
        hit = cache.get(ck) if ck is not None else None
        if hit and time.time() - hit[0] < self.CHART_TTL_S:
            return hit[1]
        if cache_only:
            return None
        trs = c.get("trades") or []
        tot = sum(abs(v["usd"]) for v in c["venues"]) or 0.0
        vby = {}
        for v in c["venues"]:
            x = vby.setdefault(v["exKey"], {"key": v["exKey"], "label": v["ex"] + " " + v["symbol"], "sym": v["symbol"], "n": 0, "usd": 0.0})
            x["n"] += v["n"]
            x["usd"] += v["usd"]
        venues = sorted(vby.values(), key=lambda x: (-abs(x["usd"]), x["key"]))
        for x in venues:
            x["usd"] = round(x["usd"], 2)
            x["sharePct"] = round(100.0 * abs(x["usd"]) / tot, 1) if tot else None
        venues = [x for x in venues if x["n"] > 0] or venues
        sel = next((x for x in venues if x["key"] == venue), None) or venues[0]
        trs = [t for t in trs if t.get("exKey") == sel["key"]] if len(venues) > 1 else trs
        n_all = (c.get("tradesTotalEx") or {}).get(sel["key"], len(trs)) if len(venues) > 1 else c.get("tradesTotal", len(trs))
        cap_note = f"큰 손익 {len(trs)}건만 그림(그날 {n_all}건)" if trs and n_all > len(trs) else None
        if not trs:
            out = {"ok": True, "side": "fut", "date": iso, "sym": sym, "label": c.get("label"), "iv": iv, "builtAt": base.get("builtAt"), "venues": [], "venue": sel["key"],
                   "cur": "USD", "window": None, "marks": [], "spans": [],
                   "chart": {"ok": False, "src": None, "tried": [], "candles": [], "complete": True, "why": "그날 이 종목은 청산이 없어(수수료·펀딩만) 차트를 그리지 않아요"}}
            if ck is not None:
                cache[ck] = (time.time(), out)
            return out
        now = time.time()
        ex_ts = [float(t["exitTs"]) for t in trs]
        en_ts = [float(t["entryTs"]) for t in trs if t.get("entryTs")]
        w1 = min(max(ex_ts) + 3600, now)
        w0 = min(min(ex_ts) - 3600, (min(en_ts) - 1800) if en_ts else float("inf"))
        w0 = max(w0, w1 - self.FUT_SPAN_MAX_S)
        iv_use = "1h" if w1 - w0 > self.FUT_SPAN_LO_S else iv
        iv_s = candles.IV_SEC[iv_use]
        w0, w1 = int(w0) // iv_s * iv_s, int(w1)
        out = {"ok": True, "side": "fut", "date": iso, "sym": sym, "label": c.get("label"), "iv": iv, "ivUse": iv_use, "builtAt": base.get("builtAt"),
               "venues": [{k: v for k, v in x.items() if k != "sym"} for x in venues], "venue": sel["key"], "cur": "USD",
               "window": {"from": w0, "to": w1}, "chart": None, "marks": [], "spans": []}
        if cap_note:
            out["capNote"] = cap_note
        cs9 = None
        if fetch:
            prim = self._fut_spec(sel["key"], sym, sel["sym"])
            if sel["key"] not in ("binance", "bybit"):
                out["srcNote"] = f"{sel['label']} 봉 대신 같은 코인 선물 봉"
            plan = candles.plan_chain(prim, sym, "USD")
            alts = [(sp, None, "alt_cex") for sp in ({"venue": "binance_futures", "base": sym, "quote": "USDT"},
                                                       {"venue": "bybit_linear", "base": sym, "quote": "USDT"})
                    if candles.spec_key(sp) != candles.spec_key(prim)]
            plan = plan[:1] + alts + plan[1:]
            ref = sorted(float(t["exitPx"]) for t in trs if t.get("exitPx"))
            res = candles.best_chart(plan, iv_use, w0, w1 + iv_s, "USD", budget_s=self.CHART_BUDGET_S, ref_px=ref[len(ref) // 2] if ref else None)
            cs9 = res["candles"]
            out["chart"] = {"ok": res["ok"], "src": res["src"], "tried": res["tried"], "candles": cs9 or [], "complete": bool(res.get("complete", True)),
                            "volUnit": "coin" if res["ok"] else None,
                            "why": None if res["ok"] else "봉을 받지 못했어요 — " + " · ".join(
                                f"{t['label']}: {t.get('note') or t.get('why')}" for t in res["tried"][:4])}
        bars = sorted(cs9 or [], key=lambda r9: r9[0])

        def close_at(ts9):
            if not bars:
                return None
            lo9, hi9 = 0, len(bars) - 1
            while lo9 < hi9:
                mid9 = (lo9 + hi9 + 1) // 2
                if bars[mid9][0] <= ts9:
                    lo9 = mid9
                else:
                    hi9 = mid9 - 1
            return bars[lo9][4]
        for t in trs:
            p9 = t.get("exitPx")
            out["marks"].append({"id": t["id"], "ts": t["exitTs"], "px": p9 if p9 else close_at(t["exitTs"]), "kind": "close", "side": t.get("side"),
                                 "exKey": t["exKey"], "q": t.get("qty"), "pnl": t["pnl"], "approx": not p9})
            if p9 and t.get("entryPx"):
                out["spans"].append({"id": t["id"], "from": t.get("entryTs"), "to": t["exitTs"], "entryPx": t["entryPx"], "exitPx": p9,
                                     "side": t.get("side"), "pnl": t["pnl"]})
        for o in c.get("opens") or ():
            if o.get("exKey") != sel["key"] or not (w0 <= float(o["ts"]) <= w1):
                continue
            m9 = {"ts": o["ts"], "px": o["px"], "kind": "open", "side": o["side"], "exKey": o["exKey"], "q": o.get("q"), "approx": False}
            if o.get("fills"):
                m9["fills"] = o["fills"]
            out["marks"].append(m9)
        out["marks"].sort(key=lambda x: x["ts"])
        if len(cache) >= self.CHART_CACHE_MAX:
            cache.pop(next(iter(cache)))
        if ck is not None and ((out.get("chart") or {}).get("ok") or not fetch):
            cache[ck] = (time.time(), out)
        return out

    def purge_memo_charts(self, iso, sym):
        def hit(key9):
            if not isinstance(key9, tuple) or iso not in key9:
                return False
            return any(isinstance(x, str) and day_memo.norm_sym(x) == sym for x in key9)
        cache = self.__dict__.get("_chart_cache") or {}
        for k9 in [k9 for k9 in list(cache) if hit(k9)]:
            cache.pop(k9, None)
        with StateBuilder._CHART_JLOCK:
            J = StateBuilder._CHART_JOBS
            for k9 in [k9 for k9, j9 in list(J.items()) if j9.get("done") and hit(k9)]:
                J.pop(k9, None)

    @staticmethod
    def _memo_inp(inp, iso, syms):
        try:
            mm = DAY_MEMOS.for_date(iso)
        except Exception:
            return inp
        if not mm:
            return inp
        for s9 in syms:
            k9 = day_memo.norm_sym(str(s9 or ""))
            if k9 and k9 in mm:
                return dict(inp, memo=mm[k9])
        return inp

    @staticmethod
    def _eval_rec(rec, side="sell"):
        import review_prompt as rp9
        cur9 = rp9.BUY_EVAL_VERSION if side == "buy" else rp9.SELL_EVAL_VERSION
        return dict(rec, old=True) if rec.get("pv") != cur9 else dict(rec)

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

    def receipt_list(self, d_from, d_to):
        idx = getattr(self, "_day_idx", None)
        if not idx or idx.get("pos") is None:
            return None
        import review_daily as rd
        by_day = {}
        for p in idx["pos"]:
            if p.get("kind") in ("gas", "stake") or not p.get("sym"):
                continue
            for k9, v9 in (p.get("realizedByDay") or {}).items():
                if len(str(k9)) != 10 or not (d_from <= k9 <= d_to):
                    continue
                try:
                    v9 = float(v9 or 0)
                except (TypeError, ValueError):
                    continue
                by_day.setdefault(k9, {}).setdefault(p["sym"], 0.0)
                by_day[k9][p["sym"]] += v9
        items = []
        for d9, m9 in by_day.items():
            canon = rd._canon_map(set(m9))
            agg = {}
            for s9, v9 in m9.items():
                c9 = canon.get(s9, s9)
                agg[c9] = agg.get(c9, 0.0) + v9
            for s9, v9 in agg.items():
                if abs(v9) >= 0.005:
                    items.append({"date": d9, "sym": s9, "usd": round(v9, 2)})
        items.sort(key=lambda x: (x["date"], abs(x["usd"])), reverse=True)
        return {"ok": True, "from": d_from, "to": d_to, "builtAt": idx.get("builtAt"), "n": len(items), "items": items}

    BUY_FILLS_MAX = 400
    EVAL_INPUTS_MAX = 256
    BRIDGE_MAX_S = 30 * 86400
    GAP_BRIDGE_S = buychart.GAP_BRIDGE_S
    GAP_BRIDGE_BUDGET_S = 15.0

    @staticmethod
    def _fetched_span(res, a, b, iv_s):
        if not res or not res.get("ok"):
            return None
        if res.get("complete", True):
            return (a, b)
        cs9 = res.get("candles") or []
        return (int(cs9[0][0]), int(cs9[-1][0]) + int(iv_s)) if cs9 else None

    @staticmethod
    def _xc_resolve(legs, raw_syms):
        fam = {str(x9 or "").split("#", 1)[0].strip().upper() for x9 in raw_syms}
        conn9 = dbm.open_db(common.DB_PATH, readonly=True)
        try:
            for l9 in legs:
                x9 = l9["xc"]
                ch9, tx9 = str(x9.get("chain") or ""), str(x9.get("tx") or "")
                if not ch9 or not tx9:
                    continue
                txq9 = tx9.lower() if tx9.startswith("0x") else tx9
                hit9 = None
                for r9 in conn9.execute("SELECT p.posting_id, p.event_ts, a.symbol FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
                                        " WHERE p.source_kind = 'chain_tx' AND p.source_ns = ? AND p.source_id = ? AND p.leg_kind = 'acq'",
                                        (ch9, txq9)).fetchall():
                    if str(r9["symbol"] or "").split("#", 1)[0].strip().upper() in fam:
                        hit9 = r9
                        break
                if hit9 is not None:
                    l9["pid"], l9["ts"] = int(hit9["posting_id"]), int(hit9["event_ts"])
                    x9["tsFrom"] = "ledger"
                    continue
                if l9["ts"] or x9.get("block") in (None, ""):
                    continue
                try:
                    blk9 = int(x9["block"])
                except (TypeError, ValueError):
                    continue
                for r9 in conn9.execute("SELECT txhash FROM raw_txs WHERE chain = ? AND block = ? LIMIT 8", (ch9, blk9)).fetchall():
                    p9 = conn9.execute("SELECT event_ts FROM postings WHERE source_kind = 'chain_tx' AND source_ns = ? AND source_id = ? LIMIT 1",
                                       (ch9, r9["txhash"])).fetchone()
                    if p9 is not None and p9["event_ts"]:
                        l9["ts"] = int(p9["event_ts"])
                        x9["tsFrom"] = "block"
                        break
        finally:
            conn9.close()

    def _buy_cards(self, raw_syms):
        idx = self._day_idx
        ck = (idx.get("builtAt"), tuple(sorted(str(x) for x in raw_syms)))
        cc = self.__dict__.setdefault("_buy_cards_cache", {})
        if ck in cc:
            return cc[ck]
        cards = {}
        for _d9, rows in (idx.get("ix") or {}).items():
            for ts, kind, e, meta in rows:
                if kind != "pos" or meta is None or meta[1] not in raw_syms:
                    continue
                c9 = cards.get(meta[0])
                if c9 is None:
                    c9 = cards[meta[0]] = {"sym": meta[1], "chain": meta[2], "ev": []}
                c9["ev"].append((int(ts), e))
        for c9 in cards.values():
            c9["ev"].sort(key=lambda x: x[0])
        while len(cc) >= 8:
            cc.pop(next(iter(cc)))
        cc[ck] = cards
        return cards

    def receipt_chart_buy(self, iso, sym, iv="5m", venue=None, bvenue=None, fetch=True, cache_only=False):
        base = self.receipt(iso, sym)
        if base is None:
            return None
        if base.get("empty"):
            return {"ok": True, "empty": True, "side": "buy", "date": iso, "sym": sym}
        want = base["sym"]
        raw_syms = set(base.get("aliases") or ()) | {want, sym}
        ck = ("buy", base.get("builtAt"), iso, want, iv, venue or "", bvenue or "", bool(fetch))
        cache = self.__dict__.setdefault("_chart_cache", {})
        hit = cache.get(ck)
        if hit and time.time() - hit[0] < self.CHART_TTL_S:
            return self._with_eval(hit[1])
        if cache_only:
            return None
        sell = self.receipt_chart(iso, sym, iv, "1h", venue, fetch=fetch) or {}
        bs9, tx9 = base.get("sell") or {}, base.get("tax") or {}
        cur = sell.get("cur") or ("KRW" if bs9.get("krwMarket") else "USD")
        ssm = sell.get("summary") or {}
        sw = sell.get("window") or {}
        sq9 = float(bs9.get("qty") or 0)
        cost9 = None
        if tx9.get("recon") and sq9 > 0:
            rz9 = base.get("realized") or {}
            if cur == "KRW" and tx9.get("dispKrw") is not None and rz9.get("krw") is not None:
                cost9 = (float(tx9["dispKrw"]) - float(rz9["krw"])) / sq9
            elif cur == "USD":
                cost9 = (float(tx9.get("disp") or 0) - float(rz9.get("usd") or 0)) / sq9
        sell_ctx = {"avgPx": ssm.get("avgPx") if (ssm.get("cur") or cur) == cur else None,
                    "firstTs": sw.get("sellFrom") or (base.get("pathTs") or {}).get("first_sell"), "lastTs": sw.get("sellTo"),
                    "openTs": ssm.get("openTs"), "costPx": cost9 if cost9 and cost9 > 0 else None}
        idx = self._day_idx
        cards = self._buy_cards(raw_syms)
        real = buychart.sell_cards(cards, iso)
        ex = buychart.extract_legs(cards, real, iso)
        legs = list(ex["legs"])
        inflows = [dict(x9) for x9 in (ex.get("inflows") or ())]
        if any(l9.get("xc") for l9 in legs):
            self._xc_resolve([l9 for l9 in legs if l9.get("xc")], raw_syms)
            legs, inflows = buychart.xc_settle(legs, inflows)
        specs, gtok = self._sell_specs([l9["pid"] for l9 in legs if l9.get("pid")])
        ko2code = {v9: k9 for k9, v9 in candles.CHAIN_KO.items()}
        card_gid = lambda pk9: (int(m9.group(1)) if (m9 := re.match(r"g(\d+)", str(pk9 or ""))) else None)
        lp_odd = sorted({l9["pid"] for l9 in legs if l9.get("pid") and l9["k"] == "LP 전환 매수" and specs.get(l9["pid"])
                         and specs[l9["pid"]][3] is not None and card_gid(l9["pkey"]) is not None and int(specs[l9["pid"]][3]) != card_gid(l9["pkey"])})
        row_sym = {}
        if lp_odd:
            conn9 = dbm.open_db(common.DB_PATH, readonly=True)
            try:
                for i9 in range(0, len(lp_odd), 400):
                    ch9 = lp_odd[i9:i9 + 400]
                    for x9 in conn9.execute("SELECT p.posting_id, a.symbol FROM postings p JOIN assets a ON a.asset_id = p.asset_id WHERE p.posting_id IN (%s)"
                                            % ",".join("?" * len(ch9)), ch9).fetchall():
                        row_sym[int(x9["posting_id"])] = x9["symbol"]
            finally:
                conn9.close()
        spec_of_leg = {}
        for l9 in legs:
            r9 = specs.get(l9.get("pid"))
            spec_of_leg[id(l9)] = r9 if (r9 and buychart.keep_leg_row(l9["k"], card_gid(l9["pkey"]), r9[3], row_sym.get(l9.get("pid")), raw_syms)) else None
        gid_of = {}
        for l9 in legs:
            cg9 = card_gid(l9["pkey"])
            g9 = cg9 if cg9 is not None else (spec_of_leg[id(l9)] or (None, None, None, None))[3]
            if g9 is not None:
                gid_of.setdefault(l9["pkey"], g9)
        any_gid = next(iter(gid_of.values()), None)
        fills, need_fx, groups = [], [], {}
        for l9 in legs:
            sp9, px9, cur9, gid9 = spec_of_leg[id(l9)] or (None, None, "USD", None)
            if sp9 is None:
                ch9 = ko2code.get(str(l9.get("chain") or ""), str(l9.get("chain") or "").lower())
                tok9 = next((ca for c9, ca in (gtok.get(gid_of.get(l9["pkey"], any_gid)) or ()) if c9 == ch9), None)
                if tok9 is None and gid_of.get(l9["pkey"], any_gid) is not None:
                    conn9 = dbm.open_db(common.DB_PATH, readonly=True)
                    try:
                        r9 = conn9.execute("SELECT address FROM assets WHERE group_id=? AND chain=? AND address IS NOT NULL AND address != '' AND hidden=0 LIMIT 1",
                                           (gid_of.get(l9["pkey"], any_gid), ch9)).fetchone()
                        tok9 = r9["address"] if r9 else None
                    finally:
                        conn9.close()
                if l9.get("xc") and l9["xc"].get("chain"):
                    ch9, tok9 = str(l9["xc"]["chain"]), l9["xc"].get("token")
                sp9 = {"venue": "dex", "chain": ch9, "token": tok9} if (tok9 and ch9 in candles.GT_NETWORK) else None
                gid9 = gid_of.get(l9["pkey"], any_gid)
            q9 = float(l9["q"])
            if cur == "KRW":
                px = (l9["krw"] / q9) if l9.get("krw") else (px9 if (cur9 == "KRW" and px9) else None)
            else:
                px = l9.get("un") or (px9 if (cur9 == "USD" and px9) else None)
            vlab = candles.spec_label(sp9) if sp9 else str(l9.get("chain") or "?")
            f9 = {"ts": l9["ts"], "px": px, "q": q9, "amt": (px * q9) if px else None, "kind": buychart.KIND_SHORT.get(l9["k"], l9["k"]),
                  "venue": sellchart.clean_label(vlab) or "?", "usd": l9.get("usd"), "un": l9.get("un"),
                  "vkey": candles.spec_key(sp9) if sp9 else None}
            if l9.get("from"):
                f9["from"] = l9["from"]
            if l9.get("xc"):
                f9["via"] = "경유 역추적" + (" · 시각 = 같은 블록" if l9["xc"].get("tsFrom") == "block" else "")
            if px is None and cur == "KRW" and l9.get("un"):
                need_fx.append(f9)
            fills.append(f9)
            if sp9 is not None:
                k9 = candles.spec_key(sp9)
                g = groups.get(k9)
                if g is None:
                    g = groups[k9] = {"spec": {k: v for k, v in sp9.items() if k != "native"}, "gid": gid9, "usd": 0.0, "n": 0}
                if sp9.get("venue") == "dex" and sp9.get("tx_addrs"):
                    g["spec"] = dict(g["spec"], tx_addrs=sorted(set(g["spec"].get("tx_addrs") or ()) | set(sp9["tx_addrs"])))
                g["usd"] += float(l9.get("usd") or 0)
                g["n"] += 1
        inf_out = []
        for x9 in inflows:
            u9 = x9.get("un")
            f9 = {"ts": x9["ts"], "q": float(x9["q"]), "un": u9, "usd": x9.get("usd"), "px": (u9 if cur != "KRW" else None),
                  "kind": "입금", "d": x9.get("d"), "rule": x9.get("rule"), "chain": x9.get("chain")}
            f9["amt"] = (f9["px"] * f9["q"]) if f9["px"] else None
            if f9["px"] is None and u9:
                need_fx.append(f9)
            inf_out.append(f9)
        if need_fx and fetch:
            t9 = [f["ts"] for f in need_fx]
            iv_fx = iv if max(t9) - min(t9) <= 86400 else "1h"
            r9 = candles.fx_rows(iv_fx, min(t9) - 3600, max(t9) + candles.IV_SEC[iv_fx])
            fr9 = sorted((c[0], c[4]) for c in (r9.candles or ()) if c[4] > 0) if r9 is not None and r9.ok else []
            for f in need_fx:
                k9 = next((c for t, c in reversed(fr9) if t <= f["ts"]), fr9[0][1] if fr9 else None)
                if k9:
                    f["px"], f["amt"] = f["un"] * k9, f["un"] * k9 * f["q"]
        fills = sorted([f for f in fills if f["px"]], key=lambda f: f["ts"])
        tot_usd = sum(g["usd"] for g in groups.values()) or 0.0
        venues = [{"key": k9, "label": candles.spec_label(g["spec"]), "venue": g["spec"].get("venue"), "n": g["n"], "usd": round(g["usd"], 2),
                   "sharePct": round(100.0 * g["usd"] / tot_usd, 1) if tot_usd else None}
                  for k9, g in sorted(groups.items(), key=lambda kv: -kv[1]["usd"])]
        lg9 = {"cards": ex["cards"], "srcCards": ex["srcCards"], "unmatched": ex["unmatched"], "fallback": ex.get("fallback", 0),
               "source": ex.get("source"), "simSells": ex.get("simSells", 0), "other": ex.get("other"), "unknownQty": ex.get("unknownQty"),
               "trimmed": ex["trimmed"], "lpFee": ex["lpFee"],
               "n": len(legs), "priced": len(fills), "inflows": len(inf_out),
               "inflowQty": sellchart._r(sum(f9["q"] for f9 in inf_out)), "inflowUsd": round(sum(float(f9.get("usd") or 0) for f9 in inf_out), 2)}
        out = {"ok": True, "side": "buy", "date": iso, "sym": want, "iv": iv, "builtAt": base.get("builtAt"), "cur": cur, "autoEval": True,
               "curSym": sellchart.CUR_SYM.get(cur, ""), "sellVenue": sell.get("venue"), "venues": venues, "venue": None,
               "fills": [], "segs": [], "chart": None, "summary": None, "legs": lg9,
               "inflows": [{"ts": f9["ts"], "px": sellchart._r(f9["px"]) if f9["px"] else None, "q": sellchart._r(f9["q"]),
                            "amt": sellchart._r(f9["amt"]) if f9["amt"] else None, "kind": "입금", "d": f9.get("d"), "rule": f9.get("rule"),
                            "chain": f9.get("chain")} for f9 in sorted(inf_out, key=lambda f9: f9["ts"])],
               "sell": {k: v for k, v in sell_ctx.items() if v is not None}}
        if not fills:
            out["why"] = (("이 매도의 원가는 매수 기록이 아니라 입금으로 잡혔어요 — " + str(max(inf_out, key=lambda f9: f9["q"]).get("rule") or "규칙 표시 없음"))
                          if inf_out else
                          "이 매도의 원가가 된 매수 기록을 찾지 못했어요(이전 보유분 · 원가 미상 · 이관 짝 없음)" if not legs
                          else "매수 체결가를 표시 통화로 바꾸지 못했어요")
            cache[ck] = (time.time(), out)
            return self._with_eval(out)
        sel = next((v for v in venues if v["key"] == bvenue), None) or (venues[0] if venues else None)
        out["venue"] = sel["key"] if sel else None
        segs, outside = buychart.segments(fills, sell_from=sw.get("from"))
        out["outside"] = {"n": len(outside), "amt": sellchart._r(sum(float(fills[i]["amt"] or 0) for i in outside))} if outside else None
        iv_s = candles.IV_SEC[iv]
        cs_all, srcs, bridge = [], [], None
        fetched9 = []
        seg_out = []
        gseg9, gap_job = [], None
        if fetch and sel:
            g = groups[sel["key"]]
            primary = g["spec"]
            dex_specs = []
            if primary.get("venue") != "dex":
                for ch9, ca9 in gtok.get(g["gid"]) or ():
                    dex_specs.append({"venue": "dex", "chain": ch9, "token": ca9})
            base_sym = primary.get("base") or want.split("#", 1)[0].upper()
            plan = candles.plan_chain(primary, base_sym, cur, dex_specs)
            s_ch = sell.get("chart") or {}
            s_cs = sorted((list(c[:6]) for c in (s_ch.get("candles") or ()) if isinstance(c, (list, tuple)) and len(c) >= 6), key=lambda c: c[0]) \
                if (s_ch.get("ok") and sell.get("cur") == cur) else []
            s_first = s_cs[0][0] if s_cs else None
            rk9 = (float(tx9["dispKrw"]) / float(tx9["disp"])) if (tx9.get("dispKrw") and tx9.get("disp")) else None

            def val9(c, unit, fxk):
                if unit == "usd":
                    return c[5] * (fxk if cur == "KRW" else 1.0)
                return c[5] * (c[2] + c[3] + c[4]) / 3.0
            s_unit = s_ch.get("volUnit") or "coin"
            s_iv9 = candles.IV_SEC.get((s_ch.get("src") or {}).get("iv") or iv, iv_s)
            s_fx = (((s_ch.get("src") or {}).get("fx") or {}).get("avg")) or rk9 or 1.0
            for s9 in segs:
                res = candles.best_chart(plan, iv, s9["from"], s9["to"] + iv_s, cur, fx_rows_fn=lambda iv9, a9, b9: candles.fx_rows(iv9, a9, b9),
                                         budget_s=self.CHART_BUDGET_S / max(1, len(segs)),
                                         ref_px=candles.median_px([f9 for f9 in fills if s9["from"] <= f9["ts"] <= s9["to"]] or fills))
                src9 = res["src"]
                unit9 = "usd" if (src9 or {}).get("venue") == "dex" else "coin"
                fx9 = ((src9 or {}).get("fx") or {}).get("avg") or rk9 or 1.0
                own = [c for c in (res["candles"] or []) if s_first is None or c[0] < s_first]
                raw_n9 = len(own)
                end9 = min(s9["to"] + iv_s, s_first) if s_first else s9["to"] + iv_s
                g_iv9 = candles.IV_SEC.get((src9 or {}).get("iv") or iv, iv_s)
                cs9 = [c[:5] + [val9(c, unit9, fx9), (c[6] if len(c) > 6 else 0), g_iv9] for c in buychart.ffill(own, g_iv9, s9["from"], end9)]
                joined = [c[:5] + [val9(c, s_unit, s_fx), 2, s_iv9] for c in s_cs if s9["from"] - s_iv9 < c[0] < s9["to"] + iv_s] if s_first is not None else []
                seg_out.append(dict(s9, ok=res["ok"] or bool(joined), src=src9, tried=res["tried"], candles=cs9 + joined, filled=len(cs9) - raw_n9,
                                    joinAt=joined[0][0] if joined else None, joinSrc=(s_ch.get("src") if joined else None),
                                    volUnit="val",
                                    why=None if (res["ok"] or joined) else "봉을 받지 못했어요 — " + " · ".join(
                                        f"{t['label']}: {t.get('note') or t.get('why')}" for t in res["tried"][:4])))
                cs_all += cs9 + joined
                if res["ok"] and res.get("spec") and cs9:
                    gseg9.append({"from": int(s9["from"]), "end": int(s9["to"]) + g_iv9, "iv": g_iv9, "spec": res["spec"], "res": res.get("res"),
                                  "src": src9, "unit": unit9, "fx": fx9, "last": cs9[-1][4], "lastT": cs9[-1][0]})
                sp9 = self._fetched_span(res, s9["from"], s9["to"] + iv_s, candles.IV_SEC.get((src9 or {}).get("iv") or iv, iv_s))
                if sp9:
                    fetched9.append(sp9)
                if src9:
                    srcs.append(src9)
            if s_first is not None:
                sp9 = self._fetched_span({"ok": True, "complete": s_ch.get("complete", True), "candles": s_cs},
                                         int(sw.get("from") or s_cs[0][0]), int(sw.get("to") or s_cs[-1][0]) + s_iv9, s_iv9)
                if sp9:
                    fetched9.append(sp9)
            fs9 = int(sell_ctx.get("firstTs") or 0)
            if s_first is not None and fs9:
                seen9 = {c[0] for c in cs_all if len(c) > 6 and c[6] == 2}
                cs_all += [c[:5] + [val9(c, s_unit, s_fx), 2, s_iv9] for c in s_cs if c[0] < fs9 and c[0] not in seen9]
            if segs and fs9 and fs9 - segs[-1]["to"] > 0 and fs9 - segs[-1]["to"] <= self.BRIDGE_MAX_S and srcs:
                rb = candles.best_chart([(primary, "hour", "bridge")], iv, segs[-1]["to"], fs9 + 3600, cur,
                                        fx_rows_fn=lambda iv9, a9, b9: candles.fx_rows(iv9, a9, b9), budget_s=20, by_date=False)
                bridge = rb["candles"] if rb["ok"] else None
                sp9 = self._fetched_span(rb, segs[-1]["to"], fs9 + 3600, 3600)
                if sp9:
                    fetched9.append(sp9)
            if gseg9 and s_first is not None and self.GAP_BRIDGE_S > 0:
                ls9 = int(sw.get("sellTo") or 0) or fs9
                sv9 = str(sell.get("venue") or "").split(":", 1)[0]
                gap_job = {"segs": sorted(gseg9, key=lambda g9: g9["from"]), "s_first": int(s_first), "w_from": int(sw["from"]) if sw.get("from") else None,
                           "open_ts": ssm.get("openTs"), "s_iv": s_iv9, "short": bool(ls9) and ls9 - int(fills[0]["ts"]) <= buychart.SHORT_SPAN_S,
                           "s_spec": (self.__dict__.get("_chart_src_spec") or {}).get((base.get("builtAt"), iso, want, iv, "1h", venue or "", bool(fetch))),
                           "s_name": self._venue_name(sv9), "cur": cur, "iv": iv, "rk": rk9, "val": val9}
            out["chart"] = {"ok": any(x["ok"] for x in seg_out), "src": srcs[0] if srcs else None,
                            "why": None if any(x["ok"] for x in seg_out) else (seg_out[0]["why"] if seg_out else "봉을 받지 못했어요")}
        else:
            seg_out = [dict(s9, ok=False, src=None, tried=[], candles=[], volUnit=None, why=None) for s9 in segs]
        out["segs"] = seg_out
        cs_all.sort(key=lambda c: c[0])
        iv_eff = candles.IV_SEC.get(((out.get("chart") or {}).get("src") or {}).get("iv") or iv, iv_s)
        fl_sum = [{"ts": f["ts"], "px": f["px"], "q": f["q"], "amt": f["amt"]} for f in fills]
        out["summary"] = buychart.summarize_buy(cs_all, fl_sum, iv_eff, segs, cur=cur, sell=sell_ctx, bridge=bridge, fetched=fetched9 if fetch else None)
        keep9 = fills if len(fills) <= self.BUY_FILLS_MAX else sorted(sorted(fills, key=lambda f: -float(f["amt"] or 0))[:self.BUY_FILLS_MAX], key=lambda f: f["ts"])
        out["fills"] = [{"ts": f["ts"], "px": sellchart._r(f["px"]), "q": sellchart._r(f["q"]), "amt": sellchart._r(f["amt"]), "kind": f["kind"],
                         "venue": f["venue"]} for f in keep9]
        out["fillsTotal"] = len(fills)
        if cs_all:
            inp = buychart.buy_eval_input(iso, want, [v["label"] for v in venues], (out["chart"] or {}).get("src"), out["summary"], fills, cs_all,
                                          extra={"outside": len(outside) or None, "trimmed": ex["trimmed"]["n"] or None,
                                                 "lp_fee_n": ex["lpFee"]["n"] or None})
            inp = self._memo_inp(inp, iso, [want, sym] + sorted(str(x) for x in (base.get("aliases") or ())))
            out["evalFp"] = sellchart.eval_fp(inp)
            self._eval_inputs = getattr(self, "_eval_inputs", {})
            self._eval_inputs[("buy", iso, want, out["evalFp"])] = inp
            while len(self._eval_inputs) > self.EVAL_INPUTS_MAX:
                self._eval_inputs.pop(next(iter(self._eval_inputs)))
        if gap_job is not None and (out.get("chart") or {}).get("ok"):
            try:
                gb9 = self._gap_bridges(gap_job)
            except Exception as e9:
                log.warning("빈 시간 표시 봉 실패(%s %s): %s", iso, want, e9)
                gb9 = None
            if gb9:
                out["gapBridges"] = gb9
        if len(cache) >= self.CHART_CACHE_MAX:
            cache.pop(next(iter(cache)))
        if (out.get("chart") or {}).get("ok") or not fetch:
            cache[ck] = (time.time(), out)
        return self._with_eval(out)

    @staticmethod
    def _venue_name(v):
        return {"dex": "DEX", "coingecko": "코인게코"}.get(v) or candles.VENUE_KO.get(v, v or "")

    def _gap_bridges(self, job):
        gs = job["segs"]
        plan = buychart.gap_plan([(g["from"], g["end"], g["iv"]) for g in gs], job["s_first"], job["w_from"], job["open_ts"], job["s_iv"],
                                 job["short"], self.GAP_BRIDGE_S)
        cur, iv = job["cur"], job["iv"]
        iv_s = candles.IV_SEC[iv]
        fxf = lambda iv9, a9, b9: candles.fx_rows(iv9, a9, b9)
        out = []
        for gp in plan:
            g, a, b = gs[gp["seg"]], gp["from"], gp["to"]
            got = None
            if gp["kind"] == "wait" and job.get("s_spec") and job["s_spec"][0]:
                r = candles.best_chart([(job["s_spec"][0], job["s_spec"][1], "bridge")], iv, a, b, cur, fx_rows_fn=fxf,
                                       budget_s=self.GAP_BRIDGE_BUDGET_S, by_date=False)
                if r["ok"]:
                    s9 = r["src"] or {}
                    iv9 = candles.IV_SEC.get(s9.get("iv") or iv, iv_s)
                    rows = buychart.bridge_rows(r["candles"], iv9, a, b)
                    if rows:
                        got = ("wait", s9, rows, iv9, "usd" if s9.get("venue") == "dex" else "coin", (s9.get("fx") or {}).get("avg") or job["rk"] or 1.0)
            if got is None:
                r = candles.best_chart([(g["spec"], g["res"], "bridge")], iv, a, b, cur, fx_rows_fn=fxf, budget_s=self.GAP_BRIDGE_BUDGET_S, by_date=False)
                s9 = r["src"] or g["src"] or {}
                iv9 = candles.IV_SEC.get(s9.get("iv") or iv, iv_s) if r["ok"] else g["iv"]
                none9 = not r["ok"] and any(t9.get("why") == "no_data" for t9 in r["tried"])
                rows = buychart.bridge_rows(r["candles"] if r["ok"] else [], iv9, a, b, seed=g["last"]) if (r["ok"] or none9) else []
                if rows:
                    got = ("move" if gp["kind"] == "wait" else gp["kind"], s9, rows, iv9, g["unit"], (s9.get("fx") or {}).get("avg") or g["fx"])
            if got is None:
                continue
            kind, s9, rows, iv9, unit, fx = got
            short, label = buychart.bridge_label(kind, self._venue_name(s9.get("venue")) if kind == "wait" else job["s_name"],
                                                 self._venue_name((g["src"] or {}).get("venue")), opened=job["open_ts"] is not None)
            out.append({"from": a, "to": b, "kind": kind, "short": short, "label": label, "src": s9,
                        "candles": [r9[:5] + [job["val"](r9, unit, fx), r9[6], iv9] for r9 in rows], "volUnit": "val",
                        "filled": sum(1 for r9 in rows if r9[6] == 1)})
        return out

    @staticmethod
    def _review_stale_why(iso, fp, day_ix, rbd, fbd, rbdk=None, fbdk=None):
        why = []
        if REVIEW_PV and fp.get("pv") != REVIEW_PV:
            why.append("리뷰 방식 변경")
        mm = iso[5:]
        for k9, src9 in (("rs", rbd), ("rf", fbd)):
            cur9 = float((src9.get(iso) if iso in src9 else src9.get(mm)) or 0)
            old9 = float(fp.get(k9) or 0)
            if abs(cur9 - old9) > max(1.0, 0.01 * max(abs(cur9), abs(old9))):
                why.append("실현손익 변경")
                break
        else:
            fu9 = float((fbd.get(iso) if iso in fbd else fbd.get(mm)) or 0)
            if fp.get("rk") is not None and rbdk is not None and (iso in rbdk or mm in rbdk) \
                    and (abs(fu9) < 0.005 or iso in (fbdk or {})):
                cur9 = float((rbdk.get(iso) if iso in rbdk else rbdk.get(mm)) or 0) + float((fbdk or {}).get(iso) or 0)
                old9 = float(fp.get("rk") or 0)
                if abs(cur9 - old9) > max(1500.0, 0.005 * max(abs(cur9), abs(old9))):
                    why.append("원화 실현 변경")
        ent9 = day_ix.get(iso) or []
        n9 = sum(1 for x9 in ent9 if x9[1] != "hidden")
        if fp.get("n") is not None and int(fp.get("n") or 0) != n9:
            why.append(f"기록 {int(fp.get('n') or 0)}→{n9}건")
        return " · ".join(why) or None

    def _merge_llm_reviews(self, reviews, day_ix, rbd, fbd, today_iso, rbdk=None, fbdk=None):
        llm_path = os.path.join(common.STATE_DIR, "reviews_llm.json")
        llm = (common.read_json(llm_path, {}) or {}) if os.path.exists(llm_path) else {}
        items = []
        for key, rv in llm.items():
            if not isinstance(rv, dict) or not rv.get("s") or not isinstance(rv.get("fp"), dict):
                continue
            k9 = str(key)
            if len(k9) == 10 and k9[4] == "-":
                items.append((1, k9, k9[5:], rv))
            elif len(k9) == 5 and k9[2] == "-":
                items.append((0, today_iso[:4] + "-" + k9, k9, rv))
        items.sort(key=lambda x9: (x9[0], x9[1]))
        for pri9, iso9, mm9, rv in items:
            why9 = self._review_stale_why(iso9, rv["fp"], day_ix, rbd, fbd, rbdk, fbdk)
            out9 = dict(rv)
            out9.update(iso=iso9, stale=bool(why9))
            if why9:
                out9["staleWhy"] = why9
            reviews[mm9] = out9
        return self._merge_weekly_reviews(rbd, fbd)

    @staticmethod
    def _wk_seg_sum(frm, to, rbd, fbd):
        tot, d9 = 0.0, frm
        try:
            dt9, end9 = datetime.strptime(frm, "%Y-%m-%d"), datetime.strptime(to, "%Y-%m-%d")
        except (TypeError, ValueError):
            return None
        while dt9 <= end9:
            d9 = dt9.strftime("%Y-%m-%d")
            for src9 in (rbd, fbd):
                tot += float((src9.get(d9) if d9 in src9 else src9.get(d9[5:])) or 0)
            dt9 += timedelta(days=1)
        return round(tot, 2)

    def _merge_weekly_reviews(self, rbd, fbd):
        wk_path = os.path.join(common.STATE_DIR, "reviews_llm_weekly.json")
        wk = (common.read_json(wk_path, {}) or {}) if os.path.exists(wk_path) else {}
        weekly = {}
        keys = sorted((k9 for k9, v9 in wk.items() if isinstance(v9, dict) and isinstance(v9.get("fp"), dict)))
        kset = set(keys)
        for key in keys:
            out9 = dict(wk[key])
            fp9 = out9["fp"]
            why = []
            if REVIEW_WPV and fp9.get("pv") != REVIEW_WPV:
                why.append("리뷰 방식 변경")
            frm, to = str(out9.get("from") or ""), str(out9.get("to") or "")
            cur9 = self._wk_seg_sum(frm, to, rbd, fbd) if frm and to else None
            if cur9 is not None and fp9.get("rs") is not None:
                old9 = float(fp9.get("rs") or 0)
                if abs(cur9 - old9) > max(5.0, 0.01 * max(abs(cur9), abs(old9))):
                    why.append("실현손익 변경")
                    out9["rsNow"] = cur9
            m9 = re.match(r"^(\d{4}-W\d{2})([ab]?)$", key)
            if m9 and not m9.group(2) and frm and to and frm[:7] != to[:7]:
                if (key + "a") in kset or (key + "b") in kset:
                    out9["superseded"] = True
                else:
                    out9["legacy"] = True
            out9["stale"] = bool(why)
            if why:
                out9["staleWhy"] = " · ".join(why)
            weekly[key] = out9
        return weekly

    def _auto_reviews(self, daily, realized_by_date, acts=None) -> dict:
        out = {}
        prev = None
        acts = acts or {}
        for d in daily:
            r = realized_by_date.get(d["date"])
            a = acts.get(d["date"]) or {}
            nb, ns = int(a.get("b") or 0), int(a.get("s") or 0)
            act_txt = " · ".join(x for x in ((f"매수 {nb}건" if nb else ""), (f"매도 {ns}건" if ns else "")) if x)
            n_txt = f"실현 {'+' if r > 0 else ''}{r:,.0f}$" if r else (act_txt or "체결 없음")
            delta = (d["val"] - prev) if prev is not None else 0
            s = "관망"
            out[d["date"]] = {
                "s": s, "auto": True, "note": n_txt,
                "sum": f"총자산 ${d['val']:,.0f}" + (f" · 전일대비 {'+' if delta >= 0 else ''}{delta:,.0f}$" if prev is not None else "")
                       + (f" · 당일 실현손익 ${r:,.0f}" if r else (f" · 실현 없음 · {act_txt}" if act_txt else " · 매매 없음"))
                       + ". 이 날은 AI 리뷰가 아직 없어 숫자 요약만 보여요.",
                "obs": [], "next": "—",
            }
            prev = d["val"]
        return out


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


def _cfg_file_sig():
    try:
        st9 = os.stat(common.CONFIG_PATH)
        return (st9.st_mtime_ns, st9.st_size)
    except OSError:
        return None


AUTO_OFF_PX_DAYS = 7


def _recent_px_gids(b9, now=None) -> set:
    out = set()
    try:
        now = time.time() if now is None else now
        lo9 = time.strftime("%Y-%m-%d", time.gmtime(now + 9 * 3600 - AUTO_OFF_PX_DAYS * 86400))
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
    except Exception:
        return set()
    return out


def _chain_auto_off_info():
    b9 = BUILDER
    if b9 is None:
        return None
    try:
        last9 = b9.latest(0) if b9.__dict__.get("_built_sig") != b9._input_sig() else b9.__dict__.get("_last_out")
    except (Exception, SystemExit):
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
    except Exception:
        return None
    try:
        lim9 = min(100.0, dust_usd_eff(b9.prefs()))
    except Exception:
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
                                cwd=common.BASE_DIR, env=dict(os.environ))

    @staticmethod
    def _kill(p):
        try:
            p.kill()
            p.wait(timeout=5)
        except Exception:
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
        except Exception as e:
            log.warning("검색 일꾼 실패(직접 검색으로): %s", type(e).__name__)
            self.off_until = time.time() + 60
            return None
        finally:
            if p is not None:
                self._kill(p)
            self.sem.release()


SEARCH_POOL = _SearchPool()
BUILDER: StateBuilder = None
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


class MemoHourly(Exception):
    pass


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
            except Exception as e:
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
    except Exception:
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
_V2_CSP = {}


def _v2_csp(raw: bytes, key: str) -> str:
    c = _V2_CSP.get(key)
    if c:
        return c
    hs = []
    for m9 in re.finditer(rb"<script(?P<a>[^>]*)>(?P<b>.*?)</script>", raw, re.S):
        a9 = m9.group("a")
        if re.search(rb"\bsrc\s*=", a9) or re.search(rb"type\s*=\s*[\"']application/json", a9):
            continue
        hs.append("'sha256-" + base64.b64encode(hashlib.sha256(m9.group("b")).digest()).decode() + "'")
    c = ("default-src 'self'; script-src 'self' " + " ".join(dict.fromkeys(hs)) + "; "
         "style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
         "img-src 'self' data: blob: https:; connect-src 'self' https://cdn.jsdelivr.net; "
         "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
    _V2_CSP.clear()
    _V2_CSP[key] = c
    return c


_BENCH = {"sig": None, "at": 0.0, "body": None}
_BENCH_LOCK = threading.Lock()


def _bench_btc_ids() -> set:
    import sqlite3
    try:
        c9 = sqlite3.connect(common.sqlite_ro_uri(common.DB_PATH), uri=True, timeout=5)
        try:
            return {str(r[0]) for r in c9.execute("SELECT asset_id FROM assets WHERE upper(symbol)='BTC'")}
        finally:
            c9.close()
    except Exception:
        return set()


def bench_series() -> dict:
    hp = os.path.join(common.STATE_DIR, "curve_hist_px.json")
    sig = []
    for p9 in (hp, DAILY_PX_PATH):
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
        h9 = common.read_json(hp, {}) if os.path.exists(hp) else {}
        sp9 = ((h9.get("specs") or {}).get("sym:BTC") or {}).get("p") or {}
        for d9, v9 in sp9.items():
            try:
                f9 = float(v9)
            except (TypeError, ValueError):
                continue
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d9)) and math.isfinite(f9) and f9 > 0:
                px[d9] = f9
                n_hist += 1
    except (SystemExit, Exception):
        pass
    ids = _bench_btc_ids()
    if ids:
        try:
            dp9 = common.read_json(DAILY_PX_PATH, {}) if os.path.exists(DAILY_PX_PATH) else {}
            for d9, row9 in dp9.items():
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d9)) or not isinstance(row9, dict):
                    continue
                vs = sorted(float(v) for k, v in (row9.get("p") or {}).items()
                            if str(k) in ids and isinstance(v, (int, float)) and math.isfinite(v) and v > 1000)
                if vs:
                    px[d9] = vs[len(vs) // 2]
                    n_day += 1
        except (SystemExit, Exception):
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
    except Exception:
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


class Handler(BaseHTTPRequestHandler):
    server_version = "tj-web/0.1"
    protocol_version = "HTTP/1.1"
    timeout = 120

    def log_message(self, fmt, *args):
        pass

    def parse_request(self):
        ok = super().parse_request()
        if ok and not getattr(self, "_tj_sw", False):
            self._tj_sw = True
            _sw_enter()
        return ok

    def handle_one_request(self):
        try:
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
        except Exception:
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
            px = login_auth.proxied(self)
        except Exception:
            px = True
        if not px:
            return False, ()
        return True, PROXY_SEC_HEADERS + ((HSTS,) if login_auth.proxied_https(self) else ())

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

    EX_KEYS = {"업비트": "upbit", "바이낸스": "binance", "바이빗": "bybit", "okx": "okx", "쿠코인": "kucoin",
               "게이트": "gate", "게이트아이오": "gate", "gate.io": "gate", "빗썸": "bithumb",
               "하이퍼리퀴드": "hyperliquid", "Hyperliquid": "hyperliquid"}

    @classmethod
    def _exchange_key(cls, v) -> str:
        s = str(v or "").strip()
        k = s.lower()
        if k in {"upbit", "binance", "bybit", "okx", "kucoin", "gate", "bithumb", "hyperliquid"}:
            return k
        return cls.EX_KEYS.get(s) or cls.EX_KEYS.get(k) or s

    def _wd_dest_register(self, body: dict):
        if not self._write_guard(need_json=False):
            return
        a = xfer_match.norm_addr(body.get("address"))
        cands = getattr(BUILDER, "_wd_dest_unknown", None)
        if cands is None:
            BUILDER.kick_refresh()
            return self._send(503, {"ok": False, "error": "출금 목적지 후보를 계산하는 중 — 잠시 뒤 다시 시도하세요"})
        u9 = cands.get(a)
        if not u9:
            return self._send(404, {"ok": False, "error": "거래소 출금 목적지 후보에 없는 주소"})
        alias = str(body.get("alias") or "").strip()
        if len(alias) > 40 or any(ord(c) < 32 for c in alias):
            return self._send(400, {"ok": False, "error": "지갑 이름은 40자 이내 한 줄"})
        chains = sorted({c9 for c9 in (depaddr.chain_of(n9, None, a) for n9 in (u9.get("networks") or [])) if c9})
        if not chains:
            chains = ["sol"] if not a.startswith("0x") else ["eth", "bsc", "base", "arbitrum"]
        try:
            import wallet_register
            reg = wallet_register.register_wallet(a, chains, alias or f"{a[:6]}…{a[-4:]}", source="exchange_withdraw", idempotent=True)
        except (ValueError, OSError) as e:
            if isinstance(e, OSError):
                return self._send(400, {"ok": False, "error": "지갑 등록 실패: 설정 파일을 읽거나 저장할 수 없습니다"})
            return self._send(400, {"ok": False, "error": f"지갑 등록 실패: {common.safe_err(e)}"})
        with BUILDER.lock:
            BUILDER.cache = None
        BUILDER.kick_refresh()
        apply9 = reg.get("apply") or {}
        return self._send(200, {"ok": True, "address": a, "chains": reg.get("chains") or chains, "restartNeeded": not apply9.get("runner")})

    def _flow_register(self, body: dict):
        if not self._write_guard():
            return
        a = xchain_match.norm(str(body.get("address") or "").strip())
        cands = getattr(BUILDER, "_flow_recips", None)
        if cands is None:
            BUILDER.kick_refresh()
            return self._send(503, {"ok": False, "error": "돈 흐름을 계산하는 중 — 잠시 뒤 다시 시도하세요"})
        u9 = cands.get(a)
        if not u9 or u9.get("level") not in ("high", "mid"):
            return self._send(404, {"ok": False, "error": "돈 흐름 추적에서 내 지갑 근거가 있는 상대 주소가 아니에요"})
        if not isinstance(body.get("alias") or "", str):
            return self._send(400, {"ok": False, "error": "alias 는 문자열"})
        alias = str(body.get("alias") or "").strip()
        if len(alias) > 24 or any(ord(c) < 32 for c in alias):
            return self._send(400, {"ok": False, "error": "지갑 이름은 24자 이내 한 줄"})
        chains = sorted(c9 for c9 in (u9.get("chains") or ()) if isinstance(c9, str) and re.fullmatch(r"[a-z0-9_-]{1,24}", c9))
        if not chains:
            chains = ["sol"] if not a.startswith("0x") else ["eth", "bsc", "base", "arbitrum"]
        try:
            import wallet_register
            reg = wallet_register.register_wallet(a, chains, alias or f"{a[:6]}…{a[-4:]}", source="flow_trace", idempotent=True)
        except (ValueError, OSError) as e:
            if isinstance(e, OSError):
                return self._send(400, {"ok": False, "error": "지갑 등록 실패: 설정 파일을 읽거나 저장할 수 없습니다"})
            return self._send(400, {"ok": False, "error": f"지갑 등록 실패: {common.safe_err(e)}"})
        log.info("flow_register: %s %s (목적지 %s)", a, chains, ",".join(sorted(u9.get("dests") or ()))[:200])
        with BUILDER.lock:
            BUILDER.cache = None
        BUILDER.kick_refresh()
        apply9 = reg.get("apply") or {}
        return self._send(200, {"ok": True, "address": a, "chains": reg.get("chains") or chains, "restartNeeded": not apply9.get("runner"),
                                "note": reg.get("note") or ""})

    def _outflow_resolve(self, body: dict):
        if not self._write_guard():
            return
        a = str(body.get("address") or "").strip()
        a = a.lower() if a.startswith("0x") else a
        if body.get("op") == "salealert":
            if not isinstance(body.get("on"), bool):
                return self._send(400, {"ok": False, "error": "on 은 true/false"})
            pr9 = BUILDER.prefs()
            pr9["sale_cand_alert"] = bool(body["on"])
            common.atomic_write_json(PREFS_PATH, pr9)
            with BUILDER.lock:
                BUILDER.cache = None
            return self._send(200, {"ok": True, "on": pr9["sale_cand_alert"]})
        if body.get("op") is not None:
            return self._outflow_op(a, body)
        verdict = str(body.get("verdict") or "")
        if verdict not in ("own", "exchange", "external", "clear"):
            return self._send(400, {"ok": False, "error": "verdict 는 own|exchange|external|clear"})
        if not isinstance(body.get("memo") or "", str):
            return self._send(400, {"ok": False, "error": "메모는 문자열"})
        memo = str(body.get("memo") or "").strip()
        if len(memo) > 200 or any(ord(c) < 32 for c in memo):
            return self._send(400, {"ok": False, "error": "메모는 200자 이내 한 줄"})
        ch_in = body.get("chains")
        if ch_in is not None and (not isinstance(ch_in, list) or len(ch_in) > 12
                                  or any(not isinstance(c, str) or not re.fullmatch(r"[a-z0-9_-]{1,24}", c) for c in ch_in)):
            return self._send(400, {"ok": False, "error": "chains 는 체인 이름 배열(≤12)"})
        for f9 in ("alias", "exchange", "category"):
            if body.get(f9) is not None and not isinstance(body.get(f9), str):
                return self._send(400, {"ok": False, "error": f"{f9} 는 문자열"})
        if len(str(body.get("alias") or "")) > 40:
            return self._send(400, {"ok": False, "error": "지갑 이름은 40자 이내"})
        dests = getattr(BUILDER, "_outflow_dests", None)
        if dests is None:
            BUILDER.build()
            dests = getattr(BUILDER, "_outflow_dests", None) or {}
        cur = BUILDER.outflow_decisions()
        if a not in dests and a not in cur:
            return self._send(404, {"ok": False, "error": "보낸 내역에 없는 목적지 주소"})
        ent = {"verdict": verdict, "ts": int(time.time())}
        restart = False
        apply9 = None
        exw9 = a.startswith("wd:") or (a in (getattr(BUILDER, "_outflow_exwd", None) or set()) and not (body.get("chains") or dests.get(a)))
        if verdict == "own" and exw9:
            ent.update({"alias": str(body.get("alias") or "").strip() or "내 지갑(추적 밖)", "chains": []})
        elif verdict == "own":
            chains = [str(c) for c in (body.get("chains") or dests.get(a) or [])][:12]
            alias = str(body.get("alias") or "").strip() or f"{a[:6]}…{a[-4:]}"
            try:
                import wallet_register
                reg = wallet_register.register_wallet(a, chains, alias, source="outflow", idempotent=True)
            except (ValueError, OSError) as e:
                if isinstance(e, OSError):
                    return self._send(400, {"ok": False, "error": "지갑 등록 실패: 설정 파일을 읽거나 저장할 수 없습니다"})
                return self._send(400, {"ok": False, "error": f"지갑 등록 실패: {common.safe_err(e)}"})
            ent.update({"alias": alias, "chains": reg.get("chains") or chains})
            apply9 = reg.get("apply") or {}
            restart = not apply9.get("runner")
        elif verdict == "exchange":
            ex = self._exchange_key(body.get("exchange"))
            if not ex or len(ex) > 24 or any(c in ex for c in "<>\"'`") or any(ord(c) < 32 for c in ex):
                return self._send(400, {"ok": False, "error": "exchange(거래소 이름, 1~24자) 필요"})
            ent.update({"exchange": ex, "chains": [] if a.startswith("wd:") else [str(c) for c in (body.get("chains") or dests.get(a) or [])][:12]})
        elif verdict == "external":
            cat = str(body.get("category") or "")
            if cat not in StateBuilder.OUTFLOW_CATEGORIES:
                return self._send(400, {"ok": False, "error": "category 는 " + " | ".join(StateBuilder.OUTFLOW_CATEGORIES)})
            ent["category"] = cat
        d = common.read_json(BUILDER.OUTFLOW_PATH, {}) if os.path.exists(BUILDER.OUTFLOW_PATH) else {}
        if not isinstance(d, dict):
            d = {}
        decs = d.setdefault("decisions", {})
        if not isinstance(decs, dict):
            decs = d["decisions"] = {}
        old9 = copy.deepcopy(decs.get(a)) if isinstance(decs.get(a), dict) else None
        prev0 = decs.get(a) if isinstance(decs.get(a), dict) else {}
        if "memo" not in body and prev0.get("memo"):
            memo = str(prev0["memo"])
        if memo:
            ent["memo"] = memo
        if verdict == "external" and prev0.get("verdict") == "external" and isinstance(prev0.get("links"), list) and prev0["links"]:
            ent["links"] = prev0["links"]
        if verdict == "external" and prev0.get("verdict") == "external" and isinstance(prev0.get("excludeLegs"), list) and prev0["excludeLegs"]:
            ent["excludeLegs"] = prev0["excludeLegs"]
        if verdict == "external" and prev0.get("verdict") == "external" and isinstance(prev0.get("dismiss"), list) and prev0["dismiss"]:
            ent["dismiss"] = prev0["dismiss"]
        if verdict == "clear":
            st9 = (getattr(BUILDER, "_outflow_status", None) or {}).get(a)
            if not prev0.get("verdict") and (st9 in ("exchange_matched", "returned", "bridge_matched", "bridge_untracked")
                                             or a in (getattr(BUILDER, "_outflow_autorows", None) or set())):
                ent = {"verdict": "clear", "noAuto": True, "ts": ent["ts"]}
                if memo:
                    ent["memo"] = memo
                decs[a] = ent
            elif memo:
                ent = decs[a] = {"memo": memo, "ts": ent["ts"]}
            else:
                decs.pop(a, None)
                ent = None
        else:
            prev = decs.get(a) or {}
            if {k: v for k, v in prev.items() if k != "ts"} == {k: v for k, v in ent.items() if k != "ts"}:
                ent["ts"] = prev.get("ts", ent["ts"])
            decs[a] = ent
        d["version"] = 1
        d["updated"] = int(time.time())
        common.atomic_write_json(BUILDER.OUTFLOW_PATH, d)
        self._of_after_save(a, old9, decs.get(a))
        return self._send(200, {"ok": True, "address": a, "decision": decs.get(a), "row": _bcall("of_row_patch", a, decs.get(a), old9),
                                "restartNeeded": restart, "apply": apply9,
                                "note": ("config 등록 완료 — tj-evm·tj-sol·tj-bsc·tj-core 재기동 뒤 백필·내 지갑 이동으로 재분류" if restart
                                         else ("등록 완료 — 약 30초 안에 수집기·core 가 자동으로 다시 시작해 백필·재분류" if (verdict == "own" and not exw9)
                                               else ("tj-core 가 60초 안에 재분류(거래소 입금 원가 승계)" if verdict == "exchange" else "저장됨")))})

    def _outflow_op(self, a: str, body: dict):
        op = body.get("op")
        if op not in ("memo", "link", "unlink", "exclude", "include", "ret", "dismiss", "undismiss"):
            return self._send(400, {"ok": False, "error": "op 는 memo | link | unlink | exclude | include | ret | dismiss | undismiss"})
        dests = getattr(BUILDER, "_outflow_dests", None)
        if dests is None:
            BUILDER.build()
            dests = getattr(BUILDER, "_outflow_dests", None) or {}
        d = common.read_json(BUILDER.OUTFLOW_PATH, {}) if os.path.exists(BUILDER.OUTFLOW_PATH) else {}
        if not isinstance(d, dict):
            d = {}
        decs = d.setdefault("decisions", {})
        if not isinstance(decs, dict):
            decs = d["decisions"] = {}
        if not a or (a not in dests and a not in decs):
            return self._send(404, {"ok": False, "error": "보낸 내역에 없는 목적지 주소"})
        old9 = copy.deepcopy(decs.get(a)) if isinstance(decs.get(a), dict) else None
        ent = dict(decs.get(a)) if isinstance(decs.get(a), dict) else {}
        now9 = int(time.time())
        if op == "ret":
            if not isinstance(body.get("on"), bool):
                return self._send(400, {"ok": False, "error": "on 은 true/false"})
            if ent.get("verdict") not in (None, "clear"):
                return self._send(409, {"ok": False, "error": "이미 판정한 목적지예요 — 판정을 되돌린 뒤 정리해 주세요"})
            if body["on"]:
                ent.update(verdict="clear", ret=True, ts=now9)
            else:
                ent.pop("ret", None)
                if ent.get("verdict") == "clear" and not ent.get("noAuto"):
                    ent.pop("verdict", None)
        elif op == "memo":
            if not isinstance(body.get("memo"), str):
                return self._send(400, {"ok": False, "error": "메모는 문자열"})
            memo = body["memo"].strip()
            if len(memo) > 200 or any(ord(c) < 32 for c in memo):
                return self._send(400, {"ok": False, "error": "메모는 200자 이내 한 줄"})
            if memo:
                ent["memo"] = memo
                ent.setdefault("ts", now9)
            else:
                ent.pop("memo", None)
        elif op in ("dismiss", "undismiss"):
            if ent.get("verdict") != "external":
                return self._send(409, {"ok": False, "error": "외부 유출로 확정한 목적지만 제안을 정리할 수 있어요"})
            k9 = body.get("key")
            cur9 = [str(x9) for x9 in (ent.get("dismiss") or []) if isinstance(x9, str)]
            if not isinstance(k9, str) or not k9 or len(k9) > 300:
                return self._send(400, {"ok": False, "error": "key 는 후보 키 문자열"})
            if op == "dismiss":
                if k9 not in (getattr(BUILDER, "_of_cands", None) or {}):
                    return self._send(400, {"ok": False, "error": "지금 후보에 없는 유입이에요"})
                cur9 = [x9 for x9 in cur9 if x9 != k9] + [k9]
            else:
                if k9 not in cur9:
                    return self._send(400, {"ok": False, "error": "뺀 제안이 아니에요"})
                cur9 = [x9 for x9 in cur9 if x9 != k9]
            if len(cur9) > 200:
                return self._send(400, {"ok": False, "error": "아님은 200개까지"})
            if cur9:
                ent["dismiss"] = cur9
            else:
                ent.pop("dismiss", None)
        elif op in ("exclude", "include"):
            if ent.get("verdict") != "external":
                return self._send(409, {"ok": False, "error": "외부 유출로 확정한 목적지만 참가금 레그를 고를 수 있어요"})
            k9 = body.get("key")
            cur9 = [x9 for x9 in (ent.get("excludeLegs") or []) if isinstance(x9, (str, dict))]
            if not isinstance(k9, str) or not k9 or len(k9) > 300:
                return self._send(400, {"ok": False, "error": "key 는 레그 키 문자열"})
            ek9 = lambda x9: str(x9.get("key") if isinstance(x9, dict) else x9)
            if op == "exclude":
                if k9 not in ((getattr(BUILDER, "_outflow_legkeys", None) or {}).get(a) or set()):
                    return self._send(400, {"ok": False, "error": "이 목적지로 보낸 레그가 아니에요"})
                mt9 = ((getattr(BUILDER, "_outflow_legmeta", None) or {}).get(a) or {}).get(k9) or (None, None)
                cur9 = [x9 for x9 in cur9 if ek9(x9) != k9] + [{"key": k9, "asset": mt9[0], "qb": mt9[1]}]
            else:
                if k9 not in [ek9(x9) for x9 in cur9]:
                    return self._send(400, {"ok": False, "error": "참가금에서 뺀 레그가 아니에요"})
                cur9 = [x9 for x9 in cur9 if ek9(x9) != k9]
            if len(cur9) > 200:
                return self._send(400, {"ok": False, "error": "참가금 아님은 200개까지"})
            if cur9:
                ent["excludeLegs"] = cur9
            else:
                ent.pop("excludeLegs", None)
        else:
            if ent.get("verdict") != "external":
                return self._send(409, {"ok": False, "error": "외부 유출로 확정한 목적지만 받은 것과 연결할 수 있어요"})
            links = [l9 for l9 in (ent.get("links") or []) if isinstance(l9, dict)]
            if op == "unlink":
                k9 = body.get("key")
                if not isinstance(k9, str) or k9 not in {str(l9.get("key")) for l9 in links}:
                    return self._send(400, {"ok": False, "error": "이 목적지에 연결되지 않은 유입"})
                links = [l9 for l9 in links if str(l9.get("key")) != k9]
            else:
                req9 = body.get("links")
                if not isinstance(req9, list) or not 1 <= len(req9) <= 20 or not all(isinstance(x9, dict) for x9 in req9):
                    return self._send(400, {"ok": False, "error": "links 는 [{kind, key}] 1~20개"})
                cands = getattr(BUILDER, "_of_cands", None) or {}
                first9 = (getattr(BUILDER, "_outflow_first", None) or {}).get(a)
                taken9 = {str(l9.get("key")): a9 for a9, v9 in decs.items() if a9 != a and isinstance(v9, dict)
                          for l9 in (v9.get("links") or []) if isinstance(l9, dict)}
                for x9 in req9:
                    kind9, k9 = x9.get("kind"), x9.get("key")
                    if kind9 not in StateBuilder.OF_LINK_KINDS or not isinstance(k9, str) or len(k9) > 300:
                        return self._send(400, {"ok": False, "error": "kind 는 refund | tokens · key 는 문자열"})
                    c9 = cands.get(k9)
                    if not c9:
                        return self._send(400, {"ok": False, "error": "연결 후보에 없는 유입(내 지갑·거래소로 받은 것만)"})
                    if first9 is None or int(c9["ts"]) < int(first9):
                        return self._send(400, {"ok": False, "error": "보낸 시각 이전에 받은 유입은 연결할 수 없어요"})
                    if (kind9 == "refund") != bool(c9.get("stable")):
                        return self._send(400, {"ok": False, "error": "환불은 스테이블 유입만, 세일 토큰은 스테이블이 아닌 유입만"})
                    own9 = (getattr(BUILDER, "_of_claims", None) or {}).get(k9)
                    if own9 and not any(isinstance(l0, dict) and str(l0.get("key")) == own9[1]
                                        for l0 in ((decs.get(own9[0]) or {}).get("links") or [])):
                        own9 = None
                    if k9 in taken9 or (own9 and own9[0] != a):
                        return self._send(409, {"ok": False, "error": "다른 보낸 내역에 이미 연결된 유입"})
                    alias9 = {k9} | ({own9[1]} if own9 else set())
                    links = [l9 for l9 in links if str(l9.get("key")) not in alias9]
                    links.append({"kind": kind9, "key": k9, "asset": c9.get("asset"), "qb": c9.get("qb"), "sym": c9.get("sym"),
                                  "qty": c9.get("qty"), "ts": int(c9["ts"]), "where": c9.get("where"), "tx": c9.get("ref"), "lts": now9})
                if len(links) > StateBuilder.OF_LINK_MAX:
                    return self._send(400, {"ok": False, "error": f"한 목적지에 연결은 {StateBuilder.OF_LINK_MAX}개까지"})
            if links:
                ent["links"] = links
            else:
                ent.pop("links", None)
        if set(ent) <= {"ts"}:
            decs.pop(a, None)
            ent = None
        else:
            decs[a] = ent
        d["version"] = 1
        d["updated"] = now9
        common.atomic_write_json(BUILDER.OUTFLOW_PATH, d)
        self._of_after_save(a, old9, ent)
        return self._send(200, {"ok": True, "address": a, "decision": ent, "row": _bcall("of_row_patch", a, ent, old9)})

    def _of_after_save(self, a, old, new):
        if _bcall("of_memo_only", a, old, new) and _bcall("mpatch", {"of_memo"}):
            try:
                if salelink.dest_name(a, old if isinstance(old, dict) else {}) != salelink.dest_name(a, new if isinstance(new, dict) else {}):
                    BUILDER.soft_invalidate()
            except Exception:
                BUILDER.soft_invalidate()
            return
        with BUILDER.lock:
            BUILDER.cache = None

    OF_CAND_CAP = 300
    OF_CAND_CAP_STABLE = 100

    def _send_outflow_cands(self, query):
        qs = urllib.parse.parse_qs(query)
        a = (qs.get("address") or [""])[0].strip()
        a = a.lower() if a.startswith("0x") else a
        q9 = (qs.get("q") or [""])[0].strip().lower()
        all9 = (qs.get("all") or [""])[0] == "1"
        spam9 = (qs.get("spam") or [""])[0] == "1"
        if not a or len(a) > 200 or len(q9) > 80:
            return self._send(400, {"ok": False, "error": "address 필요 · q 는 80자 이내"})
        BUILDER.snapshot()
        first9 = (getattr(BUILDER, "_outflow_first", None) or {}).get(a)
        if first9 is None:
            return self._send(404, {"ok": False, "error": "보낸 내역에 없는 목적지 주소"})
        first9 = int(first9)
        to9 = None if all9 else first9 + StateBuilder.OF_CAND_WINDOW
        decs = BUILDER.outflow_decisions()
        mine9 = {str(l9.get("key")): l9.get("kind") for l9 in ((decs.get(a) or {}).get("links") or []) if isinstance(l9, dict)} \
            if isinstance(decs.get(a), dict) else {}
        taken9 = {str(l9.get("key")) for a9, v9 in decs.items() if a9 != a and isinstance(v9, dict)
                  for l9 in (v9.get("links") or []) if isinstance(l9, dict)}
        ret9 = (getattr(BUILDER, "_outflow_rettx", None) or {}).get(a) or set()
        fw9 = (getattr(BUILDER, "_outflow_from_w", None) or {}).get(a) or set()
        dis9 = {str(x9) for x9 in (((decs.get(a) or {}) if isinstance(decs.get(a), dict) else {}).get("dismiss") or []) if isinstance(x9, str)}
        cl9 = getattr(BUILDER, "_of_claims", None) or {}
        where = BUILDER._of_where
        quar9 = getattr(BUILDER, "_risk_quarantined", None) or set()
        out, quar_n = [], 0
        for c9 in (getattr(BUILDER, "_of_cands", None) or {}).values():
            own9 = cl9.get(c9["key"])
            ts9 = int(c9["ts"])
            if ts9 < first9 or (to9 is not None and ts9 > to9) or c9["key"] in taken9 or (own9 and own9[0] != a):
                continue
            x9 = {"key": c9["key"], "sym": c9["sym"], "qty": c9["qty"], "ts": ts9,
                  "t": datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d %H:%M"), "where": where(c9.get("where") or ""),
                  "chain": c9.get("chain") or "", "tx": c9.get("ref") or "", "stable": bool(c9.get("stable")),
                  "sale": bool(c9.get("sale")), "fromDest": str(c9.get("ref") or "").lower() in ret9, "quar": c9.get("gid") in quar9,
                  "linked": mine9.get(c9["key"]) or (own9[2] if own9 and own9[0] == a else None),
                  "fromSender": str(c9.get("where") or "") in fw9, "dismissed": c9["key"] in dis9}
            if q9 and q9 not in (x9["sym"] + " " + x9["where"] + " " + x9["tx"] + " " + x9["t"]).lower():
                continue
            if x9["quar"] and not spam9 and not x9["linked"]:
                quar_n += 1
                continue
            out.append(x9)
        out.sort(key=lambda x9: (x9["stable"], x9["dismissed"], not x9["fromSender"], x9["ts"] - first9))
        tok9 = [x9 for x9 in out if not x9["stable"]]
        st9 = [x9 for x9 in out if x9["stable"]]
        shown = tok9[:self.OF_CAND_CAP] + st9[:self.OF_CAND_CAP_STABLE]
        self._send(200, {"ok": True, "address": a, "firstTs": first9, "total": len(out), "totalTok": len(tok9), "totalStable": len(st9),
                         "shown": len(shown), "quarN": quar_n, "window": {"from": first9, "to": to9, "all": all9}, "spam": spam9, "q": q9,
                         "cands": shown})

    def _backfill_request(self, body: dict):
        if not self._write_guard(origin_err="출처(Origin) 확인 실패"):
            return
        path = StateBuilder.BF_REQ_PATH
        cur = common.read_json(path, {}) if os.path.exists(path) else {}
        if not isinstance(cur, dict):
            cur = {}
        if body.get("clear"):
            if os.path.exists(path):
                os.remove(path)
            return self._send(200, {"ok": True, "request": {}})
        secs = set(BUILDER._backfill_since_view()["sections"]) | {"okx", "binance", "bybit", "kucoin", "gate", "bithumb"}
        today = datetime.now(KST).strftime("%Y-%m-%d")

        def _d(v):
            v = str(v or "").strip()
            if not re.fullmatch(r"20\d\d-\d\d-\d\d", v) or not bf_engine.parse_date_ts(v):
                raise ValueError("날짜는 YYYY-MM-DD")
            if v > today or v < "2015-01-01":
                raise ValueError("날짜 범위(2015-01-01 ~ 오늘)")
            return v
        try:
            new = dict(cur)
            if body.get("since"):
                v = _d(body["since"])
                new["since"] = min(v, cur["since"]) if cur.get("since") else v
            per_in = body.get("per") or {}
            if not isinstance(per_in, dict):
                raise ValueError("per 는 {섹션: 날짜}")
            per = dict(new.get("per") or {})
            for k, v in per_in.items():
                if k not in secs:
                    raise ValueError(f"모르는 섹션: {str(k)[:20]}")
                v = _d(v)
                per[k] = min(v, per[k]) if per.get(k) else v
            if per:
                new["per"] = per
            if not new.get("since") and not new.get("per"):
                raise ValueError("since 또는 per 필요")
        except ValueError as e:
            return self._send(400, {"ok": False, "error": common.safe_err(e)})
        new["updated"] = int(time.time())
        common.atomic_write_json(path, new)
        with BUILDER.lock:
            BUILDER.cache = None
        return self._send(200, {"ok": True, "request": new,
                                "note": "수집기가 다음 주기(≤1분)에 옛 구간을 가져오고, 끝나면 tj-core 가 원장을 자동 재구축합니다(≈4분 소비 정지)"})

    def _send_asset(self, fpath, ctype, query=""):
        if ctype == "font/woff2":
            with open(fpath, "rb") as f:
                raw = f.read()
            return self._send_bytes(200, raw, None, ctype, etag='W/"' + os.path.basename(fpath)[:-6] + '"', cache="private, max-age=31536000, immutable")
        a = _asset(fpath)
        if os.path.normpath(fpath) == os.path.normpath(os.path.join(V2_DIR, "index.html")):
            return self._send_v2_index(a)
        v = urllib.parse.parse_qs(query).get("v", [""])[0]
        cache = "private, max-age=31536000, immutable" if (v and v == a["hash"]) else "private, no-cache"
        self._send_bytes(200, a["raw"], a["gz"], ctype, etag=a["etag"], cache=cache)

    def _send_v2_index(self, a):
        b = BUILDER
        snap = getattr(getattr(b, "snaps", None), "cur", None) if b is not None else None
        hero = getattr(snap, "hero", None) if snap is not None else None
        csp = (("Content-Security-Policy", _v2_csp(a["raw"], a["hash"])),)
        if hero and any(c.strip() == "tj_v2_rand=1" for raw9 in (self.headers.get_all("Cookie") or []) for c in raw9.split(";")):
            hero = None
        if not hero or not _hero_ok(b, snap) or b"<!--HERO-->" not in a["raw"]:
            return self._send_bytes(200, a["raw"], a["gz"], "text/html; charset=utf-8", etag=a["etag"], cache="private, no-cache", extra=csp)
        k9 = (a["hash"], snap.ver)
        with _HERO_HTML_LOCK:
            m9 = _HERO_HTML.get(k9)
        if m9 is None:
            js = json.dumps(hero, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").encode()
            raw = a["raw"].replace(b"<!--HERO-->", b'<script id="tjHero" type="application/json">' + js + b"</script>", 1)
            m9 = (raw, websnap.gz(raw), f'W/"{a["hash"]}-{snap.ver[:8]}"')
            with _HERO_HTML_LOCK:
                _HERO_HTML.clear()
                _HERO_HTML[k9] = m9
        self._send_bytes(200, m9[0], m9[1], "text/html; charset=utf-8", etag=m9[2], cache="private, no-cache", extra=csp)

    def _send_state_v2(self, query):
        qs9 = urllib.parse.parse_qs(query)
        since = qs9.get("since", [""])[0][:64]
        if since and not self._VER_RE.fullmatch(since):
            since = ""
        slim9 = qs9.get("slim", [""])[0] == "1"
        nd9 = slim9 and qs9.get("nd", [""])[0] == "1"
        snap = BUILDER.snapshot()
        snaps9 = BUILDER.snaps
        if since and hasattr(snaps9, "hold"):
            snaps9.hold(since)
        if since and since == snap.ver:
            BUILDER.snaps.note_served(snap.ver)
            body = websnap.dumps({"v": snap.ver, "b": since, "same": 1})
            return self._send_bytes(200, body, None, extra=(("X-TJ-Kind", "same"), ("X-TJ-Ver", snap.ver)))
        if since and not nd9:
            dg = BUILDER.snaps.delta_gz(since, target=snap)
            if dg:
                BUILDER.snaps.note_served(snap.ver)
                hdr = (("X-TJ-Kind", "delta"), ("X-TJ-Ver", snap.ver))
                if self._gzip_ok():
                    return self._send_bytes(200, b"", dg, extra=hdr)
                return self._send_bytes(200, gzip.decompress(dg), None, extra=hdr)
        BUILDER.snaps.note_served(snap.ver)
        if hasattr(snaps9, "pin"):
            snaps9.pin(snap.ver)
        if slim9 and snap.slim_gz is not None and snap.parts_gz:
            hdr = (("X-TJ-Kind", "slim"), ("X-TJ-Ver", snap.ver), ("X-TJ-Parts", ",".join(websnap.PARTS)))
            if self._gzip_ok():
                return self._send_bytes(200, b"", snap.slim_gz, extra=hdr)
            return self._send_bytes(200, gzip.decompress(snap.slim_gz), None, extra=hdr)
        self._send_bytes(200, snap.raw, snap.gz, etag=f'W/"{snap.ver}"',
                         extra=(("X-TJ-Kind", "full"), ("X-TJ-Ver", snap.ver)))

    _VER_RE = re.compile(r"[0-9a-f]{16}")

    def _send_part(self, query):
        qs9 = urllib.parse.parse_qs(query)
        name = qs9.get("name", [""])[0]
        ver = qs9.get("v", [""])[0]
        if name not in websnap.PARTS or not self._VER_RE.fullmatch(ver):
            return self._send(400, {"ok": False, "error": "name(ev|oft)·v(버전) 필요"})
        BUILDER._last_client = time.time()
        g9 = BUILDER.snaps.part_gz(ver, name)
        if g9 is None:
            return self._send(410, {"ok": False, "stale": 1, "error": "그 버전 조각이 없어요 — 상태를 다시 받으세요"})
        etag = f'W/"{ver}-{name}"'
        if self._gzip_ok():
            return self._send_bytes(200, b"", g9, etag=etag, cache="private, no-store", extra=(("X-TJ-Ver", ver),))
        return self._send_bytes(200, gzip.decompress(g9), None, etag=etag, cache="private, no-store", extra=(("X-TJ-Ver", ver),))

    _DAY_RE = re.compile(r"20\d\d-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])")

    @staticmethod
    def _max_age(query):
        v = urllib.parse.parse_qs(query or "").get("max_age", [""])[0]
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return min(86400.0, max(5.0, f)) if f == f else None

    def _send_day_events(self, query):
        qs = urllib.parse.parse_qs(query)
        one = (qs.get("date") or [""])[0].strip()
        d_from = one or (qs.get("from") or [""])[0].strip() or "2000-01-01"
        d_to = one or (qs.get("to") or [""])[0].strip() or "2099-12-31"
        if not (self._DAY_RE.fullmatch(d_from) and self._DAY_RE.fullmatch(d_to)) or d_from > d_to:
            return self._send(400, {"ok": False, "error": "date(또는 from·to)는 YYYY-MM-DD"})
        lim9, off9 = (qs.get("limit") or [""])[0].strip(), (qs.get("offset") or [""])[0].strip()
        if (lim9 and not lim9.isdigit()) or (off9 and not off9.isdigit()):
            return self._send(400, {"ok": False, "error": "limit·offset 은 0 이상의 정수"})
        ma9 = self._max_age(query)
        if ma9 is not None and not onboarding.origin_ok(self, required=False):
            return self._send(403, {"ok": False, "error": "다른 출처(사이트)에서 온 요청은 거부합니다"})
        BUILDER.snapshot() if ma9 is None else BUILDER.snapshot(max_age=ma9)
        body = (BUILDER.day_events(d_from, d_to) if not lim9 else
                BUILDER.day_events(d_from, d_to, limit=int(lim9), offset=int(off9) if off9 else 0))
        if body is None:
            BUILDER.kick_refresh()
            return self._send(503, {"ok": False, "error": "기록 색인을 만드는 중 — 잠시 뒤 다시 시도하세요"})
        if one:
            body["date"] = one
        self._send(200, body)

    _YM_RE = re.compile(r"20\d\d-(0[1-9]|1[0-2])")

    def _send_tax_rows(self, query):
        qs = urllib.parse.parse_qs(query)
        ym = (qs.get("ym") or [""])[0].strip()
        sym = (qs.get("sym") or [""])[0].strip()
        off = (qs.get("offset") or ["0"])[0].strip()
        if not self._YM_RE.fullmatch(ym) or len(sym) > 120 or not off.isdigit() or len(off) > 7:
            return self._send(400, {"ok": False, "error": "ym(YYYY-MM) 필요 · sym(선택) · offset(0 이상 정수)"})
        BUILDER.snapshot()
        body = BUILDER.tax_rows(ym, sym, int(off))
        if body is None:
            BUILDER.kick_refresh()
            return self._send(503, {"ok": False, "error": "명세 색인을 만드는 중 — 잠시 뒤 다시 시도하세요"})
        self._send(200, body)

    def _send_curve_hist(self, query):
        qs = urllib.parse.parse_qs(query)
        r9 = (qs.get("range") or ["all"])[0].strip()
        if r9 not in ("90", "180", "365", "all"):
            return self._send(400, {"ok": False, "error": "range = 90 | 180 | 365 | all"})
        code9, body9 = histcurve.HIST.view(None if r9 == "all" else int(r9))
        self._send(code9, body9)

    def _send_receipt(self, query):
        qs = urllib.parse.parse_qs(query)
        d9 = (qs.get("date") or [""])[0].strip()
        sym = (qs.get("sym") or [""])[0].strip()
        if not self._DAY_RE.fullmatch(d9) or not sym or len(sym) > 120:
            return self._send(400, {"ok": False, "error": "date(YYYY-MM-DD)·sym 필요"})
        try:
            datetime.strptime(d9, "%Y-%m-%d")
        except ValueError:
            return self._send(400, {"ok": False, "error": "date는 유효한 YYYY-MM-DD 날짜여야 합니다"})
        BUILDER.snapshot()
        body = BUILDER.receipt(d9, sym)
        if body is None:
            BUILDER.kick_refresh()
            return self._send(503, {"ok": False, "error": "기록 색인을 만드는 중 — 잠시 뒤 다시 시도하세요"})
        self._send(200, body)

    def _send_fut_receipt(self, query):
        qs = urllib.parse.parse_qs(query)
        d9 = (qs.get("date") or [""])[0].strip()
        if not self._DAY_RE.fullmatch(d9):
            return self._send(400, {"ok": False, "error": "date(YYYY-MM-DD) 필요"})
        try:
            datetime.strptime(d9, "%Y-%m-%d")
        except ValueError:
            return self._send(400, {"ok": False, "error": "date는 유효한 YYYY-MM-DD 날짜여야 합니다"})
        fn9 = getattr(BUILDER, "fut_receipt", None)
        if fn9 is None:
            return self._send(200, {"ok": True, "empty": True, "date": d9})
        BUILDER.snapshot()
        body = fn9(d9)
        if body is None:
            BUILDER.kick_refresh()
            return self._send(503, {"ok": False, "error": "기록 색인을 만드는 중 — 잠시 뒤 다시 시도하세요"})
        self._send(200, body)

    _IV_OK = ("1m", "5m")
    _AFTER_OK = ("1h", "6h", "24h")

    def _chart_args(self, src, fut_ok=False):
        if not isinstance(src, dict):
            return None, {"ok": False, "error": "date(YYYY-MM-DD)·sym 필요"}
        g = lambda k, d="": (src.get(k) if isinstance(src.get(k), str) else d)
        d9, sym = (g("date") or "").strip(), (g("sym") or "").strip()
        iv, after, venue = g("iv", "5m") or "5m", g("after", "1h") or "1h", (g("venue") or "").strip() or None
        side, bvenue = g("side", "sell") or "sell", (g("bvenue") or "").strip() or None
        if side not in (("sell", "buy", "fut") if fut_ok else ("sell", "buy")) or (src.get("side") is not None and not isinstance(src.get("side"), str)) \
                or (bvenue is not None and len(bvenue) > 200):
            return None, {"ok": False, "error": "side = sell|buy" + ("|fut" if fut_ok else "") + " · bvenue ≤ 200자"}
        if not self._DAY_RE.fullmatch(d9) or not sym or len(sym) > 120:
            return None, {"ok": False, "error": "date(YYYY-MM-DD)·sym 필요"}
        try:
            datetime.strptime(d9, "%Y-%m-%d")
        except ValueError:
            return None, {"ok": False, "error": "date는 유효한 YYYY-MM-DD 날짜여야 합니다"}
        if iv not in self._IV_OK or after not in self._AFTER_OK or (venue is not None and len(venue) > 200):
            return None, {"ok": False, "error": "iv = 1m|5m · after = 1h|6h|24h · venue ≤ 200자"}
        return {"date": d9, "sym": sym, "iv": iv, "after": after, "venue": venue, "side": side, "bvenue": bvenue}, None

    def _send_receipt_chart(self, query):
        if not onboarding.origin_ok(self, required=False):
            return self._send(403, {"ok": False, "error": "다른 출처(사이트)에서 온 요청은 거부합니다"})
        qs = urllib.parse.parse_qs(query)
        a9, err = self._chart_args({k: v[0] for k, v in qs.items() if v}, fut_ok=True)
        if err:
            return self._send(400, err)
        BUILDER.snapshot()
        body, st9 = BUILDER.chart_request(a9["date"], a9["sym"], a9["iv"], a9["after"], a9["venue"], side=a9["side"], bvenue=a9["bvenue"])
        if st9 != "ok":
            return self._send(202, {"ok": True, "status": st9, "retryAfter": 3,
                                    "message": "차트를 준비하는 중이에요" if st9 == "preparing" else "다른 차트를 받는 중이에요 — 잠시 뒤 다시"})
        if body is None:
            BUILDER.kick_refresh()
            return self._send(503, {"ok": False, "error": "기록 색인을 만드는 중 — 잠시 뒤 다시 시도하세요"})
        if (qs.get("inp") or [""])[0] == "1" and body.get("evalFp"):
            ik9 = (("buy",) if a9["side"] == "buy" else ()) + (a9["date"], body.get("sym"), body["evalFp"])
            inp9 = (getattr(BUILDER, "_eval_inputs", None) or {}).get(ik9)
            msym9 = memo_driven(a9["date"], body.get("sym"), inp9, a9["side"]) if inp9 is not None else None
            if msym9:
                inp9 = None
            if inp9 is not None:
                body = dict(body, evalInput=inp9)
        self._send(200, body)

    def _send_receipt_list(self, query):
        qs = urllib.parse.parse_qs(query)
        a9, b9 = (qs.get("from") or [""])[0].strip(), (qs.get("to") or ["2099-12-31"])[0].strip()
        if not (self._DAY_RE.fullmatch(a9) and self._DAY_RE.fullmatch(b9)) or a9 > b9:
            return self._send(400, {"ok": False, "error": "from·to 는 YYYY-MM-DD"})
        BUILDER.snapshot()
        body = BUILDER.receipt_list(a9, b9)
        if body is None:
            BUILDER.kick_refresh()
            return self._send(503, {"ok": False, "error": "기록 색인을 만드는 중 — 잠시 뒤 다시 시도하세요"})
        self._send(200, body)

    def _send_receipt_eval(self, query):
        qs = urllib.parse.parse_qs(query)
        d9 = (qs.get("date") or [""])[0].strip()
        sym = (qs.get("sym") or [""])[0].strip()
        side = (qs.get("side") or ["sell"])[0].strip() or "sell"
        if not self._DAY_RE.fullmatch(d9) or not sym or len(sym) > 120:
            return self._send(400, {"ok": False, "error": "date(YYYY-MM-DD)·sym 필요"})
        if side not in ("sell", "buy"):
            return self._send(400, {"ok": False, "error": "side = sell|buy"})
        st = BUY_EVALS if side == "buy" else SELL_EVALS
        recs = st.get(d9, sym)
        k9 = f"{d9}|{sym}"
        memo9 = DAY_MEMO_REEVAL.pending(d9, day_memo.norm_sym(sym) or sym)
        st9 = "running" if (k9 in st.running or memo9) else ("error" if k9 in st.errors else ("done" if recs else "none"))
        day9 = datetime.now(KST).strftime("%Y-%m-%d")
        body = {"ok": True, "date": d9, "sym": sym, "status": st9, "eval": StateBuilder._eval_rec(recs[0], side) if recs else None,
                "history": [{"fp": r.get("fp"), "at": r.get("at"), "score": r.get("score"), "verdict": r.get("verdict")} for r in recs[:10]],
                "budget": st.budget(day9, sellchart.daily_max(BUILDER.cfg, side))}
        if side == "buy":
            body["side"] = "buy"
        if st9 == "error":
            body["error"] = st.errors[k9].get("error")
        self._send(200, body)

    def _ops_post(self, path: str, body: dict):
        if not self._write_guard():
            return None
        now9 = time.time()
        with _OPS_RL_LOCK:
            while _OPS_RL and now9 - _OPS_RL[0] > 60:
                _OPS_RL.popleft()
            if len(_OPS_RL) >= 30:
                return self._send(429, {"ok": False, "error": "요청이 너무 많아요 — 잠시 뒤 다시"})
            _OPS_RL.append(now9)
        act = path[len("/api/ops/"):]
        if act == "rebuild_approve":
            sha9 = body.get("report_sha")
            ok9, msg9 = ops_requests.approve(sha9 if isinstance(sha9, str) else "", "web")
        elif act == "rebuild_cancel":
            ok9 = ops_requests.cancel_approve()
            msg9 = "승인 취소" if ok9 else "취소할 승인이 없어요"
        elif act == "poison_replay":
            ids9 = body.get("ids")
            ok9, msg9 = ops_requests.poison_request(ids=ids9 if isinstance(ids9, list) else None, all_=False, by="web")
        elif act == "decimals_resolve":
            ok9, msg9 = ops_requests.decimals_request(body.get("asset_id"), body.get("stored"), body.get("seen"), "web")
        else:
            return self._send(404, {"ok": False, "error": "없는 요청"})
        log.warning("정리 요청(%s): %s — %s", act, "접수" if ok9 else "거절", str(msg9)[:160])
        return self._send(200 if ok9 else 409, {"ok": bool(ok9), ("msg" if ok9 else "error"): msg9, "ops": ops_requests.status()})

    def _write_guard(self, need_json: bool = True, origin_err: str = "출처(Origin) 확인 실패 — 같은 화면에서만 요청할 수 있습니다") -> bool:
        if not onboarding.origin_ok(self, required=True):
            self._send(403, {"ok": False, "error": origin_err})
            return False
        tok = self.headers.get("X-TJ-CSRF") or ""
        try:
            import settings_store
            good = bool(tok) and hmac.compare_digest(tok, settings_store.csrf_token())
        except Exception:
            good = False
        if not good:
            self._send(403, {"ok": False, "error": "CSRF 토큰 불일치 — 페이지를 새로고침하세요"})
            return False
        if need_json and "application/json" not in (self.headers.get("Content-Type") or ""):
            self._send(415, {"ok": False, "error": "JSON 요청만 받습니다"})
            return False
        return True

    def _alert_prefs_post(self, prefs, body):
        if not self._write_guard():
            return
        old9 = prefs.get(alert_prefs.PREF_KEY)
        doc9, err9 = alert_prefs.apply_post(old9, body)
        if err9:
            return self._send(400, {"ok": False, "error": err9})
        if isinstance(old9, dict) and old9.get("v") != alert_prefs.SCHEMA and "alert_prefs_v1" not in prefs:
            prefs["alert_prefs_v1"] = old9
        prefs[alert_prefs.PREF_KEY] = doc9
        common.atomic_write_json(PREFS_PATH, prefs)
        log.info("알림 설정 저장: %s", alert_prefs.match_preset(doc9))
        self._send(200, _alert_view(prefs))

    def _alert_test_post(self, body):
        if not self._write_guard():
            return
        cat9 = body.get("cat")
        if not isinstance(cat9, str) or cat9 not in alert_prefs.CAT:
            return self._send(400, {"ok": False, "error": "cat(알림 카테고리) 필요"})
        if not _tg_connected():
            return self._send(409, {"ok": False, "error": "텔레그램이 연결돼 있지 않아요 — 설정 › 연결 · 키에서 먼저 연결하세요"})
        now9 = time.time()
        with _ALERT_TEST_LOCK:
            _ALERT_TEST_T[:] = [x for x in _ALERT_TEST_T if now9 - x[0] < 3600]
            if any(c9 == cat9 and now9 - t9 < 60 for t9, c9 in _ALERT_TEST_T):
                return self._send(429, {"ok": False, "error": "같은 종류 테스트는 1분에 한 번이에요 — 잠시 뒤 다시"})
            if len(_ALERT_TEST_T) >= ALERT_TEST_HOURLY:
                left9 = max(1, int((3600 - (now9 - min(t9 for t9, _c in _ALERT_TEST_T))) // 60) + 1)
                return self._send(429, {"ok": False, "error": f"테스트는 시간당 {ALERT_TEST_HOURLY}통까지예요 — 약 {left9}분 뒤 다시"})
            _ALERT_TEST_T.append((now9, cat9))
        _append_alert(alert_watch.test_line(cat9))
        self._send(200, {"ok": True, "cat": cat9, "queued": True})

    def _oa_view(self):
        q9 = _oa_quoter()
        try:
            with other_assets.STORE_LOCK:
                d9 = other_assets.load_store()
        except other_assets.StoreError as e9:
            return {"ok": False, "error": common.safe_err(e9)}
        bc9 = (getattr(BUILDER, "cfg", None) or {}).get("brokers")
        return other_assets.view(d9, q9, _oa_rate(), bc9 if isinstance(bc9, dict) else {})

    def _send_wow(self, path, query):
        if not onboarding.origin_ok(self, required=False):
            return self._send(403, {"ok": False, "error": "다른 출처(사이트)에서 온 요청은 거부합니다"})
        qs9 = urllib.parse.parse_qs(query or "")
        g9 = lambda k: (qs9.get(k) or [""])[0]
        last9 = getattr(BUILDER, "_last_out", None) or {}
        f9 = last9.get("fields") if isinstance(last9, dict) else None
        bt9 = last9.get("builtAt") if isinstance(last9, dict) and isinstance(f9, dict) else None
        if not isinstance(f9, dict) and onboarding.DEMO:
            try:
                b9 = BUILDER.build() or {}
                f9, bt9 = b9.get("fields"), b9.get("builtAt")
            except Exception:
                f9 = None
        f9 = f9 if isinstance(f9, dict) else {}
        if not f9:
            bt9 = None
        conn9 = None
        try:
            if path == "/api/search/ask":
                cfg9 = (getattr(BUILDER, "cfg", None) or {}).get("wow") or {}
                coins9 = sorted({str(c.get("sym") or "").upper() for c in (f9.get("coins") or ()) if isinstance(c, dict) and c.get("sym")})[:800]
                body = wow2.ask(g9("q"), coins=coins9, chains=sorted(CHAIN_NAME), rate=float(f9.get("rate") or 1384),
                               llm_on=(cfg9.get("ask_llm") is True) and not onboarding.DEMO, llm_cap=int(cfg9.get("ask_llm_daily_max") or 40))
                return self._send(200 if body.get("ok") else 400, body)
            conn9 = demo_data.ledger() if onboarding.DEMO else wow2._ro()
            hist9 = demo_data.DemoHist() if onboarding.DEMO else histcurve.HIST
            if path == "/api/wow/tm":
                kit9 = getattr(hist9, "kit", None) or {}
                now9 = {str(k): float(g.get("lp") or g.get("ov") or 0) for k, g in (kit9.get("groups") or {}).items()}
                body = wow2.tm(g9("date"), hist=None if onboarding.DEMO else hist9, daily=getattr(BUILDER, "daily", None), dpx=getattr(BUILDER, "daily_px", None), fields=f9, conn=conn9,
                              chain_names=CHAIN_NAME, now_px=now9)
                if body.get("ok"):
                    body["builtAt"] = bt9
            else:
                body = wow2.flows(f9, conn=conn9, chain_names=CHAIN_NAME, since=g9("since") or None, hist=hist9)
            self._send(200 if body.get("ok") else 400, body)
        except Exception as e9:
            log.warning("감탄 기능 %s 실패: %s", path, type(e9).__name__, exc_info=True)
            self._send(503, {"ok": False, "error": "지금은 만들지 못했어요 — 잠시 뒤 다시"})
        finally:
            if conn9 is not None:
                try:
                    conn9.close()
                except Exception:
                    pass

    def _send_search(self, query):
        qs9 = urllib.parse.parse_qs(query or "")
        g9 = lambda k: (qs9.get(k) or [""])[0]
        kinds9 = [k for k in g9("kinds").split(",") if k] or None
        req9 = {"q": g9("q")[:search_index.Q_MAX], "kinds": kinds9, "limit": g9("limit") or None,
                "after": g9("after") or None, "before": g9("before") or None, "offset": g9("offset") or None}
        try:
            body = SEARCH_POOL.run(req9)
            if body is None:
                body = search_index.search(req9["q"], kinds=kinds9, limit=req9["limit"], after=req9["after"], before=req9["before"], offset=req9["offset"])
        except Exception as e9:
            log.warning("검색 실패: %s", type(e9).__name__)
            return self._send(503, {"ok": False, "error": "검색하지 못했어요 — 잠시 뒤 다시"})
        self._send(200, body)

    def _send_nft(self, query):
        try:
            v9 = _nft_tracker().view()
        except Exception as e9:
            log.warning("NFT 보기 실패: %s", type(e9).__name__)
            return self._send(503, {"ok": False, "error": "NFT 목록을 만들지 못했어요"})
        self._send(200, v9)

    def _nft_post(self, body):
        if not self._write_guard():
            return
        v9, err9 = _nft_tracker().apply_prefs(body)
        if err9:
            return self._send(err9[0], {"ok": False, "error": err9[1]})
        self._send(200, v9)

    def _send_other_assets(self, query):
        v9 = self._oa_view()
        self._send(200 if v9.get("ok") else 503, v9)

    def _send_oa_quote(self, query):
        if not onboarding.origin_ok(self, required=False):
            return self._send(403, {"ok": False, "error": "다른 출처(사이트)에서 온 요청은 거부합니다"})
        t9 =urllib.parse.parse_qs(query or "").get("t", [""])[0]
        if not t9 or len(t9) > 16:
            return self._send(400, {"ok": False, "error": "t(종목 코드) 필요"})
        out9, st9 = _oa_quoter().lookup(t9)
        self._send(st9, out9)

    def _oa_post(self, path, body):
        if not self._write_guard():
            return
        q9 = _oa_quoter()
        with other_assets.STORE_LOCK:
            try:
                d9 = other_assets.load_store()
            except other_assets.StoreError as e9:
                return self._send(503, {"ok": False, "error": common.safe_err(e9)})
            if path.endswith("/delete"):
                ok9, err9 = other_assets.apply_delete(d9, body.get("id"))
                if not ok9:
                    return self._send(err9[0], {"ok": False, "error": err9[1]})
                other_assets.save_store(d9)
                return self._send(200, {"ok": True, "id": body.get("id")})
            it9, err9 = other_assets.apply_save(d9, body)
            if err9:
                return self._send(err9[0], {"ok": False, "error": err9[1]})
            other_assets.save_store(d9)
        try:
            q9.apply_quotes()
        except Exception as e9:
            log.warning("기타 자산 평가 반영 실패: %s", type(e9).__name__)
        if it9.get("auto"):
            q9.wake.set()
        self._send(200, {"ok": True, "id": it9["id"]})

    def _receipt_eval_post(self, body):
        if not self._write_guard():
            return
        a9, err = self._chart_args(body)
        if err:
            return self._send(400, err)
        force = body.get("force", False)
        if not isinstance(force, bool):
            return self._send(400, {"ok": False, "error": "force 는 true/false"})
        buy9 = a9["side"] == "buy"
        ST, side_ko = (BUY_EVALS, "매수") if buy9 else (SELL_EVALS, "매도")
        cap9 = sellchart.daily_max(BUILDER.cfg, a9["side"])
        day9 = datetime.now(KST).strftime("%Y-%m-%d")
        with ST.mu:
            busy9 = bool(ST.running)
            bud9 = ST._budget_read(day9)
        if busy9:
            return self._send(409, {"ok": False, "status": "running", "error": f"다른 {side_ko} 평가가 진행 중이에요 — 끝나면 다시 눌러 주세요"})
        if bud9.get("_bad") or bud9["used"] >= cap9:
            return self._send(429, {"ok": False, "error": _eval_budget_msg(cap9, a9["side"], side_ko)})
        BUILDER.snapshot()
        ch, st9 = BUILDER.chart_request(a9["date"], a9["sym"], a9["iv"], a9["after"], a9["venue"], side=a9["side"], bvenue=a9["bvenue"])
        if st9 != "ok":
            return self._send(202, {"ok": True, "status": "preparing", "retryAfter": 3, "message": "차트를 준비하는 중이에요 — 잠시 뒤 다시 눌러 주세요"})
        if ch is None:
            BUILDER.kick_refresh()
            return self._send(503, {"ok": False, "error": "기록 색인을 만드는 중 — 잠시 뒤 다시 시도하세요"})
        fp9 = ch.get("evalFp")
        ik9 = (("buy",) if buy9 else ()) + (a9["date"], ch.get("sym"), fp9)
        inp = (getattr(BUILDER, "_eval_inputs", None) or {}).get(ik9) if fp9 else None
        if not inp:
            return self._send(422, {"ok": False, "error": "차트(봉)가 없어 평가할 수 없어요 — " + str(((ch.get("chart") or {}).get("why")) or ch.get("why") or "")})
        sym9 = ch["sym"]
        k9 = f"{a9['date']}|{sym9}"
        old = ST.find(a9["date"], sym9, fp9)
        if old and not force:
            return self._send(200, {"ok": True, "status": "done", "cached": True, "eval": StateBuilder._eval_rec(old, a9["side"])})
        runner9 = None
        msym9 = memo_driven(a9["date"], sym9, inp, a9["side"])
        if msym9:
            if a9["iv"] == "5m" and a9["after"] == "1h" and not a9["venue"] and not a9["bvenue"]:
                if not DAY_MEMO_REEVAL.schedule(a9["date"], msym9, reset=False, force=force, side=a9["side"], manual=body.get("auto") is not True):
                    return self._send(429, {"ok": False, "error": "근거 메모 평가 대기 줄이 가득 찼어요 — 잠시 뒤 다시"})
                return self._send(202, {"ok": True, "status": "running", "queued": True, "fp": fp9})
            if DAY_MEMO_REEVAL.hour_left() <= 0:
                return self._send(429, {"ok": False, "error": DAY_MEMO_REEVAL.HOURLY_MSG.format(n=DAY_MEMO_REEVAL.HOURLY_MAX)})
            runner9 = DAY_MEMO_REEVAL.runner(f"{side_ko}평가(근거·보기) {a9['date']}|{sym9}")
        with ST.mu:
            if k9 in ST.running or ST.running:
                return self._send(409, {"ok": False, "status": "running", "error": f"다른 {side_ko} 평가가 진행 중이에요 — 끝나면 다시 눌러 주세요"})
            bud9 = ST._budget_read(day9)
            if bud9.get("_bad") or bud9["used"] >= cap9:
                return self._send(429, {"ok": False, "error": _eval_budget_msg(cap9, a9["side"], side_ko)})
            ST.running[k9] = {"since": int(time.time()), "fp": fp9}
            ST.errors.pop(k9, None)
        cfg9 = BUILDER.cfg

        def work():
            try:
                rec, e9 = sellchart.run_eval(ST, cfg9, a9["date"], sym9, fp9, inp, skip_if_fresh=not force, runner=runner9)
                if e9:
                    ST.errors[k9] = {"at": int(time.time()), "error": e9}
            except MemoHourly:
                ST.errors[k9] = {"at": int(time.time()), "error": DAY_MEMO_REEVAL.HOURLY_MSG.format(n=DAY_MEMO_REEVAL.HOURLY_MAX)}
            except Exception as e9:
                log.warning("%s 평가 실패(%s): %s", side_ko, k9, e9)
                ST.errors[k9] = {"at": int(time.time()), "error": "평가 중 오류"}
            finally:
                with ST.mu:
                    ST.running.pop(k9, None)
        threading.Thread(target=work, name=f"{'buy' if buy9 else 'sell'}-eval {k9}", daemon=True).start()
        self._send(202, {"ok": True, "status": "running", "fp": fp9})

    def _day_traded(self, d9, s9):
        idx = getattr(BUILDER, "_day_idx", None)
        if not idx or idx.get("ix") is None:
            return None
        syms = set()
        for _ts, kind, e, meta in (idx["ix"].get(d9) or ()):
            if kind == "hidden" or not isinstance(e, dict):
                continue
            k9 = str(e.get("k") or "")
            if ("매수" in k9 or "매도" in k9) and "평단" not in k9:
                sy = meta[1] if meta is not None else e.get("sym")
                if sy:
                    syms.add(str(sy))
        canon = day_memo.canon_map(syms)
        return any(day_memo.norm_sym(canon.get(x, x)) == s9 or day_memo.norm_sym(x) == s9 for x in syms)

    def _day_memo_post(self, body):
        if not self._write_guard():
            return
        extra9 = set(body) - {"date", "sym", "memo"}
        if extra9:
            return self._send(400, {"ok": False, "error": "모르는 필드: " + ", ".join(sorted(str(x)[:20] for x in extra9))[:120]})
        d9 = day_memo.norm_date(body.get("date"))
        if not d9:
            return self._send(400, {"ok": False, "error": "date 는 유효한 YYYY-MM-DD"})
        if d9 > datetime.now(KST).strftime("%Y-%m-%d"):
            return self._send(400, {"ok": False, "error": "앞날에는 메모를 쓸 수 없어요"})
        s9 = day_memo.norm_sym(body.get("sym"))
        if not s9:
            return self._send(400, {"ok": False, "error": f"sym 은 1~{day_memo.SYM_MAX}자 심볼(공백·특수 구분자 없음)"})
        m9, e9 = day_memo.norm_memo(body.get("memo"))
        if e9:
            return self._send(400, {"ok": False, "error": e9})
        if not onboarding.RL.hit("day_memo", self.DAY_MEMO_RL_N, 60):
            return self._send(429, {"ok": False, "error": "너무 자주 저장했어요 — 잠시 뒤 다시"})
        mm9, err9 = DAY_MEMOS.read()
        if err9:
            return self._send(503, {"ok": False, "error": "근거 메모 파일을 읽지 못해 저장하지 않았어요(" + err9 + ") — 파일을 고친 뒤 다시"})
        k9 = day_memo.key(d9, s9)
        old9 = mm9.get(k9)
        if old9 is None and not m9:
            return self._send(200, {"ok": True, "date": d9, "sym": s9, "memo": "", "at": int(time.time()), "deleted": False, "changed": False})
        if old9 is not None and old9["memo"] == m9:
            return self._send(200, {"ok": True, "date": d9, "sym": s9, "memo": m9, "at": old9["at"], "deleted": False, "changed": False})
        if old9 is None:
            tr9 = self._day_traded(d9, s9)
            if tr9 is None:
                BUILDER.kick_refresh()
                return self._send(503, {"ok": False, "error": "기록 색인을 만드는 중 — 잠시 뒤 다시 시도하세요"})
            if not tr9:
                return self._send(400, {"ok": False, "error": f"{d9} 에 {s9} 매수·매도 기록이 없어요"})
        try:
            rec9 = DAY_MEMOS.put(d9, s9, m9)
        except day_memo.Corrupt as e:
            return self._send(503, {"ok": False, "error": f"근거 메모 파일을 읽지 못해 저장하지 않았어요({common.safe_err(e)})"})
        except day_memo.TooBig as e:
            return self._send(413, {"ok": False, "error": common.safe_err(e)})
        except day_memo.Full as e:
            return self._send(409, {"ok": False, "error": common.safe_err(e)})
        BUILDER.purge_memo_charts(d9, s9)
        if not _bcall("mpatch", {"day_memo"}):
            if BUILDER.__dict__.get("_snapfile_on"):
                _snapfile_drop()
            BUILDER.soft_invalidate()
        q9 = False if review_pause_eff(BUILDER.prefs() if BUILDER is not None else {}).get("on") else DAY_MEMO_REEVAL.schedule(d9, s9)
        self._send(200, {"ok": True, "date": d9, "sym": s9, "memo": m9, "at": rec9["at"] if rec9 else int(time.time()),
                         "deleted": not m9, "changed": True, "reeval": bool(q9)})

    DAY_MEMO_RL_N = 30

    def _body_on_bodyless(self) -> bool:
        cl = (self.headers.get("Content-Length") or "").strip()
        if self.headers.get("Transfer-Encoding") is None and cl in ("", "0"):
            return False
        self.close_connection = True
        self._send(400, {"error": "GET 요청에 본문을 실을 수 없습니다"})
        return True

    def do_GET(self):
        path, _, query = self.path.partition("?")
        login_auth.mark_conn(self)
        if self._body_on_bodyless():
            return
        try:
            if login_auth.handle(self, "GET", path, query):
                return
            if onboarding.handle_get(self, path):
                return
            if not _mats_ready(path):
                return self._send(503, {"ok": False, "error": "계산 재료를 만드는 중 — 잠시 뒤 다시 시도하세요"})
            ui9 = _ui_route(path)
            if ui9:
                return self._send_asset(ui9[0], ui9[1], query)
            if path == "/" or path == "/index.html":
                self._send_asset(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")
            elif path == "/classic":
                self._send_bytes(302, b"", None, "text/plain; charset=utf-8", extra=(("Location", "/"),))
            elif path == "/support.js":
                self._send_optional("support.js", "application/javascript; charset=utf-8")
            elif path == "/api/state":
                ma9 = self._max_age(query)
                if ma9 is not None and not onboarding.origin_ok(self, required=False):
                    return self._send(403, {"ok": False, "error": "다른 출처(사이트)에서 온 요청은 거부합니다"})
                snap = BUILDER.snapshot() if ma9 is None else BUILDER.snapshot(max_age=ma9)
                self._send_bytes(200, snap.raw, snap.gz, etag=f'W/"{snap.ver}"', extra=(("X-TJ-Ver", snap.ver),))
            elif path == "/api/v2/state":
                self._send_state_v2(query)
            elif path == "/api/v2/part":
                self._send_part(query)
            elif path == "/api/day_events":
                self._send_day_events(query)
            elif path == "/api/tax_rows":
                self._send_tax_rows(query)
            elif path == "/api/bench":
                b9 = bench_series()
                try:
                    sn9 = (urllib.parse.parse_qs(query).get("since") or [""])[0].strip()
                    b9.update(wow.bench(getattr(BUILDER, "_day_idx", None), since=sn9 if re.fullmatch(r"\d{4}-\d{2}-\d{2}", sn9) else None))
                except Exception as e9:
                    log.warning("비교선(안 팔았다면) 계산 실패: %s", common.safe_err(e9)[:120])
                self._send(200, b9)
            elif path == "/api/habits":
                self._send(200, wow.habits(getattr(BUILDER, "_day_idx", None)))
            elif path == "/api/curve_hist":
                self._send_curve_hist(query)
            elif path == "/api/receipt":
                self._send_receipt(query)
            elif path == "/api/fut_receipt":
                self._send_fut_receipt(query)
            elif path == "/api/receipt_chart":
                self._send_receipt_chart(query)
            elif path == "/api/receipt_eval":
                self._send_receipt_eval(query)
            elif path == "/api/receipt_list":
                self._send_receipt_list(query)
            elif path == "/api/other_assets":
                self._send_other_assets(query)
            elif path == "/api/other_assets/quote":
                self._send_oa_quote(query)
            elif path in ("/api/wow/tm", "/api/wow/flows", "/api/search/ask"):
                self._send_wow(path, query)
            elif path == "/api/search":
                self._send_search(query)
            elif path == "/api/nft":
                self._send_nft(query)
            elif path == "/api/alert_prefs":
                self._send(200, _alert_view(BUILDER.prefs()))
            elif path == "/api/wallet_reload":
                self._send(200, _wallet_reload_view())
            elif path == "/api/outflow_candidates":
                self._send_outflow_cands(query)
            elif path == "/futures":
                if os.path.isfile(os.path.join(WEB_DIR, "futures.html")):
                    self._send_optional("futures.html", "text/html; charset=utf-8")
                else:
                    self._send_bytes(302, b"", None, "text/plain; charset=utf-8", extra=(("Location", "/"),))
            elif path == "/api/futures":
                self._send(200, futures_api_payload())
            elif path == "/api/leverage":
                self._send(200, leverage_api_payload())
            elif path == "/api/coverage_limits":
                if not os.path.exists(COVERAGE_PATH):
                    coverage_refresh()
                d9 = coverage_limits._rj(COVERAGE_PATH, None)
                if isinstance(d9, dict) and "api_limits" not in d9:
                    d9["api_limits"] = coverage_limits.api_limits_table()
                if isinstance(d9, dict):
                    d9 = common.scrub_secrets(d9)[0]
                self._send(200, {"ok": True, "data": d9} if isinstance(d9, dict) else {"ok": False, "error": "수집 한계를 아직 만들지 못했어요"})
            elif path == "/api/health":
                self._send(200, {"ok": True, "spot_updated": BUILDER.spot.updated,
                                 "last_scan": BUILDER._last_scan_str(), "health": health.web_view()})
            elif path == "/api/ops":
                self._send(200, ops_requests.status())
            else:
                self._send(404, {"error": "not found"})
        except BrokenPipeError:
            pass
        except (Exception, SystemExit) as e:
            log.warning("GET %s 실패: %s", path, e, exc_info=True)
            try:
                self._send(500, self._err500_body(e))
            except Exception:
                pass

    def _send_optional(self, name, ctype):
        fp = os.path.join(WEB_DIR, name)
        if not os.path.isfile(fp):
            return self._send(404, {"error": "not found"})
        with open(fp, "rb") as f:
            return self._send(200, f.read(), ctype)

    def _err500_body(self, e):
        return {"error": f"처리 중 오류({type(e).__name__}) — tj-web 로그를 확인하세요"}

    def _method_not_allowed(self):
        login_auth.mark_conn(self)
        self.close_connection = True
        self._send_bytes(405, b'{"error": "method not allowed"}', extra=(("Allow", "GET, POST"),))

    do_HEAD = do_OPTIONS = do_PUT = do_DELETE = do_PATCH = _method_not_allowed

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        login_auth.mark_conn(self)
        self.close_connection = True
        locked = False
        try:
            if login_auth.handle(self, "POST", path):
                return
            if onboarding.handle_post(self, path):
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._send(400, {"error": "Content-Length 형식 오류"})
            if n < 0 or n > 1024 * 1024:
                return self._send(413 if n > 0 else 400, {"error": "본문은 0~1 MiB"})
            self.connection.settimeout(10)
            try:
                body = json.loads(self.rfile.read(n).decode() or "{}") if n else {}
            except ValueError:
                return self._send(400, {"error": "JSON 형식 오류"})
            if not isinstance(body, dict):
                return self._send(400, {"error": "JSON 객체 필요"})
            if not _mats_ready(path):
                return self._send(503, {"ok": False, "error": "계산 재료를 만드는 중 — 잠시 뒤 다시 시도하세요"})
            if path == "/api/flow_register":
                return self._flow_register(body)
            if path in ("/api/other_assets/save", "/api/other_assets/delete"):
                return self._oa_post(path, body)
            if path == "/api/nft/prefs":
                return self._nft_post(body)
            if path == "/api/receipt_eval":
                if body.get("auto") is True and review_pause_eff(BUILDER.prefs() if BUILDER is not None else {}).get("on"):
                    return self._send(409, {"ok": False, "paused": True, "error": "AI 자동 생성 멈춤 중 — 버튼으로 직접 만들 수 있어요"})
                return self._receipt_eval_post(body)
            if path == "/api/day_memo":
                return self._day_memo_post(body)
            if path == "/api/alert_test":
                return self._alert_test_post(body)
            if path == "/api/wd_dest_register":
                return self._wd_dest_register(body)
            if path.startswith("/api/ops/"):
                return self._ops_post(path, body)
            PREFS_LOCK.acquire()
            locked = True
            prefs = BUILDER.prefs()
            if path == "/api/alert_prefs":
                return self._alert_prefs_post(prefs, body)
            if path == "/api/outflow_resolve":
                return self._outflow_resolve(body)
            if path == "/api/backfill_request":
                return self._backfill_request(body)
            if path == "/api/sale_link":
                lot9 = str(body.get("lot") or "")
                off_now9 = [str(x) for x in (prefs.get("sale_link_off") or [])]
                if not lot9 or len(lot9) > 160 or lot9 not in (set(getattr(BUILDER, "_sale_lot_ids", None) or ()) | set(off_now9)):
                    return self._send(400, {"ok": False, "error": "세일 연결 목록에 없는 로트"})
                off9 = body.get("off")
                if not isinstance(off9, bool):
                    return self._send(400, {"ok": False, "error": "off 는 true/false"})
                prefs["sale_link_off"] = [x for x in off_now9 if x != lot9] + ([lot9] if off9 else [])
                common.atomic_write_json(PREFS_PATH, prefs)
                with BUILDER.lock:
                    BUILDER.cache = None
                return self._send(200, {"ok": True, "lot": lot9, "off": off9})
            if path == "/api/xfer_link":
                dep9 = str(body.get("dep") or "")
                off_now9 = [str(x) for x in (prefs.get("xfer_link_off") or [])]
                known9 = set(getattr(BUILDER, "_xfer_links_all", None) or {}) | set(off_now9)
                if not dep9 or len(dep9) > 160 or dep9 not in known9:
                    return self._send(400, {"ok": False, "error": "연결 목록에 없는 입금"})
                off9 = body.get("off")
                if not isinstance(off9, bool):
                    return self._send(400, {"ok": False, "error": "off 는 true/false"})
                lst9 = [x for x in off_now9 if x != dep9] + ([dep9] if off9 else [])
                prefs["xfer_link_off"] = lst9
                common.atomic_write_json(PREFS_PATH, prefs)
                with BUILDER.lock:
                    BUILDER.cache = None
                return self._send(200, {"ok": True, "dep": dep9, "off": off9})
            if path == "/api/plan":
                key = str(body.get("key") or "")
                if not key:
                    return self._send(400, {"error": "key 필요"})
                for f9 in ("target", "stop"):
                    v9 = body.get(f9)
                    if v9 in (None, ""):
                        continue
                    try:
                        v9 = float(v9)
                    except (TypeError, ValueError):
                        return self._send(400, {"error": f"{f9} 숫자 필요"})
                    if not (-float("inf") < v9 < float("inf")):
                        return self._send(400, {"error": f"{f9} 유한수 필요"})
                    body[f9] = v9
                if len(key) > 120:
                    return self._send(400, {"error": "key 는 120자 이하"})
                for f9, lim9 in (("memo", 2000), ("src", 40), ("venue", 120)):
                    v9 = body.get(f9)
                    if v9 is not None and (not isinstance(v9, str) or len(v9) > lim9):
                        return self._send(400, {"error": f"{f9} 는 {lim9}자 이하 문자열"})
                if "tags" in body and body["tags"] is not None and (
                        not isinstance(body["tags"], list) or len(body["tags"]) > 20
                        or any(not isinstance(t9, str) or len(t9) > 40 for t9 in body["tags"])):
                    return self._send(400, {"error": "tags 는 40자 이하 문자열 배열(≤20)"})
                plans = prefs.setdefault("plans", {})
                if key not in plans and len(plans) >= PLANS_MAX:
                    return self._send(413, {"error": f"계획(목표가·메모)은 {PLANS_MAX:,}개까지예요 — 안 쓰는 계획을 지운 뒤 다시"})
                ent = plans.setdefault(key, {})
                for f in ("target", "stop", "memo", "src", "venue", "tags"):
                    if f in body:
                        ent[f] = body[f]
                common.atomic_write_json(PREFS_PATH, prefs)
                if not _bcall("mpatch", {"plan"}):
                    with BUILDER.lock:
                        BUILDER.cache = None
                self._send(200, {"ok": True})
            elif path in ("/api/ignore", "/api/ignore_bulk"):
                keys = body.get("keys") if path.endswith("_bulk") else [body.get("key")]
                if not isinstance(keys, list) or len(keys) > 1000:
                    return self._send(400, {"error": "keys 는 배열(≤1000)"})
                if any((not isinstance(k, str)) or len(k) > 120 for k in keys):
                    return self._send(400, {"error": "key 는 120자 이하 문자열"})
                ig = prefs.setdefault("ignored", [])
                new9 = {k for k in keys if k} - set(ig)
                if len(ig) + len(new9) > IGNORED_MAX:
                    return self._send(413, {"error": f"무시 목록은 {IGNORED_MAX:,}개까지예요(지금 {len(ig):,}개) — 저장하지 않았어요"})
                added = 0
                for k in keys:
                    if k and k not in ig:
                        ig.append(k); added += 1
                common.atomic_write_json(PREFS_PATH, prefs)
                with BUILDER.lock:
                    BUILDER.cache = None
                self._send(200, {"ok": True, "added": added, "total": len(ig)})
            elif path == "/api/wallet_alias":
                a_in, n_in = body.get("address"), body.get("alias")
                if not isinstance(a_in, str) or (n_in is not None and not isinstance(n_in, str)):
                    return self._send(400, {"error": "address·alias 는 문자열"})
                addr = a_in.strip()
                alias = (n_in or "").strip()[:40]
                if not addr or len(addr) > 128:
                    self._send(400, {"error": "address 필요"})
                    return
                if any(ord(c) < 32 or ord(c) == 127 for c in alias):
                    return self._send(400, {"error": "지갑 이름은 한 줄(제어문자 없음)"})
                key9 = addr.lower() if addr.startswith("0x") else addr
                al = prefs.get("aliases") if isinstance(prefs.get("aliases"), dict) else {}
                prefs["aliases"] = al
                if alias:
                    if key9 not in _registered_wallet_keys(BUILDER.cfg) and not _ALIAS_ADDR_RE.fullmatch(key9):
                        return self._send(400, {"error": "등록된 지갑이거나 지갑 주소 형식(0x… 40자리 · Solana)이어야 해요"})
                    if key9 not in al and len(al) >= ALIAS_MAX:
                        return self._send(400, {"error": f"지갑 이름은 {ALIAS_MAX}개까지예요 — 안 쓰는 이름을 지운 뒤 다시"})
                    al[key9] = alias
                else:
                    al.pop(key9, None)
                common.atomic_write_json(PREFS_PATH, prefs)
                with BUILDER.lock:
                    BUILDER.cache = None
                self._send(200, {"ok": True, "address": key9, "alias": alias})
            elif path == "/api/cost_override":
                key = str(body.get("key") or ""); mode = str(body.get("mode") or "")
                if not re.fullmatch(r"g\d+", key) or mode not in ("unit", "market", "clear", "breakeven", "breakeven_clear"):
                    return self._send(400, {"error": "key=g<gid> + mode(unit|market|clear|breakeven|breakeven_clear) 필요"})
                if mode in ("breakeven", "breakeven_clear"):
                    be = prefs.get("cost_breakeven") if isinstance(prefs.get("cost_breakeven"), dict) else {}
                    if mode == "breakeven":
                        last9 = getattr(BUILDER, "_last_out", None) or {}
                        last9 = last9.get("fields") if isinstance(last9.get("fields"), dict) else last9
                        row9 = next((p9 for p9 in (last9.get("pendings") or ())
                                     if isinstance(p9, dict) and p9.get("gkey") == key and "원가미상 매도" in str(p9.get("kind") or "")), None)
                        def _dq(r9):
                            try:
                                v9 = Decimal(str(r9.get("qtyExact") if r9.get("qtyExact") is not None else r9.get("qty")))
                            except (InvalidOperation, TypeError, ValueError, AttributeError):
                                return None
                            return v9 if v9.is_finite() and v9 >= 0 else None
                        q9 = _dq(row9) if row9 else None
                        if q9 is None or q9 <= 0:
                            return self._send(409, {"error": "이 항목의 원가 미상 매도를 지금 화면에서 찾지 못했습니다 — 새로고침 뒤 다시 눌러 주세요"})
                        done9 = next((d9 for d9 in (last9.get("costDecidedRows") or ()) if isinstance(d9, dict) and d9.get("gkey") == key), None)
                        p9 = (_dq(done9) or Decimal(0)) if done9 else Decimal(0)
                        be[key] = {"until": int(time.time()), "qty": str(p9 + q9)}
                    else:
                        be.pop(key, None)
                    prefs["cost_breakeven"] = be
                    common.atomic_write_json(PREFS_PATH, prefs)
                    with BUILDER.lock:
                        BUILDER.cache = None
                    return self._send(200, {"ok": True, "key": key, "breakeven": be.get(key)})
                ov = prefs.setdefault("cost_overrides", {})
                if mode == "clear":
                    ov.pop(key, None)
                elif mode == "market":
                    ov[key] = {"mode": "market"}
                else:
                    try:
                        unit = float(body.get("value"))
                    except (TypeError, ValueError):
                        return self._send(400, {"error": "value(개당 $) 숫자 필요"})
                    if not (unit > 0) or unit > 1e9:
                        return self._send(400, {"error": "value 범위 오류"})
                    ov[key] = {"mode": "unit", "unit": unit}
                common.atomic_write_json(PREFS_PATH, prefs)
                with BUILDER.lock:
                    BUILDER.cache = None
                self._send(200, {"ok": True, "key": key, "override": ov.get(key)})
            elif path == "/api/fallback_avg":
                if not isinstance(body.get("on"), bool):
                    return self._send(400, {"ok": False, "error": "on 은 true/false"})
                prefs["fallback_avg"] = body["on"]
                common.atomic_write_json(PREFS_PATH, prefs)
                with BUILDER.lock:
                    BUILDER.cache = None
                self._send(200, {"ok": True, "on": prefs["fallback_avg"]})
            elif path == "/api/offchain_self":
                ex9 = body.get("ex")
                if not isinstance(ex9, str) or ex9 not in OFFC_EXCHANGES:
                    return self._send(400, {"ok": False, "error": "ex(" + "|".join(OFFC_EXCHANGES) + ") 필요"})
                if "addr" in body:
                    a9, x9 = body.get("addr"), body.get("excl")
                    if not isinstance(a9, str) or not a9.strip() or len(a9) > 128 or not isinstance(x9, bool):
                        return self._send(400, {"ok": False, "error": "addr(문자열 ≤128) + excl(true/false) 필요"})
                    a9 = xfer_match.norm_addr(a9)
                    ex0 = prefs.get("offchain_self_excl") if isinstance(prefs.get("offchain_self_excl"), dict) else {}
                    cur9 = [str(x) for x in (ex0.get(ex9) if isinstance(ex0.get(ex9), list) else [])]
                    known9 = set(((getattr(BUILDER, "_offc_addrs", None) or {}).get(ex9)) or ()) if x9 else set(cur9)
                    if a9 not in known9:
                        return self._send(400, {"ok": False, "error": ("이 거래소의 오프체인 출금 받는 주소 목록에 없는 주소" if x9
                                                                       else "제외 목록에 없는 주소")})
                    lst9 = [x for x in cur9 if x != a9] + ([a9] if x9 else [])
                    ex0 = {k9: v9 for k9, v9 in ex0.items() if k9 in OFFC_EXCHANGES and isinstance(v9, list) and k9 != ex9}
                    if lst9:
                        ex0[ex9] = lst9
                    prefs["offchain_self_excl"] = ex0
                    common.atomic_write_json(PREFS_PATH, prefs)
                    with BUILDER.lock:
                        BUILDER.cache = None
                    return self._send(200, {"ok": True, "ex": ex9, "addr": a9, "excl": x9})
                on9 = body.get("on")
                if not isinstance(on9, bool):
                    return self._send(400, {"ok": False, "error": "on(true/false) 필요"})
                oc9 = prefs.get("offchain_self") if isinstance(prefs.get("offchain_self"), dict) else {}
                oc9 = {k9: v9 for k9, v9 in oc9.items() if k9 in OFFC_EXCHANGES and isinstance(v9, bool)}
                oc9[ex9] = on9
                prefs["offchain_self"] = oc9
                common.atomic_write_json(PREFS_PATH, prefs)
                with BUILDER.lock:
                    BUILDER.cache = None
                self._send(200, {"ok": True, "ex": ex9, "on": on9})
            elif path == "/api/gas_in_cost":
                if not isinstance(body.get("on"), bool):
                    return self._send(400, {"ok": False, "error": "on 은 true/false"})
                prefs["gas_in_cost"] = body["on"]
                common.atomic_write_json(PREFS_PATH, prefs)
                with BUILDER.lock:
                    BUILDER.cache = None
                self._send(200, {"ok": True, "on": prefs["gas_in_cost"]})
            elif path == "/api/review_len":
                kind9, len9 = body.get("kind"), body.get("len")
                if kind9 not in ("daily", "weekly") or len9 not in REVIEW_LEN_KEYS:
                    return self._send(400, {"ok": False, "error": "kind(daily|weekly) + len(short|normal|long) 필요"})
                rl9 = prefs.get("review_len") if isinstance(prefs.get("review_len"), dict) else {}
                prefs["review_len"] = dict(rl9, **{kind9: len9})
                common.atomic_write_json(PREFS_PATH, prefs)
                if not _bcall("mpatch", {"review"}):
                    with BUILDER.lock:
                        BUILDER.cache = None
                self._send(200, {"ok": True, "kind": kind9, "len": len9, "reviewLen": review_len_eff(prefs)})
            elif path == "/api/review_pause":
                if not isinstance(body.get("on"), bool):
                    return self._send(400, {"ok": False, "error": "on 은 true/false"})
                prefs["review_pause"] = {"on": body["on"], "at": int(time.time())}
                common.atomic_write_json(PREFS_PATH, prefs)
                if not _bcall("mpatch", {"review"}):
                    with BUILDER.lock:
                        BUILDER.cache = None
                self._send(200, {"ok": True, "reviewPause": review_pause_eff(prefs)})
            elif path == "/api/review_fill":
                ord9, par9 = body.get("order"), body.get("parallel")
                if review_progress is None or ord9 not in review_progress.FILL_ORDERS or isinstance(par9, bool) \
                        or not isinstance(par9, int) or par9 not in review_progress.FILL_PARALLEL:
                    return self._send(400, {"ok": False, "error": "order(recent|oldest) + parallel(1|3) 필요"})
                prefs["review_fill"] = {"order": ord9, "parallel": par9}
                common.atomic_write_json(PREFS_PATH, prefs)
                if not _bcall("mpatch", {"review"}):
                    with BUILDER.lock:
                        BUILDER.cache = None
                self._send(200, {"ok": True, "reviewFill": review_progress.fill_eff(prefs["review_fill"])})
            elif path == "/api/chain_auto_off":
                code9, out9 = chain_auto_off_save(prefs, body)
                self._send(code9, out9)
            elif path == "/api/dust_threshold":
                try:
                    v9 = float(body.get("usd"))
                except (TypeError, ValueError):
                    self._send(400, {"error": "usd 숫자 필요"})
                    return
                prefs["dust_usd"] = max(0.0, min(v9, 1e6))
                common.atomic_write_json(PREFS_PATH, prefs)
                with BUILDER.lock:
                    BUILDER.cache = None
                self._send(200, {"ok": True, "usd": prefs["dust_usd"]})
            elif path == "/api/risk_override":
                key = str(body.get("key") or "")
                verdict = str(body.get("verdict") or "")
                if not re.fullmatch(r"g\d+", key) or \
                        verdict not in ("visible", "spam", "clear"):
                    return self._send(400, {"error": "key=g<gid> + verdict(visible|spam|clear) 필요"})
                ro = prefs.setdefault("risk_overrides", {})
                if verdict == "clear":
                    ro.pop(key, None)
                else:
                    ro[key] = verdict
                common.atomic_write_json(PREFS_PATH, prefs)
                with BUILDER.lock:
                    BUILDER.cache = None
                self._send(200, {"ok": True, "key": key, "verdict": verdict})
            elif path == "/api/src_whitelist":
                raw15 = str(body.get("address") or "").strip()
                if re.fullmatch(r"0[xX][0-9a-fA-F]{40}", raw15):
                    addr = raw15.lower()
                elif re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", raw15):
                    addr = raw15
                else:
                    return self._send(400, {"error": "address 형식 오류 (0x40hex/base58)"})
                rm9 = body.get("remove", False)
                if not isinstance(rm9, bool):
                    return self._send(400, {"error": "remove 는 true/false"})
                wl = prefs.setdefault("src_whitelist", [])
                if rm9:
                    prefs["src_whitelist"] = [a for a in wl if a != addr]
                elif addr not in wl:
                    if len(wl) >= SRC_WL_MAX:
                        return self._send(413, {"error": f"발신 화이트리스트는 {SRC_WL_MAX:,}개까지예요 — 안 쓰는 주소를 지운 뒤 다시"})
                    wl.append(addr)
                common.atomic_write_json(PREFS_PATH, prefs)
                with BUILDER.lock:
                    BUILDER.cache = None
                self._send(200, {"ok": True, "whitelist": prefs["src_whitelist"]})
            else:
                self._send(404, {"error": "not found"})
        except (Exception, SystemExit) as e:
            log.warning("POST %s 실패: %s", path, e, exc_info=True)
            try:
                self._send(500, self._err500_body(e))
            except Exception:
                pass
        finally:
            if locked:
                PREFS_LOCK.release()


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


ALERTS_PATH = os.path.join(common.STATE_DIR, "alerts_web.jsonl")
ALERTS_SENT_PATH = os.path.join(common.STATE_DIR, "alerts_sent_web.json")


ALERTS_LOCK = threading.Lock()


def _append_alert(obj):
    with ALERTS_LOCK:
        common.append_durable_jsonl(ALERTS_PATH, obj)


_ALERT_TEST_LOCK = threading.Lock()
_ALERT_TEST_T = []
ALERT_TEST_HOURLY = 6
ALERT_WATCH_EVERY = 60
ALERT_WATCH_SAVE = 300


def _tg_connected() -> bool:
    try:
        import settings_store
        return bool(settings_store.env_value(settings_store.TG_TOKEN) and settings_store.env_value(settings_store.TG_CHAT))
    except Exception:
        return False


def _venue_flows30(vflow, real_loc, venue_w, today_kst):
    lo9 = (today_kst - timedelta(days=29)).strftime("%Y-%m-%d")
    by = {}

    def slot(loc):
        w9 = venue_w(loc)
        if not w9:
            return None
        return by.setdefault(w9, {"in": 0.0, "out": 0.0, "realized": 0.0, "realizedKrw": 0.0})
    for loc9, v9 in (vflow or {}).items():
        b9 = slot(loc9)
        if b9 is not None:
            b9["in"] += float(v9[0])
            b9["out"] += float(v9[1])
    for (loc9, d9), v9 in (real_loc or {}).items():
        if str(d9) < lo9:
            continue
        b9 = slot(loc9)
        if b9 is not None:
            b9["realized"] += float(v9[0])
            b9["realizedKrw"] += float(v9[1])
    return {"days": 30, "flowOk": vflow is not None,
            "by": {k9: {"in": round(b9["in"], 2), "out": round(b9["out"], 2), "realized": round(b9["realized"], 2),
                        "realizedKrw": round(b9["realizedKrw"])} for k9, b9 in by.items()}}


def _fut_by_date_ex(by_date_ex, exn):
    out = {}
    for (dk9, ex9), v9 in by_date_ex.items():
        if abs(v9[0]) < 0.005:
            continue
        out.setdefault(dk9, []).append({"ex": exn.get(ex9, ex9), "exKey": ex9, "usd": round(v9[0], 2), "krw": round(v9[1]),
                                        "n": v9[2], "t": datetime.fromtimestamp(v9[3] / 1000, KST).strftime("%H:%M") if v9[3] else ""})
    for l9 in out.values():
        l9.sort(key=lambda x: (-abs(x["usd"]), str(x["exKey"])))
    return out


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
    except Exception:
        extra["oaAuto"] = extra["oaBrokers"] = 0
    return alert_prefs.view(prefs, tg_connected=_tg_connected(), extra=extra)


_PUBLIC_URL_RE = re.compile(r"https://(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(?::\d{1,5})?")


def _eval_budget_msg(cap, side, side_ko) -> str:
    fn = getattr(sellchart, "budget_msg", None)
    if callable(fn):
        try:
            return str(fn(cap, side))
        except Exception:
            pass
    return f"오늘 AI {side_ko} 평가 한도({cap}회)를 다 썼어요"


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
    except Exception:
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
        except Exception:
            oa9 = None
    try:
        import settings_store
        cur9 = "USD" if (settings_store.read_settings() or {}).get("currency") == "USD" else "KRW"
    except Exception:
        cur9 = "KRW"
    try:
        pub9 = public_url(getattr(b9, "cfg", None))
    except Exception:
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
    except Exception as e9:
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
        except (Exception, SystemExit) as e:
            log.warning("새 알림 생산자 실패(다음 판): %s", e)
        time.sleep(ALERT_WATCH_EVERY)


COVERAGE_PATH = os.path.join(common.STATE_DIR, coverage_limits.OUT_NAME)
COVERAGE_EVERY = 24 * 3600
_COV_LOCK = threading.Lock()


def coverage_refresh():
    if not _COV_LOCK.acquire(blocking=False):
        return False
    try:
        d = coverage_limits.write()
        log.info("수집 한계 갱신: 소스 %d · 한계 %d", len(d.get("sources") or []), len(d.get("unavailable") or []))
        return True
    except (Exception, SystemExit) as e:
        log.warning("수집 한계 생성 실패(다음 주기): %s", e)
        return False
    finally:
        _COV_LOCK.release()


def coverage_loop():
    time.sleep(300)
    while True:
        try:
            age = time.time() - os.path.getmtime(COVERAGE_PATH) if os.path.exists(COVERAGE_PATH) else None
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
    except (Exception, SystemExit) as e:
        log.warning("잔고 대조 지연 대기 판정 실패(DM 은 종전대로): %s", e)
        return set()


def _hist_flows(fk, days, dpx, fx_day) -> dict:
    sh9 = StateBuilder.__new__(StateBuilder)
    sh9.daily = fk.get("wdt") or {}
    sh9.daily_px = {}
    sh9._flow_px_delta = {}
    today9 = datetime.strptime(fk.get("today") or datetime.now(KST).strftime("%Y-%m-%d"), "%Y-%m-%d").replace(tzinfo=KST)
    conn9 = dbm.open_db(common.DB_PATH, readonly=True)
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
                prev = common.read_json(balcheck.STATUS_PATH, {}) \
                    if os.path.exists(balcheck.STATUS_PATH) else {}
                conn = dbm.open_db(common.DB_PATH, readonly=True)
                try:
                    state = balcheck.run_once(BUILDER.cfg, conn,
                                              dict(getattr(BUILDER, "_live_px", {}) or {}),
                                              set(getattr(BUILDER, "_risk_quarantined", set()) or set()), prev)
                finally:
                    conn.close()
                new_alerts = balcheck.finalize(state, _balcheck_defer_keys(state))
                if new_alerts:
                    common.atomic_write_json(balcheck.STATUS_PATH, state)
                    _append_alert({"ts": int(time.time()), "kind": "BALANCE_MISMATCH",
                                   "text": balcheck.alert_text(new_alerts),
                                   "keys": sorted({str(m.get("key")) for m in new_alerts if m.get("key")})})
                    log.warning("온체인 잔고 불일치 알림 적재: %d건", len(new_alerts))
                else:
                    common.atomic_write_json(balcheck.STATUS_PATH, state)
                log.info("온체인 잔고 대조: %d항목·%d콜·불일치 %d(확정 %d)%s%s", state["checked"], state["calls"],
                         len(state["mismatches"]), sum(1 for m in state["mismatches"] if m.get("confirmed")),
                         " · 호출 상한 도달(부분)" if state["capped"] else "",
                         f" · 오류 {len(state['errors'])}" if state["errors"] else "")
                BUILDER.soft_invalidate()
            except (Exception, SystemExit) as e:
                log.warning("온체인 잔고 대조 실패(다음 주기): %s", e)
        try:
            iv = max(600, int(st9.get("interval_sec") or 3600))
        except (TypeError, ValueError):
            iv = 3600
        time.sleep(iv)


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
        if wait > 0:
            if not sp_once and st9.get("enabled"):
                sp_once = True
                try:
                    cfg9 = common.load_config()
                    gate9 = common.read_json(common.ACTIVITY_GATE_PATH, {}) or {}
                    if chainsweep.missing_speed(cfg9, gate9):
                        chainsweep.speed_tick(cfg9, gate9)
                except (Exception, SystemExit) as e:
                    log.warning("체인 백필 속도 실측(빠진 체인) 실패(다음 점검 때): %s", e)
            time.sleep(min(wait, iv))
            continue
        if st9.get("enabled"):
            try:
                cfg9 = common.load_config()
                try:
                    bn9 = pricing.binance_spot_usdt()
                except Exception:
                    bn9 = {}
                spot9 = dict(getattr(BUILDER.spot, "usd", {}) or {})
                led9 = set()
                conn = dbm.open_db(common.DB_PATH, readonly=True)
                try:
                    for r9 in conn.execute("SELECT DISTINCT location FROM postings WHERE location LIKE 'wallet:%'"):
                        p9 = str(r9[0] or "").split(":")
                        if len(p9) >= 3 and p9[2].startswith("0x"):
                            led9.add((p9[1], p9[2].lower()))
                finally:
                    conn.close()
                gate9 = common.read_json(common.ACTIVITY_GATE_PATH, {}) or {}
                res = chainsweep.run_once(cfg9, price_fn=lambda sym: bn9.get(sym) or spot9.get(sym), gate=gate9, ledger_pairs=led9)
                common.atomic_write_json(common.ACTIVITY_GATE_PATH, gate9)
                prev_auto = {(f["chain"], f["wallet"]) for f in (prev.get("autoEnabled") or [])}
                common.atomic_write_json(chainsweep.STATUS_PATH, common.scrub_secrets(res)[0])
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
                except (Exception, SystemExit) as e:
                    log.warning("체인 백필 속도 실측 실패(다음 판): %s", e)
                _chain_auto_off()
            except (Exception, SystemExit) as e:
                log.warning("미추적 체인 점검 실패(1시간 뒤 재시도): %s", e)
                time.sleep(3600)
                continue
        time.sleep(iv)


def _chain_auto_off():
    try:
        import chainoff
        off9 = chainoff.auto_off()
    except (Exception, SystemExit) as e:
        log.warning("체인 자동 끄기 실패(다음 점검 때): %s", common.safe_err(e)[:160])
        return []
    if off9:
        log.info("체인 자동 끔(활동 없음 — 추천 조건): %s", ", ".join(off9))
        _append_alert({"ts": int(time.time()), "kind": "CHAIN_AUTO",
                       "text": "[체인 자동 끔] 지갑마다 보낸 거래가 거의 없고 최근 30일 활동이 없어 조회를 꺼 뒀어요: " + ", ".join(off9)
                               + "\n켜려면 설정 › 지갑 › 체인별 조회에서 스위치를 켜세요(다시 켠 체인은 자동으로 끄지 않아요)."})
    return off9


def _goplus_fetch(cid, ca_l):
    req = urllib.request.Request(
        f"https://api.gopluslabs.io/api/v1/token_security/{cid}?contract_addresses={ca_l}",
        headers={"User-Agent": "tj-bot/0.1", "Accept": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=15).read().decode())


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
    cache = common.read_json(GOPLUS_PATH, {}) if os.path.exists(GOPLUS_PATH) else {}
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
        except Exception as e:
            fail_until[key] = now + GOPLUS_FAIL_RETRY
            state["net_fail"] = state.get("net_fail", 0) + 1
            note("연결", f"{type(e).__name__}: {common.safe_err(e)[:60]} ({key})")
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
        common.atomic_write_json(GOPLUS_PATH, cache)
        BUILDER.soft_invalidate()
    for k9 in [k9 for k9, t9 in fail_until.items() if t9 <= now - GOPLUS_FAIL_RETRY]:
        fail_until.pop(k9, None)
    return done


def build_stats(hist) -> dict:
    h = [int(x) for x in hist if isinstance(x, (int, float))]
    if not h:
        return {"last_ms": None, "p50": None, "p95": None, "n": 0}
    srt = sorted(h)

    def q(p):
        return srt[min(len(srt) - 1, max(0, int(round(p * (len(srt) - 1)))))]
    return {"last_ms": h[-1], "p50": q(0.5), "p95": q(0.95), "n": len(h)}


def goplus_state_load(path=None) -> dict:
    try:
        d = common.read_json(path or GOPLUS_STATUS_PATH, {}) if os.path.exists(path or GOPLUS_STATUS_PATH) else {}
    except (Exception, SystemExit):
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
                common.atomic_write_json(GOPLUS_STATUS_PATH, doc9)
                last_st = st9
        except (Exception, SystemExit) as e:
            log.warning("goplus loop 오류(다음 주기): %s", e)
        time.sleep(60)


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
            sent = common.read_json(ALERTS_SENT_PATH, {}) if os.path.exists(ALERTS_SENT_PATH) else {}
            today = datetime.now(KST).strftime("%Y-%m-%d")
            changed = False
            for key, pl in plans.items():
                c = coins.get(key)
                if not c or not c.get("price"):
                    continue
                px = c["price"]
                hits = []
                lk9 = alert_watch._link({"pub": public_url(getattr(BUILDER, "cfg", None))}, "journal")
                if px >= pl["target"]:
                    hits.append(("TARGET_HIT", f"🔴 {c['sym']} 목표가에 닿았어요\n팔 계획이었다면 지금이에요.\n"
                                               f"지금 {alert_watch.px_txt(px)} · 목표 {alert_watch.px_txt(pl['target'])}" + lk9))
                if px <= pl["stop"]:
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
                common.atomic_write_json(ALERTS_SENT_PATH, sent)
        except (Exception, SystemExit) as e:
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
            except Exception:
                pass
            ext.update(srv=None, host=None, thread=None)
        if want and ext["srv"] is None:
            try:
                srv2 = QuietHTTPServer((want, port), Handler)
            except OSError as e:
                if ext.get("bind_err") != common.safe_err(e):
                    log.warning("추가 바인딩 실패(%s:%d, 60초 뒤 재시도): %s", want, port, e)
                    ext["bind_err"] = common.safe_err(e)
            else:
                t2 = threading.Thread(target=srv2.serve_forever, daemon=True, name="http-ext")
                t2.start()
                ext.update(srv=srv2, host=want, thread=t2, bind_err=None)
                log.info("가동: http://%s:%d (%s)", want, port, why)
    except Exception as e:
        log.warning("바인딩 감시 오류(다음 주기): %s", e)


class QuietHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


def _login_startup_warnings(cfg):
    try:
        web9 = (cfg or {}).get("web") or {}
        mode9 = web9.get("bind", "loopback")
        ext9, _why = extra_host(cfg)
        tail9 = isinstance(ext9, str) and ext9.startswith("100.") and 64 <= int(ext9.split(".")[1]) <= 127
        if not login_auth.S.enabled:
            if ext9:
                log.error("★웹 로그인이 꺼져 있어요 — %s(%s)에 닿는 누구나 대시보드를 보고 바꿀 수 있어요★ config.json web.login.enabled 를 "
                          "true 로(또는 키 삭제) 바꾸고 tj-web 을 다시 시작하세요", ext9, "테일넷" if tail9 else "사설망")
            else:
                log.error("웹 로그인이 꺼져 있어요(web.login.enabled=false) — 이 컴퓨터의 다른 프로그램·사용자도 대시보드를 열 수 있어요. "
                          "리버스 프록시·터널 요청은 거부합니다(403). 켜려면 enabled 를 true 로(또는 키 삭제)")
        elif ext9 and not tail9 and not ((web9.get("login") or {}).get("secure_cookie") is True if isinstance(web9.get("login"), dict) else False):
            log.warning("웹 로그인 켜짐 · 사설 IP(%s) 바인딩은 HTTP 라 비밀번호·로그인 쿠키가 같은 네트워크에 암호화 없이 오가요 — "
                        "테일넷(bind \"tailscale\")이나 HTTPS 리버스 프록시를 쓰세요(bind=%s)", ext9, mode9)
    except Exception as e:
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
    common.ensure_dirs()
    ms9 = globals().get("_SQLITE_MEMSTAT_OFF")
    if ms9 is not None:
        log.info("SQLite 메모리 통계 %s — %s(빌드 자식 교착 방지 — fork 순간 다른 스레드가 쥔 전역 뮤텍스)",
                 "끔" if ms9 is True else ("끄기 시도함 · 적용 확인 불가" if ms9 == "unverified" else "못 끔(종전 — 교착이면 다시 fork)"),
                 common.SQLITE_MEMSTAT_WHY[0] or "-")
    try:
        buildproc.sweep_tmp()
    except Exception as e9:
        log.warning("임시 파일 정리 실패: %s", type(e9).__name__)
    if common.tighten_config_mode():
        log.info("config.json 권한을 본인만 읽게(0600) 좁혔어요 — 증권사 비밀값이 들어갈 수 있는 파일이에요")
    cfg = common.load_config()
    bf_engine.configure(cfg)
    try:
        tp9, cp9 = str(os.environ.get("TJ_PORT") or "").strip(), int((cfg.get("web") or {}).get("port", 8023))
        if tp9 and tp9 != str(cp9):
            log.warning("TJ_PORT=%s 는 데모(TJ_DEMO=1) 전용이라 무시해요 — 일반 실행 포트는 config.json 의 web.port(지금 %d)", tp9[:8], cp9)
    except (TypeError, ValueError):
        pass
    try:
        n9 = (common.scrub_secret_file(COVERAGE_PATH) + bf_engine.scrub_status_file()
              + common.scrub_secret_file(chainsweep.STATUS_PATH))
        if n9:
            log.info("수정 전 상태 문구 %d칸 비밀값 가림(수집 한계·백필 진행)", n9)
    except Exception as e9:
        log.warning("상태 문구 비밀값 정리 실패(서빙 때 가림): %s", type(e9).__name__)
    try:
        histcurve.migrate_px1004()
    except Exception as e9:
        log.warning("px1004 이관 실패(다음 기동에 다시): %s", common.safe_err(e9)[:160])
    login_auth.init(cfg)
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
