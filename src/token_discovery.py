from __future__ import annotations

import fcntl
import json
import os
import re
import threading
import time
import urllib.parse

import common

STATE_NAME = "token_discovery.json"
SEED_NAME = "coverage/token_sources.json"
SCHEMA = 1
TRANSFER_T0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
CA_RE = re.compile(r"^0x[0-9a-f]{40}$")
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
ENV_ALCHEMY = "TJ_ALCHEMY_KEY"
ENV_ANKR = "TJ_ANKR_KEY"
ENV_ES = "TJ_ETHERSCAN_KEY"
INDEX_SOURCES = ("etherscan", "routescan", "blockscout", "alchemy", "ankr")
FINAL_FAIL = ("unsupported", "nokey", "slow", "partial")
KEYED = ("etherscan", "alchemy", "ankr")
MAX_CAS = 3000
MAX_QUERY = 1500
ES_PAGES = 5
BS_PAGES = 40
AL_PAGES = 20
AN_PAGES = 5
LOGS_MAX_CALLS = 600
JOB_MAX_SEC = 900.0
RETRY_FAIL_SEC = 6 * 3600
HOLD_RETRY_SEC = 3600
HOLD_DEX_MAX = 20
PX_MAX_AGE = 6 * 3600
ANKR_ADV_CREDITS = 700
ALCHEMY_FALLBACK = {"hosts": ["*.g.alchemy.com"], "unit": "cu", "month": 30_000_000, "pct": 80.0, "cu": 26, "cu_heavy": 26,
                    "cu_methods": {"alchemy_getTokenBalances": 20, "eth_getLogs": 60, "eth_call": 26, "eth_getBalance": 20}}
DS_MIN_RESERVE = 10000.0
_SEED = {"d": None}
_LOCK = threading.Lock()


class SourceFail(RuntimeError):
    def __init__(self, kind: str, msg: str = ""):
        super().__init__(f"{kind}: {msg}" if msg else kind)
        self.kind = kind


def sources_table(base: str = None) -> dict:
    if base is None and _SEED["d"] is not None:
        return _SEED["d"]
    d = common.seed_json(SEED_NAME, {}, base_dir=base) or {}
    d = d if isinstance(d, dict) else {}
    if base is None:
        _SEED["d"] = d
    return d


def chain_row(chain: str) -> dict:
    r = (sources_table().get("chains") or {}).get(chain)
    return r if isinstance(r, dict) else {}


def _env() -> dict:
    out = {}
    try:
        out = dict(common.read_env_file())
    except Exception:
        out = {}
    for k in (ENV_ALCHEMY, ENV_ANKR, ENV_ES):
        if os.environ.get(k):
            out[k] = os.environ[k]
    return out


def alchemy_net(chain: str):
    try:
        import chaincatalog
        f_tok = getattr(chaincatalog, "alchemy_tokens", None)
        if callable(f_tok) and not f_tok(chain):
            return None
        f_net = getattr(chaincatalog, "alchemy_network", None)
        n = f_net(chain) if callable(f_net) else None
        n = n or (chaincatalog.CATALOG.get(chain) or {}).get("alchemy")
        if n:
            return str(n)
    except Exception:
        pass
    return chain_row(chain).get("alchemy") or None


def alchemy_url(chain: str, env: dict = None):
    net = alchemy_net(chain)
    if not net:
        return None
    if env is None:
        try:
            import nodekeys
            f = getattr(nodekeys, "alchemy_url", None)
            if callable(f):
                u = f(net)
                return u or None
        except Exception:
            pass
        env = _env()
    k = str(env.get(ENV_ALCHEMY) or "").strip()
    return f"https://{net}.g.alchemy.com/v2/{k}" if KEY_RE.match(k) else None


def ankr_url(env: dict = None):
    if env is None:
        try:
            import nodekeys
            f = getattr(nodekeys, "ankr_multichain_url", None)
            if callable(f):
                u = f()
                return u or None
        except Exception:
            pass
        env = _env()
    k = str(env.get(ENV_ANKR) or "").strip()
    return f"https://rpc.ankr.com/multichain/{k}" if KEY_RE.match(k) else None


def es_key(env: dict = None):
    k = str((env if env is not None else _env()).get(ENV_ES) or "").strip()
    return k or None


def _cc(cfg: dict, chain: str) -> dict:
    cc = ((cfg or {}).get("chains") or {}).get(chain)
    return cc if isinstance(cc, dict) else {}


def blockscout_base(chain: str, cfg: dict = None):
    row = chain_row(chain)
    v = row.get("blockscout") if row else None
    if v == "blocked":
        return None
    if isinstance(v, str) and v.startswith("https://"):
        return v.rstrip("/")
    cc = _cc(cfg, chain)
    if cc.get("blockscout") and not common.bs_blocked(chain, cc) and common.chain_discovery(chain, cc) != "rpc":
        return str(cc["blockscout"]).rstrip("/")
    return None


def plan(chain: str, cfg: dict = None, env: dict = None, logs: bool = True) -> list:
    row = chain_row(chain)
    env = _env() if env is None else env
    out = []
    if row.get("etherscan") == "free" and es_key(env):
        out.append("etherscan")
    if row.get("routescan"):
        out.append("routescan")
    if blockscout_base(chain, cfg):
        out.append("blockscout")
    if alchemy_net(chain) and alchemy_url(chain, env):
        out.append("alchemy")
    if row.get("ankr") and ankr_url(env):
        out.append("ankr")
    out.append("rabby")
    cc = _cc(cfg, chain)
    if logs and chain != "bsc" and logs_span(chain, cfg) and (cc.get("rpc_logs") or cc.get("rpcs")):
        out.append("logs")
    return out


def old_status(chain: str, cfg: dict = None, env: dict = None) -> str:
    p = [s for s in plan(chain, cfg, env) if s in INDEX_SOURCES]
    if any(s in ("etherscan", "routescan", "blockscout") for s in p):
        return "free"
    if p:
        return "key"
    row = chain_row(chain)
    if row.get("old") == "key":
        return "nokey"
    if logs_span(chain, cfg):
        return "slow"
    return "none"


def logs_span(chain: str, cfg: dict = None):
    cc = _cc(cfg, chain)
    sp = None
    try:
        sp = ((common.read_json(common.BACKFILL_SPEED_PATH, {}) or {}).get("chains") or {}).get(chain, {}).get("getLogsSpan")
    except (Exception, SystemExit):
        sp = None
    best = None
    for v in (cc.get("getlogs_span"), sp, chain_row(chain).get("logs_span")):
        try:
            if v and int(v) > 0:
                best = max(best or 0, int(v))
        except (TypeError, ValueError):
            continue
    return best


def state_path(state_dir: str = None) -> str:
    return os.path.join(state_dir or common.STATE_DIR, STATE_NAME)


def load_state(state_dir: str = None) -> dict:
    try:
        with open(state_path(state_dir), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def update_state(fn, state_dir: str = None) -> dict:
    p = state_path(state_dir)
    with _LOCK, open(p + ".lock", "a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        cur = load_state(state_dir)
        cur.setdefault("v", SCHEMA)
        cur.setdefault("pairs", {})
        new = fn(cur) or cur
        new["updatedAt"] = int(time.time())
        common.atomic_write_json(p, new)
        return new


def pair_key(chain: str, wallet: str) -> str:
    return f"{chain}:{str(wallet).lower()}"


def entry(chain: str, wallet: str, state: dict = None) -> dict:
    st = load_state() if state is None else state
    e = (st.get("pairs") or {}).get(pair_key(chain, wallet))
    return e if isinstance(e, dict) else {}


def need_refresh(ent: dict, sig: dict, now: float = None, srcs=None) -> tuple:
    now = time.time() if now is None else now
    if not ent or not ent.get("at"):
        return True, "first"
    old = ent.get("sig") if isinstance(ent.get("sig"), dict) else {}
    for k, v in (sig or {}).items():
        if k in old and v is not None and old.get(k) is not None and str(old.get(k)) != str(v):
            return True, f"changed:{k}"
    fail = ent.get("fail") if isinstance(ent.get("fail"), dict) else {}
    soft = {s9 for s9, v in fail.items() if str(v).split(":")[0] not in FINAL_FAIL}
    if soft and now - float(ent.get("at") or 0) >= RETRY_FAIL_SEC:
        return True, "retry"
    done = set((ent.get("ok") or {}).keys()) | set(fail.keys())
    for s in srcs or ():
        if s in INDEX_SOURCES and s not in done:
            return True, f"new:{s}"
    return False, "cache"


def _clean(msg: str, env: dict = None) -> str:
    t = common.redact_secret_text(common.redact_urls(str(msg or "")))
    for v in (env if env is not None else _env()).values():
        v = str(v or "")
        if len(v) >= 8:
            t = t.replace(v, "<KEY>")
    return t[:140]


def _add(out: dict, meta: dict, ca, src: str, sym=None, dec=None, **kw):
    ca = str(ca or "").lower()
    if not CA_RE.match(ca) or ca == "0x" + "0" * 40:
        return
    if ca not in out and len(out) >= MAX_CAS:
        return
    out.setdefault(ca, set()).add(src)
    m = meta.setdefault(ca, {})
    if sym and not m.get("sym"):
        m["sym"] = str(sym)[:40]
    if dec is not None and m.get("dec") is None:
        try:
            d9 = int(dec)
            if 0 <= d9 <= 77:
                m["dec"] = d9
        except (TypeError, ValueError):
            pass
    for k, v in kw.items():
        if v is not None:
            m[k] = v


def _http(url: str, **kw):
    import bf_engine
    try:
        return bf_engine.http_json(url, **kw)
    except bf_engine.NetError as e:
        k = "quota" if e.kind in ("quota", "budget") else ("http" if str(e.kind).startswith("http") else "net")
        raise SourceFail(k, common.redact_urls(str(e))[:120]) from e


def _es_like(base_url: str, params: dict, upto, out: dict, meta: dict, src: str, budget: bool, sleep) -> int:
    import bf_engine
    start, calls = 0, 0
    for _p in range(ES_PAGES):
        q = dict(params, module="account", action="tokentx", startblock=start, page=1, offset=10000, sort="asc")
        if upto:
            q["endblock"] = int(upto)
        if budget:
            try:
                import evm_watch
                if evm_watch.es_daily_left() > 0:
                    raise SourceFail("quota", "이더스캔 하루 한도 쉼 창")
            except ImportError:
                pass
            if not bf_engine.es_budget_take("disc", kind="aux"):
                raise SourceFail("quota", f"이더스캔 하루 예산({bf_engine.es_budget_why()})")
        calls += 1
        d = _http(base_url + "?" + urllib.parse.urlencode(q), retries=1)
        if not isinstance(d, dict):
            raise SourceFail("error", "응답 형식")
        res = d.get("result")
        if str(d.get("status")) == "0":
            msg = f"{d.get('message')} {res if isinstance(res, str) else ''}"
            if "no transactions found" in msg.lower() or "no records found" in msg.lower():
                return calls
            low = msg.lower()
            if "not supported" in low or "upgrade your api plan" in low or "unsupported chainid" in low or "chain not supported" in low:
                raise SourceFail("unsupported", msg[:80])
            if "day/limit" in low or ("daily" in low and "limit" in low):
                if budget:
                    try:
                        import evm_watch
                        evm_watch.es_daily_trip(msg)
                    except ImportError:
                        pass
                raise SourceFail("quota", msg[:80])
            if "api key" in low:
                raise SourceFail("key", "키 거부")
            raise SourceFail("error", common.redact_urls(msg)[:80])
        if not isinstance(res, list):
            raise SourceFail("error", "result 형식")
        last = start
        for r in res:
            if not isinstance(r, dict):
                continue
            _add(out, meta, r.get("contractAddress"), src, r.get("tokenSymbol"), r.get("tokenDecimal"))
            try:
                last = max(last, int(r.get("blockNumber") or 0))
            except (TypeError, ValueError):
                pass
        if len(res) < 10000:
            return calls
        if last <= start:
            raise SourceFail("partial", "한 블록에 1만 줄 넘음")
        start = last
        sleep(0.5)
    raise SourceFail("partial", f"{ES_PAGES}쪽 상한")


def src_etherscan(chain: str, wallet: str, upto=None, env=None, sleep=time.sleep, out=None, meta=None) -> int:
    cid = chain_row(chain).get("chain_id")
    k = es_key(env)
    if not cid or not k:
        raise SourceFail("nokey" if not k else "unsupported")
    return _es_like("https://api.etherscan.io/v2/api", {"chainid": int(cid), "address": wallet, "apikey": k}, upto, out, meta,
                    "etherscan", True, sleep)


def src_routescan(chain: str, wallet: str, upto=None, sleep=time.sleep, out=None, meta=None) -> int:
    cid = chain_row(chain).get("chain_id")
    if not cid:
        raise SourceFail("unsupported")
    return _es_like(f"https://api.routescan.io/v2/network/mainnet/evm/{int(cid)}/etherscan/api", {"address": wallet}, upto, out, meta,
                    "routescan", False, sleep)


def src_blockscout(base: str, wallet: str, sleep=time.sleep, out=None, meta=None) -> int:
    calls, nxt = 0, None
    for _p in range(BS_PAGES):
        q = {"type": "ERC-20"}
        if nxt:
            q.update({k: v for k, v in nxt.items() if v is not None})
        calls += 1
        d = _http(f"{base}/api/v2/addresses/{wallet}/token-transfers?" + urllib.parse.urlencode(q), retries=3)
        if not isinstance(d, dict) or not isinstance(d.get("items"), list):
            raise SourceFail("error", "token-transfers 형식")
        for it in d["items"]:
            tok = (it or {}).get("token") or {}
            if (tok.get("type") or "ERC-20") != "ERC-20":
                continue
            _add(out, meta, tok.get("address_hash") or tok.get("address"), "blockscout", tok.get("symbol"), tok.get("decimals"))
        nxt = d.get("next_page_params") if isinstance(d.get("next_page_params"), dict) else None
        if not nxt:
            return calls
        sleep(0.5)
    calls += 1
    d = _http(f"{base}/api/v2/addresses/{wallet}/token-balances", retries=3)
    for it in d if isinstance(d, list) else []:
        tok = (it or {}).get("token") or {}
        if (tok.get("type") or "ERC-20") == "ERC-20":
            _add(out, meta, tok.get("address_hash") or tok.get("address"), "blockscout", tok.get("symbol"), tok.get("decimals"))
    raise SourceFail("partial", f"전송 {BS_PAGES * 50}줄 상한 — 지금 보유 목록으로 보탬")


def _ensure_ledger(host: str, fallback: dict = None, method_cu=None) -> bool:
    import bf_engine
    try:
        bf_engine._rpc_cfg_ensure()
    except Exception:
        pass
    name = bf_engine._rpc_day_of(host)
    if name:
        if method_cu:
            with bf_engine._RPC_DAY_LOCK:
                ent = bf_engine._RPC_DAY.get(name)
                if ent is not None and (ent["spec"].get("unit") == "cu"):
                    cm = ent["spec"].get("cu_methods") if isinstance(ent["spec"].get("cu_methods"), dict) else {}
                    if method_cu[0] not in cm:
                        ent["spec"]["cu_methods"] = dict(cm, **{method_cu[0]: int(method_cu[1])})
        return True
    if not fallback:
        return False
    try:
        cfg = common.load_config()
    except (Exception, SystemExit):
        cfg = {}
    lim = dict(cfg.get("rpc_day_limits") or {}) if isinstance(cfg.get("rpc_day_limits"), dict) else {}
    lim.setdefault("node_alchemy", dict(fallback))
    cfg["rpc_day_limits"] = lim
    bf_engine.rpc_day_configure(cfg)
    return bool(bf_engine._rpc_day_of(host))


def _rpc_json(url: str, body: dict):
    import bf_engine
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    try:
        return bf_engine.rpc_post(url, body, retries=1)
    except (bf_engine.NetError, getattr(bf_engine, "RpcTransportError", bf_engine.NetError)) as e:
        kd = str(getattr(e, "kind", "") or "")
        k = "quota" if kd in ("quota", "budget") else ("http" if kd.startswith("http") else "net")
        raise SourceFail(k, common.redact_secret_text(common.redact_urls(str(e)))[:120].replace(host, "<host>")) from e


def src_alchemy(chain: str, wallet: str, url: str, sleep=time.sleep, out=None, meta=None) -> int:
    if not url:
        raise SourceFail("nokey")
    if not _ensure_ledger((urllib.parse.urlsplit(url).hostname or "").lower(), ALCHEMY_FALLBACK):
        raise SourceFail("quota", "Alchemy 하루 장부 없음 — 호출 안 함")
    calls, pk = 0, None
    for _p in range(AL_PAGES):
        prm = [wallet, "erc20"] + ([{"pageKey": pk}] if pk else [])
        calls += 1
        d = _rpc_json(url, {"jsonrpc": "2.0", "id": 1, "method": "alchemy_getTokenBalances", "params": prm})
        if not isinstance(d, dict):
            raise SourceFail("error", "응답 형식")
        if d.get("error"):
            msg = str((d.get("error") or {}).get("message") if isinstance(d.get("error"), dict) else d.get("error"))
            low = msg.lower()
            raise SourceFail("unsupported" if ("not enabled" in low or "unsupported" in low) else
                             ("quota" if ("limit" in low or "capacity" in low or "exceeded" in low) else "error"), msg[:80])
        r = d.get("result") if isinstance(d.get("result"), dict) else None
        if r is None or not isinstance(r.get("tokenBalances"), list):
            raise SourceFail("error", "result 형식")
        for t in r["tokenBalances"]:
            if not isinstance(t, dict):
                continue
            nz = None
            try:
                nz = int(str(t.get("tokenBalance") or "0x0"), 16) > 0
            except (TypeError, ValueError):
                nz = None
            ca = str(t.get("contractAddress") or "").lower()
            _add(out, meta, ca, "alchemy")
            if ca in meta and nz is not None:
                meta[ca]["alnz"] = bool(meta[ca].get("alnz")) or nz
        pk = r.get("pageKey")
        if not pk:
            return calls
        sleep(0.2)
    raise SourceFail("partial", f"{AL_PAGES * 100}개 상한")


def src_ankr(chain: str, wallet: str, url: str, sleep=time.sleep, out=None, meta=None) -> int:
    name = chain_row(chain).get("ankr")
    if not url:
        raise SourceFail("nokey")
    if not name:
        raise SourceFail("unsupported")
    if not _ensure_ledger("rpc.ankr.com", method_cu=("ankr_getAccountBalance", ANKR_ADV_CREDITS)):
        raise SourceFail("quota", "Ankr 하루 장부 없음 — 호출 안 함")
    calls, tok = 0, None
    for _p in range(AN_PAGES):
        prm = {"blockchain": [name], "walletAddress": wallet, "onlyWhitelisted": True}
        if tok:
            prm["pageToken"] = tok
        calls += 1
        d = _rpc_json(url, {"jsonrpc": "2.0", "id": 1, "method": "ankr_getAccountBalance", "params": prm})
        if not isinstance(d, dict):
            raise SourceFail("error", "응답 형식")
        if d.get("error"):
            msg = str((d.get("error") or {}).get("message") if isinstance(d.get("error"), dict) else d.get("error"))
            raise SourceFail("unsupported" if "invalid blockchain" in msg.lower() else "error", msg[:80])
        r = d.get("result") if isinstance(d.get("result"), dict) else None
        if r is None or not isinstance(r.get("assets"), list):
            raise SourceFail("error", "result 형식")
        for a in r["assets"]:
            if not isinstance(a, dict) or str(a.get("tokenType") or "").upper() != "ERC20":
                continue
            px = None
            try:
                px = float(a.get("tokenPrice") or 0) or None
            except (TypeError, ValueError):
                px = None
            _add(out, meta, a.get("contractAddress"), "ankr", a.get("tokenSymbol"), a.get("tokenDecimals"), wl=True, px=px)
        tok = r.get("nextPageToken")
        if not tok:
            return calls
        sleep(0.3)
    raise SourceFail("partial", f"{AN_PAGES}쪽 상한")


def src_rabby(chain: str, wallet: str, cfg: dict = None, out=None, meta=None) -> int:
    try:
        import rabby
        st = rabby.load_state(os.path.join(common.STATE_DIR, rabby.STATE_NAME))
        res = rabby.chain_resolver(cfg or {}, st)
    except Exception:
        return 0
    w = ((st.get("wallets") or {}).get(str(wallet).lower()) or (st.get("wallets") or {}).get(wallet) or {})
    toks = list(w.get("tokens") or [])
    for p in w.get("protocols") or []:
        for it in (p or {}).get("items") or []:
            toks += list((it or {}).get("assets") or [])
    for t in toks:
        if not isinstance(t, dict) or res(t.get("chain")) != chain:
            continue
        ok = bool(t.get("v") or t.get("c")) and not (t.get("scam") or t.get("sus"))
        bad = bool(t.get("scam") or t.get("sus"))
        _add(out, meta, t.get("id"), "rabby", t.get("sym"), None, rb=ok or None, rbscam=bad or None,
             px=(float(t.get("px")) if isinstance(t.get("px"), (int, float)) and t.get("px") > 0 else None))
    return 0


def src_logs(chain: str, wallet: str, cfg: dict = None, upto=None, max_calls: int = LOGS_MAX_CALLS, rpcs=None, sleep=time.sleep,
             out=None, meta=None, deadline: float = None) -> int:
    import recon
    span = logs_span(chain, cfg)
    cc = _cc(cfg, chain)
    urls = list(rpcs or cc.get("rpc_logs") or cc.get("rpcs") or [])
    if not urls:
        try:
            from evm_watch import RpcSynthMixin
            urls = list(RpcSynthMixin.RPC_DEFAULT.get(chain) or [])
        except Exception:
            urls = []
    if not span or not urls:
        raise SourceFail("unsupported", "로그 구간·RPC 모름")
    head = int(upto) if upto else recon._rpc_any(urls, "eth_blockNumber", [], check=recon._hex_int, sleep=sleep)
    try:
        lo = max(0, int(cc.get("start_block") or 0))
    except (TypeError, ValueError):
        lo = 0
    est = 2 * (-(-(head - lo + 1) // span))
    if est > max_calls:
        raise SourceFail("slow", f"예상 {est:,}콜 > 상한 {max_calls:,}")
    me = "0x" + str(wallet).lower().replace("0x", "").rjust(64, "0")
    calls = 0
    for topics in ([TRANSFER_T0, me], [TRANSFER_T0, None, me]):
        a, sp = lo, span
        while a <= head:
            if deadline is not None and time.time() > deadline:
                raise SourceFail("partial", "시간 상한")
            b = min(head, a + sp - 1)
            calls += 1
            if calls > max_calls * 2:
                raise SourceFail("slow", "구간 줄이다 상한")
            try:
                logs = recon._rpc_any(urls, "eth_getLogs", [{"fromBlock": hex(a), "toBlock": hex(b), "topics": topics}], tries=2, sleep=sleep)
            except Exception as e:
                low = str(e).lower()
                if sp > 100 and any(x in low for x in ("range", "limit", "too many", "exceed", "10000", "block range", "query returned")):
                    sp = max(100, sp // 2)
                    continue
                raise SourceFail("net", common.redact_urls(str(e))[:100]) from e
            for lg in logs if isinstance(logs, list) else []:
                if isinstance(lg, dict) and len(lg.get("topics") or []) == 3:
                    _add(out, meta, lg.get("address"), "logs")
            a = b + 1
    return calls


def discover(chain: str, wallet: str, *, upto=None, cfg: dict = None, env: dict = None, sources=None, logs_max_calls: int = LOGS_MAX_CALLS,
             sleep=time.sleep, deadline: float = None, burst: bool = False) -> dict:
    import contextlib
    cm = None
    if burst:
        try:
            import bf_engine
            cm = getattr(bf_engine, "ledger_burst", None)
        except Exception:
            cm = None
    with (cm() if callable(cm) else contextlib.nullcontext()):
        return _discover(chain, wallet, upto=upto, cfg=cfg, env=env, sources=sources, logs_max_calls=logs_max_calls, sleep=sleep, deadline=deadline)


def _discover(chain: str, wallet: str, *, upto=None, cfg: dict = None, env: dict = None, sources=None, logs_max_calls: int = LOGS_MAX_CALLS,
              sleep=time.sleep, deadline: float = None) -> dict:
    env = _env() if env is None else env
    srcs = list(sources) if sources is not None else plan(chain, cfg, env)
    cas, meta, ok, fail, calls = {}, {}, {}, {}, {}
    w = str(wallet).lower()
    for s in srcs:
        if s == "logs":
            continue
        one = {}
        try:
            if s == "etherscan":
                n = src_etherscan(chain, w, upto, env, sleep, one, meta)
            elif s == "routescan":
                n = src_routescan(chain, w, upto, sleep, one, meta)
            elif s == "blockscout":
                b = blockscout_base(chain, cfg)
                if not b:
                    raise SourceFail("unsupported")
                n = src_blockscout(b, w, sleep, one, meta)
            elif s == "alchemy":
                n = src_alchemy(chain, w, alchemy_url(chain, env), sleep, one, meta)
            elif s == "ankr":
                n = src_ankr(chain, w, ankr_url(env), sleep, one, meta)
            elif s == "rabby":
                n = src_rabby(chain, w, cfg, one, meta)
            else:
                continue
            calls[s] = n
            ok[s] = len(one)
        except SourceFail as e:
            fail[s] = _clean(f"{e.kind}: {str(e)[len(e.kind) + 2:]}")
            if e.kind == "partial":
                ok[s] = len(one)
        except Exception as e:
            fail[s] = _clean("error: " + common.safe_err(e))
        for ca, ss in one.items():
            cas.setdefault(ca, set()).update(ss)
    if "logs" in srcs and not any(s in ok for s in INDEX_SOURCES):
        one = {}
        try:
            calls["logs"] = src_logs(chain, w, cfg, upto, logs_max_calls, sleep=sleep, out=one, meta=meta, deadline=deadline)
            ok["logs"] = len(one)
        except SourceFail as e:
            fail["logs"] = _clean(f"{e.kind}: {str(e)[len(e.kind) + 2:]}")
        except Exception as e:
            fail["logs"] = _clean("error: " + common.safe_err(e))
        for ca, ss in one.items():
            cas.setdefault(ca, set()).update(ss)
    return {"cas": {k: sorted(v) for k, v in cas.items()}, "meta": {k: v for k, v in meta.items() if k in cas},
            "ok": ok, "fail": fail, "calls": calls}


def scam_name(sym) -> str:
    import spamguard
    s = str(sym or "")
    if not s.strip():
        return ""
    if spamguard.impostor_of(s) or spamguard.odd_symbol(s):
        return "사칭 문자"
    if spamguard._TAIL_LURE.search(s):
        return "링크·보상 유도 이름"
    return ""


def static_credible(chain: str, ca: str, srcs, m: dict, strict=None, confirmed=frozenset()):
    import spamguard
    ca = str(ca).lower()
    m = m or {}
    try:
        if strict is not None and strict(ca):
            return True, "정품 목록"
    except Exception:
        pass
    sym = m.get("sym")
    why = scam_name(sym)
    if not why and sym and spamguard.fake_major(sym, [(chain, ca)]):
        why = "대표 심볼 흉내(정품 주소 아님)"
    if why:
        return False, why
    if ca in confirmed:
        return True, "원장 스왑 확인"
    if m.get("rbscam"):
        return False, "Rabby 스캠·의심"
    if m.get("wl") or "ankr" in (srcs or ()):
        return True, "Ankr 정품 목록"
    if m.get("rb"):
        return True, "Rabby 검증"
    return None, ""


def dex_check(chain: str, cas: list, min_reserve: float = DS_MIN_RESERVE, sleep=time.sleep, retries: int = 2) -> dict:
    import pricing
    net = pricing.DS_CHAIN.get(chain)
    out = {}
    if not net:
        return out
    lst = sorted({str(c).lower() for c in cas})
    for i in range(0, len(lst), 30):
        batch = lst[i:i + 30]
        try:
            d = _http(f"https://api.dexscreener.com/tokens/v1/{net}/{','.join(batch)}", retries=retries)
        except SourceFail:
            continue
        if isinstance(d, dict):
            d = d.get("pairs") or []
        if not isinstance(d, list):
            continue
        res, best, sym = {}, {}, {}
        for pr in d:
            if not isinstance(pr, dict) or (pr.get("chainId") and pr.get("chainId") != net):
                continue
            try:
                liq = float(((pr.get("liquidity") or {}).get("usd")) or 0)
            except (TypeError, ValueError, AttributeError):
                liq = 0.0
            for side in ("baseToken", "quoteToken"):
                a = str(((pr.get(side) or {}).get("address")) or "").lower()
                if a not in batch:
                    continue
                res[a] = res.get(a, 0.0) + liq
                sym.setdefault(a, (pr.get(side) or {}).get("symbol"))
                if side == "baseToken":
                    try:
                        px = float(pr.get("priceUsd") or 0)
                    except (TypeError, ValueError):
                        px = 0.0
                    if px > 0 and (a not in best or liq > best[a][0]):
                        best[a] = (liq, px)
        for a in batch:
            if a in res:
                out[a] = (res[a] >= float(min_reserve), res[a], best.get(a, (0, None))[1], sym.get(a))
            else:
                out[a] = (False, 0.0, None, None)
        sleep(0.5)
    return out


_DEX_IMPL = dex_check


def ledger_genuine(conn, chain: str, strict=None) -> set:
    import pricing
    import spamguard
    out = set()
    for r in conn.execute("SELECT address FROM assets WHERE chain=? AND kind='token' AND confirmed=1 AND address IS NOT NULL", (chain,)).fetchall():
        a = str(r[0]).lower()
        if CA_RE.match(a):
            out.add(a)
    for tab in (pricing.STABLE_CAS, pricing.JPY_STABLE_CAS, spamguard.GENUINE_CAS):
        out |= {str(k).lower() for k in (tab.get(chain) or {}) if CA_RE.match(str(k).lower())}
    return out


def confirmed_cas(conn, chain: str) -> set:
    return {str(r[0]).lower() for r in conn.execute(
        "SELECT address FROM assets WHERE chain=? AND kind='token' AND confirmed=1 AND address IS NOT NULL", (chain,)).fetchall()}


def wallet_sig(conn, chain: str, wallet: str) -> dict:
    r = conn.execute("SELECT count(*), max(event_ts) FROM postings WHERE location=? AND source_kind='chain_tx'",
                     (f"wallet:{chain}:{str(wallet).lower()}",)).fetchone()
    return {"txn": int(r[0] or 0), "txts": int(r[1] or 0)}


def recon_prep(conn, cfg: dict, chain: str, wallets: list, strict=None, kind: str = "evm", enabled: bool = True) -> dict:
    if not enabled:
        return {"chain": chain, "off": True}
    conf = confirmed_cas(conn, chain)
    gen = ledger_genuine(conn, chain)
    sigs = {str(w).lower(): wallet_sig(conn, chain, w) for w in wallets}
    st = load_state()
    ents = {str(w).lower(): entry(chain, w, st) for w in wallets}
    try:
        pg = (cfg or {}).get("price_guard") or {}
        mr = float(pg.get("min_reserve_usd", DS_MIN_RESERVE))
    except (TypeError, ValueError):
        mr = DS_MIN_RESERVE
    return {"chain": chain, "kind": kind, "cfg": {"chains": {chain: dict(_cc(cfg, chain))}}, "confirmed": conf, "genuine": gen,
            "sigs": sigs, "ents": ents, "strict": strict, "min_reserve": mr, "off": False}


def recon_extra(prep: dict, upto=None, sleep=time.sleep, deadline: float = None, discover_fn=None) -> dict:
    out = {"extra": {}, "meta": {}, "src": {}, "status": {}, "fail": {}, "ok": {}}
    if not prep or prep.get("off"):
        return out
    chain = prep["chain"]
    cfg = prep.get("cfg") or {}
    env = _env()
    srcs = plan(chain, cfg, env)
    dl = deadline if deadline is not None else time.time() + JOB_MAX_SEC
    dfn = discover_fn or discover
    for w, sig in (prep.get("sigs") or {}).items():
        ent = (prep.get("ents") or {}).get(w) or {}
        need, why = need_refresh(ent, sig, srcs=srcs)
        if need and time.time() > dl:
            out["status"][w] = "pending"
            continue
        if need:
            r = dfn(chain, w, upto=upto, cfg=cfg, env=env, sources=srcs, sleep=sleep, deadline=dl, burst=(why == "first"))
            save_result(chain, w, r, sig, why)
            cas, meta, fail, ok9 = r["cas"], r["meta"], r["fail"], r.get("ok") or {}
            out["status"][w] = "ok" if any(s9 in INDEX_SOURCES or s9 == "logs" for s9 in ok9) else "fail"
        else:
            cas, meta, fail, ok9 = ent.get("cas") or {}, ent.get("meta") or {}, ent.get("fail") or {}, ent.get("ok") or {}
            out["status"][w] = "cache"
        out["ok"][w] = dict(ok9)
        src9 = {ca: list(ss) for ca, ss in cas.items()}
        for ca in prep.get("genuine") or ():
            src9.setdefault(ca, [])
            if "ledger" not in src9[ca]:
                src9[ca] = list(src9[ca]) + ["ledger"]
        def rank(ca, src9=src9, meta=meta):
            m = meta.get(ca) or {}
            ss = src9.get(ca) or []
            return (0 if "ledger" in ss else 1 if ("ankr" in ss or m.get("rb")) else 2 if m.get("alnz") else 3, ca)
        cand = []
        for ca, ss in src9.items():
            m = meta.get(ca) or {}
            if m.get("rbscam") and set(ss) <= {"rabby"}:
                continue
            cand.append(ca)
        cand.sort(key=rank)
        out["extra"][w] = set(cand[:MAX_QUERY])
        out["src"][w] = {ca: src9[ca] for ca in out["extra"][w]}
        for ca in out["extra"][w]:
            if ca in meta:
                out["meta"].setdefault(ca, dict(meta[ca]))
        if fail:
            out["fail"][w] = dict(fail)
    return out


def recon_extra_safe(prep: dict, upto=None, **kw) -> dict:
    try:
        return recon_extra(prep, upto=upto, **kw)
    except Exception as e:
        import logging
        logging.getLogger("tj-core").warning("토큰 발견 실패(종전 목록으로 대사): %s", common.safe_err(e)[:160])
        return {"extra": {}, "meta": {}, "src": {}, "status": {}, "fail": {"*": {"disc": "error"}}}


def bsc_fetch(rpcs: list, wallets: list, cas_all: dict, own: dict, prep: dict, fetch=None) -> dict:
    import recon
    fetch = fetch or recon.fetch_bsc_balances
    ext = recon_extra_safe(prep)
    per, meta, zero, xonly, pre = {}, {}, {}, {}, {}
    decs = dict(((load_state().get("dec") or {}).get("bsc") or {}))
    new_dec = {}
    for w in wallets:
        wl = str(w).lower()
        own9 = {c for c in (own.get(wl) or ())}
        ex9 = set((ext.get("extra") or {}).get(wl) or ())
        indexed = any(s in INDEX_SOURCES for s in _ok_sources(ext, wl))
        want = own9 | ex9 | (set() if indexed else {str(c).lower() for c in cas_all})
        cw = {}
        for ca in sorted(want):
            if ca in cas_all:
                cw[ca] = cas_all[ca]
            else:
                m = (ext.get("meta") or {}).get(ca) or {}
                cw[ca] = (m.get("sym"), m.get("dec"))
        r = fetch(rpcs, [w], cw)
        for (k9, ca9), v9 in list((((r or {}).get("per_wallet") or {}).get(w) or {}).items()):
            if k9 != "token" or not v9 or ca9 in cas_all or (cw.get(ca9) or (None, None))[1] is not None:
                continue
            d9 = decs.get(ca9)
            if d9 is None:
                d9 = _decimals(rpcs, ca9)
                if isinstance(d9, int):
                    decs[ca9] = new_dec[ca9] = d9
            if not isinstance(d9, int):
                r["per_wallet"][w].pop((k9, ca9), None)
                pre.setdefault(wl, {})[ca9] = ("일시 보류 — 소수 조회 실패(전송·한도)" if d9 == "transient" else "소수(decimals) 모름 — 앵커 안 함")
            else:
                (r.setdefault("_meta", {}))[ca9] = ((cw.get(ca9) or (None, None))[0], d9)
        per.update((r or {}).get("per_wallet") or {})
        for ca9, m9 in ((r or {}).get("_meta") or {}).items():
            old9 = meta.get(ca9)
            if isinstance(old9, tuple) and len(old9) == 2 and old9[1] is not None and isinstance(m9, tuple) and len(m9) == 2 and m9[1] is None:
                meta[ca9] = (m9[0] or old9[0], old9[1])
            else:
                meta[ca9] = m9
        for k, v in ((r or {}).get("_zero") or {}).items():
            zero[k] = list(v)
        xo = sorted(set(cw) - own9)
        if xo:
            xonly[w] = xo
    bal = {"per_wallet": per, "_meta": meta, "_zero": zero}
    if xonly:
        bal["_extra_only"] = xonly
    if pre:
        bal["_disc_pre_skip"] = pre
    if new_dec:
        def _fn(cur, new_dec=new_dec):
            d9 = cur.setdefault("dec", {}).setdefault("bsc", {})
            d9.update(new_dec)
            if len(d9) > 5000:
                cur["dec"]["bsc"] = dict(list(d9.items())[-5000:])
            return cur
        try:
            update_state(_fn)
        except OSError:
            pass
    return filter_result(bal, prep, ext)


def _decimals(rpcs: list, ca: str):
    import recon
    try:
        r = recon._rpc_any(list(rpcs), "eth_call", [{"to": ca, "data": "0x313ce567"}, "latest"], tries=2)
    except recon.RpcExecFail:
        return None
    except Exception:
        return "transient"
    if not isinstance(r, str) or not r.startswith("0x") or len(r) != 66:
        return None
    d = int(r, 16)
    return d if 0 <= d <= 77 else None


TRANSIENT_SKIP = ("일시 보류",)


def skip_final(reason) -> bool:
    return not any(str(reason or "").startswith(t) for t in TRANSIENT_SKIP)


def rejudge_hold(chain: str, wallet: str, items: list, min_reserve: float = DS_MIN_RESERVE, budget: list = None,
                 now: float = None, dex=None) -> list:
    import pricing
    import spamguard
    now = time.time() if now is None else float(now)
    its = []
    for ca, ss, m in items:
        m = dict(m or {})
        stale = bool(m.pop("_stale", False))
        if stale:
            m.pop("px", None)
        its.append((ca, ss, m, stale))
    due = [ca for ca, _s, m, _st in its if now - float(m.get("dexAt") or 0) >= HOLD_RETRY_SEC]
    if budget is not None and budget[0] <= 0:
        due = []
    if not due and not any(st9 for _c, _s, _m, st9 in its):
        return [(ca, ss, m) for ca, ss, m, _st in its]
    ds_ok = chain in pricing.DS_CHAIN
    got = {}
    if ds_ok and due:
        fn = dex or dex_check
        kw = {"retries": 1} if fn is _DEX_IMPL else {}
        tried = []
        for i9 in range(0, len(due), 30):
            if budget is not None and budget[0] <= 0:
                break
            part = due[i9:i9 + 30]
            if budget is not None:
                budget[0] -= 1
            tried += part
            try:
                g9 = fn(chain, part, min_reserve, **kw) or {}
            except Exception:
                g9 = {}
            got.update(g9)
            if not g9:
                if budget is not None:
                    budget[0] = 0
                break
        due = tried
    res, out = {}, []
    for ca, ss, m, stale in its:
        if ca not in due:
            if stale:
                res[ca] = ({}, "일시 보류 — 시세 갱신 대기", True)
            out.append((ca, ss, m))
            continue
        upd = {"dexAt": int(now)}
        g = got.get(ca)
        ok, why = static_credible(chain, ca, ss, m)
        syms = [x for x in (m.get("sym"), g[3] if g and len(g) > 3 else None) if x and str(x).strip()]
        bad = why if ok is False else ""
        for sy in syms:
            bad = bad or scam_name(sy) or ("대표 심볼 흉내(정품 주소 아님)" if spamguard.fake_major(sy, [(chain, ca)]) else "")
        if bad:
            sk = bad
        elif ok:
            sk = None
        elif not ds_ok:
            sk = "판정 불가 체인(덱스 미지원) — 정품 목록 밖이라 앵커 안 함"
        elif g is None:
            sk = False
        elif not syms:
            sk = "심볼 모름 — 앵커 안 함"
        elif g[0]:
            sk = None
        else:
            sk = "유동성 부족 — 스팸 의심"
        if g and sk is None:
            try:
                px9 = float(g[2] or 0)
            except (TypeError, ValueError):
                px9 = 0.0
            if 0 < px9 < float("inf"):
                upd["px"] = px9
            if syms and not m.get("sym"):
                upd["sym"] = str(syms[0])
        m.update(upd)
        if sk is None:
            try:
                px8 = float(m.get("px") or 0)
            except (TypeError, ValueError):
                px8 = 0.0
            if not (0 < px8 < float("inf")):
                sk = False
        drop = False
        if sk is False and stale:
            sk, drop = "일시 보류 — 시세 갱신 대기", True
        res[ca] = (upd, sk, drop)
        if sk is None or sk is False or (drop and not skip_final(sk)):
            out.append((ca, ss, m))

    def _fn(cur, k9=pair_key(chain, wallet), res=res):
        e9 = (cur.get("pairs") or {}).get(k9)
        if not isinstance(e9, dict):
            return cur
        for ca9, (upd9, sk9, drop9) in res.items():
            if ca9 not in (e9.get("cas") or {}):
                continue
            m9 = e9.setdefault("meta", {}).setdefault(ca9, {})
            m9.update(upd9)
            if drop9:
                m9.pop("px", None)
            s9 = e9.setdefault("skip", {})
            if sk9 is None:
                s9.pop(ca9, None)
            elif sk9 is not False:
                s9[ca9] = sk9
        return cur
    try:
        update_state(_fn)
    except OSError:
        pass
    return out


def _ok_sources(ext: dict, wl: str) -> list:
    return list(((ext.get("ok") or {}).get(wl) or {}).keys())


def save_result(chain: str, wallet: str, r: dict, sig: dict, why: str = "", skip: dict = None) -> None:
    k = pair_key(chain, wallet)

    def fn(cur):
        old = (cur.get("pairs") or {}).get(k) or {}
        cas9, meta9 = dict(r.get("cas") or {}), {k9: dict(v9) for k9, v9 in (r.get("meta") or {}).items() if isinstance(v9, dict)}
        om9 = old.get("meta") or {}
        osk9 = old.get("skip") or {}
        for ca9, ss9 in (old.get("cas") or {}).items():
            if ca9 in osk9 and skip_final(osk9[ca9]):
                continue
            held9 = "recon" in (ss9 or ()) or ca9 in osk9 or bool((om9.get(ca9) or {}).get("dexAt"))
            if held9 and ca9 not in cas9:
                cas9[ca9] = list(ss9)
                meta9[ca9] = dict(om9.get(ca9) or {}, **(meta9.get(ca9) or {}))
            elif "recon" in (ss9 or ()) and "recon" not in (cas9.get(ca9) or ()):
                cas9[ca9] = list(cas9.get(ca9) or []) + ["recon"]
        for ca9 in cas9:
            o9 = om9.get(ca9) or {}
            if o9.get("dexAt"):
                for f9 in ("px", "dexAt"):
                    if o9.get(f9) is not None and f9 not in (meta9.get(ca9) or {}):
                        meta9.setdefault(ca9, {})[f9] = o9[f9]
        e = {"at": int(time.time()), "why": why, "sig": dict(sig or {}), "cas": cas9, "meta": meta9,
             "ok": r.get("ok") or {}, "fail": r.get("fail") or {}, "calls": r.get("calls") or {}, "n": len(r.get("cas") or {})}
        if skip is not None:
            e["skip"] = skip
        elif old.get("skip"):
            e["skip"] = old["skip"]
        cur["pairs"][k] = e
        return cur
    try:
        update_state(fn)
    except OSError:
        pass


def note_skip(chain: str, skips: dict, meta: dict = None) -> None:
    if not skips:
        return

    def fn(cur):
        for w, d in skips.items():
            e = cur["pairs"].setdefault(pair_key(chain, w), {})
            s9 = dict(e.get("skip") or {})
            s9.update(d)
            e["skip"] = dict(list(s9.items())[-500:])
            for ca9, why9 in d.items():
                if skip_final(why9) or ca9 in (e.get("cas") or {}) or not CA_RE.match(str(ca9)):
                    continue
                e.setdefault("cas", {})[ca9] = ["recon"]
                e.setdefault("meta", {})[ca9] = dict((meta or {}).get(ca9) or {}, **((e.get("meta") or {}).get(ca9) or {}))
        return cur
    try:
        update_state(fn)
    except OSError:
        pass


def filter_result(bal: dict, prep: dict, ext: dict, dex=None) -> dict:
    if not isinstance(bal, dict) or not prep or prep.get("off"):
        return bal
    chain = prep["chain"]
    strict, conf = prep.get("strict"), prep.get("confirmed") or set()
    per = bal.get("per_wallet") or {}
    qd = bal.get("_queried") if isinstance(bal.get("_queried"), dict) else None
    zero = bal.get("_zero") if isinstance(bal.get("_zero"), dict) else None
    unobs = bal.get("_unobs") if isinstance(bal.get("_unobs"), dict) else None
    eo = bal.get("_extra_only") if isinstance(bal.get("_extra_only"), dict) else {}
    meta_all = ext.get("meta") or {}
    src_all = ext.get("src") or {}
    bmeta = bal.get("_meta") if isinstance(bal.get("_meta"), dict) else {}
    bmeta0 = dict(bmeta)
    keep_why, unknown = {}, {}
    skip = {str(w).lower(): dict(d) for w, d in (bal.pop("_disc_pre_skip", None) or {}).items()}

    def syms(ca, extra=None):
        out9 = []
        bm9 = bmeta.get(ca)
        for x in ((meta_all.get(ca) or {}).get("sym"), bm9[0] if isinstance(bm9, (tuple, list)) and bm9 else None, extra):
            if x and str(x).strip() and str(x) not in out9:
                out9.append(str(x))
        return out9

    def name_bad(ca, ss):
        import spamguard
        for sy in ss:
            why9 = scam_name(sy) or ("대표 심볼 흉내(정품 주소 아님)" if spamguard.fake_major(sy, [(chain, ca)]) else "")
            if why9:
                return why9
        return ""

    def wkey(d, w):
        if d is None:
            return None
        return w if w in d else (str(w).lower() if str(w).lower() in d else None)
    for w, cas in eo.items():
        wl = str(w).lower()
        wb = per.get(w) if w in per else per.get(wl)
        for ca in cas or ():
            ca = str(ca).lower()
            v = (wb or {}).get(("token", ca)) if wb is not None else None
            if not v:
                k9 = wkey(unobs, w)
                if k9 is not None and isinstance(unobs[k9], list) and ca in unobs[k9]:
                    unobs[k9] = [x for x in unobs[k9] if str(x).lower() != ca]
                    k8 = wkey(qd, w)
                    if k8 is not None and isinstance(qd[k8], list):
                        qd[k8] = [x for x in qd[k8] if str(x).lower() != ca]
                continue
            if ca in skip.get(wl, {}):
                continue
            try:
                gen9 = bool(strict(ca)) if strict is not None else False
            except Exception:
                gen9 = False
            if gen9:
                keep_why.setdefault(wl, {})[ca] = "정품 목록"
                continue
            ss = syms(ca)
            bad = name_bad(ca, ss)
            if bad:
                skip.setdefault(wl, {})[ca] = bad
                continue
            m9 = dict(meta_all.get(ca) or {}, sym=(ss[0] if ss else None))
            ok, why = static_credible(chain, ca, (src_all.get(wl) or {}).get(ca), m9, None, conf)
            if ok is False:
                skip.setdefault(wl, {})[ca] = why
            elif ok and ss:
                keep_why.setdefault(wl, {})[ca] = why
            else:
                unknown.setdefault(ca, {"ws": [], "cred": why if ok else ""})["ws"].append(w)
    import pricing
    ds_ok = chain in pricing.DS_CHAIN
    if unknown:
        got = {}
        if ds_ok:
            try:
                got = (dex or dex_check)(chain, sorted(unknown), prep.get("min_reserve") or DS_MIN_RESERVE)
            except Exception:
                got = {}
        for ca, u9 in unknown.items():
            g = got.get(ca)
            ss = syms(ca, g[3] if g and len(g) > 3 else None)
            bad = name_bad(ca, ss)
            for w in u9["ws"]:
                wl = str(w).lower()
                if bad:
                    skip.setdefault(wl, {})[ca] = bad
                elif not ss:
                    skip.setdefault(wl, {})[ca] = "심볼 모름 — 앵커 안 함"
                elif u9["cred"]:
                    keep_why.setdefault(wl, {})[ca] = u9["cred"]
                elif g and g[0]:
                    keep_why.setdefault(wl, {})[ca] = f"덱스 유동성 ${g[1]:,.0f}"
                elif g:
                    skip.setdefault(wl, {})[ca] = "유동성 부족 — 스팸 의심"
                elif not ds_ok:
                    skip.setdefault(wl, {})[ca] = "판정 불가 체인(덱스 미지원) — 정품 목록 밖이라 앵커 안 함"
                else:
                    skip.setdefault(wl, {})[ca] = "일시 보류 — 판정 출처 장애"
            if g and g[2] and not bad and ss:
                meta_all.setdefault(ca, {}).setdefault("px", g[2])
            if ss and not (meta_all.get(ca) or {}).get("sym"):
                meta_all.setdefault(ca, {})["sym"] = ss[0]
    for wl, d in skip.items():
        w = next((x for x in per if str(x).lower() == wl), wl)
        for ca in d:
            (per.get(w) or {}).pop(("token", ca), None)
            if ca in bmeta and not any(("token", ca) in (wb9 or {}) for wb9 in per.values()):
                bmeta.pop(ca, None)
            for dd in (qd, zero, unobs):
                k9 = wkey(dd, w)
                if k9 is not None and isinstance(dd[k9], list):
                    dd[k9] = [x for x in dd[k9] if str(x).lower() != ca]
    meta = bal.get("_meta") if isinstance(bal.get("_meta"), dict) else None
    if meta is not None:
        for ca, m in meta_all.items():
            if ca in meta and isinstance(meta[ca], tuple) and len(meta[ca]) == 2 and not meta[ca][0] and m.get("sym"):
                meta[ca] = (m["sym"], meta[ca][1])
    hold = bal.setdefault("_hold", {}) if isinstance(bal.get("_hold", {}), dict) else None
    for w, s in (ext.get("status") or {}).items():
        if s == "pending" and hold is not None:
            ww = next((x for x in per if str(x).lower() == w), w)
            hold.setdefault(ww, []).append("발견 진행 중")
            per.pop(ww, None)
    bal["_disc_skip"] = {w: d for w, d in skip.items() if d}
    bal["_disc_keep"] = {w: d for w, d in keep_why.items() if d}
    bal["_disc"] = {"status": dict(ext.get("status") or {}), "fail": {w: sorted(f) for w, f in (ext.get("fail") or {}).items()}}
    if skip:
        hm9 = {}
        for d9 in skip.values():
            for ca9, why9 in d9.items():
                if skip_final(why9):
                    continue
                m9 = {k9: v9 for k9, v9 in (meta_all.get(ca9) or {}).items() if k9 in ("sym", "dec", "px")}
                b9 = bmeta0.get(ca9)
                if isinstance(b9, (tuple, list)) and len(b9) == 2:
                    if b9[0] and not m9.get("sym"):
                        m9["sym"] = b9[0]
                    if b9[1] is not None and m9.get("dec") is None:
                        m9["dec"] = b9[1]
                hm9[ca9] = m9
        note_skip(chain, skip, hm9)
    return bal


def summary(cfg: dict = None, state: dict = None, env: dict = None) -> dict:
    st = load_state() if state is None else state
    pairs = st.get("pairs") or {}
    if cfg is not None:
        act9 = {pair_key("bsc" if w.get("type") == "bsc_rpc" else w.get("chain"), w.get("address"))
                for w in cfg.get("wallets") or [] if w.get("type", "evm") in ("evm", "bsc_rpc") and w.get("address")}
        pairs = {k: e for k, e in pairs.items() if k in act9}
    fb, fp, sk, done = {}, 0, 0, 0
    hold = 0
    for k, e in pairs.items():
        if not isinstance(e, dict):
            continue
        if e.get("at"):
            done += 1
        f = e.get("fail") or {}
        hard = {s: v for s, v in f.items() if str(v).split(":")[0] not in ("unsupported", "nokey")}
        if hard:
            fp += 1
            for s, v in hard.items():
                fb[s] = fb.get(s, 0) + 1
        sk9 = e.get("skip") or {}
        hd9 = sum(1 for v in sk9.values() if not skip_final(v))
        sk += len(sk9) - hd9
        hold += hd9
    chains = {}
    noold = []
    env = _env() if env is None else env
    for w in (cfg or {}).get("wallets") or []:
        t = w.get("type", "evm")
        c = "bsc" if t == "bsc_rpc" else (w.get("chain") if t == "evm" else None)
        if not c or c in chains:
            continue
        chains[c] = old_status(c, cfg, env)
        if chains[c] in ("none", "nokey"):
            noold.append(c)
    return {"pairs": len(pairs), "done": done, "failPairs": fp, "failBy": fb, "skip": sk, "hold": hold, "chains": chains, "noOld": sorted(noold)}
