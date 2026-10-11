from __future__ import annotations

import os
import re
import urllib.parse

import common

SHARES = (10, 25, 50, 80)
FREE_PCT = 80
BURST_X = 10
FRESH_EXTRA = ("helius",)
PAID_DEFAULT_SHARE = 10
PLANS_KEY = "node_plans"

PROVIDERS = {
    "nodereal": {"name": "NodeReal", "unit": "cu", "free_month": 10_000_000, "cu": 25, "cu_heavy": 50, "cu_methods": {"eth_getLogs": 50},
                 "hosts": ["bsc-mainnet.nodereal.io"], "paid_only": False},
    "ankr": {"name": "Ankr", "unit": "cu", "free_month": 200_000_000, "cu": 200, "cu_prefix": {"ankr_": 700}, "hosts": ["rpc.ankr.com"], "paid_only": False},
    "quicknode": {"name": "QuickNode", "unit": "cu", "free_month": 10_000_000, "cu": 20, "cu_heavy": 40, "hosts": ["*.quiknode.pro"], "paid_only": False,
                  "paid_share": 80, "no_logs": True},
    "alchemy": {"name": "Alchemy", "unit": "cu", "free_month": 30_000_000, "cu": 26, "cu_heavy": 80,
                "cu_methods": {"alchemy_getTokenBalances": 20, "alchemy_getTokenMetadata": 10, "eth_call": 26, "eth_getBalance": 20,
                               "eth_getLogs": 60, "alchemy_getAssetTransfers": 120, "eth_blockNumber": 10, "eth_getTransactionCount": 20,
                               "eth_getTransactionReceipt": 20, "eth_getBlockByNumber": 20},
                "hosts": ["*.g.alchemy.com"], "paid_only": False, "pool": False},
}
PAID_HOST_POLICY = {
    "nodereal": {"bsc-mainnet.nodereal.io": {"rate": 8.0, "burst": 8, "conc": 4, "call_rate": 5.0, "call_burst": 5,
                                             "share": "node_nodereal", "share_rate": 5.0, "share_burst": 5, "share_xproc": True}},
}
FREE_HOST_POLICY = {
    "quicknode": {"*.quiknode.pro": {"call_rate": 6.0, "call_burst": 6, "share_rate": 6.0, "share_burst": 6}},
}
UNIT_KO = {"nodereal": "CU", "ankr": "크레딧", "quicknode": "크레딧", "alchemy": "CU"}
ENV_NODEREAL = "TJ_NODEREAL_KEY"
ENV_ANKR = "TJ_ANKR_KEY"
ENV_ALCHEMY = "TJ_ALCHEMY_KEY"
HOT_KEYS = ("alchemy",)
NET_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
ENV_QN = "TJ_QUICKNODE_KEY"
ENV_QN_BSC = "TJ_QUICKNODE_BSC_KEY"
ENV_QN_BASE = "TJ_QUICKNODE_BASE_KEY"
QN_NET = {"bsc": "bsc", "base": "base-mainnet"}
QN_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
QN_TOKEN_RE = re.compile(r"^[A-Za-z0-9]{8,128}$")
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
SPAN = {"nodereal": 50000, "ankr": 3000, "quicknode": 10000}


def _env() -> dict:
    out = common.read_env_file()
    for k in (ENV_NODEREAL, ENV_ANKR, ENV_QN, ENV_QN_BSC, ENV_QN_BASE, ENV_ALCHEMY):
        if os.environ.get(k):
            out[k] = os.environ[k]
    return out


def _key(env: dict, name: str):
    k = str((env or {}).get(name) or "").strip()
    return k if KEY_RE.match(k) else None


def alchemy_url(net: str, env: dict = None):
    if not isinstance(net, str) or not NET_RE.match(net):
        return None
    k = _key(_env() if env is None else env, ENV_ALCHEMY)
    return f"https://{net}.g.alchemy.com/v2/{k}" if k else None


def ankr_multichain_url(env: dict = None):
    k = _key(_env() if env is None else env, ENV_ANKR)
    return f"https://rpc.ankr.com/multichain/{k}" if k else None


def used_today(p: str, now: float = None) -> int:
    import time as _t
    day = int((_t.time() if now is None else now) // 86400)
    d = os.path.join(common.quota_dir(), f"rpc_day_node_{p}")
    try:
        names = os.listdir(d)
    except OSError:
        return 0
    tot = 0
    for f in names:
        if not f.endswith(".json"):
            continue
        try:
            j = common.read_json(os.path.join(d, f), None)
            if isinstance(j, dict) and j.get("day") == day:
                tot += max(0, int(j.get("n") or 0))
        except (Exception, SystemExit):
            continue
    return tot


def _qn_url(v: str, want: str) -> str:
    try:
        sp = urllib.parse.urlsplit(str(v or "").strip())
    except ValueError:
        return ""
    h = (sp.hostname or "").lower()
    if sp.scheme != "https" or not h.endswith(".quiknode.pro") or sp.username or sp.password:
        return ""
    labs = h.split(".")[:-2]
    if want == "bsc" and "bsc" not in labs:
        return ""
    if want == "base" and "base-mainnet" not in labs:
        return ""
    return urllib.parse.urlunsplit(("https", h, sp.path or "/", "", ""))


def qn_parts(v: str):
    try:
        sp = urllib.parse.urlsplit(str(v or "").strip())
        port = sp.port
    except ValueError:
        return None
    h = (sp.hostname or "").lower()
    if sp.scheme not in ("https", "wss") or sp.username or sp.password or port is not None or not h.endswith(".quiknode.pro"):
        return None
    labs = h.split(".")[:-2]
    if len(labs) not in (1, 2) or not all(QN_NAME_RE.match(x) for x in labs):
        return None
    seg = [x for x in (sp.path or "").split("/") if x]
    if not seg or not QN_TOKEN_RE.match(seg[0]):
        return None
    return labs[0], seg[0]


def qn_chain_url(v: str, chain: str) -> str:
    net = QN_NET.get(chain)
    pt = qn_parts(v)
    if not net or not pt:
        return ""
    return f"https://{pt[0]}.{net}.quiknode.pro/{pt[1]}/"


def qn_multi(env: dict) -> bool:
    return bool(str((env or {}).get(ENV_QN) or "").strip())


def urls(env: dict = None) -> dict:
    env = _env() if env is None else env
    out = {"bsc": [], "base": []}
    k = str(env.get(ENV_NODEREAL) or "").strip()
    if KEY_RE.match(k):
        out["bsc"].append(("nodereal", f"https://bsc-mainnet.nodereal.io/v1/{k}"))
    k = str(env.get(ENV_ANKR) or "").strip()
    if KEY_RE.match(k):
        out["bsc"].append(("ankr", f"https://rpc.ankr.com/bsc/{k}"))
        out["base"].append(("ankr", f"https://rpc.ankr.com/base/{k}"))
    for c in ("bsc", "base"):
        u = qn_chain_url(env.get(ENV_QN), c) if qn_multi(env) else _qn_url(env.get(ENV_QN_BSC if c == "bsc" else ENV_QN_BASE), c)
        if u:
            out[c].append(("quicknode", u))
    return out


def plans(settings: dict = None) -> dict:
    if settings is None:
        settings = common.read_json(os.path.join(common.STATE_DIR, "settings.json"), {}) or {}
    raw = settings.get(PLANS_KEY) if isinstance(settings, dict) and isinstance(settings.get(PLANS_KEY), dict) else {}
    out = {}
    for p, meta in PROVIDERS.items():
        r = raw.get(p) if isinstance(raw.get(p), dict) else {}
        plan = r.get("plan") if r.get("plan") in ("free", "paid") else ("paid" if meta["paid_only"] else "free")
        if meta["paid_only"]:
            plan = "paid"
        share = r.get("share") if r.get("share") in SHARES and not isinstance(r.get("share"), bool) else meta.get("paid_share", PAID_DEFAULT_SHARE)
        month = r.get("month")
        month = int(month) if isinstance(month, int) and not isinstance(month, bool) and 0 < month <= 10 ** 12 else None
        out[p] = {"plan": plan, "share": share, "month": month}
        fs = _fresh_str(r.get("fresh_since"))
        if fs:
            out[p]["fresh_since"] = fs
    return out


def _fresh_str(v):
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return None
    try:
        import time as _t
        _t.strptime(v, "%Y-%m-%d")
    except ValueError:
        return None
    return v


def fresh_day_num(v):
    fs = _fresh_str(v)
    if not fs:
        return None
    import calendar
    import time as _t
    return int(calendar.timegm(_t.strptime(fs, "%Y-%m-%d")) // 86400)


_FRESH_CACHE = {"key": None, "v": {}}


def fresh_day(p: str):
    path = os.path.join(common.STATE_DIR, "settings.json")
    try:
        st = os.stat(path)
        key = (path, st.st_mtime_ns, st.st_size)
    except OSError:
        return None
    if _FRESH_CACHE["key"] != key:
        try:
            st9 = common.read_json(path, {}) or {}
            pl = plans(st9 if isinstance(st9, dict) else {})
        except Exception:
            return None
        v9 = {q: (fresh_day_num(v.get("fresh_since")) if v.get("plan") != "paid" and not PROVIDERS[q]["paid_only"] else None)
              for q, v in pl.items()}
        raw9 = st9.get(PLANS_KEY) if isinstance(st9, dict) and isinstance(st9.get(PLANS_KEY), dict) else {}
        for q in FRESH_EXTRA:
            r9 = raw9.get(q) if isinstance(raw9.get(q), dict) else {}
            v9[q] = fresh_day_num(r9.get("fresh_since"))
        _FRESH_CACHE["v"] = v9
        _FRESH_CACHE["key"] = key
    return _FRESH_CACHE["v"].get(p)


def budget_spec(p: str, plan: dict) -> dict:
    meta = PROVIDERS[p]
    if plan["plan"] == "paid":
        month, pct = (plan["month"] or meta["free_month"]), plan["share"]
    else:
        month, pct = meta["free_month"], FREE_PCT
    spec = {"hosts": list(meta["hosts"]), "unit": meta["unit"], "month": int(month), "pct": float(pct),
            "window": True}
    if plan["plan"] != "paid" and not meta["paid_only"]:
        spec["burst"] = float(BURST_X)
        spec["svc"] = p
        fd = fresh_day_num(plan.get("fresh_since"))
        if fd is not None:
            spec["fresh_since"] = fd
    if meta["unit"] == "cu":
        spec["cu"] = meta.get("cu", 20)
        spec["cu_heavy"] = meta.get("cu_heavy", meta.get("cu", 20))
        spec["cu_methods"] = dict(meta.get("cu_methods") or {})
        if meta.get("cu_prefix"):
            spec["cu_prefix"] = dict(meta["cu_prefix"])
    return spec


def logs_ok(p: str) -> bool:
    return not PROVIDERS.get(p, {}).get("no_logs")


def trace_url(us: dict, chain: str):
    for p, u in us.get(chain, []):
        if p == "quicknode":
            return u
    return None


def apply(cfg: dict, env: dict = None, settings: dict = None) -> dict:
    us = urls(env)
    pl = plans(settings)
    done = {}
    lim = cfg.get("rpc_day_limits") if isinstance(cfg.get("rpc_day_limits"), dict) else {}
    lim = dict(lim)
    for p in PROVIDERS:
        if f"node_{p}" not in lim:
            lim[f"node_{p}"] = budget_spec(p, pl[p])
    cfg["rpc_day_limits"] = lim
    for p, pols, want in ([(p9, v9, "paid") for p9, v9 in PAID_HOST_POLICY.items()]
                          + [(p9, v9, "free") for p9, v9 in FREE_HOST_POLICY.items()]):
        bf = cfg.get("backfill", {})
        hosts = bf.get("hosts", {}) if isinstance(bf, dict) else None
        if pl[p]["plan"] != want or not isinstance(hosts, dict):
            continue
        hosts = dict(hosts)
        for h, pol in pols.items():
            hosts.setdefault(h, dict(pol))
        cfg["backfill"] = dict(bf, hosts=hosts)
    bc = cfg.get("bsc") if isinstance(cfg.get("bsc"), dict) else None
    if bc is not None and us["bsc"]:
        logs = [str(u) for u in (bc.get("logs_rpcs") or [])]
        arch = [str(u) for u in (bc.get("archive_rpcs") or [u for u in logs if "nodereal" in u])]
        caps = dict(bc.get("getlogs_span_caps") or {})
        for p, u in us["bsc"]:
            if logs_ok(p):
                if u not in logs:
                    logs.append(u)
                caps.setdefault(u, SPAN[p])
            if u not in arch:
                arch.append(u)
            done.setdefault("bsc", []).append(p)
        bc["logs_rpcs"], bc["archive_rpcs"], bc["getlogs_span_caps"] = logs, arch, caps
    cb = (cfg.get("chains") or {}).get("base") if isinstance(cfg.get("chains"), dict) else None
    tq = trace_url(us, "base")
    if isinstance(cb, dict) and tq:
        tr = [str(u) for u in (cb.get("trace_rpcs") or [])] if "trace_rpcs" in cb else []
        if tq not in tr:
            tr.insert(0, tq)
        cb["trace_rpcs"] = tr
        done["base_trace"] = ["quicknode"]
    if isinstance(cb, dict) and us["base"]:
        rl = [str(u) for u in (cb.get("rpc_logs") or [])]
        if not rl:
            try:
                import evm_watch
                rl = [str(u) for u in (evm_watch.rpc_nodes(cfg, "base").get("logs") or [])]
            except Exception:
                rl = None
        if rl is None:
            return done
        ar = [str(u) for u in (cb.get("archive_rpcs") or [])]
        if not ar:
            try:
                import evm_watch
                ar = [str(u) for u in (evm_watch.rpc_nodes(cfg, "base").get("state") or [])]
            except Exception:
                return done
        caps = dict(cb.get("rpc_log_span_caps") or {})
        for p, u in us["base"]:
            if u not in ar:
                ar.append(u)
        for p, u in reversed(us["base"]):
            if not logs_ok(p):
                continue
            if u not in rl:
                rl.insert(0, u)
            caps.setdefault(u, SPAN[p])
        cb["rpc_logs"], cb["archive_rpcs"], cb["rpc_log_span_caps"] = rl, ar, caps
        done["base"] = [p for p, _u in us["base"]]
    return done


def is_key_node(url: str) -> bool:
    try:
        h = (urllib.parse.urlsplit(str(url)).hostname or "").lower()
    except ValueError:
        return False
    return h in ("bsc-mainnet.nodereal.io", "rpc.ankr.com") or h.endswith(".quiknode.pro") or h.endswith(".g.alchemy.com")


def fingerprint() -> str:
    import hashlib
    env = _env()
    vals = [str(env.get(k) or "") for k in (ENV_NODEREAL, ENV_ANKR, ENV_QN_BSC, ENV_QN_BASE)]
    if qn_multi(env):
        vals.append(str(env.get(ENV_QN) or ""))
    pl = {q: {k: v for k, v in d.items() if k != "fresh_since"} for q, d in plans().items()}
    return hashlib.sha256(json_dumps([vals, pl]).encode()).hexdigest()[:12]


def json_dumps(o) -> str:
    import json
    return json.dumps(o, sort_keys=True, ensure_ascii=False)


def status(env: dict = None, settings: dict = None) -> dict:
    env = _env() if env is None else env
    us = urls(env)
    pl = plans(settings)
    out = {}
    for p, meta in PROVIDERS.items():
        chains = [c for c in ("bsc", "base") if any(q == p for q, _u in us[c])]
        sp = budget_spec(p, pl[p])
        out[p] = {"name": meta["name"], "chains": chains, "plan": pl[p]["plan"], "share": pl[p]["share"], "month": pl[p]["month"],
                  "freeMonth": meta["free_month"], "unit": meta["unit"], "unitKo": UNIT_KO.get(p, "CU"), "paidOnly": meta["paid_only"], "shares": list(SHARES),
                  "perDay": int(sp["month"] / 31 * sp["pct"] / 100), "pct": sp["pct"],
                  "usedToday": used_today(p), "pool": meta.get("pool", True)}
        out[p]["burstX"] = sp.get("burst") or 1
        out[p]["noLogs"] = bool(meta.get("no_logs"))
        out[p]["freshSince"] = pl[p].get("fresh_since")
        out[p]["bursting"] = bool(sp.get("burst")) and out[p]["usedToday"] > out[p]["perDay"]
        if sp.get("burst"):
            out[p].update(_flex_view(p, sp))
    return out


def _flex_view(p: str, sp: dict) -> dict:
    try:
        import time as _t
        import bf_engine
        now = _t.time()
        per = float(sp["month"]) / bf_engine.RPC_DAY_MONTH_DAYS
        n_day = max(1, int(per * float(sp["pct"]) / 100.0))
        cap = int(float(sp["month"]) * float(sp["pct"]) / 100.0)
        d = os.path.join(common.quota_dir(), f"rpc_day_node_{p}")
        L = bf_engine.es_ledger_read(now, d=d)
        r = bf_engine.node_day_lims(d, now, n_day, float(sp["burst"]), cap, int(L["n"]), int(L["nh"]), fresh_day(p))
        if r.get("bad"):
            return {}
        return {"rtDay": int(r.get("rt") or 0), "burstCap": int(r.get("burst") or 0)}
    except Exception:
        return {}
