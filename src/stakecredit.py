from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable
from typing import Any

import bf_engine
import calcguard
import logs
import paths
import statefile

log = logging.getLogger("tj-web")

FILE = "stake_credit.json"
STAKE_HUB = "0x0000000000000000000000000000000000002002"
SEL_VALIDATOR = "0x3a5381b5"
SEL_CREDIT_OF = "0xdbda7fb3"
SEL_BNB_BY_SHARES = "0x91faf0b4"
ONE = 10 ** 18
SRC = "derived:bnbstake"
RATE_EVERY = 3600
RATE_STALE = 24 * 3600
RATE_USE_MAX = 30 * 86400
NEG_TTL = 30 * 86400
FAIL_GAP = 900
RATE_MIN, RATE_MAX = 0.5, 10.0
PER_ROUND = 8
TIMEOUT = 10.0
MAX_ENTRIES = 2000

_LOCK = threading.Lock()
_FAIL: dict = {}


class NodeFail(Exception):
    pass


def _norm(ca: str) -> str:
    a = str(ca or "").strip().lower()
    return a if a.startswith("0x") and len(a) == 42 and all(c in "0123456789abcdef" for c in a[2:]) else ""


def load(read: Callable = None) -> dict:
    try:
        d = (read or statefile.read_json)(paths.state(FILE), {}) or {}
    except (Exception, SystemExit) as e:   # noqa: BLE001 [fallback]
        calcguard.swallowed("stakecredit:load", e)
        d = {}
    out = {}
    for k, v in ((d.get("e") or {}).items() if isinstance(d, dict) and isinstance(d.get("e"), dict) else ()):
        if _norm(k) and isinstance(v, dict) and isinstance(v.get("ok"), bool) and isinstance(v.get("at"), (int, float)):
            out[_norm(k)] = v
    return out


def _save(e: dict) -> None:
    if len(e) > MAX_ENTRIES:
        for key in sorted(e, key=lambda k: float(e[k].get("at") or 0))[:len(e) - MAX_ENTRIES]:
            e.pop(key, None)
    statefile.atomic_write_json(paths.state(FILE), {"v": 1, "e": e})


def rate_of(ent: dict, now: float):
    if not isinstance(ent, dict) or ent.get("ok") is not True:
        return None
    r, rt = ent.get("r"), ent.get("rt")
    if not isinstance(r, (int, float)) or not isinstance(rt, (int, float)) or not (RATE_MIN <= r <= RATE_MAX):
        return None
    return (float(r), float(rt)) if now - float(rt) <= RATE_USE_MAX else None


class Lookup:

    def __init__(self, spot, now: float = None):
        self.spot = spot
        self.now = time.time() if now is None else float(now)
        self.e = load()
        self.want: set = set()

    def px(self, pairs: Iterable) -> tuple | None:
        for ch, ca in pairs or ():
            a = _norm(ca) if ch == "bsc" else ""
            if not a:
                continue
            self.want.add(a)
            rr = rate_of(self.e.get(a), self.now)
            if rr is None:
                continue
            self.spot.want(["BNB"])
            bnb = self.spot.price("BNB")
            if not bnb:
                return None
            age = self.now - rr[1]
            if age <= RATE_STALE:
                ts = (getattr(self.spot, "usd_ts", None) or {}).get("BNB")
                age = (self.now - float(ts)) if ts else None
            return rr[0] * float(bnb), SRC, (max(0.0, age) if age is not None else None)
        return None


def _eth_call(rpcs: list, to: str, data: str, post: Callable) -> tuple:
    last = "노드 없음"
    for u in rpcs:
        body = {"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": to, "data": data}, "latest"]}
        try:
            d = post(u, body, timeout=TIMEOUT, ua="tj-bot/0.1")
        except Exception as e:   # noqa: BLE001 [isolate]
            calcguard.swallowed("stakecredit:eth_call", e)
            last = logs.safe_err(e)[:120]
            continue
        if not isinstance(d, dict):
            last = "응답 형식 이상"
            continue
        err = d.get("error")
        if isinstance(err, dict):
            msg = str(err.get("message") or "")
            if err.get("code") == 3 or "revert" in msg.lower():
                return "revert", msg[:80]
            last = f"RPC 오류 {err.get('code')}: {msg[:80]}"
            continue
        res = d.get("result")
        if isinstance(res, str) and res.startswith("0x"):
            return "ok", res[2:]
        last = "결과 없음"
    raise NodeFail(last)


def _word_addr(h: str) -> str:
    if len(h) < 64:
        return ""
    a = "0x" + h[24:64].lower()
    return "" if int(h[:64], 16) >> 160 or a == "0x" + "0" * 40 else a


def check(rpcs: list, ca: str, post: Callable) -> dict:
    kind, h = _eth_call(rpcs, ca, SEL_VALIDATOR, post)
    if kind == "ok" and 0 < len(h) < 64:
        raise NodeFail("validator() 답 길이 이상")
    op = _word_addr(h) if kind == "ok" else ""
    if not op:
        return {"ok": False, "why": "validator() 없음"}
    kind, h = _eth_call(rpcs, STAKE_HUB, SEL_CREDIT_OF + op[2:].rjust(64, "0"), post)
    if kind != "ok" or len(h) < 64:
        raise NodeFail("StakeHub 답 이상")
    if _word_addr(h) != ca:
        return {"ok": False, "why": "StakeHub 불일치"}
    return {"ok": True, "op": op}


def fetch_rate(rpcs: list, ca: str, post: Callable) -> float:
    kind, h = _eth_call(rpcs, ca, SEL_BNB_BY_SHARES + hex(ONE)[2:].rjust(64, "0"), post)
    if kind != "ok" or len(h) < 64:
        raise NodeFail("교환비 답 이상")
    r = int(h[:64], 16) / ONE
    if not (RATE_MIN <= r <= RATE_MAX):
        raise NodeFail(f"교환비 범위 밖 {r:.6g}")
    return r


def _due(e: dict, want: Iterable, now: float) -> list:
    out = []
    for a in sorted({_norm(x) for x in want or ()} - {""}):
        if now - float(_FAIL.get(a) or 0) < FAIL_GAP:
            continue
        v = e.get(a)
        if not v:
            out.append((0, a))
        elif v.get("ok") is True and now - float(v.get("rt") or 0) >= RATE_EVERY:
            out.append((1, a))
        elif v.get("ok") is False and now - float(v.get("at") or 0) >= NEG_TTL:
            out.append((2, a))
    out.sort()
    return [a for _p, a in out[:PER_ROUND]]


def refresh(rpcs: list, want: Iterable, now: float = None, post: Callable = None) -> int:
    now = time.time() if now is None else float(now)
    post = post or bf_engine.rpc_post
    rpcs = [str(u) for u in rpcs or () if u]
    with _LOCK:
        e = load()
        due = _due(e, want, now) if rpcs else []
        n = 0
        for a in due:
            v = dict(e.get(a) or {})
            try:
                if v.get("ok") is not True:
                    v = dict(check(rpcs, a, post), at=int(now))
                    e[a] = v
                    n += 1
                if v["ok"]:
                    e[a] = dict(v, r=fetch_rate(rpcs, a, post), rt=int(now))
                    n += 1
            except NodeFail:
                _FAIL[a] = now
                continue
            _FAIL.pop(a, None)
        if n:
            _save(e)
    return n


def worker_round(b: Any, rpcs_of: Callable, post: Callable = None) -> int:
    try:
        want = set(b.__dict__.get("_stake_want") or ())
        if not want or "bsc" in set(getattr(getattr(b, "spot", None), "off_chains", None) or ()):
            return 0
        n = refresh(rpcs_of(b.cfg, "bsc"), want, post=post)
    except (Exception, SystemExit) as e:   # noqa: BLE001 [isolate]
        calcguard.swallowed("stakecredit:worker_round", e)
        log.warning("스테이킹 증서 확인 실패(다음 주기): %s", logs.safe_err(e)[:160])
        return 0
    if n:
        log.info("BNB 스테이킹 증서 확인·교환비 %d건 갱신", n)
        b.soft_invalidate(kick=False)
    return n


def reset_for_tests() -> None:
    with _LOCK:
        _FAIL.clear()
