from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import uuid as uuidlib
from collections.abc import Callable

import calcguard
import envfile
import ex_sign
import exf_net
import logs
import net_http
import num_parse
import paths
import statefile

log = logging.getLogger("tj-exf")

FILE = "ex_wallet_status.json"
EXCHANGES = ("upbit", "bithumb", "binance", "bybit", "okx", "kucoin", "gate")
EVERY = 600
START_DELAY = 60
TICK = 30
CONFIRM_N = 2
REBLOCK_KEEP = 1800
MISS_KEEP = 86400
NET_MISS_N = 3
HOSTS = {"upbit": "api.upbit.com", "bithumb": "api.bithumb.com", "binance": "api.binance.com", "bybit": "api.bybit.com", "okx": "www.okx.com",
         "kucoin": "api.kucoin.com", "gate": "api.gateio.ws"}
MAINT_MIN, MAINT_FRAC, MAINT_END = 10, 0.25, 0.5
RL_MAX = 3600
MAX_BYTES = 16 * 1024 * 1024
TIMEOUT = 20
UA = "tj-bot/1.0 (self-hosted trade journal; read-only)"
_LOCK = threading.Lock()
_THREAD = {"t": None}
DENY_CODES = {"binance": {"-2014", "-2015"}, "bybit": {"10003", "10004", "10005", "10010"},
              "okx": {"50105", "50110", "50111", "50113", "50114"}}


class ExwError(Exception):

    def __init__(self, msg, status=0, ex="", code=None, retry_after=None):
        super().__init__(logs.redact_secret_text(msg))
        self.status = 403 if code is not None and str(code) in DENY_CODES.get(ex, ()) else status
        self.retry_after = retry_after


def http_get(url: str, headers: dict = None, auth: bool = False, send: Callable = None):
    h = {"User-Agent": UA, "Accept": "application/json", "Accept-Encoding": "gzip"}
    h.update(headers or {})
    req = net_http.request(url, headers=h, method="GET")
    opener = send or (net_http.auth_urlopen if auth else net_http.urlopen)
    try:
        with opener(req, timeout=TIMEOUT) as r:
            raw = net_http.read_capped(r, MAX_BYTES)
            if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
                raw = _gunzip(raw)
            return json.loads(raw.decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        try:
            body = e.read(512).decode("utf-8", "ignore")
        except Exception:   # noqa: BLE001 [fallback]
            body = ""
        ra = num_parse.to_float((e.headers or {}).get("Retry-After")) if e.headers is not None else None
        raise ExwError(f"HTTP {e.code}: {body[:160]}", e.code, retry_after=ra) from None
    except (urllib.error.URLError, OSError, ValueError, net_http.ResponseTooLarge) as e:
        raise ExwError(f"network: {type(e).__name__}: {str(e)[:120]}", 0) from None


def _gunzip(raw: bytes) -> bytes:
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as g:
        out = g.read(MAX_BYTES + 1)
    if len(out) > MAX_BYTES:
        raise ValueError("압축 해제 크기 초과")
    return out


def _signed(ex, env, path, send=None):
    if ex == "upbit":
        tok = ex_sign.jwt_hs256({"access_key": env["UPBIT_ACCESS"], "nonce": str(uuidlib.uuid4())}, env["UPBIT_SECRET"])
        return http_get("https://api.upbit.com" + path, {"Authorization": "Bearer " + tok}, True, send)
    if ex == "binance":
        qs = urllib.parse.urlencode({"timestamp": exf_net.sign_ms("binance"), "recvWindow": 10000})
        sig = ex_sign.binance_sign(env["TJ_BINANCE_SECRET"], qs)
        return http_get(f"https://api.binance.com{path}?{qs}&signature={sig}", {"X-MBX-APIKEY": env["TJ_BINANCE_KEY"]}, True, send)
    if ex == "bybit":
        t = str(exf_net.sign_ms("bybit"))
        sig = ex_sign.bybit_sign(env["TJ_BYBIT_SECRET"], t, env["TJ_BYBIT_KEY"], "10000", "")
        return http_get("https://api.bybit.com" + path, {"X-BAPI-API-KEY": env["TJ_BYBIT_KEY"], "X-BAPI-TIMESTAMP": t,
                                                     "X-BAPI-RECV-WINDOW": "10000", "X-BAPI-SIGN": sig}, True, send)
    t = exf_net.iso_ms(exf_net.sign_ms("okx"))
    sig = ex_sign.okx_sign(env["TJ_OKX_SECRET"], t, "GET", path)
    return http_get("https://www.okx.com" + path, {"OK-ACCESS-KEY": env["TJ_OKX_KEY"], "OK-ACCESS-SIGN": sig, "OK-ACCESS-TIMESTAMP": t,
                                               "OK-ACCESS-PASSPHRASE": env["TJ_OKX_PASSPHRASE"]}, True, send)


def fetch(ex: str, env: dict, send: Callable = None):
    if ex == "upbit":
        d = _signed(ex, env, "/v1/status/wallet", send)
        if isinstance(d, dict) and d.get("error"):
            raise ExwError(f"upbit {str((d['error'] or {}).get('name') if isinstance(d['error'], dict) else d['error'])[:80]}", 200)
        return d
    if ex == "binance":
        d = _signed(ex, env, "/sapi/v1/capital/config/getall", send)
        if isinstance(d, dict) and isinstance(d.get("code"), int) and d["code"] < 0:
            raise ExwError(f"binance {d['code']} {str(d.get('msg'))[:80]}", 200, ex, d["code"])
        return d
    if ex in ("bybit", "okx"):
        d = _signed(ex, env, "/v5/asset/coin/query-info" if ex == "bybit" else "/api/v5/asset/currencies", send)
        ok = isinstance(d, dict) and (d.get("retCode") == 0 if ex == "bybit" else str(d.get("code")) == "0")
        if not ok:
            code = (d.get("retCode") if ex == "bybit" else d.get("code")) if isinstance(d, dict) else "?"
            raise ExwError(f"{ex} {code} {str((d or {}).get('retMsg' if ex == 'bybit' else 'msg') if isinstance(d, dict) else d)[:80]}", 200, ex, code)
        return d
    url = {"bithumb": "https://api.bithumb.com/public/assetsstatus/multichain/ALL", "kucoin": "https://api.kucoin.com/api/v3/currencies",
           "gate": "https://api.gateio.ws/api/v4/spot/currencies"}[ex]
    d = http_get(url, None, False, send)
    if ex == "bithumb" and not (isinstance(d, dict) and str(d.get("status")) == "0000"):
        raise ExwError(f"bithumb {str((d or {}).get('status') if isinstance(d, dict) else d)[:40]}", 200)
    if ex == "kucoin" and not (isinstance(d, dict) and str(d.get("code")) == "200000"):
        raise ExwError(f"kucoin {str((d or {}).get('code') if isinstance(d, dict) else d)[:40]}", 200)
    return d


def _b(v):
    if isinstance(v, bool):
        return v
    return {"1": True, "0": False}.get(str(v)) if isinstance(v, (int, str)) else None


def _put(out, sym, net, dep, wd, meta=None):
    s, n = str(sym or "").strip().upper(), str(net or "")
    if not s or len(s) > 30 or dep is None or wd is None:
        return
    cur = out.setdefault(s, {}).get(n) or [False, False]
    out[s][n] = [bool(dep) or cur[0], bool(wd) or cur[1]]
    mt = {k: v for k, v in (meta or {}).items() if v}
    if mt:
        out[s][n].append(mt)


def _bool(v):
    return v if isinstance(v, bool) else None


def _neg(v):
    return (not v) if isinstance(v, bool) else None


def _est(v) -> int:
    x = num_parse.to_int(v, 0) or 0
    return x // 1000 if x > 10 ** 11 else 0


def _rows(d, key):
    v = d.get(key) if isinstance(d, dict) else d
    return [r for r in (v if isinstance(v, list) else []) if isinstance(r, dict)]


def parse(ex: str, d: object) -> dict:
    out = {}
    if ex == "upbit":
        for r in _rows(d, None):
            ws = str(r.get("wallet_state") or "")
            if ws in ("working", "deposit_only", "withdraw_only", "paused"):
                bs = str(r.get("block_state") or "")
                _put(out, r.get("currency"), r.get("net_type") or r.get("currency"), ws in ("working", "deposit_only"), ws in ("working", "withdraw_only"),
                     {"bs": bs if bs not in ("", "normal") else ""})
    elif ex == "bithumb":
        for r in _rows(d, "data"):
            _put(out, r.get("currency"), r.get("net_type") or r.get("currency"), _b(r.get("deposit_status")), _b(r.get("withdrawal_status")))
    elif ex == "binance":
        for c in _rows(d, None):
            if c.get("isLegalMoney"):
                continue
            nets = _rows(c.get("networkList"), None)
            for n in nets:
                _put(out, c.get("coin"), n.get("network"), _bool(n.get("depositEnable")), _bool(n.get("withdrawEnable")))
            if not nets:
                _put(out, c.get("coin"), "", _bool(c.get("depositAllEnable")), _bool(c.get("withdrawAllEnable")))
    elif ex == "bybit":
        for c in _rows((d or {}).get("result") if isinstance(d, dict) else None, "rows"):
            for n in _rows(c.get("chains"), None):
                _put(out, c.get("coin"), n.get("chain"), _b(n.get("chainDeposit")), _b(n.get("chainWithdraw")))
    elif ex == "okx":
        for r in _rows(d, "data"):
            _put(out, r.get("ccy"), r.get("chain"), _bool(r.get("canDep")), _bool(r.get("canWd")),
                 {"eo_d": _est(r.get("depEstOpenTime")), "eo_w": _est(r.get("wdEstOpenTime"))})
    elif ex == "kucoin":
        for c in _rows(d, "data"):
            for n in _rows(c.get("chains"), None):
                _put(out, c.get("currency"), n.get("chainName") or n.get("chainId"), _bool(n.get("isDepositEnabled")), _bool(n.get("isWithdrawEnabled")))
    elif ex == "gate":
        _parse_gate(out, d)
    return out


def _parse_gate(out, d):
    for c in _rows(d, None):
        if c.get("delisted"):
            continue
        nets = _rows(c.get("chains"), None)
        for n in nets:
            _put(out, c.get("currency"), n.get("name"), _neg(n.get("deposit_disabled")), _neg(n.get("withdraw_disabled")))
        if not nets:
            _put(out, c.get("currency"), c.get("chain") or "", _neg(c.get("deposit_disabled")), _neg(c.get("withdraw_disabled")))


def kind_of(nets: dict, i: int):
    closed = sorted(n for n, v in nets.items() if _bits(v)[i] == "0")
    if not nets or not closed:
        return None, []
    return ("full" if len(closed) == len(nets) else "part"), closed


def _bits(v) -> str:
    b = v[0] if isinstance(v, list) and v else v
    return b if isinstance(b, str) and len(b) == 2 else "11"


def _open_known(nets: dict, i: int) -> bool:
    return any(_bits(v)[i] == "1" for v in nets.values())


def _nets_now(old: dict, cur, now):
    out = {}
    for n, v in (old or {}).items():
        if cur is not None and n in cur:
            continue
        t0 = v[1] if isinstance(v, list) and len(v) > 1 else now
        k = (int(v[2]) if isinstance(v, list) and len(v) > 2 and isinstance(v[2], int) else 0) + (cur is not None)
        if (cur is None and now - float(t0) < MISS_KEEP) or (cur is not None and k < NET_MISS_N):
            out[n] = [_bits(v), int(t0), k]
    for n, v in (cur or {}).items():
        out[n] = ("1" if v[0] else "0") + ("1" if v[1] else "0")
    return out


def step_dir(r: dict, kind: str, now: float, first: bool) -> dict:
    r = dict(r or {})
    st = r.get("st") if r.get("st") != "unk" else None
    if kind == "full":
        if st == "on" or (st == "off" and now - float(r.get("end") or 0) < REBLOCK_KEEP):
            r.update(st="on", n=CONFIRM_N)
            r.pop("end", None)
        elif st == "cand":
            r["n"] = int(r.get("n") or 1) + 1
            r["st"] = "on" if r["n"] >= CONFIRM_N else "cand"
        else:
            r = {"st": "cand", "n": 1, "s": int(now)} | ({"pre": 1} if first else {})
        return r
    if st == "on" and not r.get("pre"):
        r.update(st="off", end=int(now))
    elif st == "off" and now - float(r.get("end") or 0) < REBLOCK_KEEP:
        pass
    else:
        r = {}
    return r


def _coin_step(old_c: dict, nets: dict, b0: dict, now: float, seen: str) -> dict:
    out = {}
    for i, dk in enumerate(("d", "w")):
        kind, closed = kind_of(nets, i)
        if kind != "full" and not _open_known(nets, i):
            r = dict((old_c or {}).get(dk) or {})
        else:
            r = step_dir((old_c or {}).get(dk), kind, now, dk not in seen)
        nb = sorted(set(closed) - set(b0.get(dk) or [])) if kind == "part" else []
        pn = int(((old_c or {}).get(dk) or {}).get("pn") or 0) + 1 if nb else 0
        r = {k: v for k, v in r.items() if k not in ("bn", "nb", "pn", "eo", "bs")}
        if r or pn:
            r["bn"] = closed
            if pn:
                r.update(nb=nb, pn=pn)
            ms = [v[2] for n, v in nets.items() if n in closed and isinstance(v, list) and len(v) > 2 and isinstance(v[2], dict)]
            eo = max([int(m.get("eo_" + dk) or 0) for m in ms] or [0])
            bs = next((str(m["bs"])[:20] for m in ms if m.get("bs")), "")
            r |= ({"eo": eo} if eo else {}) | ({"bs": bs} if bs else {})
            out[dk] = r
    return out


def _maint(prev: dict, coins: dict, new_pairs: set, now: float):
    m = prev.get("maint") if isinstance(prev.get("maint"), dict) else None
    live = {f"{sym}|{dk}" for sym, c in coins.items() for dk, r in c.items() if r.get("st") in ("cand", "on")}
    if m:
        st = {x for x in (m.get("set") or []) if isinstance(x, str)}
        return (m, set()) if st and len(st & live) >= MAINT_END * len(st) else (None, st & live)
    pc = prev.get("c") or {}
    prev_full = sum(1 for c in pc.values() if isinstance(c, dict) for r in c.values() if isinstance(r, dict) and r.get("st") in ("cand", "on"))
    open_prev = max(0, 2 * len(prev.get("nets") or {}) - prev_full)
    if prev.get("cy") and len(new_pairs) >= max(MAINT_MIN, MAINT_FRAC * open_prev):
        return {"since": int(now), "set": sorted(new_pairs)[:5000]}, set()
    return None, set()


def update(prev: dict, parsed: dict, now: float) -> dict:
    prev = prev if isinstance(prev, dict) else {}
    pnets, pc, pb0, pso = prev.get("nets") or {}, prev.get("c") or {}, prev.get("b0") or {}, prev.get("so") or {}
    nets_all, coins, b0s, new_pairs, so = {}, {}, {}, set(), dict(pso)
    for sym in set(parsed) | set(pnets) | set(pc):
        nets = _nets_now(pnets.get(sym), parsed.get(sym), now)
        first = sym not in pnets and sym not in pc
        if nets:
            nets_all[sym] = nets
        if not nets:
            if any(isinstance(r, dict) and r.get("st") for r in (pc.get(sym) or {}).values()):
                coins[sym] = {dk: {"st": "unk", "s": r.get("s")} | ({"pre": 1} if r.get("pre") else {})
                              for dk, r in pc[sym].items() if isinstance(r, dict) and r.get("st")}
            continue
        b0 = pb0.get(sym) or ({dk: kind_of(nets, i)[1] for i, dk in enumerate(("d", "w"))} if first else {})
        b0 = {dk: [n for n in (b0.get(dk) or []) if n in kind_of(nets, i)[1]] for i, dk in enumerate(("d", "w"))}
        if any(b0.values()):
            b0s[sym] = b0
        seen = so.get(sym, "")
        c = _coin_step(pc.get(sym), _with_meta(nets, parsed.get(sym)), b0, now, seen)
        seen = "".join(dk for i, dk in enumerate(("d", "w")) if dk in seen or _open_known(nets, i))
        if seen:
            so[sym] = seen
        new_pairs |= {f"{sym}|{dk}" for dk, r in c.items() if r.get("st") == "cand" and r.get("n") == 1 and not r.get("pre")}
        if c:
            coins[sym] = c
    out = {k: prev[k] for k in ("kf", "gen", "err_at") if k in prev}
    out.update({"at": int(now), "try": int(now), "err": "", "fail": 0, "next": int(now + EVERY), "n": len(parsed),
                "cy": int(prev.get("cy") or 0) + 1, "c": coins, "nets": nets_all, "b0": b0s, "so": so})
    out.setdefault("gen", int(now))
    m, ended = _maint(prev, coins, new_pairs, now)
    if m:
        out["maint"] = m
    for pair in ended:
        sym, dk = pair.split("|", 1)
        coins[sym][dk]["mt"] = 1
    return out


def _with_meta(nets: dict, cur) -> dict:
    out = dict(nets)
    for n, v in (cur or {}).items():
        if len(v) > 2 and isinstance(v[2], dict):
            out[n] = [out[n] if isinstance(out[n], str) else _bits(out[n]), 0, v[2]]
    return out


def failed(prev: dict, err: ExwError, now: float) -> dict:
    out = dict(prev if isinstance(prev, dict) else {})
    n = int(out.get("fail") or 0) + 1
    st = getattr(err, "status", 0)
    ra = _ra(err)
    wait = exf_net.DENY_COOL_SEC if st in (401, 403) else max(ra, min(RL_MAX, EVERY * (2 ** min(n, 4)))) if st in (418, 429) else EVERY
    out.update({"try": int(now), "err": str(err)[:160], "fail": n, "next": int(now + wait), "err_at": int(now),
                "f0": int(out.get("f0") or now) if int(out.get("fail") or 0) else int(now)})
    return out


def _ra(err) -> float:
    st = getattr(err, "status", 0)
    if st not in (418, 429):
        return 0.0
    ra = num_parse.to_float(getattr(err, "retry_after", None), 0.0) or 0.0
    return min(ra if ra > 0 else (120.0 if st == 418 else 60.0), 3 * 86400.0)


def load(path: str = None) -> dict:
    try:
        d = statefile.read_json(path or paths.state(FILE), {}) or {}
    except (Exception, SystemExit) as e:   # noqa: BLE001 [fallback]
        calcguard.swallowed("exwallet:load", e, expected=True)
        d = {}
    return d if isinstance(d, dict) and isinstance(d.get("ex"), dict) else {"v": 1, "ex": {}}


def _kfp(ex, env) -> str:
    return hashlib.sha256(str(env.get(envfile.EX_KEYS[ex][0]) or "").encode()).hexdigest()[:12]


def _one(ex, prev, env, now, send):
    try:
        parsed = parse(ex, fetch(ex, env, send))
        if len(parsed) < max(1, 0.5 * int(prev.get("n") or 0)):
            raise ExwError(f"{ex} 응답 코인 {len(parsed)}개 — 비었거나 지난번의 절반도 안 됨(이번 주기 버림)", 200)
        return update(prev, parsed, now), "ok", None
    except ExwError as e:
        return failed(prev, e, now), str(e)[:120], e
    except Exception as e:   # noqa: BLE001 [isolate]
        calcguard.swallowed("exwallet:exchange", e, expected=True)
        err = ExwError(f"{type(e).__name__}: {str(e)[:100]}")
        return failed(prev, err, now), str(err)[:120], err


def round_once(env: dict, now: float = None, path: str = None, send: Callable = None, rl: dict = None) -> dict:
    now = time.time() if now is None else now
    rl = {} if rl is None else rl
    res, changed = {}, False
    with _LOCK:
        doc = load(path)
        exs = doc["ex"]
        for ex in EXCHANGES:
            if not envfile.exchange_accounts(env or {}, ex, envfile.EX_KEYS[ex]):
                changed = exs.pop(ex, None) is not None or changed
                continue
            prev = exs.get(ex) if isinstance(exs.get(ex), dict) else {}
            kf = _kfp(ex, env)
            if prev.get("kf") and prev.get("kf") != kf:
                prev = {}
            if (prev.get("kf") == kf and now < float(prev.get("next") or 0)) or now < num_parse.to_float(rl.get(HOSTS[ex]), 0.0):
                continue
            new, res[ex], err = _one(ex, prev, env, now, send)
            if err is not None and _ra(err):
                rl[HOSTS[ex]] = max(num_parse.to_float(rl.get(HOSTS[ex]), 0.0), now + _ra(err))
            new["kf"] = kf
            exs[ex] = new
        if res or changed:
            doc["v"], doc["ts"] = 1, int(now)
            statefile.atomic_write_json(path or paths.state(FILE), doc)
    return res


def start_background(env_fn: Callable, rl_map: dict = None):
    if _THREAD["t"] and _THREAD["t"].is_alive():
        return _THREAD["t"]
    if not any(t.name == "tj-depaddr" and t.is_alive() for t in threading.enumerate()):
        log.info("입출금 상태 스레드 안 띄움 — 입금주소 스레드(tj-depaddr)가 없는 실행(시험·부분 기동)")
        return None

    def loop():
        time.sleep(START_DELAY)
        while True:
            try:
                got = round_once(env_fn() or {}, rl=rl_map)
                bad = {k: v for k, v in got.items() if v != "ok"}
                if bad:
                    log.info("입출금 상태 읽기 실패(다음 주기 다시): %s", logs.redact_secret_text(json.dumps(bad, ensure_ascii=False))[:300])
            except Exception as e:   # noqa: BLE001 [boundary]
                calcguard.swallowed("exwallet:round", e)
                log.warning("입출금 상태 스레드 예외(계속): %s", logs.redact_secret_text(repr(e))[:160])
            time.sleep(TICK)
    t = threading.Thread(target=loop, name="tj-exwallet", daemon=True)
    t.start()
    _THREAD["t"] = t
    return t
