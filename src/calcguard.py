import atexit
import json
import os
import sys
import threading
import time

import fsio
import logs

BUG_TYPES = (NameError, AssertionError)
SUSPECT_TYPES = (KeyError, IndexError, TypeError, AttributeError, ArithmeticError, UnicodeError)
STRICT_TYPES = (NameError, ImportError, AssertionError)
FLUSH_SEC = 60
MAX_SITES = 2000

_LOCK = threading.Lock()
_FLUSH_LOCK = threading.Lock()
_SITES = {}
_DIRTY = [False]
_LAST_FLUSH = [0.0]
_SUFFIX = [""]
_MERGE = [False]
_TIMER = {"pid": None}
KEEP_SEC = 7 * 86400
_START = time.time()
_CARRY = {"loaded": False, "sites": {}}


def strict() -> bool:
    return os.environ.get("TJ_STRICT") == "1"


def _proc() -> str:
    try:
        return os.path.splitext(os.path.basename(sys.argv[0] or "py"))[0] or "py"
    except Exception:   # noqa: BLE001 [fallback]
        return "py"


def path_of(state_dir: str = None, suffix: str = "") -> str:
    try:
        import paths
        d = state_dir or paths.STATE_DIR
    except Exception:   # noqa: BLE001 [fallback]
        d = state_dir or "."
    return os.path.join(d, "calcguard_%s%s.json" % (_proc(), ("_" + suffix) if suffix else ""))


def _ensure_timer() -> None:
    pid = os.getpid()
    if _TIMER["pid"] == pid or _SUFFIX[0]:
        return
    _TIMER["pid"] = pid

    ev9 = threading.Event()

    def _loop():
        while True:
            ev9.wait(float(FLUSH_SEC))
            if os.getpid() != pid or _SUFFIX[0]:
                return
            flush()
    try:
        threading.Thread(target=_loop, name="calcguard-flush", daemon=True).start()
    except Exception:   # noqa: BLE001 [fallback]
        _TIMER["pid"] = None


def swallowed(site: str, exc: BaseException) -> None:
    if strict() and isinstance(exc, STRICT_TYPES):
        raise exc
    try:
        now = time.time()
        tn = type(exc).__name__
        with _LOCK:
            s = _SITES.get(site)
            if s is None:
                if len(_SITES) >= MAX_SITES:
                    return
                s = _SITES[site] = {"n": 0, "first": int(now), "last": 0, "types": {}, "why": "", "bug": 0, "bug_last": 0, "bug_why": "",
                                    "sus": 0, "sus_last": 0, "sus_why": ""}
            s["n"] += 1
            s["last"] = int(now)
            s["types"][tn] = s["types"].get(tn, 0) + 1
            why = ("%s: %s" % (tn, exc))[:200]
            s["why"] = why
            if isinstance(exc, BUG_TYPES):
                s["bug"] += 1
                s["bug_last"] = int(now)
                s["bug_why"] = why
            elif isinstance(exc, SUSPECT_TYPES):
                s["sus"] = s.get("sus", 0) + 1
                s["sus_last"] = int(now)
                s["sus_why"] = why
            _DIRTY[0] = True
        _ensure_timer()
    except Exception:   # noqa: BLE001 [optional]
        pass


def child_reset(suffix: str = "build") -> None:
    global _LOCK, _FLUSH_LOCK
    _LOCK = threading.Lock()
    _FLUSH_LOCK = threading.Lock()
    _SITES.clear()
    _DIRTY[0] = False
    _SUFFIX[0] = suffix
    _MERGE[0] = True
    _TIMER["pid"] = None


def flush_as(suffix: str) -> None:
    flush(suffix=suffix)


def _read_doc(p: str) -> dict:
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:   # noqa: BLE001 [fallback]
        return {}


def _carry_sites(p: str) -> dict:
    if not _CARRY["loaded"]:
        d = _read_doc(p)
        try:
            prev = float(d.get("at") or 0) < _START
        except (TypeError, ValueError):
            prev = False
        sites = d.get("sites") if prev else None
        _CARRY.update(loaded=True, sites=sites if isinstance(sites, dict) else {})
    return _CARRY["sites"]


def _merge_old(p: str, snap: dict, now: float, old: dict = None) -> dict:
    if old is None:
        old = _read_doc(p).get("sites") or {}
    if not isinstance(old, dict):
        old = {}
    out = {}
    for k, o in old.items():
        try:
            if not isinstance(o, dict):
                continue
            o = dict(o)
            if int(o.get("bug") or 0) > 0 and "bug_last" not in o:
                o["bug_last"], o["bug_why"] = int(float(o.get("last") or 0)), str(o.get("why") or "")
            if now - max(float(o.get("last") or 0), float(o.get("bug_last") or 0), float(o.get("sus_last") or 0)) <= KEEP_SEC:
                out[str(k)] = o
        except Exception:   # noqa: BLE001 [isolate]
            continue
    for k, v in snap.items():
        o = out.get(k)
        if not isinstance(o, dict):
            out[k] = v
            continue
        m = dict(v)
        try:
            m["n"] = int(o.get("n") or 0) + int(v["n"])
            m["bug"] = int(o.get("bug") or 0) + int(v["bug"])
            m["sus"] = int(o.get("sus") or 0) + int(v.get("sus") or 0)
            m["first"] = min(int(float(o.get("first") or v["first"])), int(v["first"]))
            ty = dict(o.get("types") or {}) if isinstance(o.get("types"), dict) else {}
            for t9, c9 in v["types"].items():
                ty[t9] = int(ty.get(t9) or 0) + c9
            m["types"] = ty
            if not v.get("bug_last") and o.get("bug_last"):
                m["bug_last"], m["bug_why"] = int(float(o.get("bug_last"))), str(o.get("bug_why") or "")
            if not v.get("sus_last") and o.get("sus_last"):
                m["sus_last"], m["sus_why"] = int(float(o.get("sus_last"))), str(o.get("sus_why") or "")
        except Exception:   # noqa: BLE001 [fallback]
            m = dict(v)
        out[k] = m
    return out


def flush(now: float = None, suffix: str = None) -> None:
    now = now or time.time()
    sfx = _SUFFIX[0] if suffix is None else suffix
    with _FLUSH_LOCK:
        with _LOCK:
            if not _DIRTY[0]:
                _LAST_FLUSH[0] = now
                return
            snap = {k: dict(v, types=dict(v["types"])) for k, v in _SITES.items()}
            _DIRTY[0] = False
            _LAST_FLUSH[0] = now
        try:
            p = path_of(suffix=sfx)
            if _MERGE[0] and sfx:
                snap = _merge_old(p, snap, now)
            elif not sfx:
                snap = _merge_old(p, snap, now, old=_carry_sites(p))
            for v in snap.values():
                v["why"] = logs.safe_err(str(v.get("why") or ""))[:200]
                v["bug_why"] = logs.safe_err(str(v.get("bug_why") or ""))[:200] if v.get("bug_why") else ""
                v["sus_why"] = logs.safe_err(str(v.get("sus_why") or ""))[:200] if v.get("sus_why") else ""
            fsio.atomic_write_json(p, {"v": 1, "proc": _proc(), "pid": os.getpid(), "at": int(now), "sites": snap},
                                   ensure_ascii=False, fsync=False, dir_fsync=False, makedirs=False)
        except Exception:   # noqa: BLE001 [fallback]
            with _LOCK:
                _DIRTY[0] = True


def snapshot() -> dict:
    with _LOCK:
        return {k: dict(v, types=dict(v["types"])) for k, v in _SITES.items()}


atexit.register(flush)
