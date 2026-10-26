from __future__ import annotations

import fcntl
import json
import os
import re
import threading
import time
import urllib.parse

import config, envfile, logs, num_parse, paths, seeds, statefile
import bf_engine

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
FINAL_FAIL = ("unsupported", "nokey", "slow", "partial", "cap")
KEYED = ("etherscan", "alchemy", "ankr")
MAX_CAS = 3000
MAX_QUERY = 3000
ES_PAGES = 5
ES_LIKE = ("etherscan", "routescan")
ES_V = 2
ES_ROWS = {"etherscan": 1000, "routescan": 10000}
ES_ROW_FLOOR = 1000
ES_BLOCK_PAGES = 10
ES_DEFER_RUNS = 6
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
DS_PAIRS_MAX = 5
DS_PAIRS_TTL_S = 86400
_SEED = {"d": None}
_LOCK = threading.Lock()


class SourceFail(RuntimeError):
    def __init__(self, kind: str, msg: str = ""):
        super().__init__(f"{kind}: {msg}" if msg else kind)
        self.kind = kind


def sources_table(base: str = None) -> dict:
    if base is None and _SEED["d"] is not None:
        return _SEED["d"]
    d = seeds.seed_json(SEED_NAME, {}, base_dir=base) or {}
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
        out = dict(envfile.read_env_file())
    except Exception:   # noqa: BLE001 [fallback]
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
    except Exception:   # noqa: BLE001 [optional]
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
        except Exception:   # noqa: BLE001 [optional]
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
        except Exception:   # noqa: BLE001 [optional]
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
    if cc.get("blockscout") and not config.bs_blocked(chain, cc) and config.chain_discovery(chain, cc) != "rpc":
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
    if _rabby_on(cfg):
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
        sp = ((statefile.read_json(paths.BACKFILL_SPEED_PATH, {}) or {}).get("chains") or {}).get(chain, {}).get("getLogsSpan")
    except (Exception, SystemExit):   # noqa: BLE001 [fallback]
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
    return os.path.join(state_dir or paths.STATE_DIR, STATE_NAME)


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
        statefile.atomic_write_json(p, new)
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
    rs9, up9 = _es_due(ent, srcs)
    if rs9 or up9:
        return True, ("resume:" if rs9 else "upgrade:") + "+".join(rs9 + up9)
    soft = {s9 for s9, v in fail.items() if str(v).split(":")[0] not in FINAL_FAIL}
    if soft and now - float(ent.get("at") or 0) >= RETRY_FAIL_SEC:
        return True, "retry"
    done = set((ent.get("ok") or {}).keys()) | set(fail.keys())
    for s in srcs or ():
        if (s in INDEX_SOURCES or s == "rabby") and s not in done:
            return True, f"new:{s}"
    return False, "cache"


def _es_cur(c):
    if not isinstance(c, dict) or c.get("v") != ES_V:
        return None
    try:
        int(c.get("lo") or 0), int(c.get("pg") or 0)
        if c.get("hi") is not None:
            int(c["hi"])
    except (TypeError, ValueError):
        return None
    return c


def _es_due(ent: dict, srcs) -> tuple:
    if not isinstance(ent, dict) or not ent.get("at"):
        return [], []
    esd = ent.get("es") if isinstance(ent.get("es"), dict) else {}
    ok = ent.get("ok") if isinstance(ent.get("ok"), dict) else {}
    fail = ent.get("fail") if isinstance(ent.get("fail"), dict) else {}
    rs, up = [], []
    for s9 in srcs or ():
        if s9 not in ES_LIKE:
            continue
        c = _es_cur(esd.get(s9))
        fk = str(fail.get(s9, "")).split(":")[0]
        if c is None:
            if s9 in ok or fk == "partial":
                up.append(s9)
        elif not c.get("done") and fk == "more":
            rs.append(s9)
    return rs, up


def _es_usable(chain: str, src: str, env: dict = None) -> bool:
    row = chain_row(chain)
    if src == "etherscan":
        return row.get("etherscan") == "free" and bool(es_key(env))
    return bool(row.get("routescan")) if src == "routescan" else False


def run_sources(srcs, why) -> list:
    w9 = str(why or "")
    if srcs is not None and w9.startswith(("resume:", "upgrade:")):
        only = [x for x in w9.split(":", 1)[1].split("+") if x]
        sub = [x for x in srcs if x in only]
        if sub:
            return sub
    return srcs


def _clean(msg: str, env: dict = None) -> str:
    t = logs.redact_secret_text(logs.redact_urls(str(msg or "")))
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
        raise SourceFail(k, logs.redact_urls(str(e))[:120]) from e


def es_cursor(old, upto) -> dict:
    c = _es_cur(old)
    hi = int(upto) if upto else None
    if c is not None and not c.get("done"):
        out = dict(c, lo=int(c.get("lo") or 0), pg=int(c.get("pg") or 0), n=int(c.get("n") or 0) + 1)
        if c.get("hi") is not None and (hi is None or hi > int(c["hi"])):
            w0 = c["want"] if "want" in c else hi
            out["want"] = None if (hi is None or w0 is None) else max(int(w0), hi)
        return out
    if c is not None:
        nxt = {"v": ES_V, "g": int(c.get("g") or 1) + 1, "lo": int(c.get("end") if c.get("end") is not None else c.get("lo") or 0), "pg": 0,
               "hi": hi, "done": False, "n": 1}
        if c.get("gap"):
            nxt["gap"] = list(c["gap"])[-20:]
        return nxt
    return {"v": ES_V, "g": 1, "lo": 0, "pg": 0, "hi": hi, "done": False, "n": 1}


def _es_done(cur: dict, last) -> None:
    cur["done"] = True
    cur["pg"] = 0
    lo9 = int(cur.get("lo") or 0)
    cur["end"] = max(lo9, int(cur["hi"])) if cur.get("hi") is not None else max(lo9, int(last or 0))


def _es_roll(cur: dict) -> bool:
    if "want" not in cur:
        return False
    want = cur.pop("want")
    end = int(cur.get("end") or 0)
    if want is not None and int(want) <= end:
        return False
    cur.update(g=int(cur.get("g") or 1) + 1, lo=end, pg=0, hi=None if want is None else int(want), done=False, n=1)
    cur.pop("end", None)
    return True


def _es_like(base_url: str, params: dict, upto, out: dict, meta: dict, src: str, budget: bool, sleep, cur: dict = None,
             deadline: float = None) -> int:
    import bf_engine
    cur = cur if isinstance(cur, dict) else es_cursor(None, upto)
    rows9 = int(ES_ROWS.get(src) or ES_ROW_FLOOR)
    max_calls = max(1, ES_PAGES * 10000 // rows9)
    calls, last_fp, seen_last = 0, None, None
    while True:
        hi = cur.get("hi")
        if hi is not None and int(cur["lo"]) > int(hi):
            _es_done(cur, seen_last)
            if _es_roll(cur):
                continue
            break
        if calls >= max_calls:
            raise SourceFail("more", f"한 실행 몫 {calls}콜 — 다음 실행에서 {int(cur['lo'])} 블록부터 이어서")
        if deadline is not None and time.time() > deadline:
            raise SourceFail("more", f"시간 상한 — 다음 실행에서 {int(cur['lo'])} 블록부터 이어서")
        pg = int(cur.get("pg") or 0)
        lo = int(cur["lo"])
        if pg > 0:
            size = ES_ROW_FLOOR
            q = dict(params, module="account", action="tokentx", startblock=lo, endblock=lo, page=pg, offset=size, sort="asc")
        else:
            size = rows9
            q = dict(params, module="account", action="tokentx", startblock=lo, page=1, offset=size, sort="asc")
            if hi is not None:
                q["endblock"] = int(hi)
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
                res = []
            else:
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
                raise SourceFail("error", logs.redact_urls(msg)[:80])
        if not isinstance(res, list):
            raise SourceFail("error", "result 형식")
        blks, prev = [], None
        for r in res:
            try:
                b9 = int((r or {}).get("blockNumber"))
            except (TypeError, ValueError, AttributeError):
                raise SourceFail("error", "응답 행 형식(blockNumber)") from None
            if b9 < lo or (pg > 0 and b9 != lo) or (hi is not None and b9 > int(hi)) or (prev is not None and b9 < prev):
                raise SourceFail("error", "응답 블록 범위·정렬 어긋남 — 완료로 안 침")
            prev = b9
            blks.append(b9)
        if pg > 0 and res:
            fp = (len(res), json.dumps(res[0], sort_keys=True, default=str), json.dumps(res[-1], sort_keys=True, default=str))
            if fp == last_fp:
                raise SourceFail("error", "같은 쪽 반복(제공자가 page 무시) — 완료로 안 침")
            last_fp = fp
        over = 0
        for r in res:
            ca9 = str(r.get("contractAddress") or "").lower()
            if CA_RE.match(ca9) and ca9 not in out and ca9 != "0x" + "0" * 40 and len(out) >= MAX_CAS:
                over += 1
                continue
            _add(out, meta, ca9, src, r.get("tokenSymbol"), r.get("tokenDecimal"))
        if over:
            raise SourceFail("cap", f"후보 상한 {MAX_CAS:,} — {lo} 블록부터 {over}개+ 미확인")
        cur["rows"] = int(cur.get("rows") or 0) + len(res)
        short = len(res) < min(size, ES_ROW_FLOOR)
        if blks:
            seen_last = blks[-1]
        if pg > 0:
            if short:
                cur["lo"], cur["pg"] = lo + 1, 0
            elif pg >= ES_BLOCK_PAGES:
                gp = list(cur.get("gap") or [])
                if lo not in gp:
                    gp.append(lo)
                cur["gap"] = gp[-20:]
                cur["lo"], cur["pg"] = lo + 1, 0
            else:
                cur["pg"] = pg + 1
            last_fp = None if cur["pg"] == 0 else last_fp
        elif short:
            _es_done(cur, seen_last)
            if not _es_roll(cur):
                break
        elif blks[-1] > lo:
            cur["lo"] = blks[-1]
        else:
            cur["pg"] = 2 if size == ES_ROW_FLOOR else 1
        sleep(0.5)
    if cur.get("gap"):
        raise SourceFail("partial", f"한 블록 1만 줄 넘음 {len(cur['gap'])}블록 — 그 블록 일부 미확인")
    return calls


def src_etherscan(chain: str, wallet: str, upto=None, env=None, sleep=time.sleep, out=None, meta=None, cur=None, deadline=None) -> int:
    cid = chain_row(chain).get("chain_id")
    k = es_key(env)
    if not cid or not k:
        raise SourceFail("nokey" if not k else "unsupported")
    return _es_like("https://api.etherscan.io/v2/api", {"chainid": int(cid), "address": wallet, "apikey": k}, upto, out, meta,
                    "etherscan", True, sleep, cur=cur, deadline=deadline)


def src_routescan(chain: str, wallet: str, upto=None, sleep=time.sleep, out=None, meta=None, cur=None, deadline=None) -> int:
    cid = chain_row(chain).get("chain_id")
    if not cid:
        raise SourceFail("unsupported")
    return _es_like(f"https://api.routescan.io/v2/network/mainnet/evm/{int(cid)}/etherscan/api", {"address": wallet}, upto, out, meta,
                    "routescan", False, sleep, cur=cur, deadline=deadline)


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
    except Exception:   # noqa: BLE001 [optional]
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
        cfg = config.load_config()
    except (Exception, SystemExit):   # noqa: BLE001 [fallback]
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
        raise SourceFail(k, logs.redact_secret_text(logs.redact_urls(str(e)))[:120].replace(host, "<host>")) from e


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


def _rabby_on(cfg: dict) -> bool:
    try:
        import rabby
        return rabby.enabled(cfg or {})
    except Exception:   # noqa: BLE001 [fallback]
        return False


def src_rabby(chain: str, wallet: str, cfg: dict = None, out=None, meta=None) -> int:
    if not _rabby_on(cfg):
        return 0
    try:
        import rabby
        st = rabby.load_state(paths.state(rabby.STATE_NAME))
        res = rabby.chain_resolver(cfg or {}, st)
    except Exception:   # noqa: BLE001 [fallback]
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
        except Exception:   # noqa: BLE001 [fallback]
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
                hits = recon._rpc_any(urls, "eth_getLogs", [{"fromBlock": hex(a), "toBlock": hex(b), "topics": topics}], tries=2, sleep=sleep)
            except Exception as e:   # noqa: BLE001
                low = str(e).lower()
                if sp > 100 and any(x in low for x in ("range", "limit", "too many", "exceed", "10000", "block range", "query returned")):
                    sp = max(100, sp // 2)
                    continue
                raise SourceFail("net", logs.redact_urls(str(e))[:100]) from e
            if isinstance(hits, list) and len(hits) in bf_engine.SILENT_ROW_CAPS:
                if sp > 100:
                    sp = max(100, sp // 2)
                    continue
                raise SourceFail("partial", f"getLogs {len(hits)}행 = 결과 상한 — 잘림 의심")
            for lg in hits if isinstance(hits, list) else []:
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
        except Exception:   # noqa: BLE001 [fallback]
            cm = None
    with (cm() if callable(cm) else contextlib.nullcontext()):
        return _discover(chain, wallet, upto=upto, cfg=cfg, env=env, sources=sources, logs_max_calls=logs_max_calls, sleep=sleep, deadline=deadline)


def _discover(chain: str, wallet: str, *, upto=None, cfg: dict = None, env: dict = None, sources=None, logs_max_calls: int = LOGS_MAX_CALLS,
              sleep=time.sleep, deadline: float = None) -> dict:
    env = _env() if env is None else env
    srcs = list(sources) if sources is not None else plan(chain, cfg, env)
    cas, meta, ok, fail, calls = {}, {}, {}, {}, {}
    w = str(wallet).lower()
    es_out, ran = {}, []
    ent0 = {}
    if any(s in ES_LIKE for s in srcs):
        try:
            ent0 = entry(chain, w)
        except Exception:   # noqa: BLE001 [fallback]
            ent0 = {}
    for s in srcs:
        if s == "logs":
            continue
        one = {}
        ran.append(s)
        try:
            if s in ES_LIKE:
                cur9 = es_out[s] = es_cursor(((ent0.get("es") or {}) if isinstance(ent0.get("es"), dict) else {}).get(s), upto)
                osk9 = ent0.get("skip") if isinstance(ent0.get("skip"), dict) else {}
                om9 = ent0.get("meta") if isinstance(ent0.get("meta"), dict) else {}
                for ca9, ss9 in sorted(((ent0.get("cas") or {}) if isinstance(ent0.get("cas"), dict) else {}).items()):
                    if s in (ss9 or ()) and not (ca9 in osk9 and skip_final(osk9[ca9])):
                        m9 = om9.get(ca9) if isinstance(om9.get(ca9), dict) else {}
                        _add(one, meta, ca9, s, m9.get("sym"), m9.get("dec"))
                if s == "etherscan":
                    n = src_etherscan(chain, w, upto, env, sleep, one, meta, cur=cur9, deadline=deadline)
                else:
                    n = src_routescan(chain, w, upto, sleep, one, meta, cur=cur9, deadline=deadline)
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
            if e.kind in ("partial", "more", "cap"):
                ok[s] = len(one)
        except Exception as e:   # noqa: BLE001 [fallback]
            fail[s] = _clean("error: " + logs.safe_err(e))
        for ca, ss in one.items():
            cas.setdefault(ca, set()).update(ss)
    if "logs" in srcs and not any(s in ok for s in INDEX_SOURCES):
        ran.append("logs")
        one = {}
        try:
            calls["logs"] = src_logs(chain, w, cfg, upto, logs_max_calls, sleep=sleep, out=one, meta=meta, deadline=deadline)
            ok["logs"] = len(one)
        except SourceFail as e:
            fail["logs"] = _clean(f"{e.kind}: {str(e)[len(e.kind) + 2:]}")
        except Exception as e:   # noqa: BLE001 [fallback]
            fail["logs"] = _clean("error: " + logs.safe_err(e))
        for ca, ss in one.items():
            cas.setdefault(ca, set()).update(ss)
    out = {"cas": {k: sorted(v) for k, v in cas.items()}, "meta": {k: v for k, v in meta.items() if k in cas},
           "ok": ok, "fail": fail, "calls": calls, "ran": ran}
    if es_out:
        out["es"] = es_out
    return out


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
    except Exception:   # noqa: BLE001 [optional]
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


def dex_check(chain: str, cas: list, min_reserve: float = DS_MIN_RESERVE, sleep=time.sleep, retries: int = 2,
              pairs_budget: list = None, batch_ok: list = None) -> dict:
    import token_tables
    net = token_tables.DS_CHAIN.get(chain)
    out = {}
    if not net:
        return out
    lst = sorted({str(c).lower() for c in cas})
    pairs_left = pairs_budget if pairs_budget is not None else [DS_PAIRS_MAX]
    late = []
    for i in range(0, len(lst), 30):
        batch = lst[i:i + 30]
        try:
            d = _http(f"https://api.dexscreener.com/tokens/v1/{net}/{','.join(batch)}", retries=retries)
        except SourceFail:
            continue
        if isinstance(d, dict):
            d = d.get("pairs")
        if not isinstance(d, list):
            continue
        if batch_ok is not None:
            batch_ok[0] = True
        res, best, sym, stray, nf = _ds_rows(d, batch, net)
        low = [a for a in batch if a in res and res[a] < float(min_reserve)] + [a for a in batch if a not in res]
        lt = {a for a in low if a in nf}
        late += [(a, res, best, sym) for a in low if a in lt]
        low = [a for a in low if a not in lt]
        full = _pairs_liq(chain, net, low, pairs_left, sleep, float(min_reserve)) if low else {}
        cut = len(d) >= 30 or stray
        for a in batch:
            if a in lt:
                continue
            if a in low and a not in full and (a in res or cut):
                continue
            if a in res or (a in full and full[a][0] > 0):
                out[a] = _ds_judge(a, full.get(a), res, best, sym, min_reserve)
            else:
                out[a] = (False, 0.0, None, None)
        sleep(0.5)
    full = _pairs_liq(chain, net, [x[0] for x in late], pairs_left, sleep, float(min_reserve)) if late else {}
    for a, res, best, sym in late:
        if a in full:
            out[a] = _ds_judge(a, full[a], res, best, sym, min_reserve)
    return out


def _ds_rows(d: list, batch: list, net: str) -> tuple:
    res, best, sym, stray, nf = {}, {}, {}, False, set()
    for pr in d:
        if not isinstance(pr, dict):
            stray = True
            continue
        if pr.get("chainId") and pr.get("chainId") != net:
            continue
        sides = {side: _ds_side(pr, side) for side in ("baseToken", "quoteToken")}
        if not all(_ds_addr(t) for t in sides.values()):
            stray = True
        if not any(_ds_addr(t) for t in sides.values()):
            continue
        liq = _ds_liq(pr)
        for side, tok in sides.items():
            a = _ds_addr(tok)
            if a not in batch:
                continue
            sym.setdefault(a, tok.get("symbol"))
            if liq is None:
                res.setdefault(a, 0.0)
                if _ds_nonfinite(pr):
                    nf.add(a)
                continue
            res[a] = res.get(a, 0.0) + liq
            px = _ds_px(pr) if side == "baseToken" else 0.0
            if px > 0 and (a not in best or liq > best[a][0]):
                best[a] = (liq, px)
    for a in [a for a, v in res.items() if num_parse.to_float(v) is None]:
        res[a] = 0.0
        nf.add(a)
    return res, best, sym, stray, nf


def _ds_judge(a: str, f, res: dict, best: dict, sym: dict, min_reserve: float) -> tuple:
    if f and f[0] > res.get(a, 0.0):
        res[a] = f[0]
        if f[1]:
            best[a] = (0.0, f[1])
        if f[2]:
            sym.setdefault(a, f[2])
    return (res[a] >= float(min_reserve), res[a], best.get(a, (0, None))[1], sym.get(a))


def _ds_nonfinite(pr: dict) -> bool:
    lq = pr.get("liquidity")
    v = lq.get("usd") if isinstance(lq, dict) else None
    try:
        return isinstance(v, (int, float, str)) and not isinstance(v, bool) and num_parse.to_float(float(v)) is None
    except (ValueError, OverflowError):
        return False


def _ds_side(pr: dict, side: str) -> dict:
    v = pr.get(side)
    return v if isinstance(v, dict) else {}


def _ds_addr(tok: dict) -> str:
    a = tok.get("address")
    return a.strip().lower() if isinstance(a, str) else ""


def _ds_liq(pr: dict) -> float | None:
    lq = pr.get("liquidity")
    if lq is None:
        return 0.0
    if not isinstance(lq, dict):
        return None
    v = lq.get("usd")
    if v is None or v == "":
        return 0.0
    x = num_parse.to_float(v, allow_bool=False)
    return x if x is not None and x >= 0 else None


def _ds_px(pr: dict) -> float:
    x = num_parse.to_float(pr.get("priceUsd") or 0, 0.0, allow_bool=False)
    return x if x > 0 else 0.0


def _pairs_sum(d, net: str, ca: str, floor: float | None = None) -> tuple:
    if isinstance(d, dict):
        d = d.get("pairs")
    if not isinstance(d, list):
        return None
    liq, best, sym, bad = 0.0, None, None, False
    for pr in d:
        if not isinstance(pr, dict):
            bad = True
            continue
        if pr.get("chainId") and pr.get("chainId") != net:
            continue
        base, quote = _ds_side(pr, "baseToken"), _ds_side(pr, "quoteToken")
        if not (_ds_addr(base) and _ds_addr(quote)):
            bad = True
        if not _ds_addr(base) and not _ds_addr(quote):
            continue
        mine = base if _ds_addr(base) == ca else (quote if _ds_addr(quote) == ca else None)
        if mine is None:
            continue
        pl = _ds_liq(pr)
        if pl is None:
            bad = True
            continue
        liq += pl
        sym = sym or mine.get("symbol")
        px = _ds_px(pr) if mine is base else 0.0
        if px > 0 and (best is None or pl > best[0]):
            best = (pl, px)
    if num_parse.to_float(liq) is None or (bad and (floor is None or liq < floor)):
        return None
    return liq, (best[1] if best else None), sym, not bad


def _pairs_liq(chain: str, net: str, cas: list, left: list, sleep, floor: float | None = None) -> dict:
    now = time.time()
    cache = load_state().get("dexliq") or {}
    out, fresh = {}, {}
    for ca in cas:
        ent = cache.get(f"{chain}:{ca}")
        c_liq = num_parse.to_float(ent.get("liq") or 0.0, allow_bool=False) if isinstance(ent, dict) else None
        if c_liq is not None and c_liq >= 0 and now - float(ent.get("at") or 0) < DS_PAIRS_TTL_S:
            out[ca] = (c_liq, None, ent.get("sym"))
            continue
        if left[0] <= 0:
            continue
        left[0] -= 1
        try:
            got = _pairs_sum(_http(f"https://api.dexscreener.com/token-pairs/v1/{net}/{ca}", retries=1), net, ca, floor)
        except SourceFail:
            got = None
        finally:
            sleep(0.25)
        if got is None:
            continue
        out[ca] = got[:3]
        if got[3]:
            fresh[f"{chain}:{ca}"] = {"liq": got[0], "px": got[1], "sym": got[2], "at": int(now)}
    if fresh:
        def _put(cur):
            keep = {k: v for k, v in (cur.get("dexliq") or {}).items() if isinstance(v, dict) and now - float(v.get("at") or 0) < DS_PAIRS_TTL_S}
            keep.update(fresh)
            cur["dexliq"] = keep
            return cur
        try:
            update_state(_put)
        except OSError:
            pass
    return out


_DEX_IMPL = dex_check


def ledger_genuine(conn, chain: str, strict=None) -> set:
    import token_tables
    import spamguard
    out = set()
    for r in conn.execute("SELECT address FROM assets WHERE chain=? AND kind='token' AND confirmed=1 AND address IS NOT NULL", (chain,)).fetchall():
        a = str(r[0]).lower()
        if CA_RE.match(a):
            out.add(a)
    for tab in (token_tables.STABLE_CAS, token_tables.JPY_STABLE_CAS, spamguard.GENUINE_CAS):
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
    rb9 = (cfg or {}).get("rabby") if isinstance(cfg, dict) else None
    return {"chain": chain, "kind": kind, "cfg": dict({"chains": {chain: dict(_cc(cfg, chain))}}, **({"rabby": dict(rb9)} if isinstance(rb9, dict) else {})),
            "confirmed": conf, "genuine": gen,
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
            run9 = run_sources(srcs, why)
            r = dfn(chain, w, upto=upto, cfg=cfg, env=env, sources=run9, sleep=sleep, deadline=dl, burst=(why == "first"))
            save_result(chain, w, r, sig, why)
            cas, meta, fail, ok9 = r["cas"], r["meta"], r["fail"], r.get("ok") or {}
            if run9 != srcs:
                ran9 = set(r.get("ran") or run9 or ())
                cas = {k9: list(v9) for k9, v9 in (ent.get("cas") or {}).items()}
                for k9, v9 in r["cas"].items():
                    cas[k9] = sorted(set(cas.get(k9) or ()) | set(v9))
                meta = {k9: dict(v9) for k9, v9 in (ent.get("meta") or {}).items() if isinstance(v9, dict)}
                for k9, v9 in r["meta"].items():
                    meta[k9] = dict(meta.get(k9) or {}, **v9)
                ok9 = dict({k9: v9 for k9, v9 in (ent.get("ok") or {}).items() if k9 not in ran9}, **ok9)
                fail = dict({k9: v9 for k9, v9 in (ent.get("fail") or {}).items() if k9 not in ran9}, **fail)
            out["status"][w] = _wstatus(ok9, fail, r.get("es") or {})
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
        if len(cand) > MAX_QUERY:
            out["fail"].setdefault(w, {})["query"] = f"cap: 질문 상한 {MAX_QUERY:,} — {len(cand) - MAX_QUERY:,}개 이번 대사에서 안 물음"
    return out


def fast_extra(prep: dict, deadline: float = None, discover_fn=None) -> dict:
    out = {"extra": {}, "meta": {}, "src": {}, "status": {}, "fail": {}, "ok": {}}
    if not prep or prep.get("off"):
        return out
    chain = prep["chain"]
    env = _env()
    if not (alchemy_net(chain) and alchemy_url(chain, env)):
        return out
    dl = deadline if deadline is not None else time.time() + JOB_MAX_SEC
    dfn = discover_fn or discover
    gen = set(prep.get("genuine") or ())
    for w in (prep.get("sigs") or {}):
        if time.time() > dl:
            break
        try:
            r = dfn(chain, w, cfg=prep.get("cfg") or {}, env=env, sources=["alchemy"], deadline=dl)
        except Exception as e:   # noqa: BLE001 [isolate]
            out["fail"][w] = {"alchemy": _clean("error: " + logs.safe_err(e))}
            continue
        meta = r.get("meta") or {}
        if r.get("fail"):
            out["fail"][w] = dict(r["fail"])
        out["status"][w] = "ok" if (r.get("ok") or {}).get("alchemy") is not None and "alchemy" not in (r.get("fail") or {}) else "fail"
        nz = sorted(ca for ca in (r.get("cas") or {}) if (meta.get(ca) or {}).get("alnz"))
        src9 = {ca: ["alchemy"] for ca in nz}
        for ca in gen:
            src9.setdefault(ca, []).append("ledger")
        out["extra"][w] = set(list(src9)[:MAX_QUERY])
        out["src"][w] = {ca: src9[ca] for ca in out["extra"][w]}
        for ca in nz:
            if ca in meta:
                out["meta"].setdefault(ca, dict(meta[ca]))
    return out


def _wstatus(ok9: dict, fail: dict, es: dict) -> str:
    got = [s9 for s9 in (ok9 or {}) if s9 in INDEX_SOURCES or s9 == "logs"]
    if not got:
        return "fail"
    if any(s9 not in (fail or {}) for s9 in got):
        return "ok"
    for s9 in got:
        if s9 in ES_LIKE and str((fail or {}).get(s9, "")).startswith("more") and int(((es or {}).get(s9) or {}).get("n") or 0) < ES_DEFER_RUNS:
            return "pending"
    return "partial"


def recon_extra_safe(prep: dict, upto=None, **kw) -> dict:
    try:
        return recon_extra(prep, upto=upto, **kw)
    except Exception as e:   # noqa: BLE001 [fallback]
        import logging
        logging.getLogger("tj-core").warning("토큰 발견 실패(종전 목록으로 대사): %s", logs.safe_err(e)[:160])
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
    except Exception:   # noqa: BLE001 [fallback]
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
    import token_tables
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
    ds_ok = chain in token_tables.DS_CHAIN
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
            pb = [min(DS_PAIRS_MAX, max(0, budget[0]))] if budget is not None else [DS_PAIRS_MAX]
            pb0 = pb[0]
            bok = [False]
            try:
                g9 = fn(chain, part, min_reserve, **(dict(kw, pairs_budget=pb, batch_ok=bok) if fn is _DEX_IMPL else kw)) or {}
            except Exception:   # noqa: BLE001 [fallback]
                g9 = {}
            if budget is not None:
                budget[0] -= pb0 - pb[0]
            got.update(g9)
            if not g9 and not bok[0]:
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

    def _fn(cur, k9=pair_key(chain, wallet), res=res):  # noqa: B008
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

    ran9 = set(r.get("ran") or ()) if isinstance(r.get("ran"), (list, tuple, set)) else None
    only9 = str(why or "").startswith(("resume:", "upgrade:")) and ran9 is not None
    good9 = {s9 for s9 in (ran9 or ()) if s9 in (r.get("ok") or {}) and s9 not in (r.get("fail") or {})}

    def fn(cur):
        old = (cur.get("pairs") or {}).get(k) or {}
        cas9, meta9 = dict(r.get("cas") or {}), {k9: dict(v9) for k9, v9 in (r.get("meta") or {}).items() if isinstance(v9, dict)}
        om9 = old.get("meta") or {}
        osk9 = old.get("skip") or {}
        for ca9, ss9 in (old.get("cas") or {}).items():
            if ca9 in osk9 and skip_final(osk9[ca9]):
                continue
            held9 = "recon" in (ss9 or ()) or ca9 in osk9 or bool((om9.get(ca9) or {}).get("dexAt"))
            if ran9 is not None and ca9 not in cas9 and (set(ss9 or ()) - {"recon", "ledger"}) - good9:
                held9 = True
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
        ok9, fail9, calls9 = r.get("ok") or {}, r.get("fail") or {}, r.get("calls") or {}
        if only9:
            for ca9 in cas9:
                if (old.get("cas") or {}).get(ca9):
                    cas9[ca9] = sorted(set(cas9[ca9] or ()) | set((old.get("cas") or {})[ca9]))
                if isinstance(om9.get(ca9), dict):
                    meta9[ca9] = dict(om9[ca9], **(meta9.get(ca9) or {}))
            ok9 = dict({s9: v9 for s9, v9 in (old.get("ok") or {}).items() if s9 not in ran9}, **ok9)
            fail9 = dict({s9: v9 for s9, v9 in (old.get("fail") or {}).items() if s9 not in ran9}, **fail9)
            calls9 = dict({s9: v9 for s9, v9 in (old.get("calls") or {}).items() if s9 not in ran9}, **calls9)
        e = {"at": int(time.time()), "why": why, "sig": dict(sig or {}), "cas": cas9, "meta": meta9,
             "ok": ok9, "fail": fail9, "calls": calls9, "n": len(cas9) if only9 else len(r.get("cas") or {})}
        es9 = dict(old.get("es") or {}) if isinstance(old.get("es"), dict) else {}
        if isinstance(r.get("es"), dict):
            es9.update({s9: dict(c9) for s9, c9 in r["es"].items() if isinstance(c9, dict)})
        if es9:
            e["es"] = es9
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


def filter_result(bal: dict, prep: dict, ext: dict, dex=None, keep_pending: bool = False) -> dict:
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
            except Exception:   # noqa: BLE001 [fallback]
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
    import token_tables
    ds_ok = chain in token_tables.DS_CHAIN
    if unknown:
        got = {}
        if ds_ok:
            try:
                got = (dex or dex_check)(chain, sorted(unknown), prep.get("min_reserve") or DS_MIN_RESERVE)
            except Exception:   # noqa: BLE001 [fallback]
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
                    skip.setdefault(wl, {})[ca] = "일시 보류 — 판정 출처 장애" if (ds_ok and g is None) else "심볼 모름 — 앵커 안 함"
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
        if s == "pending" and hold is not None and not keep_pending:
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


def hard_fails(e: dict) -> dict:
    f = e.get("fail") or {}
    hard = {s: v for s, v in f.items() if str(v).split(":")[0] not in ("unsupported", "nokey", "more")}
    cm9 = e.get("meta") if isinstance(e.get("meta"), dict) else {}
    nq9 = sum(1 for ca9, ss9 in (e.get("cas") if isinstance(e.get("cas"), dict) else {}).items()
              if not ((cm9.get(ca9) or {}).get("rbscam") and set(ss9 or ()) <= {"rabby"}))
    if nq9 > MAX_QUERY and "query" not in hard:
        hard["query"] = f"cap: 질문 상한 {MAX_QUERY:,} — {nq9 - MAX_QUERY:,}개"
    return hard


def summary(cfg: dict = None, state: dict = None, env: dict = None) -> dict:
    st = load_state() if state is None else state
    pairs = st.get("pairs") or {}
    if cfg is not None:
        act9 = {pair_key("bsc" if w.get("type") == "bsc_rpc" else w.get("chain"), w.get("address"))
                for w in cfg.get("wallets") or [] if w.get("type", "evm") in ("evm", "bsc_rpc") and w.get("address")}
        pairs = {k: e for k, e in pairs.items() if k in act9}
    fb, fp, sk, done = {}, 0, 0, 0
    hold = prog = 0
    env9 = _env() if env is None else env
    for k, e in pairs.items():
        if not isinstance(e, dict):
            continue
        esd9 = e.get("es") if isinstance(e.get("es"), dict) else {}
        ch9 = str(k).split(":", 1)[0]
        inc9 = bool(e.get("at")) and any(_es_usable(ch9, s9, env9) and (
            (_es_cur(esd9.get(s9)) is None and (s9 in (e.get("ok") or {}) or str((e.get("fail") or {}).get(s9, "")).startswith("partial")))
            or (_es_cur(esd9.get(s9)) is not None and not esd9[s9].get("done") and str((e.get("fail") or {}).get(s9, "")).startswith("more")))
            for s9 in ES_LIKE)
        if e.get("at") and not inc9:
            done += 1
        prog += 1 if inc9 else 0
        hard = hard_fails(e)
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
    return {"pairs": len(pairs), "done": done, "failPairs": fp, "failBy": fb, "skip": sk, "hold": hold, "chains": chains, "noOld": sorted(noold),
            "progress": prog}
