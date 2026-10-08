from __future__ import annotations

import os
import re
import urllib.parse

import common

SHARES = (10, 25, 50, 80)
FREE_PCT = 80
PAID_DEFAULT_SHARE = 10
PLANS_KEY = "node_plans"

PROVIDERS = {
    "nodereal": {"name": "NodeReal", "unit": "cu", "free_month": 10_000_000, "cu": 25, "cu_heavy": 50, "cu_methods": {"eth_getLogs": 50},
                 "hosts": ["bsc-mainnet.nodereal.io"], "paid_only": False},
    "ankr": {"name": "Ankr", "unit": "cu", "free_month": 200_000_000, "cu": 200, "hosts": ["rpc.ankr.com"], "paid_only": False},
    "quicknode": {"name": "QuickNode", "unit": "cu", "free_month": 10_000_000, "cu": 20, "cu_heavy": 40, "hosts": ["*.quiknode.pro"], "paid_only": True},
}
PAID_HOST_POLICY = {
    "nodereal": {"bsc-mainnet.nodereal.io": {"rate": 8.0, "burst": 8, "conc": 4, "call_rate": 5.0, "call_burst": 5,
                                             "share": "node_nodereal", "share_rate": 5.0, "share_burst": 5, "share_xproc": True}},
}
UNIT_KO = {"nodereal": "CU", "ankr": "크레딧", "quicknode": "크레딧"}
ENV_NODEREAL = "TJ_NODEREAL_KEY"
ENV_ANKR = "TJ_ANKR_KEY"
ENV_QN_BSC = "TJ_QUICKNODE_BSC_KEY"
ENV_QN_BASE = "TJ_QUICKNODE_BASE_KEY"
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
SPAN = {"nodereal": 50000, "ankr": 3000, "quicknode": 10000}


def _env() -> dict:
    out = {}
    try:
        with open(common.ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                if s.startswith("export "):
                    s = s[7:].lstrip()
                k, v = s.split("=", 1)
                out[k.strip()] = v.strip().strip("'\"")
    except OSError:
        pass
    for k in (ENV_NODEREAL, ENV_ANKR, ENV_QN_BSC, ENV_QN_BASE):
        if os.environ.get(k):
            out[k] = os.environ[k]
    return out


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
    u = _qn_url(env.get(ENV_QN_BSC), "bsc")
    if u:
        out["bsc"].append(("quicknode", u))
    u = _qn_url(env.get(ENV_QN_BASE), "base")
    if u:
        out["base"].append(("quicknode", u))
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
        share = r.get("share") if r.get("share") in SHARES and not isinstance(r.get("share"), bool) else PAID_DEFAULT_SHARE
        month = r.get("month")
        month = int(month) if isinstance(month, int) and not isinstance(month, bool) and 0 < month <= 10 ** 12 else None
        out[p] = {"plan": plan, "share": share, "month": month}
    return out


def budget_spec(p: str, plan: dict) -> dict:
    meta = PROVIDERS[p]
    if plan["plan"] == "paid":
        month, pct = (plan["month"] or meta["free_month"]), plan["share"]
    else:
        month, pct = meta["free_month"], FREE_PCT
    spec = {"hosts": list(meta["hosts"]), "unit": meta["unit"], "month": int(month), "pct": float(pct)}
    if meta["unit"] == "cu":
        spec["cu"] = meta.get("cu", 20)
        spec["cu_heavy"] = meta.get("cu_heavy", meta.get("cu", 20))
        spec["cu_methods"] = dict(meta.get("cu_methods") or {})
    return spec


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
    for p, pols in PAID_HOST_POLICY.items():
        bf = cfg.get("backfill", {})
        hosts = bf.get("hosts", {}) if isinstance(bf, dict) else None
        if pl[p]["plan"] != "paid" or not isinstance(hosts, dict):
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
            if u not in logs:
                logs.append(u)
            if u not in arch:
                arch.append(u)
            caps.setdefault(u, SPAN[p])
            done.setdefault("bsc", []).append(p)
        bc["logs_rpcs"], bc["archive_rpcs"], bc["getlogs_span_caps"] = logs, arch, caps
    cb = (cfg.get("chains") or {}).get("base") if isinstance(cfg.get("chains"), dict) else None
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
    return h in ("bsc-mainnet.nodereal.io", "rpc.ankr.com") or h.endswith(".quiknode.pro")


def fingerprint() -> str:
    import hashlib
    env = _env()
    vals = [str(env.get(k) or "") for k in (ENV_NODEREAL, ENV_ANKR, ENV_QN_BSC, ENV_QN_BASE)]
    return hashlib.sha256(json_dumps([vals, plans()]).encode()).hexdigest()[:12]


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
                  "perDay": int(sp["month"] / 31 * sp["pct"] / 100), "pct": sp["pct"]}
    return out
