from __future__ import annotations

import os
import threading
import time
import urllib.error
import urllib.parse

import bf_engine
import cgplan
import common

LANES = ("live", "past", "nft")
GT_ROOT = "https://api.geckoterminal.com/api/v2"
GATE = {"demo": "api.coingecko.com#key", "pro": "pro-api.coingecko.com"}
for _h, _p in ((GATE["demo"], {"rate": 0.4, "burst": 1, "conc": 1}), (GATE["pro"], {"rate": 1.0, "burst": 1, "conc": 1})):
    bf_engine.HOST_POLICIES.setdefault(_h, _p)

KEY_BAD_S = 6 * 3600
RATE_MIN_S, RATE_MAX_S = 60.0, 900.0
NET_S = 60.0
FAMILY_S = 6 * 3600
BAD_BODY_S = 600.0
LIVE_GATE_WAIT_S = 5.0
CACHE_S = 5.0

_LOCK = threading.Lock()
_ST = {"key": None, "key_at": 0.0, "rec": None, "rec_fp": None, "rec_at": 0.0, "share": None}
_BENCH = {"fp": None, "until": 0.0, "why": "", "at": 0.0, "back": 0.0}
_FAM = {}
_OVR = {}
STATS = {}
BUDGET_FN = [None]
CLOCK = [time.time]


def _now() -> float:
    return CLOCK[0]()


def _stat(lane, what, why=None):
    with _LOCK:
        s = STATS.setdefault(lane, {"ok": 0, "fail": 0, "fallback": 0, "skip": {}})
        if what == "skip":
            s["skip"][why] = s["skip"].get(why, 0) + 1
        else:
            s[what] = s.get(what, 0) + 1


def reset():
    with _LOCK:
        _ST.update(key=None, key_at=0.0, rec=None, rec_fp=None, rec_at=0.0, share=None)
        _BENCH.update(fp=None, until=0.0, why="", at=0.0, back=0.0)
        _FAM.clear()
        _OVR.clear()
        STATS.clear()


def key() -> str:
    now = _now()
    with _LOCK:
        if _ST["key"] is not None and now - _ST["key_at"] < CACHE_S:
            return _ST["key"]
    try:
        import settings_store
        k = str(settings_store.env_value(cgplan.ENV_KEY) or "").strip()
    except Exception:
        k = ""
    with _LOCK:
        _ST.update(key=k, key_at=now)
    return k


def _record(k):
    now, fp = _now(), cgplan.kfp(k)
    with _LOCK:
        if _ST["rec_fp"] == fp and now - _ST["rec_at"] < CACHE_S:
            return _ST["rec"], _ST["share"]
    st = cgplan.Store()
    try:
        rec = st.load(k)
    except Exception:
        rec = None
    try:
        share = st.share()
    except Exception:
        share = cgplan.DEFAULT_SHARE
    with _LOCK:
        _ST.update(rec=rec, rec_fp=fp, rec_at=now, share=share)
    return rec, share


def plan_of(k):
    rec, _sh = _record(k)
    p = rec.get("plan") if isinstance(rec, dict) else None
    if p not in cgplan.PLANS:
        p = _OVR.get(cgplan.kfp(k), "demo")
    return p, rec


def root(plan) -> str:
    real = cgplan.ROOT["pro" if plan == "pro" else "demo"]
    for name in (("TJ_TEST_BASE_COINGECKO_PRO", "TJ_TEST_BASE_COINGECKO") if plan == "pro" else ("TJ_TEST_BASE_COINGECKO",)):
        v = os.environ.get(name, "")
        if v.startswith("http://127.0.0.1:"):
            return v.rstrip("/") + "/api/v3"
    return real


def onchain(gt_path: str) -> str:
    p = gt_path[len(GT_ROOT):] if gt_path.startswith(GT_ROOT) else gt_path
    return "/onchain" + (p if p.startswith("/") else "/" + p)


def family(path: str) -> str:
    seg = [s for s in urllib.parse.urlsplit(path).path.split("/") if s]
    if not seg:
        return "/"
    return "/" + "/".join(seg[:2]) if seg[0] == "onchain" else "/" + seg[0]


def budget():
    if BUDGET_FN[0] is not None:
        return BUDGET_FN[0]()
    import nft
    return nft.shared_budget()


def _benched(k, rec) -> str:
    fp = cgplan.kfp(k)
    with _LOCK:
        b = dict(_BENCH)
    if not b["why"] or b["fp"] != fp or _now() >= b["until"]:
        return ""
    if b["why"] == "reject":
        at = rec.get("at") if isinstance(rec, dict) else None
        if isinstance(at, (int, float)) and not isinstance(at, bool) and at > b["at"]:
            with _LOCK:
                _BENCH.update(why="", until=0.0)
            return ""
    return b["why"]


def _bench(k, why, retry_after=None):
    now, fp = _now(), cgplan.kfp(k)
    with _LOCK:
        if why == "rate":
            prev = _BENCH["back"] if _BENCH["fp"] == fp and _BENCH["why"] == "rate" else 0.0
            back = min(RATE_MAX_S, max(RATE_MIN_S, prev * 2 if prev else RATE_MIN_S))
            if retry_after:
                try:
                    back = max(back, min(RATE_MAX_S * 4, float(retry_after)))
                except (TypeError, ValueError):
                    pass
        elif why == "reject":
            back = float(KEY_BAD_S)
        else:
            back = NET_S
        _BENCH.update(fp=fp, until=now + back, why=why, at=now, back=back)


def _fam_benched(path) -> bool:
    with _LOCK:
        return _now() < _FAM.get(family(path), 0.0)


def _fam_bench(path, sec):
    with _LOCK:
        _FAM[family(path)] = _now() + float(sec)


def _clear_ok(k):
    with _LOCK:
        if _BENCH["fp"] == cgplan.kfp(k) and _BENCH["why"] in ("rate", "net") and _now() >= _BENCH["until"]:
            _BENCH.update(why="", until=0.0, back=0.0)


def status() -> dict:
    k = key()
    if not k:
        return {"key": False}
    plan, _rec = plan_of(k)
    with _LOCK:
        b = dict(_BENCH)
        fams = {f: int(u) for f, u in _FAM.items() if u > _now()}
        st = {ln: {"ok": v["ok"], "fail": v["fail"], "fallback": v["fallback"], "skip": dict(v["skip"])} for ln, v in STATS.items()}
    on = b["fp"] == cgplan.kfp(k) and b["why"] and _now() < b["until"]
    return {"key": True, "plan": plan, "bench": b["why"] if on else "", "until": int(b["until"]) if on else None, "families": fams, "stats": st}


def reserve(lane, rec=None, share=None) -> str:
    try:
        import nft
        b = budget()
        if rec is None and share is None:
            k = key()
            rec, share = _record(k) if k else (None, None)
        pm, pd = nft.cg_key_windows(rec, b, share)
        return b.take_cg(lane, pm, pd)
    except Exception:
        return "store"


def _err_info(e):
    if isinstance(e, urllib.error.HTTPError):
        body = ""
        try:
            body = (e.read(common.HTTP_ERR_BODY_MAX) or b"")[:400].decode("utf-8", "replace")
        except Exception:
            body = ""
        ra = None
        try:
            ra = (e.headers or {}).get("Retry-After")
        except Exception:
            ra = None
        kind = "http429" if e.code == 429 else ("http5xx" if 500 <= e.code < 600 else "http4xx")
        return int(e.code), kind, body, ra
    if isinstance(e, bf_engine.NetError):
        code = e.code if isinstance(e.code, int) else 0
        body = getattr(e, "body", None)
        if body is None:
            body = str(e)
        if not code and e.kind in ("http429", "quota"):
            code = 429
        return code, e.kind, body or "", getattr(e, "retry_after", None)
    return 0, "net", "", None


_PLAN_WORDS = ("time range", "past 365", "past 180", "historical data", "upgrade", "paid plan", "pro api subscriber",
               "exclusive", "not have access")


def _classify(code, kind, body) -> str:
    if cgplan.wrong_root(body):
        return "wrong_root"
    if code == 404:
        return "notfound"
    if code == 429 or kind in ("http429", "quota"):
        return "rate"
    if code in (401, 403):
        c9, m9 = cgplan.error_of(body)
        ml = (m9 or "").lower()
        if c9 in (10005, 10012) or any(w in ml for w in _PLAN_WORDS):
            return "plan"
        if code == 401 or isinstance(cgplan._as_obj(body), dict):
            return "reject"
        return "net"
    if code and 400 <= code < 500:
        c9, m9 = cgplan.error_of(body)
        ml = ((m9 or "") + " " + (body if isinstance(body, str) else "")).lower()
        if c9 in (10005, 10012) or any(w in ml for w in _PLAN_WORDS):
            return "plan"
        return "badreq"
    return "net"


def _passthru(e) -> bool:
    return type(e).__name__ == "BudgetExceeded" or (isinstance(e, bf_engine.NetError) and e.kind == "budget")


def request(path, lane, via, allow=True, valid=None):
    if not allow:
        return "skip", "allow"
    k = key()
    if not k:
        return "skip", "nokey"
    plan, rec = plan_of(k)
    why = _benched(k, rec)
    if why:
        _stat(lane, "skip", "bench_" + why)
        return "skip", "bench_" + why
    if _fam_benched(path):
        _stat(lane, "skip", "family")
        return "skip", "family"
    if lane == "live":
        try:
            gw = bf_engine.gate_wait(GATE[plan])
        except Exception:
            gw = 0.0
        if gw > LIVE_GATE_WAIT_S:
            _stat(lane, "skip", "gate_busy")
            return "skip", "gate_busy"
    _r, share = _record(k)
    why = reserve(lane, rec, share)
    if why:
        _stat(lane, "skip", why)
        return "skip", why
    flipped = False
    while True:
        url = root(plan) + path
        try:
            d = via(url, {cgplan.HDR[plan]: k}, GATE[plan])
            code, kind, body, ra = 200, "", "", None
        except Exception as e:
            if _passthru(e):
                raise
            code, kind, body, ra = _err_info(e)
            d = None
            cls = _classify(code, kind, body)
            if cls == "notfound":
                _stat(lane, "ok")
                return "err", e
        else:
            cls = ""
            if isinstance(d, dict) and isinstance(d.get("status"), dict) and cgplan.wrong_root(d):
                cls = "wrong_root"
            elif valid is not None and (lambda v8: (not v8) or v8 == "family")(valid(d)):
                v9 = valid(d)
                c9, m9 = cgplan.error_of(d) if isinstance(d, dict) else (None, "")
                cls = "rate" if (c9 == 429 or "rate limit" in (m9 or "").lower()) else ("plan" if v9 == "family" else "badbody")
        if not cls:
            if flipped:
                with _LOCK:
                    _OVR[cgplan.kfp(k)] = plan
            _clear_ok(k)
            _stat(lane, "ok")
            return "ok", d
        if cls == "wrong_root" and not flipped:
            plan = cgplan.other(plan)
            flipped = True
            if reserve(lane, rec, share):
                _stat(lane, "fail")
                return "fail", "wrong_root_budget"
            continue
        if cls == "wrong_root":
            cls = "reject"
        if cls in ("reject", "rate", "net"):
            _bench(k, cls, ra)
        elif cls == "plan":
            _fam_bench(path, FAMILY_S)
        elif cls == "badreq":
            pass
        else:
            _fam_bench(path, BAD_BODY_S)
        _stat(lane, "fail")
        return "fail", cls


def bf_via(timeout=15.0, prio="bg"):
    def via(url, headers, gate):
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        kw = {"gate_host": gate} if gate and gate != host else {}
        return bf_engine.http_json(url, headers=headers, timeout=timeout, retries=1, prio=prio, max_inline_wait=5.0, **kw)
    return via


def mark_fallback(lane):
    _stat(lane, "fallback")
