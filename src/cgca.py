from __future__ import annotations

import os
import threading
import time
import urllib.parse

import common

FILE = "cg_ca.json"
TTL_POS = 7 * 86400
TTL_NEG = 3 * 86400
PX_FRESH = 6 * 3600
PX_EVERY = 3600
PER_TICK = 3
GAP = 8.0
LOOP_SEC = 60
ERR_BACKOFF = 600
KEY_WAIT = 1800
KEY_DAY_MAX = 100
MAX_ENTRIES = 20000

_LOCK = threading.Lock()
_ST = {"e": None, "want": {}, "px_want": set(), "dirty": False, "backoff": 0.0, "err": None, "calls": 0, "kd": None,
       "kwait": {"past": 0.0, "live": 0.0}}


class _KeyLater(Exception):
    pass


def _path() -> str:
    return os.path.join(common.STATE_DIR, FILE)


def key_of(chain, ca) -> str:
    c = str(chain or "")
    a = str(ca or "")
    return f"{c}:{a if c == 'sol' else a.lower()}"


def _entries() -> dict:
    if _ST["e"] is None:
        e9 = {}
        try:
            d = common.read_json(_path(), {}) or {}
        except (Exception, SystemExit):
            d = {}
        for k, v in ((d.get("e") or {}).items() if isinstance(d, dict) else ()):
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], (int, float)) and (v[1] is None or isinstance(v[1], (int, float))):
                e9[str(k)] = [float(v[0]), None if v[1] is None else float(v[1])]
        _ST["e"] = e9
        kd9 = d.get("kd") if isinstance(d, dict) else None
        if _ST.get("kd") is None and isinstance(kd9, list) and len(kd9) == 2 and all(isinstance(x, int) for x in kd9):
            _ST["kd"] = kd9
    return _ST["e"]


def status(chain, ca):
    with _LOCK:
        v = _entries().get(key_of(chain, ca))
    if not v:
        return None
    return v[1] is not None and v[1] > 0


def price(chain, ca, now=None):
    now = time.time() if now is None else now
    with _LOCK:
        v = _entries().get(key_of(chain, ca))
    if v and v[1] and now - v[0] <= PX_FRESH:
        return float(v[1])
    return None


def want(pairs_usd: dict, px_pairs=()):
    try:
        import candles
        plat = candles.CG_PLATFORM
    except Exception:
        plat = {}
    w9 = {}
    for p, usd in (pairs_usd or {}).items():
        if isinstance(p, tuple) and len(p) == 2 and p[0] in plat and p[1]:
            w9[(str(p[0]), str(p[1]))] = float(usd or 0)
    with _LOCK:
        _ST["want"] = w9
        _ST["px_want"] = {(str(c), str(a)) for c, a in (px_pairs or ()) if c in plat and a}


def _due(now: float) -> list:
    with _LOCK:
        e9 = _entries()
        w9 = dict(_ST["want"])
        pw9 = set(_ST["px_want"])
    out = []
    for p, usd in w9.items():
        v = e9.get(key_of(*p))
        if v and p in pw9 and now - v[0] >= PX_EVERY:
            out.append((0, v[0], p))
        elif not v:
            out.append((1, -usd, p))
        elif now - v[0] >= (TTL_POS if v[1] else TTL_NEG):
            out.append((2, v[0], p))
    out.sort()
    return [p for _r, _o, p in out]


def _key_day(now: float, take: bool = False) -> int:
    day = int(now // 86400)
    with _LOCK:
        kd = _ST.get("kd")
        if not (isinstance(kd, list) and len(kd) == 2 and kd[0] == day):
            kd = [day, 0]
        if take:
            kd = [day, int(kd[1]) + 1]
            _ST["dirty"] = True
        _ST["kd"] = kd
        return int(kd[1])


def _fetch(chain: str, ca: str, lane: str = "past"):
    import bf_engine
    import candles
    plat = candles.CG_PLATFORM.get(chain)
    tk = ca if chain == "sol" else ca.lower()
    url = (f"https://api.coingecko.com/api/v3/simple/token_price/{plat}?contract_addresses={urllib.parse.quote(tk, safe='')}"
           "&vs_currencies=usd")
    dl = time.time() + 30

    def ok(d9):
        return not candles._cg_error_body(d9)
    has_key = False
    try:
        import cgkey
        has_key = bool(cgkey.key())
    except Exception:
        has_key = False
    if has_key and _key_day(time.time()) >= KEY_DAY_MAX:
        raise _KeyLater("하루 상한")
    kind, v = candles._keyed(url, lane, has_key, ok, dl)
    if kind in ("ok", "err", "fail"):
        _key_day(time.time(), take=True)
    if kind == "ok":
        d = v
    elif kind == "err":
        raise v
    elif kind == "skip" and has_key:
        raise _KeyLater(str(v))
    else:
        d = candles._get(url, deadline=dl, inline_wait=10.0)
    if not isinstance(d, dict) or candles._cg_error_body(d):
        raise bf_engine.NetError(f"코인게코 응답 형식 이상: {str(d)[:80]}", "bad", host="api.coingecko.com")
    for k9, v9 in d.items():
        if str(k9).lower() == tk.lower() and isinstance(v9, dict):
            u9 = candles._f(v9.get("usd"))
            return u9 if u9 and u9 > 0 else None
    return None


def tick(now=None, budget_sec: float = 30.0) -> int:
    now = time.time() if now is None else now
    if now < _ST["backoff"]:
        return 0
    due = _due(now)
    n = 0
    t_end = time.time() + budget_sec
    called = 0
    for c, a in due:
        with _LOCK:
            lane9 = "live" if (c, a) in _ST["px_want"] and key_of(c, a) in _entries() else "past"
        if time.time() < float(_ST["kwait"].get(lane9) or 0):
            continue
        if called and (time.time() + GAP > t_end):
            break
        if called:
            time.sleep(GAP)
        called += 1
        try:
            usd = _fetch(c, a, lane9)
        except _KeyLater as e:
            _ST["kwait"][lane9] = time.time() + KEY_WAIT
            _ST["err"] = f"키 몫 대기({lane9}): " + str(e)[:80]
            continue
        except Exception as e:
            _ST["backoff"] = time.time() + ERR_BACKOFF
            _ST["err"] = common.safe_err(e)[:160]
            break
        with _LOCK:
            e9 = _entries()
            e9[key_of(c, a)] = [float(int(time.time())), usd]
            if len(e9) > MAX_ENTRIES:
                for k9 in sorted(e9, key=lambda k: e9[k][0])[:len(e9) - MAX_ENTRIES]:
                    e9.pop(k9, None)
            _ST["dirty"] = True
            _ST["calls"] += 1
        n += 1
        if called >= PER_TICK:
            break
    if _ST["dirty"]:
        save()
    return n


def loop():
    import logging
    lg = logging.getLogger("tj-web")
    time.sleep(90)
    while True:
        try:
            n9 = tick()
            if n9:
                lg.info("코인게코 컨트랙트 시세 확인 %d개(창 이전 기초잔고 토큰 평가 관문)", n9)
        except Exception as e:
            lg.warning("코인게코 컨트랙트 시세 확인 실패(다음 바퀴): %s", common.safe_err(e)[:120])
        time.sleep(LOOP_SEC)


def save():
    with _LOCK:
        if not _ST["dirty"] or _ST["e"] is None:
            return
        doc = {"v": 1, "e": {k: v for k, v in _ST["e"].items()}, "kd": _ST.get("kd")}
        _ST["dirty"] = False
    try:
        common.atomic_write_json(_path(), doc)
    except OSError:
        with _LOCK:
            _ST["dirty"] = True


def reset_for_tests():
    with _LOCK:
        _ST.update(e=None, want={}, px_want=set(), dirty=False, backoff=0.0, err=None, calls=0, kd=None, kwait={"past": 0.0, "live": 0.0})
