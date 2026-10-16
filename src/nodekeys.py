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
    "chainnodes": {"name": "Chainnodes", "unit": "calls", "free_month": 12_500_000, "hosts": ["*.chainnodes.org"], "paid_only": False,
                   "pool": False, "no_logs": True, "trace_only": True},
    "alchemy": {"name": "Alchemy", "unit": "cu", "free_month": 30_000_000, "cu": 26, "cu_heavy": 80,
                "cu_methods": {"alchemy_getTokenBalances": 20, "alchemy_getTokenMetadata": 10, "eth_call": 26, "eth_getBalance": 20,
                               "eth_getLogs": 60, "alchemy_getAssetTransfers": 120, "eth_blockNumber": 10, "eth_getTransactionCount": 20,
                               "eth_getTransactionReceipt": 20, "eth_getBlockByNumber": 20},
                "hosts": ["*.g.alchemy.com"], "paid_only": False, "pool": False},
}
PAID_HOST_POLICY = {
    "alchemy": {"*.g.alchemy.com": {"rate": 15.0, "burst": 2, "conc": 4, "call_rate": 25.0, "call_burst": 1,
                                    "share": "node_alchemy", "share_rate": 25.0, "share_burst": 1, "share_xproc": True}},
    "nodereal": {"bsc-mainnet.nodereal.io": {"rate": 8.0, "burst": 8, "conc": 4, "call_rate": 5.0, "call_burst": 5,
                                             "share": "node_nodereal", "share_rate": 5.0, "share_burst": 5, "share_xproc": True}},
}
FREE_HOST_POLICY = {
    "quicknode": {"*.quiknode.pro": {"call_rate": 6.0, "call_burst": 6, "share_rate": 6.0, "share_burst": 6}},
}
CN_HOST_POLICY = {"*.chainnodes.org": {"rate": 2.0, "burst": 2, "conc": 1, "call_rate": 2.0, "call_burst": 2,
                                       "share": "node_chainnodes", "share_rate": 2.0, "share_burst": 2, "share_xproc": True}}
UNIT_KO = {"nodereal": "CU", "ankr": "크레딧", "quicknode": "크레딧", "alchemy": "CU", "chainnodes": "요청"}
ENV_NODEREAL = "TJ_NODEREAL_KEY"
ENV_ANKR = "TJ_ANKR_KEY"
ENV_CN = "TJ_CHAINNODES_KEY"
CN_KEY_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
CN_HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\.chainnodes\.org$")
CN_BASE = "https://base-mainnet.chainnodes.org/"
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
    for k in (ENV_NODEREAL, ENV_ANKR, ENV_QN, ENV_QN_BSC, ENV_QN_BASE, ENV_ALCHEMY, ENV_CN):
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


QN_REJECT_FILE = "qn_reject.json"
QN_REJECT_N = 3
QN_REJECT_SEC = 120
QN_REJECT_HTTP = (401, 402, 403, 404)
_QN_REJECT_TXT = re.compile(
    r"credits?\b.{0,40}?(exhaust|exceed|insufficient|run out|ran out|depleted|used up|no (?:more|remaining))"
    r"|(exhaust|exceed|insufficient|run out|ran out|out of|depleted|used up|no remaining)\w*.{0,40}?\bcredits?\b"
    r"|payment required|\b(trial|subscription)\b.{0,30}?\b(expired|ended|inactive|cancel)", re.I | re.S)
_QN_SLOT = {"at": -1e18, "kh": None, "hosts": {}}
QN_SLOT_TTL = 60.0


def _qn_path() -> str:
    return os.path.join(common.quota_dir(), QN_REJECT_FILE)


def _host(u: str) -> str:
    try:
        return (urllib.parse.urlsplit(str(u)).hostname or "").lower()
    except ValueError:
        return ""


def qn_hosts(env: dict = None) -> dict:
    us = urls(_env() if env is None else env, all_qn=True)
    return {_host(u): c for c in ("bsc", "base") for p, u in us.get(c, []) if p == "quicknode" and _host(u)}


def qn_kh(env: dict = None):
    import hashlib
    us = urls(_env() if env is None else env, all_qn=True)
    got = sorted(u for c in ("bsc", "base") for p, u in us.get(c, []) if p == "quicknode")
    return hashlib.sha256("|".join(got).encode()).hexdigest()[:12] if got else None


def _qn_slot():
    import time as _t
    now = _t.monotonic()
    if now - _QN_SLOT["at"] > QN_SLOT_TTL:
        try:
            env = _env()
            _QN_SLOT.update(at=now, kh=qn_kh(env), hosts=qn_hosts(env))
        except Exception:
            _QN_SLOT.update(at=now, kh=None, hosts={})
    return _QN_SLOT["kh"], _QN_SLOT["hosts"]


def _qn_rej_err(err) -> bool:
    if err is None:
        return False
    if getattr(err, "code", None) in QN_REJECT_HTTP:
        return True
    return bool(_QN_REJECT_TXT.search(str(err) + " " + str(getattr(err, "body", "") or "")))


def _qn_rej_body(body) -> bool:
    items = body if isinstance(body, list) else [body]
    for it in items:
        e9 = it.get("error") if isinstance(it, dict) else None
        if e9 and _QN_REJECT_TXT.search(e9 if isinstance(e9, str) else json_dumps(e9)):
            return True
    return False


def _qn_read():
    try:
        cur = common.read_json(_qn_path(), None)
    except (Exception, SystemExit):
        return None
    return cur if isinstance(cur, dict) and isinstance(cur.get("hosts"), dict) else None


def _qn_update(fn):
    import fcntl
    p = _qn_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".lock", "a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        cur = _qn_read()
        new = fn(cur)
        if new is None:
            try:
                os.remove(p)
            except FileNotFoundError:
                pass
        elif new is not cur:
            common.atomic_write_json(p, new)
        return new


def qn_note(host: str, body=None, err=None) -> None:
    import logging
    import time as _t
    kh, hosts = _qn_slot()
    h = (host or "").lower()
    if not kh or h not in hosts:
        return
    rej = _qn_rej_err(err) if err is not None else _qn_rej_body(body)
    if err is not None and not rej:
        return
    if not rej:
        if not os.path.exists(_qn_path()):
            return

        def ok9(cur):
            if not cur or cur.get("kh") != kh:
                return None
            if h not in cur["hosts"]:
                return cur
            if cur["hosts"][h].get("off"):
                logging.getLogger("tj").warning("QuickNode 키가 다시 응답(%s) — 거부 표식 지움(그 체인 수집기가 QuickNode 를 다시 씀)", hosts.get(h))
            hs9 = {k: v for k, v in cur["hosts"].items() if k != h}
            return dict(cur, hosts=hs9) if hs9 else None
        _qn_update(ok9)
        return
    now = int(_t.time())
    code9 = getattr(err, "code", None) if err is not None else None

    def bad9(cur):
        cur = dict(cur) if cur and cur.get("kh") == kh else {"v": 1, "kh": kh, "hosts": {}}
        r9 = dict(cur["hosts"].get(h) or {"first": now, "n": 0, "chain": hosts.get(h)})
        r9["n"] = int(r9.get("n") or 0) + 1
        r9["last"] = now
        if isinstance(code9, int):
            r9["code"] = code9
        if not r9.get("off") and r9["n"] >= QN_REJECT_N and now - int(r9.get("first") or now) >= QN_REJECT_SEC:
            r9["off"] = True
            r9["off_at"] = now
            logging.getLogger("tj").warning("★QuickNode 키가 계속 거부됨(%s · %s회 · HTTP %s) — 체험이 끝났거나 크레딧을 다 썼을 수 있음 → 그 체인은 QuickNode 빼고 기본 노드로 복귀"
                                            "(수집기 자동 재시작 · 설정 › 연결·키 에서 유료로 바꾼 뒤 '연결 테스트' 통과 또는 키를 바꾸면 다시 씀)★",
                                            hosts.get(h), r9["n"], r9.get("code", "-"))
        cur["hosts"] = dict(cur["hosts"], **{h: r9})
        return cur
    _qn_update(bad9)


def qn_off_hosts(env: dict = None) -> dict:
    cur = _qn_read()
    if not cur or not any(isinstance(v, dict) and v.get("off") for v in cur["hosts"].values()):
        return {}
    env = _env() if env is None else env
    if cur.get("kh") != qn_kh(env):
        return {}
    mine = qn_hosts(env)
    return {k: v for k, v in cur["hosts"].items() if isinstance(v, dict) and v.get("off") and k in mine}


def qn_rejected(env: dict = None):
    off = qn_off_hosts(env)
    if not off:
        return None
    mine = qn_hosts(env)
    codes = [v.get("code") for v in off.values() if isinstance(v.get("code"), int)]
    return {"since": min(int(v.get("off_at") or 0) for v in off.values()), "code": codes[0] if codes else None,
            "chains": sorted({mine[k] for k in off}, key=("bsc", "base").index)}


def qn_reject_clear() -> bool:
    had = []

    def clr(cur):
        had.append(bool(cur and any(isinstance(v, dict) and v.get("off") for v in cur["hosts"].values())))
        return None
    try:
        _qn_update(clr)
    except OSError:
        return False
    _QN_SLOT["at"] = -1e18
    return bool(had and had[0])


ALCH_REJECT_FILE = "alch_reject.json"
ALCH_REJECT_N = 2
ALCH_REJECT_SEC = 60
_ALCH_MONTH_TXT = re.compile(r"monthly capacity|capacity limit exceeded|scaling policy for continued service|monthly (?:compute units?|cu)\b.{0,40}?(?:limit|exceed)"
                             r"|exceeded (?:your|its) monthly", re.I | re.S)
_ALCH_SEC_TXT = re.compile(r"per second", re.I)
ALCH_WHY_KO = {"month": "월 사용량(CU) 한도를 다 썼어요", "pay": "결제가 필요하다고 거절했어요(HTTP 402)", "key": "키를 거부했어요"}


def _alch_path() -> str:
    return os.path.join(common.quota_dir(), ALCH_REJECT_FILE)


def _alch_kh_of(k):
    import hashlib
    k = str(k or "").strip()
    return hashlib.sha256(("alchemy|" + k).encode()).hexdigest()[:12] if KEY_RE.match(k) else None


def alch_url_kh(url: str):
    try:
        sp = urllib.parse.urlsplit(str(url))
    except ValueError:
        return None
    if not (sp.hostname or "").lower().endswith(".g.alchemy.com"):
        return None
    pt = [x for x in (sp.path or "").split("/") if x]
    return _alch_kh_of(pt[1]) if len(pt) >= 2 and pt[0] == "v2" else None


def _alch_why(body=None, err=None, text: str = ""):
    if err is not None:
        code = getattr(err, "code", None)
        t9 = str(err) + " " + str(getattr(err, "body", "") or "") + " " + str(text or "")
        if code == 402:
            return "pay"
        if code in (401, 403):
            return "key"
        if code == 429 and _ALCH_MONTH_TXT.search(t9) and not _ALCH_SEC_TXT.search(t9):
            return "month"
        return None
    for it in (body if isinstance(body, list) else [body]):
        e9 = it.get("error") if isinstance(it, dict) else None
        if e9:
            t9 = e9 if isinstance(e9, str) else json_dumps(e9)
            if _ALCH_MONTH_TXT.search(t9) and not _ALCH_SEC_TXT.search(t9):
                return "month"
    return None


def _alch_read():
    try:
        cur = common.read_json(_alch_path(), None)
    except (Exception, SystemExit):
        return None
    return cur if isinstance(cur, dict) and cur.get("kh") else None


def _alch_update(fn):
    import fcntl
    p = _alch_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".lock", "a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        cur = _alch_read()
        new = fn(cur)
        if new is None:
            try:
                os.remove(p)
            except FileNotFoundError:
                pass
        elif new is not cur:
            common.atomic_write_json(p, new)
        return new


def alch_note(url: str, body=None, err=None, text: str = "") -> None:
    import logging
    import time as _t
    kh = alch_url_kh(url)
    if not kh:
        return
    why = _alch_why(body=body, err=err, text=text)
    if why is None:
        if err is not None or not os.path.exists(_alch_path()):
            return
        if any(isinstance(it, dict) and it.get("error") for it in (body if isinstance(body, list) else [body])):
            return
        if kh != _alch_kh_of(_env().get(ENV_ALCHEMY)):
            return

        def ok9(cur):
            if not cur or cur.get("kh") != kh or kh != _alch_kh_of(_env().get(ENV_ALCHEMY)):
                return cur
            if cur.get("off"):
                logging.getLogger("tj").warning("Alchemy 키가 다시 응답 — 거절 표식 지움")
            return None
        _alch_update(ok9)
        return
    if kh != _alch_kh_of(_env().get(ENV_ALCHEMY)):
        return
    now = int(_t.time())
    code9 = getattr(err, "code", None) if err is not None else None

    def bad9(cur):
        if kh != _alch_kh_of(_env().get(ENV_ALCHEMY)):
            return cur
        r9 = dict(cur) if cur and cur.get("kh") == kh else {"v": 1, "kh": kh, "first": now, "n": 0}
        r9["n"] = int(r9.get("n") or 0) + 1
        r9["last"] = now
        r9["why"] = why
        if isinstance(code9, int):
            r9["code"] = code9
        if not r9.get("off") and r9["n"] >= ALCH_REJECT_N and now - int(r9.get("first") or now) >= ALCH_REJECT_SEC:
            r9["off"] = True
            r9["off_at"] = now
            logging.getLogger("tj").warning("★Alchemy 키가 계속 거절됨 — %s(%s회 · HTTP %s) · 지갑 토큰·잔고 찾기 등 Alchemy 보조가 멈춤(수집은 종전 경로로 계속)★",
                                            ALCH_WHY_KO.get(why, why), r9["n"], r9.get("code", "-"))
        return r9
    _alch_update(bad9)


def alch_rejected(env: dict = None):
    cur = _alch_read()
    if not cur or not cur.get("off"):
        return None
    if cur.get("kh") != _alch_kh_of((_env() if env is None else env).get(ENV_ALCHEMY)):
        return None
    try:
        return {"since": int(cur.get("off_at") or cur.get("first") or 0), "first": int(cur.get("first") or 0), "n": int(cur.get("n") or 0),
                "why": str(cur.get("why") or ""), "code": cur.get("code") if isinstance(cur.get("code"), int) else None, "last": int(cur.get("last") or 0)}
    except (TypeError, ValueError):
        return None


def alch_reject_clear() -> bool:
    had = []

    def clr(cur):
        had.append(bool(cur and cur.get("off")))
        return None
    try:
        _alch_update(clr)
    except OSError:
        return False
    return bool(had and had[0])


def route_fp(chain: str) -> str:
    try:
        env = _env()
        off = qn_off_hosts(env)
        if not off:
            return ""
        mine = qn_hosts(env)
        return f"qn_off:{qn_kh(env)}:{chain}" if any(mine.get(k) == chain for k in off) else ""
    except Exception:
        return ""


def cn_key(v):
    s9 = str(v or "").strip()
    if CN_KEY_RE.match(s9):
        return s9
    try:
        sp = urllib.parse.urlsplit(s9)
        port = sp.port
    except ValueError:
        return None
    h = (sp.hostname or "").lower()
    if sp.scheme != "https" or sp.username or sp.password or port is not None or not CN_HOST_RE.match(h) or sp.query or sp.fragment:
        return None
    seg = [x for x in (sp.path or "").split("/") if x]
    return seg[0] if len(seg) == 1 and CN_KEY_RE.match(seg[0]) else None


def cn_url(env: dict = None):
    k = cn_key(((_env() if env is None else env) or {}).get(ENV_CN))
    return CN_BASE + k if k else None


def trace_nodes(env: dict = None, us: dict = None) -> list:
    env = _env() if env is None else env
    out = []
    u = cn_url(env)
    if u:
        out.append(("chainnodes", u))
    q = trace_url(urls(env) if us is None else us, "base")
    if q:
        out.append(("quicknode", q))
    return out


def urls(env: dict = None, all_qn: bool = False) -> dict:
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
    if not all_qn and any(p == "quicknode" for c in ("bsc", "base") for p, _u in out[c]) and os.path.exists(_qn_path()):
        off = qn_off_hosts(env)
        if off:
            for c in ("bsc", "base"):
                out[c] = [(p, u) for p, u in out[c] if not (p == "quicknode" and _host(u) in off)]
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
    tn = trace_nodes(env, us)
    if isinstance(cb, dict) and tn:
        try:
            import evm_watch
            d16 = [str(u) for u in (evm_watch.rpc_nodes(cfg, "base").get("trace") or [])]
        except Exception:
            d16 = []
        user9 = [str(u) for u in (cb.get("trace_rpcs") or [])] if "trace_rpcs" in cb else []
        cb["trace_rpcs"] = list(dict.fromkeys(user9 + [u for _p, u in tn] + d16))
        done["base_trace"] = [p for p, _u in tn]
    if cn_url(env):
        bf9 = cfg.get("backfill", {})
        if isinstance(bf9, dict) and isinstance(bf9.get("hosts", {}), dict):
            h9 = dict(bf9.get("hosts") or {})
            for h, pol in CN_HOST_POLICY.items():
                h9.setdefault(h, dict(pol))
            cfg["backfill"] = dict(bf9, hosts=h9)
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
    return (h in ("bsc-mainnet.nodereal.io", "rpc.ankr.com") or h.endswith(".quiknode.pro") or h.endswith(".g.alchemy.com")
            or h.endswith(".chainnodes.org"))


def fingerprint() -> str:
    import hashlib
    env = _env()
    vals = [str(env.get(k) or "") for k in (ENV_NODEREAL, ENV_ANKR, ENV_QN_BSC, ENV_QN_BASE)]
    if qn_multi(env):
        vals.append(str(env.get(ENV_QN) or ""))
    if str(env.get(ENV_CN) or "").strip():
        vals.append("cn:" + str(env.get(ENV_CN) or "").strip())
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
    cn9 = cn_url(env)
    for p, meta in PROVIDERS.items():
        chains = [c for c in ("bsc", "base") if any(q == p for q, _u in us[c])]
        if p == "chainnodes" and cn9:
            chains = ["base"]
        sp = budget_spec(p, pl[p])
        out[p] = {"name": meta["name"], "chains": chains, "plan": pl[p]["plan"], "share": pl[p]["share"], "month": pl[p]["month"],
                  "freeMonth": meta["free_month"], "unit": meta["unit"], "unitKo": UNIT_KO.get(p, "CU"), "paidOnly": meta["paid_only"], "shares": list(SHARES),
                  "perDay": int(sp["month"] / 31 * sp["pct"] / 100), "pct": sp["pct"],
                  "usedToday": used_today(p), "pool": meta.get("pool", True)}
        out[p]["burstX"] = sp.get("burst") or 1
        out[p]["noLogs"] = bool(meta.get("no_logs"))
        if meta.get("trace_only"):
            out[p]["traceOnly"] = True
        if p == "quicknode":
            try:
                rj9 = qn_rejected(env)
            except Exception:
                rj9 = None
            if rj9:
                out[p]["rejected"] = rj9
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
