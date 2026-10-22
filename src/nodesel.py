from __future__ import annotations

import collections
import os
import threading
import time
import urllib.parse

import paths, statefile

ROLES = ("head", "logs", "state", "detail", "trace")
_STATE_M = frozenset(("eth_getBalance", "eth_getTransactionCount", "eth_call", "eth_getCode", "eth_getStorageAt", "eth_getProof"))
_HEAD_M = frozenset(("eth_blockNumber", "eth_chainId", "net_version", "eth_syncing"))
_ROLE_PRI = {"trace": 0, "logs": 1, "state": 2, "detail": 3, "head": 4}


def role_of(methods) -> str:
    cnt = collections.Counter()
    for m in methods or ():
        m = str(m or "")
        if m == "eth_getLogs":
            r = "logs"
        elif m.startswith(("debug_", "trace_", "arbtrace_")):
            r = "trace"
        elif m in _STATE_M:
            r = "state"
        elif m in _HEAD_M:
            r = "head"
        else:
            r = "detail"
        cnt[r] += 1
    if not cnt:
        return "detail"
    return sorted(cnt.items(), key=lambda kv: (-kv[1], _ROLE_PRI[kv[0]]))[0][0]


ROLE_OK = {
    "nodereal": frozenset(("logs", "state", "detail", "head")),
    "ankr": frozenset(("logs", "state", "detail", "head")),
    "quicknode": frozenset(),
    "alchemy": frozenset(),
}
KEY_NAME = {"nodereal": "NodeReal", "ankr": "Ankr", "quicknode": "QuickNode", "alchemy": "Alchemy"}

SLO = {"head": 4.0, "detail": 10.0, "state": 10.0, "logs": 15.0, "trace": 20.0}
FAIL_RATE = 0.2
WIN_N = 6
MIN_N = 3
SLOW_FRAC = 1.0 / 3
WIN_MAX_AGE = 900.0
HOLD_SEC = 60.0
PROBE_SEC = 60.0
RECOVER_N = 3
BF_TARGET_SEC = 7200.0
HOLD_BF_SEC = 600.0
KEEP = 40
FLUSH_SEC = 60.0
_FAILS = frozenset(("http429", "quota", "timeout", "t408", "http5xx", "conn", "dns", "payload", "auth"))

_LOCK = threading.RLock()
_CHAIN = {}
_ST = {}
_CNT = {}
_DEM = {}
_BF = {}
_SHADOW = {}
_CFG = {"on": True, "slo": dict(SLO), "bf_target": BF_TARGET_SEC}
_FLUSH = {"at": 0.0}
_TL = threading.local()

clock = time.monotonic


def configure(cfg: dict):
    bf = (cfg or {}).get("backfill") if isinstance((cfg or {}).get("backfill"), dict) else {}
    with _LOCK:
        _CFG["on"] = bf.get("node_select") is not False
        slo = dict(SLO)
        ov = bf.get("node_slo_sec") if isinstance(bf.get("node_slo_sec"), dict) else {}
        for r, v in ov.items():
            if r in slo and isinstance(v, (int, float)) and not isinstance(v, bool) and 0.1 <= float(v) <= 600:
                slo[r] = float(v)
        _CFG["slo"] = slo
        t9 = bf.get("bf_target_sec")
        _CFG["bf_target"] = float(t9) if isinstance(t9, (int, float)) and not isinstance(t9, bool) and 60 <= float(t9) <= 30 * 86400 else BF_TARGET_SEC


def enabled() -> bool:
    return bool(_CFG["on"])


def register(chain: str, *url_lists):
    with _LOCK:
        for lst in url_lists:
            for u in (lst or ()):
                _CHAIN.setdefault(str(u), str(chain))


def chain_of(url: str):
    return _CHAIN.get(str(url))


def _host(url) -> str:
    try:
        return (urllib.parse.urlsplit(str(url)).hostname or "").lower()
    except ValueError:
        return ""


def provider_of(url) -> tuple:
    h = _host(url)
    if h == "bsc-mainnet.nodereal.io" or h.endswith(".nodereal.io"):
        return "nodereal", "key"
    if h == "rpc.ankr.com":
        return "ankr", "key"
    if h.endswith(".quiknode.pro"):
        return "quicknode", "key"
    if h.endswith(".g.alchemy.com"):
        return "alchemy", "key"
    labs = [x for x in h.split(".") if x]
    if not labs:
        return "?", "public"
    if all(x.isdigit() for x in labs) or h in ("localhost",):
        return "local", "public"
    return ".".join(labs[-2:]), "public"


def is_key(url) -> bool:
    if provider_of(url)[1] == "key":
        return True
    try:
        import nodekeys
        return bool(nodekeys.is_key_node(url))
    except Exception:   # noqa: BLE001 [probe]
        return False


def role_ok(url, role: str) -> bool:
    p, k = provider_of(url)
    return k != "key" or role in ROLE_OK.get(p, frozenset())


def mark_dispatch():
    _TL.disp = clock()


def begin():
    _TL.disp = None
    return clock()


def _err_kind(err) -> str:
    if err is None:
        return "ok"
    k = str(getattr(err, "kind", "") or "other")
    code = getattr(err, "code", None)
    if k == "http4xx" and code == 408:
        return "t408"
    if k == "http4xx" and code in (401, 402, 403):
        return "auth"
    return k


def end(url, methods, cost: int, t0: float, err=None):
    try:
        _record(url, methods, cost, t0, getattr(_TL, "disp", None), clock(), err)
    except Exception:   # noqa: BLE001 [optional]
        pass


def _mode() -> str:
    try:
        import bf_engine
        return "bf" if bf_engine.burst_on() else "rt"
    except Exception:   # noqa: BLE001 [fallback]
        return "rt"


def _record(url, methods, cost, t0, disp, t1, err):
    u = str(url)
    ch = _CHAIN.get(u)
    if ch is None:
        return
    role = role_of(methods)
    mode = _mode()
    kind = _err_kind(err)
    local = bool(getattr(err, "local", False)) or kind in ("budget", "circuit") or (disp is None and err is not None)
    key = (ch, role, mode, u)
    with _LOCK:
        c = _CNT.setdefault(key, {"n": 0, "ok": 0, "local": 0, "gate_s": 0.0, "tr_s": 0.0, "units": 0})
        if local:
            c["local"] += 1
            return
        tr = max(0.0, t1 - (disp if disp is not None else t0))
        c["n"] += 1
        c["gate_s"] += max(0.0, (disp - t0) if disp is not None else 0.0)
        c["tr_s"] += tr
        bad = kind in _FAILS
        if kind == "ok" or not bad:
            c["ok"] += 1
            c["units"] += max(1, int(cost or 1))
        if kind != "ok":
            c[kind] = c.get(kind, 0) + 1
        dq = _ST.get(key)
        if dq is None:
            dq = _ST[key] = collections.deque(maxlen=KEEP)
        dq.append((t1, not bad, tr, kind))
        _after_sample(ch, role, u, mode, not bad, tr)
    _maybe_flush()


def _p95(xs) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]


def _win_bad(samples, slo: float):
    if len(samples) < MIN_N:
        return None
    fails = sum(1 for s in samples if not s[1])
    if fails / float(len(samples)) > FAIL_RATE:
        return True
    return sum(1 for s in samples if s[2] > slo) / float(len(samples)) > SLOW_FRAC


def node_bad(chain: str, role: str, url: str, mode: str = "rt", now: float = None):
    now = clock() if now is None else now
    with _LOCK:
        dq = list(_ST.get((chain, role, mode, str(url))) or ())
    dq = [s for s in dq if now - s[0] <= WIN_MAX_AGE][-2 * WIN_N:]
    if len(dq) < 2 * WIN_N:
        return None
    half = len(dq) // 2
    a, b = _win_bad(dq[:half], _CFG["slo"].get(role, 10.0)), _win_bad(dq[half:], _CFG["slo"].get(role, 10.0))
    if a is None or b is None:
        return None
    return bool(a and b)


def _after_sample(ch, role, u, mode, ok, tr):
    if is_key(u):
        return
    k = (ch, role, u)
    d = _DEM.get(k)
    now = clock()
    if d is None:
        if mode == "rt" and node_bad(ch, role, u, "rt", now):
            _DEM[k] = {"at": now, "probe_at": now, "good": 0}
        return
    good = ok and tr <= _CFG["slo"].get(role, 10.0)
    d["good"] = d["good"] + 1 if good else 0
    if d["good"] >= RECOVER_N and now - d["at"] >= HOLD_SEC:
        _DEM.pop(k, None)
        with_q = _ST.get((ch, role, "rt", u))
        if with_q is not None:
            with_q.clear()


def demoted(chain: str, role: str, url: str) -> bool:
    with _LOCK:
        return (chain, role, str(url)) in _DEM


def _probe_due(chain, role, url, now) -> bool:
    d = _DEM.get((chain, role, str(url)))
    if d is None or now - d["probe_at"] < PROBE_SEC:
        return False
    d["probe_at"] = now
    return True


def _ready(u) -> bool:
    try:
        import bf_engine
        g = bf_engine.gate(u)
        return not g.is_open() and not g.resting()
    except Exception:   # noqa: BLE001 [fallback]
        return True


def order(chain: str, role: str, urls, base=None, key_first: bool = False) -> list:
    base = list(base if base is not None else urls)
    now = clock()
    keys = [u for u in base if is_key(u) and role_ok(u, role) and _ready(u)]
    with _LOCK:
        dem = [u for u in base if not is_key(u) and (chain, role, str(u)) in _DEM]
        probe = next((u for u in dem if _ready(u) and _probe_due(chain, role, u, now)), None) if dem else None
    if key_first and keys and len(keys) < len(base):
        out = keys + [u for u in base if u not in keys]
    else:
        out = list(base)
    moved9 = False
    for d in dem:
        i = out.index(d)
        after = out[i + 1:]
        anc = [j for j, u in enumerate(after) if u in keys]
        if not anc:
            anc = [j for j, u in enumerate(after) if not is_key(u) and u not in dem and _ready(u)]
        if not anc:
            continue
        seg = after[:anc[-1] + 1]
        carry = [u for u in seg if is_key(u) and not role_ok(u, role)]
        out = out[:i] + [u for u in seg if u not in carry] + [d] + carry + after[anc[-1] + 1:]
        moved9 = True
    if moved9 and probe is not None:
        out = [probe] + [u for u in out if u != probe]
    return out


def demote_public(chain: str, role: str, urls) -> list:
    out = list(urls)
    now = clock()
    with _LOCK:
        dem = [u for u in out if not is_key(u) and (chain, role, str(u)) in _DEM]
        if not dem or any(_ready(u) and _probe_due(chain, role, u, now) for u in dem):
            return out
    for d in dem:
        i = out.index(d)
        j = i + 1
        while j < len(out) and not is_key(out[j]):
            j += 1
        seg = out[i + 1:j]
        ok9 = [k for k, u in enumerate(seg) if u not in dem and _ready(u)]
        if ok9:
            out = out[:i] + seg[:ok9[-1] + 1] + [d] + seg[ok9[-1] + 1:] + out[j:]
    return out


def lane_eta(chain: str, eta_sec, remaining) -> None:
    now = clock()
    with _LOCK:
        b = _BF.setdefault(chain, {"mode": "public", "at": -1e18})
        try:
            rem = float(remaining) if remaining is not None else None
        except (TypeError, ValueError):
            rem = None
        try:
            eta = float(eta_sec) if eta_sec is not None else None
        except (TypeError, ValueError):
            eta = None
        b["eta"], b["rem"], b["eta_at"] = eta, rem, now
        tgt = float(_CFG["bf_target"])
        if rem is not None and rem <= 0:
            if b["mode"] == "key":
                b.update(mode="public", at=now)
            return
        if b["mode"] == "public":
            if eta is not None and eta > tgt and now - b["at"] >= HOLD_BF_SEC:
                b.update(mode="key", at=now, eta0=eta, rem0=rem)
        else:
            e0, r0 = b.get("eta0"), b.get("rem0")
            proj = (e0 * rem / r0) if (e0 is not None and rem is not None and r0) else None
            if proj is not None and proj <= tgt * 0.5 and now - b["at"] >= HOLD_BF_SEC:
                b.update(mode="public", at=now)


def bf_key_first(chain: str) -> bool:
    with _LOCK:
        b = _BF.get(chain)
        return bool(b and b.get("mode") == "key")


def shadow(chain: str, role: str, mode: str, cur: list, new: list):
    with _LOCK:
        s = _SHADOW.setdefault((chain, role, mode), {"n": 0, "diff": 0, "last": None})
        s["n"] += 1
        if cur and new and cur[0] != new[0]:
            s["diff"] += 1
            s["last"] = provider_of(new[0])[0]


def label(p: str) -> str:
    return KEY_NAME.get(p) or "공개 노드"


def via(chain: str, mode: str = None, window: float = 300.0) -> str:
    now = clock()
    cnt = collections.Counter()
    with _LOCK:
        for (ch, _r, md, u), dq in _ST.items():
            if ch != chain or (mode and md != mode):
                continue
            n = sum(1 for s in dq if s[1] and now - s[0] <= window)
            if n:
                cnt[label(provider_of(u)[0]) if is_key(u) else "공개 노드"] += n
    tot = sum(cnt.values())
    if not tot:
        return ""
    names = [k for k, v in cnt.most_common() if v / float(tot) >= 0.2][:2]
    return " + ".join(names)


def snapshot(now: float = None) -> dict:
    now = clock() if now is None else now
    rows = {}
    with _LOCK:
        for (ch, role, md, u), c in _CNT.items():
            p, kind = provider_of(u)
            k = (ch, role, md, p)
            r = rows.setdefault(k, {"chain": ch, "role": role, "mode": md, "prov": p, "kind": kind, "n": 0, "ok": 0, "local": 0,
                                    "gate_s": 0.0, "tr_s": 0.0, "units": 0, "lat": []})
            for f, v in c.items():
                if isinstance(v, (int, float)) and f in r and f != "lat":
                    r[f] += v
                elif f not in r:
                    r[f] = r.get(f, 0) + v
            dq = _ST.get((ch, role, md, u)) or ()
            r["lat"] += [s[2] for s in dq if s[1] and now - s[0] <= WIN_MAX_AGE]
            try:
                import bf_engine
                r["ledger"] = bf_engine._rpc_day_of(_host(u)) or None
            except Exception:   # noqa: BLE001 [optional]
                pass
        dem = [{"chain": ch, "role": role, "prov": provider_of(u)[0], "since": round(now - d["at"], 1)} for (ch, role, u), d in _DEM.items()]
        bf = {ch: {k: (round(v, 1) if isinstance(v, float) else v) for k, v in b.items() if k in ("mode", "eta", "rem")} for ch, b in _BF.items()}
        sh = {f"{c}:{r}:{m}": dict(v) for (c, r, m), v in _SHADOW.items()}
    out = []
    for r in rows.values():
        lat = r.pop("lat")
        r["p50"] = round(sorted(lat)[len(lat) // 2], 3) if lat else None
        r["p95"] = round(_p95(lat), 3) if lat else None
        r["gate_s"], r["tr_s"] = round(r["gate_s"], 2), round(r["tr_s"], 2)
        r["rate"] = round(r["units"] / r["tr_s"], 3) if r["tr_s"] > 0 else None
        out.append(r)
    out.sort(key=lambda r: (r["chain"], r["role"], r["mode"], r["prov"]))
    return {"v": 1, "on": enabled(), "rows": out, "demoted": dem, "bf": bf, "shadow": sh}


def _maybe_flush(force: bool = False):
    now = clock()
    if not force and now - _FLUSH["at"] < FLUSH_SEC:
        return
    _FLUSH["at"] = now
    try:
        import bf_engine
        proc = bf_engine._RPC_DAY_PROC
        snap = snapshot(now)
        snap["proc"], snap["updated"] = proc, int(time.time())
        statefile.atomic_write_json(os.path.join(paths.quota_dir(), "node_stats", f"{proc}.json"), snap)
    except Exception:   # noqa: BLE001 [optional]
        pass


def reset():
    with _LOCK:
        _CHAIN.clear()
        _ST.clear()
        _CNT.clear()
        _DEM.clear()
        _BF.clear()
        _SHADOW.clear()
        _FLUSH["at"] = 0.0
